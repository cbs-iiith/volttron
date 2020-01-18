# -*- coding: utf-8 -*- {{{
# vim: set fenc=utf-8 ft=python sw=4 ts=4 sts=4 et:
#
# Copyright (c) 2020, Sam Babu, Godithi.
# All rights reserved.
#
#
# IIIT Hyderabad

#}}}

#Sam

import datetime
import logging
import sys
import uuid

from volttron.platform.vip.agent import Agent, Core, PubSub, compat, RPC
from volttron.platform.agent import utils
from volttron.platform.messaging import topics, headers as headers_mod
from volttron.platform.agent.known_identities import (
    MASTER_WEB, VOLTTRON_CENTRAL, VOLTTRON_CENTRAL_PLATFORM)
from volttron.platform import jsonrpc
from volttron.platform.jsonrpc import (
        INVALID_REQUEST, METHOD_NOT_FOUND,
        UNHANDLED_EXCEPTION, UNAUTHORIZED,
        UNABLE_TO_REGISTER_INSTANCE, DISCOVERY_ERROR,
        UNABLE_TO_UNREGISTER_INSTANCE, UNAVAILABLE_PLATFORM, INVALID_PARAMS,
        UNAVAILABLE_AGENT)

from random import randint

import settings
import time
import struct
import gevent
import gevent.event

from ispace_utils import publish_to_bus, get_task_schdl, cancel_task_schdl, isclose

utils.setup_logging()
_log = logging.getLogger(__name__)
__version__ = '0.3'

#checking if a floating point value is “numerically zero” by checking if it is lower than epsilon
EPSILON = 1e-03

SCHEDULE_AVLB = 1
SCHEDULE_NOT_AVLB = 0

E_UNKNOWN_CCE = -4
E_UNKNOWN_TSP = -5
E_UNKNOWN_BPP = -7

class BuildingController(Agent):
    '''Building Controller
    '''
    _pp_failed = False
    
    _price_point_current = 0.4 
    _price_point_new = 0.45
    _pp_id = randint(0, 99999999)

    _rmTsp = 25
    
    #downstream energy demand and deviceId
    _ds_ed = []
    _ds_deviceId = []
    
    #building total energy demand (including downstream)
    _ted = 0

    def __init__(self, config_path, **kwargs):
        super(BuildingController, self).__init__(**kwargs)
        _log.debug("vip_identity: " + self.core.identity)

        self.config = utils.load_config(config_path)
        self._configGetPoints()
        self._configGetInitValues()
        return

    @Core.receiver('onsetup')
    def setup(self, sender, **kwargs):
        _log.info(self.config['message'])
        self._agent_id = self.config['agentid']
        return

    @Core.receiver('onstart')
    def startup(self, sender, **kwargs):
        _log.info("yeild 30s for volttron platform to initiate properly...")
        time.sleep(30) #yeild for a movement
        _log.info("Starting BuildingController...")
        
        self._runBMSTest()
        
        #TODO: get the latest values (states/levels) from h/w
        #self.getInitialHwState()
        #time.sleep(1) #yeild for a movement
        
        #TODO: apply pricing policy for default values
        
        #TODO: publish initial data to volttron bus
        
        #perodically publish total energy demand to volttron bus
        self.core.periodic(self._period_read_data, self.publishTed, wait=None)
        
        #perodically process new pricing point that keeps trying to apply the new pp till success
        self.core.periodic(self._period_process_pp, self.processNewPricePoint, wait=None)
        
        #subscribing to topic_price_point
        self.vip.pubsub.subscribe("pubsub", self.topic_price_point, self.onNewPrice)
        
        #subscribing to ds energy demand, vb publishes ed from registered ds to this topic
        self.vip.pubsub.subscribe("pubsub", self.energyDemand_topic_ds, self.onDsEd)
        
        self.vip.rpc.call(MASTER_WEB, 'register_agent_route',
                      r'^/BuildingController',
                      "rpc_from_net").get(timeout=10)
        return

    @Core.receiver('onstop')
    def onstop(self, sender, **kwargs):
        _log.debug('onstop()')

        _log.debug('un registering rpc routes')
        self.vip.rpc.call(MASTER_WEB, 'unregister_all_agent_routes').get(timeout=10)
        return

    @Core.receiver('onfinish')
    def onfinish(self, sender, **kwargs):
        _log.debug('onfinish()')
        return

    def _configGetInitValues(self):
        self._period_read_data = self.config('period_read_data', 30)
        self._period_process_pp = self.config.get('period_process_pp', 10)
        self._price_point_current = self.config.get('default_base_price', 0.2)
        self._price_point_new = self.config.get('price_point_latest', 0.3)
        return
        
    def _configGetPoints(self):
        self.root_topic              = self.config.get('topic_root', 'building')
        self.energyDemand_topic     = self.config.get('topic_energy_demand', \
                                            'building/energydemand')
        self.topic_price_point      = self.config.get('topic_price_point', \
                                            'building/pricepoint')
        self.energyDemand_topic_ds  = self.config.get('topic_energy_demand_ds', \
                                            'ds/energydemand')
        return


    def _runBMSTest(self):
        _log.debug("Running : _runBMS Commu Test()...")
        _log.debug('change pp .10')
        self.publishPriceToBMS(0.10)
        time.sleep(10)

        _log.debug('change pp .75')
        self.publishPriceToBMS(0.75)
        time.sleep(10)

        _log.debug('change pp .25')
        self.publishPriceToBMS(0.25)
        time.sleep(10)

        _log.debug("EOF Testing")
        return
        
    def onNewPrice(self, peer, sender, bus,  topic, headers, message):
        if sender == 'pubsub.compat':
            message = compat.unpack_legacy_message(headers, message)
            
        new_price_point = message[0]
        new_pp_id           = message[2] if message[2] is not None else randint(0, 99999999)
        new_pp_isoptimal    = message[3] if message[3] is not None else False
        _log.info ( "*** New Price Point: {0:.2f} ***".format(new_price_point))
        _log.debug("*** new_pp_id: " + str(new_pp_id))
        _log.debug("*** new_pp_isoptimal: " + str(new_pp_isoptimal))
        
        if not new_pp_isoptimal:
            _log.debug('not optimal pp!!!, do nothing')
            return
            
        if isclose(self._price_point_current, new_price_point, EPSILON) and self._pp_id == new_pp_id:
            _log.debug('no change in price, do nothing')
            return
            
        self._price_point_new = new_price_point
        self._pp_id_new = new_pp_id
        self.processNewPricePoint()
        return
        
    #this is a perodic function that keeps trying to apply the new pp till success
    def processNewPricePoint(self):
        if isclose(self._price_point_current, self._price_point_new, EPSILON) and self._pp_id == self._pp_id_new:
            return
            
        self._pp_failed = False     #any process that failed to apply pp sets this flag True
        self.publishPriceToBMS(self._price_point_new)
        if not self._pp_failed:
            self.applyPricingPolicy()
        
        if self._pp_failed:
            _log.error("unable to processNewPricePoint(), will try again in " + self._period_process_pp)
            return
            
        _log.info("*** New Price Point processed.")
        self._price_point_current = self._price_point_new
        self._pp_id = self._pp_id_new
        return

    def applyPricingPolicy(self):
        _log.debug("applyPricingPolicy()")
        #TODO: control the energy demand of devices at building level accordingly
        #if applying self._price_point_new failed, set self._pp_failed = True
        return
        
    # change rc surface temperature set point
    def publishPriceToBMS(self, pp):
        _log.debug('publishPriceToBMS()')
        task_id = str(randint(0, 99999999))
        result = get_task_schdl(self, task_id,'iiit/cbs/buildingcontroller')
        if result['result'] == 'SUCCESS':
            try:
                result = self.vip.rpc.call(
                    'platform.actuator', 
                    'set_point',
                    self._agent_id, 
                    'iiit/cbs/buildingcontroller/Building_PricePoint',
                    pp).get(timeout=10)
                self.updateBuildingPP()
            except gevent.Timeout:
                _log.exception("Expection: gevent.Timeout in publishPriceToBMS()")
            except Exception as e:
                _log.exception ("Expection: changing device level")
                print(e)
            finally:
                #cancel the schedule
                cancel_task_schdl(self, task_id)
        else:
            _log.debug('schedule NOT available')
        return

    def updateBuildingPP(self):
        #_log.debug('updateRmTsp()')
        _log.debug('building_pp {0:0.2f}'.format( self._price_point_new))
        
        building_pp = self.rpc_getBuildingPP()
        
        #check if the pp really updated at the bms, only then proceed with new pp
        if isclose(self._price_point_new, building_pp, EPSILON):
            self.publishBuildingPP()
        else:
            self._pp_failed = True
            
        _log.debug('Current Building PP: ' + "{0:0.2f}".format( pp))
        return

    def publishBuildingPP(self):
        #_log.debug('publishBuildingPP()')
        pubTopic = self.root_topic+"/Building_PricePoint"
        pubMsg = [self._price_point_new, {'units': 'cents', 'tz': 'UTC', 'type': 'float'}, self._pp_id_new]
        publish_to_bus(self, pubTopic, pubMsg)
        return

    def rpc_getBuildingPP(self):
        try:
            pp = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/buildingcontroller/Building_PricePoint').get(timeout=10)
            return pp
        except gevent.Timeout:
            _log.exception("Expection: gevent.Timeout in rpc_getBuildingPP()")
            return E_UNKNOWN_BPP
        except Exception as e:
            _log.exception ("Expection: Could not contact actuator. Is it running?")
            print(e)
            return E_UNKNOWN_BPP
        return E_UNKNOWN_BPP

    def rpc_getBuildingLevelEnergy(self):
        #compute the energy of the other devices which are at building level
        return 0
        
    def _calculateTed(self):
        #_log.debug('_calculateTed()')
        
        ted = self.rpc_getBuildingLevelEnergy()
        for ed in self._ds_ed:
            ted = ted + ed
        
        return ted

    def publishTed(self):
        ted = self._calculateTed()
        self._ted = ted
        _log.info( "*** New TED: {0:.2f}, publishing to bus ***".format(ted))
        pubTopic = self.energyDemand_topic
        _log.debug("TED pubTopic: " + pubTopic)
        pubMsg = [ted, {'units': 'W', 'tz': 'UTC', 'type': 'float'}, self._pp_id]
        publish_to_bus(self, pubTopic, pubMsg)
        return
        
    def onDsEd(self, peer, sender, bus,  topic, headers, message):
        if sender == 'pubsub.compat':
            message = compat.unpack_legacy_message(headers, message)
        _log.debug('*********** New ed from ds, topic: ' + topic + \
                    ' & ed: {0:.4f}'.format(message[0]))
                    
        ed_pp_id = message[2]
        if self._pp_id != ed_pp_id
            _log.debug("self._pp_id: " + str(self._pp_id) + " ed_pp_id: " + str(ed_pp_id) + " - Not same!!!, do nothing")
            return
            
        deviceID = (topic.split('/', 3))[2]
        idx = self._get_ds_device_idx(deviceID)
        self._ds_ed[idx] = message[0]
        return
        
    def _get_ds_device_idx(self, deviceID):   
        if deviceID not in self._ds_deviceId:
            self._ds_deviceId.append(deviceID)
            idx = self._ds_deviceId.index(deviceID)
            self._ds_ed.insert(idx, 0.0)
        return self._ds_deviceId.index(deviceID)
        
def main(argv=sys.argv):
    '''Main method called by the eggsecutable.'''
    try:
        utils.vip_main(BuildingController)
    except Exception as e:
        print e
        _log.exception('unhandled exception')
        
if __name__ == '__main__':
    # Entry point for script
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        pass
        

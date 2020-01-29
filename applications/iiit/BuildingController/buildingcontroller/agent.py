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

import ispace_utils

utils.setup_logging()
_log = logging.getLogger(__name__)
__version__ = '0.4'

#checking if a floating point value is “numerically zero” by checking if it is lower than epsilon
EPSILON = 1e-03

SCHEDULE_AVLB = 1
SCHEDULE_NOT_AVLB = 0

E_UNKNOWN_CCE = -4
E_UNKNOWN_TSP = -5
E_UNKNOWN_BPP = -7


def buildingcontroller(config_path, **kwargs):
    config = utils.load_config(config_path)
    vip_identity = config.get('vip_identity', 'iiit.buildingcontroller')
    # This agent needs to be named iiit.buildingcontroller. Pop the uuid id off the kwargs
    kwargs.pop('identity', None)
    
    Agent.__name__ = 'BuildingController_Agent'
    return BuildingController(config_path, identity=vip_identity, **kwargs)
    
    
class BuildingController(Agent):
    '''Building Controller
    '''
    def __init__(self, config_path, **kwargs):
        super(BuildingController, self).__init__(**kwargs)
        _log.debug("vip_identity: " + self.core.identity)
        
        self.config = utils.load_config(config_path)
        self._config_get_points()
        self._config_get_init_values()
        return
        
    @Core.receiver('onsetup')
    def setup(self, sender, **kwargs):
        _log.info(self.config['message'])
        self._agent_id = self.config['agentid']
        return
        
    @Core.receiver('onstart')
    def startup(self, sender, **kwargs):
        self._pp_failed = False
        
        self._price_point_current = 0.4 
        self._price_point_latest = 0.45
        self._pp_id = randint(0, 99999999)
        self._pp_id_latest = randint(0, 99999999)
        
        self._rmTsp = 25
        
        #downstream energy demand and deviceId
        self._ds_ed = []
        self._ds_deviceId = []
        
        #building total energy demand (including downstream)
        self._ted = 0
        
        _log.info("yeild 30s for volttron platform to initiate properly...")
        time.sleep(30) #yeild for a movement
        _log.info("Starting BuildingController...")
        
        self._run_bms_test()
        
        #TODO: get the latest values (states/levels) from h/w
        #self.getInitialHwState()
        #time.sleep(1) #yeild for a movement
        
        #TODO: apply pricing policy for default values
        
        #TODO: publish initial data to volttron bus
        
        #perodically publish total energy demand to volttron bus
        self.core.periodic(self._period_read_data, self.publish_ted, wait=None)
        
        #perodically process new pricing point that keeps trying to apply the new pp till success
        self.core.periodic(self._period_process_pp, self.process_opt_pp, wait=None)
        
        #subscribing to topic_price_point
        self.vip.pubsub.subscribe("pubsub", self.topic_price_point, self.on_new_price)
        
        #subscribing to ds energy demand, vb publishes ed from registered ds to this topic
        self.vip.pubsub.subscribe("pubsub", self.topic_energy_demand_ds, self.on_ds_ed)
        
        self.vip.rpc.call(MASTER_WEB, 'register_agent_route'
                            , r'^/BuildingController'
                            , "rpc_from_net"
                            ).get(timeout=10)
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
        
    def _config_get_init_values(self):
        self._period_read_data = self.config.get('period_read_data', 30)
        self._period_process_pp = self.config.get('period_process_pp', 10)
        self._price_point_old = self.config.get('default_base_price', 0.1)
        self._price_point_latest = self.config.get('price_point_latest', 0.2)
        return
        
    def _config_get_points(self):
        self.vb_vip_identity = self.config.get('vb_vip_identity',
                                                'volttronbridgeagent-0.3_1')
        self.root_topic = self.config.get('topic_root', 'building')
        self.topic_energy_demand = self.config.get('topic_energy_demand',
                                                    'building/energydemand')
        self.topic_price_point = self.config.get('topic_price_point',
                                                    'building/pricepoint')
        self.topic_energy_demand_ds = self.config.get('topic_energy_demand_ds',
                                                        'ds/energydemand')
        return
        
    def _run_bms_test(self):
        _log.debug("Running: _runBMS Commu Test()...")
        _log.debug('change pp .10')
        self.publish_price_to_bms(0.10)
        time.sleep(10)
        
        _log.debug('change pp .75')
        self.publish_price_to_bms(0.75)
        time.sleep(10)
        
        _log.debug('change pp .25')
        self.publish_price_to_bms(0.25)
        time.sleep(10)
        
        _log.debug("EOF Testing")
        return
        
    def on_new_price(self, peer, sender, bus,  topic, headers, message):
        if sender == 'pubsub.compat':
            message = compat.unpack_legacy_message(headers, message)
            
        new_pp = message[ParamPP.idx_pp]
        new_pp_datatype = message[ParamPP.idx_pp_datatype]
        new_pp_id = message[ParamPP.idx_pp_id]
        new_pp_isoptimal = message[ParamPP.idx_pp_isoptimal]
        discovery_address = message[ParamPP.idx_pp_discovery_addrs]
        deviceId = message[ParamPP.idx_pp_device_id]
        new_pp_ttl = message[ParamPP.idx_pp_ttl]
        new_pp_ts = message[ParamPP.idx_pp_ts]
        ispace_utils.print_pp(self, new_pp
                , new_pp_datatype
                , new_pp_id
                , new_pp_isoptimal
                , discovery_address
                , deviceId
                , new_pp_ttl
                , new_pp_ts
                )
                
        if not new_pp_isoptimal:
            _log.debug('not optimal pp!!!, do nothing')
            return
            
        self._price_point_latest = new_pp
        self._pp_id_latest = new_pp_id
        self.process_opt_pp()
        return
        
    #this is a perodic function that keeps trying to apply the new pp till success
    def process_opt_pp(self):
        if ispace_utils.isclose(self._price_point_old, self._price_point_latest, EPSILON) and self._pp_id == self._pp_id_new:
            return
            
        self._pp_failed = False     #any process that failed to apply pp sets this flag True
        self.publish_price_to_bms(self._price_point_latest)
        if not self._pp_failed:
            self._apply_pricing_policy()
            
        if self._pp_failed:
            _log.debug("unable to process_opt_pp(), will try again in " + str(self._period_process_pp))
            return
            
        _log.info("New Price Point processed.")
        self._price_point_old = self._price_point_latest
        self._pp_id = self._pp_id_new
        return
        
    def _apply_pricing_policy(self):
        _log.debug("_apply_pricing_policy()")
        #TODO: control the energy demand of devices at building level accordingly
        #if applying self._price_point_latest failed, set self._pp_failed = True
        return
        
    # Publish new price to bms (for logging (o)r for further processing by the BMS)
    def publish_price_to_bms(self, pp):
        _log.debug('publish_price_to_bms()')
        task_id = str(randint(0, 99999999))
        result = ispace_utils.get_task_schdl(self, task_id,'iiit/cbs/buildingcontroller')
        if result['result'] == 'SUCCESS':
            try:
                result = self.vip.rpc.call('platform.actuator'
                                            , 'set_point'
                                            , self._agent_id
                                            , 'iiit/cbs/buildingcontroller/Building_PricePoint'
                                            , pp
                                            ).get(timeout=10)
                self.update_building_pp()
            except gevent.Timeout:
                _log.exception("Expection: gevent.Timeout in publish_price_to_bms()")
            except Exception as e:
                _log.exception ("Expection: changing device level")
                print(e)
            finally:
                #cancel the schedule
                ispace_utils.cancel_task_schdl(self, task_id)
        else:
            _log.debug('schedule NOT available')
        return
        
    def update_building_pp(self):
        #_log.debug('updateRmTsp()')
        _log.debug('building_pp {0:0.2f}'.format( self._price_point_latest))
        
        building_pp = self.rpc_get_building_pp()
        
        #check if the pp really updated at the bms, only then proceed with new pp
        if ispace_utils.isclose(self._price_point_latest, building_pp, EPSILON):
            self.publish_building_pp()
        else:
            self._pp_failed = True
            
        _log.debug('Current Building PP: ' + "{0:0.2f}".format( self._price_point_latest))
        return
        
    def publish_building_pp(self):
        #_log.debug('publish_building_pp()')
        pub_topic = self.root_topic+"/Building_PricePoint"
        pub_msg = [self._price_point_latest,
                    {'units': 'cents', 'tz': 'UTC', 'type': 'float'},
                    self._pp_id_new,
                    True
                    ]
        ispace_utils.publish_to_bus(self, pub_topic, pub_msg)
        return
        
    def rpc_get_building_pp(self):
        try:
            pp = self.vip.rpc.call('platform.actuator'
                                    ,'get_point'
                                    , 'iiit/cbs/buildingcontroller/Building_PricePoint'
                                    ).get(timeout=10)
            return pp
        except gevent.Timeout:
            _log.exception("Expection: gevent.Timeout in rpc_get_building_pp()")
            return E_UNKNOWN_BPP
        except Exception as e:
            _log.exception ("Expection: Could not contact actuator. Is it running?")
            print(e)
            return E_UNKNOWN_BPP
        return E_UNKNOWN_BPP
        
    def rpc_get_building_level_energy(self):
        #compute the energy of the other devices which are at building level
        return 0
        
    def _calculate_ted(self):
        #_log.debug('_calculate_ted()')
        
        ted = self.rpc_get_building_level_energy()
        for ed in self._ds_ed:
            ted = ted + ed
        
        return ted
        
    def publish_ted(self):
        self._ted = self._calculate_ted()
        _log.info( "New TED: {0:.4f}, publishing to bus.".format(self._ted))
        pub_topic = self.topic_energy_demand
        #_log.debug("TED pub_topic: " + pub_topic)
        pub_msg = [self._ted
                    , {'units': 'W', 'tz': 'UTC', 'type': 'float'}
                    , self._pp_id
                    , True
                    , None
                    , None
                    , None
                    , self._period_read_data
                    , datetime.datetime.utcnow().isoformat(' ') + 'Z'
                    ]
        ispace_utils.publish_to_bus(self, pub_topic, pub_msg)
        return
        
    def on_ds_ed(self, peer, sender, bus,  topic, headers, message):
        if sender == 'pubsub.compat':
            message = compat.unpack_legacy_message(headers, message)
        _log.debug('New ed from ds, topic: ' + topic +
                    ' & ed: {0:.4f}'.format(message[ParamED.idx_ed]))
                    
        ed_pp_id = message[ParamED.idx_ed_pp_id]
        ed_isoptimal = message[ParamED.idx_ed_isoptimal]
        if not ed_isoptimal:         #only accumulate the ed of an optimal pp
            _log.debug(" - Not optimal ed!!!, do nothing")
            return
            
        #deviceID = (topic.split('/', 3))[2]
        deviceID = message[ParamED.idx_ed_device_id]
        idx = self._get_ds_device_idx(deviceID)
        self._ds_ed[idx] = message[ParamED.idx_ed]
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
        utils.vip_main(buildingcontroller)
    except Exception as e:
        print (e)
        _log.exception('unhandled exception')
        
        
if __name__ == '__main__':
    # Entry point for script
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        pass
        
        
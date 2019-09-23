# -*- coding: utf-8 -*- {{{
# vim: set fenc=utf-8 ft=python sw=4 ts=4 sts=4 et:
#
# Copyright (c) 2019, Sam Babu, Godithi.
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
from volttron.platform.messaging import headers as headers_mod

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

SCHEDULE_AVLB = 1
SCHEDULE_NOT_AVLB = 0

E_UNKNOWN_CCE = -4
E_UNKNOWN_TSP = -5

utils.setup_logging()
_log = logging.getLogger(__name__)
__version__ = '0.2'

def DatetimeFromValue(ts):
    ''' Utility for dealing with time
    '''
    if isinstance(ts, (int, long)):
        return datetime.utcfromtimestamp(ts)
    elif isinstance(ts, float):
        return datetime.utcfromtimestamp(ts)
    elif not isinstance(ts, datetime):
        raise ValueError('Unknown timestamp value')
    return ts

class ZoneController(Agent):
    '''Zone Controller
    '''
    _price_point_previous = 0.4 
    _price_point_current = 0.4 
    _price_point_new = 0.45

    _rmTsp = 25
    
    #downstream energy demand and deviceId
    _ds_ed = []
    _ds_deviceId = []
    
    #zone total energy demand (including downstream PECS)
    _ted = 0

    def __init__(self, config_path, **kwargs):
        super(ZoneController, self).__init__(**kwargs)
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
        _log.info("Starting ZoneController...")

        self._runBMSTest()
        
        #perodically publish total energy demand to volttron bus
        self.core.periodic(self._period_read_data, self.publishTed, wait=None)
        
        #perodically process new pricing point
        self.core.periodic(10, self.processNewPricePoint, wait=None)
        
        #subscribing to topic_price_point
        self.vip.pubsub.subscribe("pubsub", self.topic_price_point, self.onNewPrice)
        
        #subscribing to ds energy demand, vb publishes ed from registered ds to this topic
        self.vip.pubsub.subscribe("pubsub", self.energyDemand_topic_ds, self.onDsEd)
        
        self.vip.rpc.call(MASTER_WEB, 'register_agent_route',
                      r'^/ZoneController',
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
        self._period_read_data = self.config['period_read_data']
        self._price_point_previous = self.config['default_base_price']
        self._price_point_current = self.config['default_base_price']
        return
        
    def _configGetPoints(self):
        self.root_topic              = self.config.get('topic_root', 'zone')
        self.energyDemand_topic     = self.config.get('topic_energy_demand', \
                                            'zone/energydemand')
        self.topic_price_point      = self.config.get('topic_price_point', \
                                            'zone/pricepoint')
        self.energyDemand_topic_ds  = self.config.get('topic_energy_demand_ds', \
                                            'ds/energydemand')
        return


    def _runBMSTest(self):
        _log.debug("Running : _runBMS Commu Test()...")
        
        _log.debug('change tsp 26')
        self.setRmTsp(26.0)
        time.sleep(10)
        
        _log.debug('change tsp 27')
        self.setRmTsp(27.0)
        time.sleep(10)
        
        _log.debug('change tsp 28')
        self.setRmTsp(28.0)
        time.sleep(10)
        
        _log.debug('change tsp 29')
        self.setRmTsp(29.0)
        time.sleep(10)
        
        _log.debug("EOF Testing")
        return
        
    def onNewPrice(self, peer, sender, bus,  topic, headers, message):
        if sender == 'pubsub.compat':
            message = compat.unpack_legacy_message(headers, message)

        new_price_point = message[0]
        #_log.info ( "*** New Price Point: {0:.2f} ***".format(new_price_point))

        self._price_point_new = new_price_point
        
        if self._price_point_current != new_price_point:
        #if True:
            self.processNewPricePoint()
        return
        
    def processNewPricePoint(self):
        if self._price_point_current != self._price_point_new:
            _log.info ( "*** New Price Point: {0:.2f} ***".format(self._price_point_new))
            self._price_point_previous = self._price_point_current
            self._price_point_current = self._price_point_new
            self.applyPricingPolicy()
        return

    def applyPricingPolicy(self):
        _log.debug("applyPricingPolicy()")
        tsp = self.getNewTsp(self._price_point_current)
        _log.debug('New Setpoint: {0:0.1f}'.format( tsp))
        self.setRmTsp(tsp)
        return
    
    #compute new TSP
    def getNewTsp(self, pp):
        if pp >= 0.9 :
            tsp = 30.0
        elif pp >= 0.8 :
            tsp = 29.0
        elif pp >= 0.7 :
            tsp = 28.0
        elif pp >= 0.6 :
            tsp = 27.0
        elif pp >= 0.5 :
            tsp = 26.0
        elif pp >= 0.4 :
            tsp = 25.0
        elif pp >= 0.3 :
            tsp = 24.0
        elif pp >= 0.2 :
            tsp = 23.0
        else :
            tsp = 22.0
        return tsp
    
    # change ambient temperature set point
    def setRmTsp(self, tsp):
        #_log.debug('setRmTsp()')
        
        if self._isclose(tsp, self._rmTsp, 1e-03):
            _log.debug('same tsp, do nothing')
            return
            
        task_id = str(randint(0, 99999999))
        result = self._getTaskSchedule(task_id)
        if result['result'] == 'SUCCESS':
            result = {}
            try:
                result = self.vip.rpc.call(
                    'platform.actuator', 
                    'set_point',
                    self._agent_id, 
                    'iiit/cbs/zonecontroller/RM_TSP',
                    tsp).get(timeout=10)
                self.updateRmTsp(tsp)
            except gevent.Timeout:
                _log.exception("Expection: gevent.Timeout in setRmTsp()")
            except Exception as e:
                _log.exception ("Expection: changing ambient tsp")
                print(e)
            finally:
                #cancel the schedule
                self._cancelSchedule(task_id)
        else:
            _log.debug('schedule NOT available')
        return
        
    def updateRmTsp(self, tsp):
        #_log.debug('updateRmTsp()')
        _log.debug('tsp {0:0.1f}'.format( tsp))
        
        rm_tsp = self.rpc_getRmTsp()
        
        #check if the tsp really updated at the h/w, only then proceed with new tsp
        if self._isclose(tsp, rm_tsp, 1e-03):
            self._rmTsp = tsp
            self.publishRmTsp(tsp)
            
        _log.debug('Current TSP: ' + "{0:0.1f}".format( rm_tsp))
        return
        
    def rpc_getRmCalcCoolingEnergy(self):
        task_id = str(randint(0, 99999999))
        result = self._getTaskSchedule(task_id)
        if result['result'] == 'SUCCESS':
            try:
                coolingEnergy = self.vip.rpc.call(
                        'platform.actuator','get_point',
                        'iiit/cbs/zonecontroller/RM_CCE').get(timeout=10)
                return coolingEnergy
            except gevent.Timeout:
                _log.exception("Expection: gevent.Timeout in rpc_getRmCalcCoolingEnergy()")
                return E_UNKNOWN_CCE
            except Exception as e:
                _log.exception ("Expection: Could not contact actuator. Is it running?")
                print(e)
                return E_UNKNOWN_CCE
            finally:
                #cancel the schedule
                self._cancelSchedule(task_id)
        else:
            _log.debug('schedule NOT available')
        return E_UNKNOWN_CCE

    def rpc_getRmTsp(self):
        try:
            rm_tsp = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/zonecontroller/RM_TSP').get(timeout=10)
            return rm_tsp
        except gevent.Timeout:
            _log.exception("Expection: gevent.Timeout in rpc_getRmTsp()")
            return E_UNKNOWN_TSP
        except Exception as e:
            _log.exception ("Expection: Could not contact actuator. Is it running?")
            print(e)
            return E_UNKNOWN_TSP
        return E_UNKNOWN_TSP
        
    def publishRmTsp(self, tsp):
        #_log.debug('publishRmTsp()')
        pubTopic = self.root_topic+"/rm_tsp"
        pubMsg = [tsp,{'units': 'celcius', 'tz': 'UTC', 'type': 'float'}]
        self.publishToBus(pubTopic, pubMsg)
        return
        
    def _calculateTed(self):
        #_log.debug('_calculateTed()')
        
        ted = self.rpc_getRmCalcCoolingEnergy()
        for ed in self._ds_ed:
            ted = ted + ed
        
        return ted

    def publishTed(self):
        ted = self._calculateTed()
        self._ted = ted
        _log.info( "*** New TED: {0:.2f}, publishing to bus ***".format(ted))
        pubTopic = self.energyDemand_topic
        _log.debug("TED pubTopic: " + pubTopic)
        pubMsg = [ted,
                    {'units': 'W', 'tz': 'UTC', 'type': 'float'}]
        self.publishToBus(pubTopic, pubMsg)
        return
        
    def _calculatePredictedTed(self):
        #_log.debug('_calculatePredictedTed()')
        
        #get actual tsp from device
        tsp = self._rmTsp
        if tsp == 22.0 :
            ted = 6500
        elif tsp == 23.0 :
            ted = 6000
        elif tsp == 24.0 :
            ted = 5500
        elif tsp == 25.0 :
            ted = 5000
        elif tsp == 26.0 :
            ted = 4500
        elif tsp == 27.0 :
            ted = 4000
        elif tsp == 28.0 :
            ted = 2000
        elif tsp == 29.0 :
            ted = 1000
        else :
            ted = 500
        return ted

    def publishToBus(self, pubTopic, pubMsg):
        #_log.debug('_publishToBus()')
        now = datetime.datetime.utcnow().isoformat(' ') + 'Z'
        headers = {headers_mod.DATE: now}

        #Publish messages
        try:
            self.vip.pubsub.publish('pubsub', pubTopic, headers, pubMsg).get(timeout=10)
        except gevent.Timeout:
            _log.warning("Expection: gevent.Timeout in _publishToBus()")
        except Exception as e:
            _log.warning("Expection: _publishToBus?")
            print(e)
        return

    def _getTaskSchedule(self, task_id, time_ms=None):
        #_log.debug("_getTaskSchedule()")
        self.time_ms = 600 if time_ms is None else time_ms
        try:
            result = {}
            start = str(datetime.datetime.now())
            end = str(datetime.datetime.now() 
                    + datetime.timedelta(milliseconds=self.time_ms))

            device = 'iiit/cbs/zonecontroller'
            msg = [
                    [device,start,end]
                    ]
            result = self.vip.rpc.call(
                    'platform.actuator', 
                    'request_new_schedule',
                    self._agent_id,                 #requested id
                    task_id,
                    'HIGH',
                    msg).get(timeout=10)
        except gevent.Timeout:
            _log.exception("Expection: gevent.Timeout in _getTaskSchedule()")
        except Exception as e:
            _log.exception ("Could not contact actuator. Is it running?")
            print(e)
            print result
        return result

    def _cancelSchedule(self, task_id):
        #_log.debug('_cancelSchedule')
        result = self.vip.rpc.call('platform.actuator', 'request_cancel_schedule', \
                                    self._agent_id, task_id).get(timeout=10)
        #_log.debug("task_id: " + task_id)
        #_log.debug(result)
        return
        
    #refer to http://stackoverflow.com/questions/5595425/what-is-the-best-way-to-compare-floats-for-almost-equality-in-python
    #comparing floats is mess
    def _isclose(self, a, b, rel_tol=1e-09, abs_tol=0.0):
        return abs(a-b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)
        
    def onDsEd(self, peer, sender, bus,  topic, headers, message):
        if sender == 'pubsub.compat':
            message = compat.unpack_legacy_message(headers, message)
        _log.debug('*********** New ed from ds, topic: ' + topic + \
                    ' & ed: {0:.4f}'.format(message[0]))
        
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
        utils.vip_main(ZoneController)
    except Exception as e:
        print e
        _log.exception('unhandled exception')


if __name__ == '__main__':
    # Entry point for script
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        pass

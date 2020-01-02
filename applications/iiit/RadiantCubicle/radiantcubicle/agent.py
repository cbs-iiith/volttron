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

from ispace_utils import mround, publish_to_bus, get_task_schdl, cancel_task_schdl, isclose

SCHEDULE_AVLB = 1
SCHEDULE_NOT_AVLB = 0

E_UNKNOWN_STATE = -2
E_UNKNOWN_LEVEL = -3
E_UNKNOWN_CCE   = -4

RC_AUTO_CNTRL_ON = 1
RC_AUTO_CNTRL_OFF = 0

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

class RadiantCubicle(Agent):
    '''Radiant Cubicle
    '''
    _price_point_previous = 0.4 
    _price_point_current = 0.4 
    _price_point_new = 0.45

    _rcAutoCntrlState = RC_AUTO_CNTRL_OFF
    _rcTspLevel = 25

    def __init__(self, config_path, **kwargs):
        super(RadiantCubicle, self).__init__(**kwargs)
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
        _log.info("Starting RadiantCubicle...")

        self._runRadiantCubicleTest()
        
        _log.debug('switch ON RC_AUTO_CNTRL')
        self.setRcAutoCntrl(RC_AUTO_CNTRL_ON)
        
        self.vip.rpc.call(MASTER_WEB, 'register_agent_route',
                      r'^/RadiantCubicle',
                      "rpc_from_net").get(timeout=10)
        
        #perodically publish total energy demand to volttron bus
        self.core.periodic(self._period_read_data, self.publishTed, wait=None)
        
        #perodically process new pricing point
        self.core.periodic(10, self.processNewPricePoint, wait=None)
        
        #subscribing to topic_price_point
        self.vip.pubsub.subscribe("pubsub", self.topic_price_point, self.onNewPrice)
        
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
        self._deviceId = self.config.get('deviceId', 'RadiantCubicle-61')
        return
        
    def _configGetPoints(self):
        self.root_topic              = self.config.get('topic_root', 'radiantcubicle')
        self.energyDemand_topic     = self.config.get('topic_energy_demand', \
                                            'radiantcubicle/energydemand')
        self.topic_price_point      = self.config.get('topic_price_point', \
                                            'topic_price_point')
        return


    def _runRadiantCubicleTest(self):
        _log.debug("Running : _runRadiantCubicleTest()...")
        
        _log.debug('change level 26')
        self.setRcTspLevel(26.0)
        time.sleep(10)
        
        _log.debug('change level 27')
        self.setRcTspLevel(27.0)
        time.sleep(10)
        
        _log.debug('change level 28')
        self.setRcTspLevel(28.0)
        time.sleep(10)
        
        _log.debug('change level 29')
        self.setRcTspLevel(29.0)
        time.sleep(10)
        
        _log.debug('switch ON RC_AUTO_CNTRL')
        self.setRcAutoCntrl(RC_AUTO_CNTRL_ON)
        time.sleep(10)
        
        _log.debug('switch OFF RC_AUTO_CNTRL')
        self.setRcAutoCntrl(RC_AUTO_CNTRL_OFF)
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
        self.setRcTspLevel(tsp)
        return
    
    #compute new TSP
    def getNewTsp(self, pp):
        if pp >= 0.9 :
            tsp = 22.0
        elif pp >= 0.8 :
            tsp = 23.0
        elif pp >= 0.7 :
            tsp = 24.0
        elif pp >= 0.6 :
            tsp = 25.0
        elif pp >= 0.5 :
            tsp = 26.0
        elif pp >= 0.4 :
            tsp = 27.0
        elif pp >= 0.3 :
            tsp = 28.0
        elif pp >= 0.2 :
            tsp = 29.0
        else :
            tsp = 30.0
        return tsp
    
    # change rc surface temperature set point
    def setRcTspLevel(self, level):
        #_log.debug('setRcTspLevel()')
        
        if isclose(level, self._rcTspLevel):
            _log.debug('same level, do nothing')
            return
            
        task_id = str(randint(0, 99999999))
        result = get_task_schdl(self, task_id,'iiit/cbs/radiantcubicle')
        if result['result'] == 'SUCCESS':
            try:
                result = self.vip.rpc.call(
                    'platform.actuator', 
                    'set_point',
                    self._agent_id, 
                    'iiit/cbs/radiantcubicle/RC_TSP',
                    level).get(timeout=10)
                self.updateRcTspLevel(level)
            except gevent.Timeout:
                _log.exception("Expection: gevent.Timeout in setRcTspLevel()")
            except Exception as e:
                _log.exception ("Expection: changing device level")
                print(e)
            finally:
                #cancel the schedule
                cancel_task_schdl(self, task_id)
        else:
            _log.debug('schedule NOT available')
        return
    
    def setRcAutoCntrl(self, state):
        _log.debug('setRcAutoCntrl()')

        if self._rcAutoCntrlState == state:
            _log.info('same state, do nothing')
            return

        #get schedule to setRcAutoCntrl
        task_id = str(randint(0, 99999999))
        #_log.debug("task_id: " + task_id)
        result = get_task_schdl(self, task_id,'iiit/cbs/radiantcubicle')

        if result['result'] == 'SUCCESS':
            result = {}
            try:
                #_log.debug('schl avlb')
                result = self.vip.rpc.call(
                        'platform.actuator', 
                        'set_point',
                        self._agent_id, 
                        'iiit/cbs/radiantcubicle/RC_AUTO_CNTRL',
                        state).get(timeout=10)

                self.updateRcAutoCntrl(state)
            except gevent.Timeout:
                _log.exception("Expection: gevent.Timeout in setRcAutoCntrl()")
            except Exception as e:
                _log.exception ("Expection: setting RC_AUTO_CNTRL")
                print(e)
            finally:
                #cancel the schedule
                cancel_task_schdl(self, task_id)
        else:
            _log.debug('schedule NOT available')
        return
        
    def updateRcTspLevel(self, level):
        #_log.debug('_updateShDeviceLevel()')
        _log.debug('level {0:0.1f}'.format( level))
        
        device_level = self.rpc_getRcTspLevel()
        
        #check if the level really updated at the h/w, only then proceed with new level
        if isclose(level, device_level):
            self._rcTspLevel = level
            self.publishRcTspLevel(level)
            
        _log.debug('Current level: ' + "{0:0.1f}".format( device_level))
        return
    
    def updateRcAutoCntrl(self, state):
        _log.debug('updateRcAutoCntrl()')
        
        rcAutoCntrlState = self.rpc_getRcAutoCntrlState()
        
        if state == int(rcAutoCntrlState):
            self._rcAutoCntrlState = state
            self.publishRcAutoCntrlState(state)

        if self._rcAutoCntrlState == RC_AUTO_CNTRL_ON:
            _log.info('Current State: RC Auto Cntrl is ON!!!')
        else:
            _log.info('Current State: RC Auto Cntrl OFF!!!')
            
        return
        
    def rpc_getRcCalcCoolingEnergy(self):
        task_id = str(randint(0, 99999999))
        result = get_task_schdl(self, task_id,'iiit/cbs/radiantcubicle')
        if result['result'] == 'SUCCESS':
            try:
                coolingEnergy = self.vip.rpc.call(
                        'platform.actuator','get_point',
                        'iiit/cbs/radiantcubicle/RC_CCE').get(timeout=10)
                return coolingEnergy
            except gevent.Timeout:
                _log.exception("Expection: gevent.Timeout in rpc_getRcCalcCoolingEnergy()")
                return E_UNKNOWN_CCE
            except Exception as e:
                _log.exception ("Expection: Could not contact actuator. Is it running?")
                print(e)
                return E_UNKNOWN_CCE
            finally:
                #cancel the schedule
                cancel_task_schdl(self, task_id)
        else:
            _log.debug('schedule NOT available')
        return E_UNKNOWN_CCE
        
    def rpc_getRcTspLevel(self):
        try:
            device_level = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/radiantcubicle/RC_TSP').get(timeout=10)
            return device_level
        except gevent.Timeout:
            _log.exception("Expection: gevent.Timeout in rpc_getShDeviceLevel()")
            return E_UNKNOWN_LEVEL
        except Exception as e:
            _log.exception ("Expection: Could not contact actuator. Is it running?")
            print(e)
            return E_UNKNOWN_LEVEL
        return E_UNKNOWN_LEVEL
        
    def rpc_getRcAutoCntrlState(self):
        try:
            state = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/radiantcubicle/RC_AUTO_CNTRL').get(timeout=10)
            return state
        except gevent.Timeout:
            _log.exception("Expection: gevent.Timeout in rpc_getShDeviceLevel()")
            return E_UNKNOWN_STATE
        except Exception as e:
            _log.exception ("Expection: Could not contact actuator. Is it running?")
            print(e)
            return E_UNKNOWN_STATE
        return E_UNKNOWN_STATE
        
    def publishRcTspLevel(self, level):
        #_log.debug('publishRcTspLevel()')
        pubTopic = self.root_topic+"/rc_tsp_level"
        pubMsg = [level, {'units': 'celcius', 'tz': 'UTC', 'type': 'float'}]
        publish_to_bus(self, pubTopic, pubMsg)
        return
        
    def publishRcAutoCntrlState(self, state):
        pubTopic = self.root_topic+"/rc_auto_cntrl_state"
        pubMsg = [state, {'units': 'On/Off', 'tz': 'UTC', 'type': 'int'}]
        publish_to_bus(self, pubTopic, pubMsg)
        return

    def publishTed(self):
        ted = self.rpc_getRcCalcCoolingEnergy()
        self._ted = ted
        _log.info( "*** New TED: {0:.2f}, publishing to bus ***".format(ted))
        pubTopic = self.energyDemand_topic
        pubTopic = self.energyDemand_topic + "/" + self._deviceId
        _log.debug("TED pubTopic: " + pubTopic)
        pubMsg = [ted, {'units': 'W', 'tz': 'UTC', 'type': 'float'}]
        publish_to_bus(self, pubTopic, pubMsg)
        return
        
    def _calculatePredictedTed(self):
        #_log.debug('_calculatePredictedTed()')
        
        #get actual tsp from device
        tsp = self._rcTspLevel
        if tsp == 22.0 :
            ted = 350
        elif tsp == 23.0 :
            ted = 325
        elif tsp == 24.0 :
            ted = 300
        elif tsp == 25.0 :
            ted = 275
        elif tsp == 26.0 :
            ted = 250
        elif tsp == 27.0 :
            ted = 225
        elif tsp == 28.0 :
            ted = 200
        elif tsp == 29.0 :
            ted = 150
        else :
            ted = 100
        return ted
        


def main(argv=sys.argv):
    '''Main method called by the eggsecutable.'''
    try:
        utils.vip_main(RadiantCubicle)
    except Exception as e:
        print e
        _log.exception('unhandled exception')


if __name__ == '__main__':
    # Entry point for script
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        pass

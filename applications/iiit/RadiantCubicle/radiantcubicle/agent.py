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

import ispace_utils

utils.setup_logging()
_log = logging.getLogger(__name__)
__version__ = '0.3'

#checking if a floating point value is “numerically zero” by checking if it is lower than epsilon
EPSILON = 1e-03

SCHEDULE_AVLB = 1
SCHEDULE_NOT_AVLB = 0

E_UNKNOWN_STATE = -2
E_UNKNOWN_LEVEL = -3
E_UNKNOWN_CCE = -4

RC_AUTO_CNTRL_ON = 1
RC_AUTO_CNTRL_OFF = 0

class RadiantCubicle(Agent):
    '''Radiant Cubicle
    '''
    _pp_failed = False
    
    _price_point_current = 0.4 
    _price_point_new = 0.45
    _pp_id = randint(0, 99999999)
    _pp_id_new = randint(0, 99999999)
    
    _rcAutoCntrlState = RC_AUTO_CNTRL_OFF
    _rcTspLevel = 25
    
    def __init__(self, config_path, **kwargs):
        super(RadiantCubicle, self).__init__(**kwargs)
        _log.debug("vip_identity: " + self.core.identity)
        
        self.config = utils.load_config(config_path)
        self._configGetPoints()
        self._configGetInitValues()
        self._configGetPriceFucntions()
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
        
        self.vip.rpc.call(MASTER_WEB, 'register_agent_route'
                            , r'^/RadiantCubicle'
                            , "rpc_from_net"
                            ).get(timeout=10)
                            
        _log.debug('switch ON RC_AUTO_CNTRL')
        self.setRcAutoCntrl(RC_AUTO_CNTRL_ON)
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
        self._period_read_data = self.config.get('period_read_data', 30)
        self._period_process_pp = self.config.get('period_process_pp', 10)
        self._price_point_old = self.config.get('price_point_latest', 0.2)
        self._deviceId = self.config.get('deviceId', 'RadiantCubicle-61')
        return
        
    def _configGetPoints(self):
        self.root_topic = self.config.get('topic_root', 'radiantcubicle')
        self.energyDemand_topic = self.config.get('topic_energy_demand',
                                                    'radiantcubicle/energydemand')
        self.topic_price_point = self.config.get('topic_price_point',
                                                    'topic_price_point')
        return
        
    def _configGetPriceFucntions(self):
        _log.debug("_configGetPriceFucntions()")
        self.pf_rc = self.config.get('pf_rc')
        return
        
    def _runRadiantCubicleTest(self):
        _log.debug("Running: _runRadiantCubicleTest()...")
        
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
            
        self._price_point_new = new_pp
        self._pp_id_new = new_pp_id
        self.processNewPricePoint()
        return
        
    #this is a perodic function that keeps trying to apply the new pp till success
    def processNewPricePoint(self):
        if ispace_utils.isclose(self._price_point_old, self._price_point_new, EPSILON) and self._pp_id == self._pp_id_new:
            return
            
        self._pp_failed = False     #any process that failed to apply pp sets this flag True
        self.applyPricingPolicy()
        
        if self._pp_failed:
            _log.debug("unable to processNewPricePoint(), will try again in " + str(self._period_process_pp))
            return
            
        _log.info("New Price Point processed.")
        self._price_point_old = self._price_point_new
        self._pp_id = self._pp_id_new
        return
        
    def applyPricingPolicy(self):
        _log.debug("applyPricingPolicy()")
        tsp = self.getNewTsp(self._price_point_new)
        _log.debug('New Setpoint: {0:0.1f}'.format( tsp))
        self.setRcTspLevel(tsp)
        if not ispace_utils.isclose(tsp, self._rcTspLevel, EPSILON):
            self._pp_failed = True
        return
        
    #compute new TSP
    def getNewTsp(self, pp):
        pp = 0 if pp < 0 else 1 if pp > 1 else pp
        
        pf_idx = self.pf_rc['pf_idx']
        pf_roundup = self.pf_rc['pf_roundup']
        pf_coefficients = self.pf_rc['pf_coefficients']
        
        a = pf_coefficients[pf_idx]['a']
        b = pf_coefficients[pf_idx]['b']
        c = pf_coefficients[pf_idx]['c']
        
        tsp = a*pp**2 + b*pp + c
        return ispace_utils.mround(tsp, pf_roundup)
        
    # change rc surface temperature set point
    def setRcTspLevel(self, level):
        #_log.debug('setRcTspLevel()')
        
        if ispace_utils.isclose(level, self._rcTspLevel, EPSILON):
            _log.debug('same level, do nothing')
            return
            
        task_id = str(randint(0, 99999999))
        result = ispace_utils.get_task_schdl(self, task_id,'iiit/cbs/radiantcubicle')
        if result['result'] == 'SUCCESS':
            try:
                result = self.vip.rpc.call('platform.actuator'
                                            , 'set_point'
                                            , self._agent_id
                                            , 'iiit/cbs/radiantcubicle/RC_TSP'
                                            , level
                                            ).get(timeout=10)
                self.updateRcTspLevel(level)
            except gevent.Timeout:
                _log.exception("Expection: gevent.Timeout in setRcTspLevel()")
            except Exception as e:
                _log.exception ("Expection: changing device level")
                print(e)
            finally:
                #cancel the schedule
                ispace_utils.cancel_task_schdl(self, task_id)
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
        result = ispace_utils.get_task_schdl(self, task_id,'iiit/cbs/radiantcubicle')
        
        if result['result'] == 'SUCCESS':
            result = {}
            try:
                #_log.debug('schl avlb')
                result = self.vip.rpc.call('platform.actuator'
                                            , 'set_point'
                                            , self._agent_id,
                                            , 'iiit/cbs/radiantcubicle/RC_AUTO_CNTRL'
                                            , state
                                            ).get(timeout=10)
                        
                self.updateRcAutoCntrl(state)
            except gevent.Timeout:
                _log.exception("Expection: gevent.Timeout in setRcAutoCntrl()")
            except Exception as e:
                _log.exception ("Expection: setting RC_AUTO_CNTRL")
                print(e)
            finally:
                #cancel the schedule
                ispace_utils.cancel_task_schdl(self, task_id)
        else:
            _log.debug('schedule NOT available')
        return
        
    def updateRcTspLevel(self, level):
        #_log.debug('_updateShDeviceLevel()')
        _log.debug('level {0:0.1f}'.format( level))
        
        device_level = self.rpc_getRcTspLevel()
        
        #check if the level really updated at the h/w, only then proceed with new level
        if ispace_utils.isclose(level, device_level, EPSILON):
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
        result = ispace_utils.get_task_schdl(self, task_id,'iiit/cbs/radiantcubicle')
        if result['result'] == 'SUCCESS':
            try:
                coolingEnergy = self.vip.rpc.call('platform.actuator'
                                                    ,'get_point'
                                                    , 'iiit/cbs/radiantcubicle/RC_CCE_ELEC'
                                                    ).get(timeout=10)
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
                ispace_utils.cancel_task_schdl(self, task_id)
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
            state = self.vip.rpc.call('platform.actuator'
                                        ,'get_point'
                                        , 'iiit/cbs/radiantcubicle/RC_AUTO_CNTRL'
                                        ).get(timeout=10)
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
        ispace_utils.publish_to_bus(self, pubTopic, pubMsg)
        return
        
    def publishRcAutoCntrlState(self, state):
        pubTopic = self.root_topic+"/rc_auto_cntrl_state"
        pubMsg = [state, {'units': 'On/Off', 'tz': 'UTC', 'type': 'int'}]
        ispace_utils.publish_to_bus(self, pubTopic, pubMsg)
        return
        
    def publishTed(self):
        self._ted = self.rpc_getRcCalcCoolingEnergy()
        _log.info( "New TED: {0:.2f}, publishing to bus.".format(self._ted))
        pubTopic = self.energyDemand_topic + "/" + self._deviceId
        #_log.debug("TED pubTopic: " + pubTopic)
        pubMsg = [self._ted
                    , {'units': 'W', 'tz': 'UTC', 'type': 'float'}
                    , self._pp_id
                    , True
                    , None
                    , self._deviceId
                    , None
                    , self._period_read_data
                    , datetime.datetime.utcnow().isoformat(' ') + 'Z'
                    ]
        ispace_utils.publish_to_bus(self, pubTopic, pubMsg)
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
        print (e)
        _log.exception('unhandled exception')

if __name__ == '__main__':
    # Entry point for script
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        pass
        
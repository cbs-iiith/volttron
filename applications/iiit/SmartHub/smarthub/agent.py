# -*- coding: utf-8 -*- {{{
# vim: set fenc=utf-8 ft=python sw=4 ts=4 sts=4 et:
#
# Copyright (c) 2017, IIIT-Hyderabad
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

import settings

import time
import struct

SH_DEVICE_STATE_ON = 1
SH_DEVICE_STATE_OFF = 0

SH_DEVICE_LED_DEBUG = 0
SH_DEVICE_LED = 1
SH_DEVICE_FAN = 2
SH_DEVICE_FAN_SWING = 3
SH_DEVICE_S_LUX = 4
SH_DEVICE_S_RH = 5
SH_DEVICE_S_TEMP = 6
SH_DEVICE_S_CO2 = 7
SH_DEVICE_S_PIR = 8

SCHEDULE_AVLB = 1
SCHEDULE_NOT_AVLB = 0

E_UNKNOWN_DEVICE = -1
E_UNKNOWN_STATE = -2
E_UNKNOWN_LEVEL = -3

#action types
AT_GET_STATE    = 321
AT_GET_LEVEL    = 322
AT_SET_STATE    = 323
AT_SET_LEVEL    = 324
AT_PUB_LEVEL    = 325
AT_PUB_STATE    = 326
AT_GET_THPP     = 327
AT_SET_THPP     = 328
AT_PUB_THPP     = 329

utils.setup_logging()
_log = logging.getLogger(__name__)
__version__ = '0.1'

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

def smarthub(config_path, **kwargs):
    config = utils.load_config(config_path)
    vip_identity = config.get('vip_identity', 'iiit.smarthub')
    # This agent needs to be named iiit.smarthub. Pop the uuid id off the kwargs
    kwargs.pop('identity', None)

    Agent.__name__ = 'SmartHub_Agent'
    return SmartHub(config_path, identity=vip_identity, **kwargs)

class SmartHub(Agent):
    '''Smart Hub
    '''
    _taskID_LedDebug = 1
    _ledDebugState = 0
    _ledState = 0
    _fanState = 0
    
    _voltState = 0
    
    '''
        SH_DEVICE_LED_DEBUG = 0 only state, no level
        SH_DEVICE_LED       = 1 both state and level
        SH_DEVICE_FAN       = 2 both state and level
        SH_DEVICE_FAN_SWING = 3 state only
        SH_DEVICE_S_LUX     = 4 only level
        SH_DEVICE_S_RH      = 5 only level
        SH_DEVICE_S_TEMP    = 6 only level
        SH_DEVICE_S_CO2     = 7 only level
        SH_DEVICE_S_PIR     = 8 only level (binary on/off)
    '''
    _shDevicesState = [0, 0, 0, 0, 0, 0, 0, 0, 0]
    _shDevicesLevel = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    _shDevicesPP_th = [ 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
    _price_point_previous = 0.4 
    _price_point_current = 0.4 

    def __init__(self, config_path, **kwargs):
        super(SmartHub, self).__init__(**kwargs)
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
        self.runSmartHubTest()
        
        _log.debug('switch on debug led')
        self.setShDeviceState(SH_DEVICE_LED_DEBUG, SH_DEVICE_STATE_ON, SCHEDULE_NOT_AVLB)
        time.sleep(1) #yeild for a movement
        
        #perodically publish device threshold price point to volttron bus
        self.core.periodic(self._period_read_data, self.publishDeviceThPP, wait=None)
        
        #perodically publish sensor data to volttron bus
        self.core.periodic(self._period_read_data, self.publishSensorData, wait=None)

        self.vip.rpc.call(MASTER_WEB, 'register_agent_route', \
                            r'^/SmartHub', \
                            self.core.identity, \
                            "rpc_from_net").get(timeout=30)
        self._voltState = 1
        
        return  
    @Core.receiver('onstop')
    def onstop(self, sender, **kwargs):
        _log.debug('onstop()')
        if self._voltState != 0:
            self._stopVolt()
        
        return
    @Core.receiver('onfinish')
    def onfinish(self, sender, **kwargs):
        _log.debug('onfinish()')
        if self._voltState != 0:
            self._stopVolt()
        
        return 
        
    def _stopVolt(self):
        _log.debug('_stopVolt()')
        self.setShDeviceState(SH_DEVICE_LED_DEBUG, SH_DEVICE_STATE_OFF, SCHEDULE_NOT_AVLB)
        self.setShDeviceState(SH_DEVICE_LED, SH_DEVICE_STATE_OFF, SCHEDULE_NOT_AVLB)
        self.setShDeviceState(SH_DEVICE_FAN, SH_DEVICE_STATE_OFF, SCHEDULE_NOT_AVLB)
        self._voltState = 0
        return

    def _configGetInitValues(self):
        self._period_read_data = self.config['period_read_data']
        
        return
    def _configGetPoints(self):
        self.ledDebugState_point = self.config.get('ledDebugState_point',
                                            'smarthub/leddebugstate')    
        self.ledState_point = self.config.get('ledState_point',
                                            'smarthub/ledstate')    
        self.fanState_point = self.config.get('fanState_point',
                                            'smarthub/fanstate')    
        self.ledLevel_point = self.config.get('ledLevel_point',
                                            'smarthub/ledlevel')    
        self.fanLevel_point = self.config.get('fanLevel_point',
                                            'smarthub/fanlevel')
        self.ledThPP_point = self.config.get('ledThPP_point',
                                            'smarthub/ledthpp')    
        self.fanThPP_point = self.config.get('fanThPP_point',
                                            'smarthub/fanthpp')

        self.sensorsLevelAll_point = self.config.get('sensorsLevelAll_point',
                                            'smarthub/sensors/all')
        self.sensorLuxLevel_point = self.config.get('sensorLuxLevel_point',
                                            'smarthub/sensors/luxlevel')    
        self.sensorRhLevel_point = self.config.get('sensorRhLevel_point',
                                            'smarthub/sensors/rhlevel')    
        self.sensorTempLevel_point = self.config.get('sensorTempLevel_point',
                                            'smarthub/sensors/templevel')    
        self.sensorCo2Level_point = self.config.get('sensorCo2Level_point',
                                            'smarthub/sensors/co2level')
        self.sensorPirLevel_point = self.config.get('sensorPirLevel_point',
                                            'smarthub/sensors/pirlevel')
        return
    def runSmartHubTest(self):
        _log.debug("Running : runSmartHubTest()...")
        
        self.testLedDebug()
        self.testLed()
        self.testFan()
        #self.testSensors()
        self.testSensors_2()
        _log.debug("EOF Testing")
        
        return   
    def testLedDebug(self):
        _log.debug('switch on debug led')
        self.setShDeviceState(SH_DEVICE_LED_DEBUG, SH_DEVICE_STATE_ON, SCHEDULE_NOT_AVLB)
        time.sleep(1)

        _log.debug('switch off debug led')
        self.setShDeviceState(SH_DEVICE_LED_DEBUG, SH_DEVICE_STATE_OFF, SCHEDULE_NOT_AVLB)
        time.sleep(1)

        _log.debug('switch on debug led')
        self.setShDeviceState(SH_DEVICE_LED_DEBUG, SH_DEVICE_STATE_ON, SCHEDULE_NOT_AVLB)
        time.sleep(1)

        _log.debug('switch off debug led')
        self.setShDeviceState(SH_DEVICE_LED_DEBUG, SH_DEVICE_STATE_OFF, SCHEDULE_NOT_AVLB)
        time.sleep(1)
        
        _log.debug('switch on debug led')
        self.setShDeviceState(SH_DEVICE_LED_DEBUG, SH_DEVICE_STATE_ON, SCHEDULE_NOT_AVLB)
        time.sleep(1)

        _log.debug('switch off debug led')
        self.setShDeviceState(SH_DEVICE_LED_DEBUG, SH_DEVICE_STATE_OFF, SCHEDULE_NOT_AVLB)
        time.sleep(1)
        
        return
    def testLed(self):
        _log.debug('switch on led')
        self.setShDeviceState(SH_DEVICE_LED, SH_DEVICE_STATE_ON, SCHEDULE_NOT_AVLB)
        time.sleep(1)

        _log.debug('change led level 0.3')        
        self.setShDeviceLevel(SH_DEVICE_LED, 0.3, SCHEDULE_NOT_AVLB)
        time.sleep(1)

        _log.debug('change led level 0.6')        
        self.setShDeviceLevel(SH_DEVICE_LED, 0.6, SCHEDULE_NOT_AVLB)
        time.sleep(1)

        _log.debug('change led level 0.9')        
        self.setShDeviceLevel(SH_DEVICE_LED, 0.9, SCHEDULE_NOT_AVLB)
        time.sleep(1)
        
        _log.debug('switch off led')
        self.setShDeviceState(SH_DEVICE_LED, SH_DEVICE_STATE_OFF, SCHEDULE_NOT_AVLB)
        time.sleep(1)
        
        return
    def testFan(self):
        _log.debug('switch on fan')
        self.setShDeviceState(SH_DEVICE_FAN, SH_DEVICE_STATE_ON, SCHEDULE_NOT_AVLB)
        time.sleep(1)
        
        _log.debug('change fan level 0.3')        
        self.setShDeviceLevel(SH_DEVICE_FAN, 0.3, SCHEDULE_NOT_AVLB)
        time.sleep(1)

        _log.debug('change fan level 0.6')        
        self.setShDeviceLevel(SH_DEVICE_FAN, 0.6, SCHEDULE_NOT_AVLB)
        time.sleep(1)

        _log.debug('change fan level 0.9')        
        self.setShDeviceLevel(SH_DEVICE_FAN, 0.9, SCHEDULE_NOT_AVLB)
        time.sleep(1)
        
        _log.debug('switch off fan')
        self.setShDeviceState(SH_DEVICE_FAN, SH_DEVICE_STATE_OFF, SCHEDULE_NOT_AVLB)
        time.sleep(1)

        return
    def testSensors(self):
        _log.debug('test lux sensor')
        lux_level = self.getShDeviceLevel(SH_DEVICE_S_LUX, SCHEDULE_NOT_AVLB)
        _log.debug("lux Level: " + "{0:0.4f}".format(lux_level))
        time.sleep(1)
        
        _log.debug('test rh sensor')
        rh_level = self.getShDeviceLevel(SH_DEVICE_S_RH, SCHEDULE_NOT_AVLB)
        _log.debug("rh Level: " + "{0:0.4f}".format(rh_level))
        time.sleep(1)
        
        _log.debug('test temp sensor')
        temp_level = self.getShDeviceLevel(SH_DEVICE_S_TEMP, SCHEDULE_NOT_AVLB)
        _log.debug("temp Level: " + "{0:0.4f}".format(temp_level))
        time.sleep(1)
        
        _log.debug('test co2 sensor')
        co2_level = self.getShDeviceLevel(SH_DEVICE_S_CO2, SCHEDULE_NOT_AVLB)
        _log.debug("co2 Level: " + "{0:0.4f}".format(co2_level))
        time.sleep(1)
        
        _log.debug('test PIR sensor')
        pir_level = self.getShDeviceLevel(SH_DEVICE_S_PIR, SCHEDULE_NOT_AVLB)
        _log.debug("PIR Level: " + "{0:d}".format(int(pir_level)))
        time.sleep(1)
        
        return
    def testSensors_2(self):
        result = self._getTaskSchedule('testSensors_2', 300)
        try:
            if result['result'] == 'SUCCESS':
                _log.debug('test lux sensor')
                lux_level = self.getShDeviceLevel(SH_DEVICE_S_LUX, SCHEDULE_AVLB)
                _log.debug("lux Level: " + "{0:0.4f}".format(lux_level))
                
                _log.debug('test rh sensor')
                rh_level = self.getShDeviceLevel(SH_DEVICE_S_RH, SCHEDULE_AVLB)
                _log.debug("rh Level: " + "{0:0.4f}".format(rh_level))
                
                _log.debug('test temp sensor')
                temp_level = self.getShDeviceLevel(SH_DEVICE_S_TEMP, SCHEDULE_AVLB)
                _log.debug("temp Level: " + "{0:0.4f}".format(temp_level))
                
                _log.debug('test co2 sensor')
                co2_level = self.getShDeviceLevel(SH_DEVICE_S_CO2, SCHEDULE_AVLB)
                _log.debug("co2 Level: " + "{0:0.4f}".format(co2_level))
                
                _log.debug('test pir sensor')
                pir_level = self.getShDeviceLevel(SH_DEVICE_S_PIR, SCHEDULE_AVLB)
                _log.debug("pir Level: " + "{0:d}".format(int(pir_level)))
        except Exception as e:
            _log.exception ("Expection: no task schdl for testSensors_2()")
            #print(e)
            return
        
        return
        
    def getShDeviceState(self, deviceId, schdExist):
        state = E_UNKNOWN_STATE
        if not _validDeviceAction(deviceId, AT_GET_STATE) :
            _log.exception ("Expection: not a valid device to get state, deviceId: " + str(deviceId))
            return state
            
        if schdExist == SCHEDULE_AVLB: 
            state = self.rpc_getShDeviceState(deviceId);
        elif schdExist == SCHEDULE_NOT_AVLB:
            result = self._getTaskSchedule('getShDeviceState_' + str(deviceId))
            try:
                if result['result'] == 'SUCCESS':
                    state = self.rpc_getShDeviceState(deviceId);
            except Exception as e:
                _log.exception ("Expection: no task schdl for getting device state")
                #print(e)
                return state
        else:
            #do notthing
            _log.exception ("not a valid param - schdExist: " + schdExist)
            return state
        
        return state
        
    def getShDeviceLevel(self, deviceId, schdExist):
        #_log.debug('getShDeviceLevel()')
        level = E_UNKNOWN_LEVEL
        if not self._validDeviceAction( deviceId, AT_GET_LEVEL) :
            _log.exception ("not a valid device to get level, deviceId: " + str(deviceId))
            return level
            
        if schdExist == SCHEDULE_AVLB: 
            level = self.rpc_getShDeviceLevel(deviceId);
        elif schdExist == SCHEDULE_NOT_AVLB:
            result = self._getTaskSchedule('getShDeviceLevel_' + str(deviceId))
            try:
                if result['result'] == 'SUCCESS':
                    level = self.rpc_getShDeviceLevel(deviceId);
            except Exception as e:
                _log.exception ("Expection: no task schdl for getting device level")
                #print(e)
                return level
        else:
            #do notthing
            _log.exception ("Expection: not a valid param - schdExist: " + schdExist)
            return level
        
        return level
                
    def setShDeviceState(self, deviceId, state, schdExist):
        #_log.debug('setShDeviceState()')
        if not self._validDeviceAction(deviceId, AT_SET_STATE) :
            _log.exception ("Expection: not a valid device to change state, deviceId: " + str(deviceId))
            return

        if self._shDevicesState[deviceId] == state:
            _log.debug('same state, do nothing')
            return

        if schdExist == SCHEDULE_AVLB: 
            self.rpc_setShDeviceState(deviceId, state);
        elif schdExist == SCHEDULE_NOT_AVLB:
            result = self._getTaskSchedule('setShDeviceState_' + str(deviceId))
            try:
                if result['result'] == 'SUCCESS':
                    self.rpc_setShDeviceState(deviceId, state);
            except Exception as e:
                _log.exception ("Expection: no task schdl for changing device state")
                #print(e)
                return
        else:
            #do notthing
            _log.exception ("not a valid param - schdExist: " + schdExist)
            return
        return
        
    def setShDeviceLevel(self, deviceId, level, schdExist):
        #_log.debug('setShDeviceLevel()')
        if not self._validDeviceAction( deviceId, AT_SET_LEVEL):
            _log.exception ("Expection: not a valid device to change level, deviceId: " + str(deviceId))
            return

        if self._shDevicesLevel[deviceId] == level:
            _log.debug('same level, do nothing')
            return

        if schdExist == SCHEDULE_AVLB: 
            self.rpc_setShDeviceLevel(deviceId, level);
        elif schdExist == SCHEDULE_NOT_AVLB:
            result = self._getTaskSchedule('setShDeviceLevel_' + str(deviceId))
            try:
                if result['result'] == 'SUCCESS':
                    self.rpc_setShDeviceLevel(deviceId, level);
            except Exception as e:
                _log.exception ("Expection: no task schdl for changing device level")
                #print(e)
                return
        else:
            #do notthing
            _log.exception ("Expection: not a valid param - schdExist: " + schdExist)
            return
        
        return
              
    def publishSensorData(self) :
        #_log.debug('publishSensorData()')
        result = self._getTaskSchedule('publishSensorData', 300)
        #print(result)
        try:
            if result['result'] == 'SUCCESS':
                pubTopic = self.sensorsLevelAll_point
                lux_level = self.getShDeviceLevel(SH_DEVICE_S_LUX, SCHEDULE_AVLB)
                rh_level = self.getShDeviceLevel(SH_DEVICE_S_RH, SCHEDULE_AVLB)
                temp_level = self.getShDeviceLevel(SH_DEVICE_S_TEMP, SCHEDULE_AVLB)
                co2_level = self.getShDeviceLevel(SH_DEVICE_S_CO2, SCHEDULE_AVLB)
                pir_level = self.getShDeviceLevel(SH_DEVICE_S_PIR, SCHEDULE_AVLB)
                time.sleep(1)  #yeild for a movement
                
                _log.debug("lux Level: " + "{0:0.4f}".format(lux_level) \
                            + ", rh Level: " + "{0:0.4f}".format(rh_level) \
                            + ", temp Level: " + "{0:0.4f}".format(temp_level) \
                            + ", co2 Level: " + "{0:0.4f}".format(co2_level) \
                            + ", pir Level: " + "{0:d}".format(int(pir_level)) \
                            )
                
                pubMsg = [{'luxlevel':lux_level, \
                            'rhlevel':rh_level, \
                            'templevel':temp_level, \
                            'co2level': co2_level, \
                            'pirlevel': pir_level \
                            }, \
                            {'luxlevel':{'units': 'lux', 'tz': 'UTC', 'type': 'float'}, \
                                'rhlevel':{'units': 'cent', 'tz': 'UTC', 'type': 'float'},
                                'templevel':{'units': 'degree', 'tz': 'UTC', 'type': 'float'}, \
                                'co2level':{'units': 'ppm', 'tz': 'UTC', 'type': 'float'}, \
                                'pirlevel':{'units': 'bool', 'tz': 'UTC', 'type': 'int'} \
                            } \
                            ]
                self._publishToBus(pubTopic, pubMsg)
        
        except Exception as e:
            _log.exception ("Expection: no task schdl for publishSensorData()")
            self.core.periodic(self._period_read_data, self.publishSensorData, wait=None)
            #print(e)
            return        
        
        return
        
    def publishDeviceThPP(self) :
        #_log.debug('publishDeviceThPP()')
        thpp_led = self._shDevicesPP_th[SH_DEVICE_LED]
        thpp_fan = self._shDevicesPP_th[SH_DEVICE_FAN]
        self._publishShDeviceThPP(SH_DEVICE_LED, thpp_led)
        self._publishShDeviceThPP(SH_DEVICE_FAN, thpp_fan)
        _log.debug("led th pp: " + "{0:0.4f}".format(thpp_led) \
                    + ", fan th pp: " + "{0:0.4f}".format(thpp_fan))
        return
    
    @PubSub.subscribe('pubsub','prices/PricePoint')
    def onNewPrice(self, peer, sender, bus,  topic, headers, message):
        if sender == 'pubsub.compat':
            message = compat.unpack_legacy_message(headers, message)

        new_price_point = message[0]
        _log.debug ( "*** New Price Point: {0:.2f} ***".format(new_price_point))
        
        if self._price_point_current != new_price_point:
            self.processNewPricePoint(new_price_point)

    def processNewPricePoint(self, new_price_point):
        self._price_point_previous = self._price_point_current
        self._price_point_current = new_price_point

        self.applyPricingPolicy(SH_DEVICE_LED)
        self.applyPricingPolicy(SH_DEVICE_FAN)

    def applyPricingPolicy(self, deviceId):
        shDevicesPP_th = self._shDevicesPP_th[deviceId]
        if self._price_point_current > shDevicesPP_th: 
            if self._shDevicesState[deviceId] == SH_DEVICE_STATE_ON:
                _log.info(_getEndPoint(deviceId, AT_GET_STATE) \
                            + 'Current price point < threshold' \
                            + '({0:.2f}), '.format(plug_pp_th) \
                            + 'Switching-Off Power' \
                            )
                self.setShDeviceState(deviceId, SH_DEVICE_STATE_OFF, SCHEDULE_NOT_AVLB)
            #else:
                #do nothing
        else:
            _log.info(_getEndPoint(deviceId, AT_GET_STATE) \
                        + 'Current price point < threshold' \
                        + '({0:.2f}), '.format(plug_pp_th) \
                        + 'Switching-On Power' \
                        )
            self.setShDeviceState(deviceId, SH_DEVICE_STATE_ON, SCHEDULE_NOT_AVLB)
            
        return
    
    def rpc_getShDeviceState(self, deviceId):
        if not self._validDeviceAction(deviceId,AT_GET_STATE):
            _log.exception ("Expection: not a valid device to get state, deviceId: " + str(deviceId))
            return
        endPoint = self._getEndPoint(deviceId, AT_GET_STATE)
        try:
            device_level = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/smarthub/' + endPoint).get(timeout=1)
        except Exception as e:
            _log.exception ("Expection: Could not contact actuator. Is it running?")
            #print(e)
            return
        return int(device_level)

    def rpc_setShDeviceState(self, deviceId, state):
        if not self._validDeviceAction(deviceId, AT_SET_STATE):
            _log.exception ("Expection: not a valid device to change state, deviceId: " + str(deviceId))
            return
        endPoint = self._getEndPoint(deviceId, AT_SET_STATE)
        try:
            result = self.vip.rpc.call(
                    'platform.actuator', 
                    'set_point',
                    self._agent_id, 
                    'iiit/cbs/smarthub/' + endPoint,
                    state).get(timeout=1)
        except Exception as e:
            _log.exception ("Expection: Could not contact actuator. Is it running?")
            #print(e)
            return
        self._updateShDeviceState(deviceId, endPoint,state)
        return
        
    def rpc_getShDeviceLevel(self, deviceId):
        #_log.debug("rpc_getShDeviceLevel()")
        if not self._validDeviceAction(deviceId, AT_GET_LEVEL):
            _log.exception ("Expection: not a valid device to get level, deviceId: " + str(deviceId))
            return
        endPoint = self._getEndPoint(deviceId, AT_GET_LEVEL)
        #_log.debug("endPoint: " + endPoint)
        try:
            device_level = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/smarthub/' + endPoint).get(timeout=1)
            return float(device_level)
        except Exception as e:
            _log.exception ("Expection: Could not contact actuator. Is it running?")
            #print(e)
            return
        return 0
        
    def rpc_setShDeviceLevel(self, deviceId, level):
        if not self._validDeviceAction(deviceId, AT_SET_LEVEL):
            _log.exception ("Expection: not a valid device to change level, deviceId: " + str(deviceId))
            return
        endPoint = self._getEndPoint(deviceId, AT_SET_LEVEL)
       
        try:
            result = self.vip.rpc.call(
                    'platform.actuator', 
                    'set_point',
                    self._agent_id, 
                    'iiit/cbs/smarthub/' + endPoint,
                    level).get(timeout=1)
            self._updateShDeviceLevel(deviceId, endPoint,level)
            return
        except Exception as e:
            _log.exception ("Expection: Could not contact actuator. Is it running?")
            #print(e)
            return
        
    def rpc_setShDeviceThPP(self, deviceId, thPP):
        if not self._validDeviceAction(deviceId, AT_SET_THPP):
            _log.exception ("Expection: not a valid device to change thPP, deviceId: " + str(deviceId))
            return
        self._shDevicesPP_th[deviceId] = thPP
        return
        
    def _getTaskSchedule(self, taskId, time_ms=None):
        #_log.debug("_getTaskSchedule()")
        self.time_ms = 600 if time_ms is None else time_ms
        try: 
            start = str(datetime.datetime.now())
            end = str(datetime.datetime.now() 
                    + datetime.timedelta(milliseconds=self.time_ms))

            msg = [
                    ['iiit/cbs/smarthub',start,end]
                    ]
            result = self.vip.rpc.call(
                    'platform.actuator', 
                    'request_new_schedule',
                    self._agent_id, 
                    taskId,
                    'HIGH',
                    msg).get(timeout=1)
            #print("schedule result", result)
        except Exception as e:
            _log.exception ("Expection: Could not contact actuator. Is it running?")
            #print(e)
            return        
        return result

    def _updateShDeviceState(self, deviceId, endPoint, state):
        #_log.debug('_updateShDeviceState()')
        headers = { 'requesterID': self._agent_id, }
        
        device_state = self.rpc_getShDeviceState(deviceId)
        #check if the state really updated at the h/w, only then proceed with new state
        if state == device_state:
            self._shDevicesState[deviceId] = state
            self._publishShDeviceState(deviceId, state)
            
        if self._shDevicesState[deviceId] == SH_DEVICE_STATE_ON:
            _log.debug('Current State: ' + endPoint + ' Switched ON!!!')
        else:
            _log.debug('Current State: ' + endPoint + ' Switched OFF!!!')
            
        return
        
    def _updateShDeviceLevel(self, deviceId, endPoint, level):
        #_log.debug('_updateShDeviceLevel()')
        
        device_level = self.rpc_getShDeviceLevel(deviceId)
        #check if the level really updated at the h/w, only then proceed with new level
        if level == device_level:
            self._shDevicesLevel[deviceId] = level
            self._publishShDeviceLevel(deviceId, level)
            
        _log.debug('Current level, ' + endPoint + ': ' + "{0:0.4f}".format( device_level))
            
        return
        
    def _publishShDeviceState(self, deviceId, state):
        if not self._validDeviceAction(deviceId, AT_PUB_STATE):
            _log.exception ("not a valid device to pub state, deviceId: " + str(deviceId))
            return
        pubTopic = self._getPubTopic(deviceId, AT_PUB_STATE)
        pubMsg = [state,{'units': 'On/Off', 'tz': 'UTC', 'type': 'int'}]
        self._publishToBus(pubTopic, pubMsg)

        return
        
    def _publishShDeviceLevel(self, deviceId, level):
        if not self._validDeviceAction(deviceId, AT_PUB_LEVEL):
            _log.exception ("Expection: not a valid device to pub level, deviceId: " + str(deviceId))
            return
        pubTopic = self._getPubTopic(deviceId, AT_PUB_LEVEL)
        pubMsg = [level,{'units': 'duty', 'tz': 'UTC', 'type': 'float'}]
        self._publishToBus(pubTopic, pubMsg)
        
        return
        
    def _publishShDeviceThPP(self, deviceId, thPP):
        if not self._validDeviceAction(deviceId, AT_PUB_THPP):
            _log.exception ("Expection: not a valid device to pub level, deviceId: " + str(deviceId))
            return
        pubTopic = self._getPubTopic(deviceId, AT_PUB_THPP)
        pubMsg = [thPP,{'units': 'cent', 'tz': 'UTC', 'type': 'float'}]
        self._publishToBus(pubTopic, pubMsg)
        
        return
        
    def _publishToBus(self, pubTopic, pubMsg):
        now = datetime.datetime.utcnow().isoformat(' ') + 'Z'
        headers = {headers_mod.DATE: now}          
        #Publish messages
        self.vip.pubsub.publish('pubsub', pubTopic, headers, pubMsg).get(timeout=5)
        
        return
    
    def _getPubTopic(self, deviceId, actionType):
        if actionType == AT_PUB_STATE:
            if deviceId ==SH_DEVICE_LED_DEBUG:
                return self.ledDebugState_point
            elif deviceId ==SH_DEVICE_LED:
                return self.ledState_point
            elif deviceId ==SH_DEVICE_FAN:
                return self.fanState_point
        elif actionType == AT_PUB_LEVEL :    
            if deviceId == SH_DEVICE_LED:
                return self.ledLevel_point
            elif deviceId == SH_DEVICE_FAN:
                return self.fanLevel_point
            elif deviceId ==SH_DEVICE_S_LUX:
                return self.sensorLuxLevel_point
            elif deviceId ==SH_DEVICE_S_RH:
                return self.sensorRhLevel_point
            elif deviceId ==SH_DEVICE_S_TEMP:
                return self.sensorTempLevel_point
            elif deviceId ==SH_DEVICE_S_CO2:
                return self.sensorCo2Level_point
            elif deviceId ==SH_DEVICE_S_PIR:
                return self.sensorPirLevel_point
        elif actionType == AT_PUB_THPP:
            if deviceId == SH_DEVICE_LED:
                return self.ledThPP_point
            elif deviceId == SH_DEVICE_FAN:
                return self.fanThPP_point
        _log.exception ("Expection: not a vaild device-action type for pubTopic")
        return ""
        
    def _getEndPoint(self, deviceId, actionType):
        #_log.debug('_getEndPoint()')
        if  actionType == AT_SET_LEVEL :
            if deviceId == SH_DEVICE_LED :
                return "LEDPwmDuty"
            elif deviceId == SH_DEVICE_FAN : 
                return "FanPwmDuty"
        elif actionType == AT_GET_LEVEL :
            if deviceId == SH_DEVICE_LED :
                return "LEDPwmDuty"
            elif deviceId == SH_DEVICE_FAN :
                return "FanPwmDuty"
            elif deviceId == SH_DEVICE_S_LUX :
                return "SensorLux"
            elif deviceId == SH_DEVICE_S_RH :
                return "SensorRh"
            elif deviceId == SH_DEVICE_S_TEMP :
                return "SensorTemp"
            elif deviceId == SH_DEVICE_S_CO2 :
                return "SensorCO2"
            elif deviceId == SH_DEVICE_S_PIR :
                return "SensorOccupancy"
        elif actionType in [ \
                            AT_GET_STATE, \
                            AT_SET_STATE \
                            ]:
            if deviceId == SH_DEVICE_LED_DEBUG:
                return "LEDDebug"
            elif deviceId == SH_DEVICE_LED :
                return "LED"
            elif deviceId == SH_DEVICE_FAN :
                return "Fan"
        
        _log.exception ("Expection: not a vaild device-action type for endpoint")
        return ""
        
    def _validDeviceAction(self, deviceId, actionType):
        #_log.debug('_validDeviceAction()')
        if actionType not in [ \
                                AT_GET_STATE, \
                                AT_GET_LEVEL, \
                                AT_SET_STATE, \
                                AT_SET_LEVEL, \
                                AT_PUB_LEVEL, \
                                AT_PUB_STATE, \
                                AT_GET_THPP, \
                                AT_SET_THPP, \
                                AT_PUB_THPP \
                                ]:
            return False
        
        if actionType == AT_GET_STATE :
            if deviceId in [ \
                            SH_DEVICE_LED_DEBUG, \
                            SH_DEVICE_LED, \
                            SH_DEVICE_FAN \
                            ]:
                return True
        elif actionType ==  AT_GET_LEVEL :
            if deviceId in [ \
                            SH_DEVICE_LED, \
                            SH_DEVICE_FAN, \
                            SH_DEVICE_S_LUX, \
                            SH_DEVICE_S_RH, \
                            SH_DEVICE_S_TEMP, \
                            SH_DEVICE_S_CO2, \
                            SH_DEVICE_S_PIR \
                            ]:
                return True
        elif actionType == AT_SET_STATE :
            if deviceId in [ \
                            SH_DEVICE_LED_DEBUG, \
                            SH_DEVICE_LED, \
                            SH_DEVICE_FAN \
                            ]:
                return True
        elif actionType == AT_SET_LEVEL :
            if deviceId in [ \
                            SH_DEVICE_LED, \
                            SH_DEVICE_FAN \
                            ]:
                return True
        elif actionType == AT_PUB_LEVEL :
            if deviceId in [ \
                            SH_DEVICE_LED, \
                            SH_DEVICE_FAN, \
                            SH_DEVICE_S_LUX, \
                            SH_DEVICE_S_RH, \
                            SH_DEVICE_S_TEMP, \
                            SH_DEVICE_S_CO2, \
                            SH_DEVICE_S_PIR \
                            ]:
                return True
        elif actionType == AT_PUB_STATE :
            if deviceId in [ \
                            SH_DEVICE_LED_DEBUG, \
                            SH_DEVICE_LED, \
                            SH_DEVICE_FAN \
                            ]:
                return True
        elif actionType in [ \
                            AT_GET_THPP, \
                            AT_SET_THPP, \
                            AT_PUB_THPP
                            ] :
            if deviceId in [ \
                            SH_DEVICE_LED, \
                            SH_DEVICE_FAN \
                            ]:
                return True
        log.exception ("Expection: not a vaild device-action")
        return False
        
    @RPC.export
    def rpc_from_net(self, header, message):
        print(message)
        return self.processMessage(message)

    def processMessage(self, message):
        _log.debug('processResponse()')
        result = 'FAILED'
        try:
            rpcdata = jsonrpc.JsonRpcData.parse(message)
            _log.info('rpc method: {}'.format(rpcdata.method))
            
            if rpcdata.method == "rpc_setShDeviceState":
                args = {'deviceId': rpcdata.params['deviceId'], 
                        'state': rpcdata.params['newState']
                        }
                result = self.rpc_setShDeviceState(**args)
            elif rpcdata.method == "rpc_setShDeviceLevel":
                args = {'deviceId': rpcdata.params['deviceId'], 
                        'level': rpcdata.params['newLevel']
                        }
                result = self.rpc_setShDeviceLevel(**args)              
            elif rpcdata.method == "rpc_setShDeviceThPP":
                args = {'deviceId': rpcdata.params['deviceId'], 
                        'thPP': rpcdata.params['newThPP']
                        }
                result = self.setThresholdPP(**args)                
            else:
                return jsonrpc.json_error('NA', METHOD_NOT_FOUND,
                    'Invalid method {}'.format(rpcdata.method))
                    
            return jsonrpc.json_result(rpcdata.id, result)
            
        except AssertionError:
            print('AssertionError')
            return jsonrpc.json_error('NA', INVALID_REQUEST,
                    'Invalid rpc data {}'.format(data))
        except Exception as e:
            print(e)
            return jsonrpc.json_error('NA', UNHANDLED_EXCEPTION, e)
            
def main(argv=sys.argv):
    '''Main method called by the eggsecutable.'''
    try:
        utils.vip_main(smarthub)
    except Exception as e:
        print e
        _log.exception('unhandled exception')


if __name__ == '__main__':
    # Entry point for script
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        pass
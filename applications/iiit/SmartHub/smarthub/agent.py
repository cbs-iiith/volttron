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

import settings

import time
import struct
import gevent
import gevent.event

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

SMARTHUB_BASE_ENERGY    = 2.0
SMARTHUB_FAN_ENERGY     = 6.0
SMARTHUB_LED_ENERGY     = 3.0


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
    _shDevicesLevel = [0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3]
    _shDevicesPP_th = [ 0.95, 0.95, 0.95, 0.95, 0.95, 0.95, 0.95, 0.95, 0.95]
    _price_point_previous = 0.4 
    _price_point_current = 0.4
    
    #downstream energy demand and deviceId
    _ds_ed = []
    _ds_deviceId = []
    
    #smarthub total energy demand (including downstream smartstrips)
    _ted = SMARTHUB_BASE_ENERGY

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
        
        time.sleep(10) #yeild for a movement
        
        _log.debug('switch on debug led')
        self.setShDeviceState(SH_DEVICE_LED_DEBUG, SH_DEVICE_STATE_ON, SCHEDULE_NOT_AVLB)
        time.sleep(1) #yeild for a movement

        #get the latest values (states/levels) from h/w
        self.getInitialHwState()
        time.sleep(1) #yeild for a movement

        #apply pricing policy for default values
        self.applyPricingPolicy(SH_DEVICE_LED)
        self.applyPricingPolicy(SH_DEVICE_FAN)
        
        #publish initial data to volttron bus
        self.publishDeviceState();
        self.publishDeviceLevel();
        self.publishDeviceThPP();
        self.publishSensorData();
        self.publishCurrentPP();
        
        #perodically publish device state to volttron bus
        self.core.periodic(self._period_read_data, self.publishDeviceState, wait=None)

        #perodically publish device level to volttron bus
        self.core.periodic(self._period_read_data, self.publishDeviceLevel, wait=None)
        
        #perodically publish device threshold price point to volttron bus
        self.core.periodic(self._period_read_data, self.publishDeviceThPP, wait=None)
        
        #perodically publish sensor data to volttron bus
        self.core.periodic(self._period_read_data, self.publishSensorData, wait=None)
        
        #perodically publish sensor data to volttron bus
        self.core.periodic(self._period_read_data, self.publishTed, wait=None)
        
        #subscribing to smarthub price point, sh gc published sh pp
        self.vip.pubsub.subscribe("pubsub", self.topic_price_point, self.onNewPrice)
        
        #subscribing to ds energy demand, vb publishes ed from registered ds to this topic
        self.vip.pubsub.subscribe("pubsub", self.energyDemand_topic_ds, self.onDsEd)

        self.vip.rpc.call(MASTER_WEB, 'register_agent_route', \
                            r'^/SmartHub', \
#                            self.core.identity, \
                            "rpc_from_net").get(timeout=30)
        self._voltState = 1
        
        return  
    @Core.receiver('onstop')
    def onstop(self, sender, **kwargs):
        _log.debug('onstop()')
        if self._voltState != 0:
            self._stopVolt()
        
        _log.debug('un registering rpc routes')
        self.vip.rpc.call(MASTER_WEB, \
#                            self.core.identity, \
                            'unregister_all_agent_routes').get(timeout=30)
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
        self.topic_root = self.config.get('topic_root', 'smarthub')
        self.topic_price_point = self.config.get('topic_price_point', \
                                        'smarthub/pricepoint')
        self.energyDemand_topic     = self.config.get('topic_energy_demand', \
                                            'smarthub/energydemand')
        self.energyDemand_topic_ds  = self.config.get('topic_energy_demand_ds', \
                                            'smartstrip/energydemand')
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
        
    def getInitialHwState(self):
        #_log.debug("getInitialHwState()")
        result = self._getTaskSchedule('getInitialHwState', 300)
        try:
            if result['result'] == 'SUCCESS':
                self._shDevicesState[SH_DEVICE_LED] = self.getShDeviceState(SH_DEVICE_LED, SCHEDULE_AVLB)
                self._shDevicesState[SH_DEVICE_FAN] = self.getShDeviceState(SH_DEVICE_FAN, SCHEDULE_AVLB)
                self._shDevicesLevel[SH_DEVICE_LED] = self.getShDeviceLevel(SH_DEVICE_LED, SCHEDULE_AVLB)
                self._shDevicesLevel[SH_DEVICE_FAN] = self.getShDeviceLevel(SH_DEVICE_FAN, SCHEDULE_AVLB)
        except Exception as e:
            _log.exception ("Expection: no task schdl for getInitialHwState()")
            #print(e)
            return
            
        return
        
    def getShDeviceState(self, deviceId, schdExist):
        state = E_UNKNOWN_STATE
        if not self._validDeviceAction(deviceId, AT_GET_STATE) :
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
            
        if self._isclose(level, self._shDevicesLevel[deviceId], 1e-03):
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
        
    def setShDeviceThPP(self, deviceId, thPP):
        if not self._validDeviceAction(deviceId, AT_SET_THPP):
            _log.exception ("Expection: not a valid device to change thPP, deviceId: " + str(deviceId))
            return
         
        if self._shDevicesPP_th[deviceId] == thPP:
            _log.debug('same thPP, do nothing')
            return
        
        self._shDevicesPP_th[deviceId] = thPP
        self._publishShDeviceThPP(deviceId, thPP)
        self.applyPricingPolicy(deviceId)
        
        return
        
    def publishSensorData(self) :
        #_log.debug('publishSensorData()')
        result = self._getTaskSchedule('publishSensorData', 300)
        #print(result)
        try:
            if result['result'] == 'SUCCESS':
                pubTopic = self.topic_root + '/sensors/all'
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
        
    def publishDeviceState(self) :
        #_log.debug('publishDeviceState()')
        state_led = self._shDevicesState[SH_DEVICE_LED]
        state_fan = self._shDevicesState[SH_DEVICE_FAN]
        self._publishShDeviceState(SH_DEVICE_LED, state_led)
        self._publishShDeviceState(SH_DEVICE_FAN, state_fan)
        _log.debug("led state: " + "{0:0.4f}".format(float(state_led)) \
                    + ", fan state: " + "{0:0.4f}".format(float(state_fan)))
        return
        
    def publishDeviceLevel(self) :
        #_log.debug('publishDeviceLevel()')
        level_led = self._shDevicesLevel[SH_DEVICE_LED]
        level_fan = self._shDevicesLevel[SH_DEVICE_FAN]
        self._publishShDeviceLevel(SH_DEVICE_LED, level_led)
        self._publishShDeviceLevel(SH_DEVICE_FAN, level_fan)
        _log.debug("led level: " + "{0:0.4f}".format(float(level_led)) \
                    + ", fan level: " + "{0:0.4f}".format(float(level_fan)))
        return
        
    def publishDeviceThPP(self) :
        #_log.debug('publishDeviceThPP()')
        thpp_led = self._shDevicesPP_th[SH_DEVICE_LED]
        thpp_fan = self._shDevicesPP_th[SH_DEVICE_FAN]
        self._publishShDeviceThPP(SH_DEVICE_LED, thpp_led)
        self._publishShDeviceThPP(SH_DEVICE_FAN, thpp_fan)
        _log.debug("led th pp: " + "{0:0.4f}".format(float(thpp_led)) \
                    + ", fan th pp: " + "{0:0.4f}".format(float(thpp_fan)))
        return
        
    def publishCurrentPP(self) :
        #_log.debug('publishCurrentPP()')
        _log.debug("current price point: " + "{0:0.4f}".format(float(self._price_point_current)))
                    
        pubMsg = [self._price_point_current,{'units': 'cent', 'tz': 'UTC', 'type': 'float'}]
        self._publishToBus(self.topic_price_point, pubMsg)
        
        
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
        _log.debug("applyPricingPolicy()")
        shDevicesPP_th = self._shDevicesPP_th[deviceId]
        if self._price_point_current > shDevicesPP_th: 
            if self._shDevicesState[deviceId] == SH_DEVICE_STATE_ON:
                _log.info(self._getEndPoint(deviceId, AT_GET_STATE) \
                            + 'Current price point > threshold' \
                            + '({0:.2f}), '.format(shDevicesPP_th) \
                            + 'Switching-Off Power' \
                            )
                self.setShDeviceState(deviceId, SH_DEVICE_STATE_OFF, SCHEDULE_NOT_AVLB)
            #else:
                #do nothing
        else:
            _log.info(self._getEndPoint(deviceId, AT_GET_STATE) \
                        + 'Current price point <= threshold' \
                        + '({0:.2f}), '.format(shDevicesPP_th) \
                        + 'Switching-On Power' \
                        )
            self.setShDeviceState(deviceId, SH_DEVICE_STATE_ON, SCHEDULE_NOT_AVLB)
            
        return
        
    def rpc_getShDeviceState(self, deviceId):
        if not self._validDeviceAction(deviceId,AT_GET_STATE):
            _log.exception ("Expection: not a valid device to get state, deviceId: " + str(deviceId))
            return E_UNKNOWN_STATE
        endPoint = self._getEndPoint(deviceId, AT_GET_STATE)
        try:
            device_level = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/smarthub/' + endPoint).get(timeout=10 )
        except gevent.Timeout:
            _log.exception("Expection: gevent.Timeout in rpc_getShDeviceState()")
            return E_UNKNOWN_STATE
        except RemoteError as re:
            print(re)
            return E_UNKNOWN_STATE
        except Exception as e:
            _log.exception ("Expection: Could not contact actuator. Is it running?")
            #print(e)
            return E_UNKNOWN_STATE
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
                    state).get(timeout=10)
        except gevent.Timeout:
            _log.exception("Expection: gevent.Timeout in rpc_setShDeviceState()")
            return
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
            return E_UNKNOWN_LEVEL
        endPoint = self._getEndPoint(deviceId, AT_GET_LEVEL)
        #_log.debug("endPoint: " + endPoint)
        try:
            device_level = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/smarthub/' + endPoint).get(timeout=10)
            return device_level
        except gevent.Timeout:
            _log.exception("Expection: gevent.Timeout in rpc_getShDeviceLevel()")
            return E_UNKNOWN_LEVEL
        except Exception as e:
            _log.exception ("Expection: Could not contact actuator. Is it running?")
            #print(e)
            return E_UNKNOWN_LEVEL
        return E_UNKNOWN_LEVEL
        
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
                    level).get(timeout=10)
            self._updateShDeviceLevel(deviceId, endPoint,level)
            return
        except gevent.Timeout:
            _log.exception("Expection: gevent.Timeout in rpc_setShDeviceLevel()")
            return
        except Exception as e:
            _log.exception ("Expection: Could not contact actuator. Is it running?")
            #print(e)
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
                    msg).get(timeout=10)
            #print("schedule result", result)
        except gevent.Timeout:
            _log.exception("Expection: gevent.Timeout in _getTaskSchedule()")
            return
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
        _log.debug('_updateShDeviceLevel()')
        
        _log.debug('level {0:0.4f}'.format( level))
        device_level = self.rpc_getShDeviceLevel(deviceId)
        #check if the level really updated at the h/w, only then proceed with new level
        if self._isclose(level, device_level, 1e-03):
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
        #_log.debug('_publishShDeviceLevel()')
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
        #_log.debug('_publishToBus()')
        now = datetime.datetime.utcnow().isoformat(' ') + 'Z'
        headers = {headers_mod.DATE: now}
        #Publish messages
        try:
            self.vip.pubsub.publish('pubsub', pubTopic, headers, pubMsg).get(timeout=10)
        except gevent.Timeout:
            _log.warning("Expection: gevent.Timeout in _publishToBus()")
            return
        except Exception as e:
            _log.warning("Expection: _publishToBus?")
            return
        return
        
    def _getPubTopic(self, deviceId, actionType):
        if actionType == AT_PUB_STATE:
            if deviceId ==SH_DEVICE_LED_DEBUG:
                return self.topic_root + '/leddebugstate'
            elif deviceId ==SH_DEVICE_LED:
                return self.topic_root + '/ledstate'
            elif deviceId ==SH_DEVICE_FAN:
                return self.topic_root + '/fanstate'
        elif actionType == AT_PUB_LEVEL :    
            if deviceId == SH_DEVICE_LED:
                return self.topic_root + '/ledlevel'
            elif deviceId == SH_DEVICE_FAN:
                return self.topic_root + '/fanlevel'
            elif deviceId ==SH_DEVICE_S_LUX:
                return self.topic_root + '/sensors/luxlevel'
            elif deviceId ==SH_DEVICE_S_RH:
                return self.topic_root + '/sensors/rhlevel'
            elif deviceId ==SH_DEVICE_S_TEMP:
                return self.topic_root + '/sensors/templevel'
            elif deviceId ==SH_DEVICE_S_CO2:
                return self.topic_root + '/sensors/co2level'
            elif deviceId ==SH_DEVICE_S_PIR:
                return self.topic_root + '/sensors/pirlevel'
        elif actionType == AT_PUB_THPP:
            if deviceId == SH_DEVICE_LED:
                return self.topic_root + '/ledthpp'
            elif deviceId == SH_DEVICE_FAN:
                return self.topic_root + '/fanthpp'
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
        #print(message)
        return self._processMessage(message)
        
    def _processMessage(self, message):
        #_log.debug('processResponse()')
        result = False
        try:
            rpcdata = jsonrpc.JsonRpcData.parse(message)
            _log.info('rpc method: {}'.format(rpcdata.method))
            _log.info('rpc params: {}'.format(rpcdata.params))
            
            if rpcdata.method == "rpc_setShDeviceState":
                args = {'deviceId': rpcdata.params['deviceId'], 
                        'state': rpcdata.params['newState'],
                        'schdExist': SCHEDULE_NOT_AVLB
                        }
                result = self.setShDeviceState(**args)
                
            elif rpcdata.method == "rpc_setShDeviceLevel":
                args = {'deviceId': rpcdata.params['deviceId'], 
                        'level': rpcdata.params['newLevel'],
                        'schdExist': SCHEDULE_NOT_AVLB
                        }
                result = self.setShDeviceLevel(**args)
                
            elif rpcdata.method == "rpc_setShDeviceThPP":
                args = {'deviceId': rpcdata.params['deviceId'], 
                        'thPP': rpcdata.params['newThPP']
                        }
                result = self.setShDeviceThPP(**args)                
            elif rpcdata.method == "rpc_ping":
                result = True
            else:
                return jsonrpc.json_error('NA', METHOD_NOT_FOUND,
                    'Invalid method {}'.format(rpcdata.method))
            result = True        
            return jsonrpc.json_result(rpcdata.id, result)
            
        except KeyError as ke:
            print(ke)
            return jsonrpc.json_error('NA', INVALID_PARAMS,
                    'Invalid params {}'.format(rpcdata.params))
        except AssertionError:
            print('AssertionError')
            return jsonrpc.json_error('NA', INVALID_REQUEST,
                    'Invalid rpc data {}'.format(data))
        except Exception as e:
            print(e)
            return jsonrpc.json_error('NA', UNHANDLED_EXCEPTION, e)
            
    #refer to http://stackoverflow.com/questions/5595425/what-is-the-best-way-to-compare-floats-for-almost-equality-in-python
    #comparing floats is mess
    def _isclose(self, a, b, rel_tol=1e-09, abs_tol=0.0):
        return abs(a-b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)
    
    #calculate the local energy demand
    def _calculateLocalEd(self):
        #_log.debug('_calculateLocalEd()')
        
        ed = SMARTHUB_BASE_ENERGY
        if self._shDevicesState[SH_DEVICE_LED] == SH_DEVICE_STATE_ON:
            ed = ed + SMARTHUB_LED_ENERGY
        if self._shDevicesState[SH_DEVICE_FAN] == SH_DEVICE_STATE_ON:
            ed = ed + SMARTHUB_FAN_ENERGY
    
        return ed
    
    #calculate the total energy demand (TED)
    def _calculateTed(self):
        #_log.debug('_calculateTed()')
        
        ted = self._calculateLocalEd()
        for ed in self._ds_ed:
            ted = ted + ed
        
        return ted
        
    def publishTed(self):
        #_log.debug('publishTed()')
        
        ted = self._calculateTed()
        
        '''
        #only publish if change in ted
        if self._ted == ted:
            return
        '''
        self._ted = ted
        _log.debug ( "*** New TED: {0:.2f}, publishing to bus ***".format(ted))
        pubTopic = self.energyDemand_topic
        pubMsg = [ted,
                    {'units': 'W', 'tz': 'UTC', 'type': 'float'}]
        self._publishToBus(pubTopic, pubMsg)
        return  
        
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
        

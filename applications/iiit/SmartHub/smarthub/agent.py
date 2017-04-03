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

SCHEDULE_AVLB = 1
SCHEDULE_NOT_AVLB = 0

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
    
    '''
        SH_DEVICE_LED_DEBUG = 0 only state, no level
        SH_DEVICE_LED = 1       both state and level
        SH_DEVICE_FAN = 2       both satet and level
    '''
    _shDevicesState = [0, 0, 0]
    _shDevicesLevel = [0, 0, 0]
    
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
        self.switchShDevice(SH_DEVICE_LED_DEBUG, SH_DEVICE_STATE_ON, SCHEDULE_NOT_AVLB)
        
        return  

    @Core.receiver('onstop')
    def onstop(self, sender, **kwargs):
        _log.debug('onstop()')
        self.switchShDevice(SH_DEVICE_LED_DEBUG, SH_DEVICE_STATE_OFF, SCHEDULE_NOT_AVLB)
        
        return

    @Core.receiver('onfinish')
    def onfinish(self, sender, **kwargs):
        _log.debug('onfinish()')
        self.switchShDevice(SH_DEVICE_LED_DEBUG, SH_DEVICE_STATE_OFF, SCHEDULE_NOT_AVLB)
        
        return
        
    def _configGetInitValues(self):
        
        return

    def _configGetPoints(self):
        self.ledDebugState_point = self.config.get('ledDebugState_point',
                                            'smarthub/leddebugstate')    
        self.ledState_point = self.config.get('ledState_point',
                                            'smarthub/ledstate')    
        self.fanState_point = self.config.get('fanState_point',
                                            'smarthub/fanstate')    
        self.ledLevel_point = self.config.get('ledState_point',
                                            'smarthub/ledlevel')    
        self.fanLevel_point = self.config.get('fanState_point',
                                            'smarthub/fanlevel')    
        
        return

    def runSmartHubTest(self):
        _log.debug("Running : runSmartHubTest()...")
        
        self.testLedDebug()
        self.testLed()
        self.testFan()

        _log.debug("EOF Testing")
        
        return
    
    def testLedDebug(self):
        _log.debug('switch on debug led')
        self.switchShDevice(SH_DEVICE_LED_DEBUG, SH_DEVICE_STATE_ON, SCHEDULE_NOT_AVLB)
        time.sleep(1)

        _log.debug('switch off debug led')
        self.switchShDevice(SH_DEVICE_LED_DEBUG, SH_DEVICE_STATE_OFF, SCHEDULE_NOT_AVLB)
        time.sleep(1)

        _log.debug('switch on debug led')
        self.switchShDevice(SH_DEVICE_LED_DEBUG, SH_DEVICE_STATE_ON, SCHEDULE_NOT_AVLB)
        time.sleep(1)

        _log.debug('switch off debug led')
        self.switchShDevice(SH_DEVICE_LED_DEBUG, SH_DEVICE_STATE_OFF, SCHEDULE_NOT_AVLB)
        time.sleep(1)
        
        _log.debug('switch on debug led')
        self.switchShDevice(SH_DEVICE_LED_DEBUG, SH_DEVICE_STATE_ON, SCHEDULE_NOT_AVLB)
        time.sleep(1)

        _log.debug('switch off debug led')
        self.switchShDevice(SH_DEVICE_LED_DEBUG, SH_DEVICE_STATE_OFF, SCHEDULE_NOT_AVLB)
        time.sleep(1)
        
        return

    def testLed(self):
        _log.debug('switch on led')
        self.switchShDevice(SH_DEVICE_LED, SH_DEVICE_STATE_ON, SCHEDULE_NOT_AVLB)
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
        self.switchShDevice(SH_DEVICE_LED, SH_DEVICE_STATE_OFF, SCHEDULE_NOT_AVLB)
        time.sleep(1)
        
        return

    def testFan(self):
        _log.debug('switch on fan')
        self.switchShDevice(SH_DEVICE_FAN, SH_DEVICE_STATE_ON, SCHEDULE_NOT_AVLB)
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
        self.switchShDevice(SH_DEVICE_FAN, SH_DEVICE_STATE_OFF, SCHEDULE_NOT_AVLB)
        time.sleep(1)

        return
        
    def switchShDevice(self, deviceId, state, schdExist):
        #_log.debug('switchShDevice()')

        if self._shDevicesState[deviceId] == state:
            _log.debug('same state, do nothing')
            return

        if schdExist == SCHEDULE_AVLB: 
            self.rpc_switchShDevice(deviceId, state);
        elif schdExist == SCHEDULE_NOT_AVLB:
            result = self.getTaskSchedule('switchShDevice_' + str(deviceId))
            try:
                if result['result'] == 'SUCCESS':
                    self.rpc_switchShDevice(deviceId, state);
            except Exception as e:
                _log.exception ("Expection: no task schdl for changing device state")
                #print(e)
                return
        else:
            #do notthing
            _log.exception ("not a valid param - schdExist: " + schdExist)
            return
        return
        
    def getTaskSchedule(self, taskId):
        try: 
            start = str(datetime.datetime.now())
            end = str(datetime.datetime.now() 
                    + datetime.timedelta(milliseconds=600))

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
            _log.exception ("Could not contact actuator. Is it running?")
            #print(e)
            return        
        return result
        
    def rpc_switchShDevice(self, deviceId, state):
        if deviceId == SH_DEVICE_LED_DEBUG:
            endPoint = 'LEDDebug'
        elif deviceId == SH_DEVICE_LED:
            endPoint = 'LED'
        elif deviceId == SH_DEVICE_FAN:
            endPoint = 'Fan'
        else :
            _log.exception('not a valid deviceId')
            return
        result = self.vip.rpc.call(
                'platform.actuator', 
                'set_point',
                self._agent_id, 
                'iiit/cbs/smarthub/' + endPoint,
                state).get(timeout=1)
        #print("Set result", result)
        #_log.debug('OK call updateShDeviceState()')
        self.updateShDeviceState(deviceId, endPoint,state)
        return

    def updateShDeviceState(self, deviceId, endPoint, state):
        #_log.debug('updateShDeviceState()')
        headers = { 'requesterID': self._agent_id, }
        device_status = self.vip.rpc.call(
                'platform.actuator','get_point',
                'iiit/cbs/smarthub/' + endPoint).get(timeout=1)

        if state == int(device_status):
            self._shDevicesState[deviceId] = state
            self.publishShDeviceState(deviceId, state)
            
        if self._shDevicesState[deviceId] == SH_DEVICE_STATE_ON:
            _log.debug('Current State: ' + endPoint + ' Switched ON!!!')
        else:
            _log.debug('Current State: ' + endPoint + ' Switched OFF!!!')

    def publishShDeviceState(self, deviceId, state):
        if deviceId == SH_DEVICE_LED_DEBUG:
            pubTopic = self.ledDebugState_point
        elif deviceId == SH_DEVICE_LED:
            pubTopic = self.ledState_point
        elif deviceId == SH_DEVICE_FAN:
            pubTopic = self.fanState_point
        else :
            _log.exception('not a valid deviceId')
            return

        pubMsg = [state,{'units': 'On/Off', 'tz': 'UTC', 'type': 'int'}]
        self.publishToBus(pubTopic, pubMsg)
        
        return
        
    def publishToBus(self, pubTopic, pubMsg):
        now = datetime.datetime.utcnow().isoformat(' ') + 'Z'
        headers = {headers_mod.DATE: now}          
        #Publish messages
        self.vip.pubsub.publish('pubsub', pubTopic, headers, pubMsg).get(timeout=5)
        
        return
        
    def setShDeviceLevel(self, deviceId, level, schdExist):
        #_log.debug('setShDeviceLevel()')
        
        if deviceId != SH_DEVICE_LED and \
                deviceId != SH_DEVICE_FAN :
            _log.exception ("not a valid device to change level, deviceId: " + str(deviceId))
            return

        if self._shDevicesLevel[deviceId] == level:
            _log.debug('same level, do nothing')
            return

        if schdExist == SCHEDULE_AVLB: 
            self.rpc_setShDeviceLevel(deviceId, level);
        elif schdExist == SCHEDULE_NOT_AVLB:
            result = self.getTaskSchedule('setShDeviceLevel_' + str(deviceId))
            try:
                if result['result'] == 'SUCCESS':
                    self.rpc_setShDeviceLevel(deviceId, level);
            except Exception as e:
                _log.exception ("Expection: no task schdl for changing device level")
                #print(e)
                return
        else:
            #do notthing
            _log.exception ("not a valid param - schdExist: " + schdExist)
            return
        
        return
        
    def rpc_getShDeviceLevel(self, deviceId):
        if deviceId == SH_DEVICE_LED:
            endPoint = 'LEDPwmDuty'
        elif deviceId == SH_DEVICE_FAN:
            endPoint = 'FanPwmDuty'
        else :
            _log.exception ("not a valid device to change level, deviceId: " + str(deviceId))
            return
        device_level = self.vip.rpc.call(
                'platform.actuator','get_point',
                'iiit/cbs/smarthub/' + endPoint).get(timeout=1)
        return float(device_level)
        
    def rpc_setShDeviceLevel(self, deviceId, level):
        if deviceId == SH_DEVICE_LED:
            endPoint = 'LEDPwmDuty'
        elif deviceId == SH_DEVICE_FAN:
            endPoint = 'FanPwmDuty'
        else :
            _log.exception ("not a valid device to change level, deviceId: " + str(deviceId))
            return
        result = self.vip.rpc.call(
                'platform.actuator', 
                'set_point',
                self._agent_id, 
                'iiit/cbs/smarthub/' + endPoint,
                level).get(timeout=1)
        #print("Set result", result)
        #_log.debug('OK call updateShDeviceLevel()')
        self.updateShDeviceLevel(deviceId, endPoint,level)
        return

    def updateShDeviceLevel(self, deviceId, endPoint, level):
        #_log.debug('updateShDeviceLevel()')
        
        device_level = self.rpc_getShDeviceLevel(deviceId)
        #check if the level really updated at the h/w, only then proceed with new level
        if level == device_level:
            self._shDevicesLevel[deviceId] = level
            self.publishShDeviceLevel(deviceId, level)
            
        _log.debug('Current level, ' + endPoint + ': ' + "{0:0.4f}".format( device_level))
            
        return

    def publishShDeviceLevel(self, deviceId, level):
        if deviceId == SH_DEVICE_LED:
            pubTopic = self.ledLevel_point
        elif deviceId == SH_DEVICE_FAN:
            pubTopic = self.fanLevel_point
        else :
            _log.exception ("not a valid device to change level, deviceId: " + str(deviceId))
            return

        pubMsg = [level,{'units': 'duty', 'tz': 'UTC', 'type': 'float'}]
        self.publishToBus(pubTopic, pubMsg)
        
        return
                
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

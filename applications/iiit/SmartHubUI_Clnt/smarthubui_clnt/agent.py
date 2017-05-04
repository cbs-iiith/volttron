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

import time

import requests
import json

SH_DEVICE_LED_DEBUG = 0
SH_DEVICE_LED = 1
SH_DEVICE_FAN = 2
SH_DEVICE_FAN_SWING = 3
SH_DEVICE_S_LUX = 4
SH_DEVICE_S_RH = 5
SH_DEVICE_S_TEMP = 6
SH_DEVICE_S_CO2 = 7
SH_DEVICE_S_PIR = 8

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


def smarthubui_clnt(config_path, **kwargs):

    config = utils.load_config(config_path)
    agent_id = config['agentid']
    
    class SmartHubUI_Clnt(Agent):
        '''
        retrive the data from volttron and pushes it to the BLE UI Server
        '''

        def __init__(self, **kwargs):
            _log.debug('__init__()')
            super(SmartHubUI_Clnt, self).__init__(**kwargs)
            
            self._configGetPoints()
            
        @Core.receiver('onsetup')
        def setup(self, sender, **kwargs):
            _log.debug('setup()')
            _log.info(config['message'])
            self._agent_id = config['agentid']
            ble_ui_srv_address = config.get('ble_ui_server_address', '127.0.0.1')
            ble_ui_srv_port = config.get('ble_ui_server_port', 8081)
            self.url_root = 'http://' + ble_ui_srv_address + ':' + str(ble_ui_srv_port) + '/SmartHub'

        @Core.receiver('onstart')            
        def startup(self, sender, **kwargs):
            _log.debug('startup()')
            return

        @Core.receiver('onstop')
        def onstop(self, sender, **kwargs):
            _log.debug('onstop()')
            return
        
        def _configGetPoints(self):
            self.topic_price_point              = config.get('topic_price_point', \
                                                            'smarthub/pricepoint')
            self.topic_sensorsLevelAll_point    = config.get('sensorsLevelAll_point', \
                                                            'smarthub/sensors/all')
            self.topic_ledState_point           = config.get('ledState_point', \
                                                            'smarthub/ledstate')    
            self.topic_fanState_point           = config.get('fanState_point', \
                                                            'smarthub/fanstate')    
            self.topic_ledLevel_point           = config.get('ledLevel_point', \
                                                            'smarthub/ledlevel')    
            self.topic_fanLevel_point           = config.get('fanLevel_point', \
                                                            'smarthub/fanlevel')
            self.topic_ledThPP_point            = config.get('ledThPP_point', \
                                                            'smarthub/ledthpp')    
            self.topic_fanThPP_point            = config.get('fanThPP_point', \
                                                            'smarthub/fanthpp')
            return
            
        def _subscribeTopics(self):
            self.vip.pubsub.subscribe("pubsub", self.topic_price_point,\
                                                    self.on_match_currentPP)
            self.vip.pubsub.subscribe("pubsub", self.topic_sensorsLevelAll_point,\
                                                    self.on_match_sensorData)
            self.vip.pubsub.subscribe("pubsub", self.topic_ledState_point,\
                                                    self.on_match_ledState)
            self.vip.pubsub.subscribe("pubsub", self.topic_fanState_point,\
                                                    self.on_match_fanState)
            self.vip.pubsub.subscribe("pubsub", self.topic_ledLevel_point,\
                                                    self.on_match_ledLevel)
            self.vip.pubsub.subscribe("pubsub", self.topic_fanLevel_point,\
                                                    self.on_match_fanLevel)
            self.vip.pubsub.subscribe("pubsub", self.topic_ledThPP_point,\
                                                    self.on_match_ledThPP)
            self.vip.pubsub.subscribe("pubsub", self.topic_fanThPP_point,\
                                                    self.on_match_fanThPP)
            return
            
        def on_match_currentPP(self, peer, sender, bus,
                topic, headers, message):
            _log.debug('on_match_currentPP()')
            self.uiPostCurrentPricePoint(headers, message)
            
        def on_match_sensorData(self, peer, sender, bus,
                topic, headers, message):
            _log.debug('on_match_sensorData()')
            self.uiPostSensorData(headers, message)
            
        def on_match_ledState(self, peer, sender, bus,
                topic, headers, message):
            _log.debug('on_match_ledState()')
            self.uiPostLedState(headers, message)
            
        def on_match_fanState(self, peer, sender, bus,
                topic, headers, message):
            _log.debug('on_match_fanState()')
            self.uiPostFanState(headers, message)
            
        def on_match_ledLevel(self, peer, sender, bus,
                topic, headers, message):
            _log.debug('on_match_ledLevel()')
            self.uiPostLedLevel(headers, message)
            
        def on_match_fanLevel(self, peer, sender, bus,
                topic, headers, message):
            _log.debug('on_match_fanLevel()')
            self.uiPostFanLevel(headers, message)
            
        def on_match_ledThPP(self, peer, sender, bus,
                topic, headers, message):
            _log.debug('on_match_ledThPP()')
            self.uiPostLedThPP(headers, message)
            
        def on_match_fanThPP(self, peer, sender, bus,
                topic, headers, message):
            _log.debug('on_match_fanThPP()')
            self.uiPostFanThPP(headers, message)

        def uiPostCurrentPricePoint(self, headers, message):
            #json rpc to BLESmartHubSrv
            _log.debug('uiPostCurrentPricePoint()')
            pricePoint = message[0]
            self.do_rpc('currentPricePoint', {'pricePoint': pricePoint})

        def uiPostSensorData(self, headers, message) :
            _log.debug('uiPostSensorData()')
            luxLevel   = message[0]['luxlevel']
            rhLevel    = message[0]['rhlevel']
            tempLevel  = message[0]['templevel']
            co2Level   = message[0]['co2level']
            pirLevel   = message[0]['pirlevel']
            self.do_rpc('shSensorsData', {\
                                            'luxLevel': luxLevel, \
                                            'rhLevel':  rhLevel, \
                                            'tempLevel': tempLevel, \
                                            'co2Level': co2Level, \
                                            'pirLevel': pirLevel \
                                            })
            return
            
        def uiPostLedState(self, headers, message) :
            _log.debug('uiPostLedState()')
            state = message[0]
            self.do_rpc('shDeviceState', {'deviceId': SH_DEVICE_LED,
                                            'state': state})
            return
        def uiPostFanState(self, headers, message) :
            _log.debug('uiPostFanState()')
            state = message[0]
            self.do_rpc('shDeviceState', {'deviceId': SH_DEVICE_FAN,
                                            'state': state})
            return
        def uiPostLedLevel(self, headers, message) :
            _log.debug('uiPostLedLevel()')
            level = message[0]
            self.do_rpc('shDeviceLevel', {'deviceId': SH_DEVICE_LED,
                                            'level': level})
            return
        def uiPostFanLevel(self, headers, message) :
            _log.debug('uiPostFanLevel()')
            level = message[0]
            self.do_rpc('shDeviceLevel', {'deviceId': SH_DEVICE_FAN,
                                            'level': level})
            return
        def uiPostLedThPP(self, headers, message) :
            _log.debug('uiPostLedThPP()')
            thPP = message[0]
            self.do_rpc('shDeviceThPP', {'deviceId': SH_DEVICE_LED,
                                            'thPP': thPP})
            return
        def uiPostFanThPP(self, headers, message) :
            _log.debug('uiPostFanThPP()')
            thPP = message[0]
            self.do_rpc('shDeviceThPP', {'deviceId': SH_DEVICE_FAN,
                                            'thPP': thPP})
            return
            
        def do_rpc(self, method, params=None ):
            json_package = {
                'jsonrpc': '2.0',
                'id': self._agent_id,
                'method':method,
            }

            if params:
                json_package['params'] = params

            data = json.dumps(json_package)
            try:
                response = requests.post(self.url_root, data=json.dumps(json_package), timeout=10)
                
                if response.ok:
                    success = response.json()['result']
                    if success:
                        _log.debug('response - ok, {} result:{}'.format(method, success))
                    else:
                        _log.debug('respone - not ok, {} result:{}'.format(method, success))
                else :
                    _log.debug('no respone, {} result: {}'.format(method, response))
            except Exception as e:
                #print (e)
                _log.warning('do_rpc() unhandled exception, most likely server is down')
                return
                
    Agent.__name__ = 'SmartHubUI_Clnt_Agent'
    return SmartHubUI_Clnt(**kwargs)


def main(argv=sys.argv):
    '''Main method called by the eggsecutable.'''
    try:
        utils.vip_main(smarthubui_clnt)
    except Exception as e:
        print e
        _log.exception('unhandled exception')

if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv))
    except KeyboardInterrupt:
        pass

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
import dateutil
import logging
import sys
import uuid

from volttron.platform.vip.agent import Agent, Core, PubSub, compat, RPC
from volttron.platform.agent import utils
from volttron.platform.messaging import topics, headers as headers_mod

import time
import json

from ispace_utils import do_rpc
from ispace_msg import MessageType
from ispace_msg_utils import check_msg_type, valid_bustopic_msg



utils.setup_logging()
_log = logging.getLogger(__name__)
__version__ = '0.4'

SH_DEVICE_LED_DEBUG = 0
SH_DEVICE_LED = 1
SH_DEVICE_FAN = 2
SH_DEVICE_FAN_SWING = 3
SH_DEVICE_S_LUX = 4
SH_DEVICE_S_RH = 5
SH_DEVICE_S_TEMP = 6
SH_DEVICE_S_CO2 = 7
SH_DEVICE_S_PIR = 8

def smarthubui_clnt(config_path, **kwargs):
    config = utils.load_config(config_path)
    
    Agent.__name__ = 'SmartHubUI_Clnt_Agent'
    return SmartHubUI_Clnt(config_path, **kwargs)
    
    
class SmartHubUI_Clnt(Agent):
    '''
    retrive the data from volttron and post(jsonrpc) it to the BLE UI Server
    '''
    def __init__(self, config_path, **kwargs):
        _log.debug('__init__()')
        super(SmartHubUI_Clnt, self).__init__(**kwargs)
        
        self.config = utils.load_config(config_path)
        self._config_get_points()
        return
        
    @Core.receiver('onsetup')
    def setup(self, sender, **kwargs):
        _log.info(self.config['message'])
        self._agent_id = self.config['agentid']
        
        ble_ui_srv_address = self.config.get('ble_ui_server_address', '127.0.0.1')
        ble_ui_srv_port = self.config.get('ble_ui_server_port', 8081)
        self._url_root = 'http://' + ble_ui_srv_address + ':' + str(ble_ui_srv_port) + '/smarthub'
        _log.debug('ble server url root: {}'.format(self._url_root))
        return
        
    @Core.receiver('onstart')
    def startup(self, sender, **kwargs):
        _log.debug('startup()')
        self._valid_senders_list_pp = ['iiit.pricecontroller']
        
        self._subscribe_topics()
        _log.debug('startup() - Done. Agent is ready')
        return
        
    @Core.receiver('onstop')
    def onstop(self, sender, **kwargs):
        _log.debug('onstop()')
        return
        
    def _config_get_points(self):
        self.topic_price_point = self.config.get('topic_price_point', 'smarthub/pricepoint')
        self.topic_sensors = self.config.get('sensorsLevelAll_point', 'smarthub/sensors/all')
        self.topic_led_state = self.config.get('ledState_point', 'smarthub/ledstate')
        self.topic_fan_state = self.config.get('fanState_point', 'smarthub/fanstate')
        self.topic_led_level = self.config.get('ledLevel_point', 'smarthub/ledlevel')
        self.topic_fan_level = self.config.get('fanLevel_point', 'smarthub/fanlevel')
        self.topic_led_th_pp = self.config.get('ledThPP_point', 'smarthub/ledthpp')
        self.topic_fan_th_pp = self.config.get('fanThPP_point', 'smarthub/fanthpp')
        return
        
    def _subscribe_topics(self):
        self.vip.pubsub.subscribe("pubsub", self.topic_price_point, self.on_match_current_pp)
        self.vip.pubsub.subscribe("pubsub", self.topic_sensors, self.on_match_sensors_data)
        self.vip.pubsub.subscribe("pubsub", self.topic_led_state, self.on_match_led_state)
        self.vip.pubsub.subscribe("pubsub", self.topic_fan_state, self.on_match_fan_state)
        self.vip.pubsub.subscribe("pubsub", self.topic_led_level, self.on_match_led_level)
        self.vip.pubsub.subscribe("pubsub", self.topic_fan_level, self.on_match_fan_level)
        self.vip.pubsub.subscribe("pubsub", self.topic_led_th_pp, self.on_match_led_th_pp)
        self.vip.pubsub.subscribe("pubsub", self.topic_fan_th_pp, self.on_match_fan_th_pp)
        return
        
    def on_match_current_pp(self, peer, sender, bus, topic, headers, message):
        _log.debug('on_match_current_pp()')
        if sender not in self._valid_senders_list_pp: return
        # check message type before parsing
        if not check_msg_type(message, MessageType.price_point): return False
        self._rpc_current_pricepoint(sender, headers, message)
        
    def on_match_sensors_data(self, peer, sender, bus, topic, headers, message):
        _log.debug('on_match_sensors_data()')
        self._rpc_sensors_data(sender, headers, message)
        return
        
    def on_match_led_state(self, peer, sender, bus, topic, headers, message):
        _log.debug('on_match_led_state()')
        self._rpc_led_state(sender, headers, message)
        return
        
    def on_match_fan_state(self, peer, sender, bus, topic, headers, message):
        _log.debug('on_match_fan_state()')
        self._rpc_fan_state(sender, headers, message)
        return
        
    def on_match_led_level(self, peer, sender, bus, topic, headers, message):
        _log.debug('on_match_led_level()')
        self._rpc_led_level(sender, headers, message)
        return
        
    def on_match_fan_level(self, peer, sender, bus, topic, headers, message):
        _log.debug('on_match_fan_level()')
        self._rpc_fan_level(sender, headers, message)
        return
        
    def on_match_led_th_pp(self, peer, sender, bus, topic, headers, message):
        _log.debug('on_match_led_th_pp()')
        self._rpc_led_th_pp(sender, headers, message)
        return
        
    def on_match_fan_th_pp(self, peer, sender, bus, topic, headers, message):
        _log.debug('on_match_fan_th_pp()')
        self._rpc_fan_th_pp(sender, headers, message)
        return
        
    def _rpc_current_pricepoint(self, sender, headers, message):
        #json rpc to BLESmartHubSrv
        _log.debug('_rpc_current_pricepoint()')
        valid_senders_list = self._valid_senders_list_pp
        minimum_fields = ['msg_type', 'value', 'value_data_type', 'units', 'price_id']
        validate_fields = ['value', 'units', 'price_id', 'isoptimal', 'duration', 'ttl']
        valid_price_ids = []
        (success, pp_msg) = valid_bustopic_msg(sender, valid_senders_list
                                                , minimum_fields
                                                , validate_fields
                                                , valid_price_ids
                                                , message)
        if not success or pp_msg is None: return
        if not pp_msg.get_isoptimal(): return

        current_pp = pp_msg.get_value()
        do_rpc(self._agent_id, self._url_root
                    , 'current-price', {'value': current_pp}
                    , 'POST')
        return
        
    def _rpc_sensors_data(self, sender, headers, message):
        _log.debug('_rpc_sensors_data()')
        lux = message[0]['luxlevel']
        rh = message[0]['rhlevel']
        temp = message[0]['templevel']
        co2 = message[0]['co2level']
        pir = message[0]['pirlevel']
        do_rpc(self._agent_id, self._url_root
                    , 'sensors', {'lux': lux, 'rh':  rh, 'temp': temp, 'co2': co2, 'pir': pir}
                    , 'POST')
        return
        
    def _rpc_led_state(self, sender, headers, message):
        _log.debug('_rpc_led_state()')
        state = message[0]
        do_rpc(self._agent_id, self._url_root
                    , 'state', {'id': SH_DEVICE_LED, 'value': state}
                    , 'POST')
        return
        
    def _rpc_fan_state(self, sender, headers, message):
        _log.debug('_rpc_fan_state()')
        state = message[0]
        do_rpc(self._agent_id, self._url_root
                    , 'state', {'id': SH_DEVICE_FAN, 'value': state}
                    , 'POST')
        return
        
    def _rpc_led_level(self, sender, headers, message):
        _log.debug('_rpc_led_level()')
        level = message[0]
        do_rpc(self._agent_id, self._url_root
                    , 'level', {'id': SH_DEVICE_LED, 'value': level}
                    , 'POST')
        return
        
    def _rpc_fan_level(self, sender, headers, message):
        _log.debug('_rpc_fan_level()')
        level = message[0]
        do_rpc(self._agent_id, self._url_root
                    , 'level', {'id': SH_DEVICE_FAN, 'value': level}
                    , 'POST')
        return
        
    def _rpc_led_th_pp(self, sender, headers, message):
        _log.debug('_rpc_led_th_pp()')
        th_pp = message[0]
        do_rpc(self._agent_id, self._url_root
                    , 'threshold-price', {'id': SH_DEVICE_LED, 'value': th_pp}
                    , 'POST')
        return
        
    def _rpc_fan_th_pp(self, sender, headers, message):
        _log.debug('_rpc_fan_th_pp()')
        th_pp = message[0]
        do_rpc(self._agent_id, self._url_root
                    , 'threshold-price', {'id': SH_DEVICE_FAN, 'value': th_pp}
                    , 'POST')
        return
        
        
def main(argv=sys.argv):
    '''Main method called by the eggsecutable.'''
    try:
        utils.vip_main(smarthubui_clnt)
    except Exception as e:
        print (e)
        _log.exception('unhandled exception')
        
        
if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv))
    except KeyboardInterrupt:
        pass
        
        
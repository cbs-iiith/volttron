# -*- coding: utf-8 -*- {{{
# vim: set fenc=utf-8 ft=python sw=4 ts=4 sts=4 et:


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


def smartstripui_clnt(config_path, **kwargs):

    config = utils.load_config(config_path)
    agent_id = config['agentid']
    
    ble_ui_server_address = config.get('ble_ui_server_address', '127.0.0.1')
    ble_ui_server_port = int(config.get('ble_ui_server_port', 8081))
    
    PLUG_ID_1 = 0
    PLUG_ID_2 = 1

    topic_price_point = config.get('topic_price_point',
            'prices/PricePoint')
    plug1_meterData_all_point = config.get('plug1_meterData_all_point',
            'smartstrip/plug1/meterdata/all')
    plug2_meterData_all_point = config.get('plug2_meterData_all_point',
            'smartstrip/plug2/meterdata/all')
    plug1_relayState_point = config.get('plug1_relayState_point',
            'smartstrip/plug1/relaystate')
    plug2_relayState_point = config.get('plug2_relayState_point',
            'smartstrip/plug2/relaystate')
    plug1_thresholdPP_point = config.get('plug1_thresholdPP_point',
            'smartstrip/plug1/threshold')
    plug2_thresholdPP_point = config.get('plug2_thresholdPP_point',
            'smartstrip/plug2/threshold')
    plug1_tagId_point = config.get('plug1_tagId_point',
            'smartstrip/plug1/tagid')
    plug2_tagId_point = config.get('plug2_thresholdPP_point',
            'smartstrip/plug2/tagid')

    class SmartStripUI_Clnt(Agent):
        '''
        retrive the data from volttron and pushes it to the BLE UI Server
        '''

        def __init__(self, **kwargs):
            _log.debug('__init__()')
            super(SmartStripUI_Clnt, self).__init__(**kwargs)
            
        @Core.receiver('onsetup')
        def setup(self, sender, **kwargs):
            _log.debug('setup()')
            _log.info(config['message'])
            self._agent_id = config['agentid']
            ble_ui_srv_address = config.get('ble_ui_server_address', '127.0.0.1')
            ble_ui_srv_port = config.get('ble_ui_server_port', 8081)
            self.url_root = 'http://' + ble_ui_srv_address + ':' + str(ble_ui_srv_port) + '/SmartStrip'

        @Core.receiver('onstart')            
        def startup(self, sender, **kwargs):
            _log.debug('startup()')
            return

        @Core.receiver('onstop')
        def onstop(self, sender, **kwargs):
            _log.debug('onstop()')
            return

        @PubSub.subscribe('pubsub', topic_price_point)
        def on_match_currentPP(self, peer, sender, bus,
                topic, headers, message):
            _log.debug('on_match_currentPP()')
            self.uiPostCurrentPricePoint(headers, message)

        @PubSub.subscribe('pubsub', plug1_meterData_all_point)
        def on_match_plug1MeterData(self, peer, sender, bus, 
                topic, headers, message):
            _log.debug('on_match_plug1MeterData()')
            self.uiPostMeterData(PLUG_ID_1, headers, message)

        @PubSub.subscribe('pubsub', plug2_meterData_all_point)
        def on_match_plug2MeterData(self, peer, sender, bus,
                topic, headers, message):
            _log.debug('on_match_plug2MeterData()')
            self.uiPostMeterData(PLUG_ID_2, headers, message)

        @PubSub.subscribe('pubsub', plug1_relayState_point)
        def on_match_plug1RelayState(self, peer, sender, bus,
                topic, headers, message):
            self.uiPostRelayState(PLUG_ID_1, headers, message)

        @PubSub.subscribe('pubsub', plug2_relayState_point)
        def on_match_plug2RelayState(self, peer, sender, bus,
                topic, headers, message):
            self.uiPostRelayState(PLUG_ID_2, headers, message)

        @PubSub.subscribe('pubsub', plug1_thresholdPP_point)
        def on_match_plug1Threshold(self, peer, sender, bus,
                topic, headers, message):
            self.uiPostThreshold(PLUG_ID_1, headers, message)

        @PubSub.subscribe('pubsub', plug2_thresholdPP_point)
        def on_match_plug2Threshold(self, peer, sender, bus,
                topic, headers, message):
            self.uiPostThreshold(PLUG_ID_2, headers, message)
        
        @PubSub.subscribe('pubsub', plug1_tagId_point)
        def on_match_plug1TagID(self, peer, sender, bus,
                topic, headers, message):
            self.uiPostTagID(PLUG_ID_1, headers, message)
        
        @PubSub.subscribe('pubsub', plug2_tagId_point)
        def on_match_plug2TagID(self, peer, sender, bus,
                topic, headers, message):
            self.uiPostTagID(PLUG_ID_2, headers, message)

        def uiPostCurrentPricePoint(self, headers, message):
            #json rpc to BLESmartStripSrv
            _log.debug('uiPostCurrentPricePoint()')
            pricePoint = message[0]
            #nodejs jsonrpc-2 takes args as set and json cannot serialize sets - TypeError
            self.do_rpc('currentPricePoint', {pricePoint})

        def uiPostMeterData(self, plugID, headers, message):
            #json rpc to BLESmartStripSrv
            _log.debug('uiPostMeterData()')
            volt = message[0]['voltage']
            curr = message[0]['current']
            aPwr = message[0]['active_power']
            #nodejs jsonrpc-2 takes args as set and json cannot serialize sets - TypeError
            self.do_rpc('plugMeterData', {plugID, volt, curr, aPwr})

        def uiPostRelayState(self, plugID, headers, message):
            #json rpc to BLESmartStripSrv
            _log.debug('uiPostRelayState()')
            state = message[0]
            #nodejs jsonrpc-2 takes args as set and json cannot serialize sets - TypeError
            self.do_rpc('plugRelayState', {plugID, state})

        def uiPostThreshold(self, plugID, headers, message):
            #json rpc to BLESmartStripSrv
            _log.debug('uiPostThreshold()')
            thresholdPP = message[0]
            #nodejs jsonrpc-2 takes args as set and json cannot serialize sets - TypeError
            self.do_rpc('plugThPricePoint', {plugID, thresholdPP})
                
        def uiPostTagID(self, plugID, headers, message):
            #json rpc to BLESmartStripSrv
            _log.debug('uiPostTagID()')
            tagID = message[0]
            #nodejs jsonrpc-2 takes args as set and json cannot serialize sets - TypeError
            self.do_rpc('plugTagID', {plugID, tagID})
                
        def do_rpc(self, method, params=None ):
            json_package = {
                'jsonrpc': '2.0',
                'id': self._agent_id,
                'method':method,
            }

            if params:
                #nodejs jsonrpc-2 takes args as set and json cannot serialize sets - TypeError
                json_package['params'] = list(params)

            data = json.dumps(json_package)
            try:
                response = requests.post(self.url_root, data=json.dumps(json_package))
                
                if response.ok:
                    log_debug('response - ok, {} result:{}'.format(method, response.json()['result']))
                else:
                    log_debug('respone - not ok, {}'.format(method))
            except Exception as e:
                #print (e)
                _log.exception('do_rpc() unhandled exception, most likely server is down')
                return
                
    Agent.__name__ = 'SmartStripUI_Clnt_Agent'
    return SmartStripUI_Clnt(**kwargs)


def main(argv=sys.argv):
    '''Main method called by the eggsecutable.'''
    try:
        utils.vip_main(smartstripui_clnt)
    except Exception as e:
        print e
        _log.exception('unhandled exception')

if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv))
    except KeyboardInterrupt:
        pass

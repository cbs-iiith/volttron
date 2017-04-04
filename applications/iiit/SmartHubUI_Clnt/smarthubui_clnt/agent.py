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
    
    ble_ui_server_address = config.get('ble_ui_server_address', '127.0.0.1')
    ble_ui_server_port = int(config.get('ble_ui_server_port', 8082))
    
    topic_price_point = config.get('topic_price_point',
            'prices/PricePoint')

    class SmartHubUI_Clnt(Agent):
        '''
        retrive the data from volttron and pushes it to the BLE UI Server
        '''

        def __init__(self, **kwargs):
            _log.debug('__init__()')
            super(SmartHubUI_Clnt, self).__init__(**kwargs)
            
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

        @PubSub.subscribe('pubsub', topic_price_point)
        def on_match_currentPP(self, peer, sender, bus,
                topic, headers, message):
            _log.debug('on_match_currentPP()')
            self.uiPostCurrentPricePoint(headers, message)

        def uiPostCurrentPricePoint(self, headers, message):
            #json rpc to BLESmartHubSrv
            _log.debug('uiPostCurrentPricePoint()')
            pricePoint = message[0]
            self.do_rpc('currentPricePoint', {'pricePoint': pricePoint})
                
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
                response = requests.post(self.url_root, data=json.dumps(json_package))
                
                if response.ok:
                    _log.debug('response - ok, {} result:{}'.format(method, response.json()['result']))
                else:
                    _log.debug('respone - not ok, {}'.format(method))
            except Exception as e:
                #print (e)
                _log.exception('do_rpc() unhandled exception, most likely server is down')
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

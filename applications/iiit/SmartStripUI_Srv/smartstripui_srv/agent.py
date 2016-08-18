# -*- coding: utf-8 -*- {{{
# vim: set fenc=utf-8 ft=python sw=4 ts=4 sts=4 et:


import datetime
import logging
import sys
import uuid
import socket

from volttron.platform.vip.agent import Agent, Core, PubSub, compat, RPC
from volttron.platform.agent import BaseAgent, PublishMixin
from volttron.platform.agent import utils
from volttron.platform.messaging import headers as headers_mod

from volttron.platform.messaging import topics, headers as headers_mod

import time
import struct

from zmq.utils import jsonapi
from volttron.platform import jsonrpc
from volttron.platform.jsonrpc import (
    INVALID_REQUEST, METHOD_NOT_FOUND,
    UNHANDLED_EXCEPTION, UNAUTHORIZED,
    UNABLE_TO_REGISTER_INSTANCE, DISCOVERY_ERROR,
    UNABLE_TO_UNREGISTER_INSTANCE, UNAVAILABLE_PLATFORM, INVALID_PARAMS,
    UNAVAILABLE_AGENT)

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


def smartstripui_srv(config_path, **kwargs):

    config = utils.load_config(config_path)
    
    vip_identity = config.get('vip_identity', 'iiit.ssui_srv')
    # This agent needs to be named platform.actuator. Pop the uuid id off the kwargs
    kwargs.pop('identity', None)

    Agent.__name__ = 'SmartStripUI_Srv_Agent'
    return SmartStripUI_Srv(config_path, identity=vip_identity, **kwargs)
    
class SmartStripUI_Srv(PublishMixin, Agent):
    '''
    Volttron Server - listens for connections from UI Layer/Apps 
    and publishes the request to Volttron Bus
    '''
    def __init__(self, config_path, **kwargs):
        _log.debug('__init__()')
        super(SmartStripUI_Srv, self).__init__(**kwargs)
        _log.debug("vip_identity: " + self.core.identity)
        
        self.config = utils.load_config(config_path)
        self.agent_id = self.config['agentid']
        self.server_address = self.config.get('server_address', '127.0.0.1')
        self.server_port = int(self.config.get('server_port', 7575))
        self.backlog = int(self.config.get('backlog', 10))

        self.ssui_socket = None
        self.state = None
        
    def setup(self):
        _log.debug('setup()')
        _log.info(self.config['message'])
        self._agent_id = self.config['agentid']
        
        '''Perform additional setup.'''
        super(SmartStripUI_Srv, self).setup()

        # Open a socket to listen for incoming connections
        self.ssui_socket = sock = socket.socket()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(tuple([self.server_address, self.server_port]))
        sock.listen(self.backlog)

        # Register a callback to accept new connections
        self.reactor.register(self.ssui_socket, self.handle_accept)
        
    def handle_accept(self, ssui_sock):
        _log.debug('handle_accept()')
        '''Accept new connections.'''
        sock, addr = ssui_sock.accept()
        file = sock.makefile('r+', 0)
        _log.info('Connection {} accepted from {}:{}'.format(file.fileno(),
            *addr))
        try:
            file.write('hi from UI srv')
        except socket.error:
            _log.info('Connection {} disconnected'.format(file.fileno()))
        # Register a callback to recieve input from the client.
        self.reactor.register(file, self.handle_input)

    def handle_input(self, file):
        _log.debug('handle_input()')
        '''Recieve the data from the ble ui server'''
        try:
            response = file.readline()
            if not response:
                raise socket.error('disconnected')
            self.processResponse(response)
        except socket.error:
            _log.info('Connection {} disconnected'.format(file.fileno()))
            self.reactor.unregister(file)

    def processResponse(self, response):
        _log.debug('processResponse()')
        #response = response.strip()
        #print(response)
        try:
            
            rpcdata = jsonrpc.JsonRpcData.parse(response)
            _log.info('rpc method: {}'.format(rpcdata.method))
            
            if rpcdata.method == "rpc_changeThresholdPP":
                args = {'plugID': rpcdata.params['plugID'],
                        'newThreshold': rpcdata.params['newThreshold']}
                result = self.rpc_changeThresholdPP(**args)
            elif rpcdata.method == "rpc_changeCurrentPP":
                _log.info('newPricePoint: {}'.format(rpcdata.params['newPricePoint']))
                args = {'newPricePoint': rpcdata.params['newPricePoint']}
                result = self.rpc_changeCurrentPP(**args)
                
            return jsonrpc.json_result(rpcdata.id, result)
                
        except AssertionError:
            print('AssertionError')
            return jsonrpc.json_error(
                'NA', INVALID_REQUEST, 'Invalid rpc data {}'.format(data))
        except Exception as e:
            print(e)
            return jsonrpc.json_error(
                'NA', UNHANDLED_EXCEPTION, e
            )

        #rpcdict = data.json()
        #print('RPCDICT', rpcdict)
        #if response:
            #parse response
            #if cmd==postData
                #post to volttron bus - topic UI/Requests
                #file.write('OK')
                
    def rpc_changeThresholdPP(self, plugID, newThreshold):
        try:
            result = self.vip.rpc.call('iiit.smartstrip', 'setThresholdPP',
                                        plugID, newThreshold).get(timeout=1)
        except Exception as e:
            _log.error ("Could not contact iiit.smartstrip. Is it running?")
            print(e)
            return 'FAILED'
        return 'SUCCESS'

    def rpc_changeCurrentPP(self, newPricePoint):
        try:
            result = self.vip.rpc.call('iiit.pricepoint', 'price_from_net', newPricePoint).get(timeout=1)
        except Exception as e:
            _log.error ("Could not contact iiit.pricepoint. Is it running?")
            print(e)
            return 'FAILED'
        return 'SUCCESS'
        



def main(argv=sys.argv):
    '''Main method called by the eggsecutable.'''
    try:
        utils.vip_main(smartstripui_srv)
    except Exception as e:
        print e
        _log.exception('unhandled exception')

if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        pass

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
    agent_id = config['agentid']
    server_address = config.get('server_address', '127.0.0.1')
    server_port = int(config.get('server_port', 7575))
    backlog = int(config.get('backlog', 10))

    
    class SmartStripUI_Srv(PublishMixin, BaseAgent):
        '''
        Volttron Server - listens for connections from UI Layer/Apps 
        and publishes the request to Volttron Bus
        '''
        def __init__(self, config_path, **kwargs):
            _log.debug('__init__()')
            super(SmartStripUI_Srv, self).__init__(**kwargs)

            self.ssui_socket = None
            self.state = None

        def setup(self):
            _log.debug('setup()')
            _log.info(config['message'])
            self._agent_id = config['agentid']
            
            '''Perform additional setup.'''
            super(SmartStripUI_Srv, self).setup()

            # Open a socket to listen for incoming connections
            self.ssui_socket = sock = socket.socket()
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(tuple([server_address, server_port]))
            sock.listen(backlog)

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
            response = response.strip()
            #if response:
                #parse response
                #if cmd==postData
                    #post to volttron bus - topic UI/Requests
                    #file.write('OK')

    Agent.__name__ = 'SmartStripUI_Srv_Agent'
    return SmartStripUI_Srv(config_path, **kwargs)


def main(argv=sys.argv):
    '''Main method called by the eggsecutable.'''
    try:
        utils.default_main(smartstripui_srv,
            description='VOLTTRON platform™ server agent for to receive UI request.',
            argv=argv)
    except Exception as e:
        print e
        _log.exception('unhandled exception')

if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        pass

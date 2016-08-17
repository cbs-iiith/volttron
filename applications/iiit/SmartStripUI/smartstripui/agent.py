# -*- coding: utf-8 -*- {{{
# vim: set fenc=utf-8 ft=python sw=4 ts=4 sts=4 et:


import logging
import socket
import sys

from volttron.platform.agent import BaseAgent, PublishMixin
from volttron.platform.agent import utils

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


def smartstripui(config_path, **kwargs):

    config = utils.load_config(config_path)
    agent_id = config['agentid']

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

    class SmartStripUI(PublishMixin, BaseAgent):

        def __init__(self, **kwargs):
            _log.debug('__init__()')
            super(SmartStripUI, self).__init__(**kwargs)
            self.ssui_socket = None
            self.state = None

        @Core.receiver('onsetup')
        def setup(self, sender, **kwargs):
            _log.debug('setup()')
            _log.info(config['message'])
            self._agent_id = config['agentid']
            '''Perform additional setup.'''
            super(SmartStripUI, self).setup()

            # Open a socket to listen for incoming connections
            self.ssui_socket = sock = socket.socket()
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(tuple(self.config['address']))
            sock.listen(int(self.config['backlog']))

            # Register a callback to accept new connections
            self.reactor.register(self.ssui_socket, self.handle_accept)

        @Core.receiver('onstart')            
        def startup(self, sender, **kwargs):
            _log.debug('startup()')
            #self.core.periodic(period_read_price_point, self.update_price_point, wait=None)


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

        @PubSub.subscribe('pubsub', topic_price_point)
        def on_match_currentPP(self, peer, sender, bus,
                topic, headers, message):
            self.uiPostCurrentPricePoint(headers, message)

        @PubSub.subscribe('pubsub', plug1_meterData_all_point)
        def on_match_plug1MeterData(self, peer, sender, bus, 
                topic, headers, message):
            self.uiPostMeterData(PLUG_ID_1, headers, message)

        @PubSub.subscribe('pubsub', plug2_meterData_all_point)
        def on_match_plug2MeterData(self, peer, sender, bus,
                topic, headers, message):
            self.uiPostMeterData(PLUG_ID_2, headers, message)

        @PubSub.subscribe('pubsub', plug1_relayState_point)
        def on_match_plug1MeterData(self, peer, sender, bus,
                topic, headers, message):
            self.uiPostRelayState(PLUG_ID_1, headers, message)

        @PubSub.subscribe('pubsub', plug2_relayState_point)
        def on_match_plug2MeterData(self, peer, sender, bus,
                topic, headers, message):
            self.uiPostRelayState(PLUG_ID_2, headers, message)

        @PubSub.subscribe('pubsub', plug1_thresholdPP_point)
        def on_match_plug1Threshold(self, peer, sender, bus,
                topic, headers, message):
            self.uiPostThreshold(PLUG_ID_1, headers, message)

        @PubSub.subscribe('pubsub', plug2_thresholdPP_point)
        def on_match_plug2Threshold(self, peer, sender, bus,
                topic, headers, message):
            self.uiPostThreshold(self, PLUG_ID_2, headers, message)

        def uiPostCurrentPricePoint(self, headers, message):
            #json rpc to BLESmartStripSrv
            _log.debug('uiPostCurrentPricePoint()')

        def uiPostMeterData(self, plugId, headers, message):
            #json rpc to BLESmartStripSrv
            _log.debug('uiPostCurrentPricePoint()')

        def uiPostRelayState(self, plugId, headers, message):
            #json rpc to BLESmartStripSrv
            _log.debug('uiPostCurrentPricePoint()')

        def uiPostThreshold(self, plugId, headers, message):
            #json rpc to BLESmartStripSrv
            _log.debug('uiPostCurrentPricePoint()')

    Agent.__name__ = 'SmartStripUI_Agent'
    return SmartStripUI(**kwargs)


def main(argv=sys.argv):
    '''Main method called by the eggsecutable.'''
    try:
        utils.vip_main(smartstripui)
    except Exception as e:
        print e
        _log.exception('unhandled exception')

if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        pass

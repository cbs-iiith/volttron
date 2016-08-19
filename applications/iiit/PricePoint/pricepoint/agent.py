# -*- coding: utf-8 -*- {{{
# vim: set fenc=utf-8 ft=python sw=4 ts=4 sts=4 et:


import datetime
import logging
import sys
import uuid
import random

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


def pricepoint(config_path, **kwargs):

    config = utils.load_config(config_path)
    agentid = config['agentid']
    message = config['message']
    topic_price_point= config.get('topic_price_point', 'prices/PricePoint')
    period_read_price_point = config['period_read_price_point']
    default_base_price = config['default_base_price']
    min_price = config.get("min_price", 0.01)
    max_price = config.get("max_price", 1.1)

    pointPricePoint = 'iiit/cbs/smartstrip/PricePoint'

    vip_identity = config.get('vip_identity', 'iiit.pricepoint')
    # This agent needs to be named platform.actuator. Pop the uuid id off the kwargs
    kwargs.pop('identity', None)
    
    Agent.__name__ = 'PricePoint_Agent'
    return PricePoint(agentid, message, topic_price_point, period_read_price_point,
                    default_base_price, min_price, max_price, pointPricePoint,
                    identity=vip_identity, **kwargs)
    
class PricePoint(Agent):

    _price_point_previous = 0.4 

    def __init__(self, agentid, message, topic_price_point, period_read_price_point,
                default_base_price, min_price, max_price, pointPricePoint,
                **kwargs):
        super(PricePoint, self).__init__(**kwargs)
        _log.debug("vip_identity: " + self.core.identity)
        
        self._message = message
        self._agent_id = agentid
        self.topic_price_point = topic_price_point
        self.period_read_price_point = period_read_price_point
        self.default_base_price = default_base_price
        self.min_price = min_price
        self.max_price = max_price
        self.pointPricePoint = pointPricePoint

    @Core.receiver('onsetup')
    def setup(self, sender, **kwargs):
        _log.info(self._message)
        self.vip.rpc.export(self.rpc_from_net, 'rpc_from_net')

    @Core.receiver('onstart')            
    def startup(self, sender, **kwargs):
        #self.core.periodic(self.period_read_price_point, self.update_price_point, wait=None)
        self.vip.rpc.call(MASTER_WEB, 'register_agent_route',
                      r'^/PricePoint',
                      self.core.identity,
                      "rpc_from_net").get(timeout=30)    
        return

    def update_price_point(self):
        '''
        read the new price and publish it to the bus
        '''
        #_log.debug('update_price_point()')
        #self.fake_price_points()
        #self.price_from_net()
        self.price_from_smartstrip_bacnet()

    def fake_price_points(self):
        #Make a random price point
        _log.debug('fake_price_points()')
        new_price_reading = random.uniform(self.min_price, self.max_price)
        self.updatePricePoint(newPricePoint)
        
    @RPC.export
    def rpc_from_net(self, header, message):
        return self.processMessage(message)

    def processMessage(self, message):
        _log.debug('processResponse()')
        result = 'FAILED'
        try:
            rpcdata = jsonrpc.JsonRpcData.parse(message)
            _log.info('rpc method: {}'.format(rpcdata.method))
            
            if rpcdata.method == "rpc_updatePricePoint":
                args = {'newPricePoint': rpcdata.params['newPricePoint']}
                result = self.updatePricePoint(**args)
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
        
    def updatePricePoint(self, newPricePoint):
        if newPricePoint != self._price_point_previous :
            _log.debug('New Price Point: {0:.2f} !!!'.format(newPricePoint))
            self.post_price(newPricePoint)
            self._price_point_previous = newPricePoint
        else :
            _log.info('No change in price')
        return 'success'

    def price_from_smartstrip_bacnet(self):
        #_log.debug('price_from_smartstrip_bacnet()')
        result = []

        try: 
            start = str(datetime.datetime.now())
            end = str(datetime.datetime.now() 
                    + datetime.timedelta(milliseconds=100))

            msg = [
                    ['iiit/cbs/smartstrip',start,end]
                    ]
            result = self.vip.rpc.call(
                    'platform.actuator', 
                    'request_new_schedule',
                    agent_id, 
                    'TaskID_PricePoint',
                    'LOW',
                    msg).get(timeout=1)
        except Exception as e:
            _log.exception ("Could not contact actuator. Is it running?")
            #print(e)
            return
        try:
            #_log.debug('time...')
            if result['result'] == 'SUCCESS':
                new_price_reading = self.vip.rpc.call(
                        'platform.actuator','get_point',
                        'iiit/cbs/smartstrip/PricePoint').get(timeout=1)
                #_log.debug('...time')
                self.updatePricePoint(newPricePoint)
        except Exception as e:
            _log.exception ("Exception: reading price point")
            #print(e)
            return

    def post_price(self, new_price):
        _log.debug('post_price()')
        #Create messages for specific points
        pricepoint_message = [new_price,{'units': 'F', 'tz': 'UTC', 'type': 'float'}]

        #Create timestamp
        #now = datetime.utcnow().isoformat(' ') + 'Z'
        now = str(datetime.datetime.now())
        headers = {
                headers_mod.DATE: now
                }

        _log.info('Publishing new price point: {0:.2f}'.format(new_price))
        #Publish messages            
        self.vip.pubsub.publish(
                'pubsub', self.topic_price_point, headers, pricepoint_message)
        #_log.debug('after pub')


def main(argv=sys.argv):
    '''Main method called by the eggsecutable.'''
    try:
        utils.vip_main(pricepoint)
    except Exception as e:
        print e
        _log.exception('unhandled exception')

if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv))
    except KeyboardInterrupt:
        pass

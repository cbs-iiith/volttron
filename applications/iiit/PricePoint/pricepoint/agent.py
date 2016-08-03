# -*- coding: utf-8 -*- {{{
# vim: set fenc=utf-8 ft=python sw=4 ts=4 sts=4 et:


import logging
import sys
import uuid
import random

from datetime import datetime
from volttron.platform.vip.agent import Agent, Core, PubSub, compat, RPC
from volttron.platform.agent import utils
from volttron.platform.messaging import headers as headers_mod

from volttron.platform.messaging import topics, headers as headers_mod

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
    agent_id = config['agentid']
    topic_price_point= config.get('topic_price_point', 'prices/PricePoint')
    period_read_price_point = config['period_read_price_point']
    default_base_price = config['default_base_price']
    min_price = config.get("min_price", 0.01)
    max_price = config.get("max_price", 1.1)

    class PricePoint(Agent):
        def __init__(self, **kwargs):
            super(PricePoint, self).__init__(**kwargs)			

        @Core.receiver('onsetup')
        def setup(self, sender, **kwargs):
            _log.info(config['message'])
            self._agent_id = config['agentid']

        @Core.receiver('onstart')            
        def startup(self, sender, **kwargs):
            self.core.periodic(period_read_price_point, self.update_fake_price_points, wait=None)
            #self.core.periodic(period_read_price_point, self.update_price_point, wait=None)

        def update_fake_price_points(self):
            #Make a random price point
            _log.debug('update_fake_price_points()')
            new_price_reading = random.uniform(min_price, max_price)
            self.post_price(new_price_reading)

        def update_price_point(self):
            '''
            read the new price from net and publish it to the bus
            '''
            new_price_reading = price_from_net()
            post_price(new_price_reading)
            _log.debug('update_price_point()')

        def price_from_net(self):
            _log.debug('price_from_net()')
            new_price_reading = default_base_price
            '''
            need to somehow get the price point from net
            '''
            return new_price_reading

        def post_price(self, new_price):
            _log.debug('post_price()')
            #Create messages for specific points
            pricepoint_message = [new_price,{'units': 'F', 'tz': 'UTC', 'type': 'float'}]

            #Create timestamp
            now = datetime.utcnow().isoformat(' ') + 'Z'
            headers = {
                    headers_mod.DATE: now
                    }

            #_log.debug('before pub')
            #Publish messages            
            self.vip.pubsub.publish(
                    'pubsub', topic_price_point, headers, pricepoint_message)
            #_log.debug('after pub')

    Agent.__name__ = 'PricePoint_Agent'
    return PricePoint(**kwargs)


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

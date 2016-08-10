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

    pointPricePoint = 'iiit/cbs/smartstrip/PricePoint'

    class PricePoint(Agent):
    
        _price_point_previous = 0.4 

        def __init__(self, **kwargs):
            super(PricePoint, self).__init__(**kwargs)			

        @Core.receiver('onsetup')
        def setup(self, sender, **kwargs):
            _log.info(config['message'])
            self._agent_id = config['agentid']

        @Core.receiver('onstart')            
        def startup(self, sender, **kwargs):
            self.core.periodic(period_read_price_point, self.update_price_point, wait=None)

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
            new_price_reading = random.uniform(min_price, max_price)
            self.post_price(new_price_reading)

        def price_from_net(self):
            _log.debug('price_from_net()')
            new_price_reading = default_base_price
            '''
            need to somehow get the new price point from net
            '''


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
                _log.error ("Could not contact actuator. Is it running?")
                print(e)
                pass
            try:
                #_log.debug('time...')
                if result['result'] == 'SUCCESS':
                    new_price_reading = self.vip.rpc.call(
                            'platform.actuator','get_point',
                            'iiit/cbs/smartstrip/PricePoint').get(timeout=1)
                    #_log.debug('...time')

                    #post the new price point the volttron bus
                    if new_price_reading != self._price_point_previous :
                        _log.debug('New Price Point: {0:.2f} !!!'.format(new_price_reading))
                        self.post_price(new_price_reading)
                        self._price_point_previous = new_price_reading
                    else :
                        _log.info('No change in price')
                        
            except Exception as e:
                _log.error ("Exception: reading price point")
                print(e)
                pass
            

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

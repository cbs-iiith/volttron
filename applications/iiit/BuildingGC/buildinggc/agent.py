# -*- coding: utf-8 -*- {{{
# vim: set fenc=utf-8 ft=python sw=4 ts=4 sts=4 et:
#
# Copyright (c) 2019, Sam Babu, Godithi.
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
import random

from volttron.platform.vip.agent import Agent, Core, PubSub, compat, RPC
from volttron.platform.agent import utils
from volttron.platform.messaging import headers as headers_mod

from volttron.platform.messaging import topics, headers as headers_mod

import time
import gevent
import gevent.event

utils.setup_logging()
_log = logging.getLogger(__name__)
__version__ = '0.2'

#checking if a floating point value is “numerically zero” by checking if it is lower than epsilon
EPSILON = 1e-03

def buildinggc(config_path, **kwargs):

    config = utils.load_config(config_path)
    agentid = config['agentid']
    message = config['message']

    class BuildingGC(Agent):

        def __init__(self, **kwargs):
            _log.debug('__init__()')
            super(BuildingGC, self).__init__(**kwargs)
            

        @Core.receiver('onsetup')
        def setup(self, sender, **kwargs):
            _log.info(config['message'])
            self._agent_id = config['agentid']
            
            #current grid price
            self._current_gd_pp = 0
            
            self.topic_price_point_us   = config.get('pricePoint_topic_us', 'us/pricepoint')
            self.topic_price_point      = config.get('pricePoint_topic', 'building/pricepoint')
            return

        @Core.receiver('onstart')            
        def startup(self, sender, **kwargs):
            _log.debug('startup()')
            #subscribing to topic_price_point_us
            self.vip.pubsub.subscribe("pubsub", self.topic_price_point_us, self.onNewPrice)
            return

        def onNewPrice(self, peer, sender, bus,  topic, headers, message):
            #new zone price point
            gd_pp = message[0]
            _log.debug ( "*** New Price Point: {0:.2f} ***".format(gd_pp))
            
            if self._isclose(self._current_gd_pp, gd_pp, EPSILON):
                _log.debug('no change in price, do nothing')
                return
                
            bd_pp = self._computeNewPrice(gd_pp)
            self._post_price(bd_pp)
            return

        def _computeNewPrice(self, new_price):
            _log.debug('_computeNewPrice()')
            #TODO: implement the algorithm to compute the new price
            #      based on predicted demand, etc.
            return new_price

        def _post_price(self, bd_pp):
            _log.debug('_post_price()')
            #post to bus
            pubTopic =  self.topic_price_point
            pubMsg = [bd_pp,{'units': 'cents', 'tz': 'UTC', 'type': 'float'}]
            _log.debug('publishing to local bus topic: ' + pubTopic)
            self._publishToBus(pubTopic, pubMsg)
            return
            
        def _publishToBus(self, pubTopic, pubMsg):
            #_log.debug('_publishToBus()')
            now = datetime.datetime.utcnow().isoformat(' ') + 'Z'
            headers = {headers_mod.DATE: now}
            #Publish messages
            try:
                self.vip.pubsub.publish('pubsub', pubTopic, headers, pubMsg).get(timeout=10)
            except gevent.Timeout:
                _log.warning("Expection: gevent.Timeout in _publishToBus()")
                return
            except Exception as e:
                _log.warning ("Expection: _publishToBus?")
                return
            return
            
        #refer to http://stackoverflow.com/questions/5595425/what-is-the-best-way-to-compare-floats-for-almost-equality-in-python
        #comparing floats is mess
        def _isclose(self, a, b, rel_tol=1e-09, abs_tol=0.0):
            return abs(a-b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)

    Agent.__name__ = 'BuildingGC_Agent'
    return BuildingGC(**kwargs)

def main(argv=sys.argv):
    '''Main method called by the eggsecutable.'''
    try:
        utils.vip_main(buildinggc)
    except Exception as e:
        print e
        _log.exception('unhandled exception')

if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv))
    except KeyboardInterrupt:
        pass

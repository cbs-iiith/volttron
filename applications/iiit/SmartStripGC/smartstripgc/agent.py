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

def smartstripgc(config_path, **kwargs):

    config = utils.load_config(config_path)
    agentid = config['agentid']
    message = config['message']

    class SmartStripGC(Agent):

        def __init__(self, **kwargs):
            _log.debug('__init__()')
            super(SmartStripGC, self).__init__(**kwargs)
            

        @Core.receiver('onsetup')
        def setup(self, sender, **kwargs):
            _log.info(config['message'])
            self._agent_id = config['agentid']
            
            self._current_pp_us = 0
            
            self._max_time_bid_ed       = int(config.get('max_time_bid_ed', 10))
            
            self.topic_bid_ed           = config.get("bid_ed_topic", "smartstrip/bid_energydemand")
            self.topic_bid_ed_ds        = config.get("bid_ed_topic_ds", "ds/bid_energydemand")
            self.topic_lm_us            = config.get("lm_topic_us", "us/lm_pricepoint")
            self.topic_lm               = config.get("lm_topic", "smartstrip/lm")
            self.topic_ed               = config.get("energyDemand_topic", "smartstrip/energydemand")
            self.topic_ed_ds            = config.get("energyDemand_topic_ds", "ds/energydemand")
            self.topic_price_point_us   = config.get('pricePoint_topic_us', 'smarthub/pricepoint')
            self.topic_price_point      = config.get('pricePoint_topic', 'smartstrip/pricepoint')
            return

        @Core.receiver('onstart')            
        def startup(self, sender, **kwargs):
            _log.debug('startup()')
            #subscribing to topic_price_point_us
            self.vip.pubsub.subscribe("pubsub", self.topic_price_point_us, self.on_new_pp_us)
            
            #subscribing to topic lagrange multiplier (lm) from us
            self.vip.pubsub.subscribe("pubsub", self.topic_lm_us, self.on_new_lm_us)
            return

        #received new lagrange multiplier (lamda) from us
        def on_new_lm_us(self, peer, sender, bus,  topic, headers, message):
            _log.debug("on_new_lm_us()")
            if sender == 'pubsub.compat':
                message = compat.unpack_legacy_message(headers, message)
                
            #new lagrange multiplier
            lm_us = message[0]
            _log.debug ( "*** New lagrange multiplier: {0:.2f} ***".format(lm_us))
            self._current_lm_us = lm_us
            
            if self._isclose(self._current_pp_us, lm_us, EPSILON):
                _log.debug('New Optimal Price Point!!!')
                self._post_price(lm_us)
                return
            
            #not a lamda star
            #compute new lm
            #post the lm to local bus so that local device & ds device can compute the bid_ed
            lm = _compute_new_lm(lm_us)
            _post_lm(lm)
            return
            
        #reveived new price point from us
        def on_new_pp_us(self, peer, sender, bus,  topic, headers, message):
            _log.debug("on_new_pp_us()")
            if sender == 'pubsub.compat':
                message = compat.unpack_legacy_message(headers, message)
                
            #new hub price point
            pp_us = message[0]
            _log.debug ( "*** New Price Point: {0:.2f} ***".format(pp_us))
            
            if self._isclose(self._current_lm_us, pp_us, EPSILON) or \
                not self._isclose(self._current_pp_us, pp_us, EPSILON):
                _log.debug('New Optimal Price Point!!!')
                self._current_pp_us = pp_us
                self._post_price(pp_us)
                return
                
            return

        def _compute_new_lm(self, new_price):
            _log.debug('_compute_new_lm()')
            #TODO: implement the algorithm to compute the new price
            #      based on predicted demand, etc.
            return new_price

        def _post_lm(self, lm_us):
            _log.debug('_post_lm()')
            #post to bus
            pubTopic =  self.topic_lm
            pubMsg = [pp_us,{'units': 'cents', 'tz': 'UTC', 'type': 'float'}]
            _log.debug('publishing to local bus topic: ' + pubTopic)
            self._publishToBus(pubTopic, pubMsg)
            return

        def _post_price(self, pp_us):
            _log.debug('_post_price()')
            #post to bus
            pubTopic =  self.topic_price_point
            pubMsg = [pp_us,{'units': 'cents', 'tz': 'UTC', 'type': 'float'}]
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
                _log.warning("Expection: _publishToBus?")
                return
            return
            
        #refer to http://stackoverflow.com/questions/5595425/what-is-the-best-way-to-compare-floats-for-almost-equality-in-python
        #comparing floats is mess
        def _isclose(self, a, b, rel_tol=1e-09, abs_tol=0.0):
            return abs(a-b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)

    Agent.__name__ = 'SmartStripGC_Agent'
    return SmartStripGC(**kwargs)

def main(argv=sys.argv):
    '''Main method called by the eggsecutable.'''
    try:
        utils.vip_main(smartstripgc)
    except Exception as e:
        print e
        _log.exception('unhandled exception')

if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv))
    except KeyboardInterrupt:
        pass

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
            
            self._current_sh_pp = 0
            
            self.topic_price_point_us = config.get('pricePoint_topic_us', 'smarthub/pricepoint')
            self.topic_price_point = config.get('pricePoint_topic', 'smartstrip/pricepoint')
            return

        @Core.receiver('onstart')            
        def startup(self, sender, **kwargs):
            _log.debug('startup()')
            #subscribing to topic_price_point_us
            self.vip.pubsub.subscribe("pubsub", self.topic_price_point_us, self.onNewPrice)
            return

        def onNewPrice(self, peer, sender, bus,  topic, headers, message):
            if sender == 'pubsub.compat':
                message = compat.unpack_legacy_message(headers, message)
                
            #new hub price point
            sh_pp = message[0]
            _log.debug ( "*** New Price Point: {0:.2f} ***".format(sh_pp))
            
            if True:
            #if self._current_sh_pp != sh_pp:
                ss_pp = self._computeNewPrice(sh_pp)
                self._post_price(ss_pp)

        def _computeNewPrice(self, new_price):
            _log.debug('_computeNewPrice()')
            #TODO: implement the algorithm to compute the new price
            #      based on predicted demand, etc.
            return new_price

        def _post_price(self, ss_pp):
            _log.debug('_post_price()')
            #post to bus
            pubTopic =  self.topic_price_point
            pubMsg = [ss_pp,{'units': 'cents', 'tz': 'UTC', 'type': 'float'}]
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

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

from ispace_utils import publish_to_bus

utils.setup_logging()
_log = logging.getLogger(__name__)
__version__ = '0.2'


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
            
            if True:
            #if self._current_gd_pp != gd_pp:
                bd_pp = self._computeNewPrice(gd_pp)
                pubTopic =  self.topic_price_point
                pubMsg = [bd_pp, {'units': 'cents', 'tz': 'UTC', 'type': 'float'}]
                _log.debug('publishing to local bus topic: ' + pubTopic)
                publish_to_bus(self, pubTopic, pubMsg)
                return True
            else :
                _log.debug('No change in price')
                return False

        def _computeNewPrice(self, new_price):
            _log.debug('_computeNewPrice()')
            #TODO: implement the algorithm to compute the new price
            #      based on predicted demand, etc.
            return new_price


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

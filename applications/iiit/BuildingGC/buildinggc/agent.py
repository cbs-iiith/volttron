# -*- coding: utf-8 -*- {{{
# vim: set fenc=utf-8 ft=python sw=4 ts=4 sts=4 et:
#
# Copyright (c) 2020, Sam Babu, Godithi.
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
from volttron.platform.messaging import topics, headers as headers_mod

import time
import gevent
import gevent.event

from ispace_utils import publish_to_bus

utils.setup_logging()
_log = logging.getLogger(__name__)
__version__ = '0.3'

def buildinggc(config_path, **kwargs):

    config = utils.load_config(config_path)
    agentid = config['agentid']
    message = config['message']

    class BuildingGC(Agent):

        def __init__(self, **kwargs):
            _log.debug('__init__()')
            super(BuildingGC, self).__init__(**kwargs)
            return

        @Core.receiver('onsetup')
        def setup(self, sender, **kwargs):
            _log.info(config['message'])
            self._agent_id = config['agentid']
            
            #current grid price
            self._current_gd_pp = 0
            
            self.topic_price_point_us   = config.get('pricePoint_topic_us', 'us/pricepoint')
            self.topic_price_point      = config.get('pricePoint_topic', 'building/pricepoint')
            self.agent_disabled         = False
            return

        @Core.receiver('onstart')            
        def startup(self, sender, **kwargs):
            _log.debug('startup()')
            #subscribing to topic_price_point_us
            self.vip.pubsub.subscribe("pubsub", self.topic_price_point_us, self.onNewPrice)
            return

        def onNewPrice(self, peer, sender, bus,  topic, headers, message):
            #new zone price point
            new_pp              = message[0]
            new_pp_id           = message[2] if message[2] is not None else randint(0, 99999999)
            new_pp_isoptimal    = message[3] if message[3] is not None else False
            _log.info ("*** New Price Point: {0:.2f} ***".format(new_pp))
            _log.debug("*** new_pp_id: " + str(new_pp_id))
            _log.debug("*** new_pp_isoptimal: " + str(new_pp_isoptimal))
            
            if self.agent_disabled:
                _log.info("self.agent_disabled: " + str(self.agent_disabled) + ", do nothing!!!")
                return True
                
            if new_pp_isoptimal:
                pubTopic =  self.topic_price_point
                pubMsg = [new_pp, {'units': 'cents', 'tz': 'UTC', 'type': 'float'}, new_pp_id, new_pp_isoptimal]
                _log.debug('publishing to local bus topic: ' + pubTopic)
                publish_to_bus(self, pubTopic, pubMsg)
                return True
                
            #TODO:
            elif False:
            #if self._current_gd_pp != gd_pp:
                new_pp, new_pp_id, new_pp_isoptimal = self._computeNewPrice(new_pp, new_pp_id, new_pp_isoptimal)
                pubTopic =  self.topic_price_point
                pubMsg = [new_pp, {'units': 'cents', 'tz': 'UTC', 'type': 'float'}, new_pp_id, new_pp_isoptimal]
                _log.debug('publishing to local bus topic: ' + pubTopic)
                publish_to_bus(self, pubTopic, pubMsg)
                return True
            else :
                _log.debug('No change in price')
                return False
                
        def _computeNewPrice(self, new_pp, new_pp_id, new_pp_isoptimal):
            _log.debug('_computeNewPrice()')
            #TODO: implement the algorithm to compute the new price
            #      based on predicted demand, etc.
            return new_pp, new_pp_id, new_pp_isoptimal
            
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
        
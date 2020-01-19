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

from ispace_utils import publish_to_bus, ParamPP, ParamED

utils.setup_logging()
_log = logging.getLogger(__name__)
__version__ = '0.3'

def pricecontroller(config_path, **kwargs):

    config = utils.load_config(config_path)
    agentid = config['agentid']
    message = config['message']

    class PriceController(Agent):

        def __init__(self, **kwargs):
            _log.debug('__init__()')
            super(PriceController, self).__init__(**kwargs)
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
            
            _log.debug('registering rpc routes')
            self.vip.rpc.call(MASTER_WEB, 'register_agent_route', \
                    r'^/PriceController', \
#                    self.core.identity, \
                    "rpc_from_net").get(timeout=30)
                    
            #subscribing to topic_price_point_us
            self.vip.pubsub.subscribe("pubsub", self.topic_price_point_us, self.on_new_pp)
            return
            
        @RPC.export
        def rpc_from_net(self, header, message):
            result = False
            try:
                rpcdata = jsonrpc.JsonRpcData.parse(message)
                '''
                _log.debug('rpc_from_net()...' + \
                            ', rpc method: {}'.format(rpcdata.method) +\
                            ', rpc params: {}'.format(rpcdata.params))
                '''
                if rpcdata.method == "rpc_disable_agent":
                    args = {'disable_agent': rpcdata.params['disable_agent'],
                            }
                    result = self._disable_agent(**args)
                    
                elif rpcdata.method == "rpc_ping":
                    result = True
                else:
                    return jsonrpc.json_error(rpcdata.id, METHOD_NOT_FOUND, \
                                                'Invalid method {}'.format(rpcdata.method))
                                                
                return jsonrpc.json_result(rpcdata.id, result)
                
            except KeyError as ke:
                print(ke)
                return jsonrpc.json_error('NA', INVALID_PARAMS,
                        'Invalid params {}'.format(rpcdata.params))
            except Exception as e:
                print(e)
                return jsonrpc.json_error('NA', UNHANDLED_EXCEPTION, e)
                
        def _disable_agent(self, disable_agent):
            result = True
            if disable_agent is True:
                self.agent_disabled = True
            elif disable_agent is False:
                self.agent_disabled = False
            else:
                result = False
            return result
            
        def on_new_pp(self, peer, sender, bus,  topic, headers, message):
            #new zone price point
            new_pp              = message[ParamPP.idx_pp]
            new_pp_id           = message[ParamPP.idx_pp_id] \
                                    if message[ParamPP.idx_pp_id] is not None \
                                    else randint(0, 99999999)
            new_pp_isoptimal    = message[ParamPP.idx_pp_isoptimal] \
                                    if message[ParamPP.idx_pp_isoptimal] is not None \
                                    else False
            _log.info ("*** New Price Point: {0:.2f} ***".format(new_pp))
            _log.debug("*** new_pp_id: " + str(new_pp_id))
            _log.debug("*** new_pp_isoptimal: " + str(new_pp_isoptimal))
            
            if self.agent_disabled:
                _log.info("self.agent_disabled: " + str(self.agent_disabled) + ", do nothing!!!")
                return True
                
            if new_pp_isoptimal:
                pubTopic =  self.topic_price_point
                pubMsg = [new_pp, \
                            {'units': 'cents', 'tz': 'UTC', 'type': 'float'}, \
                            new_pp_id, \
                            new_pp_isoptimal\
                            ]
                _log.debug('publishing to local bus topic: ' + pubTopic)
                publish_to_bus(self, pubTopic, pubMsg)
                return True
                
            #TODO:
            elif False:
            #if self._current_gd_pp != gd_pp:
                new_pp, new_pp_id, new_pp_isoptimal = self._computeNewPrice(new_pp, new_pp_id, new_pp_isoptimal)
                pubTopic =  self.topic_price_point
                pubMsg = [new_pp, \
                            {'units': 'cents', 'tz': 'UTC', 'type': 'float'}, \
                            new_pp_id, \
                            new_pp_isoptimal\
                            ]
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
            
    Agent.__name__ = 'PriceController_Agent'
    return PriceController(**kwargs)
    
def main(argv=sys.argv):
    '''Main method called by the eggsecutable.'''
    try:
        utils.vip_main(pricecontroller)
    except Exception as e:
        print (e)
        _log.exception('unhandled exception')
        
if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv))
    except KeyboardInterrupt:
        pass
        
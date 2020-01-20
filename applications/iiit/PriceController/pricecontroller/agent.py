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
from random import random, randint

from volttron.platform.vip.agent import Agent, Core, PubSub, compat, RPC
from volttron.platform.agent import utils
from volttron.platform.messaging import topics, headers as headers_mod
from volttron.platform.agent.known_identities import (
    MASTER_WEB, VOLTTRON_CENTRAL, VOLTTRON_CENTRAL_PLATFORM)

import time
import gevent
import gevent.event

from ispace_utils import publish_to_bus, ParamPP, ParamED, print_pp, print_ed

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
            self.pp_optimize_option     = config.get('pp_optimize_option', 'PASS_ON_PP')
            self.topic_extrn_pp         = config.get('extrn_optimize_pp_topic', 'pca/pricepoint')
            return

        @Core.receiver('onstart')            
        def startup(self, sender, **kwargs):
            _log.debug('startup()')
            
            _log.debug('registering rpc routes')
            self.vip.rpc.call(MASTER_WEB, 'register_agent_route', \
                    r'^/PriceController', \
#                    self.core.identity, \
                    "rpc_from_net").get(timeout=30)
                    
            self.us_pp              = 0
            self.us_pp_id           = randint(0, 99999999)
            self.us_pp_datatype     = {'units': 'cents', 'tz': 'UTC', 'type': 'float'}
            self.us_pp_isoptimal    = False
            self.us_pp_ttl          = -1
            self.us_pp_timestamp    = datetime.datetime.utcnow().isoformat(' ') + 'Z'
            self.us_pp_isoptimal    = False
            
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
                    
                elif rpcdata.method == "rpc_set_pp_optimize_option":
                    args = {'option': rpcdata.params['option'],
                            }
                    result = self._set_pp_optimize_option(**args)
                    
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
            if disable_agent is True \
                or disable_agent is False \
                :
                self.agent_disabled = disable_agent
                result = True
            else:
                result = False
            return result
            
        def _set_pp_optimize_option(self, option):
            if option == "PASS_ON_PP" \
                or option == "DEFAULT_OPT" \
                or option == "EXTERN_OPT" \
                :
                self.pp_optimize_option = self.pp_optimize_option
                result = True
            else:
                result = False
            return result
            
        #
        def on_new_ed(self, peer, sender, bus,  topic, headers, message):
            #subscribe to ds/energydemand,
            #accumulate ed from all ds, also get local ed
            #publish ted to local(building/zone/smarthub/smartstrip)/enedgydemand
            
            #subscribe to local(building/zone/smarthub/smartstrip)/pricepoint
            #keep a note of pp_id
            return
            
        def on_new_pp(self, peer, sender, bus,  topic, headers, message):
            #new zone price point
            new_pp              = message[ParamPP.idx_pp]
            new_pp_datatype     = message[ParamPP.idx_pp_datatype] \
                                    if message[ParamPP.idx_pp_datatype] is not None \
                                    else {'units': 'cents', 'tz': 'UTC', 'type': 'float'}
            new_pp_id           = message[ParamPP.idx_pp_id] \
                                    if message[ParamPP.idx_pp_id] is not None \
                                    else randint(0, 99999999)
            new_pp_isoptimal    = message[ParamPP.idx_pp_isoptimal] \
                                    if message[ParamPP.idx_pp_isoptimal] is not None \
                                    else False
            new_pp_ttl          = message[ParamPP.idx_pp_ttl] \
                                    if message[ParamPP.idx_pp_ttl] is not None \
                                    else -1
            new_pp_timestamp    = message[ParamPP.idx_pp_timestamp] \
                                    if message[ParamPP.idx_pp_timestamp] is not None \
                                    else datetime.datetime.utcnow().isoformat(' ') + 'Z'
            print_pp(self, new_pp \
                            , new_pp_datatype \
                            , new_pp_id \
                            , new_pp_isoptimal \
                            , None \
                            , None \
                            , new_pp_ttl \
                            , new_pp_timestamp \
                            )
                            
            if self.agent_disabled:
                _log.info("self.agent_disabled: " + str(self.agent_disabled) + ", do nothing!!!")
                return True
                
            if new_pp_isoptimal \
                    or self.pp_optimize_option == "PASS_ON_PP" \
                    or self.pp_optimize_option == "EXTERN_OPT" \
                    :
                pubTopic =  self.topic_extrn_pp \
                                if self.pp_optimize_option == "EXTERN_OPT" \
                                else self.topic_price_point 
                pubMsg = [new_pp \
                            , new_pp_datatype \
                            , new_pp_id \
                            , new_pp_isoptimal \
                            , None \
                            , None \
                            , new_pp_ttl \
                            , new_pp_timestamp \
                            ]
                _log.debug('publishing to local bus topic: ' + pubTopic)
                publish_to_bus(self, pubTopic, pubMsg)
                return True
            elif self.pp_optimize_option == "DEFAULT_OPT":
                self.us_pp = new_pp
                self.us_pp_datatype = new_pp_datatype
                self.us_pp_id = new_pp_id
                self.us_pp_isoptimal = new_pp_isoptimal
                self.us_pp_ttl = new_pp_ttl
                self.us_pp_timestamp = new_pp_timestamp
                
                self._computeNewPrice()
                return True
                
        def _computeNewPrice(self):
            _log.debug('_computeNewPrice()')
            #TODO: implement the algorithm to compute the new price
            #      based on walras algorithm.
            #       config.get (optimization cost function)
            #       based on some initial condition like ed, us_new_pp, etc, compute new_pp
            #       publish to bus
            
            #optimization algo
            #   ed_target   = r% x ed_optimal
            #   EPSILON     = 10       #deadband
            #   gamma       = stepsize
            #   max_iter    = 20        (assuming each iter is 30sec and max time spent is 10 min)
            #   
            #   count_iter = 0
            #   pp_old = pp_opt
            #   pp_new = pp_old
            #   do while (ed_target - ed_current > EPSILON)
            #       if (count_iter < max_iter)
            #            pp_new = pp_old + gamma(ed_current - ed_previous)
            #            pp_old = pp_new
            #    
            #   pp_opt = pp_new
            #
            new_pp = self.us_pp * 1.25
            new_pp_datatype = self.us_pp_datatype
            new_pp_id = randint(0, 99999999)
            new_pp_isoptimal = False
            new_pp_ttl = 5  #5 sec
            new_pp_timestamp = datetime.datetime.utcnow().isoformat(' ') + 'Z'
            
            print_pp(self, new_pp \
                            , new_pp_datatype \
                            , new_pp_id \
                            , new_pp_isoptimal \
                            , None \
                            , None \
                            , new_pp_ttl \
                            , new_pp_timestamp \
                            )
                            
            pubTopic =  self.topic_price_point
            pubMsg = [new_pp \
                        , new_pp_datatype \
                        , new_pp_id \
                        , new_pp_isoptimal \
                        , None \
                        , None \
                        , new_pp_ttl \
                        , new_pp_timestamp \
                        ]
            _log.debug('publishing to local bus topic: ' + pubTopic)
            publish_to_bus(self, pubTopic, pubMsg)
            
            #       iterate till optimization condition satistifed
            #       when new pp is published, the new ed for all devices is accumulated by on_new_ed()
            #       once all the eds are received call this function again
            #       publish the new optimal pp
            return
            
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
        
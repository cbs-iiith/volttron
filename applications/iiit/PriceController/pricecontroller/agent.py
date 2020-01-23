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

import ispace_utils

utils.setup_logging()
_log = logging.getLogger(__name__)
__version__ = '0.3'

def pricecontroller(config_path, **kwargs):
    config = utils.load_config(config_path)
    vip_identity = config.get('vip_identity', 'iiit.pricecontroller')
    # This agent needs to be named iiit.pricecontroller. Pop the uuid id off the kwargs
    kwargs.pop('identity', None)
    
    Agent.__name__ = 'PriceController_Agent'
    return PriceController(**kwargs)
    
class PriceController(Agent):
    '''Price Controller
    '''
    def __init__(self, **kwargs):
        super(PriceController, self).__init__(**kwargs)
        _log.debug("vip_identity: " + self.core.identity)
        
        self.config = utils.load_config(config_path)
        return

    @Core.receiver('onsetup')
    def setup(self, sender, **kwargs):
        _log.info(self.config['message'])
        self._agent_id = self.config['agentid']
        
        self.topic_price_point_us = self.config.get('pricePoint_topic_us', 'us/pricepoint')
        self.topic_price_point = self.config.get('pricePoint_topic', 'building/pricepoint')
        self.agent_disabled = False
        self.pp_optimize_option = self.config.get('pp_optimize_option', 'PASS_ON_PP')
        self.topic_extrn_pp = self.config.get('extrn_optimize_pp_topic', 'pca/pricepoint')
        return

    @Core.receiver('onstart')
    def startup(self, sender, **kwargs):
        _log.debug('startup()')
        
        _log.debug('registering rpc routes')
        self.vip.rpc.call(MASTER_WEB, 'register_agent_route'
                            ,r'^/PriceController'
                            , "rpc_from_net"
                            ).get(timeout=30)
                            
        self.us_pp = 0
        self.us_pp_id = randint(0, 99999999)
        self.us_pp_datatype = {'units': 'cents', 'tz': 'UTC', 'type': 'float'}
        self.us_pp_isoptimal = False
        self.us_pp_ttl = -1
        self.us_pp_ts = datetime.datetime.utcnow().isoformat(' ') + 'Z'
        self.us_pp_isoptimal = False
        
        #subscribing to topic_price_point_us
        self.vip.pubsub.subscribe("pubsub", self.topic_price_point_us, self.on_new_pp)
        return
        
    @RPC.export
    def rpc_from_net(self, header, message):
        result = False
        try:
            rpcdata = jsonrpc.JsonRpcData.parse(message)
            '''
            _log.debug('rpc_from_net()...' +
                        ', rpc method: {}'.format(rpcdata.method) +
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
                return jsonrpc.json_error(rpcdata.id, METHOD_NOT_FOUND,
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
        if disable_agent in [True, False]:
            self.agent_disabled = disable_agent
            result = True
        else:
            result = False
        return result
        
    def _set_pp_optimize_option(self, option):
        if option in ["PASS_ON_PP"
                        , "DEFAULT_OPT"
                        , "EXTERN_OPT"
                        ]:
            self.pp_optimize_option = self.pp_optimize_option
            result = True
        else:
            result = False
        return result
        
    #subscribe to local/ed (i.e., ted) from the controller (building/zone/smarthub controller)
    def on_new_ed(self, peer, sender, bus,  topic, headers, message):
        # (_ed, _is_opt, _ed_pp_id) = get_data(message)
        #if _ed_pp_id = us_opt_pp_id:
        #   #ed for global opt, do nothing
        #   #vb moves this ed to next level
        #   return
        #if pass_on and _ed_pp_id in us_pp_ids[]
        #   #do nothing
        #   #vb moves this ed to next level
        #   return
        #if default_opt and _ed_pp_id in local_pp_ids[]
        #       (new_pp, new_pp_isopt) = _computeNewPrice()
        #       if new_pp_isopt
        #           #local optimal reached
        #           publish_ed(local/ed, _ed, us_bid_pp_id)
        #           #if next level accepts this bid, the new target is this ed
        #       based on opt conditon _computeNewPrice can publish new bid_pp or 
        #if extrn_opt and _ed_pp_id in extrn_pp_ids[]
        #   publish_ed(extrn/ed, _ed, _ed_pp_id)
        #   return
        
        return
        
    #subscribe to us/price (building/zone/smarthub/smartstrip)/pricepoint
    #and also includes extern_pp_control_algo/pricepoint
    #keep track of all the 6 pp_ids = (us, extrn, pca_generated_ids) x 2 (opt & bid)
    def on_new_pp(self, peer, sender, bus,  topic, headers, message):
        #new zone price point
        new_pp = message[ParamPP.idx_pp]
        new_pp_datatype = message[ParamPP.idx_pp_datatype]
                                if message[ParamPP.idx_pp_datatype] is not None
                                else {'units': 'cents', 'tz': 'UTC', 'type': 'float'}
        new_pp_id = message[ParamPP.idx_pp_id]
                                if message[ParamPP.idx_pp_id] is not None
                                else randint(0, 99999999)
        new_pp_isoptimal = message[ParamPP.idx_pp_isoptimal]
                                if message[ParamPP.idx_pp_isoptimal] is not None
                                else False
        new_pp_ttl = message[ParamPP.idx_pp_ttl]
                                if message[ParamPP.idx_pp_ttl] is not None
                                else -1
        new_pp_ts = message[ParamPP.idx_pp_ts]
                                if message[ParamPP.idx_pp_ts] is not None
                                else datetime.datetime.utcnow().isoformat(' ') + 'Z'
        ispace_utils.print_pp(self, new_pp
                        , new_pp_datatype
                        , new_pp_id
                        , new_pp_isoptimal
                        , None
                        , None
                        , new_pp_ttl
                        , new_pp_ts
                        )
                        
        if self.agent_disabled:
            _log.info("self.agent_disabled: " + str(self.agent_disabled) + ", do nothing!!!")
            return True
            
        if new_pp_isoptimal or self.pp_optimize_option in ["PASS_ON_PP", "EXTERN_OPT"]:
            pubTopic =  self.topic_extrn_pp
                            if self.pp_optimize_option == "EXTERN_OPT"
                            else self.topic_price_point 
            pubMsg = [new_pp
                        , new_pp_datatype
                        , new_pp_id
                        , new_pp_isoptimal
                        , None
                        , None
                        , new_pp_ttl
                        , new_pp_ts
                        ]
            _log.debug('publishing to local bus topic: ' + pubTopic)
            ispace_utils.publish_to_bus(self, pubTopic, pubMsg)
            return True
        elif self.pp_optimize_option == "DEFAULT_OPT":
            self.us_pp = new_pp
            self.us_pp_datatype = new_pp_datatype
            self.us_pp_id = new_pp_id
            self.us_pp_isoptimal = new_pp_isoptimal
            self.us_pp_ttl = new_pp_ttl
            self.us_pp_ts = new_pp_ts
            
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
        #   ed_target = r% x ed_optimal
        #   EPSILON = 10       #deadband
        #   gamma = stepsize
        #   max_iter = 20        (assuming each iter is 30sec and max time spent is 10 min)
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
        new_pp_ts = datetime.datetime.utcnow().isoformat(' ') + 'Z'
        
        ispace_utils.print_pp(self, new_pp
                        , new_pp_datatype
                        , new_pp_id
                        , new_pp_isoptimal
                        , None
                        , None
                        , new_pp_ttl
                        , new_pp_ts
                        )
                        
        pubTopic =  self.topic_price_point
        pubMsg = [new_pp
                    , new_pp_datatype
                    , new_pp_id
                    , new_pp_isoptimal
                    , None
                    , None
                    , new_pp_ttl
                    , new_pp_ts
                    ]
        _log.debug('publishing to local bus topic: ' + pubTopic)
        ispace_utils.publish_to_bus(self, pubTopic, pubMsg)
        
        #       iterate till optimization condition satistifed
        #       when new pp is published, the new ed for all devices is accumulated by on_new_ed()
        #       once all the eds are received call this function again
        #       publish the new optimal pp
        return
        
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
        
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
from volttron.platform.messaging import headers as headers_mod

from volttron.platform.messaging import topics, headers as headers_mod
from volttron.platform.agent.known_identities import (
    MASTER_WEB, VOLTTRON_CENTRAL, VOLTTRON_CENTRAL_PLATFORM)
from volttron.platform import jsonrpc
from volttron.platform.jsonrpc import (
        INVALID_REQUEST, METHOD_NOT_FOUND, PARSE_ERROR,
        UNHANDLED_EXCEPTION, UNAUTHORIZED,
        UNABLE_TO_REGISTER_INSTANCE, DISCOVERY_ERROR,
        UNABLE_TO_UNREGISTER_INSTANCE, UNAVAILABLE_PLATFORM, INVALID_PARAMS,
        UNAVAILABLE_AGENT)

from random import randint
import settings
import time
from copy import copy


from ispace_utils import publish_to_bus, retrive_details_from_vb, register_rpc_route
from ispace_msg import ISPACE_Msg, MessageType
from ispace_msg_utils import parse_jsonrpc_msg, check_msg_type

utils.setup_logging()
_log = logging.getLogger(__name__)
__version__ = '0.4'


def pricepoint(config_path, **kwargs):
    config = utils.load_config(config_path)
    vip_identity = config.get('vip_identity', 'iiit.pricepoint')
    # This agent needs to be named iiit.pricepoint. Pop the uuid id off the kwargs
    kwargs.pop('identity', None)
    
    Agent.__name__ = 'PricePoint_Agent'
    return PricePoint(config_path, identity=vip_identity, **kwargs)
    
    
class PricePoint(Agent):
    '''Agent for posting a price point to msg bus
    '''
    
    #initialized  during __init__ from config
    _default_base_price = None
    _min_price = None
    _max_price = None
    _period_read_price_point = None
    
    _topic_price_point = None
    _vb_vip_identity = None
    
    _device_id = None
    _discovery_address = None
    
    def __init__(self, config_path, **kwargs):
        super(PricePoint, self).__init__(**kwargs)
        _log.debug("vip_identity: " + self.core.identity)
        
        self.config = utils.load_config(config_path)
        self._config_get_points()
        self._config_get_init_values()
        return
        
    @Core.receiver('onsetup')
    def setup(self, sender, **kwargs):
        _log.info(self.config['message'])
        self._agent_id = self.config['agentid']
        
        return
        
    @Core.receiver('onstart')
    def startup(self, sender, **kwargs):
        #retrive self._device_id and self._discovery_address from vb
        retrive_details_from_vb(self, 5)
        
        #register rpc routes with MASTER_WEB
        #register_rpc_route is a blocking call
        register_rpc_route(self, "pricepoint", "rpc_from_net", 5)
        
        _log.debug('startup() - Done. Agent is ready')
        return
        
    @Core.receiver('onstop')
    def onstop(self, sender, **kwargs):
        _log.debug('onstop()')
        _log.debug('un registering rpc routes')
        self.vip.rpc.call(MASTER_WEB, 'unregister_all_agent_routes').get(timeout=10)
        return
        
    @Core.receiver('onfinish')
    def onfinish(self, sender, **kwargs):
        _log.debug('onfinish()')
        return
        
    def _config_get_init_values(self):
        self._default_base_price = self.config.get('default_base_price', 0.4)
        self._min_price = self.config.get('min_price', 0.0)
        self._max_price = self.config.get('max_price', 1.0)
        self._period_read_price_point = self.config.get('period_read_price_point', 5)
        return
        
    def _config_get_points(self):
        self._vb_vip_identity = self.config.get('vb_vip_identity', 'iiit.volttronbridge')
        self._topic_price_point = self.config.get('topic_price_point', 'zone/pricepoint')
        return
        
    @RPC.export
    def rpc_from_net(self, header, message):
        result = False
        try:
            rpcdata = jsonrpc.JsonRpcData.parse(message)
            _log.debug('rpc_from_net()...'
                        + 'header: {}'.format(header)
                        + ', rpc method: {}'.format(rpcdata.method)
                        + ', rpc params: {}'.format(rpcdata.params)
                        )
            if rpcdata.method == "ping":
                result = True
            elif rpcdata.method == "new-pp":
                result = self.update_price_point(rpcdata.id, message)
            else:
                return jsonrpc.json_error(rpcdata.id, METHOD_NOT_FOUND,
                                            'Invalid method {}'.format(rpcdata.method))
        except KeyError:
            #print('KeyError')
            return jsonrpc.json_error(rpcdata.id, INVALID_PARAMS,
                                        'Invalid params {}'.format(rpcdata.params))
        except Exception as e:
            #print(e)
            return jsonrpc.json_error(rpcdata.id, UNHANDLED_EXCEPTION, e)
        return jsonrpc.json_result(rpcdata.id, result)
        
    def update_price_point(self, rpcdata_id, message):
        pp_msg = None
        rpcdata = jsonrpc.JsonRpcData.parse(message)
        #Note: this is on a rpc message do the check here ONLY
        #check message for MessageType.price_point
        if not check_msg_type(message, MessageType.price_point): 
            return jsonrpc.json_error(rpcdata_id, INVALID_PARAMS, 'Invalid params {}'.format(rpcdata.params))
        try:
            minimum_fields = ['value', 'value_data_type', 'units', 'price_id']
            pp_msg = parse_jsonrpc_msg(message, minimum_fields)
            #_log.info('pp_msg: {}'.format(pp_msg))
        except KeyError as ke:
            #print(ke)
            return jsonrpc.json_error(rpcdata_id, INVALID_PARAMS,
                    'Invalid params {}'.format(rpcdata.params))
        except Exception as e:
            #print(e)
            return jsonrpc.json_error(rpcdata_id, UNHANDLED_EXCEPTION, e)
            
        #validate various sanity measure like, valid fields, valid pp ids, ttl expiry, etc.,
        hint = 'New Price Point'
        validate_fields = ['value', 'value_data_type', 'units', 'price_id', 'isoptimal', 'duration', 'ttl']
        valid_price_ids = []
        if not pp_msg.sanity_check_ok(hint, validate_fields, valid_price_ids):
            _log.warning('Msg sanity checks failed!!!')
            return jsonrpc.json_error(rpcdata_id, PARSE_ERROR, 'Msg sanity checks failed!!!')
            
        pp_msg.set_src_device_id(self._device_id)
        pp_msg.set_src_ip(self._discovery_address)
        
        #publish the new price point to the local message bus
        pub_topic = self._topic_price_point
        pub_msg = pp_msg.get_json_message(self._agent_id, 'bus_topic')
        #keep a track of us pp_msg
        if pp_msg.get_isoptimal():
            _log.info('***** New optimal price point from us: {0:0.2f}'.format(pp_msg.get_value()))
        else:
            _log.info('***** New bid price point from us: {0:0.2f}'.format(pp_msg.get_value()))

        _log.debug('publishing to local bus topic: {}'.format(pub_topic))
        _log.debug('Msg: {}'.format(pub_msg))
        publish_to_bus(self, pub_topic, pub_msg)
        return True
        
        
def main(argv=sys.argv):
    '''Main method called by the eggsecutable.'''
    try:
        utils.vip_main(pricepoint)
    except Exception as e:
        print (e)
        _log.exception('unhandled exception')
        
        
if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv))
    except KeyboardInterrupt:
        pass
        
        
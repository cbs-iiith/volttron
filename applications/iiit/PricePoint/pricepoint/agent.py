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
        INVALID_REQUEST, METHOD_NOT_FOUND,
        UNHANDLED_EXCEPTION, UNAUTHORIZED,
        UNABLE_TO_REGISTER_INSTANCE, DISCOVERY_ERROR,
        UNABLE_TO_UNREGISTER_INSTANCE, UNAVAILABLE_PLATFORM, INVALID_PARAMS,
        UNAVAILABLE_AGENT)

from random import randint
import settings
import time
from ispace_utils import publish_to_bus
from ispace_msg import parse_jsonrpc_msg
from ispace_utils import retrive_details_from_vb

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
        
        self._device_id = None
        self._ip_addr = None
        self._discovery_address = None
        
        return
        
    @Core.receiver('onstart')
    def startup(self, sender, **kwargs):
        self.vip.rpc.call(MASTER_WEB, 'register_agent_route'
                            , r'^/PricePoint'
                            , "rpc_from_net"
                            ).get(timeout=10)
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
        self.default_base_price = self.config.get('default_base_price', 0.4)
        self.min_price = self.config.get('min_price', 0.0)
        self.max_price = self.config.get('max_price', 1.0)
        self.period_read_price_point = self.config.get('period_read_price_point', 5)
        return
        
    def _config_get_points(self):
        self.vb_vip_identity = self.config.get('vb_vip_identity', 'iiit.volttronbridge')
        self.topic_price_point = self.config.get('topic_price_point', 'zone/pricepoint')
        return
        
    @RPC.export
    def rpc_from_net(self, header, message):
        _log.debug('rpc_from_net()')
        result = False
        try:
            rpcdata = jsonrpc.JsonRpcData.parse(message)
            _log.debug('rpc method: {}'.format(rpcdata.method))
            _log.debug('rpc params: {}'.format(rpcdata.params))
            if rpcdata.method == "rpc_update_price_point":
                result = self.update_price_point(message)
            elif rpcdata.method == "rpc_ping":
                result = True
            else:
                return jsonrpc.json_error(rpcdata.id, METHOD_NOT_FOUND,
                                            'Invalid method {}'.format(rpcdata.method))
            return jsonrpc.json_result(rpcdata.id, result)
        except KeyError:
            print('KeyError')
            return jsonrpc.json_error(rpcdata.id, INVALID_PARAMS,
                                        'Invalid params {}'.format(rpcdata.params))
        except Exception as e:
            print(e)
            return jsonrpc.json_error(rpcdata.id, UNHANDLED_EXCEPTION, e)
        return
        
    def update_price_point(self, message):
        try:
            mandatory_fields = ['value', 'value_data_type', 'units', 'price_id']
            pp_msg = parse_jsonrpc_msg(message, mandatory_fields)
            #_log.info('pp_msg: {}'.format(pp_msg))
        except KeyError as ke:
            print(ke)
            return jsonrpc.json_error('NA', INVALID_PARAMS,
                    'Invalid params {}'.format(rpcdata.params))
        except Exception as e:
            print(e)
            return jsonrpc.json_error('NA', UNHANDLED_EXCEPTION, e)
            
        hint = 'New Price Point'
        mandatory_fields = ['value', 'value_data_type', 'units', 'price_id', 'isoptimal', 'duration', 'ttl']
        valid_price_ids = []
        #validate various sanity measure like, valid fields, valid pp ids, ttl expiry, etc.,
        if not pp_msg.sanity_check_ok(hint, mandatory_fields, valid_price_ids):
            _log.warning('Msg sanity checks failed!!!')
            return 'Msg sanity checks failed!!!'
            
        retrive_details_from_vb(self)
        pp_msg.set_src_device_id(self._device_id)
        pp_msg.set_src_ip(self._discovery_address)
        
        #publish the new price point to the local message bus
        pub_topic = self.topic_price_point
        pub_msg = pp_msg.get_json_params(self._agent_id)
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
        
        
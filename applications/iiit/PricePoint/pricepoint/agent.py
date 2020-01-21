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
from ispace_utils import publish_to_bus, print_pp, print_ed

utils.setup_logging()
_log = logging.getLogger(__name__)
__version__ = '0.3'

class PricePoint(Agent):

    _price_point_previous = 0.4 

    def __init__(self, config_path, **kwargs):
        super(PricePoint, self).__init__(**kwargs)
        _log.debug("vip_identity: " + self.core.identity)
        
        self.config = utils.load_config(config_path)
        self._configGetPoints()
        self._configGetInitValues()
        return

    @Core.receiver('onsetup')
    def setup(self, sender, **kwargs):
        _log.info(self.config['message'])
        self._agent_id = self.config['agentid']
        return

    @Core.receiver('onstart')            
    def startup(self, sender, **kwargs):
        self.vip.rpc.call(MASTER_WEB, 'register_agent_route',
                      r'^/PricePoint',
                      "rpc_from_net").get(timeout=10)    
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

    def _configGetInitValues(self):
        self.default_base_price         = self.config.get('default_base_price', 0.4)
        self.min_price                  = self.config.get('min_price', 0.0)
        self.max_price                  = self.config.get('max_price', 1.0)
        self.period_read_price_point    = self.config.get('period_read_price_point', 5)
        return

    def _configGetPoints(self):
        self.topic_price_point          = self.config.get('topic_price_point', 'zone/pricepoint')
        return

    def fake_price_points(self):
        #Make a random price point
        _log.debug('fake_price_points()')
        new_price_reading = random.uniform(self.min_price, self.max_price)
        self.updatePricePoint(new_pp)
        return

    @RPC.export
    def rpc_from_net(self, header, message):
        return self._processMessage(message)

    def _processMessage(self, message):
        _log.debug('processResponse()')
        result = False
        try:
            rpcdata = jsonrpc.JsonRpcData.parse(message)
            _log.debug('rpc method: {}'.format(rpcdata.method))
            _log.debug('rpc params: {}'.format(rpcdata.params))
            
            if rpcdata.method == "rpc_updatePricePoint":
                args = {'new_pp': rpcdata.params['new_pp'] \
                            , 'new_pp_id': rpcdata.params['new_pp_id'] \
                                        if rpcdata.params['new_pp_id'] is not None \
                                        else randint(0, 99999999) \
                            , 'new_pp_datatype': rpcdata.params['new_pp_datatype'] \
                                        if rpcdata.params['new_pp_datatype'] is not None \
                                        else {'units': 'cents', 'tz': 'UTC', 'type': 'float'} \
                            , 'new_pp_isoptimal': rpcdata.params['new_pp_isoptimal'] \
                                        if rpcdata.params['new_pp_isoptimal'] is not None \
                                            else False \
                            , 'new_pp_ttl': rpcdata.params['new_pp_ttl'] \
                                        if rpcdata.params['new_pp_ttl'] is not None \
                                        else -1 \
                            , 'new_pp_ts': rpcdata.params['new_pp_ts'] \
                                        if rpcdata.params['new_pp_ts'] is not None \
                                        else datetime.datetime.utcnow().isoformat(' ') + 'Z' \
                        }
                result = self.updatePricePoint(**args)
            elif rpcdata.method == "rpc_ping":
                result = True
            else:
                return jsonrpc.json_error(rpcdata.id, METHOD_NOT_FOUND,
                    'Invalid method {}'.format(rpcdata.method))
                    
            return jsonrpc.json_result(rpcdata.id, result)
            
        except KeyError:
            print('KeyError')
            return jsonrpc.json_error('NA', INVALID_PARAMS,
                    'Invalid params {}'.format(rpcdata.params))
        except Exception as e:
            print(e)
            return jsonrpc.json_error('NA', UNHANDLED_EXCEPTION, e)
        return

    @RPC.export
    def updatePricePoint(self, new_pp, new_pp_datatype, new_pp_id, new_pp_isoptimal, new_pp_ttl, new_pp_ts):
        print_pp(self, new_pp \
                        , new_pp_datatype \
                        , new_pp_id \
                        , new_pp_isoptimal \
                        , None \
                        , None \
                        , new_pp_ttl \
                        , new_pp_ts \
                        )
                        
        pubTopic = self.topic_price_point
        pubMsg = [new_pp \
                    , new_pp_datatype \
                    , new_pp_id \
                    , new_pp_isoptimal \
                    , None \
                    , None \
                    , new_pp_ttl \
                    , new_pp_ts \
                    ]
        _log.debug('publishing to local bus topic: ' + pubTopic)
        publish_to_bus(self, pubTopic, pubMsg)
        self._price_point_previous = new_pp
        return True


def main(argv=sys.argv):
    '''Main method called by the eggsecutable.'''
    try:
        utils.vip_main(PricePoint)
    except Exception as e:
        print (e)
        _log.exception('unhandled exception')

if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv))
    except KeyboardInterrupt:
        pass

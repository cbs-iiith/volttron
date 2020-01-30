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

from volttron.platform.vip.agent import Agent, Core, PubSub, compat, RPC
from volttron.platform.agent import utils
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

import time
import gevent
import gevent.event
import json

import ispace_utils
from ispace_msg import ISPACE_Msg, MessageType
from ispace_msg_utils import parse_bustopic_msg, check_for_msg_type

utils.setup_logging()
_log = logging.getLogger(__name__)
__version__ = '0.3'

#checking if a floating point value is "numerically zero" by checking if it is lower than epsilon
EPSILON = 1e-03

#if the rpc connection fails to post for more than MAX_RETRIES, 
#then it is assumed that the dest is down
#in case of ds posts, the retry count is reset when the ds registers again or on a new price point
#in case of us posts, the retry count is reset when change in ed.
#   also if failed too many times to post ed, retry count is reset and the process yeilds for a movement(10sec)
MAX_RETRIES = 5


def volttronbridge(config_path, **kwargs):
    config = utils.load_config(config_path)
    vip_identity = config.get('vip_identity', 'iiit.volttronbridge')
    # This agent needs to be named iiit.volttronbridge. Pop the uuid id off the kwargs
    kwargs.pop('identity', None)
    
    Agent.__name__ = 'VolttronBridge_Agent'
    return VolttronBridge(config_path, identity=vip_identity, **kwargs)
    
    
'''
Retrive the data from volttron bus and pushes it to upstream or downstream volttron instance
if posting to downstream, then the data is pricepoint
and if posting to upstream then the data is energydemand

The assumption is that for UpStream (us), the bridge communicates with only one instance and 
for the DownStream (ds), the bridge would be posting to multiple devices

for pricepoint one-to-many communication
    energydemand one-to-one communication

The ds devices on their start up would register with this instance with ip address & port

The bridge is aware of the upstream devices and registers to it (associates to it). 
Also, as and when there is a change in energydemand, the same is posted to the upstream bridges.
whereas the the bridge does not upfront know the downstream devices. 
As and when the downstram bridges register to the bridge, the bridge starts posting the messages (pricepoint) to them
'''
class VolttronBridge(Agent):
    '''Voltron Bridge
    '''
    def __init__(self, config_path, **kwargs):
        super(VolttronBridge, self).__init__(**kwargs)
        _log.debug("vip_identity: " + self.core.identity)
        
        self.config = utils.load_config(config_path)
        self._configGetPoints()
        return
        
    @Core.receiver('onsetup')
    def setup(self, sender, **kwargs):
        _log.info(self.config['message'])
        self._agent_id = self.config['agentid']
        
        self._usConnected = False
        self._bridge_host = self.config.get('bridge_host', 'LEVEL_HEAD')
        self._deviceId = self.config.get('deviceId', 'Building-1')
        
        self._this_ip_addr = self.config.get('ip_addr', "192.168.1.51")
        self._this_port = int(self.config.get('port', 8082))
        
        self._period_process_pp = int(self.config.get('period_process_pp', 10))
        
        if self._bridge_host != 'LEVEL_TAILEND':
            _log.debug(self._bridge_host)
            
            #downstream volttron instances
            #post price point to these instances
            self._ds_register = []
            self._ds_device_ids = []
            self._ds_retrycount = []
            
        if self._bridge_host != 'LEVEL_HEAD':
            _log.debug(self._bridge_host)
            
            #upstream volttron instance
            self._us_ip_addr = self.config.get('us_ip_addr', "192.168.1.51")
            self._us_port = int(self.config.get('us_port', 8082))
            _log.debug('self._us_ip_addr: ' + self._us_ip_addr + ' self._us_port: ' + str(self._us_port))
            
        self._discovery_address = self._this_ip_addr + ':' + str(self._this_port)
        _log.debug('self._discovery_address: ' + self._discovery_address)
        return
        
    @Core.receiver('onstart')
    def startup(self, sender, **kwargs):
        _log.debug('startup()')
        _log.debug(self._bridge_host)
        
        #price point
        self._pp_current = 0
        self._pp_id = randint(0, 99999999)
        self._pp_datatype = {'units': 'cents', 'tz': 'UTC', 'type': 'float'}
        self._pp_isoptimal = False
        #self._pp_discovery_addrs = None    #using self._discovery_address, values from config
        #self._pp_device_id = None          #using self._deviceId, values from config
        self._pp_duration = 3600
        self._pp_ttl = -1
        self._pp_ts = ''
        self._all_ds_posts_success = False
        
        #energy demand
        self._ed_current = 0
        self._ed_datatype = {'units': 'W', 'tz': 'UTC', 'type': 'float'}
        self._ed_pp_id = randint(0, 99999999)
        self._ed_isoptimal = True
        self._ed_discovery_addrs = ''
        self._ed_device_id = ''
        self._ed_duration = 0
        self._ed_ttl = -1
        self._ed_ts = ''
        self._all_us_posts_success = False
        
        self._us_retrycount = 0
        
        _log.debug('registering rpc routes')
        self.vip.rpc.call(MASTER_WEB, 'register_agent_route'
                            , r'^/VolttronBridge'
                            , "rpc_from_net"
                            ).get(timeout=30)
                            
        #subscribe to price point so that it can be posted to downstream
        if self._bridge_host != 'LEVEL_TAILEND':
            _log.debug("subscribing to pricePoint_topic: " + self.pricePoint_topic)
            self.vip.pubsub.subscribe("pubsub"
                                        , self.pricePoint_topic
                                        , self.on_new_pp
                                        )
            self._ds_register[:] = []
            self._ds_device_ids[:] = []
            self._ds_retrycount[:] = []
            
        #subscribe to energy demand so that it can be posted to upstream
        if self._bridge_host != 'LEVEL_HEAD':
            _log.debug("subscribing to energyDemand_topic: " + self.energyDemand_topic)
            self.vip.pubsub.subscribe("pubsub"
                                        , self.energyDemand_topic
                                        , self.on_new_ed
                                        )
                                        
        #register to upstream
        if self._bridge_host != 'LEVEL_HEAD':
            url_root = 'http://' + self._us_ip_addr + ':' + str(self._us_port) + '/VolttronBridge'
            _log.debug("registering with upstream VolttronBridge: " + url_root)
            self._usConnected = ispace_utils.do_rpc(url_root, 'rpc_register_ds_bridge'
                                                    , {'discovery_address': discovery_address
                                                        , 'deviceId': deviceId
                                                        })
                                                        
        #keep track of us opt_pp_id & bid_pp_id
        if self._bridge_host != 'LEVEL_HEAD':
            self.us_opt_pp_id = 0
            self.us_bid_pp_id = 0
            
        #perodically keeps trying to post ed to us
        if self._bridge_host != 'LEVEL_HEAD':
            self.core.periodic(self._period_process_pp, self.post_us_new_ed, wait=None)
            
        #perodically keeps trying to post pp to ds
        if self._bridge_host != 'LEVEL_TAILEND':
            self.core.periodic(self._period_process_pp, self.post_ds_new_pp, wait=None)
            
        return
        
    @Core.receiver('onstop')
    def onstop(self, sender, **kwargs):
        _log.debug('onstop()')
        self._us_retrycount = 0
        
        if self._bridge_host != 'LEVEL_TAILEND':
            del self._ds_register[:]
            del self._ds_device_ids[:]
            del self._ds_retrycount[:]
            
        if self._bridge_host != 'LEVEL_HEAD':
            _log.debug(self._bridge_host)
            if self._usConnected:
                _log.debug("unregistering with upstream VolttronBridge")
                url_root = 'http://' + self._us_ip_addr + ':' + str(self._us_port) + '/VolttronBridge'
                result = ispace_utils.do_rpc(url_root, 'rpc_unregister_ds_bridge'
                                                , {'discovery_address': self._discovery_address
                                                , 'deviceId': self._deviceId
                                                })
                self._usConnected = False
            
        _log.debug('un registering rpc routes')
        self.vip.rpc.call(MASTER_WEB, 'unregister_all_agent_routes').get(timeout=30)
        
        _log.debug('done!!!')
        return
        
    def _configGetPoints(self):
        self.energyDemand_topic = self.config.get('energyDemand_topic', 'zone/energydemand')
        self.energyDemand_topic_ds = self.config.get('energyDemand_topic_ds', 'smarthub/energydemand')
        self.pricePoint_topic_us = self.config.get('pricePoint_topic_us', 'building/pricepoint')
        self.pricePoint_topic = self.config.get('pricePoint_topic', 'zone/pricepoint')
        return
        
    @RPC.export
    def rpc_from_net(self, header, message):
        _log.debug('rpc_from_net()')
        result = False
        try:
            rpcdata = jsonrpc.JsonRpcData.parse(message)
            '''
            _log.debug('rpc_from_net()...' +
                        ', rpc method: {}'.format(rpcdata.method) +
                        ', rpc params: {}'.format(rpcdata.params))
            '''
            if rpcdata.method == "rpc_register_ds_bridge":
                args = {'discovery_address': rpcdata.params['discovery_address']
                        , 'deviceId':rpcdata.params['deviceId']
                        }
                result = self._register_ds_bridge(**args)
                
            elif rpcdata.method == "rpc_unregister_ds_bridge":
                args = {'discovery_address': rpcdata.params['discovery_address']
                        , 'deviceId':rpcdata.params['deviceId']
                        }
                result = self._unregister_ds_bridge(**args)
                
            elif rpcdata.method == "rpc_post_ed":
                args = {'discovery_address': rpcdata.params['discovery_address']
                        , 'deviceId': rpcdata.params['deviceId']
                        , 'new_ed': rpcdata.params['new_ed']
                        , 'ed_datatype': rpcdata.params['ed_datatype']
                        , 'ed_pp_id': rpcdata.params['ed_pp_id']
                        , 'ed_isoptimal': rpcdata.params['ed_isoptimal']
                        , 'ed_duration': rpcdata.params['ed_duration']
                        , 'ed_ttl': rpcdata.params['ed_ttl']
                        , 'ed_ts': rpcdata.params['ed_ts']
                        }
                #post the new energy demand from ds to the local bus
                result = self._post_ed(**args)
                
            elif rpcdata.method == "rpc_post_pp":
                args = {'discovery_address': rpcdata.params['discovery_address']
                        , 'deviceId':rpcdata.params['deviceId']
                        , 'new_pp': rpcdata.params['new_pp']
                        , 'new_pp_id': rpcdata.params['new_pp_id']
                                    if rpcdata.params['new_pp_id'] is not None
                                    else randint(0, 99999999)
                        , 'new_pp_datatype': rpcdata.params['new_pp_datatype']
                                    if rpcdata.params['new_pp_datatype'] is not None
                                    else {'units': 'cents', 'tz': 'UTC', 'type': 'float'}
                        , 'new_pp_isoptimal': rpcdata.params['new_pp_isoptimal']
                                    if rpcdata.params['new_pp_isoptimal'] is not None
                                    else False
                        , 'new_pp_duration': rpcdata.params['new_pp_duration']
                                    if rpcdata.params['new_pp_duration'] is not None
                                    else 3600
                        , 'new_pp_ttl': rpcdata.params['new_pp_ttl']
                                    if rpcdata.params['new_pp_ttl'] is not None
                                    else -1
                        , 'new_pp_ts': rpcdata.params['new_pp_ts']
                                    if rpcdata.params['new_pp_ts'] is not None
                                    else datetime.datetime.utcnow().isoformat(' ') + 'Z'
                    }
                #post the new new price point from us to the local-us-bus
                result = self._post_pp(**args)
                
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
            
    @RPC.export
    def count_ds_devices(self):
        _log.debug('rpc count_ds_devices(): {}'.format(len(self._ds_register)))
        return len(self._ds_register)
        
    @RPC.export
    def device_id(self):
        return self._deviceId
        
    @RPC.export
    def ip_addr(self):
        return self._this_ip_addr
        
    @RPC.export
    def discovery_address(self):
        return self._discovery_address
    
    #price point on local bus published, post it to all downstream bridges
    def on_new_pp(self, peer, sender, bus,  topic, headers, message):
        if self._bridge_host == 'LEVEL_TAILEND':
            return
            
        if sender != 'iiit.pricecontroller':
            return
            
        #all pp ids are valid
        valid_pp_ids = []
        
        #mandatory fields in the message
        mandatory_fields = [ParamPP.idx_pp
                            , ParamPP.idx_pp_datatype
                            , ParamPP.idx_pp_id
                            , ParamPP.idx_pp_isoptimal
                            , ParamPP.idx_pp_duration
                            , ParamPP.idx_pp_ttl
                            , ParamPP.idx_pp_ts
                            ]
                            
        #check for msg validity, pp_id, timeout, etc., also _log.info(message) if a valid msg
        valid_msg = ispace_utils.sanity_check_pp(message, mandatory_fields, valid_pp_ids)
        if not valid_msg:
            return
            
        #store pp data to global to be retrived later
        self._pp_current = message[ParamPP.idx_pp]
        self._pp_datatype = message[ParamPP.idx_pp_datatype]
        self._pp_id = message[ParamPP.idx_pp_id]
        self._pp_isoptimal = message[ParamPP.idx_pp_isoptimal]
        self._pp_duration = message[ParamPP.idx_pp_duration]
        self._pp_ttl = message[ParamPP.idx_pp_ttl]
        self._pp_ts = message[ParamPP.idx_pp_ts]
        
        #keep a track of local pp_ids
        if self._pp_id not in [self.us_opt_pp_id, self.us_bid_pp_id]:
            if self._pp_isoptimal: 
                self.local_opt_pp_id = self._pp_id 
            else : 
                self.local_bid_pp_id = self._pp_id
                
        #reset counters & flags
        self._reset_ds_retrycount()
        self._all_ds_posts_success  = False
        
        #initiate ds post
        self.post_ds_new_pp()
        return
        
    #energy demand on local bus published, post it to upstream bridge
    def on_new_ed(self, peer, sender, bus,  topic, headers, message):
        if self._bridge_host == 'LEVEL_HEAD':
            #do nothing
            return
            
        #post ed to us only if pp_id corresponds to these ids (i.e., ed for either us opt_pp_id or bid_pp_id)
        valid_pp_ids = [self.us_opt_pp_id, self.us_bid_pp_id, self.local_opt_pp_id, self.local_bid_pp_id]
        
        #mandatory fields in the message
        mandatory_fields = [ParamPP.idx_ed
                            , ParamPP.idx_ed_datatype
                            , ParamPP.idx_ed_pp_id
                            , ParamPP.idx_ed_isoptimal
                            , ParamPP.idx_ed_device_id
                            , ParamPP.idx_pp_duration
                            , ParamPP.idx_pp_ttl
                            ,ParamPP.idx_pp_ts
                            ]
                            
        #check for msg validity, pp_id, timeout, etc., also _log.info(message) if a valid msg
        valid_msg = ispace_utils.sanity_check_ed(message, mandatory_fields, valid_pp_ids)
        if not valid_msg:
            return
            
        self._ed_current = message[ParamED.idx_ed]
        self._ed_datatype = message[ParamED.idx_ed_datatype]
        self._ed_pp_id = message[ParamED.idx_ed_pp_id]
        self._ed_isoptimal = message[ParamED.idx_ed_isoptimal]
        self._ed_duration = message[ParamED.idx_ed_duration]
        self._ed_ttl = message[ParamED.idx_ed_ttl]
        self._ed_ts = message[ParamED.idx_ed_ts]
        
        #reset counters & flags
        self._us_retrycount = 0
        self._all_us_posts_success = False
        
        #initiate us post
        self.post_us_new_ed()
        return
        
    #perodically keeps trying to post ed to us
    def post_us_new_ed(self):
        if self._all_us_posts_success:
            #_log.debug('all us posts success, do nothing')
            return
        
        url_root = 'http://' + self._us_ip_addr + ':' + str(self._us_port) + '/VolttronBridge'
        
        #check for upstream connection, if not retry once
        _log.debug('check us connection...')
        if not self._usConnected:
            _log.debug('not connected, Trying to register once...')
            self._usConnected = self._register_to_us_bridge(url_root
                                                            , self._discovery_address
                                                            , self._deviceId
                                                            )
            if not self._usConnected:
                _log.debug('_usConnected: ' + str(self._usConnected))
                _log.debug('Failed to register, May be upstream bridge is not running!!!')
                return
                
        _log.debug('_usConnected: ' + str(self._usConnected))
        
        _log.debug("posting energy demand to upstream VolttronBridge")
        success = ispace_utils.do_rpc(url_root, 'rpc_post_ed'
                                        , {'discovery_address': self._discovery_address
                                        , 'deviceId': self._deviceId
                                        , 'new_ed': self._ed_current
                                        , 'ed_datatype': self._ed_datatype
                                        , 'ed_pp_id': self._ed_pp_id
                                        , 'ed_isoptimal': self._ed_isoptimal
                                        , 'ed_duration': self._ed_duration
                                        , 'ed_ttl': self._ed_ttl
                                        , 'ed_ts': self._ed_ts
                                        })
        #_log.debug('success: ' + str(success))
        if success:
            _log.debug("Success!!!")
            self._us_retrycount = 0
            self._ed_previous = self._ed_current
            self._all_us_posts_success  = True
        else:
            _log.debug("Failed!!!")
            self._us_retrycount = self._us_retrycount + 1
            if self._us_retrycount > MAX_RETRIES:
                _log.debug('failed too many times to post ed, reset counter and yeild for a movement!!!')
                self._usConnected = False
                self._us_retrycount = 0
                time.sleep(10) #yeild for a movement
                
        return
        
    #perodically keeps trying to post pp to ds
    def post_ds_new_pp(self):
        if self._all_ds_posts_success:
            #_log.debug('all ds posts success, do nothing')
            return
            
        self._all_ds_posts_success  = True          #assume all ds post success, if any failed set to False
        for discovery_address in self._ds_register:
            index = self._ds_register.index(discovery_address)
            
            if self._ds_retrycount[index] > MAX_RETRIES:
                #maybe already posted or failed more than max retries, do nothing
                continue
                
                
            '''before posting to ds, dcrement ttl and update ts
            #decrement the ttl by time consumed to process till now + 1 sec
            decrement_status = pp_msg.decrement_ttl()
            if decrement_status and pp_msg.get_ttl() == 0:
                _log.warning('msg ttl expired on decrement_ttl(), do nothing!!!')
                return False
            elif decrement_status:
                _log.info('new ttl: {}.'.format(pp_msg.get_ttl()))
            update_ts()
            '''
            url_root = 'http://' + discovery_address + '/VolttronBridge'
            result = ispace_utils.do_rpc(url_root, 'rpc_post_pp'
                                        , {'discovery_address': self._discovery_address
                                        , 'deviceId': self._deviceId
                                        , 'new_pp': self._pp_current
                                        , 'new_pp_id': self._pp_id
                                        , 'new_pp_isoptimal': self._pp_isoptimal
                                        , 'new_pp_datatype': self._pp_datatype
                                        , 'new_pp_duration': self._pp_duration
                                        , 'new_pp_ttl': self._pp_ttl
                                        , 'new_pp_ts': self._pp_ts
                                        })
            if result:
                #success, reset retry count
                self._ds_retrycount[index] = MAX_RETRIES + 1    #no need to retry on the next run
                _log.debug("post to:" + discovery_address + " sucess!!!")
            else:
                #failed to post, increment retry count
                self._ds_retrycount[index] = self._ds_retrycount[index]  + 1
                _log.debug("post to:" + discovery_address +
                            " failed, count: {0:d} !!!".format(self._ds_retrycount[index]))
                self._all_ds_posts_success  = False
                    
        return
        
    def _register_ds_bridge(self, discovery_address, deviceId):
        _log.debug('_register_ds_bridge(), discovery_address: ' + discovery_address 
                    + ' deviceId: ' + deviceId
                    )
        if discovery_address in self._ds_register:
            _log.debug('already registered!!!')
            index = self._ds_register.index(discovery_address)
            self._ds_retrycount[index] = 0
            return True
            
        #TODO: potential bug in this method, not atomic
        self._ds_register.append(discovery_address)
        index = self._ds_register.index(discovery_address)
        self._ds_device_ids.insert(index, deviceId)
        self._ds_retrycount.insert(index, 0)
        
        _log.debug('registered!!!')
        return True
        
    def _unregister_ds_bridge(self, discovery_address, deviceId):
        _log.debug('_unregister_ds_bridge(), discovery_address: '+ discovery_address 
                    + ' deviceId: ' + deviceId
                    )
        if discovery_address not in self._ds_register:
            _log.debug('already unregistered')
            return True
            
        #TODO: potential bug in this method, not atomic
        index = self._ds_register.index(discovery_address)
        self._ds_register.remove(discovery_address)
        del self._ds_device_ids[index]
        del self._ds_retrycount[index]
        _log.debug('unregistered!!!')
        return True
        
    def _reset_ds_retrycount(self):
        for discovery_address in self._ds_register:
            index = self._ds_register.index(discovery_address)
            self._ds_retrycount[index] = 0
        return
        
    #post the new price point from us to the local-us-bus
    def _post_pp(self, discovery_address
                        , deviceId
                        , new_pp
                        , new_pp_datatype
                        , new_pp_id
                        , new_pp_isoptimal
                        , new_pp_ttl
                        , new_pp_ts
                        ):
        ispace_utils.print_pp(self, 'pp from us'
                                    , new_pp
                                    , new_pp_datatype
                                    , new_pp_id
                                    , new_pp_isoptimal
                                    , discovery_address
                                    , deviceId
                                    , new_pp_ttl
                                    , new_pp_ts
                                    )
                                    
        #keep a track of us pp_ids
        if new_pp_isoptimal:
            self.us_opt_pp_id = new_pp_id
        else:
            self.us_bid_pp_id = new_pp_id
            
        #post to bus
        _log.debug('post to the local-us-bus')
        pubTopic =  self.pricePoint_topic_us
        pubMsg = [new_pp
                    , new_pp_datatype
                    , new_pp_id
                    , new_pp_isoptimal
                    , discovery_address
                    , deviceId
                    , new_pp_ttl
                    , new_pp_ts
                    ]
        ispace_utils.publish_to_bus(self, pubTopic, pubMsg)
        _log.debug('...Done!!!')
        return True
        
    #post the new energy demand from ds to the local bus
    def _post_ed(self, discovery_address
                        , deviceId
                        , new_ed
                        , ed_datatype
                        , ed_pp_id
                        , ed_isoptimal
                        , ed_duration
                        , ed_ttl
                        , ed_ts
                        ):
        ispace_utils.print_ed(self, 'ed from ds'
                                    , new_ed
                                    , ed_datatype
                                    , ed_pp_id
                                    , ed_isoptimal
                                    , discovery_address
                                    , deviceId
                                    , ed_duration
                                    , ed_ttl
                                    , ed_ts
                                    )
                                    
        if not self._msg_from_registered_ds(discovery_address, deviceId):
            #either the post to ds failed in previous iteration and de-registered from the _ds_register
            # or the msg is corrupted
            _log.warning('msg not from registered ds, do nothing!!!')
            return False
            
        #process ed only if pp_id corresponds to either us/local opt/bid pp_ids)
        valid_pp_ids = [self.us_opt_pp_id, self.us_bid_pp_id, self._pp_id]
        if ed_pp_id not in [self.us_opt_pp_id, self.us_bid_pp_id, self._pp_id]:
            _log.debug('pp_id: {}'.format(message[ParamPP.idx_pp_id])
                    + ' not in valid_pp_ids: {}, do nothing!!!'.format(valid_pp_ids))
            return False
            
        #process ed only if msg is alive (didnot timeout)
        if ispace_utils.ttl_timeout(message[ParamPP.idx_ed_pp_ts], message[ParamPP.idx_ed_pp_ttl]):
            _log.warning('msg timed out, do nothing')
            return False
            
        #post to bus
        _log.debug('post the local-ds-bus')
        pubTopic = self.energyDemand_topic_ds + "/" + deviceId
        pubMsg = [new_ed
                    , ed_datatype
                    , ed_pp_id
                    , ed_isoptimal
                    , discovery_address
                    , deviceId
                    , ed_duration
                    , ed_ttl
                    , ed_ts
                    ]
        ispace_utils.publish_to_bus(self, pubTopic, pubMsg)
        #at this stage, ds is alive, reset the counter
        self._ds_retrycount[self._ds_register.index(discovery_address)] = 0
        _log.debug('...Done!!!')
        return True
        
    def _msg_from_registered_ds(self, discovery_address, device_id):
        return (True if discovery_address in self._ds_register
                     and device_id == self._ds_device_ids[self._ds_register.index(discovery_address)]
                     else False)
                     
                     
def main(argv=sys.argv):
    '''Main method called by the eggsecutable.'''
    try:
        utils.vip_main(volttronbridge)
    except Exception as e:
        print (e)
        _log.exception('unhandled exception')
        
        
if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv))
    except KeyboardInterrupt:
        pass
        
        
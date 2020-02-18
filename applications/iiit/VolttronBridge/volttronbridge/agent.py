# -*- coding: utf-8 -*- {{{
# vim: set fenc=utf-8 ft=python sw=4 ts=4 sts=4 et:
#
# Copyright (c) 2020, Sam Babu, Godithi.
# All rights reserved.
#
#
# IIIT Hyderabad

# }}}

# Sam

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
        INVALID_REQUEST, METHOD_NOT_FOUND, PARSE_ERROR,
        UNHANDLED_EXCEPTION, UNAUTHORIZED,
        UNABLE_TO_REGISTER_INSTANCE, DISCOVERY_ERROR,
        UNABLE_TO_UNREGISTER_INSTANCE, UNAVAILABLE_PLATFORM, INVALID_PARAMS,
        UNAVAILABLE_AGENT)

from random import randint
from copy import copy

import time
import gevent
import gevent.event

from ispace_utils import do_rpc, register_rpc_route, publish_to_bus
from ispace_msg import ISPACE_Msg, MessageType
from ispace_msg_utils import (
        parse_bustopic_msg, check_msg_type,
        parse_jsonrpc_msg, get_default_pp_msg,
        get_default_ed_msg, valid_bustopic_msg)

utils.setup_logging()
_log = logging.getLogger(__name__)
__version__ = '0.4'

# checking if a floating point value is 'numerically zero'
# by checking if it is lower than epsilon
EPSILON = 1e-04

'''
if the rpc connection fails to post for more than MAX_RETRIES, then it is
assumed that the dest is down. In case of ds posts, the retry count is reset
when the ds registers again or on a new price point. In case of us posts, the
retry count is reset when change in ed. Also if failed too many times to post
ed, retry count is reset and yeild till next ed msg.
'''
MAX_RETRIES = 5


def volttronbridge(config_path, **kwargs):
    config = utils.load_config(config_path)
    vip_identity = config.get('vip_identity', 'iiit.volttronbridge')
    # This agent needs to be named iiit.volttronbridge.
    # Pop the uuid id off the kwargs
    kwargs.pop('identity', None)

    Agent.__name__ = 'VolttronBridge_Agent'
    return VolttronBridge(config_path, identity=vip_identity, **kwargs)


class VolttronBridge(Agent):
    ''' Voltron Bridge
    Retrive the data from volttron bus and publish it to upstream or downstream
    volttron instance. If posting to downstream, then the data is pricepoint
    and if posting to upstream then the data is energy demand or active power

    The assumption is that for up stream (us), the bridge communicates with
    only one instance and for the down stream (ds), the bridge would be posting
    to multiple devices.
            price point one-to-many communication
            energy demand one-to-one communication
            active power one-to-one communication

    The ds devices on their start up would register with upstream bridge

    The bridge is aware of the upstream devices and registers to it.
    Also, as and when there is a change in energy demand, the same is posted to
    the upstream bridges.

    Whereas the the bridge does not know the downstream devices upfront.
    As and when the downstram bridges register to the bridge, the bridge starts
    posting the messages (pricepoint) to them.
    '''
    # initialized  during __init__ from config
    _topic_energy_demand = None
    _topic_energy_demand_ds = None
    _topic_price_point_us = None
    _topic_price_point = None

    def __init__(self, config_path, **kwargs):
        super(VolttronBridge, self).__init__(**kwargs)
        _log.debug('vip_identity: ' + self.core.identity)

        self.config = utils.load_config(config_path)
        self._config_get_points()
        return

    @Core.receiver('onsetup')
    def setup(self, sender, **kwargs):
        _log.info(self.config['message'])
        self._agent_id = self.config['agentid']

        self._usConnected = False
        self._bridge_host = self.config.get('bridge_host', 'LEVEL_HEAD')
        self._device_id = self.config.get('device_id', 'Building-1')

        self._this_ip_addr = self.config.get('ip_addr', '192.168.1.51')
        self._this_port = int(self.config.get('port', 8082))

        self._period_process_pp = int(self.config.get('period_process_pp', 10))

        # register to keep track of local agents
        # posting active power or energy demand
        self._local_devices_register = []   # vip_identities
        self._local_device_ids = []         # device_ids

        #queues to store us price and ds energy messages
        self._us_pp_messages = []
        self._ds_ed_messages = []

        if self._bridge_host != 'LEVEL_TAILEND':
            _log.debug(self._bridge_host)

            # downstream volttron instances
            # post price point to these instances
            self._ds_register = []          # ds discovery_addresses
            self._ds_device_ids = []        # ds device_ids
            self._ds_retrycount = []

        if self._bridge_host != 'LEVEL_HEAD':
            _log.debug(self._bridge_host)

            # upstream volttron instance
            self._us_ip_addr = self.config.get('us_ip_addr', '192.168.1.51')
            self._us_port = int(self.config.get('us_port', 8082))
            _log.debug('self._us_ip_addr: {}'.format(self._us_ip_addr) +
                ' self._us_port: '.format(self._us_port))

        self._discovery_address = '{}:{}'.format(self._this_ip_addr
                                                , self._this_port)
        _log.debug('self._discovery_address:'
                                + ' {}'.format(self._discovery_address))
        return

    @Core.receiver('onstart')
    def startup(self, sender, **kwargs):
        _log.info('Starting Bridge...')
        _log.debug(self._bridge_host)

        # register rpc routes with MASTER_WEB
        # register_rpc_route is a blocking call
        register_rpc_route(self, 'bridge', 'rpc_from_net', 5)

        # price point
        self._valid_senders_list_pp = ['iiit.pricecontroller']

        # TODO: relook -- impl queues?
        # can expect multiple pp_msgs on the bus before previous successfully
        # posted to ds
        self.tmp_bustopic_pp_msg = get_default_pp_msg(self._discovery_address
                                                    , self._device_id)
        self.tmp_bustopic_ed_msg = get_default_ed_msg(self._discovery_address
                                                    , self._device_id)

        self._all_ds_posts_success = True
        self._all_us_posts_success = True
        self._us_retrycount = 0

        self.local_opt_pp_id = randint(0, 99999999)
        self.local_bid_pp_id = randint(0, 99999999)

        # subscribe to price point so that it can be posted to downstream
        if self._bridge_host != 'LEVEL_TAILEND':
            _log.debug('subscribing to _topic_price_point:'
                        + ' {}'.format(self._topic_price_point))
            self.vip.pubsub.subscribe('pubsub'
                                        , self._topic_price_point
                                        , self.on_new_pp
                                        )
            self._ds_register[:] = []
            self._ds_device_ids[:] = []
            self._ds_retrycount[:] = []

        # subscribe to energy demand so that it can be posted to upstream
        if self._bridge_host != 'LEVEL_HEAD':
            _log.debug('subscribing to _topic_energy_demand:'
                        + ' {}'.format(self._topic_energy_demand))
            self.vip.pubsub.subscribe('pubsub'
                                        , self._topic_energy_demand
                                        , self.on_new_ed
                                        )

        # register to upstream
        if self._bridge_host != 'LEVEL_HEAD':
            url_root = 'http://{}:{}/bridge'.format(self._us_ip_addr
                                                    , self._us_port)
            _log.debug('registering with upstream: ' + url_root)
            args = {'discovery_address': self._discovery_address
                    , 'device_id': self._device_id
                    }
            self._usConnected = do_rpc(self._agent_id, url_root, 'dsbridge'
                                                            , args
                                                            , 'POST')
        # keep track of us opt_pp_id & bid_pp_id
        if self._bridge_host != 'LEVEL_HEAD':
            self.us_opt_pp_id = randint(0, 99999999)
            self.us_bid_pp_id = randint(0, 99999999)

        # perodically keeps trying to post ed to us
        if self._bridge_host != 'LEVEL_HEAD':
            self.core.periodic(self._period_process_pp
                                , self.post_us_new_ed
                                , wait=None)

        # perodically keeps trying to post pp to ds
        if self._bridge_host != 'LEVEL_TAILEND':
            self.core.periodic(self._period_process_pp
                                , self.post_ds_new_pp
                                , wait=None)
            
        _log.info('startup() - Done. Agent is ready')
        return

    @Core.receiver('onstop')
    def onstop(self, sender, **kwargs):
        _log.debug('onstop()')
        self._us_retrycount = 0
        
        del self._local_devices_register[:]
        del self._local_device_ids[:]
        
        if self._bridge_host != 'LEVEL_TAILEND':
            del self._ds_register[:]
            del self._ds_device_ids[:]
            del self._ds_retrycount[:]
            
        if self._bridge_host != 'LEVEL_HEAD':
            _log.debug(self._bridge_host)
            if self._usConnected:
                try:
                    _log.debug('unregistering with upstream VolttronBridge')
                    url_root = 'http://' + self._us_ip_addr \
                                        + ':' + str(self._us_port) \
                                        + '/bridge'
                    args = {'discovery_address': self._discovery_address
                            , 'device_id': self._device_id
                            }
                    result = do_rpc(self._agent_id, url_root, 'dsbridge'
                                                            , args
                                                            , 'DELETE')
                except Exception as e:
                    _log.exception('Failed to unregister with upstream'
                                    + ', message: {}'.format(e.message))
                    pass
                self._usConnected = False
            
        _log.debug('un registering rpc routes')
        self.vip.rpc.call(MASTER_WEB
                            , 'unregister_all_agent_routes').get(timeout=30)
        
        _log.debug('done!!!')
        return

    def _config_get_points(self):
        #default config point for zone vb
        self._topic_energy_demand = self.config.get('energyDemand_topic'
                                                    , 'zone/energydemand')
        self._topic_energy_demand_ds = self.config.get('energyDemand_topic_ds'
                                                    , 'ds/energydemand')
        self._topic_price_point_us = self.config.get('pricePoint_topic_us'
                                                    , 'us/pricepoint')
        self._topic_price_point = self.config.get('pricePoint_topic'
                                                    , 'zone/pricepoint')
        return

    @RPC.export
    def rpc_from_net(self, header, message):
        result = False
        try:
            rpcdata = jsonrpc.JsonRpcData.parse(message)
            _log.debug('rpc_from_net()...'
                        # + 'header: {}'.format(header)
                        + ', rpc method: {}'.format(rpcdata.method)
                        # + ', rpc params: {}'.format(rpcdata.params)
                        )
            if rpcdata.method == 'ping':
                result = True
            elif (rpcdata.method == 'dsbridge'
                    and header['REQUEST_METHOD'].upper() == 'GET'):
                result = self._get_ds_bridge_status(rpcdata.id, message)
            elif (rpcdata.method == 'dsbridge'
                    and header['REQUEST_METHOD'].upper() == 'POST'):
                result = self._register_ds_bridge(rpcdata.id, message)
            elif (rpcdata.method == 'dsbridge'
                    and header['REQUEST_METHOD'].upper() == 'DELETE'):
                result = self._unregister_ds_bridge(rpcdata.id, message)
            elif (rpcdata.method == 'energy'
                    and header['REQUEST_METHOD'].upper() == 'POST'):
                # post the new energy demand from ds to the local bus
                result = self._post_ed(rpcdata.id, message)
            elif (rpcdata.method == 'pricepoint'
                    and header['REQUEST_METHOD'].upper() == 'POST'):
                # post the new new price point from us to the local-us-bus
                result = self._post_pp(rpcdata.id, message)
            else:
                msg = 'Invalid params {}'.format(rpcdata.method)
                error = jsonrpc.json_error(rpcdata.id, METHOD_NOT_FOUND, msg)
                return error
        except KeyError as ke:
            msg = 'Invalid params {}'.format(rpcdata.params)
            error = jsonrpc.json_error(rpcdata.id, INVALID_PARAMS, msg)
            return error
        except Exception as e:
            msg = 'Oops!!! Unhandled exception {}'.format(e.message)
            error = jsonrpc.json_error(rpcdata.id, UNHANDLED_EXCEPTION, msg)
            return error
        return (jsonrpc.json_result(rpcdata.id, result) if result else result)

    @RPC.export
    def ping(self):
        return True

    @RPC.export
    def get_ds_device_ids(self):
        return (self._ds_device_ids 
                if self._bridge_host != 'LEVEL_TAILEND'
                else [])
        
    @RPC.export
    def local_ed_agents(self):
        # return local ed agents vip_identities
        return self._local_devices_register

    @RPC.export
    def get_local_device_ids(self):
        return self._local_device_ids

    @RPC.export
    def count_ds_devices(self):
        return (len(self._ds_device_ids)
                if self._bridge_host != 'LEVEL_TAILEND'
                else 0)

    @RPC.export
    def count_local_devices(self):
        return len(self._local_device_ids)

    @RPC.export
    def device_id(self):
        return self._device_id

    @RPC.export
    def ip_addr(self):
        return self._this_ip_addr

    @RPC.export
    def discovery_address(self):
        return self._discovery_address

    @RPC.export
    def register_local_ed_agent(self, sender, device_id):
        if device_id is None: return False

        _log.debug('register_local_ed_agent(), sender: ' + sender 
                    + ' device_id: ' + device_id
                    )
        if sender in self._local_devices_register:
            _log.debug('already registered!!!')
            return True
        self._local_devices_register.append(sender)
        index = self._local_devices_register.index(sender)
        self._local_device_ids.insert(index, device_id)
        _log.debug('registered!!!')
        return True

    @RPC.export
    def unregister_local_ed_agent(self, sender):
        _log.debug('unregister_local_ed_agent(), sender: '.format(sender))
        if sender not in self._local_devices_register:
            _log.debug('already unregistered')
            return True
        index = self._local_devices_register.index(sender)
        self._local_devices_register.remove(sender)
        del self._local_device_ids[index]
        _log.debug('unregistered!!!')
        return True

    # price point on local bus published, post it to all downstream bridges
    def on_new_pp(self, peer, sender, bus,  topic, headers, message):
        if self._bridge_host == 'LEVEL_TAILEND': return

        # handle only pp type message
        if check_msg_type(message, MessageType.price_point): pass
        else: return

        # process only pca posted pp message
        valid_senders_list = ['iiit.pricecontroller']
        minimum_fields = ['value', 'price_id']
        validate_fields = ['value', 'price_id', 'isoptimal']
        valid_price_ids = []
        (success, pp_msg) = valid_bustopic_msg(sender, valid_senders_list
                                                , minimum_fields
                                                , validate_fields
                                                , valid_price_ids
                                                , message)
        if not success or pp_msg is None: return
        else: 
            hint = 'New price point (pp)'
            _log.debug('{} msg on the local-bus'.format(hint)
                        + ', topic: {} ...'.format(topic))

        if pp_msg.get_isoptimal():
            _log.debug('***** New optimal price point from local:'
                        + ' {:0.2f}'.format(pp_msg.get_value())
                        + ' price_id: {}'.format(pp_msg.get_price_id())
                        )
            self.local_opt_pp_id = pp_msg.get_price_id()
        else :
            _log.debug('***** New bid price point from local:'
                        + ' {:0.2f}'.format(pp_msg.get_value())
                        + ' price_id: {}'.format(pp_msg.get_price_id())
                        )
            self.local_bid_pp_id = pp_msg.get_price_id()

        #self.tmp_bustopic_pp_msg = copy(pp_msg)
        self._us_pp_messages.append(copy(pp_msg))

        # reset counters & flags
        self._reset_ds_retrycount()
        #this flag activates post_ds_new_pp()
        self._all_ds_posts_success = False

        '''
            DONT call post_ds_new_pp() directly at this stage.
            It is blocking us do_rpc connection that in turn is timed out
            '''
        # initiate ds post
        #_log.debug('posting to ds...')
        #self.tmp_bustopic_pp_msg = copy(pp_msg)
        #self.post_ds_new_pp()
        #_log.debug('done.')
        return

    # energy demand on local bus published, post it to upstream bridge
    def on_new_ed(self, peer, sender, bus,  topic, headers, message):
        if self._bridge_host == 'LEVEL_HEAD': return

        self.tmp_bustopic_pp_msg = None

        # handle only ap or ed type messages
        if check_msg_type(message, MessageType.active_power): pass
        elif check_msg_type(message, MessageType.energy_demand): pass
        else: return

        # process only pca posted ed message
        valid_senders_list = ['iiit.pricecontroller']
        minimum_fields = ['value', 'price_id']
        validate_fields = ['value', 'price_id', 'isoptimal']
        valid_price_ids = ([self.us_opt_pp_id, self.us_bid_pp_id] 
                                if self._bridge_host != 'LEVEL_HEAD' 
                                else [])
        (success, ed_msg) = valid_bustopic_msg(sender, valid_senders_list
                                                , minimum_fields
                                                , validate_fields
                                                , valid_price_ids
                                                , message)
        if not success or ed_msg is None: 
            _log.warning('valid_bustopic_msg success: {}'.format(success)
                        + ', is ed_msg None? ed_msg: {}'.format(ed_msg))
            return
        else:
            hint = ('New active power (ap)'
                    if ed_msg.get_msg_type() == MessageType.active_power
                    else 'New energy demand (ed)')
            _log.debug('{} msg on the local-bus'.format(hint)
                        + ', topic: {} ...'.format(topic))

        self.tmp_bustopic_ed_msg = copy(ed_msg)

        # reset counters & flags
        self._us_retrycount = 0
        #this flag activates post_us_new_ed()
        self._all_us_posts_success = False

        # initiate us post
        #_log.debug('posting to us...')
        #self.tmp_bustopic_ed_msg = copy(ed_msg)
        # will run once, if failed perodically retries
        #self.post_us_new_ed()
        #_log.debug('done.')
        return

    # perodically keeps trying to post ed to us
    def post_us_new_ed(self):
        if self._all_us_posts_success: return

        url_root = 'http://{}:{}/bridge'.format(self._us_ip_addr
                                                , self._us_port)
        # check for upstream connection, if not retry once
        _log.debug('check us connection...')
        if not self._usConnected:
            _log.debug('not connected, Trying to register once...')
            args = {'discovery_address': self._discovery_address
                    , 'device_id': self._device_id
                    }
            self._usConnected = do_rpc(self._agent_id, url_root, 'dsbridge'
                                                            , args
                                                            , 'POST')
            if not self._usConnected:
                _log.debug('Is us connected?'
                            + 'do_rpc result: {}'.format(self._usConnected)
                            + ', Failed to register'
                            + ', may be upstream bridge is not running!!!')
                return
        _log.debug('_usConnected: {}'.format(self._usConnected))

        _log.debug('posting energy demand to upstream...')
        args = self.tmp_bustopic_ed_msg.get_json_params()
        success = do_rpc(self._agent_id, url_root, 'energy'
                                                , args
                                                , 'POST')
        # _log.debug('success: ' + str(success))
        if success:
            _log.debug('Success!!!')
            self._us_retrycount = 0
            self._all_us_posts_success  = True
        else:
            _log.debug('Failed to post pp to us'
                        + ', url_root: {}'.format(url_root)
                        + ', result: {}'.format(success))
            self._us_retrycount = self._us_retrycount + 1
            if self._us_retrycount > MAX_RETRIES:
                _log.debug('Failed too many times to post ed to up stream'
                            + ', reset counters and yeild till next ed msg.')
                self._usConnected = False
                self._us_retrycount = 0
        return

    # perodically keeps trying to post pp to ds
    # ensure that only failed in previous iterations and the new msg are sent
    def post_ds_new_pp(self):
        _log.debug('post_ds_new_pp()...')
        if self._all_ds_posts_success: return

        # assume all ds post success, if any failed set to False
        self._all_ds_posts_success  = True

        msg_count = self._us_pp_messages.count()
        _log.debug('self._us_pp_messages.count(): {:d}...'.format(msg_count))
        for idx, pp_msg in enumerate(self._us_pp_messages):
            _log.debug('processing msg {:d}/{:d}'.(format(idx, msg_count))
                        + ', price id: {}'.format(pp_msg.get_price_id()))
            # ttl <= -1 --> live forever
            # ttl == 0 --> ttl timed out
            # decrement_status == False, if ttl <= -1 or unknown tz
            # before posting to ds, dcrement ttl and update ts
            # decrement the ttl by time consumed to process till now + 1 sec
            decrement_status = pp_msg.decrement_ttl()
            if decrement_status and pp_msg.get_ttl() == 0:
                _log.warning('msg ttl expired on decrement_ttl()'
                                + ', droping the message!!!')
                #remove msg from the queue
                del self._us_pp_messages[idx]
                continue
            elif decrement_status:
                _log.debug('new ttl: {}.'.format(pp_msg.get_ttl()))
                pp_msg.update_ts()

            msg_1_to_1 = pp_msg.get_one_to_one()
            if msg_1_to_1: self._ds_rpc_1_to_1(pp_msg)
            else: self._ds_rpc_1_to_m(pp_msg)

            if self._all_ds_posts_success:
                #remove msg from the queue
                log.debug('msg successfully posted to'
                            + 'ds' if msg_1_to_1 else 'all ds'
                            + ', removing it from the queue')
                del self._us_pp_messages[idx]

                #reset the retry counter for success ds msg
                if not pp_msg.get_one_to_one():
                    for index in self._ds_retrycount:
                        if self._ds_retrycount[index] == -1:
                            self._ds_retrycount[index] = 0
            else:
                self._all_ds_posts_success  = False

            self._clean_ds_registry()
            
            # try continue with other messages
            continue

        _log.debug('post_ds_new_pp()...done')
        return

    def _ds_rpc_1_to_1(self, pp_msg):
        _log.debug('_ds_rpc_1_to_1()...')
        discovery_address = pp_msg.get_dst_ip()
        url_root = 'http://' + discovery_address + '/bridge'
        result = do_rpc(self._agent_id, url_root, 'pricepoint'
                                , pp_msg.get_json_params()
                                , 'POST')
        self._all_ds_posts_success  = result
        _log.debug('_ds_rpc_1_to_1()...done')
        return

    def _ds_rpc_1_to_m(self, pp_msg):
        _log.debug('_ds_rpc_1_to_m()...')
        # case pp_msg one-to-many(i.e., one_to_one is not True)
        # create list of ds devices to which pp_msg need to be posted
        url_roots = []
        main_idx = []
        for discovery_address in self._ds_register:
            index = self._ds_register.index(discovery_address)

            # if already posted, do nothing
            if self._ds_retrycount[index] == -1: continue

            url_roots.append('http://' + discovery_address + '/bridge')
            #keep track of main index
            main_idx.append(index)

        # use gevent for concurrent do rpc requests for posting pp msg to the
        # ds devices
        jobs = [gevent.spawn(do_rpc, self._agent_id, url_root, 'pricepoint'
                                , pp_msg.get_json_params()
                                , 'POST'
                                ) for url_root in url_roots
                                ]
        gevent.joinall(jobs, timeout=11)

        for idx, job in enumerate(jobs):
            index = main_idx[idx]
            success = job.value
            discovery_address = self._ds_register[index]
            device_id = self._ds_device_ids[index]
            if success:
                # success, reset retry count
                # no need to retry on the next run
                self._ds_retrycount[index] = -1
                _log.debug('post pp to ds ({})'.format(device_id)
                            + ', result: success!!!')
            else:
                # failed to post
                # set the failed flag and also increment retry count
                self._all_ds_posts_success  = False
                self._ds_retrycount[index] = self._ds_retrycount[index] + 1
                _log.debug('failed to post pp to ds ({})'.format(device_id)
                            + ', failed count:'
                            + ' {:d}'.format(self._ds_retrycount[index])
                            + ', will try again in'
                            + ' {} sec!!!'.format(self._period_process_pp)
                            + ', result: {}'.format(success))
        _log.debug('_ds_rpc_1_to_m()...done.')
        return

    def _clean_ds_registry(self):
        # check & cleanup the ds registery
        for index, retry_count in enumerate(self._ds_retrycount):
            if retry_count < MAX_RETRIES: continue
            #else failed too many times, unregister the ds device
            device_id = self._ds_device_ids[index]
            # failed more than max retries, unregister the ds device
            _log.debug('post pp to ds: {}'.format(device_id)
                        + ' failed more than MAX_RETRIES:'
                        + ' {:d}'.format(MAX_RETRIES)
                        + ', ds unregistering...'
                        )
            del self._ds_register[index]
            del self._ds_device_ids[index]
            del self._ds_retrycount[index]
            _log.debug('unregistered!!!')
    return

    # check if the ds is registered with this bridge
    def _get_ds_bridge_status(self, rpcdata_id, message):
        # TODO: catch jsonrpc parse exception
        params = jsonrpc.JsonRpcData.parse(message).params
        discovery_address = params['discovery_address']
        device_id = params['device_id']
        if discovery_address in self._ds_register:
            index = self._ds_register.index(discovery_address)
            if device_id == self._ds_device_ids[index]:
                result = True
        return False

    def _register_ds_bridge(self, rpcdata_id, message):
        # TODO: catch jsonrpc parse exception
        params = jsonrpc.JsonRpcData.parse(message).params
        discovery_address = params['discovery_address']
        device_id = params['device_id']
        _log.debug('_register_ds_bridge()'
                    + ', discovery_address: {}'.format(discovery_address)
                    + ', device_id: {}'.format( device_id))

        if discovery_address in self._ds_register:
            index = self._ds_register.index(discovery_address)
            # the ds is alive, reset retry counter if any
            self._ds_retrycount[index] = 0
            _log.debug('already registered!!!')
            return True

        self._ds_register.append(discovery_address)
        index = self._ds_register.index(discovery_address)
        self._ds_device_ids.insert(index, device_id)
        self._ds_retrycount.insert(index, 0)
        _log.debug('registered!!!')
        return True

    def _unregister_ds_bridge(self, rpcdata_id, message):
        params = jsonrpc.JsonRpcData.parse(message).params
        discovery_address = params['discovery_address']
        device_id = params['device_id']
        _log.debug('_unregister_ds_bridge()'
                    + ', discovery_address: {}'.format(discovery_address)
                    + ', device_id: {}'.format( device_id))

        if discovery_address not in self._ds_register:
            _log.debug('already unregistered')
            return True

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

    # post the new price point from us to the local-us-bus
    def _post_pp(self, rpcdata_id, message):
        _log.debug('New pp msg from us...')
        pp_msg = None
        rpcdata = jsonrpc.JsonRpcData.parse(message)

        # Note: this is on a rpc message do the check here ONLY
        # check message for MessageType.price_point
        if check_msg_type(message, MessageType.price_point): pass
        else:
            msg = 'Invalid params {}'.format(rpcdata.params)
            error = jsonrpc.json_error(rpcdata_id, INVALID_PARAMS, msg)
            return error

        try:
            minimum_fields = ['value', 'price_id']
            pp_msg = parse_jsonrpc_msg(message, minimum_fields)
        except KeyError as ke:
            msg = 'Invalid params {}'.format(rpcdata.params)
            error = jsonrpc.json_error(rpcdata_id, INVALID_PARAMS, msg)
            return error
        except Exception as e:
            msg = e.message
            error = jsonrpc.json_error(rpcdata_id, UNHANDLED_EXCEPTION, msg)
            return error

        # sanity measure like, valid fields, valid pp ids, ttl expiry, etc.,
        hint = 'Price Point'
        validate_fields = ['value', 'price_id', 'isoptimal', 'ttl']
        valid_price_ids = []        # accept all pp_ids from us
        if pp_msg.sanity_check_ok(hint, validate_fields, valid_price_ids): pass
        else:
            _log.warning('Msg sanity checks failed!!!')
            msg = 'Msg sanity checks failed!!!'
            error = jsonrpc.json_error(rpcdata_id, PARSE_ERROR, msg)
            return error

        # keep a track of us pp_ids
        if pp_msg.get_src_device_id() != self._device_id:
            if pp_msg.get_isoptimal():
                _log.debug('***** New optimal price point from us:'
                                    + ' {:0.2f}'.format(pp_msg.get_value()))
                self.us_opt_pp_id = pp_msg.get_price_id()
            else :
                _log.debug('***** New bid price point from us:'
                                    + ' {:0.2f}'.format(pp_msg.get_value()))
                self.us_bid_pp_id = pp_msg.get_price_id()

        # publish the new price point to the local us message bus
        pub_topic = self._topic_price_point_us
        pub_msg = pp_msg.get_json_message(self._agent_id, 'bus_topic')
        _log.info('[LOG] Price Point from us, Msg: {}'.format(pub_msg))
        _log.debug('Publishing to local bus topic: {}'.format(pub_topic))
        publish_to_bus(self, pub_topic, pub_msg)
        _log.debug('done.')
        return True

    # post the new energy demand from ds to the local-ds-bus
    def _post_ed(self, rpcdata_id, message):
        ed_msg = None
        _log.debug('New ap/ed msg from ds...')
        rpcdata = jsonrpc.JsonRpcData.parse(message)

        # Note: this is on a rpc message do the check here ONLY
        # check message for MessageType.price_point
        # handle only ap or ed type messages
        if check_msg_type(message, MessageType.active_power): pass
        elif check_msg_type(message, MessageType.energy_demand): pass
        else:
            msg = 'Invalid params {}'.format(rpcdata.params)
            error = jsonrpc.json_error(rpcdata_id, INVALID_PARAMS, msg)
            return error

        try:
            minimum_fields = ['value', 'price_id']
            ed_msg = parse_jsonrpc_msg(message, minimum_fields)
        except KeyError as ke:
            msg = 'Invalid params {}'.format(rpcdata.params)
            error = jsonrpc.json_error(rpcdata_id, INVALID_PARAMS, msg)
            return error
        except Exception as e:
            msg = e.message
            error = jsonrpc.json_error(rpcdata_id, UNHANDLED_EXCEPTION, msg)
            return error

        # sanity measure like, valid fields, valid pp ids, ttl expiry, etc.,
        hint = ('Active Power'
                if ed_msg.get_msg_type() == MessageType.active_power
                else 'Energy Demand')
        validate_fields = ['value', 'price_id', 'isoptimal', 'ttl']
        valid_price_ids = ([self.us_opt_pp_id
                            , self.us_bid_pp_id
                            , self.local_opt_pp_id, self.local_bid_pp_id]
                                if self._bridge_host != 'LEVEL_HEAD' 
                                else [self.local_opt_pp_id
                                        , self.local_bid_pp_id])
        if ed_msg.sanity_check_ok(hint, validate_fields, valid_price_ids): pass
        else:
            _log.warning('Msg sanity checks failed!!!')
            msg = 'Msg sanity checks failed!!!'
            error = jsonrpc.json_error(rpcdata_id, PARSE_ERROR, msg)
            return error

        # check if from registered ds
        if self._msg_from_registered_ds(ed_msg.get_src_ip()
                                            , ed_msg.get_src_device_id()
                                            ): pass
        else:
            # either the post to ds failed in previous iteration
            #                                   or unregistered
            #                                   or msg is corrupted
            # if the ds is unregistered by the bridge in previous iteration,
            # this return msg indicates ds that it needs to retry
            # after registering once again
            _log.warning('Msg not from registered ds!!!')
            msg = 'Msg not from registered ds!!!'
            error = jsonrpc.json_error(rpcdata_id, PARSE_ERROR, msg)
            return error

        # post to bus
        pub_topic = self._topic_energy_demand_ds
        pub_msg = ed_msg.get_json_message(self._agent_id, 'bus_topic')
        _log.info('[LOG] {} from ds, Msg: {}'.format(hint, pub_msg))
        _log.debug('Publishing to local bus topic: {}'.format(pub_topic))
        publish_to_bus(self, pub_topic, pub_msg)
        _log.debug('done.')

        # ds is alive at this stage, reset the counters, if any
        self._ds_retrycount[self._ds_register.index(ed_msg.get_src_ip())] = 0
        return True

    def _msg_from_registered_ds(self, discovery_addr, device_id):
        index = self._ds_register.index(discovery_addr)
        return (True if discovery_addr in self._ds_register
                     and device_id == self._ds_device_ids[index]
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


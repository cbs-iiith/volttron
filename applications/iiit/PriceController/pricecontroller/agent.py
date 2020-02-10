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
import dateutil
import logging
import sys
import uuid
from random import random, randint
from copy import copy

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

import time
import gevent
import gevent.event

from ispace_utils import publish_to_bus, retrive_details_from_vb, register_rpc_route
from ispace_utils import ping_vb_failed
from ispace_msg import ISPACE_Msg, MessageType
from ispace_msg_utils import parse_bustopic_msg, check_msg_type, tap_helper, ted_helper
from ispace_msg_utils import get_default_pp_msg, valid_bustopic_msg

utils.setup_logging()
_log = logging.getLogger(__name__)
__version__ = '0.4'


def pricecontroller(config_path, **kwargs):
    config = utils.load_config(config_path)
    vip_identity = config.get('vip_identity', 'iiit.pricecontroller')
    # This agent needs to be named iiit.pricecontroller. Pop the uuid id off the kwargs
    kwargs.pop('identity', None)
    
    Agent.__name__ = 'PriceController_Agent'
    return PriceController(config_path, identity=vip_identity, **kwargs)
    
    
class PriceController(Agent):
    '''Price Controller
    '''
    # initialized  during __init__ from config
    _period_read_data = None
    _period_process_loop = None
    
    _vb_vip_identity = None
    _topic_price_point_us = None
    _topic_price_point = None
    _topic_energy_demand_ds = None
    _topic_energy_demand = None
    
    _topic_extrn_pp = None
    _pca_state = None           # ['ONLINE', 'STANDALONE', 'STANDBY']
    _pca_standby = False
    _pca_standalone = False
    _pca_standalone = True
    _pca_mode = None            # ['PASS_ON_PP', 'DEFAULT_OPT', 'EXTERN_OPT']
    
    _device_id = None
    _discovery_address = None
    
    _published_us_bid_ted = None
    
    # default 15 minutes
    _bids_timeout = 900
    
    def __init__(self, config_path, **kwargs):
        super(PriceController, self).__init__(**kwargs)
        _log.debug('vip_identity: ' + self.core.identity)
        
        self.config = utils.load_config(config_path)
        return
        
    @Core.receiver('onsetup')
    def setup(self, sender, **kwargs):
        _log.info(self.config['message'])
        self._agent_id = self.config['agentid']
        
        self._period_read_data = self.config.get('period_read_data', 30)
        self._period_process_loop = self.config.get('period_process_loop', 1)
        # time to wait for devices to submit their bids. (0 --> wait-for-ever, default 900s (15min))
        self._bids_timeout = self.config.get('bids_timeout', 900)
        
        # local device_ids
        self._us_local_opt_ap = {}
        self._us_local_bid_ed = {}
        self._local_bid_ed = {}
        
        # ds device ids, opt_ap --> act_pwr@opt_pp, bid_ed --> bid_energy_demand@bid_pp
        self._us_ds_opt_ap = {}
        self._us_ds_bid_ed = {}
        self._ds_bid_ed = {}
        
        self._device_id = None
        self._ip_addr = None
        self._discovery_address = None
        
        self._vb_vip_identity = self.config.get('vb_vip_identity', 'iiit.volttronbridge')
        self._topic_price_point_us = self.config.get('pricePoint_topic_us', 'us/pricepoint')
        self._topic_price_point = self.config.get('pricePoint_topic', 'building/pricepoint')
        self._topic_energy_demand_ds = self.config.get('energyDemand_topic_ds', 'ds/energydemand')
        self._topic_energy_demand = self.config.get('energyDemand_topic', 'building/energydemand')
        
        self._pca_state = self.config.get('pca_state', 'ONLINE')
        self._pca_mode = self.config.get('pca_mode', 'PASS_ON_PP')
        self._topic_extrn_pp = self.config.get('extrn_optimize_pp_topic', 'pca/pricepoint')
        return
        
    @Core.receiver('onstart')
    def startup(self, sender, **kwargs):
        _log.debug('startup()')
        
        # retrive self._device_id and self._discovery_address from vb
        retrive_details_from_vb(self, 5)
        
        # register rpc routes with MASTER_WEB
        # register_rpc_route is a blocking call
        register_rpc_route(self, 'pca', 'rpc_from_net', 5)
        
        self._us_senders_list = ['iiit.volttronbridge', 'iiit.pricepoint']
        self._ds_senders_list = ['iiit.volttronbridge']
        self._local_ed_agents = []
        
        self.us_opt_pp_msg = get_default_pp_msg(self._discovery_address, self._device_id)
        self.us_bid_pp_msg = get_default_pp_msg(self._discovery_address, self._device_id)
        self.act_opt_pp_msg = get_default_pp_msg(self._discovery_address, self._device_id)
        self.act_bid_pp_msg = get_default_pp_msg(self._discovery_address, self._device_id)
        self.local_opt_pp_msg = get_default_pp_msg(self._discovery_address, self._device_id)
        self.local_bid_pp_msg = get_default_pp_msg(self._discovery_address, self._device_id)
        
        self.external_vip_identity = None
        
        # subscribing to _topic_price_point_us
        self.vip.pubsub.subscribe('pubsub', self._topic_price_point_us, self.on_new_us_pp)
        
        # subscribing to ds energy demand, vb publishes ed from registered ds to this topic
        self.vip.pubsub.subscribe('pubsub', self._topic_energy_demand_ds, self.on_ds_ed)
        
        # perodically publish total active power (tap) to local/energydemand
        # (vb RPCs this value to the next level)
        # since time period is much larger (default 30s, i.e, 2 reading per min), 
        # need not wait to receive from all devices
        # any ways this is used for monitoring purpose and the readings are averaged over a period
        self.core.periodic(self._period_read_data, self.aggregator_us_tap, wait=None)

        # subscribing to topic_price_point_extr
        self.vip.pubsub.subscribe('pubsub', self._topic_extrn_pp, self.on_new_extrn_pp)
        
        self._published_us_bid_ted = True
        # at regular interval check if all bid ds ed received, 
        # if so compute ted and publish to local/energydemand
        # (vb RPCs this value to the next level)
        self.core.periodic(self._period_process_loop, self.aggregator_us_bid_ted, wait=None)
        
        # default_opt process loop, i.e, each iteration's periodicity
        # if the cycle time (time consumed for each iteration) is more than periodicity,
        # the next iterations gets delayed.
        # self.core.periodic(self._period_process_loop, self.process_loop, wait=None)
        
        _log.debug('startup() - Done. Agent is ready')
        return
        
    @Core.receiver('onstop')
    def onstop(self, sender, **kwargs):
        _log.debug('onstop()')
        _log.debug('un registering rpc routes')
        
        self._us_local_opt_ap.clear()
        self._us_local_bid_ed.clear()
        self._local_bid_ed.clear()
        
        self._us_ds_opt_ap.clear()
        self._us_ds_bid_ed.clear()
        self._ds_bid_ed.clear()
        
        self.vip.rpc.call(MASTER_WEB, 'unregister_all_agent_routes').get(timeout=10)
        return
        
    @Core.receiver('onfinish')
    def onfinish(self, sender, **kwargs):
        _log.debug('onfinish()')
        return
        
    @RPC.export
    def rpc_from_net(self, header, message):
        result = False
        try:
            rpcdata = jsonrpc.JsonRpcData.parse(message)
            _log.debug('rpc_from_net()... '
                        + 'header: {}'.format(header)
                        + ', rpc method: {}'.format(rpcdata.method)
                        + ', rpc params: {}'.format(rpcdata.params)
                        )
            if rpcdata.method == 'ping':
                result = True
            elif rpcdata.method == 'state' and header['REQUEST_METHOD'] == 'POST':
                result = self._pca_mode(rpcdata.id, message)
            elif rpcdata.method == 'mode' and header['REQUEST_METHOD'] == 'POST':
                result = self._pca_mode(rpcdata.id, message)
            elif rpcdata.method == 'external-optimizer' and header['REQUEST_METHOD'] == 'POST':
                result = self._register_external_opt_agent(rpcdata.id, message)
            else:
                return jsonrpc.json_error(rpcdata.id, METHOD_NOT_FOUND,
                                            'Invalid method {}'.format(rpcdata.method))
        except KeyError as ke:
            # print(ke)
            return jsonrpc.json_error(rpcdata.id, INVALID_PARAMS,
                                        'Invalid params {}'.format(rpcdata.params))
        except Exception as e:
            # print(e)
            return jsonrpc.json_error(rpcdata.id, UNHANDLED_EXCEPTION, e)
        return jsonrpc.json_result(rpcdata.id, result)
        
    def _pca_state(self, rpcdata_id, message):
        state = jsonrpc.JsonRpcData.parse(message).params['state']
        if state not in ['ONLINE'
                        , 'STANDALONE'
                        , 'STANDBY'
                        ]:
            return jsonrpc.json_error(rpcdata_id, PARSE_ERROR, 'Invalid option!!!') 
        self._pca_state = state
        return True
        
    def _pca_mode(self, rpcdata_id, message):
        mode = jsonrpc.JsonRpcData.parse(message).params['mode']
        if mode not in ['PASS_ON_PP'
                        , 'DEFAULT_OPT'
                        , 'EXTERN_OPT'
                        ]:
            return jsonrpc.json_error(rpcdata_id, PARSE_ERROR, 'Invalid option!!!') 
        self._pca_mode = mode
        return True
        
    def _register_external_opt_agent(self, rpcdata_id, message):
        external_vip_identity = jsonrpc.JsonRpcData.parse(message).params['vip_identity']
        if external_vip_identity is None:
            return jsonrpc.json_error(rpcdata_id, PARSE_ERROR, 'Invalid option!!!') 
        self.external_vip_identity = external_vip_identity
        return True
    
    # this functionality moved to Sorting(refer to aggregator_us_tap(), aggregator_us_bid_ted()
    #                                                               , aggregator_local_bid_ted())
    # subscribe to local/ed (i.e., ted) from the controller (building/zone/smarthub controller)
    # def on_new_ed(self, peer, sender, bus,  topic, headers, message):
        # parse message & validate
        # (_ed, _is_opt, _ed_pp_id) = get_data(message)
        
        # if _ed_pp_id = us_opt_pp_id:
        #   # ed for global opt, do nothing
        #   # vb moves this ed to next level
        #   return
        
        # if pass_on and _ed_pp_id in us_pp_ids[]
        #   # do nothing
        #   # vb moves this ed to next level
        #   return
        
        # if extrn_opt and _ed_pp_id in extrn_pp_ids[]
        #   publish_ed(extrn/ed, _ed, _ed_pp_id)
        #   return
        
        # if default_opt and _ed_pp_id in local_pp_ids[]
        #       (new_pp, new_pp_isopt) = _compute_new_price()
        #       if new_pp_isopt
        #           # local optimal reached
        #           publish_ed(local/ed, _ed, us_bid_pp_id)
        #           # if next level accepts this bid, the new target is this ed
        #       based on opt conditon _computeNewPrice can publish new bid_pp or 
        # and save data to self._ds_bid_ed
        
    #    return
        
    def on_new_extrn_pp(self, peer, sender, bus,  topic, headers, message):
        if self._pp_optimize_option != 'EXTERN_OPT':
            return
        # check if this agent is not diabled
        if self._pca_standby:
            _log.info('self.pca_standby: ' + str(self._pca_standby) + ', do nothing!!!')
            return
            
        # check message type before parsing
        if not check_msg_type(message, MessageType.price_point): return False
        
        valid_senders_list = [self.external_vip_identity]
        minimum_fields = ['msg_type', 'value', 'value_data_type', 'units', 'price_id']
        validate_fields = ['value', 'units', 'price_id', 'isoptimal', 'duration', 'ttl']
        valid_price_ids = []
        (success, pp_msg) = valid_bustopic_msg(sender, valid_senders_list
                                                , minimum_fields
                                                , validate_fields
                                                , valid_price_ids
                                                , message)
        if not success or pp_msg is None: return
        else: _log.debug('New pp msg on the local-bus, topic: {}'.format(topic))
        
        self.act_pp_msg = copy(pp_msg)
        
        if pp_msg.get_isoptimal():
            self.local_opt_pp_msg = copy(pp_msg)
        else:
            self.local_bid_pp_msg = copy(pp_msg)
        
            pub_topic =  self._topic_price_point
            pub_msg = pp_msg.get_json_message(self._agent_id, 'bus_topic')
            _log.debug('publishing to local bus topic: {}'.format(pub_topic))
            _log.debug('Msg: {}'.format(pub_msg))
            publish_to_bus(self, pub_topic, pub_msg)
            return True
            
        return
        
    def on_new_us_pp(self, peer, sender, bus,  topic, headers, message):
        if self._pca_mode not in ['PASS_ON_PP', 'DEFAULT_OPT']:
            return
        # check if this agent is not diabled
        if self._pca_standby:
            _log.info('self.pca_standby: ' + str(self._pca_standby) + ', do nothing!!!')
            return False
            
        # check message type before parsing
        if not check_msg_type(message, MessageType.price_point): return False
        
        valid_senders_list = self._us_senders_list
        minimum_fields = ['msg_type', 'value', 'value_data_type', 'units', 'price_id']
        validate_fields = ['value', 'units', 'price_id', 'isoptimal', 'duration', 'ttl']
        valid_price_ids = []
        (success, pp_msg) = valid_bustopic_msg(sender, valid_senders_list
                                                , minimum_fields
                                                , validate_fields
                                                , valid_price_ids
                                                , message)
        if not success or pp_msg is None: return
        else: _log.debug('New pp msg on the us-bus, topic: {}'.format(topic))
        
        # keep a track of us pp_msg
        if pp_msg.get_isoptimal():
            self.us_opt_pp_msg = copy(pp_msg)
            _log.debug('***** New optimal price point from us:'
                                                + ' {:0.2f}'.format(pp_msg.get_value()))
        else:
            self.us_bid_pp_msg = copy(pp_msg)
            _log.debug('***** New bid price point from us:'
                                                + ' {:0.2f}'.format(pp_msg.get_value()))
        # log this msg
        _log.info('[LOG] pp msg from us: {}'.format(pp_msg))
        
        # re-initialize aggregator_us_bid_ted
        if not pp_msg.get_isoptimal():
            self._published_us_bid_ted = False
            
        if self._pca_mode == 'PASS_ON_PP':
            _log.info('[LOG] PCA mode: PASS_ON_PP')
            _log.debug('post to the local-bus...')
            pub_topic =  self._topic_price_point
            pub_msg = pp_msg.get_json_message(self._agent_id, 'bus_topic')
            _log.debug('local bus topic: {}'.format(pub_topic))
            publish_to_bus(self, pub_topic, pub_msg)
            _log.debug('Done!!!')
            return
            
        if self._pca_mode == 'DEFAULT_OPT':
            # list for pp_msg
            new_pp_msg_list = self._computeNewPrice()
            self.local_bid_pp_msg_list = copy(new_pp_msg_list)
            _log.info('new bid pp_msg_list: {}'.format(new_pp_msg_list))
            
            for msg in new_pp_msg_list:
                _log.info('new msg: {}'.format(msg))
                pub_topic =  self._topic_price_point
                pub_msg = new_pp_msg.get_json_message(self._agent_id, 'bus_topic')
                _log.debug('publishing to local bus topic: {}'.format(pub_topic))
                _log.debug('Msg: {}'.format(pub_msg))
                publish_to_bus(self, pub_topic, pub_msg)
                # _log.debug('yield a moment (50ms)')
                # time.sleep(50/1000)            # yield a moment (50ms)
            return
        return
        
    # compute new bid price point for every local device and ds devices
    # return list for pp_msg
    def _compute_new_price(self):
        _log.debug('_computeNewPrice()')
        
        # computes the new prices
        # cf may use priorities (manager assign individual device priorities
        #                             or group priorities based on device categories)
        # returns --> array of new pp_msg with one_to_one TRUE, if priorities are enabled
        #         --> array of new pp_msg with one_to_one FALSE
        #                               , if priorities are disabled (i.e, equal priorities)

        # TODO: implement the algorithm to compute the new price
        #      based on walras algorithm.
        #       config.get (optimization cost function)
        #       based on some initial condition like ed, us_new_pp, etc, compute new_pp
        #       publish to bus
        
        # optimization algo
        #   ed_target = r% x ed_optimal
        #   EPSILON = 10       # deadband
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
        #       iterate till optimization condition satistifed
        #       when new pp is published, the new ed for all devices is accumulated by on_new_ed()
        #       once all the eds are received call this function again
        #       publish the new optimal pp
        
        # price id of the new pp
        # set one_to_one = false if the pp is same for all the devices,
        #                 true if the pp pp is different for every device
        #             However, use the SAME price id for all pp_msg
        # 
        # common param meters for the new bid pp_msgs
        pp_msg = self.us_bid_pp_msg
        
        # new msg
        msg_type = MessageType.price_point
        one_to_one = True
        value_data_type = 'float'
        units = 'cents'
        price_id = randint(0, 99999999) # explore if need to use same price_id or different ones
        src_ip = None
        src_device_id = None
        duration = pp_msg.get_duration()
        ttl = 10
        ts = datetime.datetime.utcnow().isoformat(' ') + 'Z'
        tz = 'UTC'
        
        device_list = []
        dst_ip = []
        dst_device_id = []
        
        old_pricepoint = []
        old_ted = []
        target = 0
        
        self._target_acheived = False
        new_pricepoint = self._some_cost_fn(old_pricepoint, old_ted, target)
        
        if self._target_acheived and self._pca_state == 'ONLINE':
            # local optimal reached, publish this as bid to the us pp_msg
            # publish bid total energy demand to local/energydemand
            # 
            # compute total bid energy demand and publish to local/energydemand
            # (vb RPCs this value to the next level)
            bid_ted = self._calc_total(self._local_bid_ed, self._ds_bid_ed)
            
            # publish to local/energyDemand (vb pushes(RPC) this value to the next level)
            self._publish_bid_ted(pp_msg, bid_ted)
            
            # need to reset the corresponding buckets to zero
            self._local_bid_ed.clear()
            self._ds_bid_ed.clear()
            return
        
        isoptimal = (True if (self._target_acheived and self._pca_state == 'STANDALONE') 
                            else False)
        
        pp_messages = []
        for device_idx in device_list:
            pp_msg = ISPACE_Msg(msg_type, one_to_one
                    , isoptimal, new_pricepoint[device_idx], value_data_type, units, price_id
                    , src_ip, src_device_id, dst_ip[device_idx], dst_device_id[device_idx]
                    , duration, ttl, ts, tz)
            pp_messages.insert(pp_msg)
        return pp_messages
        
    def _some_cost_fn(self, old_pricepoint, old_ted, target):
        new_pricepoints = []
        return new_pricepoints
        
    # perodically run this function to check if ted from all ds received or ted_timed_out
    def process_loop(self):
        if not self._pp_optimize_option == 'DEFAULT_OPT': return
         
        # check if all the bids are received from both local & ds devices
        # rcvd_all_lc_bid_ed_lc --> local(lc) energy demand bids for local(lc) bid pricepoint
        rcvd_all_lc_bid_ed_lc = self._rcvd_all_lc_bid_ed_lc(self._get_vb_local_device_ids())
        # rcvd_all_lc_bid_ed_ds --> downstream(ds) energy demand bids for upstream(us) bid pricepoint
        rcvd_all_lc_bid_ed_ds = self._rcvd_all_lc_bid_ed_ds(self._get_vb_ds_device_ids())
        
        # TODO: timeout check -- visit later
        # lc_bid_pp_timeout = self._lc_bid_pp_timeout()
        lc_bid_pp_timeout = False               # never timeout
                 
        #       if new_pp_isopt
        #           # local optimal reached
        #           publish_ed(local/ed, _ed, us_bid_pp_id)
        #           # if next level accepts this bid, the new target is this ed
        #       based on opt conditon _computeNewPrice can publish new bid_pp or 
        # and save data to self._ds_bid_ed

        pp_messages = self._compute_new_price()
        # publish these pp_messages
        
        # clear corresponding buckets
        self._local_bid_ed.clear()
        self._ds_bid_ed.clear()
        return
        
    def _us_bids_timeout(self):
        # TODO: need to return much before actual timeout, can't wait till actual timeout
        ts  = dateutil.parser.parse(self.us_bid_pp_msg.get_ts())
        now = dateutil.parser.parse(datetime.datetime.utcnow().isoformat(' ') + 'Z')
        return (True if (now - ts).total_seconds() > self._bids_timeout else False)
        
    def _rcvd_all_us_bid_ed_lc(self, vb_local_device_ids):
        # may be some devices may have disconnected
        #      i.e., devices_count >= len(vb_devices_count)
        return (True if len(self._us_local_bid_ed) >= len(vb_local_device_ids) else False)
        
    def _rcvd_all_us_bid_ed_ds(self, vb_ds_device_ids):
        # may be some devices may have disconnected
        #      i.e., devices_count >= len(vb_devices_count)
        return (True if len(self._us_ds_bid_ed) >= len(vb_ds_device_ids) else False)
        
    def _rcvd_all_lc_bid_ed_lc(self, vb_local_device_ids):
        # may be some devices may have disconnected
        #      i.e., devices_count >= len(vb_devices_count)
        return (True if len(self._local_bid_ed) >= len(vb_local_device_ids) else False)
        
    def _rcvd_all_lc_bid_ed_ds(self, vb_ds_device_ids):
        # may be some devices may have disconnected
        #      i.e., devices_count >= len(vb_devices_count)
        return (True if len(self._ds_bid_ed) >= len(vb_ds_device_ids) else False)
        
    def on_ds_ed(self, peer, sender, bus,  topic, headers, message):
        # check if this agent is not diabled
        if self._pca_standby:
            _log.info('self.pca_standby: ' + str(self._pca_standby) + ', do nothing!!!')
            return False
        # 1. validate message
        # 2. check againt valid pp ids
        # 3. if (src_id_add == self._ip_addr) and opt_pp:
        # 5.         local_opt_tap      # local opt active power
        # 6. elif (src_id_add == self._ip_addr) and not opt_pp:
        # 7.         local_bid_ted      # local bid energy demand
        # 8. elif opt_pp:
        #             ds_opt_tap
        #    else
        #               ds_bid_ted
        # 9.      if opt_pp
        # post ed to us only if pp_id corresponds to these ids 
        #      (i.e., ed for either us opt_pp_id or bid_pp_id)
        
        success_ap = False
        success_ed = False
        # handle only ap or ed type messages
        success_ap = check_msg_type(message, MessageType.active_power)
        if not success_ap:
            success_ed = check_msg_type(message, MessageType.energy_demand)
            if not success_ed:
                return
                
        # add the message to ds_ed_msgs to be processed by process_ds_ed_msg_que()
        #msg_id = randint(0, 99999999)
        #ds_ed_msgs[msg_id] = {'msg_type': (MessageType.active_power
        #                                if success_ap else MessageType.energy_demand)
        #                        , 'message': message
        #                        }
        
        if ping_vb_failed(self):
            _log.error('!!! unable to contact bridge !!!')
            return
            
        # local ed agents vip_identities
        self._local_ed_agents = self.vip.rpc.call(self._vb_vip_identity
                                                    , 'local_ed_agents'
                                                    ).get(timeout=10)
        # unique senders list
        # valid_senders_list = list(set(self._ds_senders_list + self._local_ed_agents))
        valid_senders_list = self._ds_senders_list + self._local_ed_agents
        minimum_fields = ['msg_type', 'value', 'value_data_type', 'units', 'price_id']
        validate_fields = ['value', 'units', 'price_id', 'isoptimal', 'duration', 'ttl']
        valid_price_ids = self._get_valid_price_ids()
        (success, ed_msg) = valid_bustopic_msg(sender, valid_senders_list
                                                , minimum_fields
                                                , validate_fields
                                                , valid_price_ids
                                                , message)
        if not success or ed_msg is None: return
        else: _log.debug('New' 
                        + (' energy demand bid (ed)' if success_ed else ' active power (ap)')
                        + ' msg on the local-bus, topic: {}'.format(topic))
        
        price_id = ed_msg.get_price_id()
        device_id = ed_msg.get_src_device_id()
        
        '''
        sort energy packet to respective buckets 
            
                           |--> _us_local_opt_ap    |
        us_opt_tap---------|                        |--> aggregator publishs tap to us/energydemand
                           |--> _us_ds_opt_ap       |       at regular interval 


                           |--> _us_local_bid_ed    |
        us_bid_ted---------|                        |--> aggregator publishs ted to us/energydemand 
                           |--> _us_ds_bid_ed       |       if received from all or timeout


                           |--> _local_bid_ed       |
        local_bid_ted------|                        |--> process_loop() initiates
                           |--> _ds_bid_ed          |       _compute_new_price()
       '''
        # MessageType.active_power, aggregator publishes this data to local/energydemand
        if (success_ap and price_id == self.us_opt_pp_msg.get_price_id()):
            # put data to local_tap bucket
            if device_id in self._get_vb_local_device_ids():
                opt_tap = ed_msg.get_value()
                _log. info('[LOG] TAP opt from local_device ({})'.format(device_id)
                                            + ' for us opt pp_msg({})):'.format(price_id)
                                            + ' {:0.4f}'.format(opt_tap))
                self._us_local_opt_ap[device_id] = opt_tap
                return
            # put data to ds_tap bucket
            elif device_id in self._get_vb_ds_device_ids():
                opt_tap = ed_msg.get_value()
                _log. info('[LOG] TAP opt from ds_device ({})'.format(device_id)
                                            + ' for us opt pp_msg({})):'.format(price_id)
                                            + ' {:0.4f}'.format(opt_tap))
                self._us_ds_opt_ap[device_id] = opt_tap
                return
        # MessageType.energy_demand, aggregator publishes this data to local/energydemand
        elif (success_ed and price_id == self.us_bid_pp_msg.get_price_id()):
            # put data to ds_tap bucket
            if device_id in self._get_vb_local_device_ids():
                bid_ted = ed_msg.get_value()
                _log. info('[LOG] TED bid from local_device ({})'.format(device_id)
                                            + ' for us bid pp_msg({})):'.format(price_id)
                                            + ' {:0.4f}'.format(bid_ted))
                self._us_local_bid_ed[device_id] = bid_ted
                return
            # put data to ds_tap bucket
            elif device_id in self._get_vb_ds_device_ids():
                bid_ted = ed_msg.get_value()
                _log. info('[LOG] TED bid from ds_device ({})'.format(device_id)
                                            + ' for us bid pp_msg({})):'.format(price_id)
                                            + ' {:0.4f}'.format(bid_ted))
                self._us_ds_bid_ed[device_id] = ed_msg.get_value()
                return
        # MessageType.energy_demand, process_loop() initiates _compute_new_price()
        elif (success_ed and price_id == self.local_bid_pp_msg.get_price_id()):
            # put data to local_tap bucket
            if device_id in self._get_vb_local_device_ids():
                bid_ted = ed_msg.get_value()
                _log. info('[LOG] TED bid from local_device ({})'.format(device_id)
                                            + ' for local bid pp_msg({})):'.format(price_id)
                                            + ' {:0.4f}'.format(bid_ted))
                self._local_bid_ed[device_id] = ed_msg.get_value()
                return
            # put data to local_ted bucket
            elif device_id in self._get_vb_ds_device_ids():
                bid_ted = ed_msg.get_value()
                _log. info('[LOG] TED bid from ds_device ({})'.format(device_id)
                                            + ' for local bid pp_msg({})):'.format(price_id)
                                            + ' {:0.4f}'.format(bid_ted))
                self._ds_bid_ed[device_id] = ed_msg.get_value()
                return
        return
        
    # perodically publish total active power (tap) to local/energydemand
    def aggregator_us_tap(self):
        # since time period much larger (default 30s, i.e, 2 reading per min)
        # need not wait to receive active power from all devices
        # any ways this is used for monitoring purpose and the readings are averaged over a period
        if (self._pca_state != 'ONLINE'
                or self._pca_mode not in ['PASS_ON_PP', 'DEFAULT_OPT', 'EXTERN_OPT']):
            if self._pca_state in ['STANDALONE'
                                    # , 'STANDBY'
                                    ]:return
            # not implemented
            else: _log.warning('aggregator_us_tap() not implemented'
                                + ' pca_state: {}'.format(self._pca_state)
                                + ' pca_mode: {}'.format(self._pca_mode)
                                )
            return
            
        # compute total active power (tap)
        opt_tap = self._calc_total(self._us_local_opt_ap, self._us_ds_opt_ap)
        
        # publish to local/energyDemand (vb pushes(RPC) this value to the next level)
        self._publish_opt_tap(opt_tap)
        
        # reset the corresponding buckets to zero
        self._us_local_opt_ap.clear()
        self._us_ds_opt_ap.clear()
        return
        
    def aggregator_us_bid_ted(self):
        # nothing do, wait for new bid pp from us
        if self._published_us_bid_ted: return
        
        if self._pca_state in ['STANDALONE', 'STANDBY']: return
            
        if (self._pca_state != 'ONLINE' or self._pca_mode not in ['PASS_ON_PP'
                                                                , 'DEFAULT_OPT'
                                                                , 'EXTERN_OPT'
                                                                ]
            ):
            # not implemented
            _log.warning('aggregator_us_tap() not implemented'
                            + ' pca_state: {}'.format(self._pca_state)
                            + ' pca_mode: {}'.format(self._pca_mode)
                            )
            return
            
        # check if all the bids are received from both local & ds devices
        # rcvd_all_us_bid_ed_lc --> local(lc) energy demand bids for upstream(us) bid pricepoint
        rcvd_all_us_bid_ed_lc = self._rcvd_all_us_bid_ed_lc(self._get_vb_local_device_ids())
        # rcvd_all_us_bid_ed_ds --> downstream(ds) energy demand bids for upstream(us) bid pricepoint
        rcvd_all_us_bid_ed_ds = self._rcvd_all_us_bid_ed_ds(self._get_vb_ds_device_ids())
        
        # TODO: timeout check -- visit later
        us_bids_timeout = self._us_bids_timeout()
        # us_bids_timeout = False               # never timeout
        
        if (not (rcvd_all_us_bid_ed_lc and rcvd_all_us_bid_ed_ds)):
            if not us_bids_timeout:
                _log.debug('not all bids received and not yet timeout!!!.' 
                            + ' rcvd_all_us_bid_ed_lc: {}'.format(rcvd_all_us_bid_ed_lc)
                            + ' rcvd_all_us_bid_ed_ds: {}'.format(rcvd_all_us_bid_ed_ds)
                            + ' us_bids_timeout: {}'.format(us_bids_timeout)
                            + ', will try again in {} sec'.format(self._period_process_loop))
                self._published_us_bid_ted = False
                return
                
        # compute total energy demand (ted)
        bid_ted = self._calc_total(self._us_local_bid_ed, self._us_ds_bid_ed)
        
        # publish to local/energyDemand (vb pushes(RPC) this value to the next level)
        self._publish_bid_ted(self.us_bid_pp_msg, bid_ted)
        
        # need to reset the corresponding buckets to zero
        self._us_local_bid_ed.clear()
        self._us_ds_bid_ed.clear()
        self._published_us_bid_ted = True
        return
        
    def aggregator_local_bid_ted(self):
        # this function is not required. 
        # process_loop pickup the local individual bids
        # refer to process_loop()
        if self._pp_optimize_option != 'DEFAULT_OPT': return
        return
        
    def _get_vb_local_device_ids(self):
        result = []
        try:
            result = self.vip.rpc.call(self._vb_vip_identity
                                        , 'get_local_device_ids'
                                        ).get(timeout=10)
        except Exception as e:
            #print(e)
            _log.exception('Maybe the Volttron Bridge Agent is not yet started!!!')
            pass
        return result
        
    def _get_vb_ds_device_ids(self):
        result = []
        try:
            result = self.vip.rpc.call(self._vb_vip_identity
                                        , 'get_ds_device_ids'
                                        ).get(timeout=10)
        except Exception as e:
            #print(e)
            _log.exception('Maybe the Volttron Bridge Agent is not yet started!!!')
            pass
        return result
        
    def _get_valid_price_ids(self):
        price_ids = []
        if self._pca_mode == 'PASS_ON_PP':
            price_ids = [self.us_opt_pp_msg.get_price_id()
                            , self.us_bid_pp_msg.get_price_id()
                            ]
        else:
            _log.error('_get_valid_price_ids() for mode {} not implemented'
                                                            + '!!!'.format(self._pca_mode))
        return price_ids
        
    def _publish_opt_tap(self, opt_tap):
        # create a MessageType.active_power ISPACE_Msg in response to us_opt_pp_msg
        tap_msg = tap_helper(self.us_opt_pp_msg
                            , self._device_id
                            , self._discovery_address
                            , opt_tap
                            , self._period_read_data
                            )
                            
        _log. info('[LOG] Total Active Power(TAP) opt'
                                    + ' (for us pp_msg ({})):'.format(tap_msg.get_price_id())
                                    + ' {:0.4f}'.format(opt_tap))
        # publish the total active power to the local message bus
        # volttron bridge pushes(RPC) this value to the next level
        _log.debug('post to the local-bus...')
        pub_topic = self._topic_energy_demand
        pub_msg = tap_msg.get_json_message(self._agent_id, 'bus_topic')
        _log.debug('local bus topic: {}'.format(pub_topic))
        _log. info('[LOG] Total Active Power(TAP) opt, Msg: {}'.format(pub_msg))
        publish_to_bus(self, pub_topic, pub_msg)
        _log.debug('Done!!!')
        return
        
    def _publish_bid_ted(self, pp_msg, bid_ted):
        # already checked if all bids are received or timeout
        # create a MessageType.energy ISPACE_Msg
        ted_msg = ted_helper(pp_msg
                            , self._device_id
                            , self._discovery_address
                            , bid_ted
                            , self._period_read_data
                            )
                            
        # compute total energy demand (ted)
        bid_ted = self._calc_total(self._us_local_bid_ed, self._us_ds_bid_ed)
        _log. info('[LOG] Total Energy Demand(TED) bid'
                                    + ' (for us pp_msg ({})):'.format(ted_msg.get_price_id())
                                    + ' {:0.4f}'.format(bid_ted))
        # publish the total energy demand to the local message bus
        # volttron bridge pushes(RPC) this value to the next level
        _log.debug('post to the local-bus...')
        pub_topic = self._topic_energy_demand
        pub_msg = ted_msg.get_json_message(self._agent_id, 'bus_topic')
        _log.debug('local bus topic: {}'.format(pub_topic))
        _log. info('[LOG] Total Energy Demand(TED) bid, Msg: {}'.format(pub_msg))
        publish_to_bus(self, pub_topic, pub_msg)
        _log.debug('Done!!!')
        return
        
    def _calc_total(self, local_bucket, ds_bucket):
        # current vb registered devices that had published active power (intersection)
        # may be some devices may have disconnected
        #      i.e., devices_count >= len(vb_devices_count)
        #       reconcile the device ids and match _ap[] with device_id
        new_local_device_ids = list(set(local_bucket.keys())
                                            & set(self._get_vb_local_device_ids()))
        new_ds_device_ids = list(set(ds_bucket.keys())
                                            & set(self._get_vb_ds_device_ids()))
        # compute total
        total_value = 0.0
        for device_id in new_local_device_ids:
            if device_id in local_bucket: total_value += local_bucket[device_id]
        for device_id in new_ds_device_ids:
            if device_id in ds_bucket: total_value += ds_bucket[device_id]
        return total_value
        
        
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
        
        
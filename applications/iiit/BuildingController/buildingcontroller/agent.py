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

from random import random, randint
from copy import copy

import settings
import time
import struct
import gevent
import gevent.event

from ispace_utils import isclose, get_task_schdl, cancel_task_schdl, publish_to_bus
from ispace_utils import retrive_details_from_vb, register_with_bridge, register_rpc_route
from ispace_utils import calc_energy_wh, calc_energy_kwh
from ispace_utils import unregister_with_bridge
from ispace_msg import ISPACE_Msg, MessageType
from ispace_msg_utils import parse_bustopic_msg, check_msg_type, tap_helper, ted_helper
from ispace_msg_utils import get_default_pp_msg, valid_bustopic_msg

utils.setup_logging()
_log = logging.getLogger(__name__)
__version__ = '0.4'

# checking if a floating point value is “numerically zero” by checking if it is lower than epsilon
EPSILON = 1e-04

SCHEDULE_AVLB = 1
SCHEDULE_NOT_AVLB = 0

E_UNKNOWN_CCE = -4
E_UNKNOWN_TSP = -5
E_UNKNOWN_BPP = -7


def buildingcontroller(config_path, **kwargs):
    config = utils.load_config(config_path)
    vip_identity = config.get('vip_identity', 'iiit.buildingcontroller')
    # This agent needs to be named iiit.buildingcontroller. Pop the uuid id off the kwargs
    kwargs.pop('identity', None)
    
    Agent.__name__ = 'BuildingController_Agent'
    return BuildingController(config_path, identity=vip_identity, **kwargs)
    
    
class BuildingController(Agent):
    '''Building Controller
    '''
    # initialized  during __init__ from config
    _period_read_data = None
    _period_process_pp = None
    _price_point_latest = None
    
    _vb_vip_identity = None
    _root_topic = None
    _topic_energy_demand = None
    _topic_price_point = None
    
    _device_id = None
    _discovery_address = None
    
    # any process that failed to apply pp sets this flag False
    _process_opt_pp_success = False
    
    def __init__(self, config_path, **kwargs):
        super(BuildingController, self).__init__(**kwargs)
        _log.debug('vip_identity: ' + self.core.identity)
        
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
        _log.info('Starting BuildingController...')
        
        # retrive self._device_id and self._discovery_address from vb
        retrive_details_from_vb(self, 5)
        
        # register rpc routes with MASTER_WEB
        # register_rpc_route is a blocking call
        register_rpc_route(self, 'buildingcontroller', 'rpc_from_net', 5)
        
        # register this agent with vb as local device for posting active power & bid energy demand
        # pca picks up the active power & energy demand bids only if registered with vb as local device
        # require self._vb_vip_identity, self.core.identity, self._device_id
        # register_with_bridge is a blocking call
        register_with_bridge(self, 5)
        
        self._valid_senders_list_pp = ['iiit.pricecontroller']
        
        # any process that failed to apply pp sets this flag False
        # setting False here to initiate applying default pp on agent start
        self._process_opt_pp_success = False
        
        # on successful process of apply_pricing_policy with the latest opt pp, current = latest
        self._opt_pp_msg_current = get_default_pp_msg(self._discovery_address, self._device_id)
        # latest opt pp msg received on the message bus
        self._opt_pp_msg_latest = get_default_pp_msg(self._discovery_address, self._device_id)
        
        self._bid_pp_msg_latest = get_default_pp_msg(self._discovery_address, self._device_id)
        
        # self._run_bms_test()
        
        # TODO: get the latest values (states/levels) from h/w
        # self.getInitialHwState()
        # time.sleep(1) # yeild for a movement
        
        # TODO: apply pricing policy for default values
        
        # TODO: publish initial data to volttron bus
        
        # perodically publish total active power to volttron bus
        # active power is comupted at regular interval (_period_read_data default(30s))
        # this power corresponds to current opt pp
        # tap --> total active power (Wh)
        self.core.periodic(self._period_read_data, self.publish_opt_tap, wait=None)
        
        # perodically process new pricing point that keeps trying to apply the new pp till success
        self.core.periodic(self._period_process_pp, self.process_opt_pp, wait=None)
        
        # subscribing to topic_price_point
        self.vip.pubsub.subscribe('pubsub', self._topic_price_point, self.on_new_price)
        
        _log.debug('startup() - Done. Agent is ready')
        return
        
    @Core.receiver('onstop')
    def onstop(self, sender, **kwargs):
        _log.debug('onstop()')
        
        unregister_with_bridge(self)
        
        _log.debug('un registering rpc routes')
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
                        #+ 'header: {}'.format(header)
                        + ', rpc method: {}'.format(rpcdata.method)
                        #+ ', rpc params: {}'.format(rpcdata.params)
                        )
            if rpcdata.method == 'ping':
                return True
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
        return (jsonrpc.json_result(rpcdata.id, result) if result else result)
        
    def _config_get_init_values(self):
        self._period_read_data = self.config.get('period_read_data', 30)
        self._period_process_pp = self.config.get('period_process_pp', 10)
        self._price_point_latest = self.config.get('price_point_latest', 0.2)
        return
        
    def _config_get_points(self):
        self._vb_vip_identity = self.config.get('vb_vip_identity', 'iiit.volttronbridge')
        self._root_topic = self.config.get('topic_root', 'building')
        self._topic_price_point = self.config.get('topic_price_point', 'building/pricepoint')
        self._topic_energy_demand = self.config.get('topic_energy_demand', 'ds/energydemand')
        return
        
    def _test_new_pp(self, pp_msg, new_pp):
        _log.debug('change pp {}'.format(new_pp))
        pp_msg.set_value(new_pp)
        pp_msg.set_price_id(str(randint(0, 99999999)))
        pp_msg.set_ts(datetime.datetime.utcnow().isoformat(' ') + 'Z')
        self._process_opt_pp(pp_msg)
        return
        
    def _run_bms_test(self):
        _log.debug('Running: _runBMS Commu Test()...')
        self._test_new_pp(pp_msg, 0.10)
        time.sleep(1)
        
        self._test_new_pp(pp_msg, 0.75)
        time.sleep(1)
        
        self._test_new_pp(pp_msg, 0.25)
        time.sleep(1)
        
        _log.debug('EOF Testing')
        return
        
    '''
        Functionality related to the controller
        
        1. control the local actuators
                get/set various set point / levels / speeds
        2. local sensors
                report the sensors data at regular interval
        3. run necessary traditional control algorithm (PID, on/off, etc.,)
        
    '''
    def _rpcget_bms_pp(self):
        try:
            pp = self.vip.rpc.call('platform.actuator'
                                    ,'get_point'
                                    , 'iiit/cbs/buildingcontroller/Building_PricePoint'
                                    ).get(timeout=10)
            return pp
        except gevent.Timeout:
            _log.exception('gevent.Timeout in _rpcget_bms_pp()')
            return E_UNKNOWN_BPP
        except Exception as e:
            _log.exception('Could not contact actuator. Is it running?')
            print(e)
            return E_UNKNOWN_BPP
        return E_UNKNOWN_BPP
        
    # Publish new price to bms (for logging (or) for further processing by the BMS)
    def _rpcset_bms_pp(self, new_pp):
        _log.debug('_rpcset_bms_pp()')
        
        task_id = str(randint(0, 99999999))
        success = get_task_schdl(self, task_id, 'iiit/cbs/buildingcontroller')
        if not success: return
        try:
            result = self.vip.rpc.call('platform.actuator'
                                        , 'set_point'
                                        , self._agent_id
                                        , 'iiit/cbs/buildingcontroller/Building_PricePoint'
                                        , new_pp
                                        ).get(timeout=10)
            self._update_bms_pp(new_pp)
        except gevent.Timeout:
            _log.exception('gevent.Timeout in _rpcset_bms_pp()!!!')
        except Exception as e:
            _log.exception('_rpcset_bms_pp() changing price in the bms!!!')
            # print(e)
        finally:
            # cancel the schedule
            cancel_task_schdl(self, task_id)
        return
        
    def _update_bms_pp(self, new_pp):
        building_pp = self._rpcget_bms_pp()
        _log.debug('new_pp for bms: {:0.2f}'.format(new_pp)
                        + ' , pp at bms {:0.2f}'.format(building_pp))
        
        # check if the pp really updated at the bms, only then proceed with new pp
        if isclose(new_pp, building_pp, EPSILON):
            self._publish_bms_pp()
        return
        
    def _publish_bms_pp(self):
        # _log.debug('_publish_bms_pp()')
        if self._opt_pp_msg_latest is None:
            # this happens when the agent starts
            _log.warning('_publish_bms_pp() - self._opt_pp_msg_latest is None')
            return
            
        pp_msg = copy(self._opt_pp_msg_latest)
        
        # NOTE: not to be confused by "pricePoint_topic": "building/pricepoint" used by bridge
        pub_topic =  self._root_topic + '/bms_pp'
        pub_msg = pp_msg.get_json_message(self._agent_id, 'bus_topic')
        _log.debug('publishing to local bus topic: {}'.format(pub_topic))
        _log.debug('Msg: {}'.format(pub_msg))
        publish_to_bus(self, pub_topic, pub_msg)
        return
        
    '''
        Functionality related to the market mechanisms
        
        1. receive new prices (optimal pp or bid pp) from the pca
        2. if opt pp, apply pricing policy by computing the new setpoint based on price functions
        3. if bid pp, compute the new bid energy demand
        
    '''
    def on_new_price(self, peer, sender, bus,  topic, headers, message):
        if sender not in self._valid_senders_list_pp: return
        
        # check message type before parsing
        if not check_msg_type(message, MessageType.price_point): return False
            
        valid_senders_list = self._valid_senders_list_pp
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
        
        if pp_msg.get_isoptimal():
            _log.debug('***** New optimal price point from pca: {:0.2f}'.format(pp_msg.get_value())
                                        + ' , price_id: {}'.format(pp_msg.get_price_id()))
            self._process_opt_pp(pp_msg)
        else:
            _log.debug('***** New bid price point from pca: {:0.2f}'.format(pp_msg.get_value())
                                        + ' , price_id: {}'.format(pp_msg.get_price_id()))
            self._process_bid_pp(pp_msg)
            
        return
        
    def _process_opt_pp(self, pp_msg):
        self._opt_pp_msg_latest = copy(pp_msg)
        self._price_point_latest = pp_msg.get_value()
        
        # any process that failed to apply pp sets this flag False
        self._process_opt_pp_success = False
        # initiate the periodic process
        self.process_opt_pp()
        return
        
    # this is a perodic function that keeps trying to apply the new pp till success
    def process_opt_pp(self):
        if self._process_opt_pp_success: return
            
        # any process that failed to apply pp sets this flag False
        self._process_opt_pp_success = True
        
        self._apply_pricing_policy()
        if not self._process_opt_pp_success:
            _log.debug('unable to process_opt_pp()'
                        + ' , will try again in {} sec!!!'.format(self._period_process_pp))
            return
            
        _log.info('New Price Point processed.')
        # on successful process of apply_pricing_policy with the latest opt pp, current = latest
        self._opt_pp_msg_current = copy(self._opt_pp_msg_latest)
        return
        
    def _apply_pricing_policy(self):
        _log.debug('_apply_pricing_policy()')
        new_pp = self._opt_pp_msg_latest.get_value()
        self._rpcset_bms_pp(new_pp)
        bms_pp = self._rpcget_bms_pp()
        if not isclose(new_pp, bms_pp, EPSILON):
            self._process_opt_pp_success = False

        # TODO: control the energy demand of devices at building level accordingly
        #      use self._opt_pp_msg_latest
        #      if applying self._price_point_latest failed, set self._process_opt_pp_success = False
        return
        
        
    # perodic function to publish active power
    def publish_opt_tap(self):
        pp_msg = self._opt_pp_msg_current
        price_id = pp_msg.get_price_id()
        # compute total active power and publish to local/energydemand
        # (vb RPCs this value to the next level)
        opt_tap = self._calc_total_act_pwr()
        
        # create a MessageType.active_power ISPACE_Msg
        ap_msg = tap_helper(pp_msg
                            , self._device_id
                            , self._discovery_address
                            , opt_tap
                            , self._period_read_data
                            )
        _log. info('[LOG] Total Active Power(TAP) opt'
                                    + ' for us opt pp_msg({})'.format(price_id)
                                    + ': {:0.4f}'.format(opt_tap))
        # publish the new price point to the local message bus
        _log.debug('post to the local-bus...')
        pub_topic = self._topic_energy_demand
        pub_msg = ap_msg.get_json_message(self._agent_id, 'bus_topic')
        _log.debug('local bus topic: {}'.format(pub_topic))
        _log. info('[LOG] Total Active Power(TAP) opt, Msg: {}'.format(pub_msg))
        publish_to_bus(self, pub_topic, pub_msg)
        return
        
    # calculate total active power (tap)
    def _calc_total_act_pwr(self):
        # _log.debug('_calc_total_act_pwr()')
        tap = random() * 1000
        return tap
        
    def _process_bid_pp(self, pp_msg):
        self._bid_pp_msg_latest = copy(pp_msg)
        self.process_bid_pp()
        return
        
    def process_bid_pp(self):
        self.publish_bid_ted()
        return
        
    def publish_bid_ted(self):
        pp_msg = self._bid_pp_msg_latest
        price_id = pp_msg.get_price_id()
        
        # compute total bid energy demand and publish to local/energydemand
        # (vb RPCs this value to the next level)
        bid_ted = self._calc_total_energy_demand()
        
        # create a MessageType.energy ISPACE_Msg
        ed_msg = ted_helper(pp_msg
                            , self._device_id
                            , self._discovery_address
                            , bid_ted
                            , self._period_read_data
                            )
        _log. info('[LOG] Total Energy Demand(TED) bid'
                                    + ' for us bid pp_msg({})'.format(price_id)
                                    + ': {:0.4f}'.format(bid_ted))
                                    
        # publish the new price point to the local message bus
        _log.debug('post to the local-bus...')
        pub_topic = self._topic_energy_demand
        pub_msg = ed_msg.get_json_message(self._agent_id, 'bus_topic')
        _log.debug('local bus topic: {}'.format(pub_topic))
        _log. info('[LOG] Total Energy Demand(TED) bid, Msg: {}'.format(pub_msg))
        publish_to_bus(self, pub_topic, pub_msg)
        _log.debug('Done!!!')
        return
        
    # calculate the local total energy demand for bid_pp
    # the bid energy is for self._bid_pp_duration (default 1hr)
    # and this msg is valid for self._period_read_data (ttl - default 30s)
    def _calc_total_energy_demand(self):
        pp_msg = self._bid_pp_msg_latest
        bid_pp = pp_msg.get_value()
        duration = pp_msg.get_duration()
        
        # for testing
        bid_ted = random() * 1000
        return bid_ted
        
        
def main(argv=sys.argv):
    '''Main method called by the eggsecutable.'''
    try:
        utils.vip_main(buildingcontroller)
    except Exception as e:
        print (e)
        _log.exception('unhandled exception')
        
        
if __name__ == '__main__':
    # Entry point for script
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        pass
        
        
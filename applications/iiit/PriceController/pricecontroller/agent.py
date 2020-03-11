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
from collections import defaultdict
from copy import copy
from random import randint

import dateutil
import gevent
import gevent.event
from enum import IntEnum

from applications.iiit.Utils.ispace_msg import (ISPACE_Msg, MessageType,
                                                EnergyCategory)
from applications.iiit.Utils.ispace_msg_utils import (get_default_pp_msg,
                                                      check_msg_type,
                                                      ted_helper,
                                                      valid_bustopic_msg,
                                                      tap_helper)
from applications.iiit.Utils.ispace_utils import (publish_to_bus,
                                                  retrieve_details_from_vb,
                                                  register_rpc_route,
                                                  Runningstats)
from volttron.platform import jsonrpc
from volttron.platform.agent import utils
from volttron.platform.agent.known_identities import MASTER_WEB
from volttron.platform.vip.agent import Agent, Core, RPC

utils.setup_logging()
_log = logging.getLogger(__name__)
__version__ = '0.4'


# https://www.geeksforgeeks.org/python-creating-multidimensional-dictionary/
# Multi dimensional dictionary for RunningStats
def running_stats_multi_dict(dimensions, data_type, factor=120):
    if dimensions == 1:
        d = Runningstats(factor)
    else:
        d = defaultdict(
            lambda: running_stats_multi_dict(dimensions - 1, data_type))
    return d


def pricecontroller(config_path, **kwargs):
    config = utils.load_config(config_path)
    vip_identity = config.get('vip_identity', 'iiit.pricecontroller')
    # This agent needs to be named iiit.pricecontroller.
    # Pop the uuid id off the kwargs
    kwargs.pop('identity', None)

    Agent.__name__ = 'PriceController_Agent'
    return PriceController(config_path, identity=vip_identity, **kwargs)


class PcaState(IntEnum):
    online = 0
    standalone = 1
    standby = 2
    pass


class PcaMode(IntEnum):
    pass_on_pp = 0
    default_opt = 1
    extern_opt = 2
    pass


class PriceController(Agent):
    """
    Price Controller
    """
    # initialized  during __init__ from config

    _us_bid_timeout = None  # type: int
    _lc_bid_timeout = None  # type: int

    _period_read_data = None
    _period_process_loop = None

    _vb_vip_identity = None
    _topic_price_point_us = None
    _topic_price_point = None
    _topic_energy_demand_ds = None
    _topic_energy_demand = None

    _pca_state = None  # type: PcaState
    _pca_mode = None  # type: PcaMode

    _mode_pass_on_params = None
    _mode_default_opt_params = None
    _mode_extrn_opt_params = None

    _device_id = None
    _discovery_address = None

    _published_us_bid_ted = None

    # local ed agents vip_identities registered with the bridge
    _local_ed_agents = None
    # local device ids registered with the bridge
    _local_device_ids = None
    # ds device ids registered with the bridge
    _ds_device_ids = None

    _us_senders_list = None
    _ds_senders_list = None

    discovery_address = None
    device_id = None

    us_opt_pp_msg = None  # type: ISPACE_Msg
    us_bid_pp_msg = None  # type: ISPACE_Msg

    lc_opt_pp_msg_list = None  # type: list
    lc_bid_pp_msg_list = None  # type: list

    external_vip_identity = None

    _run__local_bidding_process = False
    _run_process_loop = False
    _target_achieved = False
    _us_bid_ready = False

    # opt_ap --> act_pwr@opt_pp, bid_ed --> bid_energy_demand@bid_pp
    # various buckets

    # local devices bid energy demands for local bid pp
    _local_bid_ed = None
    # downstream devices bid energy demands for local dib pp
    _ds_bid_ed = None

    # local devices bid energy demands for upstream bid pp
    _us_local_bid_ed = None  # bid energy demands
    # downstream devices bid energy demands for upstream bid pp
    _us_ds_bid_ed = None

    # local devices active power for upstream opt pp
    _us_local_opt_ap = None
    # downstream devices active power for upstream opt pp
    _us_ds_opt_ap = None

    # running stats factor (window)
    _rc_factor = None

    # Multi dimensional dictionary for RunningStats
    # _rs[DEVICE_ID][ENERGY_CATEGORY]
    _rs = {}

    # Exponential weighted moving average
    # _rs[DEVICE_ID][ENERGY_CATEGORY].exp_wt_mv_avg()

    def __init__(self, config_path, **kwargs):
        super(PriceController, self).__init__(**kwargs)
        _log.debug('vip_identity: ' + self.core.identity)

        self.config = utils.load_config(config_path)
        self._agent_id = self.config['agentid']

        # local device_ids
        self._us_local_opt_ap = {}
        self._us_local_bid_ed = {}
        self._local_bid_ed = {}

        # ds device ids
        #   opt_ap --> act_pwr@opt_pp, bid_ed --> bid_energy_demand@bid_pp
        self._us_ds_opt_ap = {}
        self._us_ds_bid_ed = {}
        self._ds_bid_ed = {}

        self._device_id = None
        self._ip_addr = None
        self._discovery_address = None

        return

    @Core.receiver('onsetup')
    def setup(self, sender, **kwargs):
        _log.info(self.config['message'])

        self._period_read_data = self.config.get('period_read_data', 30)
        self._period_process_loop = self.config.get('period_process_loop', 1)

        pca_state_s = self.config.get('pca_state', 'online')
        self._pca_state = PcaState[pca_state_s.lower()]

        pca_mode_s = self.config.get('pca_mode', 'pass_on_pp')
        self._pca_mode = PcaMode[pca_mode_s.lower()]

        self._mode_pass_on_params = self.config.get(
            'mode_pass_on_params', {
                "bid_timeout": 20
            }
        )

        self._mode_default_opt_params = self.config.get(
            'mode_default_opt_params', {
                "us_bid_timeout": 900,
                "lc_bid_timeout": 180,
                "max_iterations": 10,
                "epsilon": 100,
                "gamma": 0.0001,
                "alpha": 0.0035,
                "weight_factors": [0.5, 0.5]
            }
        )

        self._mode_extrn_opt_params = self.config.get(
            'mode_extrn_opt_params', {
                "vip_identity": "iiit.external_optimizer",
                "pp_topic": "pca/pricepoint",
                "ed_topic": "pca/energydemand"
            }
        )

        if self._pca_mode == PcaMode.pass_on_pp:
            self._us_bid_timeout = self._mode_pass_on_params[
                'bid_timeout'
            ]
        elif self._pca_mode == PcaMode.default_opt:
            self._us_bid_timeout = self._mode_default_opt_params[
                'us_bid_timeout'
            ]
            self._lc_bid_timeout = self._mode_default_opt_params[
                'lc_bid_timeout'
            ]
        else:
            self._us_bid_timeout = 900
            self._lc_bid_timeout = 120

        self._rc_factor = self.config.get('rc_factor', 120)
        self._rs = running_stats_multi_dict(3, list, self._rc_factor)

        self._vb_vip_identity = self.config.get(
            'vb_vip_identity',
            'iiit.volttronbridge'
        )
        self._topic_price_point_us = self.config.get(
            'pricePoint_topic_us',
            'us/pricepoint'
        )
        self._topic_price_point = self.config.get(
            'pricePoint_topic',
            'building/pricepoint'
        )
        self._topic_energy_demand_ds = self.config.get(
            'energyDemand_topic_ds',
            'ds/energydemand'
        )
        self._topic_energy_demand = self.config.get(
            'energyDemand_topic',
            'building/energydemand'
        )
        return

    @Core.receiver('onstart')
    def startup(self, sender, **kwargs):
        _log.info('Starting PriceController...')

        # retrieve self._device_id, self._ip_addr, self._discovery_address
        # from the bridge. this fn is a blocking call
        retrieve_details_from_vb(self, 5)

        # register rpc routes with MASTER_WEB
        # register_rpc_route is a blocking call
        register_rpc_route(self, 'pca', 'rpc_from_net', 5)

        self._us_senders_list = [self._vb_vip_identity, 'iiit.pricepoint']
        self._ds_senders_list = [self._vb_vip_identity]

        # check if there is a need to retrieve these details at a regular
        # interval. currently the details are retrieved on a new ed msg
        # i.e, on_ds_ed() self._topic_energy_demand_ds
        self._local_ed_agents = []
        self._local_device_ids = []
        self._ds_device_ids = []

        discovery_address = self._discovery_address
        device_id = self._device_id
        self.us_opt_pp_msg = get_default_pp_msg(discovery_address, device_id)
        self.us_bid_pp_msg = get_default_pp_msg(discovery_address, device_id)

        self.external_vip_identity = None

        # subscribing to _topic_price_point_us
        self.vip.pubsub.subscribe(
            'pubsub',
            self._topic_price_point_us,
            self.on_new_us_pp
        )

        # subscribing to ds energy demand,
        # vb publishes ed from registered ds to this topic
        self.vip.pubsub.subscribe(
            'pubsub',
            self._topic_energy_demand_ds,
            self.on_ds_ed
        )

        # periodically publish total active power (tap) to local/energydemand
        # vb RPCs this value to the next level. since time period is much
        # larger (default 30s, i.e, 2 reading per min), need not wait to
        # receive from all devices. any ways this is used for monitoring
        # purpose and the readings are averaged over a period
        self.core.periodic(
            self._period_read_data,
            self.aggregator_us_tap,
            wait=None
        )

        # subscribing to external pp topic
        if self._pca_mode == PcaMode.extern_opt:
            self.vip.pubsub.subscribe('pubsub',
                                      self._mode_extrn_opt_params['pp_topic'],
                                      self.on_new_extrn_pp
                                      )

        self._published_us_bid_ted = True
        # at regular interval check if all bid ds ed received, 
        # if so compute ted and publish to local/energydemand
        # (vb RPCs this value to the next level)
        self.core.periodic(
            self._period_process_loop,
            self.aggregator_us_bid_ted,
            wait=None
        )

        # default_opt process loop, i.e, each iteration's periodicity
        # if the cycle time (time consumed for each iteration) is more than
        # periodicity, the next iterations gets delayed.
        self.core.periodic(
            self._period_process_loop,
            self.process_loop,
            wait=None
        )

        _log.info('startup() - Done. Agent is ready')
        return

    @Core.receiver('onstop')
    def onstop(self, sender, **kwargs):
        _log.debug('onstop()')

        self._us_local_opt_ap.clear()
        self._us_local_bid_ed.clear()
        self._local_bid_ed.clear()

        self._us_ds_opt_ap.clear()
        self._us_ds_bid_ed.clear()
        self._ds_bid_ed.clear()

        _log.debug('un registering rpc routes')
        self.vip.rpc.call(
            MASTER_WEB,
            'unregister_all_agent_routes'
        ).get(timeout=10)
        return

    @Core.receiver('onfinish')
    def onfinish(self, sender, **kwargs):
        _log.debug('onfinish()')
        return

    # noinspection PyArgumentList
    @RPC.export
    def rpc_from_net(self, header, message):
        rpcdata = jsonrpc.JsonRpcData(None, None, None, None, None)
        try:
            rpcdata = jsonrpc.JsonRpcData.parse(message)
            _log.debug('rpc_from_net()... '
                       # + 'header: {}'.format(header)
                       + ', rpc method: {}'.format(rpcdata.method)
                       # + ', rpc params: {}'.format(rpcdata.params)
                       )
            if rpcdata.method == 'ping':
                result = True
            elif (
                    rpcdata.method == 'state'
                    and header['REQUEST_METHOD'].upper() == 'GET'
            ):
                result = self.get_pca_state()
            elif (
                    rpcdata.method == 'state'
                    and header['REQUEST_METHOD'].upper() == 'POST'
            ):
                result = self._set_pca_state(rpcdata.id, message)
            elif (
                    rpcdata.method == 'mode'
                    and header['REQUEST_METHOD'].upper() == 'GET'
            ):
                result = self.get_pca_mode()
            elif (
                    rpcdata.method == 'mode'
                    and header['REQUEST_METHOD'].upper() == 'POST'
            ):
                result = self._set_pca_mode(rpcdata.id, message)
            elif (
                    rpcdata.method == 'external-optimizer'
                    and header['REQUEST_METHOD'].upper() == 'POST'
            ):
                result = self._register_external_opt_agent(
                    rpcdata.id,
                    message
                )
            else:
                return jsonrpc.json_error(
                    rpcdata.id,
                    jsonrpc.METHOD_NOT_FOUND,
                    'Invalid method {}'.format(rpcdata.method)
                )
        except KeyError as ke:
            msg = 'Invalid params {}, error: {}'.format(rpcdata.params,
                                                        ke.message)
            error = jsonrpc.json_error(rpcdata.id, jsonrpc.INVALID_PARAMS, msg)
            return error
        except Exception as e:
            msg = 'Oops!!! Unhandled exception {}'.format(e.message)
            error = jsonrpc.json_error(rpcdata.id, jsonrpc.UNHANDLED_EXCEPTION,
                                       msg)
            return error
        if result:
            result = jsonrpc.json_result(rpcdata.id, result)
        return result

    # noinspection PyArgumentList
    @RPC.export
    def ping(self):
        return True

    # noinspection PyArgumentList
    @RPC.export
    def get_pca_state(self):
        return self._pca_state

    # noinspection PyArgumentList
    @RPC.export
    def set_pca_state(self, state):
        if state not in PcaState:
            return False
        self._pca_state = PcaState(state)
        return True

    # noinspection PyArgumentList
    @RPC.export
    def get_pca_mode(self):
        return self._pca_mode

    # noinspection PyArgumentList
    @RPC.export
    def set_pca_mode(self, mode):
        if mode not in PcaMode:
            return False
        self._pca_mode = PcaMode(mode)
        return True

    def _set_pca_state(self, rpcdata_id, message):
        state = jsonrpc.JsonRpcData.parse(message).params['state']
        success = self.set_pca_state(state)
        if not success:
            return jsonrpc.json_error(rpcdata_id,
                                      jsonrpc.PARSE_ERROR,
                                      'Invalid option!!!'
                                      )
        return True

    def _set_pca_mode(self, rpcdata_id, message):
        mode = jsonrpc.JsonRpcData.parse(message).params['mode']
        success = self.set_pca_mode(self, mode)
        if not success:
            return jsonrpc.json_error(
                rpcdata_id,
                jsonrpc.PARSE_ERROR,
                'Invalid option!!!'
            )
        return True

    def _register_external_opt_agent(self, rpcdata_id, message):
        params = jsonrpc.JsonRpcData.parse(message).params
        external_vip_identity = params['vip_identity']
        if external_vip_identity is None:
            return jsonrpc.json_error(
                rpcdata_id,
                jsonrpc.PARSE_ERROR,
                'Invalid option!!!'
            )
        self.external_vip_identity = external_vip_identity
        return True

    def on_new_extrn_pp(self, peer, sender, bus, topic, headers, message):
        _log.debug('on_new_us_pp()')
        if self._pca_mode != PcaMode.extern_opt:
            return
        # check if this agent is not disabled
        if self._pca_state == PcaState.standby:
            _log.debug('[LOG] PCA mode: STANDBY, do nothing')
            return

        # check message type before parsing
        if not check_msg_type(message, MessageType.price_point):
            return

        valid_senders_list = [self.external_vip_identity]
        minimum_fields = ['value', 'price_id']
        validate_fields = ['value', 'price_id', 'isoptimal']
        valid_price_ids = []
        (success, pp_msg) = valid_bustopic_msg(
            sender,
            valid_senders_list,
            minimum_fields,
            validate_fields,
            valid_price_ids,
            message
        )
        if not success or pp_msg is None:
            return
        else:
            _log.debug(
                'New pp msg on the local-bus, topic: {}'.format(topic)
            )

        if pp_msg.get_isoptimal():
            # TODO: re-look at this scenario
            # self.lc_opt_pp_msg = copy(pp_msg)
            pass
        else:
            self.lc_bid_pp_msg = copy(pp_msg)

            pub_topic = self._topic_price_point
            pub_msg = pp_msg.get_json_message(self._agent_id, 'bus_topic')
            _log.info('[LOG] Price Point, Msg: {}'.format(pub_msg))
            _log.debug('Publishing to local bus topic: {}'.format(pub_topic))
            publish_to_bus(self, pub_topic, pub_msg)
            _log.debug('done.')
            return

        return

    def on_new_us_pp(self, peer, sender, bus, topic, headers, message):
        _log.debug('on_new_us_pp()')
        if self._pca_mode not in [PcaMode.pass_on_pp, PcaMode.default_opt]:
            return

        # check if this agent is not disabled
        if self._pca_state == PcaState.standby:
            _log.debug('[LOG] PCA state: STANDBY, do nothing')
            return

        # check message type before parsing
        if not check_msg_type(message, MessageType.price_point):
            return

        valid_senders_list = self._us_senders_list
        minimum_fields = ['value', 'price_id']
        validate_fields = ['value', 'price_id', 'isoptimal']
        valid_price_ids = []
        (success, pp_msg) = valid_bustopic_msg(
            sender,
            valid_senders_list,
            minimum_fields,
            validate_fields,
            valid_price_ids,
            message
        )
        if not success or pp_msg is None:
            return
        elif pp_msg in [self.us_opt_pp_msg, self.us_bid_pp_msg]:
            _log.warning(
                'received a duplicate pp_msg'
                + ', price_id: {}!!!'.format(pp_msg.get_price_id())
            )
            return
        else:
            _log.debug('New pp msg on the us-bus, topic: {}'.format(topic))

        # keep a track of us pp_msg
        price_id = pp_msg.get_price_id()
        price = pp_msg.get_value()
        if pp_msg.get_isoptimal():
            self.us_opt_pp_msg = copy(pp_msg)
            _log.debug(
                '***** New optimal price point from us:'
                + ' {:0.2f}'.format(price)
                + ' , price_id: {}'.format(price_id)
            )
        else:
            self.us_bid_pp_msg = copy(pp_msg)
            _log.debug(
                '***** New bid price point from us:'
                + ' {:0.2f}'.format(price)
                + ' , price_id: {}'.format(price_id)
            )
        # log this msg
        # _log.info('[LOG] pp msg from us: {}'.format(pp_msg))

        if pp_msg.get_isoptimal():
            # reset running stats
            # self._rs = running_stats_multi_dict(3, list, self._rc_factor)
            pass
        else:
            # re-initialize aggregator_us_bid_ted
            self._published_us_bid_ted = False

        if self._pca_mode == PcaMode.pass_on_pp:
            _log.info('[LOG] PCA mode: PASS_ON_PP')
            pub_topic = self._topic_price_point
            pub_msg = pp_msg.get_json_message(self._agent_id, 'bus_topic')
            _log.info(
                '[LOG] Price Point for local/ds devices, Msg:'
                + ' {}'.format(pub_msg)
            )
            _log.debug('Publishing to local bus topic: {}'.format(pub_topic))
            publish_to_bus(self, pub_topic, pub_msg)
            _log.debug('done.')
            return

        elif (
                self._pca_mode == PcaMode.default_opt
                and pp_msg.get_isoptimal()
        ):
            _log.info('[LOG] PCA mode: DEFAULT_OPT & pp_msg is opt price')
            pub_topic = self._topic_price_point
            pub_msg = pp_msg.get_json_message(self._agent_id, 'bus_topic')
            _log.info(
                '[LOG] Price Point for local/ds devices, Msg:'
                + ' {}'.format(pub_msg)
            )
            _log.debug('Publishing to local bus topic: {}'.format(pub_topic))
            publish_to_bus(self, pub_topic, pub_msg)
            _log.debug('done.')
            return

        elif (
                self._pca_mode == PcaMode.default_opt
                and not pp_msg.get_isoptimal()
        ):
            _log.info('[LOG] PCA mode: DEFAULT_OPT & pp_msg is bid price')

            # init bidding process
            self._init_bidding_process()

            _log.debug('done.')
            return

        elif self._pca_mode == PcaMode.extern_opt:
            _log.info('[LOG] PCA mode: DEFAULT_OPT')
            _log.warning('not yet implemented!!!')
            return

        return

    def _init_bidding_process(self):

        self._iter_count = 0

        # list for pp_msg
        _log.debug('Compute new price points...')
        target_achieved, new_pp_msg_list = self._compute_new_prices()

        self.lc_bid_pp_msg_list = copy(new_pp_msg_list)
        # _log.info('new bid pp_msg_list: {}'.format(new_pp_msg_list))

        self._pub_pp_messages(new_pp_msg_list)

        # activate process_loop(), iterate for new bids from ds devices
        self._run_process_loop = True
        return

    def _pub_pp_messages(self, pp_messages):
        # maybe publish a list of the pp messages
        # and let the bridge do_rpc concurrently
        for pp_msg in pp_messages:
            # _log.info('new msg: {}'.format(msg))
            pub_topic = self._topic_price_point
            pub_msg = pp_msg.get_json_message(
                self._agent_id,
                'bus_topic'
            )
            device_id = (pp_msg.get_dst_device_id()
                         if pp_msg.get_one_to_one()
                         else 'local/ds devices'
                         )
            _log.info(
                '[LOG] Price Point for {}'.format(device_id)
                + ', Msg: {}'.format(pub_msg)
            )
            _log.debug(
                'Publishing to local bus topic:'
                + ' {}'.format(pub_topic)
            )
            publish_to_bus(self, pub_topic, pub_msg)

    # compute new bid price point for every local device and ds devices
    # return list for pp_msg
    def _compute_new_prices(self):
        _log.debug('_computeNewPrice()')
        '''
        computes the new prices
        cf may use priorities (manager assign individual device priorities
                                    or group priorities based on device 
                                    categories)
        returns array of new pp_msg with one_to_one TRUE, if priorities are 
        enabled
                --> array of new pp_msg with one_to_one FALSE
                , if priorities are disabled (i.e, equal priorities)

        TODO: implement the algorithm to compute the new price
             based on Walras algorithm.
              config.get (optimization cost function)
              based on some initial condition like ed, us_new_pp, etc, 
              compute new_pp
              publish to bus
        
        optimization algorithm
          ed_target = r% x ed_optimal
          EPSILON = 10       # deadband
          gamma = stepsize
          max_iter = 900 (assuming each iter is 30sec and max time spent
            is 10 min)
          
          count_iter = 0
          pp_old = pp_opt
          pp_new = pp_old
          do while (ed_target - ed_current > EPSILON)
              if (count_iter < max_iter)
                   pp_new = pp_old + gamma(ed_current - ed_previous)
                   pp_old = pp_new
           
          pp_opt = pp_new
        
              iterate till optimization condition satisfied
              when new pp is published, the new ed for all devices is 
                accumulated by on_new_ed()
              once all the eds are received call this function again
              publish the new optimal pp
        '''

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
        # explore if need to use same price_id or different ones
        price_id = randint(0, 99999999)
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

        target_achieved, new_pricepoint = self._gradient_descent(old_pricepoint,
                                                                 old_ted,
                                                                 target
                                                                 )

        # case _pca_state == PcaState.online
        if target_achieved and self._pca_state == PcaState.online:
            # local optimal reached, publish this as bid to the us pp_msg
            self._us_bid_ready = True
            return True, []

        # case _pca_state == PcaState.standalone
        isoptimal = (
            True if (
                    target_achieved
                    and self._pca_state == PcaState.standalone
            )
            else False
        )

        pp_messages = []
        for device_idx in device_list:
            pp_msg = ISPACE_Msg(msg_type, one_to_one, isoptimal,
                                new_pricepoint[device_idx], value_data_type,
                                units, price_id, src_ip, src_device_id,
                                dst_ip[device_idx], dst_device_id[device_idx],
                                duration, ttl, ts, tz)
            pp_messages.insert(pp_msg)

        return target_achieved, pp_messages

    def _gradient_descent(self, pp_old, ed_prev, target):
        alpha = self._mode_default_opt_params['alpha']
        gamma = self._mode_default_opt_params['gamma']
        epsilon = self._mode_default_opt_params['epsilon']
        max_iters = self._mode_default_opt_params['max_iterations']
        uc_bid_timeout = self._mode_default_opt_params['uc_bid_timeout']
        lc_bid_timeout = self._mode_default_opt_params['lc_bid_timeout']
        wt_factors = self._mode_default_opt_params['weight_factors']

        _log.debug(
            'alpha: {}, gamma: {}, epsilon: {}, max_iters: {}, ' +
            'us_bid_timeout: {}, lc_bid_timeout: {}, wt_factors: {}'.format(
                alpha, gamma, epsilon, max_iters, uc_bid_timeout,
                lc_bid_timeout, wt_factors
            )
        )

        _log.debug(
            'old_pricepoint: {}'.format(pp_old)
            + ', old_ted: {}'.format(ed_prev)
            + ', target: {}'.format(target)
        )

        ed_current = None
        ed_prev = None

        total_ed_current = wt_factors * ed_current
        total_ed_prev = wt_factors * ed_prev

        delta = total_ed_current - total_ed_prev

        pp_new = (
                pp_old
                + gamma * delta
                + alpha * self._delta_omega       # momentum
        )

        # remember the update delta_omega at each iteration
        self._delta_omega = pp_new - pp_old

        # target achieved is true,
        #   if us bid timed out
        #       or self._iter_count > max_iters
        #       or delta <= epsilon
        us_bid_timed_out = self._us_bid_timed_out()
        target_achieved = (
            True
            if (
                        us_bid_timed_out
                        or self._iter_count > max_iters
                        or delta <= epsilon
            )
            else False
        )

        return target_achieved, pp_new

    # periodically run this function to check if ted from all ds received or
    # ted_timed_out
    def process_loop(self):
        if not self._pca_mode == PcaMode.default_opt:
            return

        if not self._run_process_loop:
            return

        new_pp_msg_list = []

        # check if all the bids are received from both local & ds devices
        # rcvd_all_lc = local(lc) bids for local(lc) bid price
        rcvd_all_lc = self._rcvd_all_lc_bid_ed_lc(self._local_device_ids)
        # rcvd_all_ds = downstream(ds) bids for upstream(us) bid price
        rcvd_all_ds = self._rcvd_all_lc_bid_ed_ds(self._ds_device_ids)

        lc_bid_timed_out = self._lc_bid_timed_out()

        if not (rcvd_all_lc and rcvd_all_ds):
            price_id = self.lc_bid_pp_msg.get_price_id()
            if not lc_bid_timed_out:
                retry_time = self._period_process_loop
                _log.debug(
                    'not all bids received and not yet timed out'
                    + ', bid price_id: {}!!!'.format(price_id)
                    + ' rcvd all lc bid ed lc: {}'.format(rcvd_all_lc)
                    + ' rcvd_all lc bid ed ds: {}'.format(rcvd_all_ds)
                    + ' lc_bid_timed_out: {}'.format(lc_bid_timed_out)
                    + ', will try again in {} sec'.format(retry_time)
                )
                return

            else:
                _log.warning('!!! us bid pp timed out'
                             + ', bid price_id: {}!!!'.format(price_id)
                             )
                target_achieved = True
        else:
            _log.debug('Compute new price points...')
            target_achieved, new_pp_msg_list = self._compute_new_prices()

        #       if new_pp_isopt
        #           # local optimal reached
        #           publish_ed(local/ed, _ed, us_bid_pp_id)
        #           # if next level accepts this bid, the new target is this ed
        #       based on opt condition _computeNewPrice can publish new bid_pp
        #       or
        # and save data to self._ds_bid_ed

        if target_achieved and self._pca_state == PcaState.online:
            # local optimal reached, publish this as bid to the us pp_msg
            self._us_bid_ready = True
        elif target_achieved and self._pca_state == PcaState.standalone:
            self.lc_opt_pp_msg_list = copy(new_pp_msg_list)
        else:
            self.lc_bid_pp_msg_list = copy(new_pp_msg_list)
            # publish these pp_messages
            self._pub_pp_messages(new_pp_msg_list)

        # clear corresponding buckets
        self._local_bid_ed.clear()
        self._ds_bid_ed.clear()

        if target_achieved:
            # stop the process loop
            self._run_process_loop = False
        return

    def _lc_bid_timed_out(self):
        """

        :rtype: bool
        """
        if self._lc_bid_timeout == 0:
            return False
        s_now = datetime.datetime.utcnow().isoformat(' ') + 'Z'
        now = dateutil.parser.parse(s_now)
        ts = dateutil.parser.parse(self.lc_bid_pp_msg.get_ts())
        return (True
                if (now - ts).total_seconds() > self._lc_bid_timeout
                else False
                )

    def _us_bid_timed_out(self):
        """

        :rtype: bool
        """
        if self._us_bid_timeout == 0:
            return False
        s_now = datetime.datetime.utcnow().isoformat(' ') + 'Z'
        now = dateutil.parser.parse(s_now)
        ts = dateutil.parser.parse(self.us_bid_pp_msg.get_ts())
        return (True
                if (now - ts).total_seconds() > self._us_bid_timeout
                else False
                )

    def _rcvd_all_us_bid_ed_lc(self, vb_local_device_ids):
        # may be some devices may have disconnected
        #      i.e., devices_count >= len(vb_devices_count)
        return (True
                if len(self._us_local_bid_ed) >= len(vb_local_device_ids)
                else False
                )

    def _rcvd_all_us_bid_ed_ds(self, vb_ds_device_ids):
        # may be some devices may have disconnected
        #      i.e., devices_count >= len(vb_devices_count)
        return (True
                if len(self._us_ds_bid_ed) >= len(vb_ds_device_ids)
                else False
                )

    def _rcvd_all_lc_bid_ed_lc(self, vb_local_device_ids):
        # may be some devices may have disconnected
        #      i.e., devices_count >= len(vb_devices_count)
        return (True
                if len(self._local_bid_ed) >= len(vb_local_device_ids)
                else False
                )

    def _rcvd_all_lc_bid_ed_ds(self, vb_ds_device_ids):
        # may be some devices may have disconnected
        #      i.e., devices_count >= len(vb_devices_count)
        return (True
                if len(self._ds_bid_ed) >= len(vb_ds_device_ids)
                else False
                )

    def on_ds_ed(self, peer, sender, bus, topic, headers, message):
        _log.debug('on_ds_ed()')
        # check if this agent is not disabled
        if self._pca_state == PcaState.standby:
            _log.debug('[LOG] PCA mode: STANDBY, do nothing')
            return

        # 1. validate message
        # 2. check against valid pp ids
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

        # handle only ap or ed type messages
        if check_msg_type(message, MessageType.active_power):
            pass
        elif check_msg_type(message, MessageType.energy_demand):
            pass
        else:
            _log.warning('Not a ap nor ed msg!!!')
            return

        # if ping_vb_failed(self):
        #    _log.warning('!!! unable to contact bridge !!!')
        #    return

        self._local_ed_agents = self._rpcget_local_ed_agents()
        self._local_device_ids = self._rpcget_local_device_ids()
        self._ds_device_ids = self._rpcget_ds_device_ids()

        # unique senders list
        valid_senders_list = self._get_valid_senders()
        minimum_fields = ['value', 'price_id']
        validate_fields = ['value', 'price_id', 'isoptimal']
        valid_price_ids = self._get_valid_price_ids()
        (success, ed_msg) = valid_bustopic_msg(
            sender,
            valid_senders_list,
            minimum_fields,
            validate_fields,
            valid_price_ids,
            message
        )
        if not success or ed_msg is None:
            _log.warning(
                'valid_bustopic_msg success: {}'.format(success)
                + ', is ed_msg None? ed_msg: {}'.format(ed_msg)
            )
            return
        else:
            _log.debug(
                'New'
                + (' energy demand bid (ed)'
                   if ed_msg.get_msg_type() == MessageType.energy_demand
                   else ' active power (ap)'
                   )
                + ' msg on the local-bus, topic: {}'.format(topic)
            )

        _log.debug('Sorting the ed_msg...')
        self._sort_ed_msg(ed_msg)
        _log.debug('done.')
        return

    def _get_valid_senders(self):
        if self._pca_mode == PcaMode.pass_on_pp:
            valid_senders_list = (
                    self._ds_senders_list
                    + self._local_ed_agents
            )
        elif self._pca_mode == PcaMode.default_opt:
            valid_senders_list = (
                    self._ds_senders_list
                    + self._local_ed_agents
                    + self.core.identity
            )
        elif self._pca_mode == PcaMode.extern_opt:
            valid_senders_list = (
                    self._ds_senders_list
                    + self._local_ed_agents
                    + self._mode_extrn_opt_params['vip_identity']
            )
        else:
            _log.warning(
                '_get_valid_senders(), not implemented'
                + ' for pca_mode: {}'.format(self._pca_mode)
            )
            valid_senders_list = []
        return valid_senders_list

    def _sort_ed_msg(self, ed_msg):
        price_id = ed_msg.get_price_id()
        device_id = ed_msg.get_src_device_id()
        msg_type = ed_msg.get_msg_type()
        # success_ap and success_ed are mutually exclusive
        success_ap = True if msg_type == MessageType.active_power else False
        success_ed = True if msg_type == MessageType.energy_demand else False

        '''
        sort energy packet to respective buckets 
            
                           |--> _us_local_opt_ap    |
        us_opt_tap---------|                        |--> aggregator publishes 
        tap to us/energydemand
                           |--> _us_ds_opt_ap       |       at regular interval 


                           |--> _us_local_bid_ed    |
        us_bid_ted---------|                        |--> aggregator publishes 
        ted to us/energydemand 
                           |--> _us_ds_bid_ed       |       if received from 
                           all or timeout


                           |--> _local_bid_ed       |
        local_bid_ted------|                        |--> process_loop() 
        initiates
                           |--> _ds_bid_ed          |       _compute_new_price()
       '''
        # MessageType.active_power
        # aggregator publishes this data to local/energydemand
        if success_ap and price_id == self.us_opt_pp_msg.get_price_id():

            energy_cat = ed_msg.get_energy_category() or EnergyCategory.mixed

            # put data to local_tap bucket
            if device_id in self._local_device_ids:
                opt_tap = ed_msg.get_value()
                _log.info(
                    '[LOG] TAP opt from local ({})'.format(device_id)
                    + ' for us opt pp_msg({})):'.format(price_id)
                    + ' {:0.4f}'.format(opt_tap)
                )
                self._us_local_opt_ap[device_id] = opt_tap
                # update running stats
                self._rs[device_id][energy_cat].push(opt_tap)
                return
            # put data to ds_tap bucket
            elif device_id in self._ds_device_ids:
                opt_tap = ed_msg.get_value()
                _log.info(
                    '[LOG] TAP opt from ds ({})'.format(device_id)
                    + ' for us opt pp_msg({})):'.format(price_id)
                    + ' {:0.4f}'.format(opt_tap)
                )
                self._us_ds_opt_ap[device_id] = opt_tap
                # update running stats
                self._rs[device_id][energy_cat].push(opt_tap)
                return

        # MessageType.energy_demand
        # aggregator publishes this data to local/energydemand
        elif success_ed and price_id == self.us_bid_pp_msg.get_price_id():
            # put data to ds_tap bucket
            if device_id in self._local_device_ids:
                bid_ted = ed_msg.get_value()
                _log.info(
                    '[LOG] TED bid from local ({})'.format(device_id)
                    + ' for us bid pp_msg({})):'.format(price_id)
                    + ' {:0.4f}'.format(bid_ted)
                )
                self._us_local_bid_ed[device_id] = bid_ted
                return
            # put data to ds_tap bucket
            elif device_id in self._ds_device_ids:
                bid_ted = ed_msg.get_value()
                _log.info(
                    '[LOG] TED bid from ds ({})'.format(device_id)
                    + ' for us bid pp_msg({})):'.format(price_id)
                    + ' {:0.4f}'.format(bid_ted)
                )
                self._us_ds_bid_ed[device_id] = ed_msg.get_value()
                return

        # MessageType.energy_demand
        # process_loop() initiates _compute_new_price()
        elif success_ed and price_id == self.lc_bid_pp_msg.get_price_id():
            # put data to local_tap bucket
            if device_id in self._local_device_ids:
                bid_ted = ed_msg.get_value()
                _log.info(
                    '[LOG] TED bid from local ({})'.format(device_id)
                    + ' for local bid pp_msg({})):'.format(price_id)
                    + ' {:0.4f}'.format(bid_ted)
                )
                self._local_bid_ed[device_id] = ed_msg.get_value()
                return
            # put data to local_ted bucket
            elif device_id in self._ds_device_ids:
                bid_ted = ed_msg.get_value()
                _log.info(
                    '[LOG] TED bid from ds ({})'.format(device_id)
                    + ' for local bid pp_msg({})):'.format(price_id)
                    + ' {:0.4f}'.format(bid_ted)
                )
                self._ds_bid_ed[device_id] = ed_msg.get_value()
                return
        return

    # periodically publish total active power (tap) to local/energydemand
    def aggregator_us_tap(self):
        # since time period much larger (default 30s, i.e, 2 reading per min)
        # need not wait to receive active power from all devices
        # any ways this is used for monitoring purpose
        # and the readings are averaged over a period
        if (self._pca_state != PcaState.online
                or self._pca_mode not in PcaMode):
            if self._pca_state in [
                PcaState.standalone,
                # PcaState.standby
            ]:
                return
            else:
                # not implemented
                _log.warning(
                    'aggregator_us_tap() not implemented'
                    + ' pca_state: {}'.format(self._pca_state)
                    + ' pca_mode: {}'.format(self._pca_mode)
                )
            return

        # compute total active power (tap)
        opt_tap = self._calc_total(self._us_local_opt_ap, self._us_ds_opt_ap)

        # publish to local/energyDemand 
        # vb pushes(RPC) this value to the next level
        self._publish_opt_tap(opt_tap)

        # reset the corresponding buckets to zero
        self._us_local_opt_ap.clear()
        self._us_ds_opt_ap.clear()
        return

    def aggregator_us_bid_ted(self):
        # nothing to do, wait for new bid pp from us
        if self._published_us_bid_ted:
            return

        if self._pca_state in [
            PcaState.standalone,
            PcaState.standby
        ]:
            return

        if (
                self._pca_state != PcaState.online
                or self._pca_mode not in PcaMode
        ):
            # not implemented
            _log.warning('aggregator_us_tap() not implemented'
                         + ' pca_state: {}'.format(self._pca_state)
                         + ' pca_mode: {}'.format(self._pca_mode)
                         )
            return

        if self._pca_mode == PcaMode.pass_on_pp:
            success, bid_ted = self.aggr_mode_pass_on()
        elif self._pca_mode == PcaMode.default_opt:
            success, bid_ted = self.aggr_mode_default_opt()
        else:
            success, bid_ted = self.aggr_mode_extern_opt()

        if not success:
            self._published_us_bid_ted = False
            return

        # publish to local/energyDemand
        # vb pushes(RPC) this value to the next level
        self._publish_bid_ted(self.us_bid_pp_msg, bid_ted)

        self.us_bid_pp_msg = ISPACE_Msg(MessageType.price_point)
        self._published_us_bid_ted = True
        return

    def aggr_mode_pass_on(self):
        _log.debug('aggr_mode_pass_on(): {}'.format(self._pca_mode))

        # check if all the bids are received from both local & ds devices
        # rcvd_all_lc = local(lc) bids for upstream(us) bid price
        rcvd_all_lc = self._rcvd_all_us_bid_ed_lc(self._local_device_ids)
        # rcvd_all_ds = downstream(ds) bids for upstream(us) bid price
        rcvd_all_ds = self._rcvd_all_us_bid_ed_ds(self._ds_device_ids)

        # check timeout
        us_bid_timed_out = self._us_bid_timed_out()

        if not (rcvd_all_lc and rcvd_all_ds):
            price_id = self.us_bid_pp_msg.get_price_id()
            if not us_bid_timed_out:
                retry_time = self._period_process_loop
                _log.debug(
                    'not all bids received and not yet timed out'
                    + ', bid price_id: {}!!!'.format(price_id)
                    + ' rcvd all us bid ed lc: {}'.format(rcvd_all_lc)
                    + ' rcvd_all us bid ed ds: {}'.format(rcvd_all_ds)
                    + ' us_bid_timed_out: {}'.format(us_bid_timed_out)
                    + ', will try again in {} sec'.format(retry_time)
                )
                return False

            else:
                _log.warning('!!! us bid pp timed out'
                             + ', bid price_id: {}!!!'.format(price_id)
                             )

        # compute total energy demand (ted)
        bid_ted = self._calc_total(self._us_local_bid_ed, self._us_ds_bid_ed)

        # need to reset the corresponding buckets to zero
        self._us_local_bid_ed.clear()
        self._us_ds_bid_ed.clear()

        return True, bid_ted

    def aggr_mode_default_opt(self):
        _log.debug('aggr_mode_default_opt(): {}'.format(self._pca_mode))

        # check timeout
        us_bids_timeout = self._us_bid_timed_out()

        if not self._us_bid_ready:
            price_id = self.us_bid_pp_msg.get_price_id()
            if not us_bids_timeout:
                retry_time = self._period_process_loop
                _log.debug(
                    'not all bids received and not yet timed out'
                    + ', bid price_id: {}!!!'.format(price_id)
                    + ' us bid ready: {}'.format(self._us_bid_ready)
                    + ' us_bids_timeout: {}'.format(us_bids_timeout)
                    + ', will try again in {} sec'.format(retry_time)
                )
                return False

            else:
                _log.warning('!!! us bid pp timed out'
                             + ', bid price_id: {}!!!'.format(price_id)
                             )

        # compute total energy demand (ted)
        bid_ted = self._calc_total(self._local_bid_ed, self._ds_bid_ed)

        # need to reset the corresponding buckets to zero
        self._local_bid_ed.clear()
        self._ds_bid_ed.clear()

        return True, bid_ted

    def aggr_mode_extern_opt(self):
        _log.debug('aggr_mode_extern_opt(): {}'.format(self._pca_mode))
        success = True
        bid_ted = 0
        return success, bid_ted

    def aggregator_local_bid_ted(self):
        # this function is not required.
        # process_loop pickup the local individual bids
        # refer to process_loop()
        if self._pca_mode != PcaMode.default_opt:
            return
        return

    def _rpcget_local_ed_agents(self):
        # if rpc get failed, return the old copy
        result = self._local_ed_agents
        try:
            result = self.vip.rpc.call(
                self._vb_vip_identity,
                'local_ed_agents'
            ).get(timeout=1)
        except gevent.Timeout:
            _log.warning('gevent.Timeout in _rpcget_local_ed_agents()!!!')
            pass
        except Exception as e:
            _log.warning(
                'unable to get local ed agents vip_identities from bridge.'
                + ' message: {}'.format(e.message)
            )
            pass
        return result

    def _rpcget_local_device_ids(self):
        # if rpc get failed, return the old copy
        result = self._local_device_ids
        try:
            result = self.vip.rpc.call(
                self._vb_vip_identity,
                'get_local_device_ids'
            ).get(timeout=1)
        except gevent.Timeout:
            _log.warning('gevent.Timeout in _rpcget_local_device_ids()!!!')
            pass
        except Exception as e:
            # print(e)
            _log.warning(
                'unable to get local devices ids from bridge.'
                + ' message: {}'.format(e.message)
            )
            pass
        return result

    def _rpcget_ds_device_ids(self):
        # if rpc get failed, return the old copy
        result = self._ds_device_ids
        try:
            result = self.vip.rpc.call(
                self._vb_vip_identity,
                'get_ds_device_ids'
            ).get(timeout=1)
        except gevent.Timeout:
            _log.warning('gevent.Timeout in _rpcget_ds_device_ids()!!!')
            pass
        except Exception as e:
            # print(e)
            _log.warning(
                'unable to get ds device ids from bridge.'
                + ' message: {}'.format(e.message)
            )
            pass
        return result

    def _get_valid_price_ids(self):
        price_ids = []
        if self._pca_mode == PcaMode.pass_on_pp:
            opt_price_id = (
                self.us_opt_pp_msg.get_price_id()
                if self.us_opt_pp_msg is not None
                else ''
            )
            bid_price_id = (
                self.us_bid_pp_msg.get_price_id()
                if self.us_bid_pp_msg is not None
                else ''
            )
            price_ids = [opt_price_id, bid_price_id]
        else:
            _log.error(
                '_get_valid_price_ids() for mode {} not implemented'
                + '!!!'.format(self._pca_mode)
            )
        return price_ids

    def _publish_opt_tap(self, opt_tap):
        # create a ISPACE_Msg with MessageType.active_power
        # in response to us_opt_pp_msg
        tap_msg = tap_helper(
            self.us_opt_pp_msg,
            self._device_id,
            self._discovery_address,
            opt_tap,
            self._period_read_data,
            EnergyCategory.mixed
        )

        _log.debug(
            '***** Total Active Power(TAP) opt'
            + ' (for us pp_msg ({})):'.format(tap_msg.get_price_id())
            + ' {:0.4f}'.format(opt_tap)
        )
        # publish the total active power to the local message bus
        # volttron bridge pushes(RPC) this value to the next level
        pub_topic = self._topic_energy_demand
        pub_msg = tap_msg.get_json_message(self._agent_id, 'bus_topic')
        _log.info(
            '[LOG] Total Active Power(TAP) opt, Msg: {}'.format(pub_msg)
        )
        _log.debug('Publishing to local bus topic: {}'.format(pub_topic))
        publish_to_bus(self, pub_topic, pub_msg)
        _log.debug('done.')
        return

    def _publish_bid_ted(self, pp_msg, bid_ted):
        # already checked if all bids are received or timeout
        # create a MessageType.energy ISPACE_Msg
        ted_msg = ted_helper(
            pp_msg,
            self._device_id,
            self._discovery_address,
            bid_ted,
            self._period_read_data,
            EnergyCategory.mixed
        )

        _log.debug(
            '***** Total Energy Demand(TED) bid'
            + ' (for us pp_msg ({})):'.format(ted_msg.get_price_id())
            + ' {:0.4f}'.format(bid_ted)
        )
        # publish the total energy demand to the local message bus
        # volttron bridge pushes(RPC) this value to the next level
        pub_topic = self._topic_energy_demand
        pub_msg = ted_msg.get_json_message(self._agent_id, 'bus_topic')
        _log.info(
            '[LOG] Total Energy Demand(TED) bid, Msg: {}'.format(pub_msg)
        )
        _log.debug('Publishing to local bus topic: {}'.format(pub_topic))
        publish_to_bus(self, pub_topic, pub_msg)
        _log.debug('done.')
        return

    def _calc_total(self, local_bucket, ds_bucket):
        # current vb registered devices that had published active power
        # may be some devices may have disconnected
        #      i.e., devices_count >= len(vb_devices_count)
        #       reconcile the device ids and match _ap[] with device_id
        new_local_device_ids = list(
            set(local_bucket.keys())
            & set(self._local_device_ids)
        )
        new_ds_device_ids = list(
            set(ds_bucket.keys())
            & set(self._ds_device_ids)
        )
        # compute total
        total = 0.0
        for device_id in new_local_device_ids:
            if device_id in local_bucket:
                total += local_bucket[device_id]
        for device_id in new_ds_device_ids:
            if device_id in ds_bucket:
                total += ds_bucket[device_id]
        return total


def main(argv=None):
    """Main method called by the eggsecutable."""
    if argv is None:
        argv = sys.argv
    _log.debug('main(), argv: {}'.format(argv))
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

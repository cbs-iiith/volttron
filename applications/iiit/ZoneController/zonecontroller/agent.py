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

import decimal
import logging
import sys
import time
from copy import copy
from random import randint

import gevent
import gevent.event

from applications.iiit.Utils.ispace_msg import (MessageType, EnergyCategory,
                                                ISPACE_Msg, ISPACE_Msg_Budget,
                                                round_off_pp)
from applications.iiit.Utils.ispace_msg_utils import (check_msg_type,
                                                      tap_helper,
                                                      ted_helper,
                                                      get_default_pp_msg,
                                                      valid_bustopic_msg)
from applications.iiit.Utils.ispace_utils import (isclose, get_task_schdl,
                                                  cancel_task_schdl,
                                                  publish_to_bus, mround,
                                                  retrieve_details_from_vb,
                                                  register_with_bridge,
                                                  register_rpc_route,
                                                  unregister_with_bridge,
                                                  running_stats_multi_dict,
                                                  calc_energy_wh)
from volttron.platform import jsonrpc
from volttron.platform.agent import utils
from volttron.platform.agent.known_identities import (
    MASTER_WEB)
from volttron.platform.vip.agent import Agent, Core, RPC

utils.setup_logging()
_log = logging.getLogger(__name__)
__version__ = '0.4'

# checking if a floating point value is “numerically zero” by checking if it
# is lower than epsilon
EPSILON = 1e-04

SCHEDULE_AVLB = 1
SCHEDULE_NOT_AVLB = 0

E_UNKNOWN_CCE = -4
E_UNKNOWN_TSP = -5
E_UNKNOWN_LSP = -6
E_UNKNOWN_CLE = -9


def zonecontroller(config_path, **kwargs):
    config = utils.load_config(config_path)
    vip_identity = config.get('vip_identity', 'iiit.zonecontroller')
    # This agent needs to be named iiit.zonecontroller. Pop the uuid id off
    # the kwargs
    kwargs.pop('identity', None)

    Agent.__name__ = 'ZoneController_Agent'
    return ZoneController(config_path, identity=vip_identity, **kwargs)


class ZoneController(Agent):
    """
    Zone Controller
    """
    # initialized  during __init__ from config
    _period_read_data = None
    _period_process_pp = None
    _price_point_latest = None  # type: float

    _vb_vip_identity = None
    _root_topic = None
    _topic_energy_demand = None
    _topic_price_point = None

    _device_id = None
    _discovery_address = None

    # any process that failed to apply pp sets this flag False
    _process_opt_pp_success = False

    _zone_tsp = 0
    _zone_lsp = 0

    _pf_zn_ac = None
    _pf_zn_light = None

    _edf_zn_ac = None
    _edf_zn_light = None

    _valid_senders_list_pp = None  # type: list
    _opt_pp_msg_current = None  # type: ISPACE_Msg
    _opt_pp_msg_latest = None  # type: ISPACE_Msg
    _bid_pp_msg_latest = None  # type: ISPACE_Msg

    _bud_msg_latest = None  # type: ISPACE_Msg_Budget
    _latest_msg_type = None  # type: MessageType

    _gd_params = None

    # running stats factor (window)
    _rc_factor = None  # type: int

    # Multi dimensional dictionary for RunningStats
    # _rs[DEVICE_ID][ENERGY_CATEGORY]
    _rs = {}

    # Exponential weighted moving average
    # _rs[DEVICE_ID][ENERGY_CATEGORY].exp_wt_mv_avg()

    def __init__(self, config_path, **kwargs):
        super(ZoneController, self).__init__(**kwargs)
        _log.debug('vip_identity: ' + self.core.identity)

        self.config = utils.load_config(config_path)
        self._agent_id = self.config['agentid']

        self._config_get_points()
        self._config_get_init_values()
        self._config_get_price_functions()
        return

    @Core.receiver('onsetup')
    def setup(self, sender, **kwargs):
        _log.info(self.config['message'])

        self._gd_params = self.config.get(
            'gd_params', {
                "max_iterations": 1000,
                "max_repeats": 10,
                "deadband": 100,
                "gamma": {
                    "ac": 0.0002,
                    "light": 0.0125
                },
                "weight_factors": {
                    "ac": 0.50,
                    "light": 0.50
                }
            }
        )

        self._rc_factor = self.config.get('rc_factor', 120)
        self._rs = running_stats_multi_dict(3, list, self._rc_factor)

        return

    @Core.receiver('onstart')
    def startup(self, sender, **kwargs):
        _log.info('Starting ZoneController...')

        # retrieve self._device_id, self._ip_addr, self._discovery_address
        # from the bridge
        # retrieve_details_from_vb is a blocking call
        retrieve_details_from_vb(self, 5)

        # register rpc routes with MASTER_WEB
        # register_rpc_route is a blocking call
        register_rpc_route(self, 'zonecontroller', 'rpc_from_net', 5)

        # register this agent with vb as local device for posting active
        # power & bid energy demand
        # pca picks up the active power & energy demand bids only if
        # registered with vb
        # require self._vb_vip_identity, self.core.identity, self._device_id
        # register_with_bridge is a blocking call
        register_with_bridge(self, 5)

        self._valid_senders_list_pp = ['iiit.pricecontroller']

        # any process that failed to apply pp sets this flag False
        # setting False here to initiate applying default pp on agent start
        self._process_opt_pp_success = False

        # on successful process of apply_pricing_policy with the latest opt
        # pp, current = latest
        self._opt_pp_msg_current = get_default_pp_msg(self._discovery_address,
                                                      self._device_id)
        # latest opt pp msg received on the message bus
        self._opt_pp_msg_latest = get_default_pp_msg(self._discovery_address,
                                                     self._device_id)

        self._bid_pp_msg_latest = get_default_pp_msg(self._discovery_address,
                                                     self._device_id)
        self._latest_msg_type = MessageType.price_point

        self._run_bms_test()

        self._zone_tsp = 0
        self._zone_lsp = 0

        # get the latest values (states/levels) from h/w
        # self.getInitialHwState()
        # time.sleep(1) # yield for a movement

        # periodically publish total active power to volttron bus
        # active power is computed at regular interval (_period_read_data
        # default(30s))
        # this power corresponds to current opt pp
        # tap --> total active power (Wh)
        self.core.periodic(self._period_read_data, self.publish_opt_tap,
                           wait=None)

        # periodically process new pricing point that keeps trying to apply
        # the new pp till success
        self.core.periodic(self._period_process_pp, self.process_opt_pp,
                           wait=None)

        # subscribing to topic_price_point
        self.vip.pubsub.subscribe('pubsub', self._topic_price_point,
                                  self.on_new_price)

        _log.info('startup() - Done. Agent is ready')
        return

    @Core.receiver('onstop')
    def onstop(self, sender, **kwargs):
        _log.debug('onstop()')

        unregister_with_bridge(self)

        _log.debug('un registering rpc routes')
        self.vip.rpc.call(MASTER_WEB, 'unregister_all_agent_routes').get(
            timeout=10)
        return

    @Core.receiver('onfinish')
    def onfinish(self, sender, **kwargs):
        _log.debug('onfinish()')
        return

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
                return True
            else:
                result = jsonrpc.json_error(rpcdata.id,
                                            jsonrpc.METHOD_NOT_FOUND,
                                            'Invalid method {}'.format(
                                                rpcdata.method))
        except KeyError:
            # print(ke)
            result = jsonrpc.json_error(rpcdata.id, jsonrpc.INVALID_PARAMS,
                                        'Invalid params {}'.format(
                                            rpcdata.params))
        except Exception as e:
            # print(e)
            result = jsonrpc.json_error(rpcdata.id, jsonrpc.UNHANDLED_EXCEPTION,
                                        e)

        if result:
            result = jsonrpc.json_result(rpcdata.id, result)
        return result

    @RPC.export
    def ping(self):
        return True

    def _config_get_init_values(self):
        self._period_read_data = self.config.get('period_read_data', 30)
        self._period_process_pp = self.config.get('period_process_pp', 10)
        self._price_point_latest = self.config.get('price_point_latest', 0.2)
        return

    def _config_get_points(self):
        self._vb_vip_identity = self.config.get('vb_vip_identity',
                                                'iiit.volttronbridge')
        self._root_topic = self.config.get('topic_root', 'zone')
        self._topic_price_point = self.config.get('topic_price_point',
                                                  'zone/pricepoint')
        self._topic_energy_demand = self.config.get('topic_energy_demand',
                                                    'ds/energydemand')
        return

    def _config_get_price_functions(self):
        _log.debug('_config_get_price_functions()')

        self._pf_zn_ac = self.config.get('pf_zn_ac')
        self._pf_zn_light = self.config.get('pf_zn_light')

        self._edf_zn_ac = self.config.get('edf_zn_ac')
        self._edf_zn_light = self.config.get('edf_zn_light')

        return

    def _run_bms_test(self):
        _log.debug('Running: _runBMS Communication Test()...')

        _log.debug('change tsp 26')
        self._rpcset_zone_tsp(26.0)
        time.sleep(1)

        _log.debug('change tsp 27')
        self._rpcset_zone_tsp(27.0)
        time.sleep(1)

        _log.debug('change tsp 28')
        self._rpcset_zone_tsp(28.0)
        time.sleep(1)

        _log.debug('change tsp 29')
        self._rpcset_zone_tsp(29.0)
        time.sleep(1)

        _log.debug('change lsp 25')
        self._rpcset_zone_tsp(25.0)
        time.sleep(1)

        _log.debug('change lsp 75')
        self._rpcset_zone_tsp(75.0)
        time.sleep(1)

        _log.debug('change lsp 100')
        self._rpcset_zone_tsp(100.0)
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

    # change ambient temperature set point
    def _rpcset_zone_tsp(self, tsp):
        # _log.debug('_rpcset_zone_tsp()')

        if isclose(tsp, self._zone_tsp, EPSILON):
            _log.debug('same tsp, do nothing')
            return

        task_id = str(randint(0, 99999999))
        success = get_task_schdl(self, task_id, 'iiit/cbs/zonecontroller')
        if not success:
            return
        try:
            point = 'iiit/cbs/zonecontroller/RM_TSP'
            self.vip.rpc.call('platform.actuator', 'set_point', self._agent_id,
                              point, tsp).get(timeout=10)
            self._update_zone_tsp(tsp)
        except gevent.Timeout:
            _log.exception('gevent.Timeout in _rpcset_zone_tsp()')
        except Exception as e:
            _log.exception(
                'changing ambient tsp'
                + ', Message: {}'.format(e.message)
            )
            # print(e)
        finally:
            # cancel the schedule
            cancel_task_schdl(self, task_id)
        return

    # change ambient light set point
    def _rpcset_zone_lsp(self, lsp):
        # _log.debug('_rpcset_zone_lsp()')

        if isclose(lsp, self._zone_lsp, EPSILON):
            _log.debug('same lsp, do nothing')
            return

        task_id = str(randint(0, 99999999))
        success = get_task_schdl(self, task_id, 'iiit/cbs/zonecontroller')
        if not success:
            return
        try:
            point = 'iiit/cbs/zonecontroller/RM_LSP'
            self.vip.rpc.call('platform.actuator', 'set_point', self._agent_id,
                              point, lsp).get(timeout=10)
            self._update_zone_lsp(lsp)
        except gevent.Timeout:
            _log.exception('gevent.Timeout in _rpcset_zone_lsp()')
        except Exception as e:
            _log.exception(
                'changing ambient lsp'
                + ', Message: {}'.format(e.message)
            )
            # print(e)
        finally:
            # cancel the schedule
            cancel_task_schdl(self, task_id)
        return

    def _update_zone_tsp(self, tsp):
        # _log.debug('_update_zone_tsp()')
        _log.debug('tsp {:0.1f}'.format(tsp))

        rm_tsp = self._rpcget_zone_tsp()

        # check if the tsp really updated at the bms, only then proceed with
        # new tsp
        if isclose(tsp, rm_tsp, EPSILON):
            self._zone_tsp = tsp
            self._publish_zone_tsp(tsp)

        _log.debug('Current TSP: {:0.1f}'.format(rm_tsp))
        return

    def _update_zone_lsp(self, lsp):
        # _log.debug('_update_zone_lsp()')
        _log.debug('lsp {:0.1f}'.format(lsp))

        rm_lsp = self._rpcget_zone_lsp()

        # check if the lsp really updated at the bms, only then proceed with
        # new lsp
        if isclose(lsp, rm_lsp, EPSILON):
            self._zone_lsp = lsp
            self._publish_zone_lsp(lsp)

        _log.debug('Current LSP: {:0.1f}'.format(rm_lsp))
        return

    def _rpcget_zone_lighting_power(self):
        task_id = str(randint(0, 99999999))
        success = get_task_schdl(self, task_id, 'iiit/cbs/zonecontroller')
        if not success:
            return E_UNKNOWN_CLE
        try:
            point = 'iiit/cbs/zonecontroller/RM_LIGHT_CALC_PWR'
            light_energy = self.vip.rpc.call('platform.actuator', 'get_point',
                                             point).get(timeout=10)
            return light_energy
        except gevent.Timeout:
            _log.exception('gevent.Timeout in rpc_getRmCalcLightEnergy()')
        except Exception as e:
            _log.exception(
                'Could not contact actuator. Is it running?'
                + ', Message: {}'.format(e.message)
            )
            # print(e)
        finally:
            # cancel the schedule
            cancel_task_schdl(self, task_id)
            pass
        return E_UNKNOWN_CLE

    def _rpcget_zone_cooling_power(self):
        task_id = str(randint(0, 99999999))
        success = get_task_schdl(self, task_id, 'iiit/cbs/zonecontroller')
        if not success:
            return E_UNKNOWN_CCE
        try:
            point = 'iiit/cbs/zonecontroller/RM_CCE'
            cooling_energy = self.vip.rpc.call('platform.actuator', 'get_point',
                                               point).get(timeout=10)
            return cooling_energy
        except gevent.Timeout:
            _log.exception('gevent.Timeout in _rpcget_zone_cooling_power()')
        except Exception as e:
            _log.exception(
                'Could not contact actuator. Is it running?'
                + ', Message: {}'.format(e.message)
            )
            # print(e)
        finally:
            # cancel the schedule
            cancel_task_schdl(self, task_id)
            pass
        return E_UNKNOWN_CCE

    def _rpcget_zone_tsp(self):
        try:
            point = 'iiit/cbs/zonecontroller/RM_TSP'
            rm_tsp = self.vip.rpc.call('platform.actuator', 'get_point',
                                       point).get(timeout=10)
            return rm_tsp
        except gevent.Timeout:
            _log.exception('gevent.Timeout in _rpcget_zone_tsp()')
        except Exception as e:
            _log.exception(
                'Could not contact actuator. Is it running?'
                + ', Message: {}'.format(e.message)
            )
            # print(e)
        return E_UNKNOWN_TSP

    def _rpcget_zone_lsp(self):
        try:
            point = 'iiit/cbs/zonecontroller/RM_LSP'
            rm_lsp = self.vip.rpc.call('platform.actuator', 'get_point',
                                       point).get(timeout=10)
            return rm_lsp
        except gevent.Timeout:
            _log.exception('gevent.Timeout in _rpcget_zone_lsp()')
        except Exception as e:
            _log.exception(
                'Could not contact actuator. Is it running?'
                + ', Message: {}'.format(e.message)
            )
            # print(e)
        return E_UNKNOWN_LSP

    def _publish_zone_tsp(self, tsp):
        # _log.debug('_publish_zone_tsp()')
        pub_topic = self._root_topic + '/rm_tsp'
        pub_msg = [tsp, {'units': 'celsius', 'tz': 'UTC', 'type': 'float'}]
        _log.info('[LOG] Zone TSP, Msg: {}'.format(pub_msg))
        _log.debug('Publishing to local bus topic: {}'.format(pub_topic))
        publish_to_bus(self, pub_topic, pub_msg)
        _log.debug('done.')
        return

    def _publish_zone_lsp(self, lsp):
        # _log.debug('_publish_zone_lsp()')
        pub_topic = self._root_topic + '/rm_lsp'
        pub_msg = [lsp, {'units': '%', 'tz': 'UTC', 'type': 'float'}]
        _log.info('[LOG] Zone LSP, Msg: {}'.format(pub_msg))
        _log.debug('Publishing to local bus topic: {}'.format(pub_topic))
        publish_to_bus(self, pub_topic, pub_msg)
        _log.debug('done.')
        return

    '''
        Functionality related to the market mechanisms
        
        1. receive new prices (optimal pp or bid pp) from the pca
        2. if opt pp, apply pricing policy by computing the new set point 
        based on price functions
        3. if bid pp, compute the new bid energy demand
        
    '''

    def on_new_price(self, peer, sender, bus, topic, headers, message):
        if sender not in self._valid_senders_list_pp:
            return

        pp_msg_type = False
        bd_msg_type = False
        # check message type before parsing
        if check_msg_type(message, MessageType.price_point):
            pp_msg_type = True
            pass
        elif check_msg_type(message, MessageType.budget):
            bd_msg_type = True
            pass
        else:
            return

        valid_senders_list = self._valid_senders_list_pp
        minimum_fields = ['msg_type', 'value', 'value_data_type', 'units',
                          'price_id']
        validate_fields = ['value', 'units', 'price_id', 'isoptimal',
                           'duration', 'ttl']
        valid_price_ids = []
        (success, pp_msg) = valid_bustopic_msg(sender, valid_senders_list,
                                               minimum_fields, validate_fields,
                                               valid_price_ids, message)
        if not success or pp_msg is None:
            return
        elif (pp_msg.get_one_to_one()
              and pp_msg.get_dst_device_id() != self._device_id):
            return
        elif pp_msg in [self._bid_pp_msg_latest, self._opt_pp_msg_latest]:
            _log.warning(
                'received a duplicate pp_msg'
                + ', price_id: {}!!!'.format(pp_msg.get_price_id())
            )
            return
        else:
            _log.debug('New pp msg on the local-bus, topic: {}'.format(topic))

        if pp_msg_type and pp_msg.get_isoptimal():
            _log.debug('***** New optimal price point from pca:'
                       + ' {:0.2f}'.format(pp_msg.get_value())
                       + ' , price_id: {}'.format(pp_msg.get_price_id()))
            self._process_opt_pp(pp_msg)
        elif pp_msg_type and not pp_msg.get_isoptimal():
            _log.debug('***** New bid price point from pca:'
                       + ' {:0.2f}'.format(pp_msg.get_value())
                       + ' , price_id: {}'.format(pp_msg.get_price_id()))
            self._process_bid_pp(pp_msg)
        elif bd_msg_type:
            _log.debug('***** New budget from pca:'
                       + ' {:0.4f}'.format(pp_msg.get_value())
                       + ' , price_id: {}'.format(pp_msg.get_price_id()))
            self._process_opt_pp(pp_msg)

        return

    def _process_opt_pp(self, pp_msg):
        if pp_msg.get_msg_type() == MessageType.price_point:
            self._opt_pp_msg_latest = copy(pp_msg)
            self._price_point_latest = pp_msg.get_value()
            self._latest_msg_type = MessageType.price_point
        elif pp_msg.get_msg_type() == MessageType.budget:
            self._bud_msg_latest = copy(pp_msg)
            self._latest_msg_type = MessageType.budget

            # any process that failed to apply pp sets this flag False
        self._process_opt_pp_success = False
        # initiate the periodic process
        self.process_opt_pp()
        return

    # this is a periodic function that keeps trying to apply the new pp till
    # success
    def process_opt_pp(self):
        if self._process_opt_pp_success:
            return

        # any process that failed to apply pp sets this flag False
        self._process_opt_pp_success = True

        if self._latest_msg_type == MessageType.budget:
            # compute new_pp for the budget and then apply pricing policy
            new_pp = self._compute_new_opt_pp()
            self._opt_pp_msg_latest = copy(self._bud_msg_latest)
            self._opt_pp_msg_latest.set_msg_type(MessageType.price_point)
            self._opt_pp_msg_latest.set_value(new_pp)
            self._opt_pp_msg_latest.set_isoptimal(True)
            self._price_point_latest = new_pp
            _log.debug(
                '***** New optimal price point:'
                + ' {:0.2f}'.format(self._opt_pp_msg_latest.get_value())
                + ' , price_id: {}'.format(
                    self._opt_pp_msg_latest.get_price_id())
            )

        self._apply_pricing_policy()

        if not self._process_opt_pp_success:
            _log.debug(
                'unable to process_opt_pp()'
                + ', will try again in {} sec'.format(self._period_process_pp)
            )
            return

        _log.info('New Price Point processed.')
        # on successful process of apply_pricing_policy with the latest opt
        # pp, current = latest
        self._opt_pp_msg_current = copy(self._opt_pp_msg_latest)
        return

    def _apply_pricing_policy(self):
        _log.debug('_apply_pricing_policy()')

        # apply for ambient ac
        tsp = self._compute_new_tsp(self._price_point_latest)
        _log.debug('New Ambient AC set point: {:0.1f}'.format(tsp))
        self._rpcset_zone_tsp(tsp)
        if not isclose(tsp, self._zone_tsp, EPSILON):
            self._process_opt_pp_success = False

        # apply for ambient lighting
        lsp = self._compute_new_lsp(self._price_point_latest)
        _log.debug('New Ambient Lighting set point: {:0.1f}'.format(lsp))
        self._rpcset_zone_lsp(lsp)
        if not isclose(lsp, self._zone_lsp, EPSILON):
            self._process_opt_pp_success = False
        return

    # compute new zone temperature set point from price functions
    def _compute_new_tsp(self, pp):
        # type: (float) -> float
        pp = 0 if pp < 0 else 1 if pp > 1 else pp

        idx = self._pf_zn_ac['idx']
        roundup = self._pf_zn_ac['roundup']
        coefficients = self._pf_zn_ac['coefficients']

        a = float(coefficients[idx]['a'])
        b = float(coefficients[idx]['b'])
        c = float(coefficients[idx]['c'])

        tsp = a * pp ** 2 + b * pp + c
        return mround(tsp, roundup)

    # compute new zone lighting setpoint (0-100%) from price functions
    def _compute_new_lsp(self, pp):
        # type: (float) -> float
        pp = 0 if pp < 0 else 1 if pp > 1 else pp

        idx = self._pf_zn_light['idx']
        roundup = self._pf_zn_light['roundup']
        coefficients = self._pf_zn_light['coefficients']

        a = float(coefficients[idx]['a'])
        b = float(coefficients[idx]['b'])
        c = float(coefficients[idx]['c'])

        lsp = a * pp ** 2 + b * pp + c
        return mround(lsp, roundup)

    # compute ed ac from ed functions given tsp
    def _compute_ed_ac(self, bid_tsp):
        # type: (float) -> float
        idx = self._edf_zn_ac['idx']
        roundup = self._edf_zn_ac['roundup']
        coefficients = self._edf_zn_ac['coefficients']

        a = float(coefficients[idx]['a'])
        b = float(coefficients[idx]['b'])
        c = float(coefficients[idx]['c'])

        ed_ac = a * bid_tsp ** 2 + b * bid_tsp + c
        return mround(ed_ac, roundup)

    # compute ed lighting from ed functions given lsp
    def _compute_ed_light(self, bid_lsp):
        idx = self._edf_zn_light['idx']
        roundup = self._edf_zn_light['roundup']
        coefficients = self._edf_zn_light['coefficients']

        a = float(coefficients[idx]['a'])
        b = float(coefficients[idx]['b'])
        c = float(coefficients[idx]['c'])

        ed_light = a * bid_lsp ** 2 + b * bid_lsp + c
        return mround(ed_light, roundup)

    # periodic function to publish active power
    def publish_opt_tap(self):
        pp_msg = self._opt_pp_msg_current
        price_id = pp_msg.get_price_id()
        # compute total active power and publish to local/energydemand
        # (vb RPCs this value to the next level)
        opt_tap = self._calc_total_act_pwr()

        # create a MessageType.active_power ISPACE_Msg
        ap_msg = tap_helper(
            pp_msg,
            self._device_id,
            self._discovery_address,
            opt_tap,
            self._period_read_data,
            EnergyCategory.mixed
        )
        _log.debug('***** Total Active Power(TAP) opt'
                   + ' for us opt pp_msg({})'.format(price_id)
                   + ': {:0.4f}'.format(opt_tap))
        # publish the new price point to the local message bus
        pub_topic = self._topic_energy_demand
        pub_msg = ap_msg.get_json_message(self._agent_id, 'bus_topic')
        _log.info('[LOG] Total Active Power(TAP) opt, Msg: {}'.format(pub_msg))
        _log.debug('Publishing to local bus topic: {}'.format(pub_topic))
        publish_to_bus(self, pub_topic, pub_msg)
        _log.debug('done.')
        return

    # calculate total active power (tap)
    def _calc_total_act_pwr(self):
        # _log.debug('_calc_total_act_pwr()')
        tap = 0
        # zone lighting + ac
        cooling_ap = self._rpcget_zone_cooling_power()
        lighting_ap = self._rpcget_zone_lighting_power()
        ap_ac = (0 if cooling_ap == E_UNKNOWN_CCE else cooling_ap)
        ap_light = (0 if lighting_ap == E_UNKNOWN_CLE else lighting_ap)

        # update running stats
        self._rs['ac'][EnergyCategory.mixed].push(ap_ac)
        self._rs['light'][EnergyCategory.mixed].push(ap_light)

        tap = ap_ac + ap_light

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
        ed_msg = ted_helper(
            pp_msg,
            self._device_id,
            self._discovery_address,
            bid_ted,
            self._period_read_data,
            EnergyCategory.mixed
        )
        _log.debug('***** Total Energy Demand(TED) bid'
                   + ' for us bid pp_msg({})'.format(price_id)
                   + ': {:0.4f}'.format(bid_ted))

        # publish the new price point to the local message bus
        pub_topic = self._topic_energy_demand
        pub_msg = ed_msg.get_json_message(self._agent_id, 'bus_topic')
        _log.info('[LOG] Total Energy Demand(TED) bid, Msg: {}'.format(pub_msg))
        _log.debug('Publishing to local bus topic: {}'.format(pub_topic))
        publish_to_bus(self, pub_topic, pub_msg)
        _log.debug('done.')
        return

    # calculate the local total energy demand for bid_pp
    # the bid energy is for self._bid_pp_duration (default 1hr)
    # and this msg is valid for self._period_read_data (ttl - default 30s)
    def _calc_total_energy_demand(self):
        # _log.debug('_calc_total_energy_demand()')
        pp_msg = self._bid_pp_msg_latest
        bid_pp = pp_msg.get_value()
        duration = pp_msg.get_duration()

        bid_tsp = self._compute_new_tsp(bid_pp)
        ed_ac = calc_energy_wh(self._compute_ed_ac(bid_tsp),
                               duration
                               )

        bid_lsp = self._compute_new_lsp(bid_pp) / 100
        ed_light = calc_energy_wh(self._compute_ed_light(bid_lsp),
                                  duration
                                  )

        ted = ed_ac + ed_light
        return ted

    # compute new opt pp for a given budget using gradient descent
    def _compute_new_opt_pp(self):
        _log.debug('_compute_new_opt_pp()...')

        _log.debug('gd_params: {}'.format(self._gd_params))
        # configuration
        gammas = self._gd_params['gammas']
        gamma_ac = float(gammas['ac'])
        gamma_light = float(gammas['light'])
        deadband = self._gd_params['deadband']
        max_iters = self._gd_params['max_iterations']
        max_repeats = self._gd_params['max_repeats']
        wt_factors = self._gd_params['weight_factors']

        sum_wt_factors = float(wt_factors['ac'] + wt_factors['light'])
        c_ac = (
                float(wt_factors['ac']) / sum_wt_factors
                if sum_wt_factors != 0 else 0
        )
        c_light = (
                float(wt_factors['light']) / sum_wt_factors
                if sum_wt_factors != 0 else 0
        )
        _log.debug(
            'wt_factors[\'ac\']: {:0.2f}'.format(wt_factors['ac'])
            + ', wt_factors[\'light\']: {:0.2f}'.format(wt_factors['light'])
            + ', sum_wt_factors: {:0.2f}'.format(sum_wt_factors)
            + ', c_ac: {:0.4f}'.format(c_ac)
            + ', c_light: {:0.4f}'.format(c_light)
        )

        budget = self._bud_msg_latest.get_value()
        duration = self._bud_msg_latest.get_duration()
        _log.debug(
            '***** New budget: {:0.4f}'.format(budget)
            + ' , price_id: {}'.format(self._bud_msg_latest.get_price_id())
        )

        # Starting point
        i = 0               # iterations count
        j = 0               # repeats count
        new_pp = 0
        new_tsp = 0
        new_lsp = 0
        new_ed = budget
        budget_ac = c_ac * budget
        budget_light = c_light * budget
        new_ed_ac = budget_ac
        new_ed_light = budget_light

        old_pp = self._price_point_latest

        old_ap_ac = self._rs['ac'][EnergyCategory.mixed].exp_wt_mv_avg()
        old_ed_ac = calc_energy_wh(old_ap_ac, duration)

        old_ap_light = self._rs['light'][EnergyCategory.mixed].exp_wt_mv_avg()
        old_ed_light = calc_energy_wh(old_ap_light, duration)

        old_ed = old_ed_ac + old_ed_light

        # Gradient descent iteration
        _log.debug('Gradient descent iteration')
        for i in range(max_iters):

            _log.debug(
                '...iter: {}/{}'.format(i+1, max_iters)
                + ', new pp: {:0.2f}'.format(new_pp)
                + ', new ed: {:0.2f}'.format(new_ed)
                + ', old pp: {:0.2f}'.format(old_pp)
                + ', old ed: {:0.2f}'.format(old_ed)
                + ', old ed ac: {:0.2f}'.format(old_ed_ac)
                + ', old ed light: {:0.2f}'.format(old_ed_light)
            )

            delta_ac = budget_ac - old_ed_ac
            gamma_delta_ac = gamma_ac * delta_ac
            c_gamma_delta_ac = c_ac * gamma_delta_ac

            delta_light = budget_light - old_ed_light
            gamma_delta_light = gamma_light * delta_light
            c_gamma_delta_light = c_light * gamma_delta_light

            new_pp = old_pp - (c_gamma_delta_ac + c_gamma_delta_light)
            _log.debug(
                'delta_ac: {:0.2f}'.format(delta_ac)
                + ', gamma_delta_ac: {:0.2f}'.format(gamma_delta_ac)
                + ', c_gamma_delta_ac: {:0.2f}'.format(c_gamma_delta_ac)
                + ', delta_light: {:0.2f}'.format(delta_light)
                + ', gamma_delta_light: {:0.2f}'.format(gamma_delta_light)
                + ', c_gamma_delta_light: {:0.2f}'.format(c_gamma_delta_light)
            )

            _log.debug('new_pp: {}'.format(new_pp))
            new_pp = round_off_pp(new_pp)
            _log.debug('new_pp: {}'.format(new_pp))

            new_tsp = self._compute_new_tsp(new_pp)
            new_ed_ac = calc_energy_wh(self._compute_ed_ac(new_tsp),
                                       duration
                                       )

            new_lsp = self._compute_new_lsp(new_pp) / 100
            new_ed_light = calc_energy_wh(self._compute_ed_light(new_lsp),
                                          duration
                                          )

            new_ed = new_ed_ac + new_ed_light

            _log.debug(
                '......iter: {}/{}'.format(i, max_iters)
                + ', tmp_pp: {:0.2f}'.format(new_pp)
                + ', tmp_ed: {:0.2f}'.format(new_ed)
            )

            if isclose(budget, new_ed, EPSILON, deadband):
                _log.debug(
                    '|budget({:0.2f})'.format(budget)
                    + ' - tmp_ed({:0.2f})|'.format(new_ed)
                    + ' < deadband({:0.2f})'.format(deadband)
                )
                break

            if isclose(old_ed, new_ed, EPSILON, 1):
                j += 1
                _log.debug(
                    '|prev new_ed({:0.2f})'.format(old_ed)
                    + ' - new_ed({:0.2f})|'.format(new_ed)
                    + ' < deadband({:0.2f})'.format(1)
                    + ' repeat count: {:d}/{:d}'.format(j, max_repeats)
                )
                if j >= max_repeats:
                    break
            else:
                j = 0       # reset repeat count

            old_pp = new_pp
            old_ed = new_ed
            old_ed_ac = new_ed_ac
            old_ed_light = new_ed_light

        _log.debug(
            'final iter count: {}/{}'.format(i, max_iters)
            + ', new pp: {:0.2f}'.format(new_pp)
            + ', expected ted: {:0.2f}'.format(new_ed)
            + ', new tsp: {:0.1f}'.format(new_tsp)
            + ', expected ed_ac: {:0.2f}'.format(new_ed_ac)
            + ', new lsp: {:0.1f}'.format(new_lsp)
            + ', expected ed_light: {:0.2f}'.format(new_ed_light)
        )

        _log.debug('...done')
        return new_pp


def main(argv=sys.argv):
    """Main method called by the eggsecutable."""
    try:
        utils.vip_main(zonecontroller)
    except Exception as e:
        print (e)
        _log.exception('unhandled exception')


if __name__ == '__main__':
    # Entry point for script
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        pass

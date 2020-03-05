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

import logging
import struct
import sys
import time
from copy import copy
from random import randint

import gevent
import gevent.event

from applications.iiit.Utils.ispace_msg import MessageType, EnergyCategory
from applications.iiit.Utils.ispace_msg_utils import check_msg_type, tap_helper, \
    ted_helper, get_default_pp_msg, valid_bustopic_msg
from applications.iiit.Utils.ispace_utils import calc_energy_wh, get_task_schdl, \
    cancel_task_schdl, publish_to_bus, retrive_details_from_vb, \
    register_with_bridge, register_rpc_route, unregister_with_bridge
from volttron.platform import jsonrpc
from volttron.platform.agent import utils
from volttron.platform.agent.known_identities import (
    MASTER_WEB)
from volttron.platform.jsonrpc import (
    METHOD_NOT_FOUND,
    UNHANDLED_EXCEPTION, INVALID_PARAMS)
from volttron.platform.vip.agent import Agent, Core, RPC

utils.setup_logging()
_log = logging.getLogger(__name__)
__version__ = '0.4'

# checking if a floating point value is “numerically zero” by checking if it
# is lower than epsilon
EPSILON = 1e-04

LED_ON = 1
LED_OFF = 0
RELAY_ON = 1
RELAY_OFF = 0
PLUG_ID_1 = 0
PLUG_ID_2 = 1
PLUG_ID_3 = 2
PLUG_ID_4 = 3

DEFAULT_TAG_ID = '7FC000007FC00000'

SCHEDULE_AVLB = 1
SCHEDULE_NOT_AVLB = 0

E_UNKNOWN_DEVICE = -1
E_UNKNOWN_STATE = -2
E_UNKNOWN_LEVEL = -3

# smartstrip base peak energy (200mA * 12V)
SMARTSTRIP_BASE_ENERGY = 2


def smartstrip(config_path, **kwargs):
    config = utils.load_config(config_path)
    vip_identity = config.get('vip_identity', 'iiit.smartstrip')
    # This agent needs to be named iiit.smartstrip. Pop the uuid id off the
    # kwargs
    kwargs.pop('identity', None)

    Agent.__name__ = 'SmartStrip_Agent'
    return SmartStrip(config_path, identity=vip_identity, **kwargs)


class SmartStrip(Agent):
    '''Smart Strip
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

    _volt_state = 0

    _led_debug_state = 0
    _plugs_relay_state = [0, 0, 0, 0]
    _plugs_connected = [0, 0, 0, 0]
    _plugs_voltage = [0.0, 0.0, 0.0, 0.0]
    _plugs_current = [0.0, 0.0, 0.0, 0.0]
    _plugs_active_pwr = [0.0, 0.0, 0.0, 0.0]
    _plugs_tag_id = [DEFAULT_TAG_ID, DEFAULT_TAG_ID, DEFAULT_TAG_ID,
                     DEFAULT_TAG_ID]
    _plugs_th_pp = [0.35, 0.5, 0.75, 0.95]

    def __init__(self, config_path, **kwargs):
        super(SmartStrip, self).__init__(**kwargs)
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
        _log.info('Starting SmartStrip...')

        # retrieve self._device_id, self._ip_addr, self._discovery_address
        # from the bridge
        # retrive_details_from_vb is a blocking call
        retrive_details_from_vb(self, 5)

        # register rpc routes with MASTER_WEB
        # register_rpc_route is a blocking call
        register_rpc_route(self, 'smartstrip', 'rpc_from_net', 5)

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

        self._run_smartstrip_test()

        # get the latest values (states/levels) from h/w
        self._get_initial_hw_state()

        # TODO: apply pricing policy for default values

        # publish initial data from hw to volttron bus
        # self.publish_hw_data()

        # perodically publish hw data to volttron bus. 
        # The data includes plug th_pp, meter data
        self.core.periodic(self._period_read_data, self.publish_hw_data,
                           wait=None)

        # time.sleep(5) #yeild

        # perodically process connected tag ids from h/w
        # self.core.periodic(self._period_read_data,
        # self.process_plugs_tag_id, wait=None)
        # time.sleep(5) #yeild

        # perodically publish total active power to volttron bus
        # active power is comupted at regular interval (_period_read_data
        # default(30s))
        # this power corresponds to current opt pp
        # tap --> total active power (Wh)
        self.core.periodic(self._period_read_data, self.publish_opt_tap,
                           wait=None)

        # time.sleep(2) #yeild
        # perodically process new pricing point that keeps trying to apply
        # the new pp till success
        self.core.periodic(self._period_process_pp, self.process_opt_pp,
                           wait=None)

        # subscribing to topic_price_point
        self.vip.pubsub.subscribe('pubsub', self._topic_price_point,
                                  self.on_new_price)

        self._volt_state = 1

        _log.info('switch on debug led')
        self._switch_led_debug(LED_ON, SCHEDULE_NOT_AVLB)

        _log.info('startup() - Done. Agent is ready')
        return

    @Core.receiver('onstop')
    def onstop(self, sender, **kwargs):
        _log.debug('onstop()')
        unregister_with_bridge(self)

        _log.debug('un registering rpc routes')
        self.vip.rpc.call(MASTER_WEB, 'unregister_all_agent_routes').get(
            timeout=10)

        # switch-off h/w devices
        if self._volt_state != 0:
            self._stop_volt()

        _log.debug('end onstop()')
        return

    @Core.receiver('onfinish')
    def onfinish(self, sender, **kwargs):
        _log.debug('onfinish() -  do nothing!!!')
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
            elif rpcdata.method == 'plug-th-pp' and header[
                'REQUEST_METHOD'].upper() == 'GET':
                if not self._valid_plug_id(rpcdata.params['plug_id']):
                    raise KeyError('invalid plug id')
                args = {'plug_id': rpcdata.params['plug_id']
                        }
                result = self.get_th_pp(**args)
            elif rpcdata.method == 'plug-th-pp' and header[
                'REQUEST_METHOD'].upper() == 'POST':
                if not self._valid_plug_id(rpcdata.params['plug_id']):
                    raise KeyError('invalid plug id')
                args = {'plug_id': rpcdata.params['plug_id'],
                        'new_th_pp': rpcdata.params['new_th_pp']
                        }
                result = self.set_th_pp(**args)
            else:
                return jsonrpc.json_error(rpcdata.id, METHOD_NOT_FOUND,
                                          'Invalid method {}'.format(
                                              rpcdata.method))
        except KeyError as ke:
            # print(ke)
            return jsonrpc.json_error(rpcdata.id, INVALID_PARAMS,
                                      'Invalid params {}'.format(
                                          rpcdata.params))
        except Exception as e:
            # print(e)
            return jsonrpc.json_error(rpcdata.id, UNHANDLED_EXCEPTION, e)
        return (jsonrpc.json_result(rpcdata.id, result) if result else result)

    @RPC.export
    def ping(self):
        return True

    @RPC.export
    def get_th_pp(self, plug_id):
        _log.debug('get_th_pp()')
        return self._plugs_th_pp[plug_id]

    @RPC.export
    def set_th_pp(self, plug_id, new_th_pp):
        _log.debug('set_th_pp()')
        if self._plugs_th_pp[plug_id] != new_th_pp:
            _log.info(('Changing Threshold: Plug ',
                       str(plug_id + 1), ': ', new_th_pp))
            self._plugs_th_pp[plug_id] = new_th_pp
            self._apply_pricing_policy(plug_id, SCHEDULE_NOT_AVLB)
            self._publish_threshold_pp(plug_id, new_th_pp)
        return True

    def _stop_volt(self):
        # _log.debug('_stop_volt()')
        task_id = str(randint(0, 99999999))
        success = get_task_schdl(self, task_id, 'iiit/cbs/smartstrip')
        if success:
            for plug_id, state in enumerate(self._plugs_relay_state):
                if (plug_id == self._sh_plug_id
                        or state == RELAY_OFF
                ): continue
                self._rpcset_plug_relay_state(plug_id, RELAY_OFF)

            self._rpcset_led_debug_state(LED_OFF)
            cancel_task_schdl(self, task_id)
        self._volt_state = 0
        # _log.debug('end _stop_volt()')
        return

    def _config_get_init_values(self):
        self._period_read_data = self.config.get('period_read_data', 30)
        self._period_process_pp = self.config.get('period_process_pp', 10)
        self._price_point_latest = self.config.get('price_point_latest', 0.2)
        self._tag_ids = self.config['tag_ids']
        self._plugs_th_pp = self.config['plug_pricepoint_th']
        self._sh_plug_id = self.config.get('smarthub_plug', 4) - 1
        return

    def _config_get_points(self):
        self._vb_vip_identity = self.config.get('vb_vip_identity',
                                                'iiit.volttronbridge')
        self._root_topic = self.config.get('topic_root', 'smartstrip')
        self._topic_price_point = self.config.get('topic_price_point',
                                                  'smartstrip/pricepoint')
        self._topic_energy_demand = self.config.get('topic_energy_demand',
                                                    'ds/energydemand')
        return

    def _run_smartstrip_test(self):
        _log.debug('Running: _run_smartstrip_test()...')
        _log.debug('switch on debug led')
        self._switch_led_debug(LED_ON, SCHEDULE_NOT_AVLB)
        time.sleep(1)

        _log.debug('switch off debug led')
        self._switch_led_debug(LED_OFF, SCHEDULE_NOT_AVLB)
        time.sleep(1)

        _log.debug('switch on debug led')
        self._switch_led_debug(LED_ON, SCHEDULE_NOT_AVLB)

        self._test_relays()

        _log.debug('switch off debug led')
        self._switch_led_debug(LED_OFF, SCHEDULE_NOT_AVLB)
        _log.debug('EOF Testing')

        return

    def _test_relays(self):
        result = {}
        # get schedule for testing relays
        task_id = str(randint(0, 99999999))
        # _log.debug('task_id: ' + task_id)
        success = get_task_schdl(self, task_id, 'iiit/cbs/smartstrip')
        if not success: return

        # test all four relays
        _log.debug('switch on relay 1')
        self._switch_relay(PLUG_ID_1, RELAY_ON, SCHEDULE_AVLB)
        time.sleep(1)
        _log.debug('switch off relay 1')
        self._switch_relay(PLUG_ID_1, RELAY_OFF, SCHEDULE_AVLB)

        _log.debug('switch on relay 2')
        self._switch_relay(PLUG_ID_2, RELAY_ON, SCHEDULE_AVLB)
        time.sleep(1)
        _log.debug('switch off relay 2')
        self._switch_relay(PLUG_ID_2, RELAY_OFF, SCHEDULE_AVLB)

        _log.debug('switch on relay 3')
        self._switch_relay(PLUG_ID_3, RELAY_ON, SCHEDULE_AVLB)
        time.sleep(1)
        _log.debug('switch off relay 3')
        self._switch_relay(PLUG_ID_3, RELAY_OFF, SCHEDULE_AVLB)

        _log.debug('switch on relay 4')
        self._switch_relay(PLUG_ID_4, RELAY_ON, SCHEDULE_AVLB)
        time.sleep(1)
        _log.debug('switch off relay 4')
        self._switch_relay(PLUG_ID_4, RELAY_OFF, SCHEDULE_AVLB)

        # cancel the schedule
        cancel_task_schdl(self, task_id)
        return

    '''
        Functionality related to the controller
        
        1. control the local actuators
                get/set various set point / levels / speeds
        2. local sensors
                report the sensors data at regular interval
        3. run necessary traditional control algorithm (PID, on/off, etc.,)
        
    '''

    # perodic function to publish h/w data to msg bus
    def publish_hw_data(self):

        self.process_plugs_tag_id()

        # publish plug threshold price point to msg bus
        log_msg = '[LOG] plugs th_pp -'
        for plug_id, th_pp in enumerate(self._plugs_th_pp):
            self._publish_threshold_pp(plug_id, th_pp)
            log_msg += ' Plug {:d}: {:0.2f}'.format(plug_id + 1, th_pp)
        _log.info(log_msg)

        # publish relay states to msg bus
        log_msg = '[LOG] plugs state -'
        for plug_id, state in enumerate(self._plugs_relay_state):
            self._publish_plug_relay_state(plug_id, state)
            s_state = (
                'ON' if state == RELAY_ON else 'OFF' if state == RELAY_OFF
                else 'UK')
            log_msg += ' Plug {:d}: {}'.format(plug_id + 1, s_state)
        _log.info(log_msg)

        # read the meter data from h/w and publish to msg bus
        task_id = str(randint(0, 99999999))
        success = get_task_schdl(self, task_id, 'iiit/cbs/smartstrip', 500)
        if success:
            for plug_id, state in enumerate(self._plugs_relay_state):
                if state != RELAY_ON: continue
                self._rpcget_meter_data(plug_id)
            cancel_task_schdl(self, task_id)
        else:
            _log.warning('no task schdl in publish_hw_data() to read meter data'
                         + ', publishing last known data!!!')

        # publish meter data to msg bus
        for plug_id, state in enumerate(self._plugs_relay_state):
            if state != RELAY_ON: continue
            voltage = self._plugs_voltage[plug_id]
            current = self._plugs_current[plug_id]
            active_pwr = self._plugs_active_pwr[plug_id]
            self._publish_meter_data(plug_id, voltage, current, active_pwr)
            _log.info(('[LOG] Plug {:d}: '.format(plug_id + 1)
                       + ' Voltage: {:.2f}'.format(voltage)
                       + ', Current: {:.2f}'.format(current)
                       + ', ActivePower: {:.2f}'.format(active_pwr)
                       ))

        return

    def process_plugs_tag_id(self):
        # _log.debug('get_plug_data()...')

        # get schedule for to h/w latest data
        task_id = str(randint(0, 99999999))
        success = get_task_schdl(self, task_id, 'iiit/cbs/smartstrip', 500)
        if not success:
            _log.warning(
                'no task schdl in process_plugs_tag_id() to read tag ids')
            time.sleep(1)  # yeild a sec
            return

        log_msg = '[LOG] tag_ids -'
        for plug_id, plug_tag_id in enumerate(self._plugs_tag_id):
            plug_tag_id = self._rpcget_plug_tag_id(plug_id)
            self._process_new_tag_id(plug_id, plug_tag_id)
            log_msg += ' Plug_{}: {}'.format(plug_id + 1, plug_tag_id)
        # _log.debug('...done _process_new_tag_id()')

        # cancel the schedule
        cancel_task_schdl(self, task_id)

        _log.info(log_msg)
        return

    def _get_initial_hw_state(self):
        # _log.debug('_get_initial_hw_state()')
        task_id = str(randint(0, 99999999))
        success = get_task_schdl(self, task_id, 'iiit/cbs/smartstrip')
        if not success:
            _log.warning('no task schdl for getting initial h/w state')
            return

        for plug_id, state in enumerate(self._plugs_relay_state):
            self._plugs_relay_state[plug_id] = self._get_plug_relay_state(
                plug_id, SCHEDULE_AVLB)

        cancel_task_schdl(self, task_id)
        return

    def _get_plug_relay_state(self, plug_id, schd_exist):
        if not self._valid_plug_id(plug_id): return E_UNKNOWN_STATE

        state = E_UNKNOWN_STATE
        if schd_exist == SCHEDULE_AVLB:
            state = self._rpcget_plug_relay_state(plug_id);
        elif schd_exist == SCHEDULE_NOT_AVLB:
            task_id = str(randint(0, 99999999))
            success = get_task_schdl(self, task_id, 'iiit/cbs/smartstrip')
            if not success:
                _log.warning('no task schdl for getting plug relay state')
                return E_UNKNOWN_STATE
            state = self._rpcget_plug_relay_state(plug_id);
            cancel_task_schdl(self, task_id)
        else:
            _log.warning(
                'Error: not a valid param - schd_exist: {}'.format(schd_exist))
            return E_UNKNOWN_STATE
        return state

    def _process_new_tag_id(self, plug_id, new_tag_id):
        # empty string
        if not new_tag_id:
            # do nothing
            return

        if new_tag_id != '7FC000007FC00000':
            # device is connected condition
            # check if current tag id is same as new, if so, do nothing
            if new_tag_id == self._plugs_tag_id[plug_id]:
                return
            else:
                # update the tag id and change connected state
                self._plugs_tag_id[plug_id] = new_tag_id
                self._publish_tag_id(plug_id, new_tag_id)
                self._plugs_connected[plug_id] = 1
                if self._authorised_tag_id(new_tag_id):
                    plug_pp_th = self._plugs_th_pp[plug_id]
                    if self._price_point_latest < plug_pp_th:
                        _log.info(('Plug {:d}: '.format(plug_id + 1),
                                   'Current price point < '
                                   'threshold {:.2f}, '.format(plug_pp_th),
                                   'Switching-on power'))
                        self._switch_relay(plug_id, RELAY_ON, SCHEDULE_AVLB)
                    else:
                        _log.info(('Plug {:d}: '.format(plug_id + 1),
                                   'Current price point > threshold',
                                   '({:.2f}), '.format(plug_pp_th),
                                   'No-power'))
                        self._switch_relay(plug_id, RELAY_OFF, SCHEDULE_AVLB)
                else:
                    _log.info(('Plug {:d}: '.format(plug_id + 1),
                               'Unauthorised device connected',
                               '(tag id: ',
                               new_tag_id, ')'))
                    self._publish_tag_id(plug_id, new_tag_id)
                    self._switch_relay(plug_id, RELAY_OFF, SCHEDULE_AVLB)

        else:
            # no device connected condition, new tag id is DEFAULT_TAG_ID
            if self._plugs_connected[plug_id] == 0:
                return
            elif (self._plugs_connected[plug_id] == 1
                  or new_tag_id != self._plugs_tag_id[plug_id]
                  or self._plugs_relay_state[plug_id] == RELAY_ON):
                # update the tag id and change connected state
                self._plugs_tag_id[plug_id] = new_tag_id
                self._publish_tag_id(plug_id, new_tag_id)
                self._plugs_connected[plug_id] = 0
                self._switch_relay(plug_id, RELAY_OFF, SCHEDULE_AVLB)
        return

    def _construct_tag_id(self, f1_tag_id, f2_tag_id):
        buff = self._convert_to_byte_array(f1_tag_id, f2_tag_id)
        tag = ''
        for i in reversed(buff):
            tag = tag + format(i, '02x')
        return tag.upper()

    def _convert_to_byte_array(self, f1_tag_id, f2_tag_id):
        id_lsb = bytearray(struct.pack('f', f1_tag_id))
        # for id in id_lsb:
        #    print 'id: {:02x}'.format(id)
        id_msb = bytearray(struct.pack('f', f2_tag_id))

        id_msb = bytearray(struct.pack('f', f2_tag_id))
        return (id_msb + id_lsb)

    def _switch_led_debug(self, state, schdExist):
        # _log.debug('_switch_led_debug()')

        if self._led_debug_state == state:
            _log.info('same state, do nothing')
            return

        if schdExist == SCHEDULE_AVLB:
            self._rpcset_led_debug_state(state)
            self._update_led_debug_state(state)
        elif schdExist == SCHEDULE_NOT_AVLB:
            # get schedule to _switch_led_debug
            task_id = str(randint(0, 99999999))
            success = get_task_schdl(self, task_id, 'iiit/cbs/smartstrip')
            if not success:
                _log.warning('no task schdl for setting led debugb state')
                return
            self._rpcset_led_debug_state(state)
            self._update_led_debug_state(state)
            cancel_task_schdl(self, task_id)
        else:
            # do nothing
            _log.warning(
                '_switch_led_debug(), not a valid param schdExist: {}'.format(
                    schdExist))
        return

    def _switch_relay(self, plug_id, state, schdExist):
        # _log.debug('switchPlug1Relay()')

        if self._plugs_relay_state[plug_id] == state:
            _log.debug('same state, do nothing')
            return

        if schdExist == SCHEDULE_AVLB:
            self._rpcset_plug_relay_state(plug_id, state);
            self._update_plug_relay_state(plug_id, state)
        elif schdExist == SCHEDULE_NOT_AVLB:
            # get schedule to _switch_relay
            task_id = str(randint(0, 99999999))
            # _log.debug('task_id: ' + task_id)
            success = get_task_schdl(self, task_id, 'iiit/cbs/smartstrip')
            if not success:
                _log.warning('no task schdl for setting relay state')
                return
            self._rpcset_plug_relay_state(plug_id, state)
            self._update_plug_relay_state(plug_id, state)
            cancel_task_schdl(self, task_id)
        else:
            # do notthing
            _log.warning(
                '_switch_relay(), not a valid param schdExist: {}'.format(
                    schdExist))
        return

    def _rpcset_led_debug_state(self, state):
        end_point = 'LEDDebug'
        try:
            # _log.debug('schl avlb')
            result = self.vip.rpc.call('platform.actuator'
                                       , 'set_point'
                                       , self._agent_id
                                       , 'iiit/cbs/smartstrip/' + end_point
                                       , state
                                       ).get(timeout=10)

            # self._update_led_debug_state(state)
        except gevent.Timeout:
            _log.exception('gevent.Timeout in _rpcset_led_debug_state()')
            pass
        except Exception as e:
            _log.exception(
                'in _rpcset_led_debug_state(), message: unhandled exception'
                + ' {}!!!'.format(e.message))
            pass
        return

    def _rpcset_plug_relay_state(self, plug_id, state):
        if not self._valid_plug_id(plug_id): return

        end_point = 'Plug' + str(plug_id + 1) + 'Relay'
        try:
            result = self.vip.rpc.call('platform.actuator'
                                       , 'set_point'
                                       , self._agent_id
                                       , 'iiit/cbs/smartstrip/' + end_point
                                       , state
                                       ).get(timeout=10)
        except gevent.Timeout:
            _log.exception('gevent.Timeout in _rpcset_plug_relay_state()')
            # return E_UNKNOWN_STATE
            pass
        except Exception as e:
            _log.exception(
                'in _rpcset_plug_relay_state(), message: unhandled exception'
                + ' {}!!!'.format(e.message))
            pass
        # _log.debug('OK call updatePlug1RelayState()')
        # self._update_plug_relay_state(plug_id, state)
        return

    def _rpcget_led_debug_state(self):
        end_point = 'LEDDebug'
        relay_state = E_UNKNOWN_STATE
        try:
            state = self.vip.rpc.call('platform.actuator'
                                      , 'get_point'
                                      , 'iiit/cbs/smartstrip/' + end_point
                                      ).get(timeout=10)
            relay_state = int(state)
        except gevent.Timeout:
            _log.exception('gevent.Timeout in _rpcget_plug_relay_state()')
            pass
        except Exception as e:
            _log.exception(
                'in _rpcget_plug_relay_state(), message: unhandled exception'
                + ' {}!!!'.format(e.message))
            pass
        return relay_state

    def _rpcget_plug_relay_state(self, plug_id):
        if not self._valid_plug_id(plug_id): return E_UNKNOWN_STATE

        end_point = 'Plug' + str(plug_id + 1) + 'Relay'
        relay_state = E_UNKNOWN_STATE
        try:
            state = self.vip.rpc.call('platform.actuator'
                                      , 'get_point'
                                      , 'iiit/cbs/smartstrip/' + end_point
                                      ).get(timeout=10)
            relay_state = int(state)
        except gevent.Timeout:
            _log.exception('gevent.Timeout in _rpcget_plug_relay_state()')
            pass
        except Exception as e:
            _log.exception(
                'in _rpcget_plug_relay_state(), message: unhandled exception'
                + ' {}!!!'.format(e.message))
            pass
        return relay_state

    def _rpcget_meter_data(self, plug_id):
        # _log.debug ('_rpcget_meter_data(), plug_id: ' + str(plug_id))
        if not self._valid_plug_id(plug_id): return

        point_voltage = 'Plug' + str(plug_id + 1) + 'Voltage'
        point_current = 'Plug' + str(plug_id + 1) + 'Current'
        point_active_power = 'Plug' + str(plug_id + 1) + 'ActivePower'

        try:
            f_voltage = self.vip.rpc.call('platform.actuator'
                                          , 'get_point'
                                          ,
                                          'iiit/cbs/smartstrip/' + point_voltage
                                          ).get(timeout=10)
            # _log.debug('voltage: {:.2f}'.format(f_voltage))
            f_current = self.vip.rpc.call('platform.actuator'
                                          , 'get_point'
                                          ,
                                          'iiit/cbs/smartstrip/' + point_current
                                          ).get(timeout=10)
            # _log.debug('current: {:.2f}'.format(f_current))
            f_active_power = self.vip.rpc.call('platform.actuator'
                                               , 'get_point'
                                               ,
                                               'iiit/cbs/smartstrip/' +
                                               point_active_power
                                               ).get(timeout=10)
            # _log.debug('active: {:.2f}'.format(f_active_power))

            # keep track of plug meter data
            self._plugs_voltage[plug_id] = f_voltage
            self._plugs_current[plug_id] = f_current
            self._plugs_active_pwr[plug_id] = f_active_power

        except gevent.Timeout:
            _log.exception('gevent.Timeout in _rpcget_meter_data()')
            pass
        except Exception as e:
            _log.exception(
                'Exception: reading meter data, message: {}'.format(e.message))
            pass
        return

    def _rpcget_plug_tag_id(self, plug_id):
        '''
            Smart Strip bacnet server splits the 64 bit tag id 
            into two parts and sends them accros as two float values.
            Hence need to get both the points (floats value)
            and recover the actual tag id
        '''
        tag_id = DEFAULT_TAG_ID
        end_point_1 = 'TagID' + str(plug_id + 1) + '_1'
        end_point_2 = 'TagID' + str(plug_id + 1) + '_2'
        try:
            f1_tag_id = self.vip.rpc.call('platform.actuator'
                                          , 'get_point'
                                          , 'iiit/cbs/smartstrip/' + end_point_1
                                          ).get(timeout=10)
            f2_tag_id = self.vip.rpc.call('platform.actuator'
                                          , 'get_point'
                                          , 'iiit/cbs/smartstrip/' + end_point_2
                                          ).get(timeout=10)
            tag_id = self._construct_tag_id(f1_tag_id, f2_tag_id)
        except gevent.Timeout:
            _log.exception('gevent.Timeout in _rpcget_tag_ids()')
            pass
        except Exception as e:
            _log.exception(
                'Exception: reading tag ids, message: {}'.format(e.message))
            pass
        return tag_id

    def _update_led_debug_state(self, state):
        # _log.debug('_update_led_debug_state()')

        led_debug_state = self._rpcget_led_debug_state()
        if state == led_debug_state: self._led_debug_state = state

        if state == LED_ON:
            _log.info('Current State: LED Debug is ON!!!')
        elif state == LED_OFF:
            _log.info('Current State: LED Debug is OFF!!!')
        else:
            _log.info('Current State: LED Debug STATE UNKNOWN!!!')
        return

    def _update_plug_relay_state(self, plug_id, state):
        # _log.debug('updatePlug1RelayState()')
        relay_state = self._rpcget_plug_relay_state(plug_id)

        if state == relay_state:
            self._plugs_relay_state[plug_id] = state
            self._publish_plug_relay_state(plug_id, state)

        if state == RELAY_ON:
            _log.info('Current State: Plug ' + str(
                plug_id + 1) + ' Relay Switched ON!!!')
        elif state == RELAY_OFF:
            _log.info('Current State: Plug ' + str(
                plug_id + 1) + ' Relay Switched OFF!!!')
        else:
            _log.info('Current State: Plug ' + str(
                plug_id + 1) + ' Relay STATE UNKNOWN!!!')
        return

    def _publish_meter_data(self, plug_id, fVolatge, fCurrent, fActivePower):
        if not self._valid_plug_id(plug_id): return

        pub_topic = self._root_topic + '/plug' + str(
            plug_id + 1) + '/meterdata/all'
        pub_msg = [{'voltage': fVolatge, 'current': fCurrent,
                    'active_power': fActivePower},
                   {'voltage': {'units': 'V', 'tz': 'UTC', 'type': 'float'},
                    'current': {'units': 'A', 'tz': 'UTC', 'type': 'float'},
                    'active_power': {'units': 'W', 'tz': 'UTC', 'type': 'float'}
                    }]
        # _log.info('[LOG] SS plug meter data, Msg: {}'.format(pub_msg))
        # _log.debug('Publishing to local bus topic: {}'.format(pub_topic))
        publish_to_bus(self, pub_topic, pub_msg)
        # _log.debug('done.')
        return

    def _publish_tag_id(self, plug_id, new_tag_id):
        if not self._valid_plug_id(plug_id): return

        pub_topic = self._root_topic + '/plug' + str(plug_id + 1) + '/tagid'
        pub_msg = [new_tag_id, {'units': '', 'tz': 'UTC', 'type': 'string'}]
        # _log.info('[LOG] SS plug tag id, Msg: {}'.format(pub_msg))
        # _log.debug('Publishing to local bus topic: {}'.format(pub_topic))
        publish_to_bus(self, pub_topic, pub_msg)
        # _log.debug('done.')
        return

    def _publish_plug_relay_state(self, plug_id, state):
        if not self._valid_plug_id(plug_id): return

        pub_topic = self._root_topic + '/plug' + str(
            plug_id + 1) + '/relaystate'
        pub_msg = [state, {'units': 'On/Off', 'tz': 'UTC', 'type': 'int'}]
        # _log.info('[LOG] SS plug relay state, Msg: {}'.format(pub_msg))
        # _log.debug('Publishing to local bus topic: {}'.format(pub_topic))
        publish_to_bus(self, pub_topic, pub_msg)
        # _log.debug('done.')
        return

    def _publish_threshold_pp(self, plug_id, thresholdPP):
        if not self._valid_plug_id(plug_id): return

        pub_topic = self._root_topic + '/plug' + str(plug_id + 1) + '/threshold'
        pub_msg = [thresholdPP,
                   {'units': 'cents', 'tz': 'UTC', 'type': 'float'}]
        # _log.info('[LOG] SS plug threshold price, Msg: {}'.format(pub_msg))
        # _log.debug('Publishing to local bus topic: {}'.format(pub_topic))
        publish_to_bus(self, pub_topic, pub_msg)
        # _log.debug('done.')
        return

    def _authorised_tag_id(self, tag_id):
        return (True if tag_id in self._tag_ids else False)

    def _valid_plug_id(self, plug_id):
        return (True if plug_id < len(self._plugs_th_pp) else False)

    '''
        Functionality related to the market mechanisms
        
        1. receive new prices (optimal pp or bid pp) from the pca
        2. if opt pp, apply pricing policy by computing the new setpoint 
        based on price functions
        3. if bid pp, compute the new bid energy demand
        
    '''

    def on_new_price(self, peer, sender, bus, topic, headers, message):
        if sender not in self._valid_senders_list_pp: return

        # check message type before parsing
        if not check_msg_type(message, MessageType.price_point): return False

        valid_senders_list = self._valid_senders_list_pp
        minimum_fields = ['msg_type', 'value', 'value_data_type', 'units',
                          'price_id']
        validate_fields = ['value', 'units', 'price_id', 'isoptimal',
                           'duration', 'ttl']
        valid_price_ids = []
        (success, pp_msg) = valid_bustopic_msg(sender, valid_senders_list
                                               , minimum_fields
                                               , validate_fields
                                               , valid_price_ids
                                               , message)
        if not success or pp_msg is None:
            return
        else:
            _log.debug('New pp msg on the local-bus, topic: {}'.format(topic))

        if pp_msg.get_isoptimal():
            _log.debug('***** New optimal price point from pca: {:0.2f}'.format(
                pp_msg.get_value())
                       + ' , price_id: {}'.format(pp_msg.get_price_id()))
            self._process_opt_pp(pp_msg)
        else:
            _log.debug('***** New bid price point from pca: {:0.2f}'.format(
                pp_msg.get_value())
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

    # this is a perodic function that keeps trying to apply the new pp till
    # success
    def process_opt_pp(self):
        if self._process_opt_pp_success: return

        # any process that failed to apply pp sets this flag False
        self._process_opt_pp_success = True

        task_id = str(randint(0, 99999999))
        success = get_task_schdl(self, task_id, 'iiit/cbs/smartstrip', 1000)
        if not success:
            _log.debug('unable to process_opt_pp()'
                       + ', will try again in {} sec'.format(
                self._period_process_pp))
            self._process_opt_pp_success = False
            return

        for plug_id, th_pp in enumerate(self._plugs_th_pp):
            self._apply_pricing_policy(plug_id, SCHEDULE_AVLB)
            if not self._process_opt_pp_success:
                cancel_task_schdl(self, task_id)
                _log.debug('unable to process_opt_pp()'
                           + ', will try again in {} sec'.format(
                    self._period_process_pp))
                return

        cancel_task_schdl(self, task_id)

        # _log.info('New Price Point processed.')
        pp_msg = self._opt_pp_msg_latest
        _log.debug('***** New opt price point from pca: {:0.2f}'.format(
            pp_msg.get_value())
                   + ' , price_id: {}'.format(pp_msg.get_price_id())
                   + ' - processed!!!')
        # on successful process of apply_pricing_policy with the latest opt
        # pp, current = latest
        self._opt_pp_msg_current = copy(self._opt_pp_msg_latest)
        return

    def _apply_pricing_policy(self, plug_id, schdExist):
        plug_pp_th = self._plugs_th_pp[plug_id]
        if self._price_point_latest > plug_pp_th:
            if self._plugs_relay_state[plug_id] == RELAY_ON:
                _log.info(('Plug {:d}: '.format(plug_id + 1)
                           , 'Current price point > threshold'
                           , '({:.2f}), '.format(plug_pp_th)
                           , 'Switching-Off Power'
                           ))
                self._switch_relay(plug_id, RELAY_OFF, schdExist)
                if self._plugs_relay_state[plug_id] != RELAY_OFF:
                    self._process_opt_pp_success = False

            # else:
            # do nothing
        else:
            if self._plugs_connected[plug_id] == 1 and self._authorised_tag_id(
                    self._plugs_tag_id[plug_id]):
                _log.info(('Plug {:d}: '.format(plug_id + 1)
                           , 'Current price point < threshold'
                           , '({:.2f}), '.format(plug_pp_th)
                           , 'Switching-On Power'
                           ))
                self._switch_relay(plug_id, RELAY_ON, schdExist)
                if self._plugs_relay_state[plug_id] != RELAY_ON:
                    self._process_opt_pp_success = False
            # else:
            # do nothing
        return

    # perodic function to publish active power
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
            EnergyCategory.plug_load
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
        # active pwr is measured in realtime from the connected plug

        # ss base energy demand
        tap = SMARTSTRIP_BASE_ENERGY

        # connected plugs active power
        for plug_id, state in enumerate(self._plugs_relay_state):
            if (state == RELAY_ON
                    and plug_id != self._sh_plug_id
            ):
                tap += self._plugs_active_pwr[plug_id]

        return tap

    def _process_bid_pp(self, pp_msg):
        self._bid_pp_msg_latest = copy(pp_msg)
        self.process_bid_pp()
        return

    # this is a perodic function that keeps trying to apply the new pp till
    # success
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
            EnergyCategory.plug_load
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

    # calculate the local energy demand for bid_pp
    # the bid energy is for self._bid_pp_duration (default 1hr)
    # and this msg is valid for self._period_read_data (ttl - default 30s)
    def _calc_total_energy_demand(self):
        # TODO: ted should be computed based on some  predictive modeling
        pp_msg = self._bid_pp_msg_latest
        bid_pp = pp_msg.get_value()
        duration = pp_msg.get_duration()

        # sh base energy demand
        ted = calc_energy_wh(SMARTSTRIP_BASE_ENERGY, duration)

        # connected plugs active power
        for plug_id, th_pp in enumerate(self._plugs_th_pp):
            if (bid_pp > th_pp
                    or plug_id == self._sh_plug_id
            ):
                pass
            else:
                ted += calc_energy_wh(self._plugs_active_pwr[plug_id], duration)

        return ted


def main(argv=sys.argv):
    '''Main method called by the eggsecutable.'''
    try:
        utils.vip_main(smartstrip)
    except Exception as e:
        print (e)
        _log.exception('unhandled exception')


if __name__ == '__main__':
    # Entry point for script
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        pass

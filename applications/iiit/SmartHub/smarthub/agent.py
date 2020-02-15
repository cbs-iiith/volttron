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

from random import random, randint
from copy import copy

import settings

import time
import struct
import gevent
import gevent.event

from ispace_utils import isclose, get_task_schdl, cancel_task_schdl, publish_to_bus, mround
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

SH_DEVICE_STATE_ON = 1
SH_DEVICE_STATE_OFF = 0

SH_DEVICE_LED_DEBUG = 0
SH_DEVICE_LED = 1
SH_DEVICE_FAN = 2
SH_DEVICE_FAN_SWING = 3
SH_DEVICE_S_LUX = 4
SH_DEVICE_S_RH = 5
SH_DEVICE_S_TEMP = 6
SH_DEVICE_S_CO2 = 7
SH_DEVICE_S_PIR = 8

SCHEDULE_AVLB = 1
SCHEDULE_NOT_AVLB = 0

E_UNKNOWN_DEVICE = -1
E_UNKNOWN_STATE = -2
E_UNKNOWN_LEVEL = -3

# action types
AT_GET_STATE = 321
AT_GET_LEVEL = 322
AT_SET_STATE = 323
AT_SET_LEVEL = 324
AT_PUB_LEVEL = 325
AT_PUB_STATE = 326
AT_GET_THPP = 327
AT_SET_THPP = 328
AT_PUB_THPP = 329

# these provide the average active power (W) of the devices, observed based on experiments data
# for bid - calculate total energy (Wh or kWh)
# for opt - calculate total active power (W)
SH_BASE_POWER = 10
SH_FAN_POWER = 8
SH_LED_POWER = 10

SH_FAN_THRESHOLD_PCT = 0.30
SH_LED_THRESHOLD_PCT = 0.30


def smarthub(config_path, **kwargs):
    config = utils.load_config(config_path)
    vip_identity = config.get('vip_identity', 'iiit.smarthub')
    # This agent needs to be named iiit.smarthub. Pop the uuid id off the kwargs
    kwargs.pop('identity', None)
    
    Agent.__name__ = 'SmartHub_Agent'
    return SmartHub(config_path, identity=vip_identity, **kwargs)
    
    
class SmartHub(Agent):
    '''Smart Hub
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
    
    _sh_devices_state = [0, 0, 0, 0, 0, 0, 0, 0, 0]
    _sh_devices_level = [0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3]
    _sh_devices_th_pp = [ 0.95, 0.95, 0.95, 0.95, 0.95, 0.95, 0.95, 0.95, 0.95]
    
    _pf_sh_fan = None
    
    def __init__(self, config_path, **kwargs):
        super(SmartHub, self).__init__(**kwargs)
        _log.debug('vip_identity: ' + self.core.identity)
        
        self.config = utils.load_config(config_path)
        self._config_get_points()
        self._config_get_init_values()
        self._config_get_price_fucntions()
        return
        
    @Core.receiver('onsetup')
    def setup(self, sender, **kwargs):
        _log.info(self.config['message'])
        self._agent_id = self.config['agentid']
        return
        
    @Core.receiver('onstart')            
    def startup(self, sender, **kwargs):
        _log.info('Starting SmartHub...')
        
        # retrive self._device_id, self._ip_addr, self._discovery_address from the bridge
        # retrive_details_from_vb is a blocking call
        retrive_details_from_vb(self, 5)
        
        # register rpc routes with MASTER_WEB
        # register_rpc_route is a blocking call
        register_rpc_route(self, 'smarthub', 'rpc_from_net', 5)
        
        # register this agent with vb as local device for posting active power & bid energy demand
        # pca picks up the active power & energy demand bids only if registered with vb
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
        
        self._run_smarthub_test()
        
        # get the latest values (states/levels) from h/w
        self._get_initial_hw_state()
        
        # publish initial data from hw to volttron bus
        self.publish_hw_data()
        
        # perodically publish hw data to volttron bus. 
        # The data includes fan, light & various sensors(state/level/readings) 
        self.core.periodic(self._period_read_data, self.publish_hw_data, wait=None)
        
        # perodically publish total active power to volttron bus
        # active power is comupted at regular interval (_period_read_data default(30s))
        # this power corresponds to current opt pp
        # tap --> total active power (Wh)
        self.core.periodic(self._period_read_data, self.publish_opt_tap, wait=None)
        
        # perodically process new pricing point that keeps trying to apply the new pp till success
        self.core.periodic(self._period_process_pp, self.process_opt_pp, wait=None)
        
        # subscribing to topic_price_point
        self.vip.pubsub.subscribe('pubsub', self._topic_price_point, self.on_new_price)
        
        self._volt_state = 1
        
        _log.info('switch on debug led')
        self._set_sh_device_state(SH_DEVICE_LED_DEBUG, SH_DEVICE_STATE_ON, SCHEDULE_NOT_AVLB)
        
        _log.info('startup() - Done. Agent is ready')
        return
        
    @Core.receiver('onstop')
    def onstop(self, sender, **kwargs):
        _log.debug('onstop()')
        
        unregister_with_bridge(self)
        
        _log.debug('un registering rpc routes')
        self.vip.rpc.call(MASTER_WEB, 'unregister_all_agent_routes').get(timeout=30)
        
        if self._volt_state != 0:
            self._stop_volt()
        return
        
    @Core.receiver('onfinish')
    def onfinish(self, sender, **kwargs):
        _log.debug('onfinish()')
        if self._volt_state != 0:
            self._stop_volt()
        return 
        
    @RPC.export
    def rpc_from_net(self, header, message):
        result = False
        try:
            rpcdata = jsonrpc.JsonRpcData.parse(message)
            _log.debug('rpc_from_net()...'
                        #+ 'header: {}'.format(header)
                        + ', rpc method: {}'.format(rpcdata.method)
                        #+ ', rpc params: {}'.format(rpcdata.params)
                        )
            if rpcdata.method == 'ping':
                result = True
            # TODO: rename methods and params in sync with BLESmartHubSrv/main.js
            elif rpcdata.method == 'state' and header['REQUEST_METHOD'].upper() == 'POST':
                args = {'lhw_device_id': rpcdata.params['id'],
                        'state': rpcdata.params['value'],
                        'schd_exist': SCHEDULE_NOT_AVLB
                        }
                result = self._set_sh_device_state(**args)
            elif rpcdata.method == 'level' and header['REQUEST_METHOD'].upper() == 'POST':
                args = {'lhw_device_id': rpcdata.params['id'],
                        'level': rpcdata.params['value'],
                        'schd_exist': SCHEDULE_NOT_AVLB
                        }
                result = self._set_sh_device_level(**args)
            elif (rpcdata.method == 'threshold-price'
                                        and header['REQUEST_METHOD'].upper() == 'POST'):
                args = {'lhw_device_id': rpcdata.params['id'],
                        'thPP': rpcdata.params['value']
                        }
                result = self._set_sh_device_th_pp(**args)
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
        
    @RPC.export
    def ping(self):
        return True
        
    def _stop_volt(self):
        #_log.debug('_stop_volt()')
        task_id = str(randint(0, 99999999))
        success = get_task_schdl(self, task_id,'iiit/cbs/smarthub')
        if success:
            self._rpcset_sh_device_state(SH_DEVICE_LED_DEBUG, SH_DEVICE_STATE_OFF)
            self._rpcset_sh_device_state(SH_DEVICE_LED, SH_DEVICE_STATE_OFF)
            self._rpcset_sh_device_state(SH_DEVICE_FAN, SH_DEVICE_STATE_OFF)
            # cancel the schedule
            cancel_task_schdl(self, task_id)
        self._volt_state = 0
        return
        
    def _config_get_init_values(self):
        self._period_read_data = self.config.get('period_read_data', 30)
        self._period_process_pp = self.config.get('period_process_pp', 10)
        self._price_point_latest = self.config.get('price_point_latest', 0.2)
        return
        
    def _config_get_points(self):
        self._vb_vip_identity = self.config.get('vb_vip_identity', 'iiit.volttronbridge')
        self._root_topic = self.config.get('topic_root', 'smarthub')
        self._topic_price_point = self.config.get('topic_price_point', 'smarthub/pricepoint')
        self._topic_energy_demand = self.config.get('topic_energy_demand', 'ds/energydemand')
        return
        
    def _config_get_price_fucntions(self):
        _log.debug('_config_get_price_fucntions()')
        self._pf_sh_fan = self.config.get('pf_sh_fan')
        return
        
    def _run_smarthub_test(self):
        _log.debug('Running: _run_smarthub_test()...')
        
        self._test_led_debug()
        self._test_led()
        self._test_fan()
        # self._test_sensors()
        self._test_sensors_2()
        _log.debug('EOF Testing')
        return
        
    def _test_led_debug(self):
        _log.debug('switch on debug led')
        
        self._set_sh_device_state(SH_DEVICE_LED_DEBUG, SH_DEVICE_STATE_ON, SCHEDULE_NOT_AVLB)
        time.sleep(1)
        
        _log.debug('switch off debug led')
        self._set_sh_device_state(SH_DEVICE_LED_DEBUG, SH_DEVICE_STATE_OFF, SCHEDULE_NOT_AVLB)
        time.sleep(1)
        
        _log.debug('switch on debug led')
        self._set_sh_device_state(SH_DEVICE_LED_DEBUG, SH_DEVICE_STATE_ON, SCHEDULE_NOT_AVLB)
        time.sleep(1)
        
        _log.debug('switch off debug led')
        self._set_sh_device_state(SH_DEVICE_LED_DEBUG, SH_DEVICE_STATE_OFF, SCHEDULE_NOT_AVLB)
        time.sleep(1)
        
        _log.debug('switch on debug led')
        self._set_sh_device_state(SH_DEVICE_LED_DEBUG, SH_DEVICE_STATE_ON, SCHEDULE_NOT_AVLB)
        time.sleep(1)
        
        _log.debug('switch off debug led')
        self._set_sh_device_state(SH_DEVICE_LED_DEBUG, SH_DEVICE_STATE_OFF, SCHEDULE_NOT_AVLB)
        return
        
    def _test_led(self):
        _log.debug('switch on led')
        self._set_sh_device_state(SH_DEVICE_LED, SH_DEVICE_STATE_ON, SCHEDULE_NOT_AVLB)
        time.sleep(1)
        
        _log.debug('change led level 0.3')
        self._set_sh_device_level(SH_DEVICE_LED, 0.3, SCHEDULE_NOT_AVLB)
        time.sleep(1)
        
        _log.debug('change led level 0.6')
        self._set_sh_device_level(SH_DEVICE_LED, 0.6, SCHEDULE_NOT_AVLB)
        time.sleep(1)
        
        _log.debug('change led level 0.9')
        self._set_sh_device_level(SH_DEVICE_LED, 0.9, SCHEDULE_NOT_AVLB)
        time.sleep(1)
        
        _log.debug('change led level 0.4')
        self._set_sh_device_level(SH_DEVICE_LED, 0.4, SCHEDULE_NOT_AVLB)
        time.sleep(1)
        
        _log.debug('switch off led')
        self._set_sh_device_state(SH_DEVICE_LED, SH_DEVICE_STATE_OFF, SCHEDULE_NOT_AVLB)
        return
        
    def _test_fan(self):
        _log.debug('switch on fan')
        self._set_sh_device_state(SH_DEVICE_FAN, SH_DEVICE_STATE_ON, SCHEDULE_NOT_AVLB)
        time.sleep(1)
        
        _log.debug('change fan level 0.3')
        self._set_sh_device_level(SH_DEVICE_FAN, 0.3, SCHEDULE_NOT_AVLB)
        time.sleep(1)
        
        _log.debug('change fan level 0.6')
        self._set_sh_device_level(SH_DEVICE_FAN, 0.6, SCHEDULE_NOT_AVLB)
        time.sleep(1)
        
        _log.debug('change fan level 0.9')
        self._set_sh_device_level(SH_DEVICE_FAN, 0.9, SCHEDULE_NOT_AVLB)
        time.sleep(1)
        
        _log.debug('change fan level 0.4')
        self._set_sh_device_level(SH_DEVICE_FAN, 0.4, SCHEDULE_NOT_AVLB)
        time.sleep(1)
        
        _log.debug('switch off fan')
        self._set_sh_device_state(SH_DEVICE_FAN, SH_DEVICE_STATE_OFF, SCHEDULE_NOT_AVLB)
        return
        
    # with schedule not available
    def _test_sensors(self):
        _log.debug('test lux sensor')
        lux_level = self._get_sh_device_level(SH_DEVICE_S_LUX, SCHEDULE_NOT_AVLB)
        _log.debug('lux Level: {:0.2f}'.format(lux_level))
        time.sleep(1)
        
        _log.debug('test rh sensor')
        rh_level = self._get_sh_device_level(SH_DEVICE_S_RH, SCHEDULE_NOT_AVLB)
        _log.debug('rh Level: {:0.2f}'.format(rh_level))
        time.sleep(1)
        
        _log.debug('test temp sensor')
        temp_level = self._get_sh_device_level(SH_DEVICE_S_TEMP, SCHEDULE_NOT_AVLB)
        _log.debug('temp Level: {:0.2f}'.format(temp_level))
        time.sleep(1)
        
        _log.debug('test co2 sensor')
        co2_level = self._get_sh_device_level(SH_DEVICE_S_CO2, SCHEDULE_NOT_AVLB)
        _log.debug('co2 Level: {0:0.2f}'.format(co2_level))
        time.sleep(1)
        
        _log.debug('test PIR sensor')
        pir_level = self._get_sh_device_level(SH_DEVICE_S_PIR, SCHEDULE_NOT_AVLB)
        _log.debug('PIR Level: {0:d}'.format(int(pir_level)))
        return
        
    # with schedule available
    def _test_sensors_2(self):
        task_id = str(randint(0, 99999999))
        success = get_task_schdl(self, task_id, 'iiit/cbs/smarthub', 300)
        if not success: return
        
        _log.debug('test lux sensor')
        lux_level = self._get_sh_device_level(SH_DEVICE_S_LUX, SCHEDULE_AVLB)
        _log.debug('lux Level: {:0.2f}'.format(lux_level))
        
        _log.debug('test rh sensor')
        rh_level = self._get_sh_device_level(SH_DEVICE_S_RH, SCHEDULE_AVLB)
        _log.debug('rh Level: {:0.2f}'.format(rh_level))
        
        _log.debug('test temp sensor')
        temp_level = self._get_sh_device_level(SH_DEVICE_S_TEMP, SCHEDULE_AVLB)
        _log.debug('temp Level: {:0.2f}'.format(temp_level))
        
        _log.debug('test co2 sensor')
        co2_level = self._get_sh_device_level(SH_DEVICE_S_CO2, SCHEDULE_AVLB)
        _log.debug('co2 Level: {:0.2f}'.format(co2_level))
        
        _log.debug('test pir sensor')
        pir_level = self._get_sh_device_level(SH_DEVICE_S_PIR, SCHEDULE_AVLB)
        _log.debug('pir Level: {:d}'.format(int(pir_level)))
        
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
    def _get_initial_hw_state(self):
        # _log.debug('_get_initial_hw_state()')
        task_id = str(randint(0, 99999999))
        success = get_task_schdl(self, task_id, 'iiit/cbs/smarthub', 300)
        if not success: return
        
        self._sh_devices_state[SH_DEVICE_LED] = \
                                self._get_sh_device_state(SH_DEVICE_LED, SCHEDULE_AVLB)
        self._sh_devices_state[SH_DEVICE_FAN] = \
                                self._get_sh_device_state(SH_DEVICE_FAN, SCHEDULE_AVLB)
        self._sh_devices_level[SH_DEVICE_LED] = \
                                self._get_sh_device_level(SH_DEVICE_LED, SCHEDULE_AVLB)
        self._sh_devices_level[SH_DEVICE_FAN] = \
                                self._get_sh_device_level(SH_DEVICE_FAN, SCHEDULE_AVLB)
        cancel_task_schdl(self, task_id)
        return
        
    def _get_sh_device_state(self, lhw_device_id, schd_exist):
        if not self._valid_device_action(lhw_device_id, AT_GET_STATE):
            _log.error ('Error: not a valid device to get state, lhw_device_id:'
                                                            + ' {}.'.format(lhw_device_id))
            return E_UNKNOWN_STATE
            
        state = E_UNKNOWN_STATE
        if schd_exist == SCHEDULE_AVLB: 
            state = self._rpcget_sh_device_state(lhw_device_id);
            return state
        elif schd_exist == SCHEDULE_NOT_AVLB:
            task_id = str(randint(0, 99999999))
            success = get_task_schdl(self, task_id, 'iiit/cbs/smarthub')
            if not success: return E_UNKNOWN_STATE
            try:
                state = self._rpcget_sh_device_state(lhw_device_id);
            except Exception as e:
                _log.exception('no task schdl for getting device state')
                # print(e)
            finally:
                # cancel the schedule
                cancel_task_schdl(self, task_id)
        else:
            _log.error('Error: not a valid param - schd_exist: {}'.format(schd_exist))
            return E_UNKNOWN_STATE
        return state
        
    def _get_sh_device_level(self, lhw_device_id, schd_exist):
        # _log.debug('_get_sh_device_level()')
        if not self._valid_device_action( lhw_device_id, AT_GET_LEVEL):
            _log.error('Error: not a valid device to get level, lhw_device_id:'
                                                            + ' {}.'.format(lhw_device_id))
            return E_UNKNOWN_LEVEL
            
        level = E_UNKNOWN_LEVEL
        if schd_exist == SCHEDULE_AVLB: 
            level = self._rpcget_sh_device_level(lhw_device_id);
        elif schd_exist == SCHEDULE_NOT_AVLB:
            task_id = str(randint(0, 99999999))
            success = get_task_schdl(self, task_id, 'iiit/cbs/smarthub')
            if not success: return E_UNKNOWN_LEVEL
            try:
                level = self._rpcget_sh_device_level(lhw_device_id);
            except Exception as e:
                _log.warning('no task schdl for getting device level.'
                                        + ' message: {}'.format(e.message))
                # print(e)
            finally:
                # cancel the schedule
                cancel_task_schdl(self, task_id)
        else:
            _log.warning('Error: not a valid param - schd_exist: {}'.format(schd_exist))
            return E_UNKNOWN_LEVEL
        return level
                
    def _set_sh_device_state(self, lhw_device_id, state, schd_exist):
        # _log.debug('_set_sh_device_state()')
        if not self._valid_device_action(lhw_device_id, AT_SET_STATE):
            _log.warning('Error: not a valid device to change state, lhw_device_id:'
                                                            + ' {}.'.format(lhw_device_id))
            return
            
        if self._sh_devices_state[lhw_device_id] == state:
            _log.debug('same state, do nothing')
            return
            
        if schd_exist == SCHEDULE_AVLB: 
            self._rpcset_sh_device_state(lhw_device_id, state)
            end_point = self._get_lhw_end_point(lhw_device_id, AT_SET_STATE)
            self._update_sh_device_state(lhw_device_id, end_point,state)
        elif schd_exist == SCHEDULE_NOT_AVLB:
            task_id = str(randint(0, 99999999))
            success = get_task_schdl(self, task_id, 'iiit/cbs/smarthub')
            if not success: return
            try:
                self._rpcset_sh_device_state(lhw_device_id, state)
                end_point = self._get_lhw_end_point(lhw_device_id, AT_SET_STATE)
                self._update_sh_device_state(lhw_device_id, end_point,state)
            except Exception as e:
                _log.exception('no task schdl for changing device state')
                # print(e)
            finally:
                # cancel the schedule
                cancel_task_schdl(self, task_id)
        else:
            _log.exception('not a valid param - schd_exist: {}'.format(schd_exist))
        return
        
    def _set_sh_device_level(self, lhw_device_id, level, schd_exist):
        # _log.debug('_set_sh_device_level()')
        if not self._valid_device_action( lhw_device_id, AT_SET_LEVEL):
            _log.exception('not a valid device to change level, lhw_device_id:'
                                                    + ' {}.'.format(lhw_device_id))
            return
            
        if isclose(level, self._sh_devices_level[lhw_device_id], EPSILON):
            _log.debug('same level, do nothing')
            return
            
        if schd_exist == SCHEDULE_AVLB: 
            self._rpcset_sh_device_level(lhw_device_id, level);
            end_point = self._get_lhw_end_point(lhw_device_id, AT_SET_LEVEL)
            self._updateShDeviceLevel(lhw_device_id, end_point,level)
        elif schd_exist == SCHEDULE_NOT_AVLB:
            task_id = str(randint(0, 99999999))
            success = get_task_schdl(self, task_id, 'iiit/cbs/smarthub')
            if not success: return
            try:
                self._rpcset_sh_device_level(lhw_device_id, level);
                end_point = self._get_lhw_end_point(lhw_device_id, AT_SET_LEVEL)
                self._updateShDeviceLevel(lhw_device_id, end_point,level)
            except Exception as e:
                _log.exception('no task schdl for changing device level')
                # print(e)
            finally:
                # cancel the schedule
                cancel_task_schdl(self, task_id)
        else:
            # do notthing
            _log.exception('not a valid param - schd_exist: ' + schd_exist)
        return
        
    def _set_sh_device_th_pp(self, lhw_device_id, thPP):
        if not self._valid_device_action(lhw_device_id, AT_SET_THPP):
            _log.exception('not a valid device to change thPP, lhw_device_id: ' + str(lhw_device_id))
            return
        
        if self._sh_devices_th_pp[lhw_device_id] == thPP:
            _log.debug('same thPP, do nothing')
            return
        
        self._sh_devices_th_pp[lhw_device_id] = thPP
        self._publish_sh_device_th_pp(lhw_device_id, thPP)
        self._apply_pricing_policy(lhw_device_id, SCHEDULE_NOT_AVLB)
        return
        
    def publish_hw_data(self):
        self._publish_device_state();
        self._publish_device_level();
        self._publish_device_th_pp();
        self._publish_sensor_data();
        return
        
    def _publish_sensor_data(self):
        # _log.debug('publish_sensor_data()')
        task_id = str(randint(0, 99999999))
        success = get_task_schdl(self, task_id, 'iiit/cbs/smarthub', 300)
        if not success: return
        
        lux_level = self._get_sh_device_level(SH_DEVICE_S_LUX, SCHEDULE_AVLB)
        rh_level = self._get_sh_device_level(SH_DEVICE_S_RH, SCHEDULE_AVLB)
        temp_level = self._get_sh_device_level(SH_DEVICE_S_TEMP, SCHEDULE_AVLB)
        co2_level = self._get_sh_device_level(SH_DEVICE_S_CO2, SCHEDULE_AVLB)
        pir_level = self._get_sh_device_level(SH_DEVICE_S_PIR, SCHEDULE_AVLB)
        cancel_task_schdl(self, task_id)
        _log.debug('Lux: {:0.2f}'.format(lux_level)
                    + ', Rh: {:0.2f}'.format(rh_level)
                    + ', Temp: {:0.2f}'.format(temp_level)
                    + ', Co2: {:0.2f}'.format(co2_level)
                    + ', PIR: {:d}'.format('OCCUPIED' if int(pir_level) == 1 else 'UNOCCUPIED')
                    )
                    
        pub_topic = self._root_topic + '/sensors/all'
        pub_msg = [{'luxlevel':lux_level,
                    'rhlevel':rh_level,
                    'templevel':temp_level,
                    'co2level': co2_level,
                    'pirlevel': pir_level
                    },
                    {'luxlevel':{'units': 'lux', 'tz': 'UTC', 'type': 'float'},
                        'rhlevel':{'units': 'cent', 'tz': 'UTC', 'type': 'float'},
                        'templevel':{'units': 'degree', 'tz': 'UTC', 'type': 'float'},
                        'co2level':{'units': 'ppm', 'tz': 'UTC', 'type': 'float'},
                        'pirlevel':{'units': 'bool', 'tz': 'UTC', 'type': 'int'}
                    }
                    ]
        _log.info('[LOG] Sensors Data, Msg: {}'.format(pub_msg))
        _log.debug('Publishing to local bus topic: {}'.format(pub_topic))
        publish_to_bus(self, pub_topic, pub_msg)
        _log.debug('done.')
        return
        
    def _publish_device_state(self):
        # _log.debug('publish_device_state()')
        state_led = self._sh_devices_state[SH_DEVICE_LED]
        state_fan = self._sh_devices_state[SH_DEVICE_FAN]
        self._publish_sh_device_state(SH_DEVICE_LED, state_led)
        self._publish_sh_device_state(SH_DEVICE_FAN, state_fan)
        _log.debug('Led state: {}'.format('ON' if state_led == SH_DEVICE_STATE_ON else 'OFF')
                + ', Fan state: {}'.format('ON' if state_fan == SH_DEVICE_STATE_ON else 'OFF'))
        return
        
    def _publish_device_level(self):
        # _log.debug('publish_device_level()')
        level_led = self._sh_devices_level[SH_DEVICE_LED]
        level_fan = self._sh_devices_level[SH_DEVICE_FAN]
        self._publish_sh_device_level(SH_DEVICE_LED, level_led)
        self._publish_sh_device_level(SH_DEVICE_FAN, level_fan)
        _log.debug('Led level: {:0.2f}'.format(level_led)
                    + ', Fan level: {:0.2f}'.format(level_fan))
        return
        
    def _publish_device_th_pp(self):
        # _log.debug('publish_device_th_pp()')
        thpp_led = self._sh_devices_th_pp[SH_DEVICE_LED]
        thpp_fan = self._sh_devices_th_pp[SH_DEVICE_FAN]
        self._publish_sh_device_th_pp(SH_DEVICE_LED, thpp_led)
        self._publish_sh_device_th_pp(SH_DEVICE_FAN, thpp_fan)
        _log.debug('Led threshold price: {:0.2f}'.format(thpp_led)
                    + ', Fan threshold price: {0:0.2f}'.format(thpp_fan))
        return
        
    def _rpcget_sh_device_state(self, lhw_device_id):
        end_point = self._get_lhw_end_point(lhw_device_id, AT_GET_STATE)
        try:
            device_state = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/smarthub/' + end_point).get(timeout=10 )
        except gevent.Timeout:
            _log.exception('gevent.Timeout in _rpcget_sh_device_state()')
            return E_UNKNOWN_STATE
        except RemoteError as re:
            # print(re)
            return E_UNKNOWN_STATE
        except Exception as e:
            _log.exception('Could not contact actuator. Is it running?')
            # print(e)
            return E_UNKNOWN_STATE
        return int(device_state)
        
    def _rpcset_sh_device_state(self, lhw_device_id, state):
        end_point = self._get_lhw_end_point(lhw_device_id, AT_SET_STATE)
        try:
            result = self.vip.rpc.call(
                    'platform.actuator', 
                    'set_point',
                    self._agent_id, 
                    'iiit/cbs/smarthub/' + end_point,
                    state).get(timeout=10)
        except gevent.Timeout:
            _log.exception('gevent.Timeout in _rpcset_sh_device_state()')
            return
        except Exception as e:
            _log.exception('Could not contact actuator. Is it running?')
            # print(e)
            return
        return
        
    def _rpcget_sh_device_level(self, lhw_device_id):
        # _log.debug('_rpcget_sh_device_level()')
        end_point = self._get_lhw_end_point(lhw_device_id, AT_GET_LEVEL)
        # _log.debug('end_point: ' + end_point)
        try:
            device_level = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/smarthub/' + end_point).get(timeout=10)
            return device_level
        except gevent.Timeout:
            _log.exception('gevent.Timeout in _rpcget_sh_device_level()')
            return E_UNKNOWN_LEVEL
        except Exception as e:
            _log.exception('Could not contact actuator. Is it running?')
            # print(e)
            return E_UNKNOWN_LEVEL
        return E_UNKNOWN_LEVEL
        
    def _rpcset_sh_device_level(self, lhw_device_id, level):
        end_point = self._get_lhw_end_point(lhw_device_id, AT_SET_LEVEL)
        try:
            result = self.vip.rpc.call(
                    'platform.actuator', 
                    'set_point',
                    self._agent_id, 
                    'iiit/cbs/smarthub/' + end_point,
                    level).get(timeout=10)
            return
        except gevent.Timeout:
            _log.exception('gevent.Timeout in _rpcset_sh_device_level()')
            return
        except Exception as e:
            _log.exception('Could not contact actuator. Is it running?')
            # print(e)
            return
            
    def _update_sh_device_state(self, lhw_device_id, end_point, state):
        # _log.debug('_update_sh_device_state()')
        headers = { 'requesterID': self._agent_id, }
        
        device_state = self._rpcget_sh_device_state(lhw_device_id)
        # check if the state really updated at the h/w, only then proceed with new state
        if state == device_state:
            self._sh_devices_state[lhw_device_id] = state
            self._publish_sh_device_state(lhw_device_id, state)
            
        if self._sh_devices_state[lhw_device_id] == SH_DEVICE_STATE_ON:
            _log.debug('Current State: ' + end_point + ' Switched ON!!!')
        else:
            _log.debug('Current State: ' + end_point + ' Switched OFF!!!')
            
        return
        
    def _updateShDeviceLevel(self, lhw_device_id, end_point, level):
        # _log.debug('_updateShDeviceLevel()')
        
        _log.debug('level {0:0.2f}'.format( level))
        device_level = self._rpcget_sh_device_level(lhw_device_id)
        # check if the level really updated at the h/w, only then proceed with new level
        if isclose(level, device_level, EPSILON):
            _log.debug('same value!!!')
            self._sh_devices_level[lhw_device_id] = level
            self._publish_sh_device_level(lhw_device_id, level)
            
        _log.debug('Current level, ' + end_point + ': ' + '{:0.2f}'.format( device_level))
            
        return
        
    def _publish_sh_device_state(self, lhw_device_id, state):
        if not self._valid_device_action(lhw_device_id, AT_PUB_STATE):
            _log.exception('not a valid device to pub state, lhw_device_id: ' + str(lhw_device_id))
            return
        pub_topic = self._get_lhw_sub_topic(lhw_device_id, AT_PUB_STATE)
        _log.info('[LOG] SH device state, Msg: {}'.format(pub_msg))
        pub_msg = [state, {'units': 'On/Off', 'tz': 'UTC', 'type': 'int'}]
        _log.debug('Publishing to local bus topic: {}'.format(pub_topic))
        publish_to_bus(self, pub_topic, pub_msg)
        _log.debug('done.')
        return
        
    def _publish_sh_device_level(self, lhw_device_id, level):
        # _log.debug('_publish_sh_device_level()')
        if not self._valid_device_action(lhw_device_id, AT_PUB_LEVEL):
            _log.exception('not a valid device to pub level, lhw_device_id: ' + str(lhw_device_id))
            return
        pub_topic = self._get_lhw_sub_topic(lhw_device_id, AT_PUB_LEVEL)
        pub_msg = [level, {'units': 'duty', 'tz': 'UTC', 'type': 'float'}]
        _log.info('[LOG] SH device level, Msg: {}'.format(pub_msg))
        _log.debug('Publishing to local bus topic: {}'.format(pub_topic))
        publish_to_bus(self, pub_topic, pub_msg)
        _log.debug('done.')
        return
        
    def _publish_sh_device_th_pp(self, lhw_device_id, thPP):
        if not self._valid_device_action(lhw_device_id, AT_PUB_THPP):
            _log.exception('not a valid device to pub level, lhw_device_id: ' + str(lhw_device_id))
            return
        pub_topic = self._get_lhw_sub_topic(lhw_device_id, AT_PUB_THPP)
        pub_msg = [thPP, {'units': 'cent', 'tz': 'UTC', 'type': 'float'}]
        _log.info('[LOG] SH device threshold price, Msg: {}'.format(pub_msg))
        _log.debug('Publishing to local bus topic: {}'.format(pub_topic))
        publish_to_bus(self, pub_topic, pub_msg)
        _log.debug('done.')
        return
        
    def _get_lhw_sub_topic(self, lhw_device_id, actionType):
        if actionType == AT_PUB_STATE:
            if lhw_device_id == SH_DEVICE_LED_DEBUG:
                return self._root_topic + '/leddebugstate'
            elif lhw_device_id == SH_DEVICE_LED:
                return self._root_topic + '/ledstate'
            elif lhw_device_id == SH_DEVICE_FAN:
                return self._root_topic + '/fanstate'
        elif actionType == AT_PUB_LEVEL:
            if lhw_device_id == SH_DEVICE_LED:
                return self._root_topic + '/ledlevel'
            elif lhw_device_id == SH_DEVICE_FAN:
                return self._root_topic + '/fanlevel'
            elif lhw_device_id == SH_DEVICE_S_LUX:
                return self._root_topic + '/sensors/luxlevel'
            elif lhw_device_id == SH_DEVICE_S_RH:
                return self._root_topic + '/sensors/rhlevel'
            elif lhw_device_id == SH_DEVICE_S_TEMP:
                return self._root_topic + '/sensors/templevel'
            elif lhw_device_id == SH_DEVICE_S_CO2:
                return self._root_topic + '/sensors/co2level'
            elif lhw_device_id == SH_DEVICE_S_PIR:
                return self._root_topic + '/sensors/pirlevel'
        elif actionType == AT_PUB_THPP:
            if lhw_device_id == SH_DEVICE_LED:
                return self._root_topic + '/ledthpp'
            elif lhw_device_id == SH_DEVICE_FAN:
                return self._root_topic + '/fanthpp'
        _log.exception('not a valid device-action type for pub_topic')
        return ''
        
    def _get_lhw_end_point(self, lhw_device_id, actionType):
        # _log.debug('_get_lhw_end_point()')
        if  actionType == AT_SET_LEVEL:
            if lhw_device_id == SH_DEVICE_LED:
                return 'LEDPwmDuty'
            elif lhw_device_id == SH_DEVICE_FAN:
                return 'FanPwmDuty'
        elif actionType == AT_GET_LEVEL:
            if lhw_device_id == SH_DEVICE_LED:
                return 'LEDPwmDuty'
            elif lhw_device_id == SH_DEVICE_FAN:
                return 'FanPwmDuty'
            elif lhw_device_id == SH_DEVICE_S_LUX:
                return 'SensorLux'
            elif lhw_device_id == SH_DEVICE_S_RH:
                return 'SensorRh'
            elif lhw_device_id == SH_DEVICE_S_TEMP:
                return 'SensorTemp'
            elif lhw_device_id == SH_DEVICE_S_CO2:
                return 'SensorCO2'
            elif lhw_device_id == SH_DEVICE_S_PIR:
                return 'SensorOccupancy'
        elif actionType in [AT_GET_STATE, AT_SET_STATE]:
            if lhw_device_id == SH_DEVICE_LED_DEBUG:
                return 'LEDDebug'
            elif lhw_device_id == SH_DEVICE_LED:
                return 'LED'
            elif lhw_device_id == SH_DEVICE_FAN:
                return 'Fan'
        
        _log.exception('not a valid device-action type for end_point')
        return ''
        
    def _valid_device_action(self, lhw_device_id, actionType):
        # _log.debug('_valid_device_action()')
        if actionType not in [AT_GET_STATE
                                , AT_GET_LEVEL
                                , AT_SET_STATE
                                , AT_SET_LEVEL
                                , AT_PUB_LEVEL
                                , AT_PUB_STATE
                                , AT_GET_THPP
                                , AT_SET_THPP
                                , AT_PUB_THPP
                                ]:
            return False
            
        if actionType == AT_GET_STATE :
            if lhw_device_id in [SH_DEVICE_LED_DEBUG
                            , SH_DEVICE_LED
                            , SH_DEVICE_FAN
                            ]:
                return True
        elif actionType ==  AT_GET_LEVEL :
            if lhw_device_id in [SH_DEVICE_LED
                            , SH_DEVICE_FAN
                            , SH_DEVICE_S_LUX
                            , SH_DEVICE_S_RH
                            , SH_DEVICE_S_TEMP
                            , SH_DEVICE_S_CO2
                            , SH_DEVICE_S_PIR
                            ]:
                return True
        elif actionType == AT_SET_STATE :
            if lhw_device_id in [SH_DEVICE_LED_DEBUG
                            , SH_DEVICE_LED
                            , SH_DEVICE_FAN
                            ]:
                return True
        elif actionType == AT_SET_LEVEL :
            if lhw_device_id in [SH_DEVICE_LED
                            , SH_DEVICE_FAN
                            ]:
                return True
        elif actionType == AT_PUB_LEVEL :
            if lhw_device_id in [SH_DEVICE_LED
                            , SH_DEVICE_FAN
                            , SH_DEVICE_S_LUX
                            , SH_DEVICE_S_RH
                            , SH_DEVICE_S_TEMP
                            , SH_DEVICE_S_CO2
                            , SH_DEVICE_S_PIR
                            ]:
                return True
        elif actionType == AT_PUB_STATE :
            if lhw_device_id in [SH_DEVICE_LED_DEBUG
                            , SH_DEVICE_LED
                            , SH_DEVICE_FAN
                            ]:
                return True
        elif actionType in [AT_GET_THPP
                            , AT_SET_THPP
                            , AT_PUB_THPP
                            ]:
            if lhw_device_id in [SH_DEVICE_LED
                            , SH_DEVICE_FAN
                            ]:
                return True
        log.exception ('not a valid device-action')
        return False
        
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
        
        task_id = str(randint(0, 99999999))
        success = get_task_schdl(self, task_id, 'iiit/cbs/smarthub')
        if not success:
            _log.debug('unable to process_opt_pp()'
                            + ', will try again in {} sec'.format(self._period_process_pp))
            self._process_opt_pp_success = False
            return
            
        self._apply_pricing_policy(SH_DEVICE_LED, SCHEDULE_AVLB)
        if not self._process_opt_pp_success:
            _log.debug('unable to process_opt_pp()'
                            + ', will try again in {} sec'.format(self._period_process_pp))
            cancel_task_schdl(self, task_id)
            return
            
        self._apply_pricing_policy(SH_DEVICE_FAN, SCHEDULE_AVLB)
        if not self._process_opt_pp_success:
            _log.debug('unable to process_opt_pp()'
                            + ', will try again in {} sec'.format(self._period_process_pp))
            cancel_task_schdl(self, task_id)
            return
            
        cancel_task_schdl(self, task_id)
        
        _log.info('New Price Point processed.')
        # on successful process of apply_pricing_policy with the latest opt pp, current = latest
        self._opt_pp_msg_current = copy(self._opt_pp_msg_latest)
        return
        
    def _apply_pricing_policy(self, lhw_device_id, schd_exist):
        _log.debug('_apply_pricing_policy()')
        threshold_pp = self._sh_devices_th_pp[lhw_device_id]
        if self._price_point_latest > threshold_pp: 
            if self._sh_devices_state[lhw_device_id] == SH_DEVICE_STATE_ON:
                _log.debug(self._get_lhw_end_point(lhw_device_id, AT_GET_STATE)
                            + ' Current price point > threshold'
                            + '({0:.2f}), '.format(threshold_pp)
                            + 'Switching-Off Power'
                            )
                self._set_sh_device_state(lhw_device_id, SH_DEVICE_STATE_OFF, schd_exist)
                if self._sh_devices_state[lhw_device_id] != SH_DEVICE_STATE_OFF:
                    self._process_opt_pp_success = False
            # else:
                # do nothing
        else:
            _log.debug(self._get_lhw_end_point(lhw_device_id, AT_GET_STATE)
                        + ' Current price point <= threshold'
                        + '({0:.2f}), '.format(threshold_pp)
                        + 'Switching-On Power'
                        )
            self._set_sh_device_state(lhw_device_id, SH_DEVICE_STATE_ON, schd_exist)
            if self._sh_devices_state[lhw_device_id] != SH_DEVICE_STATE_ON:
                self._process_opt_pp_success = False
                
            if lhw_device_id == SH_DEVICE_FAN:
                fan_speed = self._compute_new_fan_speed(self._price_point_latest) / 100
                _log.debug( 'New Fan Speed: {0:.4f}'.format(fan_speed))
                self._set_sh_device_level(SH_DEVICE_FAN, fan_speed, schd_exist)
                if not isclose(fan_speed, self._sh_devices_level[lhw_device_id], EPSILON):
                    self._process_opt_pp_success = False
                    
        return
        
    # compute new Fan Speed (0-100%) from price functions
    def _compute_new_fan_speed(self, pp):
        pp = 0 if pp < 0 else 1 if pp > 1 else pp
        
        idx = self._pf_sh_fan['idx']
        roundup = self._pf_sh_fan['roundup']
        coefficients = self._pf_sh_fan['coefficients']
        
        a = coefficients[idx]['a']
        b = coefficients[idx]['b']
        c = coefficients[idx]['c']
        
        speed = a*pp**2 + b*pp + c
        return mround(speed, roundup)
        
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
        # active pwr should be measured in realtime from the connected plug
        # however, since we don't have model for the battery charge controller
        # we are assumuing constant energy for the devices based on experimental data
        
        #sh base energy demand
        tap = SH_BASE_POWER
        
        #sh led active power
        if self._sh_devices_state[SH_DEVICE_LED] == SH_DEVICE_STATE_ON:
            led_level = self._sh_devices_level[SH_DEVICE_LED]
            tap += ((SH_LED_POWER * SH_LED_THRESHOLD_PCT)
                                    if led_level <= SH_LED_THRESHOLD_PCT
                                    else (SH_LED_POWER * led_level))
                                    
        #sh fan active power
        if self._sh_devices_state[SH_DEVICE_FAN] == SH_DEVICE_STATE_ON:
            fan_speed = self._sh_devices_level[SH_DEVICE_FAN]
            tap += ((SH_FAN_POWER * SH_LED_THRESHOLD_PCT)
                                    if fan_speed <= SH_LED_THRESHOLD_PCT
                                    else (SH_FAN_POWER * fan_speed))
        return tap
        
    def _process_bid_pp(self, pp_msg):
        self._bid_pp_msg_latest = copy(pp_msg)
        self.process_bid_pp()
        return
        
    # this is a perodic function that keeps trying to apply the new pp till success
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
        
        #sh base energy demand
        ted = calc_energy_wh(SH_BASE_POWER, duration)
        
        #sh led energy demand
        if bid_pp <= self._sh_devices_th_pp[SH_DEVICE_LED]:
            led_level = self._sh_devices_level[SH_DEVICE_LED]
            led_energy = calc_energy_wh(SH_LED_POWER, duration)
            ted += ((led_energy * SH_LED_THRESHOLD_PCT)
                                    if led_level <= SH_LED_THRESHOLD_PCT 
                                    else (led_energy * led_level))
                                    
        #sh fan energy demand
        if bid_pp <= self._sh_devices_th_pp[SH_DEVICE_FAN]:
            fan_speed = self._compute_new_fan_speed(bid_pp)
            fan_energy = calc_energy_wh(SH_FAN_POWER, duration)
            ted += ((fan_energy * SH_FAN_THRESHOLD_PCT)
                                    if fan_speed <= SH_FAN_THRESHOLD_PCT
                                    else (fan_energy * fan_speed))
        return ted
        
        
def main(argv=sys.argv):
    '''Main method called by the eggsecutable.'''
    try:
        utils.vip_main(smarthub)
    except Exception as e:
        print (e)
        _log.exception('unhandled exception')
        
        
if __name__ == '__main__':
    # Entry point for script
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        pass
        
        
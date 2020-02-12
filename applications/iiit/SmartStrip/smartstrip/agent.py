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

# smartstrip base peak energy (200mA * 12V)
SMARTSTRIP_BASE_ENERGY = 2

def smartstrip(config_path, **kwargs):
    config = utils.load_config(config_path)
    vip_identity = config.get('vip_identity', 'iiit.smartstrip')
    # This agent needs to be named iiit.smartstrip. Pop the uuid id off the kwargs
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
    _plugs_connected = [ 0, 0, 0, 0]
    _plugs_active_pwr = [0.0, 0.0, 0.0, 0.0]
    _plugs_tag_id = ['7FC000007FC00000', '7FC000007FC00000', '7FC000007FC00000', '7FC000007FC00000']
    _plugs_th_pp = [0.35, 0.5, 0.75, 0.95]
    
    _new_tag_id1 = ''
    _new_tag_id2 = ''
    _new_tag_id3 = ''
    _new_tag_id4 = ''
    
    # smartstrip total energy demand
    _ted = SMARTSTRIP_BASE_ENERGY
    
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
        
        # retrive self._device_id and self._discovery_address from vb
        retrive_details_from_vb(self, 5)
        
        # register rpc routes with MASTER_WEB
        # register_rpc_route is a blocking call
        register_rpc_route(self, 'smartstrip', 'rpc_from_net', 5)
        
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
        
        self._run_smartstrip_test()
        
        # TODO: get the latest values (states/levels) from h/w
        # self.getInitialHwState()
        # time.sleep(1) # yeild for a movement
        
        # TODO: apply pricing policy for default values
        
        # TODO: publish initial data to volttron bus
        
        # perodically read the meter data & connected tag ids from h/w
        self.core.periodic(self._period_read_data, self.get_plug_data, wait=None)
        
        # perodically publish plug threshold price point to volttron bus
        self.core.periodic(self._period_read_data, self.publish_plug_th_pp, wait=None)
        
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
        
        _log.debug('switch on debug led')
        self._switch_led_debug(LED_ON)
        
        _log.debug('startup() - Done. Agent is ready')
        return
        
    @Core.receiver('onstop')
    def onstop(self, sender, **kwargs):
        _log.debug('onstop()')
        if self._volt_state != 0:
            self._stop_volt()
        
        unregister_with_bridge(self)
        
        _log.debug('un registering rpc routes')
        self.vip.rpc.call(MASTER_WEB, 'unregister_all_agent_routes').get(timeout=10)
        return
        
    @Core.receiver('onfinish')
    def onfinish(self, sender, **kwargs):
        _log.debug('onfinish()')
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
            elif rpcdata.method == 'plug-th-pp' and header['REQUEST_METHOD'] == 'GET':
                if not _valid_plug_id(rpcdata.params['plug_id']):
                    raise KeyError('invalid plug id')
                args = {'plug_id': rpcdata.params['plug_id']
                        }
                result = self.get_th_pp(**args)
            elif rpcdata.method == 'plug-th-pp' and header['REQUEST_METHOD'] == 'POST':
                if not _valid_plug_id(rpcdata.params['plug_id']):
                    raise KeyError('invalid plug id')
                args = {'plug_id': rpcdata.params['plug_id'],
                        'new_th_pp': rpcdata.params['new_th_pp']
                        }
                result = self.set_th_pp(**args)
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
                        str(plug_id+1), ': ', new_th_pp))
            self._plugs_th_pp[plug_id] = new_th_pp
            self._apply_pricing_policy(plug_id, SCHEDULE_NOT_AVLB)
            self._publish_threshold_pp(plug_id, new_th_pp)
        return 'success'
        
    def _stop_volt(self):
        _log.debug('_stop_volt()')
        task_id = str(randint(0, 99999999))
        success = get_task_schdl(self, task_id,'iiit/cbs/zonecontroller')
        if not success:
            self._volt_state = 0
            return
        try:
            self._switch_led_debug(LED_OFF)
            self._switch_relay(PLUG_ID_1, RELAY_OFF, SCHEDULE_AVLB)
            self._switch_relay(PLUG_ID_2, RELAY_OFF, SCHEDULE_AVLB)
            self._switch_relay(PLUG_ID_3, RELAY_OFF, SCHEDULE_AVLB)
            self._switch_relay(PLUG_ID_4, RELAY_OFF, SCHEDULE_AVLB)
        except Exception as e:
            _log.exception('Could not contact actuator. Is it running?')
        finally:
            # cancel the schedule
            cancel_task_schdl(self, task_id)
        self._volt_state = 0
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
        self._vb_vip_identity = self.config.get('vb_vip_identity', 'iiit.volttronbridge')
        self._root_topic = self.config.get('topic_root', 'smartstrip')
        self._topic_price_point = self.config.get('topic_price_point', 'smartstrip/pricepoint')
        self._topic_energy_demand = self.config.get('topic_energy_demand', 'ds/energydemand')
        return
        
    def _run_smartstrip_test(self):
        _log.debug('Running: _run_smartstrip_test()...')
        _log.debug('switch on debug led')
        self._switch_led_debug(LED_ON)
        time.sleep(1)
        
        _log.debug('switch off debug led')
        self._switch_led_debug(LED_OFF)
        time.sleep(1)
        
        _log.debug('switch on debug led')
        self._switch_led_debug(LED_ON)
        
        self._test_relays()
        
        _log.debug('switch off debug led')
        self._switch_led_debug(LED_OFF)
        _log.debug('EOF Testing')
        
        return
        
    def _test_relays(self):
        result = {}
        # get schedule for testing relays
        task_id = str(randint(0, 99999999))
        # _log.debug('task_id: ' + task_id)
        result = get_task_schdl(self, task_id,'iiit/cbs/smartstrip')
        
        # test all four relays
        if result['result'] == 'SUCCESS':
            _log.debug('switch on relay 1')
            self._switch_relay(PLUG_ID_1, RELAY_ON, True)
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
        
    def publish_plug_th_pp(self):
        self._publish_threshold_pp(PLUG_ID_1, self._plugs_th_pp[PLUG_ID_1])
        self._publish_threshold_pp(PLUG_ID_2, self._plugs_th_pp[PLUG_ID_2])
        self._publish_threshold_pp(PLUG_ID_3, self._plugs_th_pp[PLUG_ID_3])
        self._publish_threshold_pp(PLUG_ID_4, self._plugs_th_pp[PLUG_ID_4])
        return
        
    def get_plug_data(self):
        # _log.debug('get_plug_data()...')
        result = {}
        
        # get schedule for to h/w latest data
        task_id = str(randint(0, 99999999))
        # _log.debug('task_id: ' + task_id)
        result = get_task_schdl(self, task_id,'iiit/cbs/smartstrip')
        
        # run the task
        if result['result'] == 'SUCCESS':
        
            # _log.debug('meterData()')
            if self._plugs_relay_state[PLUG_ID_1] == RELAY_ON:
                self._rpcget_meter_data(PLUG_ID_1)
                
            if self._plugs_relay_state[PLUG_ID_2] == RELAY_ON:
                self._rpcget_meter_data(PLUG_ID_2)
                
            if self._plugs_relay_state[PLUG_ID_3] == RELAY_ON:
                self._rpcget_meter_data(PLUG_ID_3)
                
            if self._plugs_relay_state[PLUG_ID_4] == RELAY_ON:
                self._rpcget_meter_data(PLUG_ID_4)
                
            # _log.debug('..._rpcget_tag_ids()')
            self._rpcget_tag_ids()
            
            # _log.debug('start _process_new_tag_id()...')
            self._process_new_tag_id(PLUG_ID_1, self._new_tag_id1)
            self._process_new_tag_id(PLUG_ID_2, self._new_tag_id2)
            self._process_new_tag_id(PLUG_ID_3, self._new_tag_id3)
            self._process_new_tag_id(PLUG_ID_4, self._new_tag_id4)
            # _log.debug('...done _process_new_tag_id()')
            
            # cancel the schedule
            cancel_task_schdl(self, task_id)
        return
        
    def _rpcget_meter_data(self, plug_id):
        # _log.debug ('_rpcget_meter_data(), plug_id: ' + str(plug_id))
        if plug_id not in [PLUG_ID_1, PLUG_ID_2, PLUG_ID_3, PLUG_ID_4]:
            return
            
        point_voltage = 'Plug' + str(plug_id+1) + 'Voltage'
        point_current = 'Plug' + str(plug_id+1) + 'Current'
        point_active_power = 'Plug' + str(plug_id+1) +'ActivePower'
        pub_topic = self._root_topic + '/plug' + str(plug_id+1) + '/meterdata/all'
        
        try:
            f_voltage = self.vip.rpc.call('platform.actuator'
                                            ,'get_point',
                                            'iiit/cbs/smartstrip/' + point_voltage
                                            ).get(timeout=10)
            # _log.debug('voltage: {:.2f}'.format(f_voltage))
            f_current = self.vip.rpc.call('platform.actuator'
                                            ,'get_point',
                                            , 'iiit/cbs/smartstrip/' + point_current
                                            ).get(timeout=10)
            # _log.debug('current: {:.2f}'.format(f_current))
            f_active_power = self.vip.rpc.call('platform.actuator'
                                            ,'get_point',
                                            'iiit/cbs/smartstrip/' + point_active_power
                                            ).get(timeout=10)
            # _log.debug('active: {:.2f}'.format(f_active_power))
            
            # keep track of plug active power
            self._plugs_active_pwr[plug_id] = f_active_power
            
            # publish data to volttron bus
            self._publish_meter_data(pub_topic, f_voltage, f_current, f_active_power)
            
            _log.info(('Plug {:d}: '.format(plug_id + 1)
                    + 'voltage: {:.2f}'.format(f_voltage) 
                    + ', Current: {:.2f}'.format(f_current)
                    + ', ActivePower: {:.2f}'.format(f_active_power)
                    ))
        except gevent.Timeout:
            _log.exception('gevent.Timeout in _rpcget_meter_data()')
            return
        except Exception as e:
            _log.exception('exception in _rpcget_meter_data()')
            print(e)
            return
        return
        
    def _rpcget_tag_ids(self):
        # _log.debug('_rpcget_tag_ids()')
        self._new_tag_id1 = ''
        self._new_tag_id2 = ''
        self._new_tag_id3 = ''
        self._new_tag_id4 = ''
        
        try:
            '''
            Smart Strip bacnet server splits the 64 bit tag id 
            into two parts and sends them accros as two float values.
            Hence need to get both the points (floats value)
            and recover the actual tag id
            '''
            f1_tag_id_1 = self.vip.rpc.call('platform.actuator'
                                            ,'get_point',
                                            'iiit/cbs/smartstrip/TagID1_1'
                                            ).get(timeout=10)
                                            
            f2_tag_id_1 = self.vip.rpc.call('platform.actuator'
                                            ,'get_point',
                                            , 'iiit/cbs/smartstrip/TagID1_2'
                                            ).get(timeout=10)
            self._new_tag_id1 = self._construct_tag_id(f1_tag_id_1, f2_tag_id_1)
            
            # get second tag id
            f1_tag_id_2 = self.vip.rpc.call('platform.actuator'
                                            ,'get_point'
                                            , 'iiit/cbs/smartstrip/TagID2_1'
                                            ).get(timeout=10)
                    
            f2_tag_id_2 = self.vip.rpc.call('platform.actuator'
                                            ,'get_point'
                                            , 'iiit/cbs/smartstrip/TagID2_2'
                                            ).get(timeout=10)
            self._new_tag_id2 = self._construct_tag_id(f1_tag_id_2, f2_tag_id_2)
            
            # get third tag id
            f1_tag_id_3 = self.vip.rpc.call('platform.actuator'
                                            , 'get_point'
                                            , 'iiit/cbs/smartstrip/TagID3_1'
                                            ).get(timeout=10)
                    
            f2_tag_id_3 = self.vip.rpc.call('platform.actuator'
                                            , 'get_point'
                                            , 'iiit/cbs/smartstrip/TagID3_2'
                                            ).get(timeout=10)
            self._new_tag_id3 = self._construct_tag_id(f1_tag_id_3, f2_tag_id_3)
            
            # get fourth tag id
            f1_tag_id_4 = self.vip.rpc.call('platform.actuator'
                                            , 'get_point'
                                            , 'iiit/cbs/smartstrip/TagID4_1'
                                            ).get(timeout=10)
                    
            f2_tag_id_4 = self.vip.rpc.call('platform.actuator'
                                            ,'get_point'
                                            , 'iiit/cbs/smartstrip/TagID4_2'
                                            ).get(timeout=10)
            self._new_tag_id4 = self._construct_tag_id(f1_tag_id_4, f2_tag_id_4)
            
            _log.info('Tag 1: '+ self._new_tag_id1 +', Tag 2: ' + self._new_tag_id2 + ', Tag 3: '+ self._new_tag_id3 +', Tag 4: ' + self._new_tag_id4)
            
        except gevent.Timeout:
            _log.exception('gevent.Timeout in _rpcget_tag_ids()')
            return
        except Exception as e:
            _log.exception('Exception: reading tag ids')
            print(e)
            return
        return
        
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
                else:
                    _log.info(('Plug {:d}: '.format(plug_id + 1),
                            'Unauthorised device connected',
                            '(tag id: ',
                            new_tag_id, ')'))
                    self._publish_tag_id(plug_id, new_tag_id)
                    # TODO: bug with new unauthorised tag id, switch-off power if its already swithched-on
                    
        else:
            # no device connected condition, new tag id is DEFAULT_TAG_ID
            if self._plugs_connected[plug_id] == 0:
                return
            elif self._plugs_connected[plug_id] == 1 or
                    new_tag_id != self._plugs_tag_id[plug_id] or
                    self._plugs_relay_state[plug_id] == RELAY_ON:
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
        
    def _authorised_tag_id(self, tag_id):
        return (True if tag_id in self._tag_ids else False)
        
    def _switch_led_debug(self, state):
        _log.debug('_switch_led_debug()')
        # result = {}
        
        if self._led_debug_state == state:
            _log.info('same state, do nothing')
            return
            
        # get schedule to _switch_led_debug
        task_id = str(randint(0, 99999999))
        # _log.debug('task_id: ' + task_id)
        result = get_task_schdl(self, task_id,'iiit/cbs/smartstrip')
        
        if result['result'] == 'SUCCESS':
            result = {}
            try:
                # _log.debug('schl avlb')
                result = self.vip.rpc.call(
                        'platform.actuator', 
                        'set_point',
                        self._agent_id, 
                        'iiit/cbs/smartstrip/LEDDebug',
                        state).get(timeout=10)
                        
                self.updateLedDebugState(state)
            except gevent.Timeout:
                _log.exception('gevent.Timeout in _switch_led_debug()')
            except Exception as e:
                _log.exception('setting ledDebug')
                print(e)
            finally:
                # cancel the schedule
                cancel_task_schdl(self, task_id)
        return
        
    def _switch_relay(self, plug_id, state, schdExist):
        # _log.debug('switchPlug1Relay()')
        
        if self._plugs_relay_state[plug_id] == state:
            _log.debug('same state, do nothing')
            return
            
        if schdExist == SCHEDULE_AVLB: 
            self._rpcset_relay(plug_id, state);
        elif schdExist == SCHEDULE_NOT_AVLB:
            # get schedule to _switch_relay
            task_id = str(randint(0, 99999999))
            # _log.debug('task_id: ' + task_id)
            result = get_task_schdl(self, task_id,'iiit/cbs/smartstrip')
            
            if result['result'] == 'SUCCESS':
                try:
                    self._rpcset_relay(plug_id, state)
                    
                except gevent.Timeout:
                    _log.exception('gevent.Timeout in _switch_relay()')
                    return
                except Exception as e:
                    _log.exception('setting plug' + str(plug_id) + ' relay')
                    print(e)
                    return
                finally:
                    # cancel the schedule
                    cancel_task_schdl(self, task_id)
                    return
        else:
            # do notthing
            return
        return
        
    def _rpcset_relay(self, plug_id, state):
        try:
            result = self.vip.rpc.call(
                    'platform.actuator', 
                    'set_point',
                    self._agent_id, 
                    'iiit/cbs/smartstrip/Plug' + str(plug_id+1) + 'Relay',
                    state).get(timeout=10)
        except gevent.Timeout:
            _log.exception('gevent.Timeout in _rpcset_relay()')
            # return E_UNKNOWN_STATE
        except Exception as e:
            _log.exception('in _rpcset_relay() Could not contact actuator. Is it running?')
            print(e)
            # return E_UNKNOWN_STATE
            
        # _log.debug('OK call updatePlug1RelayState()')
        self.updatePlugRelayState(plug_id, state)
        return
        
    def updateLedDebugState(self, state):
        _log.debug('updateLedDebugState()')
        headers = { 'requesterID': self._agent_id, }
        try:
            ledDebug_status = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/smartstrip/LEDDebug').get(timeout=10)
        except gevent.Timeout:
            _log.exception('gevent.Timeout in updateLedDebugState()')
            ledDebug_status = E_UNKNOWN_STATE
        except Exception as e:
            _log.exception('in updateLedDebugState() Could not contact actuator. Is it running?')
            print(e)
            ledDebug_status = E_UNKNOWN_STATE
            
        if state == int(ledDebug_status):
            self._led_debug_state = state
            
        if state == LED_ON:
            _log.info('Current State: LED Debug is ON!!!')
        elif state == LED_OFF:
            _log.info('Current State: LED Debug is OFF!!!')
        else:
            _log.info('Current State: LED Debug STATE UNKNOWN!!!')
        return
        
    def updatePlugRelayState(self, plug_id, state):
        # _log.debug('updatePlug1RelayState()')
        headers = { 'requesterID': self._agent_id, }
        try:
            relay_status = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/smartstrip/Plug' + str(plug_id+1) + 'Relay').get(timeout=10)
        except gevent.Timeout:
            _log.exception('gevent.Timeout in updatePlugRelayState()')
            relay_status = E_UNKNOWN_STATE
        except Exception as e:
            _log.exception('in updatePlugRelayState() Could not contact actuator. Is it running?')
            print(e)
            relay_status = E_UNKNOWN_STATE
            
        if state == int(relay_status):
            self._plugs_relay_state[plug_id] = state
            self.publishRelayState(plug_id, state)
            
        if state == RELAY_ON:
            _log.info('Current State: Plug ' + str(plug_id+1) + ' Relay Switched ON!!!')
        elif state == RELAY_OFF:
            _log.info('Current State: Plug ' + str(plug_id+1) + ' Relay Switched OFF!!!')
        else:
            _log.info('Current State: Plug ' + str(plug_id+1) + ' Relay STATE UNKNOWN!!!')
        return
        
    def _publish_meter_data(self, pub_topic, fVolatge, fCurrent, fActivePower):
        pub_msg = [{'voltage':fVolatge, 'current':fCurrent,
                    'active_power':fActivePower},
                    {'voltage':{'units': 'V', 'tz': 'UTC', 'type': 'float'},
                    'current':{'units': 'A', 'tz': 'UTC', 'type': 'float'},
                    'active_power':{'units': 'W', 'tz': 'UTC', 'type': 'float'}
                    }]
        publish_to_bus(self, pub_topic, pub_msg)
        return
        
    def _publish_tag_id(self, plug_id, new_tag_id):
        if not self._valid_plug_id(plug_id):
            return
            
        pub_topic = self._root_topic + '/plug' + str(plug_id+1) + '/tagid'
        pub_msg = [new_tag_id,{'units': '', 'tz': 'UTC', 'type': 'string'}]
        publish_to_bus(self, pub_topic, pub_msg)
        return
        
    def publishRelayState(self, plug_id, state):
        if not self._valid_plug_id(plug_id):
            return
            
        pub_topic = self._root_topic + '/plug' + str(plug_id+1) + '/relaystate'
        pub_msg = [state,{'units': 'On/Off', 'tz': 'UTC', 'type': 'int'}]
        publish_to_bus(self, pub_topic, pub_msg)
        return
        
    def _publish_threshold_pp(self, plug_id, thresholdPP):
        if not self._valid_plug_id(plug_id):
            return
            
        pub_topic = self._root_topic + '/plug' + str(plug_id+1) + '/threshold'
        pub_msg = [thresholdPP,{'units': 'cents', 'tz': 'UTC', 'type': 'float'}]
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
        
    # this is a periodic function that
    def process_bid_pp(self):
        bid_ed = self.compute_bid_ed(self._bid_pp)
        # publish bid_ed
        
        return
        
    # this is a perodic function that keeps trying to apply the new pp till success
    def process_opt_pp(self):
        if isclose(self._price_point_old, self._price_point_latest, EPSILON) and self._pp_id == self._pp_id_new:
            return
            
        self._process_opt_pp_success = True     # any process that failed to apply pp, sets this flag True
        # get schedule for testing relays
        task_id = str(randint(0, 99999999))
        # _log.debug('task_id: ' + task_id)
        result = get_task_schdl(self, task_id,'iiit/cbs/smartstrip')
        if result['result'] != 'SUCCESS':
            _log.debug('unable to process_opt_pp(), will try again in ' + str(self._period_process_pp))
            self._process_opt_pp_success = False
            return
            
        self._apply_pricing_policy(PLUG_ID_1, SCHEDULE_AVLB)
        self._apply_pricing_policy(PLUG_ID_2, SCHEDULE_AVLB)
        self._apply_pricing_policy(PLUG_ID_3, SCHEDULE_AVLB)
        self._apply_pricing_policy(PLUG_ID_4, SCHEDULE_AVLB)
        # cancel the schedule
        cancel_task_schdl(self, task_id)
        
        if self._process_opt_pp_success:
            _log.debug('unable to process_opt_pp(), will try again in ' + str(self._period_process_pp))
            return
            
        _log.info('New Price Point processed.')
        self._price_point_old = self._price_point_latest
        self._pp_id = self._pp_id_new
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
                if not self._plugs_relay_state[plug_id] == RELAY_OFF:
                    self._process_opt_pp_success = False
                    
            # else:
                # do nothing
        else:
            if self._plugs_connected[plug_id] == 1 and self._authorised_tag_id(self._plugs_tag_id[plug_id]):
                _log.info(('Plug {:d}: '.format(plug_id + 1)
                            , 'Current price point < threshold'
                            , '({:.2f}), '.format(plug_pp_th)
                            , 'Switching-On Power'
                            ))
                self._switch_relay(plug_id, RELAY_ON, schdExist)
                if not self._plugs_relay_state[plug_id] == RELAY_ON:
                    self._process_opt_pp_success = False
            # else:
                # do nothing
        return
        
    # calculate the bid total energy demand (TED)
    def _bid_ted(self):
        # _log.debug('_calculate_ted()')
        bid_ted = SMARTSTRIP_BASE_ENERGY
        for idx in enumerate(self._plugs_relay_state):
            if idx != self._sh_plug_id:
                bid_ted = bid_ted + self._plugs_active_pwr[idx]
        return bid_ted
        
    # calculate the total energy demand (TED)
    def _calculate_ted(self):
        # _log.debug('_calculate_ted()')
        ted = SMARTSTRIP_BASE_ENERGY
        for idx, plugState in enumerate(self._plugs_relay_state):
            if plugState == RELAY_ON and idx != self._sh_plug_id:
                ted = ted + self._plugs_active_pwr[idx]
        return ted
        
    def publish_ted(self):
        self._ted = self._calculate_ted()
        _log.info( 'New TED: {:.4f}, publishing to bus.'.format(self._ted))
        pub_topic = self._topic_energy_demand
        # _log.debug('TED pub_topic: ' + pub_topic)
        pub_msg = [self._ted
                    , {'units': 'W', 'tz': 'UTC', 'type': 'float'}
                    , self._pp_id
                    , True
                    , None
                    , None
                    , None
                    , self._period_read_data
                    , datetime.datetime.utcnow().isoformat(' ') + 'Z'
                    ]
        publish_to_bus(self, pub_topic, pub_msg)
        return
        
    def _valid_plug_id(self, plug_id):
        if plug_id == PLUG_ID_1 or plug_id == PLUG_ID_2 or plug_id == PLUG_ID_3 or plug_id == PLUG_ID_4:
            return True
        else:
            return False
            
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
        
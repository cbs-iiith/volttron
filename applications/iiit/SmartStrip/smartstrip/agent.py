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
    
    _taskID_LedDebug = 1
    _taskID_Plug1Relay = 2
    _taskID_Plug2Relay = 3
    _taskID_ReadTagIDs = 4
    _taskID_ReadMeterData = 5

    _ledDebugState = 0
    _plugRelayState = [0, 0, 0, 0]
    _plugConnected = [ 0, 0, 0, 0]
    _plugActivePwr = [0.0, 0.0, 0.0, 0.0]
    _plug_tag_id = ['7FC000007FC00000', '7FC000007FC00000', '7FC000007FC00000', '7FC000007FC00000']
    _plug_pricepoint_th = [0.35, 0.5, 0.75, 0.95]
    
    _price_point_current = 0.4 
    _price_point_latest = 0.45
    _pp_id = randint(0, 99999999)
    _pp_id_latest = randint(0, 99999999)
    
    _newTagId1 = ''
    _newTagId2 = ''
    _newTagId3 = ''
    _newTagId4 = ''
    
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
        self.core.periodic(self._period_read_data, self.getData, wait=None)
        
        # perodically publish plug threshold price point to volttron bus
        self.core.periodic(self._period_read_data, self.publishPlugThPP, wait=None)
        
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
        self.switchLedDebug(LED_ON)
        
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
        
    def _stop_volt(self):
        _log.debug('_stop_volt()')
        task_id = str(randint(0, 99999999))
        success = get_task_schdl(self, task_id,'iiit/cbs/zonecontroller')
        if not success:
            self._volt_state = 0
            return
        try:
            self.switchLedDebug(LED_OFF)
            self.switchRelay(PLUG_ID_1, RELAY_OFF, SCHEDULE_AVLB)
            self.switchRelay(PLUG_ID_2, RELAY_OFF, SCHEDULE_AVLB)
            self.switchRelay(PLUG_ID_3, RELAY_OFF, SCHEDULE_AVLB)
            self.switchRelay(PLUG_ID_4, RELAY_OFF, SCHEDULE_AVLB)
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
        self._plug_pricepoint_th = self.config['plug_pricepoint_th']
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
        self.switchLedDebug(LED_ON)
        time.sleep(1)
        
        _log.debug('switch off debug led')
        self.switchLedDebug(LED_OFF)
        time.sleep(1)
        
        _log.debug('switch on debug led')
        self.switchLedDebug(LED_ON)
        
        self.testRelays()
        
        _log.debug('switch off debug led')
        self.switchLedDebug(LED_OFF)
        _log.debug('EOF Testing')
        
        return
        
    def testRelays(self):
        result = {}
        # get schedule for testing relays
        task_id = str(randint(0, 99999999))
        # _log.debug('task_id: ' + task_id)
        result = get_task_schdl(self, task_id,'iiit/cbs/smartstrip')
        
        # test all four relays
        if result['result'] == 'SUCCESS':
            _log.debug('switch on relay 1')
            self.switchRelay(PLUG_ID_1, RELAY_ON, True)
            time.sleep(1)
            _log.debug('switch off relay 1')
            self.switchRelay(PLUG_ID_1, RELAY_OFF, SCHEDULE_AVLB)
            
            _log.debug('switch on relay 2')
            self.switchRelay(PLUG_ID_2, RELAY_ON, SCHEDULE_AVLB)
            time.sleep(1)
            _log.debug('switch off relay 2')
            self.switchRelay(PLUG_ID_2, RELAY_OFF, SCHEDULE_AVLB)
            
            _log.debug('switch on relay 3')
            self.switchRelay(PLUG_ID_3, RELAY_ON, SCHEDULE_AVLB)
            time.sleep(1)
            _log.debug('switch off relay 3')
            self.switchRelay(PLUG_ID_3, RELAY_OFF, SCHEDULE_AVLB)
            
            _log.debug('switch on relay 4')
            self.switchRelay(PLUG_ID_4, RELAY_ON, SCHEDULE_AVLB)
            time.sleep(1)
            _log.debug('switch off relay 4')
            self.switchRelay(PLUG_ID_4, RELAY_OFF, SCHEDULE_AVLB)
            
            # cancel the schedule
            cancel_task_schdl(self, task_id)
        return
        
    def publishPlugThPP(self):
        self.publishThresholdPP(PLUG_ID_1,
                                self._plug_pricepoint_th[PLUG_ID_1])
        self.publishThresholdPP(PLUG_ID_2,
                                self._plug_pricepoint_th[PLUG_ID_2])
        self.publishThresholdPP(PLUG_ID_3,
                                self._plug_pricepoint_th[PLUG_ID_3])
        self.publishThresholdPP(PLUG_ID_4,
                                self._plug_pricepoint_th[PLUG_ID_4])
        return
        
    def getData(self):
        # _log.debug('getData()...')
        result = {}
        
        # get schedule for to h/w latest data
        task_id = str(randint(0, 99999999))
        # _log.debug('task_id: ' + task_id)
        result = get_task_schdl(self, task_id,'iiit/cbs/smartstrip')
        
        # run the task
        if result['result'] == 'SUCCESS':
        
            # _log.debug('meterData()')
            if self._plugRelayState[PLUG_ID_1] == RELAY_ON:
                self.readMeterData(PLUG_ID_1)
                
            if self._plugRelayState[PLUG_ID_2] == RELAY_ON:
                self.readMeterData(PLUG_ID_2)
                
            if self._plugRelayState[PLUG_ID_3] == RELAY_ON:
                self.readMeterData(PLUG_ID_3)
                
            if self._plugRelayState[PLUG_ID_4] == RELAY_ON:
                self.readMeterData(PLUG_ID_4)
                
            # _log.debug('...readTagIDs()')
            self.readTagIDs()
            
            # _log.debug('start processNewTagId()...')
            self.processNewTagId(PLUG_ID_1, self._newTagId1)
            self.processNewTagId(PLUG_ID_2, self._newTagId2)
            self.processNewTagId(PLUG_ID_3, self._newTagId3)
            self.processNewTagId(PLUG_ID_4, self._newTagId4)
            # _log.debug('...done processNewTagId()')
            
            # cancel the schedule
            cancel_task_schdl(self, task_id)
        return
        
    def readMeterData(self, plugID):
        # _log.debug ('readMeterData(), plugID: ' + str(plugID))
        if plugID not in [PLUG_ID_1, PLUG_ID_2, PLUG_ID_3, PLUG_ID_4]:
            return
            
        pointVolatge = 'Plug'+str(plugID+1)+'Voltage'
        pointCurrent = 'Plug'+str(plugID+1)+'Current'
        pointActivePower = 'Plug'+str(plugID+1)+'ActivePower'
        pubTopic = self._root_topic + '/plug' + str(plugID+1) + '/meterdata/all'
        
        try:
            fVolatge = self.vip.rpc.call('platform.actuator'
                                            ,'get_point',
                                            'iiit/cbs/smartstrip/' + pointVolatge
                                            ).get(timeout=10)
            # _log.debug('voltage: {:.2f}'.format(fVolatge))
            fCurrent = self.vip.rpc.call('platform.actuator'
                                            ,'get_point',
                                            , 'iiit/cbs/smartstrip/' + pointCurrent
                                            ).get(timeout=10)
            # _log.debug('current: {:.2f}'.format(fCurrent))
            fActivePower = self.vip.rpc.call('platform.actuator'
                                            ,'get_point',
                                            'iiit/cbs/smartstrip/' + pointActivePower
                                            ).get(timeout=10)
            # _log.debug('active: {:.2f}'.format(fActivePower))
            
            # keep track of plug active power
            self._plugActivePwr[plugID] = fActivePower
            
            # publish data to volttron bus
            self.publishMeterData(pubTopic, fVolatge, fCurrent, fActivePower)
            
            _log.info(('Plug {:d}: '.format(plugID + 1)
                    + 'voltage: {:.2f}'.format(fVolatge) 
                    + ', Current: {:.2f}'.format(fCurrent)
                    + ', ActivePower: {:.2f}'.format(fActivePower)
                    ))
        except gevent.Timeout:
            _log.exception('gevent.Timeout in readMeterData()')
            return
        except Exception as e:
            _log.exception('exception in readMeterData()')
            print(e)
            return
        return
        
    def readTagIDs(self):
        # _log.debug('readTagIDs()')
        self._newTagId1 = ''
        self._newTagId2 = ''
        self._newTagId3 = ''
        self._newTagId4 = ''
        
        try:
            '''
            Smart Strip bacnet server splits the 64 bit tag id 
            into two parts and sends them accros as two float values.
            Hence need to get both the points (floats value)
            and recover the actual tag id
            '''
            newTagId1 = ''
            newTagId2 = ''
            newTagId3 = ''
            newTagId4 = ''
            
            fTagID1_1 = self.vip.rpc.call('platform.actuator'
                                            ,'get_point',
                                            'iiit/cbs/smartstrip/TagID1_1'
                                            ).get(timeout=10)
                                            
            fTagID1_2 = self.vip.rpc.call('platform.actuator'
                                            ,'get_point',
                                            , 'iiit/cbs/smartstrip/TagID1_2'
                                            ).get(timeout=10)
            self._newTagId1 = self.recoveryTagID(fTagID1_1, fTagID1_2)
            # _log.debug('Tag 1: ' + newTagId1)
            
            # get second tag id
            fTagID2_1 = self.vip.rpc.call('platform.actuator'
                                            ,'get_point'
                                            , 'iiit/cbs/smartstrip/TagID2_1'
                                            ).get(timeout=10)
                    
            fTagID2_2 = self.vip.rpc.call('platform.actuator'
                                            ,'get_point'
                                            , 'iiit/cbs/smartstrip/TagID2_2'
                                            ).get(timeout=10)
            self._newTagId2 = self.recoveryTagID(fTagID2_1, fTagID2_2)
            # _log.debug('Tag 2: ' + newTagId2)
            
            # get third tag id
            fTagID3_1 = self.vip.rpc.call('platform.actuator'
                                            , 'get_point'
                                            , 'iiit/cbs/smartstrip/TagID3_1'
                                            ).get(timeout=10)
                    
            fTagID3_2 = self.vip.rpc.call('platform.actuator'
                                            , 'get_point'
                                            , 'iiit/cbs/smartstrip/TagID3_2'
                                            ).get(timeout=10)
            self._newTagId3 = self.recoveryTagID(fTagID3_1, fTagID3_2)
            # _log.debug('Tag 3: ' + newTagId3)
            
            # get fourth tag id
            fTagID4_1 = self.vip.rpc.call('platform.actuator'
                                            , 'get_point'
                                            , 'iiit/cbs/smartstrip/TagID4_1'
                                            ).get(timeout=10)
                    
            fTagID4_2 = self.vip.rpc.call('platform.actuator'
                                            ,'get_point'
                                            , 'iiit/cbs/smartstrip/TagID4_2'
                                            ).get(timeout=10)
            self._newTagId4 = self.recoveryTagID(fTagID4_1, fTagID4_2)
            # _log.debug('Tag 4: ' + newTagId4)
            
            _log.info('Tag 1: '+ self._newTagId1 +', Tag 2: ' + self._newTagId2 + ', Tag 3: '+ self._newTagId3 +', Tag 4: ' + self._newTagId4)
            
        except gevent.Timeout:
            _log.exception('gevent.Timeout in readTagIDs()')
            return
        except Exception as e:
            _log.exception('Exception: reading tag ids')
            print(e)
            return
        return
        
    def processNewTagId(self, plugID, newTagId):
        # empty string
        if not newTagId:
            # do nothing
            return
            
        if newTagId != '7FC000007FC00000':
            # device is connected condition
            # check if current tag id is same as new, if so, do nothing
            if newTagId == self._plug_tag_id[plugID]:
                return
            else:
                # update the tag id and change connected state
                self._plug_tag_id[plugID] = newTagId
                self.publishTagId(plugID, newTagId)
                self._plugConnected[plugID] = 1
                if self.tagAuthorised(newTagId):
                    plug_pp_th = self._plug_pricepoint_th[plugID]
                    if self._price_point_latest < plug_pp_th:
                        _log.info(('Plug {:d}: '.format(plugID + 1),
                                'Current price point < '
                                'threshold {:.2f}, '.format(plug_pp_th),
                                'Switching-on power'))
                        self.switchRelay(plugID, RELAY_ON, SCHEDULE_AVLB)
                    else:
                        _log.info(('Plug {:d}: '.format(plugID + 1),
                                'Current price point > threshold',
                                '({:.2f}), '.format(plug_pp_th),
                                'No-power'))
                else:
                    _log.info(('Plug {:d}: '.format(plugID + 1),
                            'Unauthorised device connected',
                            '(tag id: ',
                            newTagId, ')'))
                    self.publishTagId(plugID, newTagId)
                    # TODO: bug with new unauthorised tag id, switch-off power if its already swithched-on
                    
        else:
            # no device connected condition, new tag id is DEFAULT_TAG_ID
            if self._plugConnected[plugID] == 0:
                return
            elif self._plugConnected[plugID] == 1 or
                    newTagId != self._plug_tag_id[plugID] or
                    self._plugRelayState[plugID] == RELAY_ON:
                # update the tag id and change connected state
                self._plug_tag_id[plugID] = newTagId
                self.publishTagId(plugID, newTagId)
                self._plugConnected[plugID] = 0
                self.switchRelay(plugID, RELAY_OFF, SCHEDULE_AVLB)
        return
        
    def on_new_price(self, peer, sender, bus,  topic, headers, message):
        if sender == 'pubsub.compat':
            message = compat.unpack_legacy_message(headers, message)
            
        new_pp = message[ParamPP.idx_pp]
        new_pp_datatype = message[ParamPP.idx_pp_datatype]
        new_pp_id = message[ParamPP.idx_pp_id]
        new_pp_isoptimal = message[ParamPP.idx_pp_isoptimal]
        discovery_address = message[ParamPP.idx_pp_discovery_addrs]
        deviceId = message[ParamPP.idx_pp_device_id]
        new_pp_ttl = message[ParamPP.idx_pp_ttl]
        new_pp_ts = message[ParamPP.idx_pp_ts]
                
        if not new_pp_isoptimal:
            _log.debug('not optimal pp!!!')
            self._bid_pp = new_pp
            self._bid_pp_datatype = new_pp_datatype
            self._bid_pp_id = new_pp_id
            self._bid_pp_ttl = new_pp_ttl
            self._bid_pp_ts = new_pp_ts
            # process bid_pp
            self.process_bid_pp()
            return
            
        self._price_point_latest = new_pp
        self._pp_id_latest = new_pp_id
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
        
    def _apply_pricing_policy(self, plugID, schdExist):
        plug_pp_th = self._plug_pricepoint_th[plugID]
        if self._price_point_latest > plug_pp_th:
            if self._plugRelayState[plugID] == RELAY_ON:
                _log.info(('Plug {:d}: '.format(plugID + 1)
                            , 'Current price point > threshold'
                            , '({:.2f}), '.format(plug_pp_th)
                            , 'Switching-Off Power'
                            ))
                self.switchRelay(plugID, RELAY_OFF, schdExist)
                if not self._plugRelayState[plugID] == RELAY_OFF:
                    self._process_opt_pp_success = False
                    
            # else:
                # do nothing
        else:
            if self._plugConnected[plugID] == 1 and self.tagAuthorised(self._plug_tag_id[plugID]):
                _log.info(('Plug {:d}: '.format(plugID + 1)
                            , 'Current price point < threshold'
                            , '({:.2f}), '.format(plug_pp_th)
                            , 'Switching-On Power'
                            ))
                self.switchRelay(plugID, RELAY_ON, schdExist)
                if not self._plugRelayState[plugID] == RELAY_ON:
                    self._process_opt_pp_success = False
            # else:
                # do nothing
        return
        
    def recoveryTagID(self, fTagIDPart1, fTagIDPart2):
        buff = self.convertToByteArray(fTagIDPart1, fTagIDPart2)
        tag = ''
        for i in reversed(buff):
            tag = tag + format(i, '02x')
        return tag.upper()
        
    def convertToByteArray(self, fltVal1, fltVal2):
        idLsb = bytearray(struct.pack('f', fltVal1))
        # for id in idLsb:
        #    print 'id: {:02x}'.format(id)
        idMsb = bytearray(struct.pack('f', fltVal2))
        
        idMsb = bytearray(struct.pack('f', fltVal2))
        return (idMsb + idLsb)
        
    def tagAuthorised(self, tagID):
        # return True
        for authTagID in self._tag_ids:
            if tagID == authTagID:
                return True
        return False
        
    @RPC.export
    def setThresholdPP(self, plugID, newThreshold):
        _log.debug('setThresholdPP()')
        if self._plug_pricepoint_th[plugID] != newThreshold:
            _log.info(('Changing Threshold: Plug ',
                        str(plugID+1), ': ', newThreshold))
            self._plug_pricepoint_th[plugID] = newThreshold
            self.publishThresholdPP(plugID, newThreshold)
        return 'success'
        
    def switchLedDebug(self, state):
        _log.debug('switchLedDebug()')
        # result = {}
        
        if self._ledDebugState == state:
            _log.info('same state, do nothing')
            return
            
        # get schedule to switchLedDebug
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
                _log.exception('gevent.Timeout in switchLedDebug()')
            except Exception as e:
                _log.exception('setting ledDebug')
                print(e)
            finally:
                # cancel the schedule
                cancel_task_schdl(self, task_id)
        return
        
    def switchRelay(self, plugID, state, schdExist):
        # _log.debug('switchPlug1Relay()')
        
        if self._plugRelayState[plugID] == state:
            _log.debug('same state, do nothing')
            return
            
        if schdExist == SCHEDULE_AVLB: 
            self.rpc_switchRelay(plugID, state);
        elif schdExist == SCHEDULE_NOT_AVLB:
            # get schedule to switchRelay
            task_id = str(randint(0, 99999999))
            # _log.debug('task_id: ' + task_id)
            result = get_task_schdl(self, task_id,'iiit/cbs/smartstrip')
            
            if result['result'] == 'SUCCESS':
                try:
                    self.rpc_switchRelay(plugID, state)
                    
                except gevent.Timeout:
                    _log.exception('gevent.Timeout in switchRelay()')
                    return
                except Exception as e:
                    _log.exception('setting plug' + str(plugID) + ' relay')
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
        
    def rpc_switchRelay(self, plugID, state):
        try:
            result = self.vip.rpc.call(
                    'platform.actuator', 
                    'set_point',
                    self._agent_id, 
                    'iiit/cbs/smartstrip/Plug' + str(plugID+1) + 'Relay',
                    state).get(timeout=10)
        except gevent.Timeout:
            _log.exception('gevent.Timeout in rpc_switchRelay()')
            # return E_UNKNOWN_STATE
        except Exception as e:
            _log.exception('in rpc_switchRelay() Could not contact actuator. Is it running?')
            print(e)
            # return E_UNKNOWN_STATE
            
        # _log.debug('OK call updatePlug1RelayState()')
        self.updatePlugRelayState(plugID, state)
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
            self._ledDebugState = state
            
        if state == LED_ON:
            _log.info('Current State: LED Debug is ON!!!')
        elif state == LED_OFF:
            _log.info('Current State: LED Debug is OFF!!!')
        else:
            _log.info('Current State: LED Debug STATE UNKNOWN!!!')
        return
        
    def updatePlugRelayState(self, plugID, state):
        # _log.debug('updatePlug1RelayState()')
        headers = { 'requesterID': self._agent_id, }
        try:
            relay_status = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/smartstrip/Plug' + str(plugID+1) + 'Relay').get(timeout=10)
        except gevent.Timeout:
            _log.exception('gevent.Timeout in updatePlugRelayState()')
            relay_status = E_UNKNOWN_STATE
        except Exception as e:
            _log.exception('in updatePlugRelayState() Could not contact actuator. Is it running?')
            print(e)
            relay_status = E_UNKNOWN_STATE
            
        if state == int(relay_status):
            self._plugRelayState[plugID] = state
            self.publishRelayState(plugID, state)
            
        if state == RELAY_ON:
            _log.info('Current State: Plug ' + str(plugID+1) + ' Relay Switched ON!!!')
        elif state == RELAY_OFF:
            _log.info('Current State: Plug ' + str(plugID+1) + ' Relay Switched OFF!!!')
        else:
            _log.info('Current State: Plug ' + str(plugID+1) + ' Relay STATE UNKNOWN!!!')
        return
        
    def publishMeterData(self, pubTopic, fVolatge, fCurrent, fActivePower):
        pubMsg = [{'voltage':fVolatge, 'current':fCurrent,
                    'active_power':fActivePower},
                    {'voltage':{'units': 'V', 'tz': 'UTC', 'type': 'float'},
                    'current':{'units': 'A', 'tz': 'UTC', 'type': 'float'},
                    'active_power':{'units': 'W', 'tz': 'UTC', 'type': 'float'}
                    }]
        publish_to_bus(self, pubTopic, pubMsg)
        return
        
    def publishTagId(self, plugID, newTagId):
        if not self._validPlugId(plugID):
            return
            
        pubTopic = self._root_topic + '/plug' + str(plugID+1) + '/tagid'
        pubMsg = [newTagId,{'units': '', 'tz': 'UTC', 'type': 'string'}]
        publish_to_bus(self, pubTopic, pubMsg)
        return
        
    def publishRelayState(self, plugID, state):
        if not self._validPlugId(plugID):
            return
            
        pubTopic = self._root_topic + '/plug' + str(plugID+1) + '/relaystate'
        pubMsg = [state,{'units': 'On/Off', 'tz': 'UTC', 'type': 'int'}]
        publish_to_bus(self, pubTopic, pubMsg)
        return
        
    def publishThresholdPP(self, plugID, thresholdPP):
        if not self._validPlugId(plugID):
            return
            
        pubTopic = self._root_topic + '/plug' + str(plugID+1) + '/threshold'
        pubMsg = [thresholdPP,{'units': 'cents', 'tz': 'UTC', 'type': 'float'}]
        publish_to_bus(self, pubTopic, pubMsg)
        return
        
    @RPC.export
    def rpc_from_net(self, header, message):
        result = False
        try:
            rpcdata = jsonrpc.JsonRpcData.parse(message)
            _log.debug('rpc_from_net()...'
                        + 'header: {}'.format(header)
                        + ', rpc method: {}'.format(rpcdata.method)
                        + ', rpc params: {}'.format(rpcdata.params)
                        )
            if rpcdata.method == 'ping':
                result = True
            elif rpcdata.method == 'setPlugThPP':
                result = self.setThresholdPP(message)
            else:
                return jsonrpc.json_error('NA', METHOD_NOT_FOUND,
                    'Invalid method {}'.format(rpcdata.method))
        except KeyError as ke:
            print(ke)
            return jsonrpc.json_error('NA', INVALID_PARAMS,
                    'Invalid params {}'.format(rpcdata.params))
        except AssertionError:
            print('AssertionError')
            return jsonrpc.json_error('NA', INVALID_REQUEST,
                    'Invalid rpc data {}'.format(data))
        except Exception as e:
            print(e)
            return jsonrpc.json_error('NA', UNHANDLED_EXCEPTION, e)
        return jsonrpc.json_result(rpcdata.id, result)
            
    # calculate the bid total energy demand (TED)
    def _bid_ted(self):
        # _log.debug('_calculate_ted()')
        bid_ted = SMARTSTRIP_BASE_ENERGY
        for idx in enumerate(self._plugRelayState):
            if idx != self._sh_plug_id:
                bid_ted = bid_ted + self._plugActivePwr[idx]
        return bid_ted
        
    # calculate the total energy demand (TED)
    def _calculate_ted(self):
        # _log.debug('_calculate_ted()')
        ted = SMARTSTRIP_BASE_ENERGY
        for idx, plugState in enumerate(self._plugRelayState):
            if plugState == RELAY_ON and idx != self._sh_plug_id:
                ted = ted + self._plugActivePwr[idx]
        return ted
        
    def publish_ted(self):
        self._ted = self._calculate_ted()
        _log.info( 'New TED: {:.4f}, publishing to bus.'.format(self._ted))
        pubTopic = self._topic_energy_demand
        # _log.debug('TED pubTopic: ' + pubTopic)
        pubMsg = [self._ted
                    , {'units': 'W', 'tz': 'UTC', 'type': 'float'}
                    , self._pp_id
                    , True
                    , None
                    , None
                    , None
                    , self._period_read_data
                    , datetime.datetime.utcnow().isoformat(' ') + 'Z'
                    ]
        publish_to_bus(self, pubTopic, pubMsg)
        return
        
    def _validPlugId(self, plugID):
        if plugID == PLUG_ID_1 or plugID == PLUG_ID_2 or plugID == PLUG_ID_3 or plugID == PLUG_ID_4:
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
        
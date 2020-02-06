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

from random import random, randint
from copy import copy

import settings
import time
import struct
import gevent
import gevent.event

from ispace_utils import isclose, get_task_schdl, cancel_task_schdl, publish_to_bus, mround
from ispace_utils import retrive_details_from_vb, register_agent_with_vb, register_rpc_route
from ispace_msg import ISPACE_Msg, MessageType
from ispace_msg_utils import parse_bustopic_msg, check_msg_type, tap_helper, ted_helper
from ispace_msg_utils import get_default_pp_msg, valid_bustopic_msg

utils.setup_logging()
_log = logging.getLogger(__name__)
__version__ = '0.4'

#checking if a floating point value is “numerically zero” by checking if it is lower than epsilon
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
    # This agent needs to be named iiit.zonecontroller. Pop the uuid id off the kwargs
    kwargs.pop('identity', None)
    
    Agent.__name__ = 'ZoneController_Agent'
    return ZoneController(config_path, identity=vip_identity, **kwargs)
    
    
class ZoneController(Agent):
    '''Zone Controller
    '''
    #initialized  during __init__ from config
    _period_read_data = None
    _period_process_pp = None
    _price_point_current = None
    _price_point_latest = None
    
    _vb_vip_identity = None
    _root_topic = None
    _topic_energy_demand = None
    _topic_price_point = None
    
    _device_id = None
    _discovery_address = None
    
    #any process that failed to apply pp sets this flag False
    _process_opt_pp_success = False
    
    _zone_tsp = 0
    _zone_lsp = 0
    
    _pf_zn_ac = None
    _pf_zn_light = None
    
    def __init__(self, config_path, **kwargs):
        super(ZoneController, self).__init__(**kwargs)
        _log.debug("vip_identity: " + self.core.identity)

        self.config = utils.load_config(config_path)
        self._config_get_points()
        self._config_get_init_values()
        self._config_get_pricefucntions()
        return
        
    @Core.receiver('onsetup')
    def setup(self, sender, **kwargs):
        _log.info(self.config['message'])
        self._agent_id = self.config['agentid']
        return
        
    @Core.receiver('onstart')
    def startup(self, sender, **kwargs):
        _log.info("Starting ZoneController...")
        
        #retrive self._device_id and self._discovery_address from vb
        retrive_details_from_vb(self, 5)
        
        #register rpc routes with MASTER_WEB
        #register_rpc_route is a blocking call
        register_rpc_route(self, "zonecontroller", "rpc_from_net", 5)
        
        #register this agent with vb as local device for posting active power & bid energy demand
        #pca picks up the active power & energy demand bids only if registered with vb
        #require self._vb_vip_identity, self.core.identity, self._device_id
        #register_agent_with_vb is a blocking call
        register_agent_with_vb(self, 5)
        
        self._valid_senders_list_pp = ['iiit.pricecontroller']
        
        #any process that failed to apply pp sets this flag False
        self._process_opt_pp_success = False
        
        #on successful process of apply_pricing_policy with the latest opt pp, current = latest
        self._opt_pp_msg_current = get_default_pp_msg(self._discovery_address, self._device_id)
        #latest opt pp msg received on the message bus
        self._opt_pp_msg_latest = get_default_pp_msg(self._discovery_address, self._device_id)
        
        self._bid_pp_msg_latest = get_default_pp_msg(self._discovery_address, self._device_id)
        
        self._run_bms_test()
        
        self._zone_tsp = 0
        self._zone_lsp = 0
        
        #TODO: get the latest values (states/levels) from h/w
        #self.getInitialHwState()
        #time.sleep(1) #yeild for a movement
        
        #TODO: apply pricing policy for default values
        
        #TODO: publish initial data to volttron bus
        
        #perodically publish total active power to volttron bus
        #active power is comupted at regular interval (_period_read_data default(30s))
        #this power corresponds to current opt pp
        #tap --> total active power (Wh)
        self.core.periodic(self._period_read_data, self.publish_opt_tap, wait=None)
        
        #perodically process new pricing point that keeps trying to apply the new pp till success
        self.core.periodic(self._period_process_pp, self.process_opt_pp, wait=None)
        
        #subscribing to topic_price_point
        self.vip.pubsub.subscribe("pubsub", self._topic_price_point, self.on_new_price)
        
        _log.debug('startup() - Done. Agent is ready')
        return
        
    @Core.receiver('onstop')
    def onstop(self, sender, **kwargs):
        _log.debug('onstop()')
        
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
                        + 'header: {}'.format(header)
                        + ', rpc method: {}'.format(rpcdata.method)
                        + ', rpc params: {}'.format(rpcdata.params)
                        )
            if rpcdata.method == "ping":
                return True
            else:
                return jsonrpc.json_error(rpcdata.id, METHOD_NOT_FOUND,
                                            'Invalid method {}'.format(rpcdata.method))
        except KeyError as ke:
            #print(ke)
            return jsonrpc.json_error(rpcdata.id, INVALID_PARAMS,
                                        'Invalid params {}'.format(rpcdata.params))
        except Exception as e:
            #print(e)
            return jsonrpc.json_error(rpcdata.id, UNHANDLED_EXCEPTION, e)
        return jsonrpc.json_result(rpcdata.id, result)
        
    def _config_get_init_values(self):
        self._period_read_data = self.config.get('period_read_data', 30)
        self._period_process_pp = self.config.get('period_process_pp', 10)
        self._price_point_old = self.config.get('default_base_price', 0.1)
        self._price_point_latest = self.config.get('price_point_latest', 0.2)
        return
        
    def _config_get_points(self):
        self._vb_vip_identity = self.config.get('vb_vip_identity', 'iiit.volttronbridge')
        self.root_topic = self.config.get('topic_root', 'zone')
        self._topic_energy_demand = self.config.get('topic_energy_demand', 'zone/energydemand')
        self._topic_price_point = self.config.get('topic_price_point', 'zone/pricepoint')
        return
        
    def _config_get_pricefucntions(self):
        _log.debug("_config_get_pricefucntions()")
        
        self._pf_zn_ac = self.config.get('pf_zn_ac')
        self._pf_zn_light = self.config.get('pf_zn_light')
        
        return
        
    def _run_bms_test(self):
        _log.debug("Running: _runBMS Commu Test()...")
        
        _log.debug('change tsp 26')
        self._rpcset_zone_tsp(26.0)
        time.sleep(10)
        
        _log.debug('change tsp 27')
        self._rpcset_zone_tsp(27.0)
        time.sleep(10)
        
        _log.debug('change tsp 28')
        self._rpcset_zone_tsp(28.0)
        time.sleep(10)
        
        _log.debug('change tsp 29')
        self._rpcset_zone_tsp(29.0)
        time.sleep(10)
        
        _log.debug('change lsp 25')
        self._rpcset_zone_tsp(25.0)
        time.sleep(10)
        
        _log.debug('change lsp 75')
        self._rpcset_zone_tsp(75.0)
        time.sleep(10)
        
        _log.debug('change lsp 100')
        self._rpcset_zone_tsp(100.0)
        time.sleep(10)

        _log.debug("EOF Testing")
        return
        
    def on_new_price(self, peer, sender, bus,  topic, headers, message):
        if sender not in self._valid_senders_list_pp: return
        
        #check message type before parsing
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
        
        #any process that failed to apply pp sets this flag False
        self._process_opt_pp_success = False
        #initiate the periodic process
        self.process_opt_pp()
        return
        
    def _process_bid_pp(self, pp_msg):
        self._bid_pp_msg_latest = copy(pp_msg)
        self.process_bid_pp()
        return
        
    #this is a perodic function that keeps trying to apply the new pp till success
    def process_opt_pp(self):
        if self._process_opt_pp_success:
            #_log.debug('all apply opt pp processess success, do nothing')
            return
            
        self._apply_pricing_policy()
        
        if self._process_opt_pp_success:
            _log.debug('unable to process_opt_pp()'
                                + ', will try again in {} sec'.format(self._period_process_pp))
            return
            
        _log.info("New Price Point processed.")
        #on successful process of apply_pricing_policy with the latest opt pp, current = latest
        self._opt_pp_msg_current = copy(self._opt_pp_msg_latest)
        self._price_point_current = copy(self._price_point_latest)
        self._process_opt_pp_success = True
        return
        
    def _apply_pricing_policy(self):
        _log.debug("_apply_pricing_policy()")
        
        #apply for ambient ac
        tsp = self._compute_new_tsp(self._price_point_latest)
        _log.debug('New Ambient AC Setpoint: {:0.1f}'.format( tsp))
        self._rpcset_zone_tsp(tsp)
        if not isclose(tsp, self._zone_tsp, EPSILON):
            self._process_opt_pp_success = False
            
        #apply for ambient lightinh
        lsp = self._compute_new_lsp(self._price_point_latest)
        _log.debug('New Ambient Lighting Setpoint: {:0.1f}'.format( lsp))
        self._rpcset_zone_lsp(lsp)
        if not isclose(lsp, self._zone_lsp, EPSILON):
            self._process_opt_pp_success = False
        return
        
    #compute new zone temperature setpoint from price functions
    def _compute_new_tsp(self, pp):
        pp = 0 if pp < 0 else 1 if pp > 1 else pp
        
        pf_idx = self._pf_zn_ac['pf_idx']
        pf_roundup = self._pf_zn_ac['pf_roundup']
        pf_coefficients = self._pf_zn_ac['pf_coefficients']
        
        a = pf_coefficients[pf_idx]['a']
        b = pf_coefficients[pf_idx]['b']
        c = pf_coefficients[pf_idx]['c']
        
        tsp = a*pp**2 + b*pp + c
        return mround(tsp, pf_roundup)
        
    #compute new zone lighting setpoint from price functions
    def _compute_new_lsp(self, pp):
        pp = 0 if pp < 0 else 1 if pp > 1 else pp
        
        pf_idx = self._pf_zn_light['pf_idx']
        pf_roundup = self._pf_zn_light['pf_roundup']
        pf_coefficients = self._pf_zn_light['pf_coefficients']
        
        a = pf_coefficients[pf_idx]['a']
        b = pf_coefficients[pf_idx]['b']
        c = pf_coefficients[pf_idx]['c']
        
        lsp = a*pp**2 + b*pp + c
        return mround(lsp, pf_roundup)
        
    # change ambient temperature set point
    def _rpcset_zone_tsp(self, tsp):
        #_log.debug('_rpcset_zone_tsp()')
        
        if isclose(tsp, self._zone_tsp, EPSILON):
            _log.debug('same tsp, do nothing')
            return
            
        task_id = str(randint(0, 99999999))
        result = get_task_schdl(self, task_id,'iiit/cbs/zonecontroller')
        if result['result'] == 'SUCCESS':
            result = {}
            try:
                result = self.vip.rpc.call('platform.actuator'
                                            , 'set_point'
                                            , self._agent_id
                                            , 'iiit/cbs/zonecontroller/RM_TSP'
                                            , tsp
                                            ).get(timeout=10)
                self._update_zone_tsp(tsp)
            except gevent.Timeout:
                _log.exception("Expection: gevent.Timeout in _rpcset_zone_tsp()")
            except Exception as e:
                _log.exception ("Expection: changing ambient tsp")
                #print(e)
            finally:
                #cancel the schedule
                cancel_task_schdl(self, task_id)
        else:
            _log.debug('schedule NOT available')
        return
        
    # change ambient light set point
    def _rpcset_zone_lsp(self, lsp):
        #_log.debug('_rpcset_zone_lsp()')
        
        if isclose(lsp, self._zone_lsp, EPSILON):
            _log.debug('same lsp, do nothing')
            return
            
        task_id = str(randint(0, 99999999))
        result = get_task_schdl(self, task_id,'iiit/cbs/zonecontroller')
        if result['result'] == 'SUCCESS':
            result = {}
            try:
                result = self.vip.rpc.call('platform.actuator'
                                            , 'set_point'
                                            , self._agent_id
                                            , 'iiit/cbs/zonecontroller/RM_LSP'
                                            , lsp
                                            ).get(timeout=10)
                self._update_zone_lsp(lsp)
            except gevent.Timeout:
                _log.exception("Expection: gevent.Timeout in _rpcset_zone_lsp()")
            except Exception as e:
                _log.exception ("Expection: changing ambient lsp")
                #print(e)
            finally:
                #cancel the schedule
                cancel_task_schdl(self, task_id)
        else:
            _log.debug('schedule NOT available')
        return

    def _update_zone_tsp(self, tsp):
        #_log.debug('_update_zone_tsp()')
        _log.debug('tsp {:0.1f}'.format( tsp))
        
        rm_tsp = self._rpcget_zone_tsp()
        
        #check if the tsp really updated at the bms, only then proceed with new tsp
        if isclose(tsp, rm_tsp, EPSILON):
            self._zone_tsp = tsp
            self._publish_zone_tsp(tsp)
            
        _log.debug('Current TSP: {:0.1f}'.format( rm_tsp))
        return
        
    def _update_zone_lsp(self, lsp):
        #_log.debug('_update_zone_lsp()')
        _log.debug('lsp {:0.1f}'.format( lsp))
        
        rm_lsp = self._rpcget_zone_lsp()
        
        #check if the lsp really updated at the bms, only then proceed with new lsp
        if isclose(lsp, rm_lsp, EPSILON):
            self._zone_lsp = lsp
            self._publish_zone_lsp(lsp)
            
        _log.debug('Current LSP: {:0.1f}'.format( rm_lsp))
        return
        
    def _rpcget_zone_lighting_power(self):
        task_id = str(randint(0, 99999999))
        result = get_task_schdl(self, task_id,'iiit/cbs/zonecontroller')
        if result['result'] == 'SUCCESS':
            try:
                lightEnergy = self.vip.rpc.call('platform.actuator'
                                                , 'get_point'
                                                , 'iiit/cbs/zonecontroller/RM_LIGHT_CALC_PWR'
                                                ).get(timeout=10)
                return lightEnergy
            except gevent.Timeout:
                _log.exception("Expection: gevent.Timeout in rpc_getRmCalcLightEnergy()")
                return E_UNKNOWN_CLE
            except Exception as e:
                _log.exception ("Expection: Could not contact actuator. Is it running?")
                #print(e)
                return E_UNKNOWN_CLE
            finally:
                #cancel the schedule
                cancel_task_schdl(self, task_id)
        else:
            _log.debug('schedule NOT available')
        return E_UNKNOWN_CLE
        
    def _rpcget_zone_cooling_power(self):
        task_id = str(randint(0, 99999999))
        result = get_task_schdl(self, task_id,'iiit/cbs/zonecontroller')
        if result['result'] == 'SUCCESS':
            try:
                coolingEnergy = self.vip.rpc.call('platform.actuator'
                                                    ,'get_point'
                                                    , 'iiit/cbs/zonecontroller/RM_CCE'
                                                    ).get(timeout=10)
                return coolingEnergy
            except gevent.Timeout:
                _log.exception("Expection: gevent.Timeout in _rpcget_zone_cooling_power()")
                return E_UNKNOWN_CCE
            except Exception as e:
                _log.exception ("Expection: Could not contact actuator. Is it running?")
                #print(e)
                return E_UNKNOWN_CCE
            finally:
                #cancel the schedule
                cancel_task_schdl(self, task_id)
        else:
            _log.debug('schedule NOT available')
        return E_UNKNOWN_CCE
        
    def _rpcget_zone_tsp(self):
        try:
            rm_tsp = self.vip.rpc.call('platform.actuator'
                                        , 'get_point'
                                        , 'iiit/cbs/zonecontroller/RM_TSP'
                                        ).get(timeout=10)
            return rm_tsp
        except gevent.Timeout:
            _log.exception("Expection: gevent.Timeout in _rpcget_zone_tsp()")
            return E_UNKNOWN_TSP
        except Exception as e:
            _log.exception ("Expection: Could not contact actuator. Is it running?")
            #print(e)
            return E_UNKNOWN_TSP
        return E_UNKNOWN_TSP
        
    def _rpcget_zone_lsp(self):
        try:
            rm_lsp = self.vip.rpc.call('platform.actuator'
                                        , 'get_point'
                                        , 'iiit/cbs/zonecontroller/RM_LSP'
                                        ).get(timeout=10)
            return rm_lsp
        except gevent.Timeout:
            _log.exception("Expection: gevent.Timeout in _rpcget_zone_lsp()")
            return E_UNKNOWN_LSP
        except Exception as e:
            _log.exception ("Expection: Could not contact actuator. Is it running?")
            #print(e)
            return E_UNKNOWN_LSP
        return E_UNKNOWN_LSP

    def _publish_zone_tsp(self, tsp):
        #_log.debug('_publish_zone_tsp()')
        pubTopic = self.root_topic+"/rm_tsp"
        pubMsg = [tsp, {'units': 'celcius', 'tz': 'UTC', 'type': 'float'}]
        publish_to_bus(self, pubTopic, pubMsg)
        return
        
    def _publish_zone_lsp(self, lsp):
        #_log.debug('_publish_zone_lsp()')
        pubTopic = self.root_topic+"/rm_lsp"
        pubMsg = [lsp, {'units': '%', 'tz': 'UTC', 'type': 'float'}]
        publish_to_bus(self, pubTopic, pubMsg)
        return
        
    #perodic function to publish active power
    def publish_opt_tap(self):
        #compute total active power and publish to local/energydemand
        #(vb RPCs this value to the next level)
        opt_tap = self._calc_total_act_pwr()
        
        #create a MessageType.active_power ISPACE_Msg
        pp_msg = tap_helper(self._opt_pp_msg_current
                            , self._device_id
                            , self._discovery_address
                            , opt_tap
                            , self._period_read_data
                            )
        _log. info('[LOG] Total Active Power(TAP) opt'
                                    + ' for us opt pp_msg({})'.format(pp_msg.get_price_id())
                                    + ': {:0.4f}'.format(opt_tap))
        #publish the new price point to the local message bus
        _log.debug('post to the local-bus...')
        pub_topic = self._topic_energy_demand
        pub_msg = pp_msg.get_json_message(self._agent_id, 'bus_topic')
        _log.debug('local bus topic: {}'.format(pub_topic))
        _log. info('[LOG] Total Active Power(TAP) opt, Msg: {}'.format(pub_msg))
        publish_to_bus(self, pub_topic, pub_msg)
        return
        
    #calculate total active power (tap)
    def _calc_total_act_pwr(self):
        #_log.debug('_calc_total_act_pwr()')
        tap = 0
        #zone lighting + ac
        cooling_ap = self._rpcget_zone_cooling_power()
        lighting_ap = self._rpcget_zone_lighting_power() 
        tap += (0 if cooling_ap == E_UNKNOWN_CCE else cooling_ap)
        tap += (0 if lighting_ap == E_UNKNOWN_CLE else lighting_ap)
        return tap
        
    def process_bid_pp(self):
        self.publish_bid_ted()
        return
        
    def publish_bid_ted(self):
        #compute total bid energy demand and publish to local/energydemand
        #(vb RPCs this value to the next level)
        bid_ted = self._calc_total_energy_demand()
        #create a MessageType.energy ISPACE_Msg
        pp_msg = ted_helper(self._bid_pp_msg_latest
                            , self._device_id
                            , self._discovery_address
                            , bid_ted
                            , self._period_read_data
                            )
        _log. info('[LOG] Total Energy Demand(TED) bid'
                                    + ' for us bid pp_msg({})'.format(pp_msg.get_price_id())
                                    + ': {:0.4f}'.format(bid_ted))
        #publish the new price point to the local message bus
        _log.debug('post to the local-bus...')
        pub_topic = self._topic_energy_demand
        pub_msg = pp_msg.get_json_message(self._agent_id, 'bus_topic')
        _log.debug('local bus topic: {}'.format(pub_topic))
        _log. info('[LOG] Total Energy Demand(TED) bid, Msg: {}'.format(pub_msg))
        publish_to_bus(self, pub_topic, pub_msg)
        _log.debug('Done!!!')
        return
        
    #calculate the local total energy demand for bid_pp
    #the bid energy is for self._bid_pp_duration (default 1hr)
    #and this msg is valid for self._period_read_data (ttl - default 30s)
    def _calc_total_energy_demand(self):
        #_log.debug('_calc_total_energy_demand()')
        #TODO: Sam
        #get actual tsp from energy functions
        ted = 0
        tsp = self._zone_tsp
        if isclose(tsp, 22.0, EPSILON):
            ted = 6500
        elif isclose(tsp, 23.0, EPSILON):
            ted = 6000
        elif isclose(tsp, 24.0, EPSILON):
            ted = 5500
        elif isclose(tsp, 25.0, EPSILON):
            ted = 5000
        elif isclose(tsp, 26.0, EPSILON):
            ted = 4500
        elif isclose(tsp, 27.0, EPSILON):
            ted = 4000
        elif isclose(tsp, 28.0, EPSILON):
            ted = 2000
        elif isclose(tsp, 29.0, EPSILON):
            ted = 1000
        else :
            ted = 500
        return ted
        
        
def main(argv=sys.argv):
    '''Main method called by the eggsecutable.'''
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
        
        
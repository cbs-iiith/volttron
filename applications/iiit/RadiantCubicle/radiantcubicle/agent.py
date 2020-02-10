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

import ispace_utils

utils.setup_logging()
_log = logging.getLogger(__name__)
__version__ = '0.4'

# checking if a floating point value is “numerically zero” by checking if it is lower than epsilon
EPSILON = 1e-04

SCHEDULE_AVLB = 1
SCHEDULE_NOT_AVLB = 0

E_UNKNOWN_STATE = -2
E_UNKNOWN_LEVEL = -3
E_UNKNOWN_CCE = -4

RC_AUTO_CNTRL_ON = 1
RC_AUTO_CNTRL_OFF = 0

def radiantcubicle(config_path, **kwargs):
    config = utils.load_config(config_path)
    vip_identity = config.get('vip_identity', 'iiit.radiantcubicle')
    # This agent needs to be named iiit.radiantcubicle. Pop the uuid id off the kwargs
    kwargs.pop('identity', None)
    
    Agent.__name__ = 'RadiantCubicle_Agent'
    return RadiantCubicle(config_path, identity=vip_identity, **kwargs)
    
class RadiantCubicle(Agent):
    '''Radiant Cubicle
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
    
    _rcAutoCntrlState = RC_AUTO_CNTRL_OFF
    _rcTspLevel = 25
    
    def __init__(self, config_path, **kwargs):
        super(RadiantCubicle, self).__init__(**kwargs)
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
        _log.info('Starting RadiantCubicle...')
        
        # we need to retain the device_id, retrive_details_from_vb() overwrite with vb device_id
        _device_id = self._device_id
        # retrive self._device_id and self._discovery_address from vb
        retrive_details_from_vb(self, 5)
        self._device_id = _device_id
        
        # register rpc routes with MASTER_WEB
        # register_rpc_route is a blocking call
        register_rpc_route(self, 'smarthub', 'rpc_from_net', 5)
        
        # register this agent with vb as local device for posting active power & bid energy demand
        # pca picks up the active power & energy demand bids only if registered with vb
        # require self._vb_vip_identity, self.core.identity, self._device_id
        # register_agent_with_vb is a blocking call
        register_agent_with_vb(self, 5)
        
        self._valid_senders_list_pp = ['iiit.pricecontroller']
        
        # any process that failed to apply pp sets this flag False
        # setting False here to initiate applying default pp on agent start
        self._process_opt_pp_success = False
        
        # on successful process of apply_pricing_policy with the latest opt pp, current = latest
        self._opt_pp_msg_current = get_default_pp_msg(self._discovery_address, self._device_id)
        # latest opt pp msg received on the message bus
        self._opt_pp_msg_latest = get_default_pp_msg(self._discovery_address, self._device_id)
        
        self._bid_pp_msg_latest = get_default_pp_msg(self._discovery_address, self._device_id)
        
        self._run_radiant_cubicle_test()
        
        # TODO: get the latest values (states/levels) from h/w
        # self.getInitialHwState()
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
        
        _log.debug('switch ON RC_AUTO_CNTRL')
        self.setRcAutoCntrl(RC_AUTO_CNTRL_ON)
        
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
            _log.debug('rpc_from_net()...'
                        + 'header: {}'.format(header)
                        + ', rpc method: {}'.format(rpcdata.method)
                        + ', rpc params: {}'.format(rpcdata.params)
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
        
    def _config_get_init_values(self):
        self._period_read_data = self.config.get('period_read_data', 30)
        self._period_process_pp = self.config.get('period_process_pp', 10)
        self._price_point_old = self.config.get('price_point_latest', 0.2)
        self._deviceId = self.config.get('deviceId', 'RadiantCubicle-61')
        return
        
    def _config_get_points(self):
        self.root_topic = self.config.get('topic_root', 'radiantcubicle')
        self.energyDemand_topic = self.config.get('topic_energy_demand',
                                                    'radiantcubicle/energydemand')
        self.topic_price_point = self.config.get('topic_price_point',
                                                    'topic_price_point')
        return
        
    def _config_get_price_fucntions(self):
        _log.debug('_config_get_price_fucntions()')
        self.pf_rc = self.config.get('pf_rc')
        return
        
    def _run_radiant_cubicle_test(self):
        _log.debug('Running: _run_radiant_cubicle_test()...')
        
        _log.debug('change level 26')
        self._rcpset_rc_tsp(26.0)
        time.sleep(1)
        
        _log.debug('change level 27')
        self._rcpset_rc_tsp(27.0)
        time.sleep(1)
        
        _log.debug('change level 28')
        self._rcpset_rc_tsp(28.0)
        time.sleep(1)
        
        _log.debug('change level 29')
        self._rcpset_rc_tsp(29.0)
        time.sleep(1)
        
        _log.debug('switch ON RC_AUTO_CNTRL')
        self.setRcAutoCntrl(RC_AUTO_CNTRL_ON)
        time.sleep(1)
        
        _log.debug('switch OFF RC_AUTO_CNTRL')
        self.setRcAutoCntrl(RC_AUTO_CNTRL_OFF)
        time.sleep(1)
        
        _log.debug('EOF Testing')
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
        ispace_utils.print_pp(self, new_pp
                , new_pp_datatype
                , new_pp_id
                , new_pp_isoptimal
                , discovery_address
                , deviceId
                , new_pp_ttl
                , new_pp_ts
                )
                
        if not new_pp_isoptimal:
            _log.debug('not optimal pp!!!, do nothing')
            return
            
        self._price_point_latest = new_pp
        self._pp_id_latest = new_pp_id
        self.process_opt_pp()
        return
        
    # this is a perodic function that keeps trying to apply the new pp till success
    def process_opt_pp(self):
        if ispace_utils.isclose(self._price_point_old, self._price_point_latest, EPSILON) and self._pp_id == self._pp_id_new:
            return
            
        self._pp_failed = False     # any process that failed to apply pp sets this flag True
        self._apply_pricing_policy()
        
        if self._pp_failed:
            _log.debug('unable to process_opt_pp(), will try again in ' + str(self._period_process_pp))
            return
            
        _log.info('New Price Point processed.')
        self._price_point_old = self._price_point_latest
        self._pp_id = self._pp_id_new
        return
        
    def _apply_pricing_policy(self):
        _log.debug('_apply_pricing_policy()')
        tsp = self._compute_rc_new_tsp(self._price_point_latest)
        _log.debug('New Setpoint: {:0.1f}'.format( tsp))
        self._rcpset_rc_tsp(tsp)
        if not ispace_utils.isclose(tsp, self._rcTspLevel, EPSILON):
            self._pp_failed = True
        return
        
    # compute new TSP from price functions
    def _compute_rc_new_tsp(self, pp):
        pp = 0 if pp < 0 else 1 if pp > 1 else pp
        
        pf_idx = self.pf_rc['pf_idx']
        pf_roundup = self.pf_rc['pf_roundup']
        pf_coefficients = self.pf_rc['pf_coefficients']
        
        a = pf_coefficients[pf_idx]['a']
        b = pf_coefficients[pf_idx]['b']
        c = pf_coefficients[pf_idx]['c']
        
        tsp = a*pp**2 + b*pp + c
        return ispace_utils.mround(tsp, pf_roundup)
        
    # change rc surface temperature set point
    def _rcpset_rc_tsp(self, level):
        # _log.debug('_rcpset_rc_tsp()')
        
        if ispace_utils.isclose(level, self._rcTspLevel, EPSILON):
            _log.debug('same level, do nothing')
            return
            
        task_id = str(randint(0, 99999999))
        result = ispace_utils.get_task_schdl(self, task_id,'iiit/cbs/radiantcubicle')
        if result['result'] == 'SUCCESS':
            try:
                result = self.vip.rpc.call('platform.actuator'
                                            , 'set_point'
                                            , self._agent_id
                                            , 'iiit/cbs/radiantcubicle/RC_TSP'
                                            , level
                                            ).get(timeout=10)
                self.updateRcTspLevel(level)
            except gevent.Timeout:
                _log.exception('gevent.Timeout in _rcpset_rc_tsp()')
            except Exception as e:
                _log.exception('changing device level')
                print(e)
            finally:
                # cancel the schedule
                ispace_utils.cancel_task_schdl(self, task_id)
        else:
            _log.debug('schedule NOT available')
        return
        
    def setRcAutoCntrl(self, state):
        _log.debug('setRcAutoCntrl()')
        
        if self._rcAutoCntrlState == state:
            _log.info('same state, do nothing')
            return
            
        # get schedule to setRcAutoCntrl
        task_id = str(randint(0, 99999999))
        # _log.debug('task_id: ' + task_id)
        result = ispace_utils.get_task_schdl(self, task_id,'iiit/cbs/radiantcubicle')
        
        if result['result'] == 'SUCCESS':
            result = {}
            try:
                # _log.debug('schl avlb')
                result = self.vip.rpc.call('platform.actuator'
                                            , 'set_point'
                                            , self._agent_id,
                                            , 'iiit/cbs/radiantcubicle/RC_AUTO_CNTRL'
                                            , state
                                            ).get(timeout=10)
                        
                self.updateRcAutoCntrl(state)
            except gevent.Timeout:
                _log.exception('gevent.Timeout in setRcAutoCntrl()')
            except Exception as e:
                _log.exception('setting RC_AUTO_CNTRL')
                print(e)
            finally:
                # cancel the schedule
                ispace_utils.cancel_task_schdl(self, task_id)
        else:
            _log.debug('schedule NOT available')
        return
        
    def updateRcTspLevel(self, level):
        # _log.debug('_updateShDeviceLevel()')
        _log.debug('level {:0.1f}'.format( level))
        
        device_level = self.rpc_getRcTspLevel()
        
        # check if the level really updated at the h/w, only then proceed with new level
        if ispace_utils.isclose(level, device_level, EPSILON):
            self._rcTspLevel = level
            self.publishRcTspLevel(level)
            
        _log.debug('Current level: ' + '{:0.1f}'.format( device_level))
        return
        
    def updateRcAutoCntrl(self, state):
        _log.debug('updateRcAutoCntrl()')
        
        rcAutoCntrlState = self.rpc_getRcAutoCntrlState()
        
        if state == int(rcAutoCntrlState):
            self._rcAutoCntrlState = state
            self.publishRcAutoCntrlState(state)
            
        if self._rcAutoCntrlState == RC_AUTO_CNTRL_ON:
            _log.info('Current State: RC Auto Cntrl is ON!!!')
        else:
            _log.info('Current State: RC Auto Cntrl OFF!!!')
            
        return
        
    def rpc_getRcCalcCoolingEnergy(self):
        task_id = str(randint(0, 99999999))
        result = ispace_utils.get_task_schdl(self, task_id,'iiit/cbs/radiantcubicle')
        if result['result'] == 'SUCCESS':
            try:
                coolingEnergy = self.vip.rpc.call('platform.actuator'
                                                    ,'get_point'
                                                    , 'iiit/cbs/radiantcubicle/RC_CCE_ELEC'
                                                    ).get(timeout=10)
                return coolingEnergy
            except gevent.Timeout:
                _log.exception('gevent.Timeout in rpc_getRcCalcCoolingEnergy()')
                return E_UNKNOWN_CCE
            except Exception as e:
                _log.exception('Could not contact actuator. Is it running?')
                print(e)
                return E_UNKNOWN_CCE
            finally:
                # cancel the schedule
                ispace_utils.cancel_task_schdl(self, task_id)
        else:
            _log.debug('schedule NOT available')
        return E_UNKNOWN_CCE
        
    def rpc_getRcTspLevel(self):
        try:
            device_level = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/radiantcubicle/RC_TSP').get(timeout=10)
            return device_level
        except gevent.Timeout:
            _log.exception('gevent.Timeout in rpc_getShDeviceLevel()')
            return E_UNKNOWN_LEVEL
        except Exception as e:
            _log.exception('Could not contact actuator. Is it running?')
            print(e)
            return E_UNKNOWN_LEVEL
        return E_UNKNOWN_LEVEL
        
    def rpc_getRcAutoCntrlState(self):
        try:
            state = self.vip.rpc.call('platform.actuator'
                                        ,'get_point'
                                        , 'iiit/cbs/radiantcubicle/RC_AUTO_CNTRL'
                                        ).get(timeout=10)
            return state
        except gevent.Timeout:
            _log.exception('gevent.Timeout in rpc_getShDeviceLevel()')
            return E_UNKNOWN_STATE
        except Exception as e:
            _log.exception('Could not contact actuator. Is it running?')
            print(e)
            return E_UNKNOWN_STATE
        return E_UNKNOWN_STATE
        
    def publishRcTspLevel(self, level):
        # _log.debug('publishRcTspLevel()')
        pubTopic = self.root_topic+'/rc_tsp_level'
        pubMsg = [level, {'units': 'celcius', 'tz': 'UTC', 'type': 'float'}]
        ispace_utils.publish_to_bus(self, pubTopic, pubMsg)
        return
        
    def publishRcAutoCntrlState(self, state):
        pubTopic = self.root_topic+'/rc_auto_cntrl_state'
        pubMsg = [state, {'units': 'On/Off', 'tz': 'UTC', 'type': 'int'}]
        ispace_utils.publish_to_bus(self, pubTopic, pubMsg)
        return
        
    def publish_ted(self):
        self._ted = self.rpc_getRcCalcCoolingEnergy()
        _log.info( 'New TED: {:.4f}, publishing to bus.'.format(self._ted))
        pubTopic = self.energyDemand_topic + '/' + self._deviceId
        # _log.debug('TED pubTopic: ' + pubTopic)
        pubMsg = [self._ted
                    , {'units': 'W', 'tz': 'UTC', 'type': 'float'}
                    , self._pp_id
                    , True
                    , None
                    , self._deviceId
                    , None
                    , self._period_read_data
                    , datetime.datetime.utcnow().isoformat(' ') + 'Z'
                    ]
        ispace_utils.publish_to_bus(self, pubTopic, pubMsg)
        return
        
def main(argv=sys.argv):
    '''Main method called by the eggsecutable.'''
    try:
        utils.vip_main(radiantcubicle)
    except Exception as e:
        print (e)
        _log.exception('unhandled exception')
        
if __name__ == '__main__':
    # Entry point for script
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        pass
        
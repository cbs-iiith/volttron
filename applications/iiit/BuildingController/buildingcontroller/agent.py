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

from random import randint

import settings
import time
import struct
import gevent
import gevent.event

from ispace_utils import isclose, get_task_schdl, cancel_task_schdl, publish_to_bus
from ispace_msg import parse_jsonrpc_msg

utils.setup_logging()
_log = logging.getLogger(__name__)
__version__ = '0.4'

#checking if a floating point value is “numerically zero” by checking if it is lower than epsilon
EPSILON = 1e-03

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
    def __init__(self, config_path, **kwargs):
        super(BuildingController, self).__init__(**kwargs)
        _log.debug("vip_identity: " + self.core.identity)
        
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
        _log.debug('startup()')
        
        self._valid_senders_list_pp = ['iiit.pricecontroller']
        
        #any process that failed to apply pp sets this flag False
        self._process_opt_pp_success = False
        
        self._ds_tap
        self._total_act_pwr
        
        #on successful process of apply_pricing_policy with the latest opt pp, current = latest
        self._opt_pp_msg_current = None
        #latest opt pp msg received on the message bus
        self._opt_pp_msg_latest = None
        
        self._price_point_current = 0.4 
        self._price_point_latest = 0.45
        
        self._opt_pp_id = randint(0, 99999999)
        self._bid_pp_id = randint(0, 99999999)
        
        #reset to zero on receiving new opt_pp_msg
        self._total_act_pwr = -1
        self._ds_total_act_pwr[:] = []
        

        
        #downstream energy demand and deviceId
        self._ds_ed = []
        self._ds_deviceId = []
        
        #building total energy demand (including downstream)
        self._ted = 0
        
        _log.info("yeild 30s for volttron platform to initiate properly...")
        time.sleep(30) #yeild for a movement
        _log.info("Starting BuildingController...")
        
        self._run_bms_test()
        
        #TODO: get the latest values (states/levels) from h/w
        #self.getInitialHwState()
        #time.sleep(1) #yeild for a movement
        
        #TODO: apply pricing policy for default values
        
        #TODO: publish initial data to volttron bus
        
        #perodically publish total active power to volttron bus
        #active power is comupted are regurlar interval (_period_process_pp default(30s))
        #this power corresponds to current opt pp
        #tap --> total active power (Wh)
        self.core.periodic(self._period_read_data, self.publish_tap, wait=None)
        
        #perodically process new pricing point that keeps trying to apply the new pp till success
        self.core.periodic(self._period_process_pp, self.process_opt_pp, wait=None)
        
        #subscribing to topic_price_point
        self.vip.pubsub.subscribe("pubsub", self.topic_price_point, self.on_new_price)
        
        #subscribing to ds energy demand, vb publishes ed from registered ds to this topic
        self.vip.pubsub.subscribe("pubsub", self.topic_energy_demand_ds, self.on_ds_ed)
        
        self.vip.rpc.call(MASTER_WEB, 'register_agent_route'
                            , r'^/BuildingController'
                            , "rpc_from_net"
                            ).get(timeout=10)
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
        
    def _config_get_init_values(self):
        self._period_read_data = self.config.get('period_read_data', 30)
        self._period_process_pp = self.config.get('period_process_pp', 10)
        self._price_point_current = self.config.get('default_base_price', 0.1)
        self._price_point_latest = self.config.get('price_point_latest', 0.2)
        return
        
    def _config_get_points(self):
        self.vb_vip_identity = self.config.get('vb_vip_identity',
                                                'volttronbridgeagent-0.3_1')
        self.root_topic = self.config.get('topic_root', 'building')
        self.topic_energy_demand = self.config.get('topic_energy_demand',
                                                    'building/energydemand')
        self.topic_price_point = self.config.get('topic_price_point',
                                                    'building/pricepoint')
        self.topic_energy_demand_ds = self.config.get('topic_energy_demand_ds',
                                                        'ds/energydemand')
        return
        
    def _run_bms_test(self):
        _log.debug("Running: _runBMS Commu Test()...")
        _log.debug('change pp .10')
        self.publish_price_to_bms(0.10)
        time.sleep(10)
        
        _log.debug('change pp .75')
        self.publish_price_to_bms(0.75)
        time.sleep(10)
        
        _log.debug('change pp .25')
        self.publish_price_to_bms(0.25)
        time.sleep(10)
        
        _log.debug("EOF Testing")
        return
        
    def on_new_price(self, peer, sender, bus,  topic, headers, message):
        self.tmp_pp_msg = None
        valid_senders_list = self._valid_senders_list_pp
        if not self._validate_msg(sender, valid_senders_list, message):
            #cleanup and return
            self.tmp_pp_msg = None
            return
        pp_msg = self.tmp_pp_msg
        self.tmp_pp_msg = None      #release self.tmp_pp_msg
        
        if pp_msg.get_isoptimal():
            _log.debug('optimal pp!!!')
            self._process_opt_pp(pp_msg)
        else:
            _log.debug('not optimal pp!!!')
            self._process_bid_pp(pp_msg)
        return
            
        return
        
    def _validate_msg(self, sender, valid_senders_list, message):
        _log.debug('_validate_msg()')
        if self.agent_disabled:
            _log.info("self.agent_disabled: " + str(self.agent_disabled) + ", do nothing!!!")
            return False
            
        if sender not in valid_senders_list:
            _log.debug('sender: {}'.format(sender)
                        + ' not in sender list: {}, do nothing!!!'.format(valid_senders_list))
            return False
            
        try:
            _log.debug('message: {}'.format(message))
            mandatory_fields = ['value', 'value_data_type', 'units', 'price_id']
            self.tmp_pp_msg = parse_bustopic_msg(message, mandatory_fields)
            #_log.info('self.tmp_pp_msg: {}'.format(self.tmp_pp_msg))
        except KeyError as ke:
            _log.exception(ke)
            _log.exception(jsonrpc.json_error('NA', INVALID_PARAMS,
                    'Invalid params {}'.format(rpcdata.params)))
            return False
        except Exception as e:
            _log.exception(e)
            _log.exception(jsonrpc.json_error('NA', UNHANDLED_EXCEPTION, e))
            return False
            
        hint = 'New Price Point'
        mandatory_fields = ['value', 'value_data_type', 'units', 'price_id', 'isoptimal', 'duration', 'ttl']
        valid_price_ids = []
        #validate various sanity measure like, valid fields, valid pp ids, ttl expiry, etc.,
        if not self.tmp_pp_msg.sanity_check_ok(hint, mandatory_fields, valid_price_ids):
            _log.warning('Msg sanity checks failed!!!')
            return False
            
        return True
        
    def _process_opt_pp(self, pp_msg):
        self._opt_pp_msg_latest = pp_msg
        
        self._process_opt_pp_success = False    #any process that failed to apply pp sets this flag False
        self._total_act_pwr = -1                #reset total active pwr to zero on new opt_pp
        self._ds_total_act_pwr[:] = []          #
        self.process_opt_pp()                   #initiate the periodic process
        return
        
    def _process_bid_pp(self, pp_msg):
        self._bid_pp_msg_new = pp_msg
        
        self._bid_ed = -1        #reset bid_ed to zero on new bid_pp
        self._ds_bid_ed[:] = []
        self.process_bid_pp()   #initiate the periodic process
        return

    #this is a perodic function that keeps trying to apply the new pp till success
    def process_opt_pp(self):
        if self._process_opt_pp_success:
            #_log.debug('all apply opt pp processess success, do nothing')
            return
            
        self.publish_price_to_bms()
        if not self._process_opt_pp_success:
            self._apply_pricing_policy()
            
        if self._process_opt_pp_success:
            _log.debug("unable to process_opt_pp(), will try again in " + str(self._period_process_pp))
            return
            
        _log.info("New Price Point processed.")
        #on successful process of apply_pricing_policy with the latest opt pp, current = latest
        self._opt_pp_msg_current = self._opt_pp_msg_latest
        return
        
    def _apply_pricing_policy(self):
        _log.debug("_apply_pricing_policy()")
        #TODO: control the energy demand of devices at building level accordingly
        #      use self._opt_pp_msg_latest
        #      if applying self._price_point_latest failed, set self._process_opt_pp_success = False
        return
        
    # Publish new price to bms (for logging (o)r for further processing by the BMS)
    def publish_price_to_bms(self):
        _log.debug('publish_price_to_bms()')
        task_id = str(randint(0, 99999999))
        result = ispace_utils.get_task_schdl(self, task_id,'iiit/cbs/buildingcontroller')
        if result['result'] == 'SUCCESS':
            try:
                result = self.vip.rpc.call('platform.actuator'
                                            , 'set_point'
                                            , self._agent_id
                                            , 'iiit/cbs/buildingcontroller/Building_PricePoint'
                                            , self._opt_pp_msg_latest.get_value()
                                            ).get(timeout=10)
                self.update_building_pp()
            except gevent.Timeout:
                _log.exception("Expection: gevent.Timeout in publish_price_to_bms()")
            except Exception as e:
                _log.exception ("Expection: changing device level")
                print(e)
            finally:
                #cancel the schedule
                ispace_utils.cancel_task_schdl(self, task_id)
        else:
            _log.debug('schedule NOT available')
        return
        
    def update_building_pp(self):
        #_log.debug('updateRmTsp()')
        
        building_pp = self.rpc_get_building_pp()
        latest_pp = self._opt_pp_msg_latest.get_value()
        _log.debug('latest_pp: {0:0.2f}, building_pp {1:0.2f}'.format(latest_pp, building_pp))
        
        #check if the pp really updated at the bms, only then proceed with new pp
        if ispace_utils.isclose(latest_pp, building_pp, EPSILON):
            self.publish_building_pp()
        else:
            self._process_opt_pp_success = False
            
        return
        
    def publish_building_pp(self):
        #_log.debug('publish_building_pp()')
        pp_msg = self._opt_pp_msg_latest
        
        pub_topic =  self.root_topic+"/Building_PricePoint"
        pub_msg = pp_msg.get_json_params(self._agent_id)
        _log.debug('publishing to local bus topic: {}'.format(pub_topic))
        _log.debug('Msg: {}'.format(pub_msg))
        publish_to_bus(self, pub_topic, pub_msg)
        return
        
    def rpc_get_building_pp(self):
        try:
            pp = self.vip.rpc.call('platform.actuator'
                                    ,'get_point'
                                    , 'iiit/cbs/buildingcontroller/Building_PricePoint'
                                    ).get(timeout=10)
            return pp
        except gevent.Timeout:
            _log.exception("Expection: gevent.Timeout in rpc_get_building_pp()")
            return E_UNKNOWN_BPP
        except Exception as e:
            _log.exception ("Expection: Could not contact actuator. Is it running?")
            print(e)
            return E_UNKNOWN_BPP
        return E_UNKNOWN_BPP
        
    def rpc_get_building_level_energy(self):
        #compute the energy of the other devices which are at building level
        return 0
        
    #calculate total active power (tap), ap --> active power
    def _calc_tap(self):
        #_log.debug('_calc_tap()')
        tap = self.rpc_get_building_level_energy()
        for ap in self._ds_tap:
            tap = tap + ap
        return ted
        
    def publish_tap(self):
        self._total_act_pwr = self._calc_tap()
        _log.info( "New Total Active Pwr: {0:.4f}, publishing to bus.".format(self._total_act_pwr))
        
        pp_msg = self._opt_pp_msg_latest
        
        msg_type = MessageType.energy
        one_to_one = pp_msg.get_one_to_one()
        isoptimal = pp_msg.get_isoptimal()
        value = self._total_act_pwr
        value_data_type = 'float'
        units = 'Wh'
        price_id = pp_msg.get_price_id()
        src_ip = pp_msg.get_dst_ip()
        src_device_id = pp_msg.get_dst_device_id()
        dst_ip = pp_msg.get_src_ip()
        dst_device_id = pp_msg.get_src_device_id()
        duration = self.act_pp_msg.get_duration()
        ttl = 10
        ts = datetime.datetime.utcnow().isoformat(' ') + 'Z'
        tz = 'UTC'
        
        tap_msg = ISPACE_Msg(msg_type, one_to_one
                            , isoptimal, value, value_data_type, units, price_id
                            , src_ip, src_device_id, dst_ip, dst_device_id
                            , duration, ttl, ts, tz)
                            
        pub_topic =  self.topic_energy_demand
        pub_msg = tap_msg.get_json_params(self._agent_id)
        _log.debug('publishing to local bus topic: {}'.format(pub_topic))
        _log.debug('Msg: {}'.format(pub_msg))
        publish_to_bus(self, pub_topic, pub_msg)
        return
        
    def on_ds_ed(self, peer, sender, bus,  topic, headers, message):
        #post ed to us only if pp_id corresponds to these ids (i.e., ed for either us opt_pp_id or bid_pp_id)
        valid_pp_ids = [self.self._pp_id, self._bid_pp_id]

        
        _log.debug('New ed from ds, topic: ' + topic +
                    ' & ed: {0:.4f}'.format(message[ParamED.idx_ed]))
                    
        ed_pp_id = message[ParamED.idx_ed_pp_id]
        ed_isoptimal = message[ParamED.idx_ed_isoptimal]
        if not ed_isoptimal:         #only accumulate the ed of an optimal pp
            _log.debug(" - Not optimal ed!!!, do nothing")
            return
            
        #deviceID = (topic.split('/', 3))[2]
        deviceID = message[ParamED.idx_ed_device_id]
        idx = self._get_ds_device_idx(deviceID)
        self._ds_ed[idx] = message[ParamED.idx_ed]
        return
        
    def _get_ds_device_idx(self, deviceID):   
        if deviceID not in self._ds_deviceId:
            self._ds_deviceId.append(deviceID)
            idx = self._ds_deviceId.index(deviceID)
            self._ds_ed.insert(idx, 0.0)
        return self._ds_deviceId.index(deviceID)
        
        
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
        
        
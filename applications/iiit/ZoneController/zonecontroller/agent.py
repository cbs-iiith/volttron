# -*- coding: utf-8 -*- {{{
# vim: set fenc=utf-8 ft=python sw=4 ts=4 sts=4 et:
#
# Copyright (c) 2019, Sam Babu, Godithi.
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

from random import randint

import settings

import time
import struct
import gevent
import gevent.event

from ispace_utils import mround, publish_to_bus, get_task_schdl, cancel_task_schdl, isclose

utils.setup_logging()
_log = logging.getLogger(__name__)
__version__ = '0.2'

SCHEDULE_AVLB = 1
SCHEDULE_NOT_AVLB = 0

E_UNKNOWN_CCE = -4
E_UNKNOWN_TSP = -5
E_UNKNOWN_LSP = -6

def DatetimeFromValue(ts):
    ''' Utility for dealing with time
    '''
    if isinstance(ts, (int, long)):
        return datetime.utcfromtimestamp(ts)
    elif isinstance(ts, float):
        return datetime.utcfromtimestamp(ts)
    elif not isinstance(ts, datetime):
        raise ValueError('Unknown timestamp value')
    return ts

class ZoneController(Agent):
    '''Zone Controller
    '''
    _price_point_previous = 0.4 
    _price_point_current = 0.4 
    _price_point_new = 0.45

    _rmTsp = 25
    _rmLsp = 100
    
    #downstream energy demand and deviceId
    _ds_ed = []
    _ds_deviceId = []
    
    #zone total energy demand (including downstream PECS)
    _ted = 0

    def __init__(self, config_path, **kwargs):
        super(ZoneController, self).__init__(**kwargs)
        _log.debug("vip_identity: " + self.core.identity)

        self.config = utils.load_config(config_path)
        self._configGetPoints()
        self._configGetInitValues()
        self._configGetPriceFucntions()
        return

    @Core.receiver('onsetup')
    def setup(self, sender, **kwargs):
        _log.info(self.config['message'])
        self._agent_id = self.config['agentid']
        return

    @Core.receiver('onstart')
    def startup(self, sender, **kwargs):
        _log.info("yeild 30s for volttron platform to initiate properly...")
        time.sleep(30) #yeild for a movement
        _log.info("Starting ZoneController...")

        self._runBMSTest()
        
        #perodically publish total energy demand to volttron bus
        self.core.periodic(self._period_read_data, self.publishTed, wait=None)
        
        #perodically process new pricing point
        self.core.periodic(10, self.processNewPricePoint, wait=None)
        
        #subscribing to topic_price_point
        self.vip.pubsub.subscribe("pubsub", self.topic_price_point, self.onNewPrice)
        
        #subscribing to ds energy demand, vb publishes ed from registered ds to this topic
        self.vip.pubsub.subscribe("pubsub", self.energyDemand_topic_ds, self.onDsEd)
        
        self.vip.rpc.call(MASTER_WEB, 'register_agent_route',
                      r'^/ZoneController',
                      "rpc_from_net").get(timeout=10)
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

    def _configGetInitValues(self):
        self._period_read_data = self.config['period_read_data']
        self._price_point_previous = self.config['default_base_price']
        self._price_point_current = self.config['default_base_price']
        return
        
    def _configGetPoints(self):
        self.root_topic              = self.config.get('topic_root', 'zone')
        self.energyDemand_topic     = self.config.get('topic_energy_demand', \
                                            'zone/energydemand')
        self.topic_price_point      = self.config.get('topic_price_point', \
                                            'zone/pricepoint')
        self.energyDemand_topic_ds  = self.config.get('topic_energy_demand_ds', \
                                            'ds/energydemand')
        return
        
    def _configGetPriceFucntions(self):
        _log.debug("_configGetPriceFucntions()")
        
        self.pf_zn_ac  = self.config.get('pf_zn_ac')
        self.pf_zn_light  = self.config.get('pf_zn_light')
        
        return
        
    def _runBMSTest(self):
        _log.debug("Running : _runBMS Commu Test()...")
        
        _log.debug('change tsp 26')
        self.setRmTsp(26.0)
        time.sleep(10)
        
        _log.debug('change tsp 27')
        self.setRmTsp(27.0)
        time.sleep(10)
        
        _log.debug('change tsp 28')
        self.setRmTsp(28.0)
        time.sleep(10)
        
        _log.debug('change tsp 29')
        self.setRmTsp(29.0)
        time.sleep(10)
        
        _log.debug('change lsp 25')
        self.setRmLsp(25.0)
        time.sleep(10)
        
        _log.debug('change lsp 75')
        self.setRmLsp(75.0)
        time.sleep(10)
        
        _log.debug('change lsp 100')
        self.setRmLsp(100.0)
        time.sleep(10)

        _log.debug("EOF Testing")
        return
        
    def onNewPrice(self, peer, sender, bus,  topic, headers, message):
        if sender == 'pubsub.compat':
            message = compat.unpack_legacy_message(headers, message)

        new_price_point = message[0]
        _log.info ( "*** New Price Point: {0:.2f} ***".format(new_price_point))
        
        if isclose(self._price_point_current, new_price_point):
            _log.debug('no change in price, do nothing')
            return
        
        self._price_point_new = new_price_point
        self.processNewPricePoint()
        return
        
    def processNewPricePoint(self):
        if isclose(self._price_point_current, self._price_point_new):
            return
            
        #_log.info ( "*** New Price Point: {0:.2f} ***".format(self._price_point_new))
        self._price_point_previous = self._price_point_current
        self.applyPricingPolicy()
        self._price_point_current = self._price_point_new
        return

    def applyPricingPolicy(self):
        _log.debug("applyPricingPolicy()")
        
        #apply for ambient ac
        tsp = self.getNewTsp(self._price_point_new)
        _log.debug('New Ambient AC Setpoint: {0:0.1f}'.format( tsp))
        self.setRmTsp(tsp)
        
        #apply for ambient lightinh
        lsp = self.getNewLsp(self._price_point_new)
        _log.debug('New Ambient Lighting Setpoint: {0:0.1f}'.format( lsp))
        self.setRmLsp(lsp)
        
        return
        
    #compute new zone temperature setpoint from price functions
    def getNewTsp(self, pp):
        pp = 0 if pp < 0 else 1 if pp > 1 else pp
        
        pf_idx = self.pf_zn_ac['pf_idx']
        pf_roundup = self.pf_zn_ac['pf_roundup']
        pf_coefficients = self.pf_zn_ac['pf_coefficients']
        
        a = pf_coefficients[pf_idx]['a']
        b = pf_coefficients[pf_idx]['b']
        c = pf_coefficients[pf_idx]['c']
        
        tsp = a*pp**2 + b*pp + c
        return mround(tsp, pf_roundup)
        
    #compute new zone lighting setpoint from price functions
    def getNewLsp(self, pp):
        pp = 0 if pp < 0 else 1 if pp > 1 else pp
        
        pf_idx = self.pf_zn_light['pf_idx']
        pf_roundup = self.pf_zn_light['pf_roundup']
        pf_coefficients = self.pf_zn_light['pf_coefficients']
        
        a = pf_coefficients[pf_idx]['a']
        b = pf_coefficients[pf_idx]['b']
        c = pf_coefficients[pf_idx]['c']
        
        lsp = a*pp**2 + b*pp + c
        return mround(lsp, pf_roundup)
        
    # change ambient temperature set point
    def setRmTsp(self, tsp):
        #_log.debug('setRmTsp()')
        
        if isclose(tsp, self._rmTsp):
            _log.debug('same tsp, do nothing')
            return
            
        task_id = str(randint(0, 99999999))
        result = get_task_schdl(self, task_id,'iiit/cbs/zonecontroller')
        if result['result'] == 'SUCCESS':
            result = {}
            try:
                result = self.vip.rpc.call(
                    'platform.actuator', 
                    'set_point',
                    self._agent_id, 
                    'iiit/cbs/zonecontroller/RM_TSP',
                    tsp).get(timeout=10)
                self.updateRmTsp(tsp)
            except gevent.Timeout:
                _log.exception("Expection: gevent.Timeout in setRmTsp()")
            except Exception as e:
                _log.exception ("Expection: changing ambient tsp")
                print(e)
            finally:
                #cancel the schedule
                cancel_task_schdl(self, task_id)
        else:
            _log.debug('schedule NOT available')
        return
        
    # change ambient light set point
    def setRmLsp(self, lsp):
        #_log.debug('setRmLsp()')
        
        if isclose(lsp, self._rmLsp):
            _log.debug('same lsp, do nothing')
            return
            
        task_id = str(randint(0, 99999999))
        result = get_task_schdl(self, task_id,'iiit/cbs/zonecontroller')
        if result['result'] == 'SUCCESS':
            result = {}
            try:
                result = self.vip.rpc.call(
                    'platform.actuator', 
                    'set_point',
                    self._agent_id, 
                    'iiit/cbs/zonecontroller/RM_LSP',
                    lsp).get(timeout=10)
                self.updateRmLsp(lsp)
            except gevent.Timeout:
                _log.exception("Expection: gevent.Timeout in setRmLsp()")
            except Exception as e:
                _log.exception ("Expection: changing ambient lsp")
                print(e)
            finally:
                #cancel the schedule
                cancel_task_schdl(self, task_id)
        else:
            _log.debug('schedule NOT available')
        return

    def updateRmTsp(self, tsp):
        #_log.debug('updateRmTsp()')
        _log.debug('tsp {0:0.1f}'.format( tsp))
        
        rm_tsp = self.rpc_getRmTsp()
        
        #check if the tsp really updated at the bms, only then proceed with new tsp
        if isclose(tsp, rm_tsp):
            self._rmTsp = tsp
            self.publishRmTsp(tsp)
            
        _log.debug('Current TSP: ' + "{0:0.1f}".format( rm_tsp))
        return
        
    def updateRmLsp(self, lsp):
        #_log.debug('updateRmLsp()')
        _log.debug('lsp {0:0.1f}'.format( lsp))
        
        rm_lsp = self.rpc_getRmLsp()
        
        #check if the lsp really updated at the bms, only then proceed with new lsp
        if isclose(lsp, rm_lsp):
            self._rmLsp = lsp
            self.publishRmLsp(lsp)
            
        _log.debug('Current LSP: ' + "{0:0.1f}".format( rm_lsp))
        return

    #For given light setpoint(lsp), returns the lighting power in watts
    #refer to excel sheet "Philips CFL Power Chart.xlsx"
    def _get_rm_light_power(self, lsp):
        if lsp < 0:
            return 65
        elif lsp > 10:
            return 145
        else:
            return ((8 * lsp) + 65)
    
    def rpc_getRmCalcCoolingEnergy(self):
        task_id = str(randint(0, 99999999))
        result = get_task_schdl(self, task_id,'iiit/cbs/zonecontroller')
        if result['result'] == 'SUCCESS':
            try:
                coolingEnergy = self.vip.rpc.call(
                        'platform.actuator','get_point',
                        'iiit/cbs/zonecontroller/RM_CCE').get(timeout=10)
                return coolingEnergy
            except gevent.Timeout:
                _log.exception("Expection: gevent.Timeout in rpc_getRmCalcCoolingEnergy()")
                return E_UNKNOWN_CCE
            except Exception as e:
                _log.exception ("Expection: Could not contact actuator. Is it running?")
                print(e)
                return E_UNKNOWN_CCE
            finally:
                #cancel the schedule
                cancel_task_schdl(self, task_id)
        else:
            _log.debug('schedule NOT available')
        return E_UNKNOWN_CCE

    def rpc_getRmTsp(self):
        try:
            rm_tsp = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/zonecontroller/RM_TSP').get(timeout=10)
            return rm_tsp
        except gevent.Timeout:
            _log.exception("Expection: gevent.Timeout in rpc_getRmTsp()")
            return E_UNKNOWN_TSP
        except Exception as e:
            _log.exception ("Expection: Could not contact actuator. Is it running?")
            print(e)
            return E_UNKNOWN_TSP
        return E_UNKNOWN_TSP
        
    def rpc_getRmLsp(self):
        try:
            rm_lsp = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/zonecontroller/RM_LSP').get(timeout=10)
            return rm_lsp
        except gevent.Timeout:
            _log.exception("Expection: gevent.Timeout in rpc_getRmLsp()")
            return E_UNKNOWN_LSP
        except Exception as e:
            _log.exception ("Expection: Could not contact actuator. Is it running?")
            print(e)
            return E_UNKNOWN_LSP
        return E_UNKNOWN_LSP

    def publishRmTsp(self, tsp):
        #_log.debug('publishRmTsp()')
        pubTopic = self.root_topic+"/rm_tsp"
        pubMsg = [tsp, {'units': 'celcius', 'tz': 'UTC', 'type': 'float'}]
        publish_to_bus(self, pubTopic, pubMsg)
        return
        
    def publishRmLsp(self, lsp):
        #_log.debug('publishRmLsp()')
        pubTopic = self.root_topic+"/rm_lsp"
        pubMsg = [lsp, {'units': '%', 'tz': 'UTC', 'type': 'float'}]
        publish_to_bus(self, pubTopic, pubMsg)
        return

    def _calculateTed(self):
        #_log.debug('_calculateTed()')
        
        #zone lighting + ac
        ted = self.rpc_getRmCalcCoolingEnergy() + self._get_rm_light_power(self._rmLsp)
        
        #ted from ds devices associated with the zone
        for ed in self._ds_ed:
            ted = ted + ed
        
        return ted

    def publishTed(self):
        #_log.debug('publishTed()')
        self._ted = self._calculateTed()
        _log.info( "*** New TED: {0:.2f}, publishing to bus ***".format(self._ted))
        pubTopic = self.energyDemand_topic
        #_log.debug("TED pubTopic: " + pubTopic)
        pubMsg = [self._ted, {'units': 'W', 'tz': 'UTC', 'type': 'float'}]
        publish_to_bus(self, pubTopic, pubMsg)
        return
        
    def _calculatePredictedTed(self):
        #_log.debug('_calculatePredictedTed()')
        #TODO: Sam
        #get actual tsp from device
        tsp = self._rmTsp
        if isclose(tsp, 22.0):
            ted = 6500
        elif isclose(tsp, 23.0):
            ted = 6000
        elif isclose(tsp, 24.0):
            ted = 5500
        elif isclose(tsp, 25.0):
            ted = 5000
        elif isclose(tsp, 26.0):
            ted = 4500
        elif isclose(tsp, 27.0):
            ted = 4000
        elif isclose(tsp, 28.0):
            ted = 2000
        elif isclose(tsp, 29.0):
            ted = 1000
        else :
            ted = 500
        return ted
        
    def onDsEd(self, peer, sender, bus,  topic, headers, message):
        if sender == 'pubsub.compat':
            message = compat.unpack_legacy_message(headers, message)
        _log.debug('*********** New ed from ds, topic: ' + topic + \
                    ' & ed: {0:.4f}'.format(message[0]))
        
        deviceID = (topic.split('/', 3))[2]
        idx = self._get_ds_device_idx(deviceID)
        self._ds_ed[idx] = message[0]
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
        utils.vip_main(ZoneController)
    except Exception as e:
        print e
        _log.exception('unhandled exception')


if __name__ == '__main__':
    # Entry point for script
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        pass

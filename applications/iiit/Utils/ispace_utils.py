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
import math
import time
import gevent
import gevent.event
import requests
from enum import IntEnum
import json

from volttron.platform.agent import utils
from volttron.platform.messaging import headers as headers_mod
from volttron.platform.agent.known_identities import MASTER_WEB
from volttron.platform.agent import json as jsonapi

utils.setup_logging()
_log = logging.getLogger(__name__)

#some agent needs to communicate with the local bridge
#for example: pca --> to get the list of local/ds devices
#             building/zone/sh/rc/ss register with bridge to post tap/ted
#attimes bridge agent may not respond, it would be busy or crashed
#the agents can check bridge is active before making active calls to better handle rpc exceptions
#a perodic process can be scheduled that checks the bridge is active and reregisters if necessary
def ping_vb_failed(self):
    try:
        success = self.vip.rpc.call(self._vb_vip_identity
                                    , 'ping'
                                    ).get(timeout=10)
        if success:
            return False
    except Exception as e:
        #print(e)
        _log.exception('Bridge Agent is not responding!!! Message: {}'.format(e.message))
        pass
    return True
    
#register agent with local vb, blocking fucntion
#register this agent with vb as local device for posting active power & bid energy demand
#pca picks up the active power & energy demand bids only if registered with vb as local device
def register_agent_with_vb(self, sleep_time=10):
    while True:
        try:
            _log.info('registering with the Volttron Bridge...')
            success = self.vip.rpc.call(self._vb_vip_identity
                                        , 'register_local_ed_agent'
                                        , self.core.identity
                                        , self._device_id
                                        ).get(timeout=10)
            _log.debug ('self.vip.rpc.call() result: {}'.format(success))
            if success:
                _log.debug('Done.')
                break
        except Exception as e:
            #print(e)
            _log.exception('Maybe the Volttron Bridge Agent is not yet started!!!')
            pass
        _log.debug('will try again in {} sec'.format(sleep_time))
        time.sleep(sleep_time)
    return
    
#register rpc routes with MASTER_WEB
def register_rpc_route(self, name, handle, sleep_time=10):
    while True:
        try:
            _log.info('registering agent route...')
            success = self.vip.rpc.call(MASTER_WEB
                                        , 'register_agent_route'
                                        , r'^/' + name
                                        , handle
                                        ).get(timeout=10)
            _log.debug ('self.vip.rpc.call() result: {}'.format(success))
            if success is None:
                _log.debug('Done.')
                break
        except Exception as e:
            #print(e)
            _log.exception('Maybe the Volttron instance is not yet ready!!!')
            pass
        _log.debug('will try again in {} sec'.format(sleep_time))
        time.sleep(sleep_time)
    return
    
#try to retrive self._device_id, self._ip_addr, self._discovery_address from volttron bridge
def retrive_details_from_vb(self, sleep_time=10):
    while True:
        try:
            _log.info('retrive details from vb...')
            if self._device_id is None:
                self._device_id = self.vip.rpc.call(self._vb_vip_identity
                                                        , 'device_id').get(timeout=10)
                _log.debug('device id as per vb: {}'.format(self._device_id))
            if self._discovery_address is None:
                self._discovery_address = self.vip.rpc.call(self._vb_vip_identity
                                                        , 'discovery_address').get(timeout=10)
                _log.debug('discovery_address as per vb: {}'.format(self._discovery_address))
            if self._device_id is not None and self._discovery_address is not None:
                _log.debug('Done.')
                break
        except Exception as e:
            _log.exception (e)
            pass
        _log.debug('will try again in {} sec'.format(sleep_time))
        time.sleep(sleep_time)
    return
    
def publish_to_bus(self, topic, msg):
    #_log.debug('publish_to_bus()')
    now = datetime.datetime.utcnow().isoformat(' ') + 'Z'
    headers = {headers_mod.DATE: now}
    #Publish messages
    try:
        self.vip.pubsub.publish('pubsub'
                                , topic
                                , headers
                                , msg
                                ).get(timeout=10)
    except gevent.Timeout:
        _log.warning('gevent.Timeout in publish_to_bus()')
        return
    except Exception as e:
        _log.warning('Expection in publish_to_bus(), {}'.format(e.message))
        return
    return
    
def get_task_schdl(self, task_id, device, time_ms=None):
    #_log.debug('get_task_schdl()')
    self.time_ms = 600 if time_ms is None else time_ms
    try:
        start = str(datetime.datetime.now())
        end = str(datetime.datetime.now() 
                + datetime.timedelta(milliseconds=self.time_ms))
                
        msg = [[device,start,end]]
        result = self.vip.rpc.call('platform.actuator'
                                    , 'request_new_schedule'
                                    , self._agent_id
                                    , task_id
                                    , 'HIGH'
                                    , msg
                                    ).get(timeout=10)
        if result['result'] != 'SUCCESS':
            return False
    except gevent.Timeout:
        _log.exception('gevent.Timeout for task_id: {}'.format(task_id))
        return False
    except Exception as e:
        _log.exception ('Could not contact actuator for task_id: {}.'
                                            + ' Is it running? {}'.format(task_id, e.message))
        return False
        #print(e)
    return True
    
def cancel_task_schdl(self, task_id):
    #_log.debug('cancel_task_schdl()')
    try:
        result = self.vip.rpc.call('platform.actuator'
                                    , 'request_cancel_schedule'
                                    , self._agent_id, task_id
                                    ).get(timeout=10)
    except Exception as e:
        _log.exception('cancel_task_schdl() for task_id: {}'.format(task_id))
    return
    
def mround(num, multipleOf):
    #_log.debug('mround()')
    return (math.floor((num + multipleOf / 2) / multipleOf) * multipleOf)
    
#refer to https://bit.ly/3beuacI 
#(stackoverflow What is the best way to compare floats for almost-equality in Python?)
#comparing floats is mess
def isclose(a, b, rel_tol=1e-09, abs_tol=0.0):
    #_log.debug('isclose()')
    return (abs(a-b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol))
    
#return energy in kWh for the given duration
def calc_energy(self, pwr_wh, duration_sec):
    return ((pwr_wh * duration_sec)/3600000)
    
#TODO: do_rpc is synchrous, using requests which is a blocking operation
#need to convert to async operations, maybe can use gevent 
#(volttron inherently supports gevents)
def do_rpc(id, url_root, method, params=None, request_method='POST'):
    #global authentication
    #_log.debug('do_rpc()')
    result = False
    json_package = {
        'jsonrpc': '2.0',
        'id': id,
        'method':method,
    }
    
    #if authentication is not None:
    #    json_package['authorization'] = authentication
        
    if params:
        json_package['params'] = params
        
    try:
        if request_method == 'POST':
            response = requests.post(url_root, data=json.dumps(json_package), timeout=10)
        elif request_method == 'DELETE':
            response = requests.delete(url_root, data=json.dumps(json_package), timeout=10)
        else:
            response = requests.get(url_root, data=json.dumps(json_package), timeout=10)
            
        if response.ok:
            if 'result' in response.json().keys():
                success = response.json()['result']
                if success:
                    #_log.debug('response - ok, {} result:{}'.format(method, success))
                    result = True
                else:
                    _log.debug('respone - not ok, {} result:{}'.format(method, success))
            elif 'error' in response.json().keys():
                error = response.json()['error']
                _log.error('{} returned error, Error: {}'.format(method, error))
        else:
            _log.error('no respone, url_root:{}'.format(url_root)
                                    + ' method:{}'.format(method)
                                    + ' response: {}'.format(response))
    except Exception as e:
        #print(e)
        _log.exception('do_rpc() unhandled exception, most likely dest is down')
    return result
    
    

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
import gevent
import gevent.event
import requests
from enum import IntEnum

from volttron.platform.agent import utils
from volttron.platform.messaging import headers as headers_mod

utils.setup_logging()
_log = logging.getLogger(__name__)

#try to retrive self._device_id, self._ip_addr, self._discovery_address from volttron bridge
def retrive_details_from_vb(self):
    try:
        if self._device_id is None:
            self._device_id = self.vip.rpc.call(self._vb_vip_identity, 'device_id').get(timeout=10)
            _log.debug('device id as per vb: {}'.format(self._device_id))
        if self._discovery_address is None:
            self._discovery_address = self.vip.rpc.call(self._vb_vip_identity
                                                            , 'discovery_address').get(timeout=10)
            _log.debug('discovery_address as per vb: {}'.format(self._discovery_address))
    except Exception as e:
        _log.exception (e)
        pass
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
        _log.warning('Expection: gevent.Timeout in publish_to_bus()')
        return
    except Exception as e:
        _log.warning('Expection: publish_to_bus?')
        return
    return
    
def get_task_schdl(self, task_id, device, time_ms=None):
    #_log.debug('get_task_schdl()')
    self.time_ms = 600 if time_ms is None else time_ms
    try:
        result = {}
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
    except gevent.Timeout:
        _log.exception('Expection: gevent.Timeout in get_task_schdl()')
    except Exception as e:
        _log.exception ('Expection: Could not contact actuator. Is it running?')
        print(e)
    finally:
        return result
        
def cancel_task_schdl(self, task_id):
    #_log.debug('cancel_task_schdl()')
    result = self.vip.rpc.call('platform.actuator'
                                , 'request_cancel_schedule'
                                , self._agent_id, task_id
                                ).get(timeout=10)
    #_log.debug('task_id: ' + task_id)
    #_log.debug(result)
    return
    
def mround(num, multipleOf):
    #_log.debug('mround()')
    return math.floor((num + multipleOf / 2) / multipleOf) * multipleOf
    
#refer to http://stackoverflow.com/questions/5595425/what-is-the-best-way-to-compare-floats-for-almost-equality-in-python
#comparing floats is mess
def isclose(a, b, rel_tol=1e-09, abs_tol=0.0):
    #_log.debug('isclose()')
    return abs(a-b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)
    
#return energy in kWh for the given duration
def calc_energy(self, pwr_wh, duration_sec):
    return ((pwr_wh * duration_sec)/3600000)
    
def do_rpc(self, url_root, method, params=None ):
    #_log.debug('do_rpc()')
    result = False
    json_package = {
        'jsonrpc': '2.0',
        'id': self._agent_id,
        'method':method,
    }
    
    if params:
        json_package['params'] = params
        
    data = json.dumps(json_package)
    try:
        response = requests.post(url_root, data=json.dumps(json_package), timeout=10)
        
        if response.ok:
            success = response.json()['result']
            if success == True:
                #_log.debug('response - ok, {} result:{}'.format(method, success))
                result = True
            else:
                _log.debug('respone - not ok, {} result:{}'.format(method, success))
        else:
            _log.debug('no respone, {} result: {}'.format(method, response))
    except KeyError:
        error = response.json()['error']
        #print (error)
        _log.exception('KeyError: SHOULD NEVER REACH THIS ERROR - contact developer')
        return False
    except Exception as e:
        #print (e)
        _log.warning('Exception: do_rpc() unhandled exception, most likely dest is down')
        return False
    return result
    
    

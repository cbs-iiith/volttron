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

class ParamPP(IntEnum):
    idx_pp = 0
    idx_pp_datatype = 1
    idx_pp_id = 2
    idx_pp_isoptimal = 3
    idx_pp_discovery_addrs = 4
    idx_pp_device_id = 5
    idx_pp_duration = 6
    idx_pp_ttl = 7
    idx_pp_ts = 8
    
class ParamED(IntEnum):
    idx_ed = 0
    idx_ed_datatype = 1
    idx_ed_pp_id = 2
    idx_ed_isoptimal = 3
    idx_ed_discovery_addrs = 4
    idx_ed_device_id = 5
    idx_ed_duration = 6
    idx_ed_ttl = 7
    idx_ed_ts = 8
    
def ttl_timeout(str_ts, ttl):
        if ttl < 0:
            return False
        ts  = dateutil.parser.parse(str_ts)
        now = dateutil.parser.parse(datetime.datetime.utcnow().isoformat(' ') + 'Z')
        return (True if (now - ts) > ttl else False)
        
def print_pp(self, new_pp
                    , pp_datatype
                    , pp_id
                    , pp_isoptimal
                    , discovery_address
                    , deviceId
                    , pp_duration
                    , pp_ttl
                    , pp_ts
                    , hint
                    ):
    _log.info('New PP ({}): {0:.2f}'.format(hint, new_pp)
                    #+ ', pp_datatype: ' + str(pp_datatype)
                    + ', pp_id: ' + str(pp_id)
                    + ', pp_isoptimal: ' + str(pp_isoptimal)
                    + ', discovery_address: ' + str(discovery_address)
                    + ', deviceId: ' + str(deviceId)
                    + ', pp_duration: ' + str(pp_duration)
                    + ', pp_ttl: ' + str(pp_ttl)
                    + ', pp_ts: ' + str(pp_ts)
                    )
    return
    
def print_pp_msg(self, message, hint=None):
    print_pp(message[ParamPP.idx_pp]
            , message[ParamPP.idx_pp_datatype]
            , message[ParamPP.idx_pp_id]
            , message[ParamPP.idx_pp_isoptimal]
            , message[ParamPP.idx_pp_discovery_addrs]
            , message[ParamPP.idx_pp_device_id]
            , message[ParamPP.idx_pp_ttl]
            , message[ParamPP.idx_pp_ts]
            , hint
            )
    return
    
def print_ed(self, new_ed
                    , ed_datatype
                    , ed_pp_id
                    , ed_isoptimal
                    , ed_discovery_addrs
                    , ed_device_id
                    , ed_no_of_devices
                    , ed_ttl
                    , ed_ts
                    , hint
                    ):
    _log.info('New ED ({}): {0:.2f}'.format(hint, new_ed)
                    #+ ', ed_datatype: ' + str(ed_datatype)
                    + ', ed_pp_id: ' + str(ed_pp_id)
                    + ', ed_isoptimal: ' + str(ed_isoptimal)
                    + ', ed_discovery_addrs: ' + str(ed_discovery_addrs)
                    + ', ed_device_id: ' + str(ed_device_id)
                    + ', ed_no_of_devices: ' + str(ed_no_of_devices)
                    + ', ed_duration: ' + str(ed_duration)
                    + ', ed_ttl: ' + str(ed_ttl)
                    + ', ed_ts: ' + str(ed_ts)
                    )
    return
    
def print_ed_msg(self, message, hint=None):
    print_ed(message[ParamED.idx_ed]
            , message[ParamED.idx_ed_datatype]
            , message[ParamED.idx_ed_pp_id]
            , message[ParamED.idx_ed_isoptimal]
            , message[ParamED.idx_ed_discovery_addrs]
            , message[ParamED.idx_ed_device_id]
            , message[ParamED.idx_ed_no_of_devices]
            , message[ParamED.idx_ed_ttl]
            , message[ParamED.idx_ed_ts]
            , hint
            )
    return
    
#check for mandatory fields in the message
def valid_msg(message, mandatory_fields = []):
    try:
        for idx in mandatory_fields:
            if message[idx] is None:
                return False
    except Exception as e:
            print(e)
            return False
    return True
    
def sanity_check_pp(self, message, mandatory_fields = [], valid_pp_ids = []):
    if not valid_msg(message, mandatory_fields):
        _log.warning('rcvd a invalid pp msg, message: {}, do nothing!!!'.format(message))
        return False
        
    #print only if a valid msg
    print_pp_msg(message)
    
    #process pp only if pp_id corresponds to these ids (i.e., pp for either opt_pp_id or bid_pp_id)
    if valid_pp_ids != [] and message[ParamPP.idx_pp_id] not in valid_pp_ids:
        _log.debug('pp_id: {}'.format(message[ParamPP.idx_pp_id])
                    + ' not in valid_pp_ids: {}, do nothing!!!'.format(valid_pp_ids))
        return False
        
    #process ed only if msg is alive (didnot timeout)
    if ispace_utils.ttl_timeout(message[ParamPP.idx_pp_ts], message[ParamPP.idx_pp_ttl]):
        _log.warning('msg timed out, do nothing!!!')
        return False
        
    return True
    
def sanity_check_ed(self, message, mandatory_fields = [], valid_pp_ids = []):
    if not valid_msg(message, mandatory_fields):
        _log.warning('rcvd a invalid ed msg, message: {}, do nothing!!!'.format(message))
        return False
        
    #print only if a valid msg
    print_ed_msg(message)
    
    #process ed only if pp_id corresponds to these ids (i.e., ed for either opt_pp_id or bid_pp_id)
    if valid_pp_ids != [] and message[ParamPP.idx_ed_pp_id] not in valid_pp_ids:
        _log.debug('pp_id: {}'.format(message[ParamPP.idx_pp_id])
                    + ' not in valid_pp_ids: {}, do nothing!!!'.format(valid_pp_ids))
        return False
        
    #process ed only if msg is alive (didnot timeout)
    if ispace_utils.ttl_timeout(message[ParamPP.idx_ed_pp_ts], message[ParamPP.idx_ed_pp_ttl]):
        _log.warning('msg timed out, do nothing')
        return False
        
    return True
    
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
            if success:
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


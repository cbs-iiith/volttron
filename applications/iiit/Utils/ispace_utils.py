# -*- coding: utf-8 -*- {{{
# vim: set fenc=utf-8 ft=python sw=4 ts=4 sts=4 et:
#
# Copyright (c) 2020, Sam Babu, Godithi.
# All rights reserved.
#
#
# IIIT Hyderabad

#}}}

#Sam - Test

import datetime
import logging
import math
import gevent
import gevent.event

from volttron.platform.agent import utils
from volttron.platform.messaging import headers as headers_mod

from enum import IntEnum

utils.setup_logging()
_log = logging.getLogger(__name__)

class ParamPP(IntEnum):
    idx_pp                  = 0
    idx_pp_datatype         = 1
    idx_pp_id               = 2
    idx_pp_isoptimal        = 3
    idx_pp_discovery_addrs  = 4
    idx_pp_device_id        = 5
    idx_pp_duration         = 6
    idx_pp_ttl              = 7
    idx_pp_ts               = 8
    
class ParamED(IntEnum):
    idx_ed                  = 0
    idx_ed_datatype         = 1
    idx_ed_pp_id            = 2
    idx_ed_isoptimal        = 3
    idx_ed_discovery_addrs  = 4
    idx_ed_device_id        = 5
    idx_ed_duration         = 6
    idx_ed_ttl              = 7
    idx_ed_ts               = 8
    
def ttl_timeout(self, str_ts, ttl):
        _ts  = dateutil.parser.parse(str_ts)
        _now = dateutil.parser.parse(datetime.datetime.utcnow().isoformat(' ') + 'Z')
        ttl_timeout = True if (_now - _ts) > ttl else False
        return ttl_timeout
        
def print_pp(self, new_pp
                    , pp_datatype
                    , pp_id
                    , pp_isoptimal
                    , discovery_address
                    , deviceId
                    , pp_duration
                    , pp_ttl
                    , pp_ts
                    ):
    _log.info("New PP: {0:.2f}".format(new_pp)
                    #+ ", pp_datatype: " + str(pp_datatype)
                    + ", pp_id: " + str(pp_id)
                    + ", pp_isoptimal: " + str(pp_isoptimal)
                    + ", discovery_address: " + str(discovery_address)
                    + ", deviceId: " + str(deviceId)
                    + ", pp_duration: " + str(pp_duration)
                    + ", pp_ttl: " + str(pp_ttl)
                    + ", pp_ts: " + str(pp_ts)
                )
    return
    
def print_pp_msg(self, message):
    print_pp(message[ParamPP.idx_pp]
            , message[ParamPP.idx_pp_datatype]
            , message[ParamPP.idx_pp_id]
            , message[ParamPP.idx_pp_isoptimal]
            , message[ParamPP.idx_pp_discovery_addrs]
            , message[ParamPP.idx_pp_device_id]
            , message[ParamPP.idx_pp_ttl]
            , message[ParamPP.idx_pp_ts]
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
                    ):
    _log.info("New ED: {0:.2f}".format(new_ed)
                    #+ ", ed_datatype: " +str(ed_datatype)
                    + ", ed_pp_id: " +str(ed_pp_id)
                    + ", ed_isoptimal: " +str(ed_isoptimal)
                    + ", ed_discovery_addrs: " +str(ed_discovery_addrs)
                    + ", ed_device_id: " +str(ed_device_id)
                    + ", ed_no_of_devices: " +str(ed_no_of_devices)
                    + ", ed_duration: " + str(ed_duration)
                    + ", ed_ttl: " +str(ed_ttl)
                    + ", ed_ts: " +str(ed_ts)
                )
    return
    
def print_ed_msg(self, message):
    print_ed(message[ParamED.idx_ed]
            , message[ParamED.idx_ed_datatype]
            , message[ParamED.idx_ed_pp_id]
            , message[ParamED.idx_ed_isoptimal]
            , message[ParamED.idx_ed_discovery_addrs]
            , message[ParamED.idx_ed_device_id]
            , message[ParamED.idx_ed_no_of_devices]
            , message[ParamED.idx_ed_ttl]
            , message[ParamED.idx_ed_ts]
            )
    return
    
def publish_to_bus(self, topic, msg):
    #_log.debug('publish_to_bus()')
    now = datetime.datetime.utcnow().isoformat(' ') + 'Z'
    headers = {headers_mod.DATE: now}
    #Publish messages
    try:
        self.vip.pubsub.publish('pubsub', topic, headers, msg).get(timeout=10)
    except gevent.Timeout:
        _log.warning("Expection: gevent.Timeout in publish_to_bus()")
        return
    except Exception as e:
        _log.warning("Expection: publish_to_bus?")
        return
    return

def get_task_schdl(self, task_id, device, time_ms=None):
    #_log.debug("get_task_schdl()")
    self.time_ms = 600 if time_ms is None else time_ms
    try:
        result = {}
        start = str(datetime.datetime.now())
        end = str(datetime.datetime.now() 
                + datetime.timedelta(milliseconds=self.time_ms))
                
        msg = [
                [device,start,end]
                ]
        result = self.vip.rpc.call(
                'platform.actuator', 
                'request_new_schedule',
                self._agent_id, 
                task_id,
                'HIGH',
                msg).get(timeout=10)
    except gevent.Timeout:
        _log.exception("Expection: gevent.Timeout in get_task_schdl()")
    except Exception as e:
        _log.exception ("Expection: Could not contact actuator. Is it running?")
        print(e)
    finally:
        return result

def cancel_task_schdl(self, task_id):
    #_log.debug('cancel_task_schdl()')
    result = self.vip.rpc.call('platform.actuator', 'request_cancel_schedule', \
                                self._agent_id, task_id).get(timeout=10)
    #_log.debug("task_id: " + task_id)
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

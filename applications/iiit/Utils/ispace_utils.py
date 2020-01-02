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

from volttron.platform.agent import utils
from volttron.platform.messaging import headers as headers_mod

utils.setup_logging()
_log = logging.getLogger(__name__)

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

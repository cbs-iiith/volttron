# -*- coding: utf-8 -*- {{{
# vim: set fenc=utf-8 ft=python sw=4 ts=4 sts=4 et:
#
# Copyright (c) 2017, IIIT-Hyderabad
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

import settings

import time
import struct

LED_ON = 1
LED_OFF = 0
FAN_ON = 1
FAN_OFF = 0

SCHEDULE_AVLB = 1
SCHEDULE_NOT_AVLB = 0

utils.setup_logging()
_log = logging.getLogger(__name__)
__version__ = '0.1'

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

def smarthub(config_path, **kwargs):
    config = utils.load_config(config_path)
    vip_identity = config.get('vip_identity', 'iiit.smarthub')
    # This agent needs to be named iiit.smarthub. Pop the uuid id off the kwargs
    kwargs.pop('identity', None)

    Agent.__name__ = 'SmartHub_Agent'
    return SmartHub(config_path, identity=vip_identity, **kwargs)

class SmartHub(Agent):
    '''Smart Hub
    '''
    _taskID_LedDebug = 1
    _ledDebugState = 0

    def __init__(self, config_path, **kwargs):
        super(SmartHub, self).__init__(**kwargs)
        _log.debug("vip_identity: " + self.core.identity)

        self.config = utils.load_config(config_path)
        self._configGetPoints()
        self._configGetInitValues()
        
        return

    @Core.receiver('onsetup')
    def setup(self, sender, **kwargs):
        _log.info(self.config['message'])
        self._agent_id = self.config['agentid']
        
        return

    @Core.receiver('onstart')            
    def startup(self, sender, **kwargs):
        self.runSmartHubTest()
        self.switchLedDebug(LED_ON)
        
        return  

    @Core.receiver('onstop')
    def onstop(self, sender, **kwargs):
        _log.debug('onstop()')
        self.switchLedDebug(LED_OFF)
        
        return

    @Core.receiver('onfinish')
    def onfinish(self, sender, **kwargs):
        _log.debug('onfinish()')
        self.switchLedDebug(LED_OFF)
        
        return
        
    def _configGetInitValues(self):
        
        return

    def _configGetPoints(self):
        
        return

    def runSmartHubTest(self):
        _log.debug("Running : runSmartHubTest()...")
        _log.debug('switch on debug led')
        self.switchLedDebug(LED_ON)
        time.sleep(1)

        _log.debug('switch off debug led')
        self.switchLedDebug(LED_OFF)
        time.sleep(1)

        _log.debug('switch on debug led')
        self.switchLedDebug(LED_ON)

        _log.debug("EOF Testing")
        
        return

    def switchLedDebug(self, state):
        #_log.debug('switchLedDebug()')
        result = []

        if self._ledDebugState == state:
            #_log.debug('same state, do nothing')
            return

        try: 
            start = str(datetime.datetime.now())
            end = str(datetime.datetime.now() 
                    + datetime.timedelta(milliseconds=500))

            msg = [
                    ['iiit/cbs/smarthub',start,end]
                    ]
            result = self.vip.rpc.call(
                    'platform.actuator', 
                    'request_new_schedule',
                    self._agent_id, 
                    str(self._taskID_LedDebug),
                    'HIGH',
                    msg).get(timeout=2)
            #print("schedule result", result)
        except Exception as e:
            _log.exception ("Exception: Could not contact actuator. Is it running?")
            #print(e)
            return

        try:
            if result['result'] == 'SUCCESS':
                result = self.vip.rpc.call(
                        'platform.actuator', 
                        'set_point',
                        self._agent_id, 
                        'iiit/cbs/smarthub/LEDDebug',
                        state).get(timeout=1)
                #print("Set result", result)
                self.updateLedDebugState(state)
        except Exception as e:
            _log.exception ("Expection: setting ledDebug")
            #print(e)
            return


    def updateLedDebugState(self, state):
        _log.debug('updateLedDebugState()')
        headers = { 'requesterID': self._agent_id, }
        ledDebug_status = self.vip.rpc.call(
                'platform.actuator','get_point',
                'iiit/cbs/smarthub/LEDDebug').get(timeout=1)
        
        if state == int(ledDebug_status):
            self._ledDebugState = state
        
        if self._ledDebugState == LED_ON:
            _log.debug('Current State: LED Debug is ON!!!')
        else:
            _log.debug('Current State: LED Debug is OFF!!!')

        return


def main(argv=sys.argv):
    '''Main method called by the eggsecutable.'''
    try:
        utils.vip_main(smarthub)
    except Exception as e:
        print e
        _log.exception('unhandled exception')


if __name__ == '__main__':
    # Entry point for script
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        pass

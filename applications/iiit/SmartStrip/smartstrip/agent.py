# -*- coding: utf-8 -*- {{{
# vim: set fenc=utf-8 ft=python sw=4 ts=4 sts=4 et:
#
# Copyright (c) 2016, IIIT-Hyderabad
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
# ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
# The views and conclusions contained in the software and documentation are those
# of the authors and should not be interpreted as representing official policies,
# either expressed or implied, of the FreeBSD Project.
#
#
# IIIT Hyderabad

#}}}


import datetime
import logging
import sys
import uuid

from volttron.platform.vip.agent import Agent, Core, PubSub, compat, RPC
from volttron.platform.agent import utils
from volttron.platform.messaging import headers as headers_mod

from volttron.platform.messaging import topics, headers as headers_mod

import settings

import time


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

def smartstrip(config_path, **kwargs):

    config = utils.load_config(config_path)
    agent_id = config['agentid']
    LED_ON = 1
    LED_OFF = 0
    RELAY_ON = 1
    RELAY_OFF = 0
    PLUG_ID_1 = 0
    PLUG_ID_2 = 1

    class SmartStrip(Agent):
        '''Smart Strip with 2 plug
        '''
        #_taskID = 1
        _present_value = 0
        _taskID_LedDebug = 1
        _taskID_Plug1Relay = 2
        _taskID_Plug2Relay = 3
        _taskID_ReadMeterData = 100
        _ledDebugState = 0
        _plug2RelayState = 0
        _plugRelayState = [0, 0]
        _plugConnected = [ 0, 0]
        _plug_tag_id = ["ffffffffffffffff", "ffffffffffffffff"]

        def __init__(self, **kwargs):
            super(SmartStrip, self).__init__(**kwargs)

        @Core.receiver('onsetup')
        def setup(self, sender, **kwargs):
            _log.info(config['message'])
            self._agent_id = config['agentid']

        @Core.receiver('onstart')            
        def startup(self, sender, **kwargs):
            #self.publish_schedule()
            #self.use_rpc()
            period = config['period']
            #self.core.periodic(period, self.publish_schedule, wait=None)
            self._tag_ids = config['tag_ids']
            print (self._tag_ids[0])
            print (self._tag_ids[1])
            print (type (self._tag_ids[0]))

            _log.debug('switch on debug led')
            self.switchLedDebug(LED_ON)
            time.sleep(1)

            _log.debug('switch off debug led')
            self.switchLedDebug(LED_OFF)
            time.sleep(1)

            _log.debug('switch on debug led')
            self.switchLedDebug(LED_ON)

            _log.debug('switch on relay 1')
            self.switchRelay(PLUG_ID_1, RELAY_ON)
            time.sleep(1)
            _log.debug('switch off relay 1')
            self.switchRelay(PLUG_ID_1, RELAY_OFF)
            _log.debug('switch on relay 2')
            self.switchRelay(PLUG_ID_2, RELAY_ON)
            time.sleep(1)
            _log.debug('switch off relay 2')
            self.switchRelay(PLUG_ID_2, RELAY_OFF)
            time.sleep(1)

        @RPC.export
        def switchLedDebug(self, state):
            _log.debug('switchLedDebug()')
            if self._ledDebugState == state:
                _log.debug('same state, do nothing')
                return

            try: 
                start = str(datetime.datetime.now())
                end = str(datetime.datetime.now() + datetime.timedelta(milliseconds=300))

                msg = [
                        ['iiit/cbs/smartstrip',start,end]
                        ]
                result = self.vip.rpc.call(
                        'platform.actuator', 
                        'request_new_schedule',
                        agent_id, 
                        str(self._taskID_LedDebug),
                        'LOW',
                        msg).get(timeout=1)
                self._taskID_LedDebug = self._taskID_LedDebug + 1
                #print("schedule result", result)
            except Exception as e:
                print ("Could not contact actuator. Is it running?")
                print(e)
                return

            try:
                if result['result'] == 'SUCCESS':
                    result = self.vip.rpc.call(
                            'platform.actuator', 
                            'set_point',
                            agent_id, 
                            'iiit/cbs/smartstrip/LEDDebug',
                            state).get(timeout=1)
                    print("Set result", result)
            except Exception as e:
                print(e)

            _log.debug('OK call updateLedDebugState()')
            self.updateLedDebugState()


        @RPC.export
        def switchRelay(self, plugID, state):
            _log.debug('switchRelay()')
            if plugID == PLUG_ID_1:
                self.switchPlug1Relay(state)
            elif plugID == PLUG_ID_2:
                self.switchPlug2Relay(state)


        def switchPlug1Relay(self, state):
            _log.debug('switchPlug1Relay()')
            if self._plugRelayState[PLUG_ID_1] == state:
                _log.debug('same state, do nothing')
                return

            try: 
                start = str(datetime.datetime.now())
                end = str(datetime.datetime.now() + datetime.timedelta(milliseconds=400))

                msg = [
                        ['iiit/cbs/smartstrip',start,end]
                        ]
                result = self.vip.rpc.call(
                        'platform.actuator', 
                        'request_new_schedule',
                        agent_id, 
                        str(self._taskID_Plug1Relay),
                        'LOW',
                        msg).get(timeout=10)
                print("schedule result", result)
            except Exception as e:
                print ("Could not contact actuator. Is it running?")
                print(e)
                return

            try:
                if result['result'] == 'SUCCESS':
                    result = self.vip.rpc.call(
                            'platform.actuator', 
                            'set_point',
                            agent_id, 
                            'iiit/cbs/smartstrip/Plug1Relay',
                            state).get(timeout=10)
                    print("Set result", result)
            except Exception as e:
                print(e) 

            _log.debug('OK call updatePlug1RelayState()')
            self.updatePlug1RelayState()

        def switchPlug2Relay(self, state):
            _log.debug('switchPlug2Relay()')

            if self._plugRelayState[PLUG_ID_2] == state:
                _log.debug('same state, do nothing')
                return

            try: 
                start = str(datetime.datetime.now())
                end = str(datetime.datetime.now() + datetime.timedelta(milliseconds=400))

                msg = [
                        ['iiit/cbs/smartstrip',start,end]
                        ]
                result = self.vip.rpc.call(
                        'platform.actuator', 
                        'request_new_schedule',
                        agent_id, 
                        str(self._taskID_Plug2Relay),
                        'LOW',
                        msg).get(timeout=10)
                print("schedule result", result)
            except Exception as e:
                print ("Could not contact actuator. Is it running?")
                print(e)
                return

            try:
                if result['result'] == 'SUCCESS':
                    result = self.vip.rpc.call(
                            'platform.actuator', 
                            'set_point',
                            agent_id, 
                            'iiit/cbs/smartstrip/Plug2Relay',
                            state).get(timeout=1)
                    print("Set result", result)
            except Exception as e:
                print(e) 

            _log.debug('OK call updatePlug2RelayState()' )
            self.updatePlug2RelayState()


        @PubSub.subscribe('pubsub', topics.ACTUATOR_SCHEDULE_ANNOUNCE(campus='iiit',
            building='cbs',unit='smartstrip'))
        def actuate(self, peer, sender, bus,  topic, headers, message):
            _log.debug('actuate()')
            _taskID = headers.get('taskID')
            _log.debug("Task ID : " + _taskID)
            if headers[headers_mod.REQUESTER_ID] != agent_id:
                return
            '''Match the announce for our device with our ID
            Then take an action.
            '''
            _log.debug("*** SAM _taskID Check***************************")
            if _taskID == str(self._taskID_LedDebug):
                #_log.debug('OK call updateLedDebugState()')
                #self.updateLedDebugState()
                return
            elif _taskID == str(self._taskID_Plug1Relay):
                #self.updatePlug1RelayState()
                return
            elif _taskID == str(self._taskID_Plug2Relay):
                #self.updatePlug1RelayState()
                return

            _log.debug('eof actuate(), should never reach!!!')


        def updateLedDebugState(self):
            _log.debug('updateLedDebugState()')
            headers = { 'requesterID': agent_id, }
            ledDebug_status = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/smartstrip/LEDDebug').get(timeout=1)

            _log.debug('plug 1 old self._ledDebugState : %d', self._ledDebugState)
            _log.debug('plug 1 new ledDebug_status : %d', ledDebug_status)

            #update = ledDebug_status & self._ledDebugState
            #_log.debug('update: ' + str(update))
            #if(update):
            _log.debug('Changing led debug state...')
            self._ledDebugState = int(ledDebug_status)


        def updatePlug1RelayState(self):
            _log.debug('updatePlug1RelayState()')
            headers = { 'requesterID': agent_id, }
            relay_status = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/smartstrip/Plug1Relay').get(timeout=1)

            _log.debug('plug 1 old _plugRelayState : %d', self._plugRelayState[PLUG_ID_1])
            _log.debug('plug 1 new relay_status : %d', relay_status)

            #update = relay_status & self._plugRelayState[PLUG_ID_1]
            #_log.debug('update: ', str(update))
            #if(update):
            _log.debug('Changing relay state...')
            self._plugRelayState[PLUG_ID_1] = int(relay_status)


        def updatePlug2RelayState(self):
            _log.debug('updatePlug2RelayState()')
            headers = { 'requesterID': agent_id, }
            relay_status = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/smartstrip/Plug2Relay').get(timeout=1)

            _log.debug('plug 2 old _plugRelayState : %d', self._plugRelayState[PLUG_ID_2])
            _log.debug('plug 2 new relay_status : %d', relay_status)

            #update = relay_status & self._plugRelayState[1]
            #_log.debug('update: ', str(update))
            #if(update):
            _log.debug('Changing relay state...')
            self._plugRelayState[PLUG_ID_2] = int(relay_status)


        #@Core.periodic(5)	#doing it in on startup, hence commented here
        def publish_schedule(self):
            '''Periodically publish a schedule request'''
            _log.debug('publish_schedule()')
            _log.debug('_taskID_ReadMeterData: %d', self._taskID_ReadMeterData)

            headers = {
                    'AgentID': agent_id,
                    'type': 'NEW_SCHEDULE',
                    'requesterID': agent_id, #The name of the requesting agent.
                    'taskID': agent_id + "-ReadMeterDataTask-" + str(self._taskID_ReadMeterData), #The desired task ID for this task. It must be unique among all other scheduled tasks.
                    'priority': 'HIGH', #The desired task priority, must be 'HIGH', 'LOW', or 'LOW_PREEMPT'
                    }

            self._taskID_ReadMeterData = self._taskID_ReadMeterData + 1
            #_log.debug('taskID: %d', self._taskID_ReadMeterData)

            start = str(datetime.datetime.now())
            end = str(datetime.datetime.now() + datetime.timedelta(milliseconds=300))


            msg = [
                    ['iiit/cbs/smartstrip',start,end]
                    #Could add more devices
                    #                 ["campus/building/device1", #First time slot.
                    #                  "2014-1-31 12:27:00",     #Start of time slot.
                    #                  "2016-1-31 12:29:00"],     #End of time slot.
                    #                 ["campus/building/device2", #Second time slot.
                    #                  "2014-1-31 12:26:00",     #Start of time slot.
                    #                  "2016-1-31 12:30:00"],     #End of time slot.
                    #                 ["campus/building/device3", #Third time slot.
                    #                  "2014-1-31 12:30:00",     #Start of time slot.
                    #                  "2016-1-31 12:32:00"],     #End of time slot.
                    #etc...
                    ]
            self.vip.pubsub.publish(
                    'pubsub', topics.ACTUATOR_SCHEDULE_REQUEST, headers, msg)


            def use_rpc(self):
                _log.debug('use_rpc(), _taskID_ReadMeterData: %d', self._taskID_ReadMeterData)
            try: 
                start = str(datetime.datetime.now())
                end = str(datetime.datetime.now() + datetime.timedelta(minutes=1))

                msg = [
                        ['iiit/cbs/smartstrip',start,end]
                        ]
                result = self.vip.rpc.call(
                        'platform.actuator', 
                        'request_new_schedule',
                        agent_id, 
                        "ReadMeterData",
                        'LOW',
                        msg).get(timeout=10)
                print("schedule result", result)
            except Exception as e:
                print ("Could not contact actuator. Is it running?")
                print(e)
                return

            try:
                if result['result'] == 'SUCCESS':
                    result = self.vip.rpc.call(
                            'platform.actuator', 
                            'set_point',
                            agent_id, 
                            'iiit/cbs/smartstrip/Plug1Voltage',
                            1).get(timeout=10)
                    print("Set result", result)
            except Exception as e:
                print ("Expected to fail since there is no real device to set")
                print(e)    




    Agent.__name__ = 'SmartStrip_Agent'
    return SmartStrip(**kwargs)



def main(argv=sys.argv):
    '''Main method called by the eggsecutable.'''
    try:
        utils.vip_main(smartstrip)
    except Exception as e:
        print e
        _log.exception('unhandled exception')


if __name__ == '__main__':
    # Entry point for script
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        pass

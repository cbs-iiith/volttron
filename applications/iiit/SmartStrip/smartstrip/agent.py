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
import struct

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
        _taskID_ReadTagIDs = 4
        _taskID_ReadMeterData = 100
        _ledDebugState = 0
        _plug2RelayState = 0
        _plugRelayState = [0, 0]
        _plugConnected = [ 0, 0]
        _plug_tag_id = ["7FC000007FC00000", "7FC000007FC00000"]

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

            #self.runSmartStripTest(self)

            period_read_tag = config['period_read_tag']
            self.core.periodic(period_read_tag, self.readTagIDs, wait=None)
            #self.readTagIDs()

        def runSmartStripTest(self):
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

        def readTagIDs(self):
            _log.debug('readTagIDs()')
            tempTagId1 = ''
            tempTagId2 = ''

            try: 
                start = str(datetime.datetime.now())
                end = str(datetime.datetime.now() 
                        + datetime.timedelta(milliseconds=300))

                msg = [
                        ['iiit/cbs/smartstrip',start,end]
                        ]
                result = self.vip.rpc.call(
                        'platform.actuator', 
                        'request_new_schedule',
                        agent_id, 
                        str(self._taskID_ReadTagIDs),
                        'HIGH',
                        msg).get(timeout=1)
            except Exception as e:
                print ("Could not contact actuator. Is it running?")
                print(e)
                return
            #
            try:
                '''
                Smart Strip bacnet server splits the 64 bit tag id 
                into two parts and sends them accros as two float values.
                Hence need to get both the points (floats value) and recover the actual tag id
                '''
                if result['result'] == 'SUCCESS':
                    fTagID1_1 = self.vip.rpc.call(
                            'platform.actuator','get_point',
                            'iiit/cbs/smartstrip/TagID1_1').get(timeout=1)

                    if result['result'] == 'SUCCESS':
                        fTagID1_2 = self.vip.rpc.call(
                                'platform.actuator','get_point',
                                'iiit/cbs/smartstrip/TagID1_2').get(timeout=1)
                        newTagId1 = self.recoveryTagID(fTagID1_1, fTagID1_2)
                    _log.debug('Tag 1: ' + newTagId1)

                #get second tag id
                if result['result'] == 'SUCCESS':
                    fTagID2_1 = self.vip.rpc.call(
                            'platform.actuator','get_point',
                            'iiit/cbs/smartstrip/TagID2_1').get(timeout=1)

                    if result['result'] == 'SUCCESS':
                        fTagID2_2 = self.vip.rpc.call(
                                'platform.actuator','get_point',
                                'iiit/cbs/smartstrip/TagID2_2').get(timeout=1)
                        newTagId2 = self.recoveryTagID(fTagID2_1, fTagID2_2)
                    _log.debug('Tag 2: ' + newTagId2)

            except Exception as e:
                print(e)

            self.processNewTagId(PLUG_ID_1, newTagId1)
            self.processNewTagId(PLUG_ID_2, newTagId2)

        def processNewTagId(self, plugID, newTagId):		
            if newTagId != '7FC000007FC00000':
                #device is connected condition
                #check if current tag id is same as new, if so, do nothing
                if newTagId != self._plug_tag_id[plugID] :
                    #update the tag id and change connected state
                    self._plug_tag_id[plugID] = newTagId
                    self._plugConnected[plugID] = 1
                    if self.tagAuthorised(newTagId) :
                        self.switchRelay(plugID, RELAY_ON)
            else:
                #no device connected condition
                if self._plugConnected[plugID] == 0:
                    return
                elif self._plugConnected[plugID] == 1 or newTagId != self._plug_tag_id[plugID] :
                            #update the tag id and change connected state
                    self._plug_tag_id[plugID] = newTagId
                    self._plugConnected[plugID] = 0
                    self.switchRelay(plugID, RELAY_OFF)

        def recoveryTagID(self, fTagIDPart1, fTagIDPart2):
            buff = self.convertToByteArray(fTagIDPart1, fTagIDPart2)
            tag = ''			
            for i in reversed(buff):
                tag = tag + format(i, '02x')
            return tag.upper()

        def convertToByteArray(self, fltVal1, fltVal2):
            idLsb = bytearray(struct.pack('f', fltVal1))
            idMsb = bytearray(struct.pack('f', fltVal2))
            return (idMsb + idLsb)    


        def tagAuthorised(self, tagID):
            for id in self._tag_ids :
                if tagID == id:
                    return True
            return False

        @RPC.export
        def switchLedDebug(self, state):
            _log.debug('switchLedDebug()')
            if self._ledDebugState == state:
                _log.debug('same state, do nothing')
                return

            try: 
                start = str(datetime.datetime.now())
                end = str(datetime.datetime.now() 
                        + datetime.timedelta(milliseconds=300))

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
                end = str(datetime.datetime.now() 
                        + datetime.timedelta(milliseconds=400))

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
                end = str(datetime.datetime.now() 
                        + datetime.timedelta(milliseconds=400))

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

        def updateLedDebugState(self):
            _log.debug('updateLedDebugState()')
            headers = { 'requesterID': agent_id, }
            ledDebug_status = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/smartstrip/LEDDebug').get(timeout=1)

            _log.debug('plug 1 old self._ledDebugState : %d', 
                    self._ledDebugState)
            _log.debug('plug 1 new ledDebug_status : %d', ledDebug_status)
            self._ledDebugState = int(ledDebug_status)


        def updatePlug1RelayState(self):
            _log.debug('updatePlug1RelayState()')
            headers = { 'requesterID': agent_id, }
            relay_status = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/smartstrip/Plug1Relay').get(timeout=1)

            _log.debug('plug 1 old _plugRelayState : %d', 
                    self._plugRelayState[PLUG_ID_1])
            _log.debug('plug 1 new relay_status : %d', relay_status)
            self._plugRelayState[PLUG_ID_1] = int(relay_status)


        def updatePlug2RelayState(self):
            _log.debug('updatePlug2RelayState()')
            headers = { 'requesterID': agent_id, }
            relay_status = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/smartstrip/Plug2Relay').get(timeout=1)

            _log.debug('plug 2 old _plugRelayState : %d', 
                    self._plugRelayState[PLUG_ID_2])
            _log.debug('plug 2 new relay_status : %d', relay_status)
            self._plugRelayState[PLUG_ID_2] = int(relay_status)


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

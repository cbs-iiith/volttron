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
    topic_price_point= config.get('topic_price_point', 'prices/PricePoint')

    LED_ON = 1
    LED_OFF = 0
    RELAY_ON = 1
    RELAY_OFF = 0
    PLUG_ID_1 = 0
    PLUG_ID_2 = 1
    DEFAULT_TAG_ID = '7FC000007FC00000'

    class SmartStrip(Agent):
        '''Smart Strip with 2 plug
        '''
        _taskID_LedDebug = 1
        _taskID_Plug1Relay = 2
        _taskID_Plug2Relay = 3
        _taskID_ReadTagIDs = 4
        _taskID_ReadMeterData = 5

        _ledDebugState = 0
        _plugRelayState = [0, 0]
        _plugConnected = [ 0, 0]
        _plug_tag_id = ['7FC000007FC00000', '7FC000007FC00000']
        _plug_pricepoint_th = [0.5, 0.75]
        _price_point_previous = 0.4 
        _price_point_current = 0.4 
        
        _newTagId1 = ''
        _newTagId2 = ''

        def __init__(self, **kwargs):
            super(SmartStrip, self).__init__(**kwargs)

        @Core.receiver('onsetup')
        def setup(self, sender, **kwargs):
            _log.info(config['message'])
            self._agent_id = config['agentid']

        @Core.receiver('onstart')            
        def startup(self, sender, **kwargs):
            self._tag_ids = config['tag_ids']

            #self.runSmartStripTest(self)
            #self.readTagIDs()
            #period_read_tag = config['period_read_tag']
            #self.core.periodic(period_read_tag, self.readTagIDs, wait=None)
            #time.sleep(10)
            #self.meterData(PLUG_ID_1)
            #self.meterData(PLUG_ID_2)
            period_read_data = config['period_read_meterdata']
            self.core.periodic(period_read_data, self.getData, wait=None)

            self._price_point_previous = config['default_base_price']
            self._price_point_current = config['default_base_price']
            self._plug_pricepoint_th = config['plug_pricepoint_th']

            self.switchLedDebug(LED_ON)

        @Core.receiver('onstop')
        def onstop(self, sender, **kwargs):
            _log.debug('onstop()')
            self.switchLedDebug(LED_OFF)
            self.switchRelay(PLUG_ID_1, RELAY_OFF)
            self.switchRelay(PLUG_ID_2, RELAY_OFF)
            pass

        @Core.receiver('onfinish')
        def onfinish(self, sender, **kwargs):
            _log.debug('onfinish()')
            self.switchLedDebug(LED_OFF)
            self.switchRelay(PLUG_ID_1, RELAY_OFF)
            self.switchRelay(PLUG_ID_2, RELAY_OFF)
            pass

        def runSmartStripTest(self):
            _log.debug("Running : runSmartStripTest()...")
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
            _log.debug("EOF Testing")

        def getData(self):
            _log.debug('getData()...')
            
            #get schedule
            try: 
                start = str(datetime.datetime.now())
                end = str(datetime.datetime.now() 
                        + datetime.timedelta(seconds=3))

                msg = [
                        ['iiit/cbs/smartstrip',start,end]
                        ]
                result = self.vip.rpc.call(
                        'platform.actuator', 
                        'request_new_schedule',
                        agent_id, 
                        'schdl_getData_low_preempt',
                        'LOW_PREEMPT',
                        msg).get(timeout=1)
            except Exception as e:
                _log.error ("Could not contact actuator. Is it running?")
                print(e)
                pass

            #run the task
            if result['result'] == 'SUCCESS':

                #_log.debug('meterData()')
                if self._plugRelayState[PLUG_ID_1] == RELAY_ON:
                    self.readMeterData(PLUG_ID_1)

                if self._plugRelayState[PLUG_ID_2] == RELAY_ON:
                    self.readMeterData(PLUG_ID_2)
                    
                self.readTagIDs()
                
                #cancel the schedule
                
                _log.debug('...getData()')
                
                #_log.debug('start processNewTagId()...')
                self.processNewTagId(PLUG_ID_1, self._newTagId1)
                self.processNewTagId(PLUG_ID_2, self._newTagId2)
                #_log.debug('...done processNewTagId()')

        def readMeterData(self, plugID):
            #_log.info ('readMeterData(), plugID: ' + str(plugID))
            if plugID == PLUG_ID_1:
                pointVolatge = 'Plug1Voltage'
                pointCurrent = 'Plug1Current'
                pointActivePower = 'Plug1ActivePower'
            elif plugID == PLUG_ID_2:
                pointVolatge = 'Plug2Voltage'
                pointCurrent = 'Plug2Current'
                pointActivePower = 'Plug2ActivePower'

            #
            try:
                fVolatge = self.vip.rpc.call(
                        'platform.actuator','get_point',
                        'iiit/cbs/smartstrip/' + \
                        pointVolatge).get(timeout=1)
                #_log.debug('voltage: {0:.2f}'.format(fVolatge))
                fCurrent = self.vip.rpc.call(
                        'platform.actuator','get_point',
                        ('iiit/cbs/smartstrip/' + \
                        pointCurrent)).get(timeout=1)
                #_log.debug('current: {0:.2f}'.format(fCurrent))
                fActivePower = self.vip.rpc.call(
                        'platform.actuator','get_point',
                        'iiit/cbs/smartstrip/' + \
                        pointActivePower).get(timeout=1)
                #_log.debug('active: {0:.2f}'.format(fActivePower))

                #TODO: temp fix, need to move this to backend code
                if fVolatge > 80000:
                    fVolatge = 0.0
                if fCurrent > 80000:
                    fCurrent = 0.0
                if fActivePower > 80000:
                    fActivePower = 0.0

                _log.info(('Plug {0:d}: '.format(plugID + 1)
                        + 'voltage: {0:.2f}'.format(fVolatge) 
                        + ', Current: {0:.2f}'.format(fCurrent)
                        + ', ActivePower: {0:.2f}'.format(fActivePower)
                        ))
                #release the time schedule, if we finish early.
            except Exception as e:
                _log.error ("Expection:, exception in readMeterData()")
                print(e)
                pass

        def readTagIDs(self):
            #_log.debug('readTagIDs()')
            self._newTagId1 = ''
            self._newTagId2 = ''

            try:
                '''
                Smart Strip bacnet server splits the 64 bit tag id 
                into two parts and sends them accros as two float values.
                Hence need to get both the points (floats value)
                and recover the actual tag id
                '''
                fTagID1_1 = self.vip.rpc.call(
                        'platform.actuator','get_point',
                        'iiit/cbs/smartstrip/TagID1_1').get(timeout=1)

                fTagID1_2 = self.vip.rpc.call(
                        'platform.actuator','get_point',
                        'iiit/cbs/smartstrip/TagID1_2').get(timeout=1)
                self._newTagId1 = self.recoveryTagID(fTagID1_1, fTagID1_2)
                #_log.debug('Tag 1: ' + newTagId1)

                #get second tag id
                fTagID2_1 = self.vip.rpc.call(
                        'platform.actuator','get_point',
                        'iiit/cbs/smartstrip/TagID2_1').get(timeout=1)

                fTagID2_2 = self.vip.rpc.call(
                        'platform.actuator','get_point',
                        'iiit/cbs/smartstrip/TagID2_2').get(timeout=1)
                self._newTagId2 = self.recoveryTagID(fTagID2_1, fTagID2_2)
                #_log.debug('Tag 2: ' + newTagId2)

                _log.debug('Tag 1: '+ self._newTagId1 +', Tag 2: ' + self._newTagId2)

            except Exception as e:
                _log.error ('Exception: reading tag ids')
                print(e)
                pass



        #TODO: should move the relay switch on/off functionality to a new agent
        #to accommodate for more roboast control algorithms
        #(incl price point changes)
        #also might resolve some of the scheduling issues
        def processNewTagId(self, plugID, newTagId):
            #empty string
            if not newTagId:
                #do nothing
                return
            if newTagId != '7FC000007FC00000':
                #device is connected condition
                #check if current tag id is same as new, if so, do nothing
                if newTagId == self._plug_tag_id[plugID] :
                    return
                else:
                    #update the tag id and change connected state
                    self._plug_tag_id[plugID] = newTagId
                    self._plugConnected[plugID] = 1
                    if self.tagAuthorised(newTagId):
                        plug_pp_th = self._plug_pricepoint_th[plugID]
                        if self._price_point_current < plug_pp_th:
                            _log.info(('Plug {0:d}: '.format(plugID + 1),
                                    'Current price point < '
                                    'threshold {0:.2f}, '.format(plug_pp_th),
                                    'Switching-on power'))
                            self.switchRelay(plugID, RELAY_ON)
                        else:
                            _log.info(('Plug {0:d}: '.format(plugID + 1),
                                    'Current price point > threshold',
                                    '({0:.2f}), '.format(plug_pp_th),
                                    'No-power'))
                    else:
                        _log.info(('Plug {0:d}: '.format(plugID + 1),
                                'Unauthorised device connected',
                                '(tag id: ',
                                newTagId, ')'))
            else:
                #no device connected condition, new tag id is DEFAULT_TAG_ID
                if self._plugConnected[plugID] == 0:
                    return
                elif self._plugConnected[plugID] == 1 or \
                        newTagId != self._plug_tag_id[plugID] or \
                        self._plugRelayState[plugID] == RELAY_ON :
                    #update the tag id and change connected state
                    self._plug_tag_id[plugID] = newTagId
                    self._plugConnected[plugID] = 0
                    self.switchRelay(plugID, RELAY_OFF)

        @PubSub.subscribe('pubsub', topic_price_point)
        def onNewPrice(self, peer, sender, bus,  topic, headers, message):
            if sender == 'pubsub.compat':
                message = compat.unpack_legacy_message(headers, message)

            new_price_point = message[0]
            _log.debug ( "*** New Price Point: {0:.2f} ***".format(new_price_point))
            
            if self._price_point_current != new_price_point:
                self.processNewPricePoint(new_price_point)

        def processNewPricePoint(self, new_price_point):
            self._price_point_previous = self._price_point_current
            self._price_point_current = new_price_point

            self.applyPricingPolicy(PLUG_ID_1)
      
            self.applyPricingPolicy(PLUG_ID_2)

        def applyPricingPolicy(self, plugID):
            plug_pp_th = self._plug_pricepoint_th[plugID]
            if self._price_point_current > plug_pp_th: 
                if self._plugRelayState[plugID] == RELAY_ON:
                    _log.info(('Plug {0:d}: '.format(plugID + 1),
                            'Current price point > threshold',
                            '({0:.2f}), '.format(plug_pp_th),
                            'Switching-Off Power'))
                    self.switchRelay(plugID, RELAY_OFF)
                #else:
                    #do nothing
            else:
                if self._plugConnected[plugID] == 1:
                    _log.info(('Plug {0:d}: '.format(plugID + 1),
                            'Current price point < threshold',
                            '({0:.2f}), '.format(plug_pp_th),
                            'Switching-On Power'))
                    self.switchRelay(plugID, RELAY_ON)
                #else:
                    #do nothing


        def recoveryTagID(self, fTagIDPart1, fTagIDPart2):
            buff = self.convertToByteArray(fTagIDPart1, fTagIDPart2)
            tag = ''
            for i in reversed(buff):
                tag = tag + format(i, '02x')
            return tag.upper()

        def convertToByteArray(self, fltVal1, fltVal2):
            idLsb = bytearray(struct.pack('f', fltVal1))
            #for id in idLsb:
            #    print 'id: {0:02x}'.format(id)
            idMsb = bytearray(struct.pack('f', fltVal2))

            idMsb = bytearray(struct.pack('f', fltVal2))
            return (idMsb + idLsb)    


        def tagAuthorised(self, tagID):
            for authTagID in self._tag_ids :
                if tagID == authTagID:
                    return True
            return False

        @RPC.export
        def switchLedDebug(self, state):
            #_log.debug('switchLedDebug()')
            if self._ledDebugState == state:
                #_log.debug('same state, do nothing')
                return

            try: 
                start = str(datetime.datetime.now())
                end = str(datetime.datetime.now() 
                        + datetime.timedelta(milliseconds=500))

                msg = [
                        ['iiit/cbs/smartstrip',start,end]
                        ]
                result = self.vip.rpc.call(
                        'platform.actuator', 
                        'request_new_schedule',
                        agent_id, 
                        str(self._taskID_LedDebug),
                        'HIGH',
                        msg).get(timeout=1)
                #print("schedule result", result)
            except Exception as e:
                _log.error ("Exception: Could not contact actuator.", 
                        "Is it running?")
                print(e)
                pass

            try:
                if result['result'] == 'SUCCESS':
                    result = self.vip.rpc.call(
                            'platform.actuator', 
                            'set_point',
                            agent_id, 
                            'iiit/cbs/smartstrip/LEDDebug',
                            state).get(timeout=1)
                    #print("Set result", result)
                    self.updateLedDebugState(state)
            except Exception as e:
                _log.error ("Expection: setting ledDebug")
                print(e)
                pass

        @RPC.export
        def switchRelay(self, plugID, state):
            #_log.debug('switchPlug1Relay()')
            if self._plugRelayState[plugID] == state:
                _log.debug('same state, do nothing')
                return
            try: 
                start = str(datetime.datetime.now())
                end = str(datetime.datetime.now() 
                        + datetime.timedelta(milliseconds=2000))

                msg = [
                        ['iiit/cbs/smartstrip',start,end]
                        ]
                result = self.vip.rpc.call(
                        'platform.actuator', 
                        'request_new_schedule',
                        agent_id, 
                        'taskID_Plug' + str(plugID+1) + 'Relay',
                        'HIGH',
                        msg).get(timeout=1)
                print("schedule result", result)
            except Exception as e:
                _log.error ("Could not contact actuator. Is it running?")
                print(e)
                pass

            try:
                if result['result'] == 'SUCCESS':
                    result = self.vip.rpc.call(
                            'platform.actuator', 
                            'set_point',
                            agent_id, 
                            'iiit/cbs/smartstrip/Plug' + str(plugID+1) + 'Relay',
                            state).get(timeout=1)
                    #print("Set result", result)
                    #_log.debug('OK call updatePlug1RelayState()')
                    self.updatePlugRelayState(plugID, state)
            except Exception as e:
                _log.error ("Expection: setting plug 1 relay")
                print(e)
                pass

        def updateLedDebugState(self, state):
            #_log.debug('updateLedDebugState()')
            headers = { 'requesterID': agent_id, }
            ledDebug_status = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/smartstrip/LEDDebug').get(timeout=1)
            
            if state == int(ledDebug_status):
                self._ledDebugState = state
            
            if self._ledDebugState == LED_ON:
                _log.debug('Current State: LED Debug is ON!!!')
            else:
                _log.debug('Current State: LED Debug is OFF!!!')


        def updatePlugRelayState(self, plugID, state):
            #_log.debug('updatePlug1RelayState()')
            headers = { 'requesterID': agent_id, }
            relay_status = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/smartstrip/Plug' + str(plugID+1) + 'Relay').get(timeout=1)

            if state == int(relay_status):
                self._plugRelayState[plugID] = state
                
            if self._plugRelayState[plugID] == RELAY_ON:
                _log.debug('Current State: Plug ' + str(plugID+1) + ' Relay Switched ON!!!')
            else:
                _log.debug('Current State: Plug ' + str(plugID+1) + ' Relay Switched OFF!!!')


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

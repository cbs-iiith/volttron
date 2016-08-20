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
RELAY_ON = 1
RELAY_OFF = 0
PLUG_ID_1 = 0
PLUG_ID_2 = 1
DEFAULT_TAG_ID = '7FC000007FC00000'
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

def smartstrip(config_path, **kwargs):
    config = utils.load_config(config_path)
    vip_identity = config.get('vip_identity', 'iiit.smartstrip')
    # This agent needs to be named iiit.smartstrip. Pop the uuid id off the kwargs
    kwargs.pop('identity', None)

    Agent.__name__ = 'SmartStrip_Agent'
    return SmartStrip(config_path, identity=vip_identity, **kwargs)

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

    def __init__(self, config_path, **kwargs):
        super(SmartStrip, self).__init__(**kwargs)
        _log.debug("vip_identity: " + self.core.identity)

        self.config = utils.load_config(config_path)
        self._configGetPoints()
        self._configGetInitValues()

    @Core.receiver('onsetup')
    def setup(self, sender, **kwargs):
        _log.info(self.config['message'])
        self._agent_id = self.config['agentid']

    @Core.receiver('onstart')            
    def startup(self, sender, **kwargs):
        self.runSmartStripTest()
        self.switchLedDebug(LED_ON)
        
        #perodically read the meter data & connected tag ids from h/w
        self.core.periodic(self._period_read_data, self.getData, wait=None)
        
        self.publishThresholdPP(PLUG_ID_1,
                                self._plug_pricepoint_th[PLUG_ID_1])
        self.publishThresholdPP(PLUG_ID_2,
                                self._plug_pricepoint_th[PLUG_ID_2])
        
        self.vip.rpc.call(MASTER_WEB, 'register_agent_route',
                      r'^/SmartStrip',
                      self.core.identity,
                      "rpc_from_net").get(timeout=30)   

    @Core.receiver('onstop')
    def onstop(self, sender, **kwargs):
        _log.debug('onstop()')
        self.switchLedDebug(LED_OFF)
        self.switchRelay(PLUG_ID_1, RELAY_OFF, SCHEDULE_NOT_AVLB)
        self.switchRelay(PLUG_ID_2, RELAY_OFF, SCHEDULE_NOT_AVLB)
        return

    @Core.receiver('onfinish')
    def onfinish(self, sender, **kwargs):
        #_log.debug('onfinish()')
        #self.switchLedDebug(LED_OFF)
        #self.switchRelay(PLUG_ID_1, RELAY_OFF, SCHEDULE_NOT_AVLB)
        #self.switchRelay(PLUG_ID_2, RELAY_OFF, SCHEDULE_NOT_AVLB)
        return
        
    def _configGetInitValues(self):
        self._tag_ids = self.config['tag_ids']
        self._period_read_data = self.config['period_read_data']
        self._price_point_previous = self.config['default_base_price']
        self._price_point_current = self.config['default_base_price']
        self._plug_pricepoint_th = self.config['plug_pricepoint_th']

    def _configGetPoints(self):
        self.topic_price_point= self.config.get('topic_price_point',
                                            'prices/PricePoint')
        self.plug1_meterData_all_point = self.config.get('plug1_meterData_all_point',
                                            'smartstrip/plug1/meterdata/all')
        self.plug2_meterData_all_point = self.config.get('plug2_meterData_all_point',
                                            'smartstrip/plug2/meterdata/all')
        self.plug1_relayState_point = self.config.get('plug1_relayState_point',
                                            'smartstrip/plug1/relaystate')
        self.plug2_relayState_point = self.config.get('plug2_relayState_point',
                                            'smartstrip/plug2/relaystate')
        self.plug1_thresholdPP_point = self.config.get('plug1_thresholdPP_point',
                                            'smartstrip/plug1/threshold')
        self.plug2_thresholdPP_point = self.config.get('plug2_thresholdPP_point',
                                            'smartstrip/plug2/threshold')
        self.plug1_tagId_point = self.config.get('plug1_tagId_point',
                                            'smartstrip/plug1/tagid')
        self.plug2_tagId_point = self.config.get('plug2_thresholdPP_point',
                                            'smartstrip/plug2/tagid')

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
        self.switchRelay(PLUG_ID_1, RELAY_ON, SCHEDULE_NOT_AVLB)
        time.sleep(1)
        _log.debug('switch off relay 1')
        self.switchRelay(PLUG_ID_1, RELAY_OFF, SCHEDULE_NOT_AVLB)

        _log.debug('switch on relay 2')
        self.switchRelay(PLUG_ID_2, RELAY_ON, SCHEDULE_NOT_AVLB)
        time.sleep(1)
        _log.debug('switch off relay 2')
        self.switchRelay(PLUG_ID_2, RELAY_OFF, SCHEDULE_NOT_AVLB)
        _log.debug("EOF Testing")

    def getData(self):
        #_log.debug('getData()...')
        result = []
        
        #get schedule
        try: 
            start = str(datetime.datetime.now())
            end = str(datetime.datetime.now() 
                    + datetime.timedelta(seconds=6))

            msg = [
                    ['iiit/cbs/smartstrip',start,end]
                    ]
            result = self.vip.rpc.call(
                    'platform.actuator', 
                    'request_new_schedule',
                    self._agent_id, 
                    'schdl_getData_low_preempt',
                    'LOW_PREEMPT',
                    msg).get(timeout=1)
        except Exception as e:
            _log.exception ("Could not contact actuator. Is it running?")
            #print(e)
            return

        #run the task
        if result['result'] == 'SUCCESS':

            #_log.debug('meterData()')
            if self._plugRelayState[PLUG_ID_1] == RELAY_ON:
                self.readMeterData(PLUG_ID_1)

            if self._plugRelayState[PLUG_ID_2] == RELAY_ON:
                self.readMeterData(PLUG_ID_2)
                
            self.readTagIDs()
            
            #cancel the schedule
            
            #_log.debug('...getData()')
            
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
            pubTopic = self.plug1_meterData_all_point
        elif plugID == PLUG_ID_2:
            pointVolatge = 'Plug2Voltage'
            pointCurrent = 'Plug2Current'
            pointActivePower = 'Plug2ActivePower'
            pubTopic = self.plug2_meterData_all_point
        else:
            return

        #
        try:
            fVolatge = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/smartstrip/' + \
                    pointVolatge).get(timeout=2)
            #_log.debug('voltage: {0:.2f}'.format(fVolatge))
            fCurrent = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    ('iiit/cbs/smartstrip/' + \
                    pointCurrent)).get(timeout=2)
            #_log.debug('current: {0:.2f}'.format(fCurrent))
            fActivePower = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/smartstrip/' + \
                    pointActivePower).get(timeout=2)
            #_log.debug('active: {0:.2f}'.format(fActivePower))

            #TODO: temp fix, need to move this to backend code
            if fVolatge > 80000:
                fVolatge = 0.0
            if fCurrent > 80000:
                fCurrent = 0.0
            if fActivePower > 80000:
                fActivePower = 0.0
                
            #publish data to volttron bus
            self.publishMeterData(pubTopic, fVolatge, fCurrent, fActivePower)

            _log.info(('Plug {0:d}: '.format(plugID + 1)
                    + 'voltage: {0:.2f}'.format(fVolatge) 
                    + ', Current: {0:.2f}'.format(fCurrent)
                    + ', ActivePower: {0:.2f}'.format(fActivePower)
                    ))
            #release the time schedule, if we finish early.
        except Exception as e:
            _log.exception ("Expection: exception in readMeterData()")
            #print(e)
            return

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
            newTagId1 = ''
            newTagId2 = ''
            
            fTagID1_1 = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/smartstrip/TagID1_1').get(timeout=2)

            fTagID1_2 = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/smartstrip/TagID1_2').get(timeout=2)
            self._newTagId1 = self.recoveryTagID(fTagID1_1, fTagID1_2)
            #_log.debug('Tag 1: ' + newTagId1)

            #get second tag id
            fTagID2_1 = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/smartstrip/TagID2_1').get(timeout=2)

            fTagID2_2 = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/smartstrip/TagID2_2').get(timeout=2)
            self._newTagId2 = self.recoveryTagID(fTagID2_1, fTagID2_2)
            #_log.debug('Tag 2: ' + newTagId2)

            _log.debug('Tag 1: '+ self._newTagId1 +', Tag 2: ' + self._newTagId2)

        except Exception as e:
            _log.exception ("Exception: reading tag ids")
            #print(e)
            return



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
                self.publishTagId(plugID, newTagId)
                self._plugConnected[plugID] = 1
                if self.tagAuthorised(newTagId):
                    plug_pp_th = self._plug_pricepoint_th[plugID]
                    if self._price_point_current < plug_pp_th:
                        _log.info(('Plug {0:d}: '.format(plugID + 1),
                                'Current price point < '
                                'threshold {0:.2f}, '.format(plug_pp_th),
                                'Switching-on power'))
                        self.switchRelay(plugID, RELAY_ON, SCHEDULE_AVLB)
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
                    self.publishTagId(plugID, newTagId)

        else:
            #no device connected condition, new tag id is DEFAULT_TAG_ID
            if self._plugConnected[plugID] == 0:
                return
            elif self._plugConnected[plugID] == 1 or \
                    newTagId != self._plug_tag_id[plugID] or \
                    self._plugRelayState[plugID] == RELAY_ON :
                #update the tag id and change connected state
                self._plug_tag_id[plugID] = newTagId
                self.publishTagId(plugID, newTagId)
                self._plugConnected[plugID] = 0
                self.switchRelay(plugID, RELAY_OFF, SCHEDULE_AVLB)

    #@PubSub.subscribe('pubsub', self.topic_price_point)
    @PubSub.subscribe('pubsub','prices/PricePoint')
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
                self.switchRelay(plugID, RELAY_OFF, SCHEDULE_NOT_AVLB)
            #else:
                #do nothing
        else:
            if self._plugConnected[plugID] == 1:
                _log.info(('Plug {0:d}: '.format(plugID + 1),
                        'Current price point < threshold',
                        '({0:.2f}), '.format(plug_pp_th),
                        'Switching-On Power'))
                self.switchRelay(plugID, RELAY_ON, SCHEDULE_NOT_AVLB)
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
    def setThresholdPP(self, plugID, newThreshold):
        _log.debug('setThresholdPP()')
        if self._plug_pricepoint_th[plugID] != newThreshold:
            _log.debug(('Changining Threshold: Plug ',
                        str(plugID+1), ' : ', newThreshold))
            self._plug_pricepoint_th[plugID] = newThreshold
            self.publishThresholdPP(plugID, newThreshold)
        return 'success'
    
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
                    ['iiit/cbs/smartstrip',start,end]
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
                        'iiit/cbs/smartstrip/LEDDebug',
                        state).get(timeout=1)
                #print("Set result", result)
                self.updateLedDebugState(state)
        except Exception as e:
            _log.exception ("Expection: setting ledDebug")
            #print(e)
            return

    def switchRelay(self, plugID, state, schdExist):
        #_log.debug('switchPlug1Relay()')

        if self._plugRelayState[plugID] == state:
            _log.debug('same state, do nothing')
            return

        if schdExist == SCHEDULE_AVLB: 
            self.rpc_switchRelay(plugID, state);
        elif schdExist == SCHEDULE_NOT_AVLB:
            try: 
                start = str(datetime.datetime.now())
                end = str(datetime.datetime.now() 
                        + datetime.timedelta(milliseconds=600))

                msg = [
                        ['iiit/cbs/smartstrip',start,end]
                        ]
                result = self.vip.rpc.call(
                        'platform.actuator', 
                        'request_new_schedule',
                        self._agent_id, 
                        'taskID_Plug' + str(plugID+1) + 'Relay',
                        'HIGH',
                        msg).get(timeout=1)
                #print("schedule result", result)
            except Exception as e:
                _log.exception ("Could not contact actuator. Is it running?")
                #print(e)
                return

            try:
                if result['result'] == 'SUCCESS':
                    self.rpc_switchRelay(plugID, state)
            except Exception as e:
                _log.exception ("Expection: setting plug 1 relay")
                #print(e)
                return
        else:
            #do notthing
            return
        return

    def rpc_switchRelay(self, plugID, state):
        result = self.vip.rpc.call(
                'platform.actuator', 
                'set_point',
                self._agent_id, 
                'iiit/cbs/smartstrip/Plug' + str(plugID+1) + 'Relay',
                state).get(timeout=1)
        #print("Set result", result)
        #_log.debug('OK call updatePlug1RelayState()')
        self.updatePlugRelayState(plugID, state)
        return

    def updateLedDebugState(self, state):
        #_log.debug('updateLedDebugState()')
        headers = { 'requesterID': self._agent_id, }
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
        headers = { 'requesterID': self._agent_id, }
        relay_status = self.vip.rpc.call(
                'platform.actuator','get_point',
                'iiit/cbs/smartstrip/Plug' + str(plugID+1) + 'Relay').get(timeout=1)

        if state == int(relay_status):
            self._plugRelayState[plugID] = state
            self.publishRelayState(plugID, state)
            
        if self._plugRelayState[plugID] == RELAY_ON:
            _log.debug('Current State: Plug ' + str(plugID+1) + ' Relay Switched ON!!!')
        else:
            _log.debug('Current State: Plug ' + str(plugID+1) + ' Relay Switched OFF!!!')

    def publishMeterData(self, pubTopic, fVolatge, fCurrent, fActivePower):
        pubMsg = [{'voltage':fVolatge, 'current':fCurrent,
                    'active_power':fActivePower},
                    {'voltage':{'units': 'V', 'tz': 'UTC', 'type': 'float'},
                    'current':{'units': 'A', 'tz': 'UTC', 'type': 'float'},
                    'active_power':{'units': 'mW', 'tz': 'UTC', 'type': 'float'}
                    }]
        self.publishToBus(pubTopic, pubMsg)

    def publishTagId(self, plugID, newTagId):
        if plugID == PLUG_ID_1:
            pubTopic = self.plug1_tagId_point
        elif plugID == PLUG_ID_2:
            pubTopic = self.plug2_tagId_point
        else:
            return
        pubMsg = [newTagId,{'units': '', 'tz': 'UTC', 'type': 'string'}]
        self.publishToBus(pubTopic, pubMsg)
            
    def publishRelayState(self, plugID, state):
        if plugID == PLUG_ID_1:
            pubTopic = self.plug1_relayState_point
        elif plugID == PLUG_ID_2:
            pubTopic = self.plug2_relayState_point
        else:
            return
        pubMsg = [state,{'units': 'On/Off', 'tz': 'UTC', 'type': 'int'}]
        self.publishToBus(pubTopic, pubMsg)
            
    def publishThresholdPP(self, plugID, thresholdPP):
        if plugID == PLUG_ID_1:
            pubTopic = self.plug1_thresholdPP_point
        elif plugID == PLUG_ID_2:
            pubTopic = self.plug2_thresholdPP_point
        else:
            return
        pubMsg = [thresholdPP,
                    {'units': 'cents', 'tz': 'UTC', 'type': 'float'}]
        self.publishToBus(pubTopic, pubMsg)
            
    def publishToBus(self, pubTopic, pubMsg):
        now = datetime.datetime.utcnow().isoformat(' ') + 'Z'
        headers = {headers_mod.DATE: now}          
        #Publish messages
        self.vip.pubsub.publish('pubsub', pubTopic, headers, pubMsg).get(timeout=5)
        
    @RPC.export
    def rpc_from_net(self, header, message):
        print(message)
        return self.processMessage(message)

    def processMessage(self, message):
        _log.debug('processResponse()')
        result = 'FAILED'
        try:
            rpcdata = jsonrpc.JsonRpcData.parse(message)
            _log.info('rpc method: {}'.format(rpcdata.method))
            
            if rpcdata.method == "rpc_setPlugThPP":
                args = {'plugID': rpcdata.params['plugID'], 
                        'newThreshold': rpcdata.params['newThreshold']
                        }
                result = self.setThresholdPP(**args)
            else:
                return jsonrpc.json_error('NA', METHOD_NOT_FOUND,
                    'Invalid method {}'.format(rpcdata.method))
                    
            return jsonrpc.json_result(rpcdata.id, result)
            
        except AssertionError:
            print('AssertionError')
            return jsonrpc.json_error('NA', INVALID_REQUEST,
                    'Invalid rpc data {}'.format(data))
        except Exception as e:
            print(e)
            return jsonrpc.json_error('NA', UNHANDLED_EXCEPTION, e)



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

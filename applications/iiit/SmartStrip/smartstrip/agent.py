# -*- coding: utf-8 -*- {{{
# vim: set fenc=utf-8 ft=python sw=4 ts=4 sts=4 et:
#
# Copyright (c) 2019, Sam Babu, Godithi.
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

from random import randint

import settings

import time
import struct
import gevent
import gevent.event

LED_ON = 1
LED_OFF = 0
RELAY_ON = 1
RELAY_OFF = 0
PLUG_ID_1 = 0
PLUG_ID_2 = 1
PLUG_ID_3 = 2
PLUG_ID_4 = 3
DEFAULT_TAG_ID = '7FC000007FC00000'
SCHEDULE_AVLB = 1
SCHEDULE_NOT_AVLB = 0

# smartstrip base peak energy (200mA * 12V)
SMARTSTRIP_BASE_ENERGY = 2

utils.setup_logging()
_log = logging.getLogger(__name__)
__version__ = '0.2'

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

class SmartStrip(Agent):
    '''Smart Strip with 2 plug
    '''
    _taskID_LedDebug = 1
    _taskID_Plug1Relay = 2
    _taskID_Plug2Relay = 3
    _taskID_ReadTagIDs = 4
    _taskID_ReadMeterData = 5

    _ledDebugState = 0
    _plugRelayState = [0, 0, 0, 0]
    _plugConnected = [ 0, 0, 0, 0]
    _plugActivePwr = [0.0, 0.0, 0.0, 0.0]
    _plug_tag_id = ['7FC000007FC00000', '7FC000007FC00000', '7FC000007FC00000', '7FC000007FC00000']
    _plug_pricepoint_th = [0.35, 0.5, 0.75, 0.95]
    _price_point_previous = 0.4 
    _price_point_current = 0.4 
    _price_point_new = 0.45

    _newTagId1 = ''
    _newTagId2 = ''
    _newTagId3 = ''
    _newTagId4 = ''

    #smartstrip total energy demand
    _ted = SMARTSTRIP_BASE_ENERGY


    def __init__(self, config_path, **kwargs):
        super(SmartStrip, self).__init__(**kwargs)
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
        _log.info("yeild 30s for volttron platform to initiate properly...")
        time.sleep(30) #yeild for a movement
        _log.info("Starting SmartStrip...")

        self.runSmartStripTest()
        self.switchLedDebug(LED_ON)

        #perodically read the meter data & connected tag ids from h/w
        self.core.periodic(self._period_read_data, self.getData, wait=None)

        #perodically publish plug threshold price point to volttron bus
        self.core.periodic(self._period_read_data, self.publishPlugThPP, wait=None)

        #perodically publish total energy demand to volttron bus
        self.core.periodic(self._period_read_data, self.publishTed, wait=None)
        
        #perodically process new pricing point
        self.core.periodic(10, self.processNewPricePoint, wait=None)
        

        #subscribing to topic_price_point
        self.vip.pubsub.subscribe("pubsub", self.topic_price_point, self.onNewPrice)

        self.vip.rpc.call(MASTER_WEB, 'register_agent_route',
                      r'^/SmartStrip',
                      "rpc_from_net").get(timeout=10)
        return

    @Core.receiver('onstop')
    def onstop(self, sender, **kwargs):
        _log.debug('onstop()')
        self.switchLedDebug(LED_OFF)
        self.switchRelay(PLUG_ID_1, RELAY_OFF, SCHEDULE_NOT_AVLB)
        self.switchRelay(PLUG_ID_2, RELAY_OFF, SCHEDULE_NOT_AVLB)
        self.switchRelay(PLUG_ID_3, RELAY_OFF, SCHEDULE_NOT_AVLB)
        self.switchRelay(PLUG_ID_4, RELAY_OFF, SCHEDULE_NOT_AVLB)

        _log.debug('un registering rpc routes')
        self.vip.rpc.call(MASTER_WEB, 'unregister_all_agent_routes').get(timeout=10)
        return

    @Core.receiver('onfinish')
    def onfinish(self, sender, **kwargs):
        _log.debug('onfinish()')
        #self.switchLedDebug(LED_OFF)
        #self.switchRelay(PLUG_ID_1, RELAY_OFF, SCHEDULE_NOT_AVLB)
        #self.switchRelay(PLUG_ID_2, RELAY_OFF, SCHEDULE_NOT_AVLB)
        #self.switchRelay(PLUG_ID_3, RELAY_OFF, SCHEDULE_NOT_AVLB)
        #self.switchRelay(PLUG_ID_4, RELAY_OFF, SCHEDULE_NOT_AVLB)
        return

    def _configGetInitValues(self):
        self._tag_ids = self.config['tag_ids']
        self._period_read_data = self.config['period_read_data']
        self._price_point_previous = self.config['default_base_price']
        self._price_point_current = self.config['default_base_price']
        self._plug_pricepoint_th = self.config['plug_pricepoint_th']
        return

    def _configGetPoints(self):
        self.root_topic              = self.config.get('topic_root', 'smartstrip')
        self.energyDemand_topic     = self.config.get('topic_energy_demand', \
                                            'smartstrip/energydemand')
        self.topic_price_point      = self.config.get('topic_price_point', \
                                            'topic_price_point')
        return

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

        self.testRelays()
        
        _log.debug('switch off debug led')
        self.switchLedDebug(LED_OFF)
        _log.debug("EOF Testing")

        return

    def testRelays(self):
        result = {}
        #get schedule for testing relays
        task_id = str(randint(0, 99999999))
        #_log.debug("task_id: " + task_id)
        result = self._getTaskSchedule(task_id)

        #test all four relays
        if result['result'] == 'SUCCESS':
            _log.debug('switch on relay 1')
            self.switchRelay(PLUG_ID_1, RELAY_ON, True)
            time.sleep(1)
            _log.debug('switch off relay 1')
            self.switchRelay(PLUG_ID_1, RELAY_OFF, SCHEDULE_AVLB)

            _log.debug('switch on relay 2')
            self.switchRelay(PLUG_ID_2, RELAY_ON, SCHEDULE_AVLB)
            time.sleep(1)
            _log.debug('switch off relay 2')
            self.switchRelay(PLUG_ID_2, RELAY_OFF, SCHEDULE_AVLB)
            
            _log.debug('switch on relay 3')
            self.switchRelay(PLUG_ID_3, RELAY_ON, SCHEDULE_AVLB)
            time.sleep(1)
            _log.debug('switch off relay 3')
            self.switchRelay(PLUG_ID_3, RELAY_OFF, SCHEDULE_AVLB)

            _log.debug('switch on relay 4')
            self.switchRelay(PLUG_ID_4, RELAY_ON, SCHEDULE_AVLB)
            time.sleep(1)
            _log.debug('switch off relay 4')
            self.switchRelay(PLUG_ID_4, RELAY_OFF, SCHEDULE_AVLB)
            
            #cancel the schedule
            self._cancelSchedule(task_id)
        return

    def publishPlugThPP(self):
        self.publishThresholdPP(PLUG_ID_1,
                                self._plug_pricepoint_th[PLUG_ID_1])
        self.publishThresholdPP(PLUG_ID_2,
                                self._plug_pricepoint_th[PLUG_ID_2])
        self.publishThresholdPP(PLUG_ID_3,
                                self._plug_pricepoint_th[PLUG_ID_3])
        self.publishThresholdPP(PLUG_ID_4,
                                self._plug_pricepoint_th[PLUG_ID_4])
        return

    def getData(self):
        #_log.debug('getData()...')
        result = {}

        #get schedule for to h/w latest data
        task_id = str(randint(0, 99999999))
        #_log.debug("task_id: " + task_id)
        result = self._getTaskSchedule(task_id)

        #run the task
        if result['result'] == 'SUCCESS':

            #_log.debug('meterData()')
            if self._plugRelayState[PLUG_ID_1] == RELAY_ON:
                self.readMeterData(PLUG_ID_1)

            if self._plugRelayState[PLUG_ID_2] == RELAY_ON:
                self.readMeterData(PLUG_ID_2)

            if self._plugRelayState[PLUG_ID_3] == RELAY_ON:
                self.readMeterData(PLUG_ID_3)

            if self._plugRelayState[PLUG_ID_4] == RELAY_ON:
                self.readMeterData(PLUG_ID_4)

            #_log.debug('...readTagIDs()')
            self.readTagIDs()

            #_log.debug('start processNewTagId()...')
            self.processNewTagId(PLUG_ID_1, self._newTagId1)
            self.processNewTagId(PLUG_ID_2, self._newTagId2)
            self.processNewTagId(PLUG_ID_3, self._newTagId3)
            self.processNewTagId(PLUG_ID_4, self._newTagId4)
            #_log.debug('...done processNewTagId()')

            #cancel the schedule
            self._cancelSchedule(task_id)
        return

    def readMeterData(self, plugID):
        #_log.debug ('readMeterData(), plugID: ' + str(plugID))
        if plugID not in [PLUG_ID_1, PLUG_ID_2, PLUG_ID_3, PLUG_ID_4]:
            return

        pointVolatge = 'Plug'+str(plugID+1)+'Voltage'
        pointCurrent = 'Plug'+str(plugID+1)+'Current'
        pointActivePower = 'Plug'+str(plugID+1)+'ActivePower'
        pubTopic = self.root_topic + '/plug' + str(plugID+1) + '/meterdata/all'

        try:
            fVolatge = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/smartstrip/' + \
                    pointVolatge).get(timeout=10)
            #_log.debug('voltage: {0:.2f}'.format(fVolatge))
            fCurrent = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    ('iiit/cbs/smartstrip/' + \
                    pointCurrent)).get(timeout=10)
            #_log.debug('current: {0:.2f}'.format(fCurrent))
            fActivePower = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/smartstrip/' + \
                    pointActivePower).get(timeout=10)
            #_log.debug('active: {0:.2f}'.format(fActivePower))

            #keep track of plug active power
            self._plugActivePwr[plugID] = fActivePower
            
            #publish data to volttron bus
            self.publishMeterData(pubTopic, fVolatge, fCurrent, fActivePower)

            _log.info(('Plug {0:d}: '.format(plugID + 1)
                    + 'voltage: {0:.2f}'.format(fVolatge) 
                    + ', Current: {0:.2f}'.format(fCurrent)
                    + ', ActivePower: {0:.2f}'.format(fActivePower)
                    ))
        except gevent.Timeout:
            _log.exception("Expection: gevent.Timeout in readMeterData()")
            return
        except Exception as e:
            _log.exception ("Expection: exception in readMeterData()")
            print(e)
            return
        return

    def readTagIDs(self):
        #_log.debug('readTagIDs()')
        self._newTagId1 = ''
        self._newTagId2 = ''
        self._newTagId3 = ''
        self._newTagId4 = ''

        try:
            '''
            Smart Strip bacnet server splits the 64 bit tag id 
            into two parts and sends them accros as two float values.
            Hence need to get both the points (floats value)
            and recover the actual tag id
            '''
            newTagId1 = ''
            newTagId2 = ''
            newTagId3 = ''
            newTagId4 = ''

            fTagID1_1 = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/smartstrip/TagID1_1').get(timeout=10)

            fTagID1_2 = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/smartstrip/TagID1_2').get(timeout=10)
            self._newTagId1 = self.recoveryTagID(fTagID1_1, fTagID1_2)
            #_log.debug('Tag 1: ' + newTagId1)

            #get second tag id
            fTagID2_1 = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/smartstrip/TagID2_1').get(timeout=10)

            fTagID2_2 = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/smartstrip/TagID2_2').get(timeout=10)
            self._newTagId2 = self.recoveryTagID(fTagID2_1, fTagID2_2)
            #_log.debug('Tag 2: ' + newTagId2)

            #get third tag id
            fTagID3_1 = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/smartstrip/TagID3_1').get(timeout=10)

            fTagID3_2 = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/smartstrip/TagID3_2').get(timeout=10)
            self._newTagId3 = self.recoveryTagID(fTagID3_1, fTagID3_2)
            #_log.debug('Tag 3: ' + newTagId3)

            #get fourth tag id
            fTagID4_1 = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/smartstrip/TagID4_1').get(timeout=10)

            fTagID4_2 = self.vip.rpc.call(
                    'platform.actuator','get_point',
                    'iiit/cbs/smartstrip/TagID4_2').get(timeout=10)
            self._newTagId4 = self.recoveryTagID(fTagID4_1, fTagID4_2)
            #_log.debug('Tag 4: ' + newTagId4)

            _log.info('Tag 1: '+ self._newTagId1 +', Tag 2: ' + self._newTagId2 + ', Tag 3: '+ self._newTagId3 +', Tag 4: ' + self._newTagId4)

        except gevent.Timeout:
            _log.exception("Expection: gevent.Timeout in readTagIDs()")
            return
        except Exception as e:
            _log.exception ("Exception: reading tag ids")
            print(e)
            return
        return

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
        return

    def onNewPrice(self, peer, sender, bus,  topic, headers, message):
        if sender == 'pubsub.compat':
            message = compat.unpack_legacy_message(headers, message)

        new_price_point = message[0]
        #_log.info ( "*** New Price Point: {0:.2f} ***".format(new_price_point))

        self._price_point_new = new_price_point
        
        if self._price_point_current != new_price_point:
        #if True:
            self.processNewPricePoint()
        return
        
    def processNewPricePoint(self):
        if self._price_point_current != self._price_point_new:
            _log.info ( "*** New Price Point: {0:.2f} ***".format(self._price_point_new))
            result = {}
            #get schedule for testing relays
            task_id = str(randint(0, 99999999))
            #_log.debug("task_id: " + task_id)
            result = self._getTaskSchedule(task_id)
            
            if result['result'] == 'SUCCESS':
                self._price_point_previous = self._price_point_current
                self._price_point_current = self._price_point_new

                self.applyPricingPolicy(PLUG_ID_1, SCHEDULE_AVLB)
                self.applyPricingPolicy(PLUG_ID_2, SCHEDULE_AVLB)
                self.applyPricingPolicy(PLUG_ID_3, SCHEDULE_AVLB)
                self.applyPricingPolicy(PLUG_ID_4, SCHEDULE_AVLB)
            else :
                _log.error("unable to processNewPricePoint()")
                
            #cancel the schedule
            self._cancelSchedule(task_id)
        return

    def applyPricingPolicy(self, plugID, schdExist):
        plug_pp_th = self._plug_pricepoint_th[plugID]
        if self._price_point_current > plug_pp_th: 
            if self._plugRelayState[plugID] == RELAY_ON:
                _log.info(('Plug {0:d}: '.format(plugID + 1),
                        'Current price point > threshold',
                        '({0:.2f}), '.format(plug_pp_th),
                        'Switching-Off Power'))
                self.switchRelay(plugID, RELAY_OFF, schdExist)
            #else:
                #do nothing
        else:
            if self._plugConnected[plugID] == 1 and self.tagAuthorised(self._plug_tag_id[plugID]):
                _log.info(('Plug {0:d}: '.format(plugID + 1),
                        'Current price point < threshold',
                        '({0:.2f}), '.format(plug_pp_th),
                        'Switching-On Power'))
                self.switchRelay(plugID, RELAY_ON, schdExist)
            #else:
                #do nothing
        return

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
            _log.info(('Changing Threshold: Plug ',
                        str(plugID+1), ' : ', newThreshold))
            self._plug_pricepoint_th[plugID] = newThreshold
            self.publishThresholdPP(plugID, newThreshold)
        return 'success'

    def switchLedDebug(self, state):
        _log.debug('switchLedDebug()')
        #result = {}

        if self._ledDebugState == state:
            _log.info('same state, do nothing')
            return

        #get schedule to switchLedDebug
        task_id = str(randint(0, 99999999))
        #_log.debug("task_id: " + task_id)
        result = self._getTaskSchedule(task_id)

        if result['result'] == 'SUCCESS':
            result = {}
            try:
                #_log.debug('schl avlb')
                result = self.vip.rpc.call(
                        'platform.actuator', 
                        'set_point',
                        self._agent_id, 
                        'iiit/cbs/smartstrip/LEDDebug',
                        state).get(timeout=10)

                self.updateLedDebugState(state)
            except gevent.Timeout:
                _log.exception("Expection: gevent.Timeout in switchLedDebug()")
                return
            except Exception as e:
                _log.exception ("Expection: setting ledDebug")
                #print(e)
                return
            finally:
                #cancel the schedule
                self._cancelSchedule(task_id)
        return

    def switchRelay(self, plugID, state, schdExist):
        #_log.debug('switchPlug1Relay()')

        if self._plugRelayState[plugID] == state:
            _log.debug('same state, do nothing')
            return

        if schdExist == SCHEDULE_AVLB: 
            self.rpc_switchRelay(plugID, state);
        elif schdExist == SCHEDULE_NOT_AVLB:
            #get schedule to switchRelay
            task_id = str(randint(0, 99999999))
            #_log.debug("task_id: " + task_id)
            result = self._getTaskSchedule(task_id)

            if result['result'] == 'SUCCESS':
                try:
                    self.rpc_switchRelay(plugID, state)

                except gevent.Timeout:
                    _log.exception("Expection: gevent.Timeout in switchRelay()")
                    return
                except Exception as e:
                    _log.exception ("Expection: setting plug" + str(plugID) + " relay")
                    print(e)
                    return
                finally:
                    #cancel the schedule
                    self._cancelSchedule(task_id)
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
                state).get(timeout=10)
        
        #_log.debug('OK call updatePlug1RelayState()')
        self.updatePlugRelayState(plugID, state)
        return

    def updateLedDebugState(self, state):
        _log.debug('updateLedDebugState()')
        headers = { 'requesterID': self._agent_id, }
        ledDebug_status = self.vip.rpc.call(
                'platform.actuator','get_point',
                'iiit/cbs/smartstrip/LEDDebug').get(timeout=10)

        if state == int(ledDebug_status):
            self._ledDebugState = state

        if self._ledDebugState == LED_ON:
            _log.info('Current State: LED Debug is ON!!!')
        else:
            _log.info('Current State: LED Debug is OFF!!!')

    def updatePlugRelayState(self, plugID, state):
        #_log.debug('updatePlug1RelayState()')
        headers = { 'requesterID': self._agent_id, }
        relay_status = self.vip.rpc.call(
                'platform.actuator','get_point',
                'iiit/cbs/smartstrip/Plug' + str(plugID+1) + 'Relay').get(timeout=10)

        if state == int(relay_status):
            self._plugRelayState[plugID] = state
            self.publishRelayState(plugID, state)

        if self._plugRelayState[plugID] == RELAY_ON:
            _log.info('Current State: Plug ' + str(plugID+1) + ' Relay Switched ON!!!')
        else:
            _log.info('Current State: Plug ' + str(plugID+1) + ' Relay Switched OFF!!!')

    def publishMeterData(self, pubTopic, fVolatge, fCurrent, fActivePower):
        pubMsg = [{'voltage':fVolatge, 'current':fCurrent,
                    'active_power':fActivePower},
                    {'voltage':{'units': 'V', 'tz': 'UTC', 'type': 'float'},
                    'current':{'units': 'A', 'tz': 'UTC', 'type': 'float'},
                    'active_power':{'units': 'W', 'tz': 'UTC', 'type': 'float'}
                    }]
        self.publishToBus(pubTopic, pubMsg)

    def publishTagId(self, plugID, newTagId):
        if not self._validPlugId(plugID):
            return

        pubTopic = self.root_topic+"/plug"+str(plugID+1)+"/tagid"
        pubMsg = [newTagId,{'units': '', 'tz': 'UTC', 'type': 'string'}]
        self.publishToBus(pubTopic, pubMsg)

    def publishRelayState(self, plugID, state):
        if not self._validPlugId(plugID):
            return

        pubTopic = self.root_topic+"/plug" + str(plugID+1) + "/relaystate"
        pubMsg = [state,{'units': 'On/Off', 'tz': 'UTC', 'type': 'int'}]
        self.publishToBus(pubTopic, pubMsg)

    def publishThresholdPP(self, plugID, thresholdPP):
        if not self._validPlugId(plugID):
            return

        pubTopic = self.root_topic+"/plug" + str(plugID+1) + "/threshold"
        pubMsg = [thresholdPP,
                    {'units': 'cents', 'tz': 'UTC', 'type': 'float'}]
        self.publishToBus(pubTopic, pubMsg)

    def publishToBus(self, pubTopic, pubMsg):
        #_log.debug('_publishToBus()')
        now = datetime.datetime.utcnow().isoformat(' ') + 'Z'
        headers = {headers_mod.DATE: now}

        #Publish messages
        try:
            self.vip.pubsub.publish('pubsub', pubTopic, headers, pubMsg).get(timeout=10)
        except gevent.Timeout:
            _log.warning("Expection: gevent.Timeout in _publishToBus()")
            return
        except Exception as e:
            _log.warning("Expection: _publishToBus?")
            return
        return

    @RPC.export
    def rpc_from_net(self, header, message):
        _log.debug(message)
        return self._processMessage(message)

    def _processMessage(self, message):
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
            elif rpcdata.method == "rpc_ping":
                result = True
            else:
                return jsonrpc.json_error('NA', METHOD_NOT_FOUND,
                    'Invalid method {}'.format(rpcdata.method))

            return jsonrpc.json_result(rpcdata.id, result)

        except KeyError as ke:
            print(ke)
            return jsonrpc.json_error('NA', INVALID_PARAMS,
                    'Invalid params {}'.format(rpcdata.params))
        except AssertionError:
            print('AssertionError')
            return jsonrpc.json_error('NA', INVALID_REQUEST,
                    'Invalid rpc data {}'.format(data))
        except Exception as e:
            print(e)
            return jsonrpc.json_error('NA', UNHANDLED_EXCEPTION, e)

    #calculate the total energy demand (TED)
    def _calculateTed(self):
        #_log.debug('_calculateTed()')

        ted = SMARTSTRIP_BASE_ENERGY
        for idx, plugState in enumerate(self._plugRelayState):
            if plugState == RELAY_ON:
                ted = ted + self._plugActivePwr[idx]

        return ted

    def publishTed(self):
        #_log.debug('publishTed()')

        ted = self._calculateTed()

        '''
        #only publish if change in ted
        if self._ted == ted:
            return
        '''
        self._ted = ted
        _log.info( "*** New TED: {0:.2f}, publishing to bus ***".format(ted))
        pubTopic = self.energyDemand_topic
        pubMsg = [ted,
                    {'units': 'W', 'tz': 'UTC', 'type': 'float'}]
        self.publishToBus(pubTopic, pubMsg)
        return

    def _validPlugId(self, plugID):
        if plugID == PLUG_ID_1 or plugID == PLUG_ID_2 or plugID == PLUG_ID_3 or plugID == PLUG_ID_4:
            return True
        else:
            return False

    def _getTaskSchedule(self, task_id, time_ms=None):
        #_log.debug("_getTaskSchedule()")
        self.time_ms = 600 if time_ms is None else time_ms
        try: 
            start = str(datetime.datetime.now())
            end = str(datetime.datetime.now() 
                    + datetime.timedelta(milliseconds=self.time_ms))

            device = 'iiit/cbs/smartstrip'
            msg = [
                    [device,start,end]
                    ]
            result = self.vip.rpc.call(
                    'platform.actuator', 
                    'request_new_schedule',
                    self._agent_id,                 #requested id
                    task_id,
                    'HIGH',
                    msg).get(timeout=10)
        except gevent.Timeout:
            _log.exception("Expection: gevent.Timeout in _getTaskSchedule()")
            return result
        except Exception as e:
            _log.exception ("Could not contact actuator. Is it running?")
            print(e)
            print result
            return result
        return result

    def _cancelSchedule(self, task_id):
        #_log.debug('_cancelSchedule')
        result = self.vip.rpc.call('platform.actuator', 'request_cancel_schedule', \
                                    self._agent_id, task_id).get(timeout=10)
        #_log.debug("task_id: " + task_id)
        #_log.debug(result)
        return


def main(argv=sys.argv):
    '''Main method called by the eggsecutable.'''
    try:
        utils.vip_main(SmartStrip)
    except Exception as e:
        print e
        _log.exception('unhandled exception')


if __name__ == '__main__':
    # Entry point for script
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        pass

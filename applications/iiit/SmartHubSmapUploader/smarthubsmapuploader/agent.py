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
import sys
import uuid

from volttron.platform.vip.agent import Agent, Core, PubSub, compat, RPC
from volttron.platform.agent import utils
from volttron.platform.messaging import topics, headers as headers_mod

import time
import requests
import json
import cPickle

from smap_tools import smap_post
import dateutil

utils.setup_logging()
_log = logging.getLogger(__name__)
__version__ = '0.3'

# Change this to whatever the root of the messages is on your system
# For example, all of the messages being generated by our volttron-level code
# start with LPDM.  E.G. /LPDM/energy_price or /LPDM/power_use
# If you want to listen to all topics just replace the below with empty string ""  
SH_MAIN_TOPIC   = "smarthub" 
VB_MAIN_TOPIC   = "zone" 

# This is the information needed to post to smap.  The source_name might be able
# to be derived somehow and the API key and server root could go in a config
# But this seems easier to show for an example.
SMAP_ROOT = "http://chomp.lbl.gov/"
API_KEY = "u606HlEFHTeVLfpBQZkNF232wChljnLHCKBY"
SOURCE_NAME = "CBERD Flexlab Data V2"
TIME_ZONE = "Etc/UTC"

#agents whose published data to volttron bus we are interested in uploading to smap
SENDER_SH = 'iiit.smarthub'
SENDER_VB = 'iiit.volttronbridge'
SENDER_GC = 'iiit.smarthubgc'
    
def smarthubsmapuploader(config_path, **kwargs):
    
    config = utils.load_config(config_path)
    agent_id = config['agentid']
    
    class SmartHubSmapUploader(Agent):
        '''
        retrive the data from volttron and post it the smap Server
        '''
        
        def __init__(self, **kwargs):
            _log.debug('__init__()')
            super(SmartHubSmapUploader, self).__init__(**kwargs)
            
        @Core.receiver('onsetup')
        def setup(self, sender, **kwargs):
            _log.debug('setup()')
            _log.info(config['message'])
            self._agent_id = config['agentid']
            
            self.sh_id          = config.get('sh_id', 'SmartHub-62')
            self.smap_root      = config.get('smap_root', SMAP_ROOT)
            self.api_key        = config.get('api_key', API_KEY)
            self.source_data    = config.get('source_data', SOURCE_NAME)
            self.time_zone      = config.get('time_zone', TIME_ZONE)
            
            self.sender_sh      = config.get('sender_sh', SENDER_SH)
            self.sender_vb      = config.get('sender_vb', SENDER_VB)
            self.sender_gc      = config.get('sender_gc', SENDER_GC)
            
            self.sh_main_topic  = config.get('sh_main_topic', SH_MAIN_TOPIC)
            self.vb_main_topic  = config.get('vb_main_topic', VB_MAIN_TOPIC)
            return
            
        @Core.receiver('onstart')            
        def startup(self, sender, **kwargs):
            _log.debug('startup()')
            
            #subscribing to sh_main_topic
            self.vip.pubsub.subscribe("pubsub", self.sh_main_topic, self.on_match_shData)
            #subscribing to vb_main_topic
            self.vip.pubsub.subscribe("pubsub", self.vb_main_topic, self.on_match_shCurrentPP)
        
            return
            
        @Core.receiver('onstop')
        def onstop(self, sender, **kwargs):
            _log.debug('onstop()')
            return
            
        def on_match_shData(self, peer, sender, bus, topic, headers, message):
            _log.debug('on_match_shData()')
            self.shSmapPostData(peer, sender, bus, topic, headers, message)
            return
            
        def on_match_shCurrentPP(self, peer, sender, bus, topic, headers, message):
            _log.debug('on_match_ssCurrentPP()')
            self.shSmapPostData(peer, sender, bus, topic, headers, message)
            return
        
        def shSmapPostData(self, peer, sender, bus, topic, headers, message):
            _log.debug('shSmapPostData()')
            
            '''
            #we don't want to post messages other than those
            #published by 'iiit.smarthub' or by 'iiit.volttronbridge' or by  'iiit.smarthubgc'
            if sender != self.sender_sh and sender != self.sender_vb and sender != self.sender_gc:
                _log.debug('not valid sender: ' + sender)
                return
                
            #vb & gc agent id is not static 
            '''
            # Just check for it or any other messages you don't want to log here
            # and return without doing anything.            
            keywords_to_skip = ["subscriptions", "init", "finished_processing"]
            for keyword in keywords_to_skip:
                if keyword in topic:
                    return
                    
            _log.debug("Peer: %r, Sender: %r, Bus: %r, Topic: %r, Headers: %r, Message: %r", peer, sender, bus, topic, headers, message)
            
            str_time = headers[headers_mod.DATE]
            msg_time = dateutil.parser.parse(str_time)
            reading_type = 'double'
            
            if 'sensors' in topic:
                _log.debug('shSmapPostData() - sensors')
                #strip 'all' from the topic, don't know how to post all (lux, rh, temp, co2 & pir) to the smap
                #so posting individually
                #topic = (topic.split('all', 1))[0]
                
                topic = "/SmartHub/" + self.sh_id + "/Sensors/lux"
                self.smapPostSensorsData('luxlevel', topic, headers, message, msg_time)
                
                topic = "/SmartHub/" + self.sh_id + "/Sensors/rh"
                self.smapPostSensorsData('rhlevel', topic, headers, message, msg_time)
                
                topic = "/SmartHub/" + self.sh_id + "/Sensors/temperature"
                self.smapPostSensorsData('templevel', topic, headers, message, msg_time)
                
                topic = "/SmartHub/" + self.sh_id + "/Sensors/co2"
                self.smapPostSensorsData('co2level', topic, headers, message, msg_time)
                
                topic = "/SmartHub/" + self.sh_id + "/Sensors/occupancy"
                self.smapPostSensorsData('pirlevel', topic, headers, message, msg_time)
                return
            elif 'ledstate' in topic:
                _log.debug('shSmapPostData() - ledstate')
                
                topic = "/SmartHub/" + self.sh_id + "/Led/state"
                units = message[1]['units']
                msg_value = message[0]
                readings = [[msg_time, msg_value]]
                
                smap_post(self.smap_root, self.api_key, topic, units, reading_type, readings, self.source_data, self.time_zone)
                return
            elif 'fanstate' in topic:
                _log.debug('shSmapPostData() - fanstate')
                
                topic = "/SmartHub/" + self.sh_id + "/Fan/state"
                units = message[1]['units']
                msg_value = message[0]
                readings = [[msg_time, msg_value]]
                
                smap_post(self.smap_root, self.api_key, topic, units, reading_type, readings, self.source_data, self.time_zone)
                return
            elif 'ledlevel' in topic:
                _log.debug('shSmapPostData() - ledlevel')
                
                topic = "/SmartHub/" + self.sh_id + "/Led/level"
                units = message[1]['units']
                msg_value = message[0]
                readings = [[msg_time, msg_value]]
                
                smap_post(self.smap_root, self.api_key, topic, units, reading_type, readings, self.source_data, self.time_zone)
                return
            elif 'fanlevel' in topic:
                _log.debug('shSmapPostData() - fanlevel')
                
                topic = "/SmartHub/" + self.sh_id + "/Fan/level"
                units = message[1]['units']
                msg_value = message[0]
                readings = [[msg_time, msg_value]]
                
                smap_post(self.smap_root, self.api_key, topic, units, reading_type, readings, self.source_data, self.time_zone)
                return
            elif 'ledthpp' in topic:
                _log.debug('shSmapPostData() - ledthpp')
                
                topic = "/SmartHub/" + self.sh_id + "/Led/threshold"
                units = message[1]['units']
                msg_value = message[0]
                readings = [[msg_time, msg_value]]
                
                smap_post(self.smap_root, self.api_key, topic, units, reading_type, readings, self.source_data, self.time_zone)
                return
            elif 'fanthpp' in topic:
                _log.debug('shSmapPostData() - fanthpp')
                
                topic = "/SmartHub/" + self.sh_id + "/Fan/threshold"
                units = message[1]['units']
                msg_value = message[0]
                readings = [[msg_time, msg_value]]
                
                smap_post(self.smap_root, self.api_key, topic, units, reading_type, readings, self.source_data, self.time_zone)
                return
            elif 'ds/energydemand' in topic:
                #downstream smart strips energy demand
                _log.debug('smapPostSSData() - Energy Demand - SmartStrip - (DownStream) - YET TO IMPLEMENT!!!!!')
                return
            elif 'smarthub/energydemand' in topic:
                _log.debug('smapPostSSData() - Energy Demand - SmartHub')
                
                topic = "/SmartHub/" + self.sh_id + "/energydemand/smarthub"
                units = message[1]['units']
                msg_value = message[0]
                readings = [[msg_time, msg_value]]
                
                print('**Sam**')
                print('topic: ' + topic)
                print('msg_value: ' + str(msg_value))
                print('message: ' + str(message))
                
                smap_post(self.smap_root, self.api_key, topic, units, reading_type, readings, self.source_data, self.time_zone)
                return
            elif 'smarthub/pricepoint' in topic:
                _log.debug('shSmapPostData() - PricePoint - SmartHub')
                
                topic = "/SmartHub/" + self.sh_id + "/pricepoint/smarthub"
                units = message[1]['units']
                msg_value = message[0]
                readings = [[msg_time, msg_value]]
                
                print('**Sam**')
                print('topic: ' + topic)
                print('msg_value: ' + str(msg_value))
                print('message: ' + str(message))
                
                smap_post(self.smap_root, self.api_key, topic, units, reading_type, readings, self.source_data, self.time_zone)
                return
            elif 'us/pricepoint' in topic:
                _log.debug('shSmapPostData() - PricePoint - Zone (Upstream)')
                
                topic = "/SmartHub/" + self.sh_id + "/pricepoint/zone"
                units = message[1]['units']
                msg_value = message[0]
                readings = [[msg_time, msg_value]]
                
                print('**Sam**')
                print('topic: ' + topic)
                print('msg_value: ' + str(msg_value))
                print('message: ' + str(message))
                
                smap_post(self.smap_root, self.api_key, topic, units, reading_type, readings, self.source_data, self.time_zone)
                return
            else:
                _log.exception("Exception: unhandled topic: " + topic)
                return
                        
        def smapPostSensorsData(self, field, topic, headers, message, msg_time):
            reading_type = 'double'
            
            units = message[1][field]['units']
            msg_value = message[0][field]
            readings = [[msg_time, msg_value]]      
            
            smap_post(self.smap_root, self.api_key, topic, units, reading_type, readings, self.source_data, self.time_zone)
            return
            
    Agent.__name__ = 'SmartHubSmapUploader_Agent'
    return SmartHubSmapUploader(**kwargs)

def main(argv=sys.argv):
    '''Main method called by the eggsecutable.'''
    try:
        utils.vip_main(smarthubsmapuploader)
    except Exception as e:
        print (e)
        _log.exception('unhandled exception')

if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv))
    except KeyboardInterrupt:
        pass
        
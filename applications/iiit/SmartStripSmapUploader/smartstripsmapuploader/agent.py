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

import time

import requests
import json

import cPickle

from smap_tools import smap_post
import dateutil

utils.setup_logging()
_log = logging.getLogger(__name__)
__version__ = '0.2'

# Change this to whatever the root of the messages is on your system
# For example, all of the messages being generated by our volttron-level code
# start with LPDM.  E.G. /LPDM/energy_price or /LPDM/power_use
# If you want to listen to all topics just replace the below with empty string ""  
SS_MAIN_TOPIC   = "smartstrip" 
VB_MAIN_TOPIC   = "smarthub"

# This is the information needed to post to smap.  The source_name might be able
# to be derived somehow and the API key and server root could go in a config
# But this seems easier to show for an example.
SMAP_ROOT = "http://chomp.lbl.gov/"
API_KEY = "u606HlEFHTeVLfpBQZkNF232wChljnLHCKBY"
SOURCE_NAME = "CBERD Flexlab Data V2"
TIME_ZONE = "Etc/UTC"

#agents whose published data to volttron bus we are interested in uploading to smap
SENDER_SS = 'iiit.smartstrip'
SENDER_VB = 'iiit.volttronbridge'
    
def smartstripsmapuploader(config_path, **kwargs):
    
    config = utils.load_config(config_path)
    agent_id = config['agentid']
    
    class SmartStripSmapUploader(Agent):
        '''
        retrive the data from volttron and post it the smap Server
        '''
        
        def __init__(self, **kwargs):
            _log.debug('__init__()')
            super(SmartStripSmapUploader, self).__init__(**kwargs)
            
        @Core.receiver('onsetup')
        def setup(self, sender, **kwargs):
            _log.debug('setup()')
            _log.info(config['message'])
            self._agent_id = config['agentid']
            
            self.ss_id          = config.get('ss_id', 'SmartStrip-72')
            self.smap_root      = config.get('smap_root', SMAP_ROOT)
            self.api_key        = config.get('api_key', API_KEY)
            self.source_data    = config.get('source_data', SOURCE_NAME)
            self.time_zone      = config.get('time_zone', TIME_ZONE)
            
            self.sender_ss      = config.get('sender_ss', SENDER_SS)
            self.sender_vb      = config.get('sender_vb', SENDER_VB)

            self.ss_main_topic = config.get('ss_main_topic', SS_MAIN_TOPIC)
            self.vb_main_topic = config.get('vb_main_topic', VB_MAIN_TOPIC)
            
            return
            
        @Core.receiver('onstart')            
        def startup(self, sender, **kwargs):
            _log.debug('startup()')
            self.vip.pubsub.subscribe("pubsub", self.ss_main_topic, self.on_match_ssData)
            self.vip.pubsub.subscribe("pubsub", self.vb_main_topic, self.on_match_ssCurrentPP)
            return
            
        @Core.receiver('onstop')
        def onstop(self, sender, **kwargs):
            _log.debug('onstop()')
            return
            
        def on_match_ssData(self, peer, sender, bus, topic, headers, message):
            _log.debug('on_match_ssData()')
            self.ssSmapPostData(peer, sender, bus, topic, headers, message)
            return
            
        def on_match_ssCurrentPP(self, peer, sender, bus, topic, headers, message):
            _log.debug('on_match_ssCurrentPP()')
            self.ssSmapPostData(peer, sender, bus, topic, headers, message)
            return
            
        def ssSmapPostData(self, peer, sender, bus, topic, headers, message):
            _log.debug('ssSmapPostData()')
            
            #we don't want to post messages other than those
            #published by 'iiit.smartstrip' or by 'iiit.volttronbridge' or by 'iiit.smartstripgc'
            '''
            if sender != self.sender_ss and sender != self.sender_vb and sender != 'iiit.smartstripgc':
                _log.debug('not valid sender: ' + sender)
                return
                
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

            plug_id = (topic.split('/', 3))[1]
                
            if 'meterdata' in topic:
                _log.debug('smapPostSSData() - meterdata')
                #strip 'all' from the topic, don't know how to post all (volt, current & apwr) to the smap
                #so posting individually
                
                topic = "/SmartStrip/" + self.ss_id + "/meterdata/voltage/" + plug_id
                self.smapPostMeterData('voltage', topic, headers, message, msg_time)
                
                topic = "/SmartStrip/" + self.ss_id + "/meterdata/current/" + plug_id
                self.smapPostMeterData('current', topic, headers, message, msg_time)
                
                topic = "/SmartStrip/" + self.ss_id + "/meterdata/active_power/" + plug_id
                self.smapPostMeterData('active_power', topic, headers, message, msg_time)
                return
            elif 'threshold' in topic:
                _log.debug('smapPostSSData() - threshold')
                
                topic = "/SmartStrip/" + self.ss_id + "/threshold/" + plug_id
                units = message[1]['units']                
                msg_value = message[0]
                readings = [[msg_time, msg_value]]

                smap_post(self.smap_root, self.api_key, topic, units, reading_type, readings, self.source_data, self.time_zone)
                return
            elif 'smartstrip/energydemand' in topic:
                _log.debug('smapPostSSData() - Energy Demand - SmartStrip')
                
                topic = "/SmartStrip/" + self.ss_id + "/energydemand/smartstrip"
                units = message[1]['units']
                msg_value = message[0]
                readings = [[msg_time, msg_value]]

                smap_post(self.smap_root, self.api_key, topic, units, reading_type, readings, self.source_data, self.time_zone)
                return
            elif 'smartstrip/pricepoint' in topic:
                _log.debug('smapPostSSData() - PricePoint - SmartStrip')
                
                topic = "/SmartStrip/" + self.ss_id + "/pricepoint/smartstrip"
                units = message[1]['units']
                msg_value = message[0]
                readings = [[msg_time, msg_value]]

                smap_post(self.smap_root, self.api_key, topic, units, reading_type, readings, self.source_data, self.time_zone)
                return
            elif 'us/pricepoint' in topic:
                _log.debug('smapPostSSData() - PricePoint - Smarthub (Upstream)')
                
                topic = "/SmartStrip/" + self.ss_id + "/pricepoint/smarthub"
                units = message[1]['units']
                msg_value = message[0]
                readings = [[msg_time, msg_value]]

                smap_post(self.smap_root, self.api_key, topic, units, reading_type, readings, self.source_data, self.time_zone)
                return
            elif 'tagid' in topic:
                _log.debug('smapPostSSData() - tagid')
                
                topic = "/SmartStrip/" + self.ss_id + "/tagid/" + plug_id
                units = 'n/a'
                msg_value = float.fromhex('0x'+message[0])
                readings = [[msg_time, msg_value]]

                smap_post(self.smap_root, self.api_key, topic, units, reading_type, readings, self.source_data, self.time_zone)
                return
            elif 'relaystate' in topic:
                _log.debug('smapPostSSData() - relaystate')
                
                topic = "/SmartStrip/" + self.ss_id + "/relaystate/" + plug_id
                units = message[1]['units']
                msg_value = message[0]
                readings = [[msg_time, msg_value]]

                smap_post(self.smap_root, self.api_key, topic, units, reading_type, readings, self.source_data, self.time_zone)
                return
            else:
                _log.exception("Exception: unhandled topic: " + topic)
                return
                        
        def smapPostMeterData(self, field, topic, headers, message, msg_time):
            reading_type = 'double'            
            units = message[1][field]['units']
            msg_value = message[0][field]
            readings = [[msg_time, msg_value]]      

            smap_post(self.smap_root, self.api_key, topic, units, reading_type, readings, self.source_data, self.time_zone)
            return
            
    Agent.__name__ = 'SmartStripSmapUploader_Agent'
    return SmartStripSmapUploader(**kwargs)

def main(argv=sys.argv):
    '''Main method called by the eggsecutable.'''
    try:
        utils.vip_main(smartstripsmapuploader)
    except Exception as e:
        print e
        _log.exception('unhandled exception')

if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv))
    except KeyboardInterrupt:
        pass
        
# -*- coding: utf-8 -*- {{{
# vim: set fenc=utf-8 ft=python sw=4 ts=4 sts=4 et:
#
# Copyright (c) 2016, CBS-IIIT
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

# IIIT
#

#}}}

from __future__ import absolute_import

from datetime import datetime
import logging
import random
import sys

from volttron.platform.vip.agent import Agent, Core, PubSub, compat
from volttron.platform.agent import utils
from volttron.platform.messaging import headers as headers_mod




utils.setup_logging()
_log = logging.getLogger(__name__)
__version__ = '0.1'

'''
Structuring the agent this way allows us to grab config file settings 
for use in subscriptions instead of hardcoding them.
'''

def subscriber_agent(config_path, **kwargs):
    config = utils.load_config(config_path)
    led1_point= config.get('led1_point',
                          'devices/campus_iiit/building_cbs/bacnet_smarthub/LEDLight1')
    led2_point= config.get('led2_point',
                          'devices/campus_iiit/building_cbs/bacnet_smarthub/LEDLight2')
	led3_point= config.get('led3_point',
                          'devices/campus_iiit/building_cbs/bacnet_smarthub/LEDLight3')
	led4_point= config.get('led4_point',
                          'devices/campus_iiit/building_cbs/bacnet_smarthub/LEDLight4')
    all_topic = config.get('all_topic', 
                           'devices/campus_iiit/building_cbs/bacnet_smarthub/all')
    query_point= config.get('query_point',
                            'campus_iiit/building_cbs/bacnet_smarthub/LEDLight1')
    
    
    class SmartHubStatusSubscriber(Agent):
        '''
        This agent demonstrates usage of the 3.0 pubsub service as well as 
        interfacting with the historian. This agent is mostly self-contained, 
        but requires the histoiran be running to demonstrate the query feature.
        '''
    
        def __init__(self, **kwargs):
            super(SmartHubStatusSubscriber, self).__init__(**kwargs)
    
        @Core.receiver('onsetup')
        def setup(self, sender, **kwargs):
            # Demonstrate accessing a value from the config file
            self._agent_id = config['agentid']
    
    

        @PubSub.subscribe('pubsub', all_topic)
        def match_device_all(self, peer, sender, bus,  topic, headers, message):
            '''
            This method subscribes to all points under a device then pulls out 
            the specific point it needs.
            The first element of the list in message is a dictionairy of points 
            under the device. The second element is a dictionary of metadata for points.
            '''
                       
            print("Whole message", message)
            
            #The time stamp is in the headers
            print('Date', headers['Date'])
            
            #Pull out the value for the point of interest
            print("Value1", message[0]['LEDLight1'])
            
            #Pull out the metadata for the point
            print('Unit', message[1]['LEDLight1']['units'])
            print('Timezone', message[1]['LEDLight1']['tz'])
            print('Type', message[1]['LEDLight1']['type'])
			
			#Pull out the value for the point of interest
            print("Value2", message[0]['LEDLight2'])
            
            #Pull out the metadata for the point
            print('Unit', message[1]['LEDLight2']['units'])
            print('Timezone', message[1]['LEDLight2']['tz'])
            print('Type', message[1]['LEDLight2']['type'])
			
			#Pull out the value for the point of interest
            print("Value3", message[0]['LEDLight3'])
            
            #Pull out the metadata for the point
            print('Unit', message[1]['LEDLight3']['units'])
            print('Timezone', message[1]['LEDLight3']['tz'])
            print('Type', message[1]['LEDLight3']['type'])
			
			#Pull out the value for the point of interest
            print("Value4", message[0]['LEDLight4'])
            
            #Pull out the metadata for the point
            print('Unit', message[1]['LEDLight4']['units'])
            print('Timezone', message[1]['LEDLight4']['tz'])
            print('Type', message[1]['LEDLight4']['type'])
           

    
        @PubSub.subscribe('pubsub', led1_point)
        def on_match_led(self, peer, sender, bus,  topic, headers, message):
            '''
            This method subscribes to the specific point topic.
            For these topics, the value is the first element of the list 
            in message.
            '''
            
            print("Whole message", message)
            print('Date', headers['Date'])
            print("Value", message[0])
            print("Units", message[1]['units'])
            print("TimeZone", message[1]['tz'])
            print("Type", message[1]['type'])
            
    
        @PubSub.subscribe('pubsub', '')
        def on_match_all(self, peer, sender, bus,  topic, headers, message):
            ''' This method subscibes to all topics. It simply prints out the 
            topic seen.
            '''
            
            print(topic)
#     
        # Demonstrate periodic decorator and settings access
        @Core.periodic(10)
        def lookup_data(self):
            '''
            This method demonstrates how to query the platform historian for data
            This will require that the historian is already running on the platform.
            '''
            
            try: 
                
                result = self.vip.rpc.call(
                                           #Send this message to the platform historian
                                           #Using the reserved ID
                                           'platform.historian', 
                                           #Call the query method on this agent
                                           'query', 
                                           #query takes the keyword arguments of:
                                           #topic, then optional: start, end, count, order
#                                            start= "2015-10-14T20:51:56",
                                           topic=query_point,
                                           count = 20,
                                           #RPC uses gevent and we must call .get(timeout=10)
                                           #to make it fetch the result and tell 
                                           #us if there is an error
                                           order = "FIRST_TO_LAST").get(timeout=10)
                print('Query Result', result)
            except Exception as e:
                print ("Could not contact historian. Is it running?")
                print(e)

        @Core.periodic(10)
        def pub_fake_data(self):
            ''' This method publishes fake data for use by the rest of the agent.
            The format mimics the format used by VOLTTRON drivers.
            
            This method can be removed if you have real data to work against.
            '''
            
            #Make some random readings
			#READ THE DATA FROM MESSAGE BUS
            led1_reading = random.uniform(30,100)
			led2_reading = random.uniform(30,100)
			led3_reading = random.uniform(30,100)
			led4_reading = random.uniform(30,100)
            
            # Create a message for all points.
            all_message = [{'LEDLight1': led1_reading, 'LEDLight2': led2_reading,
						'LEDLight3': led3_reading, 'LEDLight4': led4_reading,},
                       {'LEDLight1': {'units': 'F', 'tz': 'UTC', 'type': 'float'},
					    'LEDLight2': {'units': 'F', 'tz': 'UTC', 'type': 'float'},
						'LEDLight3': {'units': 'F', 'tz': 'UTC', 'type': 'float'},
						'LEDLight4': {'units': 'F', 'tz': 'UTC', 'type': 'float'},
                        }]
            
            #Create messages for specific points
            led1_message = [led1_reading,{'units': 'F', 'tz': 'UTC', 'type': 'float'}]
            led2_message = [led2_reading,{'units': 'F', 'tz': 'UTC', 'type': 'float'}]
            led3_message = [led3_reading,{'units': 'F', 'tz': 'UTC', 'type': 'float'}]
            led4_message = [led4_reading,{'units': 'F', 'tz': 'UTC', 'type': 'float'}]
            
            #Create timestamp
            now = datetime.utcnow().isoformat(' ') + 'Z'
            headers = {
                headers_mod.DATE: now
            }
            
            #Publish messages
            self.vip.pubsub.publish(
                'pubsub', all_topic, headers, all_message)
            
            self.vip.pubsub.publish(
                'pubsub', led1_point, headers, led1_message)
            
            self.vip.pubsub.publish(
                'pubsub', led2_point, headers, led2_message)
            
			self.vip.pubsub.publish(
                'pubsub', led3_point, headers, led3_message)

			self.vip.pubsub.publish(
                'pubsub', led4_point, headers, led4_message)

            


    return SmartHubStatusSubscriber(**kwargs)
def main(argv=sys.argv):
    '''Main method called by the eggsecutable.'''
    try:
        utils.vip_main(subscriber_agent)
    except Exception as e:
        _log.exception('unhandled exception')


if __name__ == '__main__':
    # Entry point for script
    sys.exit(main())

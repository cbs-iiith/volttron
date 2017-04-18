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
        
import time

import requests
import json

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


def volttronbridge(config_path, **kwargs):

    config = utils.load_config(config_path)
    agent_id = config['agentid']
    
    energyDemand_topic = self.config.get('energyDemand_topic', \
                                            'zone/energydemand')  
    pricePoint_topic = self.config.get('pricePoint_topic', \
                                            'zone/pricepoint')
    '''
    the assumption is that for UpStream (us) the bridge communicates with only one instance and 
    for the DownStream (ds) the bridge would be posting to multiple devices

    for pricepoint one-to-many communication
        energydemand one-to-one communication
    
    The ds devices on their start up would register with this instance with ip address & port
    
    The bridge is aware of the upstream devices and registers to it (associates to it). 
    Also, as and when the is a change in energydemand, the same is posted to the upstream bridges.
    whereas the the bridge does not upfront know the downstream devices. 
    As and when the downstram bridges register to the bridge, the bridge starts posting the messages (pricepoint) to them
    '''
        
    class VolttronBridge(Agent):
        '''
        retrive the data from volttron bus and pushes it to upstream or downstream volttron instance
        if posting to downstream, then the data is pricepoint
        and if posting to upstream then the data is energydemand
        '''

        def __init__(self, **kwargs):
            _log.debug('__init__()')
            super(VolttronBridge, self).__init__(**kwargs)
                        
        @Core.receiver('onsetup')
        def setup(self, sender, **kwargs):
            _log.debug('setup()')
            _log.info(config['message'])
            self._agent_id = config['agentid']
            
            self._usConnected = False
            self._bridge_host = config.get('bridge_host', 'ZONE')
            self._deviceId    = config.get('deviceId', 'Zone-1')
            
            if self._bridge_host == 'ZONE':
                
                self._this_ip_addr    = config.get('zone_ip_addr', "192.168.1.250")
                self._this_port       = config.get('zone_port', 8082)
                
                #downstream volttron instances (SmartHubs)
                #post price point to these instances
                self._ds_voltBr = []
                self._ds_deviceId = []
                
            elif self._bridge_host == 'HUB'
                
                #upstream volttron instance (Zone)
                self._up_ip_addr      = config.get('zone_ip_addr', "192.168.1.250")
                self._up_port         = config.get('zone_port', 8082)
                
                self._this_ip_addr    = config.get('sh_ip_addr', "192.168.1.61")
                self._this_port       = config.get('sh_port', 8082)

                #downstream volttron instances (SmartStrips)
                #post price point to these instances
                self._ds_voltBr = []
                self._ds_deviceId = []
                
            elif self._bridge_host == 'STRIP'
                
                #upstream volttron instance (Smart Hub)
                self._up_ip_addr      = config.get('sh_ip_addr', "192.168.1.61")
                self._up_port         = config.get('sh_port', 8082)
                
                self._this_ip_addr      = config.get('ss_ip_addr', "192.168.1.71")
                self._this_port         = config.get('ss_port', 8082)
                
            self._discovery_address = self._this_ip_addr + ':' + self._this_port
            
        @Core.receiver('onstart')            
        def startup(self, sender, **kwargs):
            _log.debug('startup()')
            self.vip.rpc.call(MASTER_WEB, 'register_agent_route', \
                    r'^/VolttronBridge', \
                    self.core.identity, \
                    "rpc_from_net").get(timeout=30)

            if self._bridge_host == 'ZONE':
                #downstream volttron instances (SmartHubs)
                #do nothing
                
            elif self._bridge_host == 'HUB'
                #upstream volttron instance (Zone) - register with zone VolttronBridge
                url_root = 'http://' + self._up_ip_addr + ':' + self._up_port + '/VolttronBridge'
                result = self.do_rpc(url_root, 'rpc_registerDsBridge', 
                                    {'discovery_address': self._discovery_address, 
                                        'deviceId': self._deviceId
                                    })
                if result == 'SUCCESS':
                    self._usConnected = True
                    
                #downstream volttron instances (SmartStrips)
                # do nothing
                
            elif self._bridge_host == 'STRIP'
                #upstream volttron instance (SmartHub) - register with smarthub VolttronBridge
                url_root = 'http://' + self._up_ip_addr + ':' + self._up_port + '/VolttronBridge'
                result = self.do_rpc(url_root, 'rpc_registerDsBridge', 
                                    {'discovery_address': self._discovery_address, 
                                        'deviceId': self._deviceId
                                    })
                if result == 'SUCCESS':
                    self._usConnected = True
                
            return
            
        @Core.receiver('onstop')
        def onstop(self, sender, **kwargs):
            _log.debug('onstop()')
            return

        @RPC.export
        def rpc_from_net(self, header, message):
            result = False
            try:
                rpcdata = jsonrpc.JsonRpcData.parse(message)
                _log.info('rpc method: {}'.format(rpcdata.method) + \
                            '; rpc params: {}'.format(rpcdata.params))
                
                if rpcdata.method == "rpc_registerDsBridge":
                    args = {'discovery_address': rpcdata.params['discovery_address'],
                            'deviceId':rpcdata.params['deviceId']
                            }
                    result = self._registerDsBridge(**args)
                elif rpcdata.method == "rpc_postEnergyDemand":
                    args = {'discovery_address': rpcdata.params['discovery_address'],
                            'deviceId':rpcdata.params['deviceId'],
                            'newEnergyDemand': rpcdata.params['newEnergyDemand']
                            }
                    result = self._postEnergyDemand(**args)    
                return jsonrpc.json_result(rpcdata.id, result)
            except AssertionError:
                print('AssertionError')
                return jsonrpc.json_error('NA', INVALID_REQUEST,
                        'Invalid rpc data {}'.format(data))
            except Exception as e:
                print(e)
                return jsonrpc.json_error('NA', UNHANDLED_EXCEPTION, e)
            
        def _registerDsBridge(self, discovery_address, deviceId):
            if discovery_address in ds_voltBr:
                _log.debug('already registered')
                return True
                
            ds_voltBr.append(discovery_address)
            index = ds_voltBr.index(discovery_address)
            ds_deviceId.insert(index, deviceId)
            return True
            
        def _postEnergyDemand(self, discovery_address, deviceId, newEnergyDemand):
            if discovery_address in ds_voltBr:
                index = ds_voltBr.index(discovery_address)
                if ds_deviceId(index) == deviceId:
                    #post to bus
                    pubTopic = energyDemand_topic + "/" + deviceId
                    pubMsg = [newEnergyDemand,{'units': 'mW', 'tz': 'UTC', 'type': 'float'}]
                    self._publishToBus(pubTopic, pubMsg)
                    return True
            return False
            
        def _publishToBus(self, pubTopic, pubMsg):
            now = datetime.datetime.utcnow().isoformat(' ') + 'Z'
            headers = {headers_mod.DATE: now}          
            #Publish messages
            self.vip.pubsub.publish('pubsub', pubTopic, headers, pubMsg).get(timeout=5)
        
        return
        
        def do_rpc(self, url_root, method, params=None ):
            result = 'FAILED'
            json_package = {
                'jsonrpc': '2.0',
                'id': self._agent_id,
                'method':method,
            }

            if params:
                json_package['params'] = params

            data = json.dumps(json_package)
            try:
                response = requests.post(url_root, data=json.dumps(json_package))
                
                if response.ok:
                    success = response.json()['result']
                    if success:
                        _log.debug('response - ok, {} result:{}'.format(method, success))
                        result = 'SUCCESS'
                    else:
                        _log.debug('respone - not ok, {} result:{}'.format(method, success))
                else :
                    _log.debug('no respone, {} result: {}'.format(method, response))
            except Exception as e:
                #print (e)
                _log.exception('do_rpc() unhandled exception, most likely server is down')
                return
                
    Agent.__name__ = 'VolttronBridge_Agent'
    return VolttronBridge(**kwargs)


def main(argv=sys.argv):
    '''Main method called by the eggsecutable.'''
    try:
        utils.vip_main(volttronbridge)
    except Exception as e:
        print e
        _log.exception('unhandled exception')

if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv))
    except KeyboardInterrupt:
        pass

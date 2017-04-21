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
    
    energyDemand_topic      = config.get('energyDemand_topic', \
                                            'zone/energydemand')  
    energyDemand_topic_ds   = config.get('energyDemand_topic_ds', \
                                            'smarthub/energydemand')  
                                            
    pricePoint_topic_us     = config.get('pricePoint_topic_us', \
                                            'building/pricepoint')
    pricePoint_topic        = config.get('pricePoint_topic', \
                                            'zone/pricepoint')

    '''
    Retrive the data from volttron bus and pushes it to upstream or downstream volttron instance
    if posting to downstream, then the data is pricepoint
    and if posting to upstream then the data is energydemand

    The assumption is that for UpStream (us), the bridge communicates with only one instance and 
    for the DownStream (ds), the bridge would be posting to multiple devices

    for pricepoint one-to-many communication
        energydemand one-to-one communication
    
    The ds devices on their start up would register with this instance with ip address & port
    
    The bridge is aware of the upstream devices and registers to it (associates to it). 
    Also, as and when the is a change in energydemand, the same is posted to the upstream bridges.
    whereas the the bridge does not upfront know the downstream devices. 
    As and when the downstram bridges register to the bridge, the bridge starts posting the messages (pricepoint) to them
    '''
    class VolttronBridge(Agent):
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
                    
            #we want to post ds only if there is change in price point
            self._price_point_current   = 0
            self._price_point_previous  = 0
            
            self._us_last_pp_previous   = 0
            self._us_last_pp_current    = 0
            
            #we want to post to us only if there is change in energy demand
            self._ed_current    = 0
            self._ed_previous   = 0
            
            if self._bridge_host == 'ZONE':
                _log.debug(self._bridge_host)
                
                self._this_ip_addr    = config.get('zone_ip_addr', "192.168.1.250")
                self._this_port       = int(config.get('zone_port', 8082))
                
                #downstream volttron instances (SmartHubs)
                #post price point to these instances
                self._ds_voltBr = []
                self._ds_deviceId = []
                
            elif self._bridge_host == 'HUB':
                _log.debug(self._bridge_host)
                
                #upstream volttron instance (Zone)
                self._up_ip_addr      = config.get('zone_ip_addr', "192.168.1.250")
                self._up_port         = int(config.get('zone_port', 8082))
                _log.debug('self._up_ip_addr: ' + self._up_ip_addr + ' self._up_port: ' + str(self._up_port))
                
                self._this_ip_addr    = config.get('sh_ip_addr', "192.168.1.61")
                self._this_port       = int(config.get('sh_port', 8082))

                #downstream volttron instances (SmartStrips)
                #post price point to these instances
                self._ds_voltBr = []
                self._ds_deviceId = []
                
            elif self._bridge_host == 'STRIP':
                _log.debug(self._bridge_host)
                
                #upstream volttron instance (Smart Hub)
                self._up_ip_addr      = config.get('sh_ip_addr', "192.168.1.61")
                self._up_port         = int(config.get('sh_port', 8082))
                _log.debug('self._up_ip_addr: ' + self._up_ip_addr + ' self._up_port: ' + str(self._up_port))
                
                self._this_ip_addr      = config.get('ss_ip_addr', "192.168.1.71")
                self._this_port         = int(config.get('ss_port', 8082))
                
            self._discovery_address = self._this_ip_addr + ':' + str(self._this_port)
            _log.debug('self._discovery_address: ' + self._discovery_address)
            
        @Core.receiver('onstart')            
        def startup(self, sender, **kwargs):
            _log.debug('startup()')
            
            _log.debug('registering rpc routes')
            self.vip.rpc.call(MASTER_WEB, 'register_agent_route', \
                    r'^/VolttronBridge', \
                    self.core.identity, \
                    "rpc_from_net").get(timeout=30)

            if self._bridge_host == 'ZONE':
                _log.debug(self._bridge_host)
                #do nothing
                
            elif self._bridge_host == 'HUB' or self._bridge_host == 'STRIP' :
                _log.debug(self._bridge_host)
                _log.debug("registering with upstream VolttronBridge")
                url_root = 'http://' + self._up_ip_addr + ':' + str(self._up_port) + '/VolttronBridge'
                self._usConnected = self._registerToUsBridge(url_root, self._discovery_address, self._deviceId)
                
            return

        #register with upstream volttron bridge
        def _registerToUsBridge(self, url_root, discovery_address, deviceId):
            return self.do_rpc(url_root, 'rpc_registerDsBridge', \
                                {'discovery_address': discovery_address, \
                                    'deviceId': deviceId \
                                    })
                                    
        @Core.receiver('onstop')
        def onstop(self, sender, **kwargs):
            _log.debug('onstop()')
            if self._bridge_host == 'ZONE':
                _log.debug(self._bridge_host)
                #do nothing
                
            elif self._bridge_host == 'HUB' or self._bridge_host == 'STRIP':
                _log.debug(self._bridge_host)
                if self._usConnected == False:
                    return
                    
                _log.debug("unregistering with upstream VolttronBridge")
                url_root = 'http://' + self._up_ip_addr + ':' + str(self._up_port) + '/VolttronBridge'
                result = self.do_rpc(url_root, 'rpc_unregisterDsBridge', \
                                    {'discovery_address': self._discovery_address, \
                                        'deviceId': self._deviceId \
                                    })
            return

        @RPC.export
        def rpc_from_net(self, header, message):
            _log.debug('rpc_from_net()')
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
                elif rpcdata.method == "rpc_unregisterDsBridge":
                    args = {'discovery_address': rpcdata.params['discovery_address'],
                            'deviceId':rpcdata.params['deviceId']
                            }
                    result = self._unregisterDsBridge(**args)
                elif rpcdata.method == "rpc_postEnergyDemand":
                    args = {'discovery_address': rpcdata.params['discovery_address'],
                            'deviceId':rpcdata.params['deviceId'],
                            'newEnergyDemand': rpcdata.params['newEnergyDemand']
                            }
                    #post the new energy demand from ds to the local bus
                    result = self._postEnergyDemand(**args)    
                elif rpcdata.method == "rpc_postPricePoint":
                    args = {'discovery_address': rpcdata.params['discovery_address'],
                            'deviceId':rpcdata.params['deviceId'],
                            'newPricePoint': rpcdata.params['newPricePoint']
                            }
                    #post the new new price point from us to the local-us-bus
                    result = self._postPricePoint(**args)
                else:
                    return jsonrpc.json_error(rpcdata.id, METHOD_NOT_FOUND, \
                                                'Invalid method {}'.format(rpcdata.method))
                return jsonrpc.json_result(rpcdata.id, result)
                
            except KeyError as ke:
                print(ke)
                return jsonrpc.json_error('NA', INVALID_PARAMS,
                        'Invalid params {}'.format(rpcdata.params))
            except Exception as e:
                print(e)
                return jsonrpc.json_error('NA', UNHANDLED_EXCEPTION, e)
        
        #price point on local bus published, post it to all downstream bridges
        @PubSub.subscribe('pubsub', pricePoint_topic)
        def onNewPrice(self, peer, sender, bus,  topic, headers, message):
            if self._bridge_host == 'STRIP':
                return
                
            _log.debug('onNewPrice()')
            if sender == 'pubsub.compat':
                message = compat.unpack_legacy_message(headers, message)
                
            new_price_point = message[0]
            _log.debug ( "*** New Price Point: {0:.2f} ***".format(new_price_point))
            
            #we want to post to ds only if there is change in price point
            if self._price_point_current != new_price_point:
                self._processNewPricePoint(new_price_point)
            
            return
            
        #energy demand on local bus published, post it to upstream bridge
        @PubSub.subscribe('pubsub', energyDemand_topic)
        def onNewEnergyDemand(self, peer, sender, bus,  topic, headers, message):
            if self._bridge_host == 'ZONE':
                #do nothing
                return
                
            _log.debug("onNewEnergyDemand()")
                    
            if sender == 'pubsub.compat':
                message = compat.unpack_legacy_message(headers, message)
                
            newEnergyDemand = message[0]
            _log.debug ( "*** New Energy Demand: {0:.4f} ***".format(newEnergyDemand))
            
            #we want to post to us only if there is change in energy demand
            if self._ed_current == newEnergyDemand:
                return
                
            self._ed_previous = self._ed_current
            self._ed_current = newEnergyDemand
            
            _log.debug("posting new energy demand to upstream VolttronBridge")
            url_root = 'http://' + self._up_ip_addr + ':' + str(self._up_port) + '/VolttronBridge'
            
            #check for upstream connection, if not retry once
            if self._usConnected == False:
                self._usConnected = self._registerToUsBridge(url_root,\
                                                                self._discovery_address,\
                                                                self._deviceId)
                if not self._usConnected:
                    _log.debug('May be upstream bridge is not running!!!')
                    return

            if self.do_rpc(url_root, 'rpc_postEnergyDemand', \
                            {'discovery_address': self._discovery_address, \
                                'deviceId': self._deviceId, \
                                'newEnergyDemand': newEnergyDemand
                            }):
                _log.debug("Success!!!")
            else : 
                _log.debug("Failed!!!")

            return
            
        #price point on local bus changed post it to ds
        def _processNewPricePoint(self, new_price_point):
            _log.debug('_processNewPricePoint()')
            self._price_point_previous = self._price_point_current
            self._price_point_current = new_price_point
            
            for discovery_address in self._ds_voltBr:
                self._postDsNewPricePoint(discovery_address, new_price_point)
                
            return
            
        def _postDsNewPricePoint(self, discovery_address, newPricePoint):
            _log.debug('_postDsNewPricePoint() to : ' + discovery_address)
            
            url_root = 'http://' + discovery_address + '/VolttronBridge'
            result = self.do_rpc(url_root, 'rpc_postPricePoint', \
                                    {'discovery_address': self._discovery_address, \
                                    'deviceId': self._deviceId, \
                                    'newPricePoint':newPricePoint   \
                                    })
            return
            
        def _registerDsBridge(self, discovery_address, deviceId):
            _log.debug('_registerDsBridge(), discovery_address: ' + discovery_address + ' deviceId: ' + deviceId)
            if discovery_address in self._ds_voltBr:
                _log.debug('already registered!!!')
                return True
                
            #TODO: potential bug in this method, not atomic
            self._ds_voltBr.append(discovery_address)
            index = self._ds_voltBr.index(discovery_address)
            self._ds_deviceId.insert(index, deviceId)
            _log.debug('registered!!!')
            return True
            
        def _unregisterDsBridge(self, discovery_address, deviceId):
            _log.debug('_unregisterDsBridge(), discovery_address: ' + discovery_address + ' deviceId: ' + deviceId)
            if discovery_address not in self._ds_voltBr:
                _log.debug('already unregistered')
                return True
                
            #TODO: potential bug in this method, not atomic
            index = self._ds_voltBr.index(discovery_address)
            self._ds_voltBr.remove(discovery_address)
            del self._ds_deviceId[index]
            _log.debug('unregistered!!!')
            return True
            
        #post the new new price point from us to the local-us-bus        
        def _postPricePoint(self, discovery_address, deviceId, newPricePoint):
            if self._bridge_host == 'ZONE':
                #do nothing 
                return
                
            _log.debug('_postPricePoint()')
            _log.debug ( "*** New Price Point: {0:.2f} ***".format(newPricePoint))
            #we want to post to bus only if there is change in previous us price point
            if self._us_last_pp_current != newPricePoint:
                self._us_last_pp_previous = self._us_last_pp_current
                self._us_last_pp_current = newPricePoint
                #post to bus
                pubTopic =  pricePoint_topic_us
                pubMsg = [newPricePoint,{'units': 'cents', 'tz': 'UTC', 'type': 'float'}]
                _log.debug('publishing to local bus topic: ' + pubTopic)
                self._publishToBus(pubTopic, pubMsg)
                return True
            else:
                _log.debug('no change in price, do nothing')
                return False
                
        #post the new energy demand from ds to the local bus
        def _postEnergyDemand(self, discovery_address, deviceId, newEnergyDemand):
            _log.debug('_postEnergyDemand(), newEnergyDemand: {0:.4f}'.format(newEnergyDemand))
            if discovery_address in self._ds_voltBr:
                index = self._ds_voltBr.index(discovery_address)
                if self._ds_deviceId[index] == deviceId:
                    #post to bus
                    pubTopic = energyDemand_topic_ds + "/" + deviceId
                    _log.debug('publishing to local bus topic: ' + pubTopic)
                    pubMsg = [newEnergyDemand,{'units': 'mW', 'tz': 'UTC', 'type': 'float'}]
                    self._publishToBus(pubTopic, pubMsg)
                    return True
            return False
            
        def _publishToBus(self, pubTopic, pubMsg):
            _log.debug('_publishToBus()')
            now = datetime.datetime.utcnow().isoformat(' ') + 'Z'
            headers = {headers_mod.DATE: now}          
            #Publish messages
            self.vip.pubsub.publish('pubsub', pubTopic, headers, pubMsg).get(timeout=5)
            return
        
        def do_rpc(self, url_root, method, params=None ):
            _log.debug('do_rpc()')
            result = False
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
                        result = True
                    else:
                        _log.debug('respone - not ok, {} result:{}'.format(method, success))
                else :
                    _log.debug('no respone, {} result: {}'.format(method, response))
            except KeyError:
                error = response.json()['error']
                #print (error)
                _log.exception('KeyError: SHOULD NEVER REACH THIS ERROR - contact developer')
                return False
            except Exception as e:
                #print (e)
                _log.exception('Exception: do_rpc() unhandled exception, most likely dest is down')
                return False
            return result
            
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

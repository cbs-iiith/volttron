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

import time
import gevent
import gevent.event
import requests
import json

from ispace_utils import publish_to_bus, isclose

utils.setup_logging()
_log = logging.getLogger(__name__)
__version__ = '0.3'

#checking if a floating point value is "numerically zero" by checking if it is lower than epsilon
EPSILON = 1e-03

#if the rpc connection fails to post for more than MAX_RETRIES, 
#then it is assumed that the dest is down
#in case of ds posts, the retry count is reset when the ds registers again or on a new price point
#in case of us posts, the retry count is reset when change in ed.
#   also if failed too many times to post ed, retry count is reset and the process yeilds for a movement(10sec)
MAX_RETRIES = 5

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
    Also, as and when there is a change in energydemand, the same is posted to the upstream bridges.
    whereas the the bridge does not upfront know the downstream devices. 
    As and when the downstram bridges register to the bridge, the bridge starts posting the messages (pricepoint) to them
    '''
    class VolttronBridge(Agent):
        def __init__(self, **kwargs):
            _log.debug('__init__()')
            super(VolttronBridge, self).__init__(**kwargs)
            return
            
        @Core.receiver('onsetup')
        def setup(self, sender, **kwargs):
            _log.debug('setup()')
            _log.info(config['message'])
            self._agent_id = config['agentid']
            
            self._usConnected = False
            self._bridge_host = config.get('bridge_host', 'LEVEL_HEAD')
            self._deviceId    = config.get('deviceId', 'Building-1')
            
            #we want to post ds only if there is change in price point
            self._pp_current            = 0
            self._pp_new                = 0
            self._pp_id                 = randint(0, 99999999)
            self._pp_isoptimal          = False
            self._all_ds_posts_success  = True
            

            #we want to post to us only if there is change in energy demand
            self._ed_current    = 0
            self._ed_previous   = 0
            self._ed_pp_id      = randint(0, 99999999)
            
            self._us_retrycount = 0
            
            self._this_ip_addr    = config.get('ip_addr', "192.168.1.51")
            self._this_port       = int(config.get('port', 8082))
            
            self._period_process_pp = self.config.get('period_process_pp', 10)
            
            if self._bridge_host != 'LEVEL_TAILEND':
                _log.debug(self._bridge_host)
                
                #downstream volttron instances
                #post price point to these instances
                self._ds_voltBr = []
                self._ds_deviceId = []
                self._ds_retrycount = []
                
            if self._bridge_host != 'LEVEL_HEAD':
                _log.debug(self._bridge_host)
                
                #upstream volttron instance
                self._us_ip_addr      = config.get('us_ip_addr', "192.168.1.51")
                self._us_port         = int(config.get('us_port', 8082))
                _log.debug('self._us_ip_addr: ' + self._us_ip_addr + ' self._us_port: ' + str(self._us_port))
                
            self._discovery_address = self._this_ip_addr + ':' + str(self._this_port)
            _log.debug('self._discovery_address: ' + self._discovery_address)
            return
            
        @Core.receiver('onstart')            
        def startup(self, sender, **kwargs):
            _log.debug('startup()')
            _log.debug(self._bridge_host)
            
            _log.debug('registering rpc routes')
            self.vip.rpc.call(MASTER_WEB, 'register_agent_route', \
                    r'^/VolttronBridge', \
#                    self.core.identity, \
                    "rpc_from_net").get(timeout=30)
                    
            #subscribe to price point so that it can be posted to downstream
            if self._bridge_host != 'LEVEL_TAILEND':
                _log.debug("subscribing to pricePoint_topic: " + pricePoint_topic)
                self.vip.pubsub.subscribe("pubsub", \
                                            pricePoint_topic, \
                                            self.onNewPrice \
                                            )
                self._ds_voltBr[:] = []
                self._ds_deviceId[:] = []
                self._ds_retrycount[:] = []
                
            #subscribe to energy demand so that it can be posted to upstream
            if self._bridge_host != 'LEVEL_HEAD':
                _log.debug("subscribing to energyDemand_topic: " + energyDemand_topic)
                self.vip.pubsub.subscribe("pubsub", \
                                            energyDemand_topic, \
                                            self.onNewEnergyDemand \
                                            )
                                            
            #register to upstream
            if self._bridge_host != 'LEVEL_HEAD':
                url_root = 'http://' + self._us_ip_addr + ':' + str(self._us_port) + '/VolttronBridge'
                _log.debug("registering with upstream VolttronBridge: " + url_root)
                self._usConnected = self._registerToUsBridge(url_root, self._discovery_address, self._deviceId)
                
            #perodically keeps trying to post ed to us
            if self._bridge_host != 'LEVEL_HEAD':
                self.core.periodic(self._period_process_pp, self._postUsEnergyDemand, wait=None)
                
            #perodically keeps trying to post pp to ds
            if self._bridge_host != 'LEVEL_TAILEND':
                self.core.periodic(self._period_process_pp, self._postDsNewPricePoint, wait=None)
                
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
            self._us_retrycount = 0
            
            if self._bridge_host != 'LEVEL_TAILEND':
                del self._ds_voltBr[:]
                del self._ds_deviceId[:]
                del self._ds_retrycount[:]
                
            if self._bridge_host != 'LEVEL_HEAD':
                _log.debug(self._bridge_host)
                if self._usConnected:
                    _log.debug("unregistering with upstream VolttronBridge")
                    url_root = 'http://' + self._us_ip_addr + ':' + str(self._us_port) + '/VolttronBridge'
                    result = self.do_rpc(url_root, 'rpc_unregisterDsBridge', \
                                        {'discovery_address': self._discovery_address, \
                                            'deviceId': self._deviceId \
                                        })
                    self._usConnected = False
                
            _log.debug('un registering rpc routes')
            self.vip.rpc.call(MASTER_WEB, \
                                'unregister_all_agent_routes'\
#                                , self.core.identity\
                                ).get(timeout=30)
                                
            _log.debug('done!!!')
            return
            
        @RPC.export
        def rpc_from_net(self, header, message):
            result = False
            try:
                rpcdata = jsonrpc.JsonRpcData.parse(message)
                '''
                _log.debug('rpc_from_net()...' + \
                            ', rpc method: {}'.format(rpcdata.method) +\
                            ', rpc params: {}'.format(rpcdata.params))
                '''
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
                            'newEnergyDemand': rpcdata.params['newEnergyDemand'],
                            'ed_pp_id': rpcdata.params['ed_pp_id']
                            }
                    #post the new energy demand from ds to the local bus
                    result = self._postEnergyDemand(**args)    
                elif rpcdata.method == "rpc_postPricePoint":
                    args = {'discovery_address': rpcdata.params['discovery_address'],
                            'deviceId':rpcdata.params['deviceId'],
                            'newPricePoint': rpcdata.params['newPricePoint'],
                            'new_pp_id': rpcdata.params['new_pp_id'] \
                                        if rpcdata.params['new_pp_id'] is not None \
                                            else randint(0, 99999999), 
                            'new_pp_isoptimal': rpcdata.params['new_pp_isoptimal'] \
                                        if rpcdata.params['new_pp_isoptimal'] is not None \
                                            else False
                            }
                    #post the new new price point from us to the local-us-bus
                    result = self._postPricePoint(**args)
                elif rpcdata.method == "rpc_ping":
                    result = True
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
        def onNewPrice(self, peer, sender, bus,  topic, headers, message):
            if self._bridge_host == 'LEVEL_TAILEND':
                return
                
            new_price_point     = message[0]
            new_pp_id           = message[2] if message[2] is not None else randint(0, 99999999)
            new_pp_isoptimal    = message[3] if message[3] is not None else False
            _log.debug("*** New Price Point: {0:.2f} ***".format(new_price_point))
            _log.debug("*** new_pp_id: " + str(new_pp_id))
            _log.debug("*** new_pp_isoptimal: " + str(new_pp_isoptimal))
            
            self._processNewPricePoint(new_price_point, new_pp_id, new_pp_isoptimal)
            return
            
        #energy demand on local bus published, post it to upstream bridge
        def onNewEnergyDemand(self, peer, sender, bus,  topic, headers, message):
            if self._bridge_host == 'LEVEL_HEAD':
                #do nothing
                return
                
            newEnergyDemand = message[0]
            ed_pp_id = message[2] if message[2] is not None else randint(0, 99999999)
            _log.debug ( "*** New Energy Demand: {0:.4f} ***".format(newEnergyDemand)+' pp_id:' + str(ed_pp_id))
            
            self._ed_previous = self._ed_current
            self._ed_current = newEnergyDemand
            self._ed_pp_id = ed_pp_id
            self._us_retrycount = 0
            self._postUsEnergyDemand()
            return
            
        #perodically keeps trying to post ed to us
        def _postUsEnergyDemand(self):
            post_ed = False
            
            url_root = 'http://' + self._us_ip_addr + ':' + str(self._us_port) + '/VolttronBridge'
            
            #check for upstream connection, if not retry once
            _log.debug('check us connection...')
            if not self._usConnected:
                _log.debug('not connected, Trying to register once...')
                self._usConnected = self._registerToUsBridge(url_root,\
                                                                self._discovery_address,\
                                                                self._deviceId)
                if not self._usConnected:
                    _log.debug('_usConnected: ' + str(self._usConnected))
                    _log.debug('Failed to register, May be upstream bridge is not running!!!')
                    return
                else:
                    post_ed = True
                    
            _log.debug('_usConnected: ' + str(self._usConnected))
            
            #we want to post to us only if there is change in energy demand
            if isclose(self._ed_current, self._ed_previous, EPSILON) and post_ed == False:
                _log.debug('No change in energy demand, do nothing')
                return
                
            _log.debug("posting energy demand to upstream VolttronBridge")
            success = self.do_rpc(url_root, 'rpc_postEnergyDemand', \
                            {'discovery_address': self._discovery_address, \
                                'deviceId': self._deviceId, \
                                'newEnergyDemand': self._ed_current,
                                'ed_pp_id': self._ed_pp_id
                            })
            #_log.debug('success: ' + str(success))
            if success:
                _log.debug("Success!!!")
                self._us_retrycount = 0
                self._ed_previous = self._ed_current
            else :
                _log.debug("Failed!!!")
                self._us_retrycount = self._us_retrycount + 1
                if self._us_retrycount > MAX_RETRIES:
                    _log.debug('failed too many times to post ed, reset counter and yeild for a movement!!!')
                    self._usConnected = False
                    self._us_retrycount = 0
                    time.sleep(10) #yeild for a movement
                    
            return
            
        #price point on local bus changed post it to ds
        def _processNewPricePoint(self, new_price_point, new_pp_id, new_pp_isoptimal):
            #_log.debug('_processNewPricePoint()')
            #we want to post to ds only if there is change in price point
            if isclose(self._pp_current, new_price_point, EPSILON) and \
                            self._pp_id == new_pp_id and \
                            self._pp_isoptimal == new_pp_isoptimal :
                _log.debug('no change, do nothing')
                return
            self._pp_current = self._pp_new
            self._pp_new = newPricePoint
            self._pp_id = new_pp_id
            self._pp_isoptimal = new_pp_isoptimal
            self._reset_ds_retrycount(self)
            self._postDsNewPricePoint()
            return
            
        def _reset_ds_retrycount(self):
            for discovery_address in self._ds_voltBr:
                index = self._ds_voltBr.index(discovery_address)
                self._ds_retrycount[index] = 0
            return
            
        #perodically keeps trying to post pp to ds
        def _postDsNewPricePoint(self):
            #we want to post to ds only if there is change in price point
            if isclose(self._pp_current, self._pp_new, EPSILON) and \
                    self._all_ds_posts_success :
                _log.debug('No change in price point, do nothing')
                return
                
            self._all_ds_posts_success  = True
            for discovery_address in self._ds_voltBr:
                index = self._ds_voltBr.index(discovery_address)
                
                if self._ds_retrycount[index] > MAX_RETRIES:
                    #maybe already posted or failed more than max retries, do nothing
                    continue
                    
                url_root = 'http://' + discovery_address + '/VolttronBridge'
                result = self.do_rpc(url_root, 'rpc_postPricePoint', \
                                        {'discovery_address': self._discovery_address, \
                                        'deviceId': self._deviceId, \
                                        'newPricePoint': self._pp_current, \
                                        'new_pp_id': self._pp_id, \
                                        'new_pp_isoptimal': self._pp_isoptimal \
                                        })
                if result:
                    #success, reset retry count
                    self._ds_retrycount[index] = MAX_RETRIES + 1    #no need to retry on the next run
                    _log.debug("post to:" + discovery_address + " sucess!!!")
                    self._pp_current = self._pp_new                 #atleast one success, update pp
                else:
                    #failed to post, increment retry count
                    self._ds_retrycount[index] = self._ds_retrycount[index]  + 1
                    _log.debug("post to:" + discovery_address + \
                                " failed, count: {0:d} !!!".format(self._ds_retrycount[index]))
                    self._all_ds_posts_success  = False
                        
            return
            
        def _postDsNewPricePoint(self, discovery_address, newPricePoint, new_pp_id, new_pp_isoptimal):
            _log.debug('_postDsNewPricePoint() to : ' + discovery_address)
            
            url_root = 'http://' + discovery_address + '/VolttronBridge'
            result = self.do_rpc(url_root, 'rpc_postPricePoint', \
                                    {'discovery_address': self._discovery_address, \
                                    'deviceId': self._deviceId, \
                                    'newPricePoint': newPricePoint, \
                                    'new_pp_id': new_pp_id, \
                                    'new_pp_isoptimal': new_pp_isoptimal \
                                    })
            return result
            
        def _registerDsBridge(self, discovery_address, deviceId):
            _log.debug('_registerDsBridge(), discovery_address: ' + discovery_address + ' deviceId: ' + deviceId)
            if discovery_address in self._ds_voltBr:
                _log.debug('already registered!!!')
                index = self._ds_voltBr.index(discovery_address)
                self._ds_retrycount[index] = 0
                return True
                
            #TODO: potential bug in this method, not atomic
            self._ds_voltBr.append(discovery_address)
            index = self._ds_voltBr.index(discovery_address)
            self._ds_deviceId.insert(index, deviceId)
            self._ds_retrycount.insert(index, 0)
            
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
            del self._ds_retrycount[index]
            _log.debug('unregistered!!!')
            return True
            
        #post the new price point from us to the local-us-bus
        def _postPricePoint(self, discovery_address, deviceId, newPricePoint, new_pp_id, new_pp_isoptimal):
            _log.debug ( "*** New Price Point(us): {0:.2f} ***".format(newPricePoint))
            _log.debug("*** new_pp_id: " + str(new_pp_id))
            _log.debug("*** new_pp_isoptimal: " + str(new_pp_isoptimal))

            #post to bus
            _log.debug('post the new price point from us to the local-us-bus')
            pubTopic =  pricePoint_topic_us
            pubMsg = [newPricePoint,{'units': 'cents', 'tz': 'UTC', 'type': 'float'}, new_pp_id, new_pp_isoptimal]
            publish_to_bus(self, pubTopic, pubMsg)
            return True
            
        #post the new energy demand from ds to the local bus
        def _postEnergyDemand(self, discovery_address, deviceId, newEnergyDemand, ed_pp_id):
            _log.debug ( "*** New Energy Demand: {0:.4f} ***".format(newEnergyDemand) + ' ed_pp_id'+ str(ed_pp_id)+' from: ' + deviceId)
            if discovery_address in self._ds_voltBr:
                index = self._ds_voltBr.index(discovery_address)
                if self._ds_deviceId[index] == deviceId:
                    #post to bus
                    pubTopic = energyDemand_topic_ds + "/" + deviceId
                    pubMsg = [newEnergyDemand,{'units': 'W', 'tz': 'UTC', 'type': 'float'}, ed_pp_id, deviceId, len(self._ds_deviceId)]
                    publish_to_bus(self, pubTopic, pubMsg)
                    self._ds_retrycount[index] = 0
                    _log.debug("...Done!!!")
                    return True
            _log.debug("...Failed!!!")
            return False
            
        def do_rpc(self, url_root, method, params=None ):
            #_log.debug('do_rpc()')
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
                response = requests.post(url_root, data=json.dumps(json_package), timeout=10)
                
                if response.ok:
                    success = response.json()['result']
                    if success:
                        #_log.debug('response - ok, {} result:{}'.format(method, success))
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
                _log.warning('Exception: do_rpc() unhandled exception, most likely dest is down')
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
        
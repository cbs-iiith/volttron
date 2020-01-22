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
import random

from volttron.platform.vip.agent import Agent, Core, PubSub, compat, RPC
from volttron.platform.agent import utils
from volttron.platform.messaging import topics, headers as headers_mod

import time
import gevent
import gevent.event

utils.setup_logging()
_log = logging.getLogger(__name__)
__version__ = '0.3'

MAX_RETRIES = 5
MAX_THPP = 1
MIN_THPP = 0

def ss_sh_device(config_path, **kwargs):

    config = utils.load_config(config_path)
    agentid = config['agentid']
    message = config['message']
    
    '''
    This agent runs on the smart strip and controls the plug to which the smart hub is connected.
        
    sh_btry_th = 1 if the battery charge level is above a certain charge threshold
               = 0

    sh_brty_level = 100 (0-100)
    sh_on_btry = True

    sh_on_btry_start_time
    sh_on_grid_start_time
    
    
    Process-I (when PP changes, subscribe to ss_pp_topic)
        If the price point is more than the SmartHub threshold pricepoint && sh_btry_th = 1, 
            change th_pp to 1 for the plug to which hub is connected (ss will switch-off the plug)
            sh_on_btry = True
            if sh_on_btry_start_time != 0
                charge_time = now() - sh_on_btry_start_time
                sh_brty_level = sh_brty_level -  charge_time * charge_rate (decrease the btry level)
            sh_on_btry_start_time = now()
                
        If the price point is less than the SmartHub threshold pricepoint
            change th_pp to 0 for the plug to which hub is connected (ss will switch-on the plug)
            sh_on_btry = False
            if sh_on_grid_start_time != 0
                charge_time = now() - sh_on_grid_start_time
                sh_brty_level = sh_brty_level +  charge_time * charge_rate (increase the btry level)
            sh_on_grid_start_time = now()
    
    Process-II (at regular interval)
        This agent pings the Upstream SmartHub to see if it is active.
        If the upstream SmartHub is not alive and plug relay state is off, 
            sh_btry_th = 0 (assume that battery depleted)
            change th_pp to 0 for the plug to which hub is connected (ss will switch-on the plug)
            sh_on_grid_start_time = now()
    
    Process-III (at regular interval)
        monitor hub Battery (fuel guage)
        if running on battery for more than 2 hours
               sh_btry_th = 0 
        after certain amount of time (when batter is charged to a threshold limit) sh_btry_th = 1

    '''
    class SS_SH_Device(Agent):
        
        def __init__(self, **kwargs):
            _log.debug('__init__()')
            super(SS_SH_Device, self).__init__(**kwargs)
            
            self._configGetInitValues()
            return
            
        @Core.receiver('onsetup')
        def setup(self, sender, **kwargs):
            _log.info(config['message'])
            self._agent_id = config['agentid']            
            return
            
        @Core.receiver('onstart')            
        def startup(self, sender, **kwargs):
            _log.debug('startup()')
            self.hub_ping_count = 0
            self.core.periodic(self.period_read, self._pingSmartHub, wait=None)
            self.core.periodic(self.period_read, self._monitorShBattery, wait=None)
            self.vip.pubsub.subscribe("pubsub", self.ss_pp_topic, self.on_new_price)
            return
            
        @Core.receiver('onstop')
        def onstop(self, sender, **kwargs):
            _log.debug('onstop()')
            return
            
        def _configGetInitValues(self):
            self.period_read = config.get("period_read", 10)
            self.sh_ip_addr = config.get("sh_ip_addr", "192.168.1.50")
            self.sh_port = config.get("sh_port", 8080)
            self.sh_plug_id = config.get("sh_plug_id", 4)
            self.sh_th_pp = config.get("sh_threshold_pp", 0.5)
            self.ss_pp_topic = config.get("ss_pp_topic", "smartstrip/pricepoint")
            return
            
        def on_new_price(self, peer, sender, bus,  topic, headers, message):
            new_price_point = message[0]
            if self._price_point == new_price_point:
                return
                
            if not sh_on_btry and new_price_point > self.sh_th_pp and sh_btry_th == 1:
                #change th_pp to max for the plug to which hub is connected (ss will switch-off the plug)
                plugOff = self.vip.rpc.call('iiit.smartstrip'
                                            , 'setThresholdPP'
                                            , self.sh_plug_id
                                            , MAX_THPP
                                            ).get(timeout=10)
                
                if plugOff:
                    sh_on_btry = True
                    sh_on_btry_start_time = datetime.datetime.utcnow()
                else:
                    #dont know what to do
                    pass
                    
            if sh_on_btry and new_price_point <= self.sh_th_pp:
                #change th_pp to min for the plug to which hub is connected (ss will switch-on the plug)
                plugOn = self.vip.rpc.call('iiit.smartstrip'
                                            , 'setThresholdPP'
                                            , self.sh_plug_id
                                            , MIN_THPP
                                            ).get(timeout=10)
                                            
                if plugOn:
                    sh_on_btry = False
                    sh_on_grid_start_time = datetime.datetime.utcnow()
                else:
                    #dont know what to do
                    pass
                    
            self._price_point = new_price_point
            return
            
        def _pingSmartHub(self):
            _log.debug('_pingSmartHub()')
            url_root = 'http://' + self.sh_ip_addr + ':' + str(self.sh_port) + '/SmartHub'
            if not sh_on_btry or self.do_rpc(url_root, 'rpc_ping'):
                #hub is not on btry or hub is alive, do nothing
                self.hub_ping_count = 0
                return
                
            self.hub_ping_count = self.hub_ping_count + 1
            _log.debug('not pinging, ping count: ' +str(self.hub_ping_count))
                
            if self.hub_ping_count > MAX_RETRIES:
                _log.debug('ping count > MAX_RETRIES, switch on power to hub')
                plugOn = self.vip.rpc.call('iiit.smartstrip',
                                        'setThresholdPP',
                                        self.sh_plug_id,
                                        MIN_THPP
                                        ).get(timeout=10)
                if plugOn:
                    _log.debug('thpp updated successfuly, hopefull ss will switch-on power!!!')
                    sh_on_btry = False
                    sh_on_grid_start_time = datetime.datetime.utcnow()
                else:
                    _log.debug('failed to switch on power, will try in next iteration')
                    self.hub_ping_count = 0
                    
            return
            
        def _monitorShBattery(self):
            return
            
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
                else:
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
            
    Agent.__name__ = 'SS_SH_Device_Agent'
    return SS_SH_Device(**kwargs)
    
def main(argv=sys.argv):
    '''Main method called by the eggsecutable.'''
    try:
        utils.vip_main(ss_sh_device)
    except Exception as e:
        print (e)
        _log.exception('unhandled exception')
        
if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv))
    except KeyboardInterrupt:
        pass
        
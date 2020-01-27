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
import dateutil
from enum import IntEnum
import logging
from random import randint

from volttron.platform.agent import utils
from volttron.platform import jsonrpc

from ispace_utils import mround

utils.setup_logging()
_log = logging.getLogger(__name__)


ROUNDOFF_PRICE_POINT = 0.01
ROUNDOFF_BUDGET = 10
ROUNDOFF_ACTIVE_POWER = 0.0001
ROUNDOFF_ENERGY = 0.0001

class MessageType(IntEnum):
    price_point = 0
    budget = 1
    active_power = 2
    energy = 3
    pass


class ISPACE_Msg:
    
    '''
    [type, value, value_data_type, units
                , price_id, isoptimal
                , src_ip, src_device_id
                , dst_ip, dst_device_id
                , duration, ttl, ts, tz
                ]
    '''
    type = None
    value = None
    value_data_type = None
    units = None
    price_id = None
    isoptimal = None
    #msg_from_remote_device = True if src_ip == local_ip else False
    src_ip = None
    src_device_id = None
    dst_ip = None
    dst_device_id = None
    duration = None
    ttl = None
    ts = None
    tz  = None
    
    def __init__(self, type = None
                    , isoptimal = None
                    , value = None
                    , value_data_type = None
                    , units = None
                    , price_id = None
                    , src_ip = None
                    , src_device_id = None
                    , dst_ip = None
                    , dst_device_id = None
                    , duration = None
                    , ttl = None
                    , ts = None
                    , tz = None
                    ):
        self.type = type
        self.value = value
        self.value_data_type = value_data_type
        self.units = units
        self.price_id = price_id
        self.isoptimal = isoptimal
        self.src_ip = src_ip
        self.src_device_id = src_device_id
        self.dst_ip = dst_ip
        self.dst_device_id = dst_device_id
        self.duration = duration
        self.ttl = ttl
        self.ts = ts
        self.tz = tz
        return
        
    #str overload to return class attributes as json params str
    def __str__(self):
        #_log.debug('__str__()')
        params = {}
        params['type'] = self.type
        params['value'] = self.value
        params['value_data_type'] = self.value_data_type
        params['units'] = self.units
        params['price_id'] = self.price_id
        params['isoptimal'] = self.isoptimal
        params['src_ip'] = self.src_ip
        params['src_device_id'] = self.src_device_id
        params['dst_ip'] = self.dst_ip
        params['dst_device_id'] = self.dst_device_id
        params['duration'] = self.duration
        params['ttl'] = self.ttl
        params['ts'] = self.ts
        params['tz'] = self.tz
        #_log.debug('params: {}'.format(params))
        return str(params)
                
    def ttl_timeout(self):
        #live for ever
        if self.ttl < 0:
            _log.warning('ttl: {} < 0, do nothing!!!'.format(self.ttl))
            return False
            
        if self.tz == 'UTC':
            ts  = dateutil.parser.parse(self.ts)
            now = dateutil.parser.parse(datetime.datetime.utcnow().isoformat(' ') + 'Z')
            check = True if (now - ts).total_seconds() > self.ttl else False
            return check
        else:
            _log.warning('ttl_timeout(), unknown tz: {}'.format(self.tz))
            return False
            
    def decrement_ttl(self):
        #live for ever
        if self.ttl < 0:
            _log.warning('ttl: {} < 0, do nothing!!!'.format(self.ttl))
            return False
            
        if self.tz == 'UTC':
            ts  = dateutil.parser.parse(self.ts)
            now = dateutil.parser.parse(datetime.datetime.utcnow().isoformat(' ') + 'Z')
            #_log.debug('ts: {}, now: {}'.format(ts, now))
            self.ttl = self.ttl - (mround((now -ts).total_seconds(),1) + 1)
            return True
        else:
            _log.warning('decrement_ttl(), unknown tz: {}'.format(self.tz))
            return False
            
    def get_pub_msg(self):
        return str(self)
                
    #check for mandatory fields in the message
    def valid_msg(self, mandatory_fields = []):
        for idx in mandatory_fields:
            if idx == 'type' and self.type is None:
                return False
            elif idx == 'value' and self.value is None:
                return False
            elif idx == 'value_data_type' and self.value_data_type is None:
                return False
            elif idx == 'units' and self.units is None:
                return False
            elif idx == 'price_id' and self.price_id is None:
                return False
            elif idx == 'isoptimal' and self.isoptimal is None:
                return False
            elif idx == 'src_ip' and self.src_ip is None:
                return False
            elif idx == 'src_device_id' and self.src_device_id is None:
                return False
            elif idx == 'dst_ip' and self.dst_ip is None:
                return False
            elif idx == 'dst_device_id' and self.dst_device_id is None:
                return False
            elif idx == 'duration' and self.duration is None:
                return False
            elif idx == 'ttl' and self.ttl is None:
                return False
            elif idx == 'ts' and self.ts is None:
                return False
            elif idx == 'tz' and self.tz is None:
                return False
        return True
    
    #validate various sanity measure like, valid fields, valid pp ids, ttl expire, etc.,
    def sanity_check_ok(self, hint = None, mandatory_fields = [], valid_price_ids = []):
        if not self.valid_msg(mandatory_fields):
            _log.warning('rcvd a invalid msg, message: {}, do nothing!!!'.format(message))
            return False
            
        #print only if a valid msg
        _log.info('Hint: {}, Msg: {}'.format(hint, self))
        
        #process msg only if price_id corresponds to these ids
        if valid_price_ids != [] and self.price_id not in valid_price_ids:
            _log.debug('pp_id: {}'.format(self.price_id)
                        + ' not in valid_price_ids: {}, do nothing!!!'.format(valid_price_ids))
            return False
            
        #process msg only if msg is alive (didnot timeout)
        if self.ttl_timeout():
            _log.warning('msg ttl expired, do nothing!!!')
            return False
            
        return True
    
    #return class attributes as json params that can be passed to do_rpc()
    def get_json_params(self):
        return str(self)
        
    #getters
    def get_type(self):
        return self.type
        
    def get_value(self):
        return self.value
        
    def get_value_data_type(self):
        return self.value_data_type
        
    def get_units(self):
        return self.units
        
    def get_price_id(self):
        return self.price_id
        
    def get_isoptimal(self):
        return self.isoptimal
        
    def get_src_ip(self):
        return self.src_ip
        
    def get_src_device_id(self):
        return self.src_device_id
        
    def get_dst_ip(self):
        return self.dst_ip
        
    def get_dst_device_id(self):
        return self.dst_device_id
        
    def get_duration(self):
        return self.duration
        
    def get_ttl(self):
        return self.ttl
        
    def get_ts(self):
        return self.ts
        
    def get_tz(self):
        return self.tz
        
    #setters
    def set_type(self, type):
        #_log.debug('set_type()')
        self.type = type
        
    def set_value(self, value):
        #_log.debug('set_value()')
        if self.type == MessageType.price_point:
            self.value = mround(value, ROUNDOFF_PRICE_POINT)
        elif self.type == MessageType.budget:
            self.value = mround(value, ROUNDOFF_BUDGET)
        elif self.type == MessageType.active_power:
            self.value = mround(value, ROUNDOFF_ACTIVE_POWER)
        elif self.type == MessageType.energy:
            self.value = mround(value, ROUNDOFF_ENERGY)
        else:
            #_log.debug('else')
            self.value = value
        
    def set_value_data_type(self, value_data_type):
        self.value_data_type = value_data_type
        
    def set_units(self, units):
        self.units = units
        
    def set_price_id(self, price_id):
        self.price_id = price_id
        
    def set_isoptimal(self, isoptimal):
        self.isoptimal = isoptimal
        
    def set_src_ip(self, src_ip):
        self.src_ip = src_ip
        
    def set_src_device_id(self, src_device_id):
        self.src_device_id = src_device_id
        
    def set_dst_ip(self, dst_ip):
        self.dst_ip = dst_ip
        
    def set_dst_device_id(self, dst_device_id):
        self.dst_device_id = dst_device_id
        
    def set_duration(self, duration):
        self.duration = duration
        
    def set_ttl(self, ttl):
        self.ttl = ttl
        
    def set_ts(self, ts):
        self.ts = ts
        
    def set_tz(self, tz):
        self.tz = tz
        
    pass
    
    
#converts bus message into an ispace_msg
def parse_bustopic_msg(message, mandatory_fields = []):
    return _parse_data(message, mandatory_fields)
    
#converts jsonrpc_msg into an ispace_msg
def parse_jsonrpc_msg(message, mandatory_fields = []):
    data = jsonrpc.JsonRpcData.parse(message).params
    return _parse_data(data, mandatory_fields)
    
def _update_value(new_msg, attrib, new_value):
    if attrib == 'type':
        new_msg.set_type(new_value)
    elif attrib == 'value':
        new_msg.set_value(new_value)
    elif attrib == 'value_data_type':
        new_msg.set_value_data_type(new_value)
    elif attrib == 'units':
        new_msg.set_units(new_value)
    elif attrib == 'price_id':
        new_msg.set_price_id(new_value if new_value is not None else randint(0, 99999999))
    elif attrib == 'isoptimal':
        new_msg.set_isoptimal(new_value)
    elif attrib == 'src_ip':
        new_msg.set_src_ip(new_value)
    elif attrib == 'src_device_id':
        new_msg.set_src_device_id(new_value)
    elif attrib == 'dst_ip':
        new_msg.set_dst_ip(new_value)
    elif attrib == 'dst_device_id':
        new_msg.set_dst_device_id(new_value)
    elif attrib == 'duration':
        new_msg.set_duration(new_value if new_value is not None else 3600)
    elif attrib == 'ttl':
        new_msg.set_ttl(new_value if new_value is not None else -1)
    elif attrib == 'ts':
        new_msg.set_ts(new_value if new_value is not None
                                else datetime.datetime.utcnow().isoformat(' ') + 'Z')
    elif attrib == 'tz':
        new_msg.set_tz(new_value if new_value is not None else 'UTC')
    return
    
def _parse_data(data, mandatory_fields = []):
    full_list = [ 'type', 'value', 'value_data_type', 'units'
                    , 'price_id', 'isoptimal'
                    , 'src_ip', 'src_device_id'
                    , 'dst_ip', 'dst_device_id'
                    , 'duration', 'ttl', 'ts', 'tz'
                    ]
                    
    new_msg = ISPACE_Msg()
    #if list is empty, parse all attributes
    if mandatory_fields == []:
        _log.warning('mandatory_fields to check against is empty!!!')
        #if the param is not found, throws a keyerror exception
        new_msg.set_type(data['type'])
        new_msg.set_value(data['value'])
        new_msg.set_value_data_type(data['value_data_type']
                                        if data['tz'] is not None
                                        else 'float'
                                        )
        new_msg.set_units(data['units'])
        new_msg.set_price_id(data['price_id']
                                        if data['price_id'] is not None
                                        else randint(0, 99999999)
                                        )
        new_msg.set_isoptimal(data['isoptimal'])
        new_msg.set_src_ip(data['src_ip'])
        new_msg.set_src_device_id(data['src_device_id'])
        new_msg.set_dst_ip(data['dst_ip'])
        new_msg.set_dst_device_id(data['dst_device_id'])
        new_msg.set_duration(data['duration']
                                        if data['duration'] is not None
                                        else 3600
                                        )
        new_msg.set_ttl(data['ttl']
                                        if data['ttl'] is not None
                                        else -1
                                        )
        new_msg.set_ts(data['ts']
                                        if data['ts'] is not None
                                        else datetime.datetime.utcnow().isoformat(' ') + 'Z'
                                        )
        new_msg.set_tz(data['tz']
                                        if data['tz'] is not None
                                        else 'UTC'
                                        )
    else:
        #_log.debug('mandatory_fields is NOT empty!!!')
        for attrib in mandatory_fields:
            #if the param is not found, throws a keyerror exception
            _update_value(new_msg, attrib, data[attrib])
        #do a second pass to also get params not in the mandatory_fields
        #if key not found, catch the exception and pass to continue with next key
        for attrib in full_list:
            if attrib not in mandatory_fields:
                try:
                    _update_value(new_msg, attrib, data[attrib])
                except KeyError:
                    _log.warning('key: {}, not available in the data'.format(attrib))
                    pass
                    
    return new_msg
        
        
class ISPACE_Msg_OptPricePoint(ISPACE_Msg):
    def __init__(self):
        super().__init__(self, MessageType.price_point, True)
        return
    pass
    
    
class ISPACE_Msg_BidPricePoint(ISPACE_Msg):
    def __init__(self):
        super().__init__(self, MessageType.price_point, False)
        return
    pass
    
    
class ISPACE_Msg_ActivePower(ISPACE_Msg):
    def __init__(self):
        super().__init__(self, MessageType.active_power, True)
        return
    pass
    
    
class ISPACE_Msg_Energy(ISPACE_Msg):
    def __init__(self):
        super().__init__(self, MessageType.energy, False)
        return
    pass
    
    
class ISPACE_Msg_Budget(ISPACE_Msg):
    def __init__(self):
        super().__init__(self, MessageType.budget)
        return
    pass
    
    
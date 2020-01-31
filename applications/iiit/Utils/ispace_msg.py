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
import json

from volttron.platform.agent import utils
from volttron.platform import jsonrpc

from ispace_utils import mround, publish_to_bus

utils.setup_logging()
_log = logging.getLogger(__name__)


ROUNDOFF_PRICE_POINT = 0.01
ROUNDOFF_BUDGET = 0.0001
ROUNDOFF_ACTIVE_POWER = 0.0001
ROUNDOFF_ENERGY = 0.0001

ISPACE_MSG_ATTRIB_LIST = ['msg_type', 'one_to_one', 'isoptimal'
                            , 'value', 'value_data_type', 'units'
                            , 'price_id'
                            , 'src_ip', 'src_device_id'
                            , 'dst_ip', 'dst_device_id'
                            , 'duration', 'ttl', 'ts', 'tz'
                            ]
                            
                            
class MessageType(IntEnum):
    price_point = 0
    budget = 1
    active_power = 2
    energy_demand = 3
    pass
    
    
class ISPACE_Msg:
    ''' iSPACE Message base class
    '''
    #TODO: enchancement - need to add a msg uuid, also convert price_id to use uuid instead for radint
    msg_type = None
    one_to_one = None
    isoptimal = None
    value = None
    value_data_type = None
    units = None
    price_id = None
    #msg_from_remote_device = True if src_ip == local_ip else False
    src_ip = None
    src_device_id = None
    dst_ip = None
    dst_device_id = None
    duration = None
    #TODO: currelty ttl is in seconds, maybe changed to milliseconds for better performance
    ttl = None
    ts = None
    tz  = None
    
    def __init__(self, msg_type
                    , one_to_one = None
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
        if msg_type is not None: self.set_msg_type(msg_type)
        if one_to_one is not None: self.set_one_to_one(one_to_one)
        if value is not None: self.set_value(value)
        if value_data_type is not None: self.set_value_data_type(value_data_type)
        if units is not None: self.set_units(units)
        if price_id is not None: self.set_price_id(price_id)
        if isoptimal is not None: self.set_isoptimal(isoptimal)
        if src_ip is not None: self.set_src_ip(src_ip)
        if src_device_id is not None: self.set_src_device_id(src_device_id)
        if dst_ip is not None: self.set_dst_ip(dst_ip)
        if dst_device_id is not None: self.set_dst_device_id(dst_device_id)
        if duration is not None: self.set_duration(duration)
        if ttl is not None: self.set_ttl(ttl)
        if ts is not None: self.set_ts(ts)
        if tz is not None: self.set_tz(tz)
        return
        
    #str overload to return class attributes as str dict
    def __str__(self):
        #_log.debug('__str__()')
        params = self._get_params_dict()
        return str(params)
                
    def _get_params_dict(self):
        params = {}
        params['msg_type'] = self.msg_type
        params['one_to_one'] = self.one_to_one
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
        return params

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
        if self.ttl <= 0:
            _log.warning('ttl: {} < 0, do nothing!!!'.format(self.ttl))
            return False
            
        if self.tz == 'UTC':
            ts  = dateutil.parser.parse(self.ts)
            now = dateutil.parser.parse(datetime.datetime.utcnow().isoformat(' ') + 'Z')
            self.ttl = int((self.ttl - mround((now - ts).total_seconds(), 1)) - 1 )
            return True
        else:
            _log.warning('decrement_ttl(), unknown tz: {}'.format(self.tz))
            return False
            
    #check for mandatory fields in the message
    def valid_msg(self, validate_fields = []):
        for attrib in validate_fields:
            #null value check
            if self._is_attrib_null(attrib):
                return False
            #TODO: data validations checks based on message type and field type
        return True
    
    def _is_attrib_null(self, attrib):
        if attrib == 'msg_type' and self.msg_type is None:
            return True
        elif attrib == 'one_to_one' and self.one_to_one is None:
            return True
        elif attrib == 'value' and self.value is None:
            return True
        elif attrib == 'value_data_type' and self.value_data_type is None:
            return True
        elif attrib == 'units' and self.units is None:
            return True
        elif attrib == 'price_id' and self.price_id is None:
            return True
        elif attrib == 'isoptimal' and self.isoptimal is None:
            return True
        elif attrib == 'src_ip' and self.src_ip is None:
            return True
        elif attrib == 'src_device_id' and self.src_device_id is None:
            return True
        elif attrib == 'dst_ip' and self.dst_ip is None:
            return True
        elif attrib == 'dst_device_id' and self.dst_device_id is None:
            return True
        elif attrib == 'duration' and self.duration is None:
            return True
        elif attrib == 'ttl' and self.ttl is None:
            return True
        elif attrib == 'ts' and self.ts is None:
            return True
        elif attrib == 'tz' and self.tz is None:
            return True
        return False
        
    #validate various sanity measure like, valid fields, valid pp ids, ttl expire, etc.,
    def sanity_check_ok(self, hint = None, validate_fields = [], valid_price_ids = []):
        if not self.valid_msg(validate_fields):
            _log.warning('rcvd a invalid msg, message: {}, do nothing!!!'.format(message))
            return False
            
        #print only if a valid msg
        _log.info('{} Msg: {}'.format(hint, self))
        
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
        
    def check_dst_addr(self, device_id, ip_addr):
        return (False if self.one_to_one and 
                            (device_id != self.dst_device_id or ip_addr != self.dst_ip)
                            else True)
                            
    #return class attributes as json params that can be passed to do_rpc()
    def get_json_params(self, id='123456789'):
        json_package = {
            'jsonrpc': '2.0',
            'id': id,
            'method':'bus_topic',
        }
        json_package['params'] = self._get_params_dict()
        data = json.dumps(json_package)
        return data
        
    #getters
    def get_msg_type(self):
        return self.msg_type
        
    def get_one_to_one(self):
        return self.one_to_one
        
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
    def set_msg_type(self, msg_type):
        #_log.debug('set_msg_type({})'.format(msg_type))
        self.msg_type = int(msg_type)
        
    def set_one_to_one(self, one_to_one):
        self.one_to_one = one_to_one
        
    def set_value(self, value):
        #_log.debug('set_value()')
        #_log.debug('self.msg_type: {}, MessageType.price_point: {}'.format(self.msg_type, MessageType.price_point))
        if self.msg_type == MessageType.price_point:
            tmp_value = mround(value, ROUNDOFF_PRICE_POINT)
            self.value = 0 if tmp_value <= 0 else 1 if tmp_value >= 1 else tmp_value
        elif self.msg_type == MessageType.budget:
            self.value = mround(value, ROUNDOFF_BUDGET)
        elif self.msg_type == MessageType.active_power:
            self.value = mround(value, ROUNDOFF_ACTIVE_POWER)
        elif self.msg_type == MessageType.energy_demand:
            self.value = mround(value, ROUNDOFF_ENERGY)
        else:
            _log.debug('else')
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
        super().__init__(self, MessageType.energy_demand, False)
        return
    pass
    
    
class ISPACE_Msg_Budget(ISPACE_Msg):
    def __init__(self):
        super().__init__(self, MessageType.budget)
        return
    pass
    
    
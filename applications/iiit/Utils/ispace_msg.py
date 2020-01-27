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
from enum import IntEnum


class MessageType(IntEnum):
    price_point = 0
    budget = 1
    active_power = 2
    energy = 3
    pass


class ISPACE_Msg:
    
    type = MessageType.price_point
    value = 0
    value_data_type = 'float'
    units = 'cents'
    price_id = None
    isoptimal = None
    src_ip = None
    src_device_id = None
    dst_ip = None
    dst_device_id = None
    duration = 3600
    ttl = -1
    ts = datetime.datetime.utcnow().isoformat(' ') + 'Z'
    tz  = 'UTC'
    
    __init__(self, type = None
                    , value = None
                    , value_data_type = None
                    , units = None
                    , price_id = None
                    , isoptimal = None
                    , discovery_addrs = None
                    , device_id = None
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
        self.discovery_addrs = discovery_addrs
        self.device_id = device_id
        self.duration = duration
        self.ttl = ttl
        self.ts = ts
        self.tz = tz
        return
        
    def __str__(self):
        return ('{type: {}, value: {0.2f}, value_data_type: {}, units:{}'.format(type, 
                                                                                    value
                                                                                    , value_data_type
                                                                                    , units)
                + ', {price_id: {}, isoptimal: {}'.format(price_id, isoptimal)
                + ', {src_ip: {}, src_device_id: {}'.format(src_ip
                                                                            , src_device_id)
                + ', {dst_ip: {}, dst_device_id: {}, id: {}, isoptimal:{}'.format(dst_ip, dst_device_id)
                + ', {duration: {}, ttl: {}, ts: {}, tz:{}'.format()
                )
                
    def ttl_timeout():
            if self.ttl < 0:
                return False
            ts  = dateutil.parser.parse(self.ts)
            now = dateutil.parser.parse(datetime.datetime.utcnow().isoformat(' ') + 'Z')
            return (True if (now - ts) > self.ttl else False)
        return
        
    def get_pub_msg(self):
        return[type, value, value_data_type, units
                , price_id, isoptimal
                , src_ip, src_device_id
                , dst_ip, dst_device_id
                , duration, ttl, ts, tz
                ]
                
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
    
    def sanity_check(self, mandatory_fields = [], valid_price_ids = []):
        if not self.valid_msg(mandatory_fields):
            _log.warning('rcvd a invalid msg, message: {}, do nothing!!!'.format(message))
            return False
            
        #print only if a valid msg
        #print_pp_msg(message)
        
        #process msg only if price_id corresponds to these ids
        if valid_price_ids != [] and self.price_id not in valid_price_ids:
            _log.debug('pp_id: {}'.format(self.price_id)
                        + ' not in valid_price_ids: {}, do nothing!!!'.format(valid_price_ids))
            return False
            
        #process msg only if msg is alive (didnot timeout)
        if self.ttl_timeout():
            _log.warning('msg timed out, do nothing!!!')
            return False
            
    return True
    
    #return class attributes as json params that can be passed to do_rpc()
    def get_json_params(self):
        params = {}
        if self.type is None:
            params['type'] = self.type
        if self.value is None:
            params['value'] = self.value
        if self.value_data_type is None:
            params['value_data_type'] = self.value_data_type
        if self.units is None:
            params['units'] = self.units
        if self.price_id is None:
            params['price_id'] = self.price_id
        if self.isoptimal is None:
            params['isoptimal'] = self.isoptimal
        if self.src_ip is None:
            params['src_ip'] = self.src_ip
        if self.src_device_id is None:
            params['src_device_id'] = self.src_device_id
        if self.dst_ip is None:
            params['dst_ip'] = self.dst_ip
        if self.dst_device_id is None:
            params['dst_device_id'] = self.dst_device_id
        if self.duration is None:
            params['duration'] = self.duration
        if self.ttl is None:
            params['ttl'] = self.ttl
        if self.ts is None:
            params['ts'] = self.ts
        if self.tz is None:
            params['tz'] = self.tz
            
        return params
        
    #getters
    def get_type(self):
        return type
        
    def get_value(self):
        return value
        
    def get_value_data_type(self):
        return value_data_type
        
    def get_units(self):
        return units
        
    def get_price_id(self):
        return price_id
        
    def get_isoptimal(self):
        return isoptimal
        
    def get_src_ip(self):
        return src_ip
        
    def get_src_device_id(self):
        return src_device_id
        
    def get_dst_ip(self):
        return dst_ip
        
    def get_dst_device_id(self):
        return dst_device_id
        
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
        self.type = type
        
    def set_value(value):
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
    
    
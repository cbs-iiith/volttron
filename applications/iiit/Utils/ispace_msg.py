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
import math
from enum import IntEnum
import logging
from random import randint
import json


from volttron.platform.agent import utils
from volttron.platform import jsonrpc
from volttron.platform.agent import json as jsonapi

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
                            
                            
'''
#https://www.oreilly.com/library/view/python-cookbook/0596001673/ch05s12.html
#Making a Fast Copy of an Object. Credit: Alex Martelli
def empty_copy(obj):
    class Empty(obj._ _class_ _):
        def _ _init_ _(self): pass
    newcopy = Empty(  )
    newcopy._ _class_ _ = obj._ _class_ _
    return newcopy
'''
    
#avaliable in ispace_utils, copied here to remove dependecny on ispace_utils
def mround(num, multipleOf):
    #_log.debug('mround()')
    return math.floor((num + multipleOf / 2) / multipleOf) * multipleOf
#refer to http://stackoverflow.com/questions/5595425/what-is-the-best-way-to-compare-floats-for-almost-equality-in-python
#comparing floats is mess
def isclose(a, b, rel_tol=1e-09, abs_tol=0.0):
    #_log.debug('isclose()')
    return abs(a-b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)
#checking if a floating point value is “numerically zero” by checking if it is lower than epsilon
EPSILON = 1e-04
    
    
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
    
    _params = {}
    
    def __init__(self, msg_type, one_to_one = None, isoptimal = None
                    , value = None, value_data_type = None, units = None
                    , price_id = None
                    , src_ip = None, src_device_id = None
                    , dst_ip = None, dst_device_id = None
                    , duration = None, ttl = None, ts = None, tz = None
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
        
    ''' str overload to return class attributes as json params
    '''
    def __str__(self):
        #_log.debug('__str__()')
        params = self._get_params_dict()
        return json.dumps(params)
        
    '''hold-on
    def _ _copy_ _(self):
        newcopy = empty_copy(self)
        print "now copy some relevant subset of self's attributes to newcopy"
        for attrib in ISPACE_MSG_ATTRIB_LIST:
            
        return newcopy
    '''
    
    ''' overload methods for self and other
    '''
    # overload + operator
    def __add__(self, other):
        return (self.value + other.value)
        
    # overload - operator
    def __sub__(self, other):
        return (self.value - other.value)
        
    # overload * operator
    def __mul__(self, other):
        return (self.value * other.value)
        
    # overload / operator
    def __truediv__(self, other):
        return (self.value / other.value)
        
    # overload % operator
    def __mod__(self, other):
        return (self.value % other.value)
        
    # overload < operator
    def __lt__(self, other):
        return (True if (not isclose(self.value, other.value, EPSILON)
                        and (self.value < other.value))
                    else False)
                    
    # overload <= operator
    def __le__(self, other):
        return (True if (self.value <= other.value)
                    else False)
                    
    # overload != operator
    def __ne__(self, other):
        return (True if not isclose(self.value, other.value, EPSILON)
                    else False)
                    
    # overload > operator
    def __gt__(self, other):
        return (True if (not isclose(self.value, other.value, EPSILON)
                        and (self.value > other.value))
                    else False)
                    
    # overload >= operator
    def __ge__(self, other):
        return (True if (self.value <= other.value)
                    else False)
                    
    # overload == operator
    def __eq__(self, other):
        return (True if (self.price_id == other.price_id 
                        and isclose(self.value, other.value, EPSILON))
                   else False)
                   
    ''' ENDOF overload methods for self and other
    '''
    
    ''' overload methods for self and value
    '''
    # overload + operator
    def __add__(self, value):
        self.set_value(self.get_value() + value)
        return self
        
    # overload - operator
    def __sub__(self, value):
        self.value -= value
        return self
        
    # overload * operator
    def __mul__(self, value):
        return (self.value * value)
        
    # overload / operator
    def __truediv__(self, value):
        return (self.value / value)
        
    # overload % operator
    def __mod__(self, value):
        return (self.value % value)
        
    # overload < operator
    def __lt__(self, value):
        return (True if (not isclose(self.value, value, EPSILON)
                        and (self.value < value))
                    else False)
                    
    # overload <= operator
    def __le__(self, value):
        return (True if (self.value <= value)
                    else False)
                    
    # overload != operator
    def __ne__(self, value):
        return (True if not isclose(self.value, value, EPSILON)
                    else False)
                    
    # overload > operator
    def __gt__(self, value):
        return (True if (not isclose(self.value, value, EPSILON)
                        and (self.value > value))
                    else False)
                    
    # overload >= operator
    def __ge__(self, value):
        return (True if (self.value <= value)
                    else False)
                    
    # overload == operator
    def __eq__(self, value):
        return (True if (self.price_id == price_id 
                        and isclose(self.value, value, EPSILON))
                   else False)
    ''' ENDOF overload methods for self and value
    '''
    
    def _get_params_dict(self):
        self._params['msg_type'] = self.msg_type
        self._params['one_to_one'] = self.one_to_one
        self._params['value'] = self.value
        self._params['value_data_type'] = self.value_data_type
        self._params['units'] = self.units
        self._params['price_id'] = self.price_id
        self._params['isoptimal'] = self.isoptimal
        self._params['src_ip'] = self.src_ip
        self._params['src_device_id'] = self.src_device_id
        self._params['dst_ip'] = self.dst_ip
        self._params['dst_device_id'] = self.dst_device_id
        self._params['duration'] = self.duration
        self._params['ttl'] = self.ttl
        self._params['ts'] = self.ts
        self._params['tz'] = self.tz
        #_log.debug('params: {}'.format(params))
        return self._params

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
    
    def _cp_attrib(self, attrib, value):
        if attrib == 'msg_type': self.set_msg_type(value)
        elif attrib == 'one_to_one': self.set_(value)
        elif attrib == 'value': self.set_value(value)
        elif attrib == 'value_data_type': self.set_value_data_type(value)
        elif attrib == 'units': self.set_units(value)
        elif attrib == 'price_id': self.set_price_id(value)
        elif attrib == 'isoptimal': self.set_isoptimal(value)
        elif attrib == 'src_ip': self.set_src_ip(value)
        elif attrib == 'src_device_id': self.set_src_device_id(value)
        elif attrib == 'dst_ip': self.set_dst_ip(value)
        elif attrib == 'dst_device_id': self.set_dst_device_id(value)
        elif attrib == 'duration': self.set_duration(value)
        elif attrib == 'ttl': self.set_ttl(value)
        elif attrib == 'ts': self.set_ts(value)
        elif attrib == 'tz': self.set_tz(value)
        return
        
    def _is_attrib_null(self, attrib):
        if attrib == 'msg_type' and self.msg_type is None: return True
        elif attrib == 'one_to_one' and self.one_to_one is None: return True
        elif attrib == 'value' and self.value is None: return True
        elif attrib == 'value_data_type' and self.value_data_type is None: return True
        elif attrib == 'units' and self.units is None: return True
        elif attrib == 'price_id' and self.price_id is None: return True
        elif attrib == 'isoptimal' and self.isoptimal is None: return True
        elif attrib == 'src_ip' and self.src_ip is None: return True
        elif attrib == 'src_device_id' and self.src_device_id is None: return True
        elif attrib == 'dst_ip' and self.dst_ip is None: return True
        elif attrib == 'dst_device_id' and self.dst_device_id is None: return True
        elif attrib == 'duration' and self.duration is None: return True
        elif attrib == 'ttl' and self.ttl is None: return True
        elif attrib == 'ts' and self.ts is None: return True
        elif attrib == 'tz' and self.tz is None: return True
        else: return False
        
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
    def get_json_params(self):
        return json.dumps(self._get_params_dict())
    
    def get_json_message(self, id=randint(0, 99999999), method='bus_topic'):
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
    
    
class ISPACE_Msg_PricePoint(ISPACE_Msg):
    def __init__(self):
        super().__init__(self, MessageType.price_point, False, True)
        return
    pass
    
    
class ISPACE_Msg_OptPricePoint(ISPACE_Msg_PricePoint):
    def __init__(self, msg_type, one_to_one = None, isoptimal = True
                    , value = None, value_data_type = None, units = None
                    , price_id = None
                    , src_ip = None, src_device_id = None
                    , dst_ip = None, dst_device_id = None
                    , duration = None, ttl = None, ts = None, tz = None
                    ):
        super().__init__(self, MessageType.active_power, one_to_one, isoptimal
                        , value, value_data_type, units
                        , price_id
                        , src_ip, src_device_id
                        , dst_ip, dst_device_id
                        , duration, ttl, ts, tz
                        )
        if energy_category is not None: self.set_energy_category(energy_category)
        return
    pass
    
    
class ISPACE_Msg_BidPricePoint(ISPACE_Msg_PricePoint):
    def __init__(self, msg_type, one_to_one = None, isoptimal = False
                    , value = None, value_data_type = None, units = None
                    , price_id = None
                    , src_ip = None, src_device_id = None
                    , dst_ip = None, dst_device_id = None
                    , duration = None, ttl = None, ts = None, tz = None
                    ):
        super().__init__(self, MessageType.active_power, one_to_one, isoptimal
                        , value, value_data_type, units
                        , price_id
                        , src_ip, src_device_id
                        , dst_ip, dst_device_id
                        , duration, ttl, ts, tz
                        )
        return
    pass
    
    
class ISPACE_Msg_ActivePower(ISPACE_Msg):
    energy_category = None
    def __init__(self, msg_type, one_to_one = None, isoptimal = True
                    , value = None, value_data_type = None, units = None
                    , price_id = None
                    , src_ip = None, src_device_id = None
                    , dst_ip = None, dst_device_id = None
                    , duration = None, ttl = None, ts = None, tz = None
                    , energy_category = None
                    ):
        super().__init__(self, MessageType.active_power, one_to_one, isoptimal
                        , value, value_data_type, units
                        , price_id
                        , src_ip, src_device_id
                        , dst_ip, dst_device_id
                        , duration, ttl, ts, tz
                        )
        if energy_category is not None: self.set_energy_category(energy_category)
        return
        
    def _get_params_dict(self):
        self._params['energy_category'] = self.energy_category
        return super()._get_params_dict(self)
    
    def _cp_attrib(self, attrib, value):
        if attrib == 'energy_category': self.set_energy_category(value)
        else: super()._cp_attrib(self, attrib, value)
        return
        
    def _is_attrib_null(self, attrib):
        is_null = False
        if attrib == 'energy_category' and self.energy_category is None: 
            is_null = True
        else:
            is_null = super()._is_attrib_null(self, attrib)
        return is_null
        
    def get_energy_category(self):
        return self.energy_category
        
    #setters
    def set_energy_category(self, energy_category):
        self.energy_category = energy_category
        
        
    pass
    
    
class ISPACE_Msg_Energy(ISPACE_Msg_ActivePower):
    def __init__(self):
        super().__init__(self, MessageType.energy_demand, False, False)
        return
    pass
    
    
class ISPACE_Msg_Budget(ISPACE_Msg_Energy):
    def __init__(self):
        super().__init__(self, MessageType.budget)
        return
    pass
    
    
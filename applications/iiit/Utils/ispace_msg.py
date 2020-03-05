# -*- coding: utf-8 -*- {{{
# vim: set fenc=utf-8 ft=python sw=4 ts=4 sts=4 et:
# 
# Copyright (c) 2020, Sam Babu, Godithi.
# All rights reserved.
# 
# 
# IIIT Hyderabad

# }}}

# Sam

import datetime
import decimal
import json
import logging
import math
from copy import copy
from random import randint

import dateutil
from enum import IntEnum
from typing import Dict, Any, Union

from volttron.platform.agent import utils

utils.setup_logging()
_log = logging.getLogger(__name__)

ROUNDOFF_PRICE_POINT = 0.01
ROUNDOFF_BUDGET = 0.0001
ROUNDOFF_ACTIVE_POWER = 0.0001
ROUNDOFF_ENERGY_DEMAND = 0.0001

PP_DECIMAL_DIGITS = decimal.Decimal(
    str(ROUNDOFF_PRICE_POINT)).as_tuple().exponent * -1
BD_DECIMAL_DIGITS = decimal.Decimal(
    str(ROUNDOFF_BUDGET)).as_tuple().exponent * -1
AP_DECIMAL_DIGITS = decimal.Decimal(
    str(ROUNDOFF_ACTIVE_POWER)).as_tuple().exponent * -1
ED_DECIMAL_DIGITS = decimal.Decimal(
    str(ROUNDOFF_ENERGY_DEMAND)).as_tuple().exponent * -1

ISPACE_MSG_ATTRIB_LIST = ['msg_type', 'one_to_one', 'isoptimal',
                          'value', 'value_data_type', 'units',
                          'price_id',
                          'src_ip', 'src_device_id',
                          'dst_ip', 'dst_device_id',
                          'duration', 'ttl', 'ts', 'tz'
                          ]


# https://www.oreilly.com/library/view/python-cookbook/0596001673/ch05s12.html
# Making a Fast Copy of an Object. Credit: Alex Martelli
def empty_copy(obj):
    class Empty(obj.__class__):

        def __init__(self): pass


    newcopy = Empty()
    newcopy.__class__ = obj.__class__
    return newcopy


# available in ispace_utils, copied here to remove dependecny on ispace_utils
def mround(num, multiple_of):
    # _log.debug('mround()')
    value = math.floor((num + multiple_of / 2) / multiple_of) * multiple_of
    return value


# refer to https://bit.ly/3beuacI
# What is the best way to compare floats for almost-equality in Python?
# comparing floats is mess
def isclose(a, b, rel_tol=1e-09, abs_tol=0.0):
    # _log.debug('isclose()')
    value = abs(a - b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)
    return value


# checking if a floating point value is 'numerically zero'
# by checking if it is lower than epsilon
EPSILON = 1e-04


class MessageType(IntEnum):
    price_point = 0
    budget = 1
    active_power = 2
    energy_demand = 3
    pass


class EnergyCategory(IntEnum):
    thermal = 0
    lighting = 1
    plug_load = 2
    mixed = 9
    pass


class ISPACE_Msg:
    """
    iSPACE Message base class
    """
    # TODO: enhancement - need to add a msg uuid,
    # also convert price_id to use uuid instead for radint
    msg_type = None
    one_to_one = None
    isoptimal = None
    value = None
    value_data_type = None
    units = None
    price_id = None
    # msg_from_remote_device = True if src_ip == local_ip else False
    src_ip = None
    src_device_id = None
    dst_ip = None
    dst_device_id = None
    duration = None
    # TODO: currently ttl is in seconds, maybe changed to milliseconds for
    #  better performance
    ttl = None
    ts = None
    tz = None

    _params = {}

    def __init__(self, msg_type, one_to_one=None, isoptimal=None,
                 value=None, value_data_type=None, units=None,
                 price_id=None,
                 src_ip=None, src_device_id=None,
                 dst_ip=None, dst_device_id=None,
                 duration=None, ttl=None, ts=None, tz=None
                 ):
        if msg_type is not None:
            self.set_msg_type(msg_type)
        if one_to_one is not None:
            self.set_one_to_one(one_to_one)
        if value is not None:
            self.set_value(value)
        if value_data_type is not None:
            self.set_value_data_type(value_data_type)
        if units is not None:
            self.set_units(units)
        if price_id is not None:
            self.set_price_id(price_id)
        if isoptimal is not None:
            self.set_isoptimal(isoptimal)
        if src_ip is not None:
            self.set_src_ip(src_ip)
        if src_device_id is not None:
            self.set_src_device_id(src_device_id)
        if dst_ip is not None:
            self.set_dst_ip(dst_ip)
        if dst_device_id is not None:
            self.set_dst_device_id(dst_device_id)
        if duration is not None:
            self.set_duration(duration)
        if ttl is not None:
            self.set_ttl(ttl)
        if ts is not None:
            self.set_ts(ts)
        if tz is not None:
            self.set_tz(tz)
        pass

    ''' str overload to return class attributes as json params
    '''

    def __str__(self):
        # _log.debug('__str__()')
        params = self._get_params_dict()
        return json.dumps(params)

    def __copy__(self):
        newcopy = empty_copy(self)

        newcopy.msg_type = copy(self.msg_type)
        newcopy.one_to_one = copy(self.one_to_one)
        newcopy.value = copy(self.value)
        newcopy.value_data_type = copy(self.value_data_type)
        newcopy.units = copy(self.units)
        newcopy.price_id = copy(self.price_id)
        newcopy.isoptimal = copy(self.isoptimal)
        newcopy.src_ip = copy(self.src_ip)
        newcopy.src_device_id = copy(self.src_device_id)
        newcopy.dst_ip = copy(self.dst_ip)
        newcopy.dst_device_id = copy(self.dst_device_id)
        newcopy.duration = copy(self.duration)
        newcopy.ttl = copy(self.ttl)
        newcopy.ts = copy(self.ts)
        newcopy.tz = copy(self.tz)

        return newcopy

    ''' overload methods for self and other
    '''

    # overload + operator
    def __add__(self, other):
        """

        :type other: ISPACE_Msg
        """
        return self.value + other.value

    # overload - operator
    def __sub__(self, other):
        return self.value - other.value

    # overload * operator
    def __mul__(self, other):
        return self.value * other.value

    # overload / operator
    def __truediv__(self, other):
        return self.value / other.value

    # overload % operator
    def __mod__(self, other):
        return self.value % other.value

    # overload < operator
    def __lt__(self, other):
        result = True if (
                not isclose(self.value, other.value, EPSILON)
                and (self.value < other.value))\
            else False
        return result

    # overload <= operator
    def __le__(self, other):
        result = True if (self.value <= other.value) else False
        return result

    # overload != operator
    def __ne__(self, other):
        result = True if not isclose(self.value, other.value,
                                     EPSILON) else False
        return result

    # overload > operator
    def __gt__(self, other):
        result = True if (
                not isclose(self.value, other.value, EPSILON)
                and (self.value > other.value))\
            else False
        return result

    # overload >= operator
    def __ge__(self, other):
        result = True if (self.value <= other.value) else False
        return result

    # overload == operator
    def __eq__(self, other):
        result = True if (
                    self.price_id == other.price_id
                    and isclose(self.value, other.value, EPSILON))\
            else False
        return result

    ''' ENDOF overload methods for self and other
    '''

    ''' overload methods for self and value
    '''

    # overload + operator
    def __add__(self, value):
        """

        :type value: float
        """
        self.set_value(self.get_value() + value)
        return self

    # overload - operator
    def __sub__(self, value):
        self.value -= value
        return self

    # overload * operator
    def __mul__(self, value):
        return self.value * value

    # overload / operator
    def __truediv__(self, value):
        return self.value / value

    # overload % operator
    def __mod__(self, value):
        return self.value % value

    # overload < operator
    def __lt__(self, value):
        result = True if (
                not isclose(self.value, value, EPSILON)
                and (self.value < value))\
            else False
        return result

    # overload <= operator
    def __le__(self, value):
        result = True if (self.value <= value) else False
        return result

    # overload != operator
    def __ne__(self, value):
        result = True if not isclose(self.value, value, EPSILON) else False
        return result

    # overload > operator
    def __gt__(self, value):
        result = True if (
                not isclose(self.value, value, EPSILON)
                and (self.value > value))\
            else False
        return result

    # overload >= operator
    def __ge__(self, value):
        result = True if (self.value <= value) else False
        return result

    # overload == operator
    def __eq__(self, value):
        result = True if (
                self.price_id == value
                and isclose(self.value, value, EPSILON))\
            else False
        return result

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
        # _log.debug('params: {}'.format(params))
        return self._params

    def ttl_timeout(self):
        # live for ever
        if self.ttl < 0:
            _log.warning('ttl: {} < 0, do nothing!!!'.format(self.ttl))
            return False

        if self.tz == 'UTC':
            ts = dateutil.parser.parse(self.ts)
            now = dateutil.parser.parse(
                datetime.datetime.utcnow().isoformat(' ') + 'Z')
            check = True if (now - ts).total_seconds() > self.ttl else False
            return check
        else:
            _log.warning('ttl_timeout(), unknown tz: {}'.format(self.tz))
            return False

    # ttl <= -1 --> live forever
    # ttl == 0 --> ttl timed out
    # decrement_status == False, if ttl <= -1 or unknown tz
    def decrement_ttl(self):
        # live for ever
        if self.ttl <= -1:
            _log.warning('ttl: {} < 0, do nothing!!!'.format(self.ttl))
            return False

        if self.tz == 'UTC':
            ts = dateutil.parser.parse(self.ts)
            now = dateutil.parser.parse(
                datetime.datetime.utcnow().isoformat(' ') + 'Z')
            new_ttl = int(self.ttl - (now - ts).total_seconds() - 1)
            self.ttl = new_ttl if new_ttl >= 0 else 0
            return True
        else:
            _log.warning('decrement_ttl(), unknown tz: {}'.format(self.tz))
            return False

    # check for mandatory fields in the message
    def valid_msg(self, validate_fields=[]):
        # _log.debug('valid_msg(): {}'.format(validate_fields))
        for attrib in validate_fields:
            # _log.debug('checking attrib: {}'.format(attrib))
            # null value check
            if self._is_attrib_null(attrib):
                # _log.debug('....is null...')
                return False
            # TODO: data validations checks based on message type and field type
        # _log.debug('...........valid_msg()')
        return True

    def _cp_attrib(self, attrib, value):
        if attrib == 'msg_type':
            self.set_msg_type(value)
        elif attrib == 'one_to_one':
            self.set_one_to_one(value)
        elif attrib == 'value':
            self.set_value(value)
        elif attrib == 'value_data_type':
            self.set_value_data_type(value)
        elif attrib == 'units':
            self.set_units(value)
        elif attrib == 'price_id':
            self.set_price_id(value)
        elif attrib == 'isoptimal':
            self.set_isoptimal(value)
        elif attrib == 'src_ip':
            self.set_src_ip(value)
        elif attrib == 'src_device_id':
            self.set_src_device_id(value)
        elif attrib == 'dst_ip':
            self.set_dst_ip(value)
        elif attrib == 'dst_device_id':
            self.set_dst_device_id(value)
        elif attrib == 'duration':
            self.set_duration(value)
        elif attrib == 'ttl':
            self.set_ttl(value)
        elif attrib == 'ts':
            self.set_ts(value)
        elif attrib == 'tz':
            self.set_tz(value)
        return

    def _is_attrib_null(self, attrib):
        # _log.debug('_is_attrib_null()')
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
        else:
            return False

    # validate various sanity measure like, valid fields, valid pp ids,
    # ttl expire, etc.,
    def sanity_check_ok(self, hint=None, validate_fields=None,
                        valid_price_ids=None):
        # _log.debug('sanity_check_ok()')
        if valid_price_ids is None:
            valid_price_ids = []
        if validate_fields is None:
            validate_fields = []

        if not self.valid_msg(validate_fields):
            _log.warning(
                'rcvd a invalid msg,'
                + ' hint: {}, message: {}, do nothing!!!'.format(hint, self)
            )
            return False

        # log the received msg
        # _log.info('[LOG] {}, Msg: {}'.format(hint, self))
        # _log.debug('{}, Msg: {}'.format(hint, self))

        # process msg only if price_id corresponds to these ids
        # _log.debug('check if pp_id is valid...')
        if valid_price_ids != [] and self.price_id not in valid_price_ids:
            _log.warning('pp_id: {}'.format(self.price_id)
                         + ' not in valid_price_ids: {}, do nothing!!!'.format(
                valid_price_ids))
            return False
        # _log.debug('done.')

        # _log.debug('check if ttl timeout...')
        # process msg only if msg is alive (didnot timeout)
        if self.ttl_timeout():
            _log.warning('msg ttl expired, do nothing!!!')
            return False
        # _log.debug('done.')

        return True

    def check_dst_addr(self, device_id, ip_addr):
        result = False if (
                self.one_to_one
                and (
                        device_id != self.dst_device_id
                        or ip_addr != self.dst_ip
                ))\
            else True
        return result

    # return class attributes as json params that can be passed to do_rpc()
    def get_json_params(self):
        # return json.dumps(self._get_params_dict())
        return self._get_params_dict()

    def get_json_message(self, msg_id=randint(0, 99999999), method='bus_topic'):
        json_package = {
            'jsonrpc': '2.0',
            'id': msg_id,
            'method': method,
        }
        json_package['params'] = self._get_params_dict()
        data = json.dumps(json_package)
        return data

    # getters
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

    # setters
    def set_msg_type(self, msg_type):
        # _log.debug('set_msg_type({})'.format(msg_type))
        self.msg_type = int(msg_type)

    def set_one_to_one(self, one_to_one):
        self.one_to_one = one_to_one

    def set_value(self, value):
        # _log.debug('set_value()')
        # _log.debug('self.msg_type: {}, MessageType.price_point: {}'.format(
        # self.msg_type, MessageType.price_point))
        if self.msg_type == MessageType.price_point:
            tmp_value = round(mround(value, ROUNDOFF_PRICE_POINT),
                              PP_DECIMAL_DIGITS)
            self.value = 0 if tmp_value <= 0 else 1 if tmp_value >= 1 else \
                tmp_value
        elif self.msg_type == MessageType.budget:
            self.value = round(mround(value, ROUNDOFF_BUDGET),
                               BD_DECIMAL_DIGITS)
        elif self.msg_type == MessageType.active_power:
            self.value = round(mround(value, ROUNDOFF_ACTIVE_POWER),
                               AP_DECIMAL_DIGITS)
        elif self.msg_type == MessageType.energy_demand:
            self.value = round(mround(value, ROUNDOFF_ENERGY_DEMAND),
                               ED_DECIMAL_DIGITS)
        else:
            _log.warning('set_value(), unhandled message type')
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

    def update_ts(self):
        self.ts = datetime.datetime.utcnow().isoformat(' ') + 'Z'

    pass


class ISPACE_Msg_PricePoint(ISPACE_Msg):

    def __init__(self,
                 msg_type, one_to_one=False, isoptimal=True,
                 value=None, value_data_type=None, units=None,
                 price_id=None,
                 src_ip=None, src_device_id=None,
                 dst_ip=None, dst_device_id=None,
                 duration=None, ttl=None, ts=None, tz=None
                 ):
        ISPACE_Msg.__init__(self,
                            MessageType.price_point, one_to_one, isoptimal,
                            value, value_data_type, units,
                            price_id,
                            src_ip, src_device_id,
                            dst_ip, dst_device_id,
                            duration, ttl, ts, tz
                            )
        pass

    pass


class ISPACE_Msg_OptPricePoint(ISPACE_Msg_PricePoint):

    def __init__(self,
                 msg_type, one_to_one=False, isoptimal=True,
                 value=None, value_data_type=None, units=None,
                 price_id=None,
                 src_ip=None, src_device_id=None,
                 dst_ip=None, dst_device_id=None,
                 duration=None, ttl=None, ts=None, tz=None
                 ):
        ISPACE_Msg_PricePoint.__init__(self,
                                       MessageType.active_power, one_to_one,
                                       isoptimal,
                                       value, value_data_type, units,
                                       price_id,
                                       src_ip, src_device_id,
                                       dst_ip, dst_device_id,
                                       duration, ttl, ts, tz
                                       )
        pass

    pass


class ISPACE_Msg_BidPricePoint(ISPACE_Msg_PricePoint):

    def __init__(self,
                 msg_type, one_to_one=False, isoptimal=False,
                 value=None, value_data_type=None, units=None,
                 price_id=None,
                 src_ip=None, src_device_id=None,
                 dst_ip=None, dst_device_id=None,
                 duration=None, ttl=None, ts=None, tz=None
                 ):
        ISPACE_Msg_PricePoint.__init__(self,
                                       MessageType.active_power, one_to_one,
                                       isoptimal,
                                       value, value_data_type, units,
                                       price_id,
                                       src_ip, src_device_id,
                                       dst_ip, dst_device_id,
                                       duration, ttl, ts, tz
                                       )
        pass

    pass


class ISPACE_Msg_ActivePower(ISPACE_Msg):
    energy_category = None

    def __init__(self,
                 msg_type=MessageType.active_power,
                 one_to_one=False, isoptimal=True,
                 value=None, value_data_type=None, units=None,
                 price_id=None,
                 src_ip=None, src_device_id=None,
                 dst_ip=None, dst_device_id=None,
                 duration=None, ttl=None, ts=None, tz=None,
                 energy_category=None
                 ):
        ISPACE_Msg.__init__(self,
                            msg_type, one_to_one, isoptimal,
                            value, value_data_type, units,
                            price_id,
                            src_ip, src_device_id,
                            dst_ip, dst_device_id,
                            duration, ttl, ts, tz
                            )
        if energy_category is not None: self.set_energy_category(
            energy_category)
        pass

    def __copy__(self):
        # newcopy = super(ISPACE_Msg_ActivePower, self).__copy__(self)
        newcopy = ISPACE_Msg.__copy__(self)
        newcopy.energy_category = self.energy_category
        return newcopy

    def _get_params_dict(self):
        self._params['energy_category'] = self.energy_category
        # return super(ISPACE_Msg_ActivePower, self)._get_params_dict(self)
        return ISPACE_Msg._get_params_dict(self)

    def _cp_attrib(self, attrib, value):
        if attrib == 'energy_category':
            self.set_energy_category(value)
        # else: super(ISPACE_Msg_ActivePower, self)._cp_attrib(self, attrib,
        # value)
        else:
            ISPACE_Msg._cp_attrib(self, attrib, value)
        return

    def _is_attrib_null(self, attrib):
        is_null = False
        if attrib == 'energy_category' and self.energy_category is None:
            is_null = True
        else:
            # is_null = super(ISPACE_Msg_ActivePower, self)._is_attrib_null(
            # self, attrib)
            is_null = ISPACE_Msg._is_attrib_null(self, attrib)
        return is_null

    def get_energy_category(self):
        return self.energy_category

    # setters
    def set_energy_category(self, energy_category):
        self.energy_category = int(energy_category)

    pass


class ISPACE_Msg_Energy(ISPACE_Msg_ActivePower):

    def __init__(self,
                 msg_type=MessageType.energy_demand,
                 one_to_one=False, isoptimal=False,
                 value=None, value_data_type=None, units=None,
                 price_id=None,
                 src_ip=None, src_device_id=None,
                 dst_ip=None, dst_device_id=None,
                 duration=None, ttl=None, ts=None, tz=None,
                 energy_category=None
                 ):
        ISPACE_Msg_ActivePower.__init__(self,
                                        msg_type, one_to_one, isoptimal,
                                        value, value_data_type, units,
                                        price_id,
                                        src_ip, src_device_id,
                                        dst_ip, dst_device_id,
                                        duration, ttl, ts, tz,
                                        energy_category
                                        )
        pass

    pass


class ISPACE_Msg_Budget(ISPACE_Msg_Energy):

    def __init__(self,
                 msg_type=MessageType.energy_demand,
                 one_to_one=False, isoptimal=False,
                 value=None, value_data_type=None, units=None,
                 price_id=None,
                 src_ip=None, src_device_id=None,
                 dst_ip=None, dst_device_id=None,
                 duration=None, ttl=None, ts=None, tz=None,
                 energy_category=None
                 ):
        ISPACE_Msg_Energy.__init__(self,
                                   msg_type, one_to_one, isoptimal,
                                   value, value_data_type, units,
                                   price_id,
                                   src_ip, src_device_id,
                                   dst_ip, dst_device_id,
                                   duration, ttl, ts, tz,
                                   energy_category
                                   )
        pass

    pass

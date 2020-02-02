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
from copy import copy

from volttron.platform.agent import utils
from volttron.platform import jsonrpc

from ispace_utils import mround
from ispace_msg import ISPACE_Msg, MessageType, ISPACE_MSG_ATTRIB_LIST

utils.setup_logging()
_log = logging.getLogger(__name__)


ROUNDOFF_PRICE_POINT = 0.01
ROUNDOFF_BUDGET = 0.0001
ROUNDOFF_ACTIVE_POWER = 0.0001
ROUNDOFF_ENERGY = 0.0001


#validate incomming bus topic message
def valid_bustopic_msg(sender, valid_senders_list, minimum_fields
                        , validate_fields, valid_price_ids, message):
    #_log.debug('validate_bustopic_msg()')
    pp_msg = None
    
    if sender not in valid_senders_list:
        _log.debug('sender: {}'.format(sender)
                    + ' not in sender list: {}, do nothing!!!'.format(valid_senders_list))
        return (False, pp_msg)
        
        
    try:
        _log.debug('message: {}'.format(message))
        minimum_fields = ['value', 'value_data_type', 'units', 'price_id']
        pp_msg = parse_bustopic_msg(message, minimum_fields)
        #_log.info('pp_msg: {}'.format(pp_msg))
    except KeyError as ke:
        _log.exception(ke)
        _log.exception(jsonrpc.json_error('NA', INVALID_PARAMS,
                'Invalid params {}'.format(rpcdata.params)))
        return (False, pp_msg)
    except Exception as e:
        _log.exception(e)
        _log.exception(jsonrpc.json_error('NA', UNHANDLED_EXCEPTION, e))
        return (False, pp_msg)
        
    hint = ('New Price Point' if check_msg_type(message, MessageType.price_point)
           else 'New Active Power' if check_msg_type(message, MessageType.active_power)
           else 'New Energy Demand' if check_msg_type(message, MessageType.energy_demand)
           else 'Unknown Msg Type')

    validate_fields = ['value', 'value_data_type', 'units', 'price_id', 'isoptimal', 'duration', 'ttl']
    valid_price_ids = []
    #validate various sanity measure like, valid fields, valid pp ids, ttl expiry, etc.,
    if not pp_msg.sanity_check_ok(hint, validate_fields, valid_price_ids):
        _log.warning('Msg sanity checks failed!!!')
        return (False, pp_msg)
    return (True, pp_msg)

#a default pricepoint message
def get_default_pp_msg(discovery_address, device_id):
    return ISPACE_Msg(MessageType.price_point, False, True
                        , 0, 'float', 'cents'
                        , None
                        , discovery_address, device_id
                        , None, None
                        , 3600, 3600, 10, 'UTC'
                        )
                        
#a default active power message
def get_default_ap_msg(discovery_address, device_id):
    return ISPACE_Msg(MessageType.active_power, False, True
                        , 0, 'float', 'cents'
                        , None
                        , discovery_address, device_id
                        , None, None
                        , 3600, 3600, 10, 'UTC'
                        )
                        
#a default energy demand message
def get_default_ed_msg(discovery_address, device_id):
    return ISPACE_Msg(MessageType.energy_demand, False, True
                        , 0, 'float', 'cents'
                        , None
                        , discovery_address, device_id
                        , None, None
                        , 3600, 3600, 10, 'UTC'
                        )
                        
#create a MessageType.energy ISPACE_Msg
def ted_helper(pp_msg, device_id, discovery_address, ted, new_ttl=10):
    #print(MessageType.energy_demand)
    msg_type = MessageType.energy_demand
    one_to_one = copy(pp_msg.get_one_to_one())
    isoptimal = copy(pp_msg.get_isoptimal())
    value = ted
    value_data_type = 'float'
    units = 'kWh'
    price_id = copy(pp_msg.get_price_id())
    src_ip = discovery_address
    src_device_id = device_id
    dst_ip = copy(pp_msg.get_src_ip())
    dst_device_id = copy(pp_msg.get_src_device_id())
    duration = copy(pp_msg.get_duration())
    ttl = new_ttl
    ts = datetime.datetime.utcnow().isoformat(' ') + 'Z'
    tz = 'UTC'
    return ISPACE_Msg(msg_type, one_to_one
                        , isoptimal, value, value_data_type, units, price_id
                        , src_ip, src_device_id, dst_ip, dst_device_id
                        , duration, ttl, ts, tz)
                        
#create a MessageType.active_power ISPACE_Msg
def tap_helper(pp_msg, device_id, discovery_address, tap, new_ttl=10):
    #print(MessageType.active_power)
    msg_type = MessageType.active_power
    one_to_one = copy(pp_msg.get_one_to_one())
    isoptimal = copy(pp_msg.get_isoptimal())
    value = tap
    value_data_type = 'float'
    units = 'Wh'
    price_id = copy(pp_msg.get_price_id())
    src_ip = discovery_address
    src_device_id = device_id
    dst_ip = copy(pp_msg.get_src_ip())
    dst_device_id = copy(pp_msg.get_src_device_id())
    duration = copy(pp_msg.get_duration())
    ttl = new_ttl
    ts = datetime.datetime.utcnow().isoformat(' ') + 'Z'
    tz = 'UTC'
    return ISPACE_Msg(msg_type, one_to_one
                        , isoptimal, value, value_data_type, units, price_id
                        , src_ip, src_device_id, dst_ip, dst_device_id
                        , duration, ttl, ts, tz)
                        
def check_msg_type(message, msg_type):
    data = jsonrpc.JsonRpcData.parse(message).params
    try:
        if data['msg_type'] == msg_type:
            return True
    except Exception:
        _log.warning('key attrib: "msg_type", not available in the message.')
        pass
    return False
    
#converts bus message into an ispace_msg
def parse_bustopic_msg(message, minimum_fields = []):
    #data = json.loads(message)
    data = jsonrpc.JsonRpcData.parse(message).params
    return _parse_data(data, minimum_fields)
    
#converts jsonrpc_msg into an ispace_msg
def parse_jsonrpc_msg(message, minimum_fields = []):
    data = jsonrpc.JsonRpcData.parse(message).params
    return _parse_data(data, minimum_fields)
    
def _update_value(new_msg, attrib, new_value):
    if attrib == 'msg_type':
        new_msg.set_msg_type(new_value)
    elif attrib == 'one_to_one':
        new_msg.set_one_to_one(new_value if new_value is not None else False)
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
    
def _parse_data(data, minimum_fields = []):
    #_log.debug('_parse_data()')
    #_log.debug('data: [{}]'.format(data))
    #_log.debug('datatype: {}'.format(type(data)))
    
    #ensure msg_type attrib is set first
    msg_type =  data['msg_type']
        
    #TODO: select class msg_type based on msg_type, instead of base class
    new_msg = ISPACE_Msg(msg_type)
    _update_value(new_msg, 'msg_type', msg_type)
    
    #if list is empty, parse for all attributes, if any attrib not found throw keynot found error
    if minimum_fields == []:
        #if the attrib is not found in the data, throws a keyerror exception
        _log.warning('minimum_fields to check against is empty!!!')
        for attrib in ISPACE_MSG_ATTRIB_LIST:
            _update_value(new_msg, attrib, data[attrib])
    else:
        #first pass for minimum_fields
        #if the field is not found in the data, throws a keyerror exception
        for attrib in minimum_fields:
            _update_value(new_msg, attrib, data[attrib])
            
        #do a second pass to also get attribs not in the minimum_fields
        #if attrib not found, catch the exception(pass) and continue with next attrib
        for attrib in ISPACE_MSG_ATTRIB_LIST:
            if attrib not in minimum_fields:        #data parsed in first pass
                try:
                    _update_value(new_msg, attrib, data[attrib])
                except KeyError:
                    _log.warning('key: {}, not available in the data'.format(attrib))
                    pass
                
    return new_msg
        
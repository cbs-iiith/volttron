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
import json
import logging
from copy import copy
from random import randint

from ispace_msg import (ISPACE_Msg, MessageType, ISPACE_MSG_ATTRIB_LIST,
                        ISPACE_Msg_ActivePower, EnergyCategory,
                        ISPACE_Msg_Energy, ISPACE_Msg_OptPricePoint,
                        ISPACE_Msg_BidPricePoint, ISPACE_Msg_Budget)
from volttron.platform import jsonrpc
from volttron.platform.agent import utils

utils.setup_logging()
_log = logging.getLogger(__name__)


# validate incoming bus topic message
def valid_bustopic_msg(
        sender, valid_senders_list, minimum_fields,
        validate_fields, valid_price_ids, message
):
    _log.debug('validate_bustopic_msg()')
    pp_msg = None

    if sender not in valid_senders_list:
        _log.warning(
            'sender: {}'.format(sender)
            + ' not in sender list: {}'.format(valid_senders_list)
            + ', do nothing!!!'
        )
        return False, pp_msg

    try:
        # _log.debug('message: {}'.format(message))
        # minimum_fields = ['value', 'value_data_type', 'units', 'price_id']
        pp_msg = parse_bustopic_msg(message, minimum_fields)
        # _log.info('pp_msg: {}'.format(pp_msg))
    except KeyError as ke:
        _log.exception(ke.message)
        _log.exception(
            jsonrpc.json_error(
                'NA',
                jsonrpc.INVALID_PARAMS,
                'Invalid params, message: {}'.format(message)
            )
        )
        return False, pp_msg
    except Exception as e:
        _log.exception(e.message)
        _log.exception(jsonrpc.json_error('NA',
                                          jsonrpc.UNHANDLED_EXCEPTION,
                                          e))
        return False, pp_msg

    hint = get_msg_hint(pp_msg.get_msg_type())

    # sanity measure like, valid fields, valid pp ids, ttl expiry, etc.,
    if not pp_msg.sanity_check_ok(hint, validate_fields, valid_price_ids):
        _log.warning('Msg sanity checks failed!!!')
        return False, pp_msg
    return True, pp_msg


def get_msg_hint(pp_msg_type):
    return (
        'Price Point'
        if pp_msg_type == MessageType.price_point
        else 'Active Power'
        if pp_msg_type == MessageType.active_power
        else 'Energy Demand'
        if pp_msg_type == MessageType.energy_demand
        else 'Budget'
        if pp_msg_type == MessageType.budget
        else 'Unknown Msg Type'
    )


# a default pricepoint message
def get_default_pp_msg(discovery_address, device_id):
    # type: (str, str) -> ISPACE_Msg
    return ISPACE_Msg(
        MessageType.price_point, False, True,
        0, 'float', '%',
        None,
        discovery_address, device_id,
        None, None,
        3600, 3600, 60, 'UTC'
    )


# a default budget message
def get_default_bd_msg(discovery_address, device_id):
    # type: (str, str) -> ISPACE_Msg_Budget
    return ISPACE_Msg_Budget(
        MessageType.budget, False, True,
        0, 'float', '%',
        None,
        discovery_address, device_id,
        None, None,
        3600, 3600, 60, 'UTC',
        EnergyCategory.mixed
    )


# a default active power message
def get_default_ap_msg(
        discovery_address,
        device_id,
        category=EnergyCategory.mixed
):
    return ISPACE_Msg_ActivePower(
        MessageType.active_power, False, True,
        0, 'float', 'W',
        None,
        discovery_address, device_id,
        None, None,
        3600, 3600, 60, 'UTC',
        category
    )


# a default energy demand message
def get_default_ed_msg(
        discovery_address,
        device_id,
        category=EnergyCategory.mixed
):
    return ISPACE_Msg_Energy(
        MessageType.energy_demand, False, True,
        0, 'float', 'Wh',
        None,
        discovery_address, device_id,
        None, None,
        3600, 3600, 60, 'UTC',
        category
    )


# create a MessageType.energy ISPACE_Msg
def ted_helper(
        pp_msg,
        device_id,
        discovery_address,
        ted,
        new_ttl=60,
        category=EnergyCategory.mixed
):
    # print(MessageType.energy_demand)
    msg_type = MessageType.energy_demand
    one_to_one = copy(pp_msg.get_one_to_one())
    isoptimal = copy(pp_msg.get_isoptimal())
    value = ted
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
    return ISPACE_Msg_Energy(
        msg_type, one_to_one, isoptimal,
        value, value_data_type, units,
        price_id,
        src_ip, src_device_id,
        dst_ip, dst_device_id,
        duration, ttl, ts, tz,
        category
    )


# create a MessageType.active_power ISPACE_Msg
def tap_helper(
        pp_msg,
        device_id,
        discovery_address,
        tap,
        new_ttl=60,
        category=EnergyCategory.mixed
):
    # print(MessageType.active_power)
    msg_type = MessageType.active_power
    one_to_one = copy(pp_msg.get_one_to_one())
    isoptimal = copy(pp_msg.get_isoptimal())
    value = tap
    value_data_type = 'float'
    units = 'W'
    price_id = copy(pp_msg.get_price_id())
    src_ip = discovery_address
    src_device_id = device_id
    dst_ip = copy(pp_msg.get_src_ip())
    dst_device_id = copy(pp_msg.get_src_device_id())
    duration = copy(pp_msg.get_duration())
    ttl = new_ttl
    ts = datetime.datetime.utcnow().isoformat(' ') + 'Z'
    tz = 'UTC'
    return ISPACE_Msg_ActivePower(
        msg_type, one_to_one,
        isoptimal, value, value_data_type, units,
        price_id,
        src_ip, src_device_id,
        dst_ip, dst_device_id,
        duration, ttl, ts, tz,
        category
    )


def check_msg_type(message, msg_type):
    rpcdata = jsonrpc.JsonRpcData.parse(message)
    data = (
        json.loads(rpcdata.params)
        if isinstance(rpcdata.params, str)
        else rpcdata.params
    )
    try:
        if 'msg_type' in data.keys() and data['msg_type'] == msg_type:
            return True
    except Exception as e:
        _log.warning(
            'key attrib: "msg_type", not available in the message. {}'.format(
                e.message))
        pass
    return False


# converts bus message into an ispace_msg
def parse_bustopic_msg(message, minimum_fields=None):
    """

    :param message:
    :type minimum_fields: list
    """
    if minimum_fields is None:
        minimum_fields = []
    rpcdata = jsonrpc.JsonRpcData.parse(message)
    data = (
        json.loads(rpcdata.params)
        if isinstance(rpcdata.params, str)
        else rpcdata.params
    )
    return _parse_data(data, minimum_fields)


# converts jsonrpc_msg into an ispace_msg
def parse_jsonrpc_msg(message, minimum_fields=None):
    """

    :param message:
    :type minimum_fields: list
    """
    if minimum_fields is None:
        minimum_fields = []
    rpcdata = jsonrpc.JsonRpcData.parse(message)
    data = (
        json.loads(rpcdata.params)
        if isinstance(rpcdata.params, str)
        else rpcdata.params
    )
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
        new_msg.set_price_id(
            new_value
            if new_value is not None
            else randint(0, 99999999)
        )
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
        new_msg.set_ts(
            new_value
            if new_value is not None
            else datetime.datetime.utcnow().isoformat(' ') + 'Z'
        )
    elif attrib == 'tz':
        new_msg.set_tz(new_value if new_value is not None else 'UTC')
    return


def _parse_data(data, minimum_fields=None):
    """

    :type data: dict
    :type minimum_fields: list
    """
    if minimum_fields is None:
        minimum_fields = []
    msg_type = data['msg_type']

    # select class msg_type based on msg_type, instead of base class
    if msg_type == MessageType.price_point:
        isoptimal = data['isoptimal']
        if isoptimal:
            new_msg = ISPACE_Msg_OptPricePoint()
        else:
            new_msg = ISPACE_Msg_BidPricePoint()
    elif msg_type == MessageType.active_power:
        new_msg = ISPACE_Msg_ActivePower()
    elif msg_type == MessageType.energy_demand:
        new_msg = ISPACE_Msg_Energy()
    elif msg_type == MessageType.budget:
        new_msg = ISPACE_Msg_Budget()
    else:
        new_msg = ISPACE_Msg(msg_type)
        _update_value(new_msg, 'msg_type', msg_type)

    # if list is empty, parse for all attributes,
    # if any attrib not found throw key not found error
    if not minimum_fields:
        # if the attrib is not found in the data, throws a keyerror exception
        _log.warning('minimum_fields to check against is empty!!!')
        for attrib in ISPACE_MSG_ATTRIB_LIST:
            _update_value(new_msg, attrib, data[attrib])
    else:
        # first pass for minimum_fields
        # if the field is not found in the data, throws a keyerror exception
        for attrib in minimum_fields:
            _update_value(new_msg, attrib, data[attrib])

        # do a second pass to also get attribs not in the minimum_fields
        # if attrib not found, catch the exception(pass)
        # and continue with next attrib
        for attrib in ISPACE_MSG_ATTRIB_LIST:
            if attrib not in minimum_fields:  # data parsed in first pass
                try:
                    _update_value(new_msg, attrib, data[attrib])
                except KeyError:
                    _log.warning(
                        'key: {}, not available in the data'.format(attrib)
                    )
                    pass

    return new_msg

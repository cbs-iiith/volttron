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
import logging
import math
import time

import gevent
import gevent.event
from gevent import monkey

monkey.patch_all(thread=False, select=False)
# if using grequests, comment the above two (i.e., monkey.patch_all())
# import grequests
import requests

import json

from volttron.platform.agent import utils
from volttron.platform.messaging import headers as headers_mod
from volttron.platform.agent.known_identities import MASTER_WEB

utils.setup_logging()
_log = logging.getLogger(__name__)


# some agent needs to communicate with the local bridge
# for example: pca --> to get the list of local/ds devices
#             building/zone/sh/rc/ss register with bridge to post tap/ted
# at times bridge agent may not respond, it would be busy or crashed
# the agents can check bridge is active before making active calls to better
# handle rpc exceptions a periodic process can be scheduled that checks the
# bridge is active and re-registers if necessary
def ping_vb_failed(self):
    try:
        success = self.vip.rpc.call(
            self._vb_vip_identity, 'ping'
        ).get(timeout=10)

        if success:
            return False
    except Exception as e:
        # print(e)
        _log.warning('Bridge Agent is not responding!!!'
                     + ' Message: {}'.format(e.message)
                     )
        pass
    return True


# register agent with local vb, blocking function
# register this agent with vb as local device for posting active power & bid
# energy demand pca picks up the active power & energy demand bids only if
# registered with vb as local device
def register_with_bridge(self, sleep_time=10):
    while True:
        try:
            _log.info('Registering with the Volttron Bridge...')
            success = self.vip.rpc.call(
                self._vb_vip_identity,
                'register_local_ed_agent',
                self.core.identity,
                self._device_id
            ).get(timeout=10)

            # _log.debug ('self.vip.rpc.call() result: {}'.format(success))
            if success:
                _log.info('done.')
                break
        except Exception as e:
            # print(e)
            _log.warning(
                'maybe the Volttron Bridge Agent is not yet started!!!'
                + ' message: {}'.format(e.message)
            )
            pass
        _log.warning('will try again in {} sec'.format(sleep_time))
        time.sleep(sleep_time)
    return


def unregister_with_bridge(self):
    try:
        _log.info('Unregistering with the bridge...')
        self.vip.rpc.call(self._vb_vip_identity, 'unregister_local_ed_agent',
                          self.core.identity).get(timeout=10)

        # _log.debug ('self.vip.rpc.call() result: {}'.format(success))
    except Exception as e:
        # print(e)
        _log.warning(
            'Maybe the bridge agent had stopped already!!!'
            + ' message:{}'.format(e.message)
        )
        pass
    return


# register rpc routes with MASTER_WEB
def register_rpc_route(self, name, handle, sleep_time=10):
    """

    :param self: method name    # type: str
    :param name: method name    # type: str
    :param handle: call back function
    :param sleep_time: retry interval in sec    #type: int
    """
    while True:
        try:
            _log.info('Registering agent route...')
            success = self.vip.rpc.call(
                MASTER_WEB,
                'register_agent_route',
                r'^/' + name,
                handle
            ).get(timeout=10)

            # _log.debug ('self.vip.rpc.call() result: {}'.format(success))
            if success is None:
                _log.info('done.')
                break
        except gevent.Timeout:
            _log.warning('gevent.Timeout in register_rpc_route()')
            pass
        except Exception as e:
            # print(e)
            _log.warning('maybe the Volttron instance is not yet ready!!!'
                         + ' message: {}'.format(e.message)
                         )
            pass
        _log.warning('will try again in {} sec'.format(sleep_time))
        time.sleep(sleep_time)
    return


# try to retrieve self._device_id, self._ip_addr, self._discovery_address
# from bridge agent
def retrieve_details_from_vb(self, sleep_time=10):
    device_id = self._device_id
    discovery_address = self._discovery_address
    vb_vip_identity = self._vb_vip_identity
    while True:
        try:
            _log.info('Retrieve details from vb...')
            if device_id is None:
                device_id = self.vip.rpc.call(
                    vb_vip_identity,
                    'device_id'
                ).get(timeout=10)
                self._device_id = device_id
                _log.debug('device id as per vb: {}'.format(device_id))
            if discovery_address is None:
                discovery_address = self.vip.rpc.call(
                    vb_vip_identity,
                    'discovery_address'
                ).get(timeout=10)
                self._discovery_address = discovery_address
                _log.debug('discovery_address as per vb{0}'.format(
                    ' : {}'.format(discovery_address))
                )
            if device_id is not None and discovery_address is not None:
                _log.info('done.')
                break
        except Exception as e:
            _log.warning('unable to retrieve details from bridge'
                         + ', message: {}.'.format(e.message)
                         )
            pass
        _log.warning('will try again in {} sec'.format(sleep_time))
        time.sleep(sleep_time)
    return


def publish_to_bus(self, topic, msg):
    # _log.debug('publish_to_bus()')
    now = datetime.datetime.utcnow().isoformat(' ') + 'Z'
    headers = {headers_mod.DATE: now}
    # Publish messages
    try:
        self.vip.pubsub.publish('pubsub', topic, headers, msg).get(timeout=10)
    except gevent.Timeout:
        _log.warning('gevent.Timeout in publish_to_bus()')
        return
    except Exception as e:
        _log.warning(
            'unable to publish_to_bus(), message: {}'.format(e.message)
        )
        return
    return


def get_task_schdl(self, task_id, device, time_ms=None):
    # _log.debug('get_task_schdl()')
    self.time_ms = 600 if time_ms is None else time_ms
    try:
        start = str(datetime.datetime.now())
        end = str(
            datetime.datetime.now()
            + datetime.timedelta(milliseconds=self.time_ms)
        )

        msg = [[device, start, end]]
        result = self.vip.rpc.call(
            'platform.actuator',
            'request_new_schedule',
            self._agent_id,
            task_id,
            'HIGH',
            msg
        ).get(timeout=10)

        if result['result'] != 'SUCCESS':
            return False
    except gevent.Timeout:
        _log.warning('gevent.Timeout for task_id: {}'.format(task_id))
        return False
    except Exception as e:
        _log.warning('Could not contact actuator for task_id: {}.'
                     + ' Is it running? {}'.format(task_id, e.message))
        return False
        # print(e)
    return True


def cancel_task_schdl(self, task_id):
    # _log.debug('cancel_task_schdl()')
    result = {}
    try:
        result = self.vip.rpc.call(
            'platform.actuator',
            'request_cancel_schedule',
            self._agent_id,
            task_id
        ).get(timeout=10)
    except Exception as e:
        _log.warning(
            'cancel_task_schdl() for task_id ({}) failed.'.format(task_id)
            + ' message: {}'.format(e.message))
    return result


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


# return energy in kWh for the given duration
def calc_energy_kwh(pwr_wh, duration_sec):
    value = (pwr_wh * duration_sec) / 3600000
    return value


# return energy in Wh for the given duration
def calc_energy_wh(pwr_wh, duration_sec):
    value = (pwr_wh * duration_sec) / 3600
    return value


def do_rpc(msg_id, url_root, method, params=None, request_method='POST'):
    # global authentication
    # _log.debug('do_rpc()')
    result = False
    json_package = {'jsonrpc': '2.0',
                    'id': msg_id,
                    'method': method,
                    }

    # refer to examples\WebRPC\volttronwebrpc\volttronwebrpc.py
    # if authentication is not None:
    #    json_package['authorization'] = authentication

    if params:
        json_package['params'] = params

    try:
        if request_method.upper() == 'POST':
            # https://2.python-requests.org/en/v3.0.0/user/advanced/#timeouts
            response = requests.post(
                url_root,
                data=json.dumps(json_package),
                timeout=(3.05, 3.05)
            )
        elif request_method.upper() == 'DELETE':
            response = requests.delete(
                url_root,
                data=json.dumps(json_package),
                timeout=(3.05, 3.05)
            )
        else:
            if request_method.upper() != 'GET':
                _log.warning('unimplemented'
                             + ' request_method: {}'.format(request_method)
                             + ', trying "GET"!!!'
                             )
            response = requests.get(
                url_root,
                data=json.dumps(json_package),
                timeout=(3.05, 3.05)
            )

        if response.ok:
            if 'result' in response.json().keys():
                success = response.json()['result']
                if request_method.upper() not in ['POST', 'DELETE']:
                    result = success
                elif success:
                    # _log.debug('response - ok'
                    #    + ', {} result success: {}'.format(method, success)
                    # )
                    result = True
                else:
                    _log.debug('response - ok'
                               + ', {} result success: {}'.format(method,
                                                                  success)
                               )
            elif 'error' in response.json().keys():
                error = response.json()['error']
                _log.warning('{} returned error'.format(method)
                             + ', Error: {}'.format(error)
                             )
        else:
            _log.warning('no response, url_root:{}'.format(url_root)
                         + ' method:{}'.format(method)
                         + ' response: {}'.format(response)
                         )
    except requests.exceptions.HTTPError as rhe:
        _log.warning('do_rpc() requests http error occurred.'
                     + ' Check the url'
                     + ', message: {}'.format(rhe.message)
                     )
        pass
    except requests.exceptions.ConnectTimeout as rcte:
        _log.warning('do_rpc() requests connect timed out'
                     + ' while trying connect to remote.'
                     + ' Maybe set up for a retry or continue in a retry loop'
                     + ', message: {}'.format(rcte.message)
                     )
        pass
    except requests.exceptions.ConnectionError as rce:
        _log.warning('do_rpc() requests connection error.'
                     + ' Most likely dest is down'
                     + ', message: {}'.format(rce.message)
                     )
        pass
    except requests.exceptions.ReadTimeout as rrte:
        _log.warning('do_rpc() requests read timed out.'
                     + ' Dst did not send any data in the allotted amount of '
                       'time'
                     + ', message: {}'.format(rrte.message)
                     )
        pass
    except requests.exceptions.Timeout as rte:
        _log.warning('do_rpc() requests timed out.'
                     + ' Maybe set up for a retry or continue in a retry loop'
                     + ', message: {}'.format(rte.message)
                     )
        pass
    except requests.exceptions.TooManyRedirects as rre:
        _log.warning('do_rpc() too many redirects exception.'
                     + ' Most likely URL was bad'
                     + ', message: {}'.format(rre.message)
                     )
        pass
    except requests.exceptions.RequestException as re:
        _log.warning('do_rpc() unhandled requests exception.'
                     + ' Bailing out'
                     + ', message: {}'.format(re.message)
                     )
        pass
    except Exception as e:
        # print(e)
        _log.warning('do_rpc() unhandled exception, most likely dest is down'
                     + ', message: {}'.format(e.message)
                     )
        pass
    return result


'''
    # https://bit.ly/37OaR7i
    # async_do_rpc
    def async_do_rpc(url, method='GET', params=None,
        headers=None,
        encode=False,
        verify=None,
        use_verify=False,
        callback=None
        ):

        # make a string with the request type in it:
        response = None
        request = None
        try:
            if 'POST' == method:
                if use_verify:
                    request = grequests.post(
                        url,
                        data=params,
                        headers=headers,
                        verify=verify,
                        callback=callback
                    )
                else:
                    request = grequests.post(
                        url,
                        data=params,
                        headers=headers,
                        callback=callback
                    )
            else:
                request = requests.get(
                    url,
                    data=params,
                    headers=headers,
                    callback=callback
                )

            if request:
                response = grequests.send(request, grequests.Pool(1))
                return response
            else:
                return response
        except:
            return response
'''


class Runningstats:
    """
    The code is an extension of the method of Knuth and Welford for computing
    standard deviation in one pass through the data. It computes skewness and
    Kurtosis as well with a similar interface.

    "https://en.wikipedia.org/wiki/Algorithms_for_calculating_variance#Welford's
    _online_algorithm"
    https://www.johndcook.com/blog/standard_deviation/
    https://www.johndcook.com/blog/skewness_kurtosis/

    mean()
    Variance()
    std_dev()
    skewness()
    kurtosis()

    "https://stackoverflow.com/questions/12636613/how-to-calculate-moving-
    average-without-keeping-the-count-and-data-total"

    """
    n = 0  # type: int
    M1 = M2 = M3 = M4 = 0.0

    # Exponential weighted moving average
    exp_avg = 0.0
    # factor is a constant that affects how quickly the average "catches up" to
    # the latest trend. Smaller the number the faster. (At 1 it's no longer an
    # average and just becomes the latest value.)
    # assuming 2 reading per minute, 1 hour = 120 reading
    factor = 120

    def __init__(self, factor=120):
        self.clear()
        self.factor = factor
        pass

    ''' overload methods for self and other
    '''

    # overload + operator
    def __add__(self, other):
        combined = Runningstats(self.factor)  # type: Runningstats

        combined.n = self.n + other.n

        delta = other.M1 - self.M1
        delta2 = delta * delta
        delta3 = delta * delta2
        delta4 = delta2 * delta2

        combined.M1 = (self.n * self.M1 + other.n * other.M1) / combined.n

        combined.M2 = self.M2 + other.M2 + (
                    delta2 * self.n * other.n) / combined.n

        combined.M3 = self.M3 + other.M3 + delta3 * self.n * other.n * (
                self.n - other.n) / (combined.n * combined.n)
        combined.M3 += 3.0 * delta * (
                self.n * other.M2 - other.n * self.M2) / combined.n

        combined.M4 = self.M4 + other.M4 + delta4 * self.n * other.n * (
                self.n * self.n - self.n * other.n + other.n * other.n) / (
                              combined.n * combined.n * combined.n)
        combined.M4 += (
            6.0 * delta2 * (
                    self.n * self.n * other.M2 + other.n * other.n * self.M2
            ) / (combined.n * combined.n) +
            4.0 * delta * (self.n * other.M3 - other.n * self.M3) / combined.n
        )

        combined.exp_avg = (min(self.n, self.factor) * self.exp_avg + min(
            other.n, other.factor) * other.exp_avg) / combined.n

        return combined

    ''' ENDOF overload methods for self and value
    '''

    def clear(self):
        self.n = 0
        self.M1 = self.M2 = self.M3 = self.M4 = 0.0

    def push(self, x=0.0):
        n1 = self.n

        self.n += 1

        delta = x - self.M1  # type: float
        delta_n = delta / self.n  # type: float
        delta_n2 = delta_n * delta_n  # type: float
        term1 = delta * delta_n * n1  # type: float

        self.M1 += delta_n

        self.M4 += (
                (term1 * delta_n2 * ((self.n * self.n) - (3 * self.n) + 3)) +
                (6 * delta_n2 * self.M2) -
                (4 * delta_n * self.M3)
        )

        self.M3 += (term1 * delta_n * (self.n - 2)) - (3 * delta_n * self.M2)

        self.M2 += term1

        # Exponential weighted moving average
        self.exp_avg += (x - self.exp_avg) / min(self.n, self.factor)

        return

    def num_data_values(self):
        return self.n

    def mean(self):
        return self.M1

    def variance(self):
        return self.M2 / (self.n - 1)

    def std_dev(self):
        return math.sqrt(self.variance())

    def skewness(self):
        return math.sqrt(self.n) * self.M3 / pow(self.M2, 1.5)

    def kurtosis(self):
        return self.n * self.M4 / (self.M2 * self.M2) - 3.0

    def exp_wt_mv_avg(self):
        return self.exp_avg

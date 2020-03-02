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

''' Test script to send random opt and bid prices at regurlar interval
'''
from os.path import basename
import requests
import sys
import json
import math
import threading, time, signal
import datetime
from random import random, randint

from test_utils import get_timestamp

authentication=None

#OPT_WAIT_TIME_SEC = 2             # 2 sec
#OPT_WAIT_TIME_SEC = 10             # 10 sec
#OPT_WAIT_TIME_SEC = 2 * 60         # 2 min
#OPT_WAIT_TIME_SEC = 5 * 60         # 5 min
#OPT_WAIT_TIME_SEC = 15 * 60        # 15 min
#OPT_WAIT_TIME_SEC = 30 * 60        # 30 min
OPT_WAIT_TIME_SEC = 1 * 60 * 60    # 1 hour

#BID_WAIT_TIME_SEC = 2             # 2 sec
#BID_WAIT_TIME_SEC = 10             # 10 sec
BID_WAIT_TIME_SEC = 2 * 60         # 2 min
#BID_WAIT_TIME_SEC = 5 * 60         # 5 min
#BID_WAIT_TIME_SEC = 15 * 60        # 15 min
#BID_WAIT_TIME_SEC = 30 * 60        # 30 min
#BID_WAIT_TIME_SEC = 1 * 60 * 60    # 1 hour

#OPT_DUR_TIME_SEC = 2             # 2 sec
#OPT_DUR_TIME_SEC = 10             # 10 sec
#OPT_DUR_TIME_SEC = 2 * 60         # 2 min
#OPT_DUR_TIME_SEC = 5 * 60         # 5 min
#OPT_DUR_TIME_SEC = 15 * 60        # 15 min
#OPT_DUR_TIME_SEC = 30 * 60        # 30 min
OPT_DUR_TIME_SEC = 1 * 60 * 60    # 1 hour

#BID_DUR_TIME_SEC = 2             # 2 sec
#BID_DUR_TIME_SEC = 10             # 10 sec
#BID_DUR_TIME_SEC = 2 * 60         # 2 min
#BID_DUR_TIME_SEC = 5 * 60         # 5 min
#BID_DUR_TIME_SEC = 15 * 60        # 15 min
#BID_DUR_TIME_SEC = 30 * 60        # 30 min
BID_DUR_TIME_SEC = 1 * 60 * 60    # 1 hour

ROOT_URL = 'http://192.168.1.11:8080/pricepoint'

class ProgramKilled(Exception):
    pass


def signal_handler(signum, frame):
    raise ProgramKilled

def do_rpc(method, params=None ):
    global authentication
    url_root = ROOT_URL

    json_package = {
        'jsonrpc': '2.0',
        'id': '2503402',
        'method':method,
    }

    if authentication:
        json_package['authorization'] = authentication

    if params:
        json_package['params'] = params

    data = json.dumps(json_package)
    return requests.post(url_root, data=json.dumps(json_package))

def post_random_price(isoptimal = True, duration = 3600, ttl = 10):
    #random price between 0-1
    no_digit = 2
    pp = math.floor(random() * 10**no_digit) / 10**no_digit
    pp = 0.94 if pp > 0.94 else pp
    price_id = randint(0, 99999999)

    if isoptimal:
        print get_timestamp() + ' OPT PricePoint: ' + str(pp) + ', price_id: ' + str(price_id),
    else:
        print get_timestamp() + ' BID PricePoint: ' + str(pp) + ', price_id: ' + str(price_id),

    now = datetime.datetime.utcnow().isoformat(' ') + 'Z'
    try:
        response = do_rpc('new-pp', {'msg_type': 0
                                    , 'one_to_one': False
                                    , 'value': pp
                                    , 'value_data_type': 'float'
                                    , 'units': 'cents'
                                    , 'price_id': price_id
                                    , 'isoptimal': isoptimal
                                    , 'src_ip': None
                                    , 'src_device_id': None
                                    , 'dst_ip': None
                                    , 'dst_device_id': None
                                    , 'duration': duration
                                    , 'ttl': ttl
                                    , 'ts': now
                                    ,'tz': 'UTC'
                                    })
        #print "response: " +str(response),
        if response.ok:
            if 'result' in response.json().keys():
                if response.json()['result']:
                    print 'new price updated!!!'
                else:
                    print 'new price NOT updated!!!'
            elif 'error' in response.json().keys():
                print response.json()['error']
        else:
            print 'do_rpc response NOT OK, response: {}'.format(response)
    except KeyError as ke:
        print ke
    except Exception as e:
        print e
        print 'do_rpc() unhandled exception, most likely server is down'
    sys.stdout.flush()
    return


class Job(threading.Thread):
    def __init__(self, interval, execute, args, **kwargs):
        threading.Thread.__init__(self)
        self.daemon = False
        self.stopped = threading.Event()
        self.interval = interval
        self.execute = execute
        self.args = args
        self.kwargs = kwargs

    def stop(self):
        self.stopped.set()
        self.join()

    def run(self):
        #execute once
        self.execute(*self.args, **self.kwargs)

        while not self.stopped.wait(self.interval.total_seconds()):
            self.execute(*self.args, **self.kwargs)


if __name__ == '__main__':
    print get_timestamp() + ' Initialising test ' + basename(__file__) + '...'
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    #job to post opt prices at regular interval
    job_opt = Job(interval = datetime.timedelta(seconds = OPT_WAIT_TIME_SEC)
                    , execute = post_random_price
                    , args = (True, OPT_DUR_TIME_SEC, 30,))

    #job to post bid prices at regular interval
    job_bid = Job(interval = datetime.timedelta(seconds = BID_WAIT_TIME_SEC)
                    , execute = post_random_price
                    , args = (False, BID_DUR_TIME_SEC, 30,))

    print get_timestamp() + ' ROOT_URL: ' + str(ROOT_URL),
    print ', OPT_WAIT_TIME_SEC: ' + str(OPT_WAIT_TIME_SEC),
    print ', BID_WAIT_TIME_SEC: ' + str(BID_WAIT_TIME_SEC)
    sys.stdout.flush()

    print get_timestamp() + ' Starting a repetitive jobs (opt & bid prices)...'
    job_opt.start()
    time.sleep(2)
    job_bid.start()

    while True:
          try:
              time.sleep(1)
          except ProgramKilled:
              print '\n' + get_timestamp() + ' Program killed: cleanup'
              job_opt.stop()
              job_bid.stop()
              print get_timestamp() + ' End of Program.'
              break


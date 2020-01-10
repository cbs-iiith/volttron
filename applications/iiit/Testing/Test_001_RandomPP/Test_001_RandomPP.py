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

from os.path import basename
import requests
import sys
import json
import math, random
import threading, time, signal
from datetime import timedelta

from test_utils import get_timestamp

authentication=None

#WAIT_TIME_SECONDS = 10             # 10 sec
#WAIT_TIME_SECONDS = 5 * 60         # 5 min
#WAIT_TIME_SECONDS = 15 * 60        # 15 min
#WAIT_TIME_SECONDS = 30 * 60        # 30 min
WAIT_TIME_SECONDS = 1 * 60 * 60    # 1 hour

ROOT_URL = 'http://192.168.1.11:8080/PricePoint'

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
    
def post_random_price():
    #random price between 0-1
    no_digit = 2
    pp = math.floor(random.random()*10**no_digit)/10**no_digit
    pp = .94 if pp>.94 else pp
    print get_timestamp() + ' PricePoint: ' + str(pp) + ',',
    try:
        response = do_rpc("rpc_updatePricePoint", {'newPricePoint': pp})
        #print "response: " +str(response),
        if response.ok:
            success = response.json()['result']
            if success:
                print 'new price updated'
            else:
                print 'new price NOT updated'
        else:
            print 'do_rpc pricepoint response NOT OK'
    except KeyError:
        error = response.json()['error']
        print (error)
    except Exception as e:
        #print (e)
        print 'do_rpc() unhandled exception, most likely server is down'
    sys.stdout.flush()
    return
    
class Job(threading.Thread):
    def __init__(self, interval, execute, *args, **kwargs):
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
        self.execute(*self.args, **self.kwargs)         #execute once
        while not self.stopped.wait(self.interval.total_seconds()):
            self.execute(*self.args, **self.kwargs)
                
if __name__ == '__main__':
    print get_timestamp() + ' Initialising test - ' + basename(__file__) + ' ...'
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    job = Job(interval=timedelta(seconds=WAIT_TIME_SECONDS), execute=post_random_price)
    print get_timestamp() + ' ROOT_URL: ' + str(ROOT_URL) + ', WAIT_TIME_SECONDS: ' + str(WAIT_TIME_SECONDS)
    print get_timestamp() + ' Starting a repetitive job...'
    sys.stdout.flush()
    job.start()
    
    while True:
          try:
              time.sleep(1)
          except ProgramKilled:
              print '\n' + get_timestamp() + ' Program killed: running cleanup code'
              job.stop()
              print get_timestamp() + ' End of Program.'
              break
              
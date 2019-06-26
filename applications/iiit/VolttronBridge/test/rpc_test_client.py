# -*- coding: utf-8 -*- {{{
# vim: set fenc=utf-8 ft=python sw=4 ts=4 sts=4 et:
#
# Copyright (c) 2019, Sam Babu, Godithi.
# All rights reserved.
#
#
# IIIT Hyderabad

#}}}

#Sam

import requests
import sys
import json
import time
authentication=None

def do_rpc(method, params=None ):
    global authentication
    url_root = 'http://192.168.1.250:8080/VolttronBridge'

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

def test_register():
    response = do_rpc("rpc_registerDsBridge", \
                {'discovery_address': '192.168.1.61:8080', \
                    'deviceId': 'SmartHub-61'\
                })
    print('response: ' + str(response))
    if response.ok:
        success = response.json()['result']
        print(success)
        if success:
            print('registered')
        else:
            print("not registered")
    else:
        print('do_rpc register response not ok')
        
    return True
        
def test_unregister():
    response = do_rpc("rpc_unregisterDsBridge", \
                {'discovery_address': '192.168.1.61:8080', \
                    'deviceId': 'SmartHub-61'\
                })
    print('response: ' + str(response))
    if response.ok:
        success = response.json()['result']
        print(success)
        if success:
            print('unregistered')
        else:
            print("not registered")
    else:
        print('do_rpc register response not ok')
        
    return True

if __name__ == '__main__':
    
    try:
        test_register()
        time.sleep(5)
        test_unregister()
    except KeyError:
        error = response.json()['error']
        print (error)
    except Exception as e:
        print (e)
        print('do_rpc() unhandled exception, most likely server is down')

    sys.exit(0)


    





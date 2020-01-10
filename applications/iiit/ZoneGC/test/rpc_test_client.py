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

import requests
import sys
import json
authentication=None

def do_rpc(method, params=None ):
    global authentication
    url_root = 'http://192.168.1.50:8080/PricePoint'

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

if __name__ == '__main__':
    try:
        response = do_rpc("rpc_updatePricePoint1", {'newPricePoint1': 'temp'})
        print('response: ' +str(response))
        if response.ok:
            success = response.json()['result']
            print(success)
            if success:
                print('new price updated')
            else:
                print("new price notupdated")
        else:
            print('do_rpc pricepoint response not ok')
    except KeyError:
        error = response.json()['error']
        print (error)
    except Exception as e:
        #print (e)
        print('do_rpc() unhandled exception, most likely server is down')

    sys.exit(0)


    





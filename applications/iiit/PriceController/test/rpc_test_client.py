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

import json
import sys

import requests

authentication = None


def do_rpc(url_root, method, params=None):
    # _log.debug('do_rpc()')
    result = False
    json_package = {
        'jsonrpc': '2.0',
        'id': 'testing',
        'method': method,
    }

    if params:
        json_package['params'] = params

    data = json.dumps(json_package)
    try:
        response = requests.post(url_root, data=json.dumps(json_package),
                                 timeout=10)

        if response.ok:
            success = response.json()['result']
            if success == True:
                result = True
            else:
                print('respone - not ok, {} result: {}'.format(method, success))
        else:
            print('no respone, {} result: {}'.format(method, response))
    except KeyError:
        error = response.json()['error']
        print (error)
        print('KeyError: SHOULD NEVER REACH THIS ERROR - contact developer')
        return False
    except Exception as e:
        print (e)
        print(
            'Exception: do_rpc() unhandled exception, most likely dest is down')
        return False
    return result


if __name__ == '__main__':
    url_root = 'http://192.168.1.4:8080/PriceController'
    result = do_rpc(url_root, "rpc_disable_agent", {'disable_agent': 'Hi'})
    print('result: ' + str(result))
    print('******** result should be --> result: False')
    print('Test passed!!!\n' if result == False else 'Test failed!!!\n')

    result = do_rpc(url_root, "rpc_disable_agent", {'disable_agent': True})
    print('result: ' + str(result))
    print('******** result should be --> result: True')
    print('Test passed!!!\n' if result == True else 'Test failed!!!\n')

    result = do_rpc(url_root, "rpc_disable_agent", {'disable_agent': False})
    print('result: ' + str(result))
    print('******** result should be --> result: True')
    print('Test passed!!!\n' if result == True else 'Test failed!!!\n')

    sys.exit(0)

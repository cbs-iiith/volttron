import requests
import sys
import json
import time

authentication=None

def do_rpc(method, params=None ):
    global authentication
    url_root = 'http://192.168.1.50:8080/SmartHub'

    json_package = {
        'jsonrpc': '2.0',
        'id': '2503403',
        'method':method,
    }

    if authentication:
        json_package['authorization'] = authentication

    if params:
        json_package['params'] = params

    data = json.dumps(json_package)

    return requests.post(url_root, data=json.dumps(json_package))

if __name__ == '__main__':
    
    response = do_rpc('rpc_setShDeviceThPP', {'deviceId': 1, 'newThPP': 0.5})
    print('response: ' +str(response))
    if response.ok:
        success = response.json()['result']
        if success:
            print('new newThPP updated')
        else:
            print("new newThPP notupdated")
    else:
        print('do_rpc rpc_setShDeviceThPP response not ok')

    time.sleep(1)
    
    
    response = do_rpc('rpc_setShDeviceState', {'deviceId': 1, 'newState': 1})
    print('response: ' +str(response))
    if response.ok:
        success = response.json()['result']
        if success:
            print('new state updated')
        else:
            print("new state notupdated")
    else:
        print('do_rpc setShDeviceState response not ok')

    time.sleep(1)
    
    response = do_rpc('rpc_setShDeviceLevel', {'deviceId': 1, 'newLevel': 0.9})
    print('response: ' +str(response))
    if response.ok:
        success = response.json()['result']
        if success:
            print('new state updated')
        else:
            print("new state notupdated")
    else:
        print('do_rpc setShDeviceState response not ok')
    
    time.sleep(1)
    
    response = do_rpc('rpc_setShDeviceState', {'deviceId': 1, 'newState': 0})
    print('response: ' +str(response))
    if response.ok:
        success = response.json()['result']
        print(success)
        if success:
            print('new state updated')
        else:
            print("new state notupdated")
    else:
        print('do_rpc setShDeviceState response not ok')

    sys.exit(0)


    





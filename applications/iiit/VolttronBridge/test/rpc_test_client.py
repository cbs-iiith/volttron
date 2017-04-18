import requests
import sys
import json
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

if __name__ == '__main__':
    try:
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
    except KeyError:
        error = response.json()['error']
        print (error)
    except Exception as e:
        #print (e)
        print('do_rpc() unhandled exception, most likely server is down')

    sys.exit(0)


    





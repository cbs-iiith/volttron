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
    response = do_rpc("rpc_updatePricePoint", {'newPricePoint': 0.5})
    print('response: ' +str(response))
    if response.ok:
        success = response.json()['result']
        if success:
            print('new price updated')
        else:
            print("new price notupdated")
    else:
        print('do_rpc pricepoint response not ok')

    sys.exit(0)


    





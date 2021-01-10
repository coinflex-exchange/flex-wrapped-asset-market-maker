import hmac
import base64
import hashlib
import datetime
import json
import time
import requests


class CfRest:
    def __init__(self, api_key, api_secret, base_url):
        self._api_key = api_key
        self._api_secret = api_secret
        self._base_url = base_url
        self._short_url = self._base_url.replace('https://', '')

    @staticmethod
    def _nonce():
        return int(time.time() * 1000)

    def _get(self, path):
        header = self._construct_header('GET', path)
        resp = requests.get(self._base_url + path, headers=header).json()
        print(resp)
        return resp

    def _post(self, path, body):
        header = self._construct_header('POST', path, body)
        resp = requests.post(self._base_url + path, body, headers=header).json()
        print(resp)
        return resp

    def _delete(self, path):
        header = self._construct_header('DELETE', path)
        resp = requests.delete(self._base_url + path, headers=header).json()
        print(resp)
        return resp

    def _construct_header(self, method, path, body=''):
        ts = str(datetime.datetime.utcnow().isoformat())[:19]
        nonce = self._nonce()
        if body:
            msg_string = f'{ts}\n{nonce}\n{method}\n{self._short_url}\n{path}\n{body}'
        else:
            msg_string = f'{ts}\n{nonce}\n{method}\n{self._short_url}\n{path}\n'
        sig = base64.b64encode(hmac.new(
            self._api_secret.encode('utf-8'),
            msg_string.encode('utf-8'),
            hashlib.sha256
        ).digest()).decode('utf-8')
        return {
            'Content-Type': 'application/json',
            'AccessKey': self._api_key,
            'Timestamp': ts,
            'Signature': sig,
            'Nonce': str(nonce)
        }

    def get_positions(self):
        path = '/v2/positions'
        return self._get(path)

    def get_balances(self):
        path = '/v2/balances'
        return self._get(path)

    def get_orders(self):
        path = '/v2/orders'
        return self._get(path)

    def get_historical_deliveries(self):
        path = '/v2.1/delivery/orders'
        return self._get(path)

    def deliver(self, data):
        body = json.dumps(data)
        path = '/v2.1/delivery/orders'
        return self._post(path, body)

    def cancel_all(self):
        path = '/v2/cancel/orders'
        return self._delete(path)

    def get_markets(self):
        return requests.get(self._base_url + '/v2/all/markets').json()

    def get_delivery_data(self):
        return requests.get(self._base_url + '/v2/delivery/public/deliver-auction/').json()

    def get_ticker(self):
        return requests.get(self._base_url + '/v2/ticker').json()

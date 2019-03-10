# encoding: UTF-8

from __future__ import print_function
import hashlib
import hmac
import json
import ssl
import traceback

from queue import Queue, Empty
from multiprocessing.dummy import Pool
from time import time
from urlparse import urlparse
from copy import copy
from urllib import urlencode
from threading import Thread

from six.moves import input

import requests
import websocket

REST_HOST = 'https：//www.deribit.com'
WEBSOCKET_HOST = 'wss://www.deribit.com/ws/api/v1/'

TESTNET_REST_HOST = 'https://testnet.bitmex.com/api/v1'  # https://test.deribit.com
TESTNET_WEBSOCKET_HOST = 'wss://test.deribit.com/ws/api/v1/'


########################################################################
class DeribitRestApi(object):
    """REST API"""

    # ----------------------------------------------------------------------
    def __init__(self):
        """Constructor"""
        self.apiKey = ''
        self.apiSecret = ''
        self.host = ''

        self.active = False
        self.reqid = 0
        self.queue = Queue()
        self.pool = None
        self.sessionDict = {}  # 会话对象字典

        self.header = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json'
        }

    # ----------------------------------------------------------------------
    def init(self, apiKey, apiSecret, testnet=False):
        """初始化"""
        self.apiKey = apiKey
        self.apiSecret = apiSecret

        if testnet:
            self.host = TESTNET_REST_HOST
        else:
            self.host = REST_HOST

    # ----------------------------------------------------------------------
    def start(self, n=3):
        """启动"""
        if self.active:
            return

        self.active = True
        self.pool = Pool(n)
        self.pool.map_async(self.run, range(n))

    # ----------------------------------------------------------------------
    def close(self):
        """关闭"""
        self.active = False

        if self.pool:
            self.pool.close()
            self.pool.join()

    # ----------------------------------------------------------------------
    def addReq(self, method, path, callback, params=None, postdict=None):
        """添加请求"""
        self.reqid += 1
        req = (method, path, callback, params, postdict, self.reqid)
        self.queue.put(req)
        return self.reqid

    # ----------------------------------------------------------------------
    def processReq(self, req, i):
        """处理请求"""
        method, path, callback, params, postdict, reqid = req
        url = self.host + path
        expires = int(time() + 5)

        rq = requests.Request(url=url, data=postdict)
        p = rq.prepare()

        header = copy(self.header)
        header['api-expires'] = str(expires)
        header['api-key'] = self.apiKey
        header['api-signature'] = self.generateSignature(method, path, expires, params, body=p.body)

        # 使用长连接的session，比短连接的耗时缩短80%
        session = self.sessionDict[i]
        resp = session.request(method, url, headers=header, params=params, data=postdict)

        # resp = requests.request(method, url, headers=header, params=params, data=postdict)

        code = resp.status_code
        d = resp.json()

        if code == 200:
            callback(d, reqid)
        else:
            self.onError(code, d)

            # ----------------------------------------------------------------------

    def run(self, i):
        """连续运行"""
        self.sessionDict[i] = requests.Session()

        while self.active:
            try:
                req = self.queue.get(timeout=1)
                self.processReq(req, i)
            except Empty:
                pass

    # ----------------------------------------------------------------------
    def generateSignature(self, method, path, expires, params=None, body=None):
        """生成签名"""
        # 对params在HTTP报文路径中，以请求字段方式序列化
        if params:
            query = urlencode(params.items())
            path = path + '?' + query

        if body is None:
            body = ''

        msg = method + '/api/v1' + path + str(expires) + body
        signature = hmac.new(self.apiSecret, msg,
                             digestmod=hashlib.sha256).hexdigest()
        return signature



    def generate_signature(self, action, data):
        tstamp = int(time.time() * 1000)
        signature_data = {
            '_': tstamp,
            '_ackey': self.key,
            '_acsec': self.secret,
            '_action': action
        }
        signature_data.update(data)
        sorted_signature_data = OrderedDict(sorted(signature_data.items(), key=lambda t: t[0]))

        def converter(data):
            key = data[0]
            value = data[1]
            if isinstance(value, list):
                return '='.join([str(key), ''.join(value)])
            else:
                return '='.join([str(key), str(value)])

        items = map(converter, sorted_signature_data.items())

        signature_string = '&'.join(items)

        sha256 = hashlib.sha256()
        sha256.update(signature_string.encode("utf-8"))
        sig = self.key + "." + str(tstamp) + "."
        sig += base64.b64encode(sha256.digest()).decode("utf-8")
        return sig









    # ----------------------------------------------------------------------
    def onError(self, code, error):
        """错误回调"""
        print('on error')
        print(code, error)

    # ----------------------------------------------------------------------
    def onData(self, data, reqid):
        """通用回调"""
        print('on data')
        print(data, reqid)


########################################################################
class DeribitWebsocketApi(object):
    """Websocket API"""

    # ----------------------------------------------------------------------
    def __init__(self):
        """Constructor"""
        self.ws = None
        self.thread = None
        self.active = False
        self.host = ''

    # ----------------------------------------------------------------------
    def start(self, testnet=False):
        """启动"""
        if testnet:
            self.host = TESTNET_WEBSOCKET_HOST
        else:
            self.host = WEBSOCKET_HOST

        self.connectWs()

        self.active = True
        self.thread = Thread(target=self.run)
        self.thread.start()

        self.onConnect()

    # ----------------------------------------------------------------------
    def reconnect(self):
        """重连"""
        self.connectWs()
        self.onConnect()

    # ----------------------------------------------------------------------
    def connectWs(self):
        """"""
        self.ws = websocket.create_connection(self.host, sslopt={'cert_reqs': ssl.CERT_NONE})

        # ----------------------------------------------------------------------

    def run(self):
        """运行"""
        while self.active:
            try:
                stream = self.ws.recv()
                data = json.loads(stream)
                self.onData(data)
            except:
                msg = traceback.format_exc()
                self.onError(msg)
                self.reconnect()

    # ----------------------------------------------------------------------
    def close(self):
        """关闭"""
        self.active = False

        if self.thread:
            self.thread.join()

    # ----------------------------------------------------------------------
    def onConnect(self):
        """连接回调"""
        print('connected')

    # ----------------------------------------------------------------------
    def onData(self, data):
        """数据回调"""
        print('-' * 30)
        l = data.keys()
        l.sort()
        for k in l:
            print(k, data[k])

    # ----------------------------------------------------------------------
    def onError(self, msg):
        """错误回调"""
        print(msg)

    # ----------------------------------------------------------------------
    def sendReq(self, req):
        """发出请求"""
        self.ws.send(json.dumps(req))


if __name__ == '__main__':
    API_KEY = ''
    API_SECRET = ''

    ## REST测试
    rest = BitmexRestApi()
    rest.init(API_KEY, API_SECRET)
    rest.start(3)

    data = {
        'symbol': 'XBTUSD'
    }
    rest.addReq('POST', '/position/isolate', rest.onData, postdict=data)
    # rest.addReq('GET', '/instrument', rest.onData)

    # WEBSOCKET测试
    # ws = BitmexWebsocketApi()
    # ws.start()

    # req = {"op": "subscribe", "args": ['order', 'trade', 'position', 'margin']}
    # ws.sendReq(req)

    # expires = int(time())
    # method = 'GET'
    # path = '/realtime'
    # msg = method + path + str(expires)
    # signature = hmac.new(API_SECRET, msg, digestmod=hashlib.sha256).hexdigest()

    # req = {
    # 'op': 'authKey',
    # 'args': [API_KEY, expires, signature]
    # }

    # ws.sendReq(req)

    # req = {"op": "subscribe", "args": ['order', 'execution', 'position', 'margin']}
    # req = {"op": "subscribe", "args": ['instrument']}
    # ws.sendReq(req)

    input()




import time, hashlib, requests, base64, sys
from collections import OrderedDict


class RestClient(object):
    def __init__(self, key=None, secret=None, url=None):
        self.key = key
        self.secret = secret
        self.session = requests.Session()

        if url:
            self.url = url
        else:
            self.url = "https://www.deribit.com"

    def request(self, action, data):
        response = None

        if action.startswith("/api/v1/private/"):
            if self.key is None or self.secret is None:
                raise Exception("Key or secret empty")

            signature = self.generate_signature(action, data)
            response = self.session.post(self.url + action, data=data, headers={'x-deribit-sig': signature},
                                         verify=True)
        else:
            response = self.session.get(self.url + action, params=data, verify=True)

        if response.status_code != 200:
            raise Exception("Wrong response code: {0}".format(response.status_code))

        json = response.json()

        if json["success"] == False:
            raise Exception("Failed: " + json["message"])

        if "result" in json:
            return json["result"]
        elif "message" in json:
            return json["message"]
        else:
            return "Ok"

    def generate_signature(self, action, data):
        tstamp = int(time.time() * 1000)
        signature_data = {
            '_': tstamp,
            '_ackey': self.key,
            '_acsec': self.secret,
            '_action': action
        }
        signature_data.update(data)
        sorted_signature_data = OrderedDict(sorted(signature_data.items(), key=lambda t: t[0]))

        def converter(data):
            key = data[0]
            value = data[1]
            if isinstance(value, list):
                return '='.join([str(key), ''.join(value)])
            else:
                return '='.join([str(key), str(value)])

        items = map(converter, sorted_signature_data.items())

        signature_string = '&'.join(items)

        sha256 = hashlib.sha256()
        sha256.update(signature_string.encode("utf-8"))
        sig = self.key + "." + str(tstamp) + "."
        sig += base64.b64encode(sha256.digest()).decode("utf-8")
        return sig

    def getorderbook(self, instrument):
        return self.request("/api/v1/public/getorderbook", {'instrument': instrument})

    def getinstruments(self):
        return self.request("/api/v1/public/getinstruments", {})

    def getcurrencies(self):
        return self.request("/api/v1/public/getcurrencies", {})

    def getlasttrades(self, instrument, count=None, since=None):
        options = {
            'instrument': instrument
        }

        if since:
            options['since'] = since

        if count:
            options['count'] = count

        return self.request("/api/v1/public/getlasttrades", options)

    def getsummary(self, instrument):
        return self.request("/api/v1/public/getsummary", {"instrument": instrument})

    def index(self):
        return self.request("/api/v1/public/index", {})

    def stats(self):
        return self.request("/api/v1/public/stats", {})

    def account(self):
        return self.request("/api/v1/private/account", {})

    def buy(self, instrument, quantity, price, postOnly=None, label=None):
        options = {
            "instrument": instrument,
            "quantity": quantity,
            "price": price
        }

        if label:
            options["label"] = label

        if postOnly:
            options["postOnly"] = postOnly

        return self.request("/api/v1/private/buy", options)

    def sell(self, instrument, quantity, price, postOnly=None, label=None):
        options = {
            "instrument": instrument,
            "quantity": quantity,
            "price": price
        }

        if label:
            options["label"] = label
        if postOnly:
            options["postOnly"] = postOnly

        return self.request("/api/v1/private/sell", options)

    def cancel(self, orderId):
        options = {
            "orderId": orderId
        }

        return self.request("/api/v1/private/cancel", options)

    def cancelall(self, typeDef="all"):
        return self.request("/api/v1/private/cancelall", {"type": typeDef})

    def edit(self, orderId, quantity, price):
        options = {
            "orderId": orderId,
            "quantity": quantity,
            "price": price
        }

        return self.request("/api/v1/private/edit", options)

    def getopenorders(self, instrument=None, orderId=None):
        options = {}

        if instrument:
            options["instrument"] = instrument
        if orderId:
            options["orderId"] = orderId

        return self.request("/api/v1/private/getopenorders", options)

    def positions(self):
        return self.request("/api/v1/private/positions", {})

    def orderhistory(self, count=None):
        options = {}
        if count:
            options["count"] = count

        return self.request("/api/v1/private/orderhistory", options)

    def tradehistory(self, countNum=None, instrument="all", startTradeId=None):
        options = {
            "instrument": instrument
        }

        if countNum:
            options["count"] = countNum
        if startTradeId:
            options["startTradeId"] = startTradeId

        return self.request("/api/v1/private/tradehistory", options)
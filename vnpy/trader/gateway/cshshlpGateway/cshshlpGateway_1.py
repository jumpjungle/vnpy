# encoding: UTF-8

import sys
import os
import json
import socket
import urllib
from time import sleep

import wmi

from vnpy.api.cshshlp import CsHsHlp
# from vnpy.api.ctp import MdApi
from vnpy.trader.gateway.secGateway import SecMdApi
from vnpy.trader.vtGateway import *
from vnpy.trader.vtFunction import getTempPath, getJsonPath


# 接口常量
FUNCTION_LOGIN = 331100
FUNCTION_SENDORDER = 338011
FUNCTION_CANCELORDER = 338012
FUNCTION_QRYCONTRACT = 338000
FUNCTION_QRYORDER = 338020
FUNCTION_QRYTRADE = 338021
FUNCTION_QRYPOSITION = 338023
FUNCTION_QRYACCOUNT = 338022
FUNCTION_SUBSCRIBE= 620001

ISSUE_ORDER = 33012
ISSUE_TRADE = 33011


# 交易所类型映射
exchangeMap = {}
exchangeMap[EXCHANGE_SSE] = '1'
exchangeMap[EXCHANGE_SZSE] = '2'
exchangeMapReverse = {v:k for k,v in exchangeMap.items()}
exchangeMapReverse['SSE'] = EXCHANGE_SSE


# 期权类型映射
optionTypeMap = {}
optionTypeMap[OPTION_CALL] = 'C'
optionTypeMap[OPTION_PUT] = 'P'
optionTypeMapReverse = {v:k for k,v in optionTypeMap.items()}

# 方向类型映射
directionMap = {}
directionMap[DIRECTION_LONG] = '1'
directionMap[DIRECTION_SHORT] = '2'
directionMapReverse = {v: k for k, v in directionMap.items()}

# 开平类型映射
offsetMap = {}
offsetMap[OFFSET_OPEN] = 'O'
offsetMap[OFFSET_CLOSE] = 'C'
offsetMapReverse = {v:k for k,v in offsetMap.items()}

# 持仓类型映射
posDirectionMap = {}
posDirectionMap[DIRECTION_LONG] = '0'
posDirectionMap[DIRECTION_SHORT] = '1'
posDirectionMap[DIRECTION_COVEREDSHORT] = '2'
posDirectionMapReverse = {v:k for k,v in posDirectionMap.items()}

# 委托状态映射
statusMapReverse = {}
statusMapReverse['2'] = STATUS_NOTTRADED
statusMapReverse['5'] = STATUS_CANCELLED
statusMapReverse['6'] = STATUS_CANCELLED
statusMapReverse['7'] = STATUS_PARTTRADED
statusMapReverse['8'] = STATUS_ALLTRADED
statusMapReverse['9'] = STATUS_REJECTED

# 价格类型映射
priceTypeMap = {}
priceTypeMap[PRICETYPE_LIMITPRICE] = '0'
priceTypeMap[PRICETYPE_MARKETPRICE] = 'OPB'
priceTypeMapReverse = {v: k for k, v in priceTypeMap.items()}


def print_dict(d):
    """"""
    print('-' * 30)
    l = d.keys()
    l.sort()
    for k in l:
        print('%s:%s' %(k, d[k]))


def checkOptionSymbol(symbol):
    """检查是否为期权代码"""
    if len(symbol) > 6:
        return True
    return False





########################################################################
class CshshlpGateway(VtGateway):
    """"""

    #----------------------------------------------------------------------
    def __init__(self, eventEngine, gatewayName='CS'):
        """Constructor"""
        super(CshshlpGateway, self).__init__(eventEngine, gatewayName)
        
        self.mdApi = CshshlpMdApi(self)     # 行情API
        self.tdApi = CshshlpTdApi(self)      # 交易API
        
        self.mdConnected = False        # 行情API连接状态，登录完成后为True
        self.tdConnected = False        # 交易API连接状态
        
        self.qryEnabled = False         # 是否要启动循环查询
        
        self.fileName = self.gatewayName + '_connect.json'
        self.filePath = getJsonPath(self.fileName, __file__)             
        
    #----------------------------------------------------------------------
    def connect(self):
        """连接"""
        # 载入json文件
        try:
            f = open(self.filePath)
        except IOError:
            log = VtLogData()
            log.gatewayName = self.gatewayName
            log.logContent = text.LOADING_ERROR
            self.onLog(log)
            return
        
        # 解析json文件
        setting = json.load(f)
        print(u"setting:{}".format(setting))
        f.close()
        
        try:
            userID = str(setting['userID'])
            ctpPassword = str(setting['ctpPassword'])
            brokerID = str(setting['brokerID'])
            mdAddress = str(setting['mdAddress'])
            
            opEntrustWay = setting['opEntrustWay']
            opStation = setting['opStation']
            fundAccount = setting['fundAccount']
            password = setting['password']
        except KeyError:
            log = VtLogData()
            log.gatewayName = self.gatewayName
            log.logContent = u'配置文件缺少字段'
            self.onLog(log)
            return            
        
        # 创建行情和交易接口对象
        self.mdApi.connect(userID, ctpPassword, mdAddress)
        self.tdApi.connect(opEntrustWay, opStation, fundAccount, password)
        
        # 初始化并启动查询
        self.initQuery()
    
    #----------------------------------------------------------------------
    def subscribe(self, subscribeReq):
        """订阅行情"""
        print(u"line 231 subscribeReq:{},{}".format(subscribeReq.exchange, subscribeReq.symbol))
        self.mdApi.subscribe(subscribeReq)
        
    #----------------------------------------------------------------------
    def sendOrder(self, orderReq):
        """发单"""
        return self.tdApi.sendOrder(orderReq)
        
    #----------------------------------------------------------------------
    def cancelOrder(self, cancelOrderReq):
        """撤单"""
        self.tdApi.cancelOrder(cancelOrderReq)
        
    #----------------------------------------------------------------------
    def qryAccount(self):
        """查询账户资金"""
        self.tdApi.qryAccount()
        
    #----------------------------------------------------------------------
    def qryPosition(self):
        """查询持仓"""
        self.tdApi.qryPosition()
        
    #----------------------------------------------------------------------
    def close(self):
        """关闭"""
        if self.mdConnected:
            self.mdApi.close()
        
    #----------------------------------------------------------------------
    def initQuery(self):
        """初始化连续查询"""
        if self.qryEnabled:
            # 需要循环的查询函数列表
            self.qryFunctionList = [self.qryAccount, self.qryPosition]
            
            self.qryCount = 0           # 查询触发倒计时
            self.qryTrigger = 2         # 查询触发点
            self.qryNextFunction = 0    # 上次运行的查询函数索引
            
            self.startQuery()
    
    #----------------------------------------------------------------------
    def query(self, event):
        """注册到事件处理引擎上的查询函数"""
        self.qryCount += 1
        
        if self.qryCount > self.qryTrigger:
            # 清空倒计时
            self.qryCount = 0
            
            # 执行查询函数
            function = self.qryFunctionList[self.qryNextFunction]
            function()
            
            # 计算下次查询函数的索引，如果超过了列表长度，则重新设为0
            self.qryNextFunction += 1
            if self.qryNextFunction == len(self.qryFunctionList):
                self.qryNextFunction = 0
    
    #----------------------------------------------------------------------
    def startQuery(self):
        """启动连续查询"""
        self.eventEngine.register(EVENT_TIMER, self.query)
    
    #----------------------------------------------------------------------
    def setQryEnabled(self, qryEnabled):
        """设置是否要启动循环查询"""
        self.qryEnabled = qryEnabled
    

########################################################################
class CshshlpTdApi(CsHsHlp):
    """交易API实现"""
    
    #----------------------------------------------------------------------
    def __init__(self, gateway):
        """"""
        super(CshshlpTdApi, self).__init__()
        
        self.gateway = gateway
        self.gatewayName = gateway.gatewayName
        
        self.callbackDict = {}
        
        self.opBranchNo = ''
        self.opEntrustWay = ''
        self.opStation = ''
        self.branchNo = ''
        self.clientId = ''
        self.fundAccount = ''
        self.password = ''
        self.sysnodeId = ''
        
        #self.batchNo = 0
        self.batchNo = 1000000
        
        self.batchEntrustDict = {}      # key: batchNo, value: entrustNo
        self.entrustBatchDict = {}      # key: entrustNo, value: batchNo
        
        self.orderDict = {}             # key: batchNo, value: order
        self.cancelDict = {}            # key: batchNo, value: cancelReq
        
        self.loginStatus = False
        
        self.initCallback()
        
    #----------------------------------------------------------------------
    def initCallback(self):
        """"""
        self.callbackDict[FUNCTION_LOGIN] = self.onLogin
        self.callbackDict[FUNCTION_SENDORDER] = self.onSendOrder
        self.callbackDict[FUNCTION_CANCELORDER] = self.onCancelOrder
        self.callbackDict[FUNCTION_QRYCONTRACT] = self.onQryContract
        self.callbackDict[FUNCTION_QRYORDER] = self.onQryOrder
        self.callbackDict[FUNCTION_QRYTRADE] = self.onQryTrade
        self.callbackDict[FUNCTION_QRYPOSITION] = self.onQryPosition
        self.callbackDict[FUNCTION_QRYACCOUNT] = self.onQryAccount
        
        self.callbackDict[ISSUE_ORDER] = self.onRtnOrder
        self.callbackDict[ISSUE_TRADE] = self.onRtnTrade
        
    #----------------------------------------------------------------------
    def onMsg(self, type_, data, reqNo, errorNo, errorInfo):
        """收到推送"""
        #print data
        cb = self.callbackDict.get(int(type_), None)
        if not cb:
            self.writeLog(u'无法找到对应类型的回调函数%s' %type_)
            return
        
        cb(data, reqNo, errorNo, errorInfo)
    
    #----------------------------------------------------------------------
    def sendReq(self, type_, d):
        """发送请求"""
        self.beginParam()
        
        for k, v in d.items():
            self.setValue(str(k), str(v))
        
        i = self.bizCallAndCommit(type_)
        
        return i
    
    #----------------------------------------------------------------------
    def generateReq(self):
        """生成标准委托字段的字典"""
        d = {
            "op_branch_no": self.branchNo,
            "op_entrust_way": self.opEntrustWay,
            "op_station": self.opStation,
            "branch_no": self.branchNo,
            "client_id": self.clientId,
            "fund_account": self.fundAccount,
            "password": self.password,
            "asset_prop": "B",
            "sysnode_Id": self.sysnodeId
        }
        
        return d
    
    #----------------------------------------------------------------------
    def writeError(self, errorNo, errorInfo):
        """"""
        error = VtErrorData()
        error.gatewayName = self.gatewayName
        error.errorID = errorNo
        error.errorMsg = errorInfo.decode('GBK')
        self.gateway.onError(error)
    
    #----------------------------------------------------------------------
    def writeLog(self, content):
        """"""
        log = VtLogData()
        log.gatewayName = self.gatewayName
        log.logContent = content
        self.gateway.onLog(log)
    
    ###########################################################

    #----------------------------------------------------------------------
    def onLogin(self, data, reqNo, errorNo, errorInfo):
        """"""
        if errorNo:
            self.writeError(errorNo, errorInfo)
            return
        
        for d in data:
            self.branchNo = d['branch_no']
            self.clientId = d['client_id']
            self.fundAccount = d['fund_account']
            self.sysnodeId = d['sysnode_id']
        
        self.loginStatus = True
        self.writeLog(u'交易服务器登录完成')   
        
        self.subscribeOrder()
        self.subscribeTrade()
        self.qryContract()

    #----------------------------------------------------------------------
    def onSendOrder(self, data, reqNo, errorNo, errorInfo):
        """"""
        if errorNo:
            self.writeError(errorNo, errorInfo)
            return
        
        for d in data:
            batchNo = d['batch_no']
            self.batchEntrustDict[batchNo] = d['entrust_no']
            self.entrustBatchDict[d['entrust_no']] = batchNo
            
            # 检查是否需要撤单
            if batchNo in self.cancelDict:
                cancelReq = self.cancelDict[batchNo]
                self.cancelOrder(cancelReq)
                
            # 更新数据
            order = self.orderDict[batchNo]
            t = d['entrust_time'].rjust(6, '0')
            order.orderTime = ':'.join([t[:2], t[2:4], t[4:]])
            self.gateway.onOrder(order)
    
    #----------------------------------------------------------------------
    def onCancelOrder(self, data, reqNo, errorNo, errorInfo):
        """"""
        if errorNo:
            self.writeError(errorNo, errorInfo)
            return
    
    #----------------------------------------------------------------------
    def onQryContract(self, data, reqNo, errorNo, errorInfo):
        # print(u"line 426 data:{}".format(data))
        """"""
        if errorNo:
            self.writeError(errorNo, errorInfo)
            return

        for d in data:
            contract = VtContractData()
            contract.gatewayName = self.gatewayName
            
            contract.symbol = d['option_code']
            contract.exchange = exchangeMapReverse.get(d['exchange_type'], EXCHANGE_UNKNOWN)
            contract.vtSymbol = '.'.join([contract.symbol, contract.exchange])
            contract.name = d['option_name'].decode('GBK')        
            contract.size = int(float(d['amount_per_hand']))
            contract.priceTick = float(d['opt_price_step'])
            contract.strikePrice = float(d['exercise_price'])
            contract.underlyingSymbol = d['stock_code']
            contract.productClass = PRODUCT_OPTION
            contract.optionType = optionTypeMapReverse[d['option_type']]
            contract.expiryDate = d['end_date']
            
            self.gateway.onContract(contract)
        
        self.writeLog(u'合约查询完成')
        
        self.qryOrder()
    
    #----------------------------------------------------------------------
    def onQryOrder(self, data, reqNo, errorNo, errorInfo):
        """"""
        if errorNo:
            self.writeError(errorNo, errorInfo)
            return
            
        for d in data:
            order = VtOrderData()
            order.gatewayName = self.gatewayName
            
            order.symbol = d['option_code']
            order.exchange = exchangeMapReverse.get(d['exchange_type'], EXCHANGE_UNKNOWN)
            order.vtSymbol = '.'.join([order.symbol, order.exchange])
            
            batchNo = d['batch_no']
            self.batchNo = max(self.batchNo, int(batchNo))

            order.orderID = batchNo
            order.vtOrderID = '.'.join([order.gatewayName, order.orderID])
            
            self.batchEntrustDict[batchNo] = d['entrust_no']
            self.entrustBatchDict[d['entrust_no']] = batchNo
            
            order.direction = directionMapReverse.get(d['entrust_bs'], DIRECTION_UNKNOWN)
            order.offset = offsetMapReverse.get(d['entrust_oc'], OFFSET_UNKNOWN)
            order.status = statusMapReverse.get(d['entrust_status'], STATUS_UNKNOWN)
            
            order.price = float(d['opt_entrust_price'])
            order.totalVolume = int(float(d['entrust_amount']))
            order.tradedVolume = int(float(d['business_amount']))
            
            t = d['entrust_time'].rjust(6, '0')
            order.orderTime = ':'.join([t[:2], t[2:4], t[4:]])
            
            self.gateway.onOrder(order)
            
            self.orderDict[batchNo] = order
            
        self.writeLog(u'委托查询完成')            
            
        self.qryTrade()
    
    #----------------------------------------------------------------------
    def onQryTrade(self, data, reqNo, errorNo, errorInfo):
        """"""
        if errorNo:
            self.writeError(errorNo, errorInfo)
            return
            
        for d in data:
            trade = VtTradeData()
            trade.gatewayName = self.gatewayName
            
            trade.symbol = d['option_code']
            trade.exchange = exchangeMapReverse.get(d['exchange_type'], EXCHANGE_UNKNOWN)
            trade.vtSymbol = '.'.join([trade.symbol, trade.exchange])
            
            batchNo = self.entrustBatchDict[d['entrust_no']]
            trade.orderID = batchNo
            trade.vtOrderID = '.'.join([trade.gatewayName, trade.orderID])
            
            trade.tradeID = d['business_id']
            trade.vtTradeID = '.'.join([trade.gatewayName, trade.tradeID])
            
            trade.direction = directionMapReverse.get(d['entrust_bs'], DIRECTION_UNKNOWN)
            trade.offset = offsetMapReverse.get(d['entrust_oc'], OFFSET_UNKNOWN)
            
            trade.price = float(d['opt_business_price'])
            trade.volume = int(float(d['business_amount']))
            
            t = d['business_time'].rjust(6, '0')
            trade.tradeTime= ':'.join([t[:2], t[2:4], t[4:]])            
            
            self.gateway.onTrade(trade)
            
        self.writeLog(u'成交查询完成')
    
    #----------------------------------------------------------------------
    def onQryPosition(self, data, reqNo, errorNo, errorInfo):
        """"""
        if errorNo:
            self.writeError(errorNo, errorInfo)
            return
        
        for d in data:
            pos = VtPositionData()
            pos.gatewayName = self.gatewayName
            
            pos.symbol = d['option_code']
            pos.exchange = exchangeMapReverse.get(d['exchange_type'], EXCHANGE_UNKNOWN)
            pos.vtSymbol = '.'.join([pos.symbol, pos.exchange])
            pos.direction = posDirectionMapReverse.get(d['opthold_type'], DIRECTION_UNKNOWN)
            pos.vtPositionName = '.'.join([pos.vtSymbol, pos.direction]) 
    
            pos.position = int(float(d['hold_amount']))
            pos.positionProfit = float(d['income_balance'])
            pos.price = float(d['opt_cost_price'])
            pos.frozen = int((float(d['hold_amount']) - float(d['enable_amount'])))

            self.gateway.onPosition(pos)
    
    #----------------------------------------------------------------------
    def onQryAccount(self, data, reqNo, errorNo, errorInfo):
        """"""
        if errorNo:
            self.writeError(errorNo, errorInfo)
            return
            
        for d in data:
            account = VtAccountData()
            account.gatewayName = self.gatewayName
            
            account.accountID = self.fundAccount
            account.vtAccountID = '.'.join([self.gatewayName, account.accountID])
            account.available = float(d['enable_balance'])
            account.margin = float(d['real_used_bail'])
            account.positionProfit = float(d['income_balance'])
            account.balance = float(d['total_asset'])
        
            self.gateway.onAccount(account)            
    
    #----------------------------------------------------------------------
    def onRtnTrade(self, data, reqNo, errorNo, errorInfo):
        """"""
        for d in data:
            # 撤单回报business_amount小于0，可以通过其进行过滤
            tradeVolume = int(float(d['business_amount']))
            entrustNo = d['entrust_no']
            batchNo = self.entrustBatchDict.get(entrustNo, '')            
            
            # 成交推送，只有当成交数量大于0时
            if tradeVolume > 0:
                trade = VtTradeData()
                trade.gatewayName = self.gatewayName
                
                trade.symbol = d['option_code']
                trade.exchange = exchangeMapReverse.get(d['exchange_type'], EXCHANGE_UNKNOWN)
                trade.vtSymbol = '.'.join([trade.symbol, trade.exchange])
                
                trade.orderID = batchNo
                trade.vtOrderID = '.'.join([trade.gatewayName, trade.orderID])
                
                trade.tradeID = d['business_id']
                trade.vtTradeID = '.'.join([trade.gatewayName, trade.tradeID])
                
                trade.direction = directionMapReverse.get(d['entrust_bs'], DIRECTION_UNKNOWN)
                trade.offset = offsetMapReverse.get(d['entrust_oc'], OFFSET_UNKNOWN)
                
                trade.price = float(d['opt_business_price'])
                trade.volume = int(float(d['business_amount']))
                
                t = d['business_time'].rjust(6, '0')
                trade.tradeTime= ':'.join([t[:2], t[2:4], t[4:]])
                
                self.gateway.onTrade(trade)     
            
            # 委托推送
            order = self.orderDict[batchNo]
            
            if tradeVolume > 0:
                order.tradedVolume += tradeVolume
                
            order.status = statusMapReverse.get(d['entrust_status'], STATUS_UNKNOWN)  
            
            self.gateway.onOrder(order)
    
    #----------------------------------------------------------------------
    def onRtnOrder(self, data, reqNo, errorNo, errorInfo):
        """"""
        for d in data:
            entrustNo = d['entrust_no']
            if entrustNo not in self.entrustBatchDict:
                return
                
            batchNo = self.entrustBatchDict[entrustNo]
            order = self.orderDict[batchNo]

            order.status = statusMapReverse.get(d['entrust_status'], STATUS_UNKNOWN)            
            order.tradedVolume = int(float(d['business_amount']))
            
            self.gateway.onOrder(order)
        
    ###########################################################
    
    #----------------------------------------------------------------------
    def connect(self, opEntrustWay, opStation, fundAccount, password):
        """"""
        self.opEntrustWay = opEntrustWay
        #self.opStation = opStation
        self.fundAccount = fundAccount
        self.password = password        
        
        # 生成op_station        
        #data = json.loads(urllib.urlopen("http://ip.jsontest.com/").read())
        #iip = data["ip"]
        iip = '127.0.0.1'

        c = wmi.WMI()
        mac = None
        lip = None
        cpu = None
        hdd = None
        pi = None
        
        for interface in c.Win32_NetworkAdapterConfiguration(IPEnabled=1):
            mac = interface.MACAddress     # MAC地址
            lip = interface.IPAddress[0]   # 公网IP
            
        for processor in c.Win32_Processor():
            cpu = processor.Processorid.strip()   # CPU编号
            
        for disk in c.Win32_DiskDrive():   # 硬盘编号
            hdd = disk.SerialNumber.strip()   
            
        for disk in c.Win32_LogicalDisk (DriveType=3):   # 硬盘分区信息
            pi = ','.join([disk.Caption, disk.Size])
          
        pcn = socket.gethostname()         # 计算机名称
        
        self.opStation = 'TYJR-%s-IIP.%s-LIP.%s-MAC.%s-HD.%s-PCN.%s-CPU.%s-PI.%s' %(opStation,
                                                                                    iip,
                                                                                    lip,
                                                                                    mac,
                                                                                    hdd,
                                                                                    pcn,
                                                                                    cpu,
                                                                                    pi)

        # 读取配置文件
        i = self.loadConfig("Hsconfig.ini")
        if i:
            self.writeLog(u'交易加载配置失败，原因：%s' %self.getErrorMsg().decode('GBK'))
            return
        self.writeLog(u'交易加载配置成功')

        # 初始化
        i = self.init()
        if i:
            self.writeLog(u'交易初始化失败，原因：%s' %self.getErrorMsg().decode('GBK'))
            return
        self.writeLog(u'交易初始化成功')
        
        # 连接服务器
        i = self.connectServer()
        if i:
            self.writeLog(u'交易服务器连接失败，原因：%s' %self.getErrorMsg().decode('GBK'))
            return
        self.writeLog(u'交易服务器连接成功')
        
        # 登录
        req = {}
        req['identity_type'] = '2'
        req['password_type'] = '2'
        req['input_content'] = '1'
        req['op_entrust_way'] = self.opEntrustWay
        req['password'] = self.password
        req['account_content'] = self.fundAccount
        self.sendReq(FUNCTION_LOGIN, req)
    
    #----------------------------------------------------------------------
    def sendOrder(self, orderReq):
        """"""
        req = self.generateReq()
        
        req['exchange_type'] = exchangeMap.get(orderReq.exchange, '')
        req['option_code'] = orderReq.symbol
        req['entrust_amount'] = str(orderReq.volume)
        req['opt_entrust_price'] = str(orderReq.price)
        req['entrust_bs'] = directionMap.get(orderReq.direction, '')
        req['entrust_oc'] = offsetMap.get(orderReq.offset, '')
        req['covered_flag'] = ''
        req['entrust_prop'] = priceTypeMap.get(orderReq.priceType, '')
        
        self.batchNo += 1
        batchNo = str(self.batchNo)        
        req['batch_no'] = batchNo
        
        reqNo = self.sendReq(FUNCTION_SENDORDER, req)
        
        vtOrderID = '.'.join([self.gatewayName, batchNo])
        
        # 缓存委托信息
        order = VtOrderData()
        order.gatewayName = self.gatewayName
        
        order.symbol = orderReq.symbol
        order.exchange = orderReq.exchange
        order.vtSymbol = '.'.join([order.symbol, order.exchange])
        order.orderID = batchNo
        order.vtOrderID = vtOrderID        
        order.direction = orderReq.direction
        order.offset = orderReq.offset        
        order.price = orderReq.price
        order.totalVolume = orderReq.volume
        order.status = STATUS_UNKNOWN
        
        self.orderDict[batchNo] = order
        
        return vtOrderID
    
    #----------------------------------------------------------------------
    def cancelOrder(self, cancelReq):
        """"""        
        # 如果尚未收到委托的柜台编号，则缓存该撤单请求
        batchNo = cancelReq.orderID
        if batchNo not in self.batchEntrustDict:
            self.cancelDict[batchNo] = cancelReq
            return
        
        # 获取对应的柜台委托号，并撤单
        entrustNo = self.batchEntrustDict[batchNo]
        
        req = self.generateReq()
        req['entrust_no'] = entrustNo
        
        self.sendReq(FUNCTION_CANCELORDER, req)
        
        # 移除撤单请求字典中的缓存
        if batchNo in self.cancelDict:
            del self.cancelDict[batchNo]
    
    #----------------------------------------------------------------------
    def qryContract(self):
        """"""
        req = self.generateReq()
        req['request_num'] = '10000'
        self.sendReq(FUNCTION_QRYCONTRACT, req)
    
    #----------------------------------------------------------------------
    def qryPosition(self):
        """"""
        if not self.loginStatus:
            return
        
        req = self.generateReq()
        req['request_num'] = '10000'
        self.sendReq(FUNCTION_QRYPOSITION, req)
    
    #----------------------------------------------------------------------
    def qryAccount(self):
        """"""
        if not self.loginStatus:
            return
        
        req = self.generateReq()
        self.sendReq(FUNCTION_QRYACCOUNT, req)
    
    #----------------------------------------------------------------------
    def qryTrade(self):
        """"""
        req = self.generateReq()
        self.sendReq(FUNCTION_QRYTRADE, req)
    
    #----------------------------------------------------------------------
    def qryOrder(self):
        """"""
        req = self.generateReq()
        self.sendReq(FUNCTION_QRYORDER, req)
        
    #----------------------------------------------------------------------
    def subscribeOrder(self):
        """"""
        req = {}
        req['acc_info'] = '~'.join([self.branchNo, self.fundAccount])
        req['issue_Type'] = ISSUE_ORDER
        
        self.beginParam()
        for k, v in req.items():
            self.setValue(str(k), str(v))
        
        l = self.subscribeData(FUNCTION_SUBSCRIBE)
        for d in l:
            self.writeLog(u'委托推送：%s' %d['result_info'].decode('GBK'))
        
    #----------------------------------------------------------------------
    def subscribeTrade(self):
        """"""
        req = {}
        req['acc_info'] = '~'.join([self.branchNo, self.fundAccount])
        req['issue_Type'] = ISSUE_TRADE
        
        self.beginParam()
        
        for k, v in req.items():
            self.setValue(str(k), str(v))
        
        l = self.subscribeData(FUNCTION_SUBSCRIBE)
        for d in l:
            self.writeLog(u'成交推送：%s' %d['result_info'].decode('GBK'))
    

########################################################################
class CshshlpMdApi(SecMdApi):
    """行情API实现，使用的CTP接口，但是字段上和ctpGateway有区别"""

    def writeLog(self, content):
        """发出日志"""
        log = VtLogData()
        log.gatewayName = self.gatewayName
        log.logContent = content
        self.gateway.onLog(log)        





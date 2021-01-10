from datetime import time as tm
import os

'''
ENV = ENV_TO_DEPLOY
API_KEY = os.getenv('FLEXUSD_API_KEY')
API_SECRET = os.getenv('FLEXUSD_API_SECRET')
'''

ENV = 'STAGE'
API_KEY = 'Jj/Nr0Fdpo/fLO71oyUKNc/V18BuYLtLgE6mJtUpl4Y='  # change keys
API_SECRET = 'cJpXn6K7aUC2ZEylQarRV/FBXc6S5rebvC4WVG9pKH0='


class Connectivity:
    if ENV == 'STAGE':
        WS_URL = 'wss://v2stgapi.coinflex.com/v2/websocket'
        REST_URL = 'https://v2stgapi.coinflex.com'
        API_KEY = API_KEY
        API_SECRET = API_SECRET
    elif ENV == 'LIVE':
        WS_URL = 'wss://v2api.coinflex.com/v2/websocket'
        REST_URL = 'https://v2api.coinflex.com'
        API_KEY = API_KEY
        API_SECRET = API_SECRET


class USDTradeData:
    orderbook = {}
    mark_prices = {}
    size_inc = {}  # minimum order sizes by market
    net_imbal = {}  # {'swap_market': 0,...} net delivery imbalance
    available = {}  # available balance
    total = {}  # total balance
    bids = {}  # {'repo_market': {'1': [placed, size, price, oid], '2':...}...}
    asks = {}  # {'repo_market': {'1': [placed, size, price, oid], '2':...}...}

    large_cap_distribution = {'1': (0.00002, 0.25), '2': (0.00004, 0.6), '3': (0.00006, 0.15)}
    medium_cap_distribution = {'1': (0.00002, 0.25), '2': (0.00004, 0.6), '3': (0.00006, 0.15)}
    small_cap_distribution = {'1': (0.00002, 0.25), '2': (0.00004, 0.6), '3': (0.00006, 0.15)}

    coin_definition = {
        'large': ['BTC'],
        'medium': ['LINK', 'YFI', 'UNI', 'USDT', 'BCH', 'DOT', 'ETH'],
        'small': ['SNX', 'BAND', 'CRV', 'BAL', 'COMP']
    }
    coin_allocation = {
        'BTC': 0.8, 'ETH': 0.115, 'BCH': 0.01, 'DOT': 0.01, 'LTC': 0.01,
        'LINK': 0.005, 'YFI': 0.005, 'UNI': 0.005, 'USDT': 0.015, 'DASH': 0.005,
        'SNX': 0.0025, 'BAND': 0.0025, 'CRV': 0.0025, 'BAL': 0.0025,
        'COMP': 0.0025, 'OMG': 0.0025, 'SUSHI': 0.0025, 'FLEX': 0.0025
    }
    large_allocation = coin_allocation['BTC']
    medium_allocation = coin_allocation['ETH']
    small_allocation = coin_allocation['COMP']

    df = ''

    safety_buffer = 0.95
    logger = ''
    delivery_timer = {}

    repo_market = []  # Change markets here
    swap_market = []
    subscription = {
        'op': 'subscribe',
        'args': ['balance:all', 'order:all'],
        'tag': '1',
    }

    WS_FLAG = False

    # 04:00 UTC auction
    am_deliv_start = tm(3, 20)
    am_deliv_end = tm(3, 30)
    am_bid_start = tm(3, 59, 10)
    am_bid_end = tm(4, 00)

    # 12:00 UTC auction
    noon_deliv_start = tm(11, 20)
    noon_deliv_end = tm(11, 30)
    noon_bid_start = tm(11, 59, 10)
    noon_bid_end = tm(12, 00)

    # 20:00 UTC auction
    pm_deliv_start = tm(19, 20)
    pm_deliv_end = tm(19, 30)
    pm_bid_start = tm(19, 59, 10)
    pm_bid_end = tm(20, 00)

    @staticmethod
    def reset_asks():
        return {
            '6': [False, 0, 0, 0],  # placed, qty, price, orderId
        }

    @staticmethod
    def reset_bids():
        return {
            '1': [False, 0, 0, 0],  # placed, qty, price, orderId
            '2': [False, 0, 0, 0],
            '3': [False, 0, 0, 0],
        }

    @staticmethod
    def reset_coin_alloc():
        return {
            'BTC': 0.8, 'ETH': 0.12, 'BCH': 0.02, 'DOT': 0.01,
            'LINK': 0.005, 'YFI': 0.005, 'UNI': 0.005, 'USDT': 0.015,
            'SNX': 0.0028, 'BAND': 0.0028, 'CRV': 0.0028, 'BAL': 0.0028, 'COMP': 0.0028
        }

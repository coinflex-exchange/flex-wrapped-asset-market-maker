import asyncio
import json
import math
import time
import websockets
import rest_wrapper
import coinflex_websocket as cfws
import utils
from config import USDTradeData as TD, Connectivity as Conn


async def trade():
    while True:
        while not TD.repo_market:
            await asyncio.sleep(3)
        # Initialise parameters using rest.
        await trade_prep()
        # Connect to CoinFLEX's WebSocket.
        async with websockets.connect(Conn.WS_URL) as ws:
            # Authenticate the WebSocket connection.
            await ws.send(json.dumps(await cfws.auth(Conn.API_KEY, Conn.API_SECRET)))
            # Subscribe to the order book, order, position, and balance channels.
            await ws.send(json.dumps(TD.subscription))
            # Confirm all of the markets are subscribed to.
            await subscribe(ws)

            # This is where the trading logic starts.
            while TD.WS_FLAG and ws.open:
                try:
                    # Await a message from CoinFLEX's WebSocket.
                    response = await ws.recv()
                    msg = json.loads(response)
                    # Output the message from CoinFLEX's WebSocket.
                    # TD.logger.info(str(msg))

                    if 'table' in msg:
                        if msg['table'] == 'order':
                            skip = await cfws.parse_message(TD, msg)
                            if skip:
                                continue

                        if msg['table'] == 'balance':
                            # TD.logger.info(str(msg))
                            data = msg['data']
                            TD.logger.info(str(msg))
                            for asset in data:
                                TD.total[asset['instrumentId']] = float(asset['total'])
                                TD.available[asset['instrumentId']] = math.floor(
                                    float(asset['available']) * 1000) / 1000

                            # Start trading
                            # Get the total amount of USD originally input into the system.
                            for asset in TD.total:
                                spot_market = asset + '-USD'
                                if asset != 'USD' and spot_market in TD.mark_prices:
                                    TD.total['USD'] += TD.total[asset] * TD.mark_prices[spot_market]
                                    # Check for opportunities to match deliveries and deliver before each auction
                                    await deliver(ws, asset)

                            # Distribute bids and asks at the pre-defined levels from TradeData.
                            for asset in TD.total:
                                if asset == 'USD':
                                    await distribute_bids(ws)
                                else:
                                    await distribute_asks(ws, asset)

                                if (
                                        utils.is_time_between(TD.noon_bid_start, TD.noon_bid_end)
                                        or utils.is_time_between(TD.am_bid_start, TD.am_bid_end)
                                        or utils.is_time_between(TD.pm_bid_start, TD.pm_bid_end)
                                ):

                                    # Wait for the auction, yield calculations, and interest payments to be processed.
                                    await asyncio.sleep(120)
                                    # Reset allocations after the auction.
                                    TD.coin_allocation = TD.reset_coin_alloc()
                                    TD.bids = {str(i): TD.reset_bids() for i in TD.bids}
                                    TD.asks = {str(i): TD.reset_asks() for i in TD.asks}
                                    await trade_prep()
                                    continue

                except Exception:
                    TD.logger.exception('trade caught this error')
                    TD.WS_FLAG = False
                    await ws.close()


async def trade_prep():
    try:
        await asyncio.sleep(5)
        orders = rest.get_orders()['data']
        if orders:
            for i in orders:
                cl_o_id = i['clientOrderId']
                repo_market = i['marketCode']
                o_size = float(i['remainingQuantity'])
                o_price = float(i['price'])
                o_id = str(i['orderId'])

                if cl_o_id in ['1', '2', '3']:
                    TD.bids[repo_market][cl_o_id] = [True, o_size, o_price, o_id]

                elif cl_o_id == '6':
                    TD.asks[repo_market]['6'] = [True, o_size, o_price, o_id]

        # Alternatively, cancel all orders and start fresh.
        TD.logger.info(f'{TD.bids}')
        TD.logger.info(f'{TD.asks}')

    except Exception:
        TD.logger.exception('trade_prep caught this error')
    return


async def subscribe(ws):
    login, order, balance = False, False, False
    setup = False
    # Ensure all of the channels have been connected to prior to trading.
    now = time.time()
    while not setup:
        try:
            response = await ws.recv()
            msg = json.loads(response)
            TD.logger.info(f'setup {msg}')
            if 'event' in msg and 'success' in msg:
                if msg['event'] == 'login' and msg['success']:
                    login = True
            if 'channel' in msg:
                if (
                        msg['channel'] == 'order:all'
                        and msg['event'] == 'subscribe'
                ):
                    order = True
                if (
                        msg['channel'] == 'balance:all'
                        and msg['event'] == 'subscribe'
                ):
                    balance = True
            if login and order and balance:
                setup = True
                TD.WS_FLAG = True
            if now + 20 < time.time():
                TD.logger.info('something went wrong during setup; retrying!')
                return

        except Exception:
            TD.logger.exception('subscribe caught this error')
            ws.close()
            return

    TD.logger.info('successfully connected to CoinFLEX')
    return


async def distribute_bids(ws):
    for repo_market in TD.repo_market:
        if TD.available['USD'] > 0:
            coin = utils.market_to_coin(repo_market)
            if coin not in TD.coin_allocation:
                continue
            spot_market = coin + '-USD'

            filled = TD.total[coin]
            size_inc = TD.size_inc[repo_market]
            min_size = 10 ** -size_inc

            coin_alloc = TD.coin_allocation[coin]

            # Determine which distribution the coin is in.
            if coin in TD.coin_definition['large']:
                distribution = TD.large_cap_distribution
            elif coin in TD.coin_definition['medium']:
                distribution = TD.medium_cap_distribution
            else:
                distribution = TD.small_cap_distribution

            # Place or edit orders according to the distribution.
            for order in distribution:
                bid = TD.bids[repo_market][order]  # [placed, size, price, orderId]
                placed, o_size, o_price, o_id = bid[0], bid[1], bid[2], bid[3]
                price = distribution[order][0]
                bid_fraction = distribution[order][1]

                # Cancel bids if a buy auction is coming up
                if (
                    utils.is_time_between(TD.noon_deliv_end, TD.noon_bid_end)
                    or utils.is_time_between(TD.am_deliv_end, TD.am_bid_end)
                    or utils.is_time_between(TD.pm_deliv_end, TD.pm_bid_end)
                ) and TD.net_imbal[coin + '-USD-SWAP-LIN'] >= min_size:
                    if placed:
                        await cfws.cancel_order(TD, ws, o_id, repo_market)
                    continue

                # expected_size = Original bid size
                expected_size = (TD.total['USD'] * bid_fraction * coin_alloc * TD.safety_buffer)
                expected_size /= TD.mark_prices[spot_market]

                if filled > 0:
                    size = math.floor((expected_size - filled) * 10 ** size_inc) / 10 ** size_inc
                    filled -= expected_size
                else:
                    size = math.floor(expected_size * 10 ** size_inc) / 10 ** size_inc

                if not placed and size >= min_size:
                    await cfws.place_order(TD, ws, order, repo_market, 'BUY', 'LIMIT', size, 'GTC', price)
                    await asyncio.sleep(0.075)

                elif (
                        size * 1.001 < o_size
                        or size * 0.999 > o_size
                        or price != o_price
                ) and size >= min_size:
                    await cfws.cancel_order(TD, ws, o_id, repo_market)
                    await cfws.place_order(TD, ws, order, repo_market, 'BUY', 'LIMIT', size, 'GTC', price)
                    # await cfws.ModifyOrder(TD, ws, count, o_id, market, 'BUY', size, price)
                    await asyncio.sleep(0.075)

                elif size < min_size and placed:
                    await cfws.cancel_order(TD, ws, o_id, repo_market)

        elif TD.available['USD'] < 0:
            for count in range(1, 3):
                count = str(count)
                o_id = TD.bids[repo_market][count][3]
                if int(count) >= 3:
                    break
                await cfws.cancel_order(TD, ws, o_id, repo_market)
    return


async def distribute_asks(ws, asset: str):
    repo_market = f'{asset}-USD-REPO-LIN'
    size = TD.total[asset]
    if size == 0 or repo_market not in TD.repo_market:
        return
    min_size = 10 ** -TD.size_inc[repo_market]
    ask = TD.asks[repo_market]['6']  # [placed, size, price, orderId]
    placed, o_size, o_price, o_id = ask[0], ask[1], ask[2], ask[3]
    try:
        if TD.total[asset] > 0:
            # Place or edit orders according to the distribution.
            if not placed and size >= min_size:
                await cfws.place_order(TD, ws, 6, repo_market, 'SELL', 'LIMIT', size, 'GTC', 0)
                await asyncio.sleep(0.075)

            elif (o_size != size or o_price != 0) and size >= min_size:
                await cfws.cancel_order(TD, ws, o_id, repo_market)
                await cfws.place_order(TD, ws, 6, repo_market, 'SELL', 'LIMIT', size, 'GTC', 0)
                await asyncio.sleep(0.075)
                # await cfws.ModifyOrder(TD, ws, '6', o_id, repo_market, 'SELL', size, 0)

        elif TD.available[asset] < 0:
            TD.logger.info(f'exceeded available balance, cancelling orders: {TD.available[asset]} {o_id}')
            await cfws.cancel_order(TD, ws, o_id, repo_market)

    except Exception:
        TD.logger.exception('distribute_asks caught this error')
    return


async def deliver(ws, coin: str):
    repo_market = coin + '-USD-REPO-LIN'
    swap_market = coin + '-USD-SWAP-LIN'
    min_size = 10 ** -TD.size_inc[repo_market]
    total_balance = TD.total[coin]
    delivery_imbalance = TD.net_imbal[swap_market]
    ask = TD.asks[repo_market]['6']  # [placed, size, price, orderId]
    placed, o_id = ask[0], ask[3]
    if (
            utils.is_time_between(TD.noon_deliv_start, TD.noon_deliv_end)
            or utils.is_time_between(TD.am_deliv_start, TD.am_deliv_end)
            or utils.is_time_between(TD.pm_deliv_start, TD.pm_deliv_end)
    ):
        # Deliver outstanding positions prior to the 30 minute auction cut-off.
        if total_balance != 0:
            if placed:
                await cfws.cancel_order(TD, ws, o_id, repo_market)
            TD.net_imbal[swap_market] -= total_balance  # Subtract because shorts are being delivered.
            delivery = {'instrumentId': swap_market, 'qtyDeliver': str(abs(total_balance))}
            TD.logger.info(f'{delivery}')
            resp = rest.deliver(delivery)
            await asyncio.sleep(5)
            if 'data' in resp:
                if resp['data']:
                    TD.total[coin] = 0
                    TD.delivery_timer[repo_market] = time.time()

    # Deliver early if there is an opposite delivery outstanding.
    elif (
            delivery_imbalance >= min_size
            and total_balance >= min_size
            and time.time() > TD.delivery_timer[repo_market] + 8 * 60 + 1
    ):
        size = delivery_imbalance if abs(delivery_imbalance) < total_balance else total_balance
        if placed:
            await cfws.cancel_order(TD, ws, o_id, repo_market)
        delivery = {'instrumentId': swap_market, 'qtyDeliver': str(abs(size))}
        TD.logger.info(f'{delivery}')
        resp = rest.deliver(delivery)
        await asyncio.sleep(5)
        if 'data' in resp:
            if resp['data']:
                TD.delivery_timer[repo_market] = time.time()
    return


async def mark_price():
    while not TD.mark_prices:
        await asyncio.sleep(3)
    while True:
        try:
            # get /all/markets
            resp = rest.get_markets()
            TD.logger.info(f'spot mark prices {resp}')

            # parse /v2/all/markets for spot mark prices and minimum order sizes (size_inc).
            if resp:
                for i in resp['data']:
                    market_code = i['marketCode']
                    repo_market = utils.change_market(market_code, 'REPO')
                    price = float(i['marketPrice'])
                    increment = float(i['qtyIncrement'])
                    if market_code in TD.mark_prices:
                        TD.mark_prices[market_code] = price
                        TD.size_inc[repo_market] = -math.log10(increment)
            await asyncio.sleep(5)

        except Exception:
            TD.logger.exception('mark_price caught this error')


async def net_delivery():
    while not TD.net_imbal:
        await asyncio.sleep(3)
    while True:
        try:
            auction = rest.get_delivery_data()
            TD.logger.info(f'{auction}')
            if auction['data']:
                data = auction['data']
                for swap_market in data:
                    TD.net_imbal[swap_market['instrumentId']] = float(swap_market['netDeliver'])
                TD.logger.info(f'delivery imbalance: {auction} {TD.net_imbal}')

            TD.logger.info(f'{TD.available}')
            TD.logger.info(f'{TD.total}')
            TD.logger.info(f'{TD.bids}')
            TD.logger.info(f'{TD.asks}')
            await asyncio.sleep(60)

        except Exception:
            TD.logger.exception('net_delivery caught this error')


async def get_markets():
    while True:
        try:
            # get ticker data to initialise repos, cf_markets, order_topics, and mark_prices.
            resp = rest.get_ticker()
            TD.logger.info(f'tickers: {resp}')

            # loop over the tickers to get the relevant data to initialise variables.
            for i in resp:
                coin = utils.market_to_coin(i['marketCode'])
                if 'REPO' in i['marketCode'] and i['marketCode'] not in TD.repo_market:
                    repo_market = i['marketCode']
                    swap_market = utils.change_market(repo_market, 'SWAP')
                    spot_market = f'{coin}-USD'

                    TD.repo_market.append(repo_market)
                    TD.delivery_timer.update({repo_market: time.time()})
                    TD.net_imbal.update({swap_market: 0})
                    TD.mark_prices.update({spot_market: 0})

                    TD.bids.update({repo_market: TD.reset_bids()})
                    TD.asks.update({repo_market: TD.reset_asks()})

                    TD.size_inc.update({repo_market: 0})
                    TD.total.update({coin: 0})
                    TD.available.update({coin: 0})

                # In case a new coin is listed add the coin to the allocation variable.
                if 'REPO' in i['marketCode'] and coin not in TD.coin_allocation:
                    print(coin)
                    # Reconnect to websockets to pick up the new market.
                    TD.WS_FLAG = False
                    # Set allocation and distribution params for the new market.
                    TD.coin_definition['small'].append(coin)
                    small_cap_length = len(TD.coin_definition['small'])
                    allocation = TD.small_allocation * small_cap_length / (small_cap_length + 1)
                    for coin in TD.coin_definition['small']:
                        TD.coin_allocation[coin] = allocation
                    TD.small_allocation = allocation

            await asyncio.sleep(600)
        except Exception:
            TD.logger.exception('get_markets caught this error')
            await asyncio.sleep(10)


async def routines():
    tasks = [
        get_markets(),
        mark_price(),
        net_delivery(),
        trade(),
    ]
    # Start the bot.
    TD.logger.info('--- Bot Starting Up ---')
    await asyncio.wait(tasks)


def main():
    # Start the co-routines.
    loop = asyncio.get_event_loop()
    loop.run_until_complete(routines())


if __name__ == '__main__':
    TD.logger = cfws.setup_logger()
    rest = rest_wrapper.CfRest(Conn.API_KEY, Conn.API_SECRET, Conn.REST_URL)
    main()

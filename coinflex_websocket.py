import base64
import hashlib
import hmac
import json
import logging
import time
import sys


def setup_logger():
    # add logging.StreamHandler() to handlers list if needed
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # create file handler which logs even debug messages
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)

    # create formatter and add it to the handlers
    formatter = logging.Formatter('%(asctime)s, %(message)s')
    handler.setFormatter(formatter)

    # add the handlers to logger
    logger.addHandler(handler)
    return logger


async def auth(api_key, api_secret):
    timestamp = str(int(time.time() * 1000))
    message = bytes(timestamp + 'GET' + '/auth/self/verify', 'utf-8')
    secret = bytes(api_secret, 'utf-8')
    signature = base64.b64encode(
        hmac.new(secret, message, digestmod=hashlib.sha256).digest()
    ).decode('utf-8')
    args = {'apiKey': api_key, 'timestamp': timestamp, 'signature': signature}
    return {'op': 'login', 'data': args, 'tag': 1}


async def modify_order(TD, ws, cl_o_id: int, o_id: int, market: str, side: str, size: float, price: float, tag=20):
    purpose = 'modifyorder'
    TD.logger.info(f'modifying {market} {side} order, price: {price} quantity: {size}')
    await ws.send(
        json.dumps(
            {
                'op': 'modifyorder',
                'data': {
                    'marketCode': market,
                    'orderId': o_id,
                    'side': side,
                    'price': price,
                    'quantity': size,
                },
                'tag': tag,
            }
        )
    )
    await order_management(TD, ws, purpose, market, cl_o_id)
    return


async def place_order(TD, ws, cl_o_id: int, market: str, side: str, o_type: str, size: float, tif: str, price: float, tag=10):
    purpose = 'placeorder'
    TD.logger.info(f'placing {market} {side} order at {price} with size {size}')
    await ws.send(
        json.dumps(
            {
                'op': 'placeorder',
                'data': {
                    'clientOrderId': cl_o_id,
                    'marketCode': market,
                    'side': side,
                    'orderType': o_type,
                    'quantity': size,
                    'timeInForce': tif,
                    'price': price,
                },
                'tag': tag,
            }
        )
    )
    await order_management(TD, ws, purpose, market, cl_o_id)
    return


async def cancel_order(TD, ws, o_id: str, market: str):
    purpose = 'cancelorder'
    TD.logger.info(f'cancelling {market} order {o_id}')
    await ws.send(
        json.dumps(
            {'op': 'cancelorder', 'data': {'marketCode': market, 'orderId': o_id}}
        )
    )
    await order_management(TD, ws, purpose, market)
    return


async def order_management(TD, ws, purpose: str, market: str, cl_o_id: int = 9999):
    can_exit = False
    while ws.open and not can_exit:
        try:
            # Await a websocket message from CoinFLEX.
            response = await ws.recv()
            msg = json.loads(response)
            # TD.logger.info(f'MGMT {msg}')

            # Parse new orderbook data and check for an order_matched message.
            if 'data' in msg and 'submitted' not in msg:
                if isinstance(msg["data"], dict):
                    continue
                match = await parse_message(TD, msg)
                if match:
                    TD.logger.info(f'{match} {msg}')
                    if (
                            purpose in ('placeorder', 'modifyorder')
                            and cl_o_id == msg['data'][0]['clientOrderId']
                            and market == msg['data'][0]['marketCode']
                    ):
                        can_exit = True
                        continue

            # Register new order Ids, prices, and order sizes.
            if 'data' in msg and 'table' in msg:
                if msg['table'] == 'order':
                    data = msg['data'][0]
                    TD.logger.info(f'MGMT {data}')
                    cl_o_id = data['clientOrderId']
                    market_code = data['marketCode']
                    size = float(data['quantity'])
                    price = float(data['price'])
                    o_id = data['orderId']
                    if (
                        'clientOrderId' in data
                        and data['status'] == 'OPEN'
                        and (
                            data['notice'] == 'OrderOpened'
                            or data['notice'] == 'OrderModified'
                        )
                    ):
                        # Update bid information.
                        if cl_o_id in TD.bids[market_code]:
                            TD.bids[market_code][cl_o_id] = [True, size, price, o_id]
                            if purpose in ('placeorder', 'modifyorder'):
                                can_exit = True
                            continue

                        # Update ask information.
                        if cl_o_id in TD.asks[market_code]:
                            TD.asks[market_code][cl_o_id] = [True, size, price, o_id]
                            if purpose in ('placeorder', 'modifyorder'):
                                can_exit = True
                            continue

                    # Remove cancelled orders from the internal order tracking system.
                    if (
                        data['notice'] == 'OrderClosed'
                        and data['status'] == 'CANCELED_BY_USER'
                    ):
                        if cl_o_id in TD.bids[market_code]:
                            TD.bids[market_code][cl_o_id] = [False, 0, 0, 0]
                            if purpose == 'cancelorder':
                                can_exit = True
                            continue

                        if cl_o_id in TD.asks[market_code]:
                            TD.asks[market_code][cl_o_id] = [False, 0, 0, 0]
                            if purpose == 'cancelorder':
                                can_exit = True
                            continue

                    if data['status'] == 'REJECT_AMEND_ORDER_ID_NOT_FOUND':
                        TD.logger.info(f'AMENDMENT REJECTED {data}')
                        if purpose == 'modifyorder':
                            can_exit = True
                        continue

            if 'table' not in msg:
                if 'submitted' in msg:
                    TD.logger.info(f'{msg}')
                    if msg['submitted'] is False:
                        if msg['event'] == 'cancelorder' or msg['event'] == 'CANCEL':
                            # The order was filled before the cancel went through.
                            if purpose == 'cancelorder':
                                can_exit = True
                            continue
                        if purpose in ('placeorder', 'modifyorder'):
                            can_exit = True

                if 'success' in msg:
                    TD.logger.info(f'{msg}')
                    if purpose in ('placeorder', 'modifyorder'):
                        can_exit = True
                    TD.logger.info(f"error: {msg['event']} submission failed")

        except Exception:
            TD.logger.exception('error occurred during order management')
    return


async def order_matched(TD, msg):
    TD.logger.info(f'{msg}')
    market_code = msg['marketCode']
    remaining = float(msg['remainQuantity'])
    price = float(msg['price'])
    cl_o_id = msg['clientOrderId']
    o_id = msg['orderId']

    # If the match was a partial fill update the order tracking and position information.
    if remaining > 0:
        if msg['side'] == 'BUY':
            TD.bids[market_code][cl_o_id] = [True, remaining, price, o_id]
        else:
            TD.asks[market_code][cl_o_id] = [True, remaining, price, o_id]

    # If the match was a fill then reset the order tracking entirely and update position information.
    if remaining == 0:
        if msg['side'] == 'BUY':
            TD.bids[market_code][cl_o_id] = [False, 0, 0, 0]
        else:
            TD.asks[market_code][cl_o_id] = [False, 0, 0, 0]
    return


async def parse_message(TD, msg):
    data = msg['data']
    if data:
        data = data[0]
        # Process OrderMatched messages to keep track of position and order fills.
        if 'notice' in data:
            if data['notice'] == 'OrderMatched' and 'matchQuantity' in data:
                TD.logger.info(f'{data}')
                await order_matched(TD, data)
                return True
    return False

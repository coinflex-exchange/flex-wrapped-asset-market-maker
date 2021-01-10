from datetime import datetime


def is_time_between(begin_time, end_time, check_time=None):
    # If check time is not given, default to current UTC time
    check_time = check_time or datetime.utcnow().time()
    if begin_time < end_time:
        return begin_time <= check_time <= end_time
    else:   # crosses midnight
        return check_time >= begin_time or check_time <= end_time


def change_market(code: str, market: str):
    split = code.split('-')
    return f'{split[0]}-{split[1]}-{market}-LIN'


def market_to_coin(code: str):
    split = code.split('-')
    return f'{split[0]}'

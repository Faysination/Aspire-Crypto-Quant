import traceback
import ccxt

def test():
    try:
        ex = ccxt.binanceusdm({'options': {'defaultType': 'future'}})
        ex.load_markets()
        print("Tiers for FIS/USDT:")
        print(ex.fetch_leverage_tiers(['FIS/USDT:USDT']))
    except Exception as e:
        print(traceback.format_exc())

test()

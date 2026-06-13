import traceback
import ccxt

def test():
    try:
        ex = ccxt.binanceusdm({'options': {'defaultType': 'future'}})
        ex.load_markets()
        print("Market for FIS/USDT:")
        print(ex.market('FIS/USDT'))
    except Exception as e:
        print(traceback.format_exc())

test()

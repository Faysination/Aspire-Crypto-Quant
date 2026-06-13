import traceback
import ccxt

def test():
    ex = ccxt.binanceusdm({'options': {'defaultType': 'future', 'fetchCurrencies': False}})
    ex.urls['api']['fapiPublic'] = 'https://demo-fapi.binance.com/fapi/v1'
    try:
        markets = ex.fetch_tickers()
        usdt_pairs = [v for k, v in markets.items() if k.endswith('/USDT') and 'quoteVolume' in v and v['quoteVolume']]
        usdt_pairs.sort(key=lambda x: float(x.get('quoteVolume', 0)), reverse=True)
        print([p['symbol'] for p in usdt_pairs[:10]])
    except Exception as e:
        print(traceback.format_exc())

test()

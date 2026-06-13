import os
from dotenv import load_dotenv
load_dotenv(".env")
import ccxt

key = os.environ.get("BINANCE_API_KEY", "").strip()
sec = os.environ.get("BINANCE_API_SECRET", "").strip()

print("Testing Binance Demo Trading URLs...")
ex = ccxt.binance({
    "apiKey": key, "secret": sec,
    "urls": {
        "api": {
            "public": "https://demo-api.binance.com/api/v3",
            "private": "https://demo-api.binance.com/api/v3",
            "v1": "https://demo-api.binance.com/api/v1",
            "v3": "https://demo-api.binance.com/api/v3",
        }
    }
})

try:
    bal = ex.fetch_balance()
    print("SPOT SUCCESS! USDT:", bal.get('USDT', {}).get('total', 0))
except Exception as e:
    print("SPOT FAILED:", str(e))

ex_fut = ccxt.binanceusdm({
    "apiKey": key, "secret": sec,
    "urls": {
        "api": {
            "fapiPublic": "https://demo-fapi.binance.com/fapi/v1",
            "fapiPrivate": "https://demo-fapi.binance.com/fapi/v1",
            "fapiPrivateV2": "https://demo-fapi.binance.com/fapi/v2",
            "fapiPrivateV3": "https://demo-fapi.binance.com/fapi/v3",
        }
    }
})

try:
    bal2 = ex_fut.fetch_balance()
    print("FUTURES SUCCESS! USDT:", bal2.get('USDT', {}).get('total', 0))
except Exception as e:
    print("FUTURES FAILED:", str(e))

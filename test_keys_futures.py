import os
from dotenv import load_dotenv
load_dotenv(".env")
import ccxt

key = os.environ.get("BINANCE_API_KEY", "").strip()
sec = os.environ.get("BINANCE_API_SECRET", "").strip()

print("Testing Binance Futures...")
try:
    ex = ccxt.binance({"apiKey": key, "secret": sec, "options": {"defaultType": "future"}})
    ex.fetch_balance()
    print("SUCCESS on Futures!")
except Exception as e:
    print("Failed:", str(e))

import os
from dotenv import load_dotenv
load_dotenv(".env")
import ccxt

key = os.environ.get("BINANCE_API_KEY", "").strip()
sec = os.environ.get("BINANCE_API_SECRET", "").strip()

print("Using Key:", key[:5] + "..." + key[-5:])

print("\nTesting Binance Global...")
try:
    ex = ccxt.binance({"apiKey": key, "secret": sec})
    ex.fetch_balance()
    print("SUCCESS on Global!")
except Exception as e:
    print("Failed:", str(e))

print("\nTesting Binance US...")
try:
    ex = ccxt.binanceus({"apiKey": key, "secret": sec})
    ex.fetch_balance()
    print("SUCCESS on US!")
except Exception as e:
    print("Failed:", str(e))

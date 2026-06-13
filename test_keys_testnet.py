import os
from dotenv import load_dotenv
load_dotenv(".env")
import ccxt

key = os.environ.get("BINANCE_API_KEY", "").strip()
sec = os.environ.get("BINANCE_API_SECRET", "").strip()

print("Testing Binance Testnet...")
try:
    ex = ccxt.binance({"apiKey": key, "secret": sec})
    ex.set_sandbox_mode(True)
    ex.fetch_balance()
    print("SUCCESS on Testnet!")
except Exception as e:
    print("Failed:", str(e))

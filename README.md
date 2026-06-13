# Aspire Crypto Quant 🚀

**Aspire Crypto Quant** is a fully automated, intelligent algorithmic trading bot designed to trade cryptocurrencies on Binance (Spot & Futures). Powered by advanced regime-detection algorithms, the bot dynamically adapts its trading strategy based on current market conditions, ensuring robust performance across bull, bear, and sideways markets.

It also features a sleek, beautiful, full-width local dashboard to give you real-time insights into your portfolio balances, active trades, market regimes, and system health.

---

## 🌟 Key Features

* **Regime-Adaptive Engine:** The core algorithm analyzes volatility, trend strength, and momentum to determine the current "market regime" (e.g., Trending Bullish, Choppy Bearish) and adjusts risk management and trade frequency accordingly.
* **Dual Market Support:** Trade on both Binance Spot and Binance USDⓈ-M Futures accounts simultaneously.
* **Automated Execution:** Fully autonomous order placement, trailing stops, and take-profit handling.
* **Modern Dashboard:** A stunning `Node.js` + `Vite` frontend combined with a native `Flask` backend server to monitor your live assets without logging into Binance.
* **Local & Secure:** All API keys are loaded locally from your `.env` file. Your keys never leave your machine!

---

## 🛠️ Tech Stack

* **Backend:** Python 3.11, Flask, CCXT (for Binance API integration), SQLite
* **Frontend:** HTML5, CSS3, Vanilla JavaScript, Vite
* **Architecture:** Asynchronous quantitative trading loop decoupled from a REST API dashboard server.

---

## 🚀 Quick Setup & Installation

### 1. Prerequisites
- **Python 3.11+** installed on your system.
- **Node.js** (optional, only if you want to modify the frontend build).
- A Binance account with API Keys (Spot and/or Futures enabled).

### 2. Clone the Repository
```bash
git clone https://github.com/Faysination/Aspire-Crypto-Quant.git
cd Aspire-Crypto-Quant
```

### 3. Environment Variables
Create a `.env` file in the root directory (you can use `.env.template` as a starting point) and add your Binance API keys:
```ini
BINANCE_API_KEY=your_api_key_here
BINANCE_API_SECRET=your_api_secret_here
```

### 4. Install Dependencies
```bash
python -m venv venv
venv\Scripts\activate  # On Windows
pip install -r requirements.txt
```

### 5. Launch the Bot & Dashboard
For Windows users, simply run the included batch script:
```cmd
start.bat
```
This will automatically launch both the background Python trading engine and the local Flask API.

### 6. View Your Dashboard
Open your favorite web browser and navigate to:
**`http://127.0.0.1:5001`**

---

## 📂 Project Structure

* `regime_engine.py` - Core mathematical logic for market regime detection.
* `binance_executor.py` - Order execution engine utilizing the CCXT library.
* `dashboard_api.py` - Flask backend that serves data to the frontend UI.
* `trade_db.py` - SQLite database wrapper for logging trades and performance.
* `frontend/` - Contains the HTML, CSS, and JS for the modern full-width dashboard.

---

## 🤝 Acknowledgements & Credits

This project builds heavily upon the incredible quantitative research and regime-adaptive trading logic originally developed by **Aditya26189**. 

- **Original Repository:** [Aditya26189/regime-adaptive-quantitative-trading](https://github.com/Aditya26189/regime-adaptive-quantitative-trading)

Huge thanks to the original author for laying down the foundation for the regime-detection engine.

---

## ⚠️ Disclaimer

**Trading cryptocurrencies involves significant risk.** This software is provided for educational and experimental purposes only. Do not use money you cannot afford to lose. The developers are not responsible for any financial losses incurred while using this automated bot. Always test on a Testnet account before deploying real capital!

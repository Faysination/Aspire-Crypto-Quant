@echo off
echo ==============================================
echo Binance Crypto Auto Bot Setup and Start Script
echo ==============================================

IF NOT EXIST "venv" (
    echo [INFO] Creating Python virtual environment...
    python -m venv venv
)

echo [INFO] Activating virtual environment...
call venv\Scripts\activate.bat

echo [INFO] Installing required packages...
pip install -r requirements.txt

echo [INFO] Starting Dashboard and Bot Engine...
echo [INFO] The dashboard will open in your default browser.
start "" http://127.0.0.1:5001
python dashboard_api.py

pause

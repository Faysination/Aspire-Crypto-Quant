@echo off
title Zoya Bot Backend
echo ==============================================
echo   Starting Zoya Regime Bot Backend API...
echo ==============================================
echo.
call venv\Scripts\activate.bat
python dashboard_api.py
pause

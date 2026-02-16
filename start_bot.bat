@echo off
title Inventory Bot

echo ==============================
echo Starting Inventory Bot...
echo ==============================

set BOT_TOKEN=8586042678:AAE_ALlsezHXwdeqgCcHvFE4Dr-39b1yX-A
set BASE_WEB_URL=http://localhost:8000

echo.
echo BOT_TOKEN set
echo BASE_WEB_URL set
echo.

python main.py

echo.
echo Bot stopped.
pause

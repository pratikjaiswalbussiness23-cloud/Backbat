@echo off
title Liquidity Identifier Server
echo ============================================
echo Liquidity Identifier - Signal Generator
echo ============================================
echo.
echo Starting server on http://localhost:5002...
echo.
cd /d %%~dp0
python liq_app.py
pause

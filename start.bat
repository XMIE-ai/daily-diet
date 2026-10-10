@echo off
rem Double-click this file to start the app.
rem It works no matter which folder you put it in.
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   Starting the diet app...
echo   Keep this window open while using the app.
echo   Press Ctrl+C here to stop it.
echo ============================================
echo.

python -m streamlit run app.py

echo.
echo The app has stopped.
pause

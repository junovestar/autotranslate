@echo off
chcp 65001 >nul
title Auto Translate Video

echo.
echo 🎬 Auto Translate Video
echo ======================
echo.

:: Cài đặt dependencies
echo 📦 Installing dependencies...
pip install -r web_requirements.txt --quiet

:: Chạy ứng dụng
echo.
echo 🚀 Starting application...
echo 📱 Open browser: http://localhost:5000
echo ⏹️  Press Ctrl+C to stop
echo.

python web_app.py

pause


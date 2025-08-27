@echo off
chcp 65001 >nul
title Auto Translate Video

echo.
echo 🎬 Auto Translate Video - Web App
echo ========================================
echo.

:: Kiểm tra Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ LỖI: Python chưa được cài đặt
    echo Vui lòng cài đặt Python từ https://python.org
    pause
    exit /b 1
)

:: Cài đặt dependencies
echo 📦 Cài đặt dependencies...
pip install -r web_requirements.txt --quiet

:: Khởi động server
echo.
echo 🚀 Khởi động web server...
echo 📱 Mở trình duyệt: http://localhost:5000
echo ⏹️  Nhấn Ctrl+C để dừng
echo.

python web_app.py

pause


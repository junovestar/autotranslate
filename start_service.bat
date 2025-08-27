@echo off
echo ========================================
echo   Auto Translate Video Service
echo ========================================
echo.

REM Kiểm tra Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python không được tìm thấy!
    echo    Vui lòng cài đặt Python từ https://python.org
    pause
    exit /b 1
)

REM Kiểm tra dependencies
echo 🔍 Checking dependencies...
python -c "import flask, requests, pydub" >nul 2>&1
if errorlevel 1 (
    echo ⚠️ Một số dependencies bị thiếu. Đang cài đặt...
    pip install flask flask-cors requests pydub
)

REM Tạo thư mục projects nếu chưa có
if not exist "projects" mkdir projects

REM Chạy service
echo.
echo 🚀 Starting Auto Translate Video Service...
echo    Web UI sẽ tự động mở tại: http://localhost:5000
echo    Nhấn Ctrl+C để dừng service
echo.

python service_runner.py start

pause

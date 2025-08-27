@echo off
echo ========================================
echo   Stop Auto Translate Video Service
echo ========================================
echo.

echo 🛑 Stopping service...

REM Kill Python processes running web_app or service_runner
taskkill /f /im python.exe /fi "WINDOWTITLE eq Auto Translate Video*" >nul 2>&1
taskkill /f /im python.exe /fi "MODULES eq web_app.py" >nul 2>&1
taskkill /f /im python.exe /fi "MODULES eq service_runner.py" >nul 2>&1

REM More targeted kill for our specific processes
for /f "tokens=2" %%i in ('tasklist /fi "imagename eq python.exe" /fo table /nh ^| findstr "5000"') do (
    taskkill /f /pid %%i >nul 2>&1
)

echo ✅ Service stopped
echo.
pause

@echo off
REM Opens the backend and frontend in two windows, then the dashboard.
cd /d "%~dp0"

if not exist "backend\.venv" (
    echo  Not set up yet. Run setup.bat first.
    pause
    exit /b 1
)

start "NSE Scanner - backend" cmd /k "cd /d "%~dp0backend" && call .venv\Scripts\activate.bat && python -m uvicorn app.main:app --reload --port 8000"
start "NSE Scanner - frontend" cmd /k "cd /d "%~dp0frontend" && npm run dev"

echo.
echo  Starting up. Two windows will open - leave both running.
echo  Opening http://localhost:5173 in a moment...
timeout /t 6 /nobreak >nul
start http://localhost:5173
echo.
echo  To stop the dashboard, close the two windows that opened.

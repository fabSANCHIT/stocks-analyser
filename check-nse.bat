@echo off
REM Run this FIRST. Confirms NSE will actually talk to your computer.
cd /d "%~dp0backend"
if not exist ".venv" (
    echo  Run setup.bat first.
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat
python -m tools.check_nse
echo.
pause

@echo off
REM Downloads any NSE sessions you are missing, without opening the dashboard.
REM Useful the first time, or to warm things up before the market opens.
cd /d "%~dp0backend"
call .venv\Scripts\activate.bat
python -m tools.refresh --days 200
pause

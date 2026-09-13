@echo off
REM Builds data\snapshot.json.gz for hosting. Only needed if you deploy.
cd /d "%~dp0backend"
call .venv\Scripts\activate.bat
python -m tools.build_snapshot --days 300 --max-stocks 150
pause

@echo off
REM Saves the index membership list for the hosted deployment to fall back on.
cd /d "%~dp0backend"
call .venv\Scripts\activate.bat
python -m tools.build_universe
pause

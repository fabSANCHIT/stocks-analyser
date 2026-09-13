@echo off
REM Run this ONCE. It installs everything the dashboard needs.
cd /d "%~dp0"

echo.
echo  [1/2] Setting up the Python backend...
echo.
cd backend
if not exist .venv (
    py -m venv .venv
    if errorlevel 1 (
        echo.
        echo  Could not create the virtual environment.
        echo  Install Python from python.org and tick "Add Python to PATH".
        pause
        exit /b 1
    )
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt
if errorlevel 1 ( echo  Installing Python packages failed. & pause & exit /b 1 )
cd ..

echo.
echo  [2/2] Setting up the React frontend...
echo.
cd frontend
call npm install
if errorlevel 1 (
    echo.
    echo  npm failed. Install Node.js from nodejs.org, then run this again.
    pause
    exit /b 1
)
cd ..

echo.
echo  Done. Now double-click start.bat to launch the dashboard.
echo.
pause

@echo off
REM One-command launcher: bootstrap venv, install deps, build the UI, run the app.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [DriveSpeedTest] Creating virtual environment...
  python -m venv .venv || goto :err
)

echo [DriveSpeedTest] Installing Python dependencies...
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt || goto :err

if not exist "frontend\dist\index.html" (
  echo [DriveSpeedTest] Building the React frontend...
  pushd frontend
  call npm install || (popd & goto :err)
  call npm run build || (popd & goto :err)
  popd
)

echo [DriveSpeedTest] Starting...
".venv\Scripts\python.exe" run.py %*
goto :eof

:err
echo [DriveSpeedTest] Setup failed. Ensure Python 3.9+ and Node.js are installed and on PATH.
exit /b 1

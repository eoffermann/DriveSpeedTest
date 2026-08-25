@echo off
REM Build a single-file DriveSpeedTest.exe (output: dist\DriveSpeedTest.exe).
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [build] Creating virtual environment...
  python -m venv .venv || goto :err
)

echo [build] Installing Python dependencies + PyInstaller...
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt pyinstaller || goto :err

echo [build] Building the React frontend...
pushd frontend
call npm install || (popd & goto :err)
call npm run build || (popd & goto :err)
popd

echo [build] Packaging single-file executable...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean DriveSpeedTest.spec || goto :err

echo.
echo [build] Done -^> dist\DriveSpeedTest.exe
goto :eof

:err
echo [build] Build failed. Ensure Python 3.9+ and Node.js are installed and on PATH.
exit /b 1

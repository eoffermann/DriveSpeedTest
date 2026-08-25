@echo off
REM One-command launcher: self-elevate for SMART, then bootstrap the venv, install
REM deps, build the UI, and run the app.
setlocal
cd /d "%~dp0"

REM --- Relaunch as administrator unless already elevated -----------------------
REM Full SMART health (temperature, wear, error counts) is admin-gated on many
REM drives. If not elevated, request it via UAC. If the user declines, carry on
REM without admin -- everything except SMART still works.
net session >nul 2>&1
if %errorlevel% equ 0 goto :elevated

echo [DriveSpeedTest] Requesting administrator privileges (for full SMART health)...
if "%~1"=="" (
  powershell -NoProfile -Command "try { Start-Process -FilePath '%~f0' -Verb RunAs -WorkingDirectory '%~dp0' -ErrorAction Stop } catch { exit 1 }"
) else (
  powershell -NoProfile -Command "try { Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs -WorkingDirectory '%~dp0' -ErrorAction Stop } catch { exit 1 }"
)
if errorlevel 1 (
  echo [DriveSpeedTest] Elevation declined - continuing without administrator rights.
  echo                  SMART health may be limited; everything else works normally.
  goto :elevated
)
REM Elevation succeeded and launched a new window; close this one.
exit /b

:elevated
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

@echo off
setlocal
cd /d "%~dp0"
echo Texas Hold'em Vision Analyzer - Windows launcher
py -3.12 --version >nul 2>&1
if errorlevel 1 (
  echo Python 3.12 is required. Install the 64-bit version from python.org.
  echo Enable the Python launcher during installation, then try again.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  py -3.12 -m venv .venv
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m src.main
if errorlevel 1 goto failed
exit /b 0
:failed
echo.
echo Startup failed. Read the error above and docs\START_HERE_KO.md.
pause
exit /b 1

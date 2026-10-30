@echo off
setlocal
cd /d "%~dp0"
echo Texas Hold'em Vision Analyzer - Windows launcher
if exist ".venv\Scripts\python.exe" goto check_environment
py -3.12 --version >nul 2>&1
if not errorlevel 1 (
  py -3.12 -m venv .venv
  if errorlevel 1 goto failed
  goto check_environment
)
python -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>&1
if not errorlevel 1 (
  python -m venv .venv
  if errorlevel 1 goto failed
  goto check_environment
)
echo.
echo This version of the app requires Python 3.12, 64-bit.
echo Its pinned GUI packages do not support Python 3.14.
echo Keep Python 3.14 installed. Install Python 3.12 alongside it.
echo Official Python 3.12.10 Windows installer:
echo https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe
echo Enable the Python launcher, then run this file again.
pause
exit /b 1
:check_environment
".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>&1
if errorlevel 1 (
  echo The existing .venv folder does not use Python 3.12.
  echo Close the app and rename .venv to .venv-old, then run this file again.
  echo Install Python 3.12 first if it is not already installed.
  pause
  exit /b 1
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

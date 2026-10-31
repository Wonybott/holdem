@echo off
setlocal
cd /d "%~dp0"
echo Hold'em Vision - local AI model setup
set "HOLDEM_OLLAMA=ollama"
where ollama >nul 2>&1
if not errorlevel 1 goto download_model
if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" (
  set "HOLDEM_OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
  goto download_model
)
echo Install Ollama for Windows first: https://ollama.com/download/windows
echo Open Ollama, then run this file again. No API key is needed.
pause
exit /b 1
:download_model
echo Downloading qwen2.5vl:7b. This requires Internet and several GB of disk space.
echo Subsequent image recognition runs on this PC through 127.0.0.1 only.
"%HOLDEM_OLLAMA%" pull qwen2.5vl:7b
if errorlevel 1 goto failed
echo Model ready. Run run_windows.bat, then choose Local AI / Ollama.
pause
exit /b 0
:failed
echo Setup failed. Open the Ollama application and check disk space / Internet.
echo If port 11434 is busy, do not start a second Ollama server.
echo Read docs\LOCAL_AI_KO.md for details.
pause
exit /b 1

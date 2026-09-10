@echo off
REM Stop the background ScreenPulse watcher started by run_background.vbs.
cd /d "%~dp0"
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
"%PY%" -m screenpulse stop
timeout /t 2 /nobreak >nul

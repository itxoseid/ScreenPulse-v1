@echo off
REM Headless ScreenPulse watcher. Launched hidden by run_background.vbs.
cd /d "%~dp0"

set "PYW=pythonw"
if exist ".venv\Scripts\pythonw.exe" set "PYW=.venv\Scripts\pythonw.exe"

REM Start Ollama if it isn't already running.
tasklist /fi "imagename eq ollama.exe" | find /i "ollama.exe" >nul
if errorlevel 1 (
    start "" /b ollama serve
    timeout /t 4 /nobreak >nul
)

set "LOG=%LOCALAPPDATA%\ScreenPulse\watch.log"
echo. >> "%LOG%"
echo ==== started %DATE% %TIME% ==== >> "%LOG%"
"%PYW%" -m screenpulse watch --no-tui >> "%LOG%" 2>&1

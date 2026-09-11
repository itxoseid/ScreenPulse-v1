@echo off
REM Double-click to start ScreenPulse watching in the background - no window
REM stays open. Stop it yourself (Task Manager -> pythonw.exe, or
REM `python -m screenpulse stop`) when you're done.

REM Resolve the project dir from this script's own location so it works anywhere.
set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
cd /d "%PROJECT_DIR%"

set "PYW=pythonw"
if exist "%PROJECT_DIR%\.venv\Scripts\pythonw.exe" set "PYW=%PROJECT_DIR%\.venv\Scripts\pythonw.exe"

REM Start Ollama only if nothing is actually answering on its port yet.
REM (A process-name check here is racy - if it misses a starting-up Ollama
REM you get a second server fighting the first for the GPU and the port.)
curl.exe -s -o nul -m 2 http://localhost:11434/api/tags
if errorlevel 1 (
    start "" /b ollama serve
    timeout /t 4 /nobreak >nul
)

set "LOG=%LOCALAPPDATA%\ScreenPulse\watch.log"
if not exist "%LOCALAPPDATA%\ScreenPulse" mkdir "%LOCALAPPDATA%\ScreenPulse"
echo. >> "%LOG%"
echo ==== started %DATE% %TIME% ==== >> "%LOG%"

REM /b: no new window (pythonw has none anyway); output goes to the log file.
start "" /b "%PYW%" -m screenpulse tray >> "%LOG%" 2>&1

REM Close this window immediately - the watcher keeps running detached.
exit

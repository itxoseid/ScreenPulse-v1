@echo off
REM ScreenPulse launcher - double-click to start the live watch pipeline + TUI.
title ScreenPulse

REM Resolve the project dir from this script's own location so it works anywhere.
set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
cd /d "%PROJECT_DIR%"

REM Prefer a local virtualenv if one exists, otherwise use the system Python.
if exist "%PROJECT_DIR%\.venv\Scripts\python.exe" (
    set "PY=%PROJECT_DIR%\.venv\Scripts\python.exe"
) else (
    set "PY=python"
)

REM Make sure Ollama is running (the watch pipeline needs it).
tasklist /fi "imagename eq ollama.exe" | find /i "ollama.exe" >nul
if errorlevel 1 (
    echo Starting Ollama...
    start "" /b ollama serve
    timeout /t 3 /nobreak >nul
)

echo Starting ScreenPulse watch...  ^(press q to quit^)
echo.
"%PY%" -m screenpulse watch

echo.
echo ScreenPulse exited.
pause

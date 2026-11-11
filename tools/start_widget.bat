@echo off
REM Skip if the widget (Electron tray app) is already running.
tasklist /FI "IMAGENAME eq electron.exe" 2>nul | find /I "electron.exe" >nul
if not errorlevel 1 (
    echo Desktop widget already running, skipping.
    exit /b 0
)
cd /d "%~dp0..\desktop"
npm start

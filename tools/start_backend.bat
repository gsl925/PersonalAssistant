@echo off
REM Skip if the backend is already listening on :8000 (a second copy can't bind it).
netstat -ano | findstr /R /C:":8000 .*LISTENING" >nul
if not errorlevel 1 (
    echo Backend already running on :8000, skipping.
    exit /b 0
)
cd /d "%~dp0.."
venv\Scripts\python.exe start.py

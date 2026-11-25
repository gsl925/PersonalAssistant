@echo off
REM Starts everything that does NOT auto-start on boot:
REM   - Qdrant (vector DB)
REM   - llama-swap (local LLM server; only if tools\llama\bin was downloaded)
REM   - Personal AI Assistant backend (FastAPI + Telegram bot + APScheduler + Dashboard)
REM   - Dashboard, opened in the default browser (served by the backend at /dashboard)
REM   - Desktop widget (Electron tray app: Ctrl+Shift+S screenshot, Ctrl+Shift+N note)
REM PostgreSQL runs as an auto-start Windows service, and Ollama auto-starts at login —
REM neither needs to be launched here.

cd /d "%~dp0"

REM Every server is checked first and only started if it isn't already running
REM (the tools\*.bat scripts repeat the check, so they are also safe to run alone).
netstat -ano | findstr /R /C:":6333 .*LISTENING" >nul
if errorlevel 1 (
    echo Starting Qdrant...
    start "Qdrant" cmd /k "tools\qdrant\start_qdrant.bat"
    echo Waiting for Qdrant to come up...
    timeout /t 5 /nobreak >nul
) else (
    echo Qdrant already running on :6333, skipping.
)

if not exist "tools\llama\bin\llama-swap\llama-swap.exe" goto :after_llama
set "LLAMA_PORT=%LLAMA_SWAP_PORT%"
if not defined LLAMA_PORT set "LLAMA_PORT=8090"
netstat -ano | findstr /R /C:":%LLAMA_PORT% .*LISTENING" >nul
if errorlevel 1 (
    echo Starting llama-swap ^(local LLM server on :%LLAMA_PORT%^)...
    start "llama-swap" cmd /k "%~dp0tools\llama\start_llama.bat"
) else (
    echo llama-swap already running on :%LLAMA_PORT%, skipping.
)
:after_llama

netstat -ano | findstr /R /C:":8000 .*LISTENING" >nul
if errorlevel 1 (
    echo Starting Personal AI Assistant ^(FastAPI + Telegram bot^)...
    start "Personal AI Assistant" cmd /k "%~dp0tools\start_backend.bat"
) else (
    echo Backend already running on :8000, skipping.
)

echo Waiting for the backend to come up...
powershell -NoProfile -Command "for ($i = 0; $i -lt 60; $i++) { if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) { break }; Start-Sleep -Seconds 1 }"

echo Opening Dashboard in the default browser...
start "" "http://localhost:8000/dashboard/"

tasklist /FI "IMAGENAME eq electron.exe" 2>nul | find /I "electron.exe" >nul
if errorlevel 1 (
    echo Starting Desktop Widget ^(tray app^)...
    start "Desktop Widget" cmd /k "%~dp0tools\start_widget.bat"
) else (
    echo Desktop widget already running, skipping.
)

echo.
echo All services launched in separate windows:
echo   - Qdrant            (http://localhost:6333)
echo   - llama-swap         (http://localhost:8090, if installed)
echo   - Personal Assistant (http://localhost:8000/api/docs)
echo   - Dashboard          (http://localhost:8000/dashboard/) - opened in browser
echo   - Desktop Widget     (system tray icon; Ctrl+Shift+S screenshot, Ctrl+Shift+N note)
echo Close the Qdrant/Personal Assistant/Desktop Widget windows to stop those services.

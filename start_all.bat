@echo off
REM Starts everything that does NOT auto-start on boot:
REM   - Qdrant (vector DB)
REM   - Personal AI Assistant backend (FastAPI + Telegram bot + APScheduler + Dashboard)
REM   - Dashboard, opened in the default browser (served by the backend at /dashboard)
REM   - Desktop widget (Electron tray app: Ctrl+Shift+S screenshot, Ctrl+Shift+N note)
REM PostgreSQL runs as an auto-start Windows service, and Ollama auto-starts at login —
REM neither needs to be launched here.

cd /d "%~dp0"

echo Starting Qdrant...
start "Qdrant" cmd /k "tools\qdrant\start_qdrant.bat"

echo Waiting for Qdrant to come up...
timeout /t 5 /nobreak >nul

echo Starting Personal AI Assistant (FastAPI + Telegram bot)...
start "Personal AI Assistant" cmd /k "%~dp0tools\start_backend.bat"

echo Waiting for the backend to come up...
powershell -NoProfile -Command "for ($i = 0; $i -lt 60; $i++) { if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) { break }; Start-Sleep -Seconds 1 }"

echo Opening Dashboard in the default browser...
start "" "http://localhost:8000/dashboard/"

echo Starting Desktop Widget (tray app)...
start "Desktop Widget" cmd /k "%~dp0tools\start_widget.bat"

echo.
echo All services launched in separate windows:
echo   - Qdrant            (http://localhost:6333)
echo   - Personal Assistant (http://localhost:8000/api/docs)
echo   - Dashboard          (http://localhost:8000/dashboard/) - opened in browser
echo   - Desktop Widget     (system tray icon; Ctrl+Shift+S screenshot, Ctrl+Shift+N note)
echo Close the Qdrant/Personal Assistant/Desktop Widget windows to stop those services.

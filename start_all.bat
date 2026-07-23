@echo off
REM Starts everything that does NOT auto-start on boot:
REM   - Qdrant (vector DB)
REM   - Personal AI Assistant backend (FastAPI + Telegram bot + APScheduler)
REM PostgreSQL runs as an auto-start Windows service, and Ollama auto-starts at login —
REM neither needs to be launched here.

cd /d "%~dp0"

echo Starting Qdrant...
start "Qdrant" cmd /k "tools\qdrant\start_qdrant.bat"

echo Waiting for Qdrant to come up...
timeout /t 5 /nobreak >nul

echo Starting Personal AI Assistant (FastAPI + Telegram bot)...
start "Personal AI Assistant" cmd /k ""%~dp0venv\Scripts\python.exe" "%~dp0start.py""

echo.
echo Both services launched in separate windows:
echo   - Qdrant            (http://localhost:6333)
echo   - Personal Assistant (http://localhost:8000/api/docs)
echo Close those windows to stop the services.

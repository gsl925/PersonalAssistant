@echo off
REM llama-swap on http://127.0.0.1:8090 - starts/stops llama-server per requested model.
REM The backend uses this server by default (LOCAL_LLM_ENGINE=llama in .env); LOCAL_LLM_ENGINE=ollama switches it to Ollama.
REM Run from the repo root: llama-swap.yaml uses paths relative to it.
cd /d "%~dp0..\.."

REM Model folder: LLM_MODELS_DIR from the environment, else from .env, else data\llm_models here.
if not defined LLM_MODELS_DIR if exist ".env" (
    for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
        if /i "%%a"=="LLM_MODELS_DIR" if not "%%b"=="" set "LLM_MODELS_DIR=%%b"
    )
)
if not defined LLM_MODELS_DIR set "LLM_MODELS_DIR=%CD%\data\llm_models"

if not exist "tools\llama\bin\llama-swap\llama-swap.exe" (
    echo llama-swap not found. Run: powershell -ExecutionPolicy Bypass -File tools\llama\download_binaries.ps1
    exit /b 1
)
if not exist "%LLM_MODELS_DIR%" (
    echo Model folder not found: %LLM_MODELS_DIR%
    echo Run tools\llama\download_models.ps1 or fix LLM_MODELS_DIR.
    exit /b 1
)
echo Models: %LLM_MODELS_DIR%

REM Port: LLAMA_SWAP_PORT from the environment, default 8090 (what LLAMA_SWAP_BASE_URL expects).
if not defined LLAMA_SWAP_PORT set "LLAMA_SWAP_PORT=8090"
REM Skip if something already listens there: the one shared llama-swap serves every project.
netstat -ano | findstr /R /C:":%LLAMA_SWAP_PORT% .*LISTENING" >nul
if not errorlevel 1 (
    echo llama-swap already running on :%LLAMA_SWAP_PORT%, skipping.
    exit /b 0
)
"tools\llama\bin\llama-swap\llama-swap.exe" -config "tools\llama\llama-swap.yaml" -listen 127.0.0.1:%LLAMA_SWAP_PORT%

@echo off
title SWARM-100 Launcher
color 0A
echo.
echo  ============================================================
echo   SWARM-100 Autonomous AI Workforce - Launcher
echo  ============================================================
echo.
cd /d "C:\Users\srinivas\OneDrive\Desktop\SWARM 100"

echo [1/3] Checking Ollama...
ollama list >nul 2>&1
if %errorlevel% neq 0 (
    echo  WARNING: Ollama not responding. Starting ollama serve in background...
    start "" /B ollama serve
    timeout /t 3 /nobreak >nul
) else (
    echo  OK: Ollama is running.
)

echo [2/3] Verifying qwen3:4b model...
ollama list | findstr "qwen3:4b" >nul 2>&1
if %errorlevel% neq 0 (
    echo  WARNING: qwen3:4b not found. You may need to run: ollama pull qwen3:4b
) else (
    echo  OK: qwen3:4b model is available.
)

echo [3/3] Starting SWARM-100 backend (stable mode, no reload)...
echo.
python scripts\run_server.py --no-reload
pause

@echo off
title SWARM-100 + Cloudflare Tunnel
color 0B
echo.
echo  ============================================================
echo   SWARM-100 + Cloudflare Tunnel - Public Access Launcher
echo  ============================================================
echo.
cd /d "C:\Users\srinivas\OneDrive\Desktop\SWARM 100"

echo [1/4] Checking Ollama...
ollama list >nul 2>&1
if %errorlevel% neq 0 (
    echo  WARNING: Ollama not responding. Starting ollama serve in background...
    start "" /B ollama serve
    timeout /t 3 /nobreak >nul
) else (
    echo  OK: Ollama is running.
)

echo [2/4] Starting SWARM-100 backend in background...
start "SWARM-100 Backend" /B python scripts\run_server.py --no-reload
echo  Waiting 5 seconds for backend to start...
timeout /t 5 /nobreak >nul

echo [3/4] Starting Cloudflare Tunnel...
echo  Your public URL will appear below in a moment...
echo  (Press Ctrl+C in this window to stop the tunnel)
echo.

REM Try local cloudflared.exe first, then system PATH
if exist "cloudflared.exe" (
    echo  Using local cloudflared.exe
    cloudflared.exe tunnel --url http://localhost:8000
) else (
    echo  Using system cloudflared
    cloudflared tunnel --url http://localhost:8000
)

echo.
echo  Tunnel closed. Backend may still be running.
pause

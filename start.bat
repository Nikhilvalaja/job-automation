@echo off
setlocal enabledelayedexpansion
title JobPilot - Starting...
cd /d "%~dp0"
chcp 65001 >nul

echo ============================================================
echo   JobPilot - Job Automation System
echo ============================================================
echo.

set PYTHON=C:\Users\valaj\anaconda3\python.exe
set PROJECT=%~dp0

:: Kill old instances cleanly
taskkill /f /fi "WINDOWTITLE eq JobPilot-Backend*" >nul 2>&1
taskkill /f /fi "WINDOWTITLE eq JobPilot-Dashboard*" >nul 2>&1
taskkill /f /fi "WINDOWTITLE eq JobPilot-Bots*" >nul 2>&1
timeout /t 1 /nobreak >nul

:: ── 1. Backend API ──────────────────────────────────────────
echo [1/3] Starting Backend API (port 8000)...
start "JobPilot-Backend" /MIN cmd /k "%PYTHON% -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 2>&1"

:: Wait for backend to be ready (health check loop — max 30s)
echo       Waiting for backend to be ready...
set BACKEND_READY=0
for /L %%i in (1,1,15) do (
    if !BACKEND_READY! EQU 0 (
        curl -sf http://localhost:8000/health >nul 2>&1
        if !ERRORLEVEL! EQU 0 (
            set BACKEND_READY=1
            echo       Backend ready!
        ) else (
            timeout /t 2 /nobreak >nul
        )
    )
)
if %BACKEND_READY% EQU 0 (
    echo       [WARN] Backend did not respond in 30s — check logs/backend.log
)

:: ── 2. Dashboard ─────────────────────────────────────────────
echo [2/3] Starting Dashboard (port 8501)...
start "JobPilot-Dashboard" /MIN cmd /k "%PYTHON% -m streamlit run dashboard/app.py --server.port 8501 --server.headless true --browser.gatherUsageStats false 2>&1"

:: Wait a moment for dashboard to init
timeout /t 3 /nobreak >nul

:: ── 3. Orchestrator (all bots) ───────────────────────────────
echo [3/3] Starting All Bots (Discovery, Gmail, Email, Reminders)...
echo       Running all bots once immediately, then on schedule.
start "JobPilot-Bots" /MIN cmd /k "%PYTHON% -m bots.orchestrator.run --run-now 2>&1"

:: Wait for dashboard to be ready then open browser
timeout /t 4 /nobreak >nul
start "" "http://localhost:8501"

echo.
echo ============================================================
echo   JobPilot is RUNNING
echo.
echo   Dashboard  ->  http://localhost:8501  (bookmark this!)
echo   API Docs   ->  http://localhost:8000/docs
echo   Mobile Cap ->  http://localhost:8000/capture
echo.
echo   Bot Schedule (auto - no action needed):
echo     Discovery Bot  : every 60 min (700+ sources, scores jobs)
echo     Gmail Bot      : every 30 min (captures job alert emails)
echo     Email Bot      : every 5 min  (tracks application replies)
echo     Reminder Bot   : daily 9 AM   (follow-up nudges)
echo.
echo   Watchdog is active - crashed services will auto-restart.
echo   Press Ctrl+C or close this window to stop ALL services.
echo ============================================================
echo.

:: ── Watchdog loop — restart crashed services every 60s ───────
:watchdog
timeout /t 60 /nobreak >nul

:: Check Backend
tasklist /fi "WINDOWTITLE eq JobPilot-Backend*" /fo csv 2>nul | find /i "cmd.exe" >nul
if errorlevel 1 (
    echo [Watchdog] Backend crashed — restarting...
    start "JobPilot-Backend" /MIN cmd /k "%PYTHON% -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 2>&1"
)

:: Check Dashboard
tasklist /fi "WINDOWTITLE eq JobPilot-Dashboard*" /fo csv 2>nul | find /i "cmd.exe" >nul
if errorlevel 1 (
    echo [Watchdog] Dashboard crashed — restarting...
    start "JobPilot-Dashboard" /MIN cmd /k "%PYTHON% -m streamlit run dashboard/app.py --server.port 8501 --server.headless true --browser.gatherUsageStats false 2>&1"
)

:: Check Bots
tasklist /fi "WINDOWTITLE eq JobPilot-Bots*" /fo csv 2>nul | find /i "cmd.exe" >nul
if errorlevel 1 (
    echo [Watchdog] Bots crashed — restarting...
    start "JobPilot-Bots" /MIN cmd /k "%PYTHON% -m bots.orchestrator.run --run-now 2>&1"
)

goto watchdog

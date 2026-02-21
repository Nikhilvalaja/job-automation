@echo off
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

:: Wait for backend to boot
timeout /t 4 /nobreak >nul

:: ── 2. Dashboard ─────────────────────────────────────────────
echo [2/3] Starting Dashboard (port 8501)...
start "JobPilot-Dashboard" /MIN cmd /k "%PYTHON% -m streamlit run dashboard/app.py --server.port 8501 --server.headless true --browser.gatherUsageStats false 2>&1"

:: ── 3. Orchestrator (all bots) ───────────────────────────────
echo [3/3] Starting All Bots (Discovery, Gmail, Email, Reminders)...
echo       Running all bots once immediately, then on schedule.
start "JobPilot-Bots" /MIN cmd /k "%PYTHON% -m bots.orchestrator.run --run-now 2>&1"

:: Wait for dashboard to be ready
timeout /t 5 /nobreak >nul

:: Open browser
start "" "http://localhost:8501"

echo.
echo ============================================================
echo   JobPilot is RUNNING
echo.
echo   Dashboard  →  http://localhost:8501  (bookmark this!)
echo   API Docs   →  http://localhost:8000/docs
echo.
echo   Bot Schedule (auto — no action needed):
echo     Discovery Bot  : every 60 min (700+ sources, scores jobs)
echo     Gmail Bot      : every 30 min (captures job alert emails)
echo     Email Bot      : every 5 min  (tracks application replies)
echo     Reminder Bot   : daily 9 AM   (follow-up nudges)
echo.
echo   Keep this window open to keep everything running.
echo   Minimized windows = background services (don't close them).
echo   Press any key to stop ALL services.
echo ============================================================
echo.
pause >nul

:: Shutdown all services
echo Stopping all services...
taskkill /f /fi "WINDOWTITLE eq JobPilot-Backend*" >nul 2>&1
taskkill /f /fi "WINDOWTITLE eq JobPilot-Dashboard*" >nul 2>&1
taskkill /f /fi "WINDOWTITLE eq JobPilot-Bots*" >nul 2>&1
echo Done. Goodbye!
timeout /t 2 /nobreak >nul

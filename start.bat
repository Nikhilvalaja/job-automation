@echo off
title JobPilot - Starting Services...
cd /d "%~dp0"

echo ============================================
echo   JobPilot - Job Automation Dashboard
echo ============================================
echo.

:: Kill any existing instances
taskkill /f /im "python.exe" /fi "WINDOWTITLE eq uvicorn*" >nul 2>&1

:: Start Backend API (hidden in background)
echo Starting Backend API on port 8000...
start /b "" .\venv\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000

:: Wait for backend to be ready
timeout /t 3 /nobreak >nul

:: Start Dashboard
echo Starting Dashboard on port 8501...
start /b "" .\venv\Scripts\python.exe -m streamlit run dashboard/app.py --server.port 8501 --server.headless true --browser.gatherUsageStats false

:: Wait for dashboard to be ready
timeout /t 5 /nobreak >nul

echo.
echo ============================================
echo   JobPilot is running!
echo.
echo   Dashboard:  http://localhost:8501
echo   Backend:    http://localhost:8000/docs
echo.
echo   Keep this window open to keep services running.
echo   Press Ctrl+C to stop all services.
echo ============================================
echo.

:: Open dashboard in browser
start http://localhost:8501

:: Keep the window alive
pause >nul

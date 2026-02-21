@echo off
:: ============================================================
:: JobPilot — Register Windows Task Scheduler autostart
:: Run this ONCE. After that, JobPilot starts automatically
:: every time you log into Windows.
:: ============================================================
title JobPilot — Register Autostart
cd /d "%~dp0"

set VBS="%~dp0start-silent.vbs"

echo.
echo  Registering JobPilot to start automatically on Windows login...
echo.

:: Delete old task if it exists (ignore errors)
schtasks /delete /tn "JobPilot Autostart" /f >nul 2>&1

:: Create new task: runs start-silent.vbs at logon, highest privileges, no time limit
schtasks /create ^
  /tn "JobPilot Autostart" ^
  /tr "wscript.exe %VBS%" ^
  /sc ONLOGON ^
  /rl HIGHEST ^
  /delay 0000:30 ^
  /f >nul 2>&1

if %ERRORLEVEL% EQU 0 (
    echo  [OK] JobPilot will now auto-start every time you log in.
    echo.
    echo  To disable autostart later, run:
    echo    schtasks /delete /tn "JobPilot Autostart" /f
    echo.
) else (
    echo  [ERROR] Could not register task. Try running this as Administrator.
    echo  Right-click setup_autostart.bat ^> Run as administrator
    echo.
)

echo  Done. Press any key to close.
pause >nul

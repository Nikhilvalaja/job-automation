' JobPilot — Silent Startup Script
' Starts backend + dashboard without a visible command window.
' Add this to Windows Task Scheduler for auto-start on login.

Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)

' Start backend
WshShell.Run ".\venv\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000", 0, False

' Wait 4 seconds for backend
WScript.Sleep 4000

' Start dashboard
WshShell.Run ".\venv\Scripts\python.exe -m streamlit run dashboard/app.py --server.port 8501 --server.headless true --browser.gatherUsageStats false", 0, False

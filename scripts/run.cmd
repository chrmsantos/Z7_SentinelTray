@echo off
setlocal enableextensions

set "ROOT=%~dp0.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
set "Z7_SENTINELTRAY_ROOT=%ROOT%"

set "PYTHON=python"
if exist "%ROOT%\.venv\Scripts\python.exe" set "PYTHON=%ROOT%\.venv\Scripts\python.exe"

start /MIN "Z7_SentinelTray" "%PYTHON%" "%ROOT%\main.py" %*
exit /b 0

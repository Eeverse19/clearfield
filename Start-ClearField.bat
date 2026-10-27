@echo off
rem ClearField one-click launcher: starts the API+GUI server, opens the map.
cd /d "%~dp0"
title ClearField

where uv >nul 2>nul
if %ERRORLEVEL%==0 (
  start "ClearField server (close this window to stop)" cmd /k uv run uvicorn backend.app.main:app --port 8000
) else (
  start "ClearField server (close this window to stop)" cmd /k .venv\Scripts\python.exe -m uvicorn backend.app.main:app --port 8000
)

echo Waiting for the server to come up...
for /L %%i in (1,1,30) do (
  powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://localhost:8000/health).StatusCode }" >nul 2>nul
  if %ERRORLEVEL%==0 goto ready
  timeout /t 1 /nobreak >nul
)
echo Server did not answer on http://localhost:8000/health - check the server window for errors.
pause
exit /b 1

:ready
start "" http://localhost:8000/
echo ClearField is running at http://localhost:8000/
echo Close the "ClearField server" window to stop it.
timeout /t 3 /nobreak >nul

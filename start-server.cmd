@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "HOST=127.0.0.1"
set "PORT=8000"
set "RELOAD=--reload"

if exist ".env" (
  for /f "usebackq tokens=1,* delims==" %%A in (`findstr /r /c:"^PS_TOOL_WEB_HOST=" /c:"^PS_TOOL_WEB_PORT=" /c:"^PS_TOOL_WEB_RELOAD=" ".env"`) do (
    if /i "%%A"=="PS_TOOL_WEB_HOST" set "HOST=%%B"
    if /i "%%A"=="PS_TOOL_WEB_PORT" set "PORT=%%B"
    if /i "%%A"=="PS_TOOL_WEB_RELOAD" (
      if /i "%%B"=="false" set "RELOAD="
      if /i "%%B"=="0" set "RELOAD="
      if /i "%%B"=="no" set "RELOAD="
    )
  )
)

if not exist ".venv\Scripts\python.exe" (
  echo ERROR: .venv not found. Run setup-env.cmd first.
  exit /b 1
)

echo [ps-tool-web] Stopping any process listening on %HOST%:%PORT% ...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%PORT% " ^| findstr LISTENING') do (
  taskkill /F /PID %%P >nul 2>&1
)

call ".venv\Scripts\activate.bat"

echo [ps-tool-web] Starting server at http://%HOST%:%PORT%/
echo Press Ctrl+C to stop.
python -m uvicorn app.main:app %RELOAD% --host %HOST% --port %PORT%

endlocal
exit /b %ERRORLEVEL%

@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "HOST=127.0.0.1"
set "PORT=8000"
set "RELOAD=--reload"

if exist ".env" (
  for /f "usebackq tokens=1,* delims==" %%A in (`findstr /r /c:"^PS_TOOL_WEB_HOST=" /c:"^PS_TOOL_WEB_PORT=" /c:"^PS_TOOL_WEB_RELOAD=" /c:"^MOCK_DATASET=" /c:"^MOCK_REFERENCE_PATH=" /c:"^MOCK_JOB_COUNT=" ".env"`) do (
    if /i "%%A"=="PS_TOOL_WEB_HOST" set "HOST=%%B"
    if /i "%%A"=="PS_TOOL_WEB_PORT" set "PORT=%%B"
    if /i "%%A"=="PS_TOOL_WEB_RELOAD" (
      if /i "%%B"=="false" set "RELOAD="
      if /i "%%B"=="0" set "RELOAD="
      if /i "%%B"=="no" set "RELOAD="
    )
    if /i "%%A"=="MOCK_DATASET" set "MOCK_DATASET=%%B"
    if /i "%%A"=="MOCK_REFERENCE_PATH" set "MOCK_REFERENCE_PATH=%%B"
    if /i "%%A"=="MOCK_JOB_COUNT" set "MOCK_JOB_COUNT=%%B"
  )
)

if not exist ".venv\Scripts\python.exe" (
  echo ERROR: .venv not found. Run setup-env.cmd first.
  exit /b 1
)

set "PS_TOOL_CMD_PORT=%PORT%"
echo [ps-tool-web] Checking port %PORT% ...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$port = [int]$env:PS_TOOL_CMD_PORT;" ^
  "$listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue ^| Select-Object -ExpandProperty OwningProcess -Unique);" ^
  "foreach ($processId in $listeners) {" ^
  "  $process = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $processId) -ErrorAction SilentlyContinue;" ^
  "  $commandLine = [string]$process.CommandLine;" ^
  "  if ($commandLine -match '(?i)uvicorn' -and $commandLine -match 'app\.main:app') {" ^
  "    Write-Host ('[ps-tool-web] Restarting existing server process PID ' + $processId + ' ...');" ^
  "    Stop-Process -Id $processId -Force -ErrorAction Stop;" ^
  "  } else {" ^
  "    Write-Error ('Port ' + $port + ' is already used by another process (PID ' + $processId + '). Refusing to terminate it.');" ^
  "    exit 20;" ^
  "  }" ^
  "}"

if errorlevel 1 (
  echo ERROR: Cannot start ps-tool-web on port %PORT%.
  exit /b 1
)

set "PS_TOOL_CMD_PORT="

echo [ps-tool-web] Starting server at http://%HOST%:%PORT%/
echo Press Ctrl+C to stop.
".venv\Scripts\python.exe" -m uvicorn app.main:app %RELOAD% --host %HOST% --port %PORT%

set "EXIT_CODE=%ERRORLEVEL%"
endlocal & exit /b %EXIT_CODE%

@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "HOST=127.0.0.1"
set "PORT=8000"

if exist ".env" (
  for /f "usebackq tokens=1,* delims==" %%A in (`findstr /r /c:"^PS_TOOL_WEB_HOST=" /c:"^PS_TOOL_WEB_PORT=" ".env"`) do (
    if /i "%%A"=="PS_TOOL_WEB_HOST" set "HOST=%%B"
    if /i "%%A"=="PS_TOOL_WEB_PORT" set "PORT=%%B"
  )
)

set "BROWSER_HOST=%HOST%"
if "%BROWSER_HOST%"=="0.0.0.0" set "BROWSER_HOST=127.0.0.1"
if "%BROWSER_HOST%"=="::" set "BROWSER_HOST=127.0.0.1"

set "APP_URL=http://%BROWSER_HOST%:%PORT%/"
echo [ps-tool-web] Opening %APP_URL%
start "" "%APP_URL%"

endlocal
exit /b 0

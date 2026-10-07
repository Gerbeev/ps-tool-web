@echo off
setlocal
cd /d "%~dp0"

set "TARGET_DIR=%~1"
if not defined TARGET_DIR set "TARGET_DIR=workstation_connectors"

if not exist "%TARGET_DIR%" mkdir "%TARGET_DIR%"

call :copy_if_missing "bridge_v1_runtime.py"
call :copy_if_missing "autosys_connector.py"
call :copy_if_missing "process_scheduler_connector.py"

echo.
echo Workstation connector files are ready under:
echo   %TARGET_DIR%
echo Edit only autosys_connector.py and process_scheduler_connector.py.
echo Keep bridge_v1_runtime.py unchanged.
echo.
echo If this directory is outside the project, set in .env:
echo   PS_TOOL_CONNECTOR_DIR=%TARGET_DIR%
echo.
echo See docs\workstation-connector-protocol-v1.md
exit /b 0

:copy_if_missing
if exist "%TARGET_DIR%\%~1" (
  echo KEEP  %TARGET_DIR%\%~1
) else (
  copy /Y "examples\workstation_connectors\%~1" "%TARGET_DIR%\%~1" >nul
  if errorlevel 1 exit /b 1
  echo COPY  %TARGET_DIR%\%~1
)
exit /b 0

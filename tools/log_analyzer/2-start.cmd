@echo off
setlocal
cd /d "%~dp0"
set "PYTHON_CMD="
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=python"
if not defined PYTHON_CMD (
    py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=py -3"
)
if not defined PYTHON_CMD (
    echo ERROR: Python 3.11+ not found. Run 1-setup.cmd first.
    pause
    exit /b 1
)
%PYTHON_CMD% "%~dp0menu.py"
if errorlevel 1 (
    echo.
    echo ERROR: Log Analyzer exited unexpectedly.
    pause
    exit /b 1
)
exit /b 0

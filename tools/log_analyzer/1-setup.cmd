@echo off
setlocal
cd /d "%~dp0"
echo ==================================
echo       JOB LOG ANALYZER SETUP
echo ==================================
echo.
set "PYTHON_CMD="
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=python"
if not defined PYTHON_CMD (
    py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=py -3"
)
if not defined PYTHON_CMD (
    echo ERROR: Python 3.11+ not found.
    echo Install Python 3.11 or newer and add it to PATH.
    pause
    exit /b 1
)
echo Found compatible Python.
echo No third-party packages are needed.
echo Checking configuration...
%PYTHON_CMD% "%~dp0menu.py" --check
if errorlevel 1 (
    echo ERROR: Configuration validation failed.
    pause
    exit /b 1
)
echo.
echo Setup complete. Open 2-start.cmd to launch the menu.
pause
exit /b 0

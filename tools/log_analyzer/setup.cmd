@echo off
setlocal
cd /d "%~dp0" || exit /b 1

echo ==================================
echo       JOB LOG ANALYZER SETUP
echo ==================================
echo.

python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python 3.11+ is required and the `python` command must be available on PATH.
    echo Install Python 3.11 or newer and add python.exe to PATH.
    pause
    exit /b 1
)

echo Found compatible Python.
echo No third-party packages are needed.
echo Checking configuration...
python "%~dp0menu.py" --check
if errorlevel 1 (
    echo ERROR: Configuration validation failed.
    pause
    exit /b 1
)

echo.
echo Setup complete. Open start.cmd to launch the menu.
pause
exit /b 0

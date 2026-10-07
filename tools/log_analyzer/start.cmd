@echo off
setlocal
cd /d "%~dp0" || exit /b 1

python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python 3.11+ is required and the `python` command must be available on PATH.
    echo Run setup.cmd after adding python.exe to PATH.
    pause
    exit /b 1
)

python "%~dp0menu.py"
if errorlevel 1 (
    echo.
    echo ERROR: Log Analyzer exited unexpectedly.
    pause
    exit /b 1
)
exit /b 0

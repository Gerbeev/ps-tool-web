@echo off
setlocal
cd /d "%~dp0" || exit /b 1

if "%~1"=="" (
    echo Usage: run.cmd PROD [--mode inventory^|enrich] [--date YYYYMMDD] [--force] [--output-dir PATH] [--no-progress]
    exit /b 2
)

python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python 3.11+ is required and the `python` command must be available on PATH. 1>&2
    exit /b 1
)

python "%~dp0analyze.py" --env %*
exit /b %errorlevel%

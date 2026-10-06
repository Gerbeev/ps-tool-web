@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
if "%~1"=="" (
    echo Usage: run.cmd PROD [--date YYYYMMDD] [--output output.csv]
    exit /b 2
)
where python >nul 2>nul
if %errorlevel%==0 (
    python "%~dp0analyze.py" --env %*
    exit /b !errorlevel!
)
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 "%~dp0analyze.py" --env %*
    exit /b !errorlevel!
)
echo Python 3.11+ not found on PATH. 1>&2
exit /b 1

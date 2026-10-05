@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo [ps-tool-web] Setting up virtual environment in .venv ...

where py >nul 2>&1
if %ERRORLEVEL%==0 (
  py -3 -m venv .venv
) else (
  where python >nul 2>&1
  if %ERRORLEVEL% neq 0 (
    echo ERROR: Python 3 not found. Install Python 3.11+ and run this script again.
    exit /b 1
  )
  python -m venv .venv
)

if not exist ".venv\Scripts\python.exe" (
  echo ERROR: Failed to create .venv. On some systems run: py -3 -m pip install --upgrade pip
  exit /b 1
)

call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if not exist ".env" (
  if exist ".env.example" (
    copy /Y ".env.example" ".env" >nul
    echo Created .env from .env.example
  )
)

echo.
echo [ps-tool-web] Done. Run start-server.cmd to start the app.
endlocal
exit /b 0

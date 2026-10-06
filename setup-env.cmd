@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo [ps-tool-web] Checking project files ...
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if not errorlevel 1 (
  set "PYTHON_CMD=python"
) else (
  py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
  if not errorlevel 1 set "PYTHON_CMD=py -3"
)

if not defined PYTHON_CMD (
  echo ERROR: Python 3.11+ is required. Neither "python" nor "py -3" is usable.
  echo Install Python 3.11+ and make sure it is available in PATH.
  exit /b 1
)

echo [ps-tool-web] Using %PYTHON_CMD%
%PYTHON_CMD% -m scripts.verify_checkout --source
if errorlevel 1 (
  echo ERROR: Incomplete project checkout. Fix the files reported above before installing.
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [ps-tool-web] Creating .venv ...
  %PYTHON_CMD% -m venv ".venv"
  if errorlevel 1 (
    echo ERROR: Cannot create .venv with %PYTHON_CMD%.
    exit /b 1
  )
)

if not exist ".venv\Scripts\python.exe" (
  echo ERROR: .venv\Scripts\python.exe is missing.
  exit /b 1
)

".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 (
  echo ERROR: Existing .venv uses an unsupported Python version. Remove .venv and rerun setup-env.cmd.
  exit /b 1
)

echo [ps-tool-web] Installing dependencies ...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo ERROR: Dependency installation failed. Check pip output/network settings.
  exit /b 1
)

if not exist ".env" (
  if exist ".env.example" (
    copy /Y ".env.example" ".env" >nul
    if errorlevel 1 (
      echo ERROR: Cannot create .env from .env.example.
      exit /b 1
    )
    echo [ps-tool-web] Created .env from .env.example
  )
)

echo [ps-tool-web] Verifying imports and runtime ...
".venv\Scripts\python.exe" -m scripts.verify_checkout --runtime
if errorlevel 1 (
  echo ERROR: Project verification failed. Fix the reported missing modules/files.
  exit /b 1
)

echo.
echo [ps-tool-web] Setup complete. Run start-server.cmd to start the app.
endlocal
exit /b 0

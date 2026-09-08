@echo off
setlocal enabledelayedexpansion
REM ============================================================
REM  TeachFlow Launcher for Windows
REM  Double-click this file to start TeachFlow.
REM ============================================================

title TeachFlow

echo.
echo  ============================================
echo   TeachFlow - Language-Model-Assisted
echo   Teaching Platform
echo  ============================================
echo.

REM --- Change to script directory (handles spaces in path) ---
cd /d "%~dp0"

REM --- Create or validate the project virtual environment ---
set "VENV_PYTHON=.venv\Scripts\python.exe"
if not exist "%VENV_PYTHON%" (
    set "BOOTSTRAP_PYTHON="

    where py >nul 2>nul
    if !ERRORLEVEL! equ 0 (
        py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>nul
        if !ERRORLEVEL! equ 0 set "BOOTSTRAP_PYTHON=py -3"
    )

    if not defined BOOTSTRAP_PYTHON (
        where python >nul 2>nul
        if !ERRORLEVEL! equ 0 (
            python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>nul
            if !ERRORLEVEL! equ 0 set "BOOTSTRAP_PYTHON=python"
        )
    )

    if not defined BOOTSTRAP_PYTHON (
        echo  [FAIL] Python 3.9 or newer is required to create .venv.
        echo  Install Python from https://www.python.org/downloads/ and enable Add Python to PATH.
        echo  Then run this launcher again.
        echo.
        pause
        exit /b 1
    )

    echo  Creating project virtual environment...
    %BOOTSTRAP_PYTHON% -m venv ".venv"
    if !ERRORLEVEL! neq 0 (
        echo  [FAIL] Could not create .venv.
        echo  Try: %BOOTSTRAP_PYTHON% -m venv .venv
        echo.
        pause
        exit /b 1
    )
)

"%VENV_PYTHON%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>nul
if !ERRORLEVEL! neq 0 (
    echo  [FAIL] .venv does not contain Python 3.9 or newer.
    echo  Rename or remove .venv, then run this launcher again to recreate it.
    echo.
    pause
    exit /b 1
)
for /f "tokens=2 delims= " %%v in ('"%VENV_PYTHON%" --version 2^>^&1') do set PYVER=%%v
echo  [OK] Using .venv Python %PYVER%

REM --- Create config.yaml if missing ---
if not exist "config.yaml" (
    echo  Creating default config.yaml...
    (
        echo paths:
        echo   database_file: quiz_warehouse.db
        echo llm:
        echo   provider: mock
        echo generation:
        echo   default_grade_level: 7th Grade
    ) > "config.yaml"
    echo  [OK] Created config.yaml with safe Mock defaults
)

REM --- Install dependencies when requirements.txt has changed ---
"%VENV_PYTHON%" -c "import hashlib, pathlib, sys; requirements = pathlib.Path('requirements.txt'); marker = pathlib.Path('.deps_installed'); digest = hashlib.sha256(requirements.read_bytes()).hexdigest(); sys.exit(0 if marker.is_file() and marker.read_text(encoding='utf-8').strip() == digest else 1)" >nul 2>nul
if !ERRORLEVEL! neq 0 (
    echo.
    echo  Installing project dependencies ^(first run or requirements changed^)...
    echo.
    "%VENV_PYTHON%" -m pip install -r requirements.txt --quiet
    if !ERRORLEVEL! neq 0 (
        echo.
        echo  [FAIL] Could not install dependencies into .venv.
        echo  Recovery: "%VENV_PYTHON%" -m pip install -r requirements.txt
        echo  If that fails, recreate .venv with: py -3 -m venv .venv
        echo.
        pause
        exit /b 1
    )
    "%VENV_PYTHON%" -c "import hashlib, pathlib; pathlib.Path('.deps_installed').write_text(hashlib.sha256(pathlib.Path('requirements.txt').read_bytes()).hexdigest() + '\n', encoding='utf-8')"
    echo  [OK] Dependencies installed
) else (
    echo  [OK] Project dependencies match requirements.txt
)

REM --- Detect port conflict ---
set PORT=5000
netstat -an 2>nul | findstr ":5000 .*LISTENING" >nul 2>nul
if !ERRORLEVEL! equ 0 (
    echo  [NOTE] Port 5000 is in use. Using port 5001 instead.
    set PORT=5001
)

echo.
echo  Starting TeachFlow...
echo  URL: http://localhost:!PORT!
echo.
echo  To stop the server, close this window or press Ctrl+C.
echo  ============================================
echo.

REM --- Open browser after a short delay ---
set LAUNCH_URL=http://localhost:!PORT!
start "" cmd /c "timeout /t 2 /nobreak >nul && start %LAUNCH_URL%"

REM --- Start the app (with .env loading and UTF-8 config) ---
"%VENV_PYTHON%" -c "import os; from dotenv import load_dotenv; load_dotenv() if os.path.exists('.env') else None; import yaml; from pathlib import Path; config = yaml.safe_load(Path('config.yaml').read_text(encoding='utf-8')); from src.web.app import create_app; app = create_app(config); app.run(host='127.0.0.1', port=!PORT!)"

if !ERRORLEVEL! neq 0 (
    echo.
    echo  [FAIL] TeachFlow exited with an error.
    echo  Check the messages above for details.
    echo.
    pause
)

endlocal

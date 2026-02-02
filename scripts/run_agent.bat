@echo off
setlocal enabledelayedexpansion

:: Run the web_slicer_core agent

:: Get script directory and repo root
set SCRIPT_DIR=%~dp0
pushd %SCRIPT_DIR%..
set REPO_ROOT=%CD%
popd

cd /d "%REPO_ROOT%"

:: Check if virtual environment exists
if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to create virtual environment
        exit /b 1
    )
)

:: Activate virtual environment
call .venv\Scripts\activate.bat

:: Install dependencies
echo Installing dependencies...
pip install -q -r requirements.txt
if !errorlevel! neq 0 (
    echo [ERROR] Failed to install dependencies
    exit /b 1
)

:: Check if PrusaSlicer CLI exists
:: Use PRUSA_SLICER_BIN env var if set, otherwise use default path
if defined PRUSA_SLICER_BIN (
    set CLI_PATH=%PRUSA_SLICER_BIN%
) else (
    set CLI_PATH=%REPO_ROOT%\third_party\prusaslicer_build\src\Release\prusa-slicer.exe
)
echo %CLI_PATH%

if not exist "%CLI_PATH%" (
    echo [ERROR] PrusaSlicer CLI not found at %CLI_PATH%
    echo Please build PrusaSlicer first or set PRUSA_SLICER_BIN environment variable.
    exit /b 1
)
set PRUSA_SLICER_BIN=%CLI_PATH%

echo Starting web_slicer_core agent on http://127.0.0.1:5179
echo Press Ctrl+C to stop
echo.

:: Run the agent
::python -m uvicorn agent.main:app --host 127.0.0.1 --port 5179 --reload
:: Run uvicorn directly with .venv python
"%REPO_ROOT%\.venv\Scripts\python.exe" -m uvicorn agent.main:app --host 127.0.0.1 --port 5179 --app-dir "%REPO_ROOT%"

endlocal

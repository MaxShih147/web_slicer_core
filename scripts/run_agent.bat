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

:: TLS resolution order matches agent\config.py: env, then agent\tls\, then Bundle-Launcher (mac, win).
if defined AGENT_TLS_CERTFILE (
    set CERT_PATH=%AGENT_TLS_CERTFILE%
) else (
    set CERT_PATH=%REPO_ROOT%\agent\tls\localhost.crt
    if not exist "%CERT_PATH%" set CERT_PATH=%REPO_ROOT%\..\Bundle-Launcher\bundle-mac\agent\tls\localhost.crt
    if not exist "%CERT_PATH%" set CERT_PATH=%REPO_ROOT%\..\Bundle-Launcher\bundle-win\agent\tls\localhost.crt
)
if defined AGENT_TLS_KEYFILE (
    set KEY_PATH=%AGENT_TLS_KEYFILE%
) else (
    set KEY_PATH=%REPO_ROOT%\agent\tls\localhost.key
    if not exist "%KEY_PATH%" set KEY_PATH=%REPO_ROOT%\..\Bundle-Launcher\bundle-mac\agent\tls\localhost.key
    if not exist "%KEY_PATH%" set KEY_PATH=%REPO_ROOT%\..\Bundle-Launcher\bundle-win\agent\tls\localhost.key
)
if not exist "%CERT_PATH%" (
    echo [ERROR] TLS cert not found: %CERT_PATH%
    echo Set AGENT_TLS_CERTFILE and AGENT_TLS_KEYFILE, or prepare agent\tls\localhost.crt^|key
    exit /b 1
)
if not exist "%KEY_PATH%" (
    echo [ERROR] TLS key not found: %KEY_PATH%
    echo Set AGENT_TLS_CERTFILE and AGENT_TLS_KEYFILE, or prepare agent\tls\localhost.crt^|key
    exit /b 1
)
set AGENT_TLS_CERTFILE=%CERT_PATH%
set AGENT_TLS_KEYFILE=%KEY_PATH%

echo Starting web_slicer_core agent on https://127.0.0.1:5179
echo Press Ctrl+C to stop
echo.

:: Run the agent
::python -m uvicorn agent.main:app --host 127.0.0.1 --port 5179 --reload
:: Run uvicorn directly with .venv python
"%REPO_ROOT%\.venv\Scripts\python.exe" -m uvicorn agent.main:app --host 127.0.0.1 --port 5179 --app-dir "%REPO_ROOT%" --ssl-certfile "%AGENT_TLS_CERTFILE%" --ssl-keyfile "%AGENT_TLS_KEYFILE%"

endlocal

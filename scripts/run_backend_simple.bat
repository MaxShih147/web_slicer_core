@echo off
:: Simple backend startup script (without dependency install)

:: Get script directory and repo root
set SCRIPT_DIR=%~dp0
pushd %SCRIPT_DIR%..
set REPO_ROOT=%CD%
popd

echo Starting backend on http://127.0.0.1:5179
echo Press Ctrl+C to stop
echo.

:: Run uvicorn directly with .venv python
"%REPO_ROOT%\.venv\Scripts\python.exe" -m uvicorn agent.main:app --host 127.0.0.1 --port 5179 --app-dir "%REPO_ROOT%"

@echo off
setlocal enabledelayedexpansion

:: Run the web_slicer_core agent

:: Get script directory and repo root
set SCRIPT_DIR=%~dp0
pushd %SCRIPT_DIR%..
set REPO_ROOT=%CD%
popd

cd /d "%REPO_ROOT%"

:: Prefer Python 3.12 venv on Windows (manifold3d has prebuilt wheels, no TBB build needed)
set "VENV_DIR=.venv"
if exist ".venv312\Scripts\python.exe" set "VENV_DIR=.venv312"

:: Default VCPKG_ROOT for Windows manifold3d build when using .venv (override with env if needed)
if not defined VCPKG_ROOT if exist "%USERPROFILE%\vcpkg\installed\x64-windows" set "VCPKG_ROOT=%USERPROFILE%\vcpkg"

:: Create default venv only if neither exists
if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo Creating virtual environment in %VENV_DIR%...
    python -m venv %VENV_DIR%
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to create virtual environment
        exit /b 1
    )
)

:: Activate virtual environment
call %VENV_DIR%\Scripts\activate.bat

:: On Windows, manifold3d builds from source and needs TBB. If VCPKG_ROOT is set,
:: point CMake at vcpkg's installed dir and put TBB DLLs on PATH for the build.
if defined VCPKG_ROOT (
    if exist "%VCPKG_ROOT%\installed\x64-windows" (
        set "VCPKG_INSTALLED=%VCPKG_ROOT%\installed\x64-windows"
        set "CMAKE_PREFIX_PATH=%VCPKG_INSTALLED%"
        set "TBB_DIR=%VCPKG_INSTALLED%\share\tbb"
        set "PATH=%VCPKG_INSTALLED%\bin;%PATH%"
        echo Using VCPKG for manifold3d: !VCPKG_INSTALLED!
        set "SKBUILD_CMAKE_ARGS="
    )
)

:: Install dependencies. .venv312 = Python 3.12, use wheels (no build). .venv + VCPKG = build from source.
echo Installing dependencies...
if "!VENV_DIR!"==".venv312" (
    pip install -q -r requirements.txt
) else if defined VCPKG_ROOT (
    pip install -q scikit-build-core cmake 2>nul
    pip install -q fastapi "uvicorn[standard]" python-multipart pydantic trimesh rtree numpy Pillow
    pip install -q --no-build-isolation "manifold3d>=2.3.0" -C "cmake.define.MANIFOLD_PYBIND_STUBGEN=OFF"
) else (
    pip install -q -r requirements.txt
)
if !errorlevel! neq 0 (
    echo [ERROR] Failed to install dependencies
    echo On Windows, manifold3d requires TBB. See README "Windows setup" for vcpkg + VCPKG_ROOT.
    exit /b 1
)

:: Check if slicer-engine CLI exists
:: Prefer SLICER_ENGINE_BIN (canonical); accept legacy PRUSA_SLICER_BIN for local transition
if defined SLICER_ENGINE_BIN (
    set CLI_PATH=%SLICER_ENGINE_BIN%
) else if defined PRUSA_SLICER_BIN (
    set CLI_PATH=%PRUSA_SLICER_BIN%
) else if exist "%REPO_ROOT%\slicer-engine\bin\slicer-engine.exe" (
    set CLI_PATH=%REPO_ROOT%\slicer-engine\bin\slicer-engine.exe
) else (
    set CLI_PATH=%REPO_ROOT%\third_party\prusaslicer_build\src\Release\slicer-engine.exe
)
echo %CLI_PATH%

if not exist "%CLI_PATH%" (
    echo [ERROR] Slicer engine CLI not found at %CLI_PATH%
    echo Please build first ^(scripts\build_prusaslicer_fork_windows.bat^) or set SLICER_ENGINE_BIN.
    exit /b 1
)
set SLICER_ENGINE_BIN=%CLI_PATH%

:: TLS resolution order matches agent\config.py: env, then agent\tls\, then Bundle-Launcher (mac, win).
if defined AGENT_TLS_CERTFILE (
    set CERT_PATH=%AGENT_TLS_CERTFILE%
) else (
    set CERT_PATH=%REPO_ROOT%\agent\tls\localhost.crt
    if not exist "!CERT_PATH!" set CERT_PATH=%REPO_ROOT%\..\Bundle-Launcher\bundle-mac\agent\tls\localhost.crt
    if not exist "!CERT_PATH!" set CERT_PATH=%REPO_ROOT%\..\Bundle-Launcher\bundle-win\agent\tls\localhost.crt
)
if defined AGENT_TLS_KEYFILE (
    set KEY_PATH=%AGENT_TLS_KEYFILE%
) else (
    set KEY_PATH=%REPO_ROOT%\agent\tls\localhost.key
    if not exist "!KEY_PATH!" set KEY_PATH=%REPO_ROOT%\..\Bundle-Launcher\bundle-mac\agent\tls\localhost.key
    if not exist "!KEY_PATH!" set KEY_PATH=%REPO_ROOT%\..\Bundle-Launcher\bundle-win\agent\tls\localhost.key
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
"%REPO_ROOT%\%VENV_DIR%\Scripts\python.exe" -m uvicorn agent.main:app --host 127.0.0.1 --port 5179 --app-dir "%REPO_ROOT%" --ssl-certfile "%AGENT_TLS_CERTFILE%" --ssl-keyfile "%AGENT_TLS_KEYFILE%"

endlocal

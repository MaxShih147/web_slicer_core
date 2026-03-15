@echo off
setlocal enabledelayedexpansion

:: ============================================
:: Memory Mode Configuration
:: Usage: build_prusaslicer_fork_windows.bat [full|low]
::   full - 4 parallel projects, /MP enabled (32GB+ RAM)
::   low  - 1 parallel project, /MP:2 (16GB RAM) [default]
:: ============================================
set MEMORY_MODE=%1
if "%MEMORY_MODE%"=="" set MEMORY_MODE=low

if /i "%MEMORY_MODE%"=="full" (
    set BUILD_FLAGS=/m:4
    echo [CONFIG] Memory mode: FULL - 4 parallel projects, /MP enabled ^(32GB+ RAM^)
) else (
    set MEMORY_MODE=low
    set BUILD_FLAGS=/m:1 /p:CL_MPCount=1 /p:UseMultiToolTask=false
    echo [CONFIG] Memory mode: LOW - 1 parallel project, /MP disabled ^(16GB RAM^)
)
echo.

set FORK_URL=git@github.com:MaxShih147/PrusaSlicer.git
set FORK_BRANCH=master

:: Get script directory and root directory
set SCRIPT_DIR=%~dp0
pushd %SCRIPT_DIR%..
set ROOT_DIR=%CD%
popd

set SRC_DIR=%ROOT_DIR%\third_party\prusaslicer_fork
set DEPS_BUILD_DIR=%SRC_DIR%\deps\build
set BUILD_DIR=%ROOT_DIR%\third_party\prusaslicer_build

:: Use CMake 3.27 (3.28+ has issues with PrusaSlicer)
:: Check for CMake in common locations or PATH
set CMAKE_BIN=
if exist "%ROOT_DIR%\cmake-3.27.9-windows-x86_64\bin\cmake.exe" (
    set CMAKE_BIN=%ROOT_DIR%\cmake-3.27.9-windows-x86_64\bin\cmake.exe
) else (
    where cmake >nul 2>&1
    if !errorlevel! equ 0 (
        set CMAKE_BIN=cmake
    )
)

if "%CMAKE_BIN%"=="" (
    echo [ERROR] CMake not found.
    echo Please download CMake 3.27.9 from:
    echo https://github.com/Kitware/CMake/releases/download/v3.27.9/cmake-3.27.9-windows-x86_64.zip
    echo and extract to %ROOT_DIR%\cmake-3.27.9-windows-x86_64
    exit /b 1
)

:: Detect Visual Studio generator via vswhere (catalog_productLineVersion: 18=2026, 17=2022, 16=2019)
set VS_GENERATOR=Visual Studio 17 2022
set "VSWhere=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if exist "%VSWhere%" (
    for /f "usebackq delims=" %%v in (`"%VSWhere%" -latest -property catalog_productLineVersion 2^>nul`) do set "VS_VER=%%v"
    if "!VS_VER!"=="18" set VS_GENERATOR=Visual Studio 18 2026
    if "!VS_VER!"=="17" set VS_GENERATOR=Visual Studio 17 2022
    if "!VS_VER!"=="16" set VS_GENERATOR=Visual Studio 16 2019
    if "!VS_VER!"=="15" set VS_GENERATOR=Visual Studio 15 2017
)

echo [PrusaSlicer] Using fork: %FORK_URL% (%FORK_BRANCH%)
echo [PrusaSlicer] Using CMake: %CMAKE_BIN%
echo [PrusaSlicer] Using generator: %VS_GENERATOR%
echo [PrusaSlicer] Build flags: %BUILD_FLAGS%

:: Clone or update fork (if repo uses submodules, run first: git submodule update --init --recursive)
if not exist "%SRC_DIR%\.git" (
    echo [PrusaSlicer] Fork source not found. Cloning...
    echo If this repo uses submodules, run: git submodule update --init --recursive
    if not exist "%ROOT_DIR%\third_party" mkdir "%ROOT_DIR%\third_party"
    git clone "%FORK_URL%" "%SRC_DIR%"
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to clone repository
        exit /b 1
    )
)

cd /d "%SRC_DIR%"
git fetch origin
if !errorlevel! neq 0 (
    echo [ERROR] Failed to fetch from origin
    exit /b 1
)
git checkout %FORK_BRANCH%
git pull origin %FORK_BRANCH%

:: ============================================
:: Step 1: Build dependencies (if not already built)
:: ============================================
set DEPS_DESTDIR=%DEPS_BUILD_DIR%\destdir\usr\local

if not exist "%DEPS_DESTDIR%" (
    echo.
    echo [PrusaSlicer] ==========================================
    echo [PrusaSlicer] Step 1: Building dependencies...
    echo [PrusaSlicer] This may take a while...
    echo [PrusaSlicer] ==========================================
    echo.

    if not exist "%DEPS_BUILD_DIR%" mkdir "%DEPS_BUILD_DIR%"
    cd /d "%DEPS_BUILD_DIR%"

    :: Build deps without wxWidgets (headless/CLI mode)
    :: CMAKE_POLICY_VERSION_MINIMUM=3.5 allows subprojects with old cmake_minimum_required to work with CMake 4.x
    "%CMAKE_BIN%" .. ^
        -G "%VS_GENERATOR%" ^
        -A x64 ^
        -DCMAKE_BUILD_TYPE=Release ^
        -DPrusaSlicer_deps_PACKAGE_EXCLUDES="wxWidgets"

    if !errorlevel! neq 0 (
        echo [ERROR] CMake configuration failed for dependencies
        exit /b 1
    )

    :: Build dependencies
    "%CMAKE_BIN%" --build . --config Release -- %BUILD_FLAGS%

    if !errorlevel! neq 0 (
        echo [ERROR] Dependencies build failed
        exit /b 1
    )
) else (
    echo [PrusaSlicer] Dependencies already built at %DEPS_DESTDIR%
)

:: ============================================
:: Step 2: Build PrusaSlicer CLI
:: ============================================
echo.
echo [PrusaSlicer] ==========================================
echo [PrusaSlicer] Step 2: Building PrusaSlicer CLI...
echo [PrusaSlicer] ==========================================
echo.

if not exist "%BUILD_DIR%" mkdir "%BUILD_DIR%"
cd /d "%BUILD_DIR%"

echo [PrusaSlicer] Configuring build...
"%CMAKE_BIN%" "%SRC_DIR%" ^
    -G "%VS_GENERATOR%" ^
    -A x64 ^
    -DCMAKE_BUILD_TYPE=Release ^
    -DSLIC3R_GUI=OFF ^
    -DSLIC3R_BUILD_TESTS=OFF ^
    -DCMAKE_PREFIX_PATH="%DEPS_DESTDIR%"

if !errorlevel! neq 0 (
    echo [ERROR] CMake configuration failed
    exit /b 1
)

echo [PrusaSlicer] Building...
"%CMAKE_BIN%" --build . --config Release -- %BUILD_FLAGS%

if !errorlevel! neq 0 (
    echo [ERROR] Build failed
    exit /b 1
)

echo.
echo [PrusaSlicer] ==========================================
echo [PrusaSlicer] Build complete!
echo [PrusaSlicer] ==========================================
echo.
echo [PrusaSlicer] Binary location: %BUILD_DIR%\src\Release\prusa-slicer.exe
echo.
echo [PrusaSlicer] To use with the agent:
echo   set PRUSA_SLICER_BIN=%BUILD_DIR%\src\Release\prusa-slicer.exe
echo   scripts\run_agent.bat
echo.

endlocal

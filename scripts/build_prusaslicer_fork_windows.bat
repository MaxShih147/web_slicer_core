@echo off
setlocal enabledelayedexpansion

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

echo [PrusaSlicer] Using fork: %FORK_URL% (%FORK_BRANCH%)
echo [PrusaSlicer] Using CMake: %CMAKE_BIN%
echo [PrusaSlicer] Building with SINGLE THREAD

:: Clone or update fork
if not exist "%SRC_DIR%\.git" (
    echo [PrusaSlicer] Cloning fork...
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
    echo [PrusaSlicer] Using single thread - this will take a while...
    echo [PrusaSlicer] ==========================================
    echo.

    if not exist "%DEPS_BUILD_DIR%" mkdir "%DEPS_BUILD_DIR%"
    cd /d "%DEPS_BUILD_DIR%"

    :: Build deps without wxWidgets (headless/CLI mode)
    "%CMAKE_BIN%" .. ^
        -G "Visual Studio 17 2022" ^
        -A x64 ^
        -DCMAKE_BUILD_TYPE=Release ^
        -DPrusaSlicer_deps_PACKAGE_EXCLUDES="wxWidgets"

    if !errorlevel! neq 0 (
        echo [ERROR] CMake configuration failed for dependencies
        exit /b 1
    )

    :: Build with single thread (-j 1)
    "%CMAKE_BIN%" --build . --config Release -- /m:4

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
echo [PrusaSlicer] Using single thread
echo [PrusaSlicer] ==========================================
echo.

if not exist "%BUILD_DIR%" mkdir "%BUILD_DIR%"
cd /d "%BUILD_DIR%"

echo [PrusaSlicer] Configuring build...
"%CMAKE_BIN%" "%SRC_DIR%" ^
    -G "Visual Studio 17 2022" ^
    -A x64 ^
    -DCMAKE_BUILD_TYPE=Release ^
    -DSLIC3R_GUI=OFF ^
    -DSLIC3R_BUILD_TESTS=OFF ^
    -DCMAKE_PREFIX_PATH="%DEPS_DESTDIR%"

if !errorlevel! neq 0 (
    echo [ERROR] CMake configuration failed
    exit /b 1
)

echo [PrusaSlicer] Building with single thread...
"%CMAKE_BIN%" --build . --config Release -- /m:4

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

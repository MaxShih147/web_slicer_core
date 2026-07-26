@echo off
setlocal enabledelayedexpansion

:: ============================================
:: Memory Mode / Flavor / Package Configuration
:: Usage: build_prusaslicer_fork_windows.bat [full|low|qa] [clean|qa|package] [qa|package] [package]
::   full     - 4 parallel projects, /MP enabled (32GB+ RAM)
::   low      - 1 parallel project, /MP disabled (16GB RAM) [default]
::   qa       - same as low but BUNDLE_QA_CRASH_HARNESS=ON
::   clean    - optional; delete build dir and rebuild from scratch
::   package  - optional; after build, run package_slicer_engine_windows.ps1
:: Env (same as macOS): PACKAGE_SLICER_ENGINE=1 also enables packaging [default: off]
:: ============================================
set MEMORY_MODE=%1
if "%MEMORY_MODE%"=="" set MEMORY_MODE=low
set DO_CLEAN_BUILD=0
set BUILD_FLAVOR=consumer
set DO_PACKAGE=0
if /i "%PACKAGE_SLICER_ENGINE%"=="1" set DO_PACKAGE=1
if /i "%1"=="package" set DO_PACKAGE=1
if /i "%2"=="package" set DO_PACKAGE=1
if /i "%3"=="package" set DO_PACKAGE=1
if /i "%4"=="package" set DO_PACKAGE=1
if /i "%2"=="clean" set DO_CLEAN_BUILD=1
if /i "%2"=="qa" set BUILD_FLAVOR=qa
if /i "%3"=="qa" set BUILD_FLAVOR=qa
if /i "%1"=="clean" (
    set DO_CLEAN_BUILD=1
    set MEMORY_MODE=low
)
if /i "%1"=="qa" (
    set BUILD_FLAVOR=qa
    set MEMORY_MODE=low
)
:: "package" as sole/first token is not a memory mode
if /i "%MEMORY_MODE%"=="package" set MEMORY_MODE=low
if /i "%MEMORY_MODE%"=="full" (
    set "MSBUILD_ARGS=/m:4"
    set "SLIC3R_PARALLEL_FLAG=-DSLIC3R_MSVC_COMPILE_PARALLEL=ON"
    echo [CONFIG] Memory mode: FULL - 4 parallel projects, /MP enabled ^(32GB+ RAM^)
) else (
    set MEMORY_MODE=low
    set "MSBUILD_ARGS=/m:1 /p:CL_MPCount=1 /p:UseMultiToolTask=false"
    set "SLIC3R_PARALLEL_FLAG=-DSLIC3R_MSVC_COMPILE_PARALLEL=OFF"
    echo [CONFIG] Memory mode: LOW - 1 parallel project, /MP disabled ^(16GB RAM^)
)
if "!DO_PACKAGE!"=="1" (
    echo [CONFIG] Package after build: ON
) else (
    echo [CONFIG] Package after build: OFF ^(pass 'package' or set PACKAGE_SLICER_ENGINE=1^)
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
echo [PrusaSlicer] Build flags: !MSBUILD_ARGS!

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
:: Disabled: do not switch branch or pull remote updates during build
:: git fetch origin
:: if !errorlevel! neq 0 (
::     echo [ERROR] Failed to fetch from origin
::     exit /b 1
:: )
:: git checkout %FORK_BRANCH%
:: git pull origin %FORK_BRANCH%
for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD 2^>nul') do set CURRENT_BRANCH=%%b
echo [PrusaSlicer] Building on current branch: !CURRENT_BRANCH! ^(fetch/checkout/pull disabled^)

:: ============================================
:: Step 1: Build dependencies (if not already built)
:: ============================================
set DEPS_DESTDIR=%DEPS_BUILD_DIR%\destdir\usr\local
set DEPS_COMPLETE_MARKER=%DEPS_BUILD_DIR%\.deps_complete
set DEPS_TBB_MARKER=%DEPS_DESTDIR%\lib\cmake\TBB\TBBConfig.cmake
set DEPS_OPENVDB_MARKER=%DEPS_DESTDIR%\lib\libopenvdb.lib
set BUILD_DEPS=
set CONFIGURE_DEPS=

if not exist "%DEPS_COMPLETE_MARKER%" (
    if not exist "%DEPS_DESTDIR%" (
        set BUILD_DEPS=1
        set CONFIGURE_DEPS=1
    ) else if not exist "%DEPS_TBB_MARKER%" (
        echo [PrusaSlicer] Dependencies incomplete ^(TBB missing^). Resuming dependency build...
        set BUILD_DEPS=1
        if not exist "%DEPS_BUILD_DIR%\CMakeCache.txt" set CONFIGURE_DEPS=1
    ) else if not exist "%DEPS_OPENVDB_MARKER%" (
        echo [PrusaSlicer] Dependencies incomplete ^(OpenVDB lib missing^). Resuming dependency build...
        set BUILD_DEPS=1
        if not exist "%DEPS_BUILD_DIR%\CMakeCache.txt" set CONFIGURE_DEPS=1
    )
)

if defined BUILD_DEPS (
    echo.
    echo [PrusaSlicer] ==========================================
    echo [PrusaSlicer] Step 1: Building dependencies...
    echo [PrusaSlicer] This may take a while...
    echo [PrusaSlicer] ==========================================
    echo.

    if not exist "%DEPS_BUILD_DIR%" mkdir "%DEPS_BUILD_DIR%"
    cd /d "%DEPS_BUILD_DIR%"

    if defined CONFIGURE_DEPS (
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
    )

    :: Build dependencies
    "%CMAKE_BIN%" --build . --config Release -- !MSBUILD_ARGS!

    if !errorlevel! neq 0 (
        echo [ERROR] Dependencies build failed
        exit /b 1
    )

    if not exist "%DEPS_TBB_MARKER%" (
        echo [ERROR] Dependencies build finished but TBB is still missing at %DEPS_TBB_MARKER%
        exit /b 1
    )
    if not exist "%DEPS_OPENVDB_MARKER%" (
        echo [ERROR] Dependencies build finished but OpenVDB lib is still missing at %DEPS_OPENVDB_MARKER%
        exit /b 1
    )
    echo deps build complete > "%DEPS_COMPLETE_MARKER%"
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

if "!DO_CLEAN_BUILD!"=="1" (
    if exist "%BUILD_DIR%" (
        echo [PrusaSlicer] Clean build requested. Removing %BUILD_DIR% ...
        rmdir /s /q "%BUILD_DIR%"
    )
)

if not exist "%BUILD_DIR%" mkdir "%BUILD_DIR%"
cd /d "%BUILD_DIR%"

:: Remove 0-byte object files left by interrupted or parallel builds (causes LNK1136)
for /r "%BUILD_DIR%" %%f in (*.obj) do (
    if %%~zf equ 0 (
        echo [PrusaSlicer] Removing corrupt 0-byte object: %%f
        del /q "%%f"
    )
)

echo [PrusaSlicer] Configuring build...
:: Flavor already parsed at top (consumer default; qa enables harness).
if /i "!BUILD_FLAVOR!"=="qa" (
    set "QA_HARNESS_FLAG=-DBUNDLE_QA_CRASH_HARNESS=ON"
    set "QA_HARNESS_BOOL=ON"
    echo [CONFIG] Flavor: QA ^(BUNDLE_QA_CRASH_HARNESS=ON^)
) else (
    set "QA_HARNESS_FLAG=-DBUNDLE_QA_CRASH_HARNESS=OFF"
    set "QA_HARNESS_BOOL=OFF"
    echo [CONFIG] Flavor: consumer ^(BUNDLE_QA_CRASH_HARNESS=OFF^)
)
if not exist "%BUILD_DIR%\CMakeCache.txt" (
    set CONFIGURE_SLICER=1
) else (
    findstr /c:"CMAKE_GENERATOR:INTERNAL=%VS_GENERATOR%" "%BUILD_DIR%\CMakeCache.txt" >nul 2>&1
    if !errorlevel! neq 0 set CONFIGURE_SLICER=1
    findstr /c:"BUNDLE_QA_CRASH_HARNESS:BOOL=!QA_HARNESS_BOOL!" "%BUILD_DIR%\CMakeCache.txt" >nul 2>&1
    if !errorlevel! neq 0 set CONFIGURE_SLICER=1
)

if defined CONFIGURE_SLICER (
    "%CMAKE_BIN%" "%SRC_DIR%" ^
        -G "%VS_GENERATOR%" ^
        -A x64 ^
        -DCMAKE_BUILD_TYPE=Release ^
        -DSLIC3R_GUI=OFF ^
        -DSLIC3R_BUILD_TESTS=OFF ^
        !SLIC3R_PARALLEL_FLAG! ^
        !QA_HARNESS_FLAG! ^
        -DCMAKE_PREFIX_PATH="%DEPS_DESTDIR%" ^
        -DCMAKE_FIND_PACKAGE_PREFER_CONFIG=ON ^
        -DIlmBase_DIR="%DEPS_DESTDIR%\lib\cmake\IlmBase" ^
        -DOpenEXR_DIR="%DEPS_DESTDIR%\lib\cmake\OpenEXR"

    if !errorlevel! neq 0 (
        echo [ERROR] CMake configuration failed
        exit /b 1
    )
) else (
    echo [PrusaSlicer] Using existing CMake cache ^(run with 'clean' to reconfigure^)
    "%CMAKE_BIN%" !QA_HARNESS_FLAG! "%BUILD_DIR%"
)

echo [PrusaSlicer] Building PrusaSlicer_app_console...
"%CMAKE_BIN%" --build . --config Release --target PrusaSlicer_app_console -- !MSBUILD_ARGS!

if !errorlevel! neq 0 (
    echo [ERROR] Build failed
    echo [HINT] If you see LNK2001/LNK1136, retry with: %~nx0 %MEMORY_MODE% clean
    exit /b 1
)

:: Windows: OCCTWrapper is a delay-loaded MODULE (not linked into slicer_core), so it is
:: not built as a dependency of PrusaSlicer_app_console. Build it explicitly for STEP/STP.
echo [PrusaSlicer] Building OCCTWrapper ^(STEP/STP plugin^)...
"%CMAKE_BIN%" --build . --config Release --target OCCTWrapper -- !MSBUILD_ARGS!

if !errorlevel! neq 0 (
    echo [ERROR] OCCTWrapper build failed
    echo [HINT] Ensure deps include OpenCASCADE ^(SLIC3R_ENABLE_FORMAT_STEP=ON^)
    exit /b 1
)

set SLICER_BIN=%BUILD_DIR%\src\Release\slicer-engine.exe
set SLICER_DLL=%BUILD_DIR%\src\Release\slicer_core.dll
set OCCT_DLL=%BUILD_DIR%\src\Release\OCCTWrapper.dll
if not exist "%OCCT_DLL%" if exist "%BUILD_DIR%\src\occt_wrapper\Release\OCCTWrapper.dll" (
    copy /Y "%BUILD_DIR%\src\occt_wrapper\Release\OCCTWrapper.dll" "%OCCT_DLL%" >nul
)
if not exist "%SLICER_BIN%" (
    echo [ERROR] Build finished but binary not found at %SLICER_BIN%
    exit /b 1
)
if not exist "%SLICER_DLL%" (
    echo [ERROR] Build finished but DLL not found at %SLICER_DLL%
    exit /b 1
)
if not exist "%OCCT_DLL%" (
    echo [ERROR] Build finished but OCCTWrapper.dll not found at %OCCT_DLL%
    exit /b 1
)

:: Runtime deps required by slicer_core.dll (LoadLibrary error 126 if missing)
set DEPS_BIN=%DEPS_DESTDIR%\bin
if exist "%DEPS_BIN%\libgmp-10.dll" copy /Y "%DEPS_BIN%\libgmp-10.dll" "%BUILD_DIR%\src\Release\" >nul
if exist "%DEPS_BIN%\libmpfr-4.dll" copy /Y "%DEPS_BIN%\libmpfr-4.dll" "%BUILD_DIR%\src\Release\" >nul

echo.
echo [PrusaSlicer] ==========================================
echo [PrusaSlicer] Build complete!
echo [PrusaSlicer] ==========================================
echo.
echo [PrusaSlicer] Binary: %SLICER_BIN%
echo [PrusaSlicer] DLL:    %SLICER_DLL%
echo [PrusaSlicer] OCCT:   %OCCT_DLL%
echo [PrusaSlicer] Flavor: !BUILD_FLAVOR! ^(BUNDLE_QA_CRASH_HARNESS=!QA_HARNESS_BOOL!^)
if /i "!BUILD_FLAVOR!"=="qa" (
    echo [PrusaSlicer] QA mode: set BUNDLE_QA_CRASH_MODE=overflow^|segfault^|exception
) else (
    echo [PrusaSlicer] Consumer: static harness symbols must be absent ^(tasks 5.6/5.7^)
)
echo.

set PACKAGED=0
if "!DO_PACKAGE!"=="1" (
    echo [PrusaSlicer] ==========================================
    echo [PrusaSlicer] Step 3: Packaging slicer-engine ^(!BUILD_FLAVOR!^)...
    echo [PrusaSlicer] ==========================================
    echo.
    if /i "!BUILD_FLAVOR!"=="qa" (
        set "PKG_OUT=%ROOT_DIR%\slicer-engine-qa"
        set "PKG_EQ="
        if exist "%ROOT_DIR%\slicer-engine\engine_build_id.txt" (
            set /p PKG_EQ=<"%ROOT_DIR%\slicer-engine\engine_build_id.txt"
        )
        if defined PKG_EQ (
            powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT_DIR%\scripts\package_slicer_engine_windows.ps1" -Flavor qa -OutRoot "!PKG_OUT!" -ConsumerEquivalentBuildId "!PKG_EQ!"
        ) else (
            powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT_DIR%\scripts\package_slicer_engine_windows.ps1" -Flavor qa -OutRoot "!PKG_OUT!"
        )
    ) else (
        powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT_DIR%\scripts\package_slicer_engine_windows.ps1" -Flavor consumer
    )
    if !errorlevel! neq 0 (
        echo [ERROR] Packaging failed
        exit /b 1
    )
    set PACKAGED=1
)

if "!PACKAGED!"=="1" (
    if /i "!BUILD_FLAVOR!"=="qa" (
        echo [PrusaSlicer] Packaged QA: %ROOT_DIR%\slicer-engine-qa\bin\slicer-engine.exe
        echo [PrusaSlicer] To use packaged agent binary:
        echo   set SLICER_ENGINE_BIN=%ROOT_DIR%\slicer-engine-qa\bin\slicer-engine.exe
    ) else (
        echo [PrusaSlicer] Packaged: %ROOT_DIR%\slicer-engine\bin\slicer-engine.exe
        echo [PrusaSlicer] To use packaged agent binary:
        echo   set SLICER_ENGINE_BIN=%ROOT_DIR%\slicer-engine\bin\slicer-engine.exe
    )
) else (
    echo [PrusaSlicer] Packaging skipped ^(default OFF^). Enable with:
    echo   %~nx0 %MEMORY_MODE% package
    echo   or: set PACKAGE_SLICER_ENGINE=1 ^&^& %~nx0
    echo.
    echo [PrusaSlicer] Manual package:
    echo   powershell -File scripts\package_slicer_engine_windows.ps1
)
echo.
echo [PrusaSlicer] Dev build tree binary:
echo   set SLICER_ENGINE_BIN=%SLICER_BIN%
echo   scripts\run_agent.bat
echo.

endlocal

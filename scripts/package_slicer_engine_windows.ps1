#Requires -Version 5.1
<#
.SYNOPSIS
  Stage consumer slicer-engine layout for Windows (tasks 5.3 / 5.4 / D13).

.DESCRIPTION
  Copies slicer-engine.exe + slicer_core.dll (+ runtime DLLs) into
  <RepoRoot>/slicer-engine/bin/, archives PDBs under symbols/, writes
  artifact-manifest.json with pre/post hashes, and verifies:
    - named exports == 1 (slicer_run_cli)
    - no BUNDLE_QA_CRASH harness markers in consumer PE strings
    - no *.pdb in consumer staging
#>
param(
    [string]$BuildReleaseDir = "",
    [string]$OutRoot = "",
    [string]$Flavor = "consumer",
    [switch]$SkipDumpbin
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $BuildReleaseDir) {
    $BuildReleaseDir = Join-Path $RepoRoot "third_party\prusaslicer_build\src\Release"
}
if (-not $OutRoot) {
    $OutRoot = Join-Path $RepoRoot "slicer-engine"
}

$BinDir = Join-Path $OutRoot "bin"
$SymbolDir = Join-Path $OutRoot "symbols"
$ManifestPath = Join-Path $OutRoot "artifact-manifest.json"

function Get-Sha256([string]$Path) {
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Find-Dumpbin {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path $vswhere) {
        $vsPath = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
        if ($vsPath) {
            $candidate = Get-ChildItem -Path (Join-Path $vsPath "VC\Tools\MSVC") -Directory -ErrorAction SilentlyContinue |
                Sort-Object Name -Descending |
                ForEach-Object { Join-Path $_.FullName "bin\Hostx64\x64\dumpbin.exe" } |
                Where-Object { Test-Path $_ } |
                Select-Object -First 1
            if ($candidate) { return $candidate }
        }
    }
    return $null
}

Write-Host "=== package_slicer_engine_windows ===" -ForegroundColor Cyan
Write-Host "Source: $BuildReleaseDir"
Write-Host "Output: $OutRoot"

$exeSrc = Join-Path $BuildReleaseDir "slicer-engine.exe"
$dllSrc = Join-Path $BuildReleaseDir "slicer_core.dll"
if (-not (Test-Path $exeSrc)) { throw "Missing $exeSrc — build with scripts\build_prusaslicer_fork_windows.bat first" }
if (-not (Test-Path $dllSrc)) { throw "Missing $dllSrc" }

$preExe = Get-Sha256 $exeSrc
$preDll = Get-Sha256 $dllSrc

if (Test-Path $OutRoot) { Remove-Item -Recurse -Force $OutRoot }
New-Item -ItemType Directory -Path $BinDir -Force | Out-Null
New-Item -ItemType Directory -Path $SymbolDir -Force | Out-Null

# Runtime PE + dependency DLLs (exclude pdb / brand leftovers)
Get-ChildItem -LiteralPath $BuildReleaseDir -File | ForEach-Object {
    $name = $_.Name
    if ($name -match '\.pdb$') { return }
    if ($name -match '^(prusa-slicer|PrusaSlicer|prusa-gcodeviewer)') {
        Write-Host "SKIP brand leftover: $name" -ForegroundColor Yellow
        return
    }
    if ($name -match '\.(exe|dll)$') {
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $BinDir $name) -Force
    }
}

# GMP/MPFR runtime DLLs (LoadLibrary fails with 126 without these)
$depsBin = Join-Path $RepoRoot "third_party\prusaslicer_fork\deps\build\destdir\usr\local\bin"
foreach ($depDll in @("libgmp-10.dll", "libmpfr-4.dll")) {
    $src = Join-Path $depsBin $depDll
    if (Test-Path $src) {
        Copy-Item -LiteralPath $src -Destination (Join-Path $BinDir $depDll) -Force
        # Also keep next to Release for local smoke tests
        Copy-Item -LiteralPath $src -Destination (Join-Path $BuildReleaseDir $depDll) -Force
    } else {
        Write-Host "WARN: missing runtime dependency $src" -ForegroundColor Yellow
    }
}

# Resources next to exe (same layout as Release/)
$resSrc = Join-Path $BuildReleaseDir "resources"
$resDst = Join-Path $BinDir "resources"
$forkRes = Join-Path $RepoRoot "third_party\prusaslicer_fork\resources"
if (Test-Path $resSrc) {
    if ((Get-Item $resSrc).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        # Junction → copy real tree from fork resources
        if (Test-Path $forkRes) {
            robocopy $forkRes $resDst /E /NFL /NDL /NJH /NJS | Out-Null
            if ($LASTEXITCODE -ge 8) { throw "Failed to copy resources from fork" }
        }
    } else {
        robocopy $resSrc $resDst /E /NFL /NDL /NJH /NJS | Out-Null
        if ($LASTEXITCODE -ge 8) { throw "Failed to copy resources" }
    }
} elseif (Test-Path $forkRes) {
    robocopy $forkRes $resDst /E /NFL /NDL /NJH /NJS | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Failed to copy resources from fork" }
}

# Archive PDBs for symbol store (not in consumer bin)
Get-ChildItem -LiteralPath $BuildReleaseDir -Filter "*.pdb" -File -ErrorAction SilentlyContinue | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $SymbolDir $_.Name) -Force
}

$exeDst = Join-Path $BinDir "slicer-engine.exe"
$dllDst = Join-Path $BinDir "slicer_core.dll"
if (-not (Test-Path $exeDst)) { throw "Staging missing slicer-engine.exe" }
if (-not (Test-Path $dllDst)) { throw "Staging missing slicer_core.dll" }

$postExe = Get-Sha256 $exeDst
$postDll = Get-Sha256 $dllDst

# Export gate
$exportCount = -1
$hasRunCli = $false
$hasSlic3rMain = $false
if (-not $SkipDumpbin) {
    $dumpbin = Find-Dumpbin
    if (-not $dumpbin) {
        Write-Host "WARN: dumpbin.exe not found; export gate skipped" -ForegroundColor Yellow
    } else {
        $exportsTxt = & $dumpbin /EXPORTS $dllDst 2>&1 | Out-String
        $exportsPath = Join-Path $OutRoot "EXPORTS.txt"
        Set-Content -LiteralPath $exportsPath -Value $exportsTxt -Encoding utf8
        $named = [regex]::Matches($exportsTxt, '(?m)^\s+\d+\s+[0-9A-F]+\s+[0-9A-F]+\s+(\S+)\s*$') |
            ForEach-Object { $_.Groups[1].Value }
        # dumpbin also lists ordinal-only; prefer "number of names"
        if ($exportsTxt -match '(\d+)\s+number of names') {
            $exportCount = [int]$Matches[1]
        } else {
            $exportCount = @($named | Where-Object { $_ -and $_ -notmatch '^\?' }).Count
        }
        $hasRunCli = $exportsTxt -match 'slicer_run_cli'
        $hasSlic3rMain = $exportsTxt -match 'slic3r_main'
        Write-Host "Exports: count=$exportCount slicer_run_cli=$hasRunCli slic3r_main=$hasSlic3rMain"
        if ($exportCount -ne 1 -or -not $hasRunCli -or $hasSlic3rMain) {
            throw "Export gate FAILED (want exactly 1 named export: slicer_run_cli). See $exportsPath"
        }
        if ($exportsTxt -match 'Slic3r|slic3r|Prusa|prusa') {
            # slicer_run_cli itself is fine; brand tokens elsewhere fail
            $brandHits = [regex]::Matches($exportsTxt, '(?i)Slic3r|slic3r_main|PrusaSlicer|prusa')
            if ($brandHits.Count -gt 0) {
                throw "Export table still contains brand tokens"
            }
        }
    }
}

# Consumer harness static audit (5.6 / 5.7)
if ($Flavor -eq "consumer") {
    $bytes = [System.IO.File]::ReadAllBytes($dllDst)
    $ascii = [System.Text.Encoding]::ASCII.GetString($bytes)
    foreach ($marker in @("BUNDLE_QA_CRASH_HARNESS", "bundle_qa_crash_probe", "BundleQa::maybe_force_crash", "BUNDLE_QA_CRASH_MODE")) {
        if ($ascii.Contains($marker)) {
            throw "Consumer harness audit FAILED: found '$marker' in slicer_core.dll"
        }
    }
    Write-Host "Consumer harness audit: PASS" -ForegroundColor Green
}

# No pdb in bin
$pdbInBin = Get-ChildItem -LiteralPath $BinDir -Filter "*.pdb" -Recurse -ErrorAction SilentlyContinue
if ($pdbInBin) { throw "Consumer bin must not contain PDB files" }

$buildId = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$manifest = [ordered]@{
    schema_version = "1.0"
    build_id       = $buildId
    flavor         = $Flavor
    platform       = "windows-x64"
    files          = @(
        [ordered]@{
            path              = "bin/slicer-engine.exe"
            pre_strip_sha256  = $preExe
            post_strip_sha256 = $postExe
        },
        [ordered]@{
            path              = "bin/slicer_core.dll"
            pre_strip_sha256  = $preDll
            post_strip_sha256 = $postDll
            named_exports     = $exportCount
            export_entry      = "slicer_run_cli"
        }
    )
    symbols_archived = @(Get-ChildItem -LiteralPath $SymbolDir -Filter "*.pdb" -ErrorAction SilentlyContinue | ForEach-Object { $_.Name })
    notes            = "Windows PE: pre/post hash equal when no post-link rewrite; PDB excluded from bin."
}

$manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $ManifestPath -Encoding utf8
Write-Host "Wrote $ManifestPath" -ForegroundColor Green
Write-Host "Consumer staging ready: $BinDir" -ForegroundColor Green
Write-Host "Set SLICER_ENGINE_BIN=$exeDst"

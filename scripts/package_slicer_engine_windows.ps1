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
    [ValidateSet("consumer", "qa")]
    [string]$Flavor = "consumer",
    [string]$ConsumerEquivalentBuildId = "",
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
$ManifestPath = Join-Path $OutRoot "engine-artifact-manifest.json"
$ManifestAliasPath = Join-Path $OutRoot "artifact-manifest.json"

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

# Resources next to exe — de-branded filter (macOS parity: stage_slicer_engine_resources_*.sh/ps1)
$stageResPs1 = Join-Path $PSScriptRoot "stage_slicer_engine_resources_windows.ps1"
if (-not (Test-Path -LiteralPath $stageResPs1)) {
    throw "Missing resources staging script: $stageResPs1"
}
& powershell -NoProfile -ExecutionPolicy Bypass -File $stageResPs1 -ArtifactRoot $OutRoot
if ($LASTEXITCODE -ne 0) { throw "stage_slicer_engine_resources_windows.ps1 FAILED" }

# Archive only neutral engine PDBs for symbol store (not in consumer bin; skip brand leftovers)
foreach ($pdbName in @("slicer-engine.pdb", "slicer_core.pdb")) {
    $pdbSrc = Join-Path $BuildReleaseDir $pdbName
    if (Test-Path $pdbSrc) {
        Copy-Item -LiteralPath $pdbSrc -Destination (Join-Path $SymbolDir $pdbName) -Force
    }
}

# AGPL legal pack (REQ-DEID-011 / tasks 6.2–6.3) — must ship with consumer artifact
$LegalSrc = Join-Path $RepoRoot "legal\slicer-engine"
$LegalDst = Join-Path $OutRoot "legal"
$LicenseSrc = Join-Path $RepoRoot "third_party\prusaslicer_fork\LICENSE"
New-Item -ItemType Directory -Path $LegalDst -Force | Out-Null
if (-not (Test-Path $LicenseSrc)) { throw "Missing AGPL LICENSE at $LicenseSrc" }
Copy-Item -LiteralPath $LicenseSrc -Destination (Join-Path $LegalDst "LICENSE") -Force
foreach ($doc in @("NOTICE.md", "SOURCE_OFFER.md")) {
    $src = Join-Path $LegalSrc $doc
    if (-not (Test-Path $src)) { throw "Missing legal pack file: $src" }
    Copy-Item -LiteralPath $src -Destination (Join-Path $LegalDst $doc) -Force
}
Write-Host "AGPL legal pack staged: $LegalDst" -ForegroundColor Green

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
$engineCommit = "unknown"
try {
    Push-Location $RepoRoot
    $engineCommit = (git rev-parse HEAD 2>$null)
    if (-not $engineCommit) { $engineCommit = "unknown" }
} finally {
    Pop-Location
}

$archivedPdbs = @(Get-ChildItem -LiteralPath $SymbolDir -Filter "*.pdb" -ErrorAction SilentlyContinue | ForEach-Object { $_.Name })
$manifest = [ordered]@{
    schema_version   = "1.0"
    engine_commit    = "$engineCommit".Trim()
    engine_build_id  = $buildId
    build_id         = $buildId  # alias for older consumers
    flavor           = $Flavor
    platform         = "Windows"
    architecture     = "x64"
    created_at_utc   = (Get-Date).ToUniversalTime().ToString("o")
    pre_strip_sha256 = $preExe   # primary engine CLI (shim)
    post_strip_sha256 = $postExe
    files            = @(
        [ordered]@{
            path              = "bin/slicer-engine.exe"
            role              = "shim"
            pre_strip_sha256  = $preExe
            post_strip_sha256 = $postExe
            sha256            = $postExe
        },
        [ordered]@{
            path              = "bin/slicer_core.dll"
            role              = "engine_dll"
            pre_strip_sha256  = $preDll
            post_strip_sha256 = $postDll
            sha256            = $postDll
            named_exports     = $exportCount
            export_entry      = "slicer_run_cli"
        }
    )
    symbol_archive = [ordered]@{
        kind           = $(if ($archivedPdbs.Count -gt 0) { "PDB" } else { "none" })
        archived_files = $archivedPdbs
    }
    identity = [ordered]@{
        windows_original_filename = "slicer-engine.exe"
        product_version           = "Slicer Engine"
    }
    qa_delta = $(if ($Flavor -eq "qa") {
            [ordered]@{
                harness_compile_flag            = "BUNDLE_QA_CRASH_HARNESS"
                only_differences                = @("compile-time crash harness sites")
                consumer_equivalent_build_id    = $(if ($ConsumerEquivalentBuildId) { $ConsumerEquivalentBuildId } else { "" })
            }
        } else { $null })
    approvals = [ordered]@{
        naming_manifest_version = "1.3"
    }
    notes = "Windows PE: pre/post hash equal when no post-link rewrite; PDB excluded from bin. Authenticode is manual (Launcher does not sign)."
}

$json = $manifest | ConvertTo-Json -Depth 8
Set-Content -LiteralPath $ManifestPath -Value $json -Encoding utf8
Copy-Item -LiteralPath $ManifestPath -Destination $ManifestAliasPath -Force
Write-Host "Wrote $ManifestPath (alias: $ManifestAliasPath)" -ForegroundColor Green

# 6.5 — neutral build ID sidecar (CLI has no --version)
$writeIdPs1 = Join-Path $PSScriptRoot "write_engine_build_id_windows.ps1"
& powershell -NoProfile -ExecutionPolicy Bypass -File $writeIdPs1 -ArtifactRoot $OutRoot
if ($LASTEXITCODE -ne 0) { throw "write_engine_build_id_windows.ps1 FAILED" }

# 6.4 — SPDX 2.3 SBOM + source-chain.json
$sbomPs1 = Join-Path $PSScriptRoot "generate_slicer_engine_sbom_windows.ps1"
& powershell -NoProfile -ExecutionPolicy Bypass -File $sbomPs1 -ArtifactRoot $OutRoot
if ($LASTEXITCODE -ne 0) { throw "generate_slicer_engine_sbom_windows.ps1 FAILED" }

# Fail-closed formal scan (same gate Launcher will re-run)
$scanPs1 = Join-Path $PSScriptRoot "scan_slicer_engine_windows.ps1"
if (Test-Path $scanPs1) {
    Write-Host "`n=== Running scan_slicer_engine_windows (fail closed) ===" -ForegroundColor Cyan
    & powershell -NoProfile -ExecutionPolicy Bypass -File $scanPs1 -ArtifactRoot $OutRoot -ExpectFlavor $Flavor
    if ($LASTEXITCODE -ne 0) { throw "scan_slicer_engine_windows.ps1 FAILED" }
} else {
    Write-Host "WARN: scan script missing at $scanPs1" -ForegroundColor Yellow
}

Write-Host "Consumer staging ready: $BinDir" -ForegroundColor Green
Write-Host "Set SLICER_ENGINE_BIN=$exeDst"

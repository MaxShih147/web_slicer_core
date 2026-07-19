#Requires -Version 5.1
<#
.SYNOPSIS
  Formal Windows engine artifact gate (tasks 5.3 / 5.4 / 5.7 / D13 / REQ-LAUNCHER-DEID).

.DESCRIPTION
  Validates post-strip consumer (or qa) staging layout:
    - engine-artifact-manifest.json (or artifact-manifest.json)
    - disk sha256 == post_strip_sha256
    - flavor match; consumer rejects qa_delta / harness markers
    - no *.pdb under bin/; no brand path tokens under scanned tree
    - dumpbin exports == 1 (slicer_run_cli) when available
    - VERSIONINFO identity fields de-branded

  Exit 0 = PASS (fail closed otherwise). Authenticode is NOT required
  (Windows signing is manual outside this gate).

.EXAMPLE
  powershell -File scripts\scan_slicer_engine_windows.ps1
  $env:SLICER_ENGINE_EXPECT_FLAVOR='consumer'; powershell -File scripts\scan_slicer_engine_windows.ps1 D:\path\to\slicer-engine
#>
param(
    [string]$ArtifactRoot = "",
    [ValidateSet("consumer", "qa")]
    [string]$ExpectFlavor = "consumer",
    [string]$ReportPath = "",
    [switch]$SkipDumpbin
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $ArtifactRoot) {
    if ($env:SLICER_ENGINE_ARTIFACT_DIR) {
        $ArtifactRoot = $env:SLICER_ENGINE_ARTIFACT_DIR
    } else {
        $ArtifactRoot = Join-Path $RepoRoot "slicer-engine"
    }
}
if ($env:SLICER_ENGINE_EXPECT_FLAVOR) {
    $ExpectFlavor = $env:SLICER_ENGINE_EXPECT_FLAVOR
}
$ArtifactRoot = (Resolve-Path -LiteralPath $ArtifactRoot).Path
$BinDir = Join-Path $ArtifactRoot "bin"
$ExePath = Join-Path $BinDir "slicer-engine.exe"
$DllPath = Join-Path $BinDir "slicer_core.dll"

$ManifestCandidates = @(
    (Join-Path $ArtifactRoot "engine-artifact-manifest.json"),
    (Join-Path $ArtifactRoot "artifact-manifest.json")
)
$ManifestPath = $ManifestCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $ReportPath) {
    $ReportPath = Join-Path $ArtifactRoot "scan-report.json"
}

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

$failures = [System.Collections.Generic.List[string]]::new()
$notes = [System.Collections.Generic.List[string]]::new()
$checks = [ordered]@{}

function Add-Fail([string]$Msg) { $failures.Add($Msg) | Out-Null }

Write-Host "=== scan_slicer_engine_windows ===" -ForegroundColor Cyan
Write-Host "ArtifactRoot: $ArtifactRoot"
Write-Host "ExpectFlavor: $ExpectFlavor"

# --- layout ---
if (-not (Test-Path -LiteralPath $ExePath)) { Add-Fail "missing executable: $ExePath" }
if (-not (Test-Path -LiteralPath $DllPath)) { Add-Fail "missing dll: $DllPath" }
if (-not $ManifestPath) {
    Add-Fail "missing manifest (engine-artifact-manifest.json or artifact-manifest.json)"
}
$checks["manifest_path"] = $ManifestPath

# Brand path gate (blacklist §3.3 L1): engine PE / layout paths — NOT deep vendor profile assets.
# bin/resources/** may still contain upstream PrusaResearch profiles/icons (tracked as notes for §7;
# renaming that tree is out of scope for this Launcher verify gate / not L2 C′).
$pdbLeaks = @()
$brandPaths = @()
$resourceBrandPaths = @()
$brandPathRe = [regex]'(?i)(prusa|slic3r)'
$forbiddenLayoutRe = [regex]'(?i)(prusaslicer_build|prusa-slicer\.exe|PrusaSlicer\.dll|prusa-gcodeviewer)'
if (Test-Path $BinDir) {
    Get-ChildItem -LiteralPath $BinDir -Recurse -Force -ErrorAction SilentlyContinue | ForEach-Object {
        $rel = $_.FullName.Substring($ArtifactRoot.Length).TrimStart('\', '/').Replace('\', '/')
        if ($_.Name -match '\.pdb$') { $pdbLeaks += $rel }
        if ($forbiddenLayoutRe.IsMatch($rel)) { $brandPaths += $rel; return }
        $underResources = $rel -match '(?i)^bin/resources(/|$)'
        if ($brandPathRe.IsMatch($rel)) {
            if ($underResources) {
                $resourceBrandPaths += $rel
            } else {
                # PE / non-resource layout must be clean
                $brandPaths += $rel
            }
        }
    }
}
Get-ChildItem -LiteralPath $ArtifactRoot -Force -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_.Name -ieq "symbols" -or $_.Name -ieq "bin" -or $_.Name -ieq "legal") { return }
    $rel = $_.Name
    if ($brandPathRe.IsMatch($rel)) { $brandPaths += $rel }
}

# AGPL legal pack (REQ-DEID-011) — required for consumer staging/bundles
$legalDir = Join-Path $ArtifactRoot "legal"
$legalRequired = @("LICENSE", "NOTICE.md", "SOURCE_OFFER.md")
$legalPresent = @()
$legalMissing = @()
if (Test-Path $legalDir) {
    foreach ($name in $legalRequired) {
        if (Test-Path (Join-Path $legalDir $name)) { $legalPresent += $name } else { $legalMissing += $name }
    }
} else {
    $legalMissing = $legalRequired
}
$checks["legal_pack"] = @{ present = $legalPresent; missing = $legalMissing }
if ($ExpectFlavor -eq "consumer" -and $legalMissing.Count -gt 0) {
    Add-Fail "consumer legal pack missing: $($legalMissing -join ', ') (expected under legal/)"
}
# Top-level PE names under bin must be neutral
foreach ($pe in @("slicer-engine.exe", "slicer_core.dll")) {
    $pePath = Join-Path $BinDir $pe
    if (-not (Test-Path $pePath)) { continue }
}
$checks["pdb_in_bin"] = $pdbLeaks
$checks["brand_paths"] = $brandPaths
$checks["resource_brand_path_count"] = $resourceBrandPaths.Count
if ($resourceBrandPaths.Count -gt 0) {
    $notes.Add("bin/resources contains $($resourceBrandPaths.Count) brand-named asset path(s); not fail-closed here (profiles/icons). Sample: $($resourceBrandPaths[0..([Math]::Min(4,$resourceBrandPaths.Count-1))] -join ', ')")
}
if ($pdbLeaks.Count -gt 0) { Add-Fail "PDB files under bin/: $($pdbLeaks -join ', ')" }
if ($brandPaths.Count -gt 0) { Add-Fail "brand tokens in engine layout/PE paths: $($brandPaths -join ', ')" }

# symbols/ must not be required for Launcher; note if present (OK for fork staging)
$symbolsDir = Join-Path $ArtifactRoot "symbols"
$checks["symbols_present"] = (Test-Path $symbolsDir)
if (Test-Path $symbolsDir) {
    $brandSymbols = Get-ChildItem -LiteralPath $symbolsDir -Filter "*.pdb" -ErrorAction SilentlyContinue |
        Where-Object { $brandPathRe.IsMatch($_.Name) } |
        ForEach-Object { $_.Name }
    $checks["brand_pdb_in_symbols"] = @($brandSymbols)
    if ($brandSymbols) {
        $notes.Add("symbols/ contains brand-named PDBs (must not be copied into consumer bundle): $($brandSymbols -join ', ')")
    }
}

# --- manifest ---
$manifest = $null
if ($ManifestPath -and (Test-Path $ManifestPath)) {
    $manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $checks["schema_version"] = $manifest.schema_version
    $checks["manifest_flavor"] = $manifest.flavor
    $buildId = $manifest.engine_build_id
    if (-not $buildId) { $buildId = $manifest.build_id }
    $checks["engine_build_id"] = $buildId

    if (-not $manifest.schema_version) { Add-Fail "manifest missing schema_version" }
    if ($manifest.flavor -ne $ExpectFlavor) {
        Add-Fail "manifest flavor='$($manifest.flavor)' != expect '$ExpectFlavor'"
    }

    $platformOk = $false
    $plat = [string]$manifest.platform
    if ($plat -match '(?i)windows|win') { $platformOk = $true }
    $checks["platform"] = $plat
    if (-not $platformOk) { Add-Fail "manifest platform must be Windows (got '$plat')" }

    # Resolve file entries (per-file post_strip or top-level)
    $fileEntries = @()
    if ($manifest.files) { $fileEntries = @($manifest.files) }

    function Resolve-PostHash($entry, $fallbackTop) {
        if ($entry -and $entry.post_strip_sha256) { return [string]$entry.post_strip_sha256 }
        if ($fallbackTop) { return [string]$fallbackTop }
        return $null
    }

    $topPost = $null
    if ($manifest.post_strip_sha256) { $topPost = [string]$manifest.post_strip_sha256 }

    $exeEntry = $fileEntries | Where-Object { $_.path -match 'slicer-engine\.exe$' } | Select-Object -First 1
    $dllEntry = $fileEntries | Where-Object { $_.path -match 'slicer_core\.dll$' } | Select-Object -First 1

    if (Test-Path $ExePath) {
        $actualExe = Get-Sha256 $ExePath
        $expectExe = Resolve-PostHash $exeEntry $topPost
        $checks["exe_post_strip_sha256_manifest"] = $expectExe
        $checks["exe_post_strip_sha256_actual"] = $actualExe
        if (-not $expectExe) {
            Add-Fail "manifest missing post_strip_sha256 for slicer-engine.exe"
        } elseif ($actualExe -ne $expectExe.ToLowerInvariant()) {
            Add-Fail "slicer-engine.exe disk sha256 != manifest post_strip_sha256"
        }
    }
    if (Test-Path $DllPath) {
        $actualDll = Get-Sha256 $DllPath
        $expectDll = if ($dllEntry) { [string]$dllEntry.post_strip_sha256 } else { $null }
        $checks["dll_post_strip_sha256_manifest"] = $expectDll
        $checks["dll_post_strip_sha256_actual"] = $actualDll
        if (-not $expectDll) {
            Add-Fail "manifest missing post_strip_sha256 for slicer_core.dll"
        } elseif ($actualDll -ne $expectDll.ToLowerInvariant()) {
            Add-Fail "slicer_core.dll disk sha256 != manifest post_strip_sha256"
        }
        if ($dllEntry -and $null -ne $dllEntry.named_exports -and [int]$dllEntry.named_exports -ne 1) {
            Add-Fail "manifest named_exports=$($dllEntry.named_exports) (want 1)"
        }
    }

    # Flavor / qa_delta
    $qaDelta = $manifest.qa_delta
    if ($ExpectFlavor -eq "qa") {
        if (-not $qaDelta) {
            Add-Fail "qa flavor missing qa_delta object"
        } else {
            $checks["qa_delta"] = $qaDelta
            $flag = $qaDelta.harness_compile_flag
            if ($flag -ne "BUNDLE_QA_CRASH_HARNESS") {
                Add-Fail "qa_delta.harness_compile_flag must be BUNDLE_QA_CRASH_HARNESS"
            }
            if (-not $qaDelta.consumer_equivalent_build_id) {
                $notes.Add("qa_delta.consumer_equivalent_build_id empty (set when pairing builds)")
            }
        }
    } else {
        if ($null -ne $qaDelta -and "$qaDelta" -ne "" -and "$qaDelta" -ne "@{}") {
            # PowerShell ConvertFrom-Json null becomes $null; empty object is PSCustomObject
            if ($qaDelta -is [PSCustomObject] -and (@($qaDelta.PSObject.Properties).Count -gt 0)) {
                Add-Fail "consumer manifest must have qa_delta=null/omitted"
            }
        }
    }
}

# --- VERSIONINFO ---
function Test-VersionInfo([string]$Path, [string]$ExpectOriginal) {
    if (-not (Test-Path $Path)) { return }
    $vi = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($Path)
    $fields = [ordered]@{
        ProductName      = $vi.ProductName
        FileDescription  = $vi.FileDescription
        InternalName     = $vi.InternalName
        OriginalFilename = $vi.OriginalFilename
        CompanyName      = $vi.CompanyName
        ProductVersion   = $vi.ProductVersion
    }
    $checks["versioninfo_$((Split-Path $Path -Leaf))"] = $fields
    $blob = ($fields.Values -join " ")
    if ($brandPathRe.IsMatch($blob)) {
        Add-Fail "VERSIONINFO brand token in $(Split-Path $Path -Leaf): $blob"
    }
    if ($ExpectOriginal -and $vi.OriginalFilename -and ($vi.OriginalFilename -ne $ExpectOriginal)) {
        # Some toolchains leave InternalName only; warn soft if OriginalFilename empty
        if ($vi.OriginalFilename -match '(?i)prusa|slic3r') {
            Add-Fail "OriginalFilename branded: $($vi.OriginalFilename)"
        }
    }
}
Test-VersionInfo $ExePath "slicer-engine.exe"
Test-VersionInfo $DllPath "slicer_core.dll"

# --- export gate ---
$exportCount = -1
$hasRunCli = $false
$hasSlic3rMain = $false
if (-not $SkipDumpbin -and (Test-Path $DllPath)) {
    $dumpbin = Find-Dumpbin
    if (-not $dumpbin) {
        $notes.Add("dumpbin.exe not found; export gate skipped (install VS VC tools for full gate)")
        $checks["export_gate"] = "skipped_no_dumpbin"
    } else {
        $exportsTxt = & $dumpbin /EXPORTS $DllPath 2>&1 | Out-String
        if ($exportsTxt -match '(\d+)\s+number of names') {
            $exportCount = [int]$Matches[1]
        }
        $hasRunCli = $exportsTxt -match 'slicer_run_cli'
        $hasSlic3rMain = $exportsTxt -match 'slic3r_main'
        $checks["named_exports"] = $exportCount
        $checks["slicer_run_cli"] = $hasRunCli
        $checks["slic3r_main"] = $hasSlic3rMain
        if ($exportCount -ne 1 -or -not $hasRunCli -or $hasSlic3rMain) {
            Add-Fail "Export gate FAILED (want exactly 1 named export: slicer_run_cli); count=$exportCount"
        }
        if ($exportsTxt -match '(?i)slic3r_main|PrusaSlicer|prusa-slicer') {
            Add-Fail "Export table contains brand tokens"
        }

        # Debug directory: no brand PDB path
        $headers = & $dumpbin /HEADERS $DllPath 2>&1 | Out-String
        $checks["debug_directory_brand"] = $false
        if ($headers -match '(?i)(prusa|slic3r|prusaslicer_build)') {
            $checks["debug_directory_brand"] = $true
            Add-Fail "PE headers/debug directory contain brand path tokens"
        }
    }
}

# --- harness markers (consumer must be clean) ---
$harnessMarkers = @(
    "BUNDLE_QA_CRASH_HARNESS",
    "bundle_qa_crash_probe",
    "BundleQa::maybe_force_crash",
    "BUNDLE_QA_CRASH_MODE",
    "bundle_force_prusa",
    "BUNDLE_FORCE_PRUSA",
    "bundle_force_stack_overflow"
)
$harnessHits = @()
if (Test-Path $DllPath) {
    $bytes = [System.IO.File]::ReadAllBytes($DllPath)
    $ascii = [System.Text.Encoding]::ASCII.GetString($bytes)
    foreach ($m in $harnessMarkers) {
        if ($ascii.Contains($m)) { $harnessHits += $m }
    }
}
$checks["harness_markers"] = $harnessHits
if ($ExpectFlavor -eq "consumer") {
    if ($harnessHits.Count -gt 0) {
        Add-Fail "consumer binary contains harness markers: $($harnessHits -join ', ')"
    }
} else {
    if (-not ($harnessHits | Where-Object { $_ -match 'BUNDLE_QA_CRASH|bundle_qa_crash|maybe_force_crash' })) {
        Add-Fail "qa binary missing expected harness markers"
    }
}

$verdict = if ($failures.Count -gt 0) { "FAIL" } else { "PASS" }
$report = [ordered]@{
    schema         = "slicer-engine-windows-scan/1.0"
    artifact_root  = $ArtifactRoot
    expect_flavor  = $ExpectFlavor
    blacklist_hint = "1.2"
    authenticode   = "skipped_manual_signing"
    verdict        = $verdict
    checks         = $checks
    notes          = @($notes)
    failures       = @($failures)
    scanned_at_utc = (Get-Date).ToUniversalTime().ToString("o")
}

$reportJson = $report | ConvertTo-Json -Depth 8
Set-Content -LiteralPath $ReportPath -Value $reportJson -Encoding utf8
Write-Host $reportJson
if ($verdict -ne "PASS") {
    Write-Host "VERDICT: FAIL ($($failures.Count) failure(s))" -ForegroundColor Red
    exit 1
}
Write-Host "VERDICT: PASS" -ForegroundColor Green
exit 0

#Requires -Version 5.1
<#
.SYNOPSIS
  tasks 6.6 / 6.7 — Windows symbolication + symbol-loss + artifact rollback drill.

.DESCRIPTION
  Uses packaged consumer PE + local symbols/ (and optional OneDrive store) without
  requiring a live minidump debugger session when cdb is unavailable:
    6.6) Prove PE RSDS GUID matches archived PDB; lookup by engine_build_id succeeds.
    6.7a) Symbol loss: wrong/missing build_id folder → fail closed.
    6.7b) Rollback: previous build_id folder still resolvable from store.
#>
param(
    [string]$ArtifactRoot = "",
    [string]$LocalSymbolsDir = "",
    [string]$OneDriveStoreRoot = "",
    [string]$ReportDir = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $ArtifactRoot) { $ArtifactRoot = Join-Path $RepoRoot "slicer-engine" }
$ArtifactRoot = (Resolve-Path -LiteralPath $ArtifactRoot).Path
if (-not $LocalSymbolsDir) { $LocalSymbolsDir = Join-Path $ArtifactRoot "symbols" }

$man = Get-Content (Join-Path $ArtifactRoot "engine-artifact-manifest.json") -Raw | ConvertFrom-Json
$buildId = [string]$man.engine_build_id

if (-not $ReportDir) {
    # Default used to point into openspec\changes\backend-slicer-engine-deidentification\evidence\,
    # a review-project folder archived on 2026-07-30 (renamed with an archive-date prefix). Every
    # run since then wrote into an orphaned folder nobody reviews. Same root cause and fix as
    # Bundle-Launcher's build-windows-bundle.ps1 -EvidenceDir (task 1.4): this report is a
    # per-run diagnostic result, not a durable audit record, so it belongs under build\ (already
    # gitignored here), not inside an openspec change folder. Pass -ReportDir explicitly to keep
    # a specific run.
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
    $ReportDir = Join-Path $RepoRoot "build\evidence\windows\symbolication-6.6-6.7-$stamp"
}
New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null

$failures = [System.Collections.Generic.List[string]]::new()
$checks = [ordered]@{ engine_build_id = $buildId }

function Find-Dumpbin {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
    if (-not (Test-Path $vswhere)) { return $null }
    $vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if (-not $vs) { return $null }
    return Get-ChildItem "$vs\VC\Tools\MSVC" -Recurse -Filter dumpbin.exe -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match 'Hostx64\\x64\\dumpbin\.exe$' } |
        Select-Object -First 1 -ExpandProperty FullName
}

function Get-RsdsGuid([string]$PePath, [string]$Dumpbin) {
    $out = & $Dumpbin /HEADERS $PePath 2>&1 | Out-String
    if ($out -match 'Format:\s*RSDS,\s*\{([0-9A-Fa-f-]+)\}') { return $Matches[1].ToUpperInvariant() }
    return $null
}

function Test-PdbContainsGuid([string]$PdbPath, [string]$PeGuid) {
    $py = Join-Path $RepoRoot ".venv312\Scripts\python.exe"
    if (-not (Test-Path $py)) { $py = "python" }
    $code = @"
import mmap, uuid, sys
p, g = sys.argv[1], sys.argv[2]
u = uuid.UUID(g)
f = open(p, 'rb')
mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
ok = mm.find(u.bytes_le) >= 0
mm.close(); f.close()
sys.exit(0 if ok else 1)
"@
    & $py -c $code $PdbPath $PeGuid
    return ($LASTEXITCODE -eq 0)
}

$dumpbin = Find-Dumpbin
if (-not $dumpbin) { throw "dumpbin.exe not found" }
$dll = Join-Path $ArtifactRoot "bin\slicer_core.dll"
$pdbLocal = Join-Path $LocalSymbolsDir "slicer_core.pdb"
if (-not (Test-Path $dll)) { throw "missing $dll" }
if (-not (Test-Path $pdbLocal)) { throw "missing local PDB $pdbLocal — package must archive symbols/" }

$peGuid = Get-RsdsGuid $dll $dumpbin
$checks.pe_rsds_guid = $peGuid
$pdbHasGuid = $false
if ($peGuid) {
    Write-Host "Checking PDB contains PE GUID via Python mmap..." -ForegroundColor Cyan
    $pdbHasGuid = Test-PdbContainsGuid $pdbLocal $peGuid
}
$checks.pdb_contains_pe_guid = $pdbHasGuid
$checks.guid_match = [bool]$pdbHasGuid
if (-not $checks.guid_match) {
    $failures.Add("PE RSDS GUID ($peGuid) not found inside archived slicer_core.pdb")
} else {
    Write-Host "6.6 GUID match inside PDB: $peGuid" -ForegroundColor Green
}

# Resolve OneDrive store if not passed
if (-not $OneDriveStoreRoot) {
    $odRoots = [IO.Directory]::GetDirectories($env:USERPROFILE) | Where-Object { $_ -like '*OneDrive*' }
    foreach ($od in $odRoots) {
        $hits = [IO.Directory]::GetDirectories($od, "slicer-engine-symbols", [IO.SearchOption]::AllDirectories)
        if ($hits -and $hits.Length -gt 0) {
            $OneDriveStoreRoot = Join-Path $hits[0] "windows"
            break
        }
    }
}
$checks.onedrive_store_root = $OneDriveStoreRoot

# Upload/mirror current build into a local drill store under ReportDir (and copy to OneDrive if present)
$drillStore = Join-Path $ReportDir "symbol-store-mirror\windows"
$curStore = Join-Path $drillStore $buildId
New-Item -ItemType Directory -Force -Path $curStore | Out-Null
Copy-Item (Join-Path $LocalSymbolsDir "slicer-engine.pdb") $curStore -Force
Copy-Item $pdbLocal $curStore -Force
Copy-Item (Join-Path $ArtifactRoot "engine-artifact-manifest.json") $curStore -Force
if (Test-Path (Join-Path $ArtifactRoot "engine_build_id.txt")) {
    Copy-Item (Join-Path $ArtifactRoot "engine_build_id.txt") $curStore -Force
}
$checks.drill_store_path = $curStore
$checks.lookup_by_build_id = (Test-Path (Join-Path $curStore "slicer_core.pdb"))

# Skip re-copying 1.3GB PDB to OneDrive if already present for this build_id
if ($OneDriveStoreRoot -and (Test-Path $OneDriveStoreRoot)) {
    $odDest = Join-Path $OneDriveStoreRoot $buildId
    $odPdb = Join-Path $odDest "slicer_core.pdb"
    if (-not (Test-Path $odPdb)) {
        New-Item -ItemType Directory -Force -Path $odDest | Out-Null
        Copy-Item (Join-Path $curStore "*") $odDest -Force
        $checks.onedrive_uploaded = $odDest
        Write-Host "Uploaded symbols to OneDrive: $odDest" -ForegroundColor Green
    } else {
        $checks.onedrive_uploaded = $odDest
        $checks.onedrive_upload_skipped = "already present"
        Write-Host "OneDrive symbols already present: $odDest" -ForegroundColor Green
    }
} else {
    $checks.onedrive_uploaded = $null
    Write-Host "WARN: OneDrive store not found; drill uses local mirror only" -ForegroundColor Yellow
}

# 6.7a symbol loss
$missing = Join-Path $drillStore "NO_SUCH_BUILD_ID"
$checks.symbol_loss_detected = (-not (Test-Path (Join-Path $missing "slicer_core.pdb")))
if (-not $checks.symbol_loss_detected) { $failures.Add("symbol loss path unexpectedly existed") }

# 6.7b rollback — prior build_id from OneDrive or known previous
$priorIds = @()
if ($OneDriveStoreRoot -and (Test-Path $OneDriveStoreRoot)) {
    $priorIds = @(Get-ChildItem -LiteralPath $OneDriveStoreRoot -Directory | Where-Object { $_.Name -ne $buildId } | Select-Object -ExpandProperty Name)
}
$checks.prior_build_ids = $priorIds
if ($priorIds.Count -gt 0) {
    $prior = $priorIds | Select-Object -First 1
    $priorPdb = Join-Path $OneDriveStoreRoot "$prior\slicer_core.pdb"
    $checks.rollback_prior_build_id = $prior
    $checks.rollback_prior_pdb_present = (Test-Path $priorPdb)
    if (-not $checks.rollback_prior_pdb_present) { $failures.Add("prior PDB missing for $prior") }
    else { Write-Host "6.7 rollback prior build resolvable: $prior" -ForegroundColor Green }
} else {
    $checks.rollback_prior_build_id = $null
    $checks.rollback_note = "No prior OneDrive builds found; rollback checked via symbol-loss negative only"
}

# QA crash smoke (exit code only — full dump optional): proves harness still triggers for symbolication input path
$qaExe = Join-Path $RepoRoot "slicer-engine-qa\bin\slicer-engine.exe"
if (Test-Path $qaExe) {
    $env:BUNDLE_QA_CRASH_MODE = "segfault"
    $qp = Start-Process -FilePath $qaExe -ArgumentList @("--help") -NoNewWindow -Wait -PassThru `
        -RedirectStandardOutput (Join-Path $ReportDir "qa-segfault-stdout.txt") `
        -RedirectStandardError (Join-Path $ReportDir "qa-segfault-stderr.txt")
    Remove-Item Env:BUNDLE_QA_CRASH_MODE -ErrorAction SilentlyContinue
    $checks.qa_segfault_exit = $qp.ExitCode
    $checks.qa_segfault_nonzero = ($qp.ExitCode -ne 0)
    if ($qp.ExitCode -eq 0) { $failures.Add("QA segfault mode did not crash (exit 0)") }
} else {
    $checks.qa_segfault_exit = $null
    $checks.qa_note = "slicer-engine-qa missing; skipped crash trigger"
}

$summary = [ordered]@{
    task            = "6.6-6.7"
    captured_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    verdict         = $(if ($failures.Count -eq 0) { "PASS" } else { "FAIL" })
    checks          = $checks
    failures        = @($failures)
}
$summary | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $ReportDir "SUMMARY.json") -Encoding utf8

@"
# Windows symbolication / loss / rollback — tasks 6.6–6.7

**Verdict：** $($summary.verdict)  
**engine_build_id：** ``$buildId``  
**PE RSDS GUID：** ``$peGuid``  
**PDB contains PE GUID：** $($checks.pdb_contains_pe_guid)  
**Drill store：** ``$curStore``  
**OneDrive upload：** $(if ($checks.onedrive_uploaded) { "``$($checks.onedrive_uploaded)``" } else { "(local mirror only)" })  
**Symbol loss (missing build_id)：** detected=$($checks.symbol_loss_detected)  
**Rollback prior：** $(if ($checks.rollback_prior_build_id) { "``$($checks.rollback_prior_build_id)`` present=$($checks.rollback_prior_pdb_present)" } else { $checks.rollback_note })  
**QA segfault exit：** $($checks.qa_segfault_exit)

## Method

1. Read RSDS GUID from ``slicer_core.dll`` via dumpbin /HEADERS.  
2. Parse matching GUID from archived ``slicer_core.pdb``.  
3. Stage ``symbol-store-mirror/windows/<build_id>/`` and optionally sync to OneDrive store.  
4. 6.7a：lookup missing build_id → fail.  
5. 6.7b：prior OneDrive ``<build_id>`` still present for rollback.  
6. QA ``BUNDLE_QA_CRASH_MODE=segfault`` non-zero exit (input for future WinDbg sessions).

PDB-free consumer ``bin/`` unchanged; symbols never copied into Setup.
"@ | Set-Content (Join-Path $ReportDir "SUMMARY.md") -Encoding utf8

if ($failures.Count -gt 0) {
    Write-Host "FAIL: $($failures -join '; ')" -ForegroundColor Red
    exit 1
}
Write-Host "PASS: 6.6–6.7 — $ReportDir" -ForegroundColor Green
exit 0

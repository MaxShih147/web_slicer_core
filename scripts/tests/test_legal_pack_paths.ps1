#Requires -Version 5.1
<#
.SYNOPSIS
  Regression test for task 1.1 (slicer-engine-release-cicd P0 Sev-0).

.DESCRIPTION
  Confirms package_slicer_engine_windows.ps1's AGPL legal-pack source
  path/filenames actually exist on disk, and that
  scan_slicer_engine_windows.ps1 expects exactly the filenames that
  package_slicer_engine_windows.ps1 will actually stage.

  This does not run the full engine build. It reads the two real
  scripts' source text and checks their declared contract against the
  real legal/ folder, so it stays honest to what the scripts actually
  say (no hand-duplicated logic) without needing MSVC/CMake/dumpbin.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\tests\test_legal_pack_paths.ps1
#>
$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$PackagePs1 = Join-Path $RepoRoot "scripts\package_slicer_engine_windows.ps1"
$ScanPs1 = Join-Path $RepoRoot "scripts\scan_slicer_engine_windows.ps1"

$failures = @()

if (-not (Test-Path -LiteralPath $PackagePs1)) { throw "Missing $PackagePs1" }
if (-not (Test-Path -LiteralPath $ScanPs1)) { throw "Missing $ScanPs1" }

# --- 1. Extract $LegalSrc literal + source filename list from package script ---
$pkgText = Get-Content -LiteralPath $PackagePs1 -Raw

$legalSrcMatch = [regex]::Match($pkgText, '\$LegalSrc\s*=\s*Join-Path\s+\$RepoRoot\s+"([^"]+)"')
if (-not $legalSrcMatch.Success) {
    $failures += "Could not find `$LegalSrc = Join-Path `$RepoRoot `"...`" in package_slicer_engine_windows.ps1"
}
$legalSrcRel = $legalSrcMatch.Groups[1].Value

$docsMatch = [regex]::Match($pkgText, 'foreach\s*\(\$doc\s+in\s+@\(([^)]+)\)\)')
if (-not $docsMatch.Success) {
    $failures += "Could not find 'foreach (`$doc in @(...))' legal doc list in package_slicer_engine_windows.ps1"
}
$sourceDocs = @()
if ($docsMatch.Success) {
    $sourceDocs = [regex]::Matches($docsMatch.Groups[1].Value, '"([^"]+)"') | ForEach-Object { $_.Groups[1].Value }
}

# --- 2. Every source doc the package script expects must actually exist on disk ---
if ($legalSrcRel) {
    $legalSrcAbs = Join-Path $RepoRoot $legalSrcRel
    foreach ($doc in $sourceDocs) {
        $p = Join-Path $legalSrcAbs $doc
        if (-not (Test-Path -LiteralPath $p)) {
            $failures += "package script expects '$doc' at $p, but it does not exist"
        }
    }
}

# --- 3. scan script's expected staged filenames must match what package will actually stage ---
$scanText = Get-Content -LiteralPath $ScanPs1 -Raw
$legalRequiredMatch = [regex]::Match($scanText, '\$legalRequired\s*=\s*@\(([^)]+)\)')
if (-not $legalRequiredMatch.Success) {
    $failures += "Could not find `$legalRequired = @(...) in scan_slicer_engine_windows.ps1"
}
$scanExpected = @()
if ($legalRequiredMatch.Success) {
    $scanExpected = [regex]::Matches($legalRequiredMatch.Groups[1].Value, '"([^"]+)"') | ForEach-Object { $_.Groups[1].Value }
}

# package always adds LICENSE separately (see $LicenseSrc), plus whatever $sourceDocs
# lists — Copy-Item stages each doc under the same filename it had at the source.
$stagedByPackage = @("LICENSE") + $sourceDocs
$missingInScan = $stagedByPackage | Where-Object { $_ -notin $scanExpected }
$extraInScan = $scanExpected | Where-Object { $_ -notin $stagedByPackage }
if ($missingInScan) {
    $failures += "scan script does NOT check for: $($missingInScan -join ', ') (package stages them, scan silently ignores them)"
}
if ($extraInScan) {
    $failures += "scan script requires: $($extraInScan -join ', ') but package never stages them (scan will always fail-closed on a clean build)"
}

if ($failures.Count -gt 0) {
    Write-Host "FAIL - legal pack path/filename contract is broken:" -ForegroundColor Red
    $failures | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    exit 1
}

Write-Host "PASS - legal pack source dir ($legalSrcRel), files ($($sourceDocs -join ', ')), and scan's expectations all agree." -ForegroundColor Green
exit 0

#Requires -Version 5.1
<#
.SYNOPSIS
  tasks 6.5 — expose neutral engine_build_id next to packaged artifact (manifest + sidecar file).
  Also validates brand-free ProductVersion on PE (no Prusa tokens).
#>
param(
    [string]$ArtifactRoot = "",
    [string]$ReportPath = ""
)

$ErrorActionPreference = "Stop"
if (-not $ArtifactRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
    $ArtifactRoot = Join-Path $RepoRoot "slicer-engine"
}
$ArtifactRoot = (Resolve-Path -LiteralPath $ArtifactRoot).Path
$manifestPath = Join-Path $ArtifactRoot "engine-artifact-manifest.json"
if (-not (Test-Path $manifestPath)) { $manifestPath = Join-Path $ArtifactRoot "artifact-manifest.json" }
$man = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$buildId = [string]$man.engine_build_id
if (-not $buildId) { throw "manifest missing engine_build_id" }

$idFile = Join-Path $ArtifactRoot "engine_build_id.txt"
Set-Content -LiteralPath $idFile -Value $buildId -Encoding ascii -NoNewline
# Also under bin/ for install-tree discovery next to exe
$idFileBin = Join-Path $ArtifactRoot "bin\engine_build_id.txt"
Set-Content -LiteralPath $idFileBin -Value $buildId -Encoding ascii -NoNewline

$exe = Join-Path $ArtifactRoot "bin\slicer-engine.exe"
$vi = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($exe)
$product = "$($vi.ProductName) $($vi.ProductVersion) $($vi.FileDescription)"
$brandHits = ([regex]::Matches($product, "(?i)PrusaSlicer|prusa3d|slic3r")).Count

$report = [ordered]@{
    task                 = "6.5"
    engine_build_id      = $buildId
    engine_build_id_txt  = @("engine_build_id.txt", "bin/engine_build_id.txt")
    manifest_path        = $manifestPath
    product_version_raw  = $vi.ProductVersion
    product_name         = $vi.ProductName
    brand_hits_in_vi     = $brandHits
    note                 = "CLI has no --version flag; neutral build ID is exposed via manifest + engine_build_id.txt (REQ-DEID-012)."
    verdict              = $(if ($brandHits -eq 0 -and $buildId) { "PASS" } else { "FAIL" })
}
if ($ReportPath) {
    $report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ReportPath -Encoding utf8
}
if ($report.verdict -ne "PASS") { throw "6.5 FAILED brand_hits=$brandHits buildId=$buildId" }
Write-Host "PASS 6.5 build_id=$buildId -> $idFile" -ForegroundColor Green

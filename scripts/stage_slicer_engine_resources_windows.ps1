#Requires -Version 5.1
<#
.SYNOPSIS
  Stage de-branded resources next to slicer-engine.exe (Windows layout: bin/resources).

.DESCRIPTION
  Mirrors scripts/stage_slicer_engine_resources_macos.sh:
  copy runtime resources but drop brand-named paths (prusa / slic3r).
  SLA agent uses --load with job INI; bundled PrusaResearch* profiles/icons are not required.

.EXAMPLE
  powershell -File scripts\stage_slicer_engine_resources_windows.ps1 -ArtifactRoot .\slicer-engine
  powershell -File scripts\stage_slicer_engine_resources_windows.ps1 -DestDir .\slicer-engine\bin\resources
#>
param(
    [string]$ArtifactRoot = "",
    [string]$DestDir = "",
    [string]$ResourcesSrc = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if (-not $ResourcesSrc) {
    $ResourcesSrc = Join-Path $RepoRoot "third_party\prusaslicer_fork\resources"
}
if (-not $DestDir) {
    if (-not $ArtifactRoot) { throw "Pass -ArtifactRoot or -DestDir" }
    $DestDir = Join-Path $ArtifactRoot "bin\resources"
}

if (-not (Test-Path -LiteralPath $ResourcesSrc)) {
    throw "resources source missing: $ResourcesSrc"
}

if (Test-Path -LiteralPath $DestDir) {
    Remove-Item -LiteralPath $DestDir -Recurse -Force
}
New-Item -ItemType Directory -Path $DestDir -Force | Out-Null

$brandNameRe = [regex]'(?i)prusa|slic3r'
$copied = 0
$skipped = 0

Get-ChildItem -LiteralPath $ResourcesSrc -Recurse -Force | ForEach-Object {
    $rel = $_.FullName.Substring($ResourcesSrc.Length).TrimStart('\', '/')
    if ($brandNameRe.IsMatch($rel)) {
        $skipped++
        return
    }
    $dst = Join-Path $DestDir $rel
    if ($_.PSIsContainer) {
        New-Item -ItemType Directory -Path $dst -Force | Out-Null
    } else {
        $parent = Split-Path -Parent $dst
        if (-not (Test-Path -LiteralPath $parent)) {
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
        }
        Copy-Item -LiteralPath $_.FullName -Destination $dst -Force
        $copied++
    }
}

$leftover = @(Get-ChildItem -LiteralPath $DestDir -Recurse -Force -ErrorAction SilentlyContinue |
    Where-Object { $brandNameRe.IsMatch($_.FullName.Substring($DestDir.Length)) })
if ($leftover.Count -gt 0) {
    Write-Host "[ERROR] brand path remained under resources after filter:" -ForegroundColor Red
    $leftover | Select-Object -First 20 | ForEach-Object { Write-Host "  $($_.FullName)" }
    throw "resources de-brand filter failed ($($leftover.Count) leftover path(s))"
}

Write-Host "[OK] Staged de-branded resources -> $DestDir (copied=$copied skipped_brand=$skipped)" -ForegroundColor Green

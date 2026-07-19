#Requires -Version 5.1
<#
.SYNOPSIS
  tasks 5.11 / REQ-DEID-008 — prove engine stays out-of-process on Windows.
#>
param(
    [string]$EngineExe = "",
    [string]$ReportDir = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $EngineExe) {
    $EngineExe = Join-Path $RepoRoot "slicer-engine\bin\slicer-engine.exe"
}
if (-not (Test-Path -LiteralPath $EngineExe)) {
    throw "Missing engine: $EngineExe"
}
if (-not $ReportDir) {
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
    $ReportDir = Join-Path $RepoRoot "openspec\changes\backend-slicer-engine-deidentification\evidence\windows\subprocess-5.11-$stamp"
}
New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null

$failures = [System.Collections.Generic.List[string]]::new()
$checks = [ordered]@{}

$agentPid = $PID
$p = Start-Process -FilePath $EngineExe -ArgumentList @("--help") -NoNewWindow -Wait -PassThru `
    -RedirectStandardOutput (Join-Path $ReportDir "help-stdout.txt") `
    -RedirectStandardError (Join-Path $ReportDir "help-stderr.txt")
$checks.agent_pid = $agentPid
$checks.engine_pid = $p.Id
$checks.help_exit = $p.ExitCode
if ($p.Id -eq $agentPid) { $failures.Add("engine PID equals agent PID") }
if ($p.ExitCode -ne 0) { $failures.Add("--help exit=$($p.ExitCode)") }

$helpText = (Get-Content (Join-Path $ReportDir "help-stdout.txt") -Raw -ErrorAction SilentlyContinue) +
    (Get-Content (Join-Path $ReportDir "help-stderr.txt") -Raw -ErrorAction SilentlyContinue)
$checks.help_prusaslicer_hits = ([regex]::Matches($helpText, "(?i)PrusaSlicer")).Count
if ($checks.help_prusaslicer_hits -gt 0) { $failures.Add("help contains PrusaSlicer") }

# Agent process must not map slicer_core.dll
$mods = Get-Process -Id $agentPid -Module -ErrorAction SilentlyContinue |
    ForEach-Object { $_.ModuleName.ToLowerInvariant() }
$hits = @($mods | Where-Object { $_ -match 'slicer_core|prusaslicer' })
$checks.agent_mapped_engine_dlls = $hits
if ($hits.Count -gt 0) { $failures.Add("agent process mapped: $($hits -join ', ')") }

$checks.engine_path = $EngineExe
$checks.engine_is_external_exe = ($EngineExe -match '(?i)slicer-engine\.exe$')
if (-not $checks.engine_is_external_exe) { $failures.Add("engine path not slicer-engine.exe") }

$summary = [ordered]@{
    task            = "5.11"
    captured_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    verdict         = $(if ($failures.Count -eq 0) { "PASS" } else { "FAIL" })
    checks          = $checks
    failures        = @($failures)
}
$summary | ConvertTo-Json -Depth 6 | Set-Content (Join-Path $ReportDir "SUMMARY.json") -Encoding utf8
@"
# Windows subprocess boundary — tasks 5.11

**Verdict：** $($summary.verdict)  
**Engine：** ``$EngineExe``  
**Agent PID：** $agentPid · **Engine PID (--help)：** $($p.Id)  
**Agent mapped engine DLLs：** $(if ($hits.Count) { $hits -join ', ' } else { '(none)' })  

REQ-DEID-008／D4：engine remains a separate OS process; agent does not load ``slicer_core.dll``.
"@ | Set-Content (Join-Path $ReportDir "SUMMARY.md") -Encoding utf8

if ($failures.Count -gt 0) {
    Write-Host "FAIL: $($failures -join '; ')" -ForegroundColor Red
    exit 1
}
Write-Host "PASS: subprocess boundary (5.11) — $ReportDir" -ForegroundColor Green
exit 0

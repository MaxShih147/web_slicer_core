#Requires -Version 5.1
<#
.SYNOPSIS
    Task 2.19 acceptance: every stage-2 run must reproduce the Golden Baseline.

.DESCRIPTION
    Runs the four benchmark cases at --threads 1 and --threads 8 (eight runs),
    with SLA_RASTER_VERIFY=1 and SLA_RASTER_FASTPATH=1, then compares each run's
    layer and preview fingerprints against the Golden Baseline and reports the
    result as a Markdown table.

    The engine environment goes through run_bench.py's --raster-env and NOT
    through $env:. run_bench.py deliberately drops every inherited SLA_*
    variable before launching the engine, so setting them in the shell would be
    silently discarded.

    Nothing here compiles anything. Build the engine in VS2022 first and copy it
    to <work>\engines\step2-<short commit>\ as tasks 0.4 describes.

.PARAMETER Engine
    Engine directory holding slicer-engine.exe, e.g.
    scripts\raster_bench\work\engines\step2-abc1234

.PARAMETER Build
    Build label for the run directories. Default step2.

.PARAMETER GoldenBuild
    Build label of the Golden Baseline runs. Default base.

.PARAMETER Threads
    Thread counts to run. Default 1 and 8, which is what task 2.19 asks for.

.PARAMETER Force
    Delete a run directory that already exists instead of refusing.

.PARAMETER SkipRun
    Do not slice; only compare and report the runs that are already there.
    Use it to reprint the table without spending another hour.

.EXAMPLE
    .\scripts\raster_bench\verify_phase2_golden.ps1 -Engine scripts\raster_bench\work\engines\step2-abc1234
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string] $Engine,
    [string]   $Build       = 'step2',
    [string]   $GoldenBuild = 'base',
    [int[]]    $Threads     = @(1, 8),
    [string]   $Python      = '.venv\Scripts\python.exe',
    [string]   $Work        = 'scripts\raster_bench\work',
    [switch]   $Force,
    [switch]   $SkipRun
)

# Stop on our own throws. Native commands are handled by Invoke-Native below,
# which lowers this locally: PowerShell 5.1 turns a native program's stderr into
# an ErrorRecord, and under 'Stop' that would abort the whole run on the first
# failing slice instead of carrying on and reporting it in the table.
$ErrorActionPreference = 'Stop'

$Cases = @(
    'primary-16k-guide-x8',
    'secondary-8k-guide-x3',
    'tiny-16k-crown-x1',
    'fullplate-16k-slab'
)

$Platform = 'windows'
$RunBench = 'scripts\raster_bench\run_bench.py'
$Compare  = 'scripts\raster_bench\compare_fingerprints.py'
$LogDir   = Join-Path (Join-Path $Work 'logs') 'verify-phase2'
$RunsDir  = Join-Path $Work 'runs'

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Runs a native command, writes everything it printed to $LogPath, and returns
# its exit code. $ErrorActionPreference is set inside the function, so the change
# is function-scoped and disappears on return.
function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]   $Exe,
        [Parameter(Mandatory = $true)][string[]] $Arguments,
        [Parameter(Mandatory = $true)][string]   $LogPath
    )
    $ErrorActionPreference = 'Continue'
    $output = & $Exe @Arguments 2>&1
    $code = $LASTEXITCODE
    $output | Out-File -FilePath $LogPath -Encoding utf8
    return $code
}

function Get-Sha256([string] $Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLower()
}

function Get-ShortHash([string] $Hash) {
    if ($null -eq $Hash) { return 'missing' }
    return $Hash.Substring(0, 12)
}

# Lines the engine printed because a tile map invariant was broken. Task 2.19
# requires there to be none.
function Get-VerifyLineCount([string] $RunDir) {
    $file = Join-Path $RunDir 'stderr.log'
    if (-not (Test-Path -LiteralPath $file)) { return -1 }
    $hits = @(Select-String -LiteralPath $file -Pattern '[raster-verify]' -SimpleMatch)
    return $hits.Count
}

function Get-TotalWallSeconds([string] $RunDir) {
    $file = Join-Path $RunDir 'timing.json'
    if (-not (Test-Path -LiteralPath $file)) { return $null }
    try {
        $timing = Get-Content -LiteralPath $file -Raw | ConvertFrom-Json
        return [math]::Round([double] $timing.total_wall_s, 1)
    } catch {
        return $null
    }
}

# ---------------------------------------------------------------------------
# Preflight. Everything that can be wrong is checked before the first slice, so
# a typo does not surface an hour in.
# ---------------------------------------------------------------------------

Write-Host '== Preflight ==' -ForegroundColor Cyan

# -Python may be a path (.venv\Scripts\python.exe) or a command on PATH (python).
$pythonExe = $null
if (Test-Path -LiteralPath $Python) {
    $pythonExe = (Resolve-Path -LiteralPath $Python).Path
} else {
    $found = Get-Command -Name $Python -CommandType Application -ErrorAction SilentlyContinue |
             Select-Object -First 1
    if ($null -ne $found) { $pythonExe = $found.Source }
}
if ($null -eq $pythonExe) {
    throw "Python not found as a path or on PATH: '$Python'. Run this from the repository root, or pass -Python."
}
foreach ($script in @($RunBench, $Compare)) {
    if (-not (Test-Path -LiteralPath $script)) {
        throw "Bench tool not found: '$script'. Run this from the repository root."
    }
}

# run_bench.py passes these straight to the engine, whose working directory is
# the run folder, not this one. Relative paths would be unresolvable there, so
# they are made absolute here before anything else uses them.
if (-not (Test-Path -LiteralPath $Work)) {
    throw "Work directory not found: '$Work'. Run this from the repository root, or pass -Work."
}
$Work = (Resolve-Path -LiteralPath $Work).Path
if (-not (Test-Path -LiteralPath $Engine)) {
    throw "Engine directory not found: '$Engine'."
}
$Engine = (Resolve-Path -LiteralPath $Engine).Path

$LogDir  = Join-Path (Join-Path $Work 'logs') 'verify-phase2'
$RunsDir = Join-Path $Work 'runs'

$engineExe = Join-Path $Engine 'slicer-engine.exe'
if (-not (Test-Path -LiteralPath $engineExe)) {
    throw "slicer-engine.exe not found in '$Engine'. Copy the freshly built engine there first (tasks 0.4)."
}
Write-Host ("python     : {0}" -f $pythonExe)
Write-Host ("work       : {0}" -f $Work)
Write-Host ("engine     : {0}" -f $Engine)
Write-Host ("engine exe : {0}" -f (Get-ShortHash (Get-Sha256 $engineExe)))

$coreDll = Join-Path $Engine 'slicer_core.dll'
if (Test-Path -LiteralPath $coreDll) {
    Write-Host ("core dll   : {0}" -f (Get-ShortHash (Get-Sha256 $coreDll)))
}

# Golden runs have to be there for all four cases, otherwise there is nothing
# to compare against.
$golden = @{}
foreach ($case in $Cases) {
    $dir = Join-Path $RunsDir ("{0}-{1}-{2}-tdefault-r1" -f $Platform, $GoldenBuild, $case)
    if (-not (Test-Path -LiteralPath (Join-Path $dir 'layers.sha256'))) {
        throw "Golden Baseline missing for case '$case': expected '$dir' with layers.sha256."
    }
    $golden[$case] = $dir
}
Write-Host ("golden     : {0} cases under {1}" -f $Cases.Count, $RunsDir)

# Plan every run up front, and settle the existing-directory question now.
$plan = @()
foreach ($case in $Cases) {
    foreach ($t in $Threads) {
        $dir = Join-Path $RunsDir ("{0}-{1}-{2}-t{3}-r1" -f $Platform, $Build, $case, $t)
        if ((Test-Path -LiteralPath $dir) -and (-not $SkipRun)) {
            if ($Force) {
                Write-Host ("removing   : {0}" -f $dir) -ForegroundColor Yellow
                Remove-Item -LiteralPath $dir -Recurse -Force
            } else {
                throw "Run directory already exists: '$dir'. Pass -Force to replace it, or -SkipRun to only compare."
            }
        }
        $plan += [pscustomobject]@{ Case = $case; Threads = $t; RunDir = $dir }
    }
}

if (-not (Test-Path -LiteralPath $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
Write-Host ("logs       : {0}" -f $LogDir)
Write-Host ("runs       : {0}" -f @($plan).Count)

# ---------------------------------------------------------------------------
# Step B: slice. The engine's own verbose output already lands in the run
# directory's stdout.log and stderr.log; these logs capture run_bench itself.
# ---------------------------------------------------------------------------

if ($SkipRun) {
    Write-Host ''
    Write-Host '== Slicing skipped (-SkipRun) ==' -ForegroundColor Yellow
} else {
    Write-Host ''
    Write-Host '== Slicing ==' -ForegroundColor Cyan
    $index = 0
    foreach ($item in $plan) {
        $index++
        $label = "{0} t{1}" -f $item.Case, $item.Threads
        $log = Join-Path $LogDir ("run-{0}-t{1}.log" -f $item.Case, $item.Threads)
        Write-Host ("[{0}/{1}] {2} ... " -f $index, @($plan).Count, $label) -NoNewline

        $arguments = @(
            $RunBench,
            '--case',   $item.Case,
            '--engine', $Engine,
            '--build',  $Build,
            '--repeat', '1',
            '--threads', [string] $item.Threads,
            '--raster-env', 'SLA_RASTER_VERIFY=1',
            '--raster-env', 'SLA_RASTER_FASTPATH=1',
            '--work',   $Work
        )

        $started = Get-Date
        # A failing slice is recorded and the loop carries on, so one bad case
        # still leaves seven results and a table.
        $code = Invoke-Native -Exe $pythonExe -Arguments $arguments -LogPath $log
        $elapsed = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)

        if ($code -eq 0) {
            Write-Host ("done in {0}s" -f $elapsed) -ForegroundColor Green
        } else {
            Write-Host ("FAILED (exit {0}), see {1}" -f $code, $log) -ForegroundColor Red
        }
    }
}

# ---------------------------------------------------------------------------
# Step C: compare every run against its Golden.
# ---------------------------------------------------------------------------

Write-Host ''
Write-Host '== Comparing against Golden ==' -ForegroundColor Cyan

$results = @()
foreach ($item in $plan) {
    $goldenDir = $golden[$item.Case]
    $runDir    = $item.RunDir
    $log       = Join-Path $LogDir ("compare-{0}-t{1}.log" -f $item.Case, $item.Threads)

    $row = [pscustomobject]@{
        Case         = $item.Case
        Threads      = $item.Threads
        RunDir       = $runDir
        LayersGolden = Get-Sha256 (Join-Path $goldenDir 'layers.sha256')
        LayersRun    = $null
        PreviewGolden= Get-Sha256 (Join-Path $goldenDir 'preview.sha256')
        PreviewRun   = $null
        CompareExit  = $null
        VerifyLines  = $null
        Seconds      = $null
        Status       = 'FAIL'
        Note         = ''
    }

    if (-not (Test-Path -LiteralPath (Join-Path $runDir 'layers.sha256'))) {
        $row.Note = 'run missing'
        $results += $row
        Write-Host ("{0} t{1}: run missing" -f $item.Case, $item.Threads) -ForegroundColor Red
        continue
    }

    $row.LayersRun   = Get-Sha256 (Join-Path $runDir 'layers.sha256')
    $row.PreviewRun  = Get-Sha256 (Join-Path $runDir 'preview.sha256')
    $row.VerifyLines = Get-VerifyLineCount $runDir
    $row.Seconds     = Get-TotalWallSeconds $runDir

    $row.CompareExit = Invoke-Native -Exe $pythonExe `
        -Arguments @($Compare, $goldenDir, $runDir) -LogPath $log

    $notes = @()
    if ($row.CompareExit -ne 0) { $notes += ("compare exit {0}" -f $row.CompareExit) }
    if ($row.LayersRun -ne $row.LayersGolden)   { $notes += 'layers differ' }
    if ($row.PreviewRun -ne $row.PreviewGolden) { $notes += 'preview differ' }
    if ($row.VerifyLines -gt 0)  { $notes += ("{0} verify hits" -f $row.VerifyLines) }
    if ($row.VerifyLines -lt 0)  { $notes += 'no stderr.log' }

    if ($notes.Count -eq 0) {
        $row.Status = 'PASS'
        Write-Host ("{0} t{1}: PASS" -f $item.Case, $item.Threads) -ForegroundColor Green
    } else {
        $row.Note = ($notes -join '; ')
        Write-Host ("{0} t{1}: FAIL - {2}" -f $item.Case, $item.Threads, $row.Note) -ForegroundColor Red
    }

    $results += $row
}

# ---------------------------------------------------------------------------
# Step D: the report.
# ---------------------------------------------------------------------------

$passed = @($results | Where-Object { $_.Status -eq 'PASS' }).Count
$total  = @($results).Count

$lines = @()
$lines += '# Task 2.19 — stage 2 against Golden Baseline'
$lines += ''
$lines += ("- generated: {0}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
$lines += ("- engine: ``{0}``" -f $Engine)
$lines += ("- engine exe sha256: ``{0}``" -f (Get-Sha256 $engineExe))
$lines += ("- build label: ``{0}``, golden label: ``{1}``" -f $Build, $GoldenBuild)
$lines += '- engine env: `SLA_RASTER_VERIFY=1`, `SLA_RASTER_FASTPATH=1` (passed through `--raster-env`)'
$lines += ("- result: **{0}/{1} PASS**" -f $passed, $total)
$lines += ''
$lines += '| Case | Threads | Layers sha256 | Preview sha256 | verify hits | Wall s | Result | Note |'
$lines += '| --- | ---: | --- | --- | ---: | ---: | --- | --- |'

foreach ($row in $results) {
    $layers  = "{0} / {1}" -f (Get-ShortHash $row.LayersRun),  (Get-ShortHash $row.LayersGolden)
    $preview = "{0} / {1}" -f (Get-ShortHash $row.PreviewRun), (Get-ShortHash $row.PreviewGolden)
    $seconds = '-'
    if ($null -ne $row.Seconds) { $seconds = [string] $row.Seconds }
    $verify = '-'
    if ($null -ne $row.VerifyLines) { $verify = [string] $row.VerifyLines }
    $note = $row.Note
    if ([string]::IsNullOrEmpty($note)) { $note = '' }

    $lines += ("| {0} | {1} | {2} | {3} | {4} | {5} | {6} | {7} |" -f `
        $row.Case, $row.Threads, $layers, $preview, $verify, $seconds, $row.Status, $note)
}

$lines += ''
$lines += 'Fingerprint columns are `run / golden`: the SHA-256 of the run directory''s'
$lines += '`layers.sha256` and `preview.sha256`, which are themselves the per-layer and'
$lines += 'per-preview digests. Equal digests mean every layer and every preview image'
$lines += 'came out byte for byte identical.'
$lines += ''
$lines += ("Per-run comparison logs: ``{0}``" -f $LogDir)

$report = Join-Path $LogDir 'report.md'
$lines | Out-File -FilePath $report -Encoding utf8

Write-Host ''
Write-Host '== Report ==' -ForegroundColor Cyan
$lines | ForEach-Object { Write-Host $_ }
Write-Host ''
Write-Host ("Saved to {0}" -f $report)

if ($passed -eq $total) {
    Write-Host 'All runs reproduce the Golden Baseline.' -ForegroundColor Green
    exit 0
}
Write-Host ("{0} of {1} runs did not match." -f ($total - $passed), $total) -ForegroundColor Red
exit 1

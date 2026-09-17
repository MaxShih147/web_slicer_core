#Requires -Version 5.1
<#
.SYNOPSIS
    Task 2.23: measure one tile edge length T, and compare the three of them.

.DESCRIPTION
    Each T needs its own engine, so this runs one T per invocation:

        -TileSize 40   ->  build label step2-T40
        -TileSize 80   ->  build label step2-T80
        -TileSize 160  ->  build label step2-T160

    For that T it slices the primary case and the full-plate case three times
    each at the engine's default thread count, then reports the median, minimum
    and maximum rasterizing time. When all three T builds have been measured,
    -CompareOnly prints them side by side against the base measurement.

    No SLA_RASTER_* variables are passed. SLA_RASTER_VERIFY in particular scans
    the whole canvas on every layer, which would swamp exactly the number being
    measured. Correctness under VERIFY is task 2.19's job, not this one.

    Output equality is still checked: changing T must not change a single byte,
    so every repeat's fingerprints are compared with the Golden Baseline. That
    costs nothing here because the digests are already on disk.

    Nothing here compiles anything. Build the engine for this T in VS2022 first
    and copy it to its own directory under <work>\engines\.

.PARAMETER Engine
    Engine directory for this T, e.g. work\engines\step2-T40-abc1234.
    Not needed with -CompareOnly.

.PARAMETER TileSize
    The T this engine was built with: 40, 80 or 160. Not needed with
    -CompareOnly. It only names things -- it cannot change what the engine does.

.PARAMETER Repeats
    Runs per case. Default 3, which is what the median is taken over.

.PARAMETER IdleSeconds
    Seconds to wait before each run so the machine settles. Default 60, as the
    measurement rules require. Pass 0 for a quick dry run whose numbers must not
    be used for the decision.

.PARAMETER CompareOnly
    Do not slice. Read whatever T builds are already measured and print the
    comparison table.

.EXAMPLE
    .\scripts\raster_bench\bench_tile_size.ps1 -Engine scripts\raster_bench\work\engines\step2-T40-abc1234 -TileSize 40

.EXAMPLE
    .\scripts\raster_bench\bench_tile_size.ps1 -CompareOnly
#>
[CmdletBinding()]
param(
    [string] $Engine,
    [ValidateSet(40, 80, 160)][int] $TileSize,
    [string] $Build       = 'step2',
    [string] $GoldenBuild = 'base',
    [int]    $Repeats     = 3,
    [int]    $IdleSeconds = 60,
    [string] $Python      = '.venv\Scripts\python.exe',
    [string] $Work        = 'scripts\raster_bench\work',
    [switch] $Force,
    [switch] $CompareOnly
)

# Stop on our own throws. Native commands go through Invoke-Native, which lowers
# this locally so a program writing to stderr cannot abort the run.
$ErrorActionPreference = 'Stop'

$Platform  = 'windows'
$RunBench  = 'scripts\raster_bench\run_bench.py'
$TileSizes = @(40, 80, 160)

# The primary case decides, the full-plate case guards: every tile is dirty
# there, so it shows whether the tile machinery costs anything when it cannot
# skip anything.
$Cases = @(
    [pscustomobject]@{ Id = 'primary-16k-guide-x8'; Role = 'primary';   Threshold = 0.50; Note = 'must be <= 50% of base' },
    [pscustomobject]@{ Id = 'fullplate-16k-slab';   Role = 'fullplate'; Threshold = 1.03; Note = 'must be <= 103% of base' }
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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

function Get-Median([double[]] $Values) {
    if ($null -eq $Values -or $Values.Count -eq 0) { return $null }
    $sorted = @($Values | Sort-Object)
    $count = $sorted.Count
    if ($count % 2 -eq 1) { return $sorted[[int](($count - 1) / 2)] }
    return (($sorted[$count / 2 - 1] + $sorted[$count / 2]) / 2)
}

function Format-Seconds($Value) {
    if ($null -eq $Value) { return '-' }
    return ('{0:N2}' -f [double] $Value)
}

function Format-Ratio($Value, $Base) {
    if ($null -eq $Value -or $null -eq $Base -or [double] $Base -eq 0) { return '-' }
    return ('{0:N1}%' -f (100.0 * [double] $Value / [double] $Base))
}

function Get-RunDirName([string] $BuildLabel, [string] $CaseId, [int] $Repeat) {
    return ("{0}-{1}-{2}-tdefault-r{3}" -f $Platform, $BuildLabel, $CaseId, $Repeat)
}

# Median, spread and fingerprints for one build label and one case.
function Get-CaseStats([string] $RunsRoot, [string] $BuildLabel, [string] $CaseId, [int] $Count,
                       [string] $GoldenLayers, [string] $GoldenPreview) {
    $times = @()
    $peaks = @()
    $missing = 0
    $mismatched = 0

    for ($repeat = 1; $repeat -le $Count; $repeat++) {
        $dir = Join-Path $RunsRoot (Get-RunDirName $BuildLabel $CaseId $repeat)
        $timingFile = Join-Path $dir 'timing.json'
        if (-not (Test-Path -LiteralPath $timingFile)) { $missing++; continue }

        $timing = Get-Content -LiteralPath $timingFile -Raw | ConvertFrom-Json
        if ($null -ne $timing.rasterizing_wall_s) { $times += [double] $timing.rasterizing_wall_s }
        if ($null -ne $timing.peak_working_set_bytes) { $peaks += [double] $timing.peak_working_set_bytes }

        # Changing T must not change one byte of the output.
        if ($null -ne $GoldenLayers) {
            $layers  = Get-Sha256 (Join-Path $dir 'layers.sha256')
            $preview = Get-Sha256 (Join-Path $dir 'preview.sha256')
            if ($layers -ne $GoldenLayers -or $preview -ne $GoldenPreview) { $mismatched++ }
        }
    }

    $median = Get-Median $times
    $minimum = $null
    $maximum = $null
    $spread = $null
    $needsRerun = $false
    if ($times.Count -gt 0) {
        $minimum = ($times | Measure-Object -Minimum).Minimum
        $maximum = ($times | Measure-Object -Maximum).Maximum
        $spread = $maximum - $minimum
        # The measurement rule: rerun the whole group only when the spread is
        # both more than 5% of the median AND more than half a second.
        $needsRerun = ($spread -gt (0.05 * $median)) -and ($spread -gt 0.5)
    }

    return [pscustomobject]@{
        BuildLabel = $BuildLabel
        CaseId     = $CaseId
        Runs       = $times.Count
        Missing    = $missing
        Median     = $median
        Min        = $minimum
        Max        = $maximum
        Spread     = $spread
        NeedsRerun = $needsRerun
        PeakMedian = (Get-Median $peaks)
        Mismatched = $mismatched
    }
}

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

Write-Host '== Preflight ==' -ForegroundColor Cyan

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
if (-not (Test-Path -LiteralPath $RunBench)) {
    throw "Bench tool not found: '$RunBench'. Run this from the repository root."
}
if (-not (Test-Path -LiteralPath $Work)) {
    throw "Work directory not found: '$Work'. Run this from the repository root, or pass -Work."
}

# run_bench.py hands these to the engine, whose working directory is the run
# folder, so relative paths would be unresolvable from there.
$Work = (Resolve-Path -LiteralPath $Work).Path
$RunsDir = Join-Path $Work 'runs'
$LogDir  = Join-Path (Join-Path $Work 'logs') 'bench-tile-size'

if (-not $CompareOnly) {
    if ([string]::IsNullOrEmpty($Engine)) { throw 'Pass -Engine, or use -CompareOnly.' }
    if ($TileSize -eq 0) { throw 'Pass -TileSize 40, 80 or 160, or use -CompareOnly.' }
    if (-not (Test-Path -LiteralPath $Engine)) { throw "Engine directory not found: '$Engine'." }
    $Engine = (Resolve-Path -LiteralPath $Engine).Path
    $engineExe = Join-Path $Engine 'slicer-engine.exe'
    if (-not (Test-Path -LiteralPath $engineExe)) {
        throw "slicer-engine.exe not found in '$Engine'."
    }
    Write-Host ("engine     : {0}" -f $Engine)
    Write-Host ("engine exe : {0}" -f (Get-Sha256 $engineExe).Substring(0, 12))
    Write-Host ("tile size  : T = {0}" -f $TileSize)
}

Write-Host ("work       : {0}" -f $Work)

# Golden digests, so every repeat can be checked for byte equality.
$goldenLayers = @{}
$goldenPreview = @{}
foreach ($case in $Cases) {
    $dir = Join-Path $RunsDir (Get-RunDirName $GoldenBuild $case.Id 1)
    $goldenLayers[$case.Id]  = Get-Sha256 (Join-Path $dir 'layers.sha256')
    $goldenPreview[$case.Id] = Get-Sha256 (Join-Path $dir 'preview.sha256')
    if ($null -eq $goldenLayers[$case.Id]) {
        Write-Host ("warning    : no Golden for {0}; byte equality will not be checked" -f $case.Id) -ForegroundColor Yellow
    }
}

if (-not (Test-Path -LiteralPath $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

# ---------------------------------------------------------------------------
# Measure one T
# ---------------------------------------------------------------------------

if (-not $CompareOnly) {
    $buildLabel = "$Build-T$TileSize"
    Write-Host ("build label: {0}" -f $buildLabel)

    # Settle the collisions before the first slice.
    $plan = @()
    foreach ($case in $Cases) {
        for ($repeat = 1; $repeat -le $Repeats; $repeat++) {
            $dir = Join-Path $RunsDir (Get-RunDirName $buildLabel $case.Id $repeat)
            if (Test-Path -LiteralPath $dir) {
                if ($Force) {
                    Write-Host ("removing   : {0}" -f $dir) -ForegroundColor Yellow
                    Remove-Item -LiteralPath $dir -Recurse -Force
                } else {
                    throw "Run directory already exists: '$dir'. Pass -Force to replace it, or -CompareOnly to just report."
                }
            }
            $plan += [pscustomobject]@{ CaseId = $case.Id; Repeat = $repeat }
        }
    }

    if ($IdleSeconds -le 0) {
        Write-Host 'warning    : -IdleSeconds 0, these numbers are a dry run and must not decide T' -ForegroundColor Yellow
    }

    Write-Host ''
    Write-Host '== Slicing ==' -ForegroundColor Cyan
    $index = 0
    foreach ($item in $plan) {
        $index++
        $log = Join-Path $LogDir ("run-T{0}-{1}-r{2}.log" -f $TileSize, $item.CaseId, $item.Repeat)

        if ($IdleSeconds -gt 0) {
            Write-Host ("[{0}/{1}] idling {2}s ... " -f $index, @($plan).Count, $IdleSeconds) -NoNewline
            Start-Sleep -Seconds $IdleSeconds
        } else {
            Write-Host ("[{0}/{1}] " -f $index, @($plan).Count) -NoNewline
        }
        Write-Host ("{0} r{1} ... " -f $item.CaseId, $item.Repeat) -NoNewline

        # Default thread count, and no SLA_RASTER_* at all: this is a timing run.
        $arguments = @(
            $RunBench,
            '--case',   $item.CaseId,
            '--engine', $Engine,
            '--build',  $buildLabel,
            '--repeat', [string] $item.Repeat,
            '--work',   $Work
        )

        $started = Get-Date
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
# Report
# ---------------------------------------------------------------------------

Write-Host ''
Write-Host '== Report ==' -ForegroundColor Cyan

$lines = @()
$lines += '# Task 2.23 - tile edge length T'
$lines += ''
$lines += ("- generated: {0}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
$lines += ("- repeats per case: {0}, engine default thread count, no SLA_RASTER_* set" -f $Repeats)
$lines += ("- reference: ``{0}`` runs in the same work directory" -f $GoldenBuild)
$lines += ''
$lines += '| T | Case | Runs | Median s | Min s | Max s | Spread s | vs base | Peak MB | Bytes equal | Rerun? |'
$lines += '| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |'

$anyRerun = $false
$anyMismatch = $false

foreach ($case in $Cases) {
    $baseStats = Get-CaseStats $RunsDir $GoldenBuild $case.Id $Repeats `
        $goldenLayers[$case.Id] $goldenPreview[$case.Id]

    $peakMb = '-'
    if ($null -ne $baseStats.PeakMedian) { $peakMb = '{0:N0}' -f ($baseStats.PeakMedian / 1MB) }
    $lines += ("| base | {0} | {1} | {2} | {3} | {4} | {5} | {6} | {7} | {8} | {9} |" -f `
        $case.Id, $baseStats.Runs, (Format-Seconds $baseStats.Median), (Format-Seconds $baseStats.Min), `
        (Format-Seconds $baseStats.Max), (Format-Seconds $baseStats.Spread), '100.0%', $peakMb, `
        'reference', $(if ($baseStats.NeedsRerun) { 'yes' } else { 'no' }))

    foreach ($size in $TileSizes) {
        $stats = Get-CaseStats $RunsDir "$Build-T$size" $case.Id $Repeats `
            $goldenLayers[$case.Id] $goldenPreview[$case.Id]
        if ($stats.Runs -eq 0) {
            $lines += ("| {0} | {1} | 0 | - | - | - | - | - | - | - | not measured |" -f $size, $case.Id)
            continue
        }

        $peakMb = '-'
        if ($null -ne $stats.PeakMedian) { $peakMb = '{0:N0}' -f ($stats.PeakMedian / 1MB) }
        $equal = 'yes'
        if ($null -eq $goldenLayers[$case.Id]) { $equal = 'not checked' }
        elseif ($stats.Mismatched -gt 0) { $equal = ("NO ({0})" -f $stats.Mismatched); $anyMismatch = $true }
        if ($stats.NeedsRerun) { $anyRerun = $true }

        $lines += ("| {0} | {1} | {2} | {3} | {4} | {5} | {6} | {7} | {8} | {9} | {10} |" -f `
            $size, $case.Id, $stats.Runs, (Format-Seconds $stats.Median), (Format-Seconds $stats.Min), `
            (Format-Seconds $stats.Max), (Format-Seconds $stats.Spread), `
            (Format-Ratio $stats.Median $baseStats.Median), $peakMb, $equal, `
            $(if ($stats.NeedsRerun) { 'YES' } else { 'no' }))
    }
}

$lines += ''
foreach ($case in $Cases) {
    $lines += ("- {0}: {1}" -f $case.Id, $case.Note)
}
$lines += '- `Rerun?` is YES when the spread is both over 5% of the median and over 0.5 s.'
$lines += '  Rerun that whole group of three, never a single repeat.'
$lines += '- `Bytes equal` compares each repeat against the Golden Baseline. Changing T'
$lines += '  must not change the output, so anything but `yes` is a defect, not a tuning result.'
$lines += ''
$lines += ("Per-run logs: ``{0}``" -f $LogDir)

$report = Join-Path $LogDir 'report.md'
$lines | Out-File -FilePath $report -Encoding utf8
$lines | ForEach-Object { Write-Host $_ }
Write-Host ''
Write-Host ("Saved to {0}" -f $report)

if ($anyMismatch) {
    Write-Host 'Some runs did not reproduce the Golden Baseline. Fix that before choosing T.' -ForegroundColor Red
    exit 1
}
if ($anyRerun) {
    Write-Host 'Some groups are too noisy to decide on. Rerun those groups of three.' -ForegroundColor Yellow
    exit 2
}
exit 0

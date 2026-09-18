#Requires -Version 5.1
<#
.SYNOPSIS
    Tasks 2.20 / 2.21 / 2.22: the three fallback configurations must still
    reproduce their reference fingerprints.

.DESCRIPTION
    Three single runs, each switching off one of the fast paths and comparing
    against the reference recorded from the unmodified engine in task 0.15/0.16:

      2.20  SLA_RASTER_FASTPATH=0 on the primary case    -> Golden Baseline
      2.21  blur = 1 on the tiny case                    -> the 0.16 blur reference
      2.22  SLA_LAYER_RLE unset on the tiny case         -> the 0.16 PNG reference

    All three run at the engine's default thread count and repeat 1, because that
    is what the references were recorded at.

    The engine environment goes through run_bench.py's --raster-env, never
    through $env:. run_bench.py drops every inherited SLA_* variable before it
    launches the engine, so setting them in the shell would be discarded.

    Nothing here compiles anything. Build and deploy the engine first, the same
    engine directory that verify_phase2_golden.ps1 used.

.PARAMETER Engine
    Engine directory holding slicer-engine.exe.

.PARAMETER Build
    Build label for the run directories. Default step2. Task 2.20 appends
    "-fastpath0" to it, so its run never collides with a normal one.

.PARAMETER GoldenBuild
    Build label of the reference runs. Default base.

.PARAMETER Verify
    Pass SLA_RASTER_VERIFY=1 to the engine. Default true. The tile map is kept
    up to date in all three configurations -- FASTPATH=0 included, where reset()
    clears the whole buffer through the renderer and then clears the map -- so
    the check is expected to stay silent. Pass -Verify:$false to leave it out.

.PARAMETER Force
    Delete a run directory that already exists instead of refusing.

.PARAMETER SkipRun
    Do not slice; only compare and report the runs that are already there.

.EXAMPLE
    .\scripts\raster_bench\verify_phase2_fallbacks.ps1 -Engine scripts\raster_bench\work\engines\step2-570c7c5e1
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string] $Engine,
    [string] $Build       = 'step2',
    [string] $GoldenBuild = 'base',
    [bool]   $Verify      = $true,
    [string] $Python      = '.venv\Scripts\python.exe',
    [string] $Work        = 'scripts\raster_bench\work',
    [switch] $Force,
    [switch] $SkipRun
)

# Stop on our own throws. Native commands go through Invoke-Native, which lowers
# this locally: PowerShell 5.1 turns a native program's stderr into an
# ErrorRecord, and under 'Stop' that would abort the run on the first failure
# instead of carrying on and reporting it in the table.
$ErrorActionPreference = 'Stop'

$Platform = 'windows'
$RunBench = 'scripts\raster_bench\run_bench.py'
$Compare  = 'scripts\raster_bench\compare_fingerprints.py'

# ---------------------------------------------------------------------------
# Helpers (same contract as verify_phase2_golden.ps1)
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

function Get-ShortHash([string] $Hash) {
    if ($null -eq $Hash) { return 'missing' }
    return $Hash.Substring(0, 12)
}

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

# Run directory name as run_bench.py builds it:
# <platform>-<build>-<case>[-<variant>]-t<threads>-r<repeat>
function Get-RunDirName([string] $BuildLabel, [string] $Case, [string] $Variant) {
    $segments = @($Platform, $BuildLabel, $Case)
    if (-not [string]::IsNullOrEmpty($Variant)) { $segments += $Variant }
    return (($segments -join '-') + '-tdefault-r1')
}

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

Write-Host '== Preflight ==' -ForegroundColor Cyan

# -Python may be a path (.venv\Scripts\python.exe) or a command on PATH.
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
# the run folder. Relative paths would be unresolvable from there.
if (-not (Test-Path -LiteralPath $Work)) {
    throw "Work directory not found: '$Work'. Run this from the repository root, or pass -Work."
}
$Work = (Resolve-Path -LiteralPath $Work).Path
if (-not (Test-Path -LiteralPath $Engine)) {
    throw "Engine directory not found: '$Engine'."
}
$Engine = (Resolve-Path -LiteralPath $Engine).Path

$LogDir  = Join-Path (Join-Path $Work 'logs') 'verify-phase2-fallbacks'
$RunsDir = Join-Path $Work 'runs'

$engineExe = Join-Path $Engine 'slicer-engine.exe'
if (-not (Test-Path -LiteralPath $engineExe)) {
    throw "slicer-engine.exe not found in '$Engine'."
}

Write-Host ("python     : {0}" -f $pythonExe)
Write-Host ("work       : {0}" -f $Work)
Write-Host ("engine     : {0}" -f $Engine)
Write-Host ("engine exe : {0}" -f (Get-ShortHash (Get-Sha256 $engineExe)))
Write-Host ("verify     : {0}" -f $Verify)

# ---------------------------------------------------------------------------
# The three checks. Each one turns off exactly one fast path and is compared
# against the reference recorded from the unmodified engine.
# ---------------------------------------------------------------------------

$checks = @(
    [pscustomobject]@{
        Task       = '2.20'
        What       = 'SLA_RASTER_FASTPATH=0'
        Case       = 'primary-16k-guide-x8'
        BuildLabel = "$Build-fastpath0"   # FASTPATH is an env var, not a variant,
        Variant    = ''                   # so the build label keeps runs apart
        RefBuild   = $GoldenBuild
        RefVariant = ''
        Extra      = @('--raster-env', 'SLA_RASTER_FASTPATH=0')
    },
    [pscustomobject]@{
        Task       = '2.21'
        What       = 'blur = 1'
        Case       = 'tiny-16k-crown-x1'
        BuildLabel = $Build
        Variant    = 'blur1'              # run_bench derives this from --raster-param
        RefBuild   = $GoldenBuild
        RefVariant = 'blur1'
        Extra      = @('--raster-param', 'blur=1')
    },
    [pscustomobject]@{
        Task       = '2.22'
        What       = 'SLA_LAYER_RLE unset (PNG layers)'
        Case       = 'tiny-16k-crown-x1'
        BuildLabel = $Build
        Variant    = 'norle'
        RefBuild   = $GoldenBuild
        RefVariant = 'norle'
        Extra      = @('--disable-rle')
    }
)

# Resolve both directory names for every check, and settle the
# reference-exists and directory-collision questions before the first slice.
foreach ($check in $checks) {
    $refDir = Join-Path $RunsDir (Get-RunDirName $check.RefBuild $check.Case $check.RefVariant)
    if (-not (Test-Path -LiteralPath (Join-Path $refDir 'layers.sha256'))) {
        throw "Task $($check.Task): reference run missing, expected '$refDir' with layers.sha256."
    }
    $runDir = Join-Path $RunsDir (Get-RunDirName $check.BuildLabel $check.Case $check.Variant)
    if ((Test-Path -LiteralPath $runDir) -and (-not $SkipRun)) {
        if ($Force) {
            Write-Host ("removing   : {0}" -f $runDir) -ForegroundColor Yellow
            Remove-Item -LiteralPath $runDir -Recurse -Force
        } else {
            throw "Run directory already exists: '$runDir'. Pass -Force to replace it, or -SkipRun to only compare."
        }
    }
    $check | Add-Member -NotePropertyName RefDir -NotePropertyValue $refDir -Force
    $check | Add-Member -NotePropertyName RunDir -NotePropertyValue $runDir -Force
}

if (-not (Test-Path -LiteralPath $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
Write-Host ("logs       : {0}" -f $LogDir)
Write-Host ("checks     : {0}" -f @($checks).Count)

# ---------------------------------------------------------------------------
# Slice
# ---------------------------------------------------------------------------

if ($SkipRun) {
    Write-Host ''
    Write-Host '== Slicing skipped (-SkipRun) ==' -ForegroundColor Yellow
} else {
    Write-Host ''
    Write-Host '== Slicing ==' -ForegroundColor Cyan
    $index = 0
    foreach ($check in $checks) {
        $index++
        $log = Join-Path $LogDir ("run-{0}.log" -f $check.Task)
        Write-Host ("[{0}/{1}] {2} {3} ... " -f $index, @($checks).Count, $check.Task, $check.What) -NoNewline

        # No --threads: the references were recorded at the engine default.
        $arguments = @(
            $RunBench,
            '--case',   $check.Case,
            '--engine', $Engine,
            '--build',  $check.BuildLabel,
            '--repeat', '1',
            '--work',   $Work
        )
        if ($Verify) { $arguments += @('--raster-env', 'SLA_RASTER_VERIFY=1') }
        $arguments += $check.Extra

        $started = Get-Date
        # A failing run is recorded and the loop carries on, so one bad check
        # still leaves a table.
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
# Compare
# ---------------------------------------------------------------------------

Write-Host ''
Write-Host '== Comparing against the references ==' -ForegroundColor Cyan

$results = @()
foreach ($check in $checks) {
    $log = Join-Path $LogDir ("compare-{0}.log" -f $check.Task)

    $row = [pscustomobject]@{
        Task          = $check.Task
        What          = $check.What
        Case          = $check.Case
        Reference     = Split-Path -Leaf $check.RefDir
        LayersRef     = Get-Sha256 (Join-Path $check.RefDir 'layers.sha256')
        LayersRun     = $null
        PreviewRef    = Get-Sha256 (Join-Path $check.RefDir 'preview.sha256')
        PreviewRun    = $null
        CompareExit   = $null
        VerifyLines   = $null
        Seconds       = $null
        Status        = 'FAIL'
        Note          = ''
    }

    if (-not (Test-Path -LiteralPath (Join-Path $check.RunDir 'layers.sha256'))) {
        $row.Note = 'run missing'
        $results += $row
        Write-Host ("{0}: run missing" -f $check.Task) -ForegroundColor Red
        continue
    }

    $row.LayersRun   = Get-Sha256 (Join-Path $check.RunDir 'layers.sha256')
    $row.PreviewRun  = Get-Sha256 (Join-Path $check.RunDir 'preview.sha256')
    $row.VerifyLines = Get-VerifyLineCount $check.RunDir
    $row.Seconds     = Get-TotalWallSeconds $check.RunDir

    $row.CompareExit = Invoke-Native -Exe $pythonExe `
        -Arguments @($Compare, $check.RefDir, $check.RunDir) -LogPath $log

    $notes = @()
    if ($row.CompareExit -ne 0) { $notes += ("compare exit {0}" -f $row.CompareExit) }
    if ($row.LayersRun  -ne $row.LayersRef)  { $notes += 'layers differ' }
    if ($row.PreviewRun -ne $row.PreviewRef) { $notes += 'preview differ' }
    if ($Verify -and $row.VerifyLines -gt 0) { $notes += ("{0} verify hits" -f $row.VerifyLines) }
    if ($row.VerifyLines -lt 0) { $notes += 'no stderr.log' }

    if ($notes.Count -eq 0) {
        $row.Status = 'PASS'
        Write-Host ("{0}: PASS" -f $check.Task) -ForegroundColor Green
    } else {
        $row.Note = ($notes -join '; ')
        Write-Host ("{0}: FAIL - {1}" -f $check.Task, $row.Note) -ForegroundColor Red
    }

    $results += $row
}

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

$passed = @($results | Where-Object { $_.Status -eq 'PASS' }).Count
$total  = @($results).Count

$lines = @()
$lines += '# Tasks 2.20 / 2.21 / 2.22 - fallback configurations'
$lines += ''
$lines += ("- generated: {0}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
$lines += ("- engine: ``{0}``" -f $Engine)
$lines += ("- engine exe sha256: ``{0}``" -f (Get-Sha256 $engineExe))
$lines += ("- build label: ``{0}``, reference label: ``{1}``" -f $Build, $GoldenBuild)
$lines += ("- SLA_RASTER_VERIFY: {0}" -f $(if ($Verify) { '1' } else { 'not set' }))
$lines += '- all runs at the engine default thread count, repeat 1, to match the references'
$lines += ("- result: **{0}/{1} PASS**" -f $passed, $total)
$lines += ''
$lines += '| Task | Fallback | Case | Reference run | Layers sha256 | Preview sha256 | verify hits | Wall s | Result | Note |'
$lines += '| --- | --- | --- | --- | --- | --- | ---: | ---: | --- | --- |'

foreach ($row in $results) {
    $layers  = "{0} / {1}" -f (Get-ShortHash $row.LayersRun),  (Get-ShortHash $row.LayersRef)
    $preview = "{0} / {1}" -f (Get-ShortHash $row.PreviewRun), (Get-ShortHash $row.PreviewRef)
    $seconds = '-'
    if ($null -ne $row.Seconds) { $seconds = [string] $row.Seconds }
    # Not $verify: PowerShell names are case-insensitive, so that would be the
    # [bool] -Verify parameter, and assigning a string to it coerces to True.
    $verifyCell = '-'
    if ($null -ne $row.VerifyLines) { $verifyCell = [string] $row.VerifyLines }

    $lines += ("| {0} | {1} | {2} | ``{3}`` | {4} | {5} | {6} | {7} | {8} | {9} |" -f `
        $row.Task, $row.What, $row.Case, $row.Reference, $layers, $preview, `
        $verifyCell, $seconds, $row.Status, $row.Note)
}

$lines += ''
$lines += 'Fingerprint columns are `run / reference`: the SHA-256 of each run directory''s'
$lines += '`layers.sha256` and `preview.sha256`, which are themselves the per-layer and'
$lines += 'per-preview digests. Equal digests mean every layer and every preview image'
$lines += 'came out byte for byte identical to the reference recorded in task 0.15/0.16.'
$lines += ''
$lines += ("Per-check logs: ``{0}``" -f $LogDir)

$report = Join-Path $LogDir 'report.md'
$lines | Out-File -FilePath $report -Encoding utf8

Write-Host ''
Write-Host '== Report ==' -ForegroundColor Cyan
$lines | ForEach-Object { Write-Host $_ }
Write-Host ''
Write-Host ("Saved to {0}" -f $report)

if ($passed -eq $total) {
    Write-Host 'Every fallback reproduces its reference.' -ForegroundColor Green
    exit 0
}
Write-Host ("{0} of {1} checks did not match." -f ($total - $passed), $total) -ForegroundColor Red
exit 1

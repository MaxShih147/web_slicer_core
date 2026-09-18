#Requires -Version 5.1
<#
.SYNOPSIS
    Tasks 3.6, 3.7 and 3.26: schedule the Phase 3 acceptance runs and hand the
    verdict to acceptance_report.py.

.DESCRIPTION
    This script only decides WHICH runs to start and in what order. It computes
    no median, no spread and no threshold: every decision is read from the
    summary.json that acceptance_report.py writes (design.md D12, tasks 3.23).

    Stages, in order:

      gates  primary-16k-guide-x8, secondary-8k-guide-x3, fullplate-16k-slab.
             One round is base r1, final r1, base r2, final r2, base r3, final r3
             at the default thread count, labelled p3-base-aN / p3-final-aN.
             After each round the report is read again:
               PASS or FAIL                 -> the case is decided, nothing to run
               latest round asks a rerun    -> run round N+1 (new label, no collision)
               UNSTABLE                     -> stop; with -RestartUnstable archive the
                                               case's gate runs and start again at a1
               latest round incomplete      -> stop; with -RestartIncompleteRound
                                               archive that round and run it again
      tiny   tiny-16k-crown-x1, final engine only, repeats 1..3 (record only).
      curve  primary case, both engines interleaved at --threads 1, 2 and 4. The
             8-thread point is the latest gate round; only when the report says it
             is missing (the default runs did not use 8 threads) are --threads 8
             runs added.

    Archiving: run_bench.py refuses to overwrite a run directory, and an UNSTABLE
    case restarts at a1, whose directories already exist. Those directories are
    moved, never deleted, to <work>\superseded\<timestamp>-<case>-<reason>\ with
    an archive.json saying what was moved and why. A normal rerun never archives
    anything: it uses the next round label, and acceptance_report.py needs the
    earlier rounds in runs\ to prove each rerun was actually required.

    The script stops at the first failed slice, and at any identity, fingerprint
    or measurement problem the report lists. Its exit code is the final report's:
    0 PASS, 1 FAIL, 3 UNSTABLE, 4 INCOMPLETE, 2 usage error.

    Nothing here compiles anything, and no SLA_RASTER_* variable is ever passed.
    Run it from the repository root.

.PARAMETER Stage
    Stages to run: gates, tiny, curve. Default all three.

.PARAMETER IdleSeconds
    Seconds to wait before each slice so the machine settles. Default 60.

.PARAMETER RestartUnstable
    For an UNSTABLE case, archive its gate runs and start again at a1. Only use
    it after removing whatever disturbed the measurements.

.PARAMETER RestartIncompleteRound
    For a gate round that stopped part way (a failed or interrupted slice),
    archive that round and run it again from repeat 1.

.PARAMETER IncludePrz
    Add the end-to-end PRZ section (task 3.8) to the final report.

.PARAMETER DryRun
    Start no slice and move no directory. Print what the next step would do,
    based on the runs already on disk. The report is written to a temporary
    directory that is removed afterwards.

.EXAMPLE
    .\scripts\raster_bench\run_phase3_acceptance.ps1 -DryRun

.EXAMPLE
    .\scripts\raster_bench\run_phase3_acceptance.ps1 -Stage gates,tiny
#>
[CmdletBinding()]
param(
    [ValidateSet('gates', 'tiny', 'curve')][string[]] $Stage = @('gates', 'tiny', 'curve'),
    [string] $BaseEngine  = 'base-5bc83b08f',
    [string] $FinalEngine = 'final-22f2e310a',
    [string] $BaseLabel   = 'p3-base',
    [string] $FinalLabel  = 'p3-final',
    [int]    $IdleSeconds = 60,
    [string] $Python      = '.venv\Scripts\python.exe',
    [string] $Work        = 'scripts\raster_bench\work',
    [switch] $RestartUnstable,
    [switch] $RestartIncompleteRound,
    [switch] $IncludePrz,
    [switch] $DryRun
)

# Stop on our own throws. Native commands go through Invoke-Native, which lowers
# this locally so a program writing to stderr cannot abort the run.
$ErrorActionPreference = 'Stop'

$Platform      = 'windows'
$RunBench      = 'scripts\raster_bench\run_bench.py'
$ReportTool    = 'scripts\raster_bench\acceptance_report.py'
$GatedCases    = @('primary-16k-guide-x8', 'secondary-8k-guide-x3', 'fullplate-16k-slab')
$TinyCase      = 'tiny-16k-crown-x1'
$CurveCase     = 'primary-16k-guide-x8'
$CurveThreads  = @(1, 2, 4)
$Repeats       = @(1, 2, 3)
$MaxRounds     = 3
# A round decides at most one step, so this bounds a case at a1..a3 plus one
# restart, with slack for re-reading the report.
$MaxStepsPerCase = 8

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

function Get-Prop($Object, [string] $Name) {
    # Case ids contain '-', so summary.json keys are read through PSObject.
    if ($null -eq $Object) { return $null }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

function Get-Label([string] $Role, [int] $Round) {
    if ($Role -eq 'base') { return "$BaseLabel-a$Round" }
    return "$FinalLabel-a$Round"
}

function Get-RunDirName([string] $Label, [string] $CaseId, $Threads, [int] $Repeat) {
    $threadLabel = 'tdefault'
    if ($null -ne $Threads) { $threadLabel = "t$Threads" }
    return ('{0}-{1}-{2}-{3}-r{4}' -f $Platform, $Label, $CaseId, $threadLabel, $Repeat)
}

function Get-EngineDir([string] $Role) {
    if ($Role -eq 'base') { return (Join-Path $EnginesDir $BaseEngine) }
    return (Join-Path $EnginesDir $FinalEngine)
}

# Runs acceptance_report.py and returns its parsed summary.json. Exit code 2
# means the report could not read its input, which ends the schedule.
function Read-Report([string[]] $Sections, [string] $OutDir, [string] $LogName) {
    $arguments = @($ReportTool, '--work', $Work, '--out', $OutDir,
                   '--base-engine', $BaseEngine, '--final-engine', $FinalEngine,
                   '--base-label', $BaseLabel, '--final-label', $FinalLabel)
    foreach ($section in $Sections) { $arguments += @('--section', $section) }
    $log = Join-Path $LogDir $LogName
    $code = Invoke-Native -Exe $pythonExe -Arguments $arguments -LogPath $log
    if ($code -eq 2) {
        throw "acceptance_report.py could not read its input (exit 2); see $log"
    }
    $summaryPath = Join-Path $OutDir 'summary.json'
    $summary = Get-Content -LiteralPath $summaryPath -Raw -Encoding UTF8 | ConvertFrom-Json
    return [pscustomobject]@{ Code = $code; Summary = $summary }
}

function Assert-NoProblems($Summary) {
    $problems = @($Summary.problems)
    if ($problems.Count -eq 0) { return }
    Write-Host 'the report lists problems that no rerun can fix:' -ForegroundColor Red
    foreach ($problem in $problems) {
        $where = ''
        if ($problem.run) { $where = "$($problem.run): " }
        Write-Host ('  {0}: {1}{2}' -f $problem.kind, $where, $problem.detail) -ForegroundColor Red
    }
    if ($DryRun) {
        Write-Host '  (dry run: planning continues so the schedule can be inspected)' -ForegroundColor Yellow
        return
    }
    throw 'Stopping: fix the listed problems first (engine identity, Golden fingerprints or measurements).'
}

$script:sliceCount = 0

function Invoke-Slice([string] $Role, [int] $Round, [string] $CaseId, [int] $Repeat, $Threads) {
    $label = Get-Label $Role $Round
    $runDir = Join-Path $RunsDir (Get-RunDirName $label $CaseId $Threads $Repeat)
    $arguments = @($RunBench,
                   '--case',   $CaseId,
                   '--engine', (Get-EngineDir $Role),
                   '--build',  $label,
                   '--repeat', [string] $Repeat,
                   '--work',   $Work)
    if ($null -ne $Threads) { $arguments += @('--threads', [string] $Threads) }
    $script:sliceCount++

    $threadText = 'default threads'
    if ($null -ne $Threads) { $threadText = "--threads $Threads" }
    $what = ('{0} {1} r{2} {3} ({4})' -f $CaseId, $label, $Repeat, $threadText, $Role)
    if ($DryRun) {
        Write-Host ('  [plan {0}] {1}' -f $script:sliceCount, $what)
        return
    }
    if (Test-Path -LiteralPath $runDir) {
        throw "Run directory already exists: '$runDir'. Nothing was overwritten."
    }
    if ($IdleSeconds -gt 0) {
        Write-Host ('  idling {0}s ... ' -f $IdleSeconds) -NoNewline
        Start-Sleep -Seconds $IdleSeconds
    }
    Write-Host ('  [{0}] {1} ... ' -f $script:sliceCount, $what) -NoNewline
    $log = Join-Path $LogDir ('slice-{0}.log' -f (Split-Path -Leaf $runDir))
    $started = Get-Date
    $code = Invoke-Native -Exe $pythonExe -Arguments $arguments -LogPath $log
    $elapsed = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
    if ($code -ne 0) {
        Write-Host ('FAILED (exit {0})' -f $code) -ForegroundColor Red
        throw "Slice failed; see $log. Its round is now incomplete (-RestartIncompleteRound runs it again)."
    }
    Write-Host ('done in {0}s' -f $elapsed) -ForegroundColor Green
}

# One gate round, interleaved so drift in temperature or load falls on both engines.
function Invoke-GateRound([string] $CaseId, [int] $Round) {
    foreach ($repeat in $Repeats) {
        foreach ($role in @('base', 'final')) {
            $runDir = Join-Path $RunsDir (Get-RunDirName (Get-Label $role $Round) $CaseId $null $repeat)
            if ((-not $DryRun) -and (Test-Path -LiteralPath $runDir)) {
                throw "Round a$Round of $CaseId already has '$runDir'. Nothing was started."
            }
        }
    }
    foreach ($repeat in $Repeats) {
        Invoke-Slice 'base'  $Round $CaseId $repeat $null
        Invoke-Slice 'final' $Round $CaseId $repeat $null
    }
}

# Moves run directories out of runs\ so their names can be used again. Never deletes.
function Move-ToSuperseded([string] $CaseId, [string] $Reason, [object[]] $Runs, [string] $Status) {
    $stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
    $target = Join-Path $SupersededDir ('{0}-{1}-{2}' -f $stamp, $CaseId, $Reason)
    $names = @($Runs | ForEach-Object { $_.run_id } | Sort-Object)
    Write-Host ('  archive {0} run(s) of {1} ({2}) to {3}' -f $names.Count, $CaseId, $Reason, $target) -ForegroundColor Yellow
    foreach ($name in $names) { Write-Host ('    {0}' -f $name) }
    if ($DryRun) { return }

    New-Item -ItemType Directory -Path $target -Force | Out-Null
    foreach ($name in $names) {
        Move-Item -LiteralPath (Join-Path $RunsDir $name) -Destination (Join-Path $target $name)
    }
    $record = [ordered]@{
        moved_at_utc  = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
        case          = $CaseId
        reason        = $Reason
        report_status = $Status
        runs          = $names
    }
    $record | ConvertTo-Json -Depth 4 | Out-File -FilePath (Join-Path $target 'archive.json') -Encoding utf8
}

# Gate runs of one case the report knows about, optionally limited to one round.
function Get-GateRuns($Summary, [string] $CaseId, $Round) {
    return @(@($Summary.runs) | Where-Object {
        $_.case -eq $CaseId -and $null -eq $_.threads_requested -and $null -eq $_.excluded -and
        ($null -eq $Round -or $_.round -eq $Round)
    })
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
foreach ($tool in @($RunBench, $ReportTool)) {
    if (-not (Test-Path -LiteralPath $tool)) { throw "Tool not found: '$tool'. Run this from the repository root." }
}
if (-not (Test-Path -LiteralPath $Work)) {
    throw "Work directory not found: '$Work'. Run this from the repository root, or pass -Work."
}

# run_bench.py hands these to the engine, whose working directory is the run
# folder, so relative paths would be unresolvable from there.
$Work          = (Resolve-Path -LiteralPath $Work).Path
$RunsDir       = Join-Path $Work 'runs'
$EnginesDir    = Join-Path $Work 'engines'
$SupersededDir = Join-Path $Work 'superseded'
$LogDir        = Join-Path (Join-Path $Work 'logs') 'phase3-acceptance'

$missingEngine = $false
foreach ($name in @($BaseEngine, $FinalEngine)) {
    foreach ($file in @('slicer-engine.exe', 'slicer_core.dll', 'build_info.json')) {
        if (-not (Test-Path -LiteralPath (Join-Path (Join-Path $EnginesDir $name) $file))) {
            Write-Host ('missing    : {0}\{1}' -f $name, $file) -ForegroundColor Yellow
            $missingEngine = $true
        }
    }
}
if ($missingEngine -and -not $DryRun) {
    throw 'Both engines need slicer-engine.exe, slicer_core.dll and build_info.json (task 3.1).'
}
foreach ($name in @(Get-ChildItem Env: | Where-Object { $_.Name -like 'SLA_RASTER_*' } | ForEach-Object { $_.Name })) {
    Write-Host ('note       : {0} is set in this shell; run_bench.py drops it for the engine' -f $name) -ForegroundColor Yellow
}

if ($DryRun) {
    $ReportDir = Join-Path ([IO.Path]::GetTempPath()) ('phase3-dryrun-' + [guid]::NewGuid().ToString('N'))
    $LogDir = Join-Path $ReportDir 'logs'
} else {
    $ReportDir = Join-Path (Join-Path $Work 'acceptance') 'scheduler'
}
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

Write-Host ('work       : {0}' -f $Work)
Write-Host ('engines    : base {0}, final {1}' -f $BaseEngine, $FinalEngine)
Write-Host ('labels     : {0}-aN, {1}-aN' -f $BaseLabel, $FinalLabel)
Write-Host ('stages     : {0}' -f ($Stage -join ', '))
if ($DryRun) {
    Write-Host 'mode       : DRY RUN (no slice, no move)' -ForegroundColor Yellow
} elseif ($IdleSeconds -le 0) {
    Write-Host 'warning    : -IdleSeconds 0, these numbers must not decide acceptance' -ForegroundColor Yellow
}

try {
    # -----------------------------------------------------------------------
    # Gates
    # -----------------------------------------------------------------------
    if ($Stage -contains 'gates') {
        Write-Host ''
        Write-Host '== Gates ==' -ForegroundColor Cyan
        foreach ($caseId in $GatedCases) {
            for ($step = 1; $step -le $MaxStepsPerCase; $step++) {
                $report = Read-Report @('gates') $ReportDir ('report-gates-{0}-{1}.log' -f $caseId, $step)
                Assert-NoProblems $report.Summary
                $gate = Get-Prop $report.Summary.gates $caseId
                $rounds = @($gate.rounds)
                $latest = $null
                if ($rounds.Count -gt 0) { $latest = $rounds[$rounds.Count - 1] }
                Write-Host ('{0}: {1}' -f $caseId, $gate.status) -NoNewline
                if ($gate.reason) { Write-Host (' - {0}' -f $gate.reason) } else { Write-Host '' }

                $nextRound = $null
                switch ($gate.status) {
                    'PASS' { }
                    'FAIL' { }
                    'UNSTABLE' {
                        if ($RestartUnstable) {
                            Move-ToSuperseded $caseId 'unstable' (Get-GateRuns $report.Summary $caseId $null) $gate.status
                            $nextRound = 1
                        } else {
                            Write-Host '  stopped: remove the interference, then pass -RestartUnstable' -ForegroundColor Yellow
                        }
                    }
                    'INCOMPLETE' {
                        if ($null -eq $latest) {
                            $nextRound = 1
                        } elseif ($latest.complete -and $latest.triggers_rerun) {
                            if ($latest.round -lt $MaxRounds) { $nextRound = $latest.round + 1 }
                        } elseif (-not $latest.complete) {
                            if ($RestartIncompleteRound) {
                                Move-ToSuperseded $caseId ('incomplete-a{0}' -f $latest.round) `
                                    (Get-GateRuns $report.Summary $caseId $latest.round) $gate.status
                                $nextRound = $latest.round
                            } else {
                                Write-Host ('  stopped: round a{0} is incomplete; pass -RestartIncompleteRound to run it again' `
                                    -f $latest.round) -ForegroundColor Yellow
                            }
                        }
                    }
                }
                if ($null -eq $nextRound) { break }

                Write-Host ('  round a{0}:' -f $nextRound)
                Invoke-GateRound $caseId $nextRound
                # The dry run cannot see the outcome of a round it did not run.
                if ($DryRun) { break }
            }
        }
    }

    # -----------------------------------------------------------------------
    # Tiny case (record only)
    # -----------------------------------------------------------------------
    if ($Stage -contains 'tiny') {
        Write-Host ''
        Write-Host '== Tiny case (record only) ==' -ForegroundColor Cyan
        $planned = 0
        foreach ($repeat in $Repeats) {
            $runDir = Join-Path $RunsDir (Get-RunDirName (Get-Label 'final' 1) $TinyCase $null $repeat)
            if (-not (Test-Path -LiteralPath $runDir)) {
                Invoke-Slice 'final' 1 $TinyCase $repeat $null
                $planned++
            }
        }
        if ($planned -eq 0) { Write-Host ('{0}: repeats 1..3 already on disk' -f $TinyCase) }
    }

    # -----------------------------------------------------------------------
    # Thread scaling curve (record only)
    # -----------------------------------------------------------------------
    if ($Stage -contains 'curve') {
        Write-Host ''
        Write-Host '== Thread scaling curve (record only) ==' -ForegroundColor Cyan
        # Curve runs have no rerun rule, so an interrupted point is completed
        # from its missing repeats instead of being archived.
        $planned = 0
        foreach ($threads in $CurveThreads) {
            foreach ($repeat in $Repeats) {
                foreach ($role in @('base', 'final')) {
                    $runDir = Join-Path $RunsDir (Get-RunDirName (Get-Label $role 1) $CurveCase $threads $repeat)
                    if (-not (Test-Path -LiteralPath $runDir)) {
                        Invoke-Slice $role 1 $CurveCase $repeat $threads
                        $planned++
                    }
                }
            }
        }
        if ($planned -eq 0) { Write-Host '--threads 1, 2 and 4: already on disk' }

        $report = Read-Report @('gates', 'curve') $ReportDir 'report-curve.log'
        Assert-NoProblems $report.Summary
        $primary = Get-Prop $report.Summary.gates $CurveCase
        if (@('PASS', 'FAIL') -notcontains $primary.status) {
            Write-Host ('8 threads  : waiting for the {0} gate ({1})' -f $CurveCase, $primary.status) -ForegroundColor Yellow
        } else {
            foreach ($point in @($report.Summary.curve.points | Where-Object { $_.threads -eq 8 })) {
                if ($point.status -eq 'PASS') {
                    Write-Host ('8 threads  : {0} from {1}' -f $point.engine, $point.source)
                    continue
                }
                foreach ($repeat in $Repeats) {
                    $runDir = Join-Path $RunsDir (Get-RunDirName (Get-Label $point.engine 1) $CurveCase 8 $repeat)
                    if (-not (Test-Path -LiteralPath $runDir)) { Invoke-Slice $point.engine 1 $CurveCase $repeat 8 }
                }
            }
        }
    }

    # -----------------------------------------------------------------------
    # Final report
    # -----------------------------------------------------------------------
    Write-Host ''
    Write-Host '== Report ==' -ForegroundColor Cyan
    $sections = @('gates', 'curve')
    if ($IncludePrz) { $sections += 'prz' }
    $finalDir = $ReportDir
    if (-not $DryRun) { $finalDir = Join-Path $Work 'acceptance' }
    $final = Read-Report $sections $finalDir 'report-final.log'
    Write-Host ('verdict    : {0} (exit {1})' -f $final.Summary.verdict, $final.Code)
    Write-Host ('summary    : {0}' -f (Join-Path $finalDir 'summary.json'))
    if ($DryRun) {
        Write-Host ('planned    : {0} slice(s) for the next step' -f $script:sliceCount)
        exit 0
    }
    exit $final.Code
} finally {
    if ($DryRun -and (Test-Path -LiteralPath $ReportDir)) {
        Remove-Item -LiteralPath $ReportDir -Recurse -Force
    }
}

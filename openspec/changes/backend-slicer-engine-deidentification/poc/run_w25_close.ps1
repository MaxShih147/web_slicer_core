# Windows 2.5 PoC close: three crash modes + WER LocalDumps + static checks.
# Requires QA build with BUNDLE_QA_CRASH_HARNESS=ON (slicer-engine.exe + slicer_core.dll).

param(
    [string]$EngineDir = "",
    [string]$OutRoot = ""
)

$ErrorActionPreference = "Stop"
$ChangeRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (-not $EngineDir) {
    $EngineDir = Join-Path $ChangeRoot "..\..\..\third_party\prusaslicer_build\src\Release" | Resolve-Path -ErrorAction SilentlyContinue
    if (-not $EngineDir) {
        $EngineDir = "C:\Phrozen3D\Lechon\03_Development\Win\web_slicer_core\third_party\prusaslicer_build\src\Release"
    }
}
$EngineDir = (Resolve-Path $EngineDir).Path
$exe = Join-Path $EngineDir "slicer-engine.exe"
$dll = Join-Path $EngineDir "slicer_core.dll"
if (-not (Test-Path $exe)) { throw "Missing $exe — build QA flavor first" }
if (-not (Test-Path $dll)) { throw "Missing $dll" }

$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
if (-not $OutRoot) {
    $OutRoot = Join-Path $PSScriptRoot "evidence\w25-close-$stamp"
}
New-Item -ItemType Directory -Force -Path $OutRoot, (Join-Path $OutRoot "dumps"), (Join-Path $OutRoot "static"), (Join-Path $OutRoot "wer") | Out-Null

$dumpbin = Get-ChildItem "${env:ProgramFiles}\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC" -Recurse -Filter dumpbin.exe -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -match '\\Hostx64\\x64\\' } | Select-Object -First 1 -ExpandProperty FullName
if (-not $dumpbin) {
    $dumpbin = "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.29.30133\bin\HostX64\x64\dumpbin.exe"
}

# Static checks
& $dumpbin /EXPORTS $dll 2>&1 | Out-File -Encoding utf8 (Join-Path $OutRoot "static\EXPORTS.txt")
& $dumpbin /HEADERS $exe 2>&1 | Out-File -Encoding utf8 (Join-Path $OutRoot "static\HEADERS_exe.txt")
& $dumpbin /HEADERS $dll 2>&1 | Out-File -Encoding utf8 (Join-Path $OutRoot "static\HEADERS_dll.txt")

function Get-Vi([string]$path) {
    $vi = [Diagnostics.FileVersionInfo]::GetVersionInfo($path)
    @(
        "File=$path"
        "CompanyName=$($vi.CompanyName)"
        "ProductName=$($vi.ProductName)"
        "FileDescription=$($vi.FileDescription)"
        "InternalName=$($vi.InternalName)"
        "OriginalFilename=$($vi.OriginalFilename)"
        "FileVersion=$($vi.FileVersion)"
        "ProductVersion=$($vi.ProductVersion)"
    ) -join "`n"
}
((Get-Vi $exe) + "`n---`n" + (Get-Vi $dll)) | Set-Content -Encoding utf8 (Join-Path $OutRoot "static\VERSIONINFO.txt")

$exp = Get-Content (Join-Path $OutRoot "static\EXPORTS.txt") -Raw
$hasOld = $exp -match '\bslic3r_main\b'
$hasNew = $exp -match '\bslicer_run_cli\b'
$named = ([regex]::Matches($exp, '(?m)^\s+\d+\s+[0-9A-F]+\s+[0-9A-F]+\s+\S+')).Count
@"
slicer_run_cli=$hasNew
slic3r_main=$hasOld
named_exports_approx=$named
exe_sha256=$((Get-FileHash $exe -Algorithm SHA256).Hash)
dll_sha256=$((Get-FileHash $dll -Algorithm SHA256).Hash)
"@ | Set-Content (Join-Path $OutRoot "static\EXPORT_SUMMARY.txt")

# LocalDumps
$ld = "HKCU:\Software\Microsoft\Windows\Windows Error Reporting\LocalDumps\slicer-engine.exe"
New-Item -Path $ld -Force | Out-Null
New-ItemProperty -Path $ld -Name DumpFolder -Value (Join-Path $OutRoot "dumps") -PropertyType ExpandString -Force | Out-Null
New-ItemProperty -Path $ld -Name DumpType -Value 2 -PropertyType DWord -Force | Out-Null
New-ItemProperty -Path $ld -Name DumpCount -Value 20 -PropertyType DWord -Force | Out-Null

$modes = @("overflow", "segfault", "exception")
$results = @()
foreach ($mode in $modes) {
    $beforeNames = @(Get-ChildItem (Join-Path $OutRoot "dumps") -Filter *.dmp -ErrorAction SilentlyContinue | ForEach-Object { $_.Name })
    $env:BUNDLE_QA_CRASH_MODE = $mode
    $p = Start-Process -FilePath $exe -ArgumentList "--help" -WorkingDirectory $EngineDir -PassThru -Wait -NoNewWindow `
        -RedirectStandardOutput (Join-Path $OutRoot "wer\$mode.stdout.txt") `
        -RedirectStandardError (Join-Path $OutRoot "wer\$mode.stderr.txt")
    Remove-Item Env:BUNDLE_QA_CRASH_MODE -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
    $after = @(Get-ChildItem (Join-Path $OutRoot "dumps") -Filter *.dmp -ErrorAction SilentlyContinue)
    $newDumps = @($after | Where-Object { $beforeNames -notcontains $_.Name })
    if (-not $newDumps -or $newDumps.Count -eq 0) {
        $newDumps = @($after | Sort-Object LastWriteTime -Descending | Select-Object -First 1)
    }
    $dumpName = if ($newDumps -and $newDumps.Count -gt 0 -and $newDumps[0]) { $newDumps[0].Name } else { "MISSING" }
    $results += [pscustomobject]@{ mode = $mode; exit = $p.ExitCode; dump = $dumpName }
    "mode=$mode exit=$($p.ExitCode) dump=$dumpName" | Add-Content (Join-Path $OutRoot "wer\CRASH_LOG.txt")
}

$results | ConvertTo-Json | Set-Content (Join-Path $OutRoot "SUMMARY.json")
@"
# Windows 2.5 PoC run ``$((Split-Path $OutRoot -Leaf))``

- exe: ``$exe``
- dll: ``$dll``
- slicer_run_cli: $hasNew
- slic3r_main: $hasOld
- named_exports_approx: $named

## Crashes
$($results | ForEach-Object { "- $($_.mode): exit=$($_.exit) dump=$($_.dump)" } | Out-String)
"@ | Set-Content -Encoding utf8 (Join-Path $OutRoot "SUMMARY.md")

Write-Host "OUT=$OutRoot"
Get-Content (Join-Path $OutRoot "SUMMARY.md")

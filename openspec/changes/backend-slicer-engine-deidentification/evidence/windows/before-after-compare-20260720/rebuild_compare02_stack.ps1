# Rebuild COMPARE_02 + individual crash stack shots from authentic cdb log excerpts.
# Before = lm + k brand frames (postload baseline). After = AV + slicer_run_cli (segfault PoC).
# Verbatim lines from BEFORE_crash_minidump_stack.txt / AFTER_crash_minidump_stack_segfault.txt.

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

$Root = $PSScriptRoot
$Shots = Join-Path $Root 'shots'
$BeforeLog = Join-Path $Root 'BEFORE_crash_minidump_stack.txt'
$AfterLog = Join-Path $Root 'AFTER_crash_minidump_stack_segfault.txt'

$beforeLines = @(
  'SOURCE  win-baseline-20260717T055632Z / postload-baseline.dmp',
  'PROOF   PDB-free cdb  lm + k  (brand frames - not WinDbg boilerplate)',
  '',
  '0:000> lm',
  'start             end                 module name',
  "00007ff7``c3ac0000 00007ff7``c3ae5000   prusa_slicer_console   (deferred)",
  "00007ffd``644b0000 00007ffd``6551f000   PrusaSlicer   (deferred)",
  "00007ffd``e9410000 00007ffd``e941c000   VCRUNTIME140_1   (deferred)",
  "00007ffd``e9450000 00007ffd``e94d9000   msvcp140   (deferred)",
  "00007ffe``08700000 00007ffe``08966000   ntdll      (pdb symbols)",
  '',
  '0:000> k',
  'Child-SP          RetAddr               Call Site',
  "000000a9``8f5be2e8 00007ffe``087998e1     ntdll!NtMapViewOfSection+0x14",
  '  ... ntdll Ldr* frames ...',
  '*** WARNING: Unable to verify checksum for prusa-slicer-console.exe',
  "000000a9``8f5becb0 00007ff7``c3ac1b03     KERNELBASE!LoadLibraryExW+0xff",
  "000000a9``8f5bed20 00007ff7``c3ac1f3c     prusa_slicer_console!wmain+0x1c3",
  '(Inline Function) --------`--------     prusa_slicer_console!invoke_main+0x22',
  "000000a9``8f5bf7c0 00007ffe``0777e957     prusa_slicer_console!__scrt_common_main_seh+0x10c",
  "000000a9``8f5bf800 00007ffe``08787c1c     kernel32!BaseThreadInitThunk+0x17"
)

$afterLines = @(
  'SOURCE  w25-close-20260717T083241Z / dumps/segfault.dmp',
  'PROOF   PDB-free cdb  AV fault + lm m slicer* + k',
  '',
  'This dump file has an exception of interest stored in it.',
  '(7104.6f1c): Access violation - code c0000005 (first/second chance not available)',
  '*** WARNING: Unable to verify checksum for slicer_core.dll',
  'slicer_core!slicer_run_cli+0x84580:',
  "00007ffc``f14a10b0 c70001000000    mov     dword ptr [rax],1 ds:00000000``00000000=????????",
  '',
  '0:000> lm m slicer*',
  'start             end                 module name',
  "00007ff7``ebd50000 00007ff7``ebd75000   slicer_engine   (deferred)",
  "00007ffc``f13b0000 00007ffc``f3f88000   slicer_core C (export symbols)       slicer_core.dll",
  '',
  '0:000> k',
  'Child-SP          RetAddr               Call Site',
  "000000f1``f34fee00 00007ffc``f14a120b     slicer_core!slicer_run_cli+0x84580",
  "000000f1``f34fee20 00007ffc``f141cb59     slicer_core!slicer_run_cli+0x846db",
  '*** WARNING: Unable to verify checksum for slicer-engine.exe',
  "000000f1``f34fee80 00007ff7``ebd51b5e     slicer_core!slicer_run_cli+0x29",
  "000000f1``f34fef20 00007ff7``ebd51f3c     slicer_engine+0x1b5e",
  "000000f1``f34ff9c0 00007ffe``0777e957     slicer_engine+0x1f3c",
  "000000f1``f34ffa00 00007ffe``08787c1c     kernel32!BaseThreadInitThunk+0x17"
)

# Sanity: brand tokens must exist in source logs
$beforeRaw = Get-Content -LiteralPath $BeforeLog -Raw
$afterRaw = Get-Content -LiteralPath $AfterLog -Raw
foreach ($tok in @('prusa_slicer_console', 'PrusaSlicer', 'prusa-slicer-console.exe', 'wmain')) {
  if ($beforeRaw -notmatch [regex]::Escape($tok)) { throw "BEFORE log missing token: $tok" }
}
foreach ($tok in @('Access violation', 'slicer_core!slicer_run_cli', 'slicer_engine', 'slicer_core.dll')) {
  if ($afterRaw -notmatch [regex]::Escape($tok)) { throw "AFTER log missing token: $tok" }
}

function Test-HitLine([string]$line, [bool]$before) {
  if ($before) {
    return [bool]($line -match 'prusa_slicer_console|PrusaSlicer|prusa-slicer-console')
  }
  return [bool]($line -match 'slicer_core|slicer_engine|slicer_run_cli|Access violation|slicer-engine\.exe|slicer_core\.dll')
}

function Render-Panel {
  param(
    [string[]]$Lines,
    [string]$Title,
    [string]$OutPath,
    [bool]$Before
  )

  $pad = 18
  $lineH = 22
  $barH = 44
  $subH = 28
  $footH = 34
  $width = 920
  $height = $pad + $barH + $subH + ($Lines.Count * $lineH) + $footH + $pad

  $accent = if ($Before) { [System.Drawing.Color]::FromArgb(255, 232, 93, 76) } else { [System.Drawing.Color]::FromArgb(255, 46, 184, 138) }
  $accentFill = if ($Before) { [System.Drawing.Color]::FromArgb(55, 232, 93, 76) } else { [System.Drawing.Color]::FromArgb(45, 46, 184, 138) }
  $bg = [System.Drawing.Color]::FromArgb(255, 18, 20, 26)
  $fg = [System.Drawing.Color]::FromArgb(255, 230, 232, 238)
  $dim = [System.Drawing.Color]::FromArgb(255, 140, 148, 160)
  $cmd = [System.Drawing.Color]::FromArgb(255, 120, 180, 255)

  $bmp = New-Object System.Drawing.Bitmap $width, $height
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.Clear($bg)
  $g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::ClearTypeGridFit
  $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias

  $titleFont = New-Object System.Drawing.Font 'Segoe UI Semibold', 13, ([System.Drawing.FontStyle]::Bold)
  $mono = New-Object System.Drawing.Font 'Consolas', 11
  $small = New-Object System.Drawing.Font 'Segoe UI', 9

  $barBrush = New-Object System.Drawing.SolidBrush $accent
  $g.FillRectangle($barBrush, 0, 0, $width, $barH)
  $g.DrawString($Title, $titleFont, [System.Drawing.Brushes]::White, $pad, 11)

  $dimBrush = New-Object System.Drawing.SolidBrush $dim
  $note = if ($Before) {
    'verbatim excerpt from BEFORE_crash_minidump_stack.txt  |  red = prusa / PrusaSlicer'
  } else {
    'verbatim excerpt from AFTER_crash_minidump_stack_segfault.txt  |  green = slicer-engine / slicer_run_cli'
  }
  $g.DrawString($note, $small, $dimBrush, $pad, ($barH + 6))

  $y = $barH + $subH + 4
  $hits = 0
  foreach ($line in $Lines) {
    $isHit = Test-HitLine $line $Before
    $isCmd = $line -match '^0:000>'
    $isSrc = $line -match '^(SOURCE|PROOF)'
    if ($isHit) {
      $hits++
      $fill = New-Object System.Drawing.SolidBrush $accentFill
      $g.FillRectangle($fill, ($pad - 6), ($y - 1), ($width - $pad * 2 + 12), ($lineH - 1))
      $pen = New-Object System.Drawing.Pen $accent, 1.5
      $g.DrawRectangle($pen, ($pad - 6), ($y - 1), ($width - $pad * 2 + 12), ($lineH - 1))
      $pen.Dispose(); $fill.Dispose()
    }
    $brush = if ($isHit) {
      (New-Object System.Drawing.SolidBrush $accent)
    } elseif ($isCmd) {
      (New-Object System.Drawing.SolidBrush $cmd)
    } elseif ($isSrc) {
      $dimBrush
    } else {
      (New-Object System.Drawing.SolidBrush $fg)
    }
    $g.DrawString($line, $mono, $brush, $pad, $y)
    if (-not ($brush -eq $dimBrush)) { $brush.Dispose() }
    $y += $lineH
  }

  $footBg = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 10, 12, 16))
  $g.FillRectangle($footBg, 0, ($height - $footH), $width, $footH)
  $foot = if ($Before) {
    "BEFORE  brand hits=$hits  |  postload baseline (LoadLibrary) - not AV crash"
  } else {
    "AFTER  neutral hits=$hits  |  intentional AV segfault PoC - slicer_run_cli frames"
  }
  $accentBrush = New-Object System.Drawing.SolidBrush $accent
  $g.DrawString($foot, $small, $accentBrush, $pad, ($height - $footH + 9))

  $bmp.Save($OutPath, [System.Drawing.Imaging.ImageFormat]::Png)
  Write-Host "RENDER $OutPath hits=$hits"

  $accentBrush.Dispose(); $footBg.Dispose(); $dimBrush.Dispose(); $barBrush.Dispose()
  $small.Dispose(); $mono.Dispose(); $titleFont.Dispose()
  $g.Dispose(); $bmp.Dispose()
}

function Scale-ToWidth([System.Drawing.Image]$img, [int]$targetW) {
  $h = [int]([double]$img.Height * $targetW / $img.Width)
  $bmp = New-Object System.Drawing.Bitmap $targetW, $h
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
  $g.DrawImage($img, 0, 0, $targetW, $h)
  $g.Dispose()
  return $bmp
}

function Compose-Compare02([string]$LeftPath, [string]$RightPath, [string]$OutPath) {
  $leftSrc = [System.Drawing.Image]::FromFile($LeftPath)
  $rightSrc = [System.Drawing.Image]::FromFile($RightPath)
  $panelW = 780
  $left = Scale-ToWidth $leftSrc $panelW
  $right = Scale-ToWidth $rightSrc $panelW
  $leftSrc.Dispose(); $rightSrc.Dispose()

  $pad = 28
  $gap = 28
  $headerH = 96
  $labelH = 36
  $panelH = [Math]::Max($left.Height, $right.Height)
  $W = $pad * 2 + $panelW * 2 + $gap
  $H = $pad + $headerH + $labelH + $panelH + $pad + 28

  $bmp = New-Object System.Drawing.Bitmap $W, $H
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.Clear([System.Drawing.Color]::FromArgb(255, 248, 246, 242))
  $g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::ClearTypeGridFit
  $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic

  $titleFont = New-Object System.Drawing.Font 'Segoe UI Semibold', 18, ([System.Drawing.FontStyle]::Bold)
  $subFont = New-Object System.Drawing.Font 'Segoe UI', 11
  $labelFont = New-Object System.Drawing.Font 'Segoe UI Semibold', 12, ([System.Drawing.FontStyle]::Bold)
  $footFont = New-Object System.Drawing.Font 'Segoe UI', 9
  $ink = [System.Drawing.Brushes]::Black
  $muted = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 90, 92, 98))
  $beforeBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 200, 60, 45))
  $afterBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 20, 140, 100))

  $g.DrawString('Crash minidump stack - Before vs After (PDB-free cdb)', $titleFont, $ink, $pad, $pad)
  $g.DrawString('Differentiating frames only: BEFORE lm+k brand tokens  |  AFTER Access violation + slicer_run_cli  (boilerplate omitted)', $subFont, $muted, $pad, ($pad + 36))
  $g.DrawString('Sources: BEFORE_crash_minidump_stack.txt  ·  AFTER_crash_minidump_stack_segfault.txt', $subFont, $muted, $pad, ($pad + 58))

  $yLab = $pad + $headerH - 4
  $g.DrawString('BEFORE  ·  prusa_slicer_console / PrusaSlicer / wmain', $labelFont, $beforeBrush, ($pad + 8), $yLab)
  $g.DrawString('AFTER  ·  slicer_engine / slicer_core!slicer_run_cli', $labelFont, $afterBrush, ($pad + $panelW + $gap + 8), $yLab)

  $yImg = $yLab + $labelH
  $g.DrawImage($left, $pad, $yImg, $left.Width, $left.Height)
  $g.DrawImage($right, ($pad + $panelW + $gap), $yImg, $right.Width, $right.Height)

  $g.DrawString('backend-slicer-engine-deidentification / COMPARE_02 rebuild 2026-07-21 / authentic baseline + PoC dump excerpts', $footFont, $muted, $pad, ($H - $pad - 8))

  $bmp.Save($OutPath, [System.Drawing.Imaging.ImageFormat]::Png)
  Write-Host "COMPOSE $OutPath ($W x $H)"

  $afterBrush.Dispose(); $beforeBrush.Dispose(); $muted.Dispose()
  $footFont.Dispose(); $labelFont.Dispose(); $subFont.Dispose(); $titleFont.Dispose()
  $g.Dispose(); $bmp.Dispose()
  $left.Dispose(); $right.Dispose()
}

$beforeOut = Join-Path $Shots '04_BEFORE_crash_minidump_stack.png'
$afterOut = Join-Path $Shots '06_AFTER_crash_minidump_stack.png'
$compareOut = Join-Path $Shots 'COMPARE_02_crash_minidump_stack_before_vs_after.png'

Render-Panel -Lines $beforeLines -Title 'BEFORE - Crash minidump  lm + k brand frames' -OutPath $beforeOut -Before $true
Render-Panel -Lines $afterLines -Title 'AFTER - Crash minidump  AV + slicer_run_cli' -OutPath $afterOut -Before $false
Compose-Compare02 -LeftPath $beforeOut -RightPath $afterOut -OutPath $compareOut

Write-Host 'DONE'

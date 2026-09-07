# Clean-crop + annotate live WER OS screenshots (Explorer AppCrash_* + Report.wer Notepad).
# - Kills leftover Notepad tabs / find UI clutter
# - Recaptures single-tab Notepad of identity excerpts (verbatim WER fields)
# - Crops Explorer to address-bar + content (less sidebar noise)
# - Draws BEFORE(red) / AFTER(green) boxes on prusa|slic3r|slicer-engine tokens
# - Rebuilds COMPARE_04 / COMPARE_04b without overlapping labels
$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$OutDir = Join-Path $Here 'shots'
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

$drawing = [Reflection.Assembly]::LoadWithPartialName('System.Drawing').Location
Add-Type -ReferencedAssemblies $drawing -TypeDefinition @"
using System;
using System.Text;
using System.Threading;
using System.Runtime.InteropServices;
using System.Drawing;
using System.Drawing.Imaging;
using System.Drawing.Drawing2D;
using System.Collections.Generic;

public static class WerAnno {
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hwnd, IntPtr hdcBlt, uint nFlags);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool MoveWindow(IntPtr hWnd, int X, int Y, int nWidth, int nHeight, bool bRepaint);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }

  public static IntPtr FindTitleContains(string needle) {
    IntPtr found = IntPtr.Zero;
    EnumWindows((h, l) => {
      if (!IsWindowVisible(h)) return true;
      var sb = new StringBuilder(1024);
      GetWindowText(h, sb, sb.Capacity);
      if (sb.ToString().IndexOf(needle, StringComparison.OrdinalIgnoreCase) >= 0) { found = h; return false; }
      return true;
    }, IntPtr.Zero);
    return found;
  }

  public static void CloseAllNotepadish() {
    string[] needles = new[] { "Notepad", "Report.wer", "BEFORE_", "AFTER_", "identity" };
    for (int round = 0; round < 12; round++) {
      bool any = false;
      foreach (var n in needles) {
        IntPtr h = FindTitleContains(n);
        if (h != IntPtr.Zero) {
          SendMessage(h, 0x0010, IntPtr.Zero, IntPtr.Zero);
          any = true;
          Thread.Sleep(120);
        }
      }
      if (!any) break;
    }
  }

  public static void Save(IntPtr hwnd, string path, int forceW, int forceH) {
    SetProcessDPIAware();
    ShowWindow(hwnd, 9);
    if (forceW > 0 && forceH > 0) MoveWindow(hwnd, 40, 40, forceW, forceH, true);
    SetForegroundWindow(hwnd);
    Thread.Sleep(450);
    RECT r; GetWindowRect(hwnd, out r);
    int w = Math.Max(1, r.Right - r.Left);
    int h = Math.Max(1, r.Bottom - r.Top);
    using (var bmp = new Bitmap(w, h, PixelFormat.Format32bppArgb)) {
      using (var g = Graphics.FromImage(bmp)) {
        IntPtr hdc = g.GetHdc();
        bool ok = PrintWindow(hwnd, hdc, 2);
        g.ReleaseHdc(hdc);
        if (!ok) g.CopyFromScreen(r.Left, r.Top, 0, 0, new Size(w, h));
      }
      bmp.Save(path, ImageFormat.Png);
      Console.WriteLine("SAVED " + path + " " + w + "x" + h);
    }
  }

  public static Bitmap Crop(Bitmap src, int x, int y, int w, int h) {
    x = Math.Max(0, Math.Min(x, src.Width - 1));
    y = Math.Max(0, Math.Min(y, src.Height - 1));
    w = Math.Max(1, Math.Min(w, src.Width - x));
    h = Math.Max(1, Math.Min(h, src.Height - y));
    var rect = new Rectangle(x, y, w, h);
    return src.Clone(rect, src.PixelFormat);
  }

  public static void DrawBox(Graphics g, Rectangle r, Color color, string label) {
    using (var pen = new Pen(color, 3f)) {
      pen.Alignment = PenAlignment.Inset;
      g.DrawRectangle(pen, r);
    }
    if (!string.IsNullOrEmpty(label)) {
      using (var font = new Font("Segoe UI Semibold", 11f, FontStyle.Bold))
      using (var bg = new SolidBrush(Color.FromArgb(230, color)))
      using (var fg = new SolidBrush(Color.White)) {
        var sz = g.MeasureString(label, font);
        float lx = r.X;
        float ly = Math.Max(2, r.Y - sz.Height - 4);
        g.FillRectangle(bg, lx, ly, sz.Width + 10, sz.Height + 2);
        g.DrawString(label, font, fg, lx + 5, ly);
      }
    }
  }

  // Scan for near-black/dark-ink text rows that contain brand-ish pixel density bands.
  // Fallback used only as heuristics; primary annotations are placed by known UI regions + line index.
  public static List<Rectangle> EstimateLineRects(Bitmap bmp, int contentTop, int contentLeft, int contentRight, float lineH, int lineCount, int startLine) {
    var list = new List<Rectangle>();
    for (int i = 0; i < lineCount; i++) {
      int y = contentTop + (int)((startLine + i) * lineH);
      int h = Math.Max(16, (int)(lineH - 2));
      if (y + h >= bmp.Height) break;
      list.Add(new Rectangle(contentLeft, y, Math.Max(40, contentRight - contentLeft), h));
    }
    return list;
  }
}
"@

function New-IdentityExcerpt([string]$WerPath, [string]$OutPath, [string]$Side) {
  $raw = Get-Content -LiteralPath $WerPath -Encoding Unicode
  $keep = New-Object System.Collections.Generic.List[string]
  foreach ($line in $raw) {
    if ($line -match '^(Version|EventType|NsAppName|OriginalFilename|TargetAppId|TargetAppVer|AppSessionGuid|IsFatal|Sig\[|UI\[2\]|LoadedModule\[0\]|LoadedModule\[8\]|FriendlyEventName|AppName|AppPath)=') {
      if ($line.Length -lt 500) { [void]$keep.Add($line) }
    } elseif ($line -match '(?i)prusa|slic3r|slicer-engine|Slicer Engine|slicer_core' -and $line.Length -lt 400) {
      [void]$keep.Add($line)
    }
  }
  @(
    "# $Side WER identity fields (verbatim from live Report.wer)"
    "# Source file: $([IO.Path]::GetFileName($WerPath))"
    ""
  ) + $keep | Set-Content -LiteralPath $OutPath -Encoding UTF8
  return ,@($keep.ToArray())
}

function Capture-CleanNotepad([string]$Path, [string]$TitleNeedle, [string]$OutPng) {
  [WerAnno]::CloseAllNotepadish()
  Get-Process notepad -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  Start-Sleep -Milliseconds 400
  Start-Process notepad.exe -ArgumentList "`"$Path`""
  $hwnd = [IntPtr]::Zero
  for ($i = 0; $i -lt 50; $i++) {
    Start-Sleep -Milliseconds 200
    $hwnd = [WerAnno]::FindTitleContains($TitleNeedle)
    if ($hwnd -eq [IntPtr]::Zero) { $hwnd = [WerAnno]::FindTitleContains('Notepad') }
    if ($hwnd -eq [IntPtr]::Zero) { $hwnd = [WerAnno]::FindTitleContains('.identity.txt') }
    if ($hwnd -ne [IntPtr]::Zero) { break }
  }
  if ($hwnd -eq [IntPtr]::Zero) { throw "Notepad not found for $TitleNeedle" }
  Start-Sleep -Milliseconds 500
  [WerAnno]::SetForegroundWindow($hwnd) | Out-Null
  # Ensure word wrap ON for identity excerpt readability; dismiss any find UI
  [System.Windows.Forms.SendKeys]::SendWait('{ESC}')
  Start-Sleep -Milliseconds 150
  [System.Windows.Forms.SendKeys]::SendWait('^{HOME}')
  Start-Sleep -Milliseconds 200
  [WerAnno]::Save($hwnd, $OutPng, 1100, 900)
  [WerAnno]::SendMessage($hwnd, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
}

function Annotate-Explorer([string]$SrcPath, [string]$OutPath, [string]$Side, [string]$Needle, [string]$Label) {
  $src = [System.Drawing.Bitmap]::FromFile($SrcPath)
  try {
    # Crop: drop left nav (~22%) and bottom status; keep tab/address/content/details
    $x0 = [int]($src.Width * 0.18)
    $y0 = [int]($src.Height * 0.02)
    $cw = [int]($src.Width * 0.80)
    $ch = [int]($src.Height * 0.62)
    $crop = [WerAnno]::Crop($src, $x0, $y0, $cw, $ch)
    $g = [System.Drawing.Graphics]::FromImage($crop)
    $g.SmoothingMode = 'AntiAlias'
    $color = if ($Side -eq 'BEFORE') { [System.Drawing.Color]::FromArgb(220, 200, 40, 30) } else { [System.Drawing.Color]::FromArgb(220, 20, 130, 90) }

    # Address bar band (approx Win11)
    $addrY = [int]($crop.Height * 0.11)
    $addrH = [int]($crop.Height * 0.055)
    $addr = New-Object System.Drawing.Rectangle ([int]($crop.Width * 0.02), $addrY, [int]($crop.Width * 0.72), $addrH)
    [WerAnno]::DrawBox($g, $addr, $color, "$Label  folder: $Needle")

    # Details pane folder title (right side)
    $det = New-Object System.Drawing.Rectangle ([int]($crop.Width * 0.62), [int]($crop.Height * 0.28), [int]($crop.Width * 0.36), [int]($crop.Height * 0.12))
    [WerAnno]::DrawBox($g, $det, $color, "$Label  details pane")

    # Tab title strip
    $tab = New-Object System.Drawing.Rectangle ([int]($crop.Width * 0.01), [int]($crop.Height * 0.01), [int]($crop.Width * 0.45), [int]($crop.Height * 0.06))
    [WerAnno]::DrawBox($g, $tab, $color, $null)

    $crop.Save($OutPath, [System.Drawing.Imaging.ImageFormat]::Png)
    Write-Host "ANNOTATED $OutPath"
    $g.Dispose(); $crop.Dispose()
  } finally { $src.Dispose() }
}

function Annotate-Notepad([string]$SrcPath, [string]$OutPath, [string]$Side, [string[]]$HighlightLines, [string]$LabelPrefix) {
  $src = [System.Drawing.Bitmap]::FromFile($SrcPath)
  try {
    # Crop away thick window chrome / multi-tab strip if any; keep text body
    $x0 = [int]($src.Width * 0.01)
    $y0 = [int]($src.Height * 0.14)   # below menu+tabs
    $cw = [int]($src.Width * 0.98)
    $ch = [int]($src.Height * 0.78)  # above status bar
    $crop = [WerAnno]::Crop($src, $x0, $y0, $cw, $ch)
    $g = [System.Drawing.Graphics]::FromImage($crop)
    $g.SmoothingMode = 'AntiAlias'
    $color = if ($Side -eq 'BEFORE') { [System.Drawing.Color]::FromArgb(220, 200, 40, 30) } else { [System.Drawing.Color]::FromArgb(220, 20, 130, 90) }

    # Approximate text metrics for Segoe UI in Win11 Notepad at ~100%
    $lineH = 22.0
    $contentTop = 8
    $contentLeft = 12
    $contentRight = $crop.Width - 20

    # Map highlight line texts to indices in the visible excerpt (header = 3 lines)
    $allLines = Get-Content -LiteralPath ($(if ($Side -eq 'BEFORE') { Join-Path $Here 'BEFORE_Report.wer.identity.txt' } else { Join-Path $Here 'AFTER_Report.wer.identity.txt' }))
    $idx = 0
    $n = 0
    foreach ($ln in $allLines) {
      $isHit = $false
      foreach ($h in $HighlightLines) {
        if ($ln -like "*$h*") { $isHit = $true; break }
      }
      # Also auto-hit brand tokens
      if ($Side -eq 'BEFORE' -and $ln -match '(?i)prusa|slic3r') { $isHit = $true }
      if ($Side -eq 'AFTER' -and $ln -match '(?i)slicer-engine|Slicer Engine|slicer_core') { $isHit = $true }

      if ($isHit -and $ln -notmatch '^#') {
        $y = $contentTop + [int]($idx * $lineH) - 1
        if ($y -ge 0 -and $y -lt $crop.Height - 10) {
          $rect = New-Object System.Drawing.Rectangle $contentLeft, $y, ($contentRight - $contentLeft), ([int]$lineH)
          $label = $null
          if ($n -eq 0) { $label = "$LabelPrefix" }
          [WerAnno]::DrawBox($g, $rect, $color, $label)
          $n++
        }
      }
      $idx++
    }

    # Legend strip at bottom of crop
    $font = New-Object System.Drawing.Font 'Segoe UI', 10
    $bgLegend = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(235, 30, 30, 34))
    $fgLegend = New-Object System.Drawing.SolidBrush $color
    try {
      $msg = if ($Side -eq 'BEFORE') {
        "BEFORE highlight: prusa / slic3r brand tokens in live WER identity fields"
      } else {
        "AFTER highlight: slicer-engine / Slicer Engine neutral tokens (prusa/slic3r absent)"
      }
      $g.FillRectangle($bgLegend, 0, ($crop.Height - 28), $crop.Width, 28)
      $g.DrawString($msg, $font, $fgLegend, 10, ($crop.Height - 22))
    } finally {
      $font.Dispose(); $bgLegend.Dispose(); $fgLegend.Dispose()
    }

    $crop.Save($OutPath, [System.Drawing.Imaging.ImageFormat]::Png)
    Write-Host "ANNOTATED $OutPath hits~$n"
    $g.Dispose(); $crop.Dispose()
  } finally { $src.Dispose() }
}

function Scale-ToWidth([System.Drawing.Image]$img, [int]$targetW) {
  $h = [int]([double]$img.Height * $targetW / $img.Width)
  $bmp = New-Object System.Drawing.Bitmap $targetW, $h
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.InterpolationMode = 'HighQualityBicubic'
  $g.DrawImage($img, 0, 0, $targetW, $h)
  $g.Dispose()
  return $bmp
}

function Compose-CleanCompare {
  $bExp = [System.Drawing.Image]::FromFile((Join-Path $OutDir '17_OS_WER_ReportArchive_prusa-slicer-console_annotated.png'))
  $aExp = [System.Drawing.Image]::FromFile((Join-Path $OutDir '16_OS_WER_ReportArchive_slicer-engine_annotated.png'))
  $bNp  = [System.Drawing.Image]::FromFile((Join-Path $OutDir '22_OS_WER_Report_wer_prusa-slicer-console_notepad_annotated.png'))
  $aNp  = [System.Drawing.Image]::FromFile((Join-Path $OutDir '18_OS_WER_Report_wer_slicer-engine_notepad_annotated.png'))
  try {
    $panelW = 920
    $bExpS = Scale-ToWidth $bExp $panelW
    $aExpS = Scale-ToWidth $aExp $panelW
    $bNpS  = Scale-ToWidth $bNp  $panelW
    $aNpS  = Scale-ToWidth $aNp  $panelW

    $pad = 28; $gap = 24; $colLabelH = 34; $rowGap = 22; $headerH = 72; $footerH = 30
    $row1H = [Math]::Max($bExpS.Height, $aExpS.Height)
    $row2H = [Math]::Max($bNpS.Height, $aNpS.Height)
    $W = $pad * 2 + $panelW * 2 + $gap
    $H = $pad + $headerH + $colLabelH + $row1H + $rowGap + $colLabelH + $row2H + $footerH + $pad

    $bmp = New-Object System.Drawing.Bitmap $W, $H
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.Clear([System.Drawing.Color]::FromArgb(255, 248, 247, 244))
    $g.TextRenderingHint = 'ClearTypeGridFit'

    $titleFont = New-Object System.Drawing.Font 'Segoe UI Semibold', 18
    $subFont = New-Object System.Drawing.Font 'Segoe UI', 10
    $labelFont = New-Object System.Drawing.Font 'Segoe UI Semibold', 11
    $footFont = New-Object System.Drawing.Font 'Segoe UI', 8.5
    $ink = [System.Drawing.Brushes]::Black
    $beforeBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 180, 45, 35))
    $afterBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 15, 120, 85))
    $muted = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 95, 95, 100))

    $g.DrawString('WER Surface - Before vs After (clean crop + annotations)', $titleFont, $ink, $pad, $pad)
    $g.DrawString('Red boxes = prusa/slic3r brand tokens   |   Green boxes = slicer-engine neutral tokens   |   real OS UI crops', $subFont, $muted, $pad, ($pad + 36))

    # Column headers on SEPARATE sides (no overlap)
    $yCol = $pad + $headerH
    $g.FillRectangle($beforeBrush, $pad, ($yCol + 6), 14, 14)
    $g.DrawString('BEFORE', $labelFont, $beforeBrush, ($pad + 22), $yCol)
    $g.FillRectangle($afterBrush, ($pad + $panelW + $gap), ($yCol + 6), 14, 14)
    $g.DrawString('AFTER', $labelFont, $afterBrush, ($pad + $panelW + $gap + 22), $yCol)

    $y1 = $yCol + $colLabelH
    $g.DrawString('Explorer / AppCrash_* folder name', $subFont, $muted, $pad, ($y1 - 2))
    $g.DrawString('Explorer / AppCrash_* folder name', $subFont, $muted, ($pad + $panelW + $gap), ($y1 - 2))
    # small spacer then images
    $y1b = $y1 + 18
    $g.DrawImage($bExpS, $pad, $y1b)
    $g.DrawImage($aExpS, ($pad + $panelW + $gap), $y1b)

    $y2 = $y1b + $row1H + $rowGap
    $g.DrawString('Report.wer identity fields (Notepad)', $subFont, $muted, $pad, $y2)
    $g.DrawString('Report.wer identity fields (Notepad)', $subFont, $muted, ($pad + $panelW + $gap), $y2)
    $y2b = $y2 + 18
    $g.DrawImage($bNpS, $pad, $y2b)
    $g.DrawImage($aNpS, ($pad + $panelW + $gap), $y2b)

    $g.DrawString('Live WER 2026-07-20 / annotated crops / backend-slicer-engine-deidentification', $footFont, $muted, $pad, ($H - $pad - 16))

    $out = Join-Path $OutDir 'COMPARE_04_WER_surface_before_vs_after.png'
    $bmp.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)
    Write-Host "COMPOSED $out $($bmp.Width)x$($bmp.Height)"

    # Notepad-only compare
    $out2 = Join-Path $OutDir 'COMPARE_04b_WER_Report_wer_notepad_before_vs_after.png'
    $W2 = $pad * 2 + $panelW * 2 + $gap
    $H2 = $pad + 80 + $colLabelH + $bNpS.Height + 24
    $bmp2 = New-Object System.Drawing.Bitmap $W2, $H2
    $g2 = [System.Drawing.Graphics]::FromImage($bmp2)
    $g2.Clear([System.Drawing.Color]::FromArgb(255, 248, 247, 244))
    $g2.DrawString('Report.wer identity - Before vs After (annotated)', $titleFont, $ink, $pad, $pad)
    $g2.DrawString('prusa/slic3r tokens boxed in red (BEFORE) | slicer-engine tokens boxed in green (AFTER)', $subFont, $muted, $pad, ($pad + 34))
    $g2.FillRectangle($beforeBrush, $pad, ($pad + 62), 14, 14)
    $g2.DrawString('BEFORE', $labelFont, $beforeBrush, ($pad + 22), ($pad + 56))
    $g2.FillRectangle($afterBrush, ($pad + $panelW + $gap), ($pad + 62), 14, 14)
    $g2.DrawString('AFTER', $labelFont, $afterBrush, ($pad + $panelW + $gap + 22), ($pad + 56))
    $g2.DrawImage($bNpS, $pad, ($pad + 80 + $colLabelH - 10))
    $g2.DrawImage($aNpS, ($pad + $panelW + $gap), ($pad + 80 + $colLabelH - 10))
    $bmp2.Save($out2, [System.Drawing.Imaging.ImageFormat]::Png)
    Write-Host "COMPOSED $out2"
    $g2.Dispose(); $bmp2.Dispose()
    $g.Dispose(); $bmp.Dispose()
    $bExpS.Dispose(); $aExpS.Dispose(); $bNpS.Dispose(); $aNpS.Dispose()
  } finally {
    $bExp.Dispose(); $aExp.Dispose(); $bNp.Dispose(); $aNp.Dispose()
  }
}

# ---- main ----
$beforeWer = Join-Path $Here 'BEFORE_Report.wer'
$afterWer  = Join-Path $Here 'AFTER_Report.wer'
if (-not (Test-Path $beforeWer)) { throw "Missing $beforeWer" }
if (-not (Test-Path $afterWer))  { throw "Missing $afterWer" }

$beforeId = Join-Path $Here 'BEFORE_Report.wer.identity.txt'
$afterId  = Join-Path $Here 'AFTER_Report.wer.identity.txt'
New-IdentityExcerpt $beforeWer $beforeId 'BEFORE' | Out-Null
New-IdentityExcerpt $afterWer  $afterId  'AFTER'  | Out-Null

# Clean notepad captures (single window, no find overlay, no leftover tabs)
$npBeforeRaw = Join-Path $OutDir '22_OS_WER_Report_wer_prusa-slicer-console_notepad.png'
$npAfterRaw  = Join-Path $OutDir '18_OS_WER_Report_wer_slicer-engine_notepad.png'
Capture-CleanNotepad $beforeId 'BEFORE_Report.wer.identity' $npBeforeRaw
Capture-CleanNotepad $afterId  'AFTER_Report.wer.identity'  $npAfterRaw

# Annotate explorer crops (reuse existing live explorer shots)
Annotate-Explorer (Join-Path $OutDir '17_OS_WER_ReportArchive_prusa-slicer-console.png') `
  (Join-Path $OutDir '17_OS_WER_ReportArchive_prusa-slicer-console_annotated.png') `
  'BEFORE' 'prusa-slicer-con' 'BEFORE'

Annotate-Explorer (Join-Path $OutDir '16_OS_WER_ReportArchive_slicer-engine.png') `
  (Join-Path $OutDir '16_OS_WER_ReportArchive_slicer-engine_annotated.png') `
  'AFTER' 'slicer-engine' 'AFTER'

Annotate-Notepad $npBeforeRaw `
  (Join-Path $OutDir '22_OS_WER_Report_wer_prusa-slicer-console_notepad_annotated.png') `
  'BEFORE' @('prusa-slicer-console.exe','prusa-slicer.exe','PrusaSlicer') 'BEFORE prusa/slic3r'

Annotate-Notepad $npAfterRaw `
  (Join-Path $OutDir '18_OS_WER_Report_wer_slicer-engine_notepad_annotated.png') `
  'AFTER' @('slicer-engine.exe','Slicer Engine','slicer_core.dll') 'AFTER slicer-engine'

Compose-CleanCompare
Write-Host 'DONE'

# Clean WER evidence: render identity fields (verbatim from live Report.wer) + recapture Explorer via CopyFromScreen.
# Fixes Win11 Notepad PrintWindow/Mica ghosting; adds prusa/slic3r vs slicer-engine annotation boxes.
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
using System.Drawing.Text;
using System.Collections.Generic;
using System.Text.RegularExpressions;

public static class WerClean {
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
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

  public static void SaveScreen(IntPtr hwnd, string path, int forceW, int forceH) {
    SetProcessDPIAware();
    ShowWindow(hwnd, 9);
    if (forceW > 0 && forceH > 0) MoveWindow(hwnd, 60, 60, forceW, forceH, true);
    SetForegroundWindow(hwnd);
    Thread.Sleep(500);
    RECT r; GetWindowRect(hwnd, out r);
    int w = Math.Max(1, r.Right - r.Left);
    int h = Math.Max(1, r.Bottom - r.Top);
    using (var bmp = new Bitmap(w, h, PixelFormat.Format32bppArgb))
    using (var g = Graphics.FromImage(bmp)) {
      // CopyFromScreen avoids Win11 Mica/PrintWindow ghost layers
      g.CopyFromScreen(r.Left, r.Top, 0, 0, new Size(w, h));
      bmp.Save(path, ImageFormat.Png);
      Console.WriteLine("SAVED " + path + " " + w + "x" + h);
    }
  }

  public static Bitmap Crop(Bitmap src, int x, int y, int w, int h) {
    x = Math.Max(0, Math.Min(x, src.Width - 1));
    y = Math.Max(0, Math.Min(y, src.Height - 1));
    w = Math.Max(1, Math.Min(w, src.Width - x));
    h = Math.Max(1, Math.Min(h, src.Height - y));
    return src.Clone(new Rectangle(x, y, w, h), src.PixelFormat);
  }

  public static void DrawLabel(Graphics g, float x, float y, string text, Color bg) {
    using (var font = new Font("Segoe UI Semibold", 11f, FontStyle.Bold))
    using (var brush = new SolidBrush(bg))
    using (var fg = new SolidBrush(Color.White)) {
      var sz = g.MeasureString(text, font);
      g.FillRectangle(brush, x, y, sz.Width + 12, sz.Height + 4);
      g.DrawString(text, font, fg, x + 6, y + 1);
    }
  }

  public static void AnnotateExplorer(string srcPath, string outPath, bool before, string needle) {
    using (var src = (Bitmap)Image.FromFile(srcPath)) {
      // Tight crop: address bar + file list + details (drop left nav)
      int x0 = (int)(src.Width * 0.20);
      int y0 = (int)(src.Height * 0.04);
      int cw = (int)(src.Width * 0.78);
      int ch = (int)(src.Height * 0.58);
      using (var crop = Crop(src, x0, y0, cw, ch))
      using (var g = Graphics.FromImage(crop)) {
        g.SmoothingMode = SmoothingMode.AntiAlias;
        g.TextRenderingHint = TextRenderingHint.ClearTypeGridFit;
        Color c = before ? Color.FromArgb(210, 190, 45, 35) : Color.FromArgb(210, 15, 125, 90);
        string side = before ? "BEFORE" : "AFTER";

        // Address bar highlight
        var addr = new Rectangle((int)(crop.Width * 0.01), (int)(crop.Height * 0.10),
                                 (int)(crop.Width * 0.70), (int)(crop.Height * 0.07));
        using (var pen = new Pen(c, 3f)) g.DrawRectangle(pen, addr);
        DrawLabel(g, addr.X, Math.Max(2, addr.Y - 26), side + " folder: " + needle, c);

        // Details pane title area (right)
        var det = new Rectangle((int)(crop.Width * 0.58), (int)(crop.Height * 0.30),
                                (int)(crop.Width * 0.40), (int)(crop.Height * 0.16));
        using (var pen = new Pen(c, 3f)) g.DrawRectangle(pen, det);
        DrawLabel(g, det.X, det.Y - 26, side + " details: " + needle, c);

        // Search box (often repeats AppCrash_*)
        var search = new Rectangle((int)(crop.Width * 0.72), (int)(crop.Height * 0.10),
                                   (int)(crop.Width * 0.26), (int)(crop.Height * 0.07));
        using (var pen = new Pen(c, 2f)) g.DrawRectangle(pen, search);

        crop.Save(outPath, ImageFormat.Png);
        Console.WriteLine("ANNOTATED " + outPath);
      }
    }
  }

  // Render clean identity document (no OS ghosting) with token boxes.
  public static void RenderIdentity(string[] lines, string outPath, bool before, string title) {
    Color accent = before ? Color.FromArgb(255, 190, 45, 35) : Color.FromArgb(255, 15, 125, 90);
    Color accentFill = before ? Color.FromArgb(40, 255, 100, 80) : Color.FromArgb(40, 80, 220, 160);
    Regex brand = before
      ? new Regex(@"prusa|slic3r|PrusaSlicer", RegexOptions.IgnoreCase)
      : new Regex(@"slicer-engine|Slicer Engine|slicer_core", RegexOptions.IgnoreCase);

    int pad = 28;
    int lineH = 28;
    int width = 1100;
    int height = pad * 2 + 70 + lines.Length * lineH + 40;
    using (var bmp = new Bitmap(width, height, PixelFormat.Format32bppArgb))
    using (var g = Graphics.FromImage(bmp))
    using (var titleFont = new Font("Segoe UI Semibold", 14f, FontStyle.Bold))
    using (var mono = new Font("Consolas", 12f, FontStyle.Regular))
    using (var small = new Font("Segoe UI", 9.5f)) {
      g.Clear(Color.FromArgb(255, 252, 251, 248));
      g.TextRenderingHint = TextRenderingHint.ClearTypeGridFit;
      g.SmoothingMode = SmoothingMode.AntiAlias;

      // Title bar strip
      using (var bar = new SolidBrush(accent))
        g.FillRectangle(bar, 0, 0, width, 44);
      g.DrawString(title, titleFont, Brushes.White, pad, 10);
      using (var muted = new SolidBrush(Color.FromArgb(255, 100, 100, 105)))
        g.DrawString("verbatim fields from live Report.wer  |  clean render (no Notepad ghosting)", small, muted, pad, 52);

      int y = pad + 70;
      int hits = 0;
      foreach (var raw in lines) {
        string line = raw ?? "";
        bool hit = brand.IsMatch(line);
        if (hit) {
          hits++;
          using (var fill = new SolidBrush(accentFill))
            g.FillRectangle(fill, pad - 6, y - 2, width - pad * 2 + 12, lineH - 2);
          using (var pen = new Pen(accent, 2f))
            g.DrawRectangle(pen, pad - 6, y - 2, width - pad * 2 + 12, lineH - 2);
        }
        g.DrawString(line, mono, Brushes.Black, pad, y);
        y += lineH;
      }

      using (var footBg = new SolidBrush(Color.FromArgb(245, 35, 35, 38)))
        g.FillRectangle(footBg, 0, height - 34, width, 34);
      string foot = before
        ? ("BEFORE  red boxes mark prusa/slic3r tokens  |  hits=" + hits)
        : ("AFTER  green boxes mark slicer-engine tokens (prusa/slic3r absent)  |  hits=" + hits);
      g.DrawString(foot, small, new SolidBrush(accent), pad, height - 24);

      bmp.Save(outPath, ImageFormat.Png);
      Console.WriteLine("RENDERED " + outPath + " hits=" + hits);
    }
  }
}
"@

function Get-IdentityLines([string]$WerPath) {
  $raw = Get-Content -LiteralPath $WerPath -Encoding Unicode
  $keep = New-Object System.Collections.Generic.List[string]
  foreach ($line in $raw) {
    if ($line -match '^(Version|EventType|NsAppName|OriginalFilename|TargetAppId|TargetAppVer|AppSessionGuid|IsFatal|Sig\[0\]|Sig\[1\]|Sig\[3\]|UI\[2\]|LoadedModule\[0\]|LoadedModule\[8\]|FriendlyEventName|AppName|AppPath)=') {
      if ($line.Length -lt 420) { [void]$keep.Add($line) }
    }
  }
  return ,@($keep.ToArray())
}

function Recapture-Explorer([string]$FolderPath, [string]$TitleNeedle, [string]$OutPng) {
  # Close previous explorer windows with similar titles is hard; open fresh and capture.
  Start-Process explorer.exe -ArgumentList $FolderPath
  $hwnd = [IntPtr]::Zero
  for ($i = 0; $i -lt 50; $i++) {
    Start-Sleep -Milliseconds 220
    $hwnd = [WerClean]::FindTitleContains($TitleNeedle)
    if ($hwnd -ne [IntPtr]::Zero) { break }
  }
  if ($hwnd -eq [IntPtr]::Zero) { throw "Explorer not found for $TitleNeedle" }
  Start-Sleep -Milliseconds 700
  [WerClean]::SaveScreen($hwnd, $OutPng, 1280, 820)
  [WerClean]::SendMessage($hwnd, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
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

function Compose-Final {
  $bExp = [System.Drawing.Image]::FromFile((Join-Path $OutDir '17_OS_WER_ReportArchive_prusa-slicer-console_annotated.png'))
  $aExp = [System.Drawing.Image]::FromFile((Join-Path $OutDir '16_OS_WER_ReportArchive_slicer-engine_annotated.png'))
  $bNp  = [System.Drawing.Image]::FromFile((Join-Path $OutDir '22_OS_WER_Report_wer_prusa-slicer-console_notepad_annotated.png'))
  $aNp  = [System.Drawing.Image]::FromFile((Join-Path $OutDir '18_OS_WER_Report_wer_slicer-engine_notepad_annotated.png'))
  try {
    $panelW = 900
    $bExpS = Scale-ToWidth $bExp $panelW
    $aExpS = Scale-ToWidth $aExp $panelW
    $bNpS  = Scale-ToWidth $bNp  $panelW
    $aNpS  = Scale-ToWidth $aNp  $panelW

    $pad = 28; $gap = 24; $headerH = 78; $sectionLabelH = 26; $footerH = 28
    $row1H = [Math]::Max($bExpS.Height, $aExpS.Height)
    $row2H = [Math]::Max($bNpS.Height, $aNpS.Height)
    $W = $pad * 2 + $panelW * 2 + $gap
    $H = $pad + $headerH + $sectionLabelH + $row1H + 28 + $sectionLabelH + $row2H + $footerH + $pad

    $bmp = New-Object System.Drawing.Bitmap $W, $H
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.Clear([System.Drawing.Color]::FromArgb(255, 248, 247, 244))
    $g.TextRenderingHint = 'ClearTypeGridFit'

    $titleFont = New-Object System.Drawing.Font 'Segoe UI Semibold', 18
    $subFont = New-Object System.Drawing.Font 'Segoe UI', 10
    $labelFont = New-Object System.Drawing.Font 'Segoe UI Semibold', 12
    $footFont = New-Object System.Drawing.Font 'Segoe UI', 8.5
    $beforeBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 180, 45, 35))
    $afterBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 15, 120, 85))
    $muted = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 95, 95, 100))

    $g.DrawString('WER Surface - Before vs After (clean crops + annotations)', $titleFont, [System.Drawing.Brushes]::Black, $pad, $pad)
    $g.DrawString('Red = prusa/slic3r brand tokens    Green = slicer-engine neutral tokens    Explorer = live OS    Report.wer fields = verbatim clean render', $subFont, $muted, $pad, ($pad + 38))

    # Non-overlapping column headers
    $y = $pad + $headerH
    $g.FillRectangle($beforeBrush, $pad, ($y + 4), 16, 16)
    $g.DrawString('BEFORE', $labelFont, $beforeBrush, ($pad + 24), $y)
    $g.FillRectangle($afterBrush, ($pad + $panelW + $gap), ($y + 4), 16, 16)
    $g.DrawString('AFTER', $labelFont, $afterBrush, ($pad + $panelW + $gap + 24), $y)

    $y1 = $y + $sectionLabelH
    $g.DrawString('1) Explorer AppCrash_* folder', $subFont, $muted, $pad, $y1)
    $g.DrawString('1) Explorer AppCrash_* folder', $subFont, $muted, ($pad + $panelW + $gap), $y1)
    $y1b = $y1 + 20
    $g.DrawImage($bExpS, $pad, $y1b)
    $g.DrawImage($aExpS, ($pad + $panelW + $gap), $y1b)

    $y2 = $y1b + $row1H + 16
    $g.DrawString('2) Report.wer identity fields (annotated)', $subFont, $muted, $pad, $y2)
    $g.DrawString('2) Report.wer identity fields (annotated)', $subFont, $muted, ($pad + $panelW + $gap), $y2)
    $y2b = $y2 + 20
    $g.DrawImage($bNpS, $pad, $y2b)
    $g.DrawImage($aNpS, ($pad + $panelW + $gap), $y2b)

    $g.DrawString('Live WER 2026-07-20 / backend-slicer-engine-deidentification / clean annotated evidence', $footFont, $muted, $pad, ($H - $pad - 14))

    $out = Join-Path $OutDir 'COMPARE_04_WER_surface_before_vs_after.png'
    $bmp.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)
    Write-Host "COMPOSED $out $($bmp.Width)x$($bmp.Height)"

    $out2 = Join-Path $OutDir 'COMPARE_04b_WER_Report_wer_notepad_before_vs_after.png'
    $W2 = $pad * 2 + $panelW * 2 + $gap
    $H2 = $pad + 90 + [Math]::Max($bNpS.Height, $aNpS.Height) + 24
    $bmp2 = New-Object System.Drawing.Bitmap $W2, $H2
    $g2 = [System.Drawing.Graphics]::FromImage($bmp2)
    $g2.Clear([System.Drawing.Color]::FromArgb(255, 248, 247, 244))
    $g2.DrawString('Report.wer identity - Before vs After (annotated)', $titleFont, [System.Drawing.Brushes]::Black, $pad, $pad)
    $g2.DrawString('prusa/slic3r boxed in red (BEFORE)  |  slicer-engine boxed in green (AFTER)', $subFont, $muted, $pad, ($pad + 36))
    $g2.FillRectangle($beforeBrush, $pad, ($pad + 62), 14, 14)
    $g2.DrawString('BEFORE', $labelFont, $beforeBrush, ($pad + 22), ($pad + 56))
    $g2.FillRectangle($afterBrush, ($pad + $panelW + $gap), ($pad + 62), 14, 14)
    $g2.DrawString('AFTER', $labelFont, $afterBrush, ($pad + $panelW + $gap + 22), ($pad + 56))
    $g2.DrawImage($bNpS, $pad, ($pad + 90))
    $g2.DrawImage($aNpS, ($pad + $panelW + $gap), ($pad + 90))
    $bmp2.Save($out2, [System.Drawing.Imaging.ImageFormat]::Png)
    Write-Host "COMPOSED $out2"

    $g2.Dispose(); $bmp2.Dispose(); $g.Dispose(); $bmp.Dispose()
    $bExpS.Dispose(); $aExpS.Dispose(); $bNpS.Dispose(); $aNpS.Dispose()
  } finally {
    $bExp.Dispose(); $aExp.Dispose(); $bNp.Dispose(); $aNp.Dispose()
  }
}

# ---- main ----
$beforeWer = Join-Path $Here 'BEFORE_Report.wer'
$afterWer  = Join-Path $Here 'AFTER_Report.wer'
if (-not (Test-Path $beforeWer)) { throw "Missing BEFORE_Report.wer" }
if (-not (Test-Path $afterWer))  { throw "Missing AFTER_Report.wer" }

$beforeLines = Get-IdentityLines $beforeWer
$afterLines  = Get-IdentityLines $afterWer

# Clean annotated identity renders (replace ghosted notepad shots used by COMPARE)
[WerClean]::RenderIdentity(
  $beforeLines,
  (Join-Path $OutDir '22_OS_WER_Report_wer_prusa-slicer-console_notepad_annotated.png'),
  $true,
  'BEFORE  Report.wer identity  |  prusa / slic3r')
[WerClean]::RenderIdentity(
  $afterLines,
  (Join-Path $OutDir '18_OS_WER_Report_wer_slicer-engine_notepad_annotated.png'),
  $false,
  'AFTER  Report.wer identity  |  slicer-engine')

# Also save clean non-annotated copies for individual section cards
Copy-Item (Join-Path $OutDir '22_OS_WER_Report_wer_prusa-slicer-console_notepad_annotated.png') `
          (Join-Path $OutDir '22_OS_WER_Report_wer_prusa-slicer-console_notepad.png') -Force
Copy-Item (Join-Path $OutDir '18_OS_WER_Report_wer_slicer-engine_notepad_annotated.png') `
          (Join-Path $OutDir '18_OS_WER_Report_wer_slicer-engine_notepad.png') -Force

# Recapture Explorer with CopyFromScreen (no PrintWindow ghosting), then annotate+crop
$beforeFolder = Get-ChildItem 'C:\ProgramData\Microsoft\Windows\WER\ReportArchive' -Directory |
  Where-Object { $_.Name -like 'AppCrash_prusa-slicer*' } |
  Sort-Object LastWriteTime -Descending | Select-Object -First 1
$afterFolder = Get-ChildItem 'C:\ProgramData\Microsoft\Windows\WER\ReportArchive' -Directory |
  Where-Object { $_.Name -like 'AppCrash_slicer-engine*' } |
  Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $beforeFolder) { throw 'No AppCrash_prusa-slicer* folder' }
if (-not $afterFolder)  { throw 'No AppCrash_slicer-engine* folder' }

$rawBeforeExp = Join-Path $OutDir '_tmp_before_explorer.png'
$rawAfterExp  = Join-Path $OutDir '_tmp_after_explorer.png'
Recapture-Explorer $beforeFolder.FullName ($beforeFolder.Name.Substring(0, [Math]::Min(24, $beforeFolder.Name.Length))) $rawBeforeExp
Recapture-Explorer $afterFolder.FullName  ($afterFolder.Name.Substring(0, [Math]::Min(24, $afterFolder.Name.Length)))  $rawAfterExp

# Keep full raw as the main explorer shots too
Copy-Item $rawBeforeExp (Join-Path $OutDir '17_OS_WER_ReportArchive_prusa-slicer-console.png') -Force
Copy-Item $rawAfterExp  (Join-Path $OutDir '16_OS_WER_ReportArchive_slicer-engine.png') -Force

[WerClean]::AnnotateExplorer(
  $rawBeforeExp,
  (Join-Path $OutDir '17_OS_WER_ReportArchive_prusa-slicer-console_annotated.png'),
  $true,
  'prusa-slicer-con')
[WerClean]::AnnotateExplorer(
  $rawAfterExp,
  (Join-Path $OutDir '16_OS_WER_ReportArchive_slicer-engine_annotated.png'),
  $false,
  'slicer-engine')

Compose-Final
Remove-Item $rawBeforeExp, $rawAfterExp -Force -ErrorAction SilentlyContinue
Write-Host 'DONE'

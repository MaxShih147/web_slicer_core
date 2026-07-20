# Fix WER evidence: full folder paths visible + no title/subtitle overlap.
$ErrorActionPreference = 'Stop'
$Here = 'D:\Repos\Phrozen\Bundle\web_slicer_core\openspec\changes\backend-slicer-engine-deidentification\evidence\windows\before-after-compare-20260720'
$OutDir = Join-Path $Here 'shots'
Add-Type -AssemblyName System.Drawing

$drawing = [Reflection.Assembly]::LoadWithPartialName('System.Drawing').Location
Add-Type -ReferencedAssemblies $drawing -TypeDefinition @"
using System;
using System.Text;
using System.Threading;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Drawing;
using System.Drawing.Imaging;
using System.Drawing.Drawing2D;
using System.Drawing.Text;
using System.Text.RegularExpressions;
using System.Collections.Generic;

public static class WerFix {
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
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }

  public static IntPtr FindExplorerTitle(string needle) {
    IntPtr found = IntPtr.Zero;
    EnumWindows((h, l) => {
      if (!IsWindowVisible(h)) return true;
      var sb = new StringBuilder(1024);
      GetWindowText(h, sb, sb.Capacity);
      if (sb.ToString().IndexOf(needle, StringComparison.OrdinalIgnoreCase) < 0) return true;
      uint pid; GetWindowThreadProcessId(h, out pid);
      try {
        if (!string.Equals(Process.GetProcessById((int)pid).ProcessName, "explorer", StringComparison.OrdinalIgnoreCase))
          return true;
      } catch { return true; }
      found = h; return false;
    }, IntPtr.Zero);
    return found;
  }

  public static void SavePrint(IntPtr hwnd, string path, int w, int h) {
    SetProcessDPIAware();
    ShowWindow(hwnd, 9);
    MoveWindow(hwnd, 10, 10, w, h, true);
    SetForegroundWindow(hwnd);
    Thread.Sleep(900);
    RECT r; GetWindowRect(hwnd, out r);
    int bw = Math.Max(1, r.Right - r.Left);
    int bh = Math.Max(1, r.Bottom - r.Top);
    using (var bmp = new Bitmap(bw, bh, PixelFormat.Format32bppArgb))
    using (var g = Graphics.FromImage(bmp)) {
      IntPtr hdc = g.GetHdc();
      bool ok = PrintWindow(hwnd, hdc, 2);
      g.ReleaseHdc(hdc);
      if (!ok) throw new Exception("PrintWindow failed");
      bmp.Save(path, ImageFormat.Png);
      Console.WriteLine("SAVED " + path + " " + bw + "x" + bh);
    }
  }

  // Build explorer evidence card: screenshot crop + FULL path caption (never truncated by OS chrome).
  public static void BuildExplorerCard(string srcPath, string outPath, bool before, string fullPath, string shortNeedle) {
    Color accent = before ? Color.FromArgb(255, 180, 45, 35) : Color.FromArgb(255, 15, 120, 85);
    string side = before ? "BEFORE" : "AFTER";
    using (var src = (Bitmap)Image.FromFile(srcPath)) {
      // Crop: drop left nav, keep title+address+toolbar+file list top
      int x0 = (int)(src.Width * 0.14);
      int y0 = 0;
      int cw = (int)(src.Width * 0.86);
      int ch = (int)(src.Height * 0.55);
      var cropRect = new Rectangle(Math.Max(0,x0), y0, Math.Min(cw, src.Width - x0), Math.Min(ch, src.Height));
      using (var crop = src.Clone(cropRect, src.PixelFormat)) {
        int pathBlockH = 78;
        int pad = 16;
        int W = Math.Max(980, crop.Width + pad * 2);
        int H = pad + 36 + crop.Height + 12 + pathBlockH + pad;
        using (var bmp = new Bitmap(W, H, PixelFormat.Format32bppArgb))
        using (var g = Graphics.FromImage(bmp))
        using (var titleFont = new Font("Segoe UI Semibold", 13f, FontStyle.Bold))
        using (var pathFont = new Font("Consolas", 10.5f, FontStyle.Regular))
        using (var small = new Font("Segoe UI", 9f)) {
          g.Clear(Color.FromArgb(255, 252, 251, 248));
          g.TextRenderingHint = TextRenderingHint.ClearTypeGridFit;
          g.SmoothingMode = SmoothingMode.AntiAlias;

          // Side label ABOVE image (does not cover folder name)
          using (var bg = new SolidBrush(accent))
          using (var fg = new SolidBrush(Color.White)) {
            string lab = side + "  live Explorer  |  AppCrash_" + shortNeedle;
            var sz = g.MeasureString(lab, titleFont);
            g.FillRectangle(bg, pad, pad, sz.Width + 14, 28);
            g.DrawString(lab, titleFont, fg, pad + 7, pad + 4);
          }

          int imgY = pad + 36;
          int imgX = pad + Math.Max(0, (W - pad * 2 - crop.Width) / 2);
          g.DrawImage(crop, imgX, imgY, crop.Width, crop.Height);
          using (var pen = new Pen(Color.FromArgb(180, 180, 180), 1f))
            g.DrawRectangle(pen, imgX, imgY, crop.Width - 1, crop.Height - 1);

          // Thin boxes on title tab + address band (no opaque overlay on text)
          using (var pen = new Pen(accent, 2.5f)) {
            g.DrawRectangle(pen, imgX + 4, imgY + 4, Math.Min(700, crop.Width - 80), 32);
            g.DrawRectangle(pen, imgX + 4, imgY + 42, crop.Width - 8, 38);
          }

          // FULL path block under screenshot
          int py = imgY + crop.Height + 10;
          using (var bar = new SolidBrush(Color.FromArgb(245, 32, 32, 36)))
            g.FillRectangle(bar, pad, py, W - pad * 2, pathBlockH);
          g.DrawString("Full folder path (complete, not truncated by Explorer chrome):", small, new SolidBrush(Color.FromArgb(200, 200, 200)), pad + 10, py + 8);
          // Wrap path
          var lines = Wrap(fullPath, pathFont, g, W - pad * 2 - 24);
          float ly = py + 28;
          foreach (var line in lines) {
            bool hit = line.IndexOf(shortNeedle, StringComparison.OrdinalIgnoreCase) >= 0
                       || line.IndexOf("prusa", StringComparison.OrdinalIgnoreCase) >= 0
                       || line.IndexOf("slicer-engine", StringComparison.OrdinalIgnoreCase) >= 0;
            if (hit) {
              var m = g.MeasureString(line, pathFont);
              using (var fill = new SolidBrush(Color.FromArgb(55, accent)))
                g.FillRectangle(fill, pad + 8, ly - 1, m.Width + 6, m.Height + 2);
              using (var pen = new Pen(accent, 1.5f))
                g.DrawRectangle(pen, pad + 8, ly - 1, m.Width + 6, m.Height + 2);
            }
            g.DrawString(line, pathFont, Brushes.White, pad + 10, ly);
            ly += 18;
          }

          bmp.Save(outPath, ImageFormat.Png);
          Console.WriteLine("CARD " + outPath + " " + W + "x" + H);
        }
      }
    }
  }

  static List<string> Wrap(string text, Font font, Graphics g, float maxW) {
    var result = new List<string>();
    if (string.IsNullOrEmpty(text)) return result;
    // Prefer break at backslash
    var parts = text.Split('\\');
    string cur = parts[0];
    for (int i = 1; i < parts.Length; i++) {
      string trial = cur + "\\" + parts[i];
      if (g.MeasureString(trial, font).Width <= maxW) cur = trial;
      else { result.Add(cur + "\\"); cur = parts[i]; }
    }
    if (!string.IsNullOrEmpty(cur)) result.Add(cur);
    return result;
  }

  public static void RenderIdentity(string[] lines, string outPath, bool before, string title) {
    Color accent = before ? Color.FromArgb(255, 180, 45, 35) : Color.FromArgb(255, 15, 120, 85);
    Color accentFill = before ? Color.FromArgb(42, 255, 100, 80) : Color.FromArgb(42, 80, 220, 160);
    Regex brand = before
      ? new Regex(@"prusa|slic3r|PrusaSlicer", RegexOptions.IgnoreCase)
      : new Regex(@"slicer-engine|Slicer Engine|slicer_core", RegexOptions.IgnoreCase);

    int pad = 22;
    int lineH = 26;
    int width = 1180;
    // Pre-wrap long lines so paths are complete
    var wrapped = new List<string>();
    using (var tmp = new Bitmap(8, 8))
    using (var tg = Graphics.FromImage(tmp))
    using (var mono = new Font("Consolas", 11f)) {
      float maxW = width - pad * 2 - 8;
      foreach (var raw in lines) {
        string s = raw ?? "";
        if (tg.MeasureString(s, mono).Width <= maxW) wrapped.Add(s);
        else {
          // hard wrap by chars
          int start = 0;
          while (start < s.Length) {
            int take = Math.Min(96, s.Length - start);
            while (take < s.Length - start && tg.MeasureString(s.Substring(start, take + 1), mono).Width <= maxW) take++;
            // prefer break after \\ or !
            int slice = take;
            string chunk = s.Substring(start, slice);
            int br = Math.Max(chunk.LastIndexOf('\\'), chunk.LastIndexOf('!'));
            if (br > 40 && start + br + 1 < s.Length) slice = br + 1;
            wrapped.Add(s.Substring(start, slice));
            start += slice;
          }
        }
      }
    }

    int height = pad + 58 + wrapped.Count * lineH + 40;
    using (var bmp = new Bitmap(width, height, PixelFormat.Format32bppArgb))
    using (var g = Graphics.FromImage(bmp))
    using (var titleFont = new Font("Segoe UI Semibold", 13f, FontStyle.Bold))
    using (var mono = new Font("Consolas", 11f))
    using (var small = new Font("Segoe UI", 9f)) {
      g.Clear(Color.FromArgb(255, 252, 251, 248));
      g.TextRenderingHint = TextRenderingHint.ClearTypeGridFit;
      using (var bar = new SolidBrush(accent))
        g.FillRectangle(bar, 0, 0, width, 40);
      g.DrawString(title, titleFont, Brushes.White, pad, 9);
      using (var muted = new SolidBrush(Color.FromArgb(255, 110, 110, 115)))
        g.DrawString("verbatim from live Report.wer  |  long paths wrapped (complete)", small, muted, pad, 46);

      int y = pad + 58;
      int hits = 0;
      foreach (var line in wrapped) {
        bool hit = brand.IsMatch(line);
        if (hit) {
          hits++;
          using (var fill = new SolidBrush(accentFill))
            g.FillRectangle(fill, pad - 4, y - 2, width - pad * 2 + 8, lineH - 2);
          using (var pen = new Pen(accent, 2f))
            g.DrawRectangle(pen, pad - 4, y - 2, width - pad * 2 + 8, lineH - 2);
        }
        g.DrawString(line, mono, Brushes.Black, pad, y);
        y += lineH;
      }
      using (var footBg = new SolidBrush(Color.FromArgb(245, 32, 32, 36)))
        g.FillRectangle(footBg, 0, height - 32, width, 32);
      string foot = before
        ? ("BEFORE  red = prusa/slic3r  |  hits=" + hits)
        : ("AFTER  green = slicer-engine (prusa/slic3r absent)  |  hits=" + hits);
      g.DrawString(foot, small, new SolidBrush(accent), pad, height - 22);
      bmp.Save(outPath, ImageFormat.Png);
      Console.WriteLine("RENDER " + outPath + " hits=" + hits);
    }
  }
}
"@

function Get-IdentityLines([string]$WerPath) {
  $raw = Get-Content -LiteralPath $WerPath -Encoding Unicode
  $keep = New-Object System.Collections.Generic.List[string]
  foreach ($line in $raw) {
    if ($line -match '^(Version|EventType|NsAppName|OriginalFilename|TargetAppId|TargetAppVer|AppSessionGuid|IsFatal|Sig\[0\]|Sig\[1\]|Sig\[3\]|UI\[2\]|LoadedModule\[0\]|LoadedModule\[8\]|FriendlyEventName|AppName|AppPath)=') {
      [void]$keep.Add($line)
    }
  }
  return ,@($keep.ToArray())
}

function Capture-Explorer([string]$Folder, [string]$Needle, [string]$RawOut) {
  Start-Process -FilePath 'explorer.exe' -ArgumentList @('/separate,', "`"$Folder`"")
  $hwnd = [IntPtr]::Zero
  for ($i = 0; $i -lt 80; $i++) {
    Start-Sleep -Milliseconds 250
    $hwnd = [WerFix]::FindExplorerTitle($Needle)
    if ($hwnd -ne [IntPtr]::Zero) { break }
  }
  if ($hwnd -eq [IntPtr]::Zero) { throw "explorer not found for $Needle" }
  # Wide window so address bar shows more of the AppCrash_* name
  [WerFix]::SavePrint($hwnd, $RawOut, 1680, 920)
  [WerFix]::SendMessage($hwnd, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
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

function Compose-Pair([string]$LeftPath, [string]$RightPath, [string]$OutPath, [string]$Title, [string]$Subtitle) {
  $left = [System.Drawing.Image]::FromFile($LeftPath)
  $right = [System.Drawing.Image]::FromFile($RightPath)
  try {
    $panelW = 900
    $lS = Scale-ToWidth $left $panelW
    $rS = Scale-ToWidth $right $panelW
    $pad = 28
    $gap = 24
    # CRITICAL: enough header room so title / subtitle / column labels never overlap
    $headerH = 110
    $footerH = 28
    $rowH = [Math]::Max($lS.Height, $rS.Height)
    $W = $pad * 2 + $panelW * 2 + $gap
    $H = $pad + $headerH + $rowH + $footerH + $pad

    $bmp = New-Object System.Drawing.Bitmap $W, $H
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.Clear([System.Drawing.Color]::FromArgb(255, 248, 247, 244))
    $g.TextRenderingHint = 'ClearTypeGridFit'

    $titleFont = New-Object System.Drawing.Font 'Segoe UI Semibold', 17
    $subFont = New-Object System.Drawing.Font 'Segoe UI', 10
    $labelFont = New-Object System.Drawing.Font 'Segoe UI Semibold', 12
    $footFont = New-Object System.Drawing.Font 'Segoe UI', 8.5
    $beforeBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 180, 45, 35))
    $afterBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 15, 120, 85))
    $muted = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 95, 95, 100))

    # Title then subtitle with clear gap
    $g.DrawString($Title, $titleFont, [System.Drawing.Brushes]::Black, $pad, $pad)
    $g.DrawString($Subtitle, $subFont, $muted, $pad, ($pad + 34))

    # Column labels on their own row (below subtitle)
    $yLab = $pad + 62
    $g.FillRectangle($beforeBrush, $pad, ($yLab + 4), 14, 14)
    $g.DrawString('BEFORE', $labelFont, $beforeBrush, ($pad + 22), $yLab)
    $g.FillRectangle($afterBrush, ($pad + $panelW + $gap), ($yLab + 4), 14, 14)
    $g.DrawString('AFTER', $labelFont, $afterBrush, ($pad + $panelW + $gap + 22), $yLab)

    $yImg = $pad + $headerH
    $g.DrawImage($lS, $pad, $yImg)
    $g.DrawImage($rS, ($pad + $panelW + $gap), $yImg)

    $g.DrawString('Live WER 2026-07-20 / backend-slicer-engine-deidentification / full paths + no overlapping headers', $footFont, $muted, $pad, ($H - $pad - 14))

    $bmp.Save($OutPath, [System.Drawing.Imaging.ImageFormat]::Png)
    Write-Host "COMPOSED $OutPath $($bmp.Width)x$($bmp.Height)"
    $g.Dispose(); $bmp.Dispose()
    $lS.Dispose(); $rS.Dispose()
  } finally {
    $left.Dispose(); $right.Dispose()
  }
}

# ---- main ----
$beforeWer = Join-Path $Here 'BEFORE_Report.wer'
$afterWer  = Join-Path $Here 'AFTER_Report.wer'
$beforeFolder = Get-ChildItem 'C:\ProgramData\Microsoft\Windows\WER\ReportArchive' -Directory |
  Where-Object { $_.Name -like 'AppCrash_prusa-slicer*' } |
  Sort-Object LastWriteTime -Descending | Select-Object -First 1
$afterFolder = Get-ChildItem 'C:\ProgramData\Microsoft\Windows\WER\ReportArchive' -Directory |
  Where-Object { $_.Name -like 'AppCrash_slicer-engine*' } |
  Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $beforeFolder -or -not $afterFolder) { throw 'WER folders missing' }

Write-Host "BEFORE path=$($beforeFolder.FullName)"
Write-Host "AFTER  path=$($afterFolder.FullName)"

# 1) Identity renders with wrapped complete paths
[WerFix]::RenderIdentity(
  (Get-IdentityLines $beforeWer),
  (Join-Path $OutDir '22_OS_WER_Report_wer_prusa-slicer-console_notepad_annotated.png'),
  $true,
  'BEFORE  Report.wer identity  |  prusa / slic3r')
[WerFix]::RenderIdentity(
  (Get-IdentityLines $afterWer),
  (Join-Path $OutDir '18_OS_WER_Report_wer_slicer-engine_notepad_annotated.png'),
  $false,
  'AFTER  Report.wer identity  |  slicer-engine')
Copy-Item (Join-Path $OutDir '22_OS_WER_Report_wer_prusa-slicer-console_notepad_annotated.png') (Join-Path $OutDir '22_OS_WER_Report_wer_prusa-slicer-console_notepad.png') -Force
Copy-Item (Join-Path $OutDir '18_OS_WER_Report_wer_slicer-engine_notepad_annotated.png') (Join-Path $OutDir '18_OS_WER_Report_wer_slicer-engine_notepad.png') -Force

# 2) Explorer capture + card with FULL path caption
$rawB = Join-Path $OutDir '_tmp_before_explorer.png'
$rawA = Join-Path $OutDir '_tmp_after_explorer.png'
Capture-Explorer $beforeFolder.FullName 'prusa-slicer' $rawB
Capture-Explorer $afterFolder.FullName  'slicer-engine' $rawA
Copy-Item $rawB (Join-Path $OutDir '17_OS_WER_ReportArchive_prusa-slicer-console.png') -Force
Copy-Item $rawA (Join-Path $OutDir '16_OS_WER_ReportArchive_slicer-engine.png') -Force

[WerFix]::BuildExplorerCard(
  $rawB,
  (Join-Path $OutDir '17_OS_WER_ReportArchive_prusa-slicer-console_annotated.png'),
  $true,
  $beforeFolder.FullName,
  'prusa-slicer-con')
[WerFix]::BuildExplorerCard(
  $rawA,
  (Join-Path $OutDir '16_OS_WER_ReportArchive_slicer-engine_annotated.png'),
  $false,
  $afterFolder.FullName,
  'slicer-engine')

# 3) Composites with non-overlapping headers
Compose-Pair `
  (Join-Path $OutDir '17_OS_WER_ReportArchive_prusa-slicer-console_annotated.png') `
  (Join-Path $OutDir '16_OS_WER_ReportArchive_slicer-engine_annotated.png') `
  (Join-Path $OutDir 'COMPARE_04_WER_surface_before_vs_after.png') `
  'WER Surface - Before vs After' `
  'Red = prusa/slic3r brand tokens     Green = slicer-engine neutral tokens     Full paths shown under each Explorer crop'

# Dual-row COMPARE_04: explorer + identity
$bExp = [System.Drawing.Image]::FromFile((Join-Path $OutDir '17_OS_WER_ReportArchive_prusa-slicer-console_annotated.png'))
$aExp = [System.Drawing.Image]::FromFile((Join-Path $OutDir '16_OS_WER_ReportArchive_slicer-engine_annotated.png'))
$bNp  = [System.Drawing.Image]::FromFile((Join-Path $OutDir '22_OS_WER_Report_wer_prusa-slicer-console_notepad_annotated.png'))
$aNp  = [System.Drawing.Image]::FromFile((Join-Path $OutDir '18_OS_WER_Report_wer_slicer-engine_notepad_annotated.png'))
try {
  $panelW = 900
  $bExpS = Scale-ToWidth $bExp $panelW; $aExpS = Scale-ToWidth $aExp $panelW
  $bNpS  = Scale-ToWidth $bNp  $panelW; $aNpS  = Scale-ToWidth $aNp  $panelW
  $pad = 28; $gap = 24; $headerH = 110; $secH = 28; $footerH = 28
  $row1H = [Math]::Max($bExpS.Height, $aExpS.Height)
  $row2H = [Math]::Max($bNpS.Height, $aNpS.Height)
  $W = $pad * 2 + $panelW * 2 + $gap
  $H = $pad + $headerH + $secH + $row1H + 24 + $secH + $row2H + $footerH + $pad
  $bmp = New-Object System.Drawing.Bitmap $W, $H
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.Clear([System.Drawing.Color]::FromArgb(255, 248, 247, 244))
  $g.TextRenderingHint = 'ClearTypeGridFit'
  $titleFont = New-Object System.Drawing.Font 'Segoe UI Semibold', 17
  $subFont = New-Object System.Drawing.Font 'Segoe UI', 10
  $labelFont = New-Object System.Drawing.Font 'Segoe UI Semibold', 12
  $footFont = New-Object System.Drawing.Font 'Segoe UI', 8.5
  $beforeBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 180, 45, 35))
  $afterBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 15, 120, 85))
  $muted = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 95, 95, 100))

  $g.DrawString('WER Surface - Before vs After (clean crops + annotations)', $titleFont, [System.Drawing.Brushes]::Black, $pad, $pad)
  $g.DrawString('Red = prusa/slic3r brand tokens     Green = slicer-engine neutral tokens', $subFont, $muted, $pad, ($pad + 34))
  $yLab = $pad + 62
  $g.FillRectangle($beforeBrush, $pad, ($yLab + 4), 14, 14)
  $g.DrawString('BEFORE', $labelFont, $beforeBrush, ($pad + 22), $yLab)
  $g.FillRectangle($afterBrush, ($pad + $panelW + $gap), ($yLab + 4), 14, 14)
  $g.DrawString('AFTER', $labelFont, $afterBrush, ($pad + $panelW + $gap + 22), $yLab)

  $y1 = $pad + $headerH
  $g.DrawString('1) Explorer AppCrash_* folder  +  full path caption', $subFont, $muted, $pad, $y1)
  $g.DrawString('1) Explorer AppCrash_* folder  +  full path caption', $subFont, $muted, ($pad + $panelW + $gap), $y1)
  $y1b = $y1 + $secH
  $g.DrawImage($bExpS, $pad, $y1b)
  $g.DrawImage($aExpS, ($pad + $panelW + $gap), $y1b)

  $y2 = $y1b + $row1H + 16
  $g.DrawString('2) Report.wer identity fields (annotated, paths wrapped complete)', $subFont, $muted, $pad, $y2)
  $g.DrawString('2) Report.wer identity fields (annotated, paths wrapped complete)', $subFont, $muted, ($pad + $panelW + $gap), $y2)
  $y2b = $y2 + $secH
  $g.DrawImage($bNpS, $pad, $y2b)
  $g.DrawImage($aNpS, ($pad + $panelW + $gap), $y2b)

  $g.DrawString('Live WER 2026-07-20 / full paths / no overlapping headers', $footFont, $muted, $pad, ($H - $pad - 14))
  $out = Join-Path $OutDir 'COMPARE_04_WER_surface_before_vs_after.png'
  $bmp.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)
  Write-Host "COMPOSED $out $($bmp.Width)x$($bmp.Height)"
  $g.Dispose(); $bmp.Dispose()
  $bExpS.Dispose(); $aExpS.Dispose(); $bNpS.Dispose(); $aNpS.Dispose()
} finally {
  $bExp.Dispose(); $aExp.Dispose(); $bNp.Dispose(); $aNp.Dispose()
}

Compose-Pair `
  (Join-Path $OutDir '22_OS_WER_Report_wer_prusa-slicer-console_notepad_annotated.png') `
  (Join-Path $OutDir '18_OS_WER_Report_wer_slicer-engine_notepad_annotated.png') `
  (Join-Path $OutDir 'COMPARE_04b_WER_Report_wer_notepad_before_vs_after.png') `
  'Report.wer identity - Before vs After (annotated)' `
  'prusa/slic3r boxed in red (BEFORE)     slicer-engine boxed in green (AFTER)'

Remove-Item $rawB, $rawA -Force -ErrorAction SilentlyContinue
Write-Host 'DONE'

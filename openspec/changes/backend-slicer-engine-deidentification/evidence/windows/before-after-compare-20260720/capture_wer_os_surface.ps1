# Capture real Windows OS WER surfaces (Explorer ReportArchive + Notepad Report.wer).
# Prefer live AppCrash folders; optionally force a fresh AppCrash via remote AV (no debugger).
# Usage examples:
#   powershell -File capture_wer_os_surface.ps1 -Mode after
#   powershell -File capture_wer_os_surface.ps1 -Mode before -ForceCrash
#   powershell -File capture_wer_os_surface.ps1 -Mode both -ForceCrash
param(
  [ValidateSet('before','after','both','compose-only')]
  [string]$Mode = 'both',
  [switch]$ForceCrash,
  [string]$OutDir = ''
)

$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $OutDir) { $OutDir = Join-Path $Here 'shots' }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$BeforeExe = 'D:\Repos\Phrozen\Bundle\web_slicer_core\third_party\prusaslicer_build\src\Release\prusa-slicer-console.exe'
$AfterExe  = 'C:\Program Files\Bundle Launcher\resources\bundle\slicer-engine\bin\slicer-engine.exe'
if (-not (Test-Path -LiteralPath $AfterExe)) {
  $AfterExe = 'D:\Repos\Phrozen\Bundle\web_slicer_core\slicer-engine-qa\bin\slicer-engine.exe'
}

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
using System.Diagnostics;

public static class WerCap {
  public const uint PROCESS_ALL_ACCESS = 0x001F0FFF;
  public const uint CREATE_SUSPENDED = 0x00000004;

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
  [DllImport("kernel32.dll", SetLastError=true)] public static extern IntPtr OpenProcess(uint a, bool b, int pid);
  [DllImport("kernel32.dll", SetLastError=true)] public static extern IntPtr CreateRemoteThread(IntPtr h, IntPtr a, UIntPtr s, IntPtr start, IntPtr p, uint f, IntPtr tid);
  [DllImport("kernel32.dll", SetLastError=true)] public static extern bool CloseHandle(IntPtr h);
  [DllImport("kernel32.dll", SetLastError=true)] public static extern IntPtr VirtualAllocEx(IntPtr h, IntPtr a, UIntPtr s, uint t, uint p);
  [DllImport("kernel32.dll", SetLastError=true)] public static extern bool WriteProcessMemory(IntPtr h, IntPtr a, byte[] buf, int n, out int w);
  [DllImport("kernel32.dll", SetLastError=true)] public static extern uint WaitForSingleObject(IntPtr h, uint ms);
  [DllImport("kernel32.dll", SetLastError=true, CharSet=CharSet.Unicode)]
  public static extern bool CreateProcessW(string app, string cmd, IntPtr pa, IntPtr ta, bool inherit, uint flags, IntPtr env, string dir, ref STARTUPINFO si, out PROCESS_INFORMATION pi);
  [DllImport("kernel32.dll")] public static extern uint ResumeThread(IntPtr hThread);
  [DllImport("kernel32.dll")] public static extern bool TerminateProcess(IntPtr h, uint c);

  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
  [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
  public struct STARTUPINFO {
    public int cb; public string lpReserved; public string lpDesktop; public string lpTitle;
    public int dwX,dwY,dwXSize,dwYSize,dwXCountChars,dwYCountChars,dwFillAttribute,dwFlags;
    public short wShowWindow, cbReserved2; public IntPtr lpReserved2, hStdInput, hStdOutput, hStdError;
  }
  [StructLayout(LayoutKind.Sequential)]
  public struct PROCESS_INFORMATION {
    public IntPtr hProcess, hThread; public int dwProcessId, dwThreadId;
  }

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

  public static void CloseTitleContains(string needle) {
    IntPtr h = FindTitleContains(needle);
    if (h != IntPtr.Zero) SendMessage(h, 0x0010, IntPtr.Zero, IntPtr.Zero);
  }

  public static void Save(IntPtr hwnd, string path) {
    SetProcessDPIAware();
    ShowWindow(hwnd, 9);
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
      long nw = 0;
      for (int y = 0; y < h; y += 5)
        for (int x = 0; x < w; x += 5) {
          Color c = bmp.GetPixel(x, y);
          if (c.R < 248 || c.G < 248 || c.B < 248) nw++;
        }
      bmp.Save(path, ImageFormat.Png);
      Console.WriteLine("SAVED " + path + " " + w + "x" + h + " nw=" + nw);
      if (nw < 40) throw new Exception("Capture looks blank: " + path);
    }
  }

  // Keep process suspended, inject tiny AV shellcode, run it (no debugger) so WER writes AppCrash_*.
  public static int ForceAppCrash(string exePath) {
    string dir = System.IO.Path.GetDirectoryName(exePath);
    var si = new STARTUPINFO(); si.cb = Marshal.SizeOf(typeof(STARTUPINFO));
    PROCESS_INFORMATION pi;
    // No CLI args: stay alive while suspended; primary thread never needs to finish --help.
    if (!CreateProcessW(exePath, "\"" + exePath + "\"", IntPtr.Zero, IntPtr.Zero, false, CREATE_SUSPENDED, IntPtr.Zero, dir, ref si, out pi))
      throw new Exception("CreateProcess failed err=" + Marshal.GetLastWin32Error());
    try {
      // xor rax,rax; mov qword [rax],rax  => AV
      byte[] code = new byte[] { 0x48, 0x31, 0xC0, 0x48, 0x89, 0x00, 0xC3 };
      IntPtr mem = VirtualAllocEx(pi.hProcess, IntPtr.Zero, new UIntPtr((uint)code.Length), 0x3000, 0x40);
      if (mem == IntPtr.Zero) throw new Exception("VirtualAllocEx failed err=" + Marshal.GetLastWin32Error());
      int written;
      if (!WriteProcessMemory(pi.hProcess, mem, code, code.Length, out written))
        throw new Exception("WriteProcessMemory failed err=" + Marshal.GetLastWin32Error());
      IntPtr th = CreateRemoteThread(pi.hProcess, IntPtr.Zero, UIntPtr.Zero, mem, IntPtr.Zero, 0, IntPtr.Zero);
      if (th == IntPtr.Zero) throw new Exception("CreateRemoteThread failed err=" + Marshal.GetLastWin32Error());
      WaitForSingleObject(th, 8000);
      CloseHandle(th);
      uint wr = WaitForSingleObject(pi.hProcess, 20000);
      if (wr == 0x00000102) { // WAIT_TIMEOUT
        TerminateProcess(pi.hProcess, 1);
        throw new Exception("Process did not exit after AV shellcode");
      }
      return pi.dwProcessId;
    } finally {
      CloseHandle(pi.hThread);
      CloseHandle(pi.hProcess);
    }
  }
}
"@

function Get-WerRoots {
  @(
    (Join-Path $env:PROGRAMDATA 'Microsoft\Windows\WER\ReportArchive'),
    (Join-Path $env:LOCALAPPDATA 'Microsoft\Windows\WER\ReportArchive'),
    (Join-Path $env:PROGRAMDATA 'Microsoft\Windows\WER\ReportQueue'),
    (Join-Path $env:LOCALAPPDATA 'Microsoft\Windows\WER\ReportQueue')
  ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
}

function Find-LatestAppCrash([string]$NamePrefix) {
  $best = $null
  foreach ($root in Get-WerRoots) {
    Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue |
      Where-Object { $_.Name -like ("AppCrash_" + $NamePrefix + '*') } |
      ForEach-Object {
        if (-not $best -or $_.LastWriteTime -gt $best.LastWriteTime) { $best = $_ }
      }
  }
  return $best
}

function Wait-NewAppCrash([string]$NamePrefix, [datetime]$Since, [int]$TimeoutSec = 90) {
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    $hit = Find-LatestAppCrash $NamePrefix
    if ($hit -and $hit.LastWriteTime -ge $Since.AddSeconds(-2)) {
      # Prefer folders that already contain Report.wer
      $wer = Join-Path $hit.FullName 'Report.wer'
      if (Test-Path -LiteralPath $wer) { return $hit }
    }
    Start-Sleep -Milliseconds 800
  }
  return $null
}

function Capture-ExplorerFolder([string]$FolderPath, [string]$OutPng, [string]$TitleNeedle) {
  [WerCap]::CloseTitleContains($TitleNeedle) | Out-Null
  Start-Sleep -Milliseconds 300
  Start-Process explorer.exe -ArgumentList $FolderPath
  $hwnd = [IntPtr]::Zero
  for ($i = 0; $i -lt 50; $i++) {
    Start-Sleep -Milliseconds 200
    $hwnd = [WerCap]::FindTitleContains($TitleNeedle)
    if ($hwnd -ne [IntPtr]::Zero) { break }
  }
  if ($hwnd -eq [IntPtr]::Zero) { throw "Explorer window not found for needle=$TitleNeedle path=$FolderPath" }
  Start-Sleep -Milliseconds 700
  [WerCap]::Save($hwnd, $OutPng)
  [WerCap]::SendMessage($hwnd, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
}

function Capture-NotepadWer([string]$WerPath, [string]$OutPng) {
  [WerCap]::CloseTitleContains('Report.wer') | Out-Null
  Start-Sleep -Milliseconds 250
  Start-Process notepad.exe -ArgumentList "`"$WerPath`""
  $hwnd = [IntPtr]::Zero
  for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 200
    $hwnd = [WerCap]::FindTitleContains('Report.wer')
    if ($hwnd -ne [IntPtr]::Zero) { break }
  }
  if ($hwnd -eq [IntPtr]::Zero) { throw "Notepad Report.wer not found" }
  Start-Sleep -Milliseconds 500
  # Home then select a bit of key identity lines for readability
  [WerCap]::SetForegroundWindow($hwnd) | Out-Null
  [System.Windows.Forms.SendKeys]::SendWait('^{HOME}')
  Start-Sleep -Milliseconds 200
  [WerCap]::Save($hwnd, $OutPng)
  [WerCap]::SendMessage($hwnd, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
}

function Ensure-AppCrash([string]$Side, [string]$Exe, [string]$Prefix, [switch]$Force) {
  $existing = Find-LatestAppCrash $Prefix
  if ($existing -and -not $Force) {
    Write-Host "[$Side] reuse existing $($existing.FullName)"
    return $existing
  }
  if (-not (Test-Path -LiteralPath $Exe)) { throw "[$Side] exe missing: $Exe" }
  Write-Host "[$Side] ForceAppCrash $Exe"
  $since = Get-Date
  $pidCrash = [WerCap]::ForceAppCrash($Exe)
  Write-Host "[$Side] crashed pid=$pidCrash; waiting WER AppCrash_$Prefix*"
  $hit = Wait-NewAppCrash -NamePrefix $Prefix -Since $since -TimeoutSec 120
  if (-not $hit) {
    # Fallback: any matching archive
    $hit = Find-LatestAppCrash $Prefix
  }
  if (-not $hit) { throw "[$Side] no AppCrash_$Prefix* WER folder found after crash" }
  Write-Host "[$Side] WER folder=$($hit.FullName)"
  return $hit
}

function Compose-Compare([string]$BeforeExplorer, [string]$AfterExplorer, [string]$OutPng) {
  Add-Type -AssemblyName System.Drawing
  $left = [System.Drawing.Image]::FromFile($BeforeExplorer)
  $right = [System.Drawing.Image]::FromFile($AfterExplorer)
  try {
    $pad = 28
    $gap = 24
    $headerH = 86
    $labelH = 36
    $footerH = 28
    $panelW = [Math]::Max($left.Width, $right.Width)
    $panelH = [Math]::Max($left.Height, $right.Height)
    $W = $pad * 2 + $panelW * 2 + $gap
    $H = $pad + $headerH + $labelH + $panelH + $footerH + $pad
    $bmp = New-Object System.Drawing.Bitmap $W, $H
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.Clear([System.Drawing.Color]::FromArgb(255, 250, 249, 246))
    $g.SmoothingMode = 'HighQuality'
    $g.TextRenderingHint = 'ClearTypeGridFit'

    $titleFont = New-Object System.Drawing.Font 'Segoe UI Semibold', 18
    $subFont = New-Object System.Drawing.Font 'Segoe UI', 10
    $labelFont = New-Object System.Drawing.Font 'Segoe UI Semibold', 11
    $footFont = New-Object System.Drawing.Font 'Segoe UI', 8
    $ink = [System.Drawing.Brushes]::Black
    $beforeBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 180, 50, 40))
    $afterBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 20, 120, 90))
    $muted = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 90, 90, 95))

    $g.DrawString('WER Surface - Before vs After (real OS Explorer)', $titleFont, $ink, $pad, $pad)
    $g.DrawString('Windows Error Reporting / ReportArchive / AppCrash_* folders (not dump / not cdb text)', $subFont, $muted, $pad, ($pad + 36))

    $y0 = $pad + $headerH
    $g.FillRectangle($beforeBrush, $pad, $y0, 14, 14)
    $g.DrawString('BEFORE  AppCrash_prusa-slicer-con...', $labelFont, $beforeBrush, ($pad + 22), ($y0 - 2))
    $g.FillRectangle($afterBrush, ($pad + $panelW + $gap), $y0, 14, 14)
    $g.DrawString('AFTER  AppCrash_slicer-engine...', $labelFont, $afterBrush, ($pad + $panelW + $gap + 22), ($y0 - 2))

    $yImg = $y0 + $labelH
    $g.DrawImage($left, $pad, $yImg, $panelW, [int]($left.Height * $panelW / $left.Width))
    # Keep aspect: draw at natural size centered in panel box
    $g.FillRectangle([System.Drawing.Brushes]::WhiteSmoke, $pad, $yImg, $panelW, $panelH)
    $g.FillRectangle([System.Drawing.Brushes]::WhiteSmoke, ($pad + $panelW + $gap), $yImg, $panelW, $panelH)
    $lx = $pad + [int](($panelW - $left.Width) / 2)
    $ly = $yImg + [int](($panelH - $left.Height) / 2)
    $rx = $pad + $panelW + $gap + [int](($panelW - $right.Width) / 2)
    $ry = $yImg + [int](($panelH - $right.Height) / 2)
    $g.DrawImage($left, $lx, $ly, $left.Width, $left.Height)
    $g.DrawImage($right, $rx, $ry, $right.Width, $right.Height)

    $g.DrawString('Source: live WER ReportArchive / captured on this machine / backend-slicer-engine-deidentification', $footFont, $muted, $pad, ($H - $pad - 16))

    $bmp.Save($OutPng, [System.Drawing.Imaging.ImageFormat]::Png)
    Write-Host "COMPOSED $OutPng $($bmp.Width)x$($bmp.Height)"
    $g.Dispose(); $bmp.Dispose()
    $titleFont.Dispose(); $subFont.Dispose(); $labelFont.Dispose(); $footFont.Dispose()
    $beforeBrush.Dispose(); $afterBrush.Dispose(); $muted.Dispose()
  } finally {
    $left.Dispose(); $right.Dispose()
  }
}

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$meta = @()

if ($Mode -eq 'compose-only') {
  $b = Join-Path $OutDir '17_OS_WER_ReportArchive_prusa-slicer-console.png'
  $a = Join-Path $OutDir '16_OS_WER_ReportArchive_slicer-engine.png'
  Compose-Compare $b $a (Join-Path $OutDir 'COMPARE_04_WER_surface_before_vs_after.png')
  return
}

$doBefore = $Mode -eq 'before' -or $Mode -eq 'both'
$doAfter  = $Mode -eq 'after'  -or $Mode -eq 'both'

$beforeFolder = $null
$afterFolder = $null

if ($doBefore) {
  $beforeFolder = Ensure-AppCrash -Side 'BEFORE' -Exe $BeforeExe -Prefix 'prusa-slicer' -Force:$ForceCrash
  $wer = Join-Path $beforeFolder.FullName 'Report.wer'
  $outExp = Join-Path $OutDir '17_OS_WER_ReportArchive_prusa-slicer-console.png'
  $outNp  = Join-Path $OutDir '22_OS_WER_Report_wer_prusa-slicer-console_notepad.png'
  $needle = ($beforeFolder.Name.Substring(0, [Math]::Min(28, $beforeFolder.Name.Length)))
  Capture-ExplorerFolder -FolderPath $beforeFolder.FullName -OutPng $outExp -TitleNeedle $needle
  if (Test-Path -LiteralPath $wer) {
    Capture-NotepadWer -WerPath $wer -OutPng $outNp
    Copy-Item -LiteralPath $wer -Destination (Join-Path $Here 'BEFORE_Report.wer') -Force
  }
  $meta += "BEFORE_FOLDER=$($beforeFolder.FullName)"
  $meta += "BEFORE_EXPLORER=$outExp"
  $meta += "BEFORE_NOTEPAD=$outNp"
}

if ($doAfter) {
  $afterFolder = Ensure-AppCrash -Side 'AFTER' -Exe $AfterExe -Prefix 'slicer-engine' -Force:$ForceCrash
  $wer = Join-Path $afterFolder.FullName 'Report.wer'
  $outExp = Join-Path $OutDir '16_OS_WER_ReportArchive_slicer-engine.png'
  $outNp  = Join-Path $OutDir '18_OS_WER_Report_wer_slicer-engine_notepad.png'
  $needle = ($afterFolder.Name.Substring(0, [Math]::Min(28, $afterFolder.Name.Length)))
  Capture-ExplorerFolder -FolderPath $afterFolder.FullName -OutPng $outExp -TitleNeedle $needle
  if (Test-Path -LiteralPath $wer) {
    Capture-NotepadWer -WerPath $wer -OutPng $outNp
    Copy-Item -LiteralPath $wer -Destination (Join-Path $Here 'AFTER_Report.wer') -Force
  }
  $meta += "AFTER_FOLDER=$($afterFolder.FullName)"
  $meta += "AFTER_EXPLORER=$outExp"
  $meta += "AFTER_NOTEPAD=$outNp"
}

# Also capture parent ReportArchive listing focused on AppCrash rows (AFTER root that has folders)
$parent = Split-Path -Parent (Find-LatestAppCrash 'slicer-engine').FullName
if ($parent) {
  $outParent = Join-Path $OutDir "23_OS_WER_ReportArchive_parent_$stamp.png"
  Capture-ExplorerFolder -FolderPath $parent -OutPng $outParent -TitleNeedle 'ReportArchive'
  $meta += "PARENT=$outParent"
}

$bExp = Join-Path $OutDir '17_OS_WER_ReportArchive_prusa-slicer-console.png'
$aExp = Join-Path $OutDir '16_OS_WER_ReportArchive_slicer-engine.png'
if ((Test-Path $bExp) -and (Test-Path $aExp)) {
  Compose-Compare $bExp $aExp (Join-Path $OutDir 'COMPARE_04_WER_surface_before_vs_after.png')
}

$metaPath = Join-Path $Here ("WER_OS_CAPTURE_META_$stamp.txt")
$meta + @("STAMP=$stamp", "MODE=$Mode", "FORCE=$ForceCrash") | Set-Content -Encoding UTF8 $metaPath
Write-Host "META $metaPath"
Write-Host 'DONE'

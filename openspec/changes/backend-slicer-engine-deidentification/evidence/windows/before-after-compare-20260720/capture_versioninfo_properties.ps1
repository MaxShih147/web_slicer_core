# Capture real Windows Properties > Details for VERSIONINFO evidence.
# Usage: $env:CAP_FILE=...; $env:CAP_OUT=...; $env:CAP_NEEDLE=...; powershell -File this.ps1
$ErrorActionPreference = 'Stop'
$TargetFile = $env:CAP_FILE
$OutputPng = $env:CAP_OUT
$TitleNeedle = $env:CAP_NEEDLE
if (-not $TargetFile -or -not $OutputPng) { throw "Set CAP_FILE and CAP_OUT env vars" }
if (-not $TitleNeedle) { $TitleNeedle = [IO.Path]::GetFileName($TargetFile) }
if (-not (Test-Path -LiteralPath $TargetFile)) { throw "File not found: $TargetFile" }

Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms

$drawing = [Reflection.Assembly]::LoadWithPartialName('System.Drawing').Location
Add-Type -ReferencedAssemblies $drawing -TypeDefinition @"
using System;
using System.Text;
using System.Threading;
using System.Runtime.InteropServices;
using System.Drawing;
using System.Drawing.Imaging;

public static class WinCap2 {
  public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hwnd, IntPtr hdcBlt, uint nFlags);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }

  public static IntPtr FindTitleContains(string needle) {
    IntPtr found = IntPtr.Zero;
    EnumWindows((h, l) => {
      if (!IsWindowVisible(h)) return true;
      var sb = new StringBuilder(512);
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
    Thread.Sleep(500);
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
}
"@

[WinCap2]::CloseTitleContains($TitleNeedle)
Start-Sleep -Milliseconds 400

$dir = [IO.Path]::GetDirectoryName($TargetFile)
$leaf = [IO.Path]::GetFileName($TargetFile)
$shell = New-Object -ComObject Shell.Application
$folder = $shell.NameSpace($dir)
$item = $folder.ParseName($leaf)
if (-not $item) { throw "Shell item not found" }
$item.InvokeVerb('properties')

$ph = [IntPtr]::Zero
for ($i = 0; $i -lt 40; $i++) {
  Start-Sleep -Milliseconds 200
  $ph = [WinCap2]::FindTitleContains($TitleNeedle)
  if ($ph -ne [IntPtr]::Zero) { break }
}
if ($ph -eq [IntPtr]::Zero) { throw "Properties window not found for $TitleNeedle" }
Write-Host "Properties hwnd=$ph"

$root = [System.Windows.Automation.AutomationElement]::FromHandle($ph)
$tabCond = New-Object System.Windows.Automation.PropertyCondition(
  [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
  [System.Windows.Automation.ControlType]::TabItem)
$tabs = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $tabCond)
$clicked = $false
foreach ($t in $tabs) {
  $name = $t.Current.Name
  Write-Host "TAB: $name"
  if ($name -match '詳細資料|Details') {
    $sel = $t.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern)
    $sel.Select()
    $clicked = $true
    Write-Host "Selected tab: $name"
    break
  }
}
if (-not $clicked) {
  Write-Host "WARN: Details tab not found; Ctrl+Tab fallback"
  [WinCap2]::SetForegroundWindow($ph) | Out-Null
  Start-Sleep -Milliseconds 300
  for ($i = 0; $i -lt 4; $i++) {
    [System.Windows.Forms.SendKeys]::SendWait("^{TAB}")
    Start-Sleep -Milliseconds 250
  }
}

Start-Sleep -Milliseconds 700
[WinCap2]::Save($ph, $OutputPng)
[WinCap2]::SendMessage($ph, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
Write-Host "DONE $OutputPng"

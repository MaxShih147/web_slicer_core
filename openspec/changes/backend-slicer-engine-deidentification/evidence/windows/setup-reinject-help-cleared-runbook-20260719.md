# Windows Setup reinject runbook — help-cleared consumer

**Date：** 2026-07-19  
**Why：** Program Files install tree still morning postsign（`--help` PrusaSlicer>0）. Staging／7.6／7.5 gate use help-cleared `engine_build_id=20260719T105832Z`.

## Already done on this machine

1. Synced `web_slicer_core/slicer-engine` → `Bundle-Launcher/bundle-win/slicer-engine`（exe hash match staging）.  
2. CI gate 7.5 PASS on staging＋existing signed Setup Authenticode（signature of **old** Setup still Valid；content not yet reinjected）.

## Remaining（needs EV signing session）

```powershell
cd D:\Repos\Phrozen\Bundle\Bundle-Launcher
# 1) Repackage Launcher with synced bundle-win engine
powershell -File .\build-scripts\build-windows-bundle.ps1 -RepackageOnly

# 2) Manually Authenticode-sign new Setup.exe (existing EV process)

# 3) Gate with signature
powershell -File .\scripts\ci_gate_windows_deid_7.5.ps1 `
  -ArtifactRoot .\dist\win-unpacked\resources\bundle\slicer-engine `
  -SetupExe ".\dist\Bundle Launcher Setup 1.0.0.exe"

# 4) Silent reinstall + rescan install root (elevated)
# Setup /S → scan_slicer_engine_windows.ps1 on Program Files\...\slicer-engine
# Confirm --help PrusaSlicer=0 on install tree
```

Until step 2–4 complete, **7.2 declaration** treats help-cleared staging as the accepted consumer; install-tree lag is an explicit residual.

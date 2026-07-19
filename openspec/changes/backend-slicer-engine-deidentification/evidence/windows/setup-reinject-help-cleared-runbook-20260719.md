# Windows Setup reinject runbook — help-cleared consumer

**Date：** 2026-07-19（**closed install-tree 2026-07-20** — 見 [`setup-reinject-20260720/SUMMARY.md`](./setup-reinject-20260720/SUMMARY.md)）  
**Why：** Program Files install tree still morning postsign（`--help` PrusaSlicer>0）. Staging／7.6／7.5 gate use help-cleared consumer（現為 `engine_build_id=20260719T162525Z`）。

## Already done on this machine

1. Synced `web_slicer_core/slicer-engine` → `Bundle-Launcher/bundle-win/slicer-engine`（exe hash match staging；resources brand=0）。  
2. Built unsigned reinjection Setup → `dist-reinject-20260720002645/`（`dist/` 被 Cursor 鎖 `app.asar` 時改用旁路目錄）。  
3. Silent `/S` install → Program Files **help PrusaSlicer=0**／scan PASS／resources=0。  
4. CI gate 7.5（無 SetupExe）PASS — `ci-gate-7.5-20260719T162759Z`。

## Remaining（needs EV signing session）

```powershell
cd D:\Repos\Phrozen\Bundle\Bundle-Launcher
# Sign (EV token required — no reader attached on 2026-07-20 session):
# signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a `
#   ".\dist-reinject-20260720002645\Bundle Launcher Setup 1.0.0.exe"

powershell -File .\scripts\ci_gate_windows_deid_7.5.ps1 `
  -ArtifactRoot ".\dist-reinject-20260720002645\win-unpacked\resources\bundle\slicer-engine" `
  -SetupExe ".\dist-reinject-20260720002645\Bundle Launcher Setup 1.0.0.exe"
```

**Install-tree residual closed**（本機 PF）。對外 post-Authenticode Setup 仍待 EV 簽後重跑上式。

# Windows Setup reinject — help-cleared + resources-cleared consumer

**Date：** 2026-07-20  
**engine_build_id：** `20260719T162525Z`  
**Status：** **install-tree closed**；**Setup EV Authenticode Valid**＋7.5 `-SetupExe` **PASS**（2026-07-20）。

## Why

Program Files 仍為早上 postsign（`F9498CCB…`；`--help` PrusaSlicer>0）。Staging／bundle-win 已是 help-cleared；本輪一併清 `bin/resources` 品牌路徑（148→0）。

## Done this session

| Step | Result |
|------|--------|
| `stage_slicer_engine_resources_windows.ps1` + package consumer | **PASS**；`resource_brand_path_count=0`；build_id=`20260719T162525Z` |
| Sync → `bundle-win/slicer-engine` | hash match；help PrusaSlicer=0 |
| electron-builder → `dist-reinject-20260720002645/`（locked `dist/` bypass；Cursor 鎖 `app.asar`） | **PASS** |
| `ci_gate_windows_deid_7.5.ps1`（無 `-SetupExe`） | **PASS** — evidence `Bundle-Launcher/.../ci-gate-7.5-20260719T162759Z/` |
| Silent Setup `/S`（elevated） | exit 0（初裝 unsigned；其後 EV 簽） |
| Program Files scan＋`--help` | exe=`254248FC…`；**PrusaSlicer=0**；scan **PASS** |
| EV sign＋`ci_gate … -SetupExe` | **PASS** — [`CI-GATE-7.5-SIGNED.md`](./CI-GATE-7.5-SIGNED.md)；SHA256 `15C3E441…` |

## Artifacts

| Item | Path / value |
|------|----------------|
| Reinjection Setup（**EV signed**） | `Bundle-Launcher/dist-reinject-20260720002645/Bundle Launcher Setup 1.0.0.exe` |
| Setup SHA256（signed） | `15C3E44138CD81DCC19BD620BD9EF60A275B601A290BE4900DE79DF8B84FF0E5` |
| Authenticode | **Valid**（PHROZEN TECH EV） |
| Program Files engine | `C:\Program Files\Bundle Launcher\resources\bundle\slicer-engine` |
| PF scan report | [`scan-report-programfiles.json`](./scan-report-programfiles.json) |

## Remaining（shipping）

無（本機 reinject＋EV＋7.5 已關）。可選：將簽後 Setup 同步覆蓋正式 `dist/`（若仍被 Cursor 鎖 `app.asar`，先關閉鎖定行程）。

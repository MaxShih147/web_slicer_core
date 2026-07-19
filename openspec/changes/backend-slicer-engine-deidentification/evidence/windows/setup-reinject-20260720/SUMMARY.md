# Windows Setup reinject — help-cleared + resources-cleared consumer

**Date：** 2026-07-20  
**engine_build_id：** `20260719T162525Z`  
**Status：** **Install-tree closed**（Program Files help=0／scan PASS／resources=0）。**Setup Authenticode EV 待插 token 後簽**（本機無 smart card reader）。

## Why

Program Files 仍為早上 postsign（`F9498CCB…`；`--help` PrusaSlicer>0）。Staging／bundle-win 已是 help-cleared；本輪一併清 `bin/resources` 品牌路徑（148→0）。

## Done this session

| Step | Result |
|------|--------|
| `stage_slicer_engine_resources_windows.ps1` + package consumer | **PASS**；`resource_brand_path_count=0`；build_id=`20260719T162525Z` |
| Sync → `bundle-win/slicer-engine` | hash match；help PrusaSlicer=0 |
| electron-builder → `dist-reinject-20260720002645/`（locked `dist/` bypass；Cursor 鎖 `app.asar`） | **PASS** |
| `ci_gate_windows_deid_7.5.ps1`（無 `-SetupExe`） | **PASS** — evidence `Bundle-Launcher/.../ci-gate-7.5-20260719T162759Z/` |
| Silent Setup `/S`（elevated；**NotSigned**） | exit 0 |
| Program Files scan＋`--help` | exe=`254248FC…`；**PrusaSlicer=0**；scan **PASS**（report 見本目錄） |

## Artifacts

| Item | Path / value |
|------|----------------|
| Reinjection Setup（unsigned） | `Bundle-Launcher/dist-reinject-20260720002645/Bundle Launcher Setup 1.0.0.exe` |
| Setup SHA256 | `7C19E5EE5834FC1A42278DFA1C99581EA870B2EF7DF3EB1609BB33E6134C0D6D` |
| Authenticode | **NotSigned**（無 EV token／reader） |
| Program Files engine | `C:\Program Files\Bundle Launcher\resources\bundle\slicer-engine` |
| PF scan report | [`scan-report-programfiles.json`](./scan-report-programfiles.json) |

## Remaining（shipping）

1. 插入 EV smart card／token。  
2. `signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a "…\Bundle Launcher Setup 1.0.0.exe"`（或既有 EV 流程）。  
3. 重跑：  
   `ci_gate_windows_deid_7.5.ps1 -ArtifactRoot <engine> -SetupExe <signed Setup>`  
4. （可選）將簽後 Setup 覆蓋進正式 `dist/`（先關閉鎖住 `app.asar` 的 Cursor／Explorer）。

Until step 2–3，**本機安裝樹已與 help-cleared＋resources-cleared consumer 一致**；對外發布 Setup 仍須 EV 簽後再宣告 post-Authenticode gate。

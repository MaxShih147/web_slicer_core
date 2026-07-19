# Symbol archive runbook（Windows half）— tasks 5.5

**Status：** **adopted** — 手動 OneDrive（禁 git）；2026-07-19 確認維持此方案  
**Date：** 2026-07-19  
**Depends：** D13 `scripts/package_slicer_engine_windows.ps1`；policy [`windows-policy.md`](../windows-policy.md)

## Store decision（維持）

| Item | Choice |
|------|--------|
| Store | **Microsoft OneDrive**（每次包版後**手動**上傳） |
| Git | **禁止** commit `*.pdb` |
| Consumer bundle | **禁止** 帶 PDB |
| 重編同 commit | **不能**取代當次 PDB（客戶 dump 仍要當次那份） |

建議 OneDrive 資料夾佈局（可依團隊實際路徑調整）：

```
OneDrive\...\slicer-engine-symbols\windows\
  <engine_build_id>\
    slicer-engine.pdb
    slicer_core.pdb
    engine-artifact-manifest.json   # 從 staging 一併拷貝
```

例：`20260719T095415Z\`

## What is archived

| Item | Location（build 機） | Location（store） |
|------|----------------------|-------------------|
| PDB（shim） | `slicer-engine/symbols/slicer-engine.pdb` | OneDrive `…\<build_id>\` |
| PDB（core） | `slicer-engine/symbols/slicer_core.pdb` | 同上（約 **1.3 GB**） |
| Manifest | `slicer-engine/engine-artifact-manifest.json` | 同上 |
| PE hashes | manifest `files[].post_strip_sha256` | 同上 |

## Produce then upload

```bat
cd web_slicer_core
scripts\build_prusaslicer_fork_windows.bat low
powershell -File scripts\package_slicer_engine_windows.ps1
```

```powershell
# 確認本機產出
Get-ChildItem slicer-engine\symbols\*.pdb
# 讀 build_id
(Get-Content slicer-engine\engine-artifact-manifest.json -Raw | ConvertFrom-Json).engine_build_id

# 手動：在 OneDrive 建 <engine_build_id> 資料夾，拷貝
#   slicer-engine\symbols\*.pdb
#   slicer-engine\engine-artifact-manifest.json
```

## Lookup for crash symbolication

1. 從客訴／安裝包讀 `engine_build_id`（或 exe／dll SHA-256）。  
2. 到 OneDrive `windows\<build_id>\` 取 PDB＋manifest。  
3. WinDbg／VS 載入對應 PDB（GUID+Age 須匹配）。  
4. **Never** 把 PDB 放回 consumer `bin/` 或 Setup 內容。

Until further notice, **OneDrive** is the Win symbol store. Uploads recorded 2026-07-19:

- `…\slicer-engine-symbols\windows\20260719T095415Z\`（CLI-help cleanup consumer）  
- `…\slicer-engine-symbols\windows\20260719T105832Z\`（post–QA-restore consumer）  

各含 `slicer-engine.pdb`、`slicer_core.pdb`（≈1.3GB）、`engine-artifact-manifest.json`。

## Retention／演練（後補即可）

- [x] Upload path decided + first consumer build uploaded（OneDrive）  
- [ ] 約定保留 N 個 release train  
- [ ] 做一次 minidump → OneDrive PDB → 符號化煙測（tasks 6.6／6.7）  
- [ ] Pair macOS dSYM：[`macos-symbol-archive-runbook-5.5.md`](./macos-symbol-archive-runbook-5.5.md)

**不做 git store；以 OneDrive 手動備份為 Win 方案（已維持定案）。**

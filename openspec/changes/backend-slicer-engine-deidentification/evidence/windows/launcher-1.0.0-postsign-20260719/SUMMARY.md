# Windows post-Authenticode acceptance — Bundle Launcher 1.0.0

**captured_at_utc:** 2026-07-19T08:49:33Z  
**artifact:** `Bundle-Launcher/dist/Bundle Launcher Setup 1.0.0.exe`  
**tasks:** main 4.6／7.5（partial）；Launcher 3.3／3.4  

## 1. Authenticode

| Field | Value |
|-------|--------|
| Status | **Valid** |
| SHA256 | `6592EE9E01D311ABE6BEF22FF384DBD3526DCBAC3FB414B797D23EEE37D446C5` |
| Signer | CN=PHROZEN TECH CO., LTD. (EV) |
| Issuer | GlobalSign GCC R45 EV CodeSigning CA 2020 |
| NotAfter | 2026-09-19 |

**Note:** Only the **Setup.exe** is Authenticode-signed. Installed `Bundle Launcher.exe` reports `NotSigned` (`signAndEditExecutable: false`；手動只簽 installer)。這符合目前手動簽章流程。

## 2. Install / upgrade / uninstall / reinstall

| Step | Result |
|------|--------|
| Silent upgrade install (`Setup /S`) over prior 1.0.0 | exit 0；layout 從 `third_party` → **`slicer-engine/`** |
| Post-install engine scan | **PASS** |
| Uninstall (`Uninstall … /S /allusers`) | exit 0；registry entry gone；brand leftovers **0**；`Program Files\Bundle Launcher` 當下未完全消失（可能鎖定／延遲刪除） |
| Silent reinstall | exit 0；`slicer-engine` 存在；無 `third_party` |
| Rescan after reinstall | **PASS** |

## 3. Post-sign engine gate

Installed root: `C:\Program Files\Bundle Launcher\resources\bundle\slicer-engine`

| Check | Result |
|-------|--------|
| `scan_slicer_engine_windows.ps1` | **PASS**（見 `scan-report.json`／`scan-report-after-reinstall.json`） |
| export | 1 × `slicer_run_cli` |
| PDB in bin | none |
| harness markers | none |
| exe sha256 | `f9498ccb208c67ae878dcca58d5826754dbb9b7c0cdd29bc009760db6ad62f2f` |
| dll sha256 | `cedff73cc47035ff242c2507b15e99696d87bce65cce4aeb3fb0222b9c143f0d` |

## 4. CLI smoke

`--help` 開頭為 `Slicer Engine`／`Usage: slicer-engine`。  
**殘留：** help 本文仍含 *「This version of PrusaSlicer may not understand…」* 相容性警告（user-visible string；屬後續清理／非本輪 PE gate FAIL）。

## 5. Known residuals (not fail-closed this round)

- `bin/resources/**` ≈148 brand-named profiles/icons（scanner note）
- CLI help PrusaSlicer compat strings
- Inner app exe unsigned（僅 Setup 簽章）

## 6. Not covered yet

- Full SLA slice regression（7.6）
- QA three-crash dynamic（7.3）
- macOS Launcher §4
- AGPL §6

### Sync note（2026-07-20）

本檔為 **2026-07-19 早上 post-sign 捕捉快照**。現行（[`PROGRESS.md`](../../../PROGRESS.md)）：CLI help／resources=0 已回灌；Setup reinject **EV Valid**（`15C3E441…`）；7.3／7.6／mac §4／AGPL 皆已關。內嵌 app exe 未簽仍為殘留。

## Artifacts in this folder

- `postsign-meta.json`
- `lifecycle.json`
- `scan-report.json`
- `scan-report-after-reinstall.json`
- `cli-help.txt`

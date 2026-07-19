# Windows 7.6 minimal functional／performance matrix

**Date：** 2026-07-19  
**Task：** main **7.6**（Win 半邊）  
**Budget：** [`../../functional-budget-2.7-approved-20260719.md`](../../functional-budget-2.7-approved-20260719.md)  
**Verdict：** **PASS**（minimal MUST matrix；optional agent smoke SKIP）

## Under test

| Field | Value |
|-------|--------|
| Kind | Current help-cleared **consumer staging** |
| Path | `web_slicer_core/slicer-engine/bin/slicer-engine.exe` |
| `engine_build_id` | `20260719T105832Z` |
| flavor | `consumer` |
| exe sha256 | `254248FC041C30FE0DB3529DA5EEEABC0BDE0156E712AB46B79D05E6F0DD76E5` |
| dll sha256 | `DF36EAB9105548732BA4D8F87484E09DB5431A9747B1122123CE9EE8FBB93A41` |
| Formal scan | **PASS**（`slicer-engine/scan-report.json`） |

### Install-tree delta（not primary）

| Field | Value |
|-------|--------|
| Path | `C:\Program Files\Bundle Launcher\resources\bundle\slicer-engine\bin\slicer-engine.exe` |
| exe sha256 | `F9498CCB…`（postsign morning Setup） |
| `--help` `PrusaSlicer` hits | **3**（stale vs PrintConfig cleanup） |

**Note：** 2.7 寫 post-sign Setup install tree；本機安裝樹仍為早上 postsign 產物。Win CLI help 清零已由較新 consumer staging 證明（見 `cli-help-printconfig-20260719.md`）。本輪 7.6 **以現行 help-cleared staging 為準**；需重新打簽 Setup 回灌後，install tree 才與 help=0 一致。

## Fixture

| Item | Value |
|------|--------|
| Class | `5731d266`-class minimal SLA（20 mm box + default `SLAConfig`） |
| STL | `fixture/model.stl` ← `prusaslicer_fork/tests/data/test_stl/ASCII/20mmbox-LF.stl` |
| STL sha256 | see `summary.json` |
| INI | `fixture/config.ini` via `generate_config_ini(SLAConfig(...))`；`printer_technology = SLA` |

## Cases（2.7 minimal MUST）

| Case | Exit | Duration (s) | Brand hits | Verdict |
|------|------|--------------|------------|---------|
| `01-help` | 0 | ~1.02 | PrusaSlicer=0 | **PASS** |
| `01-help-fff` | 0 | ~1.01 | PrusaSlicer=0 | **PASS** |
| `02-missing-stl` | 1 | ~1.01 | 0 | **PASS** |
| `02-invalid-stl` | 1 | ~1.02 | 0 | **PASS** |
| `03-export-sla` cold（baseline） | 0 | ~1.01 | 0 | **PASS** — `.sl1` **129 207** bytes |
| `03-export-sla` warm vs cold | 0 | ~1.01 | 0 | **PASS** — size ratio **1.000**（±5%）；time ≤ cold×1.20 |
| `04-packaged-agent-smoke` | — | — | — | **SKIP**（optional） |

Cold／warm 同機、同 fixture；warm 建立 characterization 自洽（size／wall-clock 相對 cold）。

## Output check

- Cold／warm `.sl1` open as ZIP；含 `config.ini`、layer PNGs。  
- Archive 內仍有上游檔名 `prusaslicer.ini`（**L3／內部產物**；非 CLI user-visible；不列本輪 FAIL）。

## Artifacts

- `summary.json` — machine-readable results  
- `fixture/` — STL＋INI  
- `runs/` — stdout／stderr／`.sl1`

## Remaining for full 7.6 close

- **macOS** 半邊最小矩陣（對 `…2111`）仍開  
- 可選：agent smoke；acceptance-procedure §6 延伸矩陣（SHOULD）  
- 建議：新簽 Setup 回灌 help-cleared engine，使 install tree 與本 evidence 一致  

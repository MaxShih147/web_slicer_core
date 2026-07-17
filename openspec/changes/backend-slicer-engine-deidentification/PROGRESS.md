# Progress Snapshot — backend-slicer-engine-deidentification

**更新日期：** 2026-07-17  
**Change status：** `in_progress`（見 `.openspec.yaml`）  
**權威 macOS PoC 證據：** [`poc/evidence/m1-close-20260717T032408Z/`](./poc/evidence/m1-close-20260717T032408Z/)  
**權威 Windows baseline：** [`evidence/windows/baseline/win-baseline-20260717T055632Z/`](./evidence/windows/baseline/win-baseline-20260717T055632Z/)  
**PoC 報告：** [`poc/REPORT.md`](./poc/REPORT.md)  
**Win baseline 報告：** [`evidence/windows/baseline/BASELINE.md`](./evidence/windows/baseline/BASELINE.md)

---

## 1. 總覽

| 區塊 | 狀態 |
|------|------|
| 治理／命名／schema（§1 大部） | **完成**（缺 1.5 Security、1.6 Legal） |
| M1 macOS PoC（tasks **2.4**） | **關閉／PASS** |
| 乾淨參考報告（tasks **2.4b**） | **已批准** — [`clean-reference-report.md`](./clean-reference-report.md) |
| macOS flags 定案（tasks **2.2**） | **完成**（PoC 定案；manifest hash 鏈仍歸 5.1） |
| Windows baseline（tasks **1.7**） | **關閉** — 見 BASELINE.md |
| Windows PoC／政策（2.3／2.5） | **未開始**（baseline 已解除阻塞） |
| L1 正式改名落地（§3） | **PoC 級已驗證（macOS）**；正式 agent／CMake 雙平台落地未完成 |
| Launcher 組包（§4） | **未開始** |
| 正式 C′ 產品化（§5） | **未開始**（macOS PoC 已證明可行性） |
| AGPL／驗收自動化（§6–7） | **未開始** |

---

## 2. M1／tasks 2.4 測試結論（摘要）

| 項 | 結果 |
|----|------|
| L1 `procName`／`codeSigningID` | `slicer-engine` |
| Thread | `slicer-worker`（`slic3r_main`=0） |
| 三種 crash → `.ips` | overflow／segfault／exception 皆有 |
| L2 可讀 `Slic3r::` | **0**（乾淨符號環境） |
| Scanner 原型 | **PASS**（exit 0） |
| 定案手段 | `-fvisibility=hidden` + plain `strip`（**否決 `strip -x`**） |
| 殘餘 | `nm` brand ≈172 global（移交 5.1）；runtime harness 須改 compile-time |

**環境硬條件：** 無同 UUID dSYM／未 strip 複本；否則 ReportCrash／CoreSymbolication 可能還原舊符號。

---

## 2b. Windows／tasks 1.7 baseline（摘要）

| 項 | 結果 |
|----|------|
| Process／modules | `prusa-slicer-console`＋`PrusaSlicer.dll` |
| VERSIONINFO（exe） | `PrusaSlicer`／`Prusa Research`／`PrusaSlicer-2.9.4+UNKNOWN` |
| Exports | 470 named；`slic3r_main`；大量 `Slic3r` mangled |
| Loader error | `PrusaSlicer.dll was not loaded` |
| PDB path（exe） | `...\prusaslicer_build\...\prusa-slicer-console.pdb` |
| Minidump | modules／stack 見品牌模組名（`postload-baseline.dmp`） |
| QA crash harness | 本 Windows 建置**無** runtime `BUNDLE_QA_CRASH_MODE` |

---

## 3. 下一步（建議優先序）

1. **2.3** 定案 Windows：DLL＋shim ABI、`/DEBUG`+/PDB: 封存、consumer 排除與 debug directory 政策（依 1.7 證據）  
2. **2.5** Windows PoC（VERSIONINFO／exports／WER／三種 crash；需 compile-time harness）  
3. **§3／§5** 正式落地 visibility＋strip＋manifest；harness compile-time 化  
4. **§4** Launcher 驗證＋簽署（不二次 strip）

並行：1.5 Security、1.6 Legal／AGPL。

---

## 4. 相關產物路徑

| 產物 | 路徑 |
|------|------|
| Close 腳本（macOS） | `poc/run_m1_close.sh` |
| Scanner 原型（macOS） | `poc/scan_macos_artifact.sh` |
| Notion M1 測試稿 | [`poc/NOTION-TEST-TASK.md`](./poc/NOTION-TEST-TASK.md) |
| Notion Win baseline 稿 | [`poc/NOTION-WIN-BASELINE-TASK.md`](./poc/NOTION-WIN-BASELINE-TASK.md) |
| 乾淨參考報告（已批准） | [`clean-reference-report.md`](./clean-reference-report.md) |
| Win baseline 報告 | [`evidence/windows/baseline/BASELINE.md`](./evidence/windows/baseline/BASELINE.md) |
| Fork visibility | `prusaslicer_fork/src/libslic3r/CMakeLists.txt`、`…/src/CMakeLists.txt` |

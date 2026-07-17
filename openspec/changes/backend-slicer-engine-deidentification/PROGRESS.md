# Progress Snapshot — backend-slicer-engine-deidentification

**更新日期：** 2026-07-17  
**Change status：** `in_progress`（見 `.openspec.yaml`）  
**權威 macOS PoC 證據：** [`poc/evidence/m1-close-20260717T032408Z/`](./poc/evidence/m1-close-20260717T032408Z/)  
**PoC 報告：** [`poc/REPORT.md`](./poc/REPORT.md)

---

## 1. 總覽

| 區塊 | 狀態 |
|------|------|
| 治理／命名／schema（§1 大部） | **完成**（缺 1.5 Security、1.6 Legal、1.7 Windows baseline） |
| M1 macOS PoC（tasks **2.4**） | **關閉／PASS** |
| 乾淨參考報告（tasks **2.4b**） | **已批准** — [`clean-reference-report.md`](./clean-reference-report.md) |
| macOS flags 定案（tasks **2.2**） | **完成**（PoC 定案；manifest hash 鏈仍歸 5.1） |
| Windows PoC／baseline | **未開始**（阻塞 Win L2） |
| L1 正式改名落地（§3） | **PoC 級已驗證**；正式 agent／CMake 雙平台落地未完成 |
| Launcher 組包（§4） | **未開始** |
| 正式 C′ 產品化（§5） | **未開始**（PoC 已證明可行性） |
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

## 3. 下一步（建議優先序）

1. **1.7** Windows baseline  
2. **2.5** Windows PoC  
3. **§3／§5** 正式落地 visibility＋strip＋manifest；harness compile-time 化  
4. **§4** Launcher 驗證＋簽署（不二次 strip）

---

## 4. 相關產物路徑

| 產物 | 路徑 |
|------|------|
| Close 腳本 | `poc/run_m1_close.sh` |
| Scanner 原型 | `poc/scan_macos_artifact.sh` |
| Notion 測試稿（可貼上） | [`poc/NOTION-TEST-TASK.md`](./poc/NOTION-TEST-TASK.md) |
| 乾淨參考報告（已批准） | [`clean-reference-report.md`](./clean-reference-report.md) |
| Fork visibility | `prusaslicer_fork/src/libslic3r/CMakeLists.txt`、`…/src/CMakeLists.txt` |

# Progress Snapshot — backend-slicer-engine-deidentification

**更新日期：** 2026-07-17（合併：macOS 5.4／5.6／5.7＋Windows 5.3 產品化）  
**Change status：** `in_progress`（見 `.openspec.yaml`）  
**權威 macOS PoC：** [`poc/evidence/m1-close-20260717T032408Z/`](./poc/evidence/m1-close-20260717T032408Z/)  
**權威 Windows PoC：** [`poc/evidence/w25-close-20260717T083241Z/`](./poc/evidence/w25-close-20260717T083241Z/)  
**macOS 產品化證據：** [`evidence/macos-productize-5.2-3.5-3.6.md`](./evidence/macos-productize-5.2-3.5-3.6.md)、[`evidence/macos-productize-5.4-5.6-5.7.md`](./evidence/macos-productize-5.4-5.6-5.7.md)

---

## 1. 總覽

| 區塊 | 狀態 |
|------|------|
| 治理／命名／schema（§1 大部） | **完成**（缺 1.5／1.6） |
| 雙平台 PoC（§2） | **關閉／PASS** |
| §3 L1 | **macOS 3.1／3.2／3.4／3.5／3.6 關閉**；**Win 3.3 關閉** |
| §5 C′ | **macOS 5.1／5.2／5.4／5.6／5.7 關閉**；**Win 5.3 關閉**；5.1b／5.5 待 |
| §4 Launcher | **未開始**（腳本路徑文字已改；完整組包未跑） |
| §6–7 | **未開始** |

---

## 2. 已驗證結果（雙平台）

### Windows

| 項 | 狀態 |
|----|------|
| **5.3** export=1 | **PASS**（`dumpbin` 僅 `slicer_run_cli`） |
| Win package／harness 靜態稽核 | **PASS**（`package_slicer_engine_windows.ps1`） |
| Win smoke `--help` | **PASS** |

```bat
scripts\build_prusaslicer_fork_windows.bat low clean
powershell -File scripts\package_slicer_engine_windows.ps1
```

### macOS

| 項 | 狀態 |
|----|------|
| Formal scan gate | `scan_slicer_engine_macos.sh`；packager fail-closed |
| Consumer | nm 0；無 dSYM；`harness_markers=[]`；PASS |
| QA flavor | `slicer-engine-qa/`＋`qa_delta`；PASS |
| Runtime env | consumer 對 `BUNDLE_QA_CRASH_MODE` 不崩 |

```bash
./scripts/build_prusaslicer_fork_macos.sh
# or: SLICER_ENGINE_FLAVOR=qa ./scripts/build_prusaslicer_fork_macos.sh
```

---

## 3. 下一步

1. **Launcher §4** 接 macOS／Win manifest 與正式組包  
2. **5.5** symbol archive runbook；並行 1.5／1.6  
3. §6 AGPL／§7 雙平台正式驗收  

---

## 4. 關鍵路徑

| 產物 | 路徑 |
|------|------|
| D13 package (macOS) | `scripts/package_slicer_engine_macos.sh` |
| Formal scan (macOS) | `scripts/scan_slicer_engine_macos.sh` |
| Consumer／QA (macOS) | `third_party/slicer-engine/`、`…-qa/`（gitignored） |
| Win package | `scripts/package_slicer_engine_windows.ps1` |
| macOS 證據 | [`evidence/macos-productize-5.4-5.6-5.7.md`](./evidence/macos-productize-5.4-5.6-5.7.md) |

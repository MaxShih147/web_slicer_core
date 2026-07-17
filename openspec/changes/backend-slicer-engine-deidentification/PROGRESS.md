# Progress Snapshot — backend-slicer-engine-deidentification

**更新日期：** 2026-07-17（修正：macOS 項不得因 Win 工作誤勾）  
**Change status：** `in_progress`（見 `.openspec.yaml`）  
**權威 macOS PoC 證據：** [`poc/evidence/m1-close-20260717T032408Z/`](./poc/evidence/m1-close-20260717T032408Z/)  
**權威 Windows baseline：** [`evidence/windows/baseline/win-baseline-20260717T055632Z/`](./evidence/windows/baseline/win-baseline-20260717T055632Z/)  
**權威 Windows PoC：** [`poc/evidence/w25-close-20260717T083241Z/`](./poc/evidence/w25-close-20260717T083241Z/)  
**PoC 報告：** [`poc/REPORT.md`](./poc/REPORT.md)（macOS）／[`poc/REPORT-WIN.md`](./poc/REPORT-WIN.md)（Windows 2.5）  
**Win baseline 報告：** [`evidence/windows/baseline/BASELINE.md`](./evidence/windows/baseline/BASELINE.md)  
**Win 政策定案：** [`windows-policy.md`](./windows-policy.md)

---

## 1. 總覽

| 區塊 | 狀態 |
|------|------|
| 治理／命名／schema（§1 大部） | **完成**（缺 1.5 Security、1.6 Legal） |
| M1 macOS PoC（tasks **2.4**） | **關閉／PASS**（先前 Mac；非本輪） |
| Windows baseline／政策／PoC（**1.7／2.3／2.5**） | **關閉／PASS** |
| **本輪 Windows 產品化** | **5.3 PASS**（export=1＋package＋`--help`）；3.3／3.4 部分 |
| **macOS 產品化（§3／4／5）** | **未驗證** — 僅有腳本／原始碼草稿，**tasks 已改回未勾** |
| Launcher 完整組包／簽章 | **未跑** |
| AGPL／§7 驗收 | **未開始** |

---

## 2. 本輪實際驗證範圍（Windows only）

| 項 | 狀態 |
|----|------|
| **5.3** export=1 | **PASS**（`dumpbin` 僅 `slicer_run_cli`） |
| Win package／harness 靜態稽核 | **PASS**（`package_slicer_engine_windows.ps1`） |
| Win smoke `--help` | **PASS**（含 GMP／MPFR 同目錄） |
| macOS 5.1／3.2／4.1 | **腳本已寫，未執行** → tasks **未勾** |

**驗證指令（Windows）：**

```bat
scripts\build_prusaslicer_fork_windows.bat low clean
powershell -File scripts\package_slicer_engine_windows.ps1
```

**macOS（待 Mac 機）：**

```bash
./scripts/build_prusaslicer_fork_macos.sh consumer
./scripts/package_slicer_engine_macos.sh
```

---

## 3. 下一步

1. 在 **Mac** 跑 5.1／3.1–3.2／4.1 並留 evidence 後再勾 tasks  
2. Win 完整 Launcher installer（4.2／4.5）  
3. §6 AGPL／§7 雙平台正式驗收  

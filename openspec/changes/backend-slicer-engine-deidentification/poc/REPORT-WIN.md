# Windows PoC REPORT — tasks 2.5（＋compile-time harness）

**Status：** PASS（PoC close）  
**日期：** 2026-07-17  
**政策：** [`windows-policy.md`](../windows-policy.md)（2.3）  
**權威 evidence：** [`evidence/w25-close-20260717T083241Z/`](./evidence/w25-close-20260717T083241Z/)  
**Build：** `BUNDLE_QA_CRASH_HARNESS=ON`，`SLIC3R_GUI=OFF`，VS2022 Release

---

## 0. 結論

| 項 | 結果 |
|----|------|
| Compile-time harness | **Done** — `bundle_qa_crash_probe.cpp`；已移出 `SLAPrint.cpp` |
| Rename／ABI | **Done** — `slicer-engine.exe` → `slicer_core.dll` → `slicer_run_cli` |
| VERSIONINFO | **Done** — Company=`Phrozen Technology`；Product=`Slicer Engine`（exe＋DLL） |
| PDBALTPATH | **Done** — RSDS=`slicer-engine.pdb`／`slicer_core.pdb`（無 `prusaslicer_build` 路徑） |
| 三種 crash | **Done** — overflow／segfault／exception 皆有 dump＋非零失敗 exit |
| Minidump 模組名 | **Done** — `slicer_engine`／`slicer_core`（無 `PrusaSlicer`） |
| Export 收斂為 1 | **部分（PoC 當日）** — 仍 ~470 cereal mangled → **其後 5.3 已關閉（export=1）** |
| Go／No-go | **Go** 進 §3／§5 — **後續 5.3／Launcher §4（Win unsigned）已於 2026-07-17～19 關閉** |

---

## 1. Harness（compile-time）

| 項目 | 實作 |
|------|------|
| Flag | CMake `BUNDLE_QA_CRASH_HARNESS` → `-DBUNDLE_QA_CRASH_HARNESS` |
| TU | `src/bundle_qa_crash_probe.cpp`（僅 ON 時編譯） |
| 呼叫點 | `slicer_run_cli`／unix `main` 入口（非 `SLAPrint`） |
| Mode | `BUNDLE_QA_CRASH_MODE=overflow\|segfault\|exception`（僅 QA binary 內有效） |
| Consumer | 預設 OFF；未定義巨集時 probe **不**編入 |

---

## 2. Windows 政策對照（2.3 → 2.5）

| 政策 | PoC 結果 |
|------|----------|
| W-ABI-1 | `slicer-engine.exe`／`slicer_core.dll`／`slicer_run_cli` |
| W-EXP-1 | 入口已更名；殘餘 mangled 未清零 |
| W-PDB-1 | `/DEBUG`＋`/PDBALTPATH:` 短中性名已見於 PE |
| W-VER-1 | exe＋DLL VERSIONINFO 中性 |

---

## 3. Follow-ups

1. ~~**5.3** export=1~~ → **Done 2026-07-17**（`dumpbin` = `slicer_run_cli` only）。  
2. ~~**5.6／5.7** consumer harness OFF~~ → **Done**（Win package／scan gate）。  
3. ~~Agent／Launcher 路徑~~ → **Done 2026-07-19**（Win＋mac §4；見 [`PROGRESS.md`](../PROGRESS.md)）。  
4. LocalDumps HKCU 未穩定產出 dump；本 PoC 以 `cdb` 取 dump（exit code 已證明三種 native 失敗）。正式 §7 可用同等取證。  
5. ~~Authenticode／install lifecycle~~ → **Done 2026-07-19／20**（Setup Valid＋lifecycle＋reinject **EV**；見 [`PROGRESS.md`](../PROGRESS.md)）。~~§7／CLI help／mac 4.6／mac QA／mac 5.11／6.x／5.1b~~ → **已關**；可選僅 **8.6**／QA 重配對。

---

## 4. 重跑

```bat
scripts\build_prusaslicer_fork_windows.bat low
powershell -File openspec\changes\backend-slicer-engine-deidentification\poc\run_w25_close.ps1
```

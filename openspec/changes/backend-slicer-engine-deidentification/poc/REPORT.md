# macOS PoC Report — rename + strip + three crash sites

**日期：** 2026-07-17  
**Change：** `backend-slicer-engine-deidentification`  
**任務：** tasks.md **2.4 — 關閉**  
**權威 close run：** [`evidence/m1-close-20260717T032408Z/`](./evidence/m1-close-20260717T032408Z/)（scanner **PASS**）

---

## 0. 結論（M1／2.4）

| 目標 | 結果 |
|------|------|
| L1 檔名／`procName`／`codeSigningID` | **達標** → `slicer-engine` |
| Thread 名去品牌 | **達標** → `slicer-worker`（`slic3r_main`=0） |
| 三種 crash 皆產出 `.ips` | **達標**（overflow／segfault／exception） |
| L2 可讀堆疊無 `Slic3r::` | **達標（乾淨符號環境）** |
| Scanner 原型 | **PASS**（`poc/scan_macos_artifact.sh`） |
| `strip -x` 當 L2 充分條件 | **否決** |
| plain `strip` alone | **不足**（須 visibility；且須無同 UUID dSYM／符號快取） |

**定案 flags（macOS CLI PoC）：**  
`-fvisibility=hidden -fvisibility-inlines-hidden`（`libslic3r` + `PrusaSlicer`）→ 產 dSYM 封存 → plain `strip` → `codesign --identifier slicer-engine`。

**驗收環境硬條件：** consumer 崩潰當下不得存在**同 UUID** 的未 strip 複本或可被 Spotlight／CoreSymbolication 找到的 dSYM；本機重複 PoC 若 UUID 未變，ReportCrash 可能從快取還原舊符號（見 §7）。close 腳本以 **LC_UUID patch** 隔離此污染（僅 PoC；正式包靠「不發佈 dSYM + 新 build UUID」即可）。

---

## 1. PoC 做了什麼

| 步驟 | 結果 |
|------|------|
| CMake `OUTPUT_NAME=slicer-engine`（Apple） | ✅ |
| `codesign --identifier slicer-engine` | ✅ |
| Visibility flags（Apple targets） | ✅ 見 fork `CMakeLists.txt` |
| Crash harness 三種 mode | ✅ `BUNDLE_QA_CRASH_MODE=…`（**已改** compile-time `BUNDLE_QA_CRASH_HARNESS`；見 2.5／2.6／`REPORT-WIN.md`） |
| Exception → `.ips` | ✅ `noexcept` lambda 強制 terminate／abort（exit 134） |
| Thread 字串中性化 + 重編 | ✅ |
| 靜態 `nm` + 動態 `.ips` + scanner | ✅ close run PASS |

腳本：`poc/run_macos_poc.sh`、`poc/run_m1_close.sh`、`poc/scan_macos_artifact.sh`

---

## 2. 靜態符號

| Binary | `nm -gU` brand | `nm -U` brand |
|--------|----------------|---------------|
| 未 strip（改名後） | ~4959 → visibility 後 **933** | （高） |
| `strip -x` only | ≈不動 global | — |
| **visibility + plain `strip`** | **172** | **172** |

殘餘 ~172 多為 template／boost 具體化等仍為 global 的 mangled 名（含 `Slic3r` 子字串）。**本 close run 的三種 crash 堆疊未解析出 `Slic3r::`**；殘餘屬 §5／2.2 後續收斂（更嚴 export／strip），不阻擋 M1 關閉。

---

## 3. 動態 `.ips`（close run）

證據：`evidence/m1-close-20260717T032408Z/`

| Mode | `.ips` | procName / codeSigningID | `Slic3r::` | `slic3r_main` | threads |
|------|--------|--------------------------|------------|---------------|---------|
| overflow | ✅ | `slicer-engine` | **0** | 0 | `slicer-engine`／`slicer-worker` |
| segfault | ✅ | `slicer-engine` | **0** | 0 | 同上 |
| exception | ✅ | `slicer-engine` | **0** | 0 | 同上 |

Scanner：`SCAN.json` → **verdict PASS**。

對照（污染環境）：同 UUID + 可發現 dSYM 時，堆疊會再出現 `Slic3r::bundle_force_*`／`SLAPrint::process` 等（見較早 `m1-close-20260717T031801Z`，**FAIL**）——屬符號環境問題，非改名失敗。

---

## 4. 與接受線對照

| 目標 | 狀態 |
|------|------|
| L1 | **PoC 達標** |
| L2 可讀 `Slic3r::`／品牌 thread | **PoC 達標**（visibility＋strip＋乾淨 UUID／無 dSYM） |
| 三種 crash site | **達標** |
| runtime harness 進正式包 | **否** — 僅 PoC |
| 全面 `Slic3r::`→`slice::`／OLLVM | **L3，不做** |

---

## 5. 產物與路徑

| 項目 | 路徑 |
|------|------|
| 建置產物 | `web_slicer_core/third_party/prusaslicer_build/src/slicer-engine` |
| Visibility | `prusaslicer_fork/src/libslic3r/CMakeLists.txt`、`…/src/CMakeLists.txt` |
| Harness | `prusaslicer_fork/src/libslic3r/SLAPrint.cpp`（後續移出熱點） |
| Close 證據 | `poc/evidence/m1-close-20260717T032408Z/` |
| Thread 單獨驗證 | `poc/evidence/thread-verify-20260717T031014Z/` |

---

## 6. Follow-ups（M1 之後，不阻擋 2.4）

1. ~~**2.2／5.1 流水線＋nm 收斂**~~ → **Done（2026-07-17 夜）** `package_slicer_engine_macos.sh`；arrange／wrapper visibility＋`-exported_symbol,_main`；consumer **nm brand 0**。  
2. ~~**Harness compile-time 化**~~ **Done（2.6 PoC）** — `BUNDLE_QA_CRASH_HARNESS`／`bundle_qa_crash_probe`；consumer OFF → **5.6**。  
3. ~~**Windows baseline／PoC**~~ **Done（1.7／2.5）** — 見 `BASELINE.md`／`REPORT-WIN.md`。  
4. **正式包：** 永不附 dSYM／PDB；符號庫 ACL／retention（D12／5.5）；Launcher §4。

---

## 7. 符號污染教訓（寫入驗收）

1. `strip -x` ≠ L2。  
2. 同 UUID 的 dSYM／未 strip 複本 → ReportCrash 仍可寫出 `Slic3r::`。  
3. 僅 `mdfind` 清零仍可能因 **CoreSymbolication 快取** 還原舊符號 → PoC 以 **UUID patch** 證明「strip 後堆疊可無品牌名」；產品流程用新 build UUID + 不發佈 dSYM。

---

## 8. Thread 名（摘要）

重編後 `.ips` thread = `slicer-worker`；**無需加密**。證據：`thread-verify-20260717T031014Z`。

---

## 9. 狀態一句話

**M1／tasks 2.4 已關閉：改名＋visibility＋strip＋三種 crash `.ips`＋scanner PASS；L2 在乾淨符號環境下成立。**

# Notion Task — Windows PoC（tasks 2.5＋compile-time harness）

> 複製下方「可貼區塊」全文到 Notion Test task（可取代 Untitled／由 2.3 模板改寫的新頁）。  
> 對應 OpenSpec：`backend-slicer-engine-deidentification`／tasks **2.5**（＋**2.6** PoC）  
> 權威證據：`poc/evidence/w25-close-20260717T083241Z/`  
> 報告：`poc/REPORT-WIN.md`  
> 政策依據：`windows-policy.md`（tasks **2.3** already decided）

---

## 可貼區塊（由此開始）

### Test 測試

**標題：** Windows 去識別 PoC（rename／VERSIONINFO／exports／PDBALTPATH／三種 crash）

**狀態建議：** 通過／Done  
**測試日期：** 2026-07-17  
**平台／Arch：** Windows NT 10.0.26200.0／x64  
**執行人：** Backend（PoC）

---

## 測試原因及目的（建立人填寫）

依 OpenSpec tasks **2.5**（REQ-DEID-006；前置 **2.3** 政策已定案），在 Windows 上**實際改碼＋重編＋取證**，驗證政策是否真的生效：

1. **DLL／shim ABI：** `slicer-engine.exe` → 同目錄載入 `slicer_core.dll` → 只解析 `slicer_run_cli`（取代 `PrusaSlicer.dll`／`slic3r_main`）。
2. **Export 入口：** 公開入口改為 `slicer_run_cli`；`slic3r_main` 必須消失（**完整收斂為恰好 1 個 export 屬 5.3**，本 PoC 允許記錄殘餘 mangled）。
3. **PDB／Debug directory：** 顯式 `/Zi`＋`/DEBUG`＋`/PDB:`＋**`/PDBALTPATH:`** 短中性名；PE 內不得再出現 `prusaslicer_build\...\*.pdb` 路徑。
4. **VERSIONINFO：** exe＋DLL 皆有中性 Company／Product（不得再空 DLL）。
5. **三種 QA crash：** overflow／segfault／exception（**compile-time** `BUNDLE_QA_CRASH_HARNESS`）；minidump 模組名無 `PrusaSlicer`。

**非目的：** 不驗證 Authenticode 最終 installer、不做 Bundle-Launcher 正式組包、不宣告正式產品 L1+L2 PASS（屬 §3／§5／§7）、不要求 LocalDumps 必自動出 dump（可用 `cdb` 等價取證）、不要求本輪就把 export 清到恰好 1（→ **5.3**）、不做 consumer `HARNESS=OFF` 靜態零殘留稽核（→ **5.6／5.7**）。

---

## 測試背景（建立人填寫）

| **前端網址** | **N/A（本測試僅後端 CLI／PE／minidump；無前端）** |
| --- | --- |
| 後端版本 | QA fork：`slicer-engine.exe`＋`slicer_core.dll`（`BUNDLE_QA_CRASH_HARNESS=ON`，`SLIC3R_GUI=OFF`，VS2022 Release） |
| OpenSpec change | `web_slicer_core/openspec/changes/backend-slicer-engine-deidentification/` |
| 對應 task | tasks.md **2.5**（已關閉／PASS）；**2.6** PoC（compile-time harness 已落地） |
| 前置依賴 | tasks **1.7** baseline PASS；**2.3** `windows-policy.md` Status=`decided`；naming-manifest approved |
| 對照 baseline | `evidence/windows/baseline/win-baseline-20260717T055632Z/`（品牌指紋對照） |
| 權威 evidence | `poc/evidence/w25-close-20260717T083241Z/` |
| 定案／報告 | `windows-policy.md`（政策）＋ **`poc/REPORT-WIN.md`**（本 PoC） |
| OS／工具 | Windows 10.0.26200 x64；VS2022 `dumpbin`；Windows SDK `cdb`；HKCU LocalDumps（輔助） |
| 產物路徑 | `web_slicer_core/third_party/prusaslicer_build/src/Release/` |
| 同步回寫 | `tasks.md` 2.5／2.6、`PROGRESS.md`、`FILE-INDEX`、`traceability`、`crash-harness-forensics`、Launcher `.openspec.yaml` |

**對照 baseline → PoC（要消掉的東西 vs 實際結果）：**

| **表面** | **1.7 觀測（before）** | **2.5 PoC（after）** |
| --- | --- | --- |
| ABI | `prusa-slicer-console`＋`PrusaSlicer.dll`；loader：`PrusaSlicer.dll was not loaded` | `slicer-engine.exe`＋`slicer_core.dll`＋`slicer_run_cli` |
| Export 入口 | 含 `slic3r_main` | `slicer_run_cli` 存在；`slic3r_main` **已消失** |
| Export 數量 | 470 named | 仍 ≈470 cereal mangled（**未達「恰好 1」** → 5.3） |
| PDB path | `...\prusaslicer_build\...\prusa-slicer-console.pdb` | RSDS=`slicer-engine.pdb`／`slicer_core.pdb`（無建置樹路徑） |
| VERSIONINFO | exe 全品牌；DLL 空 | Company=`Phrozen Technology`；Product=`Slicer Engine`（exe＋DLL） |
| QA harness | 無 runtime crash mode | compile-time harness；三種 mode 皆可崩 |

---

## 測試範圍（建立人填寫）

- 測
    - 改名後檔名／LoadLibrary／GetProcAddress（`slicer_run_cli`）
    - VERSIONINFO（exe＋DLL）中性欄位
    - `dumpbin /exports`：入口名；記錄殘餘 export 數
    - PE debug directory／RSDS：`/PDBALTPATH:` 短中性名
    - 三種 crash：`BUNDLE_QA_CRASH_MODE=overflow|segfault|exception` 的 exit code＋minidump
    - PDB-free stack：模組名是否仍見 `PrusaSlicer`
    - compile-time harness（非 SLAPrint runtime）
- 不測
    - export 清到恰好 1（→ **5.3**）
    - consumer `BUNDLE_QA_CRASH_HARNESS=OFF` 零殘留（→ **5.6／5.7**）
    - Authenticode 最終 installer
    - Bundle-Launcher 正式組包／公證
    - macOS（已由 2.4 覆蓋）
    - L3（全面 namespace／OLLVM／packer）
    - AGPL Legal 簽核（1.6）

---

## 測試結果追蹤

### **總結**

| **項目** | **結果** | **備註** |
| --- | --- | --- |
| 整體 verdict | **PASS（PoC）** | tasks **2.5 關閉**；可進 §3／§5 |
| ABI／改名 | **達標** | `slicer-engine.exe`→`slicer_core.dll`→`slicer_run_cli` |
| VERSIONINFO | **達標** | 中性；DLL 不再空 |
| PDBALTPATH／RSDS | **達標** | 短中性名；無 `prusaslicer_build` 路徑 |
| 三種 crash | **達標** | overflow／segfault／exception 皆失敗 exit＋dump |
| Minidump 模組名 | **達標** | `slicer_engine`／`slicer_core`（無 PrusaSlicer） |
| Export 入口更名 | **達標** | `slic3r_main` 已消失 |
| Export 收斂為 1 | **未達（已知）** | 仍 ≈470 → **5.3** |
| LocalDumps 自動 dump | **未穩定** | 以 `cdb` 取 dump；exit 已證明崩潰 |
| Go／No-go | **Go → §3／§5** | 產品化；export=1 另追 5.3 |

### **三種 crash 結果**

| **Mode** | **Exit** | **Dump** | **白話** |
| --- | --- | --- | --- |
| overflow | `0xC00000FD` | `overflow.dmp` | 堆疊溢位，有崩 |
| segfault | `0xC0000005` | `segfault.dmp` | 空指標存取違規，有崩 |
| exception | `0xC0000409` | `exception.dmp` | C++ 例外後終止，有崩 |

### **證據／文件索引**

| **檔案** | **說明** |
| --- | --- |
| `poc/REPORT-WIN.md` | **權威 PoC 報告** |
| `poc/evidence/w25-close-20260717T083241Z/SUMMARY.md` | 本次 run 摘要 |
| `…/static/VERSIONINFO.txt`、`EXPORT_SUMMARY.txt`、`HEADERS_*.txt` | 靜態 PE 證據 |
| `…/dumps/*.dmp`＋`HASHES.txt` | 三種 crash dump（~85MB；**勿 commit git**） |
| `windows-policy.md` | 2.3 政策（本 PoC 的驗收尺） |
| `tasks.md` 2.5／2.6 | `[x]` 關閉 |
| `PROGRESS.md` §2d | PoC 摘要＋下一步 |
| Launcher `.openspec.yaml` | `resolved_gates: windows-poc-l2-evidence` |

**Artifacts hash：**

- exe `62A7F4B55C83C8424070A8175E92205D66CE0CA1426B1B64A3E839DD470F9EA0`
- dll `A16577A2EE24D4C71585CC93FA7106FCA8A4C39893A37376D7F1B06CEE251DC9`

### **已知限制／Follow-up**

1. **Export 仍 ≈470**（cereal mangled）— 政策要「恰好 1」；本 PoC **只保證入口正確**，完整收斂 → **5.3**。
2. LocalDumps 未穩定自動產 dump；本輪用 **cdb** 取證（三種 native 失敗 exit 仍成立）。
3. Consumer 建置須 `BUNDLE_QA_CRASH_HARNESS=OFF`；零 harness 靜態稽核 → **5.6／5.7**。
4. DLL `OriginalFilename` 目前與 exe 共用 rc（產品化可拆）。
5. Agent／Launcher 正式路徑 `slicer-engine/`、簽署包 → §3／§4／§7。

### **測試結果追蹤（勾選）**

- [x]  ABI／shim／DLL 改名落地並可執行
- [x]  VERSIONINFO exe＋DLL 中性
- [x]  PDBALTPATH／RSDS 短中性名（無建置樹路徑）
- [x]  `slicer_run_cli` 存在且 `slic3r_main` 消失
- [x]  三種 crash（overflow／segfault／exception）＋dump／失敗 exit
- [x]  Minidump 模組名無 `PrusaSlicer`
- [x]  compile-time harness（移出 SLAPrint）
- [x]  寫入 `REPORT-WIN.md`＋evidence；回寫 tasks／PROGRESS／Launcher
- [x]  tasks 2.5 關閉
- [ ]  Export 收斂為恰好 1（→ **5.3**，不擋本 task Done）
- [ ]  Consumer OFF harness 稽核（→ **5.6／5.7**）
- [ ]  Authenticode／Launcher 正式組包（→ §4／§7）

> **關閉判定：** 上列必做項完成 → **Done／PASS（PoC）**。  
> Export=1、consumer OFF、正式簽署包 **不屬本 task 通過條件**。

---

## （可選）若仍要改「舊的 2.3 政策 Notion」Follow-up 區塊

把原本「Go → 2.5／尚未改碼」改成：

> **後續狀態（2026-07-17）：** tasks **2.5 PASS** — 見 `poc/REPORT-WIN.md`／Notion「Windows 去識別 PoC」。本 2.3 頁仍只負責政策定案，不必重開。

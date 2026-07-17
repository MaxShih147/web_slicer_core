# Notion Task — Windows 政策定案＋PoC（tasks 2.3／2.5）

> 複製下方「可貼區塊」全文到 Notion Test task（標題見下）。  
> OpenSpec：`backend-slicer-engine-deidentification`  
> 政策：`windows-policy.md`（2.3）｜PoC：`poc/REPORT-WIN.md`（2.5）｜Evidence：`poc/evidence/w25-close-20260717T083241Z/`

---

## 可貼區塊（由此開始）

### Test 測試

**標題：** Windows 政策定案＋PoC（2.3／2.5：VERSIONINFO／exports／WER／三種 crash）

**狀態建議：** 通過／Done  
**測試日期：** 2026-07-17  
**平台／Arch：** Windows NT 10.0.26200.0／x64  
**執行人：** Backend（政策＋PoC）

---

## 測試原因及目的（建立人填寫）

本 Test 合併兩階段，一次收尾 Windows 去識別的「定規則＋真的做出來」：

### A. tasks **2.3** — 政策定案（文件／簽核）

依 REQ-DEID-006／012，在改碼前定案並文件化：

1. **DLL／shim ABI：** `slicer-engine.exe` → 同目錄載入 `slicer_core.dll` → 只解析 `slicer_run_cli`（取代 `PrusaSlicer.dll`／`slic3r_main`）。
2. **Export 收斂：** consumer 公開 export **唯一**為 `slicer_run_cli`；否決「只改名、留下 ~470 個 `Slic3r` mangled exports」（1.7 baseline 現況）。
3. **PDB 流水線：** 顯式產 PDB（`/Zi`＋`/DEBUG`＋`/PDB:`）→ 內部封存 → consumer **無 `.pdb`**。
4. **Debug directory：** 使用 **`/PDBALTPATH:`** 短中性檔名；否決「只 `/XF *.pdb`」（baseline 已證仍會洩漏 `prusaslicer_build\...\*.pdb` 路徑）。
5. **原子遷移／VERSIONINFO：** shim＋DLL＋agent＋錯誤字串＋exe／DLL VERSIONINFO 同變更集；DLL VERSIONINFO 不得再空。

### B. tasks **2.5** — PoC 實作＋實驗室取證

依 2.3 政策實際改碼、重編 QA flavor，並驗證：

1. VERSIONINFO（exe＋DLL）中性落地。  
2. Export 入口更名（`slicer_run_cli`；`slic3r_main` 消失）；殘餘 mangled 數記錄並移交 **5.3**。  
3. PDBALTPATH／RSDS 短中性名（無建置樹路徑）。  
4. 三種 QA crash（overflow／segfault／exception）＋minidump／WER 對等取證。  
5. compile-time `BUNDLE_QA_CRASH_HARNESS`（非 runtime-only；移出 SLAPrint）。

**非目的（整份 Test 都不做）：** Authenticode 最終 installer、Bundle-Launcher 正式組包／公證、宣告正式產品 L1+L2 PASS（屬 §3／§5／§7）、export 清到恰好 1（→ **5.3**）、consumer `HARNESS=OFF` 靜態零殘留（→ **5.6／5.7**）、macOS／L3／AGPL Legal（1.6）。

---

## 測試背景（建立人填寫）

| **前端網址** | **N/A（政策＋後端 CLI／PE／minidump；無前端）** |
| --- | --- |
| OpenSpec change | `web_slicer_core/openspec/changes/backend-slicer-engine-deidentification/` |
| 對應 task | **2.3**（政策 `decided`）＋**2.5**（PoC PASS）＋**2.6** PoC（compile-time harness） |
| 前置依賴 | **1.7** baseline PASS；naming-manifest／artifact-manifest.schema **approved** |
| Baseline 產物（before） | `prusa-slicer-console.exe`／`PrusaSlicer.dll`（`PrusaSlicer-2.9.4+UNKNOWN`） |
| PoC 產物（after） | `slicer-engine.exe`／`slicer_core.dll`（`BUNDLE_QA_CRASH_HARNESS=ON`，`SLIC3R_GUI=OFF`，VS2022 Release） |
| 政策產出 | **`windows-policy.md`**（Status=`decided`，2026-07-17） |
| PoC 報告 | **`poc/REPORT-WIN.md`** |
| Baseline 證據 | `evidence/windows/baseline/win-baseline-20260717T055632Z/`、`BASELINE.md` |
| PoC 證據 | `poc/evidence/w25-close-20260717T083241Z/` |
| OS／工具 | Windows 10.0.26200 x64；VS2022 `dumpbin`；Windows SDK `cdb`；HKCU LocalDumps（輔助） |
| 同步回寫 | `design.md` D10、`tasks.md`、`PROGRESS.md`、`naming-manifest.md`、`acceptance-procedure.md`、checklist、traceability、`crash-harness-forensics.md`、Launcher `.openspec.yaml` |

**Before → After（關鍵表面）：**

| **表面** | **1.7 baseline（before）** | **2.5 PoC（after）** |
| --- | --- | --- |
| ABI | `prusa-slicer-console`＋`PrusaSlicer.dll`；loader：`PrusaSlicer.dll was not loaded` | `slicer-engine.exe`＋`slicer_core.dll`＋`slicer_run_cli` |
| Export 入口 | 含 `slic3r_main` | `slicer_run_cli`=True；`slic3r_main`=False |
| Export 數量 | 470 named | 仍 ≈470 cereal mangled（**未達恰好 1** → 5.3） |
| PDB／RSDS | `...\prusaslicer_build\...\prusa-slicer-console.pdb` | `slicer-engine.pdb`／`slicer_core.pdb`（無建置樹路徑） |
| VERSIONINFO | exe 全品牌；DLL 空 | Company=`Phrozen Technology`；Product=`Slicer Engine`（exe＋DLL） |
| QA harness | 無 runtime crash mode | compile-time harness；三種 mode 皆可崩 |
| Minidump 模組 | 品牌模組名 | `slicer_engine`／`slicer_core`（無 `PrusaSlicer`） |

---

## 測試範圍（建立人填寫）

### 測（2.3 政策）

- DLL／shim 載入契約（檔名、同目錄 LoadLibrary、GetProcAddress 名、錯誤文案）
- 公開 export 目標態（唯一 `slicer_run_cli`）與對 baseline 470 的收斂手段（`.def` 或等效）
- PDB：`/Zi`＋`/DEBUG`＋`/PDB:`＋`/PDBALTPATH:`；產→封存→consumer 排除
- PE debug directory 不得含品牌／建置樹路徑（否決只刪 pdb）
- VERSIONINFO（exe＋DLL）中性欄位對齊 naming-manifest
- 原子遷移順序與 2.5／§3／§5 分界、scanner／CI FAIL 條件
- 與 D10／D13／artifact-manifest 語意對齊

### 測（2.5 PoC）

- CMake／shim／DLL 實際改碼與 QA 重編
- VERSIONINFO 實測（FileVersionInfo）
- `dumpbin /exports`／`/HEADERS`（入口名＋RSDS）
- 三種 crash：`BUNDLE_QA_CRASH_MODE=overflow|segfault|exception` 的 exit＋minidump
- PDB-free stack／模組名中性化
- compile-time harness（`bundle_qa_crash_probe`；非 SLAPrint runtime）

### 不測

- Authenticode 最終 installer 驗收
- macOS／Launcher 正式組包
- Export 清到恰好 1（→ **5.3**）
- Consumer `BUNDLE_QA_CRASH_HARNESS=OFF` 零殘留（→ **5.6／5.7**）
- L3（全面 namespace／OLLVM／packer）
- AGPL Legal 簽核（1.6）
- 正式產品 L1+L2 PASS 宣告（→ §7）

---

## 測試結果追蹤

### **總結（整份 Test）**

| **項目** | **結果** | **備註** |
| --- | --- | --- |
| 整體 verdict | **PASS** | **2.3 定案＋2.5 PoC** 皆關閉 |
| 2.3 政策 | **PASS／decided** | 權威：`windows-policy.md` |
| 2.5 PoC | **PASS** | 權威：`poc/REPORT-WIN.md` |
| VERSIONINFO | **達標（PoC）** | 中性；DLL 不再空 |
| Export 入口 | **達標（PoC）** | `slicer_run_cli`；無 `slic3r_main` |
| Export＝恰好 1 | **未達（已知）** | ≈470 residual → **5.3** |
| PDBALTPATH／RSDS | **達標（PoC）** | 短中性名；無 `prusaslicer_build` |
| 三種 crash＋dump | **達標（PoC）** | overflow／segfault／exception |
| WER／LocalDumps | **部分** | HKCU 未穩定自動 dump；以 **cdb** 取證（exit 已證崩潰） |
| Compile-time harness | **達標** | `BUNDLE_QA_CRASH_HARNESS`（2.6 PoC） |
| Go／No-go | **Go → §3／§5** | 產品化；export=1／consumer OFF 另追 |

---

### **階段一：2.3 政策定案結果**

| **項目** | **結果** | **備註** |
| --- | --- | --- |
| ABI 契約 | **已定案** | `slicer-engine.exe`→`slicer_core.dll`→`slicer_run_cli` |
| Export 收斂政策 | **已定案** | consumer export 數＝1；否決只改 `slic3r_main` |
| PDB 產→封存→排除 | **已定案** | 顯式 `/DEBUG`＋`/PDB:`；先封存再交付 |
| Debug directory | **已定案** | **`/PDBALTPATH:`** 短中性名；否決只 XF |
| VERSIONINFO 政策 | **已定案** | exe＋DLL 皆必填中性欄位 |
| 原子遷移 | **已定案** | 禁止半套上線 |

#### 定案對照表（W-*）

| **ID** | **決策** | **2.5 PoC 落地？** |
| --- | --- | --- |
| W-ABI-1 | 單一 shim＋`slicer_core.dll`＋唯一 export `slicer_run_cli` | **ABI／入口已落地**；「唯一」數量 → 5.3 |
| W-ABI-2 | 原子遷移；呼叫簽名語意不變、僅更名 | PoC 變更集含 shim／DLL／VERSIONINFO／loader 字串 |
| W-EXP-1 | Export 收斂為 1；否決只改名留下 mangled | **政策仍成立**；PoC 未完成清零 → 5.3 |
| W-PDB-1 | `/Zi`＋`/DEBUG`＋`/PDB:`＋`/PDBALTPATH:` | **已證** RSDS 短中性名 |
| W-PDB-2 | 否決只 XF pdb；先封存再 consumer | 政策有效；正式 consumer 排除 → §5 |
| W-VER-1 | DLL VERSIONINFO 不得再空 | **已達標** |

---

### **階段二：2.5 PoC 實驗室結果（完整）**

#### 靜態（VERSIONINFO／exports／PDB）

| **檢查項** | **結果** | **證據** |
| --- | --- | --- |
| 檔名 | `slicer-engine.exe`／`slicer_core.dll` | Release 產物 |
| VERSIONINFO Company | `Phrozen Technology` | `static/VERSIONINFO.txt` |
| VERSIONINFO Product | `Slicer Engine` | 同上 |
| Export `slicer_run_cli` | **True** | `static/EXPORT_SUMMARY.txt` |
| Export `slic3r_main` | **False（已消失）** | 同上 |
| named_exports_approx | **≈470**（cereal residual） | 同上 → **5.3** |
| RSDS／PDBALTPATH | `slicer-engine.pdb`／`slicer_core.pdb` | `static/HEADERS_*.txt` |
| 建置樹路徑洩漏 | **無** | 同上 |

**Artifacts sha256：**

| 檔案 | sha256 |
| --- | --- |
| `slicer-engine.exe` | `62A7F4B55C83C8424070A8175E92205D66CE0CA1426B1B64A3E839DD470F9EA0` |
| `slicer_core.dll` | `A16577A2EE24D4C71585CC93FA7106FCA8A4C39893A37376D7F1B06CEE251DC9` |

#### 動態（三種 crash＋WER／dump）

| **Mode** | **Exit code** | **Dump** | **白話** |
| --- | --- | --- | --- |
| overflow | `0xC00000FD` | `dumps/overflow.dmp` | 堆疊溢位，有崩 |
| segfault | `0xC0000005` | `dumps/segfault.dmp` | 空指標存取違規，有崩 |
| exception | `0xC0000409` | `dumps/exception.dmp` | C++ 例外後終止，有崩 |

| **取證面** | **結果** |
| --- | --- |
| Minidump 模組名 | `slicer_engine`＋`slicer_core`（**無** `PrusaSlicer`） |
| Stack 入口符號（segfault） | `slicer_core!slicer_run_cli+…`（**無** `slic3r_main`） |
| LocalDumps（HKCU） | **未穩定**自動產出 → 本 PoC 以 **cdb** 寫入同目錄 dump |
| Dump 大小／hash | 各約 85MB；見 `dumps/HASHES.txt`（**勿 commit 至 git**） |

#### Harness

| **項目** | **結果** |
| --- | --- |
| Flag | CMake `BUNDLE_QA_CRASH_HARNESS=ON`（QA only） |
| 實作 | `bundle_qa_crash_probe.cpp`；CLI 入口呼叫 |
| 舊 runtime（SLAPrint） | **已移除** |
| Mode 環境變數 | `BUNDLE_QA_CRASH_MODE`（僅 QA binary 內有效） |

---

### **證據／文件索引**

| **檔案** | **說明** |
| --- | --- |
| `windows-policy.md` | **2.3 權威定案**（Status=`decided`） |
| `poc/REPORT-WIN.md` | **2.5 權威 PoC 報告** |
| `poc/evidence/w25-close-20260717T083241Z/SUMMARY.md` | PoC run 摘要 |
| `…/static/VERSIONINFO.txt`、`EXPORT_SUMMARY.txt`、`HEADERS_*.txt` | VERSIONINFO／exports／RSDS |
| `…/dumps/*.dmp`＋`HASHES.txt` | 三種 crash dump（內部存放） |
| `evidence/windows/baseline/BASELINE.md` | 1.7 現況指紋（before） |
| `design.md` D10 | 已回寫 Win PDB／export 政策 |
| `tasks.md` 2.3／2.5／2.6 | 皆 `[x]` 關閉（2.6＝PoC 部分） |
| `PROGRESS.md` §2c／§2d | 政策＋PoC 摘要 |
| Launcher `.openspec.yaml` | `windows-abi-pdb-export-policy`＋`windows-poc-l2-evidence` resolved |

---

### **已知限制／Follow-up**

1. **Export 仍 ≈470** — 政策要求恰好 1；本 Test **入口已正確**，完整清零 → **5.3**。  
2. LocalDumps 未穩定自動存檔；崩潰本身已由 **非零 exit＋cdb dump** 證明。  
3. Consumer 必須 `BUNDLE_QA_CRASH_HARNESS=OFF`；零 harness 稽核 → **5.6／5.7**。  
4. DLL `OriginalFilename` 目前與 exe 共用 rc 模板（產品化可拆）。  
5. Agent／Launcher 正式路徑 `slicer-engine/`、簽署包 → §3／§4／§7。  
6. 本 Test **不**宣告正式產品 L1+L2 PASS。

---

### **測試結果追蹤（勾選）**

#### 2.3 政策

- [x] ABI／shim／DLL／export 契約定案
- [x] PDB 產→封存→consumer 排除定案
- [x] Debug directory／`PDBALTPATH` 定案
- [x] 否決「只 XF pdb」「只改 slic3r_main」
- [x] VERSIONINFO＋原子遷移順序定案
- [x] 寫入 `windows-policy.md`
- [x] 回寫 design／tasks／PROGRESS／checklist／Launcher metadata
- [x] tasks 2.3 關閉

#### 2.5 PoC

- [x] 改名／ABI 落地（`slicer-engine.exe`／`slicer_core.dll`／`slicer_run_cli`）
- [x] VERSIONINFO exe＋DLL 中性實測
- [x] PDBALTPATH／RSDS 短中性名實測
- [x] Export 入口更名（`slic3r_main` 消失）
- [x] 三種 crash（overflow／segfault／exception）＋dump／失敗 exit
- [x] Minidump 模組名無 `PrusaSlicer`
- [x] compile-time harness（移出 SLAPrint）
- [x] 寫入 `REPORT-WIN.md`＋evidence；回寫 OpenSpec／Launcher
- [x] tasks 2.5 關閉
- [ ] Export 收斂為恰好 1（→ **5.3**，不擋本 Test Done）
- [ ] Consumer OFF harness 稽核（→ **5.6／5.7**）
- [ ] Authenticode／Launcher 正式組包（→ §4／§7）

> **關閉判定：** 2.3 定案＋2.5 PoC 必做項完成 → **Done／PASS**。  
> Export=1、consumer OFF、正式簽署包 **不屬本 Test 通過條件**。  
> **白話結論：** 政策寫清楚了，也真的做出「改名／版本資訊／PDB 路徑中性／三種可崩潰取證」；唯一還沒做完的是「DLL 只剩 1 個 export」，已排進後續 5.3。

# Notion Task — Windows 崩潰 baseline（tasks 1.7）

> 複製下方「可貼區塊」全文到 Notion Test task。  
> 對應 OpenSpec：`backend-slicer-engine-deidentification`／tasks **1.7**  
> 權威證據：`web_slicer_core/openspec/changes/backend-slicer-engine-deidentification/evidence/windows/baseline/win-baseline-20260717T055632Z/`

---

## 可貼區塊（由此開始）

### Test 測試

**標題：** Windows 崩潰 baseline 收集（WER／minidump 現況指紋）

**狀態建議：** 通過／Done  
**測試日期：** 2026-07-17  
**平台／Arch：** Windows NT 10.0.26200.0／x64  
**執行人：** Backend（baseline）

---

## 測試原因及目的（建立人填寫）

依 OpenSpec `acceptance-procedure.md` **§5.1**，在 Windows L2／去識別實作開始前，保存**目前正式包（consumer-like unpack）**在診斷表面上的品牌指紋，作為後續 2.3 政策定案與 2.5 PoC 的對照基準。

須涵蓋：

1. **L1 現況：** process 名、module 完整路徑、VERSIONINFO、shim loader 可見錯誤。  
2. **L2 現況：** PE export（尤其 `slic3r_main`／`Slic3r` mangled）、PE debug／PDB path、WER／LocalDumps 設定下的 minidump 模組名與可讀 stack 表面。  
3. **手段確認：** 本 Windows 建置是否具備 runtime QA crash harness（`BUNDLE_QA_CRASH_MODE`）。

**非目的：** 不驗證去識別後 L1+L2 PASS、不做三種 QA crash site PoC、不驗證 Authenticode 最終 installer／Bundle-Launcher 公證包、不以攔截 WER 作為通過條件。

---

## 測試背景（建立人填寫）

| 前端網址 | N/A（本測試僅後端 CLI／WER／minidump／PE 靜態；無前端） |
| --- | --- |
| 後端版本 | Bundle-Launcher `dist/win-unpacked` 內引擎：`prusa-slicer-console.exe`／`prusa-slicer.exe`／`PrusaSlicer.dll`（`PrusaSlicer-2.9.4+UNKNOWN`） |
| OpenSpec change | `web_slicer_core/openspec/changes/backend-slicer-engine-deidentification/` |
| 對應 task | tasks.md **1.7**（已關閉） |
| 驗收條款 | `acceptance-procedure.md` §5.1；黑名單 `blacklist.md` §3.3／3.4 |
| 命名簽核（目標名，非本 baseline 產物） | `slicer-engine.exe`／`slicer_core.dll`／`slicer_run_cli`（naming-manifest approved） |
| OS | Windows NT 10.0.26200.0，x64 |
| 工具 | VS 2022 `dumpbin` 14.29；Windows SDK `cdb` 10.0.22621；HKCU LocalDumps |
| 產物來源 | `Bundle-Launcher/dist/win-unpacked/resources/bundle/third_party/prusaslicer_build/src/Release/` |
| 權威 evidence | `evidence/windows/baseline/win-baseline-20260717T055632Z/`（captured_at_utc `2026-07-17T05:56:32Z`） |
| 乾淨環境 | `_NT_SYMBOL_PATH` 空；未注入私有 PDB；分析時 `.sympath` 清空（MS public `srv*` 仍可能解析 ntdll） |

**產物 sha256：**

| 檔案 | sha256 | bytes |
| --- | --- | ---: |
| `prusa-slicer-console.exe` | `92F40FD062505FD5494848B0FA22E1484547958076906A5F36DDFA5B89F458DE` | 134144 |
| `prusa-slicer.exe` | `63B53B12772E5C446622BEB517AB06210337682E697B4A1CC8189B70F9AE407E` | 134144 |
| `PrusaSlicer.dll` | `DD998AC8524AB89DC05B1F0DCDB46279BFA5A0B41C80B5CF093AC84ADD55521F` | 16932864 |

**測試過程（摘要）：**

1. 靜態：PATH 清點、VERSIONINFO、`dumpbin /EXPORTS`／`/HEADERS`、嵌入 PDB path 字串、品牌 token 掃描。  
2. 動態：sandbox 複本執行 `--help`，擷取 process／loaded modules。  
3. Loader：暫時改名 `PrusaSlicer.dll` → 擷取 shim 錯誤字串後還原。  
4. QA probe：`BUNDLE_QA_CRASH_MODE=overflow|segfault|exception` → 皆 exit 0（**無** runtime crash harness）。  
5. WER：設定 HKCU LocalDumps（`prusa-slicer-console.exe` → evidence `dumps/`）。  
6. Minidump：`cdb` 於 `PrusaSlicer.dll` load 斷點寫入 `postload-baseline.dmp`；再以 PDB-free 分析 `lm`＋`k`。

---

## 測試範圍（建立人填寫）

- 測
    - Windows x64 consumer-like unpack 引擎路徑／檔名（`prusa-slicer*.exe`、`PrusaSlicer.dll`、`prusaslicer_build`）
    - 行程名＋已載入模組完整路徑
    - PE VERSIONINFO（Company／Product／Internal／OriginalFilename／Version 等）
    - `dumpbin /exports`（`slic3r_main`、`Slic3r` mangled 數量）
    - PE debug directory／嵌入 PDB path
    - shim 缺 DLL 時 user-visible loader 錯誤
    - LocalDumps 設定＋minidump 模組名／PDB-free stack 表面（品牌模組可見性）
    - runtime QA crash harness 有無（probe）
- 不測
    - 去識別後 L1+L2 PASS（屬 2.5／7.2）
    - 三種 QA crash site（overflow／segfault／exception）正式 PoC（需 compile-time harness → 2.5）
    - Authenticode 最終 installer／簽核包
    - Bundle-Launcher 正式組包流程、前端 UI、安裝升級
    - macOS／`.ips`（已由 M1／2.4 關閉）
    - L3（全面 namespace／OLLVM／packer／攔截 WER）
    - AGPL source-offer／Legal 簽核

---

## 測試結果追蹤

### 總結

| 項目 | 結果 | 備註 |
| --- | --- | --- |
| 整體 verdict | **PASS（baseline 收集完成）** | tasks **1.7 關閉** |
| process／module path | **已保存** | `prusa-slicer-console`＋`PrusaSlicer.dll` |
| VERSIONINFO | **已保存** | exe 全品牌；DLL 資源空但仍以檔名暴露 |
| exports | **已保存** | 470 named；`slic3r_main`=1；含 `Slic3r` 約 462 行 |
| PDB path | **已保存** | exe → `...\prusaslicer_build\...\prusa-slicer-console.pdb` |
| shim loader error | **已保存** | `PrusaSlicer.dll was not loaded` |
| WER／minidump 表面 | **已保存** | `postload-baseline.dmp`；模組／stack 見品牌名 |
| runtime crash harness | **不存在** | `BUNDLE_QA_CRASH_MODE` 無效（exit 0） |
| Go／No-go | **Go** | 可進 **2.3** 政策定案 → **2.5** Win PoC |

### 分項結果（L1）

| 表面 | 觀測值 | 品牌？ |
| --- | --- | --- |
| ProcessName | `prusa-slicer-console` | ✅ |
| Module | `prusa-slicer-console.exe`、`PrusaSlicer.dll`（完整路徑含 `prusaslicer_build`） | ✅ |
| CompanyName | `Prusa Research` | ✅ |
| ProductName／InternalName／FileDescription | `PrusaSlicer` | ✅ |
| FileVersion／ProductVersion | `PrusaSlicer-2.9.4+UNKNOWN` | ✅ |
| OriginalFilename | `prusa-slicer.exe` | ✅ |
| CLI banner | `PrusaSlicer-2.9.4+UNKNOWN based on Slic3r` | ✅ |
| Loader error | `PrusaSlicer.dll was not loaded` | ✅ |

### 分項結果（L2）

| 表面 | 觀測值 | 品牌？ |
| --- | --- | --- |
| Export `slic3r_main` | 存在（`dumpbin`：`470  1D5 0004C7B0 slic3r_main`） | ✅ |
| Named exports | **470**；多數 mangled 含 `Slic3r` | ✅ |
| PE PDB path（exe） | `C:\Phrozen3D\Lechon\03_Development\Win\web_slicer_core\third_party\prusaslicer_build\src\Release\prusa-slicer-console.pdb` | ✅ |
| Minidump modules | `prusa_slicer_console`、`PrusaSlicer` | ✅ |
| Minidump stack（無私有 PDB） | `prusa_slicer_console!wmain+0x1c3` 等 | ✅ |

### 證據索引

| 檔案 | 說明 |
| --- | --- |
| `evidence/windows/baseline/BASELINE.md` | 人工可讀總報告 |
| `win-baseline-20260717T055632Z/METADATA.json` | run metadata＋產物 hash |
| `static/VERSIONINFO.txt` | PE 版本資源全文 |
| `static/EXPORTS_PrusaSlicer.dll.txt` | 完整 exports |
| `static/EXPORT_slic3r_main.txt`／`EXPORT_COUNTS.txt` | 關鍵 export 摘要 |
| `static/PDB_PATH_STRINGS_EXE.txt` | 嵌入 PDB path |
| `dynamic/PROCESS_MODULES_help.txt` | 行程／模組路徑 |
| `dynamic/SHIM_LOADER_ERROR.txt` | loader 錯誤 |
| `dynamic/QA_CRASH_MODE_PROBE.txt` | harness 探測 |
| `dynamic/LOCALDUMPS_CONFIG.txt` | LocalDumps 設定 |
| `dynamic/WER_METADATA_BASELINE.txt` | dump 表面品牌行 |
| `dynamic/MINIDUMP_STACK_PDBFREE.txt` | cdb `lm`＋`k` 日誌 |
| `dumps/postload-baseline.dmp` | 權威 minidump（DLL load 時；sha256 `C9C09483…`） |
| `dumps/forced-av-baseline.dmp` | 補充 dump |

### 已知限制／Follow-up

1. 本 baseline 對象為 **win-unpacked consumer-like**，非 Authenticode 最終 installer（可選加測）。  
2. ~~無三種 QA crash~~ → **後續已由 2.5 完成**（`poc/REPORT-WIN.md`／`w25-close-20260717T083241Z`）。  
3. Minidump 取於 `PrusaSlicer.dll` **load 斷點**（證明模組／路徑指紋），非 overflow／segfault／exception site（屬 baseline 設計）。  
4. ~~下一步 2.3→2.5~~ → **已完成**（政策＋PoC PASS）。產品化見 §3／§5（export=1 → 5.3）。

### 測試結果追蹤（勾選）

- [x] process／module path 擷取  
- [x] VERSIONINFO 擷取  
- [x] dumpbin／exports（含 `slic3r_main`）  
- [x] PDB path／debug directory  
- [x] shim loader error  
- [x] LocalDumps 設定  
- [x] minidump＋PDB-free stack／模組名  
- [x] QA crash harness probe（確認不存在）  
- [x] 文件回寫（BASELINE／tasks 1.7／PROGRESS）  
- [x] tasks 1.7 關閉  

> **關閉判定：** 上列皆完成 → **Done／通過**。  
> 三種 crash PoC／去識別驗收 **原不屬本 task**；**後續狀態（2026-07-17）：2.3／2.5 已關閉** — 見 `NOTION-WIN-POLICY-POC-TASK.md`。

---

## 可貼區塊（結束）

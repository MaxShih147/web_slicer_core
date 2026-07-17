# Notion Task — Test 測試（可貼上）

> 複製下方「可貼區塊」全文到 Notion Test task。  
> 對應 OpenSpec：`backend-slicer-engine-deidentification`／tasks **2.4（M1 macOS PoC）**  
> 權威證據目錄：`web_slicer_core/openspec/changes/backend-slicer-engine-deidentification/poc/evidence/m1-close-20260717T032408Z/`

---

## 可貼區塊（由此開始）

### Test 測試

**標題建議：** M1 macOS PoC：改名＋visibility＋strip；三種 crash 對照 .ips＋scanner 原型

**狀態建議：** 通過／Done（本 task 可關閉；Windows 不在本 task 範圍）  
**測試日期：** 2026-07-17  
**平台／Arch：** macOS 26.5.1 (25F80)／arm64  
**執行人：** Backend（PoC）

---

## 測試原因及目的（建立人填寫）

驗證後端切片引擎去識別（OpenSpec `backend-slicer-engine-deidentification`）在 **macOS** 上，以 **精簡版 C′**（visibility＋strip＋thread 中性化＋改名）能否達成產品接受線 **L1+L2**：

1. **L1：** OS 崩潰報告抬頭不再出現 `PrusaSlicer`／品牌路徑身分，改為簽核中性名 `slicer-engine`。  
2. **L2：** DiagnosticReports `.ips` 中可讀堆疊／thread 名不出現黑名單 token（尤其 `Slic3r::`、`slic3r_main`）。  
3. **手段定案：** 確認 `strip -x` 不足；需 `-fvisibility=hidden`＋plain `strip`；並驗證三種 QA crash site（overflow／segfault／exception）皆能產出 `.ips`。  
4. **工具：** 落地 scanner 原型，對 binary＋`.ips` 做自動化 PASS／FAIL。

**非目的：** 不驗證 L3（全面 namespace／OLLVM／packer）、不驗證 Windows、不驗證正式 Bundle 公證包、不以加密 `.ips` 或攔截 Crash Reporter 作為通過條件。

---

## 測試背景（建立人填寫）

| 前端網址 | N/A（本測試僅後端 CLI／OS DiagnosticReports；無前端） |
| --- | --- |
| 後端版本 | PoC fork build：`slicer-engine`（Apple `OUTPUT_NAME`）；visibility flags 已套用；evidence binary sha256 `632962c7ea9e550f71dc6ca97e5c74cc4282fe7533b4bb31efd00b1ec44cc59f`（見 close run `SCAN.json`） |
| OpenSpec change | `web_slicer_core/openspec/changes/backend-slicer-engine-deidentification/` |
| 對應 task | tasks.md **2.4**（已關閉） |
| 命名簽核 | `slicer-engine`／`slicer_core.dll`／`slicer_run_cli`／目錄 `slicer-engine/`（naming-manifest approved 2026-07-17） |
| OS | macOS 26.5.1 (25F80)，arm64 |
| 觸發方式 | runtime `BUNDLE_QA_CRASH_MODE=overflow\|segfault\|exception`（PoC only；正式版須改 compile-time harness） |
| 重跑腳本 | `poc/run_m1_close.sh`＋`poc/scan_macos_artifact.sh` |

**前置發現（簡述）：**

- 僅改檔名可清 L1 抬頭，但堆疊仍可能出現 `Slic3r::`。  
- `strip -x` 幾乎不降 global 品牌符號；plain `strip`＋visibility 後堆疊可無 `Slic3r::`。  
- 同 UUID 的 dSYM／未 strip 複本或符號快取會讓 ReportCrash **重新寫出**函式名 → 驗收必須乾淨符號環境（正式包不附 dSYM）。

---

## 測試範圍（建立人填寫）

- 測
    - macOS arm64 CLI 改名為 `slicer-engine`＋`codesign --identifier slicer-engine`
    - `-fvisibility=hidden -fvisibility-inlines-hidden` 後 plain `strip` 的 consumer-like 產物
    - Thread 名中性化（`slicer-worker`）在 `.ips` 中的呈現
    - 三種 crash：stack overflow／segfault／未捕捉例外（abort）→ 各一份 `.ips`
    - L1 欄位：`procName`、`codeSigningID`、無 `prusaslicer` 路徑指紋
    - L2 欄位：`.ips` 內 `Slic3r::`＝0、`slic3r_main`＝0
    - Scanner 原型對 stripped binary＋三份 `.ips` 的 verdict
    - 對照：有 dSYM／同 UUID 污染時會 FAIL（環境教訓，非改名失敗）
- 不測
    - Windows／WER／PDB／export
    - Bundle-Launcher 正式組包、公證、Authenticode
    - 前端 UI、安裝流程
    - L3：全面 `Slic3r::`→`slice::`、OLLVM、packer、Crash Reporter 攔截
    - 正式 compile-time QA flavor 與 consumer 無 harness 稽核（屬後續 2.6／5.6）
    - AGPL source-offer／Legal 簽核
    - 功能／效能 golden regression 全量
    - 殘餘 `nm` ≈172 品牌 mangled global 的歸零（移交 5.1；本 PoC 不以 nm=0 為通過條件）

---

## 測試結果追蹤

### 總結

| 項目 | 結果 | 備註 |
| --- | --- | --- |
| 整體 verdict | **PASS** | tasks 2.4 關閉 |
| Scanner | **PASS**（exit 0） | `SCAN.json` |
| L1 | **通過** | `procName`／`codeSigningID`=`slicer-engine` |
| L2（可讀堆疊／thread） | **通過** | 三種 `.ips` 皆 `Slic3r::`=0、`slic3r_main`=0；thread=`slicer-worker` |
| 三種 crash site | **通過** | 皆有 `.ips` |
| `strip -x` 當 L2 充分條件 | **否決** | 實測無效 |
| Go／No-go | **Go（macOS C′ 可行）** | 正式落地仍須 dSYM 隔離＋manifest；Win 另測 |

### 分項結果

| Case | `.ips` | procName | codeSigningID | Slic3r:: | slic3r_main | thread 名 |
| --- | --- | --- | --- | --- | --- | --- |
| overflow | ✅ | slicer-engine | slicer-engine | 0 | 0 | slicer-engine／slicer-worker |
| segfault | ✅ | slicer-engine | slicer-engine | 0 | 0 | 同上 |
| exception | ✅ | slicer-engine | slicer-engine | 0 | 0 | 同上 |

### 靜態符號（附註，非本 PoC 阻擋項）

| 指標 | 數值 |
| --- | --- |
| unstripped `nm -gU` brand | 933（visibility 後） |
| stripped `nm -gU`／`nm -U` brand | 172／172 |
| 說明 | 殘餘多為 template／boost 具體化；本 close run 崩潰堆疊未解析出 `Slic3r::` |

### 證據索引

| 檔案 | sha256（前綴可對） | 說明 |
| --- | --- | --- |
| `poc/evidence/m1-close-20260717T032408Z/` | — | 權威 close run 目錄 |
| `SCAN.json` | `2125ba094e06…` | scanner PASS 全文 |
| `SUMMARY.md` | `91e8b88a5666…` | 人工可讀摘要 |
| `ips/overflow.ips` | `ba00aa1b7c40…` | |
| `ips/segfault.ips` | `a5f990f5c98e…` | |
| `ips/exception.ips` | `93efc79b5161…` | |
| `poc/REPORT.md` | — | PoC 結論與定案 flags |
| `PROGRESS.md`（change 根目錄） | — | 開發／測試進度總表 |

### 已知限制／Follow-up

1. Runtime env harness（`BUNDLE_QA_CRASH_MODE`）僅 PoC；正式須 compile-time QA flavor。  
2. 正式包不得附 dSYM；驗收環境須無同 UUID 符號污染。  
3. `nm` 殘餘 ~172 → tasks 2.2 已定案手段，收斂屬 5.1。  
4. Windows baseline／PoC、Launcher 組包、AGPL 簽核 **不在本 M1 task**；另開 OpenSpec **1.7／2.5**（及對應 Notion Test）。  
5. tasks **2.4b**「已知乾淨參考報告」→ **已批准（2026-07-17，批准人 Vance）**，見 `clean-reference-report.md`。

### 測試結果追蹤（勾選）

- [x] 改名＋identifier L1 驗證  
- [x] visibility＋strip 重編  
- [x] overflow `.ips`  
- [x] segfault `.ips`  
- [x] exception `.ips`  
- [x] scanner PASS  
- [x] 文件回寫（REPORT／tasks 2.4／PROGRESS）  
- [x] 2.4b 乾淨參考報告正式批准  

> **關閉判定：** 上列本 task 勾選皆完成 → **Done／通過**。  
> ~~Windows 對等測試~~ **不屬本 task 通過條件**（見「非目的」／「不測」）；請勿以未勾 Windows 阻擋關閉。Windows 追蹤：OpenSpec tasks **1.7**（baseline）→ **2.5**（Win PoC）。

---

## 可貼區塊（結束）

# Crash Harness 取證設計修正待辦

**版本：** 1.0-draft
**Status：** 工程修正待辦（對現有 harness 實作的整改）
**適用 Requirement：** REQ-DEID-006、REQ-DEID-009、REQ-DEID-014；`design.md` D3／D7／D13
**對應 tasks：** 2.4、2.6、5.6、7.3

> 本文件針對目前已存在於 working tree 的「Prusa 原生崩潰重現 harness」提出整改。該 harness 可作為取得 **改名前 macOS 基準 `.ips`** 的一次性 spike，但**不得**被當成去識別的正式驗證設計，也**不得**照現況進入 consumer release。

---

## 1. 現況（實作位置）

| Repo | 位置 | 現況 |
|------|------|------|
| `prusaslicer_fork` | `src/libslic3r/SLAPrint.cpp`（`SLAPrint::process()` 內 `bundle_force_stack_overflow()`） | **runtime** `std::getenv("BUNDLE_FORCE_PRUSA_STACK_OVERFLOW")` 觸發無限遞迴 stack overflow |
| `web_slicer_core` | `agent/sla_operations.py` `notify_launcher_if_prusa_crashed()` | 子行程以 signal 結束時寫 sentinel JSON |
| `Bundle-Launcher` | `main.cjs` `startPrusaCrashHybridWatcher()`／`waitForPrusaIpsReport()` | 偵測 sentinel → 等 `.ips` → `open` → `process.crash()` |

---

## 2. 四項必要修正

### 修正 1：改為 compile-time，移除 runtime env 崩潰路徑（最高優先）

**問題：** `SLAPrint.cpp` 以 `std::getenv` 在**執行期**判斷，崩潰路徑會被編入正式 binary。這直接違反本 change 的 [`REQ-DEID-009`](./specs/slicer-engine-deidentification/spec.md) 與 `design.md` D7：consumer release **MUST NOT** 含可由 runtime environment 啟動的故意崩潰路徑。

**修正：**

- 崩潰觸發 **MUST** 以 **compile-time flag**（`BUNDLE_QA_CRASH_HARNESS`）隔離；未定義該巨集時，相關程式碼 **MUST NOT** 編入 binary（`#ifdef` 整段排除，非 runtime 分支）。
- 產生 **qa** 與 **consumer** 兩個 flavor，唯一差異為此 compile-time harness（release-equivalent，見 `artifact-manifest.schema.md` §3、`design.md` D7）。
- consumer binary inspection **MUST** 證明不含 harness 符號／字串（對應 REQ-DEID-009、task 5.7）。
- 保留期間，現有 `BUNDLE_FORCE_PRUSA_STACK_OVERFLOW` runtime 版 **MUST** 標記為僅限本機取證 spike，**MUST NOT** 隨任何簽署 release 出貨。

### 修正 2：移出 `SLAPrint.cpp`，最小化 fork 改動

**問題：** 觸發點插在上游熱點 library step（`SLAPrint::process()`），是 rebase 衝突面最大的位置，每次同步上游都要處理。

**修正（擇一，優先序由上而下）：**

1. **獨立 translation unit**：`bundle_qa_crash_probe.cpp`，僅在 `BUNDLE_QA_CRASH_HARNESS` 時加入編譯，由 CLI 進入點呼叫。
2. **CLI 進入點隱藏 flag**：在 Prusa CLI `main`（`Setup.cpp`／CLI 層）解析隱藏參數觸發，不動 libslic3r。
3. **獨立 `crash_probe` 小程式**：完全不改 fork 原始碼，另編一支模擬引擎符號布局的測試 binary（僅用於 PoC 對照）。
- fork 內若仍需改動，**MUST** 以 quilt／patch-on-pinned-tag 維護，並列入 fork patch 清單（降低 rebase 成本，對齊 naming-manifest「最小化 patch 面」原則）。

### 修正 3：覆蓋三類 crash site，而非只有 stack overflow

**問題：** 現況僅觸發 stack overflow；但最會洩漏 `Slic3r::` demangle 型別名的是**未捕捉 C++ 例外**，目前取不到該類基準。

**修正：** harness **MUST** 支援三種可選觸發，對應 [`acceptance-procedure.md`](./acceptance-procedure.md) 與 task 2.4／7.3：

| 類型 | 觸發 | 主要驗證目標 |
|------|------|--------------|
| Stack overflow | 無限遞迴 | thread name、模組名＋offset |
| 一般 native crash | null-deref／`abort()`（SIGSEGV／SIGABRT） | 一般堆疊符號、函式名 |
| 未捕捉 C++ 例外 | 拋出帶 `Slic3r::` 型別的例外並不捕捉 | RTTI／typeinfo demangle 型別名（`design.md` D3、spec REQ-DEID-006.2） |

### 修正 4：參數化預期行程名／報告前綴，支援改名前後對照

**問題：** `main.cjs` `waitForPrusaIpsReport()` 以 `prusa-slicer`／`prusaslicer` 前綴寫死比對 `.ips`；一旦改名為 `slicer-engine` 即失效，只能用於「改名前」，無法作為 before／after diff 的同一支工具。

**修正：**

- 預期行程名／報告前綴 **MUST** 參數化（env 或設定），使同一工具能驗證改名後（`slicer-engine*.ips`）。
- 選取 `.ips` **MUST** 以 sentinel 內 `pid`（必要時加時間戳）對應具體那次崩潰，**MUST NOT** 僅取「最新且 mtime ≥ 起始-2s」而可能抓到無關報告。
- 取證 **MUST** 在乾淨環境（無私有 dSYM／PDB／`_NT_SYMBOL_PATH`）執行（`acceptance-procedure.md` §1.9）。

---

## 3. 附帶修正（同批處理）

- **不要 `process.crash()` 崩掉 Launcher 作為取證手段。** 去識別證物是**引擎 CLI 子行程**的 `.ips`；應以讀檔／symbolication 取得。若需可見系統對話框僅為 demo，**MUST** 明確標為獨立 demo 路徑，不與取證流程混用。
- **跨平台 signal 判定收斂。** `agent/sla_operations.py` 的 `returncode < 0 or returncode >= 128` 需確認在 macOS（asyncio 負值）與 Windows（stack overflow `0xC00000FD`）皆正確判為崩潰。
- **提供 Windows／WER 對等取證。** 現況 watcher 於非 darwin 直接 return；Windows baseline（task 1.7）仍為 blocker，取證工具 **MUST** 補 WER／minidump 對等路徑。

---

## 4. 完成定義（DoD）

- [ ] harness 僅存在於 compile-time `BUNDLE_QA_CRASH_HARNESS`；consumer binary inspection 零 harness 殘留（5.6／5.7）
- [ ] 觸發點不在 `SLAPrint.cpp`；fork patch 面記錄於 patch 清單
- [x] 三類 crash site 皆可觸發並各取得一份基準報告（2.4 PoC：`poc/evidence/m1-close-20260717T032408Z/`；正式驗收仍見 7.3）
- [ ] compile-time QA harness 與 consumer Release 分離（2.6／5.6）
- [ ] 參數化／移出 `SLAPrint.cpp` 熱點（5.6）
- [ ] 取證工具參數化行程名，改名前後皆可用；以 pid 對應 `.ips`
- [ ] 取證流程不依賴崩掉 Launcher；乾淨環境執行並記錄環境證據
- [ ] Windows／WER 對等取證路徑就緒（雙平台對等，`design.md` D5）

---

## 5. 與主 tasks 的關係

本文件不新增 Requirement，屬 tasks 2.4／2.6／5.6／7.3 的**實作層整改備註**。整改完成後於 `tasks.md` 勾選對應項並於 `traceability.md` 保留連結。

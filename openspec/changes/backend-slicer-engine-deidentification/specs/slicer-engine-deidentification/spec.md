## ADDED Requirements

### Requirement: REQ-DEID-001 範圍僅限後端切片引擎與包版產物

本能力 **MUST（必須）** 僅涵蓋 Local agent、引擎 CLI 產物，以及 Bundle-Launcher 正式包路徑與設定。本能力 **MUST NOT（不得）** 將前端資安審查、Launcher UI 改版或首次安裝流程簡化列為完成條件。

#### Scenario: 範圍邊界

- **WHEN** 利害關係人檢視本 change 之完成定義
- **THEN** 完成條件**必須**可由後端引擎產物、agent 路徑與雙平台包版驗證閉環證明

### Requirement: REQ-DEID-002 本版必須同時達成 L1 與 L2（L2＝精簡版 C′）

本能力完成時 **MUST（必須）** 同時滿足：

- **L1：** OS 崩潰報告抬頭／路徑／映像名／Identifier／Version（及 Windows 對等）不命中指紋黑名單。
- **L2：** 同報告中使用者或工具可讀之堆疊／thread name／公開 export 不命中指紋黑名單（包含但不限於 `Slic3r::` 形式）。L2 **MUST** 以 [`design.md`](../../design.md) D3 定義之 **精簡版 C′**（strip＋thread＋Win export）達成；**MUST NOT** 要求全面 namespace 改名或 OLLVM。

僅達成 L1 **不得**宣告本能力完成。

#### Scenario: 僅改名未 strip／未改 thread／export 視為未完成

- **WHEN** 正式包已改名但崩潰報告仍出現可讀 `Slic3r::`（未 strip）、品牌 thread 名，或 Windows 仍匯出 `slic3r_main`
- **THEN** 驗收**必須**判定失敗（L2／C′ 未達）

### Requirement: REQ-DEID-003 macOS 與 Windows 皆為必過驗收平台

本能力 **MUST（必須）** 在 **macOS 與 Windows** 各自完成 L1+L2 驗收。任一側失敗即 **MUST NOT（不得）** 宣告完成。

#### Scenario: 單平台通過不足

- **WHEN** 僅 macOS（或僅 Windows）通過黑名單掃描
- **THEN** 本能力**必須**仍標示為未完成，直至另一平台亦通過

### Requirement: REQ-DEID-004 產物改名重包為 L1 必要基線

正式包中的引擎執行檔與相關動態庫（Windows：exe／dll；macOS：CLI Mach-O）**MUST（必須）**使用產品簽核之內部名稱，**MUST NOT（不得）**使用 `PrusaSlicer`、`prusa-slicer` 或含對外品牌形式之 `prusa`／`slic3r` 檔名。Agent **MUST（必須）**能呼叫改名後路徑。正式包的目錄、symlink、loader error、資源檔名及使用者可見錯誤訊息亦 **MUST** 依 [`blacklist.md`](../../blacklist.md) 的 scope 判定。

#### Scenario: 雙平台正式包檔名

- **WHEN** 檢查與預定發布完全相同、已完成平台簽署之 macOS 與 Windows 正式 bundle
- **THEN** 兩平台引擎主產物檔名與使用者可見相對路徑**必須**皆去品牌

#### Scenario: Agent 可啟動改名後 CLI

- **WHEN** agent 執行需呼叫引擎之 SLA 操作
- **THEN** **必須**成功 subprocess 啟動改名後 CLI

### Requirement: REQ-DEID-005 身分／版本身分字串須去品牌

正式引擎產物在 OS diagnostics 可見之身分字串 **MUST（必須）** 為中性內部識別，**MUST NOT（不得）** 使用 `com.prusa3d.slic3r`、`PrusaSlicer` 或其他黑名單 token。涵蓋：

- **macOS CLI：** `.ips` 的 `bundleInfo.*`／`codeSigningID`、Version 字串；`codeSigningID` **MUST** 與核准執行檔名一致；品牌化 `Info.plist`／`CFBundleIdentifier` **MUST** 刪除或中性化。引擎為 headless CLI 時 **MUST NOT** 將法人 reverse-DNS App Bundle ID 註冊視為完成條件。
- **Windows：** VERSIONINFO 之 CompanyName／FileDescription／InternalName／OriginalFilename／ProductName／ProductVersion 等對應字串。

#### Scenario: 雙平台身分字串

- **WHEN** 檢視崩潰報告或平台身分查詢工具輸出（含 `codesign -dv`）
- **THEN** Identifier／Version／產品名**必須**去黑名單 token

### Requirement: REQ-DEID-006 L2 採精簡版 C′（可見性＋strip＋全部 thread＋Win export）

正式對外引擎產物 **MUST（必須）** 以 **精簡版 C′** 達成 L2，使 [`acceptance-procedure.md`](../../acceptance-procedure.md) 定義之 macOS 與 Windows L2 表面 **MUST NOT（不得）** 命中 [`blacklist.md`](../../blacklist.md)。C′ **MUST** 包含：

1. **符號可見性控制（優先）＋ strip（fork 完成，見 D13）：** consumer 產物在交予 Launcher 簽署前完成 strip／符號剝除。手段為結果導向；具體 flags 由 PoC target-scoped 定案（macOS CLI 候選：`-fvisibility=hidden` + `strip -x`；Windows DLL：僅導出單一中性 entry）。**`-exported_symbols_list` 不得作為 macOS CLI exe 的 L2 充分條件。** 靜態驗證 **MUST** 分開掃描 local／defined 與 global／dynamic 符號；**MUST NOT** 僅以 `nm -gU` 判定通過。
2. **RTTI／例外型別名稱：** **MUST** 以未捕捉 C++ 例外 crash site 驗證；若洩漏品牌型別名，**MUST** 於 CLI 進入點加 top-level catch 或等效處理。
3. **Thread name 去品牌（全部 call site）：** 所有 `set_current_thread_name`／`SetThreadDescription`（含 main 與 TBB／worker）**MUST** 改為簽核中性命名規則（見 [`naming-manifest.md`](../../naming-manifest.md)）。
4. **Windows 公開 export／DLL ABI 去品牌：** shim／DLL／export／VERSIONINFO／錯誤字串 **MUST** 原子遷移為簽核中性名並通過 smoke test。

L2 達標判定 **MUST** 綁定最終簽署包之靜態掃描，以及 release-equivalent qa（或可外部注入之 consumer）動態實測（token 掃描＋[`blacklist.md`](../../blacklist.md) §2.1 **第三方品牌歸因**正向複核）。C′ 為最低實作，**MUST NOT** 以「已實作 C′」預先宣稱達標。本版 **MUST NOT** 將全面 namespace／OLLVM／packer／`strings` 零品牌字串列為 L2 完成條件。內部符號組態 **MAY** 存在，但 **MUST NOT** 隨消費者正式包發布。

#### Scenario: macOS L2（strip 後 stack）

- **WHEN** 正式簽署包（qa 或可注入之 consumer）觸發引擎原生崩潰並取得 `.ips`
- **THEN** 必掃欄位與三種 crash site（含未捕捉例外）**必須**零未豁免命中；典型 stack 為模組名＋offset；thread 名為中性值（含 worker）

#### Scenario: Windows L2

- **WHEN** 正式簽署包觸發引擎原生崩潰並取得 WER／PDB-free minidump／PE 掃描輸出
- **THEN** process/module identity、loader、公開 export、PDB-free stack 與例外訊息**必須**零未豁免命中

#### Scenario: Windows shim 與 DLL ABI 原子遷移

- **WHEN** Windows headless CLI shim 仍以 DLL 與 export entry 呼叫核心
- **THEN** shim 載入路徑、DLL 檔名、export entry、錯誤訊息與 CMake target **MUST** 原子更新並通過 smoke test

#### Scenario: 否決以全面 namespace／OLLVM／加密取代 strip

- **WHEN** 提案宣稱已做 namespace 改名、OLLVM 或加密，故無需 strip 或無需改 thread／export
- **THEN** 驗收**必須**拒絕

#### Scenario: 未捕捉例外洩漏品牌型別名

- **WHEN** 未捕捉 C++ 例外導致 abort／ASI 出現 `Slic3r::` 型別名
- **THEN** L2 驗收**必須**判定失敗

#### Scenario: 僅 token 掃描或僅 global nm 不足以宣告通過

- **WHEN** token 掃描零命中，但 local 符號仍含黑名單，或品牌歸因正向複核發現未簽核第三方品牌殘留
- **THEN** 驗收**必須**判定失敗

#### Scenario: 僅改 main thread 名不足

- **WHEN** `slic3r_main` 已改但 `.ips`／掃描仍出現 `slic3r_tbb_*` 或其他品牌 thread 名
- **THEN** L2 驗收**必須**判定失敗

### Requirement: REQ-DEID-007 加深手段不得取代 A+B+C′

加密／packer／攔截 Crash Reporter／全面 namespace 改名／OLLVM **MUST NOT（不得）** 單獨作為滿足 L1 或 L2 之方案；若採用 **MUST（必須）** 建立在改名重包與精簡版 C′（含 D13 流水線）之上，並先有書面可行性評估與安全／發布審查。

#### Scenario: 否決只加密不改名／不剝符號

- **WHEN** 提案宣稱已加密故無需改名或無需 strip／處理 thread／export
- **THEN** 驗收**必須**拒絕

### Requirement: REQ-DEID-008 維持 CLI subprocess AGPL 邊界

Local agent **MUST（必須）** 以獨立行程呼叫引擎；**MUST NOT（不得）** 為去識別改為連結 libslic3r 或破壞既有 AGPL 邊界。

#### Scenario: 呼叫方式不變

- **WHEN** 正式包執行切片
- **THEN** 引擎**必須**仍為 subprocess；agent 得在引擎崩潰後依既有設計回報失敗並存活

### Requirement: REQ-DEID-009 正式包不得包含啟用中的崩潰注入能力

用於重現 crash 之 harness **MUST（必須）** 以 compile-time QA build flag 隔離；消費者正式 release **MUST NOT（不得）** 包含可由 runtime environment 啟動的故意崩潰路徑、品牌化測試變數或測試符號。

#### Scenario: Release 預設安全

- **WHEN** 使用者以正式包正常切片且未設 debug 閘控
- **THEN** binary inspection 與功能測試**必須**證明驗收 harness 未編入消費者 release，且引擎不得因驗收注入而故意崩潰

### Requirement: REQ-DEID-010 雙平台驗收紀錄可追溯

專案 **MUST（必須）** 維護黑名單，以及 **macOS 與 Windows 各至少一份**通過 L1+L2 之驗收紀錄（包版本、commit SHA、artifact hash、CPU architecture、OS／toolchain、觸發方式、報告／傾印識別、掃描器版本與結果）。

#### Scenario: 雙平台文件

- **WHEN** 宣告本能力完成
- **THEN** **必須**可取得 macOS 與 Windows 兩份通過紀錄

### Requirement: REQ-DEID-011 修改後 AGPL 作品合規

重新命名、修改或以其他方式發布 fork 產物時，正式 release **MUST（必須）** 保留適用之 AGPL 授權文本、版權與歸屬資訊、顯著修改聲明，並向適用使用者提供與發布 binary **精確對應 commit** 的 Corresponding Source 取得方式。去識別 **MUST NOT（不得）** 被用來移除或弱化授權／來源揭露義務。

#### Scenario: 發布包授權稽核

- **WHEN** macOS 或 Windows 正式包進入發布簽核
- **THEN** 發布證據**必須**包含 AGPL license、修改聲明、source URL／書面 offer、fork commit 與 binary build manifest 的對應，並取得法務／開源合規 owner 簽核

### Requirement: REQ-DEID-012 符號供應鏈與可除錯性

專案 **MUST（必須）** 為每個正式引擎 artifact 產生唯一 build ID，將 macOS dSYM 與 Windows PDB 儲存在不隨消費者包發布之受控內部位置，並定義保留期、ACL、完整性 hash、artifact UUID／GUID 對應與 symbolication runbook。

#### Scenario: 正式事故可內部符號化

- **WHEN** 支援人員取得正式版本 crash artifact
- **THEN** 經授權之工程人員**必須**能依 Launcher version、engine build ID 與 UUID／GUID 取得精確符號檔並完成內部 symbolication

### Requirement: REQ-DEID-013 最終簽署產物自動閘控

CI／release pipeline **MUST（必須）** 對 macOS 已完成 codesign、notarization、staple 的最終 app／DMG，以及 Windows 已完成 Authenticode 的最終 installer／bundle 執行可重現的 L1／靜態 L2 掃描。掃描未通過 **MUST** 阻止發布。

#### Scenario: 後續合併重新引入指紋

- **WHEN** fork 更新、包版腳本或簽署步驟重新引入黑名單命中
- **THEN** 雙平台 release gate **MUST** 失敗並保存命中位置、artifact hash 與掃描器版本

### Requirement: REQ-DEID-014 切片行為與效能回歸

去識別變更 **MUST NOT（不得）** 改變既有切片 API 契約、exit code 語意、檔案格式或可接受之切片結果。雙平台 **MUST** 執行 golden／integration regression，涵蓋 slice、generate-supports、hollow、cut、3MF／相關 CLI 路徑與失敗處理；效能退化門檻 **MUST** 在實作前簽核。

#### Scenario: 改名或符號策略破壞執行

- **WHEN** 新引擎產物在任一平台執行完整回歸套件
- **THEN** 所有必要操作、輸出完整性、agent failure handling 與簽核效能門檻**必須**通過，否則不得發布

### Requirement: REQ-DEID-015 命名與 artifact manifest 為開工前置條件

產品 owner **MUST（必須）** 在改名實作開始前簽核跨平台命名表（[`naming-manifest.md`](../../naming-manifest.md)）與機器可驗交接 schema（[`artifact-manifest.schema.md`](../../artifact-manifest.schema.md)），至少涵蓋 executable（含 macOS 真實 `OUTPUT_NAME`）、DLL、目錄、symlink、macOS `codeSigningID`／Info.plist 方針、VERSIONINFO、**全部 thread 命名規則**、**loader／export ABI**、resource 路徑、user-visible errors、pre／post_strip hash 與 flavor。法人 reverse-DNS App Bundle ID 與全面 C++ namespace 改名 **MUST NOT** 列為本版 L2 開工阻塞項。

#### Scenario: 命名尚未定案

- **WHEN** 命名表或 artifact manifest 尚未簽核
- **THEN** 改名與包版實作任務**必須**維持 blocked，不得由工程自行臆造對外名稱

#### Scenario: namespace 未改不阻塞 L2

- **WHEN** consumer 包已完成 A+B+C′（含 strip）且依驗收程序零未豁免命中，但原始碼仍使用 `Slic3r::` namespace
- **THEN** L2 驗收**必須**判定通過（不得因未做 C-full 而 FAIL）
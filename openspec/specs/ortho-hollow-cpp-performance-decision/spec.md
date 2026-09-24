# ortho-hollow-cpp-performance-decision Specification

## Purpose
記錄 Ortho Auto Process 的 Prusa Hollow C++（`slicer-engine.exe --export-hollow-stl`）效能調查結論：production 呼叫路徑與單次呼叫保證、封裝版 baseline 的 submodule 來源限制、封裝版 executable 的環境變數覆寫機制（本輪量測選用封裝版，非所有部署環境保證如此）、C++ 子階段耗時分布（OpenVDB 呼叫鏈占比 76.2%～93.8%，及高面數壓力測試模型上 mesh 載入例外約 21.0%）、兩個已否決的 OpenVDB 候選（CSG union 對空 grid 的 `clone()`、`mesh_to_grid()` 的 `its_split()`）、skip-2nd-exact-check 候選的資料狀態條件與受測範圍限定（僅一個人工增面壓力測試模型實際觸發、未涵蓋開放邊輸入）、該候選因三個新增一般模型全數未觸發而不予採用的停止決策，以及高面數壓力測試模型的來源限定（使用者確認為既有模型拆分三角面增面而成，但無法對應到任何現存模型、不得推測其原始檔案去向或退化面成因）。作為未來重新評估此路徑效能時的既定基準與觸發條件，防止探索性數字被誤引為正式基準、已否決候選被重複調查，或受測範圍有限的驗證結果被誤讀為已證明對任意輸入皆適用。
## Requirements
### Requirement: Production Hollow 呼叫路徑與單次呼叫保證 SHALL 被正確引用

Ortho Auto Process 一鍵處理對 C++ Hollow（`slicer-engine.exe --export-hollow-stl`）的呼叫路徑 SHALL 描述為：`run_ortho_pipeline()` Step 1 呼叫 `generate_hollow()`，經 `run_prusa_cli()` 啟動依 `agent/config.py` 路徑解析邏輯（[agent/config.py:33-34](../../../../../agent/config.py#L33-L34)）選定的 executable。單一 Ortho job SHALL 描述為對 C++ Hollow **最多呼叫一次**：`_is_u_arch_from_low_sections()`（U 型前置判斷）在該次呼叫**之前**決定是否跳過；Hollow-fit 檢查在 C++ 執行**之後**才判斷，不影響是否呼叫。MUST NOT 將 Hollow-fit 檢查描述為會阻止 C++ 呼叫發生的條件。

該路徑解析邏輯優先讀取 `SLICER_ENGINE_BIN`／`PRUSA_SLICER_BIN` 環境變數，僅兩者皆未設定時才落回封裝版優先的預設順序；`README.md` 明確教學使用者手動設定 `SLICER_ENGINE_BIN` 指向 dev-tree build。任何描述 MUST NOT 宣稱所有實際部署環境一律使用封裝版 executable，且 SHALL 區分「本輪量測選用的執行檔」與「所有實際部署環境的執行檔」——本輪調查全程未觀察到任何正在執行的 production 後端程序，無法確認任何實際部署當下的解析結果。

#### Scenario: 引用 production 呼叫路徑時的描述
- **WHEN** 任何人描述 Ortho Auto Process 呼叫 C++ Hollow 的路徑或次數
- **THEN** 該描述 SHALL 指出單一 job 最多呼叫一次，且呼叫是否發生僅由 U 型前置判斷決定
- **AND** 該描述 MUST NOT 將 Hollow-fit 檢查描述為會阻止或跳過 C++ 呼叫本身的條件

#### Scenario: 引用實際使用的 executable 時不得過度概括
- **WHEN** 任何人描述 production 實際部署環境使用的是哪一顆 `slicer-engine` executable
- **THEN** 該描述 SHALL 說明其取決於啟動當下 `SLICER_ENGINE_BIN`／`PRUSA_SLICER_BIN` 是否被設定，而非固定為封裝版
- **AND** 該描述 MUST NOT 宣稱本輪調查已觀察或確認任何實際部署當下解析出的 executable——本輪僅確認「本輪量測腳本在明確清空這兩個環境變數後」解析到封裝版

### Requirement: 封裝版 baseline 數字 SHALL 標示為探索性

封裝版 executable（`slicer-engine\bin\slicer-engine.exe`）的 manifest 記錄之 `engine_commit` SHALL 描述為 parent repo 的 `git rev-parse HEAD`，並未在 `third_party/prusaslicer_fork` submodule 內獨立記錄建置當下的 SHA。任何以封裝版量測的耗時數字，MUST 標示為探索性（exploratory），MUST NOT 描述為已完全可追溯、可直接用於正式 A/B 的正式基準。

#### Scenario: 引用封裝版耗時數字時的限定
- **WHEN** 任何人引用以封裝版 `slicer-engine.exe` 量測的 Hollow 耗時數字
- **THEN** 該引用 SHALL 同時標示其為探索性 baseline
- **AND** 該引用 SHALL 說明 submodule 來源僅有間接證據（現況與 parent 記錄之 pointer 一致），並非建置當下的直接記錄

### Requirement: C++ 子階段耗時分布 SHALL 以 OpenVDB 呼叫鏈為主要熱點引用

Hollow C++ 子階段耗時分布（涵蓋 CLI 啟動與 mesh 載入、mesh 複製與體積估算、OpenVDB voxelize／redistance／dilate、grid→mesh、結果複製與法線處理、binary STL 寫出）SHALL 引用為：OpenVDB 的 voxelize／redistance／dilate 呼叫鏈合計占 Hollow subprocess wall time 約 **76.2%（高面數壓力測試模型）～93.8%（小面數代表模型）**。其餘子階段 MUST NOT 一概描述為「合計皆為個位數百分比」——在小面數／中面數代表模型上個別子階段確實皆為個位數百分比，但**高面數壓力測試模型的 mesh 載入單獨即占約 21.0%**（因該模型清理後仍殘留約 5,042 個退化面，觸發了真正執行的第二次 `stl_check_facets_exact()`，見「Skip-2nd-exact-check 候選的資料狀態條件」之 Requirement），grid→mesh、STL 寫出、mesh 複製與體積估算這幾項在三個模型上則確實維持個位數百分比。

#### Scenario: 引用 C++ 子階段占比時的範圍
- **WHEN** 任何人引用 Hollow C++ 子階段的耗時占比
- **THEN** OpenVDB 呼叫鏈占比 SHALL 引用為約 76.2%～93.8%（依代表模型面數而異）
- **AND** MUST NOT 將 grid→mesh、STL 寫出、mesh 複製與體積估算描述為與 OpenVDB 呼叫鏈同等量級的熱點
- **AND** MUST NOT 將高面數壓力測試模型上約 21.0% 的 mesh 載入描述為個位數百分比或忽略不計

#### Scenario: mesh 載入例外與第二次檢查的關聯
- **WHEN** 任何人引用高面數壓力測試模型上 mesh 載入約 21.0% 的數字
- **THEN** 該引用 SHALL 說明其絕大部分是 admesh 匯入修復流程中兩次 `stl_check_facets_exact()` 的耗時，其中第二次是因該模型 `degenerate_facets > 0` 而真正被觸發執行

### Requirement: 兩個已否決的 OpenVDB 候選 MUST NOT 在未重新量測前被重新提出

以下兩個 OpenVDB 候選已於本輪實測並否決，MUST NOT 在未附上新量測證據的情況下被重新提出為可行的優化方向：

1. **CSG union 對空 grid 的 `clone()`**：實測成本約 2～3 毫秒（占比 <0.15%），否決理由為假設不成立（成本本身過小）。
2. **`mesh_to_grid()` 內對單一連通分量網格的 `its_split()`**：實測成本約 3.4～75.2 毫秒（占比 0.22%～1.38%），否決理由為潛在報酬過低、且跳過後的等價性（三角形處理順序改變是否影響 `meshToVolume` 結果）未經驗證，風險相對不成比例。

#### Scenario: 重新提出已否決 OpenVDB 候選前的要求
- **WHEN** 任何人打算重新提出上述任一已否決的 OpenVDB 候選
- **THEN** 該提議 SHALL 附上新的量測證據，證明其成本或風險評估已與本決策記載的否決依據不同
- **AND** MUST NOT 僅以「程式碼看起來多餘」為由重新提出，而不附上量測

### Requirement: Skip-2nd-exact-check 候選的資料狀態條件與受測範圍 SHALL 被正確引用，不得宣稱已證明對任意網格安全

`TriangleMesh::ReadSTLFile()` 匯入修復流程中，條件式執行的第二次 `stl_check_facets_exact()` 之**候選**跳過條件 SHALL 引用為資料狀態可判定、不依賴檔名或面數：

```
skip_2nd_check = (connected_facets_3_edge == number_of_facets，第一次檢查後即成立)
                 AND (剛執行完的 stl_verify_neighbors 沒有回報任何邊不一致)
```

此條件 MUST NOT 被描述為「安全跳過條件」或「已證明對任意網格安全」，其受測範圍 SHALL 限定為：以獨立於診斷插樁的環境變數（`HOLLOW_PROTO_SKIP_2ND_EXACT`）做成的可切換 prototype，在小面數／中面數／高面數壓力測試三個代表模型上，開關切換前後各跑 5 次（另有 1 次不計入平均值的暖機），完整 Hollow STL 輸出的 SHA-256 逐次、逐模型完全相同；同一份診斷 binary、僅環境變數不同的乾淨計時 A/B（未啟用診斷插樁）顯示高面數壓力測試模型平均耗時由約 5.518 秒降至約 5.056 秒（約省 0.462 秒／8.4%），小面數／中面數代表模型耗時差異在雜訊範圍內（因其本就不會觸發第二次檢查）。此 A/B 的逐次耗時僅印於終端機、未落地為獨立結果檔，MUST NOT 描述為可脫離本輪對話紀錄獨立重新算出；完整 Hollow STL 輸出檔案仍存於 `C:\hdiag\equiv\ab\`，其 SHA-256 可獨立重新計算核對。

#### Scenario: 引用 skip-2nd-exact-check 候選的驗證結果時的限定
- **WHEN** 任何人引用 skip-2nd-exact-check 候選的等價性驗證或 A/B 結果
- **THEN** 該引用 SHALL 明確限定驗證對象為上述三個代表模型、5 次重複、完整 Hollow STL 輸出 SHA-256 比對
- **AND** SHALL 引用高面數壓力測試模型的 A/B 節省為約 0.462 秒（8.4%）
- **AND** MUST NOT 使讀者誤以為此驗證已涵蓋任意輸入分布或已完成正式 production 整合驗證

#### Scenario: 受測範圍不得誇大為「已證明任意網格安全」
- **WHEN** 任何人描述此候選跳過條件的驗證強度
- **THEN** 該描述 SHALL 說明三個代表模型中，只有高面數壓力測試模型在驗證當下 `degenerate_facets > 0`、實際觸發過此分支；另外兩個代表模型（以及三個新增一般模型）的 `degenerate_facets` 皆為 0，開關關／開兩種設定下走的是同一段程式碼，其比對結果相同是必然的，不構成對跳過條件本身的獨立驗證
- **AND** 該描述 SHALL 說明本輪所有測試模型在判斷點時皆無開放邊（`connected_facets_3_edge == number_of_facets`），未曾以任何有開放邊的網格驗證此條件在該情況下的行為
- **AND** MUST NOT 使用「安全跳過條件」一類措辭暗示已證明此條件對任意輸入皆正確

#### Scenario: A/B 逐次耗時的可追溯性限定
- **WHEN** 任何人試圖重新核對此 A/B 的耗時數字
- **THEN** 該人 SHALL 被告知逐次耗時未落地為獨立結果檔，僅存在於本輪對話紀錄中
- **AND** 現存的 Hollow STL 輸出檔案 SHALL 只能用於重新驗證 SHA-256 等價性，MUST NOT 用於重新算出當時量到的耗時均值

### Requirement: Skip-2nd-exact-check 候選 SHALL 引用為「不予採用」，理由為新增一般模型全數未觸發

依事先議定的停止判準（若新增的一般模型全數不觸發第二次檢查，即判定此優化不予採用），本候選 SHALL 引用為**不予採用、不移植至 production**。三個新增一般完整基座代表模型（清理後面數約 16.6 萬～23.9 萬，經 production 相同之 `clean_input_for_manifold()` 清理；三者並非全數嚴格介於高面數壓力測試模型與中面數代表模型之間，其中一個略低於中面數代表模型的面數）第一次 `stl_check_facets_exact()` 後 `degenerate_facets` 皆為 0，且直接核對程式碼層級證據（`proto_skip_2nd_exact` 與對應的第二次檢查後快照標記，兩者皆位於同一個條件區塊內）確認三個模型的執行紀錄中完全沒有出現——第二次檢查是結構性地未被觸發，不是「執行了但很快」。

#### Scenario: 引用 skip-2nd-exact-check 最終決策時的描述
- **WHEN** 任何人引用 skip-2nd-exact-check 候選的最終處置
- **THEN** 該描述 SHALL 陳述為「不予採用、不移植至 production」
- **AND** SHALL 說明理由為三個新增一般完整基座代表模型全數未觸發第二次檢查（`degenerate_facets` 皆為 0），而非候選本身的等價性或 A/B 結果有問題
- **AND** MUST NOT 將高面數壓力測試模型的正面驗證結果，描述為足以支持現階段移植至 production 的依據
- **AND** MUST NOT 將此結論延伸為「面數較大的一般 production 模型比較容易觸發第二次檢查」或任何關於一般模型面數分布、退化面發生率的推論——高面數壓力測試模型是人工合成的壓力測試樣本，不具一般代表性（見「高面數壓力測試模型之來源」之 Requirement）

### Requirement: 高面數壓力測試模型的來源 SHALL 標示為使用者提供之人工增面樣本，不得作為一般 production 面數分布推論依據

高面數壓力測試模型 SHALL 描述為：由使用者確認、以既有牙科模型拆分三角面、人工增面而成，但無法確認是哪一個原始模型，用於放大子階段耗時差異；其清理後殘留的退化面恰好觸發了本候選的分支條件，但成因未知（本輪未查證是否與拆分過程有關）。比對此模型與 `tempTest` 資料夾中其餘模型的 bounding box／volume 結果皆不吻合，目前無法將此模型對應到資料夾內任何現存模型；文件 MUST NOT 對原始檔案的去向做出推斷，MUST NOT 推測它是由哪一個現存模型拆分而來。任何引用 MUST NOT 以此模型的面數、退化面數量或其觸發第二次檢查的事實，推論一般 production 輸入的面數分布或退化面發生率。此模型 MUST NOT 被描述為本輪唯一的一般代表模型——小面數／中面數代表模型與三個新增模型同樣是未經人工增面的一般完整基座模型，三個新增模型應描述為「本輪新增的非增面一般樣本」，不是「唯一」的一般樣本。

#### Scenario: 高面數壓力測試模型的來源與代表性限定
- **WHEN** 任何人引用高面數壓力測試模型的面數、退化面數量或其驗證結果
- **THEN** 該引用 SHALL 說明其為使用者提供之人工增面樣本，非自然產生（掃描／設計輸出）的一般 production 大面數模型
- **AND** MUST NOT 推測其拆分自哪一個現存模型，亦 MUST NOT 對原始檔案的去向做出推斷（例如宣稱原始檔案曾存在、現已消失）
- **AND** MUST NOT 對其殘留退化面的成因做出推定性描述（例如宣稱「很可能是拆分造成」），SHALL 標示為未知
- **AND** MUST NOT 以此模型的特徵推論一般 production 模型的面數分布或退化面發生率
- **AND** MUST NOT 將三個新增一般完整基座代表模型描述為本輪「唯一」具代表性的一般樣本——小面數／中面數代表模型同樣是未經人工增面的一般樣本，三個新增模型應描述為本輪新增的非增面一般樣本

### Requirement: 診斷版數字與封裝版數字 SHALL 明確區分，診斷快照成本 MUST NOT 誤植為 production 成本

本輪 C++ 層級的插樁、狀態快照與 prototype 修改皆只存在於隔離 git worktree（`C:\hdiag\pf`，detached HEAD 於與主 checkout 相同的 submodule pin）與獨立建置目錄（`C:\hdiag\build`，重用主 checkout 既有、唯讀的 deps destdir）。此診斷版的編譯器 toolset patch 版本與封裝版實際使用的不同，因此診斷版與封裝版的耗時數字 SHALL 視為不同 binary 的結果，MUST NOT 直接相減視為正式 production A/B。

驗證 skip-2nd-exact-check 候選時新增的 FNV-1a 狀態快照（比對第一次檢查後／第二次前／第二次後的鄰接圖與頂點資料雜湊）僅在 `HOLLOW_PROF=1` 時啟用，且**無條件**於「`stl_verify_neighbors` 執行後、第二次檢查判斷式之前」執行，與第二次 `stl_check_facets_exact()` 是否真的執行無關。在三個新增一般完整基座代表模型的驗證中量到的約 15.8～23.0 毫秒，SHALL 描述為此診斷快照本身的計算成本，MUST NOT 描述為第二次 `stl_check_facets_exact()` 的耗時，亦 MUST NOT 描述為任何 production 會有的成本。

#### Scenario: 區分診斷版與封裝版數字
- **WHEN** 任何人引用本輪任何耗時數字
- **THEN** 該引用 SHALL 明確標示數字來源為隔離診斷版（`C:\hdiag\pf`／`C:\hdiag\build`）或封裝版（依 `agent/config.py` 設定選定的 executable；本輪量測選用封裝版）
- **AND** MUST NOT 將兩者的數字直接相減，作為正式 production A/B 的改善量

#### Scenario: 診斷快照成本不得誤植為第二次檢查耗時
- **WHEN** 任何人引用三個新增一般完整基座代表模型上量到的約 15.8～23.0 毫秒
- **THEN** 該引用 SHALL 描述其為本輪新增之診斷狀態快照本身的計算成本
- **AND** MUST NOT 描述為第二次 `stl_check_facets_exact()` 的執行耗時——該三個模型的第二次檢查並未被觸發（見「Skip-2nd-exact-check 候選 SHALL 引用為『不予採用』」之 Requirement）


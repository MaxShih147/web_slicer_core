## 1. 調查內容確認（已於本提案建立前完成，本節為留存紀錄）

- [x] 1.1 確認 production 呼叫路徑：`run_ortho_pipeline()` → `generate_hollow()` → `run_prusa_cli()` → 依 `agent/config.py` 設定選定的 executable（本輪量測選用封裝版）`slicer-engine.exe --export-hollow-stl`；單一 job 最多呼叫一次；U 型前置判斷在呼叫前、Hollow-fit 檢查在呼叫後
- [x] 1.2 確認封裝版 manifest 的 `engine_commit` 記錄 parent repo HEAD、未獨立記錄 submodule SHA，baseline 數字標示為探索性
- [x] 1.3 確認 C++ 子階段拆時：OpenVDB voxelize／redistance／dilate 呼叫鏈合計占 Hollow subprocess wall time 約 76.2%～93.8%（三個代表模型：小面數／中面數／高面數壓力測試）
- [x] 1.4 確認兩個 OpenVDB 候選（CSG union 對空 grid 的 `clone()`；`mesh_to_grid()` 的 `its_split()`）已實測並否決，否決依據已記錄
- [x] 1.5 確認 skip-2nd-exact-check 候選之資料狀態條件（`connected_facets_3_edge == number_of_facets` 且 `stl_verify_neighbors` 零不一致）已透過程式碼追蹤與隔離環境狀態快照驗證
- [x] 1.6 確認 skip-2nd-exact-check 候選在受測模型上的輸出等價性：三個代表模型、開關前後各 5 次、完整 Hollow STL 輸出 SHA-256 逐次逐模型相同（僅高面數壓力測試模型真正觸發跳過分支；未驗證整條 Ortho pipeline 或任意網格輸入的等價性）
- [x] 1.7 確認 skip-2nd-exact-check 候選之乾淨 A/B：同一診斷 binary、未啟用診斷插樁，高面數壓力測試模型約省 0.462 秒（8.4%）
- [x] 1.8 確認三個新增一般完整基座代表模型重測結果：第一次檢查後 `degenerate_facets` 皆為 0，`proto_skip_2nd_exact`／第二次檢查後快照標記在三份執行紀錄中皆未出現，第二次檢查結構性地未被觸發
- [x] 1.9 確認依事先議定停止判準，skip-2nd-exact-check 候選判定為不予採用、不移植至 production
- [x] 1.10 確認三個新增一般完整基座代表模型上量到的約 15.8～23.0 毫秒屬本輪診斷狀態快照本身成本，非第二次檢查耗時，已於文件中區分

## 2. OpenSpec 決策紀錄建立

- [x] 2.1 建立 `proposal.md`，記載 Why／What Changes／Capabilities／Impact，明示本提案不變更任何 production 程式碼
- [x] 2.2 建立 `specs/ortho-hollow-cpp-performance-decision/spec.md`，以 `### Requirement:` + `#### Scenario:` 格式記載：production 呼叫路徑、封裝版來源限制、C++ 子階段占比、已否決的 OpenVDB 候選、skip-2nd-exact-check 候選的驗證範圍與最終停止判準、診斷版與封裝版數字區分
- [x] 2.3 建立 `design.md`，記載決策脈絡（Context，含代表模型之用途代稱定義）、範圍界線（Goals／Non-Goals）、六項關鍵決策（D1～D6）與風險／取捨
- [x] 2.4 執行 `openspec validate perf-ortho-hollow-cpp-investigation --strict`，確認 proposal／specs／design 格式與 delta 皆有效——已執行，通過（`Change 'perf-ortho-hollow-cpp-investigation' is valid`）
- [ ] 2.5 執行 `openspec archive perf-ortho-hollow-cpp-investigation`，將本決策紀錄併入 `openspec/specs/`，完成歸檔——**待使用者審閱本提案內容後才執行，本輪不執行**

## 3. 邊界驗證

- [x] 3.1 確認 `agent/ortho_pipeline.py`、`agent/sla_operations.py`、`agent/config.py` 沒有任何差異（scoped 檢查：僅比對這些特定路徑，不代表整個 repository 為乾淨狀態）——已執行 `git status --short` 於此三個路徑，輸出為空
- [x] 3.2 確認 `third_party/prusaslicer_fork` 主 submodule checkout 沒有任何差異（分支、pin、工作目錄狀態與本提案開始前一致）——已確認：`dev` 分支、`22f2e310ae6cdbeb3f9f0419fcc8e9d03b4e3fe6`、working tree 乾淨、與 parent 記錄之 pointer 一致
- [x] 3.3 確認封裝產物（`slicer-engine\bin\slicer-engine.exe` 及其 manifest）沒有任何差異——已確認 SHA-256 為 `9f9adc62d62106fd269e85e9e52afca0c8207dce2b6f01a543c9cc713706cfa9`，與本輪調查全程記錄之值一致
- [x] 3.4 確認本次新增的內容僅限 `openspec/changes/perf-ortho-hollow-cpp-investigation/` 目錄本身——已執行 `git status --short openspec/`，僅顯示本次新增之此目錄

## 4. 使用者查證回饋核對與修正（使用者提出五類疑點後複查，本節記錄核對結果）

- [x] 4.1 確認 `design.md` D2／`spec.md`「其餘子階段合計占比皆為個位數百分比」是否對高面數壓力測試模型的 mesh 載入成立——**不成立，已修正**：重新核對 round 3 最終拆時表，該模型 mesh 載入單獨約 21.0%（1,086.85 ms／5,171.7 ms 均值），非個位數。`design.md` D2、`proposal.md`、`spec.md` 對應 Requirement 已改為區分小／中面數模型（個位數）與高面數壓力測試模型（mesh 載入例外約 21.0%），並加入其與 D4 兩次 `stl_check_facets_exact()` 的關聯說明
- [x] 4.2 確認三個新增一般模型面數是否「都介於中面數與高面數模型之間」——**不成立，已修正**：重新以 trimesh 核對清理後面數為 178,026／166,250／239,492；其中一個（166,250）低於中面數代表模型（166,672）。`design.md` Context／D5、`proposal.md`、`spec.md` 已改為如實描述範圍（清理後約 16.6 萬～23.9 萬面），不再宣稱嚴格介於兩者之間
- [x] 4.3 確認高面數壓力測試模型是否由既有模型拆分三角面產生、文件是否已交代此事——**使用者確認屬實，已補上**：以 trimesh 比對此模型與資料夾中其餘模型的 bounding box／volume，皆不吻合，目前無法將此模型對應到資料夾內任何現存模型。`design.md` Context、`spec.md` 已新增此模型之來源說明（使用者確認為人工增面樣本，但無法確認是哪一個原始模型），並明確要求不得對原始檔案的去向做出推斷、不得推測拆分自哪個現存模型、不得以其特徵推論一般 production 面數分布
- [x] 4.4 確認 production 路徑是否可正確描述為「使用封裝版 executable」——**過度簡化，已修正**：重新核對 `agent/config.py:33-34` 與 `README.md` 第 74／101／628／632 行，確認 `SLICER_ENGINE_BIN`／`PRUSA_SLICER_BIN` 環境變數可覆寫路徑解析，且 README 明確教學指向 dev-tree build；本輪調查全程未觀察到任何正在執行的 production 後端程序。`design.md` Context、`proposal.md`、`spec.md` 已改為區分「本輪量測選用」與「所有實際部署環境」
- [x] 4.5 確認「安全跳過條件」「等價性驗證」措辭是否可能被誤讀為已證明任意網格皆適用——**確有過度概括風險，已修正**：三個代表模型中僅高面數壓力測試模型的 `degenerate_facets>0`、實際觸發過此分支；另外兩個模型的比對是同一段程式碼、屬 vacuous 確認。所有測試模型在判斷點時皆無開放邊，此條件在開放邊輸入上的行為未經實測。`design.md` D4、`spec.md` 已將「安全跳過條件」改為「候選跳過條件」，並新增受測範圍與未涵蓋情況的明確限定
- [x] 4.6 確認「各跑五次，含一次不計入的暖機」與表格 `n=5` 是否一致、原始樣本數是否可確定——**一致，已獨立重新核對**：直接從 `C:\hdiag\equiv\ab\` 尚存的 36 個 STL 檔案（3 模型 × 2 arm × (5 計次 + 1 暖機)）重新計算 SHA-256，確認每模型每 arm 確實各有 5 個計次檔案（`run1`～`run5`）與 1 個獨立暖機檔案，雜湊比對結果與原始對話紀錄一致。但發現此 A/B 的逐次耗時本身未落地為獨立結果檔（僅印於終端機），已於 `design.md` D4、`proposal.md`、`spec.md` 補充此可追溯性限定：現存檔案只能重算 SHA-256，不能重算當時的耗時均值
- [x] 4.7 重新執行 `openspec validate perf-ortho-hollow-cpp-investigation --strict`，確認修正後格式與 delta 仍有效（通過）
- [x] 4.8 修正過程中發現 `spec.md` 新增的 `agent/config.py` 相對連結深度計算錯誤（少算一層目錄），已修正為 `../../../../../agent/config.py` 並以檔案系統實際核對可解析

## 5. 第二輪使用者查證回饋核對與修正（發現第一輪修正仍有三組文字不一致）

- [x] 5.1 確認 `proposal.md`／`spec.md`／`tasks.md` 是否仍將封裝版描述為「production 實際部署的 executable」或呼叫鏈必然到「封裝版」——**成立，已修正**：`proposal.md`（What Changes 最後一項）、`spec.md`（診斷版數字區分 Requirement 之 Scenario）、`tasks.md`（1.1）皆統一改為「依 `agent/config.py` 設定選定的 executable；本輪量測選用封裝版」，不再宣稱已核實實際部署使用哪一顆
- [x] 5.2 確認 `design.md`／`spec.md` 對高面數壓力測試模型的「遠超一般 production 輸入規模」「退化面很可能由拆分造成」「三個新增模型才是唯一具代表性的一般模型」等措辭是否超出現有證據——**成立，已修正**：
  - 「遠超一般 production 輸入規模」改為「面數遠高於本輪其他代表模型」（不再宣稱掌握一般 production 分布）
  - 「退化面很可能是拆分過程本身造成的產物」改為「成因未知（可能與拆分過程有關，也可能是原始模型本身既有的瑕疵，本輪未查證）」
  - 「三個新增模型才是本輪唯一具代表性的一般模型樣本」改為「三個新增模型是本輪新增的非增面一般樣本，並非本輪唯一的一般代表模型——小面數／中面數代表模型同樣是未經人工增面的一般完整基座模型，合計本輪共有 5 個一般模型皆未觸發第二次檢查」
  - `spec.md`「高面數壓力測試模型的來源」Requirement 同步修正，並新增對應 MUST NOT 條款
- [x] 5.3 確認 `design.md` Goals／Non-Goals 與 `tasks.md` 1.6 的「等價性證明」「端到端等價性驗證」措辭是否超出實際驗證範圍——**成立，已修正**：皆改為「受測模型的完整 Hollow STL 輸出逐位元相同」，並在 Non-Goals／1.6 中明確加註「僅高面數壓力測試模型真正觸發跳過分支，未驗證整條 Ortho pipeline 或任意網格輸入的等價性」
- [x] 5.4 全文搜尋「封裝版」「遠超一般」「很可能是拆分」「唯一具代表性」「唯一的一般代表模型」「端到端等價性」等關鍵詞，確認四份文件無殘留矛盾措辭——已執行，僅剩之相符字串皆為修正後、以 MUST NOT／並非等語法明確否定原措辭的正確用法
- [x] 5.5 重新執行 `openspec validate perf-ortho-hollow-cpp-investigation --strict`，確認修正後格式與 delta 仍有效（通過）

## 6. 第三輪使用者查證回饋核對與修正（模型來源敘述的因果框架問題）

- [x] 6.1 確認 `design.md` Context 與 `tasks.md` 4.3 是否把 bounding box／volume 不吻合，錯誤描述為「與單純拆分不改變外形體積的預期一致」——**成立，已修正**：這句話的因果框架本身有問題（不吻合不能說是「與預期一致」），已移除，改為單純陳述「目前無法將此模型對應到資料夾內任何現存模型」
- [x] 6.2 確認上述兩處是否據此對原始檔案的去向做出推斷——**成立，已修正**：移除「找不到對應的原始檔案」這類隱含「檔案曾存在、現已消失」的表述，改為不對去向做任何推斷
- [x] 6.3 確認「使用者確認模型經拆分三角面增面」與「無法確認是哪個原始模型」兩項限定是否保留——已確認，兩份文件修正後皆保留這兩項限定
- [x] 6.4 使用者本輪僅指定 `design.md` Context 與 `tasks.md` 4.3，但 `spec.md`「高面數壓力測試模型的來源」Requirement 同一句話（「目前 `tempTest` 資料夾中找不到對應的原始檔案」）有同樣的去向推斷問題，若不同步修正會與另外兩份文件互相矛盾——已比照同一原則一併修正 `spec.md` 該 Requirement 本文與其 Scenario，新增「MUST NOT 對原始檔案的去向做出推斷」條款
- [x] 6.5 重新執行 `openspec validate perf-ortho-hollow-cpp-investigation --strict`，確認修正後格式與 delta 仍有效（通過）

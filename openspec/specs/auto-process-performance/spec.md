# auto-process-performance Specification

## Purpose

定義 Auto Process（Ortho 自動化流程，`run_ortho_pipeline()`）與其周邊 API（`agent/ortho_pipeline.py`、`agent/model_classifier.py`、`agent/api_v2.py`）中，純效能／實作層級改動必須維持的正確性契約：Hollow-fit component split 的 `repair` 開關、Ortho cleaned mesh 物件重用、`confirm-model-type(target_type=intraoral_scan)` 的特徵擷取早退、以及 upload／save 對同一份 STL bytes 的重複驗證去重——這四項改動涵蓋的範圍與各自的等價判準。

**本能力最重要的一條是驗收線的表達方式**：與光柵化輸出不同，本能力涵蓋的中間產物是 mesh 拓撲與 Boolean 運算結果，改動後可能出現不同的 triangle／vertex 排列順序，因此 MUST NOT 以「輸出檔案 byte-for-byte 完全相同」作為統一驗收線；每項改動改以其自訂的外部可觀察行為與幾何語意等價判準（fit 判定、reload 幾何、分類確認結果、驗證的接受／拒絕行為）驗證。這條線同時是一道收錄門檻——Boolean Step 7～10 維持 `manifold3d.Manifold` 中間表示法的鏈式優化，因無法在兩個代表模型上同時通過 `is_watertight` 等價判準，已調查並放棄，未收錄於本能力（過程與根因分析見 `openspec/changes/archive/2026-09-15-optimize-auto-process-performance/design.md` D3 小節）。
## Requirements
### Requirement: 純效能改動不得改變外部可觀察行為與幾何語意

本能力涵蓋的所有改動（component split 的 repair 開關、mesh 物件重用、Boolean 中間表示法、特徵擷取的目標感知早退、上傳驗證去重）SHALL 屬純效能或實作層級變更：以同一份輸入，改動前後的外部可觀察行為（API 回應、判定結果、驗證的接受／拒絕行為）與幾何語意（體積、拓撲有效性、所佔據的空間）SHALL 等價。

與光柵化輸出不同，本能力涵蓋的中間產物可能是 mesh 拓撲（頂點與面的具體排列），其 byte-for-byte 表示 MAY 因改動而不同（例如 Boolean 表示法改變後 triangle ordering 不同）。因此本能力 MUST NOT 以「輸出檔案的 SHA-256 完全相同」作為統一驗收線；每一項改動 SHALL 由下列對應 requirement 定義其適用的等價判準。任何一項改動若在其自訂判準下無法證明等價，SHALL 不納入本能力，並須另行定義驗收方式與取得產品端同意。

#### Scenario: 各項改動各自定義驗收線
- **WHEN** 本能力下的任一項改動完成實作
- **THEN** 該項 SHALL 在下列對應 requirement 中定義具體的、可自動化驗證的等價判準
- **AND** MUST NOT 僅以目視比對或「看起來一樣」作為驗收依據

### Requirement: Hollow-fit component split 的 repair 開關不得改變 fit 判定

`hollow_mesh.split()` 的 `repair` 參數 SHALL 不影響 Hollow-fit 判斷的任何輸出：significant component 的篩選集合、`_min_width_xy()` 的計算結果、`_radial_center_opening_stats_xy()` 的統計結果，以及最終 `_hollow_fits` 判定 SHALL 與 `repair=True`（trimesh 預設值）時完全一致。

此不變式成立的基礎是 trimesh 的 `fill_holes()` 只能補單三角形或單四邊形的邊界洞，且從不新增頂點——Hollow-fit 判斷只讀取 component 的 `.vertices`／`.bounds` 與面數門檻，不讀取 `.is_watertight` 或其他僅由 repair 產生的 topology。

#### Scenario: repair 開關不影響幾何判定
- **WHEN** 以同一份 hollow mesh 分別在 `repair=True` 與 `repair=False` 下執行 component split 與 Hollow-fit 判斷
- **THEN** 兩次的 significant component 集合（依面數門檻篩選後）SHALL 相等
- **AND** 每個對應 component 的 `.vertices` SHALL 逐一相等
- **AND** 最終的 `_hollow_fits` 布林值與 `_skip_reasons` 內容 SHALL 相等

#### Scenario: 面數門檻邊界情況不產生非預期差異
- **WHEN** 某個 component 的面數在 `repair=True` 與 `repair=False` 下不同（因 repair 補上單三角形或單四邊形邊界洞）
- **THEN** 該差異 SHALL 被視為需要另行處理的例外，MUST NOT 被默認為安全

### Requirement: Ortho cleaned mesh 重用不得改變對齊後的幾何

`run_ortho_pipeline()` 對同一份 cleaned STL（`model_clean.stl`）的 mesh 物件重用 SHALL 不改變 U-arch 判斷結果，也 SHALL 不改變 Step 3 對齊（hollow 對齊至 input）所使用的 `input_mesh` 幾何——重用已載入的物件 SHALL 與重新從磁碟載入產生等價的 `.vertices`、`.faces`、`.bounds`。

#### Scenario: 重用物件與重新載入產生等價幾何
- **WHEN** 對同一份 `model_clean.stl`，分別以「U-arch 判斷後重用同一物件」與「U-arch 判斷與 Step 3 對齊各自獨立載入」兩種方式執行
- **THEN** Step 3 對齊使用的 `input_mesh` 在兩種方式下的 `.vertices`、`.faces`、`.bounds` SHALL 相等
- **AND** U-arch 判斷結果（是否提前以 `_complete_as_no_hollow` 結束 pipeline）SHALL 相等

> **Boolean Step 7～10 中間表示法（D3）已調查並放棄，未列入本次 ADDED Requirements。** 已實作「鏈式維持 `manifold3d.Manifold`」的版本並以 `001_p.stl`／`005_p.stl` 端到端驗證，證實會在至少一個代表模型上產生 `is_watertight` regression，且找不到對兩者都安全的部分鏈式組合。Step 7～10 維持修改前的逐步 `boolean_meshes()` 行為不變，因此本能力範圍內沒有新增或變更此處的 requirement。根因分析與嘗試矩陣見 [design.md](../../design.md) D3 小節；過程記錄見 [tasks.md](../../tasks.md) 群組 3。

### Requirement: confirm-model-type 略過 ProjectionShape 不得改變分類確認結果

`confirm_dental_model_type(mesh, target)` 在 `target == intraoral_scan` 時略過 `ProjectionShape` 特徵擷取，SHALL 不改變其回傳值。此不變式是既有 `dental-model-type-confirm` 能力「與完整分類的一致性（無例外）」requirement 的特例，SHALL 繼續對全部八種 `DentalModelType` 成立，包含此項優化涉及的 `intraoral_scan`。

`classify_dental_model()` 與 `confirm_dental_model_type()` 對其餘七種 target 的呼叫 SHALL 不受此項優化影響，繼續執行完整的 `ProjectionShape` 特徵擷取。

#### Scenario: 略過 ProjectionShape 不改變 intraoral_scan 的確認結果
- **WHEN** 對同一份 STL 呼叫 `confirm_dental_model_type(mesh, DentalModelType.INTRAORAL_SCAN)`，分別在「計算完整 ProjectionShape 特徵」與「略過 ProjectionShape 特徵擷取」兩種方式下執行
- **THEN** 兩次回傳的布林值 SHALL 相等

#### Scenario: 其餘 target 不受影響
- **WHEN** 對同一份 STL 呼叫 `confirm_dental_model_type(mesh, target)`，`target` 為 `intraoral_scan` 以外的任一 `DentalModelType`
- **THEN** `extract_model_features()` SHALL 執行完整的 ProjectionShape 特徵擷取，行為與本項優化前相同

#### Scenario: classify-model 端點不受影響
- **WHEN** 呼叫 `classify_dental_model(mesh)`（不知道目標類型）
- **THEN** `extract_model_features()` SHALL 執行完整的四組特徵擷取（PCA、ProjectionShape、OpenBoundary、FlatPlane），與本項優化前完全相同

### Requirement: Upload／save 驗證去重不得降低驗證涵蓋範圍

`_save_model_to_job()` 略過對已驗證 STL bytes 的重複 `_validate_stl_bytes()` 呼叫時，SHALL 僅適用於已在 `upload_model_file()` 完成過驗證的內容。透過 `use_model_from_job()` 引用其他 job 既有輸出檔案的內容、或透過 `add_models_to_slice_job()` 提交的任意 request body 內容，皆從未經過上傳時的驗證，`_save_model_to_job()` 對其執行的驗證 SHALL 是落地前唯一一次驗證，MUST NOT 被略過。

`upload_support_file()` 上傳的 `support_stl` 內容 SHALL 不在本 requirement 範圍內——該內容落地時直接寫檔，不經過 `_save_model_to_job()`，upload 時的驗證本來就是唯一一次，不存在重複驗證可去除。

驗證是否可略過的標記，其預設狀態（標記缺失）SHALL 等同於「需要驗證」，MUST NOT 預設為「已驗證」；即使呼叫端在 `add_models_to_slice_job()` 的 request body 中提供任意內容（包含企圖冒充該標記的欄位），最終落地於 `pending["models"]` 的標記值 SHALL 由伺服器端決定，MUST NOT 被 request body 內容覆寫。

#### Scenario: 已上傳並驗證的內容略過重複 parse
- **WHEN** 內容經 `upload_model_file()` 上傳並通過 `_validate_stl_bytes()` 驗證
- **THEN** `_save_model_to_job()` 落地該內容時 SHALL 不再次執行完整 `trimesh.load()` parse
- **AND** 若該內容原本會使 `_validate_stl_bytes()` 拒絕（例如已於上傳時被拒絕），此情況 SHALL 不可能發生（上傳階段已擋下）

#### Scenario: 引用其他 job 輸出的內容仍完整驗證
- **WHEN** 內容經 `use_model_from_job()` 引用其他 job 的既有輸出檔案（未經過上傳驗證）
- **THEN** `_save_model_to_job()` 落地該內容時 SHALL 執行完整的 `_validate_stl_bytes()` 驗證
- **AND** 內容格式錯誤或空 mesh 時 SHALL 回傳 `INVALID_MODEL` 錯誤，與本項優化前行為相同

#### Scenario: 驗證標記缺失時預設驗證
- **WHEN** `pending["models"]` 的項目不含驗證標記（例如未來新增的寫入路徑忘記設置）
- **THEN** `_save_model_to_job()` SHALL 執行完整驗證，MUST NOT 因標記缺失而略過

#### Scenario: 提交任意 request body 的內容無法冒充已驗證
- **WHEN** 呼叫端透過 `add_models_to_slice_job()` 提交的 request body 中包含企圖冒充驗證標記的欄位（例如宣稱自己已通過驗證）
- **THEN** 該內容於 `pending["models"]` 中的實際驗證標記 SHALL 仍為「需要驗證」
- **AND** `_save_model_to_job()` 落地該內容時 SHALL 執行完整的 `_validate_stl_bytes()` 驗證，MUST NOT 因 request body 中的欄位而略過

### Requirement: clean_input_for_manifold() boundary-edge 判定優化不得改變分類、repair 與輸出

`clean_input_for_manifold()` 以 `trimesh.grouping.group_rows(edges_sorted, require_count=1)` 取代 `np.unique(edges_sorted, axis=0, return_counts=True)` 判定 boundary edge 時，SHALL 只改變「哪些 edge 出現次數恰為 1」的計算方式，MUST NOT 改變分類結果、repair（KD-tree weld）是否觸發、weld 結果、`stats` 內容或最終輸出 mesh。

只有 occurrence count 恰好等於 1 的 edge SHALL 被視為 boundary edge；occurrence count 為 2、3 或更多次的 edge 的分類 SHALL 與現行版本完全一致。`mesh.edges_sorted` 的無向 edge 語意（每列已依端點排序）MUST NOT 被改變。

最終 `bd_verts` SHALL 保留現行版本呼叫 `np.unique()` 的行為（即候選演算法找出 boundary edge 之後，仍須再對攤平後的頂點集合呼叫一次 `np.unique()`），以維持與現行版本完全相同的頂點集合、dtype、升冪排序與元素順序——`bd_verts` 的順序會影響下游 KD-tree pair index、connected-component member 收集順序、每個連通分量代表 vertex 的選擇與 remap 結果，因此順序不一致 SHALL 視為不可接受的行為改變。

Duplicate face（相同 winding）、reversed duplicate face（相反 winding）與 occurrence count ≥3 的 non-manifold edge，SHALL 不被誤判為 boundary edge。`merge_vertices(digits_vertex=3)` 量化後才產生的 repeated-index face／`(v, v)` self-loop edge（zero-area 過濾只在 `merge_vertices()` 之前執行一次，不會二次過濾此類退化 face），其既有分類行為（包含被歸類為 boundary 的既有邊界情況）SHALL 維持不變，不因本次優化而被連帶修正。

Empty mesh 或 `trimesh.load()` 對空/退化 STL 回傳 `Scene` 的既有分支行為 SHALL 維持不變。

#### Scenario: occurrence count 恰為 1 才是 boundary edge
- **WHEN** 對同一份經 zero-area 過濾與 `merge_vertices(digits_vertex=3)` 處理後的 mesh，分別以現行版本（`np.unique(axis=0)` + count 篩選）與新版本（`group_rows(require_count=1)`）計算 `bd_verts`
- **THEN** 兩者回傳的 `bd_verts` 值、dtype 與元素順序 SHALL 完全相等
- **AND** 此結果 SHALL 對 watertight closed mesh、open boundary mesh、edge occurrence count 恰為 2／3／4 以上的 mesh 均成立

#### Scenario: boundary-edge 集合本身（非僅攤平後的頂點集合）逐一相等
- **WHEN** mesh 中存在 occurrence count ≥3 的 edge，且該 edge 的端點同時也是其他真正 boundary edge 的端點（即攤平去重後可能巧合得到相同的 `bd_verts`，即使誤選了 count≥3 的 edge 為 boundary）
- **THEN** 新版本與現行版本各自選出的 boundary-edge array（以 `np.unique(axis=0)` 的 canonical lexicographic 順序比較）SHALL 逐一相等，包含 dtype 與 shape，而不能只比較攤平去重後的 `bd_verts`
- **AND** 用來驗證此 scenario 的測資 SHALL 明確斷言其 occurrence count 陣列中確實存在對應的 3 或 4 以上數值，以確保測資本身在 preprocessing 後仍具有預期拓樸，而非僅憑案例名稱

#### Scenario: duplicate 與 reversed duplicate face 不被誤判為 boundary
- **WHEN** mesh 中含有相同 winding 的 duplicate face，或含有相反 winding 的 duplicate face（其三條邊的 occurrence count 因此變為 2）
- **THEN** 新版本 SHALL 與現行版本一樣，不將該 face 的任何一條邊分類為 boundary edge

#### Scenario: merge 後才產生的 repeated-index／self-loop edge 維持既有行為
- **WHEN** 某 face 的兩個頂點在輸入階段座標不同（面積 > 1e-9，通過 zero-area 過濾）但在 `merge_vertices(digits_vertex=3)` 量化後被合併為同一頂點，使該 face 產生 `(v, v)` 形式的 self-loop edge
- **THEN** 新版本對此 self-loop edge 的 boundary 分類結果（含被歸類為 boundary 的既有邊界情況）SHALL 與現行版本完全相同，不因本次優化而被連帶「修正」

#### Scenario: repair 觸發與輸出 mesh 一致（不觸發 weld 的輸入）
- **WHEN** 對同一份輸入（其 boundary vertices 彼此距離皆 ≥ `weld_tol`，因此 KD-tree weld 不會觸發），分別以現行版本與新版本執行完整 `clean_input_for_manifold()`（含 KD-tree weld、connected components、remap、face 過濾、`Trimesh(process=True)` 重建、export）
- **THEN** 兩者 KD-tree weld 皆不觸發、`stats`（`zero_area_dropped`／`merged_verts`／`boundary_welded`）、以及最終匯出 mesh 的 `vertices`／`faces` SHALL 完全相等

#### Scenario: repair 觸發與輸出 mesh 一致（實際觸發 weld 的輸入）
- **WHEN** 對同一份輸入，其中至少兩個 boundary vertices 彼此距離小於 `weld_tol`（且不會被更早的 `merge_vertices(digits_vertex=3)` 提前合併），分別以現行版本與新版本執行完整 `clean_input_for_manifold()`
- **THEN** 兩者 KD-tree `query_pairs` SHALL 皆找到至少一組 pair，實際執行 connected components、代表 vertex 選擇、remap 與 invalid-face 過濾，兩者 `stats["boundary_welded"]` SHALL 皆大於 0 且彼此相等
- **AND** `stats` 全部欄位與最終匯出 mesh 的 `vertices`／`faces` SHALL 完全相等
- **AND** 此 scenario 的驗證 MUST NOT 僅以「兩者皆為 0」的比較結果視為通過

#### Scenario: empty mesh／Scene 分支維持既有行為
- **WHEN** 輸入為空 STL（`trimesh.load()` 回傳 `Scene`）或處理後頂點/面數為零的 mesh
- **THEN** 新版本 SHALL 與現行版本走相同分支、產生相同的 `stats` 與匯出結果，不拋出未預期例外


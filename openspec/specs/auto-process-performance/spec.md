# auto-process-performance Specification

## Purpose
TBD - created by archiving change optimize-auto-process-performance. Update Purpose after archive.
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


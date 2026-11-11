## MODIFIED Requirements

### Requirement: Upload／save 驗證去重不得降低驗證涵蓋範圍

`_save_model_to_job()` 略過對已驗證 STL bytes 的重複 `_validate_stl_bytes()` 呼叫時，SHALL 僅適用於已在 `upload_model_file()` 完成過驗證的內容。透過 `use_model_from_job()` 引用其他 job 既有輸出檔案的內容、或透過 `add_models_to_slice_job()` 提交的任意 request body 內容，皆從未經過上傳時的驗證，`_save_model_to_job()` 對其執行的驗證 SHALL 是落地前唯一一次驗證，MUST NOT 被略過。

`upload_support_file()` 上傳的 `support_stl` 內容 SHALL 不在本 requirement 範圍內——該內容落地時直接寫檔，不經過 `_save_model_to_job()`，upload 時的驗證本來就是唯一一次，不存在重複驗證可去除。

驗證是否可略過的標記，其預設狀態（標記缺失）SHALL 等同於「需要驗證」，MUST NOT 預設為「已驗證」；即使呼叫端在 `add_models_to_slice_job()` 的 request body 中提供任意內容（包含企圖冒充該標記的欄位），最終落地於 `pending["models"]` 的標記值 SHALL 由伺服器端決定，MUST NOT 被 request body 內容覆寫。

`_validate_stl_bytes()` 本身的判準（header 與大小檢查，不解析 mesh）由 `stl-upload-validation` 定義；本 requirement 只規範何時呼叫、何時可略過。

#### Scenario: 已上傳並驗證的內容略過重複驗證
- **WHEN** 內容經 `upload_model_file()` 上傳並通過 `_validate_stl_bytes()` 驗證
- **THEN** `_save_model_to_job()` 落地該內容時 SHALL 不再次呼叫 `_validate_stl_bytes()`
- **AND** 若該內容原本會使 `_validate_stl_bytes()` 拒絕（例如已於上傳時被拒絕），此情況 SHALL 不可能發生（上傳階段已擋下）

#### Scenario: 引用其他 job 輸出的內容仍完整驗證
- **WHEN** 內容經 `use_model_from_job()` 引用其他 job 的既有輸出檔案（未經過上傳驗證）
- **THEN** `_save_model_to_job()` 落地該內容時 SHALL 執行 `_validate_stl_bytes()` 驗證
- **AND** 內容格式錯誤或空 mesh 時 SHALL 回傳 `INVALID_MODEL` 錯誤，與本項優化前行為相同

#### Scenario: 驗證標記缺失時預設驗證
- **WHEN** `pending["models"]` 的項目不含驗證標記（例如未來新增的寫入路徑忘記設置）
- **THEN** `_save_model_to_job()` SHALL 執行 `_validate_stl_bytes()` 驗證，MUST NOT 因標記缺失而略過

#### Scenario: 提交任意 request body 的內容無法冒充已驗證
- **WHEN** 呼叫端透過 `add_models_to_slice_job()` 提交的 request body 中包含企圖冒充驗證標記的欄位（例如宣稱自己已通過驗證）
- **THEN** 該內容於 `pending["models"]` 中的實際驗證標記 SHALL 仍為「需要驗證」
- **AND** `_save_model_to_job()` 落地該內容時 SHALL 執行 `_validate_stl_bytes()` 驗證，MUST NOT 因 request body 中的欄位而略過

## MODIFIED Requirements

### Requirement: 無法歸因者一律 fail-closed

當結果無法命中任何已知的成功、中性或失敗標記時，系統 SHALL 採 fail-closed：job 狀態 MUST 為 `FAILED`，`error_code` 為 `SUPPORT_GENERATION_FAILED`，並保留原始 `stdout` / `stderr`。系統 MUST NOT 在無正向證據時將未知情況推定為成功或中性。

（原本的「寫檔失敗但 exit code 為 0」情境移到下方的「支撐 mesh 寫檔失敗須歸因為 SUPPORT_MESH_EXPORT_FAILED」：寫檔失敗現在有專屬代號，不再是無法歸因。）

#### Scenario: 同時偵測到互斥標記
- **WHEN** `stdout` 同時含成功標記與 `SUPPORT_NOT_NEEDED` 標記（例如非預期的多物件輸出）
- **THEN** 系統走 fail-closed，job 狀態為 `FAILED`，`error_code` 為 `SUPPORT_GENERATION_FAILED`
- **AND** 系統 MUST NOT 任選其一標記作為權威結論

## ADDED Requirements

### Requirement: 支撐 mesh 寫檔失敗須歸因為 SUPPORT_MESH_EXPORT_FAILED

支撐專用模式下，引擎無法寫出 `*_support.stl` 時 SHALL 在 stdout 輸出 `code` 為 `SUPPORT_MESH_EXPORT_FAILED` 的結構化錯誤行，stderr 照舊印 `Failed to export support mesh to <path>`，並以非 0 的 exit code 結束。分類器 SHALL 將其歸因為 `SUPPORT_MESH_EXPORT_FAILED`，代號與英文字串任一命中即可。

切片模式下同一個寫檔失敗 MUST NOT 讓切片失敗：`.sl1` 在寫支撐 STL 之前已完成，支撐 STL 只供 UI 顯示（與同檔預覽 ZIP 寫檔失敗的處理一致）。

#### Scenario: 新版引擎寫檔失敗
- **WHEN** 支撐專用模式下 `*_support.stl` 無法寫入
- **THEN** stdout 含 `PHZ_ERROR` 行，`code` 為 `SUPPORT_MESH_EXPORT_FAILED`
- **AND** exit code 不為 0
- **AND** job 狀態為 `FAILED`，`error_code` 為 `SUPPORT_MESH_EXPORT_FAILED`
- **AND** 此情境 MUST NOT 被歸類為 `SUPPORT_NOT_NEEDED`

#### Scenario: 舊版引擎只有英文字串
- **WHEN** `stderr` 含 `Failed to export support mesh`、無支撐 STL、無結構化錯誤行
- **THEN** job 狀態為 `FAILED`，`error_code` 為 `SUPPORT_MESH_EXPORT_FAILED`

#### Scenario: 切片模式不受影響
- **WHEN** 切片模式（`--export-sla --export-support-stl`）下 `*_support.stl` 無法寫入
- **THEN** `.sl1` 照常產出，exit code 為 0，stdout MUST NOT 含 `PHZ_ERROR` 行
- **AND** 切片結果判定為成功

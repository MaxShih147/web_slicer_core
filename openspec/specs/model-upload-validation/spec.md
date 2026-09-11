# model-upload-validation Specification

## Purpose
確保上傳至切片 job 的模型位元組在落地前經過驗證，且該驗證僅執行與判定相關的工作。驗證的語意限縮為兩項：能否被解析為 STL，以及解析結果是否為空網格；頂點合併等對判定無貢獻的幾何處理 MUST NOT 執行。這使大型模型（17.64 MB、369,843 面）的單次驗證由 774.59 ms 降至約 104 ms，而對外的攔截行與錯誤語意完全不變。
## Requirements
### Requirement: 模型驗證的判定語意須限縮為兩項，且不得執行與判定無關的幾何處理

模型位元組的驗證 SHALL 僅判定兩件事：該位元組能否被解析為 STL，以及解析結果是否為空網格。

驗證 MUST NOT 執行與上述兩項判定無關的幾何處理。具體而言，`_validate_stl_bytes()` 中的 `trimesh.load()` SHALL 明確傳入 `process=False`，以跳過頂點合併等對判定無貢獻的處理步驟。

此規範適用於 `_validate_stl_bytes()` 的所有呼叫端，包含模型上傳、支撐檔上傳、模型落地，以及 boolean 運算的 `mesh_a` / `mesh_b` 驗證。

#### Scenario: 大型模型的驗證耗時顯著下降

- **假設** 一份 18,492,234 bytes（17.64 MB、369,843 個三角面）的有效二進位 STL
- **當** 執行模型驗證
- **則** 驗證 SHALL 通過
- **且** 耗時 SHALL 顯著低於採用 `process=True` 時的耗時（實測基準：774.59 ms 降至 104.46 ms）

#### Scenario: 對外的錯誤語意不因驗證方法改變而改變

- **假設** 一份無法被解析為 STL 的位元組
- **當** 執行模型驗證
- **則** 系統 SHALL 拋出 `INVALID_MODEL`
- **且** 該錯誤型別與訊息語意 MUST NOT 因改用 `process=False` 而改變

### Requirement: 六個無效模型邊界案例的攔截行為須與變更前完全一致

改用 `process=False` 後，系統對無效模型的攔截行為 SHALL 與改用前完全相同。下列六個邊界案例 SHALL 全數納入單元測試，作為此性質的迴歸保護。

系統 MUST NOT 因為跳過幾何處理而放行任何在變更前會被攔截的輸入。

#### Scenario: 空 bytes 被攔截

- **當** 傳入長度為 0 的位元組
- **則** 驗證 SHALL 失敗並拋出 `INVALID_MODEL`

#### Scenario: 標頭宣告三角面數為 0 被攔截

- **假設** 一份僅含 80 bytes 標頭與一個值為 0 的 32 位元三角面數欄位的二進位 STL
- **當** 執行驗證
- **則** 驗證 SHALL 失敗並拋出 `INVALID_MODEL`
- **且** 攔截 SHALL 由「空網格」判定（`len(mesh.faces) == 0`）達成

#### Scenario: 標頭宣告面數但三角面資料被截斷時被攔截

- **假設** 一份標頭宣告 10 個三角面、但其後不含任何三角面資料的二進位 STL
- **當** 執行驗證
- **則** 驗證 SHALL 失敗並拋出 `INVALID_MODEL`

#### Scenario: 純亂數位元組被攔截

- **假設** 一段不構成任何已知 STL 結構的隨機位元組
- **當** 執行驗證
- **則** 驗證 SHALL 失敗並拋出 `INVALID_MODEL`
- **且** 底層解析器拋出的任何例外型別 SHALL 被轉換為 `INVALID_MODEL`，MUST NOT 洩漏為未處理的內部錯誤

#### Scenario: ASCII STL 的空 solid 被攔截

- **假設** 一份內容為空 solid 宣告（`solid x` 緊接 `endsolid x`）的 ASCII STL
- **當** 執行驗證
- **則** 驗證 SHALL 失敗並拋出 `INVALID_MODEL`

#### Scenario: 單一零面積三角面被接受

- **假設** 一份標頭宣告 1 個三角面、且該三角面的三個頂點座標皆為零的二進位 STL
- **當** 執行驗證
- **則** 驗證 SHALL 通過
- **且** 此行為 SHALL 與採用 `process=True` 時一致——本規範 MUST NOT 藉此變更收緊或放寬既有的判定範圍

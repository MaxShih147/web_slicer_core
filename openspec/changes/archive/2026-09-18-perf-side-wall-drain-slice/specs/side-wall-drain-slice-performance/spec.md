## ADDED Requirements

### Requirement: 三角形 Z min/max broad-phase 篩選不得改變外部可觀察行為

`slice_mesh_at_z()`（`agent/ortho_pipeline.py`）新增的三角形 Z min/max broad-phase 篩選 SHALL 屬純效能／實作層級變更。以同一份 mesh 與同一個 `z_world`，改動前後 `slice_mesh_at_z()` 回傳的 loop 數量、每個 loop 內的點順序，以及每個座標值，SHALL 滿足 `np.array_equal`（記憶體中的 numpy 陣列逐元素完全相同；本要求只涵蓋已實際驗證過的陣列層級比對，不涉及任何序列化檔案的 bytes 比對）——此段程式碼路徑是純 Python/NumPy 幾何運算，未引入任何 Boolean 中間表示法或其他不確定性來源，因此驗收線 SHALL 以此陣列等價表示，而非僅幾何語意等價。

`generate_side_wall_drains()`（Step 9/10 Boolean 之前）的回傳值，驗收線 SHALL 為 `None`/非 `None` 判定一致、`.vertices`／`.faces` `np.array_equal`、孔數一致；只有經過 Step 9/10 Boolean 之後的完整 pipeline 最終輸出，才適用另一項語意等價判準（見下方「完整 pipeline 最終輸出的語意等價判準」）。

#### Scenario: `slice_mesh_at_z()` 輸出 np.array_equal
- **WHEN** 以同一份 mesh 與同一個 `z_world`，分別使用改動前（對全部三角形跑 scalar 迴圈）與改動後（先做 broad-phase 篩選再跑相同 scalar 迴圈）執行 `slice_mesh_at_z()`
- **THEN** 兩者回傳的 loop 數量 SHALL 相同
- **AND** 每個對應 loop 的 shape SHALL 相同
- **AND** 每個對應 loop 的座標陣列 SHALL `np.array_equal`

#### Scenario: `generate_side_wall_drains()` 回傳值 np.array_equal 與 None 判定一致
- **WHEN** 以同一組 `outer_shell`／`inner_shell`／參數，分別使用改動前後的 `generate_side_wall_drains()` 執行
- **THEN** 兩者的 `None`/非 `None` 判定 SHALL 相同
- **AND** 非 `None` 時，兩者回傳 mesh 的 `.vertices`／`.faces` SHALL `np.array_equal`
- **AND** 孔數 SHALL 相同（`.vertices`／`.faces` `np.array_equal` 已蘊含孔數相同，因為最終 mesh 完全由通過哪些候選 gate 決定）

### Requirement: Broad-phase 篩選條件 SHALL 與「至少存在一條 strict edge crossing」數學等價，不得產生 false negative

三角形 Z min/max 篩選條件 `face_z_min < z_world < face_z_max`（嚴格不等式）SHALL 精確等價於「該三角形三條邊中，至少存在一條端點嚴格分處切平面兩側的邊」（即至少一條邊滿足既有 `d0 * d1 < 0` 判定），不是保守估計或啟發式近似：三角形三頂點的 Z 值若全部 `>= z_world` 或全部 `<= z_world`（含恰觸 `z_world`），三條邊中任一邊的 `d0 * d1` SHALL 恆為非負，不可能滿足既有判定式；此篩選條件 SHALL NOT 排除任何原本存在至少一條 strict edge crossing 的三角形，因此也 SHALL NOT 排除任何原本會產生 segment 的三角形（因為產生 segment 的必要條件正是存在 strict edge crossing）。

**此等價性明確不涵蓋「一定產生 segment」**：候選集合 MAY 保留部分三角形，其三條邊中恰好只有 1 條滿足 `d0*d1<0`（例如頂點 Z 為 `(-1, 0, +1)`、切平面為 `0` 時），因而不滿足既有「恰需 2 個交點才視為一條 segment」的規則，不會產生 segment。此為候選篩選允許的正常情況：候選集合只決定哪些三角形進入既有、本次未變更的 scalar 迴圈，最終是否產生 segment 仍完全由該既有迴圈的既有邏輯決定。

#### Scenario: 三頂點全在切平面一側的三角形被正確排除
- **WHEN** 某三角形三個頂點的 Z 值全部大於 `z_world`，或全部小於 `z_world`
- **THEN** 該三角形 SHALL NOT 出現在 broad-phase 篩選後的候選集合中
- **AND** 若強制對該三角形執行既有 scalar 迴圈，其三條邊 SHALL 沒有任何一邊滿足 `d0 * d1 < 0`

#### Scenario: 三頂點分屬切平面兩側的三角形被正確保留
- **WHEN** 某三角形至少一個頂點的 Z 值小於 `z_world`、至少一個頂點的 Z 值大於 `z_world`
- **THEN** 該三角形 SHALL 出現在 broad-phase 篩選後的候選集合中

#### Scenario: 候選集合可能保留最終不產生 segment 的三角形，且不影響正確性
- **WHEN** 某三角形被 broad-phase 篩選納入候選（`face_z_min < z_world < face_z_max` 成立），但其三條邊中只有 1 條滿足嚴格 `d0*d1<0`（例如三頂點 Z 值為 `(-1, 0, +1)`，`z_world=0`）
- **THEN** 該三角形 SHALL 進入既有 scalar 迴圈檢查
- **AND** 該迴圈找到的交點數 SHALL 少於 2 個，依既有「恰需 2 個交點才視為一條 segment」規則，SHALL NOT 產生 segment
- **AND** 此結果 SHALL 與改動前（未經 broad-phase 篩選、直接對此三角形跑既有 scalar 迴圈）完全一致

#### Scenario: 恰有頂點位於切平面上的邊界情況與既有行為一致
- **WHEN** 某三角形恰有一個頂點的 Z 值等於 `z_world`，其餘兩頂點分屬異側或同側
- **THEN** 該三角形是否產生 segment、產生幾個交點，SHALL 與改動前的既有 scalar 迴圈行為完全一致（包含既有「恰需 2 個交點才視為一條 segment」的既有語意，不因本次篩選而改變）

### Requirement: Z-bounds 生命週期不得使用全域或 Trimesh 快取

`generate_side_wall_drains()` 對 inner shell 與 outer shell 的 Z-bounds 管理 SHALL 遵循下列生命週期：inner shell 只切一次，其 Z-bounds SHALL 由 `slice_mesh_at_z()` 內部建立，該次呼叫返回後 SHALL NOT 跨呼叫被外層持有參照——`generate_side_wall_drains()` 的函式作用域中 SHALL NOT 保留一個跨越該次呼叫的 inner bounds 具名變數；outer shell 的 Z-bounds SHALL 只建立一次，持有至 `generate_side_wall_drains()` 返回為止，供其 `+1.0`／`+0.5`／`+2.0` 三次 retry 呼叫共用。

Z-bounds 的計算與持有 SHALL NOT 使用任何全域變數、模組層級快取，或掛在 mesh 物件上的快取（例如 Trimesh 的 `._cache` 機制）；MUST NOT 使用 `del` 或 `gc.collect()` 等手動記憶體操作管理其生命週期。此處「不跨呼叫持有」僅指 Python 物件參照的生命週期，SHALL NOT 被解讀為對 CPython/NumPy allocator 何時將底層記憶體歸還作業系統做出任何保證。

#### Scenario: outer shell 三次 retry 共用同一份 bounds
- **WHEN** outer shell 在 `z_drain+1.0` 找不到任何 loop，依序 retry `z_drain+0.5`、`z_drain+2.0`
- **THEN** 三次 `slice_mesh_at_z()` 呼叫 SHALL 使用同一份透過 `compute_face_z_bounds(outer_shell)` 算出的 `face_z_bounds`，SHALL NOT 為每次 retry 重新計算

#### Scenario: mesh 被修改後重新呼叫不會取得過期 bounds
- **WHEN** 同一個 mesh 物件在兩次 `generate_side_wall_drains()` 呼叫之間被外部程式修改（例如頂點被平移）
- **THEN** 第二次呼叫計算出的 Z-bounds SHALL 反映修改後的最新幾何，SHALL NOT 因任何快取機制而回傳修改前的過期值

#### Scenario: 傳入預先計算的 bounds 與函式內部自行計算結果一致
- **WHEN** 呼叫 `slice_mesh_at_z(mesh, z_world, face_z_bounds=compute_face_z_bounds(mesh))` 與 `slice_mesh_at_z(mesh, z_world)`（不傳入 `face_z_bounds`，由函式內部自行計算）
- **THEN** 兩者回傳的 loop 結果 SHALL `np.array_equal`

### Requirement: 完整 pipeline 最終輸出的語意等價判準

`generate_side_wall_drains()` 的輸出經 Step 9/10 `boolean_meshes()` 後產生的最終 `ortho_result.stl`，因 `boolean_meshes()` 內部將頂點轉為 `float32` 餵給 `manifold3d.Manifold` 並重建 `trimesh.Trimesh`，SHALL NOT 以 `np.array_equal` 作為驗收線；驗收本次（側壁排液孔 slicing broad-phase 篩選與 Z-bounds 生命週期）效能變更時，改動前後的完整 pipeline 最終輸出 SHALL 滿足下列語意等價判準：faces／vertices 數量相同、volume 相對誤差 `<= 1e-6`、bounds 絕對誤差 `<= 1e-6` mm、`is_watertight` 與固定的 pre-change reference 執行結果相同。

若某模型的 pre-change reference 本身 `is_watertight` 即為 `False`（例如網格品質或 Boolean 鏈本身既有的限制），此為該模型在既有實作下的既有狀況，該 `False` 本身 SHALL NOT 被視為本次效能變更造成的 regression，也 MUST NOT 因此放寬前述 faces／vertices／volume／bounds 等其他判準。此限定僅適用於驗收本次效能變更是否造成 regression，MUST NOT 被解讀為規定該模型的 `is_watertight` 未來永久必須維持 `False`，也不限制未來另案針對該模型 watertightness 問題的修正工作——屆時的驗收判準由該另案自行定義新的 reference 基準。

#### Scenario: 兩模型的完整 pipeline 最終輸出語意等價
- **WHEN** 對同一份真實輸入模型，分別以改動前後的 `run_ortho_pipeline()` 端到端執行完整 Auto Process
- **THEN** 兩次輸出的 `ortho_result.stl` faces／vertices 數量 SHALL 相同
- **AND** volume 相對誤差 SHALL `<= 1e-6`
- **AND** bounds 絕對誤差 SHALL `<= 1e-6` mm
- **AND** `is_watertight` SHALL 與該模型固定的 pre-change reference 執行結果相同

#### Scenario: pre-change reference 本身非 watertight 時，該既有狀況不視為本次變更的 regression
- **WHEN** 某模型的 pre-change reference 執行中，完整 pipeline 最終輸出的 `is_watertight` 為 `False`
- **THEN** 驗收本次效能變更時，改動後同一模型（相同輸入）的 `is_watertight` SHALL 與該 reference 相同（即 `False`）
- **AND** 此 pre-change 既有的 `False` 值本身 MUST NOT 被視為本次效能變更造成的 regression
- **AND** 本 Scenario MUST NOT 被解讀為限制未來另案修正該模型既有 watertightness 問題的工作範圍

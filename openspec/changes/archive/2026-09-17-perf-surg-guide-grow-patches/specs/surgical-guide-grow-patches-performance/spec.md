## ADDED Requirements

### Requirement: `_grow_patches()` per-patch statistics 優化不得改變外部可觀察行為

`_grow_patches()`（`agent/auto_orient_surg_guide.py`）的 per-patch statistics（Step 5：面數 `<5` 的 patch 略過統計、重用 `mesh.face_area`、停止計算 `max_angle_deg`）SHALL 屬純效能／實作層級變更：以同一份輸入，改動前後 `_find_guide_direction()` 與 `compute_auto_orientation_surg_guide_detail()` 的外部可觀察行為 SHALL 等價。

與光柵化輸出不同，本能力涵蓋的中間產物（`_Patch.area`／`.avg_normal`／`.center`）可能因浮點運算路徑改變（`mesh.face_area` 的向量化 reduction vs. 逐 face `_norm(_cross(...))` 重算；`numpy.sum` 的 pairwise 累加 vs. Python 逐面 `+=`）而有極小的捨入層級差異，MUST NOT 以「數值完全相同」作為驗收線；驗收線改以「該差異不改變任何 gate、候選判定或最終方向」表達。

#### Scenario: patch face membership 與候選判定不受影響
- **WHEN** 以同一份輸入分別在修改前後執行 `_weld_and_build()` + `_grow_patches()`
- **THEN** 產生的 patch 數量與每個 patch 的 face membership（面索引集合）SHALL 完全相同
- **AND** 面數 `>=5` 的 patch 集合（進入後續導孔判定的候選集合）SHALL 完全相同

#### Scenario: 最終方向與 rotation 輸出不受影響
- **WHEN** 以同一份輸入分別在修改前後呼叫 `_find_guide_direction()` 與 `compute_auto_orientation_surg_guide_detail()`
- **THEN** drill candidate 集合、選中的分支（正常導孔判定 vs. fallback）、最佳 patch、`res.dir`、`rotation_rad` SHALL 完全相同
- **AND** 若 `.area`／`.avg_normal`／`.center` 存在浮點差異，該差異 SHALL NOT 造成任何 PCA 直徑/aspect gate、scanline 判定、conn-edge 或 220° turn-angle gate 的通過/拒絕結果改變

### Requirement: 面數 `<5` 的 patch 略過統計必須有全部消費者已預先過濾為前提

`_grow_patches()` SHALL 只對 `len(P.faces) >= 5` 的 patch 計算 `area`／`avg_normal`／`center`；面數 `<5` 的 patch SHALL 保留 `_Patch` dataclass 預設值（`area=0.0`、`avg_normal=zeros(3)`、`center=zeros(3)`）。此優化的前提是：`_grow_patches()` 的**所有**呼叫端在讀取這些欄位前 SHALL 已先以 `len(P.faces) < 5`（或等價條件）短路排除面數不足的 patch。若未來新增任何讀取 `.area`／`.avg_normal`／`.center` 的呼叫端，該呼叫端 SHALL 在讀取前自行檢查面數門檻，MUST NOT 假設這些欄位對面數 `<5` 的 patch 有意義的值。

#### Scenario: 面數不足的 patch 保留預設值
- **WHEN** `_grow_patches()` 處理一個面數 `<5` 的 patch
- **THEN** 該 patch 的 `.area` SHALL 為 `0.0`
- **AND** 該 patch 的 `.avg_normal` SHALL 為零向量
- **AND** 該 patch 的 `.center` SHALL 為零向量

### Requirement: 面積計算 SHALL 重用 `mesh.face_area`，不得重新計算

`_grow_patches()` 的 per-patch 面積加總 SHALL 直接索引 `mesh.face_area`（由 `_weld_and_build()` 向量化計算），MUST NOT 對同一批 face 重新以 `_norm(_cross(...))` 或等價方式重算面積。

#### Scenario: patch 面積等於其 face 在 mesh.face_area 中的加總
- **WHEN** 取得一個面數 `>=5` 的 patch 的 `.area`
- **THEN** 該值 SHALL 等於 `mesh.face_area` 中該 patch 所有 face 索引對應值的加總（誤差在浮點累加順序造成的捨入範圍內）

### Requirement: `max_angle_deg` 不再計算，但欄位保留

`_grow_patches()` SHALL 不再計算 `_Patch.max_angle_deg` 的值；`_Patch` dataclass SHALL 繼續保留此欄位（預設值 `0.0`），以維持與既有程式碼／未來可能呼叫端的結構相容性。

#### Scenario: max_angle_deg 恆為預設值
- **WHEN** `_grow_patches()` 處理任一 patch（無論面數多寡）
- **THEN** 該 patch 的 `.max_angle_deg` SHALL 維持 `_Patch` dataclass 的預設值 `0.0`

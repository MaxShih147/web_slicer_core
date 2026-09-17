# surgical-guide-bfs-region-growing-performance Specification

## Purpose
TBD - created by archiving change perf-surg-guide-bfs-region-growing. Update Purpose after archive.
## Requirements
### Requirement: BFS region growing 向量化不得改變 patch 分組結果

`_grow_patches()`（`agent/auto_orient_surg_guide.py`）BFS 區段（Step 4）的向量化 SHALL 屬純效能／實作層級變更：以同一份輸入，改動前後產生的 patch 數量與每個 patch 的 face membership（面索引集合）SHALL 完全相同。

與 Step 5 per-patch statistics（`surgical-guide-grow-patches-performance` 能力）的連續數值不同，BFS 的門檻比較（`_dot(n, n_seed) >= cos_grow`）是離散的 accept/reject 判定，直接決定一個 face 屬於哪個 patch（或不屬於任何 patch）。因此本能力 MUST NOT 以「數值合理接近」作為驗收線；驗收線 SHALL 是逐 face 的 patch membership 完全相同。

#### Scenario: patch 分組逐 face 相同
- **WHEN** 以同一份輸入分別在修改前後執行 `_weld_and_build()` + `_grow_patches()`
- **THEN** 產生的 patch 數量 SHALL 完全相同
- **AND** 每個 patch 的 face membership（面索引集合）SHALL 完全相同，不允許任何一個 face 被分配到不同的 patch 或退化狀態（`-2`）

#### Scenario: 下游結果不受影響
- **WHEN** 以同一份輸入分別在修改前後呼叫 `_find_guide_direction()` 與 `compute_auto_orientation_surg_guide_detail()`
- **THEN** drill candidate 集合、選中的分支（正常導孔判定 vs. fallback）、最佳 patch、`res.dir`、`rotation_rad` SHALL 完全相同

### Requirement: 固定 seed 法向量比對語意不得被取代

BFS SHALL 繼續以「每個 patch 有一個固定的 seed 法向量，每個候選 face 都與該 seed 比較」的方式成長，MUST NOT 被取代為「候選 face 與觸發它的相鄰 face 比較」或任何形式的一般圖論 connected-components 演算法——兩者在法向量沿路徑緩慢漂移的情境下會產生不同的分組結果。

#### Scenario: 沿路徑漂移的曲面不因向量化而改變分組邊界
- **WHEN** 一個 patch 的候選 face 序列中，每一步與前一個 face 的法向量夾角小於 2°，但相對該 patch 最初的 seed 法向量夾角已超過 2°
- **THEN** 該 face SHALL 不被併入該 patch（與修改前的固定-seed 比對語意一致），即使一般 connected-components 演算法會將其視為同一分量

### Requirement: 門檻比較的浮點精度路徑不得從 float32 改變為 float64

`_dot(n, n_seed) >= cos_grow` 這個門檻比較，若以 inline 乘加取代 `_dot()` 函式呼叫，SHALL 維持與現行 `_dot()` 相同的精度路徑——三項乘加在 float32 精度下完成，僅最終結果轉型為 float64——MUST NOT 因為抽出純量分量（例如透過 Python `float()`）而不知不覺把整個乘加運算的精度提升為 float64。

此要求的理由：`model_classifier.py::_drill_region_growing()` 的對應實作是以 Python `float()` 抽出 seed 分量，其乘加運算因 numpy 型別提升規則而全程以 float64 進行；直接照搬會改變這個離散門檻比較在邊界情況下的行為。**這不是理論風險**——已用真實模型（`SurgicalGuide_4.stl`）量到 5 組實際的 accept/reject 翻轉案例（float32 生產路徑與 float64 classifier 路徑對相同的候選比較給出不同判定）。雖然這 5 個案例最終未改變該模型的 patch 分組結果（BFS 具路徑依賴性，某次被拒絕的候選仍可能經由另一條路徑併入相同的最終 patch），但已證實此風險真實存在，不因偶發案例未造成可觀察差異而降低其不可接受性。

#### Scenario: inline dot product 精度驗證
- **WHEN** BFS 迴圈以 inline 乘加取代 `_dot(n, n_seed)` 的函式呼叫
- **THEN** 該乘加運算 SHALL 在 float32 精度下完成，與現行 `_dot()` 的內部運算精度一致
- **AND** 對同一組輸入，`_dot(n, n_seed) >= cos_grow` 的比較結果 SHALL 與現行實作完全相同

#### Scenario: 已知臨界案例的精度驗證
- **WHEN** 對 `SurgicalGuide_4.stl` 上已識別出的 5 組 float32/float64 精度分歧候選（`(patch, face)` 配對）計算 inline dot product
- **THEN** 計算結果 SHALL 與現行 `_dot()` 的 float32 路徑 bit-exact 相同，SHALL NOT 出現與 classifier-style float64 路徑相同的判定

### Requirement: 退化法向量檢查可安全向量化

BFS 迴圈內對候選 face 的退化法向量檢查（`_norm(face_n[fidx]) < 0.5`）SHALL 允許改為迴圈外預先向量化計算（`np.linalg.norm(mesh.face_n, axis=1)`，對 float32 輸入回傳 float32 陣列），因為 `mesh.face_n` 的每一列在非退化情況下已是單位向量（norm ≈ 1.0）、退化情況下為零向量（norm = 0.0），兩種輸入相差懸殊，向量化計算（float32）與現行逐次呼叫 `_norm()` 之間即使存在浮點精度差異，也不足以影響 `< 0.5` 這個門檻的判定結果。

補充說明：`agent/auto_orient_surg_guide.py::_norm()` 的實際實作是把每個分量先以 Python `float()` 轉成雙精度再平方相加、開根號——`_norm()` 本身已是全程 **float64** 運算，與 `_dot()`（全程 float32，僅最終轉型）是不同的精度路徑，不應混淆。

#### Scenario: 退化面判定不受向量化影響
- **WHEN** 以同一份輸入分別在修改前後判定每個 face 是否為退化面（法向量長度 `< 0.5`）
- **THEN** 判定結果 SHALL 完全相同


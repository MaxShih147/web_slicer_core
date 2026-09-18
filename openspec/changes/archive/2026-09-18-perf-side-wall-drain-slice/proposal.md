## Why

Auto Process Ortho pipeline Step 6（`agent/ortho_pipeline.py::generate_side_wall_drains()`）的前置調查（source tracing + 真實模型 baseline，`001_p.stl`／`005_p.stl`／`DentalModel_1M.stl`／`DentalModel_NeedRotate.stl` 四個代表模型）確認：`agent/ortho_pipeline.py::slice_mesh_at_z()` 對 inner／outer shell 整個 mesh 的所有三角形跑純 Python scalar 迴圈找 Z 平面交點，是 Step 6 目前最大且最普遍的成本。

兩項數字來源不同、分開陳述：
- **4 個代表模型的真實 Step 6 執行**：`slice_inner + slice_outer` 合計佔該次 Step 6 wall time 的 **67%～99%**（`001_p.stl` 66.6%、`005_p.stl` 72.9%、`DentalModel_1M.stl` 69.7%、`DentalModel_NeedRotate.stl` 98.6%），即使在候選評估幾乎全免（`DentalModel_NeedRotate.stl`，僅 1/12 孔成功）的低產出案例也不例外。
- **獨立的 slicing diagnostic**（16 組真實 mesh／z-level 組合：inner 的單一 z-level，加上 outer 的 `+1.0`／`+0.5`／`+2.0` 三個 z-level）：用於量測候選面比例、各子階段耗時與正確性；其中 outer 的 `+0.5`／`+2.0` 這兩個 z-level 在這 4 個代表模型的真實 pipeline 執行中皆未曾進入 retry（`+1.0` 都直接成功），僅作為 diagnostic 的量測對象，不代表這 4 個模型的真實 Step 6 執行路徑。

這是本次調查排序出的第一個 prototype 目標，其餘已識別但本次不處理的成本（inner-poly ray/segment 迴圈、outer-poly point-in-polygon 迴圈）留待後續獨立評估。

## What Changes

- **新增 `compute_face_z_bounds()`**（`agent/ortho_pipeline.py`）：直接由 `mesh.vertices[:, 2]`／`mesh.faces` 算出每個三角形的 Z min/max（不建立完整 `mesh.triangles`、不轉 float32，維持原生 dtype）。
- **`slice_mesh_at_z()` 新增 broad-phase 篩選**：以 `candidate_face_ids = np.flatnonzero((face_z_min < z_world) & (face_z_max > z_world))` 篩掉 Z 範圍完全落在切平面單側（或恰觸切平面）的三角形，才對候選子集合執行**逐行不變**的既有 scalar edge/intersection 迴圈與 spatial-hash loop chaining。此篩選條件在數學上精確等價於「該三角形至少存在一條端點嚴格分處切面兩側的邊」（即至少一條邊滿足既有 `d0 * d1 < 0` 判定）——因此不會漏掉任何原演算法可能找到的 strict edge crossing，也不會漏掉任何原本會產生 segment 的三角形。但需注意：此等價性僅止於「存在候選交點邊」，並不等價於「該三角形一定會產生 segment」——候選集合中仍可能保留最終只找到 1 個交點、不滿足既有「恰需 2 個交點才算 segment」規則的三角形（例如頂點 Z 為 `(-1, 0, +1)`、切平面為 `0` 時：broad-phase 條件成立，但三條邊中只有一條滿足嚴格 `d0*d1<0`，最後不會形成 segment）。這是候選篩選本身允許的正常情況：候選集合只決定哪些三角形進入既有 scalar 迴圈，該迴圈判斷是否形成 segment 的既有邏輯完全不變，故不影響最終輸出正確性。函式新增可選的 `face_z_bounds` 參數，供呼叫端重用已算好的 bounds。
- **`generate_side_wall_drains()` 呼叫端調整 Z-bounds 生命週期**：inner shell 只切一次，直接呼叫 `slice_mesh_at_z(inner_shell, z_drain)`——其 Z-bounds 在該次呼叫內建立，呼叫返回後不再被 `generate_side_wall_drains()` 的作用域持有具名參照；outer shell 的 bounds 在 inner slice 完成後才建立一次，持有至 `generate_side_wall_drains()` 返回為止，供 `+1.0 → +0.5 → +2.0` 三次 retry 共用，不使用全域或 Trimesh 快取（避免 mesh 被修改後取得過期 bounds）。
- **不變更**：`compute_face_z_bounds()` 之外的候選點選取、angle-bin、slide search、孔幾何、Boolean（Step 7～10）。未新增任何第三方依賴，未建立 Z-bucket 空間索引，未向量化 edge/segment 求交本身。

## Capabilities

### New Capabilities
- `side-wall-drain-slice-performance`：定義 `slice_mesh_at_z()` 的三角形 Z min/max broad-phase 篩選必須維持的正確性契約——篩選條件與「至少存在一條 strict edge crossing」的數學等價性（不得產生 false negative，但不宣稱等價於「一定產生 segment」）、篩選後 loop chaining 輸出（loop 數量、順序、座標陣列）的 `np.array_equal` 等價判準、Z-bounds 生命週期（inner 不跨呼叫持有、outer 持有至 `generate_side_wall_drains()` 返回）不得影響輸出，以及 `generate_side_wall_drains()` 最終幾何輸出（`None` 判定、vertices/faces `np.array_equal`、孔數）的等價判準。

### Modified Capabilities
（無。本提案不修改任何既有 capability 的 spec 層級行為——`auto-process-performance` 涵蓋的四項既有改動（repair 開關、mesh 重用、model-type-confirm 早退、上傳驗證去重）與 `hex-grid-raycast-performance` 涵蓋的 Step 4 raycast broad-phase，皆與本提案涉及的 `slice_mesh_at_z()`／Step 6 完全不重疊。）

## Impact

- `agent/ortho_pipeline.py`：新增 `compute_face_z_bounds()`；`slice_mesh_at_z()` 新增 broad-phase 篩選與可選 `face_z_bounds` 參數；`generate_side_wall_drains()` 呼叫端調整 bounds 生命週期（inner 不跨呼叫持有、outer 持有至函式返回，跨 retry 共用）。
- 測試：新增 `agent/tests/test_slice_mesh_at_z_broad_phase.py`（8 tests：全高於／全低於平面、正常穿越閉合 loop、vertex 恰在平面、coplanar、degenerate、空 mesh、precomputed vs 內部計算 bounds 一致）。
- 效能，兩組獨立量測，來源不同、不可混算：
  - **診斷分析**（4 個代表模型、16 組真實 mesh／z-level 組合，逐階段 instrumentation）：候選三角形比例僅 0.03%～0.71%（排除 99.29%～99.97%）。
  - **正式 A/B timing**（`001_p.stl`／`DentalModel_1M.stl` 兩個模型，各 1 次 warm-up + 3 次計時的完整 Auto Process 執行，取 median，過程不含逐階段 instrumentation）：Step 6 wall time 各改善 −67.4%（1.3708s → 0.4465s）／−67.0%（4.6870s → 1.5485s），完整 pipeline 各改善 −16.1%／−15.2%。
- 正確性（reference＝已用 `np.array_equal` 驗證與修改前 production code 輸出一致的 probe copy，prototype＝目前 production code）：
  - 16 組真實 `slice_mesh_at_z()` loop 輸出 `np.array_equal`。
  - 4 個真實案例：`generate_side_wall_drains()` 之 `None` 判定一致、`.vertices`／`.faces` `np.array_equal`（此即蘊含最終孔數與內部候選 gate 結果相同，因為最終 mesh 完全由通過哪些 gate 的候選決定）、孔數與本次調查最初一輪自真實 pipeline 擷取的 baseline production log 一致。
  - 其中 `001_p.stl`／`DentalModel_1M.stl` 另外執行完整 pipeline 端到端比較：faces／vertices count 相同、volume 相對誤差 0.0、bounds 絕對誤差 0.0mm，placed/skip counters（`no_bin`／`no_inner_hit`／`too_close`）與 prototype 實際 production log 所表達的結果一致（reference 側顯示文字由已驗證的 probe counters 重建，非 reference pipeline 直接捕捉的原始 logger 輸出）。
  - `is_watertight`：驗收本次效能變更時與固定的 pre-change reference 一致（`001_p.stl` 兩者皆 `True`；`DentalModel_1M.stl` 兩者皆 `False`——此為該模型在此 HEAD 下的既有狀況，非本次效能變更造成的 regression，本次未調查根因，也不限制未來另案修正）。
- 不觸及：`agent/ortho_pipeline.py` 其餘 pipeline steps（Step 1～5、7～10）、`agent/sla_operations.py`（含 hex grid raycast，已由 `hex-grid-raycast-performance` 涵蓋）、candidate/slide search/孔幾何/Boolean 呼叫方式。
- 測試模型（唯讀，不納入 Git）：`C:\Users\user\Pictures\tempTest\001_p.stl`、`005_p.stl`、`DentalModel_1M.stl`、`DentalModel_NeedRotate.stl`。

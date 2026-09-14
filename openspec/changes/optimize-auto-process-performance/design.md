## Context

Auto Process（`run_ortho_pipeline()`，[agent/ortho_pipeline.py](../../../agent/ortho_pipeline.py)）與其周邊 API（`agent/api_v2.py`、`agent/model_classifier.py`）執行在使用者自己的電腦上，一次處理一個 job。跟 `archive/2026-08-06-optimize-slice-performance` 面對的 SLA 光柵化不同，這裡沒有單一的巨大熱點——瓶頸分散在 pipeline 的多個獨立步驟，且性質互不相同：component split 的 repair 開關、mesh 物件的生命週期管理、Boolean 鏈的中間表示法、特徵擷取的目標感知早退、以及 API 層的重複驗證。

這些項目的共通點不是「同一段程式碼慢」，而是「同一種模式——在功能不需要的地方多做了一次工」反覆出現。因此本變更沿用 `optimize-slice-performance` 的結構（多個獨立修正放進同一個 proposal，各自 task／驗證／commit），但驗收線的表達方式不同：那次變更處理的是光柵化這種「輸入輸出都是逐層點陣圖」的問題，byte-for-byte SHA-256 是自然的驗收線；本變更處理的是 mesh 物件與 Boolean 拓撲，其中 Boolean 表示法改變後，幾何等價的結果可能有不同 triangle／face ordering、不同的內部三角化——因此驗收線改以「外部可觀察行為與幾何語意」表達，範圍與判準由每個 task 各自定義。

## Goals / Non-Goals

**Goals:**

- 移除 5 項已確認根因、已有明確修法方向的重複運算，且不改變任何既有功能、API 契約或使用者可觀察到的輸出。
- 為每項純效能改動建立各自適用的可驗證驗收線，避免「看起來一樣」式的驗收。
- 延續 Hollow-fit 已建立的「最小 temporary timing → 實測 → 記錄 → 移除」量測模式，不建立新的永久 profiling framework。

**Non-Goals:**

- **不處理 Hex Grid raycast backend。** 瓶頸已 100% 定位在 raycast（99.7% 時間），但替代 backend 尚未 prototype——不知道要換成什麼，無法寫成可驗收的 task。
- **不處理 Side-wall drains 幾何搜尋。** bottleneck 已確認，但具體演算法方案尚未決定。
- **不處理 Surgical Guide `_grow_patches` 等。** profiling 已完成，但範圍本身尚未界定（可能拆成多個子優化），且屬於 `agent/auto_orient_surg_guide.py`——與 Ortho hollow／hex／boolean pipeline 不同的功能模組，即使範圍界定清楚，也應評估是否該獨立成另一個變更。
- **不處理 Generate Drain Holes mesh construction。** 只有優化方向，尚未 benchmark，成熟度不足以列入 What Changes。
- **不處理 `clean_input_for_manifold` fast-path。** 尚未找到可靠的 cheap gate 條件，方案本身仍是 research blocked 狀態。
- **不處理 Prusa Hollow／Support C++。** 只有 source investigation，缺少 C++ 內部分段 profiling，不知道該改哪裡；且屬於 `third_party/prusaslicer_fork` submodule，一旦方向明確，落地時機（併入本提案或另開變更）留待屆時判斷。
- **不建立永久性的效能監控／profiling 框架。** 每項改動各自的 temporary timing 在驗證完成後 SHALL 移除；正式 production code 不保留效能調查用 log，除非有獨立理由。

## Decisions

### D1：Hollow-fit component split 改用 `repair=False`（已完成）

[ortho_pipeline.py:954](../../../agent/ortho_pipeline.py#L954)（`try` 區塊內）的 `hollow_mesh.split(only_watertight=False)` 改為顯式傳入 `repair=False`。

**根因**：trimesh 4.11.1 的 `graph.split()` → `Trimesh.submesh()` → `util.submesh()` 中，即使 `only_watertight=False`，預設 `repair=True` 仍會對每個 split 出的 component 呼叫 `fill_holes()`——即使該 component 是否 watertight 的結果根本不會被用來篩選。

**為何安全**：`fill_holes()` 只能補「單三角形」或「單四邊形」的邊界洞（`hole_to_faces()` 對其餘大小的邊界迴圈回傳空陣列），且**從不新增頂點**，只用既有邊界頂點組出 1～2 個新面。Hollow-fit 判斷邏輯（[ortho_pipeline.py:954-1030](../../../agent/ortho_pipeline.py#L954-L1030)）只讀取 component 的 `.vertices`／`.bounds`（`_min_width_xy` 的 ConvexHull 計算、`_radial_center_opening_stats_xy` 的射線分析）與 `len(component.faces) >= 100` 這個 significant-component 門檻，不讀取 `.is_watertight` 或任何 repair 後才存在的 topology。因此唯一理論風險窄縮在「某個 component 的面數恰好落在 98～99 面、且剛好有小洞會被 repair 補到 100 面以上」這種邊界情況。

**驗證**：以真實 PrusaSlicer `--export-hollow-stl` 輸出（經 `load_trimesh()` 相同流程載入）分別測試一般品質（32,776 faces、5 components）與高品質（400,428 faces）hollow mesh，`repair=True`／`False` 兩者的 face count、vertices、significant components 完全一致；高品質網格下 `repair=False` 較 `repair=True` 快約 2.5 倍（0.12s vs 0.31s）。

以 `001_p.stl`／`005_p.stl` 各跑 3 次完整 Auto Process 端到端實測：Hollow-fit check 階段（扣除 hollow load）`001_p.stl` 由舊基準 2150.91ms 降至 3-run 平均 1647.35ms（約 −23.4%），`005_p.stl` 由 1837.59ms 降至 1420.73ms（約 −22.7%）；`split()` 本身 3-run 平均分別為 809.99ms（`001_p.stl`）與 694.94ms（`005_p.stl`）。兩模型 `fits=True` 判定與修改前一致，後續 Hex Grid／Drain／Boolean face counts 與最終 Ortho 幾何結果未觀察到 regression。詳細數字見 `tasks.md` 群組 1 的量測記錄。

**限制說明**：修改前每個模型只有既有單次 profiling baseline，且當時沒有獨立的 `split_ms`，因此可以確認 Hollow-fit check 整體階段約改善 23%，但不應把新舊差值直接宣稱為 `fill_holes()` 的精確單獨成本——兩者的量測條件（次數、當下機器狀態）並不完全對等。

驗證完成後，暫時性的 `[HOLLOW_FIT_PROFILE]` timing log（`hollow_load_ms`／`split_ms`／`hollow_fit_total_ms`）已依既定流程移除；正式程式碼只保留 `repair=False` 呼叫本身與說明安全性理由的註解。

### D2：Ortho cleaned mesh 物件重用

**根因**：`input_path` 在 [ortho_pipeline.py:775](../../../agent/ortho_pipeline.py#L775) 被指定為 `model_clean.stl` 後不再改變。`_is_u_arch_from_low_sections(input_path)`（[ortho_pipeline.py:638](../../../agent/ortho_pipeline.py#L638)，呼叫於 [ortho_pipeline.py:778](../../../agent/ortho_pipeline.py#L778)）內部於 [ortho_pipeline.py:652](../../../agent/ortho_pipeline.py#L652) 呼叫 `load_trimesh(input_path)`；只要該次判斷未提前結束 pipeline（非 U-arch），Step 3 對齊在 [ortho_pipeline.py:1054](../../../agent/ortho_pipeline.py#L1054) 又對**同一個檔案**呼叫一次 `load_trimesh(input_path)`。兩次載入之間沒有任何會改變 `model_clean.stl` 內容的操作。

**修法方向**：`_is_u_arch_from_low_sections()` 目前簽章為 `(input_path: Path) -> bool`，唯一呼叫點在 `run_ortho_pipeline()` 內（已確認無其他呼叫者，見 Impact）。改為由呼叫端先 `load_trimesh(input_path)` 一次，把得到的 mesh 物件同時傳給 `_is_u_arch_from_low_sections()`（簽章改為接受 mesh，內部不再自行載入）與 Step 3 對齊，取代 Step 3 那次重新讀取磁碟。

**風險**：`_is_u_arch_from_low_sections()` 內部會呼叫 `m.section(...)` 等可能修改 mesh cache（但不修改幾何）的操作；需確認重用同一個物件不會讓 Step 3 對齊拿到與原本重新載入不同的頂點資料（理論上 trimesh 的 `section()` 不修改 `mesh.vertices`／`mesh.faces`，只讀取）。此點列入 task 的驗證項。

### D3：Boolean Step 7～10 維持 Manifold 表示法

**根因**：`boolean_meshes()`（[sla_operations.py:770](../../../agent/sla_operations.py#L770)）的簽章是 `(trimesh.Trimesh, trimesh.Trimesh) -> trimesh.Trimesh`：內部把兩個運算元各自轉成 `manifold3d.Manifold`（`trimesh_to_manifold()`，[sla_operations.py:787](../../../agent/sla_operations.py#L787)）、執行布林運算、再把結果轉回 `trimesh.Trimesh`（`manifold_to_trimesh()`，[sla_operations.py:793](../../../agent/sla_operations.py#L793)，內含 `process=True` 的頂點合併）。

`run_ortho_pipeline()` 的 Step 7～10（[ortho_pipeline.py:1120](../../../agent/ortho_pipeline.py#L1120)、[:1130](../../../agent/ortho_pipeline.py#L1130)、[:1137](../../../agent/ortho_pipeline.py#L1137)、[:1145](../../../agent/ortho_pipeline.py#L1145)）依序呼叫 `boolean_meshes()` 四次，且**前一步的結果是下一步的運算元**：`step7_mesh → step8` 的第二運算元、`step8_mesh → step9` 的第二運算元、`step9_mesh → step10` 的第二運算元。這三次交接，資料剛在上一次呼叫內被轉成 `Trimesh` 送出，馬上又在下一次呼叫內被轉回 `Manifold`——來回轉換與其中的頂點合併，量測確認佔約 1.31 秒。

**修法方向**：新增一個內部變體（或為 `boolean_meshes()` 加一個保留預設值的參數，例如 `return_manifold: bool = False` 與允許輸入已是 `Manifold` 的運算元），讓 Step 7→8→9→10 之間傳遞 `manifold3d.Manifold` 而不強制每次都物化成 `Trimesh`。**只有非鏈式的運算元**（`hex_mesh`、`drain_mesh`、`flipped_hollow`、`side_wall_mesh`、`input_mesh`）與**最終輸出**（Step 10 的 `result_mesh`，需要 `.export()`）需要走 `Trimesh` 邊界。`boolean_meshes()` 現有的公開簽章（純 `Trimesh` in/out）SHALL 保留，供其他呼叫端（例如獨立的 Boolean API 端點）不受影響地繼續使用。

**風險**：`manifold3d.Manifold` 物件沒有 `trimesh.Trimesh` 的全部方法；需確認 Step 8 的 `flipped_hollow = hollow_mesh.copy(); flip_mesh_faces(flipped_hollow)` 是否也適合改在 Manifold 層級完成，或維持在 Trimesh 層級（`flipped_hollow` 不是鏈式運算元，此項非必要）。第一版 SHALL 只處理鏈式交接，不擴大範圍去重寫 `flip_mesh_faces`。

### D4：`confirm-model-type(target_type=intraoral_scan)` 略過 ProjectionShape

**根因**：`confirm_dental_model_type(mesh, target)`（[model_classifier.py:1376](../../../agent/model_classifier.py#L1376)）第一步無條件呼叫 `extract_model_features(mesh)`（[model_classifier.py:542](../../../agent/model_classifier.py#L542)），其中的 ProjectionShape 區塊（[model_classifier.py:564-587](../../../agent/model_classifier.py#L564-L587)）執行 `projection_shape_gap_stats()`。

**追蹤確認（比原始需求描述更精確）**：`u_shape_score`（`_compute_signals()`，[model_classifier.py:1001-1007](../../../agent/model_classifier.py#L1001-L1007)）是整個分類邏輯中**唯一**讀取 ProjectionShape 特徵（`projection_largest_gap_ratio`／`projection_largest_gap_contact_mm`）的訊號，且只在 `_p_base_decide()`（[model_classifier.py:1044](../../../agent/model_classifier.py#L1044)）與 `_decide_model_type_with_details()` 的 P_base 分支中被讀取。對 `target == INTRAORAL_SCAN`，`confirm_dental_model_type()` 的**每一條**路徑都不會走到會讀 `u_shape_score` 的地方：
- P_base 分支（[model_classifier.py:1401-1406](../../../agent/model_classifier.py#L1401-L1406)）：`target` 不在 `(DENTAL_MODEL, U_SHAPED_DENTAL_MODEL)` 時直接 `return False`，不呼叫 `_p_base_decide()`。
- P3 分支（[model_classifier.py:1412-1414](../../../agent/model_classifier.py#L1412-L1414)）：直接由 `skip_reason == "大型開放邊界"` 判定，只依賴 OpenBoundary 特徵。
- `needs_drill=True` 早退（[model_classifier.py:1416-1423](../../../agent/model_classifier.py#L1416-L1423)）：`INTRAORAL_SCAN` 在列，直接 `return False`，連導孔偵測都不執行。
- P5（[model_classifier.py:1425-1434](../../../agent/model_classifier.py#L1425-L1434)）：`target` 不在此分支可能命中的類型集合中（見既有 spec `dental-model-type-confirm` 的 Early Return 五種情境列舉）。

**修法方向**：`extract_model_features()` 新增一個保留預設值的參數（例如 `skip_projection_shape: bool = False`），為真時略過 ProjectionShape 區塊（其餘欄位維持 `None`，`_compute_signals()` 既有的 `projection_valid` 判斷會自然讓 `u_shape_score` 退回 `0.0`——這正是目前 `projection_valid=False` 時的既有行為，不是新分支）。`confirm_dental_model_type()` 只在 `target == DentalModelType.INTRAORAL_SCAN` 時傳入 `skip_projection_shape=True`；`classify_dental_model()`（不知道目標類型，必須支援全部八種分類，見既有 spec 的「與完整分類的一致性」不變量）與 `confirm_dental_model_type()` 對其餘七種 target 的呼叫 SHALL 不傳入此參數，維持現行行為。

**風險**：`dental-model-type-confirm` 既有 spec 的「與完整分類的一致性（無例外）」requirement（`confirm(mesh, target) == (classify(mesh) == target)` 對所有 target 無例外成立）SHALL 繼續成立——這條不變量本身就是本項優化安全性的形式化表達，task 的回歸測試 SHALL 直接針對它斷言，而不只是抽樣比對。

### D5：Upload／save 對相同 STL bytes 避免重複完整 parse

**根因**：`_validate_stl_bytes()`（[api_v2.py:193](../../../agent/api_v2.py#L193)）對輸入 bytes 執行完整 `trimesh.load()`。`upload_model_file()`（[api_v2.py:364](../../../agent/api_v2.py#L364)）在 [api_v2.py:389](../../../agent/api_v2.py#L389) 呼叫一次後，把已驗證的 bytes 存進 `pending["models"]`；execute 時 `_save_model_to_job()`（[api_v2.py:207](../../../agent/api_v2.py#L207)）在 [api_v2.py:211](../../../agent/api_v2.py#L211) 對**同一份不可變 bytes** 再完整 parse 一次才落地寫檔。`upload_support_file()`（[api_v2.py:406](../../../agent/api_v2.py#L406)）同構。

**呼叫範圍確認（安全邊界的關鍵）**：`pending["models"]` 只有兩個寫入點——`upload_model_file()`（已於 [api_v2.py:389](../../../agent/api_v2.py#L389) 驗證）與 `use_model_from_job()`（[api_v2.py:445](../../../agent/api_v2.py#L445)）。後者直接讀取**另一個 job 的既有輸出檔案**（例如 `boolean.stl`）並附加進 `pending["models"]`（[api_v2.py:467-472](../../../agent/api_v2.py#L467-L472)），**從未呼叫 `_validate_stl_bytes()`**——`_save_model_to_job()` 的驗證是這條路徑落地前**唯一**一次驗證。若不分來源一律略過 `_save_model_to_job()` 的驗證，會讓 `use_model_from_job()` 引用的內容完全不受驗證，是正確性倒退而非純效能改動。

**修法方向**：在 `pending["models"]` 的字典項加入一個標記（例如 `"validated": True`），只在 `upload_model_file()` 與 `upload_support_file()`（已呼叫 `_validate_stl_bytes()` 之後）設置；`use_model_from_job()` 附加的項目不設置此標記（或顯式設為 `False`）。`_save_model_to_job()` 只在該標記為真時略過 `_validate_stl_bytes()`，其餘情況（標記缺失或為假）維持現行的完整驗證。

**風險**：任何未來新增的 `pending["models"]` 寫入點，若忘記設置驗證標記，預設值 SHALL 為「需要驗證」（即標記缺失視同未驗證），避免新寫入點意外略過驗證——這點 SHALL 反映在 task 的回歸測試中（斷言預設/缺失狀態仍會觸發驗證）。

## Risks / Trade-offs

- **[D1 面數門檻邊界情況未被端到端案例覆蓋]** 理論風險窄縮在單一 component 面數恰好落在 98～99 且有小洞的邊界；目前的實測案例未剛好命中此邊界。→ 已用真實 hollow mesh 驗證 face count／vertices／significant components 完全一致；若未來观察到判定差異，回滾為單一 commit revert（見 Migration Plan）。
- **[D2 mesh 物件重用引入非預期的 cache 副作用]** `_is_u_arch_from_low_sections()` 對 mesh 呼叫 `.section()` 等方法可能填入 trimesh 內部 cache。→ task 驗證項包含比對「重用物件」與「原本兩次獨立載入」在 Step 3 對齊後的幾何是否一致。
- **[D3 Boolean 中間表示法改變後幾何非 byte 相同]** Manifold 內部三角化與 Trimesh `process=True` 的頂點合併演算法不同，鏈式改動後的中間結果 face ordering／triangle 數可能與改動前不同。→ 驗收線明確定義為「幾何與 validity semantics 等價」（體積、`is_watertight`、bounds、boolean 結果的實際佔據空間），不要求 byte-for-byte 相同；`boolean_meshes()` 現有公開簽章不變，其他呼叫端不受影響。
- **[D4 誤判 target 導致跳過必要特徵]** 若 `skip_projection_shape` 被錯誤地用在非 `INTRAORAL_SCAN` 的呼叫，會讓該次分類結果錯誤退化。→ 只在 `confirm_dental_model_type()` 內部依 `target` 條件式設置，不對外暴露為 API 參數；回歸測試直接斷言既有 spec 的「與完整分類的一致性」不變量對全部八種 target 仍成立。
- **[D5 新寫入點遺漏驗證標記]** → 標記預設值為「需要驗證」（fail-safe），缺失時觸發驗證而非略過；回歸測試明確覆蓋此預設情況。
- **[量測結果與各項獨立 profiling 的估計值出入]** 5 項數字分別來自不同時間點的 source investigation，尚未在同一次端到端量測中彼此對照（僅 D1 已端到端實測）。→ 各項 task 的第一步都是建立最小必要 temporary timing 並重新實測，不直接沿用舊估計值；task 完成後移除 temporary timing。

## Migration Plan

分階段，每階段可獨立驗證與獨立 commit；階段編號與 [tasks.md](tasks.md) 一致。

| 階段 | 內容 | 決策 | 回滾方式 |
|---|---|---|---|
| 0 | 共用基準模型與量測慣例（不引入永久 framework） | — | — |
| 1 | Hollow-fit split `repair=False`（已完成，待補：移除殘留的 temporary log） | D1 | 單一 commit revert |
| 2 | Ortho cleaned mesh 物件重用 | D2 | 單一 commit revert |
| 3 | Boolean Step 7～10 維持 Manifold 表示法 | D3 | 單一 commit revert |
| 4 | `confirm-model-type` 略過 ProjectionShape | D4 | 單一 commit revert |
| 5 | Upload／save 重複驗證去重 | D5 | 單一 commit revert |
| 6 | 整合驗證與收尾 | — | — |
| 7 | 不在本變更範圍（僅記錄） | — | — |

每一項改動皆為純效能／實作層級變更，SHALL 各自通過該項自訂的驗收線才可視為完成；不要求全部 5 項完成後才能合併——與 `optimize-slice-performance` 先例相同，完成一項即可獨立 commit。

## Open Questions

- ~~**D1 的 temporary log 是否已清除？**~~ **已解決。** `[HOLLOW_FIT_PROFILE]` 相關的 `# TEMP HOLLOW_FIT_PROFILE` 標記程式碼（`import time`、三處 `logger.info(...)` 與其計時變數）已全數移除；`grep -rn "TEMP HOLLOW_FIT_PROFILE\|\[HOLLOW_FIT_PROFILE\]" agent/ortho_pipeline.py` 確認無殘留。正式程式碼只保留 `hollow_mesh.split(only_watertight=False, repair=False)` 與說明安全性理由的註解。tasks.md 的 1.9／1.10 已標記完成。
- **D3 的 `flip_mesh_faces` 是否值得下放到 Manifold 層級？** 第一版故意不處理（`flipped_hollow` 不是鏈式運算元，收益有限）；若後續量測顯示這一步仍有可觀成本，可另開子項評估。
- **Prusa Hollow／Support C++ 何時具備併入條件？** 待兩項各自完成 C++ 內部分段 profiling、定位出具體修法後，再判斷是續開新變更或併入本提案的後續版本。

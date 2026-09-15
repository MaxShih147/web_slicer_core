## Context

Auto Process（`run_ortho_pipeline()`，[agent/ortho_pipeline.py](../../../agent/ortho_pipeline.py)）與其周邊 API（`agent/api_v2.py`、`agent/model_classifier.py`）執行在使用者自己的電腦上，一次處理一個 job。跟 `archive/2026-08-06-optimize-slice-performance` 面對的 SLA 光柵化不同，這裡沒有單一的巨大熱點——瓶頸分散在 pipeline 的多個獨立步驟，且性質互不相同：component split 的 repair 開關、mesh 物件的生命週期管理、Boolean 鏈的中間表示法、特徵擷取的目標感知早退、以及 API 層的重複驗證。

這些項目的共通點不是「同一段程式碼慢」，而是「同一種模式——在功能不需要的地方多做了一次工」反覆出現。因此本變更沿用 `optimize-slice-performance` 的結構（多個獨立修正放進同一個 proposal，各自 task／驗證／commit），但驗收線的表達方式不同：那次變更處理的是光柵化這種「輸入輸出都是逐層點陣圖」的問題，byte-for-byte SHA-256 是自然的驗收線；本變更處理的是 mesh 物件與 Boolean 拓撲，其中 Boolean 表示法改變後，幾何等價的結果可能有不同 triangle／face ordering、不同的內部三角化——因此驗收線改以「外部可觀察行為與幾何語意」表達，範圍與判準由每個 task 各自定義。

## Goals / Non-Goals

**Goals:**

- 移除已確認根因、已有明確修法方向的重複運算，且不改變任何既有功能、API 契約或使用者可觀察到的輸出。原始範圍列出 5 項；其中 D3（Boolean Step 7～10 維持 Manifold 表示法）實作並端到端驗證後證實無法在不違反 validity 驗收線的前提下達成，已放棄——詳見下方 D3 小節與 Non-Goals。
- 為每項純效能改動建立各自適用的可驗證驗收線，避免「看起來一樣」式的驗收。
- 延續 Hollow-fit 已建立的「最小 temporary timing → 實測 → 記錄 → 移除」量測模式，不建立新的永久 profiling framework。

**Non-Goals:**

- **不處理 Boolean Step 7～10 維持 Manifold 表示法（D3，已調查並放棄）。** 已完整實作、benchmark、除錯，證實鏈式維持 `manifold3d.Manifold` 會在 `001_p.stl`／`005_p.stl` 上產生 `is_watertight` regression，且沒有找到對兩個代表模型都安全的部分鏈式方案——詳見 D3 小節「調查結果」。Step 7～10 維持修改前的逐步 `boolean_meshes()` 呼叫，不帶來效能改善。
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

### D2：Ortho cleaned mesh 物件重用（已完成）

**根因**：`input_path` 在 [ortho_pipeline.py:775](../../../agent/ortho_pipeline.py#L775) 被指定為 `model_clean.stl` 後不再改變。`_is_u_arch_from_low_sections(input_path)`（[ortho_pipeline.py:638](../../../agent/ortho_pipeline.py#L638)，呼叫於 [ortho_pipeline.py:778](../../../agent/ortho_pipeline.py#L778)）內部於 [ortho_pipeline.py:652](../../../agent/ortho_pipeline.py#L652) 呼叫 `load_trimesh(input_path)`；只要該次判斷未提前結束 pipeline（非 U-arch），Step 3 對齊在 [ortho_pipeline.py:1054](../../../agent/ortho_pipeline.py#L1054) 又對**同一個檔案**呼叫一次 `load_trimesh(input_path)`。兩次載入之間沒有任何會改變 `model_clean.stl` 內容的操作。

**修法方向**：`_is_u_arch_from_low_sections()` 目前簽章為 `(input_path: Path) -> bool`，唯一呼叫點在 `run_ortho_pipeline()` 內（已確認無其他呼叫者，見 Impact）。改為由呼叫端先 `load_trimesh(input_path)` 一次，把得到的 mesh 物件同時傳給 `_is_u_arch_from_low_sections()`（簽章改為接受 mesh，內部不再自行載入）與 Step 3 對齊，取代 Step 3 那次重新讀取磁碟。

**風險**：`_is_u_arch_from_low_sections()` 內部會呼叫 `m.section(...)` 等可能修改 mesh cache（但不修改幾何）的操作；需確認重用同一個物件不會讓 Step 3 對齊拿到與原本重新載入不同的頂點資料（理論上 trimesh 的 `section()` 不修改 `mesh.vertices`／`mesh.faces`，只讀取）。此點列入 task 的驗證項。

**實作與驗證記錄**：

- **重用對象的選擇**：source tracing 確認 `clean_input_for_manifold()` export 前的 in-memory mesh 與 `model_clean.stl` export→reload 後的 mesh，在 vertex ordering（reload 後依 trimesh STL 匯出的 face-major 順序重新去重編號，與 export 前因多次 `merge_vertices()`／頂點 remap 形成的順序不同）、face 索引、float64/float32 精度上並非完全相同語意，因此本次**不重用 pre-export mesh**（未修改 `clean_input_for_manifold()` 回傳型別），而是重用 **export 後第一次 `load_trimesh()` reload 出來的 mesh**。由於這次 reload 與原本 Step 3 那次 reload 讀的是同一份檔案、呼叫同一個 `load_trimesh()`、trimesh 的 `merge_vertices()` 在給定輸入下具確定性，兩次獨立 reload 理論上會得到逐位元組相同的 `.vertices`／`.faces`／`.bounds`——`agent/tests/test_ortho_clean_mesh_reuse.py::test_load_trimesh_reload_is_deterministic` 已用 `numpy.array_equal` 實測確認。
- **`.copy()` 必要性**：`_is_u_arch_from_low_sections()` 對 mesh 的操作（`.bounds`、`.section()`）經 trimesh 4.11.1（專案 `.venv` 實際安裝版本）原始碼追蹤確認完全 read-only，只可能填入 trimesh 內部 `_cache`，不修改 `.vertices`／`.faces`／transform；`agent/tests/test_ortho_clean_mesh_reuse.py` 的 mutation 測試（U-arch／非 U-arch 兩案例）進一步以實測 pin 住此結論。因此**不需要 `.copy()`**——U-arch 判斷與 Step 3/6/10 直接共用同一個 `Trimesh` instance。
- **U-arch=True 提前結束路徑**：`_complete_as_no_hollow()` 只使用 `input_path`（檔案路徑）落地 `ortho_result.stl`，不依賴 mesh 物件，因此該路徑行為完全不受本次 ownership 改動影響；`test_u_arch_pipeline_takes_early_return_without_second_load` 實際執行 `run_ortho_pipeline()`（`generate_hollow` 以 monkeypatch 替換為呼叫即失敗的 stub）確認：U-arch=True 時只 `load_trimesh()` 一次、Step 1 不會被觸發、`status.json`／`ortho_result.stl` 正常產出。
- **`001_p.stl`／`005_p.stl` after benchmark**（各 3 runs）：`001_p.stl` 修改後單次 `shared_load_ms` avg 80.62 ms，較修改前兩次 reload 合計 avg 155.48 ms 減少約 74.86 ms/run；`005_p.stl` 修改前 `u_arch_load_ms` 因單次 outlier（1384.10 ms）不具代表性，改以「移除一個平均約 421 ms 的第二次 reload」描述——修改後單次 `shared_load_ms` avg 425.16 ms 與修改前正常單次 load（`step3_load_ms` avg 421.19 ms）量級一致，確認第二次 reload 已被移除。詳細數字見 `tasks.md` 群組 2 的量測記錄。
- **SHA-256 byte-for-byte 驗證**：兩模型修改前／修改後各 3 runs 的 `ortho_result.stl` SHA-256 皆逐位元組相同（`001_p.stl`：`BB150F743F6370AE01E8E5577E1110902074C3D68CB24AF93F579F24473E0912`；`005_p.stl`：`2E06094A2F19DBD8004D573C71B4F93FDAC0B82897D86AF09575AC64AF3BD2F7`），Task 2.7 的 byte-for-byte 驗收線通過。
- **Temporary profiling**：`[CLEAN_MESH_REUSE_PROFILE]` 系列 timing log（`u_arch_load_ms`／`step3_load_ms`／`reload_total_ms`，實作後改為單一 `shared_load_ms`）與本群組專用加入的 `import time` 已依既定流程移除；正式程式碼只保留單次 `load_trimesh()` 呼叫本身與必要註解。

### D3：Boolean Step 7～10 維持 Manifold 表示法（已調查，證實 not viable，放棄）

> **結論（2026-09-15 二輪調查後）**：本項已實作、benchmark、除錯過，最終確認**無法在不違反 validity 驗收線的前提下取得效能改善**，予以放棄。Step 7～10 維持現行「每步皆物化為 Trimesh」的實作，本節其餘內容保留作為調查記錄；`tasks.md` 群組 3 與下方「調查結果」小節記載完整根因與嘗試過的修法。

**根因**：`boolean_meshes()`（[sla_operations.py:770](../../../agent/sla_operations.py#L770)）的簽章是 `(trimesh.Trimesh, trimesh.Trimesh) -> trimesh.Trimesh`：內部把兩個運算元各自轉成 `manifold3d.Manifold`（`trimesh_to_manifold()`，[sla_operations.py:787](../../../agent/sla_operations.py#L787)）、執行布林運算、再把結果轉回 `trimesh.Trimesh`（`manifold_to_trimesh()`，[sla_operations.py:793](../../../agent/sla_operations.py#L793)，內含 `process=True` 的頂點合併）。

`run_ortho_pipeline()` 的 Step 7～10（[ortho_pipeline.py:1120](../../../agent/ortho_pipeline.py#L1120)、[:1130](../../../agent/ortho_pipeline.py#L1130)、[:1137](../../../agent/ortho_pipeline.py#L1137)、[:1145](../../../agent/ortho_pipeline.py#L1145)）依序呼叫 `boolean_meshes()` 四次，且**前一步的結果是下一步的運算元**：`step7_mesh → step8` 的第二運算元、`step8_mesh → step9` 的第二運算元、`step9_mesh → step10` 的第二運算元。這三次交接，資料剛在上一次呼叫內被轉成 `Trimesh` 送出，馬上又在下一次呼叫內被轉回 `Manifold`——來回轉換與其中的頂點合併，量測確認佔約 1.31 秒。

**修法方向**：新增一個內部變體（或為 `boolean_meshes()` 加一個保留預設值的參數，例如 `return_manifold: bool = False` 與允許輸入已是 `Manifold` 的運算元），讓 Step 7→8→9→10 之間傳遞 `manifold3d.Manifold` 而不強制每次都物化成 `Trimesh`。**只有非鏈式的運算元**（`hex_mesh`、`drain_mesh`、`flipped_hollow`、`side_wall_mesh`、`input_mesh`）與**最終輸出**（Step 10 的 `result_mesh`，需要 `.export()`）需要走 `Trimesh` 邊界。`boolean_meshes()` 現有的公開簽章（純 `Trimesh` in/out）SHALL 保留，供其他呼叫端（例如獨立的 Boolean API 端點）不受影響地繼續使用。

**風險**：`manifold3d.Manifold` 物件沒有 `trimesh.Trimesh` 的全部方法；需確認 Step 8 的 `flipped_hollow = hollow_mesh.copy(); flip_mesh_faces(flipped_hollow)` 是否也適合改在 Manifold 層級完成，或維持在 Trimesh 層級（`flipped_hollow` 不是鏈式運算元，此項非必要）。第一版 SHALL 只處理鏈式交接，不擴大範圍去重寫 `flip_mesh_faces`。

**調查結果（實作後發現的根因，判定 not viable）**：

依上述修法方向實作後（`_boolean_meshes_chain()` 讓 Step 7～10 鏈式交接維持 `manifold3d.Manifold`，只在最終 Step 10 物化為 `Trimesh`），以 `001_p.stl`／`005_p.stl` 端到端驗證時發現**兩模型的 `ortho_result.stl` 皆不再 `is_watertight`**——直接違反本能力 spec 的「`is_watertight` 狀態 SHALL 相等」驗收線。

根因追蹤：

- `manifold3d.Manifold` 的鏈式運算結果在記憶體中**本身是合法、watertight 的 2-manifold**——以 `status()`（`Error.NoError`）、`genus()`（有限值）與直接對 `to_mesh()` 原始輸出（不經 trimesh 二次處理）建構 `Trimesh(process=False)` 三種方式交叉驗證皆確認為 `is_watertight=True`。
- 問題出在 **STL 格式本身沒有共享頂點索引的概念**——`.export()` 會把每個三角形攤平成 3 個獨立座標點。任何下游消費者（切層軟體、本 benchmark 重新載入驗證、甚至本 pipeline 自己）都必須從原始座標重新用容忍值（tolerance）判斷哪些點該視為同一頂點才能重建拓撲。
- 連續 3 次鏈式布林運算、中間完全不經過 trimesh 的 `merge_vertices()` 重新校正（re-snap）之後，會出現少量頂點彼此距離極近但不完全重合、精度落在「任何合理 tolerance 都無法無歧義判斷」的區間——即使 `.export()` 前的記憶體物件是正確的，`.export()` 後任何重新載入＋合併頂點的動作，都可能把這些點錯誤地焊接／未焊接，產生 non-manifold 的接縫。
- 這個現象**與具體模型幾何相關**，不是單純的浮點精度問題（`manifold3d.Manifold.set_tolerance()`——在不物化的前提下對鏈式結果做 tolerance-based 重新簡化——測試 `1e-4`／`1e-3`／`1e-2` mm 三種值皆無效，face count 幾乎不變，代表問題並非「可合併但未合併」的簡單容忍值調整能解決的浮點雜訊，更像是幾何本身在特定交界處產生了真正的退化／相切結構）。

**嘗試過的修法與結果**（`001_p.stl`／`005_p.stl` 各自端到端驗證，`✓`＝通過 `is_watertight` 驗收，`✗`＝未通過）：

| 修法 | `001_p.stl` | `005_p.stl` |
| --- | --- | --- |
| 全程鏈式，僅 Step 10 前物化一次（原始修法方向） | ✗ | ✗ |
| 物化前先把座標 snap 到固定精度網格（1e-5 mm）再合併 | ✗ | 未再測試（已由下一項證明無單一固定 handoff 可行） |
| 只在 Step 9→10 交接處物化一次 | ✓ | ✗ |
| 只在 Step 8→9 交接處物化一次 | ✓ | ✗ |
| 同時在 Step 8→9 與 Step 9→10 交接處物化 | （未測試，因 9→10 單獨已足夠） | ✗ |
| 每個鏈式交接皆呼叫 `Manifold.set_tolerance()`（不物化，改用 manifold3d 原生重新簡化） | ✗（測試 3 種 tolerance 值） | ✗（測試 3 種 tolerance 值） |
| 三個交接（7→8、8→9、9→10）全部物化（＝回復原本逐步 materialize 行為） | ✓ | ✓ |

**結論**：能同時讓兩個代表模型過關的組合，只有「三個交接全部物化」——也就是完全回到修改前的逐步 materialize 行為，不帶來任何效能改善。哪個交接會產生瑕疵是**模型幾何相關**（不同模型在不同步驟出現問題），因此**不存在一個對任意未來模型都安全的固定部分鏈式組合**；任何比「全部物化」更激進的鏈式簡化，都有為未知的第三個模型引入無聲 `is_watertight` regression 的風險，且該 regression 不會在型別檢查或例外拋出中顯現——只會在下游（切層、列印前檢查）才被發現。

**決策**：本項優化在不違反 validity 驗收線的前提下無法帶來效能改善，**放棄**。已實作的 `_boolean_meshes_chain()`／`_boolean_ensure_trimesh()`／`_boolean_materialize_chain_result()` 與相關 `[BOOLEAN_MANIFOLD_PROFILE]` temporary timing 已還原（`git checkout`），Step 7～10 維持修改前的逐步 `boolean_meshes()` 呼叫。若未來要重新挑戰這個方向，建議的下一步不是繼續嘗試「該在哪個交接物化」，而是先搞清楚 manifold3d 鏈式布林運算在什麼幾何條件下會產生這種近重合但不精確重合的頂點（可能需要 manifold3d 專案本身的協助或原始碼層級除錯），否則任何經驗性選擇的部分鏈式方案都只是恰好在目前兩個測試模型上運氣好。

### D4：`confirm-model-type(target_type=intraoral_scan)` 略過 ProjectionShape

**根因**：`confirm_dental_model_type(mesh, target)`（[model_classifier.py:1376](../../../agent/model_classifier.py#L1376)）第一步無條件呼叫 `extract_model_features(mesh)`（[model_classifier.py:542](../../../agent/model_classifier.py#L542)），其中的 ProjectionShape 區塊（[model_classifier.py:564-587](../../../agent/model_classifier.py#L564-L587)）執行 `projection_shape_gap_stats()`。

**追蹤確認（比原始需求描述更精確；2026-09-15 二輪 source tracing 修正）**：全 repo grep ProjectionShape 產生的 13 個欄位名稱與 `u_shape_score`，確認 `model_classifier.py` 內實際有**兩處**消費者，而非僅 `u_shape_score` 一處：
- `u_shape_score`（`_compute_signals()`，[model_classifier.py:1001-1007](../../../agent/model_classifier.py#L1001-L1007)）讀取 `projection_largest_gap_ratio`／`projection_largest_gap_contact_mm`，只在 `_p_base_decide()`（[model_classifier.py:1044](../../../agent/model_classifier.py#L1044)）與 `_decide_model_type_with_details()` 的 P_base 分支中被讀取。
- `no_holes`（[model_classifier.py:1187-1190](../../../agent/model_classifier.py#L1187-L1190)）讀取 `projection_medium_holes`／`projection_large_holes`，只在 `_decide_model_type_with_details()` 的 P5 分支 B（SPLINT 判定）中被讀取。

對 `target == INTRAORAL_SCAN`，`confirm_dental_model_type()` 的**每一條**路徑都不會走到這兩個消費者：
- P_base 分支（[model_classifier.py:1401-1406](../../../agent/model_classifier.py#L1401-L1406)）：`target` 不在 `(DENTAL_MODEL, U_SHAPED_DENTAL_MODEL)` 時直接 `return False`，不呼叫 `_p_base_decide()`（不讀 `u_shape_score`）。
- P3 分支（[model_classifier.py:1412-1414](../../../agent/model_classifier.py#L1412-L1414)）：直接由 `skip_reason == "大型開放邊界"` 判定，只依賴 OpenBoundary 特徵。
- `needs_drill=True` 早退（[model_classifier.py:1416-1423](../../../agent/model_classifier.py#L1416-L1423)）：`INTRAORAL_SCAN` 在列，直接 `return False`，連導孔偵測都不執行，不可能進入 P5（因此也不可能讀到 `no_holes`）。
- P5（[model_classifier.py:1425-1434](../../../agent/model_classifier.py#L1425-L1434)）：`target` 不在此分支可能命中的類型集合中（見既有 spec `dental-model-type-confirm` 的 Early Return 五種情境列舉），INTRAORAL_SCAN 已在上一條被早退排除，實際不會執行到此處。

**實測驗證（`Ushape1.stl`／`Ushape2.stl`／`Ushape3.stl`／`DentalModel_2.stl`，真實 U 型基座牙模，`DentalModel_2.stl` 由使用者以人工 ground truth 指認並於 commit 前補驗）**：四個模型皆被 `classify_dental_model()` 判定為 `u_shaped_dental_model`，且在完整 ProjectionShape 計算下 `u_shape_score` 皆為 `1.0`（非零、非退化邊界情況）；`confirm_dental_model_type(mesh, INTRAORAL_SCAN)` 四者皆正確回傳 `False`——證實即使 `u_shape_score` 訊號本身強烈觸發，也不影響 `INTRAORAL_SCAN` 這條 confirm 路徑的正確性，因為該路徑根本不讀取這個訊號。詳細數字見下方「實作與驗證記錄」。

**修法方向**：`extract_model_features()` 新增一個保留預設值的參數（例如 `skip_projection_shape: bool = False`），為真時略過 ProjectionShape 區塊（其餘欄位維持 `None`，`_compute_signals()` 既有的 `projection_valid` 判斷會自然讓 `u_shape_score` 退回 `0.0`——這正是目前 `projection_valid=False` 時的既有行為，不是新分支）。`confirm_dental_model_type()` 只在 `target == DentalModelType.INTRAORAL_SCAN` 時傳入 `skip_projection_shape=True`；`classify_dental_model()`（不知道目標類型，必須支援全部八種分類，見既有 spec 的「與完整分類的一致性」不變量）與 `confirm_dental_model_type()` 對其餘七種 target 的呼叫 SHALL 不傳入此參數，維持現行行為。

**風險**：`dental-model-type-confirm` 既有 spec 的「與完整分類的一致性（無例外）」requirement（`confirm(mesh, target) == (classify(mesh) == target)` 對所有 target 無例外成立）SHALL 繼續成立——這條不變量本身就是本項優化安全性的形式化表達，task 的回歸測試 SHALL 直接針對它斷言，而不只是抽樣比對。

**實作與驗證記錄（已完成）**：

- **落地方式**：`extract_model_features()`（[model_classifier.py:543](../../../agent/model_classifier.py#L543)）新增 `skip_projection_shape: bool = False` 參數；為真時整個 ProjectionShape try 區塊（含 PCA-axes-availability 檢查）完全略過，欄位維持 `ModelFeatures` 預設值 `None`——與既有「ProjectionShape 演算法失敗」時的欄位狀態完全相同，`_compute_signals()` 不需新增任何分支。`confirm_dental_model_type()`（[model_classifier.py:1394](../../../agent/model_classifier.py#L1394)）唯一改動是把 `extract_model_features(mesh)` 改為 `extract_model_features(mesh, skip_projection_shape=(target == DentalModelType.INTRAORAL_SCAN))`。`classify_dental_model()` 未改動，仍以 `extract_model_features(mesh)`（不帶參數）呼叫，永遠完整擷取。`skip_projection_shape` 未暴露為 API 參數。
- **Test-first**：先在 `agent/tests/test_dental_model_type_confirm.py` 補齊正式回歸測試（見下），在**尚未修改 production 邏輯**的狀態下確認 8-target 不變量與「classify／非 INTRAORAL_SCAN confirm 呼叫 ProjectionShape」兩類測試全部通過（21 passed），且「INTRAORAL_SCAN confirm 不再呼叫 ProjectionShape」測試如預期失敗（red，1 failed）；實作落地後同一份測試全數轉綠（22 passed）。
- **正式回歸測試**（`agent/tests/test_dental_model_type_confirm.py`，不依賴根目錄未追蹤的 `test_classify_decision.py`／`test_classify_api.py`）：
  - `test_confirm_matches_classify_for_all_targets`：13 組以真實 `_compute_signals()`／`_get_drill_detection_plan()`／`_decide_model_type_with_details()` 跑過驗證得到 ground-truth 的合成特徵情境（涵蓋 P0／P_base×2／P2／P3／P5.1／P5.2×5／P5.3×2，8 種 `DentalModelType` 全部至少出現一次），透過 monkeypatch `extract_model_features()`／`detect_drill_holes()` 對每個情境跑滿全部 8 個 target（共 104 個斷言），確認 `confirm(mesh,t) == (classify(mesh)==t)`；`detect_drill_holes()` 若在未預期情境下被呼叫會主動 raise，額外守住「early-return 分支不得誤落入 P5」。
  - `test_classify_dental_model_calls_projection_shape` / `test_confirm_non_intraoral_scan_calls_projection_shape`（7 target 皆覆蓋）/ `test_confirm_intraoral_scan_skips_projection_shape`：以 call-counting spy 包住真正的 `projection_shape_gap_stats()`（非以欄位是否為 `None` 間接推測），confirm 三個 caller-boundary 主張。
- **U-shape 邊界案例（真實素材，`C:\Users\user\Pictures\tempTest\`）**：`Ushape1.stl`／`Ushape2.stl`／`Ushape3.stl` faces/vertices 分別為 293,095/879,285、234,150/702,450、299,798/899,394；`classify_dental_model()` 三者皆為 `u_shaped_dental_model`；完整 ProjectionShape 計算下 `u_shape_score` 三者皆為 `1.0`（`projection_largest_gap_ratio` 0.40～0.49、`projection_largest_gap_contact_mm` 53～58mm，非退化邊界情況）；`confirm_dental_model_type(mesh, INTRAORAL_SCAN)` 三者皆正確回傳 `False`，且對全部 8 個 target 掃描確認僅 `U_SHAPED_DENTAL_MODEL` 回傳 `True`，其餘 7 個皆 `False`——實作前後兩次都跑過，結果逐一相同。另以 repo 既有 `001_p.stl`／`005_p.stl`（`dental_model`，`u_shape_score=0.0`）交叉驗證，同樣前後一致。
  **`DentalModel_2.stl`**（commit 前補驗，faces=367,506／vertices=1,102,518，使用者以人工 ground truth 指認為 U 型基座）：`classify_dental_model()` 為 `u_shaped_dental_model`，`u_shape_score=1.0`（`projection_largest_gap_ratio=0.394`、`projection_largest_gap_contact_mm=56.5mm`），`confirm_dental_model_type(mesh, INTRAORAL_SCAN)` 為 `False`，8-target 掃描僅 `U_SHAPED_DENTAL_MODEL` 為 `True`——與人工 ground truth 完全相符，且是目前四個真實 U 型基座樣本中規模最大者。
- **效能量測**：於單一 process、同一 code state 下對 `extract_model_features(mesh, skip_projection_shape=False)`（模擬修改前）與 `skip_projection_shape=True`（修改後）先各跑一次暖機再各 3 runs 配對量測（消去跨 process 的冷啟動雜訊），並以真正的 `confirm_dental_model_type(mesh, INTRAORAL_SCAN)` 呼叫佐證 `[PROJECTION_SHAPE_PROFILE]` log（量測期間暫時加回）確實 0 次觸發：

  | 模型 | faces/vertices | before avg (3 runs) | after avg (3 runs) | saved | improvement |
  |---|---|---|---|---|---|
  | `Ushape1.stl` | 293,095 / 879,285 | 2411.17 ms | 2073.24 ms | 337.93 ms | 14.0% |
  | `Ushape2.stl` | 234,150 / 702,450 | 1910.90 ms | 1636.18 ms | 274.72 ms | 14.4% |
  | `Ushape3.stl` | 299,798 / 899,394 | 2411.32 ms | 2169.53 ms | 241.79 ms | 10.0% |
  | `001_p.stl` | 32,138 / 96,414 | 258.61 ms | 210.49 ms | 48.11 ms | 18.6% |
  | `005_p.stl` | 166,672 / 500,016 | 1280.41 ms | 1122.50 ms | 157.91 ms | 12.3% |
  | `DentalModel_2.stl`（commit 前補驗） | 367,506 / 1,102,518 | 8407.90 ms | 7527.01 ms | 880.89 ms | 10.5% |

  百分比為 `extract_model_features()` 呼叫本身（D4 實際改動的函式）的改善幅度，非整個 `confirm_dental_model_type()` API 呼叫的改善幅度——後者還包含 `_compute_signals()`／`_get_drill_detection_plan()`／分支判斷邏輯，以及（`needs_drill=True` 時）後續的 `detect_drill_holes()`；PCA／OpenBoundary／FlatPlane 三組**已經包含在** `extract_model_features()` 之內，不是額外成本。所有模型上 `confirmed` 結果與 ProjectionShape 呼叫次數（`0`）皆與預期相符。

  **完整 `confirm_dental_model_type(mesh, INTRAORAL_SCAN)` 配對量測（commit 前補驗，`001_p.stl`／`005_p.stl`／`DentalModel_2.stl`，同一 process、同一暖機條件、各 3 runs；「修改前」以 monkeypatch 讓 `extract_model_features()` 忽略傳入的 `skip_projection_shape` 一律強制完整計算，藉此在不永久修改 production decision logic 的前提下重建修改前行為，「修改後」直接呼叫未改動的正式程式碼）**：

  | 模型 | before confirm avg | after confirm avg | saved | improvement | confirmed before | confirmed after |
  |---|---|---|---|---|---|---|
  | `001_p.stl` | 250.96 ms | 190.44 ms | 60.53 ms | 24.1% | False | False |
  | `005_p.stl` | 3352.94 ms | 2656.68 ms | 696.26 ms | 20.8% | False | False |
  | `DentalModel_2.stl` | 8548.99 ms | 6789.75 ms | 1759.23 ms | 20.6% | False | False |

  三個模型 `confirmed` 結果修改前後完全一致。此表衡量的是整個公開 API 呼叫（`extract_model_features()` + 分支判斷邏輯）的改善幅度，與上表「僅 `extract_model_features()` 本身」的改善幅度（10～19%）是兩個不同的量測目標，數字不可直接比較或替換——兩次量測分屬不同 script 執行、不同時間點，`005_p.stl`／`DentalModel_2.stl` 的絕對 ms 之間存在明顯落差（例如 `005_p.stl` 在 `extract_model_features()`-only 量測中 before avg 為 1280.41 ms，此處整個 confirm() 呼叫的 before avg 卻是 3352.94 ms），研判為兩次獨立 process 執行之間機器負載差異所致（與上方「限制說明」段落描述的跨 process 雜訊性質相同），而非同一次量測內部的矛盾——同一次量測內部（before/after 同一 process、同一暖機）的相對關係（saved ms／improvement %）仍然有效可信。

  **`INTRAORAL_SCAN=True` correctness 案例（P3 大型開放邊界分支，補驗）**：沿用上一輪 baseline 調查中找到的既有 deidentification fixture（`openspec/changes/backend-slicer-engine-deidentification/evidence/windows/functional-7.6-20260719T143000Z/fixture/model.stl`，faces=12／vertices=36，`classify_dental_model()` = `intraoral_scan`）。完整 ProjectionShape 計算下 `confirm(mesh, INTRAORAL_SCAN)` = `True`；skip ProjectionShape（正式 production 路徑）下同樣 `= True`——兩者相符，補上了 D4 目前唯一缺少的「INTRAORAL_SCAN 為 True」真實案例（先前 Ushape／001_p／005_p／DentalModel_2 皆為 `confirmed=False` 的案例）。此分支的正式合成回歸已由 `test_confirm_matches_classify_for_all_targets[P3_large_open_boundary]` 涵蓋，本次補驗屬於錦上添花，非缺口修補。

**限制說明**：跨 process 的獨立量測（分別各自 3 runs 的「先量測修改前 baseline，之後才實作，再另開 process 量測修改後」）顯示的 saved ms 略低於上表（例如 `Ushape1.stl` 約 136ms 而非 338ms），推測主因是兩次量測的 warm-up 呼叫次數不同（修改前腳本在計時前多跑了一次完整 `classify_dental_model()`，修改後腳本沒有）造成製程/mesh cache 熱度不對等；上表的單一 process 配對量測（同一次呼叫暖機、同一 code state 下直接比較 `skip_projection_shape=False` vs `True`）排除了這個變因，視為本項改動更準確的效能數字，兩者量級一致（同為數十至數百毫秒級的改善），方向與可靠性結論不變。

### D5：Upload／save 對相同 STL bytes 避免重複完整 parse

**根因**：`_validate_stl_bytes()`（[api_v2.py:193](../../../agent/api_v2.py#L193)）對輸入 bytes 執行完整 `trimesh.load()`。`upload_model_file()`（[api_v2.py:364](../../../agent/api_v2.py#L364)）在 [api_v2.py:389](../../../agent/api_v2.py#L389) 呼叫一次後，把已驗證的 bytes 存進 `pending["models"]`；execute 時 `_save_model_to_job()`（[api_v2.py:207](../../../agent/api_v2.py#L207)）在 [api_v2.py:211](../../../agent/api_v2.py#L211) 對**同一份不可變 bytes** 再完整 parse 一次才落地寫檔。`upload_support_file()`（[api_v2.py:406](../../../agent/api_v2.py#L406)）同構。

**呼叫範圍確認（安全邊界的關鍵）**：`pending["models"]` 只有兩個寫入點——`upload_model_file()`（已於 [api_v2.py:389](../../../agent/api_v2.py#L389) 驗證）與 `use_model_from_job()`（[api_v2.py:445](../../../agent/api_v2.py#L445)）。後者直接讀取**另一個 job 的既有輸出檔案**（例如 `boolean.stl`）並附加進 `pending["models"]`（[api_v2.py:467-472](../../../agent/api_v2.py#L467-L472)），**從未呼叫 `_validate_stl_bytes()`**——`_save_model_to_job()` 的驗證是這條路徑落地前**唯一**一次驗證。若不分來源一律略過 `_save_model_to_job()` 的驗證，會讓 `use_model_from_job()` 引用的內容完全不受驗證，是正確性倒退而非純效能改動。

**修法方向**：在 `pending["models"]` 的字典項加入一個標記（例如 `"validated": True`），只在 `upload_model_file()` 與 `upload_support_file()`（已呼叫 `_validate_stl_bytes()` 之後）設置；`use_model_from_job()` 附加的項目不設置此標記（或顯式設為 `False`）。`_save_model_to_job()` 只在該標記為真時略過 `_validate_stl_bytes()`，其餘情況（標記缺失或為假）維持現行的完整驗證。

**風險**：任何未來新增的 `pending["models"]` 寫入點，若忘記設置驗證標記，預設值 SHALL 為「需要驗證」（即標記缺失視同未驗證），避免新寫入點意外略過驗證——這點 SHALL 反映在 task 的回歸測試中（斷言預設/缺失狀態仍會觸發驗證）。

## Risks / Trade-offs

- **[D1 面數門檻邊界情況未被端到端案例覆蓋]** 理論風險窄縮在單一 component 面數恰好落在 98～99 且有小洞的邊界；目前的實測案例未剛好命中此邊界。→ 已用真實 hollow mesh 驗證 face count／vertices／significant components 完全一致；若未來观察到判定差異，回滾為單一 commit revert（見 Migration Plan）。
- **[D2 mesh 物件重用引入非預期的 cache 副作用]**（已解決）`_is_u_arch_from_low_sections()` 對 mesh 呼叫 `.section()` 等方法可能填入 trimesh 內部 cache。→ trimesh 4.11.1 原始碼追蹤 + `agent/tests/test_ortho_clean_mesh_reuse.py` 的 mutation 測試確認只填入 `_cache`，不修改 `.vertices`／`.faces`／`.bounds`；`001_p.stl`／`005_p.stl` 端到端 byte-for-byte SHA-256 驗證（修改前後皆一致）與新增的 integration-style 測試確認「重用物件」與「原本兩次獨立載入」在 Step 3 對齊後的幾何一致，未觀察到 regression。
- **[D3 Boolean 中間表示法改變後幾何非 byte 相同]（風險已成真，非僅假設）** 實作後端到端驗證，`001_p.stl`／`005_p.stl` 的 `ortho_result.stl` 確實出現 `is_watertight` 從 `True` 變 `False` 的 regression——不是「face ordering 不同」這種良性差異，而是真正的 validity 倒退。根因是 STL 格式無共享頂點索引，鏈式運算累積 3 次無中間校正後，產生任何合理 tolerance 都無法無歧義焊接的近重合頂點。→ 嘗試 6 種修法（詳見 design.md D3「調查結果」小節）皆無法在兩個代表模型上同時通過，且瑕疵發生的交接點因模型而異，判定不存在安全的部分鏈式方案。**已放棄本項優化**，Step 7～10 維持修改前的逐步 `boolean_meshes()` 呼叫；`boolean_meshes()` 現有公開簽章與行為完全未變動。
- **[D4 誤判 target 導致跳過必要特徵]**（已解決）若 `skip_projection_shape` 被錯誤地用在非 `INTRAORAL_SCAN` 的呼叫，會讓該次分類結果錯誤退化。→ 只在 `confirm_dental_model_type()` 內部依 `target` 條件式設置，不對外暴露為 API 參數；`agent/tests/test_dental_model_type_confirm.py` 的 8-target 不變量測試（13 組合成情境 × 8 target）與真實 `Ushape1~3.stl`（`u_shape_score=1.0` 的非退化邊界案例）8-target 掃描皆確認未觀察到任何 regression。
- **[D5 新寫入點遺漏驗證標記]** → 標記預設值為「需要驗證」（fail-safe），缺失時觸發驗證而非略過；回歸測試明確覆蓋此預設情況。
- **[量測結果與各項獨立 profiling 的估計值出入]** 5 項數字分別來自不同時間點的 source investigation，尚未在同一次端到端量測中彼此對照（僅 D1 已端到端實測）。→ 各項 task 的第一步都是建立最小必要 temporary timing 並重新實測，不直接沿用舊估計值；task 完成後移除 temporary timing。

## Migration Plan

分階段，每階段可獨立驗證與獨立 commit；階段編號與 [tasks.md](tasks.md) 一致。

| 階段 | 內容 | 決策 | 回滾方式 |
|---|---|---|---|
| 0 | 共用基準模型與量測慣例（不引入永久 framework） | — | — |
| 1 | Hollow-fit split `repair=False`（已完成，待補：移除殘留的 temporary log） | D1 | 單一 commit revert |
| 2 | Ortho cleaned mesh 物件重用（已完成） | D2 | 單一 commit revert |
| 3 | Boolean Step 7～10 維持 Manifold 表示法 | D3 | **not viable（已調查放棄，未落地，無需 revert）** |
| 4 | `confirm-model-type` 略過 ProjectionShape（已完成） | D4 | 單一 commit revert |
| 5 | Upload／save 重複驗證去重 | D5 | 單一 commit revert |
| 6 | 整合驗證與收尾 | — | — |
| 7 | 不在本變更範圍（僅記錄） | — | — |

每一項改動皆為純效能／實作層級變更，SHALL 各自通過該項自訂的驗收線才可視為完成；不要求全部 5 項完成後才能合併——與 `optimize-slice-performance` 先例相同，完成一項即可獨立 commit。

## Open Questions

- ~~**D1 的 temporary log 是否已清除？**~~ **已解決。** `[HOLLOW_FIT_PROFILE]` 相關的 `# TEMP HOLLOW_FIT_PROFILE` 標記程式碼（`import time`、三處 `logger.info(...)` 與其計時變數）已全數移除；`grep -rn "TEMP HOLLOW_FIT_PROFILE\|\[HOLLOW_FIT_PROFILE\]" agent/ortho_pipeline.py` 確認無殘留。正式程式碼只保留 `hollow_mesh.split(only_watertight=False, repair=False)` 與說明安全性理由的註解。tasks.md 的 1.9／1.10 已標記完成。
- ~~**D3 的 `flip_mesh_faces` 是否值得下放到 Manifold 層級？**~~ **已失去意義。** D3 本身已判定 not viable 並放棄，鏈式交接不再存在，此問題不再適用。
- **Prusa Hollow／Support C++ 何時具備併入條件？** 待兩項各自完成 C++ 內部分段 profiling、定位出具體修法後，再判斷是續開新變更或併入本提案的後續版本。

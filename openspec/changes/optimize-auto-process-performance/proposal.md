## Why

Agent 的 Auto Process（Ortho 自動化流程）與其周邊 API 執行在**使用者不可控的個人電腦上**，一趟流程串接了 hollow 生成、多次 mesh 載入、四段 Boolean、模型分類與檔案驗證等步驟。前一輪針對 Hollow-fit 判斷的調查與實測（`archive` 前身：暫時性的 `AP_PROFILE` 全鏈路 timing，已在調查結束後移除）已確認：**多個步驟存在與功能無關的重複運算**——不是演算法本身慢，而是在演算法之外做了不必要的重工。

第一項（Hollow-fit component split 的 `repair=False`）已經完成實作與實測：以 `001_p.stl`、`005_p.stl` 兩個代表模型驗證，Hollow-fit check 階段耗時改善約 23%，且 split 出的 significant components、`_min_width_xy` 與 `_radial_center_opening_stats_xy` 的判定結果與修改前完全一致（見 `design.md` D1 的驗證記錄）。

在同一輪 source tracing／profiling 中，另外還定位出四個**根因已確認、修法方向已明確**的重複運算，範圍同屬 `agent/` 後端（不觸及 `third_party/prusaslicer_fork`）：Ortho pipeline 對同一份 cleaned STL 重複 `load_trimesh()`、Boolean Step 7～10 之間不必要的 `Manifold → Trimesh → Manifold` 往返、`confirm-model-type(target_type=intraoral_scan)` 計算了從未被讀取的 `ProjectionShape` 特徵、以及 upload 與 execute/save 兩個時間點對同一份不可變 STL bytes 各自完整 parse 一次。

參考 `archive/2026-08-06-optimize-slice-performance` 的先例：多項彼此獨立、但同屬一次調查產物的效能修正，適合放進同一個 proposal，各自獨立 task／驗證／commit，全部完成後再 archive。本提案即依此結構，把上述 5 項（含已完成的 Hollow-fit）納入同一個工作範圍；另外 7 項（Hex Grid raycast backend、Side-wall drains、Surgical Guide `_grow_patches`、Generate Drain Holes mesh construction、`clean_input_for_manifold` fast-path、Prusa Hollow/Support C++）因修法方向尚未收斂或缺乏內部分段 profiling，明確排除於本提案之外（見下方 Impact 與 `design.md` Non-Goals）。

## What Changes

- **Hollow-fit component split 改用 `repair=False`**（已完成）：`hollow_mesh.split(only_watertight=False, repair=False)` 取代預設 `repair=True`，省去 trimesh 對每個 component 執行的 `fill_holes()`。Significant-component 篩選與後續幾何判定 SHALL 與修改前完全一致。
- **Ortho cleaned mesh 物件重用**：`run_ortho_pipeline()` 對同一份 `model_clean.stl` 的 U-arch 判斷與 Step 3 對齊 SHALL 只 `load_trimesh()` 一次，重用已載入的 mesh 物件，而非各自從磁碟重新讀取。
- ~~**Boolean Step 7～10 維持 Manifold 表示法**~~ **已調查、實作、benchmark，證實 not viable，放棄。** 已實作讓 Step 7～10 中間結果在鏈式呼叫之間維持 `manifold3d.Manifold` 的版本，但端到端驗證發現會在 `001_p.stl`／`005_p.stl` 至少一個代表模型上使 `ortho_result.stl` 失去 `is_watertight`，且找不到對兩者都安全的部分鏈式組合（嘗試矩陣與根因見 `design.md` D3 小節）。Step 7～10 維持修改前的逐步 `boolean_meshes()` 呼叫，本項不帶來效能改善。
- **`confirm-model-type(target_type=intraoral_scan)` 略過 ProjectionShape**：當呼叫端只需要確認模型是否為 `intraoral_scan` 時，特徵擷取 SHALL 略過 `projection_shape_gap_stats()` 的計算——原始碼追蹤確認 `confirm_dental_model_type()` 對此 target 的**所有**分支（P0／P_base／P2／P3／needs_drill 早退／P5）皆不讀取 `u_shape_score`（唯一消費 ProjectionShape 特徵的訊號）。`classify_dental_model()`（不知道目標類型，必須支援全部八種分類）與其餘 target 的 `confirm_dental_model_type()` 呼叫 SHALL 不受影響，繼續計算完整特徵。
- **Upload／save 對相同 STL bytes 避免重複完整 parse**：透過 `upload_model_file()` 或 `upload_support_file()` 上傳、且已通過 `_validate_stl_bytes()` 驗證的內容，SHALL 在 `_save_model_to_job()` 落地時略過第二次完整 parse。透過 `use_model_from_job()` 引用其他 job 產出檔案（從未經過上傳驗證）的內容 SHALL 不受影響，繼續在 `_save_model_to_job()` 完整驗證一次——這是落地前**唯一**一次驗證，不得省略。

## Capabilities

### New Capabilities

- `auto-process-performance`：定義「純效能改動不得改變可觀察行為與幾何語意」的共通契約，以及本提案各項改動各自的具體驗收線（regression gate）。原始範圍列出 5 項，其中 Boolean Step 7～10 維持 Manifold 表示法（D3）已調查並證實 not viable，放棄——詳見 `design.md`。與 `sla-raster-performance` 先例的差異：Boolean 表示法改變後，幾何等價的結果可能有不同 triangle／face ordering，因此驗收線 SHALL 以「可觀察行為與幾何語意等價」表達，而非要求輸出檔案 byte-for-byte 相同；各項改動自行定義該項適用的等價判準（fit 判定一致／幾何等價／Boolean 結果的幾何與 validity semantics 等價／model-type 確認結果一致／原本的接受或拒絕行為一致）。

### Modified Capabilities

（無。本提案 5 項改動皆為純效能／實作層級變更，不改變任何既有 capability 的 spec 層級行為——`hex-grid-layout`、`dental-model-type-confirm`、`dental-model-classification` 既有 requirement 的輸入輸出契約與判定結果集合維持不變，因此不需要 delta spec。）

## Impact

**本 repo（web_slicer_core），僅 `agent/` Python 端，不觸及 `third_party/prusaslicer_fork`：**

- `agent/ortho_pipeline.py`：Hollow-fit split 呼叫（已完成）；`_is_u_arch_from_low_sections()` 與 Step 3 對齊之間的 `load_trimesh()` 重複呼叫（已完成）；Step 7～10 的 `boolean_meshes()` 呼叫鏈（已調查並放棄，見 `design.md` D3 小節與 Non-Goals）。
- `agent/sla_operations.py`：`boolean_meshes()`（已調查並放棄鏈式介面改動，見 `design.md` D3 小節與 Non-Goals）。
- `agent/model_classifier.py`：`extract_model_features()`、`confirm_dental_model_type()`。
- `agent/api_v2.py`：`upload_model_file()`、`upload_support_file()`、`use_model_from_job()`、`_save_model_to_job()`、`_validate_stl_bytes()`。
- 測試：`agent/tests/test_ortho_hollow_split_repair.py`（已存在，Hollow-fit）；其餘 4 項各自於對應 task 補齊最小必要回歸測試。
- 規格：新增 `openspec/specs/auto-process-performance/spec.md`（本提案 archive 時同步）。

**明確排除於本提案之外（見 `design.md` Non-Goals）：**

Hex Grid raycast backend、Side-wall drains 幾何搜尋、Surgical Guide `_grow_patches` 等、Generate Drain Holes mesh construction、`clean_input_for_manifold` fast-path、Prusa Hollow C++、Prusa Support C++。這 7 項目前仍需要 prototype、進一步 profiling 或方案收斂，尚不具備寫成可驗收 task 的具體實作方向；其中 Prusa 兩項另涉及 `third_party/prusaslicer_fork` submodule，成熟後是否併入本提案或另開變更，留待方向明確後再判斷。

**尚未驗證的前提**

本提案的量化數字（Hollow-fit 23%、Boolean 中間轉換約 1.31 秒等）分別來自各項目各自的 source investigation／profiling，並非同一次端到端量測；且部分數字尚未在完整 Auto Process 端到端流程中重新確認（僅 Hollow-fit 已完成端到端實測）。各項 task 的第一步皆為建立最小必要的 temporary timing 並實測，而非直接假設既有估計值成立。

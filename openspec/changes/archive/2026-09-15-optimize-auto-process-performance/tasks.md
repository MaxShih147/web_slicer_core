> **驗證原則**：每個 task 群組結束前必須通過該群組自己的驗證任務才可視為完成。禁止累積到最後才驗證。每個群組完成即可獨立 commit，不需要等待其他群組完成——與 `archive/2026-08-06-optimize-slice-performance` 先例相同。
>
> **驗收線原則**：本提案 MUST NOT 以「輸出檔案 byte-for-byte 完全相同」作為統一驗收線（Boolean 表示法改變後，幾何等價的結果可能有不同 triangle／face ordering）。每個群組依 `specs/auto-process-performance/spec.md` 中對應 requirement 定義的等價判準驗證。
>
> **Temporary timing 原則**：每個群組如需暫時性 timing／profiling code，SHALL 遵循「加入最小必要 timing → 執行修改前後 benchmark → 記錄結果 → 驗證完成後移除」的流程。除非有獨立理由，正式 production code 不保留效能調查用 log。不建立新的永久 profiling framework。
>
> **測試素材**：Auto Process 端到端沿用 `001_p.stl`、`005_p.stl` 兩個代表模型。個別群組若需要更聚焦的素材（單一 mesh、單一 API 請求），於該群組任務中另行指定。

## 0. 共用基準與量測慣例

- [x] 0.1 確認代表模型：`001_p.stl`、`005_p.stl`（沿用 Hollow-fit 已使用的基準模型）
- [x] 0.2 確認量測方法：暫時性 `logger.info()` timing log，以固定前綴（例如群組 1 的 `[HOLLOW_FIT_PROFILE]`）標記，並以 `# TEMP <TAG>` 註解讓程式碼可被單一搜尋定位與移除
- [ ] 0.3 為群組 2～5 各自約定本群組專用的 timing log 前綴（實作該群組時再加入，事先只需約定命名規則，不預先寫入程式碼）

## 1. Hollow-fit component split `repair=False`（已完成）

- [x] 1.1 [ortho_pipeline.py:954](../../agent/ortho_pipeline.py#L954) 的 `hollow_mesh.split(only_watertight=False)` 改為 `hollow_mesh.split(only_watertight=False, repair=False)`，並加上說明安全性理由的註解
- [x] 1.2 以 trimesh 原始碼追蹤確認：`graph.split()` 預設 `repair=True` 會對每個 component 呼叫 `fill_holes()`，即使 `only_watertight=False` 時其回傳值不影響篩選
- [x] 1.3 以 trimesh `repair.fill_holes()` 原始碼追蹤確認：只能補單三角形／單四邊形邊界洞，且從不新增頂點
- [x] 1.4 建立 `agent/tests/test_ortho_hollow_split_repair.py`：pin 住呼叫點確實使用 `repair=False`；驗證 `fill_holes()` 不新增頂點；驗證 repair 開關下 split 出的每個 component 幾何一致
- [x] 1.5 **驗證**：以合成 mesh（單三角形邊界洞 + 獨立小 box）測試 `repair=True`／`False` 兩者的 component vertices 完全一致，face count 差異在預期範圍內（0 或 1）
- [x] 1.6 **驗證**：以真實 PrusaSlicer `--export-hollow-stl` 輸出（一般品質 32,776 faces／5 components、高品質 400,428 faces）分別測試，`repair=True`／`False` 兩者的 significant components、face count、vertices 完全一致
- [x] 1.7 **量測**：高品質 hollow mesh 下 `repair=False` 較 `repair=True` 快約 2.5 倍（0.12s vs 0.31s）
- [x] 1.8 **端到端驗證**：以 `001_p.stl`、`005_p.stl` 各跑 3 次完整 Auto Process，記錄 `[HOLLOW_FIT_PROFILE]` 的 `hollow_load_ms`／`split_ms`／`hollow_fit_total_ms`。Hollow-fit check 階段（扣除 hollow load）較舊基準改善約 23%（`001_p.stl` 2150.91ms → 平均 1647.35ms，約 −503.56ms／−23.4%；`005_p.stl` 1837.59ms → 平均 1420.73ms，約 −416.86ms／−22.7%）；功能結果（`fits=True` 判定、significant component 選取）兩模型均與修改前一致，後續 Hex Grid／Drain／Boolean face counts 與最終 Ortho 幾何結果未觀察到 regression。詳細數字見下方「量測記錄」
- [x] 1.9 **收尾**：移除 [ortho_pipeline.py](../../agent/ortho_pipeline.py) 中的 `# TEMP HOLLOW_FIT_PROFILE` 標記程式碼——`import time`（確認全檔無其他用途後一併移除）、`_hf_t_total`／`_hf_t0` 計時變數，以及三處 `logger.info("[HOLLOW_FIT_PROFILE] ...")`。正式程式碼中只保留 `hollow_mesh.split(only_watertight=False, repair=False)` 與說明安全性理由的註解
- [x] 1.10 **驗證**：移除 temporary log 後重新執行 `pytest agent/tests/test_ortho_hollow_split_repair.py -v`（3 passed）；`grep -rn "TEMP HOLLOW_FIT_PROFILE\|\[HOLLOW_FIT_PROFILE\]" agent/ortho_pipeline.py` 無結果；`python -c "import ast; ast.parse(...)"` 與 `import agent.ortho_pipeline` 均正常；`pytest agent/tests/ -q` 619 passed、7 failed（皆為變更前既有、與本項無關的環境依賴問題，見量測記錄）

## 2. Ortho cleaned mesh 物件重用（已完成）

- [x] 2.1 確認 `_is_u_arch_from_low_sections()`（[ortho_pipeline.py:638](../../agent/ortho_pipeline.py#L638)）在專案內的唯一呼叫點為 [ortho_pipeline.py:778](../../agent/ortho_pipeline.py#L778)（已於本提案撰寫時以 `grep` 確認，實作前重新確認一次以防途中有新呼叫點加入）——source investigation 與實作前各重新 `grep` 一次，皆確認唯一呼叫點成立，過程中未發現新增呼叫點
- [x] 2.2 將 `_is_u_arch_from_low_sections()` 簽章由 `(input_path: Path) -> bool` 改為接受已載入的 mesh（例如 `(mesh: "trimesh.Trimesh") -> bool`），移除內部 [ortho_pipeline.py:652](../../agent/ortho_pipeline.py#L652) 的 `load_trimesh(input_path)` 呼叫——已改為 `_is_u_arch_from_low_sections(mesh: "trimesh.Trimesh") -> bool`（[ortho_pipeline.py:637](../../agent/ortho_pipeline.py#L637)），函式內部改用傳入的 `mesh`（區域變數沿用既有的 `m` 名稱），內部 `load_trimesh()` 呼叫已移除
- [x] 2.3 於 `run_ortho_pipeline()` 在 [ortho_pipeline.py:775](../../agent/ortho_pipeline.py#L775)（`input_path = cleaned_path` 之後）呼叫一次 `load_trimesh(input_path)`，把得到的 mesh 物件同時傳給 U-arch 判斷（2.2 的新簽章）與後續 Step 3 對齊，移除 [ortho_pipeline.py:1054](../../agent/ortho_pipeline.py#L1054) 原本的重複載入——已在 `input_path = cleaned_path` 之後新增單一次 `input_mesh = load_trimesh(input_path)`（[ortho_pipeline.py:781](../../agent/ortho_pipeline.py#L781)），同時交給 `_is_u_arch_from_low_sections(input_mesh)`（[:784](../../agent/ortho_pipeline.py#L784)）與 Step 3 對齊；Step 3 原本的 `load_trimesh(input_path)` 已移除，直接沿用同一個 `input_mesh`；重用的是**export 後第一次 reload 出來的 mesh**，並非 `clean_input_for_manifold()` 內部 export 前的 pre-export mesh（未修改 `clean_input_for_manifold()` 回傳型別）；未加 `.copy()`；未引入 global cache
- [x] 2.4 加入本群組專用 timing log（前綴依 0.3 的約定），只包住兩次 `load_trimesh()` 呼叫（重用前）與一次 `load_trimesh()` 呼叫（重用後）——`[CLEAN_MESH_REUSE_PROFILE]` 前綴：重用前記錄 `u_arch_load_ms`／`step3_load_ms`／`reload_total_ms`；改為單次載入後記錄 `shared_load_ms`；全數以 `# TEMP CLEAN_MESH_REUSE_PROFILE` 標記，已於 2.9 移除
- [x] 2.5 **驗證**：比對「U-arch 判斷後重用同一物件」與「兩次各自獨立載入」，Step 3 對齊使用的 `input_mesh` 之 `.vertices`、`.faces`、`.bounds` 逐一相等——`agent/tests/test_ortho_clean_mesh_reuse.py::test_load_trimesh_reload_is_deterministic` 以 `numpy.array_equal` 精確比對（無放寬 tolerance），確認對同一份 STL 兩次獨立 `load_trimesh()` 得到的 `.vertices`／`.faces`／`.bounds` 完全相等，故重用單次載入與原本兩次獨立載入在下游可觀察行為上等價
- [x] 2.6 **驗證**：以會被判定為 U-arch 的模型與不會被判定為 U-arch 的模型各執行一次，確認 U-arch 判斷結果與重用前一致（不影響 `_complete_as_no_hollow` 提前結束的路徑）——單元層級：`test_u_arch_detection_true_for_horseshoe`／`test_u_arch_detection_false_for_solid_base` 確認簽章改動後判定結果不變；`test_u_arch_check_does_not_mutate_mesh`／`test_u_arch_check_does_not_mutate_mesh_non_u_arch_case` 確認 U-arch 判斷對 mesh 完全 read-only（`.vertices`／`.faces`／`.bounds` 呼叫前後不變）。Integration 層級：`test_u_arch_pipeline_takes_early_return_without_second_load` 實際呼叫 `run_ortho_pipeline()`（PrusaSlicer 的 `generate_hollow` 以 monkeypatch 替換為呼叫即失敗的 stub，用以偵測 Step 1 是否被誤觸發），確認 U-arch=True 時：(a) `model_clean.stl` 全程只 `load_trimesh()` 一次、(b) 確實走到 `_complete_as_no_hollow()` 並正常寫出 `status.json`／`ortho_result.stl`、(c) Step 1 `generate_hollow()` 未被呼叫，提前結束行為與重用前完全一致
- [x] 2.7 **驗證**：以 `001_p.stl`、`005_p.stl` 端到端執行完整 Auto Process，`ortho_result.stl` 與修改前逐位元組相同（此項改動不涉及 Boolean 表示法，適用 byte-for-byte 比對）——修改前後各 3 runs，兩模型的 `ortho_result.stl` SHA-256 皆逐位元組相同（`001_p.stl`：`BB150F743F6370AE01E8E5577E1110902074C3D68CB24AF93F579F24473E0912`；`005_p.stl`：`2E06094A2F19DBD8004D573C71B4F93FDAC0B82897D86AF09575AC64AF3BD2F7`），修改前、修改後各自 3 runs 皆一致，byte-for-byte gate 有效通過
- [x] 2.8 **量測**：記錄重用前後省下的載入耗時，記入下方「量測記錄」——見下方「量測記錄」群組 2
- [x] 2.9 **收尾**：移除本群組的 temporary timing log；`pytest agent/tests/` 全數通過（既有失敗項目除外，見群組 6）——`# TEMP CLEAN_MESH_REUSE_PROFILE`／`[CLEAN_MESH_REUSE_PROFILE]`／`shared_load_ms` 已全數移除（`grep` 確認無殘留）；本輪新增的 `import time` 亦已移除（確認全檔無其他用途後一併移除）；`pytest agent/tests/ -q --continue-on-collection-errors` 結果 626 passed、7 failed、3 collection errors，與移除前（未計入本群組新測試）的既有基準（619 passed、7 failed、3 collection errors）相比，failed／collection error 數量完全一致，新增的 626−619=7 皆為本群組新增測試，未觀察到新的 regression
- [x] 2.10 補最小必要回歸測試（新增或併入 `agent/tests/`），至少涵蓋 2.5／2.6 的兩個驗證情境——新增 `agent/tests/test_ortho_clean_mesh_reuse.py`，共 7 個測試：reload 確定性（2.5）、U-arch 判斷 read-only（U-arch／非 U-arch 兩情境，2.6）、U-arch/非 U-arch 判定結果 pin、`run_ortho_pipeline()` 上 U-arch=True 提前結束路徑的 integration-style pin（2.6）、以及原始碼層級 pin（`load_trimesh(input_path)` 全檔僅 1 處、`_is_u_arch_from_low_sections` 簽章與呼叫點）

## 3. Boolean Step 7～10 維持 Manifold representation（已調查、實作、benchmark，證實 not viable，已放棄）

> **狀態總結**：3.1～3.9 皆已實際執行過一輪（含實作、timing、端到端 benchmark），但 3.5（`is_watertight` 驗證）未通過——`001_p.stl`／`005_p.stl` 兩個代表模型上，鏈式維持 `Manifold` 的實作在其中至少一個模型上總是產生 `is_watertight=False` 的 regression，且找不到對兩者都安全的部分鏈式組合（詳見 [design.md](design.md) D3 小節「調查結果」的 6 種嘗試與其結果表）。因此判定本群組 **not viable**，已用 `git checkout` 還原 `agent/ortho_pipeline.py`／`agent/sla_operations.py` 至群組 2 完成時的狀態（Step 7～10 回到逐步 `boolean_meshes()` 呼叫），並移除本群組新增的 `[BOOLEAN_MANIFOLD_PROFILE]` temporary timing 與回歸測試檔案。checkbox 維持未勾選，因為最終沒有任何程式碼異動留在 `dev` 分支上；下方逐項記錄仍保留過程供未來參考。

- [ ] 3.1 於 `boolean_meshes()` 旁新增內部介面（`_boolean_meshes_chain()`／`_boolean_materialize_chain_result()`／`_boolean_ensure_trimesh()`），允許鏈式交接維持 `Manifold`——**已實作並驗證公開簽章不受影響**，但整體方向隨 3.5 失敗而還原，不保留在程式碼中
- [ ] 3.2 於 `run_ortho_pipeline()` 的 Step 7～10 改用 3.1 的介面——**已實作並跑過完整 Auto Process**，隨 3.5 失敗還原
- [ ] 3.3 加入本群組專用 timing log（`[BOOLEAN_MANIFOLD_PROFILE]`）——**已加入並用於 before／after 量測**，收尾時隨程式碼一併還原移除（見下方「量測記錄」）
- [ ] 3.4 **驗證**：volume 在容許誤差內相等——**通過**（兩模型鏈式與非鏈式路徑 volume 完全一致，見量測記錄）
- [ ] 3.5 **驗證**：`is_watertight` 狀態相等——**未通過，本群組失敗的關鍵驗證**。`001_p.stl` 在「只物化 Step 9→10 或只物化 Step 8→9」時可通過，但 `005_p.stl` 在同樣條件下仍為 `False`，唯一能讓兩者都通過的组合是「三個交接全部物化」（＝無優化）。詳細嘗試矩陣見 design.md
- [ ] 3.6 **驗證**：非鏈式呼叫不受影響——**確認為真，但基礎前提有修正**：source tracing 發現 `boolean_meshes()` 目前**只有** Step 7～10 這 4 個呼叫點，獨立 Boolean API 端點實際呼叫的是另一條路徑（`perform_boolean()` → `boolean_operation()`，路徑版，完全不同函式），因此「非鏈式呼叫」目前是假設情境而非現存風險；`boolean_meshes()` 公開簽章與行為本身確認未被本群組改動觸及
- [ ] 3.7 **驗證**：Step 7～10 不拋例外、`ortho_result.stl` 正常匯出——**通過**（兩模型 3 runs 皆 `status=completed`、檔案皆正常匯出），但正常匯出不代表幾何有效，3.5 才是真正擋下本群組的驗證
- [ ] 3.8 **量測**：確認耗時下降——**確認下降**（Step 7～10 合計耗時，chain 版本 3-run 平均較 baseline 少約 30～45%，見量測記錄），但因 3.5 未通過，此效能改善不能兌現
- [ ] 3.9 **收尾**：移除 temporary timing log——**已完成**（隨整組程式碼 `git checkout` 一併移除，非單獨移除 log）
- [ ] 3.10 補最小必要回歸測試——**已寫（`agent/tests/test_boolean_meshes_chain.py`，9 個測試，涵蓋 3.4／3.5／3.6）**，隨程式碼還原一併刪除（測試的是不會落地的函式，保留無意義）

## 4. `confirm-model-type(target_type=intraoral_scan)` 略過 ProjectionShape（已完成）

> **Test-first**：4.10 的正式回歸測試先於 4.1／4.2 的 production 修改寫成並執行——8-target 不變量與 caller-boundary 測試在修改前即 21 passed／1 failed（`test_confirm_intraoral_scan_skips_projection_shape` 如預期為 red），實作落地後同一份測試 22 passed（green）。

- [x] 4.1 於 [model_classifier.py:543](../../agent/model_classifier.py#L543) 的 `extract_model_features()` 新增 `skip_projection_shape: bool = False` 參數，為真時略過 ProjectionShape try 區塊（含 PCA-axes 可用性檢查），欄位維持 `ModelFeatures` 預設值 `None`——與既有「ProjectionShape 演算法失敗」時的欄位狀態相同，`_compute_signals()` 不需新增分支
- [x] 4.2 於 [model_classifier.py:1394](../../agent/model_classifier.py#L1394) 的 `confirm_dental_model_type()`，改為 `extract_model_features(mesh, skip_projection_shape=(target == DentalModelType.INTRAORAL_SCAN))`；`classify_dental_model()`（[model_classifier.py:1366](../../agent/model_classifier.py#L1366)）未改動，仍以 `extract_model_features(mesh)` 呼叫，永遠完整擷取。`skip_projection_shape` 未暴露為 API 參數
- [x] 4.3 加入本群組專用 timing log（`[PROJECTION_SHAPE_PROFILE]`，延續上一輪 baseline 調查已加入的版本），只包住 `projection_shape_gap_stats()` 呼叫本身，用於本群組的修改前／修改後量測，4.9 收尾時移除
- [x] 4.4 **驗證**：`agent/tests/test_dental_model_type_confirm.py::test_confirm_matches_classify_for_all_targets`——13 組合成特徵情境（以真實 `_compute_signals()`／`_get_drill_detection_plan()`／`_decide_model_type_with_details()` 跑過驗證取得 ground truth，涵蓋 P0／P_base×2／P2／P3／P5.1／P5.2×5／P5.3×2，8 種 `DentalModelType` 全部至少出現一次）× 8 target，共 104 個斷言，確認 `confirm(mesh,t) == (classify(mesh)==t)` 無例外成立；`detect_drill_holes()` 若在未預期情境下被呼叫會主動 raise，額外守住 early-return 分支
- [x] 4.5 **驗證**：真實 U-arch STL（`C:\Users\user\Pictures\tempTest\Ushape1~3.stl` + `DentalModel_2.stl`，後者由使用者以人工 ground truth 指認、commit 前補驗）——四者皆為 `classify_dental_model()` 判定的 `u_shaped_dental_model`，完整 ProjectionShape 計算下 `u_shape_score` 四者皆為 `1.0`（非零、非退化邊界情況），`confirm(mesh, INTRAORAL_SCAN)` 在略過 ProjectionShape 前後四者皆回傳 `False`（相等），且對全部 8 個 target 掃描確認僅 `U_SHAPED_DENTAL_MODEL` 為 `True`，前後一致，與人工 ground truth 完全相符。另以 `001_p.stl`／`005_p.stl`（`u_shape_score=0.0`）交叉驗證同樣一致。**commit 前補驗**：另以既有 deidentification fixture（`intraoral_scan`，`confirm(mesh, INTRAORAL_SCAN)=True` 的案例，先前 4 個真實案例皆為 `False`）確認完整 ProjectionShape 與 skip ProjectionShape 兩者皆為 `True`，相符
- [x] 4.6 **驗證**：`agent/tests/test_dental_model_type_confirm.py::test_confirm_non_intraoral_scan_calls_projection_shape`（parametrize 全部 7 個非 INTRAORAL_SCAN target）——以 call-counting spy 包住真正的 `projection_shape_gap_stats()`（非以欄位 `None` 間接推測），確認每個非 INTRAORAL_SCAN target 仍恰好呼叫一次；`test_classify_dental_model_calls_projection_shape` 同法確認 `classify_dental_model()` 恰好呼叫一次；`test_confirm_intraoral_scan_skips_projection_shape` 確認 INTRAORAL_SCAN target 呼叫零次
- [x] 4.7 **驗證**：`import agent.api_v2` 正常、`/classify-model`／`/confirm-model-type` 兩端點程式碼路徑未改動（僅 `confirm_dental_model_type()` 內部呼叫多帶一個關鍵字參數）；`classify_dental_model()` 的呼叫方式與輸出型別（`DentalModelType`）不受影響——D4 改動完全不在 `classify_dental_model()` 的執行路徑上
- [x] 4.8 **量測**：見下方「量測記錄」群組 4。單一 process 配對量測（同一 code state 下 `skip_projection_shape=False` vs `True`，各自暖機後 3 runs）：`Ushape1~3.stl` 改善 10.0～14.4%（節省 242～338ms），`001_p.stl` 改善 18.6%（節省 48ms），`005_p.stl` 改善 12.3%（節省 158ms），`DentalModel_2.stl`（最大樣本，367,506 faces）改善 10.5%（節省 881ms）——皆為 `extract_model_features()` 呼叫本身的改善幅度；並以真正的 `confirm_dental_model_type(mesh, INTRAORAL_SCAN)` 呼叫確認 `[PROJECTION_SHAPE_PROFILE]` log 零次觸發。**commit 前補驗**：改以 monkeypatch 重建修改前行為（不永久改動 production），對完整 `confirm_dental_model_type(mesh, INTRAORAL_SCAN)` 公開 API 呼叫本身配對量測（`001_p.stl`／`005_p.stl`／`DentalModel_2.stl`）——改善 20.6～24.1%，`confirmed` 結果三者皆前後一致（False），此為整個 API 呼叫（含 `_compute_signals()`／`_get_drill_detection_plan()`／分支判斷）的改善幅度，與上方「僅 `extract_model_features()`」表分開記錄
- [x] 4.9 **收尾**：`# TEMP PROJECTION_SHAPE_PROFILE` 標記程式碼（`import time`、`_ps_t0` 計時變數、`logger.info("[PROJECTION_SHAPE_PROFILE] ...")`）已全數移除；`grep -rn "TEMP\|PROJECTION_SHAPE_PROFILE" agent/model_classifier.py` 無殘留；移除後重新執行 `agent/tests/test_dental_model_type_confirm.py`（22 passed）與 `agent/tests/`（654 passed、1 failed、3 errors——與移除前完全相同，4 項失敗皆為與本項無關的既有環境問題，見下方量測記錄）
- [x] 4.10 正式回歸測試已落地於 `agent/tests/test_dental_model_type_confirm.py`（不依賴根目錄未追蹤的 `test_classify_decision.py`／`test_classify_api.py`；source tracing 過程中確認後者已對不上目前 source——`_write_classification_txt` 在目前 `model_classifier.py` 中不存在，屬於既有 staleness，與本項改動無關）

## 5. Upload／save 重複 STL validation 去重（已完成）

> **二輪調查修正**：初版任務描述誤判 `pending["models"]` 只有兩個寫入點、且誤將 `upload_support_file()` 視為與 `upload_model_file()` 同構的重複驗證路徑。實作前重新 `grep` 後兩點皆被推翻，詳見 5.1 與下方「呼叫範圍確認」修正記錄；`design.md` D5 小節已同步更新。

- [x] 5.1 確認 `pending["models"]` 的全部寫入點——**重新 grep 後發現實際有三個，而非原假設的兩個**：[api_v2.py:391-398](../../agent/api_v2.py#L391-L398)（`upload_model_file()`，已驗證）、[api_v2.py:467-475](../../agent/api_v2.py#L467-L475)（`use_model_from_job()`，未驗證）、**[api_v2.py:338-360](../../agent/api_v2.py#L338-L360)（`add_models_to_slice_job()`，`POST /slices/{job_id}/models`，未驗證——初版調查完全遺漏此寫入點）**。另確認 `pending["support_stl"]` 的落地路徑（`execute` 內 [api_v2.py:504-507](../../agent/api_v2.py#L504-L507)）**直接 `open().write()`，完全不經過 `_save_model_to_job()`／`_validate_stl_bytes()`**，upload 時的驗證本來就是唯一一次，不存在重複驗證——`upload_support_file()` 因此排除於本群組範圍外，維持不變
- [x] 5.2 於 `upload_model_file()`（[api_v2.py:391-398](../../agent/api_v2.py#L391-L398)）已通過 [api_v2.py:389](../../agent/api_v2.py#L389) 驗證之後，append 的 dict 加入 `"validated": True`。`upload_support_file()` 因 5.1 確認不涉及重複驗證，未修改
- [x] 5.3 `use_model_from_job()`（[api_v2.py:467-475](../../agent/api_v2.py#L467-L475)）附加的項目顯式設 `"validated": False`；`add_models_to_slice_job()`（[api_v2.py:350-357](../../agent/api_v2.py#L350-L357)）同樣設 `"validated": False`，**且刻意放在 `{"id": model_id, **model, "validated": False}` 的 `**model` 展開之後**——該端點 body 是未經 schema 限制的任意 client dict，若標記放在展開之前，client 可在 request body 中夾帶 `"validated": true` 蓋掉系統值，讓自己的內容被誤判為已驗證；放在展開之後可確保這個欄位永遠由伺服器端決定
- [x] 5.4 `_save_model_to_job()`（[api_v2.py:207-222](../../agent/api_v2.py#L207-L222)）改為 `if model_data.get("validated") is not True: _validate_stl_bytes(content, "model")`——用 `is not True`（非單純 falsy 判斷）確保標記缺失、顯式 `False`、或任何非布林 truthy 值都會觸發完整驗證
- [x] 5.5 **量測方式**：本群組未在 production code 加入常駐 timing log——`_validate_stl_bytes()`／`_save_model_to_job()` 皆可在不修改 production code 的前提下由外部腳本直接量測 wall-clock 時間（呼叫真實函式、非 mock），因此改用 scratchpad 暫時性腳本（`d5_baseline_profile.py`／`d5_after_profile.py`，皆不在 repo 內，未 commit）分別在實作前／後各執行一次，取代「加 log → 移除 log」的既有模式
- [x] 5.6 **驗證**：透過 `upload_model_file()` 上傳合法 STL，`_save_model_to_job()` 不再次執行完整 `trimesh.load()` parse——`test_save_skips_second_parse_for_validated_item` 以 spy 包住 `_validate_stl_bytes()` 確認呼叫次數為 0，且落地檔案 bytes 與原始上傳內容逐位元組相同
- [x] 5.7 **驗證**：透過 `use_model_from_job()` 引用其他 job 輸出，`_save_model_to_job()` 仍執行完整驗證——`test_save_still_fully_validates_referenced_content` 確認 `_validate_stl_bytes()` 恰好呼叫一次；`test_save_still_rejects_corrupt_referenced_content` 刻意引用格式錯誤內容，確認仍回傳 `INVALID_MODEL`，與本群組改動前行為相同
- [x] 5.8 **驗證**：`pending["models"]` 項目不含驗證標記、顯式為 `False`、或標記值為非布林 truthy（`"yes"`）時，`_save_model_to_job()` 皆執行完整驗證——`TestMissingOrFalseFlagStillValidates` 三個測試涵蓋。另外，`add_models_to_slice_job()` 的 request body 若夾帶 `"validated": true`，落地後仍被強制為 `False`，且搭配偽造 `stl_data` 時 `_save_model_to_job()` 仍完整驗證並拒絕——`TestAddModelsToSliceJobCannotBypassValidation` 兩個測試涵蓋（此為二輪調查新發現的攻擊面，見 design.md D5「風險」）
- [x] 5.9 **量測**：以 `001_p.stl`、`005_p.stl` 直接呼叫 `upload_model_file()` → `_save_model_to_job()` 的真實函式序列（各 5 runs），記錄 `_save_model_to_job()` 驗證耗時差異——`001_p.stl` save 側由 avg 29.03ms 降至 0.92ms（約 −96.8%，合計 upload+save 由 63.73ms 降至 33.19ms，約 −47.9%）；`005_p.stl` save 側由 avg 190.93ms 降至 2.46ms（約 −98.7%，合計由 379.17ms 降至 207.20ms，約 −45.4%）。詳細數字見下方「量測記錄」群組 5
- [x] 5.10 **收尾**：無 production timing log 需要移除（見 5.5）；scratchpad 量測腳本從未寫入 repo，無需清理
- [x] 5.11 正式回歸測試已落地於 `agent/tests/test_save_model_to_job_validation.py`（11 個測試，涵蓋 5.6／5.7／5.8 全部情境，另加 `add_models_to_slice_job()` 的惡意標記防禦測試），延續本 repo 既有慣例直接呼叫 `api_v2` 模組函式，未新增 `TestClient`／`httpx` 依賴

## 6. 整合驗證與收尾（已完成）

- [x] 6.1 確認群組 1～5 的所有 temporary timing log 皆已移除——`grep -rn "TEMP" agent/ortho_pipeline.py agent/sla_operations.py agent/model_classifier.py agent/api_v2.py` 無結果；額外以 `grep -rn "PROFILE" agent/*.py` 交叉確認，僅存的兩處命中（`agent/boundary_detection.py` 的 `BG_PROFILE`／`BG_PROFILE_LOG` 環境變數、`agent/tests/test_extract_sla_from_mechado.py` 的 `_PROFILES` parametrize 列表）皆與本提案無關（前者屬 Surgical Guide 既有除錯開關，非本提案範圍；後者是既有測試的參數化命名），非本提案殘留
- [x] 6.2 **驗證**：`pytest agent/tests/ -q --continue-on-collection-errors` 結果 **665 passed、1 failed、3 errors**，與 D5 完成時記錄的既有基準完全相同。核對既有失敗／錯誤項目：`test_prz_print_time.py::test_6_11_single_normal_layer_full_params`（斷言 11.0≠14.0，屬 PRZ print-time 既有環境問題，與本提案觸及的 ortho/model_classifier/api_v2 無關）；3 個 collection errors（`test_slice_progress_endpoint.py`／`test_support_e2e.py`／`test_support_status_endpoint.py`）皆為 venv 缺少 `httpx` 套件導致 `fastapi.testclient` 匯入失敗，非本提案引入。四項與 D4／D5 量測記錄中已核對的既有基準數字（654 passed／1 failed／3 errors → 665 passed／1 failed／3 errors）一致，確認 D1～D5 疊加未產生新的 failed／error
- [x] 6.3 **驗證**：以 `001_p.stl`、`005_p.stl`（來源：`C:\Users\user\Pictures\tempTest\`）各執行 3 次完整 Auto Process 端到端流程（直接呼叫 `run_ortho_pipeline()`，monkeypatch `get_job_dir()` 指向獨立暫時目錄，未經 HTTP 層）。兩模型全部 6 次 runs 皆 `status=completed`、`has_ortho_result=True`、`ortho_result.stl` 正常產出。以預設 trimesh 處理（`process=True`，合併重複頂點）重新載入驗證幾何：`001_p.stl` 3 runs 皆為 face=205904／vertices=102928／`is_watertight=True`／volume=35749.34870896107；`005_p.stl` 3 runs 皆為 face=311056／vertices=155506／`is_watertight=True`／volume=29274.965437936——與 design.md D3 小節記錄的「Before baseline」功能基準完全一致，確認 D1／D2／D4／D5 疊加後幾何語意無 regression。詳細數字見下方「量測記錄」群組 6
- [x] 6.4 彙整量測表：已附於下方「量測記錄」群組 6，對照 D1／D2／D4／D5 各自 baseline 與現況耗時變化；D3 因 not viable 已放棄，列入表中僅作「無改善」記錄，不代表 regression
- [x] 6.5 確認每個群組皆已各自獨立 commit——`git log --oneline` 核對：D1＝`a62a235`（perf(ortho): open Auto Process performance change, land Hollow-fit repair=False）、D2＝`0cc564a`（perf(ortho): reuse cleaned mesh across Auto Process）、D3＝`7e18abe`（docs(openspec): mark Boolean Step 7-10 Manifold-chain optimization as not viable，僅文件記錄，因程式碼已 `git checkout` 還原而無程式碼異動需要 commit）、D4＝`85f172a`（perf(classifier): skip projection shape for intraoral confirm）、D5＝`650b30a`（perf(api): dedupe upload/save STL validation）。另有 `6ac541a`（test(agent): fix stale progress/subprocess tests, declare shapely dependency）夾在 D2 與 D4 commit 之間，內容為既有測試修復與 `requirements.txt` 補上遺漏的 `shapely` 依賴，與本提案 5 項效能改動無關，不影響群組獨立性判斷
- [x] 6.6 `openspec/changes/optimize-auto-process-performance/specs/auto-process-performance/spec.md`（本變更的 delta spec，`openspec/specs/auto-process-performance/` 主規格目錄尚不存在，將於 archive 時建立）核對後確認內容已與目前 proposal.md／design.md／tasks.md 最終狀態一致：涵蓋共用契約與 D1／D2／D4／D5 四項 requirement 的 scenario，並以獨立段落說明 D3 已調查放棄、不納入 ADDED Requirements。本輪核對未發現需要修改之處，無新增 commit

## 7. 不在本變更範圍（僅記錄）

> 本節是**記錄本身即為交付物**，不是待辦清單——寫下來就完成了，因此不使用 checkbox。

- **7.1** Hex Grid raycast backend：瓶頸已 100% 定位（99.7% 時間在 raycast），但替代 backend 尚未 prototype。候選方案確定後可另開變更或併入本提案後續版本。
- **7.2** Side-wall drains 幾何搜尋：bottleneck 已確認，具體演算法方案尚未決定。
- **7.3** Surgical Guide `_grow_patches` 等：profiling 已完成，但範圍可能拆成多個子優化，且屬 `agent/auto_orient_surg_guide.py`——與本提案涵蓋的 Ortho hollow／hex／boolean pipeline 不同功能模組，範圍界定後應評估是否獨立成另一個變更。
- **7.4** Generate Drain Holes mesh construction：只有優化方向，尚未 benchmark。
- **7.5** `clean_input_for_manifold` fast-path：尚未找到可靠的 cheap gate 條件。
- **7.6** Prusa Hollow C++：只有 source investigation，缺 C++ 內部分段 profiling，且涉及 `third_party/prusaslicer_fork` submodule。
- **7.7** Prusa Support C++：同 7.6，只有 source investigation，缺 C++ 內部分段 profiling。

## 量測記錄

> 本節於群組 0～6 執行過程中逐步填入，最終在群組 6 彙整。撰寫本提案時僅群組 1（Hollow-fit）已有實測數字。

### 群組 1（Hollow-fit，已完成）

| 模型 | 舊基準 hollow_fit_check（不含 load） | 新實測 hollow_fit_check 平均（3 runs，不含 load） | 改善 | 新實測 `split_ms` 平均（3 runs） |
| --- | --- | --- | --- | --- |
| `001_p.stl` | 2150.91 ms | 1647.35 ms | −503.56 ms（約 −23.4%） | 809.99 ms |
| `005_p.stl` | 1837.59 ms | 1420.73 ms | −416.86 ms（約 −22.7%） | 694.94 ms |

功能驗證：

- 兩個模型的 `fits=True` 判定均與修改前一致
- 後續 Hex Grid／Drain／Boolean face counts 與修改前一致
- 最終 Ortho 幾何結果未觀察到 regression
- 既有回歸測試（`agent/tests/test_ortho_hollow_split_repair.py`）已驗證 `repair` 開關不改變 component 的 vertices／bounds 等 Hollow-fit 判斷所使用的幾何資訊

**限制說明**：修改前每個模型只有既有單次 profiling baseline，且當時沒有獨立的 `split_ms`，因此可以確認 Hollow-fit check 整體階段約改善 23%，但不應把新舊差值直接宣稱為 `fill_holes()` 的精確單獨成本——新基準的 3-run 平均與舊基準的單次數字，量測條件（次數、機器熱身狀態等）並不完全對等。

### 群組 2（Ortho cleaned mesh 物件重用，已完成）

**修改前（baseline，各模型 3 runs）：**

| 模型 | `u_arch_load_ms` | `step3_load_ms` | 兩次 reload 合計 avg |
| --- | --- | --- | --- |
| `001_p.stl` | avg 73.75 ms | avg 81.73 ms | 155.48 ms |
| `005_p.stl` | runs: 441.70 / 1384.10*／403.60 ms | avg 421.19 ms（runs 429.87／438.62／395.07） | 不適用（見下方限制說明） |

\* `005_p.stl` 的 `u_arch_load_ms` Run2（1384.10 ms）為單次 outlier，不納入改善幅度計算。

**修改後（after，各模型 3 runs）：**

| 模型 | `shared_load_ms` runs | `shared_load_ms` avg |
| --- | --- | --- |
| `001_p.stl` | 109.67 / 65.61 / 66.58 ms | 80.62 ms |
| `005_p.stl` | 453.93 / 377.32 / 444.23 ms | 425.16 ms |

**改善幅度：**

- `001_p.stl`：原本兩次 reload 合計 avg 155.48 ms → 修改後單次 load avg 80.62 ms，觀察到的 load wall-time 減少約 74.86 ms/run
- `005_p.stl`：`u_arch_load_ms` baseline 因單次 outlier（1384.10 ms）不具代表性，不宣稱精確改善百分比。改以「移除一個平均約 421 ms 的第二次 reload」描述：修改後單次 `shared_load_ms` avg 425.16 ms，與修改前正常單次 load（`step3_load_ms` avg 421.19 ms）量級一致，確認第二次 reload 已被移除，省下的即是原本第二次 load 的完整耗時（約 421 ms/run 量級）

**SHA-256 byte-for-byte 驗證：**

| 模型 | Baseline SHA-256（修改前 3 runs 一致） | After SHA-256（修改後 3 runs 一致） | 結果 |
| --- | --- | --- | --- |
| `001_p.stl` | `BB150F743F6370AE01E8E5577E1110902074C3D68CB24AF93F579F24473E0912` | 同左 | byte-for-byte identical |
| `005_p.stl` | `2E06094A2F19DBD8004D573C71B4F93FDAC0B82897D86AF09575AC64AF3BD2F7` | 同左 | byte-for-byte identical |

兩模型修改前／修改後 SHA-256 完全相同，Task 2.7 的 byte-for-byte 驗收線通過。

**功能與 source-semantics 驗證：**

- 重用的是 `model_clean.stl` export 後第一次 `load_trimesh()` reload 出來的 mesh，非 `clean_input_for_manifold()` 內部 export 前的 pre-export mesh——source tracing 已確認兩者在 vertex ordering／face 索引／float precision 上非完全相同語意，故不可直接重用 pre-export mesh
- `_is_u_arch_from_low_sections()` 對 mesh 完全 read-only（僅讀 `.bounds`／`.section()`，trimesh `section()` 原始碼追蹤 + `agent/tests/test_ortho_clean_mesh_reuse.py` 的 mutation 測試雙重確認），因此不需要 `.copy()`
- U-arch=True 的提前結束路徑（`_complete_as_no_hollow`）與重用前行為完全一致：只 load 一次、不觸發 Step 1、`status.json`／`ortho_result.stl` 正常產出
- `pytest agent/tests/ -q --continue-on-collection-errors`：626 passed、7 failed、3 collection errors，與既有基準（619 passed、7 failed、3 collection errors）相比，failed／collection error 數量不變，新增的 7 個 passed 即本群組新增的回歸測試

### 群組 3（Boolean Step 7～10 Manifold representation，已調查放棄）

**Before baseline**（`001_p.stl`／`005_p.stl` 各 3 runs，`dev` 修改前）：

| 模型 | Step7-10 合計 avg | 可避免 conversion 合計 avg | 佔比 |
| --- | --- | --- | --- |
| `001_p.stl` | 1065.3 ms | 488.4 ms | ~45.8% |
| `005_p.stl` | 1048.5 ms | 417.9 ms | ~39.9% |

功能 baseline：兩模型 3 runs 皆 `status=completed`、`is_watertight=True`；`001_p.stl` face=205904／vertices=102928／volume=35749.34870896107；`005_p.stl` face=311056／vertices=155506／volume=29274.965437936（同一模型跨 3 runs 完全一致）。

**After（鏈式維持 Manifold 的實作，最終判定失敗，未採用）**：

Step7-10 合計耗時確實下降（3-run 平均約 617～786 ms，視系統負載波動；早期低負載量測顯示較 baseline 下降約 30～45%），但功能驗證未通過：

| 模型 | `is_watertight`（鏈式，僅 Step10 前物化一次） | volume |
| --- | --- | --- |
| `001_p.stl` | `False`（3/3 runs） | N/A |
| `005_p.stl` | `False`（3/3 runs） | N/A |

嘗試以「只物化特定一個交接」修復（見下表，`001_p.stl`／`005_p.stl` 端到端各測一次）：

| 修法 | `001_p.stl` | `005_p.stl` |
| --- | --- | --- |
| 全程鏈式（不物化中間交接） | `False` | `False` |
| 只物化 Step 9→10 | `True`（volume 與 baseline 一致） | `False` |
| 只物化 Step 8→9 | `True` | `False` |
| 同時物化 Step 8→9 與 9→10 | — | `False` |
| 每交接改用 `Manifold.set_tolerance()`（1e-4／1e-3／1e-2 mm） | `False`（三值皆同） | `False`（三值皆同） |
| 三個交接全部物化（＝回復原行為） | `True` | `True` |

**結論**：找不到對兩個代表模型都安全的部分鏈式組合；唯一可靠方案是完全放棄鏈式優化。詳細根因分析見 [design.md](design.md) D3 小節。本群組最終**未帶來任何效能改善**，`agent/ortho_pipeline.py`／`agent/sla_operations.py` 已 `git checkout` 還原至群組 2 完成時的狀態，本群組新增的回歸測試檔案（`agent/tests/test_boolean_meshes_chain.py`）已移除。

### 群組 4（`confirm-model-type` 略過 ProjectionShape，已完成）

**素材**：`C:\Users\user\Pictures\tempTest\Ushape1~3.stl`（真實 U 型基座牙模，本輪新增）+ repo 既有 `001_p.stl`／`005_p.stl`；commit 前另補驗 `DentalModel_2.stl`（同目錄，使用者以人工 ground truth 指認為第 4 個真實 U 型基座樣本）。

**修改前 baseline**（完整 ProjectionShape 計算，`confirm_dental_model_type(mesh, INTRAORAL_SCAN)`，各模型 3 runs）：

| 模型 | faces/vertices | `classify_dental_model()` | `u_shape_score` | `confirm(IOS)` | confirm total avg | ProjectionShape avg |
|---|---|---|---|---|---|---|
| `Ushape1.stl` | 293,095 / 879,285 | u_shaped_dental_model | 1.0 | False | 2350.83 ms | 306.42 ms |
| `Ushape2.stl` | 234,150 / 702,450 | u_shaped_dental_model | 1.0 | False | 1880.11 ms | 275.54 ms |
| `Ushape3.stl` | 299,798 / 899,394 | u_shaped_dental_model | 1.0 | False | 2356.85 ms | 299.86 ms |
| `001_p.stl` | 32,138 / 96,414 | dental_model | 0.0 | False | 251.69 ms | 46.30 ms |
| `005_p.stl` | 166,672 / 500,016 | dental_model | 0.0 | False | 1247.72 ms | 137.00 ms |

三個 Ushape 模型的 `u_shape_score` 皆為 `1.0`（非零、非退化），正式覆蓋 4.5 的邊界案例要求；`001_p.stl`／`005_p.stl` 的 `u_shape_score=0.0` 作為對照組。

**修改後（單一 process 配對量測，`extract_model_features(skip_projection_shape=False)` vs `True`，各暖機一次後 3 runs）**：

| 模型 | before avg | after avg | saved | improvement | `confirm(IOS)` 修改後 | ProjectionShape 呼叫次數 |
|---|---|---|---|---|---|---|
| `Ushape1.stl` | 2411.17 ms | 2073.24 ms | 337.93 ms | 14.0% | False（不變） | 0 |
| `Ushape2.stl` | 1910.90 ms | 1636.18 ms | 274.72 ms | 14.4% | False（不變） | 0 |
| `Ushape3.stl` | 2411.32 ms | 2169.53 ms | 241.79 ms | 10.0% | False（不變） | 0 |
| `001_p.stl` | 258.61 ms | 210.49 ms | 48.11 ms | 18.6% | False（不變） | 0 |
| `005_p.stl` | 1280.41 ms | 1122.50 ms | 157.91 ms | 12.3% | False（不變） | 0 |

百分比為 `extract_model_features()` 呼叫本身的改善幅度（D4 實際改動的函式），非整個 `confirm_dental_model_type()` API 呼叫的改善幅度——後者還包含 `_compute_signals()`／`_get_drill_detection_plan()`／分支判斷邏輯，以及（`needs_drill=True` 時）後續的 `detect_drill_holes()`；PCA／OpenBoundary／FlatPlane 三組**已經包含在** `extract_model_features()` 之內，不是額外成本。ProjectionShape 呼叫次數欄位以真實 `confirm_dental_model_type(mesh, INTRAORAL_SCAN)` 呼叫 + `[PROJECTION_SHAPE_PROFILE]` log 捕捉驗證，確認修改後為「完全未呼叫」而非「呼叫後耗時 0ms」。

**完整 `confirm_dental_model_type()` 配對量測（commit 前補驗）**：見下方「量測記錄」群組 4 的補充小節，衡量整個公開 API 呼叫（非僅 `extract_model_features()`）的改善幅度，與上表分開記錄，不混用。

**8-target 一致性驗證**：對 `Ushape1.stl` 掃描全部 8 個 `DentalModelType`，僅 `target=U_SHAPED_DENTAL_MODEL` 回傳 `True`，其餘 7 個皆 `False`——修改前後兩次執行結果完全相同。

**補驗（commit 前，`DentalModel_2.stl`，使用者以人工 ground truth 指認為 U 型基座）**：faces=367,506／vertices=1,102,518（四個真實 U-shape 樣本中規模最大者）。`classify_dental_model()` = `u_shaped_dental_model`，`u_shape_score=1.0`（`projection_largest_gap_ratio=0.394`、`projection_largest_gap_contact_mm=56.5mm`），`confirm_dental_model_type(mesh, INTRAORAL_SCAN)` = `False`，8-target 掃描僅 `U_SHAPED_DENTAL_MODEL` 為 `True`——與人工 ground truth 完全相符。由於 D4 production 邏輯已落地，此補驗直接沿用既有配對量測方法（同一 code state 下 `extract_model_features(skip_projection_shape=False)` vs `True`，暖機一次後各 3 runs），未另外重建「修改前」獨立 baseline：before avg 8407.90 ms → after avg 7527.01 ms，節省 880.89 ms（10.5%），`confirm_dental_model_type(mesh, INTRAORAL_SCAN)` 呼叫後 3 runs 總耗時 avg 7900.90 ms。

**補驗（commit 前）：`INTRAORAL_SCAN=True` correctness 案例**：先前 D4 baseline 調查找到的既有 deidentification fixture（`openspec/changes/backend-slicer-engine-deidentification/evidence/windows/functional-7.6-20260719T143000Z/fixture/model.stl`，faces=12／vertices=36），`classify_dental_model()` = `intraoral_scan`。完整 ProjectionShape 計算下 `confirm(mesh, INTRAORAL_SCAN)` = `True`；skip ProjectionShape（正式 production 路徑）下同樣 `= True`——兩者相符。補上了 D4 目前唯一缺少的「`INTRAORAL_SCAN` 為 `True`」真實案例（先前 Ushape1~3／001_p／005_p／DentalModel_2 皆為 `confirmed=False`）；正式合成回歸已由 `test_confirm_matches_classify_for_all_targets[P3_large_open_boundary]` 涵蓋，本次屬於補強而非缺口修補。

**補驗（commit 前）：完整 `confirm_dental_model_type(mesh, INTRAORAL_SCAN)` 配對量測**（`001_p.stl`／`005_p.stl`／`DentalModel_2.stl`，同一 process、同一暖機條件、各 3 runs；「修改前」以 monkeypatch 讓 `extract_model_features()` 忽略傳入的 `skip_projection_shape` 一律強制完整計算，藉此在不永久修改 production decision logic 的前提下重建修改前行為，「修改後」直接呼叫未改動的正式程式碼）——與上方「單一 process 配對量測」表（僅量測 `extract_model_features()` 本身）分開記錄，不混用：

| 模型 | before confirm avg | after confirm avg | saved | improvement | confirmed before | confirmed after |
|---|---|---|---|---|---|---|
| `001_p.stl` | 250.96 ms | 190.44 ms | 60.53 ms | 24.1% | False | False |
| `005_p.stl` | 3352.94 ms | 2656.68 ms | 696.26 ms | 20.8% | False | False |
| `DentalModel_2.stl` | 8548.99 ms | 6789.75 ms | 1759.23 ms | 20.6% | False | False |

三個模型 `confirmed` 結果修改前後完全一致。此表的絕對 ms 與「`extract_model_features()`-only」表屬不同 script 執行、不同時間點（例如 `005_p.stl` 在該表 before avg 為 1280.41 ms，此處整個 `confirm()` 呼叫 before avg 卻是 3352.94 ms），研判為跨 process 機器負載差異所致，非同一次量測內部矛盾；同一次量測內部（before/after 同一 process、同一暖機）的 saved ms／improvement % 仍然有效可信。

**Regression**：`pytest agent/tests/test_dental_model_type_confirm.py -v` 22 passed（8-target 不變量 13 組 + caller-boundary 9 個測試）；`pytest agent/tests/ -q --continue-on-collection-errors` 654 passed、1 failed、3 errors——與移除 temporary log 前完全相同數字，4 項失敗（`test_prz_print_time.py::test_6_11_single_normal_layer_full_params` 斷言 11.0≠14.0；`test_slice_progress_endpoint.py`／`test_support_e2e.py`／`test_support_status_endpoint.py` 因環境缺少 `httpx` 套件而 collection error）皆與 dental model 分類邏輯無關，且在「D4 修改前」（`--ignore=agent/tests/test_dental_model_type_confirm.py`，632 passed／1 failed／3 errors）與「D4 修改後含新測試」（654 passed／1 failed／3 errors）兩次執行中數字一致，確認非本項改動引入。

**限制說明**：另有一組跨 process 獨立量測（先量測修改前 baseline，之後才實作，再另開 process 量測修改後）顯示的 saved ms 略低（例如 `Ushape1.stl` 約 136ms 而非上表的 338ms），推測是兩次量測的 warm-up 呼叫次數不對等（修改前腳本計時前多跑一次完整 `classify_dental_model()`）造成 process/mesh cache 熱度差異；上表的單一 process 配對量測排除了此變因，視為更準確的數字，兩者量級與方向一致。

### 群組 5（Upload／save 重複 STL validation 去重，已完成）

**素材**：`001_p.stl`（1,606,984 bytes）／`005_p.stl`（8,333,684 bytes），與 D1／D2 相同代表模型。量測方式：直接呼叫真實的 `api_v2.upload_model_file()` → `api_v2._save_model_to_job()` 函式序列（不經 HTTP／`TestClient`），各 5 runs。

**Before（`dev` 修改前，即上一輪調查記錄的 baseline）**：

| 模型 | upload avg（第一次驗證，不可省略） | save avg（第二次完整 parse，D5 目標移除） | 合計 avg |
|---|---|---|---|
| `001_p.stl` | 34.70 ms | 29.03 ms | 63.73 ms |
| `005_p.stl` | 188.24 ms | 190.93 ms | 379.17 ms |

**After（實作後，`upload_model_file()` 設 `validated=True`，`_save_model_to_job()` 略過第二次 parse）**：

| 模型 | upload avg | save avg | 合計 avg |
|---|---|---|---|
| `001_p.stl` | 32.28 ms | 0.92 ms | 33.19 ms |
| `005_p.stl` | 204.73 ms | 2.46 ms | 207.20 ms |

**改善幅度**：

| 模型 | save 側改善 | 合計改善 |
|---|---|---|
| `001_p.stl` | −28.11 ms（約 −96.8%） | −30.54 ms（約 −47.9%） |
| `005_p.stl` | −188.47 ms（約 −98.7%） | −171.97 ms（約 −45.4%） |

`after save avg` 剩餘的次毫秒級耗時是單純檔案寫入（`open().write()`），確認第二次 `trimesh.load()` 完整 parse 已消失而非只是變快。`upload` 側（第一次、不可省略的驗證）修改前後量級一致，差異屬機器負載雜訊，非 regression。

**正確性驗證**：`test_save_skips_second_parse_for_validated_item` 確認略過驗證後落地檔案的 bytes 與原始上傳內容逐位元組相同；`use_model_from_job()`／`add_models_to_slice_job()`（含惡意標記注入）兩條未驗證來源在 `_save_model_to_job()` 仍完整驗證，格式錯誤內容仍正確回傳 `INVALID_MODEL`——與本項優化前行為相同。

**Regression**：`pytest agent/tests/test_save_model_to_job_validation.py -v` 11 passed；`pytest agent/tests/ -q --continue-on-collection-errors` 665 passed、1 failed、3 errors——與 D4 完成時的既有基準（654 passed、1 failed、3 errors）相比，新增的 665−654=11 即本群組新增測試，既有的 1 failed（`test_prz_print_time.py`，與本項無關的既有環境問題）與 3 collection errors（缺少 `httpx`）數字不變，確認非本項引入。

### 群組 6（整合驗證與收尾，已完成）

**6.1 temporary timing log 殘留檢查**：`grep -rn "TEMP" agent/ortho_pipeline.py agent/sla_operations.py agent/model_classifier.py agent/api_v2.py` 無結果。交叉檢查 `grep -rn "PROFILE" agent/*.py`：僅 `agent/boundary_detection.py`（`BG_PROFILE`／`BG_PROFILE_LOG`，Surgical Guide 既有除錯開關，`agent/auto_orient_surg_guide.py` 範圍，非本提案）與 `agent/tests/test_extract_sla_from_mechado.py`（`_PROFILES`，既有測試參數化列表名稱）兩處命中，皆與 D1～D5 無關，非本提案殘留。

**6.2 完整測試套件**：`pytest agent/tests/ -q --continue-on-collection-errors` → **665 passed、1 failed、3 errors**。

| 既有問題 | 類型 | 根因 | 與本提案關聯 |
|---|---|---|---|
| `test_prz_print_time.py::test_6_11_single_normal_layer_full_params` | failed | 斷言 `11.0 == 14.0`，PRZ print-time 既有環境問題 | 無——本提案未觸及 `agent/prz_*` |
| `test_slice_progress_endpoint.py` | collection error | venv 缺少 `httpx`，`fastapi.testclient` 匯入失敗 | 無——環境依賴缺失 |
| `test_support_e2e.py` | collection error | 同上 | 無——環境依賴缺失 |
| `test_support_status_endpoint.py` | collection error | 同上 | 無——環境依賴缺失 |

與 D4／D5 各自完成時記錄的既有基準（654 passed／1 failed／3 errors → 665 passed／1 failed／3 errors）完全一致，確認 D1～D5 疊加未引入新的 failed／error。

**6.3 端到端整合驗證**（`001_p.stl`／`005_p.stl` 各 3 runs，直接呼叫 `run_ortho_pipeline()`，monkeypatch `get_job_dir()` 指向獨立暫時目錄）：

| 模型 | run | status | has_ortho_result | faces | vertices（merged） | is_watertight | volume |
|---|---|---|---|---|---|---|---|
| `001_p.stl` | 1～3 | completed | True | 205904 | 102928 | True | 35749.34870896107 |
| `005_p.stl` | 1～3 | completed | True | 311056 | 155506 | True | 29274.965437936 |

三項功能指標（face／vertex／volume／`is_watertight`）在兩模型的全部 3 runs 中完全一致，且與 design.md D3 小節記錄的「Before baseline」功能基準（`001_p.stl` face=205904／vertices=102928／volume=35749.34870896107；`005_p.stl` face=311056／vertices=155506／volume=29274.965437936，兩者 `is_watertight=True`）逐項相符，確認 D1／D2／D4／D5 疊加後幾何語意無 regression。

**觀察（非 regression，僅記錄）**：`ortho_result.stl` 的 SHA-256 在 `001_p.stl`／`005_p.stl` 各自的 3 runs 中，run1／run2 相同但 run3 不同（face／vertex/volume 數字三者仍完全一致）。追蹤原因：Step 7～10 的 `boolean_meshes()` 鏈路本身（D3 已放棄鏈式優化，此段程式碼相對本提案開始前完全未變動）在多次獨立呼叫間，最終 STL 序列化的 triangle／vertex 排列順序並非跨 run 保證一致——與 design.md D3 小節「調查結果」描述的「STL 格式本身沒有共享頂點索引」現象同源，屬於 Boolean 鏈路既有、與本提案 D1／D2／D4／D5 五項改動無關的特性。本能力 spec（`specs/auto-process-performance/spec.md`）的共通契約本就因此不以「輸出檔案 byte-for-byte 完全相同」作為統一驗收線，改以幾何語意（face／vertex／volume／`is_watertight`）等價作為判準；上表已確認該判準通過。

**6.4 D1～D5 彙整量測表**（各項百分比／絕對值取自對應群組小節的量測記錄，此處僅彙整對照，不重新量測）：

| 項目 | 模型 | 修改前 | 修改後 | 改善 | 狀態 |
|---|---|---|---|---|---|
| Hollow-fit check（D1，不含 load） | `001_p.stl` | 2150.91 ms | avg 1647.35 ms（3 runs） | −23.4% | 已完成，production |
| Hollow-fit check（D1，不含 load） | `005_p.stl` | 1837.59 ms | avg 1420.73 ms（3 runs） | −22.7% | 已完成，production |
| Ortho cleaned mesh 載入（D2） | `001_p.stl` | 兩次 reload 合計 avg 155.48 ms | 單次 avg 80.62 ms | 約 −74.86 ms/run | 已完成，production |
| Ortho cleaned mesh 載入（D2） | `005_p.stl` | 單次 load 量級 avg 421.19 ms（第二次 reload） | 移除，單次 avg 425.16 ms 涵蓋原本工作 | 省去一次完整 reload（約 421 ms/run 量級） | 已完成，production |
| Boolean Step 7～10 中間表示法（D3） | `001_p.stl`／`005_p.stl` | Step7-10 合計 avg 1065.3／1048.5 ms | 同左（未變更） | 0%（鏈式版本雖曾測得約 30～45% 改善，但因 `is_watertight` regression 已放棄，未落地） | 已調查，not viable，已放棄 |
| confirm-model-type 略過 ProjectionShape（D4，`extract_model_features()` 本身） | `Ushape1~3.stl`／`001_p.stl`／`005_p.stl`／`DentalModel_2.stl` | 見群組 4 表 | 見群組 4 表 | 10.0%～18.6%（前五者），10.5%（`DentalModel_2.stl`） | 已完成，production |
| confirm-model-type 略過 ProjectionShape（D4，完整 `confirm_dental_model_type()` API） | `001_p.stl`／`005_p.stl`／`DentalModel_2.stl` | 見群組 4 補充表 | 見群組 4 補充表 | 24.1%／20.8%／20.6% | 已完成，production |
| Upload/save 驗證去重（D5，save 側） | `001_p.stl`／`005_p.stl` | 29.03／190.93 ms | 0.92／2.46 ms | −96.8%／−98.7% | 已完成，production |
| Upload/save 驗證去重（D5，合計） | `001_p.stl`／`005_p.stl` | 63.73／379.17 ms | 33.19／207.20 ms | −47.9%／−45.4% | 已完成，production |

**6.5 各群組獨立 commit 核對**：`git log --oneline` 確認 D1＝`a62a235`、D2＝`0cc564a`、D3＝`7e18abe`（僅文件，程式碼已 `git checkout` 還原無需 commit）、D4＝`85f172a`、D5＝`650b30a`，彼此獨立。`6ac541a`（既有測試修復＋`requirements.txt` 補 `shapely`）夾在 D2／D4 之間，與本提案 5 項改動無關，不影響群組獨立性。

**6.6 delta spec 核對**：`specs/auto-process-performance/spec.md` 核對後與 proposal.md／design.md／tasks.md 目前最終狀態一致（D1／D2／D4／D5 四項 requirement scenario 齊全，D3 以獨立段落註記已調查放棄、不納入 ADDED Requirements），無需修改。

**archive 條件判斷**：D1、D2、D4、D5 已完成並進入 production，各自獨立 commit；D3 已完整調查並記錄放棄（production 維持原行為，無殘留程式碼或 temporary log）；群組 0、6 收尾任務全數完成；`pytest agent/tests/` 無新增 regression；端到端驗證通過。**目前已具備 archive 條件**（本輪僅完成 D6 收尾與紀錄，不執行實際 archive 操作）。

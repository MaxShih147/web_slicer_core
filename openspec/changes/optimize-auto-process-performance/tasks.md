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

## 4. `confirm-model-type(target_type=intraoral_scan)` 略過 ProjectionShape

- [ ] 4.1 於 [model_classifier.py:542](../../agent/model_classifier.py#L542) 的 `extract_model_features()` 新增保留預設值的參數（例如 `skip_projection_shape: bool = False`），為真時略過 [model_classifier.py:564-587](../../agent/model_classifier.py#L564-L587) 的 ProjectionShape 區塊
- [ ] 4.2 於 [model_classifier.py:1376](../../agent/model_classifier.py#L1376) 的 `confirm_dental_model_type()`，僅在 `target == DentalModelType.INTRAORAL_SCAN` 時傳入 `skip_projection_shape=True`；其餘 target 與 `classify_dental_model()` 不傳入（維持完整特徵擷取）
- [ ] 4.3 加入本群組專用 timing log，只包住 `projection_shape_gap_stats()` 呼叫本身
- [ ] 4.4 **驗證**：既有 `dental-model-type-confirm` spec 的「與完整分類的一致性（無例外）」不變量——對同一份 mesh，`confirm(mesh, target)` 在 8 種 target 下的結果集合，與本群組改動前完全相同（可沿用/擴充現有的 `test_classify_decision.py` 風格測試邏輯，正式納入 `agent/tests/`）
- [ ] 4.5 **驗證**：對多份 U-arch／intraoral scan 邊界案例（ProjectionShape 的 `u_shape_score` 在完整計算下非零的模型），`confirm(mesh, INTRAORAL_SCAN)` 在略過 ProjectionShape 前後回傳值相等
- [ ] 4.6 **驗證**：對 `target` 為 `intraoral_scan` 以外的任一值，`extract_model_features()` 確實仍執行完整 ProjectionShape 擷取（可透過檢查 `features.projection_hull_area_mm2` 等欄位非 `None` 或以 mock 計數呼叫次數確認）
- [ ] 4.7 **驗證**：`classify_dental_model()`／`POST /api/v2/classify-model` 端點行為與輸出結構不受影響
- [ ] 4.8 **量測**：以數份代表性 STL 呼叫 `confirm-model-type(target_type=intraoral_scan)`，記錄略過 ProjectionShape 前後的耗時差異
- [ ] 4.9 **收尾**：移除本群組的 temporary timing log
- [ ] 4.10 正式補上 4.4～4.6 的回歸測試至 `agent/tests/`（若沿用根目錄既有的 `test_classify_decision.py`／`test_classify_api.py` 邏輯，需先確認是否移入正式測試套件或另行改寫，不得僅依賴未追蹤的臨時腳本作為驗收依據）

## 5. Upload／save 重複 STL validation 去重

- [ ] 5.1 確認 `pending["models"]` 的全部寫入點：[api_v2.py:392](../../agent/api_v2.py#L392)（`upload_model_file()`，已驗證）、[api_v2.py:467](../../agent/api_v2.py#L467)（`use_model_from_job()`，未驗證）；`pending["support_stl"]` 的寫入點：[api_v2.py:436](../../agent/api_v2.py#L436)（`upload_support_file()`，已驗證）。實作前重新以 `grep` 確認無新寫入點加入
- [ ] 5.2 於 `upload_model_file()`（[api_v2.py:392](../../agent/api_v2.py#L392)）與 `upload_support_file()`（[api_v2.py:436](../../agent/api_v2.py#L436)）寫入 `pending` 時，於已通過 [api_v2.py:389](../../agent/api_v2.py#L389)／[api_v2.py:434](../../agent/api_v2.py#L434) 驗證之後，加入標記（例如 `"validated": True`）
- [ ] 5.3 `use_model_from_job()`（[api_v2.py:467](../../agent/api_v2.py#L467)）附加的項目 MUST NOT 設置該標記（維持缺失或顯式 `False`）
- [ ] 5.4 `_save_model_to_job()`（[api_v2.py:207](../../agent/api_v2.py#L207)）於 [api_v2.py:211](../../agent/api_v2.py#L211) 呼叫 `_validate_stl_bytes()` 前，檢查 5.2 的標記；標記為真時略過該次呼叫，標記缺失或為假時維持現行的完整驗證
- [ ] 5.5 加入本群組專用 timing log，只包住 `_save_model_to_job()` 內的驗證判斷與（若執行）`_validate_stl_bytes()` 呼叫
- [ ] 5.6 **驗證**：透過 `upload_model_file()` 上傳合法 STL 後 execute，`_save_model_to_job()` 不再次執行完整 `trimesh.load()` parse（可用計數 mock 或 timing 差異確認），且模型正常落地、pipeline 正常執行
- [ ] 5.7 **驗證**：透過 `use_model_from_job()` 引用其他 job 輸出後 execute，`_save_model_to_job()` 仍執行完整驗證——刻意引用一份格式錯誤或空 mesh 的檔案，確認仍回傳 `INVALID_MODEL`（422），與本群組改動前行為相同
- [ ] 5.8 **驗證**：`pending["models"]` 項目不含驗證標記時（模擬未來遺漏設置標記的寫入路徑），`_save_model_to_job()` 仍執行完整驗證
- [ ] 5.9 **量測**：以 `001_p.stl`、`005_p.stl` 走完整 upload → execute 流程，記錄 `_save_model_to_job()` 驗證耗時差異
- [ ] 5.10 **收尾**：移除本群組的 temporary timing log
- [ ] 5.11 補最小必要回歸測試至 `agent/tests/`，至少涵蓋 5.6／5.7／5.8 三個情境

## 6. 整合驗證與收尾

- [ ] 6.1 確認群組 1～5 的所有 temporary timing log 皆已移除（`grep -rn "TEMP" agent/ortho_pipeline.py agent/sla_operations.py agent/model_classifier.py agent/api_v2.py` 應無相關殘留，或僅剩與本提案無關的既有標記）
- [ ] 6.2 **驗證**：`pytest agent/tests/ -q`，確認本提案相關測試全數通過；既有失敗項目（若與本提案無關）逐一核對是否為變更前既有缺陷，記錄於下方「量測記錄」而非列為本提案的驗收阻擋
- [ ] 6.3 **驗證**：以 `001_p.stl`、`005_p.stl` 各執行 2～3 次完整 Auto Process 端到端流程，確認 5 項改動疊加後仍能正常完成，`ortho_result.stl` 產出正常
- [ ] 6.4 彙整量測表：對照各群組 baseline，列出 Hollow-fit check、Ortho mesh 載入、Boolean Step 7～10、confirm-model-type、upload/save 驗證的前後耗時變化，附於下方「量測記錄」
- [ ] 6.5 確認每個群組（1～5）皆已各自獨立 commit（fork submodule 本提案未涉及，不需要分離 Python／fork commit）
- [ ] 6.6 更新 `openspec/specs/auto-process-performance/spec.md`（archive 時同步至主規格）

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

### 群組 4～5

（實作後依各自 task 的「量測」項回填。目前尚未開始。）

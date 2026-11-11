## 1. 基準與準備

- [ ] 1.1 在乾淨的 worktree 跑 `pytest agent/tests/ -q`，記錄改前的通過／失敗數作為基準
- [ ] 1.2 向使用者索取 `TriangleStress_5M.stl`（合成檔）；取得後量改前數字：`_validate_stl_bytes` 時間、`boolean_operation` 各階段時間、5 次 upload → generate-supports 後 agent 的 private memory；取不到則記錄原因

## 2. E：EcoQoS 節流

- [ ] 2.1 新增 `agent/power_throttling.py`，實作 `disable_execution_throttling(pid=None, label="")`（D1：結構、常數、kernel32 快取、OpenProcess／CloseHandle、非 Windows no-op、所有失敗只記 WARNING 並回傳 False）
- [ ] 2.2 `agent/main.py` lifespan 開頭對自身呼叫一次
- [ ] 2.3 `jobs.run_slicing` 與 `jobs` 的 3MF 匯出在 `create_subprocess_exec` 後以 `process.pid` 呼叫
- [ ] 2.4 `sla_operations.run_prusa_cli` 在 `create_subprocess_exec` 後、讀取輸出前以 `process.pid` 呼叫
- [ ] 2.5 新增 `agent/tests/test_power_throttling.py`：參數正確、handle 關閉、失敗只記 WARNING、例外不外漏、非 Windows no-op、`run_prusa_cli` 對子程序 PID 呼叫一次；Windows 上對自身的實際呼叫 smoke test

## 3. F1-1：STL header 驗證

- [ ] 3.1 改寫 `api_v2._validate_stl_bytes` 為 header／大小檢查（D2），移除對 `trimesh.load` 的依賴
- [ ] 3.2 新增 `agent/tests/test_validate_stl_header.py`，涵蓋 `stl-upload-validation` 每個 scenario（含 solid header 的 binary、BOM、空 ASCII、截斷、面數 0、尾端多出 37 bytes 與剛好 50 bytes 都拒絕、solid header＋含 facet＋尾端多餘 bytes 的 binary 拒絕、bytes 84–211 有 > 127 的 ASCII 開頭檔拒絕、258 MB 大小的時間上限）；另加一個測試：以前端 `STLExporter` 同樣格式（`trimesh.exchange.stl.export_stl`）產生的檔案一律接受
- [ ] 3.3 確認 `test_save_model_to_job_validation.py`、`test_config_validation_422.py` 等既有驗證測試仍通過；更新仍描述 `trimesh.load()` 的註解與 docstring

## 4. F1-2：pending job 釋放與閒置暫存

- [ ] 4.1 新增 `_LandedModel` 與 `_release_landed_model()`；`_save_model_to_job()` 支援已落地項目（同路徑不寫、不同路徑複製、遺失回 `MODEL_NOT_FOUND`）
- [ ] 4.2 `generate-supports`、`export-support-points`、`generate-hollow`、`cut` 在背景任務排入後釋放 `models[0]` 的 bytes
- [ ] 4.3 pending job 加 `last_access`，新增 `_touch_pending()` 並在讀寫 pending 的端點使用
- [ ] 4.4 新增 `_SpooledModel`、`_spool_idle_pending_jobs()` 與 `pending_job_spool_loop()`（D4）：讀取 `AGENT_PENDING_SPOOL_IDLE_SEC`（預設 600），閒置 job 的 bytes 寫到 `JOBS_DIR/.pending_spool/`；`_save_model_to_job()` 支援暫存項目（依 `validated` 驗證後移到 `input_path`）；`execute`／`ortho-process` 刪除殘留暫存；`main.lifespan` 啟動時清空暫存目錄並啟動／取消迴圈
- [ ] 4.5 新增 `agent/tests/test_pending_job_release.py`：釋放後 `modelCount` 不變；同 job 接著 `execute`／再次 generate-supports 成功且 `input/model.stl` 與上傳 bytes 相同；寫檔失敗不釋放；偽造 `"landed"`／`"spooled"` 欄位無效；落地檔案遺失；`use-model-from` 不受影響；暫存的各情境（見 design D6）

## 5. F1-3：boolean numpy 讀寫

- [ ] 5.1 新增 `agent/stl_io.py`：`read_binary_stl_triangles`、`merge_triangle_vertices`（移除非有限面、與 trimesh 相同的捨入合併、頂點依第一次出現排序）、`write_binary_stl`
- [ ] 5.2 改寫 `sla_operations.boolean_operation` 主路徑：numpy 讀取 → 直接建 `manifold3d.Mesh` → 運算 → `to_mesh` → `write_binary_stl`；ASCII 退回 `trimesh.load`；fallback 時才以 `Trimesh(process=False)` 建立網格進入既有修補序列；空結果訊息不變
- [ ] 5.3 新增 `agent/tests/test_boolean_numpy_io.py`：`merge_triangle_vertices` 的 `vertices`、`faces` 與 `trimesh.load(process=True)` 逐元素相同（含順序；含 NaN 面、重複面、退化面）；`write_binary_stl` 可被 trimesh 讀回且法向量正確；以測試內保留的改前參考實作比較 union／difference／intersection、ASCII 輸入、開口輸入的三角形數、`is_watertight`、`is_winding_consistent`、`volume`；開口輸入（修補路徑）的輸出三角形逐面相同；空結果
- [ ] 5.4 確認 `boolean-non-manifold-tolerance` 相關既有測試全部通過

## 6. 驗收與交付

- [ ] 6.1 跑完整 `pytest agent/tests/ -q`，與 1.1 基準比較，沒有新增失敗
- [ ] 6.2 若取得 5M 測試檔，量改後數字（驗證時間、boolean 各階段、重複支撐的記憶體），與 1.2 並列寫入 change 目錄的 `measurements.md`；量不到時寫明原因與合成檔的替代數字
- [ ] 6.3 在 macOS 上跑完整 `pytest agent/tests/`，並實際啟動 agent 做一次上傳 → 產生支撐 → 切片，確認節流模組為 no-op、F1 正常；沒有 Mac 可用時在交付說明中註明未驗證
- [ ] 6.4 （選做，可另開 change）依 design Open Questions 的方法在 Apple Silicon Mac 上量測是否有節流，結果記入 `measurements.md`
- [ ] 6.5 `openspec validate agent-large-model-perf --strict` 通過
- [ ] 6.6 在功能分支 commit（不 push、不開 PR），等使用者確認；如需 1.0.6.x hotfix 再討論 cherry-pick 到 `release/v1.0.6`

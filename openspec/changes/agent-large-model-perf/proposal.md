## Why

5M 面（258 MB binary STL）的模型做一次文字壓印、自動支撐或切片，各要 66–90 秒，真正的計算不到 15%（量測：Local Agent 1.0.6.3，agent commit `39c28c56fd5f`，i9-13900H／Windows 11）。其餘時間來自兩類與計算無關的浪費：

1. **Windows EcoQoS 節流**：Electron 啟動器沒有前景視窗，Windows 在大小核 CPU 上把 agent 與其子程序（slicer-engine）當背景工作降速。同一個 5M 切片，由 agent 啟動時引擎總時間 64.2 s，只對引擎關掉 EcoQoS 後降為 37.6 s；關掉 agent 本身的節流後，5M 上傳由 23.7 s 降為 11.8 s。
2. **agent 對同一個 mesh 的重複處理與記憶體洩漏**：
   - 上傳時 `_validate_stl_bytes()` 為了驗證完整 `trimesh.load()` 一次（5M 約 11.1 s），而 bytes 隨後原樣寫檔交給引擎，parse 結果完全沒用到。
   - `generate-supports` 把模型寫入 `input/model.stl` 後，`_pending_jobs[job_id]["models"]` 仍持有整份 bytes；前端每次重新產生支撐都開新 job，每調一次參數 agent 就多佔一份模型大小（5M 為 258 MB），實測數次後 private memory 達 2 GB。
   - `boolean_operation()` 讀檔走 `trimesh.load(process=True)`（12.4 s）、結果再經 `Trimesh(process=True)`（3.4 s）、`is_watertight`（3.5 s）、`export`（2.1 s），union 本身只要 0.9 s。

這兩項都是小範圍、低風險的修改，能在不動引擎與前端 API 的前提下，讓 5M 的三條流程各省下約 30–45 秒，並止住支撐重產的記憶體成長。

## What Changes

- **E. 排除 EcoQoS 節流**：agent 啟動時對自身程序、每次啟動 slicer-engine 子程序後對該子程序呼叫 `SetProcessInformation(ProcessPowerThrottling)`，`ControlMask = PROCESS_POWER_THROTTLING_EXECUTION_SPEED`、`StateMask = 0`（明確關閉執行速度節流）。僅在 Windows 執行；任何失敗只記 log，不影響 agent 啟動或任務結果。涵蓋 agent 內所有啟動引擎的位置（`jobs.run_slicing`、`jobs` 的 3MF 匯出、`sla_operations.run_prusa_cli`）。
- **F1-1. 上傳驗證改為 header 檢查**：`_validate_stl_bytes()` 不再呼叫 `trimesh.load()`，改為只檢查 STL 的格式與大小——binary 時面數 > 0 且 `84 + 面數 × 50 ≤ 長度`；否則開頭（容許 UTF-8 BOM 等前置位元組）為 `solid` 且內容含 `facet` 視為 ASCII；其餘以 `INVALID_MODEL` 拒絕。與前端 `assertImportableStl` 的判準一致。
- **F1-2. pending job 釋放模型 bytes 並清理逾時 job**：`generate-supports`（以及同樣只寫檔不移除 pending 的 `export-support-points`、`generate-hollow`、`cut`）把模型寫入 `input/model.stl` 後，`models[0]` 改為只記錄已落地的檔案路徑、不再持有 bytes；之後同一 job 的 `execute`／`ortho-process`／再次產生支撐沿用該檔案。另加背景清理：閒置超過時限的 pending job 從記憶體移除。`use-model-from`、`modelCount`、既有錯誤碼行為不變。
- **F1-3. boolean 的 STL 讀寫改用 numpy**：`boolean_operation()` 以 numpy 直讀 binary STL 並以 numpy 合併頂點（與 trimesh `merge_vertices` 同一判準），直接建 `manifold3d.Mesh`；結果直接取 `to_mesh()` 的陣列以 numpy 寫 binary STL，略過 `Trimesh(process=True)` 與 `is_watertight`。ASCII STL 與主路徑轉換失敗時仍走現有 trimesh 讀取與修補序列，修補行為不變。結果的三角形數、封閉性、繞序與改前一致。

不含：F2（模型快取／hash 引用 API，需與 DS-Online 前端共同設計）、F3（引擎 admesh 讀檔修復的超線性成長，屬 `slicer-engine` / `third_party/prusaslicer_fork`）、Bundle-Launcher 修改。對外 API 與錯誤碼沒有 **BREAKING** 變更。

## Capabilities

### New Capabilities

- `agent-power-throttling`：agent 與其啟動的 slicer-engine 子程序在 Windows 上關閉 EcoQoS 執行速度節流的時機、範圍與失敗容忍。
- `stl-upload-validation`：`_validate_stl_bytes()` 以 header 與大小判定 STL 可接受與否的判準（binary／ASCII），以及不完整解析 mesh 的效能保證。
- `pending-job-memory`：pending job 在模型落地後不再持有模型 bytes、後續操作沿用已落地檔案，以及閒置 pending job 的逾時清理。
- `boolean-mesh-io`：`boolean_operation()` 的 STL 讀取、頂點合併與結果寫出改走 numpy 時，對三角形數、封閉性、繞序的等價保證，以及何時退回 trimesh 路徑。

### Modified Capabilities

- `auto-process-performance`：「Upload／save 驗證去重不得降低驗證涵蓋範圍」的 scenario 原以「完整 `trimesh.load()` parse」描述被略過的驗證；驗證改為 header 檢查後，改以「`_validate_stl_bytes()`」描述，略過與不略過的條件不變。

## Impact

| 受影響項目 | 類型 | 說明 |
|---|---|---|
| `agent/main.py` | 程式 | lifespan 啟動時對自身關閉節流；啟動 pending job 清理迴圈 |
| 新增 `agent/power_throttling.py` | 程式 | ctypes 呼叫 `SetProcessInformation` 的小模組（非 Windows 為 no-op） |
| `agent/jobs.py` | 程式 | `run_slicing`、3MF 匯出啟動引擎後對子程序關閉節流 |
| `agent/sla_operations.py` | 程式 | `run_prusa_cli` 啟動後關閉節流；`boolean_operation` 讀寫改 numpy |
| `agent/api_v2.py` | 程式 | `_validate_stl_bytes` 改 header 檢查；`_save_model_to_job` 支援已落地模型；pending job 釋放 bytes 與逾時清理 |
| `agent/tests/` | 測試 | 新增 STL 驗證、pending job 釋放／清理、boolean 等價性、節流呼叫的單元測試 |
| 對外 API | 無變更 | 端點、回應格式、錯誤碼不變；壞檔的拒絕訊息內文可能不同 |
| 相依套件 | 無新增 | 只用標準庫 `ctypes` 與既有 numpy／manifold3d |
| 發布 | 元件更新 | 以元件更新發布新 agent；是否以 1.0.6.x hotfix cherry-pick 到 `release/v1.0.6` 另議 |

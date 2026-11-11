## Context

量測與拆解見交接文件「大模型後端交接」（E、F1 兩節）。量測對象為 Local Agent 1.0.6.3（agent commit `39c28c56fd5f`，`release/v1.0.6` tip）；本 change 從 `dev` 切出，只改 `agent/`。

現況重點：

- agent 由 Electron 啟動器（無前景視窗）帶起，slicer-engine 由 agent 以 `asyncio.create_subprocess_exec` 啟動，共三處：`jobs.run_slicing`、`jobs` 的 3MF 匯出、`sla_operations.run_prusa_cli`（支撐、挖空、切割、支撐點匯出共用）。引擎位於 Electron 的 Job Object 中，ControlMask 為 0（系統自動決定）。
- `_validate_stl_bytes()` 被 `upload_model_file()`、`upload_support_file()`、`_boolean_operation_impl()`、`_save_model_to_job()`（未預先驗證的內容）呼叫，每次都 `trimesh.load()`。驗證通過的 bytes 原樣寫檔，parse 結果丟棄。
- `_pending_jobs` 是 module 層級 dict，沒有時間戳。只有 `execute` 與 `ortho-process` 會 `del`；`generate-supports`、`export-support-points`、`generate-hollow`、`cut` 寫檔後保留 pending（之後可能在同一 job 上 `execute`），也就保留 bytes。
- `add_models_to_slice_job()` 以 `{"id": ..., **model, "validated": False}` 存入，request body 的任意 key 都會進入模型項目。
- `boolean_operation()` 的主路徑：`trimesh.load` → `Trimesh` → `manifold3d.Mesh` → `Manifold` → 運算 → `to_mesh` → `Trimesh(process=True)` → `is_watertight`（只為 log）→ `export`。修補序列（`boolean-non-manifold-tolerance`）建立在 `trimesh.Trimesh` 上。
- `boundary_detection._fast_load_binary_stl()` 已有 numpy 讀 binary STL 的先例（回傳未合併的三角形湯）。

## Goals / Non-Goals

**Goals:**

- agent 與 slicer-engine 子程序在 Windows 上不受 EcoQoS 執行速度節流。
- 上傳驗證不再解析 mesh；判準與前端 `assertImportableStl` 一致。
- 支撐重產不再累積模型 bytes；閒置 pending job 有上限壽命。
- boolean 的讀寫轉換成本降到 numpy 等級，結果與改前等價（三角形數、封閉、繞序）。

**Non-Goals:**

- F2 模型快取／hash 引用 API、indexed 上傳（需與前端 Chloe 共同設計）。
- F3 引擎讀檔修復（admesh）的超線性成長。
- 只對文字附近區域做 boolean。
- Bundle-Launcher（Electron）端的節流設定。
- 釋放 `models[1:]` 的 bytes（這些項目從未被寫檔，現況也未使用；另議）。

## Decisions

### D1. 節流設定集中於新模組 `agent/power_throttling.py`

提供 `disable_execution_throttling(pid: int | None = None, label: str = "") -> bool`：`pid=None` 用 `GetCurrentProcess()`（偽 handle，不需關閉）；否則 `OpenProcess(PROCESS_SET_INFORMATION, False, pid)`，呼叫後 `CloseHandle`。結構 `PROCESS_POWER_THROTTLING_STATE { ULONG Version=1; ULONG ControlMask=0x1; ULONG StateMask=0; }`，`ProcessPowerThrottling = 4`。`kernel32` 以 `ctypes.WinDLL("kernel32", use_last_error=True)` 載入並在第一次呼叫時快取；所有路徑包在 `try/except Exception`，失敗記 WARNING（含 `ctypes.get_last_error()`）並回傳 False。`sys.platform != "win32"` 時直接回傳 False，不記 log。

在 `main.lifespan` 開頭對自身呼叫一次；在三處 `create_subprocess_exec` 之後立即以 `process.pid` 呼叫。呼叫是同步的 Win32 呼叫（微秒等級），不需丟到 thread。

- 替代方案：只在啟動器（Electron）設定 → 不在本 change 範圍，且量測顯示子程序需要各自設定（繼承未驗證）。
- 替代方案：`STARTUPINFOEX` 在建立時帶屬性 → asyncio 子程序 API 無法傳入，需重寫啟動流程，不值得。
- 替代方案：提高程序優先權（`HIGH_PRIORITY_CLASS`）→ 與 EcoQoS 是不同機制，量測沒有證據有效，且會影響使用者其他前景工作。
- 子程序啟動到設定之間有極短時間仍被節流，可接受。

### D2. `_validate_stl_bytes` 只做 header 檢查

判準見 `stl-upload-validation`。binary 優先：先讀 bytes 80–83 的面數 `n`，`n > 0` 且 `84 + 50n ≤ len` 即接受（這也正確處理 header 以 `solid` 開頭的 binary 檔）。否則去掉開頭至多 5 bytes 的 BOM／空白後檢查 `solid`，再以 `content.find(b"facet")` 確認至少有一個面，以保留改前「空 mesh 拒絕」的語意。

代價：header 檢查不會發現 binary 內容中的 NaN 座標、退化面等。這些在改前同樣不會被拒絕（`trimesh.load` 不 validate），所以拒絕集合實質上只縮小在「大小合格但內容是垃圾」的極少數檔案；這類檔案到引擎或 boolean 時會以引擎既有的錯誤碼失敗。`_boolean_operation_impl` 也走同一個函式，boolean 端對 binary 的讀取另有大小精確檢查（D4）。

- 替代方案：numpy 讀入後檢查 finite → 仍需讀完整個 buffer（5M 約 0.3 s），而且改前並不拒絕 NaN，沒有必要。

### D3. 已落地模型以伺服器端型別標記，`_save_model_to_job` 沿用落地檔案

新增 `@dataclass(frozen=True) class _LandedModel: path: Path`。四個保留 pending 的端點在 `_save_model_to_job()` 成功、背景任務排入後呼叫 `_release_landed_model(pending, input_path)`：把 `models[0]` 換成 `{**原項目去掉 stl_data, "landed": _LandedModel(input_path)}`。`_save_model_to_job()` 只在 `isinstance(model_data.get("landed"), _LandedModel)` 時沿用檔案（同路徑不重寫、不同路徑 `shutil.copyfile`、不存在則 `MODEL_NOT_FOUND`）。

JSON request body 無法產生 `_LandedModel` 實例，所以 `add_models_to_slice_job()` 送來的 `"landed"` 欄位只會是 dict／字串，會被忽略並落入既有的 `stl_data`／`missing_body` 規則——避免呼叫端以偽造路徑讓 agent 複製任意檔案。

釋放放在背景任務排入之後：背景任務只讀 `input/model.stl`，不讀 `pending["models"]`，所以順序上沒有競爭；寫檔或設定驗證失敗時不會執行到釋放，pending 保持原狀可重試。

- 替代方案：generate-supports 後直接 `del _pending_jobs[job_id]` → 會讓之後在同一 job 上 `execute` 變成 `JOB_ALREADY_EXECUTED`，破壞現有流程。
- 替代方案：用字串 key `"saved_path"` → 可被 request body 偽造，有安全風險。

### D4. pending job 加最後存取時間與清理迴圈

`_pending_jobs[job_id]` 建立時加入 `"last_access": time.monotonic()`。`_require_pending()` 與各端點取得 pending 的位置改經 `_touch_pending(job_id)` 更新時間（集中在一個 helper，不散落 `time.monotonic()`）。新增 `pending_job_cleanup_loop()`，仿 `prz_session_cleanup_loop` 每 300 s 呼叫 `_evict_expired_pending_jobs(now)`；在 `main.lifespan` 與 PRZ 清理迴圈一起啟動、一起取消。時限預設 7200 s，`AGENT_PENDING_JOB_TTL_SEC` 可覆寫。缺少 `last_access` 的項目（例如測試直接塞入的 dict）視為剛存取，不清除。

選 2 小時：前端的上傳 → 設定 → 執行在數分鐘內完成；支撐 job 釋放 bytes 後佔用很小，清理主要針對「上傳後從未 execute」的孤兒 job。逾時後的請求依現有規則回 `JOB_NOT_FOUND`／`JOB_ALREADY_EXECUTED`，前端本來就會為新操作開新 job。

### D5. boolean 讀寫改 numpy，修補路徑保留 trimesh

新增 `agent/stl_io.py`：

- `read_binary_stl_triangles(path) -> np.ndarray | None`：大小恰為 `84 + 50n` 且 `n > 0` 才讀（與 `_fast_load_binary_stl` 相同判準），回傳 `(n, 3, 3) float32`；否則 None。
- `merge_triangle_vertices(tris) -> (vertices float64, faces int64)`：先移除含非有限座標的面（對應 `remove_infinite_values`），再以 `np.round(v * 10**digits).astype(int64)`（`digits = trimesh.util.decimal_to_digits(trimesh.tol.merge)`，與 `merge_vertices` 相同）做 `np.unique(axis=0, return_inverse=True)`，面索引 = inverse。頂點排列可能與 trimesh 不同，但面順序與繞序不變。
- `write_binary_stl(path, vertices, faces)`：以 `np.cross` 算法向量並正規化（長度 0 者為 0），組成 `dtype=[normal 3f4, v 9f4, attr u2]` 的結構陣列一次寫出。

`boolean_operation()`：兩個輸入先試 numpy 路徑，得到 `(verts, faces)` 後直接建 `manifold3d.Mesh(vert_properties=float32, tri_verts=int32)` → `Manifold`。主路徑有效時不建立 `Trimesh`。需要 fallback 時，才以 `trimesh.Trimesh(verts, faces, process=False)` 建立 `mesh_a`／`mesh_b` 交給現有修補序列（因為頂點已合併、無 NaN，`process=False` 與改前的 `process=True` 狀態相同）。ASCII 輸入沿用 `trimesh.load()`。結果：`to_mesh()` → `num_tri == 0` 判空 → `write_binary_stl`；log 改記面數與頂點數，不再計算 `is_watertight`。

合併頂點本可交給 `manifold3d.Mesh.merge()`，但 `merge()` 以容差合併並可能改變拓撲，與改前的 trimesh 判準不同；為了等價，主路徑用 numpy 與 trimesh 相同的捨入判準，`Mesh.merge()` 仍只在修補序列中使用（行為不變）。

`trimesh_to_manifold` 的 float32 轉換與改前相同：改前也是 `np.array(mesh.vertices, dtype=np.float32)`。

等價性驗收（`boolean-mesh-io`）：以改前實作的複本（測試內保留舊路徑的參考函式）與改後實作對同一組輸入（封閉 box／sphere 組合、union／difference／intersection、ASCII 輸入、開口輸入觸發修補）比較三角形數、`is_watertight`、`is_winding_consistent`、`volume`。

### D6. 測試

- `test_power_throttling.py`：非 Windows 為 no-op；以 monkeypatch 取代 kernel32 驗證參數（ControlMask=1、StateMask=0、Version=1）、handle 關閉、回傳 0 時只記 WARNING、例外被吞；`run_prusa_cli` 啟動後以子程序 PID 呼叫一次。Windows 上另有一個實際呼叫自身的 smoke test。
- `test_validate_stl_header.py`：spec 的每個 scenario 一個 case，另加 5M 大小 buffer 的時間上限。
- `test_pending_job_release.py`：上傳 → generate-supports（背景任務以 monkeypatch 替換）→ bytes 被釋放、`modelCount` 不變 → 同 job `execute` 成功且 `input/model.stl` 與上傳 bytes 相同；偽造 `"landed"` 欄位無效；落地檔案遺失回 `MODEL_NOT_FOUND`；清理迴圈依時限移除、不刪目錄。
- `test_boolean_numpy_io.py`：D5 的等價性矩陣。

## Risks / Trade-offs

- [SetProcessInformation 在舊版 Windows 不存在或回傳 `ERROR_INVALID_PARAMETER`] → 只記 WARNING；行為退回現狀。
- [Job Object 或系統原則覆寫程序層設定，量測環境以外無效] → 交接量測已在實際 Electron + Job Object 下驗證有效；驗收時以 `SLICE_PROFILING=1` 從開始選單正常啟動再量一次。
- [header 檢查放行內容損壞但大小合格的 binary 檔] → 改前同樣不拒絕 NaN／退化面；損壞內容會在引擎或 boolean 階段以既有錯誤碼失敗，錯誤訊息可能較晚出現。
- [清理移除使用者仍打算使用的 pending job] → 2 小時閒置且以每次存取更新；可用環境變數放寬；被清的 job 回既有錯誤碼，前端重開 job 即可。
- [numpy 合併頂點與 trimesh 在極端座標（|x| > 9e10）時整數溢位] → 牙科模型座標在 ±1000 mm 內；溢位或非有限時退回 `trimesh.load()` 路徑。
- [結果 STL 不再經 `process=True`，若 manifold 輸出含重複頂點則 STL 內容不同] → binary STL 本來就不存頂點索引，寫出的三角形與 `process=True` 後相同（merge 不改變面的座標）；以等價測試確認。

## Migration Plan

- 無資料遷移；對外 API 不變。以元件更新發布新 agent，前端不需同步。
- 回滾：還原 commit 重新發布即可；所有改動都在 agent 內部。
- 若要以 1.0.6.x hotfix 發出，再評估 cherry-pick 到 `release/v1.0.6`（本 change 從 `dev` 切出，需確認兩邊 `api_v2.py` 差異）。

## Open Questions

- 5M 改前後量測需要 `TriangleStress_5M.stl`（向前端索取的合成檔，不可用病患資料）；拿不到時只附合成 box 的相對倍數，並在 PR 說明。
- pending job TTL 2 小時是否符合前端實際使用節奏，請前端（Chloe）確認。

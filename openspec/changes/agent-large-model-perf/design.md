## Context

量測與拆解見交接文件「大模型後端交接」（E、F1 兩節）。量測對象為 Local Agent 1.0.6.3（agent commit `39c28c56fd5f`，`release/v1.0.6` tip）；本 change 從 `dev` 切出，只改 `agent/`。

現況重點：

- agent 由 Electron 啟動器（無前景視窗）帶起，slicer-engine 由 agent 以 `asyncio.create_subprocess_exec` 啟動，共三處：`jobs.run_slicing`、`jobs` 的 3MF 匯出、`sla_operations.run_prusa_cli`（支撐、挖空、切割、支撐點匯出共用）。引擎位於 Electron 的 Job Object 中，ControlMask 為 0（系統自動決定）。
- `_validate_stl_bytes()` 被 `upload_model_file()`、`upload_support_file()`、`_boolean_operation_impl()`、`_save_model_to_job()`（未預先驗證的內容）呼叫，每次都 `trimesh.load()`。驗證通過的 bytes 原樣寫檔，parse 結果丟棄。
- `_pending_jobs` 是 module 層級 dict，沒有時間戳。只有 `execute` 與 `ortho-process` 會 `del`；`generate-supports`、`export-support-points`、`generate-hollow`、`cut` 寫檔後保留 pending（之後可能在同一 job 上 `execute`），也就保留 bytes。
- `add_models_to_slice_job()` 以 `{"id": ..., **model, "validated": False}` 存入，request body 的任意 key 都會進入模型項目。
- `boolean_operation()` 的主路徑：`trimesh.load` → `Trimesh` → `manifold3d.Mesh` → `Manifold` → 運算 → `to_mesh` → `Trimesh(process=True)` → `is_watertight`（只為 log）→ `export`。修補序列（`boolean-non-manifold-tolerance`）建立在 `trimesh.Trimesh` 上。
- `boundary_detection._fast_load_binary_stl()` 已有 numpy 讀 binary STL 的先例（回傳未合併的三角形湯）。
- agent 與 slicer-engine 同時發布 Windows 與 macOS 版本。目前 agent 只在 `config.py` 依 `sys.platform == "win32"` 分流引擎路徑；交接量測（含 EcoQoS 的排除法）只在 Windows（i9-13900H，大小核）上做過，macOS 沒有任何量測。

## Goals / Non-Goals

**Goals:**

- agent 與 slicer-engine 子程序在 Windows 上不受 EcoQoS 執行速度節流。
- 上傳驗證不再解析 mesh；判準與前端 `assertImportableStl` 一致。
- 支撐重產不再累積模型 bytes；閒置 pending job 有上限壽命。
- boolean 的讀寫轉換成本降到 numpy 等級，結果與改前等價（三角形數、封閉、繞序）。
- F1 在 Windows 與 macOS 上行為一致；E 在 macOS 上完全不執行、不改變任何行為。

**Non-Goals:**

- F2 模型快取／hash 引用 API、indexed 上傳（需與前端 Chloe 共同設計）。
- F3 引擎讀檔修復（admesh）的超線性成長。
- 只對文字附近區域做 boolean。
- Bundle-Launcher（Electron）端的節流設定。
- 釋放 `models[1:]` 的 bytes（這些項目從未被寫檔，現況也未使用；另議）。
- macOS 的節流對策（App Nap、QoS class、`taskpolicy` 等）。沒有量測證據前不改，見 D7 與 Open Questions。

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

代價：header 檢查不會發現 binary 內容中的 NaN 座標、退化面等。這些在改前同樣不會被拒絕（`trimesh.load` 不 validate），所以拒絕集合實質上只縮小在「大小合格但內容是垃圾」的極少數檔案；這類檔案到引擎或 boolean 時會以引擎既有的錯誤碼失敗。`_boolean_operation_impl` 也走同一個函式，boolean 端對 binary 的讀取另有大小精確檢查（D5）。

改前會在上傳時被拒、改後延到引擎才失敗的檔案：ASCII 開頭正確但後段寫壞、binary 的座標全是 NaN（trimesh 會把面全部移除，變成空 mesh）。這些檔案不會產生錯誤的支撐或切片——引擎讀檔失敗時由 `slicing_classifier` 對應為 `INVALID_MODEL`（讀檔例外或 empty-model 標記），錯誤碼與改前相同；差別只在使用者要等到引擎讀檔（5M 約 30 s）後才看到錯誤，而不是上傳當下。前端匯入時已以相同判準（`assertImportableStl`）檢查，而且前端是先解析過模型才顯示的，這類檔案實際上很難走到 agent。

- 替代方案：numpy 讀入後檢查 finite → 仍需讀完整個 buffer（5M 約 0.3 s），而且改前並不拒絕 NaN，沒有必要。

### D3. 已落地模型以伺服器端型別標記，`_save_model_to_job` 沿用落地檔案

新增 `@dataclass(frozen=True) class _LandedModel: path: Path`。四個保留 pending 的端點在 `_save_model_to_job()` 成功、背景任務排入後呼叫 `_release_landed_model(pending, input_path)`：把 `models[0]` 換成 `{**原項目去掉 stl_data, "landed": _LandedModel(input_path)}`。`_save_model_to_job()` 只在 `isinstance(model_data.get("landed"), _LandedModel)` 時沿用檔案（同路徑不重寫、不同路徑 `shutil.copyfile`、不存在則 `MODEL_NOT_FOUND`）。

JSON request body 無法產生 `_LandedModel` 實例，所以 `add_models_to_slice_job()` 送來的 `"landed"` 欄位只會是 dict／字串，會被忽略並落入既有的 `stl_data`／`missing_body` 規則——避免呼叫端以偽造路徑讓 agent 複製任意檔案。

釋放放在背景任務排入之後：背景任務只讀 `input/model.stl`，不讀 `pending["models"]`，所以順序上沒有競爭；寫檔或設定驗證失敗時不會執行到釋放，pending 保持原狀可重試。

- 替代方案：generate-supports 後直接 `del _pending_jobs[job_id]` → 會讓之後在同一 job 上 `execute` 變成 `JOB_ALREADY_EXECUTED`，破壞現有流程。
- 替代方案：用字串 key `"saved_path"` → 可被 request body 偽造，有安全風險。

### D4. 閒置 pending job 的模型移到磁碟暫存，不刪除 job

**要解決的問題**：D3 只處理「模型已落地為 `input/model.stl`」的 job。另一種 job 從未落地：上傳後沒有呼叫任何操作（使用者關掉頁面、前端流程中斷、前端改開新 job 而丟下舊的），整份 bytes（5M 為 258 MB）會一直留在記憶體，直到 agent 重啟。

**初版的做法與為何放棄**：初版設計是閒置 2 小時就把整個 pending job 從 `_pending_jobs` 刪除。2 小時是估計值（前端的上傳 → 設定 → 執行通常在幾分鐘內完成），沒有量測或前端使用資料佐證。它的問題是會造成功能失敗：使用者上傳後離開超過 2 小時再按切片，會收到 `JOB_NOT_FOUND`；前端遇到這個錯誤是否會自動重開 job，目前不知道。釋放記憶體不應該以「讓使用者的操作失敗」為代價。

**採用的做法**：閒置時把 bytes 移到磁碟，job 本身留著。

- `_pending_jobs[job_id]` 建立時加入 `"last_access": time.monotonic()`；`_require_pending()` 與各端點取得 pending 的位置改經 `_touch_pending(job_id)` 更新（集中在一個 helper）。缺少 `last_access` 的項目（例如測試直接塞入的 dict）視為剛存取。
- 新增 `pending_job_spool_loop()`，每 60 s 呼叫 `_spool_idle_pending_jobs(now)`：對 `models[0]` 仍持有 `stl_data`、且閒置超過門檻的 job，把 bytes 寫到 `JOBS_DIR/.pending_spool/<job_id>.stl`（先寫 `.tmp` 再 `os.replace`，避免寫一半），成功後把 `models[0]` 換成 `{**原項目去掉 stl_data, "spooled": _SpooledModel(path)}`。`validated` 保留原值。寫檔失敗則不動該 job，記 WARNING。
- `_save_model_to_job()` 遇到 `_SpooledModel`：依 `validated` 決定是否先讀檔驗證，再以 `os.replace` 移到 `input_path`（同一個磁碟區，瞬間完成、不佔額外空間），之後項目改記為 `_LandedModel`。`_SpooledModel` 與 `_LandedModel` 一樣是 JSON 無法產生的伺服器端型別。
- `execute`／`ortho-process` 移除 pending job 時，若暫存檔仍在則刪除。agent 啟動時清空 `.pending_spool/`：重啟後 `_pending_jobs` 是空的，殘留檔案沒有對應的 job。
- 暫存目錄名稱含 `.`，`_JOB_ID_RE` 不允許 `.`，不會與任何 job id 衝突；它不是 job 目錄，`job_exists()` 與 `GET /slices/{job_id}` 的判斷不受影響。
- 背景迴圈在 `main.lifespan` 與 PRZ 清理迴圈一起啟動、一起取消；檢查是同步函式、在 event loop 內執行，與端點不會同時修改 `_pending_jobs`。寫檔本身用 `asyncio.to_thread`，期間若 job 被存取或已被移除，寫完後重新確認仍閒置、項目仍是同一個物件才替換，否則刪除剛寫的暫存檔。

**門檻怎麼定**：預設 600 s（10 分鐘），`AGENT_PENDING_SPOOL_IDLE_SEC` 可覆寫。因為暫存不會讓任何操作失敗，門檻只影響「記憶體多久釋放」與「回來時多一次讀檔」：
- 太短（例如 30 s）：使用者上傳後調整設定的空檔就可能觸發暫存，之後執行時多一次磁碟讀取。5M 從 SSD 讀約 0.2–0.5 s，代價很小但沒有必要。
- 太長（例如 2 小時）：孤兒 job 佔用記憶體太久，多開幾個就回到 2 GB 的問題。
- 10 分鐘：正常流程（上傳 → 設定 → 執行／產生支撐）在幾分鐘內完成，不會觸發；被丟下的 job 最多佔用 10 分鐘。這仍是估計值，因為不會造成失敗，可以先上線再依實際情況調整。

不設「刪除 pending job」的期限：bytes 移走後，一個 pending job 只剩設定與幾個欄位（KB 等級），留到 agent 重啟為止沒有實際負擔，也就沒有理由冒「使用者回來時 job 不見」的風險。

- 替代方案：閒置後刪除 job → 會造成 `JOB_NOT_FOUND`，見上。
- 替代方案：暫存到 job 目錄（`JOBS_DIR/<job_id>/input/`）→ 會建立 job 目錄，`GET /slices/{job_id}` 先查磁碟，回應會從 pending 的內容變成磁碟狀態，改變對外行為。
- 替代方案：上傳時就直接寫磁碟、記憶體完全不留 → 改動範圍較大（上傳、`use-model-from`、`add_models` 三條路徑都要改），且每次上傳都多一次寫檔；留給 F2 的模型快取一併設計。

### D5. boolean 讀寫改 numpy，修補路徑保留 trimesh

新增 `agent/stl_io.py`：

- `read_binary_stl_triangles(path) -> np.ndarray | None`：大小恰為 `84 + 50n` 且 `n > 0` 才讀（與 `_fast_load_binary_stl` 相同判準），回傳 `(n, 3, 3) float32`；否則 None。
- `merge_triangle_vertices(tris) -> (vertices float64, faces int64)`：先移除含非有限座標的面（對應 `remove_infinite_values`），再以 `np.round(v * 10**digits).astype(int64)`（`digits = trimesh.util.decimal_to_digits(trimesh.tol.merge)`，與 `grouping.merge_vertices` 相同）找出唯一列。**頂點順序必須與 trimesh 相同**：trimesh 用 `unique_rows(keep_order=True)`，依第一次出現的順序保留頂點；numpy 版以 `np.unique(axis=0, return_index=True, return_inverse=True)` 取得每個唯一列第一次出現的位置，依該位置重新排序並重算 inverse。結果的 `vertices`、`faces` 與 `trimesh.load(process=True)` 逐元素相同。

  為什麼一定要相同：主路徑只把陣列交給 manifold，頂點順序不影響結果；但修補序列（`fill_holes`、`fix_winding`、seam 焊接、平面封蓋）的部分步驟依頂點或邊的順序走訪，順序不同可能得到不同（雖然仍合法）的修補結果，也就是壓印結果會變。逐元素相同可以直接排除這個風險，不需要逐一證明各修補步驟與順序無關。
- `write_binary_stl(path, vertices, faces)`：以 `np.cross` 算法向量並正規化（長度 0 者為 0），組成 `dtype=[normal 3f4, v 9f4, attr u2]` 的結構陣列一次寫出。

`boolean_operation()`：兩個輸入先試 numpy 路徑，得到 `(verts, faces)` 後直接建 `manifold3d.Mesh(vert_properties=float32, tri_verts=int32)` → `Manifold`。主路徑有效時不建立 `Trimesh`。需要 fallback 時，才以 `trimesh.Trimesh(verts, faces, process=False)` 建立 `mesh_a`／`mesh_b` 交給現有修補序列（因為頂點已合併、無 NaN，`process=False` 與改前的 `process=True` 狀態相同）。ASCII 輸入沿用 `trimesh.load()`。結果：`to_mesh()` → `num_tri == 0` 判空 → `write_binary_stl`；log 改記面數與頂點數，不再計算 `is_watertight`。

合併頂點本可交給 `manifold3d.Mesh.merge()`，但 `merge()` 以容差合併並可能改變拓撲，與改前的 trimesh 判準不同；為了等價，主路徑用 numpy 與 trimesh 相同的捨入判準，`Mesh.merge()` 仍只在修補序列中使用（行為不變）。

`trimesh_to_manifold` 的 float32 轉換與改前相同：改前也是 `np.array(mesh.vertices, dtype=np.float32)`。

等價性驗收（`boolean-mesh-io`）分兩層：
1. 讀取層：`merge_triangle_vertices` 的輸出與 `trimesh.load(process=True)` 的 `vertices`、`faces` 逐元素相同（含 NaN 面、重複面、退化面）。
2. 結果層：以改前實作的複本（測試內保留舊路徑的參考函式）與改後實作對同一組輸入（封閉 box／sphere 組合、union／difference／intersection、ASCII 輸入、開口輸入觸發修補）比較。主路徑比較三角形數、`is_watertight`、`is_winding_consistent`、`volume`；修補路徑另要求輸出三角形逐面相同。

### D6. 測試

- `test_power_throttling.py`：非 Windows 為 no-op；以 monkeypatch 取代 kernel32 驗證參數（ControlMask=1、StateMask=0、Version=1）、handle 關閉、回傳 0 時只記 WARNING、例外被吞；`run_prusa_cli` 啟動後以子程序 PID 呼叫一次。Windows 上另有一個實際呼叫自身的 smoke test。
- `test_validate_stl_header.py`：spec 的每個 scenario 一個 case，另加 5M 大小 buffer 的時間上限。
- `test_pending_job_release.py`：上傳 → generate-supports（背景任務以 monkeypatch 替換）→ bytes 被釋放、`modelCount` 不變 → 同 job `execute` 成功且 `input/model.stl` 與上傳 bytes 相同；偽造 `"landed"`／`"spooled"` 欄位無效；落地檔案遺失回 `MODEL_NOT_FOUND`。暫存：閒置超過門檻才暫存、暫存後 `GET /slices/{job_id}` 不變、暫存後 `execute` 的 `input/model.stl` 與上傳 bytes 相同且暫存檔被移走、未驗證內容暫存後仍驗證、寫檔失敗時 job 保持原狀、寫檔期間 job 被存取或移除時不替換並刪掉暫存檔、啟動時清空暫存目錄、迴圈遇例外不中止。
- `test_boolean_numpy_io.py`：D5 的等價性矩陣。
- 兩個平台都要能跑：以 mock 取代 kernel32 的測試不依賴實際平台（同時 monkeypatch `sys.platform`），在 macOS 上也執行；只有「對自身實際呼叫」的 smoke test 以 `skipif(sys.platform != "win32")` 限定 Windows。另加一個 macOS 上的測試：`disable_execution_throttling()` 回傳 False、未載入 `ctypes.WinDLL`、未記任何 WARNING。

### D7. macOS：E 為 no-op，F1 跨平台，節流另行量測

**E**：`power_throttling` 以 `sys.platform == "win32"` 作唯一閘門，閘門外不 import 任何 Windows 專用符號（`ctypes.WinDLL`、`wintypes` 的 Windows 型別都只在函式內、通過閘門後才取用），確保模組在 macOS 上可正常 import。三處啟動引擎的位置無條件呼叫該函式，由函式自己判斷平台，呼叫端不寫平台分支。

**F1**：
- D2 的 header 檢查只用 `bytes` 與 `int.from_bytes(..., "little")`，與 CPU 位元組序無關。
- D5 的 numpy 讀寫明確指定 little-endian dtype（`<f4`、`<u4`、`<u2`），不依賴執行平台的原生位元組序（Apple Silicon 與 x86 都是 little-endian，明確指定是為了不留隱含假設）。
- D3 的落地檔案沿用使用 `pathlib.Path` 與 `shutil.copyfile`，不假設路徑分隔符或大小寫；同路徑判斷用 `Path.resolve()` 後比較，避免 macOS 上 `/private/var` 與 `/var` 這類符號連結造成誤判而重複複製。
- D4 的時間用 `time.monotonic()`，不受系統時鐘調整影響，兩個平台相同。

**macOS 節流**：macOS 也有可能讓 agent 變慢的機制——由沒有視窗的 Electron 啟動器帶起的程序可能受 App Nap 影響；Apple Silicon 依程序 QoS class 決定排在效能核心或效率核心。但目前沒有任何量測，無法判斷 agent 或引擎是否真的被降速、降多少，也不知道子程序會繼承什麼 QoS。若貿然加入對策（例如 agent 呼叫 `setpriority`／`pthread_set_qos_class_self_np`，或啟動器呼叫 Electron 的 `powerSaveBlocker.start('prevent-app-suspension')`），可能無效，或影響使用者前景工作的耗電與回應。因此本 change 不處理 macOS 節流，改為在 Open Questions 定義量測方法；有證據後另開 change，對策很可能落在啟動器端（Bundle-Launcher），不在 agent。

## Risks / Trade-offs

- [SetProcessInformation 在舊版 Windows 不存在或回傳 `ERROR_INVALID_PARAMETER`] → 只記 WARNING；行為退回現狀。
- [Job Object 或系統原則覆寫程序層設定，量測環境以外無效] → 交接量測已在實際 Electron + Job Object 下驗證有效；驗收時以 `SLICE_PROFILING=1` 從開始選單正常啟動再量一次。
- [header 檢查放行內容損壞但大小合格的 binary 檔] → 改前同樣不拒絕 NaN／退化面；損壞內容會在引擎或 boolean 階段以既有錯誤碼失敗，錯誤訊息可能較晚出現。
- [暫存佔用磁碟：被丟下的 job 每個在暫存目錄留一份模型檔] → 落地、execute、ortho-process 時刪除，agent 每次啟動清空；最壞情況是 agent 長時間不重啟、大量上傳後丟下，暫存目錄持續成長。與改前相比，改前同樣的情況是佔記憶體（更糟）；若實際觀察到問題，再加「暫存超過 N 天刪除」。
- [壞檔改成較晚才報錯：ASCII 後段寫壞、binary 座標全為 NaN 的檔案，改前在上傳時被拒，改後到引擎讀檔時才失敗] → 錯誤碼仍是 `INVALID_MODEL`，不會產生錯誤的支撐或切片；只是 5M 檔要等約 30 s 才看到錯誤。前端匯入時已解析過模型，這類檔案很難走到 agent。
- [boolean 修補路徑的結果改變] → D5 要求 numpy 合併頂點的順序與 trimesh 逐元素相同，修補序列的輸入與改前完全一致，並以逐面比對的測試保護。
- [numpy 合併頂點與 trimesh 在極端座標（|x| > 9e10）時整數溢位] → 牙科模型座標在 ±1000 mm 內；溢位或非有限時退回 `trimesh.load()` 路徑。
- [macOS 上其實也有節流，本 change 做完後 Mac 使用者仍偏慢] → F1 的改善在 macOS 上一樣生效；節流部分依 Open Questions 的方法量測後另行處理。
- [Windows 專用程式碼在 macOS 上 import 失敗，導致 agent 起不來] → D7 規定閘門外不碰 Windows 符號，並以 macOS 上的 import／no-op 測試保護。
- [結果 STL 不再經 `process=True`，若 manifold 輸出含重複頂點則 STL 內容不同] → binary STL 本來就不存頂點索引，寫出的三角形與 `process=True` 後相同（merge 不改變面的座標）；以等價測試確認。

## Migration Plan

- 無資料遷移；對外 API 不變。以元件更新發布新 agent（Windows 與 macOS 同一份 agent 程式碼），前端不需同步。
- 發布前在 macOS 上跑一次完整 `pytest agent/tests/`，並實際啟動 agent 做一次上傳 → 產生支撐 → 切片，確認 E 的模組不影響啟動、F1 正常。
- 回滾：還原 commit 重新發布即可；所有改動都在 agent 內部。
- 若要以 1.0.6.x hotfix 發出，再評估 cherry-pick 到 `release/v1.0.6`（本 change 從 `dev` 切出，需確認兩邊 `api_v2.py` 差異）。

## Open Questions

- 5M 改前後量測需要 `TriangleStress_5M.stl`（向前端索取的合成檔，不可用病患資料）；拿不到時只附合成 box 的相對倍數，並在 PR 說明。
- 暫存門檻 10 分鐘是估計值；暫存不會造成任何操作失敗，可先上線，再依前端（Chloe）的實際使用節奏調整。
- macOS 上 agent 與引擎是否被節流：在 Apple Silicon Mac 上，以同一個 5M 切片比較「從 Terminal 單獨執行 slicer-engine」與「由正常啟動的 agent 啟動」的引擎時間（`SLICE_PROFILING=1` 的 `profile.json`），並以 `taskinfo`／活動監視器記錄兩者的 QoS 與所在核心；同時比較 5M 上傳時間。差距明顯（例如 > 20%）才另開 change 設計對策。

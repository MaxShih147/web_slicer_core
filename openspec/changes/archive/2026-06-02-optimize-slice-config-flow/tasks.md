## 1. 後端萃取器開發（`_extract_sla_from_mechado`）

- [x] 1.1 在 [agent/api_v2.py](agent/api_v2.py)（約 1513 helper 區）新增 `_extract_sla_from_mechado(mechado, center=None)`，依 design D1 映射 9 核心欄位 + 隨附欄位（exposure、bottom_layer_count、printer_model、retract×4）。bed_size 取 `[2]/[3]`、image_size 取 `[0]/[1]`、AA Level / blur **直接複製**（禁止二次轉換）、缺值留預設不拋錯
- [x] 1.2 **【驗證】** 撰寫並執行單元測試：固定一份含完整 Machine/Advanced 的 mechado，斷言 spec「新流程萃取」場景數值（`display_width==134`、`display_height==75`、`anti_aliasing_level==2` 未被轉換、缺 `Advanced` 退預設不報錯）
- [x] 1.3 實作 center 換算：提供 `center=[x,y]` 時 `center_x = center[0] + display_width/2`、`center_y = center[1] + display_height/2`（依萃取出的 bed_size）
- [x] 1.4 **【驗證】** 撰寫並執行單元測試：`center=[10,-5]` + `bed_size=[0,0,134,75]` → `center_x==77.0`、`center_y==32.5`；未提供 center 時不產生 `center_x/center_y`

## 2. Round-trip 等價測試（測試優先，守門新舊一致）

- [x] 2.1 撰寫 Round-trip 等價測試：取同一組代表性 uiParams，比對「`uiToDefault`→mechado→`_extract_sla_from_mechado`」結果與「舊 `uiToBackendSlicingConfig`→snake」結果，逐欄位斷言**完全一致**（特別針對 `anti_aliasing_level`、`blur`、`display_width/height`、`layer_height`）
- [x] 2.2 涵蓋多個內建 profile（如 sonic_4k_2022、sonic_cs_plus）參數化驗證，確保 bed_size 索引與刻度在不同機型皆一致
- [x] 2.3 **【驗證】** 執行 2.1–2.2 全數通過；任一欄位不一致須回到階段 1 修正萃取器後重跑

## 3. API 欄位擴充（`V2SliceCreateRequest`）

- [x] 3.1 於 [agent/api_v2.py](agent/api_v2.py) 的 `V2SliceCreateRequest` 新增 `center: Optional[List[float]] = None`；`create_slice_job` 將 `center` 存入 `_pending_jobs[job_id]`
- [x] 3.2 **【驗證】** API 測試：`POST /slices` 帶 `prz_config` + `center` 應成功建立 job；**未帶 `center` 的舊請求**仍成功（不回 422），確認向後相容

## 4. Execute 合併邏輯修正（base ← override）

- [x] 4.1 改寫 `execute_slice_job`（[api_v2.py:436](agent/api_v2.py#L436)）：抽出 `_build_sla_config(prz_cfg, snake, center)`，`merged = _extract_sla_from_mechado(prz_cfg, center)`（base）→ `merged.update(snake 非 None 欄位)`（欄位級覆蓋）→ `SLAConfig(**merged)`；保留 `merged` 為空時 fallback `_convert_v2_config_to_sla(snake)`
- [x] 4.2 **【驗證】** API/整合測試三條路徑：(a) 新流程只送 mechado → 純萃取結果；(b) mechado + 後續 `PUT {layer_height:0.10}` → 最終 `layer_height==0.10`（PUT 覆蓋）；(c) 舊流程（空 config + PUT snake + execute）→ 結果等同變更前 `_convert_v2_config_to_sla(snake)`

## 5. PRZ 降級支援（download.prz config/preview optional）

- [x] 5.1 修改 `download.prz` handler（[api_v2.py:953](agent/api_v2.py#L953)）：config body 與 preview 改 optional；body 缺 config 時 fallback 讀取 job 的 `prz_config.json`；body 顯式提供時以 body 優先；缺 preview 沿用既有預設（抽出 `_resolve_prz_download_config` helper）
- [x] 5.2 **【驗證】** API 測試：(a) 空 body → 從 `prz_config.json` 解析 config（不讀檔則拋錯）；(b) 顯式 body config → 以 body 為優先（不讀檔）；(c) 無 preview → `_decode_preview_rgb(None)` 回 None 不失敗

## 6. 前端呼叫簡化（DS-online）

- [x] 6.1 修改 [slicingService.js](D:/repos/DS-online/src/services/slicingService.js)：`POST /slices` 帶 `prz_config=mechado` + `center`（`createJob` 與 `ensureSlicingJob` 加 center 參數）；正常流程**移除/註解** `PUT /config` 的 snake config 呼叫；[backendService.js](D:/repos/DS-online/src/axios/backendService.js) `downloadPrz` 改 config optional，呼叫端傳 `null`。ESLint 通過（移除未使用的 `updateJobConfig` import）
- [x] 6.2 **【驗證】** 前端對接後端跑一次完整切片→下載 PRZ 流程，確認「UI 擺放 = 圖檔位置」、切片參數（AA/解析度/幅面）正確、PRZ 正常產出 —— 使用者實機驗證通過（切片順利、UI 擺放=圖檔位置正確），並附帶解決先前的平移未連動 Known Issue
- [x] 6.3 （過渡）暫保留 `uiToBackendSlicingConfig` 不刪除（adapters 仍匯出，僅正常流程不再呼叫），待後端萃取於正式環境驗證穩定後另案移除

## 7. 全量回歸與收尾

- [x] 7.1 執行後端既有測試套件，確認無迴歸（特別是 `sla-slice-config`、`print-time-sync`、PRZ 相關）—— 80 項中 79 通過；唯一失敗 `test_6_11_single_normal_layer_full_params` 屬 `prz_encoder._compute_print_time` 的 retract Case 2 既有問題，與本變更無關（本變更僅改 `api_v2.py`，未動 `prz_encoder.py`）
- [x] 7.2 確認 design「Future Works FW1」（AA 顯示值 2/4/8）僅為記錄、未被本變更實作，控制值/顯示值未混用 —— 萃取器對 AA Level 直接複製（控制刻度），未回填顯示值，符合記錄
- [x] 7.3 更新相關文件/註解，標注 `_convert_v2_config_to_sla` 與 `_extract_sla_from_mechado` 的職責邊界 —— 兩函式 docstring 已載明差異（舊函式僅讀 Print/頂層 snake；新函式理解三段式巢狀並涵蓋 Machine/Advanced）；前端註解亦已標明單一真相流程切換
## 標準底墊全域參數（10 項）

- [Auto] 送出 10 個標準欄位任一自訂值，`generate_config_ini` 寫出的 ini 內容與送出值一致
- [Auto] 不提供任一標準欄位時，`SLAConfig` 套用 `PrintConfig.cpp` 的註冊預設值
  （`pad_wall_thickness=2.0`、`pad_wall_height=0.0`、`pad_brim_size=1.6`、
  `pad_max_merge_distance=50.0`、`pad_object_gap=1.0`、
  `pad_object_connector_stride=10.0`、`pad_object_connector_width=0.5`、
  `pad_object_connector_penetration=0.3`）
- [Auto] **預設值合約測試**：解析 `PrintConfig.cpp` 的 11 個 `pad_*`
  `set_default_value(...)`，與 `SLAConfig` 的預設值逐一比對，不一致即失敗
- [Auto] 合約測試的負向檢查：刻意改錯一個期望值時測試必須失敗（證明斷言有效）

## 底墊側壁斜度（範圍驗證）

- [Auto] `pad_wall_slope` 送 `45`／`67.5`／`90` 皆可正常設定並寫入 ini
- [Auto] `pad_wall_slope` 送 `0` 觸發驗證錯誤，不寫入 ini，不呼叫引擎 CLI
- [Auto] `pad_wall_slope` 送 `44.9`／`90.1`／`120`／負值皆觸發驗證錯誤
- [Auto] 未提供 `pad_wall_slope` 時套用預設值 `90.0`（不是 `Pad.hpp` 的 45°）

## zero-elevation 專屬欄位

- [Auto] `pad_enable=False` 時送出 5 個專屬欄位自訂值，可正常設定且不觸發驗證錯誤
- [Auto] `pad_around_object=False` 時送出 5 個專屬欄位自訂值，可正常設定且不觸發驗證錯誤
- [Auto] 這 5 個欄位未套用任何 `model_validator` 或條件式連動邏輯
- [Manual] `pad_enable=True` 且 `pad_around_object=True` 時，`pad_object_gap`
  自訂值確實改變模型底部與底墊之間的間隙
- [Manual] `pad_object_connector_stride=0` 時切片成功完成，且不產生連接柱幾何

## 引擎交叉驗證（透傳，不在 API 層攔截）

- [Auto] `pad_brim_size=0.05` 可通過 API 驗證並原樣寫入 ini（API 層不攔截）
- [Manual] 上述組合送出切片後，引擎回傳
  `"Pad brim size is too small for the current configuration."` 類型的錯誤訊息，
  且該訊息可被 API 使用者取得
- [Manual] zero-elevation 開啟且 `support_base_safety_distance < pad_object_gap`
  時，引擎回傳對應的驗證錯誤訊息

## 契約與回歸

- [Manual] `api/slicing_core.md` 已補上本批 11 個參數的請求 body 說明，含
  `pad_wall_slope` 的 `45–90` 合法範圍、5 個 zero-elevation 專屬欄位的精確
  生效條件、connector 設 `0` 的靜默停用行為、`pad_wall_height` 的脫模警告、
  `pad_around_object` 會忽略 `support_object_elevation` 的提示
- [Manual] `api/slicing_core.md` 已新增引擎兩條交叉驗證規則的說明，並註明由
  引擎在切片階段檢查
- [Manual] 直接呼叫後端 API（curl／httpie／FastAPI TestClient，不透過 UI）送出
  本次 11 個新欄位，確認 `_convert_v2_config_to_sla` 與 `_build_sla_config`
  兩條路徑的回應與 `config.ini` 內容正確
- [Auto] 既有 `test_sla_config.py`／`test_support_e2e.py` 等既有測試全數通過（無回歸）
- [Manual] 完工後的追蹤 Artifact 已發布，內容含本次做了什麼、沒做什麼、
  以及 openspec change 的回溯連結
- [Manual] 該 Artifact 已完整收錄 design.md 的「D2 白話說明」「D3 白話說明」
  「D4 白話說明」三節，含 D2 的除以零推導、D3 的預設值對照表與
  「F2 之前／之後」ini 行為對比、D4 不擋的四個理由，且未被壓縮成條列摘要
- [Manual] 該 Artifact 有一段醒目的「條件生效參數」提醒，列出 D4 的 5 個參數、
  說明其生效條件（`pad_enable` 與 `pad_around_object` 同時為 `true`）、
  並明確指示未來整理參數清單時 SHALL 特別標記這類參數

## 本次不含（移出範圍，留給前端 change）

- 面板新增 11 個可調控件（滑桿／輸入／開關）
- `pad_wall_slope` 滑桿下限設為 45（不是 0）
- 5 個 zero-elevation 專屬控件的顯示條件處理
- `pad_wall_height` 脫模警告與 `pad_around_object` 連動提示的 tooltip
- 前端 `sceneCoordinator.js:3888` 的 `PAD_WALL_THICKNESS_MM=2` 硬編碼替換
- 四語系 i18n 文案

## 本次不含（獨立追蹤項目）

- 全切片路徑（`/execute`）對引擎 `validate()` 失敗的偵測可靠性查證
- 若查證確認有洞，補上偵測邏輯的實作與測試

# dental-model-type-confirm Specification

## Purpose

提供「確認模型是否為指定類型」的後端服務，作為既有 `dental-model-classification` 的補充。
當前端工作流程只需要一個布林答案（「此模型是否為 crown？」）而非完整 model_type 時，
此 API 能透過沿用既有分類決策樹中的 early return 路徑，避免執行不必要的導孔偵測，降低回應延遲。

---

## Requirements

### Requirement: API 輸入契約

`POST /api/v2/confirm-model-type` 端點 SHALL 接受 `multipart/form-data` 格式的請求，包含下列兩個必填欄位：

| 欄位 | 型別 | 說明 |
|------|------|------|
| `file` | 二進位 | STL 檔案；檔案名稱 SHALL 以 `.stl` 結尾（大小寫不分） |
| `target_type` | 字串 | 欲確認的目標類型；SHALL 為 `dental-model-classification` 規格所定義的八種枚舉值之一 |

#### Scenario: 合法輸入
- **WHEN** 以 `multipart/form-data` 上傳副檔名為 `.stl` 的合法 STL 檔案，且 `target_type` 為合法枚舉值
- **THEN** 端點 SHALL 完成確認並回傳 HTTP 200

---

### Requirement: API 成功輸出契約

成功時 SHALL 回傳以下 JSON 結構：

```json
{
  "success": true,
  "message": null,
  "data": {
    "confirmed": true
  }
}
```

`data.confirmed` SHALL 為布林值，代表模型是否屬於指定的目標類型。
端點 SHALL 不在回應中揭露模型的實際類型（無論 confirmed 為 true 或 false）。

#### Scenario: 確認成立
- **WHEN** 上傳合法 STL 且分類結果等於 `target_type`
- **THEN** HTTP status SHALL 為 200
- **AND** `data.confirmed` SHALL 為 `true`

#### Scenario: 確認不成立
- **WHEN** 上傳合法 STL 且分類結果不等於 `target_type`
- **THEN** HTTP status SHALL 為 200
- **AND** `data.confirmed` SHALL 為 `false`
- **AND** 回應 body SHALL 不包含模型的實際類型

---

### Requirement: API 輸入驗證

端點 SHALL 在發生下列條件時拒絕請求。所有錯誤回應 SHALL 包含 `success: false`、`code`、`message`、`data.retryable`、`data.traceId` 欄位：

| 條件 | `code` | HTTP status | `data.retryable` |
|------|--------|-------------|-----------------|
| 未提供 `file` 欄位或欄位無檔案名稱 | `MISSING_BODY` | 400 | false |
| 副檔名非 `.stl`（大小寫不分） | `VALIDATION_ERROR` | 400 | false |
| 上傳內容為 0 bytes | `MISSING_BODY` | 400 | false |
| STL 格式錯誤或 mesh 無三角面 | `INVALID_MODEL` | 422 | false |
| 未提供 `target_type` 欄位 | `MISSING_BODY` | 400 | false |
| `target_type` 不在枚舉值之中 | `VALIDATION_ERROR` | 400 | false |
| 上傳檔案讀取失敗或處理期間發生未預期例外 | `INTERNAL_ERROR` | 500 | true |

#### Scenario: target_type 無效
- **WHEN** `target_type` 欄位的字串不是 `DentalModelType` 枚舉的合法值（例如 `"molar"`）
- **THEN** HTTP status SHALL 為 400
- **AND** `code` SHALL 為 `"VALIDATION_ERROR"`
- **AND** `data.retryable` SHALL 為 `false`

#### Scenario: 缺少 target_type
- **WHEN** 請求中未包含 `target_type` 欄位
- **THEN** HTTP status SHALL 為 400
- **AND** `code` SHALL 為 `"MISSING_BODY"`

---

### Requirement: 與完整分類的一致性（無例外）

`confirm(mesh, target) == (classify(mesh) == target)` SHALL 對所有 target 無例外成立。

對同一個 mesh，全部八種 DentalModelType 值中恰好有一個使 `confirm()` 回傳 true，且該值必等於 `classify()` 的回傳值；其餘七個 target SHALL 全部回傳 false。

#### Scenario: 完整不變量驗證
- **GIVEN** 任意合法 STL
- **WHEN** 先呼叫 `POST /api/v2/classify-model` 取得 `actual_type`
- **AND** 再對全部八種 DentalModelType 分別呼叫 `POST /api/v2/confirm-model-type`
- **THEN** `confirm(actual_type)` SHALL 為 `true`
- **AND** 其他所有 target 的 `confirm()` SHALL 為 `false`

此驗證 SHALL 同時涵蓋 early-return 路徑（P0 / P_base / P2 / P3）與 P5 路徑（含導孔偵測），不得有例外排除。

#### Scenario: 確定性
- **WHEN** 對同一個 STL 連續兩次呼叫 `POST /api/v2/confirm-model-type`（相同 target_type）
- **THEN** 兩次 `data.confirmed` SHALL 完全相同

---

### Requirement: Early return — 導孔偵測前確認

對於能在導孔偵測執行前即可確定確認結果的類型與情境，confirm 函式 SHALL 提前回傳布林值，不執行導孔偵測。

下列情境 SHALL 發生 early return（不執行導孔偵測）：

1. **PCA 提取失敗（P0）**：`target == "other"` 時回傳 true；其餘 target 回傳 false。

2. **基座模型跳過分支（P_base）**：skip reason 為「單側大平面且符合基座尺寸」。
   - target 為 `dental_model` 或 `u_shaped_dental_model`：透過共用 helper `_p_base_decide()` 決定分流結果並回傳
   - 其他 target：直接回傳 false

3. **牙冠跳過分支（P2）**：skip reason 為「明確牙冠尺寸」或「小尺寸交界且比例偏向牙冠」。
   - target 為 `crown`：回傳 true
   - 其他 target：回傳 false

4. **口掃跳過分支（P3）**：skip reason 為「大型開放邊界」。
   - target 為 `intraoral_scan`：回傳 true
   - 其他 target：回傳 false

5. **needs_drill=True 且 target 為 `dental_model`、`u_shaped_dental_model`、`intraoral_scan`、`other`**：
   代碼分析確認這四種類型無法出現在 P5（`other` 僅由 P0 產生，PCA 成功後不可能再出現），直接回傳 false，不執行導孔偵測。

#### Scenario: 對 crown 確認 — P_base 路徑 early return
- **GIVEN** 一個符合基座模型條件（單側大平面且尺寸符合全弓範圍）的 STL
- **WHEN** 呼叫 `POST /api/v2/confirm-model-type`，`target_type` 為 `"crown"`
- **THEN** 端點 SHALL 不執行導孔偵測
- **AND** `data.confirmed` SHALL 為 `false`

#### Scenario: 對 crown 確認 — P2 路徑 early return
- **GIVEN** 一個三軸均小且 L1 明確偏向牙冠尺寸的 STL（clear_crown_size_score ≥ 0.65）
- **WHEN** 呼叫 `POST /api/v2/confirm-model-type`，`target_type` 為 `"crown"`
- **THEN** 端點 SHALL 不執行導孔偵測
- **AND** `data.confirmed` SHALL 為 `true`

#### Scenario: 對 intraoral_scan 確認 — P3 路徑 early return
- **GIVEN** 一個具有大型開放邊界的口腔內掃描 STL
- **WHEN** 呼叫 `POST /api/v2/confirm-model-type`，`target_type` 為 `"intraoral_scan"`
- **THEN** 端點 SHALL 不執行導孔偵測
- **AND** `data.confirmed` SHALL 為 `true`

#### Scenario: 對 dental_model 確認 — P_base 路徑 early return
- **GIVEN** 一個符合基座模型條件且 U 型缺口特徵低的 STL
- **WHEN** 呼叫 `POST /api/v2/confirm-model-type`，`target_type` 為 `"dental_model"`
- **THEN** 端點 SHALL 不執行導孔偵測
- **AND** `data.confirmed` SHALL 為 `true`

---

### Requirement: P5 fallback — 無法提前確認時的處理

對於 `needs_drill=True` 且 target 為 `crown`、`bridge`、`splint`、`surgical_guide` 的情形，confirm 函式 SHALL 執行完整的 P5 流程後比較結果。

執行 P5 流程時 SHALL 沿用 confirm 流程前段已計算的 `features` 物件（包含 PCA、開放邊界、平面、投影等特徵），接續執行導孔偵測並填入 `features.drill_*` 欄位，再呼叫 `_decide_model_type_with_details(features)` 取得最終 model_type，**不得**重新從 mesh 頭開始重跑特徵提取流程。

#### Scenario: surgical_guide 目標 — P5 完整分類後比較
- **GIVEN** 一個不符合任何 early return 條件的 STL
- **WHEN** 呼叫 `POST /api/v2/confirm-model-type`，`target_type` 為 `"surgical_guide"`
- **THEN** 端點 SHALL 執行導孔偵測
- **AND** `data.confirmed` SHALL 等於（完整分類結果 == `"surgical_guide"`）

#### Scenario: bridge 目標 — P5 完整分類後比較
- **GIVEN** 一個不符合任何 early return 條件的 STL
- **WHEN** 呼叫 `POST /api/v2/confirm-model-type`，`target_type` 為 `"bridge"`
- **THEN** 端點 SHALL 執行導孔偵測
- **AND** `data.confirmed` SHALL 等於（完整分類結果 == `"bridge"`）

#### Scenario: crown 目標（P2 未命中）— P5 完整分類後比較
- **GIVEN** 一個 L1 在 12–18mm 邊界區且 crown_small_score 未達強信號門檻的 STL
- **WHEN** 呼叫 `POST /api/v2/confirm-model-type`，`target_type` 為 `"crown"`
- **THEN** 端點 SHALL 執行導孔偵測
- **AND** `data.confirmed` SHALL 等於（完整分類結果 == `"crown"`）

---

### Requirement: 既有 classify-model 端點不受影響

`POST /api/v2/classify-model` 端點的輸入契約、輸出契約與錯誤碼 SHALL 與本次變更前完全相同。
`classify_dental_model()` 函式的公開簽章（`(mesh) -> DentalModelType`）SHALL 保持不變。

#### Scenario: classify-model 端點行為不變
- **WHEN** 本次變更部署後，對任意 STL 呼叫 `POST /api/v2/classify-model`
- **THEN** 回應結構與 `data.model_type` 的取值集合 SHALL 與部署前完全相同

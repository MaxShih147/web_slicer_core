# dental-model-classification Specification

## Purpose

提供牙科 STL 模型種類自動判斷的後端服務，讓前端工作流程能取得模型類型資訊，供後續作業（例如 auto-orient 模式選擇、切片參數配置）使用。後端分類器與 API 端點已完成；前端串接及根據分類結果自動選擇後續工作流程的功能尚未完成。

## Requirements

### Requirement: 分類結果枚舉定義

分類器 SHALL 將每個 STL 模型對映至以下八種類型之一，以字串形式回傳：

| 值 | 語義 |
|----|------|
| `dental_model` | 標準牙弓基座模型（帶單側底平面） |
| `u_shaped_dental_model` | U 型牙弓基座模型（底平面加上顯著 U 型投影缺口） |
| `crown` | 單顆牙冠（三軸均小，L1 偏向牙冠範圍） |
| `bridge` | 多顆連橋（L1 較長且 L1/L2 比例具延伸特徵） |
| `splint` | 咬合板（薄型全弓覆蓋，L3 明顯薄於基座） |
| `surgical_guide` | 手術導板（含導孔圓柱，或具非單側大平面） |
| `intraoral_scan` | 口腔內掃描（大型開放邊界） |
| `other` | 必要幾何特徵缺失，無法完成可靠分類（目前為 PCA 提取失敗） |

回傳值 SHALL 不得為上表以外的字串。

---

### Requirement: API 輸入契約

`POST /api/v2/classify-model` 端點 SHALL 接受 `multipart/form-data` 格式的請求，其中 `file` 欄位為必填的 STL 檔案。`file` 欄位的檔案名稱 SHALL 以 `.stl` 結尾（大小寫不分）。

#### Scenario: 合法輸入
- **WHEN** 以 `multipart/form-data` 上傳一個副檔名為 `.stl` 的合法 STL 檔案
- **THEN** 端點 SHALL 完成分類並回傳 HTTP 200

---

### Requirement: API 成功輸出契約

成功時 SHALL 回傳以下 JSON 結構：

```json
{
  "success": true,
  "message": null,
  "data": {
    "model_type": "<DentalModelType 字串值>"
  }
}
```

`data.model_type` SHALL 為「分類結果枚舉定義」中的八種字串值之一。

#### Scenario: 成功分類
- **WHEN** 上傳合法 STL 且分類正常完成
- **THEN** HTTP status SHALL 為 200
- **AND** 回應 body 中 `success` SHALL 為 `true`
- **AND** `data.model_type` SHALL 為枚舉定義的八種字串之一

---

### Requirement: API 輸入驗證

端點 SHALL 在發生下列條件時拒絕請求。所有錯誤回應 SHALL 包含 `success: false`、`code`、`message`、`data.retryable`、`data.traceId` 欄位：

| 條件 | `code` | HTTP status | `data.retryable` |
|------|--------|-------------|-----------------|
| 未提供 `file` 欄位或欄位無檔案名稱 | `MISSING_BODY` | 400 | false |
| 副檔名非 `.stl`（大小寫不分） | `VALIDATION_ERROR` | 400 | false |
| 上傳內容為 0 bytes | `MISSING_BODY` | 400 | false |
| STL 格式錯誤或 mesh 無三角面 | `INVALID_MODEL` | 422 | false |
| 上傳檔案讀取失敗或分類處理期間發生未預期例外 | `INTERNAL_ERROR` | 500 | true |

#### Scenario: 副檔名非 .stl
- **WHEN** 上傳的 `file` 欄位檔案名稱不以 `.stl` 結尾（如 `.obj`、`.ply`）
- **THEN** HTTP status SHALL 為 400
- **AND** `code` SHALL 為 `"VALIDATION_ERROR"`
- **AND** `data.retryable` SHALL 為 `false`

#### Scenario: STL 格式錯誤
- **WHEN** 上傳的檔案副檔名為 `.stl` 但內容非合法 STL 格式，或 mesh 解析後無三角面
- **THEN** HTTP status SHALL 為 422
- **AND** `code` SHALL 為 `"INVALID_MODEL"`
- **AND** `data.retryable` SHALL 為 `false`

#### Scenario: 空白檔案
- **WHEN** 上傳的 `file` 欄位內容為 0 bytes
- **THEN** HTTP status SHALL 為 400
- **AND** `code` SHALL 為 `"MISSING_BODY"`

---

### Requirement: 幾何特徵提取

分類器 SHALL 從 STL mesh 提取以下四類幾何特徵，作為所有分類判斷的輸入依據：

1. **凸包面積加權 PCA**：計算三個主軸長度 L1（最長）、L2（次長）、L3（最短），以及 L1/L2 延伸比例等衍生值。
2. **開放邊界統計**：計算 open edge 數量、邊界 loop 數量、最大 loop 周長及全體開放邊長度總和。
3. **外側大平面統計**：偵測 mesh 表面的外側大平面，計算其面積比例及單側性（是否僅存在於單側）。
4. **投影形狀缺口統計**：將 mesh 投影至平面，計算最大缺口面積、缺口與投影凸包的接觸長度，以及中型與大型投影孔洞數量。

上述特徵的提取 SHALL 先於任何分類判斷完成。

#### Scenario: PCA 提取失敗
- **WHEN** mesh 的凸包面積趨近於零，PCA 提取失敗
- **THEN** 分類器 SHALL 跳過 signal 計算與導孔偵測，並由 P0 分支回傳 `"other"`

---

### Requirement: 條件式導孔偵測

導孔偵測（drill hole detection）為成本較高的演算法，分類器 SHALL 僅在其他低成本特徵無法得出明確結論時才執行。下列任一條件成立時 SHALL 跳過導孔偵測：

- 單側大平面信號強且尺寸符合基座模型範圍（dental_model / u_shaped_dental_model 分支）
- 明確或邊界牙冠尺寸且尺寸與比例比較偏向牙冠
- 大型開放邊界（intraoral_scan 分支）

以上條件均不成立時 SHALL 執行導孔偵測。偵測到符合規格的環形導孔時 SHALL 判斷為 `surgical_guide`。

#### Scenario: 跳過導孔偵測（基座模型）
- **WHEN** 基座模型尺寸信號達候選門檻，且單側大平面信號達強信號門檻
- **THEN** 導孔偵測 SHALL 不被執行
- **AND** 分類器 SHALL 依 U 型缺口信號強弱在 `dental_model` 與 `u_shaped_dental_model` 之間做出決定

#### Scenario: 偵測到導孔
- **WHEN** 導孔偵測執行且找到符合尺寸條件的環形導孔候選
- **THEN** `data.model_type` SHALL 為 `"surgical_guide"`

#### Scenario: 跳過導孔偵測（大型開放邊界）
- **WHEN** 大型開放邊界信號達到強信號門檻
- **THEN** 導孔偵測 SHALL 不被執行
- **AND** `data.model_type` SHALL 為 `"intraoral_scan"`

---

### Requirement: other fallback

PCA 提取失敗時，分類器 SHALL 回傳 `"other"`，而非強行推測類型。

#### Scenario: 必要特徵缺失
- **WHEN** mesh 凸包面積趨近於零導致 PCA 提取失敗
- **THEN** `data.model_type` SHALL 為 `"other"`

---

### Requirement: 分類結果確定性

分類器 SHALL 為確定性演算法；相同輸入 mesh 在相同執行環境下 SHALL 產生相同的 `model_type`。分類器不使用隨機抽樣或機率採樣。

#### Scenario: 重複呼叫相同檔案
- **WHEN** 對同一個 STL 檔案連續兩次呼叫 `POST /api/v2/classify-model`
- **THEN** 兩次回應的 `data.model_type` SHALL 完全相同

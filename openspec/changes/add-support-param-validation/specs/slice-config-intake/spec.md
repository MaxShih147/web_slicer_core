## ADDED Requirements

### Requirement: 儲存設定當下即驗證

`PUT /config` SHALL 在收下設定的當下套用參數規則表，MUST NOT 原封不動接受後等到 execute 才失敗。

驗證 MUST 與 `POST /api/v2/support-params/validate` 共用同一份 `param_rules.py`，MUST NOT 另寫一套判斷。

#### Scenario: 存入違規設定
- **WHEN** 呼叫 `PUT /config` 送出違反規則的支撐參數
- **THEN** 回應 HTTP 422、`retryable` 為 false、訊息含欄位名
- **AND** 該設定 MUST NOT 被存下

#### Scenario: 存入合法設定
- **WHEN** 送出合法設定
- **THEN** 行為與本變更前完全相同

#### Scenario: 規則只有一份
- **WHEN** 新增一條參數規則
- **THEN** `PUT /config` 與 `/validate` 兩處 MUST 同時生效，無需分別修改

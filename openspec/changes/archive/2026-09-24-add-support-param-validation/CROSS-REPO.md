# 跨 repo 對照

權威規格：**本目錄**（`specs/support-param-validation`）。規則真值放後端，因為前端不得重寫任何驗證公式。

| Repo | 本單角色 | Change |
|---|---|---|
| **web_slicer_core**（本 repo） | 權威 spec ＋ 後端實作 | `add-support-param-validation`（本目錄） |
| DS-Online | Companion：面板欄位、檢查站串接、i18n | `open-support-param-panel` |

## 相依順序

```
unify-error-code-registry (web_slicer_core)
        ↓  產出 docs/error_codes.json
merge-engine-result-classifiers (web_slicer_core)
        ↓
add-support-param-validation (web_slicer_core)   ← 本單
        ↓  提供 POST /api/v2/support-params/validate
open-support-param-panel (DS-Online)
```

前端不得在後端端點就緒前合併 companion change。前端須具備「後端未提供 `/validate` 時整段跳過」的降級路徑，面板仍可正常使用。

## 契約交接點

| 項目 | 由誰定義 | 消費方 |
|---|---|---|
| error code 清單 | `unify-error-code-registry` 的 `docs/error_codes.json` | DS-Online `api/error_codes.json` |
| `/validate` request / response schema | 本單 `specs/support-param-validation/spec.md` | DS-Online 檢查站 composable |
| `problems[].fields` 的欄位命名 | 後端 `SLAConfig` 的 snake_case 欄位名 | 前端 `SupportEditor.vue` 的 `data-field` 屬性（已一致，無需轉換） |

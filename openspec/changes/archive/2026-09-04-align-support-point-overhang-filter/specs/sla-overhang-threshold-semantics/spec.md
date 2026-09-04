## ADDED Requirements

### Requirement: 懸空角度門檻的計算公式與方向語意

懸空角度門檻 SHALL 以「表面與水平面的夾角」為判準。一個支撐點的所在表面 SHALL 通過過濾，若且唯若該表面的斜度小於或等於 `90 度 − support_critical_angle`。

設表面法線的球面極角為 `polar`（弧度，0 代表法線指向正上方，PI 代表法線指向正下方），門檻為 `threshold`（弧度，由 `support_critical_angle` 乘 `PI / 180` 換算），則通過條件 SHALL 為：

```
polar >= PI / 2 + threshold
```

此式與「表面斜度 <= 90 度 − 設定值」代數等價，推導為 `polar = PI − 表面斜度`。

方向語意 SHALL 為「數值越小，生成的支撐越多」。`support_critical_angle` 為 0 度時 SHALL 支撐所有朝下的面；為 90 度時 SHALL 只支撐完全水平朝下的面。

此方向 SHALL 與 `PrintConfig.cpp` 的參數 tooltip 及 DS-Online 前端的四國語系文案（en / tw / cn / jp）保持一致。任何一方變動時，三者 MUST 同步變動。

#### Scenario: 完全水平朝下的面在任何門檻下都通過
- **GIVEN** 一個支撐點所在表面完全水平且朝下（`polar` 為 180 度，表面斜度為 0 度）
- **WHEN** `support_critical_angle` 設為 0、45 或 90 度
- **THEN** 三種設定下該點 SHALL 皆通過過濾

> 本場景約束的是**判定式本身**，其前提為「該點的 `polar` 已知為 180 度」。實體網格上位於島嶼輪廓附近的點，其 `polar` 未必為 180 度——見下方「邊界內縮點的法線平滑效應」需求。

#### Scenario: 垂直牆面只在門檻為 0 度時通過
- **GIVEN** 一個支撐點所在表面為垂直牆面（`polar` 為 90 度，表面斜度為 90 度）
- **WHEN** `support_critical_angle` 設為 0 度
- **THEN** 該點 SHALL 通過過濾
- **AND** 當 `support_critical_angle` 設為 45 度或 90 度時，該點 SHALL 被剔除

#### Scenario: 陡峭懸空面依門檻決定去留
- **GIVEN** 一個支撐點所在表面的斜度為 60 度（`polar` 為 120 度）
- **WHEN** `support_critical_angle` 設為 20 度（通過上限為 70 度）
- **THEN** 該點 SHALL 通過過濾
- **AND** 當 `support_critical_angle` 設為 45 度（通過上限為 45 度）時，該點 SHALL 被剔除

#### Scenario: 法線朝上的面一律不通過
- **GIVEN** 一個支撐點所在表面朝上（`polar` 小於 90 度）
- **WHEN** `support_critical_angle` 設為 0 度
- **THEN** 該點 SHALL 被剔除，因為判定式要求 `polar >= PI / 2`

---

### Requirement: 判定條件須為單一事實來源

懸空角度的判定 SHALL 只有一份實作，置於 `src/libslic3r/SLA/SupportTree.hpp`，與 `SupportTreeConfig` 及 `overhang_angle_threshold` 欄位同住。

任何需要此判定的程式碼 SHALL 呼叫該函式，MUST NOT 就地重寫比較式。

該函式 SHALL 為純函式，輸入為 `polar`（弧度）與 `threshold`（弧度），輸出為布林值，MUST NOT 讀取任何全域狀態或組態物件。

#### Scenario: 全代碼庫僅存在一處判定式
- **WHEN** 在 `src/libslic3r` 中搜尋 `M_PI / 2.0 +` 與 `overhang_angle_threshold` 同時出現的比較式
- **THEN** 命中處 SHALL 僅有共用函式本身一處

#### Scenario: 函式不依賴組態物件
- **WHEN** 以任意 `polar` 與 `threshold` 數值對呼叫該函式
- **THEN** 回傳值 SHALL 只由這兩個輸入決定
- **AND** 呼叫該函式 MUST NOT 需要建構 `SupportTreeConfig` 或 `SLAPrintObjectConfig`

---

### Requirement: 角度過濾須於自動產點階段執行且僅執行一次

懸空角度過濾 SHALL 在 `slaposSupportPoints`（第 5 步）內執行，位置 SHALL 在 `move_on_mesh_surface()` 之後、`permanent_supports` 併入結果之前。

`slaposSupportTree`（第 6 步）MUST NOT 再對任何支撐點套用懸空角度門檻。

過濾 SHALL 無條件執行，MUST NOT 因 `support_critical_angle` 為特定值而短路跳過，以保證第 5 步輸出的點集與第 6 步採用的點集嚴格一致。

#### Scenario: 匯出的點清單不含角度不足的點
- **GIVEN** 一個模型含斜度超過通過上限的朝下表面
- **WHEN** 以 `--export-support-points` 匯出支撐點
- **THEN** 匯出的 JSON 中 MUST NOT 出現位於該表面上的自動產生點

#### Scenario: 匯出的點與長出的支撐柱在角度維度一致
- **GIVEN** 同一模型與同一組組態
- **WHEN** 先以 `--export-support-points` 取得清單，再以同組態執行完整支撐生成
- **THEN** 清單中 MUST NOT 存在任何「僅因懸空角度不足」而未長出支撐頭的點

#### Scenario: 門檻為 0 度時仍執行過濾
- **GIVEN** `support_critical_angle` 設為 0 度
- **WHEN** 執行自動產點
- **THEN** 系統 SHALL 仍執行過濾
- **AND** 法線朝上（`polar` 小於 90 度）的點 SHALL 被剔除

#### Scenario: 使用者攜帶的點不受第 5 步過濾影響
- **GIVEN** `permanent_supports` 中含一個位於陡峭表面的點
- **WHEN** 執行自動產點
- **THEN** 該點 SHALL 出現在第 5 步的輸出中，因為併入發生在過濾之後

---

### Requirement: 角度與法線容差須依支撐樹型分派

自動產點階段的角度值與法線計算容差 SHALL 依 `support_tree_type` 分派，MUST NOT 寫死任一組參數。

| `support_tree_type` | 角度來源 | 法線容差來源 |
|---|---|---|
| `Default` | `support_critical_angle` | `support_head_front_diameter / 2` |
| `Branching`、`Organic` | `branchingsupport_critical_angle` | `branchingsupport_head_front_diameter / 2` |

此分組 SHALL 複製 `make_support_cfg()` 的分組（該函式中 `Branching` 以 `[[fallthrough]]` 落入 `Organic`），MUST NOT 沿用 `head_diameter` 的分組（該處將 `Organic` 併給 `Default`）。兩者分組不同並非筆誤。

法線容差之所以必須一併分派，是因為第 6 步計算法線時使用 `SupportTreeConfig::head_front_radius_mm`，而該欄位在 `make_support_cfg()` 中同樣依樹型取自不同的直徑參數。兩個階段的容差不同 SHALL 被視為缺陷，即使判定函式相同亦然。

#### Scenario: 分支樹型套用分支參數
- **GIVEN** `support_tree_type` 為 `Branching`，且 `support_critical_angle` 與 `branchingsupport_critical_angle` 設為不同數值
- **WHEN** 執行自動產點
- **THEN** 過濾結果 SHALL 由 `branchingsupport_critical_angle` 決定

#### Scenario: Organic 樹型套用分支參數而非預設參數
- **GIVEN** `support_tree_type` 為 `Organic`，且 `support_critical_angle` 與 `branchingsupport_critical_angle` 設為不同數值
- **WHEN** 執行自動產點
- **THEN** 過濾結果 SHALL 由 `branchingsupport_critical_angle` 決定
- **AND** MUST NOT 由 `support_critical_angle` 決定，即使 `head_diameter` 的分派在此樹型下取自 `support_head_diameter`

#### Scenario: 預設樹型套用非前綴參數
- **GIVEN** `support_tree_type` 為 `Default`，且兩個角度參數設為不同數值
- **WHEN** 執行自動產點
- **THEN** 過濾結果 SHALL 由 `support_critical_angle` 決定

#### Scenario: 兩階段的法線容差相同
- **GIVEN** 任一支撐樹型與任一組支撐頭直徑設定
- **WHEN** 比較第 5 步過濾所用的法線容差與第 6 步 `head_front_radius_mm` 的數值
- **THEN** 兩者 SHALL 相等

---

### Requirement: 失效觸發須涵蓋自動產點步驟

`support_critical_angle` 與 `branchingsupport_critical_angle` SHALL 同時登記為 `slaposSupportPoints` 與 `slaposSupportTree` 的失效觸發鍵。

任一鍵變動時，`slaposSupportPoints` SHALL 被標記為失效並於下次執行時重算，MUST NOT 沿用先前的點集。

#### Scenario: 調整角度後支撐點重算
- **GIVEN** 已完成一次自動產點的列印物件
- **WHEN** `support_critical_angle` 被修改為不同數值
- **THEN** `slaposSupportPoints` SHALL 被標記為失效

#### Scenario: 分支樹角度鍵同樣觸發失效
- **GIVEN** 已完成一次自動產點的列印物件
- **WHEN** `branchingsupport_critical_angle` 被修改為不同數值
- **THEN** `slaposSupportPoints` SHALL 被標記為失效

---

### Requirement: 與 PhrozenOrca 的刻度分歧須明文宣告

本專案的懸空角度刻度 SHALL 與 PhrozenOrca 相反，且此分歧 SHALL 為刻意決定，MUST NOT 被視為缺陷。

PhrozenOrca 的判定式為「表面斜度 <= 設定值」，數值越大支撐越多；本專案為「表面斜度 <= 90 度 − 設定值」，數值越小支撐越多。兩者僅在設定值為 45 度時結果相同。

此分歧 SHALL 同時記錄於共用判定函式旁的程式碼註解與本規格中。任何跨專案的程式碼合併 MUST NOT 直接採用任一方的判定式，SHALL 由人工確認方向後再行處理。

#### Scenario: 45 度為唯一重合點
- **GIVEN** 兩專案的判定式與同一組表面法線
- **WHEN** 設定值為 45 度
- **THEN** 兩者的通過與否 SHALL 相同
- **AND** 當設定值為 45 度以外的任何值時，兩者的通過上限 SHALL 不同

#### Scenario: 註解中載明分歧
- **WHEN** 檢視共用判定函式的原始碼
- **THEN** 其註解 SHALL 明文指出與 PhrozenOrca 刻度相反
- **AND** SHALL 指明僅 45 度重合

---

### Requirement: 邊界內縮點的法線平滑效應須列為已知限制

支撐點取樣器將點內縮於島嶼輪廓內側 `head_radius`（`SampleConfigFactory.cpp`，預設 0.2 mm），而 `MeshNormals` 的 `get_normal()` 在點落於三角形邊或頂點的 `eps` 範圍內時會平均相鄰面的法線，其 `eps` 同為 `head_front_radius_mm`（預設 0.2 mm）。兩個半徑數值相同，因此邊界內縮點 SHALL 被視為落在 `get_normal()` 的平滑判定邊界上，其歸屬由 `SupportPoint::pos`（`Vec3f`）的浮點精度決定。

在完全水平朝下的面上，落入平滑範圍的邊界點其法線 SHALL 為平坦面法線與相鄰垂直側壁法線的平均，極角約為 135 度而非 180 度。此類點的通過條件因而退化為 `support_critical_angle <= 45 度`。

此行為 SHALL 被視為引擎既有物理行為，MUST NOT 被歸因於本變更。`slaposSupportTree`（第 6 步）在本變更前即以相同的 `normals()`、相同的 `eps` 與相同的判定式剔除同一批點；本變更僅使剔除提前於 `slaposSupportPoints` 顯現。

本變更 MUST NOT 為修正此效應而調整 `get_normal()` 的容差或取樣器的內縮距離。任何調整 SHALL 由獨立變更處理，因為更動容差會改變第 6 步全部支撐點的法線與最終支撐幾何。

若產品允許使用者將 `support_critical_angle` 設定為大於 45 度的值，此限制 SHALL 被視為未解決的風險：完全水平的懸空面將失去其整圈邊界的支撐點，且使用者無法從介面得知原因。

#### Scenario: 平坦懸空面在預設門檻下完整保留
- **GIVEN** 一個下表面完全水平的實體網格，自動產點共產生 N 個點
- **WHEN** `support_critical_angle` 設為 0 度或 45 度
- **THEN** 兩種設定下的點數 SHALL 皆為 N，MUST NOT 有任何點被剔除

#### Scenario: 平坦懸空面的邊界點在超過 45 度時被剔除
- **GIVEN** 同一網格，其中部分點位於距島嶼輪廓約 `head_radius` 處
- **WHEN** `support_critical_angle` 設為大於 45 度的值
- **THEN** 該批邊界點 SHALL 被剔除，因為其平滑後的極角約為 135 度
- **AND** 距輪廓較遠、取得真實面法線的內部點 SHALL 全數保留

#### Scenario: 第 5 步與第 6 步對同一批邊界點得出相同結論
- **GIVEN** 任一 `support_critical_angle` 設定值
- **WHEN** 比較 `slaposSupportPoints` 的過濾結果與 `slaposSupportTree` 對同一點集的角度判定
- **THEN** 兩者 SHALL 剔除完全相同的點，因為兩步使用相同的法線容差與相同的判定式

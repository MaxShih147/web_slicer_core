## Context

既有分類流程由 `classify_dental_model()` 協調，依序執行：

```
mesh
  → extract_model_features()
  → _compute_signals()
  → _get_drill_detection_plan()   ← 決定是否跳過導孔偵測
  → [條件式] detect_drill_holes() ← 最昂貴的步驟
  → _decide_model_type_with_details()
  → DentalModelType
```

`_decide_model_type_with_details()` 依 P0 → P_base → P2 → P3 → P5 優先順序決定 model_type。
P_base / P2 / P3 均在導孔偵測前確定結果；P5 是「導孔偵測執行後」的分支。

## Goals / Non-Goals

**Goals:**
- 在 `confirm_dental_model_type()` 中支援 early return：凡是確定目標類型「已不可能在後續分支成立」時，立即回傳 false，不執行導孔偵測
- 確保 `confirm(target) == (classify() == target)` 對所有類型、所有案例成立，無例外
- P_base 的 dental_model / u_shaped_dental_model 分流邏輯抽成共用 helper，避免 confirm 與分類器各自維護一份
- P5 fallback 沿用已計算的 features / signals，不重新呼叫 `classify_dental_model(mesh)` 從頭計算
- 新 API 端點只回傳 `confirmed` bool，不在 false 時揭露模型實際類型
- 既有 `classify_dental_model()` 及 `POST /api/v2/classify-model` 完全不受影響

**Non-Goals:**
- 不為 confirm 模式建立獨立的、可能與正式分類結果不一致的判斷規則
- 不處理各幾何特徵演算法本身的效能最佳化
- 不在 `confirmed=false` 時回傳 actual type

## Decisions

### D1：共用現有決策邏輯，不另建獨立規則

`confirm_dental_model_type()` 沿用 `_get_drill_detection_plan()` 的 skip reason 判斷，以及既有決策邏輯（P_base 透過共用 helper 確保一致），不引入任何只在 confirm 模式存在的閾值或判斷規則。

### D2：Early return 覆蓋範圍 — 基於代碼分析的實際結論

確認每種類型是否可能出現在 P5（`needs_drill=True` 時 `_decide_model_type_with_details()` 的分支）：

**dental_model / u_shaped_dental_model — 確認無法出現在 P5**

`_get_drill_detection_plan()` Skip 1 與 P5.2A 皆呼叫 `_is_one_sided_base_candidate()`，使用**完全相同的條件**（`base_model_size_score ≥ CANDIDATE_GROUP_MIN` AND `one_sided_flat_plane_score ≥ STRONG_SIGNAL_MIN`）：
- 若 Skip 1 命中 → P_base 分支，不進入 P5
- 若 Skip 1 未命中 → `_is_one_sided_base_candidate()` = false → P5.2A 也必定不命中

結論：dental_model / u_shaped_dental_model **無法出現在 P5**，needs_drill=True 時可直接回傳 false。

**intraoral_scan — 確認無法出現在 P5**

P5 內（5.1 / 5.2A–E / 5.3）不存在任何回傳 intraoral_scan 的分支。

結論：intraoral_scan **無法出現在 P5**，needs_drill=True 時可直接回傳 false。

**crown — 需執行 P5 後比較**

P5.2C 可在 L1 邊界區（12–18mm）回傳 crown，條件為 `crown_small_score > bridge_small_score`（無強信號門檻要求）。P2 skip 的門檻較高（`crown_small_score ≥ STRONG_SIGNAL_MIN`），因此存在 P2 未觸發但 P5.2C 仍可回傳 crown 的案例。為確保 `confirm(crown) == (classify() == crown)` 無例外，crown 在 needs_drill=True 時須執行完整 P5 流程後比較，不直接回傳 false。

**bridge / splint / surgical_guide — 需執行 P5 後比較**

這些類型均可在 P5 各子分支（5.1 / 5.2B–E / 5.3）中成立，needs_drill=True 時須執行導孔偵測並走完決策流程後比較。

**other — P0 確定，P5 中不可能出現**

`other` 只由 P0（PCA 失敗）分支產生。若已進入 P5（PCA 成功），`classify()` 必然不會回傳 `other`，confirm(other) 必然為 false，可直接回傳 false，不執行導孔偵測。

**各目標類型的完整行為表：**

| target | P0（PCA 失敗） | P_base skip | P2 skip | P3 skip | needs_drill=True |
|--------|:------------:|:-----------:|:-------:|:-------:|:----------------:|
| `dental_model` | false | 共用 helper 決定 | false | false | **false（不執行 drill）** |
| `u_shaped_dental_model` | false | 共用 helper 決定 | false | false | **false（不執行 drill）** |
| `crown` | false | false | true | false | 執行 drill → 比較結果 |
| `intraoral_scan` | false | false | false | true | **false（不執行 drill）** |
| `bridge` | false | false | false | false | 執行 drill → 比較結果 |
| `splint` | false | false | false | false | 執行 drill → 比較結果 |
| `surgical_guide` | false | false | false | false | 執行 drill → 比較結果 |
| `other` | **true** | false | false | false | **false（不執行 drill）** |

注：P0 欄位中 target=`other` 為 **true**（PCA 失敗時完整分類結果為 `other`）；其餘 target 在 P0 均為 false。

### D3：P_base 分流邏輯抽成共用 helper

P_base 的 dental_model / u_shaped_dental_model 分流公式（`u_shaped_model_score > dental_model_score`）同時需要在 `_decide_model_type_with_details()` 與 `confirm_dental_model_type()` 中使用。若各自維護一份，未來修改分流條件時容易產生 confirm 與正式分類不一致的 bug。

**決策：** 在 `model_classifier.py` 中新增私有 helper `_p_base_decide(sig: _ClassificationSignals) -> DentalModelType`，回傳 P_base 分支的決定，讓 `_decide_model_type_with_details()` 與 `confirm_dental_model_type()` 共用同一實作。

### D4：P5 fallback 不從頭重跑 pipeline

`confirm_dental_model_type()` 進入 P5 之前已完成：
1. `extract_model_features(mesh)` → `features`
2. `_compute_signals(features)` → `sig`
3. `_get_drill_detection_plan(features, sig)` → `needs_drill=True`

對於需要進入 P5 的目標類型（crown / bridge / splint / surgical_guide / other），confirm 函式應：
1. 沿用已有的 `features`，直接呼叫 `detect_drill_holes(mesh)` 並填入 `features.drill_*` 欄位（`drill_detection_ran=True`、`drill_detection_skip_reason=None`）
2. 呼叫 `_decide_model_type_with_details(features)` 取得最終 `final_type`
3. 回傳 `final_type == target`

**不呼叫** `classify_dental_model(mesh)`（會重新執行 feature extraction 與 signal calculation）。

### D5：target_type 透過 form field 傳遞

`POST /api/v2/confirm-model-type` 接受 `multipart/form-data`：
- `file`：STL 檔案（必填，與 classify-model 端點相同）
- `target_type`：目標類型字串，須為 `DentalModelType` 枚舉值之一（必填）

### D6：confirmed=false 時不揭露 actual type

API 回應只有 `data.confirmed`（bool）。若前端在 confirmed=false 時需要知道實際類型，應呼叫 `POST /api/v2/classify-model`，而非在 confirm 端點附加 actual type。理由：若端點需要回傳 actual type，在 P5 分支中必然也要執行完整分類，P_base/P2/P3 的 early return 效益便幾乎消失。

### D7：無效 target_type 視為 VALIDATION_ERROR

若 `target_type` 字串不在 DentalModelType 枚舉值之中，回傳 HTTP 400 `VALIDATION_ERROR`，與非 `.stl` 副檔名的處理方式相同。

## 一致性保證分析

`confirm(target) == (classify() == target)` 對全部八種類型無例外成立的根據：

| 分支 | 保證機制 |
|------|---------|
| P0 | 直接對比 `target == OTHER`，classify() 也回傳 OTHER，無歧義 |
| P_base | 共用 `_p_base_decide(sig)` helper，與正式分類路徑完全相同 |
| P2 | early return 條件直接對應 P2 輸出（`target == CROWN`），等價 |
| P3 | early return 條件直接對應 P3 輸出（`target == INTRAORAL_SCAN`），等價 |
| P5（crown/bridge/splint/surgical_guide/other） | 沿用相同 features，呼叫相同決策函式後比較，無歧義 |
| needs_drill=True 且 target=dental_model/u_shaped_dental_model/intraoral_scan/other | 代碼分析確認這四種類型無法出現在 P5（other 僅由 P0 產生），直接 false 與完整分類比較結果等價 |

## Risks / Trade-offs

- **P5 早期 false 依賴代碼結構不變**：dental_model、u_shaped_dental_model、intraoral_scan 的 early false 依賴 `_is_one_sided_base_candidate()` 在 Skip 1 與 P5.2A 中使用相同條件，以及 P5 無 intraoral_scan 分支這兩個結構性事實。若未來修改決策樹結構（例如在 P5 新增 intraoral_scan 分支），需重新評估這些 early false 是否仍正確。
- **P_base helper 需同步維護**：修改 P_base 分流邏輯時需確認 `_p_base_decide()` 已更新，confirm 與分類器才能保持一致。
- **P5 fallback 呼叫 `_decide_model_type_with_details()` 直接暴露私有 API**：`confirm_dental_model_type()` 與 `classify_dental_model()` 共用私有決策函式，任何對 `_decide_model_type_with_details()` 的簽章修改都需要同步確認 confirm 路徑。
- **crown P5 成本**：P2 未觸發的邊界區牙冠案例需執行完整導孔偵測，無法提前結束。此為確保一致性的必要成本。
- **初版校準門檻未變**：確認模式沿用現有 soft-score 閾值（屬初版估計值），確認結果的穩健性依賴同一組門檻的校準品質。

## Why

後端匯出給前端的支撐點清單，與引擎最終真正長出的支撐柱並不一致。使用者看得到支撐點，卻找不到對應的支撐柱，而且沒有任何錯誤訊息可循。

根因是過濾時機。支撐點在 `slaposSupportPoints`（第 5 步）產生，該步驟純粹以逐層島嶼與半島幾何取樣，**完全不涉及表面法線與傾斜角度**。懸空角度門檻 `support_critical_angle` 只在 `slaposSupportTree`（第 6 步）的長頭階段生效：`DefaultSupportTree.cpp` 的 `filterfn` 對角度不足的點直接 `return`，不長頭、不報錯、不留痕跡。

而 `--export-support-points` 依設計停在第 5 步（見已封存變更 `2026-08-30-per-point-support-sizing` 的決策 D3），**必然停在角度過濾之前**。因此匯出的清單必定夾帶一批下游會被靜默丟棄的點。

此外還有第二個缺口：目前匯入的點清單（`--import-support-points`）在第 6 步仍會被角度門檻重濾一次。使用者調整角度滑桿之後送回一份未編輯的舊清單，會有一整片點無聲消失。

本變更把角度過濾收斂到單一位置，讓「匯出的點」與「長出的柱」在角度這個維度上完全對齊。

## What Changes

### 過濾時機收斂至第 5 步

- 在 `slaposSupportPoints` 的 `move_on_mesh_surface()` 之後、`permanent_supports` 併入之前，新增一段懸空角度過濾（沿用 PhrozenOrca 的 Phase 3 命名）。該段以 `AABBMesh` 計算每點法線後套用角度門檻。第 5 步已持有 `emesh` 並已在 `move_on_mesh_surface()` 內讀取命中面法線，本變更不引入新的資料相依。
- 角度值與法線容差**必須依 `support_tree_type` 分派**（Default 走 `support_critical_angle` 與 `support_head_front_diameter`；Branching 走 `branchingsupport_*`）。PhrozenOrca 的對應實作寫死了非前綴鍵，此為已知缺陷，不予移植。

### 第 6 步全面豁免角度門檻

- **BREAKING（引擎行為）**：移除第 6 步的兩處角度閘門——`DefaultSupportTree.cpp` 的 `filterfn` 與 `SupportTreeUtils.hpp` 的 `optimize_pinhead_placement()`。兩者皆為初始長頭階段，不涉及後續的柱體路徑搜尋。
- 自動路徑不受影響：點在第 5 步已用同一門檻濾過，第 6 步再濾一次為無效操作。
- 匯入路徑（`PointsStatus::UserModified`）因此獲得完整豁免：**一份被使用者確認並送回的點清單，不再被偏好性參數二次剔除**。角度設定僅在「自動產點」階段生效。
- 連帶結論：PhrozenOrca 的 `sla-manual-support-angle-bypass` 規格**不需移植**，本變更為其超集。

### 手動點的行為邊界

- 手動點（`manual_add`）與所有匯入點一律豁免角度門檻。
- `normal_cutoff_angle`（150°，即法線落在正上方 30° 錐內才拒絕）與碰撞干涉檢查**維持現狀**，無條件適用於所有點。
- 近垂直面的手動點通過角度豁免後，方向會被 `bridge_slope` 夾住，**可能長出斜向插出的支撐柱**。此為使用者主動放置的結果，視為預期行為而非缺陷。

### 語意方向定調

- **維持 Web fork 現有語意**：通過條件為「表面與水平面的夾角 ≤ (90° − `support_critical_angle`)」，即數值越小支撐越多，0° 支撐所有朝下面、90° 只支撐完全水平朝下面。
- 此方向已與 fork 的 C++ tooltip 及 DS-online 前端四國語系文案（en / tw / cn / jp）一致，且與 Cura、Bambu Studio 等主流「從垂直量」的慣例同向。
- **不對齊 PhrozenOrca**。該專案的 `sla_support_passes_overhang_filter()` 採相反刻度（數值越大支撐越多），兩邊僅在 45° 答案相同。此刻意分歧須明文記錄，避免未來合併時被誤認為缺陷。
- 第 5 步與第 6 步的判定**必須呼叫同一個共用函式**，不得存在兩份公式。

### 交換格式語意調整

- JSON 的 `type` 欄位（`manual_add` / `island` / `slope`）在第 6 步不再影響任何行為，降級為**純資訊性標記**，僅供前端顯示與編輯使用。既有的「缺鍵即 `manual_add`」讀入規則不變。

### 失效觸發修正

- `support_critical_angle` 與 `branchingsupport_critical_angle` 目前僅登記於 `slaposSupportTree` 的失效清單。過濾移至第 5 步後，兩者須一併登記至 `slaposSupportPoints`，否則持久化路徑會沿用過期的點集。

## Capabilities

### New Capabilities

- `sla-overhang-threshold-semantics`：懸空角度門檻的方向定義與換算規則、單一事實來源（第 5 步與第 6 步共用同一判定函式）、依 `support_tree_type` 分派參數的規則、與 PhrozenOrca 相反刻度的刻意分歧記錄，以及過濾發生於管線中的唯一合法位置。

### Modified Capabilities

- `support-point-interchange`：`type` 欄位降級為純資訊性標記，引擎的支撐樹建構不再依其分派行為；並補述匯出清單已通過角度過濾、匯入清單不受角度門檻約束的往返合約。

## Impact

### 底層（`third_party/prusaslicer_fork`）

- `src/libslic3r/SLAPrintSteps.cpp` — 於 `support_points()` 新增 Phase 3 角度過濾；插入位置限定於 `move_on_mesh_surface()` 之後、`permanent_supports` 併入之前。
- `src/libslic3r/SLA/DefaultSupportTree.cpp` — 移除 `filterfn` 的角度閘門。
- `src/libslic3r/SLA/SupportTreeUtils.hpp` — 移除 `optimize_pinhead_placement()` 的角度閘門；新增供兩處共用的判定函式。
- `src/libslic3r/SLAPrint.cpp` — 將兩個 critical angle 鍵加入 `slaposSupportPoints` 的失效分支。

### 後端（`web_slicer_core/agent`）

- 不改動。`support_critical_angle` 已存在於 `SLAConfig` 且由 `generate_config_ini()` 全欄位輸出，匯出與長柱兩條路徑皆已正確傳遞。

### 前端（`D:\repos\DS-Online`）

- 本次不改動。前端目前每次產生支撐皆建立全新 job 且不回送點清單，角度滑桿行為維持正常。待前端實作逐點編輯後，需另立變更補上「調整角度後須重新產生支撐點」的提示。

### 不在本次範圍

- 其餘六種落單點成因（0.1 mm 去重、`normal_cutoff_angle`、頭部空間不足、低於底板、`ground_facing_only`、路徑搜尋失敗）不予處理。此與 PhrozenOrca 的既定取捨一致。
- PhrozenOrca 本身不改動，其相反刻度維持現狀。

### 行為變更與回歸風險

- **支撐點會微幅增加。** 0.1 mm 去重（`cluster()`）發生在角度過濾之前。過濾提前後，原本因「群代表角度不足而整群陣亡」的點群，會改由群內下一個點遞補成為代表並長出支撐柱。這不是純顯示層修正，而是實質的幾何結果變更，方向為支撐變多。
- **既有的逐層 SHA-256 回歸基準會失效**，須以本變更後的輸出重新基準化。Default 與 Branching 兩種樹型皆有各自的去重步驟，兩者都受影響；Web 端未設定樹型，實際走 Default。
- 近垂直面的匯入點在豁免後可能長出斜向支撐柱，視覺上比「完全不長」更突兀。此為已接受的取捨。

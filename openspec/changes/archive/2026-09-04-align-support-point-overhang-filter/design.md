## Context

### 現況管線

SLA 管線的第 5 步與第 6 步之間存在一道語意斷層：

```
slaposObjectSlice → slaposHollowing → slaposDrillHoles
        ↓
slaposSupportPoints（第 5 步）      ← 純逐層島嶼／半島取樣，不看法線、不看角度
        ↓                             --export-support-points 停在這裡
slaposSupportTree（第 6 步）        ← 角度門檻在這裡才生效，靜默丟點
        ↓
slaposPad → slaposSliceSupports
```

角度門檻 `support_critical_angle` 於 `make_support_cfg()`（`SLAPrint.cpp:74`）換算為 `SupportTreeConfig::overhang_angle_threshold`（弧度），僅供第 6 步使用。目前有兩處實作同一條件，兩份程式碼：

- `DefaultSupportTree.cpp:491` — 預設樹的 `add_pinheads()` / `filterfn`
- `SupportTreeUtils.hpp:474` — 分支樹的 `optimize_pinhead_placement()`

兩處的註解都已寫明「必須與另一份保持一致」，但語言層面沒有任何機制保證。

### 已具備、可直接沿用的條件

- **第 5 步已持有 `AABBMesh`**：`SLAPrintSteps.cpp:929` 有具名區域變數 `const AABBMesh& emesh = po.m_supportdata->input.emesh;`，且 `move_on_mesh_surface()` 本身已在讀取命中三角形法線。新增法線計算不引入新的資料相依。
- **第 5 步已有樹型分派**：`SLAPrintSteps.cpp:889` 的 `switch (cfg.support_tree_type)` 已依樹型選 `head_diameter`。角度與容差可沿用同一個分派點。
- **標頭已相通**：`SLAPrintSteps.hpp:10` 已 `#include <libslic3r/SLA/SupportTree.hpp>`。共用判定函式放在該標頭，第 5 步不需新增該項 include 即可取得。
- **容差本就相同**：`SLAPrint.cpp:63` 定義 `head_front_radius_mm = 0.5 * support_head_front_diameter`。第 5 步以 `support_head_front_diameter / 2` 為容差，與第 6 步的 `head_front_radius_mm` 數值相同。

### 約束

- 引擎為一次性子行程，第 5 步與第 6 步在同一次 `process()` 內執行，兩者看到的 `SLAPrintObjectConfig` 必然相同。
- 匯入路徑（`PointsStatus::UserModified`）在 `support_points()` 開頭即提前 `return`（`SLAPrintSteps.cpp:869`），永遠不會執行第 5 步的過濾。
- 後端 `agent` 不改動；`support_critical_angle` 已由 `generate_config_ini()` 全欄位輸出。

## Goals / Non-Goals

**Goals:**

- 讓角度過濾在整條管線中只發生一次，位置固定在第 5 步。
- 讓判定條件只有一份程式碼，第 5 步與第 6 步共用同一個函式。
- 讓匯出的支撐點清單在角度維度上與最終長出的支撐柱完全一致。
- 讓匯入的點清單完全不受角度門檻約束。
- 讓角度值與法線容差正確依 `support_tree_type` 分派。

**Non-Goals:**

- 不處理其餘六種落單點成因（0.1 mm 去重、`normal_cutoff_angle`、頭部空間不足、低於底板、`ground_facing_only`、路徑搜尋失敗）。
- 不改變 `support_critical_angle` 的數值語意方向。
- 不改變 `normal_cutoff_angle` 的門檻或適用範圍。
- 不修改 `--import-support-stl` 路徑（`has_imported_support()` 提前 return，本變更完全不觸及）。
- 不改動後端 `agent` 與前端 `DS-Online`。
- 不修改 PhrozenOrca。

## Decisions

### D1：共用判定函式置於 `SupportTree.hpp`，輸入為極角與弧度門檻

**決定**：新增一個純函式，與 `SupportTreeConfig` 及既有的 `ground_level()` 同住 `src/libslic3r/SLA/SupportTree.hpp`。

```cpp
// 表面朝下的程度是否足以放置支撐頭。
// polar     : 表面法線的球面極角（弧度）。0 = 法線正上方，PI = 法線正下方。
// threshold : SupportTreeConfig::overhang_angle_threshold（弧度）。
inline bool passes_overhang_filter(double polar, double threshold)
{
    return polar >= M_PI / 2.0 + threshold;
}
```

**為何放在 `SupportTree.hpp`**：

- 該標頭已定義 `SupportTreeConfig`，`overhang_angle_threshold` 就住在裡面。判定條件與它的擁有者同住，語意上最自然。
- 該標頭已被三個相關編譯單元涵蓋：`SLAPrintSteps.hpp:10` 直接 include、`DefaultSupportTree.hpp:22` 直接 include、`SupportTreeUtils.hpp` 透過 `SupportTreeBuilder.hpp` 間接取得。**三處皆不需為此新增 include**。
- 該標頭本身很輕（`AABBMesh`、`SupportPoint`、`Pad`），不會把 `Optimize/`、`Execution/` 等重量級相依拖進 `SLAPrintSteps.cpp`。

**為何輸入是 `polar` 而不是法線向量**：

第 6 步在判定之後立刻需要 `polar` 本身：

```cpp
polar = std::max(polar, PI - pt_slope);   // 飽和到坡度上限
```

若函式改收法線向量，第 6 步會被迫算兩次 `dir_to_spheric()`。收 `polar` 讓第 6 步原地替換，**逐位元保留今日的算術**，把改動風險壓到最低。

代價是第 5 步必須自行呼叫 `Slic3r::Geometry::dir_to_spheric()`，因此 `SLAPrintSteps.cpp` 需新增 `#include <libslic3r/Geometry.hpp>` 與 `#include <libslic3r/MeshNormals.hpp>`。

**數學換算（供規格與測試釘住）**：

`dir_to_spheric()`（`Geometry.hpp:545`）對單位法線計算 `polar = acos(n.z)`。設「表面與水平面的夾角」為 `s`（0 度 = 完全水平朝下，90 度 = 垂直牆面），則 `polar = PI - s`。代入判定式：

```
polar >= PI/2 + t
⟺  PI - s >= PI/2 + t
⟺  s <= PI/2 - t
```

換成角度：**通過條件為「表面斜度 <= 90 度 − support_critical_angle」**。

因此 `support_critical_angle = 0` 支撐所有朝下面、`= 90` 只支撐完全水平朝下面，**數值越小支撐越多**。此即 Web fork 既有語意，與 fork 的 C++ tooltip、DS-Online 四國語系文案，以及 Cura／Bambu Studio 的「從垂直量」慣例同向。

**與 PhrozenOrca 的刻意分歧**：該專案的 `sla_support_passes_overhang_filter()` 判定式為「表面斜度 <= 設定值」，刻度相反，兩邊僅在 45 度答案相同。此分歧必須以註解明文標示於本函式旁，避免未來合併時被誤認為缺陷。

**代數等價形式（僅供測試，不作為實作）**：由 `polar = acos(n.z)` 可得判定式等價於 `n.z <= -sin(t)`。此形式無反三角函數，適合寫成邊界測試的獨立對照，但**不得取代實作** —— `acos` 與 `sin` 在邊界的最後一個 ulp 未必一致。

### D2：Phase 3 的插入位置只有一個合法點

**決定**：新增的過濾段落必須夾在下列兩行之間（`SLAPrintSteps.cpp` 現行第 961 與 966 行）：

```cpp
SupportPoints support_points =
    move_on_mesh_surface(layer_support_points, emesh, allowed_move, cancel);

// ★ Phase 3 過濾插入於此 ★

support_points.insert(support_points.end(),
    permanent_supports.begin(), permanent_supports.end());
```

**為何不能更早**：法線必須對「已貼合到模型表面」的座標計算。`move_on_mesh_surface()` 之前的點還停留在取樣層的 z 高度上，可能離表面有一個層高的距離，`normals()` 的最近面投影會落到錯誤的三角形上。

**為何不能更晚**：`permanent_supports` 是使用者攜帶的點（來自 `ModelObject::sla_support_points`，經 `prepare_permanent_support_points()` 處理）。放在插入之後過濾會把使用者的點一併濾掉，直接違反本變更的核心決策。

**為何不能放到 `filter_support_points_by_modifiers()` 之後**：修飾體的 enforcer 語意是「這裡一定要有支撐」。若角度過濾發生在其後，enforcer 就無法救回被角度剔除的點。放在其前，enforcer 只在角度允許的點集上運作，語意較保守且與第 6 步今日的行為一致。（Web 端無修飾體 UI，此為純正確性考量。）

### D3：Phase 3 的參數分派必須跟隨 `support_tree_type`

**決定**：在 `support_points()` 內以**獨立的第二個 `switch (cfg.support_tree_type)`** 解出角度與容差，存入區域變數供 Phase 3 使用：

| 樹型 | 角度來源 | 法線容差來源 |
|------|---------|-------------|
| `Default` | `support_critical_angle` | `support_head_front_diameter / 2` |
| `Branching` / `Organic` | `branchingsupport_critical_angle` | `branchingsupport_head_front_diameter / 2` |

**不得與既有的 `config.head_diameter` switch（`SLAPrintSteps.cpp:889`）合併**，因為兩者的樹型分組不同：

```
config.head_diameter      Default + Organic  |  Branching
角度與法線容差             Default            |  Branching + Organic
```

本表的分組不是自由選擇，它必須複製 `make_support_cfg()`（`SLAPrint.cpp`）的分組，因為 Phase 3 必須與支撐樹得出相同判定，而支撐樹讀的正是該函式建出的組態。在那裡 `Branching` 以 `[[fallthrough]]` 落入 `Organic`，兩者一律取 `branchingsupport_` 前綴鍵——臨界角（決定 `overhang_angle_threshold`）與半個頭部直徑（決定 `head_front_radius_mm`，即支撐樹傳給 `normals()` 的容差）皆然。若照 `head_diameter` 的分組把 `Organic` 併給 `Default`，`Organic` 建置的第 5 步與第 6 步就會依據不同設定各自判定。

容差之所以必須跟著分派，是因為第 6 步的 `normals()` 用的是 `m_sm.cfg.head_front_radius_mm`，而該欄位在 `make_support_cfg()` 中同樣依樹型取自不同的 diameter（`SLAPrint.cpp:63` 對 `SLAPrint.cpp:92`）。兩步的容差不同會導致法線不同，進而讓「已通過 Phase 3 的點」在第 6 步被算出不同的角度 —— 即使兩步共用同一個判定函式也救不回來。

**PhrozenOrca 此處有缺陷，不予移植**：其 Phase 3 直接讀 `cfg.support_critical_angle.getFloat()`，未經樹型分派，分支樹模式下會套用錯誤的參數。

**不做短路**：`support_critical_angle` 為 0 時判定式退化為 `polar >= PI/2`，即「只要是朝下面就通過」。此時仍會剔除少數法線朝上的點，因此一律執行過濾，以保證第 5 步與第 6 步看到的點集嚴格一致。（PhrozenOrca 在此加了短路 guard，本變更不採用。）

### D4：第 6 步移除兩處閘門，且僅移除該兩行

**決定**：刪除下列兩處的角度判定，其餘邏輯一律不動。

**位置一 — `DefaultSupportTree.cpp:491`**（`add_pinheads()` 內的 `filterfn`）

```cpp
if (polar < PI - m_sm.cfg.normal_cutoff_angle) return;                 // 保留
if (polar < M_PI / 2.0 + m_sm.cfg.overhang_angle_threshold) return;    // ← 刪除
polar = std::max(polar, PI - pt_slope);                                // 保留
```

**位置二 — `SupportTreeUtils.hpp:474`**（`optimize_pinhead_placement()`）

```cpp
if (polar < PI - m.cfg.normal_cutoff_angle) return false;              // 保留
if (polar < M_PI / 2.0 + m.cfg.overhang_angle_threshold) return false; // ← 刪除
polar = std::max(polar, PI - m.cfg.bridge_slope);                      // 保留
```

**移除安全性論證**：

- `optimize_pinhead_placement()` 的呼叫者經追查僅有兩個：`SupportTreeUtils.hpp:559`（其自身的迷你柱遞迴）與 `SupportTreeUtils.hpp:584`（`calculate_pinhead_placement()`）。後者的唯一呼叫者是 `BranchingTreeSLA.cpp:417` 的 `create_branching_tree()`。**兩處皆屬初始長頭階段，不參與後續的橋接與路徑搜尋。**
- `filterfn` 同理，僅由 `add_pinheads()` 的 `execution::for_each` 呼叫。
- 移除後 `overhang_angle_threshold` 在第 6 步成為未讀欄位。**保留該欄位於 `SupportTreeConfig` 與 `make_support_cfg()`**，因為第 5 步仍需從同一條組態鏈取值；且保留欄位可讓 `invalidate_state_by_config_options()` 的既有對應維持完整。

**自動路徑的等價性**：點在第 5 步已用同一判定函式、同一容差、同一組態濾過，第 6 步的閘門對自動路徑必然為恆真，刪除不改變自動路徑的角度過濾結果。**但整體幾何結果仍會改變**，原因見 R1。

### D5：失效觸發須將兩個 critical angle 鍵補進 `slaposSupportPoints`

**決定**：`SLAPrint.cpp` 的 `invalidate_state_by_config_options()` 中，`support_critical_angle` 與 `branchingsupport_critical_angle` 目前只出現在歸屬 `slaposSupportTree` 的分支（第 1121 與 1138 行）。過濾移至第 5 步後，兩者必須**同時**觸發 `slaposSupportPoints`。

實作方式為在該函式既有的 `slaposSupportPoints` 分支中加入這兩個鍵；`slaposSupportTree` 的既有登記**保留不動**。

**【實作時的修正：「重複登記」的說法不成立】**

本節原先寫「重複登記無害且語意更明確」，該說法假設兩處登記會並存生效。實際上 `invalidate_state_by_config_options()` 是一條 **`else if` 鏈**，一個 `opt_key` 只會命中**第一個**符合的分支：

```
第 1104 行  slaposSupportPoints 分支   ← 兩個角度鍵在這裡命中
第 1131 行  slaposSupportTree   分支   ← 對這兩個鍵而言永遠到不了
```

因此 `slaposSupportTree` 分支中的那兩行（`SLAPrint.cpp:1145` 與 `1162`）在本變更後成為**永不執行的死碼**，並非「第二次登記」。

**功能仍然正確**，但正確性來自另一條路徑：`invalidate_step(slaposSupportPoints)` 會傳遞失效至 `slaposSupportTree`、`slaposPad`、`slaposSliceSupports`（`SLAPrint.cpp` 的 `invalidate_step()`）。第 6 步一定會重跑，靠的是步驟相依傳遞，不是那兩行登記。

**保留的理由因而改變**：不是「語意更明確」，而是（一）文件性質地標示支撐樹仍是這兩個設定的下游；（二）一旦有人移除上方的 `slaposSupportPoints` 分支，這兩行會重新變成活的，並退回到舊行為——那在過濾已移至第 5 步之後是錯的。兩處程式碼皆已加註此點（`SLAPrint.cpp:1136-1144` 與 `1162`）。

`else` 分支的 `assert(false)`（「All keys should be covered」）不受影響：兩個鍵都被前方分支涵蓋，不會落入該分支。

**對 Web 的影響為零**：後端每次呼叫都是全新的一次性行程，全部重算，不存在跨呼叫快取。此項純粹是 fork 自身的正確性修補，避免 GUI 路徑沿用過期的點集。

### D6：`type` 欄位降級為純資訊性標記

**決定**：第 6 步移除角度閘門後，`SupportPointType`（`manual_add` / `island` / `slope`）不再影響支撐樹建構的任何分支。交換格式中的 `type` 鍵**保留原樣**，但其角色降為前端顯示與編輯用的來源標記。

`SupportPointIO.hpp` 既有的讀入規則不變：缺 `type` 鍵即視為 `manual_add`；匯出時一律寫入實值。`SupportPoint::is_island()` 在支撐點產生器內的既有用途不受影響。

**連帶結論**：PhrozenOrca 的 `sla-manual-support-angle-bypass` 規格（僅豁免 `manual_add`）在本變更下成為冗餘，**不予移植**。本變更是其超集：所有進入第 6 步的點一律豁免。

## Data Flow

### 變更前

```
                 ┌─ 第 5 步 slaposSupportPoints ────────────────────┐
   模型 STL ────▶│ 島嶼取樣 → move_on_mesh_surface → 修飾體過濾     │
                 └──────────────┬──────────────────────────────────┘
                                │  N 個點（含角度不足者）
                 ┌──────────────▼─── --export-support-points ───────┐
                 │  匯出 JSON  ← 夾帶會被下游丟棄的點   ✗ 不一致    │
                 └─────────────────────────────────────────────────┘
                                │
                 ┌──────────────▼─ 第 6 步 slaposSupportTree ───────┐
                 │ 0.1mm 去重 → 算法線 → normal_cutoff             │
                 │            → ★角度過濾★ → 碰撞 → 長頭          │
                 └─────────────────────────────────────────────────┘

   匯入 JSON ─▶ UserModified ─▶ 直接進第 6 步 ─▶ ★角度再濾一次★  ✗ 二度剔除
```

### 變更後

```
                 ┌─ 第 5 步 slaposSupportPoints ────────────────────┐
   模型 STL ────▶│ 島嶼取樣                                         │
                 │    ↓                                             │
                 │ move_on_mesh_surface（貼合表面）                  │
                 │    ↓                                             │
                 │ ★ Phase 3：算法線 → passes_overhang_filter() ★   │
                 │    ↓                                             │
                 │ 併入 permanent_supports（不受過濾）               │
                 │    ↓                                             │
                 │ 修飾體過濾                                        │
                 └──────────────┬──────────────────────────────────┘
                                │  N' 個點（角度全部合格）
                 ┌──────────────▼─── --export-support-points ───────┐
                 │  匯出 JSON  ← 與最終支撐柱在角度維度一致   ✓     │
                 └─────────────────────────────────────────────────┘
                                │
                 ┌──────────────▼─ 第 6 步 slaposSupportTree ───────┐
                 │ 0.1mm 去重 → 算法線 → normal_cutoff             │
                 │            → 碰撞 → 長頭       （無角度閘門）    │
                 └─────────────────────────────────────────────────┘

   匯入 JSON ─▶ UserModified ─▶ 直接進第 6 步 ─▶ 無角度過濾   ✓ 完整豁免


        ┌────────────────────────────────────────────────┐
        │  passes_overhang_filter()   ← 單一事實來源      │
        │  src/libslic3r/SLA/SupportTree.hpp             │
        └──────┬─────────────────────────────────────────┘
               └─▶ 變更後唯一呼叫點：SLAPrintSteps.cpp 的 Phase 3
```

## 檔案變更清單

| 檔案 | 變更內容 |
|------|---------|
| `src/libslic3r/SLA/SupportTree.hpp` | 新增 `passes_overhang_filter()` 純函式，與 `SupportTreeConfig`、`ground_level()` 同住；旁附語意方向與 PhrozenOrca 分歧的註解。`overhang_angle_threshold` 欄位保留並加註唯一消費點。 |
| `src/libslic3r/SLAPrintSteps.cpp` | `support_points()` 的樹型 `switch` 增解角度與容差；於 `move_on_mesh_surface()` 與 `permanent_supports` 併入之間新增 Phase 3 過濾。新增 `#include <libslic3r/Geometry.hpp>` 與 `#include <libslic3r/MeshNormals.hpp>`。 |
| `src/libslic3r/SLA/DefaultSupportTree.cpp` | 刪除 `filterfn` 第 491 行的角度判定與其上方的說明註解區塊。 |
| `src/libslic3r/SLA/SupportTreeUtils.hpp` | 刪除 `optimize_pinhead_placement()` 第 474 行的角度判定與其上方的說明註解區塊。 |
| `src/libslic3r/SLAPrint.cpp` | `invalidate_state_by_config_options()` 的 `slaposSupportPoints` 分支加入 `support_critical_angle` 與 `branchingsupport_critical_angle`。 |
| `agent/`（後端） | 不改動。 |
| `DS-Online`（前端） | 不改動。 |

## Risks / Trade-offs

**[R1：支撐點微幅增加，逐層 SHA-256 回歸基準失效]**
0.1 mm 去重（預設樹的 `cluster()`，`DefaultSupportTree.cpp:405`；分支樹的 `non_duplicate_suppt_indices()`，`BranchingTreeSLA.cpp:404`）發生在角度過濾之前。過濾提前後，原本「群代表角度不足而整群陣亡」的點群，會改由群內下一個點遞補成為代表並長出支撐柱。
→ 這是實質的幾何結果變更，不是純顯示層修正，方向為**支撐變多**。既有的逐層 SHA-256 基準必須以本變更後的輸出重新基準化。兩種樹型皆受影響；Web 端未設定 `support_tree_type`，實際走 `Default`。

**【3.R.6 實測結果：本風險未觸發，逐層輸出零偏差】**

以階段三完成後的 `slicer-engine.exe`（建置於 2026-09-03 16:48，晚於全部原始碼修改）對階段 0 的兩個基準模型重跑完整切片，逐層 SHA-256 滾動值與階段 0 舊基準**逐位元完全相同**：

| 模型 | 層數 | `layers_sha256_all` | `usedMaterial` | `printTime` | 支撐點數 |
|------|-----|---------------------|---------------|-------------|---------|
| `U_overhang.obj` | 120（不變） | `8d0e183a9eb42007…`（與舊基準相同） | 0.969384（不變） | 1920.000004（不變） | 20（不變） |
| `frog_legs.obj` | 60（不變） | `ee449933c3931e05…`（與舊基準相同） | 5.215144（不變） | 975.000002（不變） | 172 → 167 |

**機制分析**：本風險的前提是「被角度剔除的點恰為某個去重群的代表，且該群另有成員可遞補」。去重半徑僅 **0.1 mm**（`DefaultSupportTree.cpp` 的 `cluster()`），而支撐點取樣的實際間距遠大於此，**含兩個以上成員的群極為罕見**。`frog_legs` 在第 5 步被剔除的 5 個點經實測全為孤立點，移除後無任何成員遞補，因此最終幾何完全未變。

**連帶結論**：

- 自動產點路徑的幾何輸出**零偏差**。本變更對這兩個模型而言是純粹的顯示與交換格式修正。
- **階段六（6.1）的「重新基準化」對這兩個模型不需要執行**——現有基準仍然有效，`verification-notes.md` 的數值不必更動。若日後改用其他模型，本風險的機制仍然成立，仍須逐案確認。
- 「輸出不變」本身也符合 D4 的等價性論證：Phase 3 與第 6 步使用同一判定式、同一容差，因此第 6 步的閘門對自動路徑本就恆真，刪除不改變自動路徑結果。

**【CLI 層級的閘門移除驗證（3.R.6 煙霧測試）】**

「輸出不變」無法單獨證明閘門確實已從執行檔中移除，故另以 `--import-support-points` 做直接驗證。測試點為 `U_overhang.obj` 上 5 個位於 `x = 0` 與 `x = 10` 垂直壁面的點（法線水平，`polar = 90` 度，距任何邊至少 0.5 mm）：

| 執行 | 組態 | 結果 |
|------|------|------|
| `walls90` | 5 個壁面點，`support_critical_angle = 90` | 120 層，`usedMaterial = 0.676368`，滾動雜湊 `377a865373ecd7d7…` |
| `walls00` | 同一份點清單，`support_critical_angle = 0` | 120 層，`usedMaterial = 0.676368`，滾動雜湊 `377a865373ecd7d7…` |
| A：`walls` + `pad_enable = 0` | 支撐開啟、無底座、角度 90 | 106 層，`usedMaterial = 0.356730` |
| B：對照組 | `supports_enable = 0`、無底座、角度 90 | 73 層，`usedMaterial = 0.285000` |

**判讀**：

1. `walls90` 與 `walls00` **逐位元相同**。若閘門仍在，角度 90 時通過條件為 `polar >= 180`，5 個點全數被剔除；角度 0 時通過條件為 `polar >= 90`，5 個點全數通過——兩次輸出必然不同。相同即證明第 6 步**完全不讀取角度**。
2. A 與 B 相差 **33 層與 0.071730 材料量**。多出的層位於模型底面之下（物件被抬升），只可能是支撐柱。證明垂直壁面點在角度 90 下**確實長出了支撐柱**，而非「兩次都因其他原因失敗」造成的假性相同。

兩項合起來，確認 `slicer-engine.exe` 執行檔層級已無角度閘門。

**[R2：近垂直面的匯入點可能長出斜向支撐柱]**
匯入點豁免角度後，`normal_cutoff_angle`（150 度，即法線落在正上方 30 度錐內才拒絕）不會擋下垂直牆面上的點（其 `polar = 90` 度）。該點的方向會被 `polar = std::max(polar, PI - pt_slope)` 夾到 135 度，若碰撞檢查通過就會長出一根斜插而出的柱子。
→ 視覺上比「完全不長」更突兀。此為使用者主動放置的結果，且 PhrozenOrca 已在其設計文件中明文接受同一取捨（「近水平面的手動點可能斜出或靜默失敗」）。本變更沿用該立場。

**[R3：第 5 步與第 6 步的法線計算呼叫形狀不同]**
第 5 步為全部點計算法線；第 6 步只為去重後的群代表計算（`normals()` 帶 `selected_points`）。兩者的網格、容差與演算法相同，同一個點的結果必然一致，但呼叫形狀不同。
→ 須以測試釘住「同一點在兩種呼叫形狀下取得相同法線」，避免日後有人改動其中一側的容差來源而無聲分岔。

**[R4：`support_critical_angle` 未經 `--load` 傳入時的失敗表徵改變]**
fork 的引擎預設為 90 度，代表「只支撐完全水平朝下面」。過濾提前後，未帶組態的 CLI 呼叫會在第 5 步就產出極少的點。
→ 這不是新行為（今日在第 6 步已是同樣結果），但失敗的表徵從「有點沒柱」變成「連點都沒有」。後端 `SLAConfig` 預設 45.0 且 `generate_config_ini()` 全欄位輸出，Web 路徑不受影響。

**[R5：`overhang_angle_threshold` 在第 6 步成為未讀欄位]**
移除兩處閘門後，該欄位不再被任何第 6 步程式碼讀取。
→ 保留欄位而非刪除，因為第 5 步仍需經同一條 `make_support_cfg()` 組態鏈取值。須在欄位旁加註「唯一消費點在 `SLAPrintSteps.cpp` 的 Phase 3」，否則日後清理未使用欄位時可能被誤刪。

**[R6：與 PhrozenOrca 的刻度分歧永久化]**
本變更明確選擇不對齊。同一參數名在兩個產品中意義相反，僅 45 度重合。
→ 分歧必須同時記錄於 `passes_overhang_filter()` 的註解與 `sla-overhang-threshold-semantics` 規格中。未來若合併程式碼，此處必須人工處理，不得直接採用任一方。

**[R7：邊界內縮點的法線被平滑，門檻超過 45 度時整圈邊界失去支撐]**

`MeshNormals` 的 `get_normal()` 在點落於三角形邊或頂點的 `eps` 範圍內時，會將相鄰面的法線平均後回傳。此處的 `eps` 即支撐樹傳入的 `head_front_radius_mm`，預設 0.2 mm。而支撐點取樣器的輪廓內縮距離（`SupportIslands/SampleConfigFactory.cpp:86`，`minimal_distance_from_outline = head_radius`）**同樣是 0.2 mm**。兩個 0.2 來自不同的參數鏈，卻是同一個數值。

```
取樣器把點放在離島嶼輪廓 0.2 mm 處
                    ↕   同一個數字
get_normal() 在 0.2 mm 內就開始平均鄰面法線
```

後果是**每一個邊界內縮點都精準落在 `squaredDistance < eps * eps` 的刀鋒上**，掉在哪一邊由 `SupportPoint::pos`（`Vec3f`）的 float32 尾數決定。實測 `U_overhang.obj` 的 20 個點中有 8 個落在內側：

| 座標（完整精度） | 距輪廓 | 距離平方 | `< 0.04` | 法線 | `polar` |
|---|---|---|---|---|---|
| `0.20000100135803223` | 0.2000010014 | `0.04000040054421561` | 否 | (0,0,−1) | 180.0 度 |
| `9.80000114440918` | 0.1999988556 | `0.03999954223763780` | 是 | (0.707,0,−0.707) | 135.0 度 |

兩點都「離輪廓 0.2 mm」，差距約 1.1 奈米。

平坦朝下面與垂直側壁平均後的極角恰為 135 度，通過條件 `135 >= 90 + t` 化簡為 `t <= 45`：

```
support_critical_angle ≤ 45 度  →  平坦懸空面的邊界內縮點全數保留
support_critical_angle > 45 度  →  平坦懸空面的邊界內縮點全數剔除（無中間地帶）
```

45 度是精確相等而非近似：`acos(-1/√2)` 與 `M_PI/2 + 45 * M_PI/180` 在 double 下**位元完全相同**（差值 0.0），這些點靠判定式的 `>=` 等號通過。`>=` 是既有語意（原式為 `if (polar < ...) return;`），本變更不更動。

→ **此為引擎既有物理行為，非本變更引入。** 第 6 步的 `add_pinheads()` 使用同一個 `normals()`、同一個 `eps`、同一個判定式，這 8 個點在變更前就已於第 6 步被剔除；Phase 3 只是讓剔除提早顯示。

→ **本變更採 (A) 方案：維持現狀，不調整 `normals()` 的容差。** 理由有三：(1) 更動 `eps` 會改變第 6 步全部點的法線，支撐結構全面變動，遠超「把角度過濾提前」的範圍，並使階段一的零偏差基線失去意義；(2) 正確的 `eps` 值需先釐清邊緣平均的原始設計意圖，屬另一場調查；(3) Web 端預設 45 度恰在安全側，不受影響。

→ **殘留風險**：滑桿範圍為 0–90 度，使用者主動調到 45 度以上時，平坦懸空面的整圈邊界會沒有支撐點，且變更後連點都不顯示，使用者失去「有球沒柱」這個唯一的可見線索。懸空面邊緣正是列印翹曲的高風險區。此限制已於 `sla-overhang-threshold-semantics` 規格明文記錄，**若產品決定允許 45 度以上的設定值，須另開變更處理**。

## 驗收方式的例外：`--import-support-stl` 以結構論證取代逐位元比對

任務 5.5 要求證明 `--import-support-stl` 路徑未受本變更影響，原訂做法是「輸出 MUST 與變更前逐位元相同」。**該做法已改為結構論證（方案乙），理由與依據如下。**

### 為何不做逐位元比對

階段 0 的基準只涵蓋自動產點的兩個模型（`U_overhang.obj`、`frog_legs.obj`），**沒有匯入支撐網格路徑的變更前基準**。要補這個基準，必須先把改動 stash 起來、重建變更前的引擎、量測、還原、再重建——引擎要編兩次，成本與本項的風險完全不成比例。

### 結構論證

本變更共動了五個引擎檔案。以下逐檔說明為何匯入支撐網格的路徑一行都碰不到。

#### (1) `SLAPrintSteps.cpp`：改動全數位於 `support_points()` 內部

| 改動 | 行號（現行） |
|------|------------|
| 新增 `#include <libslic3r/Geometry.hpp>` 與 `<libslic3r/MeshNormals.hpp>` | 16–17 |
| Phase 3 的樹型分派 switch | 904 起 |
| Phase 3 過濾區塊 | 1000 起 |

而 `support_points()` 的**第一道 guard** 就是匯入支撐網格的提前返回：

```cpp
// SLAPrintSteps.cpp:857
if (po.has_imported_support()) return;
```

**該行位於本變更所有改動之前。** 匯入支撐網格時，執行流程在第 857 行就離開了函式，Phase 3 的任何一行都不會被執行到。這不是「行為上剛好一樣」，而是**控制流上的物理隔離**。

#### (2) `DefaultSupportTree.cpp` 與 (3) `SupportTreeUtils.hpp`：第 6 步整段被跳過

這兩個檔案的改動（移除 `filterfn` 與 `optimize_pinhead_placement()` 內的角度閘門）只在原生支撐樹生成時才會被執行到。而 `support_tree()` 同樣有一道提前返回：

```cpp
// SLAPrintSteps.cpp:1094-1100
if (po.has_imported_support()) {
    if (!po.m_supportdata)
        po.m_supportdata = std::make_unique<SLAPrintObject::SupportData>(
            po.m_imported_support_its);
    po.m_supportdata->tree_mesh = TriangleMesh{po.m_imported_support_its};
    return;
}
```

匯入支撐網格時，第 6 步只是把匯入的網格掛上去就在第 1099 行返回，`DefaultSupportTree::execute()` 從未被呼叫。因此這兩個檔案的改動同樣不可達。

#### (4) `SLAPrint.cpp`：只影響失效標記，不影響輸出

`invalidate_state_by_config_options()` 的改動只是把兩個角度鍵改歸到 `slaposSupportPoints`。它決定的是「哪些步驟需要重跑」，不決定任何步驟算出什麼。對 Web 後端的一次性 CLI 行程而言，每次都是全新的 `SLAPrint` 物件、所有步驟本來就都要跑，該函式的回傳值不會改變任何輸出位元。

#### (5) `sla_per_point_geometry_tests.cpp`：測試檔，不進入產品二進位檔

其餘的 `has_imported_support()` guard（第 672、1168、1239 行）本變更一律未觸碰。

### 佐證

- 既有測試檔 `tests/sla_print/sla_import_support_tests.cpp` 覆蓋該路徑，於階段三 3.R.1（126 個案例）與階段四、五的完整測試執行中**持續全綠**。
- 3.R.6 的完整切片驗收顯示，連**自動產點**路徑的逐層 SHA-256 都與階段 0 基準逐位元相同；匯入支撐網格路徑執行的程式碼更少，不可能出現自動路徑沒有的偏差。

### 5.R.2 覆蓋核對的殘留：三個沒有 runtime 測試的 Scenario

兩份 spec 共 35 個 Scenario，32 個對應到自動化測試（28 個在 `sla_overhang_filter_tests.cpp`，3 個型別往返場景在既有的 `sla_support_point_io_tests.cpp`）。剩下 3 個**刻意沒有 runtime 測試**：

1. **「全代碼庫僅存在一處判定式」**（sla-overhang-threshold-semantics）——這是對**原始碼文字**的陳述，不是對執行期行為的陳述。以任務 3.4 的全代碼庫 grep 稽核保證。
2. **「註解中載明分歧」**（同上）——同樣是對原始碼文字的陳述。以任務 1.2 與 3.R.7 的 Code Review 保證。
3. **「門檻為 0 度時仍執行過濾」**（同上）——管線側無法從外部觀測：門檻 0 時過濾器不剔除任何點，「有執行」與「被短路跳過」的輸出完全相同。以任務 2.R.6 的 Code Review 確認 Phase 3 無任何短路 guard 來保證。**此為已知且已接受的缺口。**

前兩項不可能、也不應該以 runtime 測試表達。第三項可觀測性上不可能，除非引入僅供測試的探針。

### 此論證的界線

結構論證只保證「Phase 3 不會被執行」。若日後有人把過濾移到第 857 行之前，或在 `has_imported_support()` 為真的路徑上新增邏輯，本論證即刻失效，屆時必須改回逐位元比對。此點須在任何觸及 `support_points()` 前段的變更中重新檢查。

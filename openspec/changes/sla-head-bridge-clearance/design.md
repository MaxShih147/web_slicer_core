## Context

本設計以「`release/v1.0.6` 合入 `feat/sla-bracing-planar-topology` 之後」的程式為基底。下文的函式與行為都指 planar 版本；標明 `release/v1.0.6` 的行號只用來指認缺陷位置。動機與實測數據見 proposal。

**支撐樹的建造順序（`DefaultSupportTree::execute`）**

```
1 add_pinheads          長支撐頭
2 classify              分成朝地面 / 朝模型，朝地面者分群（每群最多 max_bridges_on_pillar 個）
3 routing_to_ground     (a) 每群中心頭長柱（循序）
                        (b) 同群其他頭：connect_to_nearpillar(中心柱)
                            → search_pillar_and_connect → create_ground_pillar（循序）
4 routing_to_model      朝模型的頭：search_pillar_and_connect → connect_to_ground
                            → connect_to_model_body → head.invalidate()
                        （execution::for_each，多執行緒）
5 interconnect_pillars  planar 的 BracingPlanner：斜撐規劃（循序）
6 輔助柱階段            planar 的 try_attach / attach / run_greedy_for
```

**現況缺陷與根因**

- 掛橋（`head`）、繞路段（`route`、`DiffBridge`）、自立柱與錨柱在建立時，只檢查模型碰撞（`bridge_mesh_distance` / `beam_mesh_hit`），不檢查彼此、柱與其他支撐頭。這是 A、C、反向 C 的來源。
- `search_pillar_and_connect()` 先呼叫 `connect_to_nearpillar()`（成功即已寫入 builder），再檢查 `pillar.r_start < head.r_back`，不合格就移除候選、繼續找，已建的橋不會撤回。這是 D 的來源（`release/v1.0.6` 的 `DefaultSupportTree.cpp:912-913`）。第 3 步失敗後又呼叫 `create_ground_pillar()`，同一頭因此可能同時有殘橋與自立柱。
- 第 3(b) 步掛到中心柱的路徑完全不檢查粗細。這是「粗頭掛細柱」的主要來源。
- `connect_to_nearpillar()` 在鎖外用 `bridgecount > max`（`:310`），鎖內用 `bridgecount < max`（`:374`），上限判斷不一致。
- 第 3(b) 步以 `m_pillar_index.query(中心頭接合點, 1)` 找「中心柱」。中心柱建立失敗時，查到的是任意一根最近的柱，不是中心柱。
- 第 4 步多執行緒直接寫入 builder 與 `m_pillar_index`：桿件與柱的 ID、陣列順序、`search_pillar_and_connect` 看到的柱集合都取決於排程。實測同一輸入 4 次輸出 4 種結果；`--threads 1` 則逐位元相同。
- planar 判定斜撐對非斜撐桿時，只要非斜撐桿的 `owner_a` / `owner_b` 是斜撐組的端柱（或同叢集）就整條豁免（`BracingPlanner::evaluate` 第 6 步的 `at_ends(...)`），因此漏掉共用柱、但碰撞點遠離柱的 B。
- planar 的 `attach()` 沒有「這對柱已有斜撐」的檢查。目前的呼叫順序不會觸發，但沒有任何機制擋住。`release/v1.0.6` 實測有完全相同的 8 根斜撐被建了兩次。

**限制**

- 模型碰撞查詢（`AABBMesh` 射線與 `beam_mesh_hit`）是主要耗時。第 4 步改單執行緒會讓 China-dragon1 由 1.7 秒增為 7.2 秒，不可接受。
- planar 的 `BracingPlanner` 是純幾何模組，並以 42 組幾何向量作為 DS-online 移植的標準。整合時 MUST NOT 讓它依賴網格或 builder。
- 本變更的新檢查一律使用 3D 判定；planar 既有的 2D 斜撐規則維持原樣。

## Goals / Non-Goals

**Goals:**

- 以一個純幾何模組集中處理掛橋、繞路段、自立柱、錨柱與支撐頭的 3D 間距判定，包含共用柱的 R 接點豁免。
- 第 3(b)、4 步改為「平行評估、依支撐頭 ID 循序提交」。這兩步的輸出逐位元可重現，且耗時增量不超過門檻。
- 消除 D 與粗頭掛細柱：每個支撐頭的路徑原子性地一次提交，所有規則在寫入前判定。
- 定義 0.2 mm → 0 mm → 保留並警告的降級狀態機，在任何情況下都不因本變更的規則而刪除支撐點。
- 以最小、可測的介面與 planar 整合：收窄 B 的豁免、斜撐柱對去重、輔助柱的反向 C。

**Non-Goals:**

- 不修改 planar 的 2D 斜撐規則（斜撐對斜撐、斜撐穿柱、共用柱 20° 夾角）、救援與保底邏輯。
- 不處理第 1、2、5 步以外其他階段原有的不確定性。
- 不檢查柱對柱的重疊、斜撐對柱底座、斜撐對支撐頭。
- 不加粗已建立的柱。
- 不修改 branching 樹與模型碰撞的判定方式，也不在本變更修改 DS-online。

## Decisions

### 決策 1：新增純幾何模組 `SLA/BridgeClearance.{hpp,cpp}`

命名空間 `Slic3r::sla::clearance`。模組不引用 `AABBMesh`、`SupportTreeBuilder`、`SupportableMesh`，只處理膠囊體幾何、索引與規則判定，由 `DefaultSupportTree` 的轉接層餵資料並寫回 builder。這樣它能像 `BracingPlanner` 一樣被單元測試直接驅動，日後也能逐一對應移植到 JS。

```cpp
namespace Slic3r::sla::clearance {

inline constexpr double SAFETY_CLEARANCE = 0.2;   // mm，與 planar 共用的唯一常數

enum class PrimKind : uint8_t { head_bar, route_bar, prop_bar, pillar, pinhead };

struct Capsule { Vec3d a, b; double r; };          // 線段 a-b 掃過半徑 r 的球

struct Prim {                                      // 一個已提交或待提交的幾何元件
    Capsule  cap;
    PrimKind kind;
    long     head_id   = -1;   // 屬於哪個支撐頭的路徑（pillar 為長出它的頭，可為 -1）
    long     pillar_a  = -1;   // 桿：起點所在柱；pillar：自身 id；pinhead：其承載柱
    long     pillar_b  = -1;   // 桿：終點所在柱
};

struct Contact {                                   // 一個違規接觸，供警告與量測
    Vec3d  p_new, p_old;
    double dist, required;
    PrimKind with;
    long   with_head, with_pillar;
};

class ClearanceIndex {                             // 決策 3
public:
    void insert(const Prim &p);                    // 只插入，不刪除
    // 對一組待提交元件，回傳所有違規接觸；空集合即通過
    std::vector<Contact> violations(const std::vector<Prim> &cand,
                                    double clearance,
                                    const PillarAxisFn &axis_of) const;
};

// 純函式
double capsule_dist(const Capsule &x, const Capsule &y);        // 軸線段 3D 最短距離
double joint_clipped_dist(const Capsule &x, const Capsule &y,
                          const std::vector<JointAxis> &shared); // 決策 4
}
```

`capsule_dist` 直接呼叫 planar 的 `bracing::geom::seg_seg_dist3d`（Ericson §5.1.9），不重寫第二份。`SAFETY_CLEARANCE` 由 planar 的 `PlannerConfig::safety_clearance` 預設值改為引用它，全專案只留一個常數。

**替代方案：** 把檢查直接寫在 `connect_to_nearpillar()` 等成員函式裡。缺點是無法脫離網格測試，四條建立路徑也會各自複製一份規則。因此不採用。

### 決策 2：膠囊體的對應與距離判定

每個元件都以「軸線段 + 半徑」的膠囊體表示：

| 元件 | 線段 | 半徑 |
|---|---|---|
| 掛橋（含自身短柱上方那根） | `startp → endp` | `r` |
| 繞路段 `Bridge` | `startp → endp` | `r` |
| 繞路段 `DiffBridge` | `startp → endp` | `max(r, end_r)`（保守） |
| 輔助柱橋 `prop` | `startp → endp` | `r` |
| 柱（含自立柱、錨柱、凍結柱、輔助柱） | 柱腳 `endpt` → 柱頂 `endpt + height·ẑ` | `max(r_start, r_end)` |
| 支撐頭 | `pos → junction_point()` | `r_back` |

判定式：

```
d = capsule_dist(x, y)               // 兩軸線段 3D 最短歐氏距離
通過 ⇔ d ≥ x.r + y.r + c             // c = 0.2（L0）或 0（L1），恰等於即通過
```

長度為 0 的線段（例如錨柱高度為 0）由 Ericson 演算法自然退化為點對線段。膠囊體在端點是半球，正好涵蓋桿件兩端的接合球，所以不另外建模接合點。支撐頭的實際形狀是錐體，以 `r_back` 的膠囊體近似：在接合點一側等於實際半徑，在接觸點一側偏大，屬於保守近似。柱的實際形狀可為錐形（`r_start ≠ r_end`），取較大者，同樣保守。柱底座（pedestal）不列入（Non-Goals）。

### 決策 3：3D 空間索引採 AABB R* 樹，只作粗篩

`ClearanceIndex` 內部是 `boost::geometry::index::rtree<std::pair<box3d, unsigned>, rstar<16, 4>>`，`box3d` 為 `model::box<model::point<double, 3, cs::cartesian>>`。

- 存入：元件膠囊體的 3D AABB，各軸外擴 `r`。
- 查詢：待判元件的 AABB 外擴 `r + c`，採 `intersects`。存入的框已含對方半徑，所以查詢框只需再加自身半徑與間隙，結果必定是所有可能違規者的超集合。
- 精判：對每個查詢結果，先套用決策 4 的豁免與 R 過濾，再以 `capsule_dist` 判定。
- 座標用 `double`，不經 `scale_()` 轉整數，所以沒有 planar `BoxIndex` 需要的向外取整問題。

索引只是粗篩，任何「通過」與「違規」都由 3D 精判決定，沒有任何判定以 2D 投影作結論。生命週期：`DefaultSupportTree` 的成員，從第 3(a) 步開始插入，到第 6 步結束；只插入不刪除，因為已提交的元件不會被撤回。第 4 步的階段一只讀取它的快照（決策 5）。

**替代方案：** 沿用 planar 的 2D `BoxIndex` 作粗篩。對細長的垂直柱，俯視框會把整根柱的高度範圍都算進來，在高密度模型中粗篩命中率差；而且容易被誤解成 2D 判定。另一個替代方案 `PointIndex` 是點索引，無法表示線段。因此都不採用。

### 決策 4：共用柱的 R 接點過濾與豁免矩陣

**共用柱的判斷一律以 ID 比對，不以幾何推斷。** 元件 x、y 的「柱集合」：

- 桿：`{pillar_a, pillar_b}` 去掉 -1。
- 柱：`{自身 id}`。
- 支撐頭：`{承載柱}`，也就是它直接坐在上面的柱，或它的掛橋終點柱。

兩者柱集合的交集 S 非空時即為共用柱。

**完全豁免（不判定）：**

- 同一支撐頭路徑內的元件彼此之間，例如掛橋與自身短柱、繞路段與其終點柱、支撐頭與自己的第一根桿。
- 桿對其兩端柱本身。
- 支撐頭對其承載柱本身。

**R 過濾（S 非空的其餘情況）：** 對每根共用柱 P ∈ S：

```
R_P = r_P + x.r + y.r + 0.2        // r_P = max(P.r_start, P.r_end)；固定用 SAFETY_CLEARANCE，L1（c = 0）也不縮小
```

把 x、y 各自位於「以 P 軸心為中心、半徑 R_P 的鉛直圓柱」內的部分剪掉，再對剩下的部分做 3D 判定：

```
對線段 s(t) = a + t(b − a)，t ∈ [0,1]：
  解 |s_xy(t) − P_xy|² = R_P²（t 的二次式），得圓柱內的參數區間 [t0, t1] ∩ [0,1]
  有多根共用柱時，逐一從 [0,1] 扣除各自的區間（區間差集）
  剩餘區間各自形成子線段（至多 3 段）
joint_clipped_dist = 所有子線段配對的 capsule_dist 最小值；任一方被剪光則視為通過
```

鉛直圓柱不設 Z 上下限的理由：共用 P 的桿必有一端落在 P 的軸線上，而直線段與鉛直線至多相交一次，所以桿在圓柱內的部分必定就是它接到 P 的那一端附近，不會在別的高度又穿回 P 附近。若 `|b_xy − a_xy|² < ε_len`（幾乎鉛直的桿），整段在或不在圓柱內，二次式退化，以端點判定。

`R_P` 隨各元件的實際半徑變化。預設尺寸（`r_P = r = 0.5`）下 `R = 1.7 mm`，相當於從同一點出發的兩桿須張開約 41°。實測 02.stl（墊高 10 mm、密度 400）5307 對共用柱桿對，有 17 對在 R 外仍違規。

**規則矩陣（新元件 × 已提交元件）：**

| 新 \ 舊 | 掛橋/繞路/prop | 柱 | 支撐頭 | 斜撐 |
|---|---|---|---|---|
| 掛橋/繞路段 | A：判定 | C：判定 | C：判定 | 不會發生（斜撐較晚建） |
| 柱（自立、錨、輔助） | 反向 C：判定 | 不判定（Non-Goals） | 判定 | 輔助柱：交由 planar |
| 斜撐（planar） | B：判定（決策 9 的收窄豁免） | planar 2D 規則 | 不判定（Open Questions） | planar 2D 規則 |

### 決策 5：兩階段排程（第 3(b) 步與第 4 步）

```
       ┌──────────── 快照 S0：builder + ClearanceIndex + 柱索引（本步開始時）
       │
階段一 │  execution::for_each（多執行緒），每個支撐頭 h 獨立：
       │    plans[h] = plan_routes(h, S0)      // 純計算，不寫入任何共享狀態
       │    → 依舊流程的優先順序，列出模型碰撞可行的候選 RoutePlan
       ▼
階段二   for h in 支撐頭 ID 由小到大（單執行緒）：
           state = degrade_and_commit(h, plans[h])   // 決策 6
           commit 時：寫入 builder、ClearanceIndex、柱索引；ID 依提交順序配發
```

**RoutePlan** 是一個支撐頭完整路徑的元件清單，提交前不觸碰 builder：

```cpp
struct RoutePlan {
    enum Kind : uint8_t { to_pillar, own_pillar, ground_route, model_anchor } kind;
    long   target_pillar = -1;          // to_pillar：目標柱
    std::vector<Prim> prims;            // 要新增的桿、短柱、新柱、錨頭（膠囊體）
    BuildRecipe recipe;                 // 提交時重放的 builder 呼叫（含 BridgeKind、owner、底座）
};                                      // 候選依清單順序嘗試：同類依距離排序，平手比柱 ID
```

現有函式拆成「規劃」與「提交」兩半，規劃半部只讀快照：

| 現有函式 | 規劃 | 提交 |
|---|---|---|
| `connect_to_nearpillar` | `plan_to_pillar(h, P)` | `commit(plan)` 依 recipe 重放 `add_bridge_to_pillar` / `add_pillar` + `add_bridge_between` |
| `search_pillar_and_connect` | 候選柱依（柱腳距離, 柱 ID）排序，逐一 `plan_to_pillar`，保留前 K 個可行者 | 同上 |
| `create_ground_pillar`（含 `search_widening_path`、零墊高修正橋） | `plan_ground_pillar` | 重放 `add_diffbridge` / `add_bridge(route)` / `add_pillar` / `add_pillar_base` / `own_*` |
| `connect_to_ground`、`search_ground_route` | `plan_ground_route`（優化器已 `seed(0)`，結果固定） | 同上 |
| `connect_to_model_body` | `plan_model_anchor` | 重放 `add_pillar` / `add_anchor` |

**階段一的計算範圍**，為了控制耗時，與舊流程「第一個成功就停」的成本相當：

- 一律計算 to_pillar 候選，最多保留 K 個模型碰撞可行者（K 為引擎內常數，定案為 4；初值 8，見 Open Questions 3）。
- 只有在沒有任何可行 to_pillar 候選時，才計算 ground_route / own_pillar / model_anchor。這和舊流程走到這一步的條件相同。
- 第 3(b) 步的候選順序：中心柱 → 其他柱（依距離）→ own_pillar。第 4 步：柱（依距離）→ ground_route → model_anchor。

**階段二的重算**：若某頭在 L0 下所有階段一候選都因間距或即時狀態（決策 8 的硬規則）失敗，就以「當下最新狀態」重算一次 `plan_routes`。這次會看得到前面剛提交的柱，並補算階段一略過的 ground_route / own_pillar / model_anchor。每頭至多重算一次，重算在單執行緒中進行。為了不讓重算的繞路搜尋在單執行緒中排隊，階段一先預判：掛柱候選對本步開始時的 `ClearanceIndex` 已全部違規的支撐頭，必然會重算（已提交的只增不減），它的退路就在階段一平行算好，但先不列入候選，等重算時才列入。選路順序與結果不變（Task 4.10：China-dragon1 第 4 步重算由 Task 3 的 24 次增為 37 次，耗時超過門檻後加入）。

**確定性的論證**：階段一的輸入是不可變快照，各頭結果存在以頭 ID 為索引的陣列，不受排程影響。階段二的走訪順序固定，重算只讀取當下狀態，而當下狀態只由更小 ID 的提交決定。所有排序都有明確的平手規則（距離相同比柱 ID）。builder 的 ID 與陣列順序依提交順序產生。因此第 3(b)、4 步的輸出與執行緒數無關。`beam_mesh_hit` 內部的平行取樣取的是最小值，與順序無關，不影響此論證。繞路的方向搜尋（`sla::plan_ground_detour`，基因演算法）靠 `seed(0)` 得到固定結果，前提是每個搜尋獨占自己的 NLopt 亂數狀態：NLopt 2.5 只在第一次 configure 偵測 thread-local，重新 configure 時 `THREADLOCAL` 會變成空的，亂數狀態就成為整個行程共用，因此 `deps/+NLopt` 在 MSVC 下明確指定 `__declspec(thread)`；階段一每個支撐頭的規劃包在 `tbb::this_task_arena::isolate` 中，執行緒在搜尋內等待平行的網格測試時，不會插入另一個頭的搜尋。（曾試過把搜尋改為循序，China-dragon1 第 3、4 步升到 7165.5 ms，不採用。）

**第 3(a) 步**（中心柱）維持循序、依群順序，但改為直接記錄每群中心柱的 ID，取代 `m_pillar_index.query(..., 1)`；中心柱建立失敗的群，其他頭的候選清單不含中心柱。中心柱維持原位建立，不進降級邏輯。它是整群的受力主幹，不因零點幾毫米的間隙差而移位。此時 `ClearanceIndex` 中已有所有支撐頭（決策 7），所以建立後以 c = 0.2 查一次中心柱對支撐頭的違規：長出它的支撐頭與被碰支撐頭本身就過近者屬原生過密，只計數；其餘每一處寫一行 info log `centroid_pillar_clearance_recorded pillar=<id> head=<id> dist=<d> required=<r> at (x,y,z) with=<kind>`（`with` 為被碰元件的種類，Task 4.11 加入），視為已記錄的邊界（2026-10-19 裁決）。

**替代方案：** 第 4 步直接改單執行緒。實測重模型整體慢 50%～100%，不採用。另一個替代方案是全域規劃（先收集所有頭的候選再排序）。新柱與繞路會改變候選集合，形成遞迴依賴，不採用。

### 決策 6：降級狀態機

每個支撐頭在階段二執行以下狀態機：

```
            ┌─────────────────────────────────────────────────┐
            ▼                                                 │
 [L0: c=0.2] ──逐一驗證候選──▶ 有通過者 ──▶ COMMIT(L0)        │
     │ 全部失敗                                                │
     ├─ 尚未重算 ──▶ 以最新狀態重算 plans[h] ───────────────────┘
     │ 已重算
     ▼
 [L1: c=0] ──逐一驗證候選──▶ 有通過者 ──▶ COMMIT(L1)，記 info log
     │ 全部失敗
     ▼
 [L2: RETAIN] ── 取「保底候選」 ──▶ COMMIT(L2)，記 WARNING 與違規接觸
     │ 沒有任何保底候選
     ▼
 [NONE] ── 舊行為：與現行相同的失敗處理（見 Open Questions 1）
```

- **驗證**一個候選 = 先檢查硬規則（決策 8），再以當前層級的 c 呼叫 `ClearanceIndex::violations(plan.prims, c)`。候選順序即決策 5 的優先順序，所以「次佳柱 → 繞路 → 錨在模型上 / 長柱到地面」自然成立。
- **保底候選** = 重算後的候選清單中，第一個通過所有硬規則者。這就是舊流程（在加上一頭一橋與粗細規則之後）會選的路徑。L2 不放寬硬規則。
- **L2 的紀錄**：log 寫一行 `WARNING: fallback_intersection_retained head=<id> kind=<plan.kind> contacts=<n> at (x,y,z)...`（`BOOST_LOG_TRIVIAL(warning)`），並把該頭與 `Contact` 清單加進匯出（決策 10）。
- L1 只記 info log 與量測計數，不寫入匯出。
- 斜撐不參與此狀態機。planar 對違規斜撐的處理維持「不建該根桿」。
- **實作補充（Task 4）**：
  - 選擇器是純函式 `select_route(cands, index, axis_of, hard_ok, recompute)`（`RoutePlan.{hpp,cpp}`）。`hard_ok` 呼叫 `hard_rules_ok()`，它是掛橋上限與粗細的唯一比較處。
  - L1、L2 紀錄的接觸，一律是選中路徑在 L0（c = 0.2）下的全部接觸，每筆的 `required` 為 `r1 + r2 + 0.2`。這樣 L0 判定下的每一處剩餘違規都能在紀錄中找到。決策 10 匯出的 `required`（`r1 + r2`）由 Task 6 從同一筆紀錄換算。
  - L1 的 log 為 `clearance_relaxed head=<id> kind=<route> contacts=<n> at (x,y,z) ...`（info）。生成結束的摘要為 `Default support tree: head route clearance: L1 <n>, L2 <n>, none <n>, centre pillar contacts recorded <n>, support point spacing <n>`。
  - 支撐頭的承載柱在分類時還不知道，所以支撐頭先以「無承載柱」插入索引；提交路徑時以 `ClearanceIndex::set_carrier()` 補上（坐在其上的柱，否則掛橋終點柱，與 support-tree 匯出相同）。只改 ID，不改膠囊體，也不刪除元件。
  - 中心柱的判定涵蓋其整條規劃（零墊高修正橋、加寬段與柱），原生過密只適用於柱對支撐頭。紀錄與 log 同時存入 `ClearanceReport`，由 `DefaultSupportTree::execute()` 的選填參數交給呼叫端。

### 決策 7：反向 C 的落實點

所有會長出新柱的地方，都必須先把柱的膠囊體與其附帶的桿放進 RoutePlan / 待判清單，通過 `violations()` 才能提交：

- 第 3(b) 步的 own_pillar，以及第 4 步的 ground_route 與 model_anchor：屬於 RoutePlan，自動經過決策 6。
- 第 6 步輔助柱：planar 在 `try_attach()` 之前，由轉接層以注入的 `ObstacleClearFn` 判定候選輔助柱（柱膠囊體 + prop 桿）對 `ClearanceIndex` 是否通過（c = 0.2）。不通過的角度視為不可放置，與現行「垂直路徑不通」同等處理。輔助柱不降級，因為它不承載支撐頭，放不下就不放。
- 第 3(a) 步的中心柱：建立時插入索引供後續判定。此時沒有掛橋可被刺穿，但可能貼近支撐頭；依決策 5，只寫 `centroid_pillar_clearance_recorded` log，不降級、不移位。
- 凍結柱（`--prior-supports`）：以柱膠囊體插入索引。它們的舊桿沒有資料，列為既有限制。

### 決策 8：硬規則（任何層級都不放寬）與 D、粗細、上限的修正

驗證任何候選時，先檢查以下規則；不滿足即視為該候選失敗，不會進入間距判定：

1. **一頭一路徑**：一個支撐頭只提交一個 RoutePlan，提交是原子的：要嘛整個寫入，要嘛完全不寫。因此不會留下殘橋，也不會同時有掛橋與自立柱（D 與其變形）。
2. **粗細**：to_pillar 候選須 `P.r_start ≥ h.r_back`。第 3(b) 步掛中心柱同樣適用。這是靜態條件，在階段一就過濾。
3. **掛橋上限**：以即時狀態判定 `bridgecount(P) < max_bridges_on_pillar`，取代 `:310` / `:374` 的不一致寫法。只在階段二判定，因為它依賴更早的提交。
4. 既有的模型碰撞、`minz`（橋端離地下限）與 `max_bridge_length` 條件，照舊在階段一判定。

### 決策 9：與 planar 的整合介面

1. **收窄 B 的豁免。** `BracingPlanner::evaluate` 第 6 步，原本是「`at_ends(o.owner_a) || at_ends(o.owner_b)` 即 `continue`」，改為：若斜撐組端柱（含叢集成員）與障礙桿的柱集合有交集，就以 `clearance::joint_clipped_dist(bar, o.seg, shared)` 取代 `too_near` 的距離判定；沒有交集時維持原判定。共用柱的 `JointAxis` 由 planner 自己的 `PillarGeom` 提供，所以 planner 仍是純幾何模組。救援與保底模式對斜撐桿的逐桿 3D 判定不變。
2. **斜撐柱對去重。** `BracingPlanner::attach()` 開頭加入 `built_pair(a, b)` 檢查，命中即回傳新原因 `Reason::duplicate_pair`，不建立。`accept()` 加上 debug assert：不得對已有斜撐的柱對再接受。`reason_name()` 新增 `"duplicate_pair"`。新增原因值是擴充，既有向量不受影響。
3. **輔助柱的反向 C。** `try_attach()` 不變；由 `DefaultSupportTree` 在呼叫它之前先做決策 7 的檢查。`BracingPlanner` 不感知 `ClearanceIndex`。
4. **共用常數。** `PlannerConfig::safety_clearance` 預設值改為 `clearance::SAFETY_CLEARANCE`。
5. **向量。** 在 `tests/data/sla_bracing_vectors/` 新增：共用柱但碰撞點在 R 外（拒絕）、碰撞點在 R 內（接受）、`attach` 重複柱對（`duplicate_pair`）；並更新 `MANIFEST.sha256`。既有 42 組向量的期望值不變，只有「共用柱的掛橋豁免」對應的向量需要確認仍落在 R 內。

### 決策 10：匯出與 log 格式

support-tree 維持 `version: 2`，新增選填的頂層陣列 `warnings`。沒有警告時不寫出這個陣列：

```json
"warnings": [
  {"code": "fallback_intersection_retained",
   "head": 17,
   "route": "to_pillar",
   "contacts": [
     {"pos": [x, y, z], "with": "head_bar", "dist": 0.41, "required": 1.0}
   ]}
]
```

`head` 是匯出後的 head 索引（與 `heads[]` 一致）。`with` 取值：`head_bar`、`route_bar`、`prop_bar`、`pillar`、`pinhead`。`required` 為 `r1 + r2`，因為 L2 是在 L1（c = 0）也失敗之後才發生。讀取端遇到未知欄位應忽略；agent 原樣轉送。

### 決策 11：量測與驗收工具

把探索期間的 Python 檢查腳本（A / B / C / D / 重複斜撐 / 粗頭細柱 / 共用柱 R 過濾）正式化為 C++，放在 `tests/sla_print/`，與 planar 的 `sla_bracing_metrics` 並列，直接讀 builder（有 `kind` 與 owner，不必像腳本那樣從匯出順序推斷型態）。輸出以下計數：A、B、C、反向 C、D、重複柱對、粗頭細柱、L1 次數、L2 次數、NONE 次數、柱數、桿數，以及第 3(b)、4 步各自的耗時。確定性測試在同一輸入下以預設執行緒數跑 N 次、再以 `--threads 1` 跑一次，比對第 3(b)、4 步產生的 head / pillar / bridge 記錄完全相同。

## Risks / Trade-offs

- [階段一看不到同一輪中更小 ID 剛提交的柱，部分支撐頭會接到較遠的柱或自立新柱，柱數可能上升] → 只在候選全滅時重算，以控制成本；量測工具記錄柱數與桿數相對基準線的變化，供判讀。
- [高密度模型中重算比例偏高，階段二的單執行緒部分變長，可能超出 max(10%, 50 ms)] → K 為內部常數，可依量測調整；必要時讓重算只補算缺少的候選類型。以 China-dragon1、Pikachu 作為效能驗收素材。
- [粗細規則讓第 3(b) 步原本掛中心柱的粗頭改走退路，自立柱增加] → 這是刻意的力學修正。以柱數趨勢監看，不設門檻。
- [L2 保留的交錯仍存在於輸出中] → 以 `warnings` 匯出並計數；參考模型的 L2 次數列為驗收觀察項，門檻在 specs 定義。
- [其他階段原有的不確定性，可能讓整棵樹的逐位元比對仍然失敗，掩蓋本變更的確定性] → 確定性測試只比對第 3(b)、4 步產生的記錄；整棵樹的比對另行記錄，不作為本變更的門檻。
- [鉛直無限圓柱的 R 過濾，依賴「共用柱的桿必有一端在柱軸上」] → 這由建立路徑保證（掛橋終點在柱軸、斜撐端點在柱軸）；以 debug assert 檢查共用柱桿至少一端與柱軸的俯視距離 < ε。
- [支撐頭以 `r_back` 膠囊體近似，柱以較大半徑近似] → 偏保守，可能多擋一些候選；由降級階梯吸收，不會因此刪除支撐點。
- [planar 分支不含 `02f19db4e` 及其後的 v1.0.6 commit，合併有衝突] → `interconnect_pillars()` 採 planar 版本；其餘檔案逐一檢查，並在合併後先跑 planar 的向量與 IO 測試，確認基底正確，再開始本變更。
- [`02f19db4e` 的提交說明提到前端 `supportInterconnect.js` 鏡像了「一根柱只主動連一個鄰居」，合入 planar 後前後端規則不一致] → 由 DS-online 的後續移植變更處理；本變更的 Impact 已列出。

## Known Limitations

Task 4 的 `/code-review`（4.11）提出、決定不在本變更處理的事項。驗收素材上都沒有造成未記錄的違規。

1. **被刪除的支撐頭留在索引中。** 第 4 步找不到路徑的支撐頭會被刪除（`invalidate()`），但它在分類時插入 `ClearanceIndex` 的膠囊體不會移除（索引只插入不刪除）。ID 較大的支撐頭仍會避開這個已經不存在的頭，可能因此重算或降級，紀錄中的 `with_head` 也可能指向它。驗收素材上，被刪除的頭為 China-dragon1 3 個、Pikachu 2 個，與基準線相同。要修正需要讓索引能停用元件，樹可能改變。
2. **第 3(b)、4 步的原生過密不排除於降級。** spec 的原生過密（柱由某支撐頭長出，而該頭與被碰支撐頭本身就過近）只在第 3(a) 步的中心柱排除並計數。第 3(b)、4 步新長的柱碰到這類支撐頭時，照常走降級，並記成 L1 或 L2。因此這些接觸都有紀錄，但 L2 次數包含了支撐點間距本身造成的部分（mixed 案例每例 L2 39～57 次）。要排除需修改 spec 的降級定義。
3. **承載柱延後綁定。** 支撐頭在分類時不知道承載柱，要等它的路徑提交後才以 `set_carrier()` 補上。在此之前，通往它將來承載柱的桿會把它整根判定，不做 R 剪除，結果偏保守：ID 較小的頭可能因此降級，且這筆紀錄在最終的樹中已不構成違規。不預先指定承載柱，因為支撐頭不一定掛到預期的柱，預先指定會漏判。
4. **中心柱紀錄可能多報。** 中心柱依 spec 在第 3(a) 步判定，此時同群支撐頭還沒有承載柱。之後若它們掛上這根中心柱，該接觸即成為「支撐頭對其承載柱」而豁免，但已寫下的 `centroid_pillar_clearance_recorded` 不會撤回。驗收素材上只有 mixed_s1、mixed_s2、China-dragon1 各 1 筆，與基準線最終樹中量到的三處相同。
5. **China-dragon1 的耗時餘裕。** 第 3、4 步中位數 2146.2 ms，門檻 2167.9 ms，餘裕 21.7 ms，單次量測有 2 次超過門檻（Open Questions 3）。階段一的預判只看本步開始時的間距，沒有考慮階段二才被填滿的掛橋上限與同一步先提交的元件；這類重算仍在單執行緒中規劃退路（含繞路搜尋）。Task 5、6 若在第 3、4 步增加計算，須重新量測；可行的下一步是讓預判也涵蓋「目標柱在本步開始時只剩一個掛橋名額」的候選。

## Migration Plan

1. 自 `release/v1.0.6` 建立修復分支。fork 合入 `feat/sla-bracing-planar-topology`（衝突採 planar 版本），主專案合入對應分支並更新子模組指標。
2. 建置合併後的引擎，跑 planar 的單元、向量與 IO 測試。以它作為本變更的基準線：記錄第 3(b)、4 步耗時 T，以及驗收素材上的 A / B / C / D 等計數。
3. 依序提交：`BridgeClearance` 模組與單元測試 → 第 3、4 步的規劃 / 提交拆分（先維持舊規則，確認幾何與單執行緒基準一致）→ 加入間距規則與降級狀態機 → planar 整合（B 收窄、去重、輔助柱反向 C）與新向量 → 匯出 `warnings` → 量測與驗收。
4. 重建依 `per-point-support-geometry` 不變式產生的支撐網格黃金檔，提交說明標示為刻意的幾何變更。
5. agent 不需改程式；舊版前端忽略 `warnings`。
6. 回滾：還原 fork 中本變更的 commit，主專案子模組指標指回合併 planar 後的 commit；若連 planar 一起回滾，則指回 `release/v1.0.6` 原指標。

## Open Questions

1. ~~完全沒有模型可行路徑的支撐頭。~~ 已裁決：本變更引入的間距與避讓規則，在任何情況下都不會導致任何支撐頭被刪除；若支撐頭因模型幾何全向物理阻擋（既有模型干涉）而完全無任何可行路徑，則維持既有行為。proposal 已同步收窄。
2. **斜撐對支撐頭。** planar 沒有把支撐頭當障礙物，斜撐可能穿過支撐頭的錐體。本變更未納入，是否另案處理待定。
3. ~~K 的初值。~~ 已定案：K = 4。初值 8 在 3.13 的效能驗收中，China-dragon1 第 3、4 步耗時 3357.7 ms，超過門檻 2167.9 ms。先在 `plan_to_pillar` 加入水平距離早退，並把模型碰撞測試移到所有廉價檢查之後，降為 2237.7 ms；10 個驗收案例的樹逐位元不變。K 再改為 4 後為 2099.1 ms，Pikachu 為 1329.1 ms（門檻 1424.4 ms），兩者都通過。10 個驗收案例的樹在 K = 8 與 K = 4 下逐位元相同。Task 4 加入間距規則後，China-dragon1 第 4 步的重算由 24 次增為 37 次，耗時升為 2255.8 ms（3 次中位數），超過門檻；加入階段一的退路預算（決策 5）後為 2146.2 ms（5 次：2146.2、2448.6、2014.1、2029.0、2257.1 ms，取中位數），Pikachu 為 1283.3 ms（5 次介於 1276.0～1331.9 ms），兩者都通過，10 個驗收案例的樹與預算前逐位元相同。China-dragon1 的餘裕只有 21.7 ms，見 Known Limitations 5。
4. **L1 是否也寫入匯出。** 目前只記 info log 與量測計數；若前端需要顯示，再改為 `warnings` 中的另一個 code。
5. **L2 次數的驗收門檻。** 於 specs 定義（例如參考素材上須為 0，或只記錄不設門檻）。

## Context

`DefaultSupportTree::interconnect_pillars()`（`third_party/prusaslicer_fork/src/libslic3r/SLA/DefaultSupportTree.cpp:992`）以「逐柱 cascade」連接柱子：對空間索引中的每根柱，查詢附近的柱、依距離排序、逐一呼叫 `interconnect()` 產生鋸齒斜撐。這個流程有四個缺陷：已滿鄰居被跳過、較細鄰居被跳過、不算數的連結讓搜尋停不下來、完全沒有桿對桿與桿對柱的檢查。詳見 proposal。

現況的資料結構：

- `SupportTreeBuilder` 內部已把桿件分開存放：`m_crossbridges`（斜撐）、`m_bridges`（掛橋、輔助柱橋、繞路段混存）、`m_diffbridges`（錐形繞路段）。三者在 `SupportTree.cpp:206-208` 匯出時被倒進同一個 `bridges` 陣列，型態資訊在這一步遺失。
- `Pillar::links` 只在高度比通過時加 1，本身就是「結構計數」，但同時被拿來當搜尋終止條件。
- 凍結柱（prior pillar）只有位置、高度、粗細與計數（`PriorPillarIO.hpp`），沒有既有桿件的幾何。

下游 DS-online 的 `src/three/supportInterconnect.js` 是 `interconnect_pillars()` 與 `interconnect()` 的 JS 轉寫，供手動支撐的即時預覽使用，並且在點擊後直接以預覽結果寫成支撐樹。本設計同時作為該轉寫的移植依據，因此幾何核心必須能逐行對應到 JS。

限制：

- 連接階段是單執行緒（在 `routing_to_model` 的平行階段之後），新邏輯不需處理共享狀態。
- 決定性：同一輸入的斜撐集合必須可重現。
- 常數不開放 API。

## Goals / Non-Goals

**Goals:**

- 把斜撐的拓撲決策抽成一個不依賴網格、可被向量測試直接驅動的純幾何模組 `BracingPlanner`。
- 以既有的 `BoxIndex` 支撐區域查詢，不引入新的空間資料結構。
- 定義所有幾何判定的公式、退化情況與浮點防護，使 C++ 與 JS 對同一份向量得到相同決策。
- 為每根桿件保留建立當下的型態，並在匯出中帶出；計數拆分後的欄位向後相容。
- 寫清楚移植到 DS-online 時的模組對應與座標換算規則。

**Non-Goals:**

- 不改動 branching 樹、頭部掛橋與繞路段的生成邏輯、模型碰撞檢查方式。
- 不提供舊演算法的執行期切換開關（見決策 9）。
- 不在本變更中修改 DS-online。

## Decisions

### 決策 1：`BracingPlanner` 是純幾何模組，網格碰撞以回呼注入

新增 `SLA/BracingPlanner.{hpp,cpp}`，命名空間 `Slic3r::sla::bracing`。模組內不引用 `AABBMesh`、`SupportTreeBuilder` 或 `SupportableMesh`，只吃「柱的幾何」與「既有桿件的幾何」，回傳「決策清單」。由 `DefaultSupportTree` 中的轉接層負責：從 builder 取資料餵進去，再把決策寫回 builder。

主要資料結構：

```cpp
namespace Slic3r::sla::bracing {

enum class Reason : uint8_t {
    accepted, too_close, pair_cap, obstacle_pillar,
    shared_angle, cross_truss, z_clear_fail, mesh_hit,
    no_room,       // 兩柱可用長度連一根桿都放不下（truss_bars 為空）
    out_of_range   // 只由 try_attach / attach 回報：超過 max_link_distance
};

struct TrussParams {              // 產生鋸齒桿所需，與 interconnect() 現行參數一一對應
    double bridge_slope_rad;      // cfg.bridge_slope（正值）
    double ground_z;              // ground_level(sm)
    double base_height;           // cfg.base_height_mm
    double base_radius;           // cfg.base_radius_mm（dynamic 模式判斷是否打叉）
    PillarConnectionMode mode;
};

struct PlannerConfig {
    double   safety_clearance   = 0.2;   // mm
    double   cos_min_shared_ang = 0.9396926207859084; // cos(20°)，以字面常數表示，見決策 6
    unsigned pair_cap           = 3;
    double   rescue_height      = 15.0;  // mm，同 max_solo_pillar_height_mm
    double   solo_height        = 15.0;  // H1，links 的 0.5 規則門檻
    double   min_height_ratio   = 0.5;
    double   max_link_distance;          // cfg.max_pillar_link_distance_mm
    double   min_pillar_distance;        // 2 × cfg.head_back_radius_mm
    TrussParams truss;
};

struct PillarGeom {               // 一根柱（含凍結柱、輔助柱）
    long     id;                  // 等於 builder 的 pillar id
    Vec2d    xy;                  // 軸心俯視位置
    double   foot_z, height;      // endpt.z 與 height；頂端 top_z() = foot_z + height，
                                  // 與 Pillar::startpoint() 同一算式，0.5 規則直接用 height
    double   r;                   // r_start
    unsigned links = 0, pairs = 0;
    bool     frozen = false;
    bool     braceable = true;    // false：只當障礙物、不參與配對與救援。轉接層對
                                  // 不在 m_pillar_index 的柱（掛橋用的自身短柱）設為 false，
                                  // 與舊 cascade 的走訪範圍一致；穿柱規則仍對所有柱生效
};

struct Segment3 { Vec3d a, b; double r; };

struct ObstacleBar {              // 非斜撐桿（head / prop / route / legacy）
    Segment3 seg;
    long     owner_a = -1, owner_b = -1;   // 供共用柱豁免
};

struct CandidateEdge {            // 候選連線，a < b
    long   a, b;
    double dist;                  // 俯視軸心距離
};

struct BuiltTruss {               // 已建立的一組斜撐
    long   a, b;
    double r;                     // min(r_a, r_b)
    std::vector<Segment3> bars;   // 實際建立的桿
    bool   rescued = false;
    bool   fallback = false;      // 保底連接建立（決策 12）
};

struct Decision {
    CandidateEdge edge;
    Reason        reason;
    unsigned      bars_built = 0;
    bool          rescue = false;
    bool          fallback = false;
    int           truss = -1;     // 接受時為 built() 的索引，供轉接層取出實際的桿
};

using MeshClearFn = std::function<bool(const Vec3d &from, const Vec3d &to, double r)>;

class BracingPlanner {
public:
    BracingPlanner(PlannerConfig cfg, MeshClearFn mesh_clear);

    void add_pillar(const PillarGeom &p);          // 建構期與輔助柱階段使用
    void add_obstacle_bar(const ObstacleBar &b);   // 非斜撐桿
    // 既有的斜撐桿（例如前端傳入的舊樹、向量的 bars 中 kind 為 truss 者）：
    // 依兩端柱分組為已建立的斜撐組；兩端柱未知時改當作 ObstacleBar
    void add_truss_bar(long a, long b, const Segment3 &bar);

    std::vector<Decision> run_greedy();            // 需求「全域由短到長」
    std::vector<Decision> run_rescue();            // 需求「孤立救援」
    // 輔助柱階段：評估 main 與尚未加入的 prop 之間能否建斜撐；不改狀態。
    // 不檢查配對上限（需求「輔助柱斜撐不受配對上限限制」）
    Decision try_attach(long main_id, const PillarGeom &prop) const;
    // 輔助柱加入後，對兩根已知柱以一般規則建立斜撐（主柱與輔助柱、輔助柱彼此）；
    // 同樣不檢查配對上限
    Decision attach(long a, long b);
    // 三個階段之後仍孤立的高柱：保底連接（決策 12）
    std::vector<Decision> run_fallback();
    // 叢集代表；同一叢集的柱回傳同一個值（決策 11）
    long cluster_of(long id) const;
    // 輔助柱加入後，只對包含新柱的候選再跑一次貪婪
    std::vector<Decision> run_greedy_for(const std::vector<long> &new_ids);

    const std::vector<BuiltTruss> &built() const;
    const PillarGeom &pillar(long id) const;
};

// 純函式（可單獨測試，也是 JS 移植的逐一對應目標）
namespace geom {
    double point_seg_dist2d(Vec2d p, Vec2d a, Vec2d b);
    double seg_seg_dist2d(Vec2d a, Vec2d b, Vec2d c, Vec2d d);
    double seg_seg_dist3d(const Vec3d &p1, const Vec3d &q1,
                          const Vec3d &p2, const Vec3d &q2);
    double seg_seg_closest2d(Vec2d a, Vec2d b, Vec2d c, Vec2d d, double &s, double &t);
    double plan_closest_dz(const Segment3 &bar1, const Segment3 &bar2); // 診斷用
    bool   shared_angle_ok(Vec2d shared, Vec2d end1, Vec2d end2, double cos_min);
    // 兩個方向向量的夾角 ≥ cos_min 對應的角度；叢集出發的斜撐用它（決策 11）
    bool   dir_angle_ok(Vec2d u, Vec2d v, double cos_min);
    std::vector<Segment3> truss_bars(const PillarGeom &p, const PillarGeom &q,
                                     const TrussParams &prm);
}
} // namespace Slic3r::sla::bracing
```

`MeshClearFn` 的轉接實作與現行 `interconnect()` 相同：`bridge_mesh_distance(from, dirv(from, to), r) >= (to - from).norm()`。現行程式比較的是 `pillar_dist / cos(slope)`，它正好等於桿長，所以結果不變。

**替代方案：** 把新邏輯直接寫進 `DefaultSupportTree` 的成員函式。缺點是向量測試必須建一棵帶網格的樹才能跑，而且 JS 移植時沒有一個邊界清楚的對應單位。因此不採用。

### 決策 2：規劃流程與狀態

```
DefaultSupportTree::interconnect_pillars()
  │
  ├─ 轉接層：builder.pillars()       → planner.add_pillar()（含凍結柱）
  │          builder.bridges() / diffbridges()（kind ≠ truss）
  │                                  → planner.add_obstacle_bar()
  │
  ├─ planner.run_greedy()
  │    1. 收集候選：非凍結柱 × 俯視距離 ≤ max_link_distance 的柱，排除凍結對凍結
  │    2. 排序：(dist, a, b)，a < b
  │    3. 逐一判定（順序固定）：
  │         too_close → pair_cap → obstacle_pillar → shared_angle → cross_truss
  │         → truss_bars() 逐桿：z_clear（對 ObstacleBar）→ mesh_clear
  │       至少一根桿通過即接受：寫入 truss 索引，pairs 兩端 +1，links 依 0.5 規則
  │
  ├─ planner.run_rescue()
  │    依全域排序走訪「至少一端為救援對象」的候選；救援對象 =
  │    非凍結 ∧ links == 0 ∧ 高度 > rescue_height，並在走訪中即時重算
  │    （某柱一旦得到 links，它剩下的候選就不再以救援名義嘗試）
  │    判定與貪婪相同，唯 cross_truss 改為逐桿：新桿對俯視相近的既有斜撐桿做 z_clear
  │
  ├─ 轉接層：依 Decision 寫回 builder（add_crossbridge_between，kind = truss；
  │          increment_links / increment_pairs；note_prior_attachment）
  │
  ├─ 輔助柱階段（auxiliary_pillars 開啟時）
  │    沿用既有的 needpillars 判定與 20 個角度的位置搜尋；
  │    一個角度要「垂直路徑暢通 ∧ 柱底不撞 ∧ try_attach(main, prop) 接受」才算可放置；
  │    通過才加柱、加 prop 桿（kind = prop，並 add_obstacle_bar）、寫入斜撐；
  │    try_attach / attach 不檢查配對上限；
  │    最後以 run_greedy_for(新柱 id) 取代 DefaultSupportTree.cpp:1238 對全部柱的重跑
  │
  └─ planner.run_fallback()（輔助柱開關不影響）
       對仍然 links == 0 ∧ 高度 > rescue_height 的非凍結可配對柱，強制連到最近的合法鄰居
```

所有規則中的「同一根柱」都經過叢集（決策 11）：穿柱、共用柱夾角、逐桿判定的共用柱豁免。

凍結柱只會出現在候選的一端，永遠不是 `run_greedy_for` 的發起端，也不會被輔助，因此滿足 R10。

**為什麼救援在走訪中即時重算資格。** 若先固定一份救援名單，同一根柱可能經由兩個候選各救一次，多出不必要的斜撐。即時重算可讓每根柱救到就停。

### 決策 3：空間索引使用三個 2D `BoxIndex`

`BoxIndex`（`SpatIndex.hpp:66`）是 boost 的 R* 樹（`rstar<16, 4>`），元素為 `std::pair<Slic3r::BoundingBox, unsigned>`。`BoundingBox` 是 2D 整數座標，以 `scale_()` 換算（`SCALING_FACTOR = 1e-6`，1 單位 = 1 nm）。它不是均勻格子，所以沒有格距參數，查詢成本為 O(log n + k)。

planner 持有三個索引：

| 索引 | 元素 | 存入的包圍盒 |
|---|---|---|
| `pillar_idx` | 每根柱 | 軸心點外擴 `r` |
| `truss_idx` | 每組已建立的斜撐 | 兩軸心連線的包圍盒外擴 `r_truss` |
| `bar_idx` | 每根非斜撐桿 | 桿端點俯視投影的包圍盒外擴 `r` |

查詢時，以候選線段（或單根桿）的俯視包圍盒外擴 `r_query + safety_clearance` 作為查詢框，採 `qtIntersects`。因為存入的框已包含元素自身半徑，查詢框只需再加上查詢方的半徑與間隙，即為完整的超集合。換算成整數時，`min` 一律向下取整、`max` 一律向上取整，確保不因捨入而漏掉邊界上的元素。查詢結果只用於「是否存在違規」的判定，走訪順序不影響結果，因此不影響決定性。

生命週期：三個索引都是 planner 的成員，在 `interconnect_pillars()` 開始時建立，函式結束時隨 planner 銷毀，不跨執行、不跨執行緒。只有插入，沒有刪除，因為已接受的斜撐不會被撤銷。

**替代方案：** 自寫均勻格子（cell = `max_link_distance`）。查詢略快，但要多維護一份新程式。現有 R* 樹在數千元素下差異可忽略，而且已經測試過，因此不採用。另一個替代方案 `PointIndex` 是 3D 點索引，無法表達線段，也不採用。

### 決策 4：2D 線段距離與退化情況

記號：`cross2(p, q) = p.x·q.y − p.y·q.x`，`ε_len = 1e-12`（mm²），`ε_par = 1e-12`（相對值）。

**點到線段**（`point_seg_dist2d(p, a, b)`）：

```
u = b − a
若 |u|² < ε_len：回傳 |p − a|                 // 長度為 0 的線段視為點
t = clamp( (p − a)·u / |u|², 0, 1 )
回傳 | p − (a + t·u) |
```

**線段到線段**（`seg_seg_dist2d(a, b, c, d)`）：

```
u = b − a, v = d − c, w = c − a
den = cross2(u, v)
若 |den| > ε_par · |u| · |v|：                 // 不平行
    s = cross2(w, v) / den
    t = cross2(w, u) / den
    若 0 ≤ s ≤ 1 且 0 ≤ t ≤ 1：回傳 0          // 真交叉（含 T 字與端點接觸）
回傳 min( point_seg_dist2d(a, c, d), point_seg_dist2d(b, c, d),
          point_seg_dist2d(c, a, b), point_seg_dist2d(d, a, b) )
```

兩條 2D 線段若不相交，最短距離必定出現在某個端點到另一條線段之間，所以「四個點到線段的最小值」對不相交、平行與共線都正確。共線重疊時，至少有一個端點落在另一條線段上，距離為 0。

**共用柱的判定不走幾何。** 是否共用柱以 `PillarGeom::id` 比對，在進入距離計算之前處理：共用柱的兩組斜撐只做夾角判定，不做距離判定。這樣可以避免「端點接觸距離為 0」被誤判成交叉。

### 決策 5：立體間距判定（Z 高度差的精確形式）

討論中原本定義為「在俯視最近點比較兩桿高度差」。推導後發現這會高估間距。

設兩桿的 3D 方向為 `d1`、`d2`，俯視交叉點的參數為 `(s*, t*)`，該點的高度差為：

```
Δz = (p1.z + s*·d1.z) − (p2.z + t*·d2.z)
```

兩條無限直線的 3D 最短距離為：

```
dist_line = |Δz| · κ，κ = |(d1 × d2).z| / |d1 × d2|，0 ≤ κ ≤ 1
```

只有兩桿都水平時 `κ = 1`。一根水平、一根 45° 時，`κ ≈ 0.707`。所以只比較 `Δz` 會讓實際間距不足的桿通過。

因此判別式定為：

```
seg_seg_dist3d(bar1, bar2) ≥ r1 + r2 + safety_clearance   → 通過
```

`seg_seg_dist3d` 採 Ericson《Real-Time Collision Detection》§5.1.9 的線段最近點演算法：

```
d1 = q1 − p1, d2 = q2 − p2, r = p1 − p2
a = d1·d1, e = d2·d2, f = d2·r
若 a ≤ ε_len 且 e ≤ ε_len：s = t = 0
否則若 a ≤ ε_len：s = 0, t = clamp(f / e, 0, 1)
否則：
    c = d1·r
    若 e ≤ ε_len：t = 0, s = clamp(−c / a, 0, 1)
    否則：
        b = d1·d2, den = a·e − b²
        s = den > ε_par·a·e ? clamp((b·f − c·e) / den, 0, 1) : 0     // 平行時任取 s = 0
        t = (b·s + f) / e
        若 t < 0：t = 0, s = clamp(−c / a, 0, 1)
        若 t > 1：t = 1, s = clamp((b − c) / a, 0, 1)
回傳 | (p1 + s·d1) − (p2 + t·d2) |
```

當兩條線段的最近點都落在線段內部時，結果等於 `|Δz|·κ`；落在端點外時，結果自動夾到端點。單元測試以 `|Δz|·κ` 作為內部最近點案例的對照答案。俯視最近點的 `Δz` 只保留作診斷輸出。

粗篩一律先做 `seg_seg_dist2d < r1 + r2 + c`（必要條件，不會漏判），通過粗篩的才計算 3D 距離。

原因代碼沿用 `z_clear_fail`，避免更動已對齊的向量格式。

### 決策 6：共用柱夾角以餘弦比較

```
u = end1 − shared, v = end2 − shared
// 兩者長度皆 ≥ min_pillar_distance（too_close 已先擋下），不會是零向量；
// 仍防護：|u|² < ε_len 或 |v|² < ε_len 時視為不通過（shared_angle）
c = (u·v) / (|u|·|v|)
c = clamp(c, −1, 1)                // 避免浮點誤差使 |c| 略大於 1
通過 ⇔ c ≤ cos_min_shared_ang     // θ < 20° ⇔ c > cos 20°；恰等於則接受
```

判定本身完全不呼叫 `acos`，也就沒有 NaN 的風險。只有在診斷輸出角度時才呼叫 `acos(clamp(c, −1, 1))`。

`cos 20°` 以字面常數 `0.9396926207859084` 寫在 C++ 與 JS 兩端，不在執行期呼叫 `cos`，避免兩端的數學函式庫在最後一位小數上不一致。`tan(bridge_slope)` 無法避免執行期計算，因此向量的門檻案例一律離門檻 ±1e-6，遠大於這種誤差。

### 決策 7：鋸齒桿產生抽成純函式，逐行保留現行行為

`geom::truss_bars(p, q, prm)` 是從 `interconnect()`（`DefaultSupportTree.cpp:209-300`）原樣抽出的純函式，只做兩處改動：不做模型碰撞（交給 `MeshClearFn`），桿半徑取 `min(p.r, q.r)`。

```
zmin   = prm.ground_z + prm.base_height
supper = (p.xy, p.top_z),  slower = (q.xy, q.top_z)
eupper = (p.xy, max(p.foot_z, zmin)),  elower = (q.xy, max(q.foot_z, zmin))
若 slower.z < elower.z 或 supper.z < eupper.z：回傳 []
d     = |p.xy − q.xy|
zstep = d · tan(−prm.bridge_slope_rad)                  // 負值
若 zstep 不小於 0（d = 0、斜撐角不為正或 NaN）：回傳 []   // 原本靠 too_close 間接避免的無窮迴圈，改為直接防護
若 supper.z < slower.z：交換 supper 與 slower（整個點，含 xy）
若 eupper.z < elower.z：交換 eupper 與 elower
startz = (slower.z − zstep < supper.z) ? slower.z − zstep : slower.z
若 slower.z − eupper.z < |zstep|：                       // 連一個叉都放不下
    startz = min(supper.z, slower.z − zstep)
    endz   = max(eupper.z + zstep, elower.z)
    avail  = startz − endz
    startz −= 0.5 · (avail − floor(avail / |zstep|) · |zstep|)
docross = mode == cross ∨ (mode == dynamic ∧ d > 2 · prm.base_radius)
sj = (supper.xy, startz), ej = (slower.xy, startz + zstep)
當 ej.z ≥ eupper.z：
    輸出 (sj, ej)
    若 docross：
        sjb = (ej.xy, sj.z), ejb = (sj.xy, ej.z)
        若 sjb.z ≤ slower.z 且 ejb.z ≥ eupper.z：輸出 (sjb, ejb)
    交換 sj 與 ej；ej.z = sj.z + zstep
每根輸出的桿 r = min(p.r, q.r)
```

現行程式的桿半徑取「cascade 發起柱」的 `r_start`。因為原本的守衛保證發起柱不比鄰居粗，那個值就等於兩者的較小值。所以這項改動在等粗或發起柱較細的情況下，結果完全不變。

JS 的 `bracePrimitives()` 沒有「連一個叉都放不下」那一段，移植時必須補上。

### 決策 8：資料模型與序列化

**`BridgeKind` 與記憶體佈局。** `BridgeKind` 定義在 `SupportTree.hpp`（實作時修正：匯出用的 `TreeBridge` 在這個檔案，而它不引用 `SupportTreeBuilder.hpp`；builder 引用 `SupportTree.hpp`，所以兩邊都看得到）。`Bridge` 的欄位加在 `SupportTreeBuilder.hpp`：

```cpp
enum class BridgeKind : uint8_t { unset = 0, truss, head, prop, route };

struct Bridge : public SupportTreeNode {   // long id
    double r;
    Vec3d  startp, endp;                   // Eigen DontAlign，各 24 bytes
    long   owner_a, owner_b;
    BridgeKind kind = BridgeKind::unset;   // 新增；對齊後每筆約多 8 bytes
};
// DiffBridge 繼承 kind；TreeBridge 同樣新增 BridgeKind kind。
```

**標記方式。** 型態由 builder 的建立函式決定，不在呼叫端事後補寫。繞路段是在平行的 `routing_to_model` 中建立，所以一根桿的所有記錄都在 `_add_bridge` 持有鎖的期間一次寫入：`kind`、`owner_a`、`owner_b`、`relaxed`、`fallback`，由呼叫端以 `BridgeTags` 傳入。加桿函式回傳的是鎖內複製的一份 `Bridge`（或 `DiffBridge`），不是指向 vector 的參考。若回傳參考，呼叫端在鎖放開後經由它讀寫，可能碰到另一個執行緒擴充同一個 vector 後已釋放的記憶體（程式碼審查第 3 項；這個競爭在本變更前就存在於 owner 的寫入）：

- `add_crossbridge` / `add_crossbridge_between`：固定為 `truss`。
- `add_bridge(long headid, const Vec3d &endp)` 與 `add_bridge_to_pillar`：固定為 `head`。
- `add_bridge(s, e, r)` 與 `add_bridge_between(...)`：新增一個**沒有預設值**的 `BridgeKind` 參數，強迫每個呼叫點明確寫出。`DefaultSupportTree.cpp:384` 寫 `head`，`:1212` 寫 `prop`，`SupportTreeUtilsLegacy.hpp:237/297` 寫 `route`。
- `add_diffbridge`：固定為 `route`（`SupportTreeUtils.hpp:625`、`SupportTreeUtilsLegacy.hpp:177`；branching 樹也會呼叫，但不在範圍內）。

**繞路桿的端點豁免。** 逐桿判定只在非斜撐桿的 `a` 或 `b` 是斜撐組的端柱（或同叢集）時豁免。落地繞路的最後一根桿，終點正好是它那根柱的柱頂，而鋸齒的第一根桿也常落在較矮那根柱的柱頂，兩者 3D 距離為 0。若這根繞路桿沒有記錄柱，該斜撐桿必被判為 `z_clear_fail`（程式碼審查第 4 項）。因此：

- `create_ground_pillar` 在柱建立後，把柱的編號寫到終點落在柱頂的那一根桿的 `owner_b`：有繞路修正桿時是它，否則是漸變桿（`own_bridge`、`own_diffbridge`，鎖內寫入）。
- `connect_to_ground` 只在 `create_ground_pillar` 沒有再往下鋪桿時（柱頂就是自己的終點），才在自己那根桿寫入柱的編號。
- 終點不在柱頂的繞路桿不寫，仍照常參與立體間距判定。
- 匯出時，這根繞路桿因此帶 `b`。`b` 的語意不變（桿接到的柱），讀取端照舊以 `a`、`b` 判定豁免。
- 量測工具 `bracing_metrics()` 原本以「沒有 owner」認出繞路桿；帶 `owner_b` 且柱不是輔助柱的桿，改以記錄的 `kind` 區分 `head` 與 `route`，因為兩者都可能剛好停在柱頂，無法以幾何分辨。

`unset` 只是防呆用的初始值。匯出時如果遇到 `unset`，Debug 建置直接 assert。Release 建置則不寫 `kind`，讓讀取端以 legacy 處理，而不是猜一個型態。IO 測試保證三個參考模型的匯出中沒有任何缺 `kind` 的桿。

**計數。** `Pillar`、`TreePillar`、`PriorPillar` 新增 `unsigned pairs = 0`；`PriorAttachment` 新增 `pairs`。builder 新增 `increment_pairs(const Pillar&)`，寫法與 `increment_links` 相同。`add_frozen_pillar` 的 `pairs` 參數放在最後且沒有預設值，舊呼叫會編譯失敗而不會默默錯位。`adopt_prior_pillars()` 把凍結柱的 `pairs` 一併帶入 `add_frozen_pillar`。資料層階段（任務 2）只計數、不讀取：每次 `interconnect()` 成功就對兩端各加 1，不影響任何決策，因此幾何不變。

**support-tree（`SupportTreeIO.hpp`，`version` 維持 2）：**

```json
"pillars": [{"endpt":[x,y,z],"height":40.2,"r_start":0.5,"r_end":0.5,
             "links":1,"pairs":2,"bridges":0}],
"bridges": [{"startp":[x,y,z],"endp":[x,y,z],"r":0.5,"kind":"truss","a":1,"b":3}]
```

`kind` 一律寫出，因為缺值代表 legacy，不能比照 `end_r`、`reaches` 的省略規則。`pairs` 一律寫出。

**prior-pillar（`PriorPillarIO.hpp`，`version` 維持 1）：**

- 讀取：先讀 `links`，再讀 `pairs`。`pairs` 只接受非負整數，且不得超過 `unsigned` 的上限；缺值、`null`（前端 `JSON.stringify` 對 NaN 的輸出）、負數、小數、字串、布林、陣列或超出範圍時，一律以 `links` 代替，不丟例外、不溢位（`detail::read_pairs`，程式碼審查第 5 項）。若讀到的 `pairs < links`，就把 `pairs` 提高到 `links`，因為每一個結構連結必定伴隨一個配對。
- 寫出：`pillars[]` 與 `attached_to[]` 都寫出 `pairs`。

C++ 端沒有 support-tree 的讀取端，所以「缺 `kind` 視為 legacy」的規則只會在 DS-online 生效，但規格仍然把它列為格式契約。

### 決策 9：不保留舊演算法的執行期切換

`sla-raster-performance` 曾以 `SLA_RASTER_FASTPATH` 保留參考實作，那是因為它要求輸出逐位元相同，參考實作可以當差分對照。本變更是刻意改變幾何，舊演算法無法當作正確性的對照。基準線改用「改動前 commit 的建置」，在同一台機器、同一套編譯設定下量測。回滾方式是還原 fork 的 commit。

**替代方案：** 保留 `SLA_BRACING_LEGACY=1`，好處是不用重新建置就能 A/B 比較。代價是兩套連接邏輯要長期並存，而且輔助柱階段會分成兩條路。考量後不採用。

### 決策 10：DS-online 移植交接

**模組對應。** 下一階段在 DS-online 新增 `src/three/bracingPlanner.js`，與 C++ 逐一對應：

| C++ | JS（`bracingPlanner.js`） | 說明 |
|---|---|---|
| `geom::point_seg_dist2d` | `pointSegDist2d` | 公式與 ε 相同 |
| `geom::seg_seg_dist2d` | `segSegDist2d` | 同上 |
| `geom::seg_seg_dist3d` | `segSegDist3d` | 同上 |
| `geom::shared_angle_ok` | `sharedAngleOk` | `cos 20°` 用同一個字面常數 |
| `geom::truss_bars` | `trussBars` | 取代 `supportInterconnect.js` 的 `bracePrimitives`，並補上「放不下一個叉」的分支 |
| `BracingPlanner` 的候選、排序、判定順序 | `planBracing({cfg, pillars, bars, meshClear})` | 回傳與 C++ 相同的 `Decision` 結構，原因代碼字串相同 |
| `run_rescue` | `planBracing` 內建 | 手動模式關掉了輔助柱，救援是唯一的安全網 |
| `MeshClearFn` | `meshClear(from, to, r)` | 由 `_manualPathClear`（射線）提供；向量測試一律回傳通過 |

`braceCandidates` 改由 `planBracing` 取代。`nearPillarRoute`（頭部掛橋）的邏輯不變。

手動點擊的情境是「只有一根非凍結柱，其餘全部凍結」。`planBracing` 在這個情境下自然只會產生包含新柱的候選，與 C++ 跑同一份向量的結果相同，不需要另寫一套單柱邏輯。

**座標系。** planner 一律在**引擎座標**（support-tree 文件所用的座標）中運算：

- 前端世界座標與引擎座標的 X、Y 完全相同，因為渲染器對樹只做純 Z 平移（`setFrame`）。
- `z_引擎 = z_世界 − originZ`，其中 `originZ = _manualModelBottomZ`（模型底面的世界高度）。這和 `supportTreeFromPreview.js` 的 `vec(p, originZ)`，以及 `_manualWorldPillars()` 加回 `_manualModelBottomZ` 的做法一致。
- 進入 planner 前，要換算的東西是：新柱（來自 `resolveSupportPrimitives` 的世界座標）、`ground_z`（`_manualGroundZ − originZ`）。store 裡的樹與 pillars 本來就是引擎座標，不用換算。
- planner 輸出的桿件是引擎座標。寫進樹時直接使用，不要再經過 `vec()`。畫預覽時才加回 `originZ`。
- 只有 `trussBars` 與 `segSegDist3d` 會受 Z 影響；俯視判定不受座標系影響。座標系混用時，症狀是 Z 判定整體偏移一個模型底面高度，而俯視判定看起來仍然正常。所以要有一個向量，專門讓混用時一定會失敗。

**計數承接。** store 中每根柱新增 `pairs`。`applyAttachments`、`withLinksFreed`、`supportTreeDrag.js` 的釋放邏輯、`sceneCoordinator.js:5056` 在增減 `links` 的同一處，同步增減 `pairs`。缺 `pairs` 的舊專案以 `links` 代替。

**向量。** DS-online 存一份 `tests/data/sla_bracing_vectors/` 的複本，vitest 先比對 `MANIFEST.sha256`，再逐一執行向量。正本的路徑與 `MANIFEST.sha256` 本身的雜湊，記錄在本變更的 `evidence/final-*/`。

### 決策 11：緊貼柱以叢集處理

**問題。** 驗收時中模型出現孤立高柱。追蹤後發現原因是緊貼的柱：例如柱 108 與 113 軸心只差 0.94 mm（兩者 `r_start` 皆約 0.5，柱身已重疊）。原規則把它們當成兩根互相擋路的柱：其中一根連出去的每條線，起點都擦過另一根，被 `obstacle_pillar` 擋下；就算其中一根先連上，另一根拉向同一批鄰居的線又會被判成 `cross_truss`。

**做法。** 以並查集（union-find）維護叢集：

```
add_pillar(p):
    以 pillar_idx 查詢 p.xy 外擴 (p.r + c) 的框
    對每根 q：若 |p.xy − q.xy| < p.r + q.r + c，union(p, q)
cluster_of(id) = find(id)
same_place(x, y) = x == y ∨ (x, y 皆為已知柱 ∧ find(x) == find(y))
```

存入索引的框已含 `q.r`，所以查詢框外擴 `p.r + c` 即足夠。叢集只有合併、沒有拆分，輔助柱加入時同樣經過 `add_pillar`。`try_attach` 評估尚未加入的輔助柱時，以「它會緊貼的柱」所屬的叢集代替它自己的叢集。並查集的代表只用來比較是否相等，不影響任何排序，因此決定性不變。

規則中原本以「編號相同」判定的地方，改用 `same_place`：

| 位置 | 原本 | 改為 |
|---|---|---|
| 穿柱 | 略過 `q == a ∨ q == b` | 略過 `same_place(q, a) ∨ same_place(q, b)` |
| 共用柱夾角 | 兩組有相同端柱編號 | 兩組各有一端 `same_place`；夾角以兩組各自端柱的軸心起算，用 `dir_angle_ok(u, v)` |
| `cross_truss` | 不共用柱才判距離 | 不 `same_place` 才判距離 |
| 逐桿判定的共用柱豁免 | 非斜撐桿的端柱編號相同 | `same_place` |
| 救援／保底比對斜撐桿 | 共用端柱編號者略過 | `same_place` 者略過 |

共用柱的配對以固定順序尋找：(候選 a, 既有 a)、(候選 a, 既有 b)、(候選 b, 既有 a)、(候選 b, 既有 b)，取第一個成立者。兩組兩端都落在同叢集時（兩條幾乎平行的雙生斜撐），夾角接近 0，結果為 `shared_angle`，這正是要擋下的情況。

**為什麼用連通性，不只看兩兩緊貼。** 三根柱排成 0.9 mm 間距的一串時，只看兩兩關係會讓頭尾兩根互相擋路，問題原封不動。連通性的風險是一長串柱會合成一個大叢集；量測工具一併輸出最大叢集的大小，用來監看。

**替代方案：** 只豁免「緊貼端柱」的柱（實驗 A）。實驗中中模型的孤立柱只從 2 根降到 1 根，因為雙生柱拉向同一批鄰居時仍互判 `cross_truss`。因此改採完整的叢集規則。

### 決策 12：保底連接（Level 3）

**時機。** 在輔助柱階段之後，`interconnect_pillars()` 結束之前。輔助柱關閉時（使用者自己決定支撐位置）同樣執行，這時它是救援之外唯一的補救。

**對象與候選。** 對象為非凍結、可配對、`links == 0`、高度 > `rescue_height` 的柱。候選以 `collect(對象)` 重新收集（輔助柱階段已加入新柱），再只留下「對方高度 ÷ 對象高度 > `min_height_ratio`」的候選，因為對象高於 `solo_height`，只有這種對象能讓它得到 `links`；其餘候選不列出、不回報原因，與超出距離的柱對相同。走訪時即時重算資格，對象一得到 `links` 就停止。

**判定。** 與救援相同（`cross_truss` 改為逐桿 3D），唯一差別是配對上限改看 `links`：

```
pair_cap（保底）⇔ pa.links ≥ pair_cap ∨ pb.links ≥ pair_cap
```

理由：`pairs` 滿了通常是被矮柱佔掉，這些配對不提供結構支撐；`links` 才是結構計數，維持它不超過 3，也符合既有完整性檢查 `links ≤ pillar_cascade_neighbors`。

**記錄。** `BuiltTruss::fallback` 與 `Decision::fallback` 為 true。轉接層寫入 builder 時，在斜撐桿上標記 `relaxed`（見下段），量測工具據此把救援與保底的斜撐排除在俯視違規門檻之外，另行計數。

**builder 的 `relaxed` 旗標。** `Bridge` 新增 `bool relaxed = false`，`add_crossbridge_between` 新增最後一個參數 `bool relaxed`（沒有預設值，和 `kind` 的作法一致），由轉接層依 `BuiltTruss::rescued || BuiltTruss::fallback` 帶入。它只供量測與除錯使用，不寫入匯出格式。

## Risks / Trade-offs

- [嚴格俯視規則減少斜撐，孤立高柱增加] → 救援與保底連接先補；驗收門檻要求參考模型的孤立高柱數為 0；桿件總數與輔助柱數一併記錄。
- [站在模型上的柱，即使斜撐從其腳下通過也會被穿柱規則擋下] → 救援與保底都不放寬穿柱規則，這是刻意保守；由同一個孤立柱指標監看，必要時另立變更，讓穿柱規則考慮柱的 Z 範圍。
- [叢集以連通性合併，一長串緊貼柱會合成大叢集，叢集內的穿柱檢查全部豁免] → 量測工具輸出最大叢集大小；若參考模型出現大叢集，再評估改為「叢集直徑上限」。
- [保底連接不看 `pairs`，個別柱的配對數可超過 3] → `links` 仍不超過 3；保底斜撐另行計數，供判讀。
- [保底在沒有合法鄰居時無能為力（例如範圍內沒有夠高的柱，或全部穿柱）] → 孤立高柱指標仍會反映；驗收門檻要求參考模型為 0。
- [頭部掛橋與繞路段的生成順序早於連接階段，而且掛橋之間本身沒有避讓] → 不在範圍內；它們只作為障礙物。
- [疊加路徑只有凍結柱、沒有舊桿，引擎無法檢查新斜撐與舊桿的交叉] → 列為已知限制；前端目前不使用此路徑，前端自己的 planner 拿得到全部桿件。
- [`tan`、`sqrt` 在 C++ 與 V8 的最後一位小數可能不同] → 向量門檻案例離門檻 ±1e-6；`cos 20°` 用字面常數；向量比對的是決策，不是浮點座標。
- [`routing_to_model` 的平行執行，可能讓 builder 的柱與桿順序在不同次執行間不同，進而影響 id 與平手排序] → 基準線先量現況的不一致範圍；驗收以基準線為準。若確認是既有問題，另案處理。
- [`BridgeKind` 漏標] → `add_bridge` / `add_bridge_between` 的 kind 參數沒有預設值，編譯期就會強迫呼叫點寫出；Debug 建置 assert；IO 測試檢查參考模型的匯出。
- [0.2 mm 與 20° 尚未經列印實驗驗證] → 先寫死為常數，列為後續校正項目。

## Migration Plan

1. 在改動前的 fork commit 建置引擎，量測基準線（tasks 第 1 組）。
2. 依序提交：資料層（驗證網格逐位元不變）→ `BracingPlanner` 與單元測試 → `interconnect_pillars` 改寫 → IO → 向量 → 模型驗收。
3. 重建受影響的支撐網格黃金檔，並在提交說明中標示為刻意的行為變更。
4. agent 不需改程式；API 回應多出的選填欄位，舊版前端會忽略。
5. 回滾：還原 fork 的相關 commit，並把 web_slicer_core 的子模組指標指回原本的 commit。新增的欄位是選填，舊引擎輸出的資料，新版前端仍可讀取（缺值走回退規則）。

## Open Questions

- 三個參考模型的具體選擇，在 tasks 1.2 決定並記錄 SHA-256。
- 前端在引擎座標下的 `ground_z`，理論上是樹文件中柱腳的 Z（約為 `-elevation`）。實際值要在移植時用真實的樹文件核對，pad 開啟時是否有額外偏移也要一併確認。
- 0.2 mm 間隙與 20° 夾角，需要列印實驗校正。
- 穿柱規則是否要考慮柱的 Z 範圍，視驗收時孤立柱指標的結果決定。

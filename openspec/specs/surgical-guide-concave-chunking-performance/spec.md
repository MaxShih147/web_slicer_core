# surgical-guide-concave-chunking-performance Specification

## Purpose
TBD - created by archiving change perf-surg-guide-concave-chunking. Update Purpose after archive.
## Requirements
### Requirement: 分批處理不得改變 detect_concave_faces() 的可觀察輸出

`detect_concave_faces()` 的 edge concavity 累加計算改為固定大小分批（chunk）處理 SHALL 屬純效能／實作層級變更：以同一份輸入，改動前後的逐 face `votes`、逐 face `total`、最終 `concave` 面索引集合、`_entrance_dir_by_concave()` 的方向、`res.dir`、`rotation_rad` SHALL 完全相同（bit-exact），不得以「數值合理接近」作為驗收線。

#### Scenario: 逐 face votes/total 完全相同
- **WHEN** 以同一份輸入分別在改動前後執行 `detect_concave_faces()`
- **THEN** 每個 face 的 `votes` 值與 `total` 值 SHALL 完全相同

#### Scenario: 最終方向與 rotation 不受影響
- **WHEN** 以同一份輸入分別在改動前後呼叫 `_entrance_dir_by_concave()` 與 `compute_auto_orientation_surg_guide_detail()`
- **THEN** 回傳的方向向量與 `rotation_rad` SHALL 完全相同

### Requirement: dtype 與算術語意不得改變

face centers（`mesh.face_c`）與 face normals（`mesh.face_n`）進入本函式後 SHALL 維持轉為 float64 並全程以 float64 運算，MUST NOT 引入 float32 或其他精度路徑。Edge concavity 的點積計算 SHALL 使用與現行 `d @ fn[f]` 數學等價的明確三分量運算式，MUST NOT 使用 `einsum`、`sum(axis=...)` 或其他可能改變加總順序或 dtype 的 reduction 方式。

#### Scenario: 全程 float64
- **WHEN** 分批處理讀取 face centers/normals 並計算 concavity
- **THEN** 所有中間值（差向量、點積結果、`votes`/`total` 陣列）SHALL 為 float64

#### Scenario: 點積結果與逐分量運算等價
- **WHEN** 對同一組 face center 差向量與 face normal 計算點積
- **THEN** 分批實作的計算結果 SHALL 與明確三分量乘加運算式的結果一致

### Requirement: threshold 與 ratio 判斷不得改變

concavity 判斷 SHALL 維持嚴格的 `> 1e-6`；per-face 的 concave 判定 SHALL 維持 `votes/total >= 0.55`。兩者的比較運算子與數值 MUST NOT 被放寬、收緊或以其他容忍值取代。

#### Scenario: 嚴格大於判斷
- **WHEN** 某次 edge concavity 點積結果恰好等於 `1e-6`
- **THEN** 該次判斷 SHALL 為不通過（`> 1e-6` 為嚴格大於，等於不算通過）

#### Scenario: ratio 門檻不變
- **WHEN** 某 face 的 `votes/total` 恰好等於 `0.55`
- **THEN** 該 face SHALL 被視為通過門檻（`>=` 為包含等於）

### Requirement: edge 累加規則不得改變

每一條有效（`f1 >= 0`）interior edge SHALL 對其兩側 face 的 `total` 各自累加恰好 1.0；兩側的 `votes` SHALL 各自根據該側 face 自己的法向量獨立判斷是否累加，MUST NOT 假設兩側對稱或共用同一次比較結果。`f1 < 0`（boundary，無第二個 face）的 edge SHALL 維持現行的完全跳過，不進入 votes/total 累加。`mesh.edge_faces` 既有的非流型 edge（first-two-faces-only）語意 SHALL 原樣繼承，MUST NOT 在本函式內重新定義或補償這個拓撲來源的既有行為。

#### Scenario: 兩側 face 各自獨立判斷
- **WHEN** 一條 interior edge 連接 face A 與 face B，且兩者法向量方向不同
- **THEN** face A 的 vote SHALL 僅由 A 自己的法向量與差向量決定，face B 的 vote SHALL 僅由 B 自己的法向量與差向量（方向相反）決定，兩者互不依賴對方的判斷結果

#### Scenario: boundary edge 略過
- **WHEN** 處理一條 `f1 < 0` 的 edge
- **THEN** 該 edge SHALL NOT 對任何 face 的 votes/total 產生影響

#### Scenario: 非流型 edge 的既有行為不變
- **WHEN** 某條 edge 在 `mesh.edge_faces` 中因非流型（3 個以上 face 共用同一 edge）只登記了前兩個發現的 face
- **THEN** 分批處理 SHALL 只依據 `mesh.edge_faces` 已登記的內容累加，MUST NOT 嘗試重新推導或補上未登記的第三個以上的 face

### Requirement: cylinder exclusion 的時機與邊界慣例不得改變

Cylinder exclusion SHALL 繼續在所有 edge 的 votes/total 累加完成、且 `ratio >= 0.55` 篩選出候選 `concave` 集合之後才執行，MUST NOT 提前執行或與累加/分批處理交錯。Cylinder 邊界判斷 SHALL 維持 `radial <= radius` 視為 inside（排除）的既有慣例。

#### Scenario: exclusion 在累加與篩選之後
- **WHEN** 呼叫 `detect_concave_faces(mesh, cylinders)`
- **THEN** cylinder exclusion SHALL 只作用於已通過 `ratio >= 0.55` 篩選的 `concave` 索引集合，MUST NOT 在逐 edge 累加階段執行

#### Scenario: 邊界值視為 inside
- **WHEN** 某個候選 concave face 的 radial 距離恰好等於 cylinder 的 radius
- **THEN** 該 face SHALL 被排除（視為 inside）

### Requirement: chunk 邊界不得影響累加正確性

同一個 face 若其累加邊被分配到不同的 chunk，最終該 face 的 `votes`／`total` SHALL 與所有邊在同一批次處理時完全一致——累加目標（`votes`/`total` 陣列）SHALL 貫穿所有 chunk 持久化，MUST NOT 因批次切換而重置或遺漏。最後一批不足 chunk size 的 partial chunk SHALL 正確處理，MUST NOT 因批次未滿而跳過、截斷或以未初始化資料計算。

#### Scenario: 同一 face 的累加跨越 chunk 邊界
- **WHEN** 一個 face 的多條累加邊被分配到 2 個以上不同的 chunk
- **THEN** 該 face 最終的 `votes` 與 `total` SHALL 與「該 face 的所有累加邊在單一批次中處理」得到的結果完全相同

#### Scenario: partial chunk 正確處理
- **WHEN** 剩餘待處理的 interior edge 數量小於設定的 chunk size
- **THEN** 該最後一批 SHALL 依實際剩餘數量正確處理，SHALL NOT 因未達到完整 chunk size 而被跳過或截斷

### Requirement: 暫存工作集 SHALL 由固定 chunk size 限制，不得隨模型 edge 數線性成長

分批處理 MUST NOT 在任何時間點同時具現化「一次容納模型全部 interior edges」所需的完整暫存陣列組合（face-index arrays、face-center/normal 的 gather 結果、差向量、點積結果、mask）。這些暫存陣列的大小 SHALL 由固定的 chunk size 決定量級，SHALL NOT 隨模型的總 interior edge 數等比例成長。

#### Scenario: 不具現化全量暫存陣列
- **WHEN** 處理一個 interior edge 數遠大於 chunk size 的模型
- **THEN** 任一時間點存在的 edge-index／face-center／face-normal／差向量／點積暫存陣列的長度 SHALL 不超過 chunk size，SHALL NOT 等於模型的總 interior edge 數

#### Scenario: 暫存工作集量級與模型規模無關
- **WHEN** 分別對 edge 數相差一個數量級以上的兩個模型執行分批處理
- **THEN** 兩次執行中，分批處理自身產生的暫存陣列大小量級 SHALL 相近（由固定 chunk size 決定），SHALL NOT 隨兩模型的 edge 數比例放大

### Requirement: 效能量測方法論

驗證本項改動的效能改善時，SHALL 以多次執行的 median 作為主要結論，MUST NOT 以單次或最小值（minimum）作為主要結論；min/max/IQR SHALL 一併記錄以呈現量測噪聲。Chunk 建立、face-index array 轉換、gather、accumulation 的成本 SHALL 全部計入量測範圍，MUST NOT 被排除在計時邊界之外。本階段改動相對現行（Phase 1＋Round 2＋A2）版本的效能改善 SHALL 標示為相對此一 baseline 的增量改善，MUST NOT 與其他 session 量測的百分比直接相加宣稱為累積改善。

#### Scenario: median 為主要結論
- **WHEN** 報告本項改動的效能改善數字
- **THEN** SHALL 以多次獨立執行（至少 7 次）的 median 作為主要結論，並同時列出 min、max、IQR

#### Scenario: 改善幅度的比較基準明確標示
- **WHEN** 報告本項改動的效能改善百分比
- **THEN** SHALL 明確標示該百分比是相對於「Phase 1＋Round 2＋A2」版本的增量改善，MUST NOT 與其他階段的改善百分比直接相加宣稱為相對最原始版本的累積改善


## Why

目前後端只有兩條支撐路徑：前端上傳一整包已成形的 `support.stl`（`--import-support-stl`），或後端依一組全域參數自動生成支撐樹。前者把責任完全推給前端，後端無從驗證；後者代表**所有支撐柱共用同一組尺寸**，無法針對受力大的區域加粗、對表面敏感的區域減細。

更根本的缺口是：後端與底層之間**沒有任何傳遞「支撐點」本身的管道**。底層算出的支撐點只存在於行程記憶體中，切完就消失；外部也無法把一份自訂的支撐點清單餵給引擎。少了這條雙向通道，「使用者調整個別支撐柱」這個需求在架構上根本無法成立。

本變更打通後端 API 與底層切片核心之間的支撐點雙向介面，並讓每個支撐點攜帶自己的幾何尺寸。範圍僅限後端（`web_slicer_core`）與底層（`third_party/prusaslicer_fork`）；前端 UI（`DS-Online`）本次不改動，但資料結構與介面須為未來 UI 預留擴充性與向前相容性。

目標業務閉環分三階段：

```
階段一  後端算出預設支撐點  →  匯出給前端
階段二  前端視覺化編輯（加點、刪點、調整個別尺寸）   ← 本次不實作
階段三  前端送回最終點清單  →  後端依清單長出支撐結構
```

## What Changes

### 底層資料結構

- `sla::SupportPoint` 新增 6 個每點幾何欄位，連同既有的 `head_front_radius` 共 **7 個獨立幾何尺寸欄位**：`head_front_radius`、`head_back_radius_mm`、`head_width_mm`、`head_penetration_mm`、`contact_sphere_radius`、`base_radius_mm`、`support_bracing_angle_deg`。
- Fallback 語意統一，但**僅適用於 6 個新擴充欄位**：`>= 0` 套用該點自訂值，`< 0`（哨兵值 `-1`）或未提供則回退至全域預設。
- **`head_front_radius` 為既有實值欄位，不納入哨兵機制**。底層的 `prepare_permanent_support_points()`（`SLAPrintSteps.cpp`）已把該欄位的 `-1` 用作「標記刪除」旗標，並以 `sqr(head_front_radius)` 當作貼面距離容差。若讓它兼作哨兵，一個未指定頭部半徑的點會被靜默刪除。任何填寫 `SupportPoint` 的路徑（含 JSON 匯入）一律須寫入解析後的具體半徑，不得寫入 `-1`。
- **`contact_sphere_radius` 於本 fork 為保留欄位**。此 fork 的 `libslic3r` 中不存在接觸球幾何，也沒有對應的全域設定，因此該欄位目前無任何消費點（no-op）。仍納入資料結構、序列化與交換格式，使呼叫端設定的值能原樣往返，待日後底層具備該幾何時即可生效。
- `contact_sphere_radius` 的 `0` 是實值（代表「此點不使用接觸球」），**不得**被當成未設定處理。
- **刻意與桌面版分歧**：解除 `base_radius_mm` 與 `support_bracing_angle_deg` 僅在 `type == manual_add` 時生效的限制。7 個欄位一律只看值、不看點的來源類型。自動生成點（`island` / `slope`）與手動新增點一視同仁。此分歧須明確記錄，避免未來與 PhrozenOrca 合併時被誤認為缺陷。
- **排除** `pillar_radius` 與 `weight` 兩個欄位。經查證，兩者在 `libslic3r` 中對切片幾何完全沒有作用（實際柱徑由 `head_back_radius_mm` 決定；`weight` 僅供桌面版 UI 顯示，且未寫入 3MF）。後端介面不傳遞這兩個欄位。

### 底層 CLI 雙向介面

- 新增 `--export-support-points <path>`：讓 SLA 管線停在 `slaposSupportPoints` 步驟（沿用既有的 `TaskParams::to_object_step` 機制），取出計算結果後匯出 JSON。跳過長樹、底筏、切支撐與光柵化。
- 新增 `--import-support-points <path>`：讀入 JSON，填入 `ModelObject::sla_support_points` 並將 `sla_points_status` 設為 `UserModified`，使既有的引擎分支直接採用傳入的點而不重新自動計算。
- 兩個新參數與 `--import-support-stl` **互斥**：同時提供時須明確報錯退出，不得靜默忽略其一。

### 座標系與匯出策略

- **Object Space 反算**：底層計算出的支撐點位於套用 `trafo` 後的世界座標。匯出前須乘上 `trafo` 逆矩陣，轉回「上傳的那份 STL 的座標系」。匯入方向不做任何轉換，由引擎既有流程自行套用 `trafo`。合約可歸納為一句話：點的座標永遠與上傳的 STL 同一座標系。
- **匯出凍結實值**：匯出時 7 個尺寸欄位一律填入當下全域預設的具體數值，不寫哨兵值。此舉對齊桌面版 `sla-support-auto-point-top-field-freeze` 規範，使點清單自我描述，並確保階段二調整全域參數不會在背後改變已生成點的幾何。
- 哨兵值 `-1` 與「缺少 key」僅保留於**輸入**方向，服務兩個用途：前端手動新增點時只給座標、以及未來新增欄位時的向前相容。
- 支撐尺寸維持**絕對毫米值**，不隨模型 scale 縮放。

### 交換格式

- CLI 交換格式採用**具名 key 的 JSON**（含格式版本欄位），而非 3MF 沿用的位置固定浮點數序列。理由：3MF 格式為新增欄位已累積至 version 5 與六段近乎重複的解析分支；具名 key 為可加式，新欄位不需版本爆炸。
- 既有的 3MF 與 cereal 序列化路徑不受本變更影響。

### 模型指紋校驗

- 匯出的 JSON 攜帶一枚**模型指紋**，由三角面數、量化後的包圍盒與頂點座標校驗和組成。指紋於模型載入後、自動排版前計算，因此只描述模型本身，不受平台尺寸或 `center` 參數影響。
- 匯入時後端重算指紋並比對。不符即**直接拒絕**並回傳 `SUPPORT_POINTS_MODEL_MISMATCH`，禁止靜默長出錯位支撐。
- 採用指紋而非列舉操作類型（平移／旋轉／挖空／打孔），原因是後端為無狀態的一次性行程，只看得到 STL 位元組，無從得知使用者執行了哪種操作。指紋讓失效規則可由後端自我執行，不依賴前端配合。
- 已知取捨：現行前端將世界座標烘焙進上傳的 STL（`STLExporter` world-space baked），因此**純平移亦會改變指紋而導致支撐點作廢**。此為刻意選擇的安全側行為。未來前端若改為上傳 local-space STL 並另行傳遞 transform 矩陣，平移將自然不改變指紋，後端無須修改即可平滑升級。

### 後端 API

- 支撐生成流程須能將底層匯出的支撐點清單回傳給呼叫端。
- 切片與支撐生成流程須能接受呼叫端提供的自訂支撐點清單，並轉交底層。
- 指紋不符時須依既有的錯誤碼分類慣例回報 `SUPPORT_POINTS_MODEL_MISMATCH`，`retryable` 為 false。

## Capabilities

### New Capabilities

- `per-point-support-geometry`：底層 `sla::SupportPoint` 的 7 個獨立幾何尺寸欄位、6 個新擴充欄位的 `-1` 哨兵值與全域預設 fallback 語意、`head_front_radius` 不納入哨兵機制的例外、`contact_sphere_radius` 的 `0` 實值語意，以及「生效範圍不受點類型限制」的規則。
- `support-point-interchange`：`--export-support-points` 與 `--import-support-points` 兩個 CLI 介面、共用的 JSON 交換格式與版本規則、Object Space 座標反算合約、匯出凍結實值策略，以及與 `--import-support-stl` 的互斥。
- `support-point-model-fingerprint`：模型指紋的組成、計算時機（載入後、排版前）、比對規則與不符時的拒絕行為。
- `support-point-api`：後端 HTTP 介面如何回傳與接收支撐點清單、與既有支撐生成／切片流程的銜接。

### Modified Capabilities

- `support-generation-error-codes`：新增 `SUPPORT_POINTS_MODEL_MISMATCH` 錯誤碼及其歸因規則（不可重試、須明確拒絕而非降級）。

## Impact

### 底層（`third_party/prusaslicer_fork`）

- `src/libslic3r/SLA/SupportPoint.hpp` — 新增每點幾何欄位與 fallback 解析輔助函式。
- `src/libslic3r/SLA/DefaultSupportTree.cpp` — 支撐頭與支撐柱幾何改讀每點值，解除點類型限制。
- `src/CLI/ProcessActions.cpp` — 新增兩個 action 的處理、停步邏輯、互斥檢查。
- `src/libslic3r/PrintConfig.cpp` — 註冊兩個新的 CLI 參數。
- `src/libslic3r/SLAPrint.cpp` / `SLAPrintSteps.cpp` — 匯出所需的存取路徑（`get_support_points()` 已存在）與匯入後的狀態設定。

### 後端（`web_slicer_core/agent`）

- `sla_operations.py` — CLI 指令組裝、新增匯出／匯入的操作路徑。
- `api_v2.py` — 支撐點清單的回傳與接收。
- `errors.py` / `support_classifier.py` — 新增錯誤碼與歸因。

### 不在本次範圍

- 前端 UI（`D:\repos\DS-Online`）不改動。階段二的視覺化編輯留待後續變更。
- 桌面版（`D:\repos\PhrozenOrca`）不改動。其 `manual_add` 限制維持現狀，分歧記錄於本變更。
- 既有的 3MF / cereal 序列化格式不變。

### 相依與風險

- `third_party/prusaslicer_fork` 子模組目前位於 `release/v1.0.5`，實作前須切換至功能分支。
- 底層與桌面版的程式碼世代不同（`DefaultSupportTree.cpp` 對 `SupportTreeBuildsteps.cpp`、`AABBMesh` 對 `IndexedMesh`），桌面版的既有實作**不可直接複製**，須逐項對位重寫。

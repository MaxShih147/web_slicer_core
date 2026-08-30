## Context

### 現況

後端（`web_slicer_core/agent`）以**一次性子行程**呼叫底層切片核心（`slicer-engine.exe`，由 `third_party/prusaslicer_fork` 建置）。參數透過 INI 檔以 `--load` 傳入，結果透過檔案與 stdout / stderr 上的文字標記讀回（`agent/sla_operations.py:189` 的 `run_prusa_cli`）。兩者之間**沒有函式庫綁定**，agent 內不存在 `ctypes` / `pybind` 之類的呼叫。

因為是一次性行程，後端**不存在跨呼叫的記憶體快取**。桌面版 GUI 那套 `invalidate_step` 的步驟失效判斷在此不適用：每次呼叫都是全新行程、全部重算，所有跨階段狀態都落在 job 目錄的檔案上。

底層目前既沒有「只計算並匯出支撐點」的介面，也沒有「載入外部支撐點」的介面。`--export-3mf` 在 `process()` **之前**執行（`src/CLI/ProcessActions.cpp:385`），匯出的是輸入模型既有的點，不是計算結果。

### 已存在、可直接利用的機制

本變更能大幅縮減新程式碼量，因為底層已具備四個現成的接點：

- **注入接點**：`SLAPrint::Steps::support_points()` 在 `src/libslic3r/SLAPrintSteps.cpp:873` 已有分支，當 `mo.sla_points_status == PointsStatus::UserModified` 時直接採用 `po.transformed_support_points()` 而跳過自動計算。
- **讀取接點**：`SLAPrintObject::get_support_points()`（`src/libslic3r/SLAPrint.cpp:1267`）已可取得計算結果。
- **停步機制**：`PrintBase::TaskParams::to_object_step` 為通用機制，既有的 `--export-support-stl` 快速路徑已用它停在 `slaposPad`（`ProcessActions.cpp:568-577`）。
- **每點幾何能力**：`sla::Head` 結構本身已是逐實例參數化（`r_back_mm` / `r_pin_mm` / `width_mm` / `penetration_mm` 皆為成員），支撐柱半徑取自 `head.r_back_mm`。瓶頸只在輸入端與決策端讀的是全域 `cfg`，不在網格生成端。

### 約束

- 前端（`D:\repos\DS-Online`）本次不改動，但介面須為未來 UI 預留向前相容性。
- 前端目前以 `STLExporter` 匯出**世界座標已烘焙**的 STL（`MeshManager.js:2204` 註解明載 "world-space baked"），且後端 API 沒有任何 rotation / scale / translation 參數。因此上傳的 STL 即為唯一座標系。
- `third_party/prusaslicer_fork` 與桌面版 `PhrozenOrca` 為不同世代的 PrusaSlicer（`DefaultSupportTree.cpp` 對 `SupportTreeBuildsteps.cpp`、`AABBMesh` 對 `IndexedMesh`），桌面版實作不可直接複製。

## Goals / Non-Goals

**Goals:**

- 打通後端與底層之間的支撐點雙向通道，使外部可取得引擎計算的支撐點，也可將自訂點清單交回引擎生成支撐。
- 讓每個支撐點攜帶自己的 7 個幾何尺寸，未指定者回退全域預設。
- 建立可由後端自我執行的模型一致性校驗，杜絕靜默長出錯位支撐。
- 交換格式須為可加式，未來新增欄位不需版本爆炸，且舊版呼叫端不受影響。
- 匯出路徑須遠快於現有的 `--export-support-stl`（跳過長樹、底筏、切支撐、光柵化）。

**Non-Goals:**

- 不實作前端 UI 的視覺化編輯（階段二）。
- 不修改桌面版 `PhrozenOrca`。
- 不修改既有的 3MF 與 cereal 檔案格式路徑（後端的 `EXPORT_PROJECT_3MF` 預設為 `False`，僅供除錯，不在關鍵路徑上）。
- 不改變 `--import-support-stl` 既有行為。
- 不引入任何新的第三方相依。

## Decisions

### D1：交換格式採用具名 key 的 JSON，使用 fork 內既有的 nlohmann/json

**決定**：CLI 匯出／匯入使用單一 JSON 檔，欄位以名稱定位，並帶 `version` 整數。函式庫使用 `nlohmann/json.hpp` —— fork 內已存在且已被 `src/libslic3r/CustomParametersHandling.cpp:3` 使用，不引入新相依。

**替代方案與否決理由**：

- *沿用 3MF 的位置固定浮點數序列*：桌面版此格式為了新增欄位已累積至 version 5，`3mf.cpp` 內躺著 v0 至 v5 六段近乎重複的解析迴圈。每加一個欄位就要跳版本、複製一段迴圈。可加式的具名 key 從結構上避免這個問題。
- *Protobuf / MessagePack*：需引入新相依，且犧牲人可讀性；本檔案是除錯時最需要肉眼檢視的東西。
- *CSV*：無巢狀能力，無法承載指紋等 header 欄位。

**格式骨架**：

```json
{
  "version": 1,
  "model_fingerprint": {
    "face_count": 324264,
    "bbox": [minx, miny, minz, maxx, maxy, maxz],
    "vertex_checksum": "..."
  },
  "points": [
    {
      "pos": [x, y, z],
      "type": "slope",
      "head_front_radius": 0.2,
      "head_back_radius_mm": 0.5,
      "head_width_mm": 1.0,
      "head_penetration_mm": 0.4,
      "contact_sphere_radius": 0.0,
      "base_radius_mm": 2.0,
      "support_bracing_angle_deg": 45.0
    }
  ]
}
```

**版本語意**：讀取端遇到未知的 `version` 應拒絕而非猜測；遇到未知的 key 應忽略。這兩條合起來，使「新增欄位」不需要跳版本，而「改變既有欄位語意」才需要。

**`type` 以字串而非浮點數編碼**（`"manual_add"` / `"island"` / `"slope"`），避開 3MF 那套「約等於 1.0 即為 island」的範圍比對編碼。

### D2：座標轉換必須使用 `SLAPrintObject::trafo()` 的逆矩陣，不得自行重組

**決定**：匯出前對每點座標套用 `po->trafo().inverse()`。匯入方向不做任何轉換，由引擎既有流程自行套用 `trafo`。

**為什麼不能自己拼矩陣**：`SLAPrint::sla_trafo()`（`src/libslic3r/SLAPrint.cpp:177`）的內容並不直觀：

- 只取 instance 的 **Z 位移**，不含排版產生的 XY 平移（XY 由 `SLAPrintObject::Instance` 在光柵化階段另行處理）。
- 線性部分為 `relative_correction()` 對角矩陣乘上 instance 的旋轉／縮放 —— 其中 `relative_correction()` **內含收縮補償（shrinkage compensation）**。
- 左手系模型另外乘一個 X 軸鏡射。

任何自行推導的「反向平移」都會漏掉收縮補償與鏡射。使用同一個 `trafo()` accessor 是唯一能保證匯出與匯入嚴格互逆的做法，且未來 `sla_trafo()` 內容再改動也不會破壞這條合約。

**衍生結論**：排版的 XY 平移不在 `trafo()` 內，因此「後端自動排版」本身不會污染支撐點座標。座標的唯一風險來源是前端把平移烘焙進 STL 頂點，而那由 D5 的指紋處理。

**收縮補償的跨階段安全性**：若使用者在階段一與階段三之間調整了收縮參數，`trafo()` 會改變。但因為點以 object space 記錄，它們仍然貼在（縮放後的）模型表面上。這正是選擇 object space 而非 world space 的實質理由。

### D3：匯出路徑停在 `slaposSupportPoints`，沿用既有停步機制

**決定**：新增 action `export_support_points`。當它是唯一被要求的輸出時（未同時要求 `export_sla` / `slice` / `export_gcode` / `export_preview_pngs` / `export_support_stl`），設定 `TaskParams::to_object_step = slaposSupportPoints` 後呼叫 `process()`，接著走訪 `sla_print.objects()` 取 `get_support_points()` 並寫檔。

管線因此停在第五步，跳過其後四步：

```
Assembly -> Hollowing -> DrillHoles -> ObjectSlice -> SupportPoints   <-- 停在這裡
                                                     SupportTree -> Pad -> SliceSupports
```

**替代方案與否決理由**：*讓 `--export-3mf` 在 `process()` 之後再跑一次*，可重用 3MF 既有的支撐點寫出邏輯。否決原因是它會拖著整包 3MF 的寫出成本、綁死在位置固定的浮點數格式上，而且要調整 `export_3mf` 現行的執行時機，風險外溢到與本變更無關的路徑。

**前置步驟不可省略**：`slaposObjectSlice`、`slaposHollowing`、`slaposDrillHoles` 都必須跑完，因為支撐點偵測是基於逐層島嶼分析，而挖空與打孔會改變待分析的幾何。

### D4：匯入必須發生在 `print->apply()` 之前

**決定**：`--import-support-points` 的處理插在模型載入與 `print->apply(model, print_config)` 之間。讀入 JSON 後填入 `ModelObject::sla_support_points`，並將 `ModelObject::sla_points_status` 設為 `PointsStatus::UserModified`。

**與 `--import-support-stl` 的差異**：後者刻意放在 `apply()` **之後**（`ProcessActions.cpp:511-513` 註解說明「objects exist」），因為它操作的是已建立的 `SLAPrintObject`。本變更操作的是 `Model` 本身，`apply()` 會依據 model 內容計算步驟失效並複製狀態，因此必須先於它完成。順序寫反會導致點被寫入但 print object 不知情。

### D5：模型指紋以幾何量構成，不用檔案位元組雜湊

**決定**：指紋由三個量組成，對 `ModelObject` 的**原始 mesh 頂點**計算，不套用任何 instance 變換：

- 三角面數
- 包圍盒 min / max，量化至小數第 4 位（0.1 µm）
- 頂點座標校驗和（座標同樣量化後累加，避免浮點加總順序造成不穩定）

**替代方案與否決理由**：

- *上傳 STL 位元組的 SHA-256*：前端重新匯出同一個未變動的模型時，浮點格式化可能產生位元差異，造成**誤判作廢**。誤判會逼使用者重做編輯，代價高於漏判。
- *列舉操作類型（平移／旋轉／挖空／打孔各自訂規則）*：後端是無狀態的一次性行程，只看得到 STL 位元組，**無從得知使用者執行了哪種操作**。以操作類型定義的規則後端無法自我執行，只能被動信任前端，而前端本次不改。

**涵蓋範圍驗證**：平移改變包圍盒位置；旋轉與縮放改變包圍盒形狀或大小；挖空與打孔改變面數；未變動的重新匯出三個量皆不變。對稱物體繞 Z 軸旋轉 180 度這類極端案例由頂點校驗和攔截。

**`vertex_checksum` 演算法決議（任務 4.1）**：採用**量化後累加**，不引入 FNV-1a 或 CRC32 的完整實作。理由：實作成本最低、無任何外部相依、且量化本身已提供對浮點格式化誤差的容忍度。

但累加**必須攜帶順序資訊**，不得是無序加總。理由來自任務 4.6 本身：對稱模型繞 Z 軸旋轉 180 度後，每個頂點都落在另一個頂點原本的位置上，量化後座標的**多重集不變**，只有順序改變。任何無序的加總（含單純的座標總和）對此案例必然回傳相同值，無法滿足「須被攔截」的要求。因此累加式定為：

```
acc = acc * PRIME + quantized_coordinate     // 逐頂點、逐分量，依網格頂點順序
```

此處「多重集不變」在幾何精確對稱時**逐位元成立**（半轉即為 `(x, y) -> (-x, -y)` 的取負，浮點取負無誤差）。若對稱性來自程式生成的近似幾何（例如以 360 段近似的圓柱），少數座標會落在量化格邊界上而跳動一格——實測 1440 個座標中有 2 個。因此單元測試把此前提釘在一份手工建構、座標皆為量化格整數倍的對稱稜柱上，而非釘在生成的圓柱上。

`PRIME` 取 64 位元 FNV 質數 `1099511628211`，此處僅作為混合性良好的大奇數使用，並非採用 FNV-1a 演算法。最後套用一次 splitmix64 finalizer，使最後一個頂點的一單位變動也能擴散至高位元。

**順序相依的前提**：同一份 STL 載入後的頂點順序是決定性的，因此對「同一份未變動的模型重複匯出」不構成問題。

**已知未涵蓋**：本校驗和僅涵蓋頂點座標（規格定義為「頂點座標校驗和」）。若一份網格的頂點座標與面數皆不變、僅三角形索引的連接方式改變（例如四邊形對角線翻轉），指紋不會改變。此類變動不在既有的失效情境（平移／旋轉／縮放／挖空／打孔）之列。

**已知取捨**：現行前端把平移烘焙進 STL 頂點，因此純平移亦會使指紋改變而作廢支撐點。這是刻意選擇的安全側行為。未來前端若改為上傳 local-space STL 並另傳 transform 矩陣，平移將自然不改變頂點，指紋自然不變，**後端與底層無須任何修改即可平滑升級**。

### D6：錯誤以 stderr 的固定英文標記回報，不依賴 exit code

**決定**：指紋不符時，CLI 在 stderr 印出一個獨特且不可翻譯的英文標記，並終止流程（不進入 `process()`）。後端 `agent/support_classifier.py` 新增一條比對規則，將該標記歸因為 `SUPPORT_POINTS_MODEL_MISMATCH`。

**為什麼不看 exit code**：既有的 `support-generation-error-codes` 規範已明定分類器 MUST NOT 將 `returncode` 納入任何分支條件 —— fork 的 `validate()` 失敗會回傳 exit 0。新錯誤必須遵循同一套慣例，否則分類邏輯會出現兩套標準。

**標記須為原始字串字面值**，不得包在 `_u8L()` / `I18N::translate` 內，才不會因語系而失效（既有的 stdout 標記如 `(supports only)` 即為此設計）。

**錯誤碼定義**：於 `agent/errors.py` 新增 factory function，比照既有樣式回傳 `APIError`，`http_status` 為 422、`retryable` 為 `False`。

### D7：C++ 資料結構擴充方式

**決定**：`sla::SupportPoint`（`src/libslic3r/SLA/SupportPoint.hpp`）新增 6 個 `float` 欄位，**接在既有欄位之後**，預設值為哨兵 `-1.f`。同時新增一組 `point_*()` 純函式解析輔助，集中 fallback 判斷，避免各呼叫點各自寫 `>= 0 ? a : b`。

**布局與相容性**：新欄位追加在尾端可讓既有的 aggregate 初始化與位置參數建構子繼續運作。`serialize()`（cereal）須同步加入新欄位，否則任何走 cereal 的路徑會靜默掉資料。`operator==` 亦須納入新欄位，否則變更偵測會漏判。

**哨兵機制的適用範圍僅為 6 個新擴充欄位**：`head_front_radius` 是既有欄位，一律攜帶實值，**不得**納入 `-1` 哨兵機制，因此不提供對應的 `point_*()` 解析函式。理由是 `-1` 在該欄位上已有既存且相衝突的語意：`prepare_permanent_support_points()`（`src/libslic3r/SLAPrintSteps.cpp`）以 `head_front_radius = -1.0f` 標記「此點待刪除」，並在函式結尾以 `head_front_radius < 0.f` 為條件 `remove_if`；同一函式另以 `sqr(p.head_front_radius)` 作為「點是否貼在網格表面」的距離容差。若讓 `-1` 同時代表「未設定」，一個只給座標的手動新增點會被**靜默刪除**，且 `sqr(-1)` 會意外變成 1 mm 的容差。任何填寫 `SupportPoint` 的路徑（含階段 5 的 JSON 讀入）一律須寫入解析後的具體半徑。

**`contact_sphere_radius` 的三態**：小於 0 代表未設定（用預設）、等於 0 代表此點明確不使用接觸球、大於 0 為球半徑。這是唯一一個 `0` 具有實質語意的欄位，所有解析邏輯不得把它與哨兵混為一談。

**`contact_sphere_radius` 在本 fork 為保留欄位（no-op）**：經查證，此 fork 的 `src/libslic3r` 中不存在任何接觸球幾何或設定（`SupportTreeConfig` 無對應欄位、`PrintConfig.cpp` 無對應參數、`DefaultSupportTree` 的前球為固定存在，無可關閉的分支）。因此本變更只把該欄位與其三態解析函式建立起來，不接上任何消費點。三態解析函式 `point_contact_sphere()` 目前無呼叫者，其存在是為了讓「`0` 不等於未設定」這條規則在底層具備該幾何的那天只有一份定義。

**排除的欄位**：`pillar_radius` 與 `weight` 不納入。經追查，桌面版的支撐柱半徑實際取自 `head.r_back_mm`（來源為 `head_back_radius_mm`），`pillar_radius` 在 `libslic3r` 中無任何讀取點，其唯一相關函式 `request_pillar_radius()` 呼叫者為零；`weight` 僅供桌面版 UI 的 L/M/H 按鈕高亮，且未寫入 3MF。兩者都是 UI 狀態，讓引擎背負它們只會製造無主的欄位。

### D8：解除點類型限制，7 個欄位規則一致

**決定**：在 fork 的支撐樹建構流程中，7 個幾何欄位一律只判斷值（大於等於 0 用自訂值，否則用全域預設），不判斷 `SupportPointType`。

**背景**：桌面版對 `base_radius_mm` 與 `support_bracing_angle_deg` 加了 `type == manual_add` 的閘門（`SupportTreeBuildsteps.cpp:495`），其餘五個欄位則無。在本變更的業務流程中，前端編輯的絕大多數是自動生成點（`island` / `slope`），若保留閘門，使用者調整這兩項會被**靜默丟棄**：七項裡五項生效、兩項無效，且無任何錯誤訊息。

**為何不改由前端把編輯過的點標記為 `manual_add`**：`type` 的語意是「這個點的來源」，`is_island()` 在支撐點產生器中另有分支依賴它。拿它兼作「是否被編輯過」的旗標，是把兩個概念塞進同一欄位，會產生連鎖影響。

**對既有輸出的影響**：無。自動生成點的這兩個欄位目前皆為 `-1`，解除閘門後仍走預設，切片結果逐位元相同。

**刻意分歧**：桌面版維持現狀不改。此差異須在程式碼註解中明確標示，避免未來合併時被誤認為缺陷。

### D9：互斥檢查

**決定**：`--import-support-points` 與 `--import-support-stl` 同時提供時，於參數檢查階段即報錯退出，不得靜默忽略其一。

**理由**：`SLAPrint::Steps::support_points()` 開頭有 `if (po.has_imported_support()) return;`（`SLAPrintSteps.cpp:851`），匯入支撐網格會使整個支撐點步驟被跳過。若容許兩者並存，使用者提供的點清單會無聲消失。

`--export-support-points` 與 `--import-support-stl` 同時提供時亦然：前者會匯出一份空清單，同樣具誤導性。

### D10：後端 agent 串接

**資料流**：

```
階段一   呼叫端觸發支撐點計算
         agent 組裝 CLI 加上 --export-support-points <job>/output/support_points.json
         run_prusa_cli -> 讀檔 -> 回傳 JSON 給呼叫端

階段二   前端編輯（本次不實作）

階段三   呼叫端帶入點清單
         agent 落地為 <job>/input/support_points.json
         組裝 CLI 加上 --import-support-points <job>/input/support_points.json
         指紋不符 -> stderr 標記 -> classifier -> SUPPORT_POINTS_MODEL_MISMATCH
```

**檔案落地位置比照既有慣例**：輸入落在 `<job>/input/`（與 `support.stl` 同層），輸出落在 `<job>/output/`（與 `model_support.stl` 同層）。

**`OperationType` 與 `OperationResult`**：新增匯出支撐點的操作類型，`OperationResult` 新增對應的路徑欄位，比照既有的 `support_mesh_path` / `hollow_mesh_path` 樣式。

**層高沿用既有優化**：支撐點偵測走 `SUPPORT_DETECTION_LAYER_HEIGHT`（0.15 mm，`sla_operations.py:78`）的粗層高路徑。這不影響凍結的尺寸值，只影響點的位置；而階段三使用的是傳回來的點、不再重算，因此兩階段不會不一致。

**`supports_enable` 必須為真**：`support_points()` 在 `supports_enable` 為假時直接 return（`SLAPrintSteps.cpp:854`）。匯出路徑須比照既有 `generate_supports()` 強制開啟。

### D11：匯出時凍結實值

**決定**：匯出的每一點，7 個尺寸欄位一律寫入**當下全域預設解析後的具體數值**，不寫哨兵。哨兵 `-1` 與「缺少 key」僅在**輸入**方向有意義。

**理由**：對齊桌面版 `sla-support-auto-point-top-field-freeze` 規範。凍結使點清單自我描述 —— 呼叫端不需要另外取得一份全域設定再自行複製一次 fallback 邏輯（那份複製品必然會與 C++ 端逐漸分岔），且階段二調整全域參數不會在背後改變已生成點的幾何。

**代價**：JSON 體積增加（500 點約 50 KB 量級），以及「改全域參數即全部套用」的便利性消失，使用者須重新觸發生成。桌面版即為此行為。

## Risks / Trade-offs

**[兩邊程式碼世代不同，桌面版實作無法複製]** -> 底層改動須逐項對位重寫，並以桌面版的既有規範（`sla-support-param-wiring`、`sla-support-head-penetration`、`sla-support-auto-point-top-field-freeze`）作為行為對照，而非以其原始碼作為複製來源。所有刻意分歧須寫入註解。

**[子模組目前位於 `release/v1.0.5` 且有未提交改動]** -> 實作前先切換至功能分支並處理現有的 CMakeLists 改動，避免功能開發污染 release 分支。

**[純平移即作廢，使用者體驗上偏嚴格]** -> 這是刻意選擇的安全側行為：支撐長錯位置會直接導致列印失敗，且使用者無從得知原因。錯誤碼須攜帶足以讓前端顯示「模型已變更，請重新產生支撐」的訊息。前端改為 local-space 上傳後此限制自然解除。

**[指紋量化門檻可能過鬆或過緊]** -> 量化至 0.1 µm 遠低於任何實際列印解析度，同時足以吸收浮點格式化誤差。若日後發現誤判，調整的是門檻常數而非架構。

**[凍結策略使 JSON 體積隨點數線性成長]** -> 數千點量級下仍在數百 KB，對本地 HTTP 與檔案 I/O 無實質影響。若未來點數量級上升，可在格式版本 2 引入「共用預設區塊加上每點差異」的壓縮表示，屬可加式演進。

**[新增欄位若遺漏同步 `serialize()` 或 `operator==`]** -> 前者導致資料靜默遺失、後者導致變更偵測漏判，兩者都不會產生編譯錯誤。須以測試覆蓋：往返序列化後逐欄位比對，以及單一欄位差異須使 `operator!=` 為真。

**[停在 `slaposSupportPoints` 的路徑未被既有測試覆蓋]** -> 新的停步點可能暴露既有步驟間的隱含相依（例如某步驟預期 `slaposSupportTree` 已初始化某狀態）。須以實際模型驗證匯出路徑可完整結束且不留下半初始化狀態。

## Migration Plan

本變更為**純新增**：兩個新 CLI 參數、`SupportPoint` 尾端追加欄位、一個新錯誤碼。不提供任一新參數時，所有既有路徑行為不變。

- **既有呼叫端**：未使用新參數者完全不受影響，`--import-support-stl` 與 `--export-support-stl` 路徑行為不變。
- **回歸基準**：以同一份模型與參數，比對變更前後 `.sl1` 的逐層 SHA-256 與 `layer_count` / `resin_volume_ml` / `estimated_print_time`，須完全一致。此基準沿用 `imported-support-sanitization` 已建立的驗證方式。
- **回滾**：底層與後端的改動彼此獨立可回滾。後端不送新參數即等同關閉功能，無須回滾底層。

## Open Questions

- ~~指紋的 `vertex_checksum` 具體演算法（量化後累加、FNV-1a、或 CRC32）尚未定案。~~ **已決議（任務 4.1）**：採用量化後累加，且累加須為順序相依。詳見 D5 的「`vertex_checksum` 演算法決議」段落。
- ~~多物件（`sla_print.objects()` 含一個以上物件）情境下 JSON 的組織方式。~~ **已決議（任務 9.8）**：維持單一扁平 `points` 陣列，多物件維度以**可加式的選用鍵**預留，不改動任何既有鍵的意義。詳見下方「多物件組織方式決議」。

## 多物件組織方式決議（任務 9.8）

**現況**：格式為 `{version, model_fingerprint, points: [...]}`，單一扁平陣列。CLI 於匯出前明確拒絕多物件輸入（實測：兩份模型時 `error: --export-support-points handles a single input model; 2 were given`，離開碼 1，不產生任何輸出檔）。

**決議**：**維持扁平陣列**。日後支援多物件時，以兩個選用鍵擴充，而非改變結構：

- 每點新增選用的 `object_id`（整數）。**缺鍵即代表 `0`**。
- 頂層新增選用的 `model_fingerprints`（`object_id` 對指紋的映射）。**缺鍵即代表 `{0: model_fingerprint}`**。

**理由**：

1. **不需跳版本**。格式版本的既定規則是「既有鍵的意義改變才跳版本；新增鍵不必跳版本，因為讀入端忽略未知鍵，且缺鍵本身已有定義好的意義」。上述兩個鍵都符合：缺席時的語意與今日的單物件行為完全等價。
2. **改為 `objects` 字典則必須跳版本**。若把 `points` 移到 `{objects: {"0": {model_fingerprint, points}}}` 之下，`points` 這個既有鍵的位置與意義都變了，所有既有讀入端立刻失效——這正是版本規則要避免的情況。
3. **單物件是壓倒性多數的情況**。API 將 JSON 原文回傳給呼叫端，前端編輯支撐點時不應為了 99% 的單物件情形先拆一層字典。
4. **與底層的消費方式一致**。`ModelObject::sla_support_points` 本來就是逐物件的，CLI 亦已走訪 `sla_print.objects()`；以每點欄位分派只需一次 partition，不需要改變檔案骨架。

**代價**：多物件時每點多出一個小整數欄位，體積影響可忽略。真正的成本是「缺鍵即 0」這個約定必須寫死在讀入端並以測試釘住，否則日後容易被誤解為「未指定」。

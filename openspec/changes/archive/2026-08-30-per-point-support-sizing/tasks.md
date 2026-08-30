## 1. 準備工作與回歸基準

- [x] 1.1 將 `third_party/prusaslicer_fork` 子模組由 `release/v1.0.5` 切換至功能分支，並處理現有未提交的 `.gitignore` 與兩份 `CMakeLists.txt` 改動
- [x] 1.2 以現行程式碼建置一次 `slicer-engine`，確認基準可建置
- [x] 1.3 選定至少兩份回歸用模型（一份需支撐、一份自撐），以固定參數各切一次，記錄 `.sl1` 的逐層 SHA-256 與 `layer_count` / `resin_volume_ml` / `estimated_print_time` 為基準檔
- [x] 1.4 驗證檢查點：重跑同一組切片，產出與基準檔逐層雜湊完全一致（證明基準本身可重現）

## 2. 底層 C++ 資料結構與輔助函式

- [x] 2.1 於 `src/libslic3r/SLA/SupportPoint.hpp` 的 `sla::SupportPoint` 尾端新增 6 個 `float` 欄位（`head_back_radius_mm`、`head_width_mm`、`head_penetration_mm`、`contact_sphere_radius`、`base_radius_mm`、`support_bracing_angle_deg`），預設值為哨兵 `-1.f`
- [x] 2.2 新增哨兵常數與一組 `point_*()` 純函式解析輔助，集中「大於等於 0 用自訂值，否則用全域預設」的判斷。適用範圍僅為 6 個新擴充欄位；`head_front_radius` 為既有實值欄位，不提供解析函式（其 `-1` 在 `SLAPrintSteps.cpp` 為刪除標記）
- [x] 2.3 為 `contact_sphere_radius` 實作三態解析（小於 0 用預設、等於 0 明確關閉、大於 0 為半徑），確保沒有任何呼叫點使用「小於等於 0 即未設定」的判斷式
- [x] 2.4 將 6 個新欄位納入 cereal `serialize()`
- [x] 2.5 將 6 個新欄位納入 `operator==`
- [x] 2.6 驗證檢查點：`libslic3r` 編譯通過；新增單元測試涵蓋序列化往返後逐欄位相等、單一欄位差異使 `operator!=` 為真、以及三態解析的三個分支

## 3. 底層每點幾何生效

- [x] 3.1 於 `src/libslic3r/SLA/DefaultSupportTree.cpp` 將支撐頭的後球半徑、連接段長度、穿透深度改為經 `point_*()` 解析，取代直接讀 `m_sm.cfg`。**接觸球半徑不在本任務範圍**：`contact_sphere_radius` 於本 fork 為保留欄位（no-op），底層既無接觸球幾何亦無對應全域設定，`point_contact_sphere()` 目前不接任何呼叫點
- [x] 3.2 將底座半徑與支撐角度改為經 `point_*()` 解析，並解除任何 `type == manual_add` 的閘門判斷
- [x] 3.3 於解除閘門處加註解，明確記錄此為與桌面版 `PhrozenOrca` 的刻意分歧及其理由，避免未來合併時被誤認為缺陷
- [x] 3.4 驗證檢查點：新增單元測試涵蓋單點加粗不影響鄰柱、三點各設不同柱徑、`island` 點的底座半徑生效、`slope` 點的支撐角度生效
- [x] 3.5 驗證檢查點：以任務 1.3 的模型與參數重切，`.sl1` 逐層 SHA-256 與統計數值須與基準檔完全一致（所有欄位皆為哨兵時輸出不得改變）

## 4. 模型指紋演算法

- [x] 4.1 決議 `vertex_checksum` 的具體演算法（量化後累加 / FNV-1a / CRC32），將選擇與理由寫回 `design.md` 的 Open Questions
- [x] 4.2 實作指紋計算函式：三角面數、量化至 0.1 µm 的包圍盒 min 與 max、量化後的頂點座標校驗和；對 `ModelObject` 原始網格計算，不套用任何 instance 變換
- [x] 4.3 實作指紋的序列化表示與比對函式
- [x] 4.4 驗證檢查點：單元測試涵蓋不同 `center` 下指紋相同、同一網格重複計算指紋相同、單一 float 最低有效位差異不改變指紋
- [x] 4.5 驗證檢查點：單元測試涵蓋平移 5 mm、繞 Y 軸旋轉 15 度、縮放 1.1 倍、面數改變、單一頂點位移 1 µm 五種變動皆使指紋不同
- [x] 4.6 驗證檢查點：單元測試涵蓋對稱模型繞 Z 軸旋轉 180 度（包圍盒與面數皆不變）仍被頂點校驗和攔截

## 5. 底層 JSON 讀寫

- [x] 5.1 定義交換格式的版本常數與 key 名稱常數，集中於單一標頭，避免字串散落
- [x] 5.2 實作寫出：以 `nlohmann/json` 產生含 `version`、`model_fingerprint`、`points` 的檔案；`type` 以字串編碼；7 個尺寸欄位一律寫入解析後的具體數值（凍結）；不得輸出 `pillar_radius` 或 `weight`
- [x] 5.3 實作讀入：未提供的 6 個擴充尺寸 key 填入哨兵 `-1`；未提供的 `head_front_radius` 須填入全域預設的具體數值（**不得填 `-1`**，該值在 `prepare_permanent_support_points()` 代表標記刪除）；未知 key 忽略；無法辨識的 `version` 拒絕載入並回報錯誤
- [x] 5.4 驗證檢查點：單元測試涵蓋寫出後讀回的往返一致、三種 `type` 字串往返不變、匯出內容不含哨兵值、匯出內容不含 `pillar_radius` 與 `weight`
- [x] 5.5 驗證檢查點：單元測試涵蓋只含 `pos` 與 `type` 的點讀入後 6 個擴充欄位皆為 `-1` 且 `head_front_radius` 為全域預設的非負值、含未知 key 的檔案可成功載入、未知 `version` 被拒絕

## 6. 底層 CLI 匯出、匯入與停步邏輯

- [x] 6.1 於 `src/libslic3r/PrintConfig.cpp` 註冊 `export_support_points` 與 `import_support_points` 兩個參數，比照既有 `import_support_stl` 的樣式
- [x] 6.2 於 `src/CLI/ProcessActions.cpp` 加入互斥檢查：`--import-support-points` 或 `--export-support-points` 與 `--import-support-stl` 同時出現時，於執行切片前報錯並終止，不得產生任何輸出檔案
- [x] 6.3 實作匯入路徑：讀入 JSON、比對指紋、填入 `ModelObject::sla_support_points`、將 `sla_points_status` 設為 `UserModified`。整段處理須置於 `print->apply(model, print_config)` **之前**
- [x] 6.4 實作指紋不符的處理：於 stderr 印出一個不可翻譯的英文標記字串並終止，不進入 `process()`，不降級為自動生成支撐點
- [x] 6.5 實作匯出路徑的停步邏輯：當 `export_support_points` 為唯一輸出時設定 `TaskParams::to_object_step = slaposSupportPoints`，比照既有 `--export-support-stl` 停在 `slaposPad` 的樣式
- [x] 6.6 實作匯出寫檔：走訪 `sla_print.objects()`，取 `get_support_points()`，以 `po->trafo().inverse()` 轉回輸入模型座標系後寫出 JSON。座標轉換須使用 `trafo()` accessor 本身，不得自行重組矩陣
- [x] 6.7 驗證檢查點：`slicer-engine` 建置通過
- [x] 6.8 驗證檢查點：CLI 端對端手動驗證——匯出產生非空 JSON 且不產生支撐 STL 與 `.sl1`；同時給互斥參數時報錯終止；以不同模型匯入時印出指紋不符標記並終止

## 7. 後端 Python Agent 串接

- [x] 7.1 於 `agent/sla_operations.py` 新增匯出支撐點的 `OperationType`，並於 `OperationResult` 新增對應路徑欄位，比照既有 `support_mesh_path` 樣式
- [x] 7.2 實作匯出操作：強制 `supports_enable` 為真、組裝 `--export-support-points <job>/output/support_points.json`、沿用既有的粗層高偵測設定
- [x] 7.3 實作匯入串接：將呼叫端提供的清單原樣落地為 `<job>/input/support_points.json`（不得補值或改寫），並於支撐生成與切片指令中加上 `--import-support-points`
- [x] 7.4 於 `agent/api_v2.py` 讓呼叫端可取得匯出的支撐點清單，回傳內容須為底層 JSON 原文
- [x] 7.5 於 `agent/api_v2.py` 讓呼叫端可在支撐生成與切片流程中提供自訂支撐點清單
- [x] 7.6 驗證檢查點：新增 pytest 測試，以 stub 掉的 `run_prusa_cli` 斷言指令組裝正確、`supports_enable` 被強制開啟、輸入落在 `input/`、輸出落在 `output/`、後端未對清單補值

## 8. 錯誤分類與回報

- [x] 8.1 於 `agent/errors.py` 新增 `SUPPORT_POINTS_MODEL_MISMATCH` 的 factory function，`http_status` 為 422、`retryable` 為 `False`
- [x] 8.2 於 `agent/support_classifier.py` 新增指紋不符標記的比對規則，順序須早於 fail-closed 的 `SUPPORT_GENERATION_FAILED`
- [x] 8.3 將指紋不符的標記字串納入既有的契約 / golden 測試，使該字串被更動時測試失敗
- [x] 8.4 驗證檢查點：新增 pytest 測試涵蓋指紋不符歸因為專屬代碼、不落入 `SUPPORT_GENERATION_FAILED`、不被誤判為 `SUPPORT_NOT_NEEDED`、以及 `returncode` 為 0 時仍能正確歸因

## 9. 整合與回歸測試

- [x] 9.1 端對端閉環驗證：對真實模型執行匯出、原樣匯入、生成支撐，確認支撐網格與同參數自動生成的結果幾何一致
- [x] 9.2 每點尺寸端對端驗證：修改匯出清單中單一點的 `head_back_radius_mm` 後匯入，確認僅該根支撐柱變粗
- [x] 9.3 凍結策略端對端驗證：匯出後調整全域柱徑再匯入，確認所有支撐柱維持匯出當時的直徑
- [x] 9.4 收縮補償往返驗證：以非 100% 的收縮補償參數執行匯出再匯入，確認支撐頭仍貼合模型表面而未偏移或浮空
- [x] 9.5 既有路徑回歸：以任務 1.3 的基準檔比對，未使用任何新參數的完整切片產出須逐層位元一致
- [x] 9.6 匯入支撐網格路徑回歸：`--import-support-stl` 流程的 `.sl1` 產出須與基準檔逐層位元一致
- [x] 9.7 效能驗證：同一模型下 `--export-support-points` 的耗時須明顯低於 `--export-support-stl`
- [x] 9.8 決議多物件情境的 JSON 組織方式（`object_id` 維度），將結論寫回 `design.md` 的 Open Questions
- [x] 9.9 驗證檢查點：`openspec validate per-point-support-sizing` 通過，且所有 spec 場景皆有對應的測試或已記錄的手動驗證結果

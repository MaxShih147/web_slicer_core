## Context

本輪調查的對象是 Ortho Auto Process 一鍵處理 Step 1 呼叫的 C++ Hollow（PrusaSlicer fork 的 `--export-hollow-stl` CLI 動作，[third_party/prusaslicer_fork/src/CLI/ProcessActions.cpp:390-457](../../../third_party/prusaslicer_fork/src/CLI/ProcessActions.cpp#L390-L457)）。調查全程使用固定的 production Hollow 參數（`hollowing_min_thickness=3.0`、`hollowing_quality=0.5`、`hollowing_closing_distance=2.0`，[agent/api_v2.py:154-156](../../../agent/api_v2.py#L154-L156) 的一鍵處理預設值），未測試或修改這些參數本身。

為避免與檔名綁定、聚焦於「用途」本身，本文件以下列代稱指稱調查中使用的代表模型（皆為 production 已確認會進入 Hollow 分支的一般完整基座正畸模型，經 `clean_input_for_manifold()` 清理後輸入）：

- **小面數代表模型**：清理後約 3.2 萬面。
- **中面數代表模型**：清理後約 16.7 萬面。
- **高面數壓力測試模型**：清理後約 102.5 萬面，面數遠高於本輪其他代表模型，用於 C++ 子階段拆時與 prototype A/B（因其面數與內部退化面數量足以放大子階段耗時差異，較容易觀察到否則會被雜訊淹沒的效果）。**來源**：使用者確認此模型是以既有牙科模型拆分三角面、人工增面而成，但無法確認是哪一個原始模型；實測比對此模型與 `tempTest` 資料夾中其餘模型的 bounding box／volume，皆不吻合，目前無法將此模型對應到資料夾內任何現存模型，本文件不對原始檔案的去向做任何推斷，也不推測它是由哪一個現存模型拆分而來。其清理後殘留的退化面成因未知（本輪未查證是否與拆分過程有關），也不以此模型的面數或退化面數量，推論一般 production 輸入的面數分布或退化面發生率。
- **三個新增一般完整基座代表模型**：清理後面數約 16.6 萬～23.9 萬（依序約 17.8 萬、16.6 萬、23.9 萬；其中一個略低於中面數代表模型的 16.7 萬面，三者並非全數嚴格介於中面數與高面數壓力測試模型之間），用於重新測試 skip-2nd-exact-check 候選是否有超出高面數壓力測試模型的適用性。

Production 路徑（`run_ortho_pipeline()` → `generate_hollow()` → `run_prusa_cli()` → 依 `agent/config.py` 路徑解析邏輯選定之 executable）已確認單一 Ortho job 對 C++ Hollow 最多呼叫一次：`_is_u_arch_from_low_sections()`（[agent/ortho_pipeline.py:754-818](../../../agent/ortho_pipeline.py#L754-L818)）在呼叫**之前**判斷是否跳過；Hollow-fit 檢查（[agent/ortho_pipeline.py:927-1155](../../../agent/ortho_pipeline.py#L927-L1155)）在 C++ 執行**之後**才判斷，不影響是否呼叫。該路徑解析邏輯（[agent/config.py:33-34](../../../agent/config.py#L33-L34)）優先吃 `SLICER_ENGINE_BIN`／`PRUSA_SLICER_BIN` 環境變數，只有兩者皆未設定時才會走封裝版優先的預設順序；`README.md` 的 Quick Start／Troubleshooting 段落明確教學使用者手動設定 `SLICER_ENGINE_BIN` 指向 dev-tree build（`third_party\prusaslicer_build\...`），若實際部署遵循該教學，使用的就不是封裝版。本輪量測選擇明確清空這兩個環境變數，讓解析結果為封裝版，但這是**本輪量測的選擇**，不是對「所有實際部署環境都使用封裝版」的觀察結果——本輪調查全程未觀察到任何正在執行的 production 後端程序（未偵測到監聽埠、亦無對應程序），無法確認任何實際部署當下的解析結果。

封裝版 executable（`slicer-engine\bin\slicer-engine.exe`）的 manifest 記錄 `engine_commit` 為 **parent repo** 的 `git rev-parse HEAD`（[scripts/package_slicer_engine_windows.ps1:270-282](../../../scripts/package_slicer_engine_windows.ps1#L270-L282)），並未在 `third_party/prusaslicer_fork` submodule 內獨立記錄建置當下的 SHA。因此本輪所有以封裝版量測的 baseline 數字，其 submodule 來源只能靠「目前 submodule 狀態與 parent 記錄的 pointer 一致」做間接推論，SHALL 標示為探索性（exploratory）。

C++ 子階段拆時、OpenVDB 候選驗證與 skip-2nd-exact-check 候選的驗證，皆在隔離環境完成：`git worktree add` 建立於 `C:\hdiag\pf`（detached HEAD，釘在與主 checkout 相同的 submodule pin），獨立建置目錄 `C:\hdiag\build`（重用主 checkout 既有、唯讀的 deps destdir，未修改主 checkout 任何檔案）。該診斷版的編譯器 toolset patch 版本與封裝版實際使用的不同（診斷版 `14.40.33807`、封裝版 `19.40.33813.0` 對應的 toolset），因此診斷版數字與封裝版數字 SHALL 視為不同 binary 的結果，不得直接相減視為正式 production A/B。

## Goals / Non-Goals

**Goals:**
- 把本輪 Ortho Hollow C++ 效能調查（production 路徑、封裝版來源限制、C++ 子階段占比、已否決的 OpenVDB 候選、skip-2nd-exact-check 候選的驗證與最終停止判準）以可追溯、可驗證的 OpenSpec 決策紀錄形式留存。
- 明確記載封裝版 baseline 的來源限制，避免未來把探索性數字誤用為正式基準。
- 明確記載兩個已否決的 OpenVDB 候選及其否決依據，避免未來重複投入同樣已被實測排除的方向。
- 明確記載 skip-2nd-exact-check 候選的完整驗證脈絡（資料狀態條件、受測模型的完整 Hollow STL 輸出逐位元相同、隔離 A/B 結果）與最終停止判準，供未來若有更廣泛適用的輸入分布時重新評估。
- 明確要求區分診斷版與封裝版數字、避免把診斷插樁本身的成本誤植為 production 成本。

**Non-Goals:**
- **不**實作、移植任何 Hollow C++ 效能優化到 production（skip-2nd-exact-check 候選雖已在受測模型上驗證完整 Hollow STL 輸出逐位元相同、並完成隔離 A/B，但依本輪停止判準不予採用；僅高面數壓力測試模型真正觸發過跳過分支，未驗證整條 Ortho pipeline 或任意網格輸入的等價性）。
- **不**重新執行任何 profiling、benchmark 或模型測試（本提案完全基於既有調查資料）。
- **不**變更 `third_party/prusaslicer_fork`、`agent/` 或任何測試檔案。
- **不**修改封裝版 executable、manifest 或既有建置腳本。
- **不**在本提案中新增或修改任何 API、CLI 參數規格。

## Decisions

### D1：封裝版 baseline 數字 SHALL 標示為探索性，不得當作已完全可追溯的正式基準

封裝版 manifest 的 `engine_commit` 只記錄 parent repo 的 HEAD，不記錄 submodule 內部的 SHA（見 Context）。這代表「封裝當下 submodule 確實是目前記錄的 pin」只有間接證據（現況一致），沒有建置當下的直接記錄。選擇不在本輪追加正式的 submodule SHA 記錄機制（例如修改打包腳本），因為這屬於建置流程本身的變更，超出本輪唯讀調查的範圍；本決策僅要求後續引用時明確標示這個限制。

### D2：C++ 子階段耗時分布以 OpenVDB 呼叫鏈為主要熱點，但高面數壓力測試模型的 mesh 載入是例外

拆時涵蓋 CLI 啟動與 mesh 載入、`ProcessActions.cpp` 的 mesh 複製與體積估算、OpenVDB voxelize／redistance／dilate、grid→mesh、結果複製與法線處理、binary STL 寫出。三個代表模型（小面數／中面數／高面數壓力測試）量測結果一致顯示：OpenVDB 的 voxelize／redistance／dilate 呼叫鏈（[third_party/prusaslicer_fork/src/libslic3r/SLA/Hollowing.cpp:81-129](../../../third_party/prusaslicer_fork/src/libslic3r/SLA/Hollowing.cpp#L81-L129)、[third_party/prusaslicer_fork/src/libslic3r/OpenVDBUtils.cpp:105-259](../../../third_party/prusaslicer_fork/src/libslic3r/OpenVDBUtils.cpp#L105-L259)）合計占 Hollow subprocess wall time 約 **76.2%（高面數壓力測試模型）～93.8%（小面數代表模型）**。

其餘子階段（mesh 載入、grid→mesh、STL 寫出、mesh 複製與體積估算）在**小面數／中面數代表模型上個別皆為個位數百分比**（mesh 載入分別約 1.0%／2.8%）。但在**高面數壓力測試模型上，mesh 載入單獨即占約 21.0%**（1,086.85 ms／5,171.7 ms 均值，分母為該模型 Hollow subprocess wall time 的 n=3 平均值），不是個位數，也不能併入「其餘子階段合計占比很小」一概而論。這 21.0% 之中，絕大部分是 `TriangleMesh::ReadSTLFile()` 匯入時的 admesh 修復流程——具體來說就是 D4 討論的兩次 `stl_check_facets_exact()`：高面數壓力測試模型清理後仍殘留約 5,042 個退化面，因此不僅無條件執行的第一次檢查跑了，條件式的第二次檢查也真的被觸發（各約 437～591 ms）。grid→mesh、STL 寫出、mesh 複製與體積估算這幾項在三個模型上則確實都維持個位數百分比。此分布是選擇優先往 OpenVDB 方向調查候選的依據，但 mesh 載入在高面數模型上的例外，也是後續轉往 D4 admesh 修復流程調查的直接線索。

### D3：兩個 OpenVDB 候選已實測並否決，理由記錄以避免重複調查

- **CSG union 對空 grid 的 `clone()`**（[third_party/prusaslicer_fork/src/libslic3r/CSGMesh/VoxelizeCSGMesh.hpp:37-57](../../../third_party/prusaslicer_fork/src/libslic3r/CSGMesh/VoxelizeCSGMesh.hpp#L37-L57)）：懷疑單一 CSGPart 情境下，先建空 grid 再整顆 `clone()` 是可省的深拷貝。實測三個代表模型此步驟成本僅約 2～3 毫秒（占比 <0.15%），假設不成立，否決。
- **`mesh_to_grid()` 內的 `its_split()`**（[third_party/prusaslicer_fork/src/libslic3r/OpenVDBUtils.cpp:105-165](../../../third_party/prusaslicer_fork/src/libslic3r/OpenVDBUtils.cpp#L105-L165)）：懷疑輸入本來就是單一連通分量時，split＋複製＋逐塊 union 是多餘工作。實測確認輸入確實是單一分量（`mesh_to_grid_part_count=1`），但此步驟成本僅約 3.4～75.2 毫秒（占比 0.22%～1.38%，隨面數增加但絕對值仍小），且跳過它會讓後續 `meshToVolume` 收到與現在不同排列順序的三角形資料，等價性風險未經驗證。因潛在報酬過低、風險相對不成比例，否決，不繼續往此方向做等價性驗證或 prototype。

這兩個候選皆為**實測後**否決，不是僅憑程式碼觀感假設「看起來多餘就可以跳過」。

### D4：Skip-2nd-exact-check 候選的資料狀態條件與受測範圍

`TriangleMesh::ReadSTLFile()` 匯入時的修復流程（`trianglemesh_repair_on_import()`，[third_party/prusaslicer_fork/src/libslic3r/TriangleMesh.cpp](../../../third_party/prusaslicer_fork/src/libslic3r/TriangleMesh.cpp)）會呼叫兩次 admesh 的 `stl_check_facets_exact()`：第一次無條件執行；第二次僅在第一次檢查後 `degenerate_facets > 0` 時才條件式執行。逐一追蹤中間步驟（`stl_check_facets_nearby`／`stl_remove_unconnected_facets`／`stl_fix_normal_directions`／`stl_fix_normal_values`／`stl_calculate_volume`／`stl_verify_neighbors`，皆在 `third_party/prusaslicer_fork/bundled_deps/admesh/admesh/`）後確認：

- `stl_check_facets_nearby`／`stl_remove_unconnected_facets`（唯二能新增/刪除面或改變鄰接關係的步驟）被既有程式碼的 `if (connected_facets_3_edge < number_of_facets)` 守衛包住——當網格在第一次檢查後已完全 3-edge-connected（無開放邊）時，結構性地完全不執行。
- 其餘步驟只會重排（reverse winding）既有面的頂點順序或改寫法線值，從不移動頂點座標、從不增減面數，因此不可能新增退化面，也不可能改變鄰接關係的存在性。

由此得出**資料狀態可判定、不依賴檔名或面數**的候選跳過條件（尚未證明對任意網格皆安全，見下方受測範圍）：

```
skip_2nd_check = (connected_facets_3_edge == number_of_facets，第一次檢查後即成立)
                 AND (剛執行完的 stl_verify_neighbors 沒有回報任何邊不一致)
```

**受測範圍**：三個代表模型（小面數／中面數／高面數壓力測試）中，只有**高面數壓力測試模型**在驗證當下 `degenerate_facets > 0`，實際進入了會被跳過的分支、真正測到開關兩種設定下的行為差異；小面數／中面數代表模型的 `degenerate_facets` 皆為 0，開關關／開兩種設定下走的是**同一段程式碼**，兩者的比對結果相同是必然的（vacuous），只能算是「確認開關關閉時不受影響」，不是對跳過條件本身的獨立驗證。此外，本輪所有測試模型在走到判斷點時皆已是 `connected_facets_3_edge == number_of_facets`（無開放邊）的狀態——**沒有任何測試案例是第一次檢查後仍有開放邊的網格**；條件式中要求此項成立，理論上會讓開放邊輸入自動落回「不跳過、照舊執行第二次檢查」，但這部分完全是結構推論，未經任何開放邊網格的實測驗證。

在高面數壓力測試模型上以隔離 `C:\hdiag\pf` 環境對三個時間點（第一次檢查後／第二次前／第二次後）做 FNV-1a 狀態快照比對，確認鄰接圖雜湊在三點完全相同、`stl_verify_neighbors` 回報零不一致，結構分析與實測結果一致。以獨立於診斷插樁的環境變數（`HOLLOW_PROTO_SKIP_2ND_EXACT`）做成可切換 prototype 後，對三個代表模型各以此開關關／開各跑 5 次（另有 1 次不計入平均值的暖機），**完整 Hollow STL 輸出的 SHA-256 逐次、逐模型完全相同**（`C:\hdiag\equiv\ab\` 下尚存的 36 個輸出檔案可重新計算 SHA-256 核對此結論，已於本輪查證時重新驗證一致）；同一份診斷 binary、僅環境變數不同的乾淨計時 A/B（未啟用診斷插樁，避免插樁成本混入）顯示：高面數壓力測試模型平均耗時由約 5.518 秒降至約 5.056 秒，約省 **0.462 秒（8.4%）**，小面數／中面數代表模型（原本就不會觸發第二次檢查）耗時差異在雜訊範圍內。此 A/B 的逐次耗時僅印於終端機、未落地為獨立結果檔，因此均值本身無法脫離本輪對話紀錄重新算出，只有 SHA-256 部分可獨立於對話紀錄重新驗證。

### D5：三個一般完整基座代表模型全數未觸發第二次檢查，依事先議定判準停止

用三個新增的一般完整基座代表模型（清理後面數約 16.6 萬～23.9 萬，見 Context——三者並非全數嚴格介於高面數壓力測試模型與中面數代表模型之間）重跑同樣流程（production 相同的 `clean_input_for_manifold()` 清理，關閉 `HOLLOW_PROTO_SKIP_2ND_EXACT` 保留原始行為）。三個模型第一次檢查後 `degenerate_facets` 皆為 0，且直接核對程式碼層級證據（`proto_skip_2nd_exact` 與 `snap_C_after_2nd_exact_*` 這組診斷標記——兩者皆寫在同一個 `if (degenerate_facets > 0)` 區塊內）確認三個模型的 log 中**完全沒有出現**，證實第二次檢查是結構性地沒有被觸發，不是「執行了但很快」。

依事先議定的停止判準——若新增的一般模型全數不觸發第二次檢查，即判定此優化不予採用——本候選在此判準下**結案，不採用，不移植至 production**。記錄理由：高面數壓力測試模型上驗證有效的節省（0.462 秒／8.4%），其觸發條件（清理後仍殘留數千個退化面）在三個新增的一般完整基座模型上完全沒有出現，代表此候選目前已知的適用範圍過窄，不足以支持投入正式移植與更廣泛的正確性驗證。**此結論不得延伸為「面數較大的一般 production 模型比較容易觸發第二次檢查」或任何關於一般模型面數分布、退化面發生率的推論**——高面數壓力測試模型是使用者以既有模型拆分三角面人工增面而成的合成樣本（見 Context），其殘留退化面的成因未知（可能與拆分過程有關，也可能是原始模型本身既有的瑕疵，本輪未查證）；三個新增模型是本輪**新增的非增面一般樣本**，並非本輪唯一的一般代表模型——小面數／中面數代表模型同樣是未經人工增面的一般完整基座模型，且自調查一開始就已使用，同樣從未觸發過第二次檢查。合計本輪共有 5 個一般模型皆未觸發，樣本數仍然有限，結論的外推力本就有限。

### D6：診斷版數字與封裝版數字 SHALL 明確區分，診斷插樁本身的成本不得誤植為 production 成本

本輪在追蹤 D4 資料狀態時，於 `TriangleMesh.cpp` 加入了一組只在 `HOLLOW_PROF=1` 時才啟用的 FNV-1a 狀態快照（比對第一次檢查後／第二次前／第二次後的鄰接圖與頂點資料雜湊）。此快照**無條件**於「`stl_verify_neighbors` 執行後、第二次檢查判斷式之前」執行，與第二次 `stl_check_facets_exact()` 是否真的執行無關。在三個一般完整基座代表模型的驗證中，此快照本身的計算成本（約 15.8～23.0 毫秒）與第二次檢查的判斷式緊鄰在同一個時間區段內量到，容易被誤讀為「第二次檢查耗時 15.8～23.0 毫秒」——但三個模型的第二次檢查實際上並未執行（見 D5），這段時間 100% 是診斷快照本身的成本，不是 production 會有的成本，也不是第二次檢查的真實耗時。此外，D4／D5 所有診斷版計時數字皆來自 `C:\hdiag\build` 這個獨立建置（不同編譯器 toolset patch 版本、含臨時計時插樁），與封裝版 baseline（`slicer-engine\bin\slicer-engine.exe`）的數字不可直接相減視為同一顆 binary 的前後比較。

## Risks / Trade-offs

- **[風險] Skip-2nd-exact-check 候選未來若在更大規模或更不規則的模型分布上重新評估，目前的資料狀態條件（`connected_facets_3_edge == number_of_facets` 且 `stl_verify_neighbors` 零不一致）可能因輸入特性改變而更常成立 → [緩解] D4 完整記錄該條件的結構性推導與驗證方法，未來若要重新評估，可直接沿用該條件與驗證流程，不需重新從零推導。
- **[風險] 本輪僅高面數壓力測試模型一個案例實際觸發過此分支、且該模型是人工合成的壓力測試樣本（見 Context），加上開放邊輸入完全未測試——若「候選跳過條件」「等價性驗證」等措辭被片段引用，可能被誤讀為已證明對任意網格皆安全 → [緩解] D4 明確標示受測範圍僅此一例、其餘兩模型的比對為 vacuous、開放邊輸入未經實測；spec.md 對應 Requirement 要求引用時附帶同樣限定。
- **[風險] 高面數壓力測試模型驗證出的 0.462 秒／8.4% 節省若被片段引用，可能被誤讀為「Hollow 已有可用優化」，或被誤用來推論一般 production 大面數模型的退化面發生率 → [緩解] D5／Requirement 明確標示此候選因新增一般模型全數未觸發而不予採用、且高面數壓力測試模型的樣本性質不具一般代表性，D6 要求任何引用皆需同時附帶此停止判準。
- **[取捨] 本提案不補做更多一般模型測試即歸檔停案，換取的是「不必為一個已知適用範圍過窄的候選繼續投入正確性驗證資源」；代價是若未來出現大量帶有殘留退化面的一般模型，需要重新評估 → 此為 D5 依使用者事先議定判準做出的刻意範圍取捨，非遺漏。

## Migration Plan

不適用——本提案不變更任何程式碼、API 或部署行為，僅新增決策紀錄型 spec。歸檔（`openspec archive`）後即完成，無需任何部署或回滾步驟。

## Open Questions

- 若未來蒐集到的一般完整基座模型中，有相當比例在清理後仍殘留數千個退化面（觸發第二次檢查的條件），是否應重新評估 skip-2nd-exact-check 候選的移植價值？（本提案不回答，僅留下 D4 的驗證方法與 D5 的停止判準供未來比對。）
- 是否需要在未來某次建置流程調查中，一併補上封裝腳本對 submodule SHA 的獨立記錄（見 D1），讓封裝版 baseline 不再需要標示為探索性？（本提案明確排除於範圍外，見 Non-Goals。）

# 任務清單

> **編譯規則（全域，適用於本檔案每一個階段）**
>
> `third_party/prusaslicer_fork` 的 C++ 編譯**一律由使用者手動執行**。Agent MUST NOT 自行在背景啟動編譯。
>
> 每個階段的驗收檢查點都會明確標示「**⏸ 交給使用者編譯**」。Agent 走到該處必須停下，把要執行的指令交給使用者，等使用者回報結果後才繼續下一步。
>
> 使用者的編譯方式二選一：
>
> - **方式 A（指令稿，建議）**：於 `D:\repos\web_slicer_core` 執行
>   `scripts\build_prusaslicer_fork_windows.bat low`
>   （記憶體 32GB 以上可改用 `full`；需要從頭重建時加 `clean`）
> - **方式 B（Visual Studio 2022 GUI）**：以 VS 2022 開啟 `third_party\prusaslicer_fork` 的 CMake 專案，選擇 `RelWithDebInfo` 組態，建置 `slicer-engine` 目標。
>
> 單元測試同樣由使用者手動建置與執行，目標為 `tests/sla_print` 產出的測試執行檔。

---

## 0. 前置準備

- [x] 0.1 確認 `third_party/prusaslicer_fork` 已切換至功能分支（非 `release/*`），並記錄起始 commit 供回滾。
- [x] 0.2 以**變更前**的引擎，對至少兩個代表性模型（一個含大面積平坦朝下面、一個含連續傾斜曲面）執行完整切片，保存逐層 SHA-256、`layer_count`、`resin_volume_ml`、`estimated_print_time` 作為「舊基準」。此基準僅供比對變化幅度，**不作為通過標準**（見 design.md R1）。
- [x] 0.3 以**變更前**的引擎，對同兩個模型執行 `--export-support-points`，保存匯出的 JSON 作為點數對照。
- [x] 0.4 記錄本次使用的 `support_critical_angle` 數值與 `support_tree_type`，寫入變更資料夾下的驗證筆記，避免後續比對時參數漂移。

---

## 1. 階段一：共用判定函式抽換

- [x] 1.1 於 `src/libslic3r/SLA/SupportTree.hpp` 新增純函式 `passes_overhang_filter(double polar, double threshold)`，置於 `SupportTreeConfig` 與 `ground_level()` 附近。
- [x] 1.2 在該函式上方撰寫註解，載明：判定式的數學推導（`polar >= PI/2 + threshold` 等價於「表面斜度 ≤ 90° − 設定值」）、方向語意（數值越小支撐越多）、以及**與 PhrozenOrca 刻度相反、僅 45° 重合**的刻意分歧宣告。
- [x] 1.3 在 `SupportTreeConfig::overhang_angle_threshold` 欄位旁加註「唯一消費點為 `SLAPrintSteps.cpp` 的 Phase 3」，避免日後清理未使用欄位時被誤刪。
- [x] 1.4 將 `DefaultSupportTree.cpp:491` 的判定式**就地替換**為呼叫 `passes_overhang_filter(polar, m_sm.cfg.overhang_angle_threshold)`（本階段僅替換，尚不刪除）。
- [x] 1.5 將 `SupportTreeUtils.hpp:474` 的判定式**就地替換**為呼叫 `passes_overhang_filter(polar, m.cfg.overhang_angle_threshold)`（本階段僅替換，尚不刪除）。
- [x] 1.6 新增測試檔 `tests/sla_print/sla_overhang_filter_tests.cpp`，並登記至 `tests/sla_print/CMakeLists.txt`。

### 1.R 階段一驗收與 Code Review

- [x] 1.R.1 撰寫函式層級單元測試，涵蓋 spec 場景：完全水平朝下面（門檻 0 / 45 / 90 皆通過）、垂直牆面（僅門檻 0 通過）、斜度 60° 面（門檻 20 通過、門檻 45 剔除）、法線朝上面（一律剔除）。
- [x] 1.R.2 以代數等價形式 `n.z <= -sin(threshold)` 作為**獨立對照**寫一組隨機取樣測試（非邊界值），驗證兩式在非邊界處結果一致。邊界值不納入此對照（浮點最後一個 ulp 不保證相同）。
- [x] 1.R.3 **⏸ 交給使用者編譯**：請使用者以方式 A 或方式 B 建置 `slicer-engine`，並建置與執行 `tests/sla_print` 測試執行檔。回報編譯是否通過、單元測試是否全綠。
- [x] 1.R.4 **⏸ 交給使用者驗證**：以本階段的引擎重跑 0.2 的兩個模型完整切片，逐層 SHA-256 **MUST 與舊基準逐位元相同**。本階段是純重構，任何差異都代表替換出錯，必須先修正才能進入階段二。
- [x] 1.R.5 Code Review：確認 `SupportTree.hpp` 未因新函式而引入任何新的 `#include`；確認三個呼叫端皆未新增 include；確認替換後兩處的 `polar` 飽和運算（`std::max(polar, PI - ...)`）完全未動。

---

## 2. 階段二：Phase 3 過濾實作

- [x] 2.1 於 `src/libslic3r/SLAPrintSteps.cpp` 新增 `#include <libslic3r/Geometry.hpp>` 與 `#include <libslic3r/MeshNormals.hpp>`。
- [x] 2.2 於 `support_points()` 既有的 `switch (cfg.support_tree_type)`（約第 889 行）中，額外解出兩個區域變數：懸空角度（弧度）與法線容差。分派規則依 design.md D3 的對照表：`Default` 一組，走 `support_critical_angle` 與 `support_head_front_diameter / 2`；`Branching` 與 `Organic` 一組，走 `branchingsupport_critical_angle` 與 `branchingsupport_head_front_diameter / 2`。此分組必須複製 `make_support_cfg()`（`SLAPrint.cpp`）的分組（`Branching` 落入 `Organic`），且**刻意不同於**同一個 switch 中 `head_diameter` 的分組（那是 `Default` + `Organic` 一組）。
- [x] 2.3 於 `move_on_mesh_surface()` 呼叫之後、`support_points.insert(... permanent_supports ...)` 之前插入 Phase 3 過濾段落：以 `Slic3r::normals()`（帶 TBB 執行策略、2.2 解出的容差、`throw_if_canceled` 取消回呼）計算全部點的法線，逐點以 `Slic3r::Geometry::dir_to_spheric()` 取 `polar`，再以 `passes_overhang_filter()` 判定去留。
- [x] 2.4 過濾**不得**加入任何短路 guard。即使 `support_critical_angle` 為 0 也一律執行，以保證第 5 步與第 6 步的點集嚴格一致（spec：門檻為 0 度時仍執行過濾）。
- [x] 2.5 在 Phase 3 段落上方撰寫註解，載明插入位置的三項約束：不得早於 `move_on_mesh_surface()`（法線需對貼合後座標計算）、不得晚於 `permanent_supports` 併入（使用者的點不受過濾）、不得晚於 `filter_support_points_by_modifiers()`（enforcer 不得救回角度剔除的點）。
- [x] 2.6 於既有的 `BOOST_LOG_TRIVIAL(debug) << "Automatic support points: "` 之前，補一行 debug 記錄本次過濾前後的點數，方便現場診斷。

### 2.R 階段二驗收與 Code Review

- [x] 2.R.1 **⏸ 交給使用者編譯**：請使用者建置 `slicer-engine`，回報編譯結果。
- [x] 2.R.2 **⏸ 交給使用者驗證**：對 0.3 的兩個模型重跑 `--export-support-points`，比對匯出點數應**少於或等於**變更前，且減少的點應集中在陡峭表面。保存新的 JSON。
- [x] 2.R.3 撰寫整合測試：同一模型分別以 `support_critical_angle` 為 0 / 45 / 90 匯出，驗證點數呈**單調遞減**（0 度最多、90 度最少），對應 spec 的方向語意需求。
- [x] 2.R.4 撰寫測試驗證兩階段的法線容差相等：對同一組態，Phase 3 使用的容差 MUST 等於 `make_support_cfg()` 產出的 `head_front_radius_mm`。
- [x] 2.R.5 撰寫測試驗證分派正確：將 `support_critical_angle` 與 `branchingsupport_critical_angle` 設為不同值，切換 `support_tree_type`，確認過濾結果由對應的參數決定。
- [x] 2.R.6 Code Review：確認 Phase 3 的插入位置與 design.md D2 完全一致；確認 `permanent_supports` 的併入仍在過濾之後；確認未動到 `filter_support_points_by_modifiers()` 的呼叫順序。

---

## 3. 階段三：移除第 6 步閘門

- [x] 3.1 刪除 `DefaultSupportTree.cpp` 中 `filterfn` 內的 `passes_overhang_filter()` 呼叫（階段一替換後的那一行）及其上方的說明註解區塊。保留 `normal_cutoff_angle` 判定與 `polar` 飽和運算。
- [x] 3.2 刪除 `SupportTreeUtils.hpp` 中 `optimize_pinhead_placement()` 內的 `passes_overhang_filter()` 呼叫及其上方的說明註解區塊。保留 `normal_cutoff_angle` 判定與 `polar` 飽和運算。
- [x] 3.3 保留 `SupportTreeConfig::overhang_angle_threshold` 欄位與 `make_support_cfg()` 中的兩處賦值，**不得刪除**（第 5 步仍需經同一條組態鏈取值）。
- [x] 3.4 全代碼庫搜尋確認：`src/libslic3r` 中同時出現 `M_PI / 2.0 +` 與 `overhang_angle_threshold` 的比較式，命中處僅剩共用函式本身一處（spec：全代碼庫僅存在一處判定式）。

### 3.R 階段三驗收與 Code Review

- [x] 3.R.1 **⏸ 交給使用者編譯**：請使用者建置 `slicer-engine`，回報編譯結果。若出現「未使用變數」之類的警告升級為錯誤，一併回報完整訊息。
- [x] 3.R.2 撰寫測試驗證匯入豁免：同一份匯入 JSON（含位於陡峭表面的點），分別以 `support_critical_angle` 為 0 / 45 / 90 載入並生成支撐，三次的**支撐點數量 MUST 相同**（spec：調整角度不影響匯入的點集）。
- [x] 3.R.3 撰寫測試驗證 `type` 已降級：兩份 JSON 座標與尺寸完全相同、僅 `type` 分別為 `manual_add` 與 `slope`，生成的支撐網格 MUST 逐位元相同。
- [x] 3.R.4 撰寫測試驗證物理極限仍生效：法線偏離正上方不足 30° 的匯入點 MUST NOT 生成支撐柱（`normal_cutoff_angle` 仍作用）；位於狹縫內無空間的點 MUST NOT 生成支撐柱且切片 MUST 正常完成。
- [x] 3.R.5 撰寫測試驗證斜柱行為：位於垂直牆面、下方空間充足的匯入點 MUST 生成支撐柱，且其方向受 `bridge_slope` 夾住而呈斜向插出（spec 驗收場景）。
- [x] 3.R.6 **⏸ 交給使用者驗證**：對 0.2 的兩個模型執行完整切片。此時逐層 SHA-256 **預期與舊基準不同**（R1）。請使用者確認差異方向為「支撐變多」，且視覺檢查支撐結構無異常斷裂或懸空。
- [x] 3.R.7 Code Review：確認兩處只刪了判定式該行與其註解，`normal_cutoff_angle` 與飽和運算原封未動；確認 `overhang_angle_threshold` 欄位仍存在且註解已標示唯一消費點。

---

## 4. 階段四：失效機制登記

- [x] 4.1 於 `src/libslic3r/SLAPrint.cpp` 的 `invalidate_state_by_config_options()` 中，將 `support_critical_angle` 與 `branchingsupport_critical_angle` 加入歸屬 `slaposSupportPoints` 的分支。
- [x] 4.2 保留兩個鍵在 `slaposSupportTree` 分支的既有登記，**不得移除**（步驟失效具傳遞性，重複登記無害且語意更明確）。
- [x] 4.3 在新增處加註：此登記的存在是因為角度過濾已移至 `slaposSupportPoints`；對 Web 的一次性 CLI 行程無實質影響，是為 GUI 與持久化路徑的正確性而設。

### 4.R 階段四驗收與 Code Review

- [x] 4.R.1 **⏸ 交給使用者編譯**：請使用者建置 `slicer-engine`，回報編譯結果。
- [x] 4.R.2 撰寫測試驗證失效傳遞：對已完成一次自動產點的列印物件修改 `support_critical_angle`，確認 `slaposSupportPoints` 被標記為失效；以 `branchingsupport_critical_angle` 重複同一驗證。
- [x] 4.R.3 Code Review：確認未誤刪 `slaposSupportTree` 分支的既有登記；確認兩個鍵的拼寫與 `PrintConfig` 中的定義完全一致（拼錯不會產生編譯錯誤，只會靜默失效）。

---

## 5. 階段五：規格場景整合測試

- [x] 5.1 將 `specs/sla-overhang-threshold-semantics/spec.md` 的每一個 Scenario 對應到一個具體測試案例，逐條核對是否已被階段一至四的測試涵蓋，補齊缺口。
- [x] 5.2 將 `specs/support-point-interchange/spec.md` 的每一個 Scenario 同樣逐條核對並補齊。
- [x] 5.3 撰寫端到端測試：同一模型與同一組態，先以 `--export-support-points` 取得清單，再執行完整支撐生成，驗證清單中 MUST NOT 存在「僅因懸空角度不足」而未長出支撐頭的點（spec：匯出的點與長出的支撐柱在角度維度一致）。
- [x] 5.4 撰寫往返測試：以某組態匯出的 JSON，再以同組態 `--import-support-points` 載回，引擎使用的支撐點集 MUST 與匯出清單逐點相同。
- [x] 5.5 驗證 `--import-support-stl` 路徑完全未受影響：以匯入支撐網格的既有測試模型執行，輸出 MUST 與變更前逐位元相同（`has_imported_support()` 提前 return，本變更不觸及該路徑）。
- [x] 5.6 執行後端 Python 測試套件（`agent/tests`），確認未因引擎行為變化而破壞既有的支撐生成與錯誤分類測試。（`python -m pytest agent/tests`：752 passed、2 failed。本任務範圍內的 278 個支撐生成／錯誤分類／分類器測試**全數通過**。2 個失敗均與本變更無關且不在本任務範圍：`test_prz_print_time.py::test_6_11_...` 為 `prz_encoder._compute_print_time()` 的純 Python 算術，屬另一個進行中的變更 `sync-prz-print-time`，完全不呼叫切片引擎；`test_subprocess_boundary_5_11.py::test_engine_runs_as_separate_process` 為環境缺少 `pytest-asyncio` 外掛，async 測試函式未被 await。`agent/` 目錄工作區無任何改動。）

### 5.R 階段五驗收與 Code Review

- [x] 5.R.1 **⏸ 交給使用者編譯**：請使用者建置 `slicer-engine` 與 `tests/sla_print` 測試執行檔，執行完整測試套件，回報結果。（**不含篩選的全套件已回報全綠：134 test cases / 33534 assertions**。輸出中的 `Detected missing Voronoi vertex...` 為既有測試的預期錯誤日誌，非失敗。）
- [x] 5.R.2 逐條核對兩份 spec 的 Scenario 覆蓋表，確認**無任何 Scenario 未對應到測試**。（35 個 Scenario 中 32 個有自動化測試；3 個無 runtime 測試者的理由記於 design.md「5.R.2 覆蓋核對的殘留」。）
- [x] 5.R.3 Code Review：整體檢視本次所有 diff，確認未夾帶與本變更無關的改動。（**發現 6 個與本變更無關的既有工作區改動，須排除於提交之外**，清單見階段六 6.4。）

---

## 6. 收尾與重新基準化

- [x] 6.1 以最終版引擎重新產生逐層 SHA-256、`layer_count`、`resin_volume_ml`、`estimated_print_time` 基準，取代舊基準，並在提交訊息中明確標註「因 `align-support-point-overhang-filter` 重新基準化」。（**實測零回歸，判定不需重新基準化**：兩個模型的逐層 SHA-256 滾動值與階段 0 基準逐位元相同，舊基準全部保留。記錄於 verification-notes.md「6.1 重新基準化」。**提交訊息不應標註重新基準化**，因為並未發生。結論僅對這兩個模型成立，換模型須逐案重驗。）
- [x] 6.2 記錄新舊基準的差異摘要（支撐點數變化量、支撐柱數變化量），寫入變更資料夾下的驗證筆記，供日後查證 R1 的實際影響幅度。（已寫入 verification-notes.md「6.2 新舊差異摘要」：支撐點 `frog_legs` 172→167、`U_overhang` 20→20；支撐柱數變化 0；型別分佈實測顯示被剔除的 5 點**全為 `island` 型**，`slope` 型零剔除。）
- [x] 6.3 **⏸ 交給使用者**：以 `scripts\package_slicer_engine_windows.ps1` 打包引擎並更新 `slicer-engine/bin`，或依既有流程處理。**（已於 2026-09-04 由使用者在外部終端機執行完成，回報 `VERDICT: PASS` / `Consumer staging ready`。）**
  - **必須明確傳入 `-BuildReleaseDir`。** 腳本預設指向 `third_party\prusaslicer_build\src\Release`，該樹的 exe 為 2026-09-03 09:18、dll 為 2026-08-30 13:15，是**變更前的舊引擎**。用預設值會靜默打包錯的引擎。
  - 正確來源為 `third_party\prusaslicer_fork\build\src\Release`（exe 2026-09-04 13:46、dll 2026-09-04 09:13，皆晚於最後的引擎原始碼修改 `SLAPrint.cpp` 2026-09-04 09:09）。該樹只有 `Release`，無 `RelWithDebInfo`。
  - 執行指令（於 `D:\repos\web_slicer_core`）：
    ```
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\package_slicer_engine_windows.ps1 -BuildReleaseDir "D:\repos\web_slicer_core\third_party\prusaslicer_fork\build\src\Release"
    ```
  - **已排除的地雷**：腳本到 `deps\build\destdir\usr\local\bin` 找 `libgmp-10.dll` / `libmpfr-4.dll`，但本機實際位於 `deps\build\out_deps\usr\local\bin`。腳本開頭會 `Remove-Item -Recurse -Force` 整個 `slicer-engine/`，而缺這兩個 DLL 只印 WARN 不中止——結果會產出**無法載入（LoadLibrary error 126）的 bin**。已於 2026-09-04 14:06 把兩個 DLL 複製到腳本預期路徑（與現行 `slicer-engine/bin` 內的檔案 SHA-256 逐位元相同）。
  - 其餘 fail-closed 閘門預檢皆通過：`OCCTWrapper.dll`、PE 圖示 SoT `resources/icons/slicer-engine.ico`、AGPL legal pack（NOTICE / MODIFICATIONS.md / SOURCE-OFFER.md）、`vswhere.exe`（export gate 需要的 dumpbin）皆存在。
  - **對提交無影響**：`slicer-engine/` 由 `.gitignore:90` 忽略，打包不產生任何版控內容。
- [x] 6.4 確認前端 `DS-Online` 與後端 `agent` 皆未產生任何檔案變更（本變更範圍不含兩者）。同時**排除下列與本變更無關的既有工作區改動**，不得混入本次提交：
  - 外層 `web_slicer_core`：`.gitignore`（新增 `.gemini/`、`.agent/`）、`.gitmodules`（submodule URL 改為 https，且格式已損壞：`url=` 前缺少縮排、檔尾缺換行）、`scripts/build_prusaslicer_fork_macos.sh`
  - 內層 `prusaslicer_fork`：`.gitignore`（新增 `.claude/`、`.github/`、`CLAUDE.md` 與 openspec evidence 忽略規則）、`src/libslic3r/CMakeLists.txt`（註解掉 `encoding_check`、新增 Blosc 連結）、`src/slic3r/CMakeLists.txt`（註解掉 `encoding_check`）——後兩者為本機建置繞道，非本變更內容
  - 另有空目錄 `third_party/prusaslicer_fork/third_party/prusaslicer_fork`（git 不追蹤空目錄，不會誤入提交；可自行刪除）
  - **6.4 檢查結果（2026-09-04）**：`git status --porcelain agent/ web/ dev-interface/` 輸出為空，後端與前端零變更。倉庫中不存在 `DS-Online` 目錄（為獨立倉庫），本次不涉及。
  - **隔離策略：一律以明確路徑 `git add`，絕不使用 `git add -A` 或 `git add .`。** 兩個倉庫的未追蹤檔案各只有一個，且都屬於本變更（外層 `openspec/changes/align-support-point-overhang-filter/`、內層 `tests/sla_print/sla_overhang_filter_tests.cpp`），無其他雜物。
  - 內層 `prusaslicer_fork` 應暫存的 **8 個**檔案：
    ```
    git -C third_party/prusaslicer_fork add \
      src/libslic3r/SLA/DefaultSupportTree.cpp \
      src/libslic3r/SLA/SupportTree.hpp \
      src/libslic3r/SLA/SupportTreeUtils.hpp \
      src/libslic3r/SLAPrint.cpp \
      src/libslic3r/SLAPrintSteps.cpp \
      tests/sla_print/CMakeLists.txt \
      tests/sla_print/sla_per_point_geometry_tests.cpp \
      tests/sla_print/sla_overhang_filter_tests.cpp
    ```
  - 外層 `web_slicer_core` 應暫存的路徑（子模組指標留給 6.5，此時**不要**加入）：
    ```
    git add openspec/changes/align-support-point-overhang-filter
    ```
  - 暫存後的驗證（三條都要做，任一不符就停下）：
    ```
    git -C third_party/prusaslicer_fork diff --cached --name-only   # 必須剛好 8 個檔案
    git -C third_party/prusaslicer_fork status --porcelain          # .gitignore 與兩個 CMakeLists.txt 必須仍在未暫存區
    git diff --cached --name-only                                   # 必須只有 openspec/changes/... 底下的檔案
    ```
  - 空目錄 `third_party/prusaslicer_fork/third_party/prusaslicer_fork`：git 不追蹤空目錄，不可能誤入提交，無需處理。
- [x] 6.5 更新 `third_party/prusaslicer_fork` 子模組指標，並在 `web_slicer_core` 提交該指標變更。（內層 commit `a986b5fd381dd76aeb41aa93ceb858ad7d3b3325`，分支 `feature/manual-edit-tree-support`，8 個檔案。外層提交封存產物、兩份主規格與該指標。6 處無關工作區改動全部維持未暫存，未混入任一提交。**兩層皆未 push。**）

---

## 附錄：Visual Studio 2022 / CMake 編譯問題診斷指引

當使用者回報編譯失敗時，依下列順序診斷，**不要直接重跑指令稿碰運氣**。

### A. 先分類錯誤

- [ ] A.1 請使用者提供**完整的第一個錯誤訊息**（含檔名與行號），不是最後一個。MSBuild 的後續錯誤多半是第一個錯誤的連鎖反應。
- [ ] A.2 判斷錯誤類型：編譯期（`C2xxx` / `C3xxx`）、連結期（`LNK2xxx`）、或 CMake 組態期（`CMake Error`）。三者的處置完全不同。

### B. 編譯期錯誤（C2xxx / C3xxx）

- [ ] B.1 `C2039` / `C2065`（找不到成員或識別字）：檢查是否漏了 `#include <libslic3r/Geometry.hpp>` 或 `#include <libslic3r/MeshNormals.hpp>`（階段二 2.1）。
- [ ] B.2 `C2664`（引數型別不符）：檢查 `normals()` 的呼叫是否漏了執行策略引數。fork 的 `Slic3r::normals()` 第一個參數是執行策略（如 `ex_tbb`），與 PhrozenOrca 的 `sla::normals()` 簽章不同，不可照抄。
- [ ] B.3 `C2666` / 多載歧義：確認 `passes_overhang_filter()` 的兩個參數皆為 `double`，呼叫端未傳入 `float` 造成隱式轉換歧義。
- [ ] B.4 命名空間錯誤：`dir_to_spheric` 位於 `Slic3r::Geometry`，`normals` 位於 `Slic3r`，`passes_overhang_filter` 位於 `Slic3r::sla`。三者命名空間不同，需完整限定或加 `using`。

### C. 連結期錯誤（LNK2xxx）

- [ ] C.1 `LNK2019`（無法解析的外部符號 `normals`）：`MeshNormals.hpp` 使用顯式範本實例化（`extern template`），只有 `ExecutionSeq` 與 `ExecutionTBB` 兩種策略有對應的實例。確認未傳入第三種策略。
- [ ] C.2 新增測試檔後出現連結錯誤：確認已在 `tests/sla_print/CMakeLists.txt` 登記新檔案（階段一 1.6），且已重新執行 CMake 組態。

### D. CMake 組態期錯誤

- [ ] D.1 新增測試檔後 CMake 未察覺：於 VS 2022 中執行「專案 → 刪除快取並重新設定」，或刪除 `third_party/prusaslicer_fork/build/CMakeCache.txt` 後重跑指令稿。
- [ ] D.2 相依套件找不到：確認 `deps` 已建置完成。若指令稿中途失敗過，以 `scripts\build_prusaslicer_fork_windows.bat low clean` 從頭重建。

### E. 記憶體不足導致編譯中止

- [ ] E.1 若編譯過程出現 `C1060`（編譯器堆積空間不足）或工具鏈被系統終止，改用 `low` 記憶體模式（單執行緒、關閉 `/MP`）：`scripts\build_prusaslicer_fork_windows.bat low`。
- [ ] E.2 若 `low` 模式仍失敗，請使用者關閉其他佔用記憶體的程式後重試；`SLAPrintSteps.cpp` 是本專案最大的編譯單元之一，對記憶體較敏感。

### F. 編譯成功但行為不符預期

- [ ] F.1 確認執行的是**剛建置出來的**執行檔，而非 `slicer-engine/bin` 中的舊版。兩者路徑不同，很容易測到舊的。
- [ ] F.2 以 `--load` 明確帶入組態檔執行。fork 的 `support_critical_angle` 引擎預設為 90 度（只支撐完全水平朝下面），不帶組態會產出極少的點，容易被誤判為過濾寫錯（design.md R4）。

## 1. Phase 0：Baseline 重現與 harness 建立

- [x] 1.1 Source tracing：確認 `generate_side_wall_drains()` 唯一呼叫端、`slice_mesh_at_z()` 全 repo 唯一呼叫者（本函式），輸入座標空間與 translation 狀態
- [x] 1.2 用真實 PrusaSlicer CLI hollow 輸出，對 `001_p.stl`／`005_p.stl`／`DentalModel_1M.stl`／`DentalModel_NeedRotate.stl` 四個代表模型跑真實 Auto Process，建立涵蓋正常產出、低產出、多重不連通 outer loop 的 coverage
- [x] 1.3 建立 scratchpad A/B 診斷 probe（逐行複製修改前程式碼 + counters/timers），先以 `np.array_equal` 對照修改前 production code 驗證輸出一致，才用於後續 profiling
- [x] 1.4 診斷 profiling 定位瓶頸：4 個代表模型的真實 Step 6 執行中，`slice_inner+slice_outer` 合計佔該次 Step 6 wall time 的 67%～99%（001_p.stl 66.6%、005_p.stl 72.9%、DentalModel_1M.stl 69.7%、DentalModel_NeedRotate.stl 98.6%）；另以 16 組真實（mesh、z-level）組合做獨立 slicing diagnostic（量測候選比例、各子階段耗時、正確性），outer 的 `+0.5`／`+2.0` 兩個 z-level 在這 4 個模型的真實 pipeline 中未曾進入 retry，兩項數字來源不同、不可混算

## 2. Phase 1：三角形 Z min/max broad-phase 篩選 + bounds 生命週期

- [x] 2.1 推導並確認：`face_z_min < z_world < face_z_max` 精確等價於「該三角形至少存在一條端點嚴格分處切平面兩側的邊」（即至少一條邊滿足既有 `d0*d1<0`；三頂點全在切平面一側或恰觸平面時，任兩邊乘積恆非負）——明確界定此等價性**不**代表「該三角形一定產生 segment」，候選集合可能保留最終只找到 1 個交點、不滿足既有「恰需 2 個交點」規則的三角形（例如頂點 Z 為 `(-1,0,+1)`、切面為 `0` 時），此為候選篩選允許的正常情況，既有 scalar 迴圈的既有邏輯不受影響
- [x] 2.2 新增 `compute_face_z_bounds()`（`agent/ortho_pipeline.py`）：以 `vertex_z`／`faces` 花式索引配合 `np.minimum`/`np.maximum`（`out=` 就地運算）計算，不建立 `mesh.triangles`、不轉 `float32`
- [x] 2.3 `slice_mesh_at_z()` 新增 `candidate_face_ids = np.flatnonzero(...)` 篩選與可選 `face_z_bounds` 參數；僅對候選子集合執行逐行不變的既有 scalar 迴圈與 spatial-hash loop chaining
- [x] 2.4 `generate_side_wall_drains()` 呼叫端調整 bounds 生命週期：inner shell 直接呼叫 `slice_mesh_at_z(inner_shell, z_drain)`（bounds 由函式內部建立即釋放，不在外層持有具名變數）；outer shell 在 inner slice 完成後才建立一次 `outer_face_z_bounds`，供 `+1.0`／`+0.5`／`+2.0` 三次 retry 共用
- [x] 2.5 確認未使用 `del`／`gc.collect()`／全域或 Trimesh 快取管理 bounds；確認未變更候選點選取、angle-bin、slide search、孔幾何、Boolean（Step 7～10）呼叫方式

## 3. 正確性驗證

- [x] 3.1 新增合成幾何單元測試（`agent/tests/test_slice_mesh_at_z_broad_phase.py`，8 tests）：全高於平面、全低於平面、正常穿越並成功閉合 loop、vertex 恰在切平面（既有「恰需 2 點才算 segment」行為不受影響）、coplanar、degenerate 三角形不當機、空 mesh、`face_z_bounds` 外部傳入與內部自算一致
- [x] 3.2 對 4 個真實代表模型、16 組（mesh、z-level）組合，執行「修改後 vs. 已驗證的修改前逐行複製」，確認 `slice_mesh_at_z()` 的 loop 數量、順序、每個 loop shape 與座標 `np.array_equal`（含 `DentalModel_1M.stl` outer 在 z=1.0/0.5/2.0 分別產生 14/5/10 個不連通 loop 的情況）
- [x] 3.3 對 4 個真實案例執行完整 `generate_side_wall_drains()`，確認 `None`/非 `None` 判定一致、`.vertices`／`.faces` `np.array_equal`（蘊含孔數與內部候選 gate 結果相同）、孔數與本次調查最初一輪自真實 pipeline 擷取的 baseline production log 一致（涵蓋正常產出 10～11 孔與低產出 1 孔）；此階段未逐一比對 `no_bin`／`no_inner_hit`／`too_close` 各自的 gate 計數細項或原始 logger 字串，該項比對只在 3.5（2 模型）執行
- [x] 3.4 Z-bounds 生命週期調整後重跑 3.1～3.3 全部檢查，確認結果不變
- [x] 3.5 對 `001_p.stl`／`DentalModel_1M.stl` 執行完整 pipeline 端到端最終幾何比較（reference／prototype 各自獨立 temp job 目錄），確認 `ortho_result.stl` 的 faces／vertices count、volume（相對誤差 0.0）、bounds（絕對誤差 0.0mm）相同；placed/skip counters（`no_bin`／`no_inner_hit`／`too_close`）與 prototype 實際 production log 所表達的結果一致（reference 側文字由已驗證的 probe counters 重建，非 reference pipeline 直接捕捉的原始 logger 輸出；prototype 側為直接捕捉的真實 log）；`is_watertight` 與固定的 pre-change reference 一致（`001_p.stl` 皆 `True`，`DentalModel_1M.stl` 皆 `False`，確認後者為既有狀況、非本次引入的 regression，不代表本次變更把該狀況定為永久必須維持）
- [x] 3.6 執行 `pytest agent/tests/test_slice_mesh_at_z_broad_phase.py agent/tests/test_ortho_clean_mesh_reuse.py agent/tests/test_ortho_hollow_split_repair.py -v`，確認 18 passed、無回歸

## 4. 效能驗證

- [x] 4.1 16 組真實（mesh、z-level）組合，分別量測修改前後的 bounds-build／z-mask／scalar-intersection／chaining 各階段耗時與候選面比例（候選比例 0.03%～0.71%）
- [x] 4.2 正式 Auto Process 端到端量測（1 次 warm-up + 3 次計時，`time.perf_counter()`，取 median）：`001_p.stl`／`DentalModel_1M.stl` 完整 pipeline 與 Step 6 各自 wall time
- [x] 4.3 確認 Step 6 改善幅度：`001_p.stl` −67.4%（3.07x）、`DentalModel_1M.stl` −67.0%（3.03x）；完整 pipeline 各改善 −16.1%／−15.2%
- [x] 4.4 估算額外記憶體持有量級：最大代表模型（`DentalModel_1M.stl` outer shell，1,024,996 faces）兩個持續存活的 `(F,)` bounds 陣列合計約 16.4MB——此為唯一直接算出的數字，未涵蓋花式索引／`.copy()`／布林遮罩等短期暫存配置，完整 process peak 未直接量測，但預期仍屬數十 MB 等級，未觀察到需要 chunking 的量級

## 5. 收尾（初版 prototype）

- [x] 5.1 design.md 補齊實際量測數字（16 組候選比例／子階段耗時表格、正式 timing 表格、正確性比對結果、記憶體量測）
- [x] 5.2 確認 production 程式碼中無殘留 temporary profiling code（`git diff agent/ortho_pipeline.py` 明確掃描確認無 `perf_counter`／`print`／debug log／benchmark 殘留；所有量測腳本僅存在於 scratchpad）
- [x] 5.3 執行 `openspec validate perf-side-wall-drain-slice --strict`，確認通過（"Change 'perf-side-wall-drain-slice' is valid"）

## 6. 最終收尾（review、archive、commit）

- [x] 6.1 檢查 branch/HEAD/working tree/diff，確認本項只涉及 `agent/ortho_pipeline.py`、`agent/tests/test_slice_mesh_at_z_broad_phase.py`、`openspec/changes/perf-side-wall-drain-slice/`（branch `dev`，HEAD `9860b62` == `origin/dev`，無 drift；`git diff --stat` 僅 `agent/ortho_pipeline.py` +73/-9，其餘 `git status` 項目為本次調查開始前即存在、與本次無關的既有 untracked 檔案／submodule 指標）
- [x] 6.2 最終文字審閱：篩選條件明確描述為與既有判定式「數學等價」（非近似或超集合）；`DentalModel_1M.stl` 完整 pipeline 非 watertight 記錄為既有行為非本次引入；Step 6 剩餘成本（inner-poly ray/segment、outer-poly point-in-polygon）明確列為 Non-Goal 留待後續；正確性描述統一改為 `np.array_equal`（陣列層級），不使用「byte-for-byte」字樣；診斷分析（16 組）與正式 A/B timing（2 模型）兩組量測來源分開陳述，不混算。**第二輪審閱補正**：65～92% 改為精確來源分離並重算為 67%～99%（4 模型真實 Step 6 執行，`slice_inner+slice_outer` 佔比，與 16 組 diagnostic 分開）；broad-phase 數學等價的對象精確限定為「至少存在一條 strict edge crossing」，不再宣稱等價於「產生 segment」，並補上 `(-1,0,+1)` 反例；記憶體段落改為「估算持有量級」，不宣稱已量測完整 peak；`is_watertight` 語意限定為「驗收本次效能變更時與固定 pre-change reference 一致」，不規定該模型未來永久維持 `False`；Step 6 log 證據改為精確描述（reference 側為 probe counters 重建、4 案例中只有 2 案例實際比對過 gate 計數細項）；移除所有帶行號的相對 Markdown source links，改為純文字 `agent/ortho_pipeline.py::函式名()`，避免 archive 後失效
- [x] 6.3 確認 production 程式碼無殘留 temporary profiling／debug log／benchmark 程式（`git diff agent/ortho_pipeline.py | grep -iE "perf_counter|print\(|TODO|DEBUG|benchmark"` 等關鍵字掃描，無匹配）
- [x] 6.4 最終驗證：`pytest agent/tests/test_slice_mesh_at_z_broad_phase.py -q`（8 passed）；`pytest agent/tests/ -q --continue-on-collection-errors`（718 passed／1 failed／3 errors——與既有基準（`2026-09-17-perf-hex-grid-raycast` 收尾時的 710 passed／1 failed／3 errors）相比，新增的 718−710=8 即本項新增測試；既有 1 failed（`test_prz_print_time.py`）與 3 errors（缺少 `httpx`）數字不變，確認非本項引入）；`openspec validate perf-side-wall-drain-slice --strict`（通過："Change 'perf-side-wall-drain-slice' is valid"）
- [ ] 6.5 使用 `openspec archive perf-side-wall-drain-slice` 正式 archive，確認 `openspec/specs/side-wall-drain-slice-performance/spec.md` 正確生成
- [ ] 6.6 Archive 後執行 `openspec validate side-wall-drain-slice-performance --strict` 與 `openspec validate --all --strict`，確認除既有 failure 外無新增問題（若有，記錄但不修改）
- [ ] 6.7 Final diff review，確認 archive 沒有產生非預期或無關變更
- [ ] 6.8 分兩個 commits：production+tests（`perf: add broad-phase filter to side-wall drain slicing`）、openspec archive+正式 spec（`chore(openspec): archive perf-side-wall-drain-slice`）
- [ ] 6.9 push 目前分支（不 force push）

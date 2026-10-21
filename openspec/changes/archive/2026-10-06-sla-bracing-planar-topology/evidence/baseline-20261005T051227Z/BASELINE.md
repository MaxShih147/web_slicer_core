# 斜撐基準線（改動前）

量測時間：2026-10-05 05:12 UTC。這份報告對應 tasks.md 的 1.1 到 1.5，是任務組 2 的「逐位元相同」比對，以及任務組 7 驗收門檻的比較基準。

## 引擎建置身分

- fork commit：`e0be76c570a59614284db063d230267e73d2c333`（web_slicer_core `0fc176d181b9531d048d9f9d4e7e392fd95bd164`）
- 工作區相對於 commit 的差異：`.gitignore`、`src/libslic3r/CMakeLists.txt`（停用 `encoding_check`、連結 Blosc）、`src/slic3r/CMakeLists.txt`（停用 `encoding_check`）。這三項在本變更開始前就已存在。本變更只新增 `tests/sla_print/` 下的三個量測檔，並登錄到 `tests/sla_print/CMakeLists.txt`。`src/libslic3r` 底下沒有任何 `.cpp` 或 `.hpp` 被修改。
- 編譯：Visual Studio 17 2022，MSVC 19.44.35225.0，Release（`/MD /O2 /Ob2 /DNDEBUG`），`SLIC3R_STATIC=ON`
- 量測程式：`build/tests/sla_print/Release/sla_print_tests.exe`，SHA-256 `0768e68864da66e932e530acde2ba72bfdffc15d3136598246b980a8730260aa`（補入第 4 個模型後重建；前三個模型的雜湊與重建前的量測完全相同，舊數據保留於 `superseded/runs-3models.jsonl`）
- 比對用的正式引擎：`build/src/Release/slicer-engine.exe`，SHA-256 `9eccb11dd47242598ba79b2ca5c1eef8169e72eded7321c5633bead5c3daaf8d`
- 機器：Intel i7-11370H（4 核心 8 執行緒），15.7 GB 記憶體，Windows 11 Pro 10.0.26200

## 量測方法

- 量測函式：`tests/sla_print/sla_bracing_metrics.{hpp,cpp}` 的 `bracing_metrics()`。它直接讀 builder，用桿件所在的容器（`crossbridges`、`bridges`、`diffbridges`）和建立時寫入的 owner id 分類，不從幾何推斷型態。規則的正確性由 `[bracing_metrics]` 的 7 個單元測試鎖定，包括門檻 ±1e-6、19°/21° 和穿柱等案例。
- 違規判定與規格驗收指標一致：
  - 不共用柱的兩組斜撐，俯視距離 < `r1 + r2 + 0.2` 記為 `cross_truss`。
  - 共用一柱且俯視夾角 < 20° 記為 `shared_angle`。
  - 斜撐組到第三根柱軸心的距離 < `r_bar + r_start + 0.2` 記為 `obstacle_pillar`。
  - 以上皆為嚴格小於才算違規。`r` 取該組最粗的桿。
- 執行程式：`sla_bracing_metrics_tests.cpp` 中的隱藏測試 `[.bracing_baseline]`，由 `plan.json` 驅動。
  - 支撐點用 `SLAPrint` 跑到 `slaposSupportPoints` 取得，使用與後端 `generate_supports` 相同的參數。
  - 支撐樹由程式直接呼叫 `DefaultSupportTree::execute` 建立，輸入與 `SLAPrint::Steps::support_tree()` 組出的相同。
  - 連接階段的耗時，取狀態回呼中 `Interconnecting pillars` 到 `Merging support mesh` 這段時間。
  - 單執行緒以 `tbb::task_arena(1)` 執行。
- 測試流程與正式流程等價的佐證：三個模型的合併支撐網格面數，與 `slicer-engine --export-support-stl` 用同一份 ini 輸出的結果完全相同，分別是 87872、132352、347264。高柱模型沒有模型檔，無法交給正式引擎，所以沒有做這項比對。

重新量測的指令：

```
BRACING_BASELINE_PLAN=<本目錄>/plan.json build/tests/sla_print/Release/sla_print_tests.exe "[.bracing_baseline]"
```

## 參考模型（1.2）

| 角色 | 模型 | SHA-256 | 切片參數 |
|---|---|---|---|
| 小 | `tests/data/frog_legs.obj` | `88504bf53c95ee57001dffc46f9bb68b5b5f7cecb3bdd2c80dfb468b30859d59` | `config-small.ini`（Sonic_Mighty 16K） |
| 中 | raster_bench `secondary-8k-guide-x3/model.stl` | `7cbf7b278f15add02e7ebd524f69b646c802bdbb67e1aeb258b33d14a35a2d31` | `config-medium.ini`（Sonic_Mini 8K S） |
| 滿版 | raster_bench `primary-16k-guide-x8/model.stl` | `d4f571910b46664469d8a47837b348a54940f7c24d1ff21dddc6b60368d79d49` | `config-full.ini`（Sonic_Mighty 16K） |
| 高柱 | `builtin:tall_fixture`（程式生成，見下） | 輸入網格雜湊 `c0b8843f5f720efc`（300 面） | `config-small.ini`（Sonic_Mighty 16K） |

三份 ini 都以 `make_fixtures.build_sla_config(..., supports_enable=True, layer_height=0.15)` 產生，與 freeze-support 的配方相同。主要參數：柱徑 1.0、頭前徑 0.4、抬升 5 mm、斜撐角 45°、柱間連接距離 10 mm、`pillar_connection_mode=dynamic`、輔助柱開啟、不產生底座。模型與 ini 的雜湊記錄在 `models.json`。

小模型原本預計用 `tiny-16k-crown-x1`，後來換掉了。原因是這顆牙冠平躺，只得到 3 個支撐點、2 根柱子，沒有任何斜撐。正式引擎的 `--export-support-points` 同樣只寫出 3 個點。替換前試了 tests/data 的 8 個模型，結果記錄在 `probe-tests-data.jsonl`；frog_legs 是其中柱數最多、而且已經出現交錯的一個。

高柱模型是補上的第 4 個參考模型。前三個模型都不會長出輔助柱，輔助柱階段與 `DefaultSupportTree.cpp:1238` 的重跑路徑因此完全沒有被執行到。tests/data 的 22 個模型中，只有 `extruder_idler`（2 根輔助柱）與 `extruder_idler_quads`（1 根）會長出輔助柱，數量太少，所以改用程式生成。生成函式是 `sla_bracing_metrics_tests.cpp` 的 `make_tall_fixture()`：

- 中央立柱 4×4×30 mm，向外伸出兩圈手臂，每圈 6 根。
- 手臂以 55° 上升，比 45° 的懸挑門檻陡，所以手臂本身不需要支撐。
- 每根手臂末端有一個 6×6×1.5 mm 的平台。內圈平台半徑 16 mm、高約 27 mm，柱高介於 15 與 35 mm 之間；外圈半徑 28 mm、高約 44 mm，柱高超過 35 mm。

程式生成的模型沒有檔案，以輸入網格雜湊（`runs.jsonl` 的 `input_mesh_digest`）確認每次都相同。試做時，3×3 mm 平台只得到 5 個支撐點（手臂穿過平台，平台底面不構成新的懸空區域），所以改成 6×6 mm。

## 斜撐指標（1.1）

| 指標 | 小 | 中 | 滿版 | 高柱 |
|---|---|---|---|---|
| 支撐點 / 有效頭 | 169 / 169 | 216 / 216 | 576 / 576 | 37 / 37 |
| 柱 / 輔助柱 | 114 / 0 | 120 / 0 | 315 / 0 | 36 / **4** |
| 斜撐桿 / 斜撐組 | 76 / 69 | 436 / 140 | 1079 / 345 | 423 / 35 |
| 頭部掛橋 / 輔助柱橋 / 繞路段 | 55 / 0 / 0 | 96 / 0 / 0 | 261 / 0 / 0 | 5 / **4** / 0 |
| **俯視違規 `cross_truss`** | **22** | **28** | **49** | **0** |
| **同柱夾角違規 `shared_angle`** | **6** | **19** | **38** | **0** |
| 涉及俯視違規的斜撐組 | 29 | 47 | 104 | 0 |
| **穿柱違規 `obstacle_pillar`** | **53** | **24** | **50** | **0** |
| 其中擋路柱不在地面 | 0 | 0 | 0 | 0 |
| 涉及穿柱的斜撐組 | 36 | 24 | 44 | 0 |
| 高度 > 15 mm 的柱 | 0 | 27 | 71 | 34 |
| **孤立高柱（links = 0 且 > 15 mm）** | **0** | **0** | **0** | **0** |
| 每柱配對夥伴數 0/1/2/3/4/5+ | 49/14/29/22/0/0 | 16/12/8/84/0/0 | 45/43/34/193/0/0 | 2/3/26/5/0/0 |

## 連接階段耗時（1.3）

以下為最終一輪（四個模型）的數據。

| 模型 | 8 執行緒（中位數，範圍） | 1 執行緒（中位數，範圍） | 整棵支撐樹（8 執行緒中位數） |
|---|---|---|---|
| 小 | 0.46 ms（0.36–0.59，n=7） | 0.55 ms（0.39–0.64，n=5） | 19.8 ms |
| 中 | 1.06 ms（0.99–1.49，n=5） | 1.20 ms（1.14–1.23，n=3） | 18.2 ms |
| 滿版 | 2.82 ms（2.58–4.23，n=5） | 3.28 ms（3.17–3.36，n=3） | 58.9 ms |
| 高柱 | 2.56 ms（2.40–3.69，n=7） | 2.77 ms（2.54–4.10，n=5） | 7.1 ms |

支撐點產生（`SLAPrint` 跑到 `slaposSupportPoints`）約需 0.8、1.8、4.6、0.03 秒，不計入連接階段。高柱模型的連接階段包含輔助柱的放置與輔助柱斜撐。

## 決定性（1.4）

每個模型的每一次執行都完全相同：支撐點產生兩次、8 執行緒 5 到 7 次、1 執行緒 3 到 5 次，比對頭、柱、掛橋、斜撐、繞路段與合併網格的位元級雜湊（FNV-1a 64），結果一致。前三個模型在量測程式重建前後也完全相同。

| 模型 | 支撐點 | 斜撐 | 合併網格（頂點 / 面） |
|---|---|---|---|
| 小 | `32542ee28036eaac` | `9ea1a06000b92df4` | `b6ebf81616bffda0`（44809 / 87872） |
| 中 | `3d2fbcd00613b741` | `5aab674343f96db0` | `c409e5c7421d8621`（67939 / 132352） |
| 滿版 | `f23526df3a6298ea` | `a611707ba0c0b3d9` | `cb962a1edbc52243`（178188 / 347264） |
| 高柱 | `5d2bd0714df290e9` | `5d188871153973f5` | `946cd02da351158e`（23667 / 48256） |

完整雜湊（含頭、柱、掛橋）見 `runs.jsonl`。

可能的不一致來源在這四個輸入上都沒有出現：`add_pinheads` 與 `routing_to_model` 都是平行執行，而 `AlgNLoptGenetic` 的 `seed(0)` 寫入的是 nlopt 的全域亂數狀態。fork 的 `.gitignore` 註解提到「GA 優化器不具決定性」，在這裡沒有重現；這不代表其他輸入不會發生。

## 對後續任務的意義

- **任務 2.5（逐位元相同）可行**：四個模型在 1 和 8 執行緒下都穩定，可直接比對上表的合併網格雜湊。
- **任務 7.2 的耗時門檻實際上是 50 ms**：連接階段只有 0.4 到 3.3 ms，10% 遠小於 50 ms，所以 `max(10%, 50 ms)` 會取 50 ms。這組模型無法看出演算法複雜度的退化。
- **任務 7.1 的孤立高柱門檻是 0**：中、滿版、高柱模型分別有 27、71、34 根超過 15 mm 的柱，改動前全部都有連到其他柱。改動後只要出現任何一根孤立高柱，就算不通過。小模型沒有超過 15 mm 的柱，這項指標對它沒有意義。
- **輔助柱路徑由高柱模型覆蓋**：它產生 4 根輔助柱、4 根輔助柱橋，並執行到 `DefaultSupportTree.cpp:1238` 的重跑。它的三項違規為 0，交錯的改善要看前三個模型。
- **凍結柱沒有被任何參考模型覆蓋**：四個模型都是從頭產生，沒有凍結柱，所以「凍結柱不得發起配對」（1238 行的修正重點）只能靠任務 6 的共通向量（例如「單一新柱對全凍結板」）驗證。
- **穿柱違規的擋路柱全部站在地面**：design.md 風險中「站在模型上的柱造成誤擋」的情況，在這組模型中沒有出現。

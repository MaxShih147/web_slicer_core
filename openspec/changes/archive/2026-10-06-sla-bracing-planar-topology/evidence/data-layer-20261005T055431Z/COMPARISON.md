# 任務 2.5 驗證：資料層重構零幾何副作用

比對執行時間：2026-10-05 05:47 UTC。本目錄保存任務 2.1 至 2.4 完成後的重跑數據，並與 `../baseline-20261005T051227Z/` 逐項比對。

## 結論

- 4 個參考模型共 40 次支撐樹執行（8 與 1 執行緒）中，有 40 次與基準線相同。比對項目是頭、柱、掛橋、斜撐、繞路段與合併網格的位元級雜湊，以及合併網格的頂點數與面數。
- 支撐點（每個模型產生兩次）與輸入網格的雜湊，全部與基準線相同。
- 所有斜撐指標都與基準線相同，包括違規數、柱數、桿數與配對夥伴分布。
- 每一根桿都帶有型態。`kind_unset` 與 `kind_disagrees` 在每次執行都是 0；後者計算的是型態與桿件所在容器、owner 推得的來源不一致的桿。
- 正式引擎 `slicer-engine --export-support-stl` 匯出的支撐 STL，改動前後的 SHA-256 完全相同（見下表）。

## 引擎建置身分

- fork commit：`e0be76c570a59614284db063d230267e73d2c333`。工作區另含任務 2.1 至 2.4 的修改：`SupportTree.hpp`、`SupportTreeBuilder.hpp`、`DefaultSupportTree.cpp`、`SupportTree.cpp`、`SupportTreeUtilsLegacy.hpp`。
- 編譯：Visual Studio 17 2022，MSVC 19.44.35225.0，Release（`/MD /O2 /Ob2 /DNDEBUG`）
- 量測程式 `sla_print_tests.exe`：SHA-256 `807ab4c39822316efc8ef845d0204977446aca14bffedbba8096fb2a7e8bfad5`
- 正式引擎 `slicer_core.dll`：SHA-256 `d453dab93ad25a82268cbeaf264ffeebc368232451cb4548a4594cb5802fe577`。`slicer-engine.exe` 只是啟動程式，雜湊不變。

## 逐模型比對

| 模型 | 支撐點產生 | 支撐樹執行 | 與基準線相同 | 指標相同 | (unset, disagree) | 桿數 |
|---|---|---|---|---|---|---|
| 小 | 2 | 12 | 12/12 | 是 | (0, 0) | 131 |
| 中 | 2 | 8 | 8/8 | 是 | (0, 0) | 532 |
| 滿版 | 2 | 8 | 8/8 | 是 | (0, 0) | 1340 |
| 高柱 | 2 | 12 | 12/12 | 是 | (0, 0) | 432 |

### 雜湊清單（FNV-1a 64；基準線與本次相同）

| 模型 | 支撐點 | 頭 | 柱 | 掛橋 | 斜撐 | 繞路段 | 合併網格（頂點 / 面） |
|---|---|---|---|---|---|---|---|
| 小 | `32542ee28036eaac` | `8f339cbb74aab7be` | `14a6816831bedb20` | `80ea3acff79b2cfa` | `9ea1a06000b92df4` | `14650fb0739d0383` | `b6ebf81616bffda0`（44809 / 87872） |
| 中 | `3d2fbcd00613b741` | `4186395296c080ec` | `56d28a3160f5b0cb` | `4cc1c65553e8909d` | `5aab674343f96db0` | `14650fb0739d0383` | `c409e5c7421d8621`（67939 / 132352） |
| 滿版 | `f23526df3a6298ea` | `810ea87205d94f0d` | `d51946b9bfc1a7c3` | `23bf2c777f317956` | `a611707ba0c0b3d9` | `14650fb0739d0383` | `cb962a1edbc52243`（178188 / 347264） |
| 高柱 | `5d2bd0714df290e9` | `f30eb491bf9b2522` | `d67c38473cce16ba` | `1ea01ca40c122ef2` | `5d188871153973f5` | `14650fb0739d0383` | `946cd02da351158e`（23667 / 48256） |

## 正式引擎匯出的支撐 STL（SHA-256）

以基準線目錄的 `config-<角色>.ini` 執行 `slicer-engine --export-support-stl`。高柱模型沒有模型檔，不在此比對。

| 模型 | 改動前 | 改動後 |
|---|---|---|
| 小 | `3c57cfbe3035fa413876e1a442cc302968a30c234a45e024f2ea088cf23cce7d` | `3c57cfbe3035fa413876e1a442cc302968a30c234a45e024f2ea088cf23cce7d` |
| 中 | `200244e07f461b108b74b3ee84b7051aa0b44c75a7d8a73238fce806494fd2fe` | `200244e07f461b108b74b3ee84b7051aa0b44c75a7d8a73238fce806494fd2fe` |
| 滿版 | `4a6993bb08b66347f35f56de8bc2042e96643997bf770b744d3f6bced65b2665` | `4a6993bb08b66347f35f56de8bc2042e96643997bf770b744d3f6bced65b2665` |

滿版的雜湊也與 `scripts/raster_bench/manifest.json` 中 `primary-16k-guide-x8` 的凍結支撐雜湊相同。那份凍結支撐是用更早的引擎產生的。

## 檔案

- `runs.jsonl`：本次每一次執行的完整雜湊與指標，格式同基準線。
- `plan.json`：執行計畫，與基準線的 `plan.json` 相同，只有輸出路徑不同。
- `run.stdout.log`：測試程式的原始輸出。

重新驗證（`runs.jsonl` 以附加方式寫入，重跑前請先移走舊檔）：

```
BRACING_BASELINE_PLAN=<本目錄>/plan.json build/tests/sla_print/Release/sla_print_tests.exe "[.bracing_baseline]"
```

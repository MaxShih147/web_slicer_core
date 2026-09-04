# 驗證筆記

本檔記錄實作過程的基準值與環境資訊，供各階段的驗收檢查點比對。

## 0.1 起始環境

| 項目 | 值 |
|------|---|
| 子模組 | `third_party/prusaslicer_fork` |
| 分支 | `feature/manual-edit-tree-support`（非 `release/*`，符合前置要求） |
| 起始 commit | `0ac2feffc` |
| 既有未提交改動 | `.gitignore`、`src/libslic3r/CMakeLists.txt`、`src/slic3r/CMakeLists.txt`（本變更之前即存在，非本次產生） |
| 基準用引擎 | `third_party/prusaslicer_fork/build/src/Release/slicer-engine.exe` |
| 引擎建置時間 | 2026-09-03 09:19（晚於最新原始碼 2026-08-29，確認為 HEAD 的建置產物） |

**回滾方式**：`git -C third_party/prusaslicer_fork checkout 0ac2feffc -- src/`

## 0.4 基準參數

取自 `agent/jobs/95070208/config.ini`，未經修改。

| 參數 | 值 |
|------|---|
| `support_critical_angle` | `45.0` |
| `support_tree_type` | 未設定，走引擎預設 `Default` |
| `supports_enable` | `1` |
| `pad_enable` | `1` |
| `support_head_front_diameter` | `0.4` |
| `layer_height` / `initial_layer_height` | `0.15` |
| `display_pixels_x` / `y` | `2560` / `1440` |

## 基準模型

取自 `third_party/prusaslicer_fork/tests/data/`，屬版本控管內的檔案，任何人皆可重現。

| 模型 | 選用理由 |
|------|---------|
| `U_overhang.obj` | 含大面積平坦朝下面，是角度過濾最不會動到的一類幾何 |
| `frog_legs.obj` | 含連續傾斜的有機曲面，是角度過濾影響最大的一類幾何 |

## 0.3 變更前支撐點基準

以 `--export-support-points` 搭配上述組態取得。

| 模型 | 支撐點數 |
|------|---------|
| `U_overhang.obj` | 20 |
| `frog_legs.obj` | 172 |

## 0.2 變更前逐層基準

以 `--export-sla` 搭配上述組態取得。`layers_sha256_all` 為所有層 PNG 各自 SHA-256 串接後再取一次 SHA-256 的滾動值。

### `U_overhang.obj`

| 項目 | 值 |
|------|---|
| `layer_count` | 120 |
| `layers_sha256_all` | `8d0e183a9eb4200760cc49e04cc978437d5e87f44949bfadcee7dca6a87cf6d6` |
| 第 1 層 SHA-256 | `cd803866c49bf7ba7002b6b05df7e3a68bda135d6159c7842955780cf8f53651` |
| 第 2 層 SHA-256 | `13ab561ab7a1be4948533e617df774f331f903c50e7abead1b273d60ccf86f91` |
| 第 3 層 SHA-256 | `13ab561ab7a1be4948533e617df774f331f903c50e7abead1b273d60ccf86f91` |
| `usedMaterial` | `0.969384` |
| `printTime` | `1920.000004` |

### `frog_legs.obj`

| 項目 | 值 |
|------|---|
| `layer_count` | 60 |
| `layers_sha256_all` | `ee449933c3931e0587c42ff362bf0711f8ec303880e1c58fc707bcc1bbe420cd` |
| 第 1 層 SHA-256 | `e121d88025c9d13f65aed01b52c2781dbc94dab4b927f7f30308d21946d74827` |
| 第 2 層 SHA-256 | `e48d8a2724f0fa0a767f01a46835790f6ba5364357cfef0613a7d5d87911c05f` |
| 第 3 層 SHA-256 | `ee7c6d71b44a3930ffd2344c16b0ec3ae7f2bd7b3df567b3b826867f15bc3ab0` |
| `usedMaterial` | `5.215144` |
| `printTime` | `975.000002` |

## 基準的用途

- **1.R.4（階段一驗收）**：階段一為純重構，上述逐層 SHA-256 與支撐點數 MUST 完全相同。任何差異都代表函式抽換出錯。
- **2.R.2（階段二驗收）**：支撐點數預期少於或等於上表，減少集中在 `frog_legs`。
- **3.R.6（階段三驗收）**：逐層 SHA-256 預期與上表不同（design.md R1），差異方向應為支撐變多。
- **6.1（重新基準化）**：原訂以最終版引擎重跑並取代本節數值。**實測後判定不需要**——輸出與本節基準逐位元相同，本節數值全部保留不動。理由見下方「6.1 重新基準化」。

## 6.1 重新基準化：實測零回歸，沿用原基準

**結論：階段 0 的基準數值全部有效，不需重算，本檔上方的表格一律不改動。**

以階段三完成後的 `slicer-engine.exe`（建置於 2026-09-03 16:48，晚於全部原始碼修改）重跑兩個基準模型的完整切片，結果與階段 0 舊基準**逐位元完全相同**：

| 模型 | 層數 | `layers_sha256_all` | `usedMaterial` | `printTime` |
|------|-----|---------------------|---------------|-------------|
| `U_overhang.obj` | 120（不變） | `8d0e183a9eb4200760cc49e04cc978437d5e87f44949bfadcee7dca6a87cf6d6`（相同） | 0.969384（不變） | 1920.000004（不變） |
| `frog_legs.obj` | 60（不變） | `ee449933c3931e0587c42ff362bf0711f8ec303880e1c58fc707bcc1bbe420cd`（相同） | 5.215144（不變） | 975.000002（不變） |

### 為何 R1 沒有觸發

design.md 的 R1 預期支撐點提前過濾後，逐層輸出會改變。前提是「被角度剔除的點恰為某個去重群的代表，且該群另有成員可遞補」。

實際上去重半徑只有 **0.1 mm**（`DefaultSupportTree.cpp` 的 `cluster()`），而支撐點取樣的實際間距遠大於此，含兩個以上成員的群極為罕見。`frog_legs` 被剔除的 5 個點經實測全為孤立點，移除後無任何成員遞補，最終幾何完全未變。

### 此結論的界線

「零回歸」只對**這兩個模型**成立，不是對本變更的普遍保證。R1 描述的機制依然存在，只是這兩個模型沒有踩到。**日後若改用其他基準模型，必須逐案重新確認，不得直接引用本節結論。**

另需注意：「輸出不變」本身不足以證明第 6 步的閘門確實已從執行檔中移除。該事實另以 `--import-support-points` 煙霧測試獨立驗證（記錄於 design.md 的「CLI 層級的閘門移除驗證」）。

---

## 6.2 新舊差異摘要

### 支撐點數變化

| 模型 | 變更前 | 變更後 | 差異 |
|------|-------|-------|------|
| `U_overhang.obj` | 20 | 20 | 0 |
| `frog_legs.obj` | 172 | 167 | −5 |

「變更前」取自階段一的匯出。階段一是純重構，1.R.4 已驗證其輸出與階段 0 基準逐位元相同，故可代表變更前行為。

### 型別分佈分析

| 模型 | 變更前 | 變更後 | 差異 |
|------|-------|-------|------|
| `U_overhang.obj` | `island` 20 | `island` 20 | 無 |
| `frog_legs.obj` | `island` 168、`slope` 4 | `island` 163、`slope` 4 | `island` −5、`slope` 0 |

**被剔除的 5 個點全部是 `island` 型，`slope` 型一個都沒被剔除。**

這個分佈本身就是本變更要修的問題的證據。`island` 點由「孤島偵測」放置——某一層出現與下方無連接的封閉區域時，就在該區域放點，**放置時完全不考慮該處表面的傾斜方向**。所以孤島點會落在角度不足的陡峭面上，變更前這些點會被匯出給使用者看，卻在第 6 步被靜默丟棄，成為孤兒點。

反觀 `slope` 型的點，本來就由斜度啟發式放置，位置與懸空方向相關，因此全數通過角度過濾。

### 支撐柱數變化

**0（兩個模型皆是）。** 逐層 SHA-256 完全相同即代表最終幾何未變，支撐柱數必然未變。這 5 個被剔除的點在變更前也長不出支撐柱——它們正是本變更要消除的孤兒點。

### 對使用者的實際影響

對這兩個模型而言，本變更是**純粹的顯示與交換格式修正**：列印結果完全一樣，但匯出的點清單不再包含 5 個永遠長不出支撐的假點。

---

## 重現指令

```
ENG=third_party/prusaslicer_fork/build/src/Release/slicer-engine.exe
CFG=agent/jobs/95070208/config.ini
DATA=third_party/prusaslicer_fork/tests/data

# 支撐點
$ENG --export-support-points <out>/<model>_points.json --load $CFG $DATA/<model>.obj

# 完整切片
$ENG --export-sla --load $CFG --output <out>/<model>.sl1 $DATA/<model>.obj
```

逐層雜湊的計算方式：開啟 `.sl1`（zip），取出所有非縮圖的 `.png` 條目並依名稱排序，各自 SHA-256 後串接，再對串接結果取一次 SHA-256。

# 量測：agent-large-model-perf

## 條件

- 日期：2026-11-11；機器：交接量測同一台（i9-13900H、Windows 11）。
- Python：`web_slicer_core/.venv`（trimesh 5.1.0、numpy 2.5.3、manifold3d）。安裝版 agent 自帶 trimesh 5.2.0、manifold3d 3.5.4，未用安裝版重量。
- **沒有使用 `TriangleStress_5M.stl`**（session 中未取得）。改用合成檔：icosphere subdivisions 9、半徑 30 mm、加上正弦起伏，**5,242,880 面、262 MB binary STL**，與 TriangleStress_5M（515.8 萬面、258 MB）同級。不是病患資料。
- 「改前」＝ 本分支起點 commit 的乾淨 checkout；「改後」＝ 本分支。兩者用同一支腳本（`bench.py`，各自獨立的 Python 程序）。
- 從終端機執行，**不經 Electron 啟動器**，所以不受 EcoQoS 影響；以下數字只反映 F1，不含 E。

## 結果

| 項目 | 改前 | 改後 | 說明 |
|---|---|---|---|
| `_validate_stl_bytes`（5M） | 14.12 s | < 0.001 s | 只讀檔頭與大小 |
| 5 次「上傳 → generate-supports」後 pending job 持有的模型 bytes | 1311 MB | 0 MB | 模型寫入 `input/model.stl` 後釋放 |
| 同上，程序 RSS 增加 | 2257 MB | 1 MB | 改前另含 trimesh 驗證的暫存 |
| `boolean_operation` union（5M 模型 + 小方塊） | 32.23 s | 15.47 s | 含讀檔、合併頂點、Manifold、union、寫檔 |
| boolean 結果 | 5,240,188 面、封閉、體積 113552.120961 | 5,240,188 面、封閉、體積 113552.120961 | 完全相同 |

boolean 改後各段（另行單獨量測）：numpy 讀檔 0.12 s、合併頂點 3.2 s（`trimesh.load` 6.4 s），其餘為 manifold 建構、union 與寫檔。

## 推估對 5M 壓印 POST 的影響

交接量到的壓印 POST 66–69 s 中，F1 拿掉：上傳驗證（交接 11.1 s）、boolean 讀檔與結果轉換（交接 12.4 + 3.4 + 3.5 + 2.1 s，改為約 3.3 s 讀檔合併與約 0.5 s 寫檔）。在未修正節流的情況下推估約 66 → 35 s；E 生效後再少約 27 s。**以上為推估，需用 TriangleStress_5M 經實際 agent（Electron 啟動）重量。**

## 端對端量測：經 HTTP、實際引擎（2026-11-11）

### 條件

- 依前端順序用 HTTPS 呼叫 agent：建立 job → 上傳 → `PUT config`（`supports_enable`、`pad_enable`）→ `generate-supports` 或 `execute` → 輪詢到 `completed`；壓印為 `POST /api/v2/boolean`（5M 模型 + 8×3×1.5 mm 方塊）。
- 同一份合成 5M 檔（同上）。三個版本都用安裝目錄的 Python runtime（trimesh 5.2.0、numpy 2.5.4）與 `slicer-engine.exe`，差別只在 agent 程式與啟動方式：
  - **安裝版**：已安裝的 Local Agent（agent build `ab63b7282120`），由 Electron 啟動器帶起，port 5179。
  - **舊版**：合併前的 `dev`（`1445bbc`）的 `agent/`，從 shell 啟動，`SLICE_PROFILING=1`。
  - **新版**：合併後的 `dev`（`8f71ad5`）的 `agent/`，從 shell 啟動，`SLICE_PROFILING=1`。
- 兩輪：第 1 輪依序安裝版 → 舊版 → 新版；第 2 輪新版、舊版交替各兩次。新版共 3 次，表中為範圍。

### 結果（秒）

| 流程 | 安裝版（啟動器帶起） | 舊版，未被節流（第 1 輪） | 舊版，被節流（第 2 輪） | 新版 |
|---|---|---|---|---|
| 上傳 | 18.4 / 20.3 | 6.6 / 6.9 | 18.7–19.3 | 0.5–0.9 |
| 產生支撐（引擎） | 23.5 | 8.6 | 22.8–22.9 | 8.1–13.2 |
| **自動支撐合計** | **41.9** | 15.5 | 41.6–42.1 | **8.6–13.7** |
| 切片（引擎） | 52.2 | 15.2 | 44.8–51.2 | 15.9–24.2 |
| **切片合計** | **72.5** | 21.7 | 64.1–70.0 | **16.7–25.1** |
| **文字壓印 POST** | **58.8** | 21.6 | 37.1–57.5 | **8.9–11.3** |
| `profile.json` `engine-startup` | — | 3.0 | 2.9–3.0 | 2.8–3.8 |
| `profile.json` `STAGE_SLICING` | — | 8.0 | 37.4–37.6 | 8.9–15.7 |
| 連續產生支撐時 agent private memory | — | 持續上升（最高約 6.1 GB） | 同左 | 固定約 1.39 GB |

### E 的驗證

- 量測期間以 `GetProcessInformation(ProcessPowerThrottling)` 查詢每個 agent 與 `slicer-engine.exe`：新版 agent 與它啟動的 7 個引擎全部是 `ControlMask=1 StateMask=0`（明確關閉執行速度節流）；安裝版與舊版的 agent 及其引擎都是 `0/0`（交由系統決定）。
- 舊版同一份程式、同一個 shell 啟動，第 1 輪（剛啟動）未被節流，閒置數分鐘後的第 2 輪被系統節流，速度掉到與安裝版相同（`STAGE_SLICING` 8.0 → 37.5 s，上傳 6.8 → 19 s）。新版在同樣條件下維持 8.9–15.7 s。也就是說，不只由啟動器帶起的 agent 會被節流，背景閒置的 agent 也會；E 對兩者都有效。

### 解讀與限制

- 安裝版 → 新版：自動支撐約 3.5 倍、切片約 3.5 倍、壓印約 6 倍。
- **合成檔的引擎讀檔＋修復只要約 3 s**（`engine-startup`），交接量的 TriangleStress_5M 約 32 s。實檔上 E＋F1 省下的秒數相近，但支撐與切片會多出約 30 s，那段屬 F3。
- 新版的引擎時間波動（切片 15.9–24.2 s）推測為筆電長時間滿載後的發熱降頻；最快一次 `STAGE_SLICING` 8.9 s，與舊版未被節流時（8.0 s）相當，不是 E 造成的變慢。
- 安裝版 agent 在量測後多持有一份 5M 模型（舊版記憶體洩漏），重啟 agent 即釋放。

## TriangleStress_5M 實檔（2026-11-11）

### 條件

- 檔案：`TriangleStress_5M.stl`（交接文件的合成測試檔，非病患資料），binary STL，5,157,984 面、257.9 MB。
- **舊版**：合併前 `dev`（`1445bbc`）的 `agent/`，從 shell 啟動，`SLICE_PROFILING=1`，安裝目錄的 Python runtime 與 `slicer-engine.exe`。
- **新版**：安裝的測試版（agent `9e91f57`，由 `Bundle-Launcher-prod` `-RepackageOnly` 打包，slicer-engine 與 1.0.6.1 逐 byte 相同），**由啟動器正常帶起**。
- 同樣以 HTTPS 依前端順序呼叫；壓印的 mesh_b 為跨在模型頂面的 8×3×1.5 mm 方塊。新舊交替兩輪，最後各做一次「連續 5 次上傳＋產生支撐」。
- 引擎程序節流狀態：新版 agent 與它啟動的引擎全部 `ControlMask=1 StateMask=0`；舊版皆為 `0/0`。舊版這次**未被節流**（`STAGE_SLICING` 5.0 / 8.9 s，在未節流範圍），所以下表新舊差異只反映 F1，不含 E。

### 結果（秒）

| 流程 | 交接量測（1.0.6.3，啟動器帶起、被節流） | 舊版（未被節流） | **新版（啟動器帶起）** |
|---|---|---|---|
| 上傳 | 22.7–23.2 | 7.1–7.9 | **0.4–0.6** |
| 產生支撐（引擎） | — | 25.7 / 28.8 | **25.7 / 26.5** |
| **自動支撐合計** | **約 90** | 33.1 / 36.8 | **26.2 / 27.0** |
| 切片（引擎） | — | 29.2 / 34.1 | **29.5 / 31.8** |
| **切片合計** | **約 87** | 36.3 / 41.3 | **29.9 / 32.2** |
| **文字壓印 POST** | **66–69** | 21.3 / 21.8 | **8.5 / 9.5** |
| 連續 5 次產生支撐 | — | 284.8（agent private memory 最高約 4.5 GB） | **151.7**（記憶體固定約 1.39 GB） |
| 舊版 `engine-startup`（讀檔＋修復） | 約 32–45 | 21.3 / 21.7 | — |

### 解讀

- 相對交接量測的現況（被節流的 1.0.6.3）：自動支撐約 90 → 27 s、切片約 87 → 31 s、壓印 66–69 → 9 s。
- 相對未被節流的舊版（只看 F1）：上傳 7.5 → 0.5 s、壓印 21.5 → 9 s；支撐與切片的引擎時間不變。
- 新版剩下的支撐與切片時間幾乎全在引擎：讀檔＋修復約 21 s（`engine-startup`），屬 F3；其餘為切片、支撐點、光柵化。
- 舊版這次從 shell 啟動且未被節流，E 的效益沒有在新舊對比中出現；E 的實際效果見上一節第 2 輪（舊版閒置後被節流，`STAGE_SLICING` 8 → 37 s）與交接文件的量測。

## 沒有量到的部分

- **macOS**：未在 Mac 上執行（tasks 6.3、6.4）。

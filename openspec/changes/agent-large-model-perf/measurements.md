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

## 沒有量到的部分

- **E（EcoQoS）**：需要由 Electron 啟動器正常啟動的 agent 與 slicer-engine；本 session 的終端機程序不受節流。驗收方法照交接文件：`SLICE_PROFILING=1` 啟動，比較同一個 5M 切片的 `profile.json`（`engine-startup` 約 45 → 32 s、`STAGE_SLICING` 約 12 → 3.6 s）與 5M `/upload` 時間（約 24 → 12 s）。
- **macOS**：未在 Mac 上執行（tasks 6.3、6.4）。
- **TriangleStress_5M 實檔**：數字以合成檔為準，實檔頂點分布不同，合併頂點時間可能有差。

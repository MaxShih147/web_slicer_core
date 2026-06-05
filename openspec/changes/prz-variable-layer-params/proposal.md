## Why

目前 PRZ 雖然在格式上已啟用 Advance Mode（`# Advance Mode (1B) = 1`，允許各層帶各自參數），但 `prz_encoder._write_layer_definition` 實際上只用**單一全域層厚**推算每層高度（`z_pos = layer_height * (layer_idx + 1)`），其餘參數僅以 `is_bottom` 做底層／一般層二分，全部為固定值。

這造成一個結構性缺陷——**「切片事實」與「編碼參數」不對稱**：

- 真正知道「每層切在哪個 Z、厚多少」的是底層 prusaslicer_fork（它在累加切高）；但 encoder 卻**無視** `.sl1` 內的切片事實，自己用一條等高公式重算 Z。
- 在等高切片下兩者剛好巧合一致，所以至今沒出事；但只要要求「不同高度範圍用不同層厚與參數組合」，這條等高公式立即崩潰，且 Z 與 PNG 影像內容會**沉默地錯層**（不報錯、印出廢品）。

本變更要讓 encoder 不再臆測切片事實，而是**忠實反映 prusaslicer_fork 實際切出來的逐層高度**，並在此真相之上，依前端定義的高度區間為每層挑選正確參數。

## What Changes

- **prusaslicer_fork（底層／切片端）**
  - 依前端傳入的「高度區間 → 層厚」設定，以**變動層厚**切片，輸出對應張數與內容正確的 PNG 序列。
  - 切片完成後，於 `.sl1` **之外**輸出一份「逐層權威表」（暫定 `model.layers.json`，與 `model.sl1` 同置於 `job_dir/output/`）。此表**只含切片事實**：每層的 `z_end`、`thickness`、層序與層數，**不含**曝光／抬升等編碼參數。
  - 權威表內含一個**內容指紋**（對其所描述的那份 `.sl1` 實際內容計算，如排序後 PNG 檔名清單／位元組 digest），用以與 `.sl1` 強綁定。
  - 切片端在「為某層選層厚」時，邊界判定須遵守下方共同契約。

- **prz_encoder（後端／編碼端）**
  - 改為**模型 Y：查表照抄**——不再用 `layer_height * (idx+1)` 自算 Z，改讀權威表逐層取 `z_end` 作為 `z_pos`。
  - 依前端定義的「高度區間參數組合」，為每層挑選曝光／光熄／抬升／回抽／PWM 等參數；**區間→參數的比對全部留在 encoder**。
  - **身分校驗**：以「內容指紋 + 層數」雙重校驗權威表與手邊 `.sl1` 是否為同一次切片產物（Task ID 不足以證明，故不採用）。
  - **條件式 mandatory**（向後相容的關鍵）：
    - config 宣告**多個高度區間**（區間數 > 1）→ 權威表為**必要**；缺檔或校驗不符即**硬報錯停止**。
    - config 為**單一全域層厚** → 沿用現行等高路徑；**無權威表屬正常**，不報錯。
  - **BREAKING**：對宣告多區間的任務，缺少／不符的權威表將使編碼**失敗中止**，而非降級輸出。

- **共同契約（slicer 與 encoder 兩端必須逐字一致實作）**
  - **錨點**：以每層 `z_end`（層頂，即 PRZ 寫入的 `z_pos`）判定其所屬高度區間。
  - **量化**：Z 與區間邊界一律換算成**整數微米（µm）**後比較，杜絕浮點累加誤差（如 `10.00000003`）造成的邊界抖動。
  - **半開區間 `[low, high)`**：保證每一層**恰好被一個區間認領**——不重疊、不漏接。
  - 此契約同時約束 slicer 的「選層厚」與 encoder 的「選參數」，避免跨界層出現「厚度屬 A、曝光屬 B」的人格分裂。

## Capabilities

### New Capabilities
- `variable-layer-slicing`: prusaslicer_fork 依高度區間以變動層厚切片，並於 `.sl1` 之外輸出含內容指紋的逐層權威表（`z_end`／`thickness`／層數）。
- `prz-variable-layer-encode`: prz_encoder 以模型 Y 查表照抄逐層 `z_end`，依共同邊界契約（`z_end` + µm 量化 + `[low, high)`）比對高度區間挑選參數，並執行內容指紋＋層數雙重校驗與條件式 mandatory 讀取。

### Modified Capabilities
- `prz-motion-time`: 逐層定義不再以單一全域層厚推算 `z_pos`，改為查權威表；逐層參數來源由「底層／一般層二分」擴展為「依高度區間」。
- `slice-config-intake`: 後端設定結構新增「高度區間 → 層厚＋參數組合」陣列，並據區間數決定是否進入變動層厚流程。

## Impact

- **底層**：`third_party/prusaslicer_fork`（變動層厚切片 + 權威表輸出）。
- **後端切片整合**：`agent/sla_operations.py`（`generate_config_ini`／`slice_model` 傳遞區間設定、產出並落地權威表）、`agent/config.py`／`agent/models.py`（`SLAConfig` 與設定 schema 擴充）。
- **後端編碼**：`agent/prz_encoder.py`（`_write_layer_definition`、`encode_prz`／`encode_prz_streaming` 改為讀權威表、區間比對、校驗與條件式 mandatory）。
- **API**：`agent/api_v2.py`／`agent/main.py` 的 PRZ 產生端點（讀取權威表路徑、校驗失敗時回傳明確錯誤）。
- **前端（非本變更負責，但為上游契約）**：`DS-online` 需提供「高度區間參數組合」的資料結構。
- **相容性**：所有既有等高任務不受影響（無權威表即走原路徑）。
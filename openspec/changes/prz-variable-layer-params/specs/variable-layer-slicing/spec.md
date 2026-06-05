## ADDED Requirements

### Requirement: 依高度區間以變動層厚切片

prusaslicer_fork SHALL 接受一組由前端定義、依高度升冪、相鄰連續、無重疊且自 `0` 起的高度區間，每個區間帶各自的層厚（`thickness`），並據此產生對應張數與內容的 PNG 切片序列。

當某層在累加切高時跨越區間邊界，slicer 為該層選擇層厚的判定 SHALL 遵守與 encoder 共用的邊界契約：**以該層 `z_end`（層頂）為錨點、邊界以整數微米（µm）量化、採半開區間 `[low, high)`**。最上層（`z_end` 等於模型頂）SHALL 歸屬最末區間。

#### Scenario: 區間切換產生對應厚度的層序列
- **WHEN** 區間設定為 `[0, 10mm) @ 0.04mm`、`[10mm, 20mm) @ 0.10mm`
- **THEN** 第 1..250 層的 `thickness` SHALL 為 `0.04mm`（`z_end` 自 `0.04` 累加至 `10.00`）
- **AND** 第 251 層起 `thickness` SHALL 為 `0.10mm`（`z_end` 自 `10.10` 起）

#### Scenario: Boundary Alignment — z_end 恰落在區間邊界
- **WHEN** 某層的 `z_end` 量化後恰為 `10000µm`（= 邊界 `10mm`）
- **THEN** 依 `[low, high)` 半開規則，該層 SHALL 歸屬下界為 `10000µm` 的**上方區間**（`[10mm, 20mm)`）
- **AND** SHALL NOT 歸屬 `[0, 10mm)`（其上界 `10000µm` 為開區間，不含）

#### Scenario: Boundary Alignment — 浮點累加值須量化後判定
- **WHEN** 0.04mm 累加多次後某層 `z_end` 浮點值為 `10.00000003mm`
- **THEN** slicer SHALL 先量化為 `10000µm` 再判區間，使其歸屬與精確 `10mm` 完全一致
- **AND** MUST NOT 因浮點殘差而與 encoder 端判定結果分歧

### Requirement: 輸出 .sl1 外的逐層權威表

切片完成後，prusaslicer_fork SHALL 於 `.sl1` 之外輸出一份逐層權威表（`model.layers.json`，與 `model.sl1` 同置於 `job_dir/output/`）。該表 SHALL **僅含切片事實**（每層 `index`、`z_end_um`、`thickness_um`），MUST NOT 含曝光／抬升等編碼參數。

表內 SHALL 滿足：`layers` 依 `index` 連續升冪（`0..N-1`）、`source.layer_count == len(layers) ==` `.sl1` 內 PNG 張數、每層 `z_end_um == 前層 z_end_um + thickness_um`、所有值為正整數 µm、`units == "um"`。

#### Scenario: 權威表結構與單位
- **WHEN** 切出 240 層的變動層厚任務
- **THEN** `model.layers.json` SHALL 與 `model.sl1` 同目錄產生
- **AND** `source.layer_count` SHALL 等於 `240` 且等於 PNG 張數
- **AND** `layers[i].z_end_um` SHALL 為整數 µm 且嚴格單調遞增
- **AND** `units` SHALL 為 `"um"`

#### Scenario: 權威表內含內容指紋
- **WHEN** 寫出 `model.layers.json`
- **THEN** `source.fingerprint` SHALL 為對所描述 `.sl1` 計算的 `sha256`
- **AND** 指紋輸入 SHALL 為 `.sl1` 內所有 `*.png` entry 取 `(name, uncompressed_size, crc32)`、依 `name` 字典序排序、以 `"{name}|{size}|{crc32:08x}"` 用 `"\n"` 連接後的 UTF-8 bytes
- **AND** slicer 端與 encoder 端以相同規則計算 SHALL 得到相同指紋值

### Requirement: 權威表於 .sl1 完整寫出後才產生

slicer SHALL 在 `.sl1` 完整寫出**之後**才計算指紋並寫出 `model.layers.json`，確保「權威表存在」即蘊含「對應 `.sl1` 已完整」。

#### Scenario: Verification Failure — 切片中途崩潰不留下半套產物對
- **WHEN** `.sl1` 寫到一半即崩潰
- **THEN** `model.layers.json` SHALL NOT 被寫出
- **AND** 下游 encoder 對多區間任務 SHALL 因「mandatory 缺檔」而中止（見 `prz-variable-layer-encode`）

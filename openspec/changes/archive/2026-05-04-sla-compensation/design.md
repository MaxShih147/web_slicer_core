## Context

`web_slicer_core` 的 SLA 切片流程以 `third_party/prusaslicer_fork`（base commit `2ae9d24`）作為切片 binary，透過 `--load config.ini` 傳遞參數，再以 subprocess 呼叫。目前缺少兩類幾何補償能力：

1. **收縮補償（Shrinkage）**：固化後材料體積收縮，需在切片前對 3D mesh 預先放大。
2. **公差補償（Tolerance）**：SLA 列印的孔洞偏小、外徑偏大，需對每層 2D 輪廓執行方向性 offset。

參考實作位於 `D:\repos\PhrozenOrca`（commits `2be8e66`、`3f8cb9a`），本次將演算法 port 至 `prusaslicer_fork`，並在 Python 層暴露 API。Phase 1（C++）與 Phase 2（Python）嚴格序列執行，Phase 1 編譯通過後才進行 Phase 2。

## Goals / Non-Goals

**Goals:**
- 在 `prusaslicer_fork` 中實作 shrinkage 縮放（`sla_trafo()`）與 tolerance 輪廓偏移（`apply_printer_corrections()`）
- 新增 11 個 config 參數，可透過 `--load config.ini` 控制補償行為
- 在 `web_slicer_core` Python 層將這 11 個參數暴露為 DS-Online API 欄位
- `"Print.Bottom Layer Count"` 零前端改動：既有 PRZ 底層曝光流程不受影響，同一個 key 同時供 C++ tolerance 底層分界使用

**Non-Goals:**
- 不修改 PrusaSlicer GUI 介面或 GUI invalidation 機制
- 不實作自動化幾何精度量測（驗證依賴 BOOST_LOG_TRIVIAL 日誌 + 人工 UVtools 目視）
- 不修改 `prz_encoder.py` 的 PRZ 底層曝光邏輯
- 不為 tolerance a/b 進行任何正負號轉換（後端 Raw Offset，前端負責 UI 語意轉換）

## Decisions

### D1：新參數宣告於 `PrintObjectConfig`（FDM 層），而非 `SLAPrintObjectConfig`

`SLAPrintObject::invalidate_state_by_config_options()` 對未知 key 呼叫 `assert(false)`，若將新參數放入 `SLAPrintObjectConfig`，必須修改這個完整的 switch 語句（高風險、高移植成本）。`PrintObjectConfig` 的 key 不出現在 `object_diff` 中，完全繞開此 assert。

替代方案（已排除）：放入 `SLAPrintObjectConfig` + 補全 switch — blast radius 過大，PhrozenOrca 也未採用此路徑。

**C++ 原始碼要求**：參數宣告處必須加注解：
```cpp
// SLA compensation params: declared here (PrintObjectConfig/FDM tier) rather than
// SLAPrintObjectConfig to avoid patching the SLA state-invalidation switch.
// CLI-only usage; changes detected via manual cache in SLAPrint::apply().
```

### D2：Manual Cache 模式（不依賴 SLA state invalidation 機制）

在 `SLAPrint` 上新增 member cache，於 `apply()` 手動讀取、比較、invalidate：

- **Tolerance 參數變更** → `invalidate_step(slapsMergeSlicesAndEval)` + 所有 object 的 `invalidate_step(slaposObjectSlice)`
- **Shrinkage 參數變更** → `invalidate_step(slapsMergeSlicesAndEval)` + 所有 object 的 `invalidate_all_steps()` + `set_trafo()`

此模式與 PhrozenOrca 參考實作完全一致，diff-free 移植。

### D3：bool 預設值統一為 `false`（與 PhrozenOrca 不同）

PhrozenOrca 中 `bool tc = true`（公差開關預設開啟）。本實作刻意設為 `false`，理由：
- **Safe Defaults**：config.ini 缺少 key 時應靜默退回無補償狀態。
- **兩端嚴格一致**：C++ 預設 `false` ↔ Python 預設 `False`，不存在跨層邊界差異。

**C++ 實作要求**：
```cpp
// Default false (not true as in PhrozenOrca): safe-off when key is absent from config.ini.
bool tc = false, btc = false;
```

### D4：Shrinkage 資料合約——百分比格式，C++ 唯一做換算

| 層 | 值 | 說明 |
|----|-----|------|
| DS-Online → Python | `100.0` | 百分比，100 = 不縮放，102 = 放大 2% |
| Python `SLAConfig` default | `100.0` | 直接存儲，不做換算 |
| Python → config.ini | `shrinkage_compensation_x = 100.0` | 原封不動寫入 |
| C++ `sla_trafo()` | `corr.x() *= v / 100.0` | 唯一做除以 100 的地方 |

Python 層零轉換，C++ 端負責 `/100.0`。

### D5：Tolerance 符號語意合約——Raw Offset，後端零轉換

| 參數 | 正值語意 | 負值語意 |
|------|---------|---------|
| `a` | 實體向孔洞擴張（孔縮小） | 實體離孔洞收縮（孔變大） |
| `b` | 實體向外擴張（外輪廓變大） | 實體向內收縮（外輪廓縮小） |

Python 收到數值後直接寫入 config.ini，絕對不翻轉正負號。若 DS-Online UI 採用「正數 = 孔變大」語意，前端在發送 API payload 前自行乘以 `-1`。

### D6：`bottom_layer_count` 一魚兩吃——前端零改動

DS-Online 已送出 `"Print.Bottom Layer Count"` 用於 PRZ 曝光控制（`prz_encoder.py` 消費）。`_convert_v2_config_to_sla()` 的 `print_config` 指向相同的 `config["Print"]`，只需新增一條 mapping 即可讓相同數值同時寫入 `config.ini` 供 C++ tolerance 底層分界使用。

### D7：永久日誌——`BOOST_LOG_TRIVIAL(info)`

日誌永久保留（不加 debug flag），與 `SLAPrint.cpp` / `SLAPrintSteps.cpp` 現有規範一致。

| 位置 | 日誌訊息 |
|------|---------|
| `sla_trafo()` shrinkage 套用時 | `[shrinkage] applying x=? y=? z=?` |
| `apply_printer_corrections()` tolerance 一般層 | `[tolerance] applying tc a=? b=? layers=?..?` |
| `apply_printer_corrections()` tolerance 底層 | `[tolerance] applying btc a=? b=? layers=0..?` |

## Risks / Trade-offs

**[風險] `PrintObjectConfig` 參數對 SLA GUI 不可見** → 本 fork 是 CLI-only，無 GUI 使用者，影響範圍為零。若未來需要 GUI 支援，需重新評估參數歸屬。

**[風險] C++ manual cache 與實際 config 狀態脫節（熱重載場景）** → CLI-only One-shot 執行，每次呼叫都是全新 process，不存在熱重載場景，此風險不適用。

**[風險] `bottom_layer_count` 語意耦合（tolerance 底層 ≠ 曝光 faded_layers）** → C++ 端 `bottom_layer_count` 為獨立 `PrintObjectConfig` 參數，與 `faded_layers` 完全解耦，兩者可獨立調整，維持正交性。

**[風險] bool 序列化格式不相容** → 已確認 `generate_config_ini()` 輸出 `1`/`0`，與 PrusaSlicer `ConfigOptionBool` 解析相容。

**[取捨] 驗證採目視而非自動化幾何解析** → 演算法移植自成熟的 PhrozenOrca 邏輯，自動化 `.sl1` 解析屬過度工程。以日誌確認分支進入 + UVtools 目視確認幾何，成本最低、風險可接受。

## Why

SLA 光固化列印存在兩類系統性尺寸誤差：材料固化後整體收縮（需 3D mesh 縮放補償），以及孔洞偏小、外徑偏大的列印公差（需每層 2D 輪廓偏移補償）。目前 `web_slicer_core` 與 `prusaslicer_fork` 皆無此功能，導致工件尺寸精度不足，DS-Online 無法提供使用者調整介面。

## What Changes

- **C++ 底層**（`third_party/prusaslicer_fork`）：新增 11 個 config 參數（收縮補償 4 個、公差補償 7 個），實作 shrinkage 縮放（作用於 `sla_trafo()`）與 tolerance 輪廓偏移（作用於 `apply_printer_corrections()`）演算法
- **Python 模型層**（`agent/models.py`）：`SLAConfig` 新增對應的 11 個欄位，含安全預設值
- **Python API 層**（`agent/api_v2.py`）：`_convert_v2_config_to_sla()` 新增 11 組 DS-Online key → snake_case 欄位 mapping
- `"Print.Bottom Layer Count"` 採「一魚兩吃」：既有的 PRZ 底層曝光流程不動，同一個 key 同時寫入 `config.ini` 供 C++ tolerance 底層分界使用（前端零改動）
- 永久保留 C++ 端補償觸發日誌（`BOOST_LOG_TRIVIAL(info)`），符合 CLI-only observability 需求

## Capabilities

### New Capabilities

- `shrinkage-compensation`：SLA 收縮補償——透過 `sla_trafo()` 在切片前對 3D mesh 套用 X/Y/Z 各軸縮放（百分比格式，100.0 = 不縮放），以及對應的 Python API 欄位與 DS-Online key mapping
- `tolerance-compensation`：SLA 公差補償——在 `apply_printer_corrections()` 對每層輪廓執行 2D offset（孔洞與外輪廓分開處理），支援一般層與底層獨立設定，以及對應的 Python API 欄位與 DS-Online key mapping

### Modified Capabilities

（無——現有 `prz-layer-session`、`prz-parser` 兩個 spec 的需求不受影響）

## Impact

**C++ 修改檔案**（`third_party/prusaslicer_fork/src/libslic3r/`）：
- `PrintConfig.hpp` — `PrintObjectConfig` macro 新增 11 個參數宣告
- `PrintConfig.cpp` — 新增 11 個參數定義，移除 tolerance_a/b 的 `def->min = 0` 限制
- `SLAPrint.hpp` — 新增 4 + 7 個 cache member variables
- `SLAPrint.cpp` — `apply()` 新增 manual cache 比對與 invalidate 邏輯；`sla_trafo()` 套用 shrinkage 縮放
- `SLAPrintSteps.cpp` — `apply_printer_corrections()` 插入 tolerance offset 邏輯

**Python 修改檔案**（`agent/`）：
- `models.py` — `SLAConfig` 新增 11 個 Pydantic 欄位
- `api_v2.py` — `_convert_v2_config_to_sla()` 新增 11 組 key mapping

**不受影響**：
- `prz_encoder.py`（`"Print.Bottom Layer Count"` 既有讀取邏輯保持不變）
- `generate_config_ini()`（已透過 `model_dump()` 自動序列化，不需修改）
- `SLAPrintObject::invalidate_state_by_config_options()`（新參數放在 `PrintObjectConfig`，不觸發 SLA state invalidation switch）

## Context

`prz_encoder.py` 完整實作了 PRZ V3.0 的二進位編碼（header 195,477 bytes + per-layer 定義 64 bytes + RLE 圖像）。`prz_pwm_patcher.py` 有基本的 layer 位置掃描（用於 PWM 修補），但只讀取必要偏移量，不還原任何欄位語義。目前系統無法從 .prz 檔案讀回列印設定或圖層影像。

## Goals / Non-Goals

**Goals:**
- 實作完整的 PRZ V3.0 header 解析（所有欄位，依照 encoder 的位元組佈局）
- 實作 per-layer 定義解析（exposure、lift/retract 參數、PWM）
- 實作 RLE 解碼（自定義格式逆運算），還原灰度像素
- 實作 RGB565 → RGB 預覽圖解碼
- 新增 API 端點：上傳 .prz → 回傳 header JSON + base64 預覽圖

**Non-Goals:**
- 不修改 `prz_pwm_patcher.py`（保持其獨立性）
- 不支援 V3.0 以外的版本
- 不做 PRZ → SL1 的完整還原（不重新包裝為 ZIP）
- 不在前端解碼（此次只做後端模組）

## Decisions

### 1. 新增獨立模組 `agent/prz_decoder.py`，不修改 patcher

**選項：**
- A. 新增 `prz_decoder.py`（獨立模組）
- B. 擴充 `prz_pwm_patcher.py` 加入解碼功能

**選擇 A，理由：** patcher 是獨立 CLI 工具，耦合它會讓兩個關注點混雜。decoder 日後可被 API、測試、其他工具直接 import，不應依賴 patcher 的實作細節。

### 2. 以 `dataclass` 表示結構化輸出

Header 與每層定義欄位多（各 30+ 個），用 `dataclass` 可提供型別提示、欄位名稱自文件化，且可直接序列化為 dict（`dataclasses.asdict()`）供 API 回傳。

```python
@dataclass
class PrzHeader: ...      # 所有 header 欄位
@dataclass
class PrzLayerDef: ...    # 單層定義（不含圖像）
@dataclass
class PrzFile:
    header: PrzHeader
    preview_small: np.ndarray   # (116, 116, 3) uint8 RGB
    preview_large: np.ndarray   # (290, 290, 3) uint8 RGB
    layers: list[PrzLayerDef]
```

### 3. 圖層影像採**按需解碼**（非急切載入）

**選項：**
- A. `parse_prz()` 時一次解碼所有層圖像
- B. `PrzFile` 儲存各層 RLE 原始位元組，另提供 `decode_layer_image(i)` 方法

**選擇 B，理由：** 大型列印任務可能有數百層，全部解碼成 numpy array 可能佔用數 GB RAM。API 端點（回傳設定 JSON）不需要圖像，按需解碼更符合預期使用模式。`decode_layer_image(i)` 可讓未來端點或工具按層索取。

### 4. RGB565 解碼使用 numpy 向量化

與 encoder 的 `_rgb_to_rgb565_be()` 對稱，decoder 也用 numpy 處理 16-bit 向量逆運算，不用 Python loop。

### 5. RLE 解碼採順序狀態機（bytes iterator）

RLE 格式是可變長度，難以完全向量化解碼。使用簡單的 `memoryview` + 索引掃描：讀 first byte → 判斷 color type 和 byte_count_bits → 若灰階先讀 1 byte 灰度值 → 再讀 extra bytes → 填像素陣列。

> **注意**：gray_value 在 extra bytes 之前（與 encoder 的寫入順序相同：`[first_byte][gray_value][extra_bytes...]`）。設計早期描述順序有誤，已依實作修正。

### 6. API 端點放在 `api_v2.py`，路由為 `POST /prz/parse`

`api_v2.py` 是新架構入口，`main.py` 是舊版。新端點遵循 v2 風格：
- 接受 `multipart/form-data`（`file` 欄位）或 `application/octet-stream`
- 回傳 JSON：header 所有欄位 + `preview_small_b64`、`preview_large_b64`（PNG base64）
- 不解碼圖層影像（可另開端點 `POST /prz/layer/{index}`）

## Risks / Trade-offs

- **RLE 解碼邊界條件** → 對照 encoder 的 `_encode_run()` 逐 case 驗證，並加單元測試（round-trip：encode → decode → compare）
- **大檔案記憶體** → 按需解碼圖層可緩解；API 端點限制上傳大小（如 500 MB）
- **patcher 邏輯重複** → 兩個模組各自維護層掃描邏輯，若格式有變需同步更新。短期可接受，長期可考慮抽共用 `_scan_layers()` helper

## Migration Plan

1. 新增 `agent/prz_decoder.py`（純加法，不影響現有功能）
2. 在 `api_v2.py` 新增 `POST /prz/parse` 端點
3. 手動測試：用現有 encoder 輸出的 .prz 檔做 round-trip 驗證
4. 無需 rollback 策略（純新增，不改現有路由）

## Open Questions

- API 是否需要 `POST /prz/layer/{index}` 端點（回傳單層灰度 PNG）？若有需求可在 tasks 中列為 optional。
- 是否需要驗證 magic bytes 並在格式不符時回傳明確錯誤（400 vs 500）？→ 建議是，加入 magic byte 校驗。

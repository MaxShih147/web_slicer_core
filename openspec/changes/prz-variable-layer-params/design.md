## Context

`prz_encoder._write_layer_definition` 目前以 `z_pos = layer_height * (layer_idx + 1)`（[prz_encoder.py:682](../../../agent/prz_encoder.py#L682)）用**單一全域層厚**自算每層高度，參數僅以 `is_bottom` 二分。`.sl1` 內的切片事實被忽略，等高切片下兩者巧合一致，因此至今無誤。

本變更導入「不同高度區間使用不同層厚＋參數組合」。如 proposal 所述，採**模型 Y**：由 prusaslicer_fork 輸出逐層權威表（`.sl1` 外的獨立 JSON），encoder **查表照抄 Z**，並在此真相上依高度區間挑參數。本文件定義四項關鍵實作：(1) 權威表資料結構、(2) 內容指紋演算法、(3) µm 量化與區間比對邏輯、(4) 錯誤處理與例外定義。

## Goals / Non-Goals

**Goals:**
- 定義 `model.layers.json` 的明確資料結構與單位約定（canonical 單位＝整數 µm）。
- 定義 slicer 與 encoder 共用、可跨語言（C++／Python）決定性重現的「內容指紋」。
- 定義 encoder 內 µm 量化 + `[low, high)` 半開區間 + `z_end` 錨點的比對虛擬碼。
- 定義校驗失敗／mandatory 缺檔的例外型別與其在 API 層的對應。

**Non-Goals:**
- 不在本文件決定前端（DS-online）的 UI 與區間輸入元件，只定義後端接收的資料形狀。
- 不改變 PRZ 二進位格式本身（Advance Mode 仍為 1，逐層欄位順序不變）。
- 不處理 prusaslicer_fork 內部「如何依區間做變動層厚切片」的演算法細節（屬切片端實作；本文件只約束其**輸出契約**：權威表與邊界判定規則）。
- 不為單一層厚（等高）任務改變既有行為。

## Decisions

### 決策 0：單位與錨點契約（前提）
- **Canonical 單位 = 整數微米（µm）**。權威表的 `z_end`、`thickness` 與前端區間邊界，全部以 µm 整數儲存與比較；只有在最後寫入 PRZ 的 `struct.pack(">f", z_um/1000.0)` 時才轉回 mm float。
- **錨點 = `z_end`**（層頂，即 PRZ 寫入的 `z_pos`）。
- **半開區間 `[low, high)`**，每層恰好被一個區間認領。
- 此三者為 **slicer 選層厚** 與 **encoder 選參數** 的**共同契約**，兩端逐字一致。

---

### 決策 1：`model.layers.json` 資料結構

與 `model.sl1` 同置於 `job_dir/output/`，檔名 `model.layers.json`。

```jsonc
{
  "schema_version": 1,
  "source": {
    "sl1_name": "model.sl1",
    "layer_count": 240,            // 必須等於 .sl1 內 PNG 張數
    "fingerprint": {
      "algo": "sha256",
      "method": "sorted-name-size-crc32",   // 見決策 2
      "value": "9f3a...e1"                   // hex 字串
    }
  },
  "units": "um",                  // 固定 "um"；明示 canonical 單位
  "layers": [
    { "index": 0,   "z_end_um": 40,    "thickness_um": 40 },
    { "index": 1,   "z_end_um": 80,    "thickness_um": 40 },
    // ...
    { "index": 199, "z_end_um": 8000,  "thickness_um": 40 },
    { "index": 200, "z_end_um": 8100,  "thickness_um": 100 }
  ]
}
```

**欄位約束（載入時驗證）：**
- `layers` 依 `index` 升冪、連續（0..N-1），`len(layers) == source.layer_count`。
- 每層 `z_end_um == 前一層 z_end_um + thickness_um`（單調遞增；首層 `z_end_um == thickness_um`）。
- 所有值為正整數 µm。
- 權威表**只含切片事實**（z/thickness），**不含**曝光／抬升等編碼參數——區間→參數比對全在 encoder。

> 設計理由：以 µm 整數存 `z_end` 讓「邊界判定」變成整數比較，根除浮點累加誤差；`thickness_um` 雖非比對所需，但保留供校驗（單調性自洽檢查）與除錯。

---

### 決策 2：內容指紋（fingerprint）演算法

**綁定語意 = 「同一次切片產物」**（而非「同一個任務」），故不採用 Task ID／per-job UUID。

**演算法（slicer 與 encoder 兩端相同、決定性）：**
1. 開啟 `.sl1`（ZIP），讀取**中央目錄**所有 `*.png` entry（不需解壓縮）。
2. 取每個 entry 的 `(name, uncompressed_size, crc32)`。
3. 依 `name` 字典序排序。
4. 對每筆組 canonical 行：`f"{name}|{size}|{crc32:08x}"`，以 `"\n"` 連接成單一 bytes（UTF-8）。
5. `sha256(canonical_bytes).hexdigest()` 即為 `fingerprint.value`。

```python
def compute_sl1_fingerprint(sl1_path: Path) -> str:
    import zipfile, hashlib
    with zipfile.ZipFile(sl1_path) as zf:
        entries = sorted(
            (i.filename, i.file_size, i.CRC)
            for i in zf.infolist() if i.filename.endswith(".png")
        )
    canonical = "\n".join(f"{n}|{s}|{c:08x}" for n, s, c in entries)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

> 設計理由：使用 ZIP 中央目錄的 `size`＋`crc32` 取得「內容身分」而非「位元組身分」，對重新壓縮（不同壓縮等級／時間戳）不敏感，但對 PNG 內容變動敏感。C++（prusaslicer_fork）寫完 `.sl1` 後以同規則重算，寫入 `layers.json`。兩端皆可從 ZIP central directory 取得 name/size/crc，跨語言可決定性重現。
>
> 崩潰／覆寫情境如何被擋下：slicer 於 `.sl1` 完整寫出**後**才算指紋並寫 `layers.json`；任一半寫崩潰 → `layers.json` 不存在 → 走 mandatory 缺檔錯誤。重切覆寫導致 `sl1_v1 + table_v2` → `table_v2` 內指紋＝`hash(sl1_v2)` ≠ `hash(sl1_v1)` → 指紋不符錯誤。

---

### 決策 3：µm 量化 + 區間比對邏輯（encoder）

前端區間設定（後端接收形狀，經 `slice-config-intake`）：每個區間 `{ low_mm, high_mm, params{...} }`，升冪、相鄰、無重疊、自 0 起。

```python
UM = 1000

def to_um(mm: float) -> int:
    return int(round(mm * UM))          # mm → µm，唯一量化點

def build_ranges(raw_ranges) -> list[Range]:
    rs = [Range(to_um(r.low_mm), to_um(r.high_mm), r.params) for r in raw_ranges]
    rs.sort(key=lambda r: r.low_um)
    # 契約驗證：自 0 起、相鄰連續、無重疊／無缺口
    if rs[0].low_um != 0:
        raise LayerRangeCoverageError("first range must start at 0")
    for a, b in zip(rs, rs[1:]):
        if a.high_um != b.low_um:        # 半開 [low,high) 下，相鄰即「上界==下界」
            raise LayerRangeCoverageError(f"gap/overlap at {a.high_um}um")
    rs[-1].high_um = INT_MAX             # 最上層 z_end==模型頂，需被末區間涵蓋
    return rs

def select_params(z_end_um: int, ranges: list[Range]) -> Params:
    for r in ranges:                     # [low, high) 半開、z_end 錨點
        if r.low_um <= z_end_um < r.high_um:
            return r.params
    raise LayerRangeCoverageError(z_end_um)   # 理論上 build 後不會發生
```

逐層編碼（取代現行 `z_pos = layer_height*(idx+1)`）：

```python
for layer in table.layers:               # 查表照抄
    z_um   = layer.z_end_um
    z_pos  = z_um / 1000.0               # → mm float，僅供 struct.pack
    params = select_params(z_um, ranges) # 依 z_end 挑該層參數
    write_layer_definition(z_pos, params, ...)
```

> 邊界一致性：`select_params` 用 `z_end_um` 判定，與 slicer 選層厚時的 `z_end` 錨點＋`[low,high)` 完全相同，故跨界層的厚度與參數必屬同一區間，不會人格分裂。`INT_MAX` 收尾確保「z_end 等於模型頂」的最後一層仍落在末區間（避免 `[low,high)` 右開把頂層漏接）。

---

### 決策 4：錯誤處理路徑與例外定義

於 `prz_encoder` 新增例外階層（沿用既有以 `ValueError` 表編碼不一致的慣例）：

```python
class VariableLayerError(ValueError):              # 基底
    ...
class LayerTableMissingError(VariableLayerError):      # mandatory 但檔案不存在
    ...
class LayerTableFingerprintMismatch(VariableLayerError):  # 指紋不符（非同一切片產物）
    ...
class LayerTableLayerCountMismatch(VariableLayerError):   # 表層數 ≠ .sl1 PNG 張數
    ...
class LayerRangeCoverageError(VariableLayerError):        # 區間缺口/重疊/未涵蓋某層
    ...
```

**條件式 mandatory 主流程：**

```
is_variable = len(config.height_ranges) > 1
table = load_table(layers_json_path) if path.exists() else None

if is_variable:
    if table is None:                       raise LayerTableMissingError
    if table.fingerprint != compute_sl1_fingerprint(sl1):
                                            raise LayerTableFingerprintMismatch
    if table.layer_count != png_count:      raise LayerTableLayerCountMismatch
    ranges = build_ranges(config.height_ranges)   # 可能 raise LayerRangeCoverageError
    # → 走決策 3 的查表照抄路徑
else:
    # 單一全域層厚：沿用現行等高路徑（z = layer_height*(idx+1)）
    # 無 layers.json 屬正常，不報錯；表即使存在亦忽略（最小化回歸面）
```

**API 層對應**（PRZ 產生端點 `agent/api_v2.py` / `agent/main.py`）：
- `LayerTableMissingError` / `LayerTableFingerprintMismatch` / `LayerTableLayerCountMismatch` → 視為伺服器側資料一致性失敗 → `internal_error(...)`（500），訊息明示「權威表缺失／不符，請重新切片」。
- `LayerRangeCoverageError` → 屬前端送入的區間設定錯誤 → `validation_error(...)`（422）。
- **絕不**對變動層厚任務降級為等高輸出（避免靜默印廢品）；缺檔／校驗失敗一律中止。

## Risks / Trade-offs

- **跨語言指紋一致性**：C++ 端必須以與決策 2 完全相同的規則（PNG entry 排序、`name|size|crc32` 格式、UTF-8、sha256）計算，任何差異都會導致永遠不符。需在切片端與後端各備一份對拍測試（同一 `.sl1` 兩端算出相同 hash）。
- **時間解耦**：切片與 PRZ 編碼為兩次 API 呼叫；若前端在 PRZ 階段送來與切片時**不同的區間定義**，層數／指紋可能仍相符，但語意已偏移。緩解：區間定義應在切片階段固定，PRZ 階段沿用同一份；必要時可將「切片時的區間設定」一併存入 `layers.json` 供 encoder 比對（本變更暫不納入，列為後續強化）。
- **`round()` 邊界**：`to_um` 採 `round`，前端送 `0.0405mm` 之類非 µm 整數倍值時會就近量化，可能與使用者直覺差 0.5µm。需在規格明定「區間邊界以 µm 為最小精度」。
- **單一區間仍想變動層厚的情境**：目前以「區間數 > 1」判定是否 mandatory；若未來出現「單一區間但非等高」需求，此判準需改以「config 是否顯式宣告變動模式」為準，而非區間數。
- **回歸面**：單一層厚路徑刻意完全不動，確保既有等高任務零行為變化；代價是「表存在但單區間」時不採用表（理論上兩者等價，影響可忽略）。
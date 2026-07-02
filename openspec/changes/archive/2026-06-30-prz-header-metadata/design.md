## Context

PRZ V3.0 標頭由 [agent/prz_encoder.py](agent/prz_encoder.py) 的 `_write_header()` 以固定位元組佈局產生（總長 `LAYER_CONTENT_OFFSET = 195477` bytes），並由 [agent/prz_decoder.py](agent/prz_decoder.py) 的 `_parse_header()` 以 1-to-1 偏移量解析。本設計依據已驗證的 `spec.md`，明確定義 8 個 metadata 欄位的偏移量、weight/price 的計算與打包邏輯、`_pack_str` 的防禦性硬化演算法，以及常數與技術債註解的落點。所有偏移量均對照現有 decoder 既有註解，確保編碼/解碼雙向一致。

## Goals / Non-Goals

**Goals:**

- 精確定義 8 個目標欄位（`software`、`softwareVersion`、`printerName`、`printerType`、`profileName`、`weight`、`price`、`priceUnit`）的偏移量、定長與寫入來源。
- 給出 weight/price 由 mm³ 體積 + 密度/單價換算的精確數學公式與 4-byte float BE 打包方式。
- 給出 `_pack_str` 字元安全截斷 + 強制 NUL 的 Python 演算法邏輯。
- 固定 `"Phrozen DS"` 常數與 `# TODO(tech-debt): per-resin-density` 註解的程式碼落點。

**Non-Goals:**

- 不修改前端 DS-online（其 `uiToDefault` / `buildMechadoConfig` 的注入為獨立並行變更）。
- 不修改既有的列印時間、lift/retract、preview、RLE 等欄位邏輯。
- 不在本階段把密度/單價下沉至 `resin_profiles`（列為下一階段技術債）。
- 不更動 `_parse_header()` 偏移量（佈局不變，僅欄位「內容」改變）。

## Decisions

### D1：標頭欄位偏移量（Offsets）與定長（Size）

下表為本變更涉及之欄位在 195477-byte 標頭中的確切位置，對照 `_parse_header()` 既有偏移量（不變）：

| 欄位 | 位元組區間 | 定長 | 型別 / 編碼 | 寫入來源（本變更後） |
|---|---|---|---|---|
| `software` | `[12:44]` | 32 B | 定長字串（`_pack_str`） | 常數 `SOFTWARE_NAME = "Phrozen DS"` |
| `softwareVersion` | `[44:68]` | 24 B | 定長字串（`_pack_str`） | 常數 `SOFTWARE_VERSION` |
| `printerName` | `[92:124]` | 32 B | 定長字串（`_pack_str`） | `Machine.Machine Name`（前端注入顯示名） |
| `printerType` | `[124:156]` | 32 B | 定長字串（`_pack_str`） | `Machine.machine_type`（前端注入顯示型別） |
| `profileName` | `[156:188]` | 32 B | 定長字串（`_pack_str`） | 樹脂名稱新 key（見 D4 契約） |
| `volume` | `[195450:195454]` | 4 B | float BE（`>f`） | `resin_volume_mm3` 或 `Other.volume`（不變） |
| `weight` | `[195454:195458]` | 4 B | float BE（`>f`） | 由 volume × 密度 計算（見 D2） |
| `price` | `[195458:195462]` | 4 B | float BE（`>f`） | 由 volume × 單價 計算（見 D2） |
| `priceUnit` | `[195462:195470]` | 8 B | 定長字串（`_pack_str`） | 常數 `"$/L"` |

備註：`file_time [68:92]`（24 B）介於 `softwareVersion` 與 `printerName` 之間，維持現狀不變。寫入順序須與 `_write_header()` 既有 `buf.write(...)` 序列嚴格一致，總長仍須通過 `len(header) == LAYER_CONTENT_OFFSET` 斷言。

### D2：weight / price 計算公式與 float BE 打包

**單位鏈**：`volume` 以 mm³ 傳入（`resin_volume_mm3`，由上游 `resin_volume_ml × 1000` 換算，見 [api_v2.py:1107](agent/api_v2.py#L1107)）。密度單位 g/mL，單價單位 $/L（對應 `priceUnit = "$/L"`）。

換算（驗證自赤兔樣本：volume=1002 mm³、density=1.1、weight≈1.1022 g；cost=33 → price≈0.033066）：

```
volume_mL = volume_mm3 / 1000.0
volume_L  = volume_mm3 / 1_000_000.0

weight_g  = volume_mL × density        # = (volume_mm3 / 1000) × Resin Density
price     = volume_L  × cost           # = (volume_mm3 / 1_000_000) × Resin Cost
```

- 密度來源：`config["Resin"]["Resin Density"]`（以 `_get_float(config, "Resin.Resin Density")` 讀取）。
- 單價來源：`config["Resin"]["Resin Cost"]`（以 `_get_float(config, "Resin.Resin Cost")` 讀取）。
- **降級邏輯**（對齊 spec）：density 缺漏或為 0（`_get_float` 回 `0.0`）→ `weight` 改寫 `volume`（mm³，維持現狀）；cost 缺漏或為 0 → `price` 改寫 `volume`。weight 與 price 各自獨立判斷降級。
- **打包**：兩欄各以 `buf.write(struct.pack(">f", value))` 寫入（big-endian IEEE-754 single）；計算結果為 Python `float`，`struct` 自動轉 32-bit。

> 注意：現行碼於 [prz_encoder.py:638-642](agent/prz_encoder.py#L638-L642) 將 `volume` 直接寫入 weight 與 price，本變更以上述公式取代，僅在降級時退回 volume。

### D3：`_pack_str` 防禦性硬化演算法

現行 [`_pack_str`](agent/prz_encoder.py#L55) 為 `s.encode("utf-8")[:size]` 裸 byte 截斷，存在無 NUL 結尾與多位元組斷字風險。改為：

```
budget  = size - 1                                   # 永遠保留 ≥1 byte 給 NUL
raw     = (s or "").encode("utf-8")[:budget]         # 先以 byte 上限粗切
safe    = raw.decode("utf-8", errors="ignore")       # 丟棄被切半的尾端多位元組序列（字元安全回退）
encoded = safe.encode("utf-8")
return encoded.ljust(size, b"\x00")                  # zero-pad 至固定長度（至少 1 個 NUL）
```

演算法要點：
- `errors="ignore"` 在 decode 階段丟棄不完整的尾端 UTF-8 序列，達成「字元安全回退」，避免輸出半個多位元組字元。
- `budget = size - 1` 保證最終 `ljust` 後至少有 1 個尾端 `\x00`，杜絕下游 C-string `strlen` overrun。
- 對全 ASCII 短字串（實務常態）輸出位元組與現行一致；僅「恰好填滿或超長」之極端值行為改變。
- 此函式為純函式，便於以 spec 的 4 個 scenario（超長 ASCII / CJK 不斷字 / 恰好填滿 / 空字串）撰寫單元測試。

### D4：常數與技術債註解的落點與組織

- **`SOFTWARE_NAME` / `SOFTWARE_VERSION`**：定義於 [prz_encoder.py](agent/prz_encoder.py) 檔首「`# ---------- Constants ----------`」區塊（現有 `PRZ_VERSION`、`PRZ_TAG` 等常數同處），集中管理：
  ```python
  SOFTWARE_NAME = "Phrozen DS"
  SOFTWARE_VERSION = "0.0.1"   # 產品端版本常數；未來可改 build-time 注入
  ```
  `_write_header()` 內以 `_pack_str(SOFTWARE_NAME, 32)`、`_pack_str(SOFTWARE_VERSION, 24)` 取代現行 `b"\x00" * 32` / `b"\x00" * 24`。
- **`priceUnit` 常數**：同區塊定義（如 `PRICE_UNIT = "$/L"`），`_write_header()` 以 `_pack_str(PRICE_UNIT, 8)` 取代現行 `b"\x00" * 8`。
- **前端↔後端 key 契約**：`profileName` 讀取的樹脂名稱 key 固定為 `Other.profile_name`（後端以 `_get_str(config, "Other.profile_name")` 讀取，缺漏回空字串）。此 key 由前端 DS-online 變更負責回寫；後端不內建任何對照表。
- **技術債註解**：於 `_write_header()` 內 weight/price 計算區塊上方，加入可全域搜尋的標記：
  ```python
  # TODO(tech-debt): per-resin-density —— 密度/單價目前取自印表機 default profile 的
  # Resin 區塊（per-printer 粒度），未來應下沉至 resin_profiles 做到 per-resin 精度。
  ```

## Open Questions（開立前端 DS-online 變更前須排查）

### OQ1：`printerName` 來源——覆寫 `Machine.Machine Name` vs 新增顯示名 key

本設計（D1）讓 `printerName` 讀取 `Machine.Machine Name`，並預期前端改為注入「完整顯示名」（如 `"Phrozen Sonic Mini 8K S"`）而非現行 slug（`"Sonic_Mini_8K_S"`）。

- 後端側已確認安全：`Machine.Machine Name` 在 [agent/](agent/) 內僅 `prz_encoder.py` 的 `printerName` 與 `profileName` 使用，**並非識別 slug**（SLA 萃取走 `machine_type → printer_model`）。故後端不受覆寫影響。
- **風險在前端**：DS-online 內部可能仍把 `Machine.Machine Name` 當 slug 用（載入 profile、機型比對）。開前端變更時 MUST 先排查；依結果二擇一：
  - **(A) 內部未把它當識別碼** → 直接覆寫 `Machine.Machine Name` 為顯示名（最省事，後端契約不變）。
  - **(B) 內部仍當識別碼** → 不覆寫；改注入**新 key（建議 `Machine.machine_label`）**，並回頭把本設計 D1 與 spec 對 `printerName` 的來源從 `Machine.Machine Name` 改為 `Machine.machine_label`，再 archive。
- 在前端排查結論出來前，D1 的 `printerName` 來源視為**暫定**。

### 跨 repo 契約 key 清單（前端變更的驗收依據）

| 後端讀取 key | 前端應回寫內容 | 缺漏時後端行為 |
|---|---|---|
| `Machine.Machine Name`（或 OQ1 決定的 `machine_label`） | 完整印表機顯示名 | 寫入現值（可能是 slug） |
| `Machine.machine_type` | 印表機類型顯示字串 | 寫入現值 |
| `Other.profile_name` | 選定樹脂的 `resin.name` | `profileName` 空字串 |
| `Resin.Resin Density` | 選定**印表機** profile 的真實密度（破靜態 seed） | `weight` 降級寫 volume |
| `Resin.Resin Cost` | 選定印表機 profile 的真實單價 | `price` 降級寫 volume |

> 實作順序：後端先行並 archive（鎖定 as-built 契約）→ 前端依此表與 OQ1 結論開立獨立變更。若後端實作期間調整了任何契約 key，MUST 同步回寫本設計後再 archive。

## Risks / Trade-offs

- **強跨 repo 相依**：若前端 DS-online 未同步注入顯示名、`Other.profile_name`、`Resin.Resin Density/Cost`，後端將持續觸發降級（weight/price 退回 volume、profileName 空字串）。屬已知且可接受的暫態，由 proposal Impact 標記為 CRITICAL，需另開前端變更收斂。
- **per-printer 密度近似**：即使解凍鏈路，密度/單價仍為機器級而非樹脂級，weight/price 為近似值；已明確列為下一階段技術債（D4）。
- **字串打包行為變更（BREAKING）**：恰好填滿欄位且無 NUL 的極端輸入，輸出位元組由 `size` 變為 `size-1 + NUL`；一般字串不受影響，且改變方向為「更安全」。後端 decoder（`rstrip(b"\x00")` + `errors="replace"`）不受影響。
- **單位誤用風險**：weight（g）與 price（$）的單位換算需嚴格遵守 D2 的 `/1000` 與 `/1_000_000` 因子；若誤用會產生 1000 倍級距誤差。須以赤兔樣本值（1002→1.1022 / 0.033066）作為回歸測試錨點。

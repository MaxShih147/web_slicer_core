## Why

PRZ V3.0 標頭中的多個 metadata 欄位長期處於錯誤狀態：`software` / `softwareVersion` / `priceUnit` 永遠寫入全空（`\x00`）、`profileName` 抓錯 key（寫成 `Machine.Machine Name` 而非樹脂名稱）、`weight` / `price` 直接寫入體積（mm³）而非真實重量與價格，且其依賴的 `Resin` 密度/單價鏈路因前端以靜態 `sonic_ls_plus.json` 為骨架而遭凍結錯置。這導致產出的 PRZ 檔案不符合赤兔（ChiTu）切片檔的標準 metadata 規範。此變更修正後端編碼器，使標頭欄位能正確反映前端傳入的真實值，並強化字串打包的安全性。

## What Changes

- **`software` / `softwareVersion`**：於後端 encoder 硬編碼產品識別常數 `"Phrozen DS"` 與對應版本號，集中為具名常數以保留未來擴充彈性（如改由 build-time 注入）。
- **`printerName` / `printerType` / `profileName`**：改為動態讀取前端傳入 `prz_config` 的真實顯示字串；後端維持「印表機無關」設計，僅負責讀取與打包，不內建任何 slug→顯示名對照表。`profileName` 修正為讀取樹脂名稱來源（不再誤用 `Machine.Machine Name`）。
- **`weight` / `price`**：解凍二進位寫入鏈路，改為動態計算（體積 × 傳入之密度 / 單價）；若 `prz_config` 缺漏密度/單價，後端降級維持現狀寫入 `volume`。
- **`priceUnit`**：硬編碼為 `"$/L"`。
- **字串截斷硬化（BREAKING）**：`_pack_str` 改採防禦性「UTF-8 字元安全截斷」，並強制保留 1 byte 給 `NUL` 結尾（有效字元上限為 `size-1`），避免下游印表機韌體以 C-string 讀取時因無 NUL 結尾而記憶體 overrun，或因多位元組（中日韓）字元被裸 byte 切斷而產生亂碼／越界讀取。此為對既有打包位元組輸出的行為變更，故標記為 **BREAKING**。

## Capabilities

### New Capabilities

- `prz-header-metadata`：定義 PRZ V3.0 標頭 metadata 欄位（`software`、`softwareVersion`、`printerName`、`printerType`、`profileName`、`weight`、`price`、`priceUnit`）的資料來源、計算規則、缺漏降級行為，以及所有定長字串欄位的防禦性打包契約（字元安全截斷 + 強制 NUL 結尾）。

### Modified Capabilities

<!-- 無：本變更為新增標頭 metadata 寫入能力；解碼端 prz-parser 既有以 rstrip NUL 讀取定長欄位，需求未變動。 -->

## Impact

- **受影響程式**：[agent/prz_encoder.py](agent/prz_encoder.py) — `_write_header()`（欄位寫入邏輯）、`_pack_str()`（字串打包硬化）、新增 `software` 等具名常數；`weight` / `price` 計算需讀取 `prz_config` 的 `Resin` 區塊（密度/單價）與體積。
- **外部相依（CRITICAL）**：本變更與前端 **DS-online** 強相依。前端必須在其 `uiToDefault` / `buildMechadoConfig` 中打破靜態 `sonic_ls_plus.json` seed 限制，**另行開立變更**回寫正確的機器顯示名（label）、`resin_name`，以及選定機器 profile 的真實 `Resin` 密度與單價至 `prz_config`；否則後端將持續觸發降級邏輯（`weight` / `price` 退回寫入 volume、`profileName` 無樹脂名）。
- **下一階段技術債**：密度/單價目前僅存在於「印表機 default profile 的 `Resin` 區塊」（per-printer 粒度），並非 per-resin。將「未來把密度/單價下沉至 `resin_profiles` 做到 per-resin 粒度」明確定義為下一階段技術債；實作時須於相關程式碼以關鍵字 `# TODO(tech-debt): per-resin-density` 寫入註解，以利後續全域搜尋追蹤。
- **相容性**：字串打包硬化會改變「剛好填滿欄位且無 NUL」之極端字串的輸出位元組（由 `size` 無 NUL 變為 `size-1` + NUL）；一般實際字串（長度遠小於上限）輸出不變。後端解碼端 `prz-parser` 以 `rstrip(b"\x00")` + `errors="replace"` 讀取，不受影響。

## Follow-up Issues（驗證階段發現，未來另開專案處理，不阻擋本次封存）

封存時 `/opsx:verify` 確認本變更無 CRITICAL 問題、5/5 需求與 14/14 場景皆有實作與測試佐證。以下兩項為驗證過程中發現、超出本變更範圍的待辦，明確記錄以利後續追蹤：

1. **既有且無關的單元測試失敗（建議另開變更修復）**：`agent/tests/test_prz_print_time.py::test_6_11_single_normal_layer_full_params`（`_compute_print_time`，期望 14.0 得 11.0）。已以 `git stash` 比對證明此失敗在 baseline（未含本變更）即存在，與 prz-header-metadata **無關**（本變更未觸及列印時間邏輯）。本變更測試檔單獨執行 32 passed。建議另開獨立變更追蹤 `_compute_print_time` 的回歸根因。
2. **OQ1 跨 repo 待解項（前端 DS-online 變更的第一步）**：design.md 記載 `printerName` 來源 `Machine.Machine Name` 為「暫定」，待前端排查其內部是否仍把該 key 當識別 slug 使用。後端側已確認安全（僅 `prz_encoder.py` 使用，非識別碼）。開立前端變更時 MUST 先解 OQ1：若結論為改用新 key（建議 `Machine.machine_label`），須回頭同步本變更已歸檔的 design D1 與 spec 對 `printerName` 的來源定義（屆時於前端變更內處理，不影響本後端封存的 as-built 契約）。

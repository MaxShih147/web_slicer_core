# prz-header-metadata Specification

## Purpose
TBD - created by archiving change prz-header-metadata. Update Purpose after archive.
## Requirements
### Requirement: 軟體識別欄位 software / softwareVersion

PRZ V3.0 標頭的 `software`（32 bytes）與 `softwareVersion`（24 bytes）欄位 SHALL 由後端編碼器寫入產品識別常數，不得再保持全空（`\x00`）。`software` 欄位 SHALL 寫入常數字串 `"Phrozen DS"`。`softwareVersion` 欄位 SHALL 寫入對應的版本號常數。兩者 MUST 以具名常數定義於編碼器中，以保留未來改由 build-time 注入的擴充彈性。

#### Scenario: 寫入軟體識別常數

- **WHEN** 編碼器產生 PRZ 標頭
- **THEN** `software` 欄位之解析值 SHALL 為 `"Phrozen DS"`
- **AND** `softwareVersion` 欄位之解析值 SHALL 為所定義之版本號常數，且非空字串

### Requirement: 印表機與樹脂顯示名欄位 printerName / printerType / profileName

`printerName`（32 bytes）、`printerType`（32 bytes）與 `profileName`（32 bytes）欄位 SHALL 動態讀取前端傳入 `prz_config` 中的真實顯示字串。後端 MUST 維持「印表機無關」設計，不得內建任何 slug→顯示名對照表或硬編印表機清單。`profileName` SHALL 讀取樹脂名稱來源，MUST NOT 再誤用 `Machine.Machine Name`。

#### Scenario: 由 config 動態讀取顯示名

- **WHEN** `prz_config` 提供印表機顯示名、印表機類型與樹脂名稱
- **THEN** `printerName`、`printerType`、`profileName` 之解析值 SHALL 分別等於 config 中對應的字串值

#### Scenario: profileName 不再誤用印表機名稱

- **WHEN** `prz_config` 同時提供印表機名稱與樹脂名稱，且兩者不同
- **THEN** `profileName` 之解析值 SHALL 等於樹脂名稱，MUST NOT 等於印表機名稱

#### Scenario: 樹脂名稱缺漏時的降級

- **WHEN** `prz_config` 未提供樹脂名稱
- **THEN** 編碼器 SHALL NOT 失敗或拋出例外
- **AND** `profileName` SHALL 寫入空字串（依打包契約補 NUL）

### Requirement: 重量與價格欄位 weight / price

`weight`（4 bytes float BE）與 `price`（4 bytes float BE）欄位 SHALL 由列印體積與前端傳入之樹脂密度／單價動態計算，反映真實重量與價格，不得再直接寫入體積值。當 `prz_config` 缺漏密度（或單價）時，對應欄位 SHALL 降級維持現狀，寫入體積（`volume`，單位 mm³）。

#### Scenario: 密度與單價齊備時動態計算

- **WHEN** `prz_config` 提供有效的樹脂密度與單價，且體積已知
- **THEN** `weight` 之解析值 SHALL 反映由體積與密度導出的真實重量
- **AND** `price` 之解析值 SHALL 反映由體積／重量與單價導出的真實價格

#### Scenario: 密度缺漏時降級寫入體積

- **GIVEN** `prz_config` 未提供樹脂密度（缺漏或為零）
- **WHEN** 編碼器寫入標頭
- **THEN** `weight` 欄位 SHALL 降級寫入體積值（mm³）
- **AND** 編碼器 SHALL NOT 失敗或拋出例外

#### Scenario: 單價缺漏時降級寫入體積

- **GIVEN** `prz_config` 未提供樹脂單價（缺漏或為零）
- **WHEN** 編碼器寫入標頭
- **THEN** `price` 欄位 SHALL 降級寫入體積值（mm³）

### Requirement: 價格單位欄位 priceUnit

`priceUnit`（8 bytes）欄位 SHALL 寫入常數字串 `"$/L"`，不得再保持全空（`\x00`）。

#### Scenario: 寫入價格單位常數

- **WHEN** 編碼器產生 PRZ 標頭
- **THEN** `priceUnit` 欄位之解析值 SHALL 為 `"$/L"`

### Requirement: 定長字串欄位之防禦性打包契約

所有定長字串標頭欄位（`software`、`softwareVersion`、`printerName`、`printerType`、`profileName`、`priceUnit`）之打包 SHALL 遵循防禦性契約，以避免下游印表機韌體以 C-string 讀取時發生記憶體 overrun 或多位元組字元亂碼：

1. 打包輸出 SHALL 保證至少保留 1 個尾端 `NUL`（`0x00`）位元組，故有效內容上限為 `size-1` 位元組。
2. 當內容超出有效上限時，截斷 SHALL 發生於合法的 UTF-8 字元邊界，MUST NOT 在輸出中遺留被切斷的部分多位元組序列。
3. 打包輸出 SHALL 以 `0x00` 補齊（zero-pad）至剛好等於欄位的固定位元組長度。

#### Scenario: 超長 ASCII 字串安全截斷並保留 NUL

- **GIVEN** 一個位元組長度大於欄位上限的 ASCII 字串（例如 34 bytes 寫入 32 bytes 的 `profileName`）
- **WHEN** 編碼器打包該欄位
- **THEN** 輸出 SHALL 恰為欄位固定長度
- **AND** 輸出 SHALL 至少包含 1 個尾端 `NUL` 位元組（有效內容不超過 `size-1`）

#### Scenario: 多位元組（中日韓）字元不被裸 byte 切斷

- **GIVEN** 一個含多位元組 UTF-8 字元、且位元組長度超出欄位上限的字串
- **WHEN** 編碼器打包該欄位
- **THEN** 輸出 SHALL NOT 包含被切半的部分多位元組序列
- **AND** 以 UTF-8 解碼輸出（去除尾端 NUL 後）SHALL 不產生無效位元組／替代字元

#### Scenario: 字串長度恰好填滿時仍保留 NUL

- **GIVEN** 一個位元組長度恰等於欄位固定長度的字串
- **WHEN** 編碼器打包該欄位
- **THEN** 輸出 SHALL 仍保留至少 1 個尾端 `NUL`（內容被縮減至 `size-1`）

#### Scenario: 空字串或 None 的打包

- **WHEN** 欄位內容為空字串或未提供
- **THEN** 輸出 SHALL 為全 `0x00`、長度等於欄位固定長度，且 SHALL NOT 拋出例外


## ADDED Requirements

### Requirement: STL 驗證只檢查 header 與大小，不解析 mesh

`_validate_stl_bytes(content, field)` SHALL 只以 header 與內容長度判定 STL 是否可接受，MUST NOT 呼叫 `trimesh.load()` 或以其他方式建立 mesh、解析頂點座標。判定 SHALL 依下列順序：

1. 長度 ≥ 84，且 bytes 80–83（little-endian uint32）的面數 `n` 滿足 `n > 0` 且 `84 + n × 50 ≤ len(content)` → 視為 binary STL，接受。
2. 否則，跳過開頭至多 5 個位元組中的 BOM／空白後以 `solid`（不分大小寫）開頭，且內容含 `facet` → 視為 ASCII STL，接受。
3. 其餘一律以 `INVALID_MODEL` 拒絕，訊息 SHALL 含 `field` 名稱。

binary 判定優先於 ASCII：header 以 `solid` 開頭但大小符合 binary 公式的檔案 SHALL 視為 binary。此判準與前端 `src/three/loaders/validateStl.js` 的 `assertImportableStl` 一致。

#### Scenario: 合法 binary STL 被接受
- **WHEN** 內容為 `84 + n × 50` bytes、面數欄位為 `n > 0` 的 binary STL
- **THEN** `_validate_stl_bytes` SHALL 不拋出例外

#### Scenario: binary STL 尾端有多餘位元組仍接受
- **WHEN** binary STL 的長度大於 `84 + n × 50`
- **THEN** `_validate_stl_bytes` SHALL 接受（與前端判準一致）

#### Scenario: 截斷的 binary STL 被拒絕
- **WHEN** 面數欄位為 `n`，但長度小於 `84 + n × 50`，且內容不是 ASCII STL
- **THEN** `_validate_stl_bytes` SHALL 拋出 `INVALID_MODEL`

#### Scenario: 面數為 0 的 binary STL 被拒絕
- **WHEN** 內容長度 ≥ 84、面數欄位為 0，且內容不是 ASCII STL
- **THEN** `_validate_stl_bytes` SHALL 拋出 `INVALID_MODEL`

#### Scenario: header 以 solid 開頭的 binary STL 視為 binary
- **WHEN** binary STL 的 80 bytes header 以 `solid` 開頭，且大小符合 binary 公式
- **THEN** `_validate_stl_bytes` SHALL 接受

#### Scenario: ASCII STL 被接受，容許 BOM
- **WHEN** 內容為 ASCII STL，開頭可能帶 UTF-8 BOM（`EF BB BF`），之後為 `solid`，且內容含 `facet`
- **THEN** `_validate_stl_bytes` SHALL 接受

#### Scenario: 沒有任何 facet 的 ASCII STL 被拒絕
- **WHEN** 內容為 `solid x\nendsolid x\n`
- **THEN** `_validate_stl_bytes` SHALL 拋出 `INVALID_MODEL`

#### Scenario: 任意非 STL 內容被拒絕
- **WHEN** 內容為空、少於 84 bytes 且不以 `solid` 開頭，或為其他格式
- **THEN** `_validate_stl_bytes` SHALL 拋出 `INVALID_MODEL`

### Requirement: 驗證時間不隨面數線性成長於 mesh 解析

`_validate_stl_bytes` 對 binary STL 的成本 SHALL 只取決於讀取 header 的固定成本，不隨面數做任何逐面處理；對 ASCII STL 只做至多一次位元組搜尋。

#### Scenario: 大型 binary STL 驗證快速完成
- **WHEN** 驗證一個 500 萬面（約 258 MB）的 binary STL
- **THEN** `_validate_stl_bytes` SHALL 在 50 ms 內完成（改前約 11 s）

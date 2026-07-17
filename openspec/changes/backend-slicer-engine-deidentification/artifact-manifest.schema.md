# Engine Artifact Manifest Schema

**版本：** 1.0  
**Status：** `approved`（2026-07-17：與 `naming-manifest.md` 一併簽核）  
**適用：** REQ-DEID-012、REQ-DEID-015、REQ-LAUNCHER-DEID-001、`design.md` D13  
**格式：** JSON（UTF-8）；檔名建議 `engine-artifact-manifest.json`

> 本 schema 定義 fork → Launcher 交接的**機器可驗**契約。Launcher **MUST** 驗證通過後才可組包／簽署；缺欄或 hash 不符 **MUST** fail closed。

---

## 1. 產物流水線與責任（摘要）

```text
fork link (unstripped)
  → 產生 dSYM / PDB
  → 上傳 symbol store（UUID/GUID + build_id）
  → consumer strip（macOS）／consumer PDB 排除（Windows）
  → 寫入本 manifest（含 pre_strip / post_strip hash）
  → Launcher 僅複製 post-strip consumer 產物
  → codesign / Authenticode
  → final post-sign hash 寫入驗收證據
```

| 步驟 | Owner |
|------|-------|
| 改名、身分字串、thread／export、可見性控制 | `web_slicer_core` fork |
| 產 dSYM／PDB、封存、strip／排除 consumer PDB | `web_slicer_core` fork |
| 複製 post-strip 產物、驗證 manifest／hash／strip、簽署 | Bundle-Launcher |
| 動態 L1／L2 驗收（最終簽署包） | QA + Backend Security |

**Launcher MUST NOT** 對引擎 binary 做 rename／strip／patch（避免破壞簽章與雙重 strip）。若驗證失敗 → fail closed，退回 fork。

---

## 2. JSON Schema（概念欄位）

```yaml
schema_version: "1.0"          # MUST
engine_commit: "<git sha>"     # MUST
engine_build_id: "<neutral id>" # MUST；與 --version／內部 store 對應
flavor: consumer | qa          # MUST
platform: macOS | Windows      # MUST
architecture: arm64 | x86_64 | x64  # MUST
toolchain: "<compiler/sdk>"    # MUST
created_at_utc: "<ISO-8601>"   # MUST

# Hash 鏈
pre_strip_sha256: "<hex>"      # MUST；strip／排除 PDB 前主引擎 binary
post_strip_sha256: "<hex>"     # MUST；交給 Launcher 的 consumer binary
# Windows：若無獨立 strip 步驟，pre_strip = 連結產出、post_strip = 已確認無 consumer PDB 後之 PE

symbol_archive:
  kind: dSYM | PDB | none      # MUST
  uuid_or_guid: "<id>"         # MUST when kind != none
  archive_uri: "<internal uri>" # MUST when kind != none
  archive_sha256: "<hex>"      # MUST when kind != none

files:                         # MUST；相對佈局見 naming-manifest §3
  - path: "slicer-engine/bin/slicer-engine"   # 例
    sha256: "<hex>"
    role: engine_cli | engine_dll | shim | resource | license | notice

identity:
  macos_codesign_identifier: "slicer-engine"  # macOS MUST
  windows_original_filename: "slicer-engine.exe"  # Windows MUST（各自檔案）
  product_version: "<neutral>"               # MUST

qa_delta:                      # REQUIRED when flavor=qa；consumer MUST 省略或 null
  harness_compile_flag: "BUNDLE_QA_CRASH_HARNESS"
  only_differences:
    - "compile-time crash harness sites"
  consumer_equivalent_build_id: "<id>"  # 對應之 consumer build

sbom:
  format: "SPDX-2.3-JSON"      # MUST（或已記錄之 CycloneDX 例外）
  uri_or_inline_sha256: "<ref>"

approvals:
  naming_manifest_version: "1.3"  # MUST 對應已簽核命名表版本
```

### 2.1 驗證規則（Launcher MUST）

1. `schema_version` 支援且 `flavor`／`platform`／`architecture` 與組包目標一致。
2. `files[].path` 零黑名單 token；不得含 `prusaslicer_build`、`PrusaSlicer`、`prusa-slicer`。
3. 磁碟上引擎主檔 `sha256` **MUST** 等於 `post_strip_sha256`。
4. macOS：對引擎主檔執行 local＋global 符號掃描（見 `acceptance-procedure.md`）；未 strip → FAIL。
5. Windows：consumer 路徑無 `.pdb`；PE debug directory 無品牌 PDB path；export 僅簽核中性名。
6. `flavor=consumer` 時 binary／manifest **MUST NOT** 含 QA harness marker。
7. `flavor=qa` 時 **MUST** 有 `qa_delta`，且 **MUST NOT** 誤發為 consumer release。

---

## 3. Flavor：release-equivalent QA derivative

| | consumer | qa |
|--|----------|-----|
| 編譯／連結／可見性／strip／簽署流水線 | 相同 | **相同** |
| 唯一允許差異 | — | compile-time harness（`BUNDLE_QA_CRASH_HARNESS`） |
| build_id | 獨立 | 獨立；`qa_delta.consumer_equivalent_build_id` 指向對應 consumer |
| 動態 crash 驗收 | 若可外部注入則優先；否則靜態＋binary inspection | **主要動態驗收對象** |
| 宣稱「consumer L2 通過」 | 靜態 L1／L2＋（若有）動態 | 動態通過 **且** consumer 靜態／inspection 通過；不得單靠 qa 動態代替 consumer 靜態 |

---

## 4. 簽核

| 角色 | 姓名 | 日期 | 結果 |
|------|------|------|------|
| Release Engineering | — | 2026-07-17 | ☑ **schema approved** |
| Backend owner | Vance | 2026-07-17 | ☑ **pipeline ownership acknowledged**（fork strip＋manifest；Launcher 只驗證＋簽署） |
| Product owner | Vance | 2026-07-17 | ☑ **與 naming-manifest 一併 acknowledged** |

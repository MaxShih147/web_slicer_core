# 指紋黑名單與掃描契約

**版本：** 1.2（2026-07-17：品牌歸因複核、worker thread／gcodeviewer token）  
**Owner：** Backend Security／Release Engineering  
**適用：** `REQ-DEID-002`～`REQ-DEID-007`、`REQ-DEID-010`、`REQ-DEID-013`

## 1. 目的與邊界

本黑名單用於降低**正式對外產物與作業系統診斷介面**中的第三方引擎品牌指紋，不構成機密保護、DRM 或「無法辨識底層技術」保證。

**L2 驗收範圍：** OS crash report／WER／傾印可讀欄位、path／filename、身分字串、thread name、公開 export、以及 **shipped** Mach-O／PE 符號表（strip 後應無品牌可讀函式名）。L2 **不以** consumer binary 全文 `strings` 零命中為通過條件（殘餘字串屬 L3）。

本黑名單 **不得** 用於刪除、隱藏或弱化 AGPL／版權／Corresponding Source／修改聲明。授權與來源揭露文件為明確排除項，並由 `REQ-DEID-011` 獨立驗收。

## 2. Canonical token set v1

掃描器 MUST 使用 Unicode case-folding 後的 case-insensitive substring match。輸入 MUST 先正規化為 Unicode NFC；path separator MUST 視為 `/`；不得只做 word-boundary match。

```yaml
blacklist_version: "1.2"
normalization:
  unicode: NFC
  casefold: true
  path_separator: "/"
  match: substring
tokens:
  - prusaslicer
  - prusa-slicer
  - prusa3d
  - prusa research
  - slic3r
  - libslic3r
  - com.prusa3d.slic3r
  - slic3r_main
  - prusaslicer.dll
  - prusa-slicer.exe
  - prusaslicer_build
  - bundle_force_prusa
  - bundle_force_stack_overflow
  - slic3r_tbb
  - prusa-gcodeviewer
  - prusagcodeviewer
  # URL／設定／協定指紋（實測存在於 binary strings）
  - files.prusa3d.com
  - prusaslicer://
  - prusaslicer_config
  - prusaslicerversion
```

重疊 token（例如 `slic3r`／`libslic3r`）刻意保留，方便報表呈現具體命中來源；pass/fail 以「是否有未豁免命中」判斷，而非命中計數。

### 2.1 Deny-list 不完整性與正向 diff（品牌歸因）

本 token 清單為 **deny-list**，本質不完整。驗收 **MUST** 於 token 掃描外，另做 **正向 diff／人工複核**：

- 取一份經批准之「已知乾淨參考報告」（記錄 hash、OS、arch、建立方式、**批准人**、有效期）。本 change macOS 參考見 [`clean-reference-report.md`](./clean-reference-report.md)（**批准人：Vance**，2026-07-17）。
- 與實測報告做全欄位 diff。
- **FAIL 條件：** 出現**可歸因於第三方品牌／來源**之殘留（即使未命中 token）— 例如品牌產品名、供應商、協定、舊 binary／PDB 路徑、品牌型別名。
- **不得 FAIL：** 預期之中性模組名＋offset（如 `slicer-engine + 0x…`、`slicer_core.dll`）、系統庫符號、已簽核豁免項、AGPL／NOTICE 合法揭露位置。**注意：** token `slic3r` 不得誤判已核准之 `slicer-*`／`slicer_*` 名稱。
- 僅 token 零命中**不足以**單獨宣告 PASS；品牌歸因複核 MUST 一併通過。

## 3. 必掃表面

### 3.1 macOS L1

- 最終 `.app`／DMG 解包後之 engine 相關 path、filename、symlink target
- `.ips`：`app_name`、`name`、`procName`、`procPath`
- `.ips`：`bundleInfo.*`、`codeSigningID`
- `.ips`：`usedImages[].name`、`usedImages[].path`、`usedImages[].CFBundleIdentifier`、版本欄位
- 使用者可見 loader／agent error message

### 3.2 macOS L2

- `.ips`：`threads[].name`
- `.ips`：`threads[].frames[].symbol`
- `.ips`：`recursionInfoArray[].keyFrame.symbol`
- `.ips` 完整文字（僅依本文件 scope／exceptions 判斷）
- shipped Mach-O symbol table／export table；consumer bundle MUST NOT 含 dSYM

### 3.3 Windows L1

- installer／bundle 解包後之 engine 相關 path、filename
- process／main module name、module full path
- PE VERSIONINFO：`CompanyName`、`FileDescription`、`FileVersion`、`InternalName`、`OriginalFilename`、`ProductName`、`ProductVersion`
- WER event metadata、loader／agent user-visible errors

### 3.4 Windows L2

- PDB-free minidump stack summary
- PE export table（含 shim → DLL entry contract）
- PE module list、DLL load failures
- consumer bundle MUST NOT 含 PDB；PE debug directory不得洩漏品牌化 PDB path

## 4. 明確排除項

以下位置可含第三方名稱，但 MUST 不出現在產品診斷表面：

1. AGPL license、copyright、NOTICE、修改聲明與 Corresponding Source 文件。
2. 受 ACL 保護的內部 dSYM／PDB、symbolication runbook 與 source mapping。
3. fork 原始碼、git history、internal-only build logs。
4. 經產品、Security、Legal 三方簽核的逐項例外。

例外 MUST 記錄：token、精確路徑／欄位、理由、owner、核准人、到期日、替代控制。不得使用泛用 wildcard 例外。

## 5. Pass／Fail

- **PASS：** 所有必掃表面零「未豁免」命中；**§2.1 品牌歸因正向複核亦通過**；每個豁免仍在有效期；AGPL 文件獨立驗收通過。
- **FAIL：** 任一必掃表面有未豁免命中、正向複核發現未簽核之**第三方品牌／來源**殘留、掃描器／artifact 不可重現、artifact 不是最終簽署版本、或 AGPL 文件缺失。

## 6. 變更治理

Token 增刪 MUST 以 pull request 更新 `blacklist_version`，同時更新 macOS／Windows fixtures 與驗收紀錄。Release pipeline MUST 在證據中保存黑名單版本與 scanner commit。

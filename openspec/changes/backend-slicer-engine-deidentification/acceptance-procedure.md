# 雙平台 L1／L2 驗收程序

**版本：** 1.2（2026-07-17：與 blacklist 1.2／D13／artifact-manifest 對齊；release-equivalent QA、local+global 符號掃描、三種 crash site、品牌歸因複核、乾淨環境）  
**適用 Requirement：** REQ-DEID-002～006、009～015  
**規範來源：** [`blacklist.md`](./blacklist.md)、[`artifact-manifest.schema.md`](./artifact-manifest.schema.md)、[`design.md`](./design.md) D7／D11／D13  

**PoC 進度（非取代本程序）：** 2026-07-17 macOS arm64 **tasks 2.4 PASS**（[`poc/REPORT.md`](./poc/REPORT.md)、`m1-close-20260717T032408Z`）。正式驗收仍須本文件之 consumer／qa flavor、簽署包與雙平台條款；PoC 額外證實：驗收機不得存在同 UUID dSYM／未 strip 複本（見原則第 9 點）。

## 1. 驗收原則

1. **靜態 L1／L2 與 binary inspection** 的對象 MUST 是與預定發布完全相同的 **consumer Release artifact**（最終簽署包）。
2. **動態 crash** 的對象 MUST 是 **release-equivalent qa** 包（見 D7／artifact-manifest §3）：與 consumer 同一 compile／link／strip／sign 流水線，唯一差異為 compile-time harness；manifest 記錄 `qa_delta` 與對應 consumer `build_id`。若存在不依賴 harness 之外部注入方式，**MAY** 另對 consumer 做動態驗證並優先作為證據。
3. macOS MUST 驗收已完成 codesign、notarization、staple 的 `.app`／DMG。
4. Windows MUST 驗收已完成 Authenticode 的 installer／bundle。
5. artifact 在簽署後不得再 strip、patch、rename 或修改（D13：strip 僅由 fork 在簽章前完成）。
6. macOS 與 Windows 任一平台未通過，整體即 FAIL。
7. consumer Release MUST 另做 binary inspection，證明不存在 runtime 可啟動之故意 crash 路徑／harness 符號。
8. **L2 手段＝精簡版 C′**：不以全面 namespace、OLLVM 或 `strings` 零品牌字串為 L2 通過條件。
9. **乾淨測試環境：** 動態驗收 MUST 在無法自動載入內部 dSYM／PDB 的環境執行（隔離 Spotlight／私有 symbol store／`_NT_SYMBOL_PATH`），並在 evidence 記錄環境描述；避免測試機「比使用者更會符號化」造成假失敗或假通過。

## 2. 每份證據必填 metadata

```yaml
change_id: backend-slicer-engine-deidentification
launcher_version: ""
launcher_commit: ""
engine_commit: ""
engine_build_id: ""
flavor: consumer | qa
consumer_equivalent_build_id: ""   # required when flavor=qa
platform: macOS | Windows
architecture: arm64 | x86_64 | x64
os_version: ""
toolchain: ""
artifact_filename: ""
artifact_sha256: ""                 # post-sign final artifact
pre_strip_sha256: ""                # from engine manifest
post_strip_sha256: ""               # from engine manifest；Launcher 輸入
signing_identity: ""
sbom_format: "SPDX-2.3-JSON"
blacklist_version: "1.2"
scanner_commit: ""
crash_fixture_sha256: ""
clean_env_notes: ""                 # no private dSYM/PDB/_NT_SYMBOL_PATH
captured_at_utc: ""
reviewers:
  release_engineering: ""
  backend_security: ""
  qa: ""
  legal_open_source: ""
```

## 3. 共用前置檢查

- [ ] 內部命名表與 [`artifact-manifest.schema.md`](./artifact-manifest.schema.md) 已簽核。
- [ ] engine artifact manifest 通過 Launcher／CI 驗證（commit、build_id、flavor、pre／post_strip hash）。
- [ ] exact fork commit 可重建；SBOM（SPDX 2.3 JSON 或已記錄例外）可取得。
- [ ] AGPL license、copyright、修改聲明、Corresponding Source URL／offer 已納入 release evidence。
- [ ] consumer bundle 不含 `.pdb`／`.dSYM`／QA harness。
- [ ] 內部 symbol archive 的 UUID／GUID 與 artifact build ID 可對應（Windows headless 亦有匹配 PDB）。
- [ ] qa 與 consumer 的 `build_id`／artifact hash 明確不同；`qa_delta` 僅列 harness 差異。
- [x] 已知乾淨參考報告（reference）已建立並經 **Vance** 批准（hash／OS／arch 固定；見 [`clean-reference-report.md`](./clean-reference-report.md)，2026-07-17）。
- [ ] golden functional regression 已通過。

## 4. macOS 驗收

### 4.1 支援矩陣

至少涵蓋實際發布之每個 architecture：Apple Silicon `arm64` 與仍發布時的 Intel `x86_64`。每個 architecture MUST 產生獨立紀錄。

### 4.2 靜態 L1／L2（consumer final）

對最終 app／DMG 解包後執行：

- path／symlink walk（不得含 `prusaslicer_build`、品牌檔名／symlink）
- `codesign -dv --verbose=4`（`Identifier` 為簽核中性值）
- `otool -L`／Mach-O load commands
- **符號掃描（分開）：**
  - local／defined：`nm -U`（或等效）— 含黑名單 token 的可讀符號 MUST 為零
  - global／dynamic：`nm -gU` 與 export 檢查 — 同上
  - **不得**僅以 `nm -gU` 判定已 strip
- consumer bundle `.dSYM` 檢查
- user-visible error fixture
- engine manifest `post_strip_sha256` 與磁碟檔一致

所有輸出 MUST 交由版本化 scanner 依 `blacklist.md` 判定。

### 4.3 動態 crash（release-equivalent qa；可選加測 consumer）

1. 使用乾淨環境（§1.9）；清除或記錄舊 DiagnosticReports；記錄測試開始 UTC。
2. 啟動 **qa flavor** 最終簽署包（或外部注入下的 consumer）。
3. 使用固定、hash 已記錄的 SLA fixture 觸發 CLI 路徑。
4. 等待最多 30 秒取得 **測試開始後、PID／binary UUID 相符** 的 `.ips`。
5. 解析並掃描：`procName`／`procPath`、`bundleInfo.*`、`codeSigningID`、`threads[].name`、`threads[].frames[].symbol`、recursion、`usedImages[]`、abort／ASI、完整 scoped text。
6. 驗證 agent 仍存活並依既有契約將 job 標為 failed。
7. **三種 test-only crash site 均須通過：**
   1. 主 site（可為遞迴／stack overflow）
   2. 非遞迴 native crash site
   3. 未捕捉 C++ 例外 site（驗證型別名／abort message）
8. **正向 diff／人工複核（`blacklist.md` §2.1）：** 與已知乾淨參考比對；僅判定**可歸因於第三方品牌／來源**之殘留（見黑名單）。預期之中性模組名＋offset（如 `slicer-engine + 0x…`）**不得**因此 FAIL；`slicer` ≠ `slic3r`。

### 4.4 macOS PASS

- consumer 靜態 L1／L2 零未豁免命中；符號 local＋global 掃描通過。
- qa（及若執行之 consumer）動態三種 crash site 通過；品牌歸因複核通過。
- thread 名無 `slic3r`／黑名單 token（含 worker）。
- consumer 不含 harness／dSYM；codesign、notarization、staple、Gatekeeper 成功。

## 5. Windows 驗收

### 5.1 前置 baseline

實作開始前 MUST 先保存目前正式包之 process／module path、VERSIONINFO、`dumpbin /exports`、WER metadata、PDB-free minidump stack、shim loader error 至 `evidence/windows/baseline/`；未取得時 Windows 實作維持 blocked。

### 5.2 靜態 L1／L2（consumer final）

- path walk；Authenticode verification
- PE VERSIONINFO dump
- PE import／export（僅簽核中性 entry）
- PE debug directory／PDB path（無品牌路徑；無 consumer `.pdb`）
- shim → DLL filename／export contract
- manifest `post_strip_sha256` 一致

### 5.3 動態 crash（release-equivalent qa）

1. 乾淨環境（無私有 `_NT_SYMBOL_PATH`／內部 PDB）。
2. 依固定 WER LocalDumps 設定建立測試環境。
3. 啟動 qa flavor；記錄 PID／module hashes。
4. 三種 crash site（同 §4.3.7）。
5. 掃描 process／module／VERSIONINFO／loader／exports／readable stack／例外訊息。
6. 品牌歸因正向複核。
7. 驗證 agent 存活與 job failure semantics。

### 5.4 Windows PASS

- consumer 靜態零未豁免命中；export／PDB path 合格。
- qa 動態三種 site＋品牌歸因複核通過。
- Authenticode 與 installer 安裝／解除安裝通過。

## 6. 功能回歸

兩平台 MUST 執行：full SLA slice、generate supports、hollow／drill、cut、project／3MF（若啟用）、invalid input／CLI missing／native crash／timeout／cancel、package install → first launch → slice → uninstall。

輸出比對方式與效能門檻 MUST 在 PoC 結束前簽核。

## 7. 證據路徑與審核

```text
evidence/
  macos/<launcher-version>/<arch>/
  windows/<launcher-version>/x64/
```

每個目錄 MUST 包含 metadata、原始 report／dump reference、normalized scan output、正向複核紀錄、PASS／FAIL summary、artifact／pre_strip／post_strip hash 與四方簽核（含 QA）。

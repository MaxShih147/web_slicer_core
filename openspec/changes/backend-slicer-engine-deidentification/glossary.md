# 術語表

**版本：** 1.2（2026-07-17：D13 流水線、release-equivalent QA、品牌歸因）
**目的：** 提供跨角色（PM／Legal／Security／Release Engineering／後端工程）單一術語定義入口，避免各文件對同一詞彙有不同理解。**本表僅彙整既有定義，不建立新規範**；若本表與規範性文件（`spec.md`／`blacklist.md`／`acceptance-procedure.md`／`design.md`）不一致，以規範性文件為準，並回報修正本表。

## 規範性關鍵字

| 詞彙 | 定義 | 來源 |
|---|---|---|
| MUST／MUST NOT／MAY／SHOULD | 依 [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119) 慣例解讀；MUST／MUST NOT 為絕對要求；MAY 為允許不強制。中文譯註（必須／不得／可以）僅輔助閱讀 | `design.md`〈用語慣例〉 |
| fail closed | 掃描／驗收未通過時，release pipeline **必須**阻止發布，不得以 warning 或 `continue-on-error` 略過 | `blacklist.md` §5、`implementation-checklist.md` Gate 3 |

## 去識別分級

| 詞彙 | 定義 | 來源 |
|---|---|---|
| L1（抬頭／路徑指紋） | Process 名、file path、映像檔名、Bundle Identifier／Version（及 Windows VERSIONINFO 對等欄位）不得命中黑名單 | `design.md`〈產品接受線〉、`blacklist.md` §3.1／3.3 |
| L2（可讀符號指紋） | OS 崩潰報告中使用者或工具可讀之堆疊、thread name、公開 export／符號字串不得命中黑名單。**達成手段定案為精簡版 C′**（strip＋thread 名＋Win export），非全面 namespace／OLLVM | `design.md` D3、`blacklist.md` §3.2／3.4 |
| L3（靜態反編譯抗性） | 全面 `Slic3r::`→`slice::`、OLLVM／混淆、`strings`／packer／encrypt-at-rest；**本 change 明確排除產品化**，僅可行性評估 | `proposal.md`〈非目標〉、`design.md`〈產品接受線〉 |
| 精簡版 C′ | L2 必要策略：可見性＋strip；**全部** thread call site；Win export／DLL ABI；RTTI／例外實測。不含全面 namespace／OLLVM | `design.md` D3 |
| D13 流水線 | fork：改名／strip／manifest；Launcher：只驗證＋簽署；記錄 pre／post_strip／post-sign hash | `design.md` D13、`artifact-manifest.schema.md` |
| release-equivalent QA | 與 consumer 同流水線，唯一差異為 compile-time harness；動態驗收主對象 | `design.md` D7 |
| 黑名單（blacklist） | Canonical 品牌指紋 token 清單與掃描契約（normalization、必掃表面、豁免規則、pass/fail） | `blacklist.md` |
| 未豁免命中 | 黑名單掃描命中且未經產品／Security／Legal 三方簽核例外記錄的結果 | `blacklist.md` §4／§5 |
| 威脅模型 | 明訂防護對手：目標＝閱讀 OS 診斷／路徑之一般使用者／客服；非目標＝有能力逆向工程師 | `design.md`〈威脅模型〉 |
| 正向 diff／品牌歸因複核 | token 掃描之外，與已知乾淨參考 diff；僅第三方品牌／來源殘留可致 FAIL；中性模組名＋offset 不得因此 FAIL | `blacklist.md` §2.1 |
| AGPL 揭露天花板 | 因法遵須保留 license／來源 offer，查看該等文件者本即得知第三方來源；L1／L2 僅降 OS 診斷表面指紋，非「無人可辨識」 | `design.md`〈威脅模型〉、D9 |

## AGPL／授權合規

| 詞彙 | 定義 | 來源 |
|---|---|---|
| Corresponding Source | AGPL-3.0 定義之「對應原始碼」；本 change 要求對應到**精確發布 binary 的 fork commit**，非泛稱版本 | `agpl-boundary.md`、`spec.md` REQ-DEID-011 |
| written offer | 以書面（含電子）方式提供 Corresponding Source 取得方式，滿足 AGPL §13 網路互動揭露義務 | `agpl-boundary.md` |
| 修改後 AGPL 作品合規 | 本專案修改並發布 PrusaSlicer fork，去識別**不得**用於移除或弱化授權／來源揭露義務 | `spec.md` REQ-DEID-011、`design.md` D9 |

## 供應鏈與符號

| 詞彙 | 定義 | 來源 |
|---|---|---|
| SBOM | Software Bill of Materials；本 change 定案格式為 **SPDX 2.3 JSON**（工具鏈限制時 MAY 用 CycloneDX 1.5 JSON，但同一 artifact 類型不得混用） | `design.md` D10a |
| build ID／UUID／GUID | 每個正式 engine artifact 的唯一建置識別碼；macOS 對應 Mach-O UUID，Windows 對應 PE/PDB GUID+Age，用於內部 symbolication 對應 | `design.md` D10、`spec.md` REQ-DEID-012 |
| dSYM／PDB | macOS／Windows 除錯符號檔；**consumer release 不得包含**，僅存於受 ACL 保護之內部 symbol store | `blacklist.md` §3.2／3.4、`spec.md` REQ-DEID-012 |
| naming-manifest | 跨平台命名與 consumer 佈局 | `naming-manifest.md` |
| artifact manifest schema | fork→Launcher 機器可驗交接（flavor、hash 鏈、files、symbol archive） | `artifact-manifest.schema.md` |
| codeSigningID | macOS `codesign` 嵌入之 identifier；CLI 設為與執行檔名一致即可，不要求 reverse-DNS | `naming-manifest.md` §2.1、`design.md` D2 |
| slicer-engine | 已確認之功能性引擎模組名／正式包目錄（`slicer` ≠ `slic3r`） | `naming-manifest.md` §0 |
| slicer_core.dll | 已確認之 Windows 核心 DLL 名 | `naming-manifest.md` §0 |
| slicer_run_cli | 已確認之 Windows 公開 export | `naming-manifest.md` §0 |

## 崩潰報告與診斷（平台特定）

| 詞彙 | 定義 | 來源 |
|---|---|---|
| `.ips` | macOS DiagnosticReports 崩潰報告格式（JSON + translated text） | `macOS_system_report.md`、`acceptance-procedure.md` §4.3 |
| WER | Windows Error Reporting；崩潰事件 metadata 與 minidump 之官方機制 | `acceptance-procedure.md` §5 |
| PDB-free minidump | 不含品牌化 PDB 路徑之最小傾印，用於驗證 Windows 崩潰報告不洩漏品牌指紋 | `blacklist.md` §3.4 |

## 發布治理

| 詞彙 | 定義 | 來源 |
|---|---|---|
| 最終簽署 artifact | 已完成 macOS codesign／notarize／staple 或 Windows Authenticode 的正式產物；驗收與掃描**僅**對此對象有效 | `design.md` D11、`acceptance-procedure.md` §1 |
| QA flavor | 含故意崩潰 harness 之測試專用建置，與 consumer release 有不同 build ID，**不得**流入正式發布 | `spec.md` REQ-DEID-009、`design.md` D7 |
| 四方簽核 | Release Engineering、Backend Security、QA、Legal／OSS 四個 owner 對發布之聯合簽核 | `implementation-checklist.md` Gate 5 |

## 相關文件

- 完整規範性需求：[`specs/slicer-engine-deidentification/spec.md`](./specs/slicer-engine-deidentification/spec.md)
- 掃描契約：[`blacklist.md`](./blacklist.md)
- 驗收程序：[`acceptance-procedure.md`](./acceptance-procedure.md)
- 決策紀錄：[`design.md`](./design.md)

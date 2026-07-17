# Requirement Traceability Matrix

**Evidence 更新（2026-07-17）：** macOS M1／tasks 2.4 → [`poc/evidence/m1-close-20260717T032408Z/`](./poc/evidence/m1-close-20260717T032408Z/)、[`poc/REPORT.md`](./poc/REPORT.md)；Windows baseline／tasks 1.7 → [`evidence/windows/baseline/`](./evidence/windows/baseline/)、[`PROGRESS.md`](./PROGRESS.md)。

| Requirement | Design | Tasks | 驗收證據 |
|---|---|---|---|
| REQ-DEID-001 Scope | Goals／Non-goals／威脅模型 | 8.1 | OpenSpec review |
| REQ-DEID-002 L1+L2（C′） | D1–D3、D13 | 3、5、7 | 雙平台 scan＋品牌歸因複核（**macOS PoC 部分：** m1-close PASS） |
| REQ-DEID-003 Dual platform | D5 | 2.4–2.5、7.1–7.2 | macOS PoC records；**Windows baseline 已存**（1.7）；Win PoC／驗收仍缺 |
| REQ-DEID-004 Rename/repack | D1、D13 | 3.1–3.5、4.1–4.6 | Artifact layout＋manifest files[]（PoC：`slicer-engine` OUTPUT_NAME） |
| REQ-DEID-005 Identity strings | D2 | 3.2、4.3 | `.ips`／VERSIONINFO／codesign（**macOS PoC：** codeSigningID=`slicer-engine`） |
| REQ-DEID-006 L2／C′ | D3、D5、D7、D10、D13 | 1.8–1.9、2.2–2.5、5.1–5.5 | **macOS：** visibility＋strip＋三 crash＋scanner PASS（2.4／2.2）；Win／正式 manifest 待 |
| REQ-DEID-007 不得以 D／E／C-full 取代 | D8 | 2.1、5.8–5.10 | Feasibility decision（C′ 定案；L3 不做） |
| REQ-DEID-008 AGPL subprocess | D4 | 5.11 | Process-boundary test |
| REQ-DEID-009 Crash harness／QA derivative | D7 | 2.6、5.6–5.7、7.3 | PoC runtime harness；compile-time／consumer inspection 待 |
| REQ-DEID-010 Evidence | D5、D11 | 7.1–7.7 | Evidence index＋四方簽核（含 QA）；PoC evidence 已存 |
| REQ-DEID-011 AGPL modified-work | D9 | 1.6、6.1–6.4 | Legal／OSS sign-off |
| REQ-DEID-012 Symbol supply chain | D10、D13 | 5.5、6.5–6.7 | Symbol archive＋pre/post_strip hash（PoC 演練 dSYM 封存；產品化待） |
| REQ-DEID-013 Final-artifact gate | D11、D13 | 4.4–4.5、7.4–7.5 | CI run URL |
| REQ-DEID-014 Functional parity | D12 | 3.6、7.6 | Regression report |
| REQ-DEID-015 Naming＋artifact schema | D6、D13 | 1.3–1.4 | naming-manifest＋artifact-manifest.schema 簽核 |
| REQ-LAUNCHER-DEID-001 Manifest copy | LD1、D13 | Launcher 1.1–1.2 | Manifest validation log |
| REQ-LAUNCHER-DEID-002 Bundle layout | LD3 | Launcher 2.1、3.1 | Path scan |
| REQ-LAUNCHER-DEID-003 Verify then sign | LD2、D13 | Launcher 2.2–2.3、3.2 | Hash＋scan before sign |
| REQ-LAUNCHER-DEID-004 Final scanner | LD3 | Launcher 2.4、3.4、5.1 | Post-sign scan |
| REQ-LAUNCHER-DEID-005 Flavor isolation | LD5、D7 | Launcher 4.1–4.2 | Flavor／harness gate |
| REQ-LAUNCHER-DEID-006 AGPL materials | LD4、D9 | Launcher 4.3 | License／offer paths |

## Traceability rule

每個 Requirement MUST 至少對應一個 Design decision、Task 與可稽核 evidence。新增／修改 Requirement 時，本表 MUST 同一 PR 更新；缺任一欄時 `openspec validate --strict` 即使通過，release readiness review 仍 MUST 判定 FAIL。

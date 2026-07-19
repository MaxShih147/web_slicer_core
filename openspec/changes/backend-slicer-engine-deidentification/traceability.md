# Requirement Traceability Matrix

**Evidence 更新（2026-07-17 晚）：** 雙平台 PoC 如上；**macOS 產品化** 3.1／3.2／3.4＋5.1 流水線 → `scripts/package_slicer_engine_macos.sh`、本機 `third_party/slicer-engine/engine-artifact-manifest.json`（gitignored）；詳見 [`PROGRESS.md`](./PROGRESS.md)。

| Requirement | Design | Tasks | 驗收證據 |
|---|---|---|---|
| REQ-DEID-001 Scope | Goals／Non-goals／威脅模型 | 8.1 | OpenSpec review |
| REQ-DEID-002 L1+L2（C′） | D1–D3、D13 | 3、5、7 | 雙平台 scan＋品牌歸因複核（**雙平台 PoC：** m1-close＋w25-close；正式 §7 待） |
| REQ-DEID-003 Dual platform | D5 | 2.4–2.5、7.1–7.2 | macOS＋Windows PoC records（1.7／2.4／2.5）；正式驗收仍缺 |
| REQ-DEID-004 Rename/repack | D1、D13 | 3.1–3.5、4.1–4.6 | **macOS 3.1／3.4 已落地**＋`slicer-engine/` manifest；3.5／§4／Win 3.3 待 |
| REQ-DEID-005 Identity strings | D2 | 3.2、4.3 | **macOS 3.2 已落地**（plist／help／codesign ID）；Win VERSIONINFO PoC；Launcher 4.3 待 |
| REQ-DEID-006 L2／C′ | D3、D5、D7、D10、D13 | 1.8–1.9、2.2–2.5、5.1–5.5 | **macOS 5.1 關閉**（nm brand 0）；**Win 2.5 PASS**（export=1 → 5.3） |
| REQ-DEID-007 不得以 D／E／C-full 取代 | D8 | 2.1、5.8–5.10 | Feasibility decision（C′ 定案；L3 不做） |
| REQ-DEID-008 AGPL subprocess | D4 | 5.11 | Process-boundary test |
| REQ-DEID-009 Crash harness／QA derivative | D7 | 2.6、5.6–5.7、7.3 | **2.6＋macOS 5.6／5.7 Done**；雙平台動態三 crash＋Win consumer 仍見 7.3／5.3 |
| REQ-DEID-010 Evidence | D5、D11 | 7.1–7.7 | Evidence index＋四方簽核（含 QA）；雙平台 PoC evidence 已存 |
| REQ-DEID-011 AGPL modified-work | D9 | 1.6、6.1–6.4 | Legal／OSS sign-off |
| REQ-DEID-012 Symbol supply chain | D10、D13 | 5.5、6.5–6.7 | **macOS pre/post_strip＋dSYM 封存已產品化**；5.5 runbook／Win PDB 正式封存待 |
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

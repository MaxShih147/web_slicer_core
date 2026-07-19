# Requirement Traceability Matrix

**Evidence 更新（2026-07-19 夜）：** mac 晚上 consumer 已回灌簽過包（DMG `…2111`；`legal/`＋help=0）。雙平台 §4／CLI／AGPL 有硬證。≈**92–94%**。詳見 [`PROGRESS.md`](./PROGRESS.md)。

| Requirement | Design | Tasks | 驗收證據 |
|---|---|---|---|
| REQ-DEID-001 Scope | Goals／Non-goals／威脅模型 | 8.1 | OpenSpec review |
| REQ-DEID-002 L1+L2（C′） | D1–D3、D13 | 3、5、7 | 雙平台 PoC＋Launcher 靜態 post-sign；**Win 7.3 PASS**；正式雙平台 §7／7.6 仍待 |
| REQ-DEID-003 Dual platform | D5 | 2.4–2.5、7.1–7.2 | Win post-sign＋macOS arm64 §4（含晚上回灌）已有；正式雙平台 §7 宣告仍缺 |
| REQ-DEID-004 Rename/repack | D1、D13 | 3.1–3.5、4.1–4.6 | Win PASS；mac §4＋晚上回灌 PASS；**CLI 雙平台簽過包清**；4.6／resources 待 |
| REQ-DEID-005 Identity strings | D2 | 3.2、4.3 | mac notarize＋Win Setup PASS；內嵌 Win exe 未簽 |
| REQ-DEID-006 L2／C′ | D3、D5、D7、D10、D13 | 1.8–1.9、2.2–2.5、5.1–5.5 | C′／scan PASS；5.1b 待 |
| REQ-DEID-007 不得以 D／E／C-full 取代 | D8 | 2.1、5.8–5.10 | C′ 定案；1.5 Security 待 |
| REQ-DEID-008 AGPL subprocess | D4 | 5.11 | Process-boundary test |
| REQ-DEID-009 Crash harness／QA | D7 | 2.6、5.6–5.7、7.3 | consumer OFF；**Win 7.3 PASS**；mac §7 動態可後補 |
| REQ-DEID-010 Evidence | D5、D11 | 7.1–7.7 | 多方 evidence 已存；四方簽核待 |
| REQ-DEID-011 AGPL | D9 | 1.6、6.1–6.4 | **1.6 approved**；**Win＋mac 簽過包皆有 legal/**；6.4 SBOM 開 |
| REQ-DEID-012 Symbol supply | D10、D13 | 5.5、6.5–6.7 | Win OneDrive＋mac drill；演練後補 |
| REQ-DEID-013 Final-artifact gate | D11、D13 | 4.4–4.5、7.4–7.5 | 雙平台手動 PASS；CI 待 |
| REQ-DEID-014 Functional parity | D12 | 3.6、4.6、7.6 | Win install smoke；mac 4.6／7.6 待 |
| REQ-DEID-015 Naming＋schema | D6、D13 | 1.3–1.4 | 已簽核 |
| REQ-LAUNCHER-DEID-001–004 | LD1–LD3 | Launcher 1–3／5 | 雙平台 verify／scan／sign 手動 PASS |
| REQ-LAUNCHER-DEID-005 Flavor | LD5 | Launcher 4.1–4.2 | consumer gate PASS；QA 組包待 |
| REQ-LAUNCHER-DEID-006 AGPL materials | LD4 | Launcher 4.3 | **雙平台簽過包 legal/ PASS**（mac＝`…2111`） |


## Traceability rule

每個 Requirement MUST 至少對應一個 Design decision、Task 與可稽核 evidence。新增／修改 Requirement 時，本表 MUST 同一 PR 更新；缺任一欄時 `openspec validate --strict` 即使通過，release readiness review 仍 MUST 判定 FAIL。

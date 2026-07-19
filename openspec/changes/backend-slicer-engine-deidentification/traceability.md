# Requirement Traceability Matrix

**Evidence 更新（2026-07-19）：** Win Launcher unsigned gate＋**已簽 Setup post-sign lifecycle PASS** — [`evidence/windows/launcher-1.0.0-postsign-20260719/SUMMARY.md`](./evidence/windows/launcher-1.0.0-postsign-20260719/SUMMARY.md)；**macOS Launcher §4 arm64 閉環 PASS** — [`evidence/macos-launcher-section4-20260719.md`](./evidence/macos-launcher-section4-20260719.md)。詳見 [`PROGRESS.md`](./PROGRESS.md)。

| Requirement | Design | Tasks | 驗收證據 |
|---|---|---|---|
| REQ-DEID-001 Scope | Goals／Non-goals／威脅模型 | 8.1 | OpenSpec review |
| REQ-DEID-002 L1+L2（C′） | D1–D3、D13 | 3、5、7 | 雙平台 PoC＋Win／macOS Launcher 靜態 post-sign；正式 §7 動態仍待 |
| REQ-DEID-003 Dual platform | D5 | 2.4–2.5、7.1–7.2 | Win post-sign＋macOS arm64 Launcher 已有；正式雙平台 §7 宣告仍缺 |
| REQ-DEID-004 Rename/repack | D1、D13 | 3.1–3.5、4.1–4.6 | **Win 4.2／4.6 PASS**；**macOS 4.1 PASS**；**殘留：** CLI help `PrusaSlicer`；macOS 4.6 待 |
| REQ-DEID-005 Identity strings | D2 | 3.2、4.3 | macOS 3.2＋Launcher notarize PASS；Win VERSIONINFO／Setup Authenticode PASS；內嵌 app exe 未簽 |
| REQ-DEID-006 L2／C′ | D3、D5、D7、D10、D13 | 1.8–1.9、2.2–2.5、5.1–5.5 | macOS＋Win C′／scan PASS |
| REQ-DEID-007 不得以 D／E／C-full 取代 | D8 | 2.1、5.8–5.10 | Feasibility decision（C′ 定案；L3 不做） |
| REQ-DEID-008 AGPL subprocess | D4 | 5.11 | Process-boundary test |
| REQ-DEID-009 Crash harness／QA derivative | D7 | 2.6、5.6–5.7、7.3 | consumer harness OFF Done；正式 qa 動態 → 7.3 |
| REQ-DEID-010 Evidence | D5、D11 | 7.1–7.7 | Win post-sign＋macOS §4 evidence 已存；四方簽核待 |
| REQ-DEID-011 AGPL modified-work | D9 | 1.6、6.1–6.4 | Legal／OSS sign-off |
| REQ-DEID-012 Symbol supply chain | D10、D13 | 5.5、6.5–6.7 | dSYM／PDB 封存有；macOS runbook 草稿 — [`macos-symbol-archive-runbook-5.5.md`](./evidence/macos-symbol-archive-runbook-5.5.md)；正式 store 待 |
| REQ-DEID-013 Final-artifact gate | D11、D13 | 4.4–4.5、7.4–7.5 | **Win 手動 post-sign PASS**；**macOS final scan PASS**；CI 自動化待 |
| REQ-DEID-014 Functional parity | D12 | 3.6、4.6、7.6 | Win install lifecycle smoke PASS；macOS 4.6 待；完整 SLA → 7.6 |
| REQ-DEID-015 Naming＋artifact schema | D6、D13 | 1.3–1.4 | naming-manifest＋artifact-manifest.schema 簽核 |
| REQ-LAUNCHER-DEID-001 Manifest copy | LD1、D13 | Launcher 1.1–1.2 | **Win PASS**；**macOS verify PASS** |
| REQ-LAUNCHER-DEID-002 Bundle layout | LD3 | Launcher 2.1、3.1 | **Win 3.1 PASS**；**macOS 2.1 PASS** |
| REQ-LAUNCHER-DEID-003 Verify then sign | LD2、D13 | Launcher 2.2–2.3、3.2–3.3 | **Win verify＋Setup 簽＋lifecycle PASS**；**macOS pre-sign verify＋Developer ID PASS** |
| REQ-LAUNCHER-DEID-004 Final scanner | LD3 | Launcher 2.4、3.4、5.1 | **Win 安裝後 scan PASS**；**macOS post-sign scan PASS** |
| REQ-LAUNCHER-DEID-005 Flavor isolation | LD5、D7 | Launcher 4.1–4.2 | **雙平台 consumer harness gate PASS**；qa flavor 正式組包待 |
| REQ-LAUNCHER-DEID-006 AGPL materials | LD4、D9 | Launcher 4.3 | License／offer paths |


## Traceability rule

每個 Requirement MUST 至少對應一個 Design decision、Task 與可稽核 evidence。新增／修改 Requirement 時，本表 MUST 同一 PR 更新；缺任一欄時 `openspec validate --strict` 即使通過，release readiness review 仍 MUST 判定 FAIL。

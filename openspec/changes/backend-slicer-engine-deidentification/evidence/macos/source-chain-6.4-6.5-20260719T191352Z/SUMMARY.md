# macOS 6.4／6.5 — SBOM source chain + neutral build ID

**Date：** 2026-07-19  
**Artifact：** `web_slicer_core/third_party/slicer-engine/` · `engine_build_id=slicer-engine-consumer-2026-07-19T095348Z`

| Task | Deliverable | Result |
|------|-------------|--------|
| **6.5** | `engine_build_id.txt`＋manifest | **PASS** — neutral ID |
| **6.4** | `sbom.spdx.json`（SPDX-2.3）＋`source-chain.json` | **PASS** — CLI SHA-256 ↔ build_id ↔ `engine_commit` ↔ `legal/SOURCE-OFFER.md` |

**CLI SHA-256：** `3c6c0976ff2c6bfe4adf5c13a61e41378f0aab787f09ee47b3e4abba3866b95b`  
**engine_commit：** `59fec072c5215d1e9105856b6b9d483d66d1a222`  
**source_offer_present：** True

**Note：** CLI 無 `--version` flag；REQ-DEID-012 以 manifest＋`engine_build_id.txt` 滿足對外可查 build ID。

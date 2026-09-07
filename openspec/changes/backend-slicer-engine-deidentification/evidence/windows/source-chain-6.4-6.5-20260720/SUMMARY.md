# Windows 6.4／6.5 — SBOM source chain + neutral build ID

**Date：** 2026-07-20  
**Artifact：** `web_slicer_core/slicer-engine/` · `engine_build_id=20260719T162525Z`

| Task | Deliverable | Result |
|------|-------------|--------|
| **6.5** | `engine_build_id.txt`（root＋`bin/`） | **PASS** — neutral ID；VERSIONINFO 無 Prusa |
| **6.4** | `sbom.spdx.json`（SPDX-2.3）＋`source-chain.json` | **PASS** — exe/dll SHA-256 ↔ build_id ↔ `engine_commit` ↔ `legal/SOURCE_OFFER.md` |

**Note：** CLI 無 `--version` flag；REQ-DEID-012 以 **manifest＋`engine_build_id.txt`** 滿足對外可查 build ID。

**Scripts：** `write_engine_build_id_windows.ps1`、`generate_slicer_engine_sbom_windows.ps1`（已接入 `package_slicer_engine_windows.ps1`）。

Artifacts in this folder: `sbom.spdx.json`、`source-chain.json`、`engine_build_id.txt`、`engine-artifact-manifest.json`.

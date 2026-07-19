# macOS follow-up — CLI help／AGPL pack-in／5.5 local drill

**Date：** 2026-07-19  
**Host：** local macOS arm64  
**Change：** `backend-slicer-engine-deidentification`

## Scope（重要）

本檔證明的是 **`web_slicer_core/third_party/slicer-engine` staging**（晚上），**不是** 下午已簽／公證的  
`Bundle-Launcher/dist/mac-arm64/Bundle Launcher.app`（引擎 build `2026-07-17T123302Z`）。

| 產物 | build_id | CLI help 複核 | `legal/` |
|------|----------|---------------|---------|
| staging | `slicer-engine-consumer-2026-07-19T095348Z` | **PASS**（`--help`／`--help-fff` PrusaSlicer=0） | **有** |
| 已簽 Launcher.app | `slicer-engine-consumer-2026-07-17T123302Z` | 本機執行 `--help` **exit 137**／無輸出；**未證明**已清 | **無** |

## Verdict（staging only）

| Item | Result |
|------|--------|
| CLI `--help` / `--help-fff` `PrusaSlicer` hits | **0** |
| Formal consumer scan | **PASS**（nm 0；legal/ staged；brand_paths []） |
| AGPL materials in artifact | **staged** under `third_party/slicer-engine/legal/` |
| 5.5 local symbol drill | **PASS**（`verify_symbol_archive_macos.sh`） |
| Re-injected into signed Launcher §4 | **PASS** — DMG `…2111`；見 [`macos-launcher-evening-reinject-20260719.md`](./macos-launcher-evening-reinject-20260719.md) |

## #1 CLI help（staging）

- Fork：`PrintConfig.cpp`、`CLI/Setup.cpp`（user-visible `PrusaSlicer` → `Slicer Engine`）
- Rebuild＋`package_slicer_engine_macos.sh`
- `post_strip_sha256`：`3c6c0976ff2c6bfe4adf5c13a61e41378f0aab787f09ee47b3e4abba3866b95b`

## #2 AGPL engineering（staging）

| Path | Role |
|------|------|
| `docs/single-node-cloud/agpl-boundary.md` | modified fork＋1.6 政策敘事 |
| `legal/slicer-engine-agpl/*` | mac templates |
| `scripts/stage_slicer_engine_agpl_macos.sh` | 打入 artifact `legal/` |

政策簽核另見 [`legal-1.6-vance-approved-20260719.md`](./legal-1.6-vance-approved-20260719.md)。  
SOURCE-OFFER 模板在 staging 仍可能含 engineering 措辭；以 1.6 evidence 的 email／書面 offer 為 release channel。

## #3 5.5 mac half

- `verify_symbol_archive_macos.sh` PASS；paired Win＝OneDrive  
- ~~演練 6.6–6.7 仍開~~ → **Win＋mac 6.6–6.7 PASS 2026-07-20**（Win [`windows/symbolication-6.6-6.7-20260719T165250Z/`](./windows/symbolication-6.6-6.7-20260719T165250Z/)；mac [`macos/symbolication-6.6-6.7-20260719T191352Z/`](./macos/symbolication-6.6-6.7-20260719T191352Z/)）

## Gap / next

1. ~~將此 staging 餵入 `build-mac-bundle.sh` → sign／notarize → `scan_final_macos_artifact.sh`~~ → **DONE 2026-07-19 夜** — [`macos-launcher-evening-reinject-20260719.md`](./macos-launcher-evening-reinject-20260719.md)（DMG `…2111`）
2. ~~確認簽過 app 內存在 `slicer-engine/legal/` 且引擎 `--help` 可跑且無 `PrusaSlicer`~~ → **PASS**

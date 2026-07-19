# macOS Launcher §4 — evening consumer re-inject（CLI＋AGPL）

**Date：** 2026-07-19（21:08–21:25）  
**Host：** local macOS arm64  
**Change：** `backend-slicer-engine-deidentification`（main + Bundle-Launcher satellite）  
**Verdict：** **PASS** — staging `2026-07-19T095348Z` 已回灌進簽過／公證 `.app`＋DMG；簽過包內有 `legal/`；`--help`／`--help-fff` `PrusaSlicer`=0

## Scope closed（相對下午 1450 缺口）

| Check | Result |
|-------|--------|
| Engine build_id in signed app | `slicer-engine-consumer-2026-07-19T095348Z` |
| `legal/` in signed app | **YES** — LICENSE／NOTICE／MODIFICATIONS／SOURCE-OFFER／BUILD-STAMP |
| CLI `--help`／`--help-fff` | exit 0；`PrusaSlicer` hits **0** |
| D13 verify pre-sign | PASS（copied from staging） |
| Developer ID＋notarize＋staple | PASS（nested／app／DMG Accepted） |
| Final de-id scan | PASS — `~/Desktop/deid-final-macos_1.0.0-202607192111.json` |

## Artifacts

| Item | Path / value |
|------|----------------|
| Signed app | `Bundle-Launcher/dist/mac-arm64/Bundle Launcher.app` |
| Notarized DMG | `~/Desktop/Bundle Launcher_mac_arm64_1.0.0-202607192111.dmg` |
| Engine post_strip | `3c6c0976ff2c6bfe4adf5c13a61e41378f0aab787f09ee47b3e4abba3866b95b` |
| Engine post_sign | `336f930329d11dd02330ec4173802f20f9cd2eddacce171254eb41225cbda5d1` |
| Notary nested | `dbdde4ce-8928-493d-8bf3-d7b34c8a38df`（Accepted） |
| Notary app | `6a1639ac-6211-4825-94bb-ecd1f3bcd9dd`（Accepted） |
| Notary DMG | `572d2967-f9c8-42ef-92e7-f4966f4972c7`（Accepted） |
| Final scan | `~/Desktop/deid-final-macos_1.0.0-202607192111.json` |
| post_sign hash file | `~/Desktop/deid-final-macos_1.0.0-202607192111.post_sign_sha256.txt` |

## Reproduce

```bash
cd Bundle-Launcher
SKIP_PRINTER_BUILD=1 SKIP_X64=1 ./build-scripts/build-mac-bundle.sh

export CERT_ID="Developer ID Application: Po Yuan Wang (TM35RSG7WJ)"
export TEAM_ID="TM35RSG7WJ"
export NOTARY_PROFILE="phrozen-notary"
export APP_PATH="dist/mac-arm64/Bundle Launcher.app"
export ARCH_SUFFIX="arm64"
./release_sign_notarize.sh
```

## Notes

1. Supersedes afternoon DMG `…1450`（引擎 `2026-07-17T123302Z`、無 `legal/`）for mac consumer CLI／AGPL claims.
2. Afternoon §4 evidence [`macos-launcher-section4-20260719.md`](./macos-launcher-section4-20260719.md) remains valid as the first arm64 closed-loop proof; this file is the **re-inject** closure.
3. **Security：** do not commit Apple ID／app-specific passwords； rotate if pasted into chat.
4. `spctl` on DMG may report “rejected (…does not seem to be an app)” — expected for DMG; nested staple／app staple succeeded.

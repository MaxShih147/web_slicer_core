# macOS Launcher §4 closed-loop evidence

**Date：** 2026-07-19  
**Host：** local macOS arm64  
**Change：** `backend-slicer-engine-deidentification`（main + Bundle-Launcher satellite）  
**Verdict：** **PASS**（macOS arm64 Launcher D13 verify → pack → Developer ID sign → notarize → staple → final de-id scan）

## Scope closed

| Task | Result |
|------|--------|
| **4.1** macOS layout `slicer-engine/` | PASS — app embeds `Contents/Resources/bundle/slicer-engine/` |
| **4.5** D13 verify（manifest／hash／scan；no strip） | PASS pre-sign；post-sign uses `VERIFY_MODE=post-sign`（Developer ID changes Mach-O hash） |
| **4.3** codesign／notarize／staple | PASS — Identifier=`slicer-engine`；Team=`TM35RSG7WJ` |
| **4.4** final-artifact scanner fail closed | PASS — `deid-final-macos_1.0.0-202607191450-recheck.json` |

## Artifacts

| Item | Path / value |
|------|----------------|
| Signed app | `Bundle-Launcher/dist/mac-arm64/Bundle Launcher.app` |
| Notarized DMG | `~/Desktop/Bundle Launcher_mac_arm64_1.0.0-202607191450.dmg` |
| Engine post_strip | `6237f08ae74389c4c8518a296a75ec4e9e5688cb70c7a8de4640fd7c5969c504` |
| Engine post_sign | `ecf6b73bae12607f5239b3e91e15cad7d257ef1412572c1969bb5ff4f0bea5b0` |
| Engine build_id | `slicer-engine-consumer-2026-07-17T123302Z` |
| Notary app submission | `58c37ce8-e257-4601-8dd9-50884c085c6b`（Accepted） |
| Notary DMG submission | `d0bb9288-dccd-4313-8754-e7f8f750f5fa`（Accepted） |
| Final scan report | `~/Desktop/deid-final-macos_1.0.0-202607191450-recheck.json` |

## Scripts landed

| Script | Role |
|--------|------|
| `Bundle-Launcher/scripts/verify_slicer_engine_artifact.sh` | D13 pre-sign／post-sign verify |
| `Bundle-Launcher/scripts/scan_final_macos_artifact.sh` | Final app gate |
| `web_slicer_core/scripts/stage_slicer_engine_resources_macos.sh` | De-branded `Resources/` for Apple `bin/../Resources` |
| `web_slicer_core/scripts/package_slicer_engine_macos.sh` | Restored full D13 packager（was stub） |

## Notes

1. Developer ID codesign **must** change engine sha256 vs `post_strip_sha256`; final gate uses `VERIFY_MODE=post-sign` + records `post_sign_sha256` outside the app（do not write into stapled bundle）.
2. Resources copy excludes `*prusa*`／`*slic3r*` filenames（L1 path gate）.
3. Windows §4／Authenticode／§7 dual-platform still open.
4. **Security：** notary app-password was used via env for this run; rotate if exposed in chat logs.

## Reproduce

```bash
# Pre-sign pack (arm64 closed loop)
cd Bundle-Launcher
SKIP_PRINTER_BUILD=1 SKIP_X64=1 ./build-scripts/build-mac-bundle.sh

# Sign + notarize + staple + final scan
export CERT_ID="Developer ID Application: Po Yuan Wang (TM35RSG7WJ)"
export TEAM_ID="TM35RSG7WJ"
export APPLE_ID="…"          # do not commit
export NOTARY_APP_PASSWORD="…"  # do not commit
export APP_PATH="dist/mac-arm64/Bundle Launcher.app"
export ARCH_SUFFIX="arm64"
./release_sign_notarize.sh
```

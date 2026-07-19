# Windows Launcher §4 handoff evidence (unsigned)

- **captured_at_utc:** 2026-07-19T06:40:00Z
- **platform:** Windows x64
- **authenticode:** skipped (manual)
- **engine_build_id:** 20260719T063955Z
- **exe sha256:** `f9498ccb208c67ae878dcca58d5826754dbb9b7c0cdd29bc009760db6ad62f2f`
- **dll sha256:** `cedff73cc47035ff242c2507b15e99696d87bce65cce4aeb3fb0222b9c143f0d`
- **export:** `slicer_run_cli` only (count=1)
- **Launcher evidence:** [`Bundle-Launcher/.../evidence/windows-launcher-deid-gate-20260719T064000Z.md`](../../../../Bundle-Launcher/openspec/changes/backend-slicer-engine-deidentification/evidence/windows-launcher-deid-gate-20260719T064000Z.md)

## Tasks touched

- Main §4.2 / 4.4 / 4.5 (Windows verify path landed; full installer lifecycle still open)
- Launcher satellite 1.1 / 1.2 / 3.1 / 3.2 / 3.4 / 4.1 / 5.1(Win) / 5.2 (partial)

## Residual notes

- `bin/resources/**` still contains ~148 upstream brand-named profile/icon paths (noted by scanner; not fail-closed for PE/layout gate).
- Install/upgrade/rollback and post-Authenticode §7 remain open.

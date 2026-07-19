# Slicer Engine — Modification Summary

This document satisfies the AGPL-3.0 requirement for a prominent notice of
modifications to the Program (PrusaSlicer fork shipped as **Slicer Engine**).

## Nature of modifications (summary)

Material changes relative to upstream PrusaSlicer include (non-exhaustive):

1. **Rename / packaging** — CLI output name `slicer-engine`; consumer layout under
   `slicer-engine/`; removal of branded consumer symlinks.
2. **Identity strings** — Neutral `codesign` identifier, Info.plist hygiene,
   VERSIONINFO (Windows), and user-visible CLI help branding aligned to
   **Slicer Engine**.
3. **L2 / C′ hardening** — Hidden visibility + plain `strip` (macOS); export
   surface reduced to `slicer_run_cli` (Windows); neutral thread names;
   dSYM / PDB archived outside the consumer tree.
4. **QA crash harness** — Optional compile-time `BUNDLE_QA_CRASH_HARNESS`
   (qa flavor only; **off** in consumer releases).
5. **Headless / agent integration** — Build flags and packaging scripts for
   Bundle Launcher / web_slicer_core agent consumption.

Exact file-level history is in the fork git repository at the commit recorded
in `SOURCE-OFFER.md` / `engine-artifact-manifest.json`.

## How to verify this binary

1. Read `engine-artifact-manifest.json` next to the binary (`engine_build_id`,
   `post_strip_sha256`, fork commit fields when present).
2. Compare the binary SHA-256 to the manifest.
3. Fetch Corresponding Source per `SOURCE-OFFER.md` for that commit.

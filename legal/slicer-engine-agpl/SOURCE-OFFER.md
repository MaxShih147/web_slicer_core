# Corresponding Source Offer — Slicer Engine

**Status：** engineering draft — **Legal／OSS owner MUST replace placeholders** before
production release (tasks 1.6／6.2／6.3).

## Offer (AGPL-3.0 §6／§13)

PHROZEN TECH CO., LTD. offers to provide the **Corresponding Source** of the
modified Program distributed as **Slicer Engine** (`slicer-engine`) for any
copy of the binary you received, at no charge, by the means below.

| Field | Value |
|-------|--------|
| Product | Slicer Engine (modified PrusaSlicer fork) |
| License | AGPL-3.0-or-later |
| Fork remote (placeholder) | `REPLACE_WITH_PUBLIC_OR_OFFER_URL` |
| Exact commit | See `engine-artifact-manifest.json` → `source_commit` / build evidence; until filled, use the commit recorded at package time |
| Written offer contact (placeholder) | `REPLACE_WITH_LEGAL_CONTACT_EMAIL` |
| Offer validity | At least three years from the date you received this binary, or as long as we offer spare parts / support for the product that includes this binary — whichever is longer (AGPL §6) |

## Network interaction

If you interact with a network service that runs this modified Program, the
operator MUST also provide a prominent opportunity to obtain Corresponding
Source (AGPL §13). Bundle cloud / agent deployments MUST publish the same
commit offer as the shipped binary.

## How packagers fill this file

At package time, `stage_slicer_engine_agpl_macos.sh` stamps:

- `engine_build_id`
- `post_strip_sha256`
- `fork_commit` (from `git -C third_party/prusaslicer_fork rev-parse HEAD`)

Legal replaces the `REPLACE_WITH_*` placeholders once; subsequent releases only
need stamped commit／hash fields.

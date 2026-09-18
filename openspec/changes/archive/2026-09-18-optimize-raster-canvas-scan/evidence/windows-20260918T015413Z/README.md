# Phase 3 acceptance evidence (Windows x64)

Generated 2026-09-18T01:54:13Z from `scripts/raster_bench/work/` records by a one-off script; every number below is read from the files in this directory. Text only: no STL, SL1, PRZ, images or binaries.

- Verdict (round 2, `final-22f2e310a`): **PASS**, sections gates, curve, prz
- Verdict (round 1, `final-10fcc6d96`): **FAIL** (fullplate over its limit; see design.md D13)

## Files

- `summary.json`, `report.md`: `acceptance_report.py` output for round 2 (gates, curve, prz)
- `iteration1-summary.json`: round-1 `summary.json`, moved to `work/superseded/` by task 3.27
- `engines/<name>/build_info.json`: identity of the four engines (commit, tree, binary SHA-256)
- `fingerprints/golden|final/<case>/`: layer and preview fingerprint lists; `fingerprints/index.json`
- `verify-matrix.json`: the 36 `SLA_RASTER_VERIFY=1` runs of task 3.2 and their Golden comparison (3.3)
- `stage-timing.json`: per-stage `thread_s` diagnostics of tasks 3.4 and 3.5 with step1 references
- `prz-e2e.json`: task 3.8 agent runs and the masked PRZ comparison

## Engines

- `base-5bc83b08f`: commit `5bc83b08fe6f5191a02102e0abba464e430a40d4`, tree `561f61f0252ae5e22648cfbdad46e6b0f26fbbb4`, exe `105a657fa3db8b8327e46cadb6014c210a68246d98f44b1e7ccc97269f1b5b4c`, dll `97b6c2ee5bb3606c886d0384c55badd00e7f9c2372b6d18f04b847051b47af32`
- `step1-570c7c5e2`: commit HEAD `e2de10e0e7c52bfb44b3f3414b844a9a8f7141ec` + uncommitted diff (built before the stage commit), tree `570c7c5e2de7ab4763a243aedd59c04e733f46c7`, exe `0892571a72dc0b6dc3312082869cdf8b01fdd0cde460e3c70c093ab91bf87bcd`, dll `81094485add8eb10fb795f0b7c7b35daf646131f3b8bdca14d80a7b92991a261`
- `final-10fcc6d96`: commit `10fcc6d96e469e9464a0c143b45373c304aa7026`, tree `4e2963b2a46d5941631478efd730afd67b300c46`, exe `73a057055d6d232b6793ae0e0c0b3c8ccae7d12d79d0db4acd5bb685221fc6ee`, dll `772ce1cd1832b9ad2d8f088d774653b570c32a4cdb6c65908565d936f3a399aa`
- `final-22f2e310a`: commit `22f2e310ae6cdbeb3f9f0419fcc8e9d03b4e3fe6`, tree `78a3a8c1a8b1df4006a08150e629bf219045b1d0`, exe `30b55401e6090e7cac45cac7ab560246b7ab87d54eb3ed6d87d24633bf74b85d`, dll `55c01333c8368e1fc77cfa9715fad63a577582045b167db2df8c9e6ea7cf6597`

## Gates: round 1 vs round 2

Medians of the latest round of each case, base and final interleaved in one session.

| Case | Metric | Limit | Base r1 | Final r1 | Ratio r1 | Result r1 | Base r2 | Final r2 | Ratio r2 | Result r2 |
| --- | --- | --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | --- |
| primary-16k-guide-x8 | rasterizing_wall_s | 50% | 22.8226 s | 4.4747 s | 19.6% | PASS | 22.6058 s | 4.1437 s | 18.3% | PASS |
| primary-16k-guide-x8 | peak_pagefile_usage_bytes | 100% | 8,045.8 MiB | 2,215.6 MiB | 27.5% | PASS | 8,044.2 MiB | 2,228.4 MiB | 27.7% | PASS |
| primary-16k-guide-x8 | peak_working_set_bytes | 103% | 1,457.5 MiB | 1,448.6 MiB | 99.4% | PASS | 1,456.5 MiB | 1,456.8 MiB | 100.0% | PASS |
| secondary-8k-guide-x3 | rasterizing_wall_s | 100% | 6.3713 s | 1.3021 s | 20.4% | PASS | 6.2214 s | 1.3480 s | 21.7% | PASS |
| fullplate-16k-slab | rasterizing_wall_s | 103% | 2.1320 s | 2.2179 s | 104.0% | FAIL | 2.2062 s | 1.7602 s | 79.8% | PASS |

## Correctness matrix

- 36 runs, all slice exit codes 0: True; `[raster-verify]` lines: 0; all layer and preview fingerprints equal Golden: True
- Fingerprint lists of the final engine identical to Golden for every case: True

## End-to-end PRZ

- `acceptance_report.py` prz result: **PASS**, mask [68, 92), first difference outside the mask: None
- Independent check: same length True (103,667,342 bytes); differing offsets [85, 86]; outside the mask: 0
- File Time fields: base `2026-09-18 09:37:19`, final `2026-09-18 09:37:55`

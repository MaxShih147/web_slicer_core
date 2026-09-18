# Phase 3 acceptance report

- generated: 2026-09-18T01:38:05Z
- platform: windows
- sections: gates, curve, prz
- verdict: **PASS**

## Engines

| Role | Directory | slicer-engine.exe | slicer_core.dll | Fork commit |
| --- | --- | --- | --- | --- |
| base | base-5bc83b08f | 105a657fa3db8b8327e46cadb6014c210a68246d98f44b1e7ccc97269f1b5b4c | 97b6c2ee5bb3606c886d0384c55badd00e7f9c2372b6d18f04b847051b47af32 | 5bc83b08fe6f5191a02102e0abba464e430a40d4 |
| final | final-22f2e310a | 30b55401e6090e7cac45cac7ab560246b7ab87d54eb3ed6d87d24633bf74b85d | 55c01333c8368e1fc77cfa9715fad63a577582045b167db2df8c9e6ea7cf6597 | 22f2e310ae6cdbeb3f9f0419fcc8e9d03b4e3fe6 |

## Gates

### primary-16k-guide-x8: PASS

| Metric | Rule | Base median | Final median | Limit | Ratio | Result |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| rasterizing_wall_s | final median <= 50% of base median | 22.6058 | 4.1437 | 11.3029 | 18.3303% | PASS |
| peak_pagefile_usage_bytes | final median <= 100% of base median | 8,434,987,008 | 2,336,636,928 | 8434987008 | 27.7017% | PASS |
| peak_working_set_bytes | final median <= 103% of base median | 1,527,230,464 | 1,527,513,088 | 1573047377.92 | 100.0185% | PASS |

| Round | Superseded | Complete | Rerun? | Base s (min~max) | Final s (min~max) |
| --- | --- | --- | --- | --- | --- |
| a1 | False | True | 0 | 22.6058 (22.3873~23.4215) | 4.1437 (4.1277~4.249) |

### secondary-8k-guide-x3: PASS

| Metric | Rule | Base median | Final median | Limit | Ratio | Result |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| rasterizing_wall_s | final median <= 100% of base median | 6.2214 | 1.348 | 6.2214 | 21.6671% | PASS |

| Round | Superseded | Complete | Rerun? | Base s (min~max) | Final s (min~max) |
| --- | --- | --- | --- | --- | --- |
| a1 | False | True | 0 | 6.2214 (6.1823~6.4448) | 1.348 (1.2581~1.3581) |

### fullplate-16k-slab: PASS

| Metric | Rule | Base median | Final median | Limit | Ratio | Result |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| rasterizing_wall_s | final median <= 103% of base median | 2.2062 | 1.7602 | 2.2724 | 79.7842% | PASS |

| Round | Superseded | Complete | Rerun? | Base s (min~max) | Final s (min~max) |
| --- | --- | --- | --- | --- | --- |
| a1 | False | True | 0 | 2.2062 (2.2037~2.4271) | 1.7602 (1.7484~1.8321) |

### tiny-16k-crown-x1 (record only): PASS

final rasterizing median 0.3128 s, committed 1,120,186,368 B, RSS 842,301,440 B

## Thread scaling curve (record only): PASS

| Engine | Threads | Rasterizing median s | Committed median B | RSS median B | Source |
| --- | ---: | ---: | ---: | ---: | --- |
| base | 1 | 86.0009 | 7,552,221,184 | 911,908,864 | --threads 1, round a1 |
| base | 2 | 41.9741 | 7,710,826,496 | 877,899,776 | --threads 2, round a1 |
| base | 4 | 26.4197 | 7,970,570,240 | 1,057,497,088 | --threads 4, round a1 |
| base | 8 | 22.6058 | 8,434,987,008 | 1,527,230,464 | gate round a1 (default threads, effective 8) |
| final | 1 | 13.4329 | 1,448,456,192 | 891,412,480 | --threads 1, round a1 |
| final | 2 | 7.4419 | 1,618,653,184 | 836,915,200 | --threads 2, round a1 |
| final | 4 | 4.8704 | 1,850,208,256 | 1,052,766,208 | --threads 4, round a1 |
| final | 8 | 4.1437 | 2,336,636,928 | 1,527,513,088 | gate round a1 (default threads, effective 8) |

## End-to-end PRZ: PASS

- base: base.prz, 103,667,342 bytes, 813cb4ae5f94c56bbf033c42733ce7db584ebcda7d05b39b7b42fe1aabe92281
- final: final.prz, 103,667,342 bytes, cd5406df71505fe62a88aca39f3dec67efd4726ad7076446209b1b2835ef12cc
- masked bytes: [68, 92)

## Runs

| Run | Engine | Round | Threads | Golden | Superseded | Excluded / void |
| --- | --- | --- | ---: | --- | --- | --- |
| windows-p3-base-a1-fullplate-16k-slab-tdefault-r1 | base | a1 | 8 | 1 | False |  |
| windows-p3-base-a1-fullplate-16k-slab-tdefault-r2 | base | a1 | 8 | 1 | False |  |
| windows-p3-base-a1-fullplate-16k-slab-tdefault-r3 | base | a1 | 8 | 1 | False |  |
| windows-p3-base-a1-primary-16k-guide-x8-t1-r1 | base | a1 | 1 | 1 | False |  |
| windows-p3-base-a1-primary-16k-guide-x8-t1-r2 | base | a1 | 1 | 1 | False |  |
| windows-p3-base-a1-primary-16k-guide-x8-t1-r3 | base | a1 | 1 | 1 | False |  |
| windows-p3-base-a1-primary-16k-guide-x8-t2-r1 | base | a1 | 2 | 1 | False |  |
| windows-p3-base-a1-primary-16k-guide-x8-t2-r2 | base | a1 | 2 | 1 | False |  |
| windows-p3-base-a1-primary-16k-guide-x8-t2-r3 | base | a1 | 2 | 1 | False |  |
| windows-p3-base-a1-primary-16k-guide-x8-t4-r1 | base | a1 | 4 | 1 | False |  |
| windows-p3-base-a1-primary-16k-guide-x8-t4-r2 | base | a1 | 4 | 1 | False |  |
| windows-p3-base-a1-primary-16k-guide-x8-t4-r3 | base | a1 | 4 | 1 | False |  |
| windows-p3-base-a1-primary-16k-guide-x8-tdefault-r1 | base | a1 | 8 | 1 | False |  |
| windows-p3-base-a1-primary-16k-guide-x8-tdefault-r2 | base | a1 | 8 | 1 | False |  |
| windows-p3-base-a1-primary-16k-guide-x8-tdefault-r3 | base | a1 | 8 | 1 | False |  |
| windows-p3-base-a1-secondary-8k-guide-x3-tdefault-r1 | base | a1 | 8 | 1 | False |  |
| windows-p3-base-a1-secondary-8k-guide-x3-tdefault-r2 | base | a1 | 8 | 1 | False |  |
| windows-p3-base-a1-secondary-8k-guide-x3-tdefault-r3 | base | a1 | 8 | 1 | False |  |
| windows-p3-final-a1-fullplate-16k-slab-tdefault-r1 | final | a1 | 8 | 1 | False |  |
| windows-p3-final-a1-fullplate-16k-slab-tdefault-r2 | final | a1 | 8 | 1 | False |  |
| windows-p3-final-a1-fullplate-16k-slab-tdefault-r3 | final | a1 | 8 | 1 | False |  |
| windows-p3-final-a1-primary-16k-guide-x8-t1-r1 | final | a1 | 1 | 1 | False |  |
| windows-p3-final-a1-primary-16k-guide-x8-t1-r2 | final | a1 | 1 | 1 | False |  |
| windows-p3-final-a1-primary-16k-guide-x8-t1-r3 | final | a1 | 1 | 1 | False |  |
| windows-p3-final-a1-primary-16k-guide-x8-t2-r1 | final | a1 | 2 | 1 | False |  |
| windows-p3-final-a1-primary-16k-guide-x8-t2-r2 | final | a1 | 2 | 1 | False |  |
| windows-p3-final-a1-primary-16k-guide-x8-t2-r3 | final | a1 | 2 | 1 | False |  |
| windows-p3-final-a1-primary-16k-guide-x8-t4-r1 | final | a1 | 4 | 1 | False |  |
| windows-p3-final-a1-primary-16k-guide-x8-t4-r2 | final | a1 | 4 | 1 | False |  |
| windows-p3-final-a1-primary-16k-guide-x8-t4-r3 | final | a1 | 4 | 1 | False |  |
| windows-p3-final-a1-primary-16k-guide-x8-tdefault-r1 | final | a1 | 8 | 1 | False |  |
| windows-p3-final-a1-primary-16k-guide-x8-tdefault-r2 | final | a1 | 8 | 1 | False |  |
| windows-p3-final-a1-primary-16k-guide-x8-tdefault-r3 | final | a1 | 8 | 1 | False |  |
| windows-p3-final-a1-secondary-8k-guide-x3-tdefault-r1 | final | a1 | 8 | 1 | False |  |
| windows-p3-final-a1-secondary-8k-guide-x3-tdefault-r2 | final | a1 | 8 | 1 | False |  |
| windows-p3-final-a1-secondary-8k-guide-x3-tdefault-r3 | final | a1 | 8 | 1 | False |  |
| windows-p3-final-a1-tiny-16k-crown-x1-tdefault-r1 | final | a1 | 8 | 1 | False |  |
| windows-p3-final-a1-tiny-16k-crown-x1-tdefault-r2 | final | a1 | 8 | 1 | False |  |
| windows-p3-final-a1-tiny-16k-crown-x1-tdefault-r3 | final | a1 | 8 | 1 | False |  |

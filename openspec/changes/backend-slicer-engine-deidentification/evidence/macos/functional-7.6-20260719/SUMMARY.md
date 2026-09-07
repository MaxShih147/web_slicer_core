# macOS functional／performance regression — task 7.6（minimal matrix）

| Field | Value |
|-------|--------|
| **Date** | 2026-07-19 |
| **Verdict** | **PASS**（macOS arm64 half） |
| **Policy** | [`../functional-budget-2.7-approved-20260719.md`](../functional-budget-2.7-approved-20260719.md) |
| **Engine** | Signed app `Bundle-Launcher/dist/mac-arm64/Bundle Launcher.app` … `slicer-engine` |
| **build_id** | `slicer-engine-consumer-2026-07-19T095348Z` |
| **post_sign_sha256** | `336f930329d11dd02330ec4173802f20f9cd2eddacce171254eb41225cbda5d1` |
| **Fixture** | `agent/jobs/5731d266`（STL＋`config.ini`；同 3.6） |

## Cases（2.7 minimal matrix）

| # | Case | Result | Notes |
|---|------|--------|-------|
| 1a | `--help` | **PASS** | exit 0；`PrusaSlicer`=0；99 lines；0.037 s |
| 1b | `--help-fff` | **PASS** | exit 0；`PrusaSlicer`=0；0.040 s |
| 2 | missing STL | **PASS** | exit 1；`PrusaSlicer`=0；0.036 s |
| 3 | `--export-sla` cold／warm | **PASS** | see metrics below |
| 4 | agent-style smoke（`SLICER_ENGINE_BIN`→signed engine `--help`） | **PASS** | exit 0；0.074 s |

## Export-SLA metrics（policy gates）

| Gate | Result |
|------|--------|
| cold exit／size | 0／**1610856** bytes／**8.563** s |
| warm exit／size | 0／**1610854** bytes／**8.065** s |
| size warm vs cold ±5% | **PASS**（band [1530313, 1691399]） |
| size vs 3.6 ~1.6 MiB ±5%（info） | **PASS** |
| perf warm ≤ cold × 1.20 | **PASS**（limit 10.276 s；warm 8.065 s） |

Raw：`export-sla-metrics.json`、`logs/`、`out/out-cold.sl1`、`out/out-warm.sl1`、`METADATA.json`、`results.env`.

## Scope note

- This closes **macOS** half of task **7.6** under the approved minimal matrix.
- **Windows** half：**PASS** — [`../../windows/functional-7.6-20260719T143000Z/SUMMARY.md`](../../windows/functional-7.6-20260719T143000Z/SUMMARY.md)（union 2026-07-19）.
- Full `acceptance-procedure.md` §6 extended suite remains SHOULD／後補 per 2.7.
- Gate 5／1.5／2.8／7.7：**Vance Approve 2026-07-19**；optional 8.5／8.6 for `completed`.

## Reproduce

```bash
ENG="Bundle-Launcher/dist/mac-arm64/Bundle Launcher.app/Contents/Resources/bundle/slicer-engine/bin/slicer-engine"
STL="web_slicer_core/agent/jobs/5731d266/input/model.stl"
INI="web_slicer_core/agent/jobs/5731d266/config.ini"
"$ENG" --help
"$ENG" --help-fff
"$ENG" --export-sla --load "$INI" /tmp/__missing__.stl   # expect non-zero
"$ENG" --export-sla --load "$INI" -o /tmp/out.sl1 "$STL"
```

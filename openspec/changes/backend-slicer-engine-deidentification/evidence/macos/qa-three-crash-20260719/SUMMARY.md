# macOS — QA three-crash dynamic（2026-07-19）

**Flavor：** `qa`（`BUNDLE_QA_CRASH_HARNESS=ON`）  
**Staging：** `web_slicer_core/third_party/slicer-engine-qa/`  
**build_id：** `slicer-engine-qa-2026-07-17T121917Z`  
**Companion consumer：** signed `…2111` engine `336f9303…`（harness must be absent）

## Method

For each mode, run packaged QA CLI with env then expect **non-zero** exit:

```bash
BUNDLE_QA_CRASH_MODE=overflow|segfault|exception \
  third_party/slicer-engine-qa/bin/slicer-engine --help
```

Control（no env）and consumer＋`BUNDLE_QA_CRASH_MODE=segfault` must exit **0**.

## Results

| Case | Exit | Verdict |
|------|------|---------|
| qa control（no env） | 0 | **PASS** |
| qa overflow | -11（SIGSEGV／abort class） | **PASS** |
| qa segfault | -11 | **PASS** |
| qa exception | -6（SIGABRT／abort class） | **PASS** |
| consumer＋segfault env | 0（harness absent） | **PASS** |

Artifacts：`summary.json`、`stdout-*`／`stderr-*` in this folder.

## Notes

- Full `.ips` brand forensics already covered by PoC [`../../poc/evidence/m1-close-20260717T032408Z/`](../../poc/evidence/m1-close-20260717T032408Z/).  
- This round mirrors Win 7.3 style：**exit-code proof** that three compile-time sites still fire on the release-equivalent qa tree.  
- Supports task **7.1** declaration；task **7.3** dual-platform dynamic remains Win formal＋mac PoC／this probe.

## Related

- tasks **7.1**／**7.3**  
- Declare：[`../section7-mac-declare-7.1-20260719.md`](../section7-mac-declare-7.1-20260719.md)

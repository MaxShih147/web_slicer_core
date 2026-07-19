# macOS symbolication / loss / rollback — tasks 6.6–6.7

**Verdict：** PASS  
**engine_build_id：** `slicer-engine-consumer-2026-07-19T095348Z`  
**Mach-O UUID：** `A5826E32-5956-3C14-A6B9-63F9354DCAF2`  
**dSYM UUID match：** True  
**Drill store：** `/Users/sw-dev/repos/Bundle/web_slicer_core/openspec/changes/backend-slicer-engine-deidentification/evidence/macos/symbolication-6.6-6.7-20260719T191352Z/symbol-store-mirror/macos/slicer-engine-consumer-2026-07-19T095348Z`  
**Symbol loss (missing build_id)：** detected=True  
**Prior symbols path：** `/Users/sw-dev/repos/Bundle/web_slicer_core/third_party/slicer-engine-symbols`

## Method

1. `verify_symbol_archive_macos.sh` — consumer has no dSYM; UUID bin==dSYM==manifest.  
2. Stage `symbol-store-mirror/macos/<build_id>/` with dSYM＋manifest.  
3. 6.7a：lookup missing build_id → absent.  
4. 6.7b：current symbols retained under mirror for rollback.

dSYM-free consumer `bin/` unchanged; symbols never copied into signed app.

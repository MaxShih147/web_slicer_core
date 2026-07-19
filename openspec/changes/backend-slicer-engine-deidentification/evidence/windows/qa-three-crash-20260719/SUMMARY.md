# Windows §7.3 — QA three-crash dynamic（2026-07-19）

**Flavor：** `qa`（`BUNDLE_QA_CRASH_HARNESS=ON`）  
**Staging：** `web_slicer_core/slicer-engine-qa/`  
**build_id：** `20260719T103747Z`  
**Scan：** `scan_slicer_engine_windows.ps1 -ExpectFlavor qa` → **PASS**（harness markers present；`qa_delta` set）

## Method

```bat
scripts\build_prusaslicer_fork_windows.bat qa
powershell -File scripts\package_slicer_engine_windows.ps1 -Flavor qa -OutRoot slicer-engine-qa
```

For each mode, run packaged CLI with env then expect **non-zero** NTSTATUS exit:

```bat
set BUNDLE_QA_CRASH_MODE=overflow|segfault|exception
slicer-engine-qa\bin\slicer-engine.exe --help
```

## Results

| Mode | Exit code | NTSTATUS（interpret） | Verdict |
|------|-----------|----------------------|---------|
| overflow | -1073741571 | `0xC00000FD` STACK_OVERFLOW | **PASS** |
| segfault | -1073741819 | `0xC0000005` ACCESS_VIOLATION | **PASS** |
| exception | -1073740791 | `0xC0000409` FAST_FAIL／abort | **PASS** |
| control（no env） | 0 | OK `--help` | **PASS** |
| **consumer** staging + `BUNDLE_QA_CRASH_MODE=segfault` | 0 | harness absent | **PASS** |

Artifacts：`summary.json`、`stdout-*`／`stderr-*` in this folder.

## Notes

- Full WER／minidump capture＋module-name forensics already covered by PoC `w25-close`；本輪以 **exit NTSTATUS** 證明三種 mode 可觸發。  
- After QA build, **Release/** was QA — restore with `build_prusaslicer_fork_windows.bat low` before packaging consumer again.  
- Launcher **4.2** formal QA bundle into Setup：**未跑**（可選）。

## Related

- tasks **7.3**  
- PoC：[`../../poc/evidence/w25-close-20260717T083241Z/`](../../poc/evidence/w25-close-20260717T083241Z/)  
- follow-up：[`../section7-followup-20260719.md`](../section7-followup-20260719.md)  

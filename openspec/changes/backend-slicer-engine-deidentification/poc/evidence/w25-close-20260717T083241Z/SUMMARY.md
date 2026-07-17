# Windows 2.5 PoC run `w25-close-20260717T083241Z`

**Verdict:** PASS (PoC) — L1 rename / VERSIONINFO / PDBALTPATH / three crashes verified; export entry is `slicer_run_cli` (residual mangled exports ~470 deferred to tasks 5.3).

## Artifacts

| File | sha256 |
|------|--------|
| slicer-engine.exe | 62A7F4B55C83C8424070A8175E92205D66CE0CA1426B1B64A3E839DD470F9EA0 |
| slicer_core.dll | A16577A2EE24D4C71585CC93FA7106FCA8A4C39893A37376D7F1B06CEE251DC9 |

## Static

- VERSIONINFO: Company=`Phrozen Technology`; Product=`Slicer Engine`; OriginalFilename=`slicer-engine.exe`
- Export: `slicer_run_cli`=True; `slic3r_main`=False; named_exports≈470 (cereal mangled residual)
- PE debug directory RSDS: `slicer-engine.pdb` / `slicer_core.pdb` (short neutral names; no `prusaslicer_build` path)

## Crashes

| Mode | Process exit | Dump | Notes |
|------|-------------:|------|-------|
| overflow | 0xC00000FD | overflow.dmp | stack overflow |
| segfault | 0xC0000005 | segfault.dmp | AV null deref |
| exception | 0xC0000409 | exception.dmp | C++ EH then terminate |

PDB-free stack (segfault): modules `slicer_engine` + `slicer_core`; frames `slicer_core!slicer_run_cli+…` (no `PrusaSlicer` / `slic3r_main` module names).

Dump hashes: see `dumps/HASHES.txt` (~85MB each; do not commit to git; keep internal).

## Harness

- Compile-time `BUNDLE_QA_CRASH_HARNESS=ON`
- Mode via `BUNDLE_QA_CRASH_MODE` (QA flavor only)
- Removed runtime probe from `SLAPrint.cpp`

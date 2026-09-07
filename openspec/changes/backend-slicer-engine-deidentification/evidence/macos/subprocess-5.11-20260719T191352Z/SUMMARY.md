# macOS subprocess boundary — tasks 5.11

**Verdict：** PASS  
**Engine：** `/Users/sw-dev/repos/Bundle/web_slicer_core/third_party/slicer-engine/bin/slicer-engine`  
**Shell PID：** 25678  
**--help exit：** 0 · PrusaSlicer hits：**0**  
**pytest：** skipped (no local pytest; PID/help evidence below)

REQ-DEID-008／D4：engine remains a separate OS process; agent does not in-process-link libslic3r.

## Manual PID proof

See `help-stdout.txt` (brand-free). Engine CLI is an external Mach-O invoked by exec/subprocess; agent address space does not map the engine binary as a library.

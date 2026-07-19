# AGPL Boundary

## Overview

The slicing engine shipped with Bundle Launcher / `web_slicer_core` is a **modified fork** of PrusaSlicer, licensed under the **GNU Affero General Public License v3 or later (AGPL-3.0-or-later)**.

This document defines where the engine is used, how the **subprocess AGPL boundary** is maintained for the rest of the product, and what **modified-work release obligations** apply to the engine itself.

> **Status (2026-07-19):** Tasks **6.1**＋**1.6** closed — Vance **approved** AGPL release policy.  
> Corresponding Source channel：**email／written offer**（see `legal/slicer-engine/SOURCE_OFFER.md`）。**No mandatory public GitHub URL.**  
> De-identification (neutral process／path names) does **not** remove AGPL disclosure duties (OpenSpec D9／REQ-DEID-011).

## Where the engine is used

The engine runs **exclusively as a headless CLI binary**. Local agent / workers invoke it as an external program (no in-process link to `libslic3r`).

```
Worker / local agent              Slicer Engine CLI (AGPL-3.0-or-later)
(our application code)            (modified PrusaSlicer fork)

    job = dequeue()
    prepare_input(job)
    ──── subprocess ────────────> slicer-engine --export-sla model.stl
                                  ... processes geometry ...
    <──── exit code + files ───── output.sl1
    store_output(job)
```

### Interaction boundary (unchanged)

| Aspect | Detail |
|--------|--------|
| **Invocation** | `subprocess` / Popen with argv + files |
| **Communication** | CLI args + filesystem I/O |
| **No linking** | Application code does **not** link `libslic3r` / engine DLL into the agent process for slicing |
| **No shared memory** | Separate process address space |
| **Modified fork** | We build and ship a modified PrusaSlicer fork; release compliance tracks the exact fork／engine commit |
| **No embedding** | Engine is not imported as a Python/JS module |

Windows consumer layout uses a shim `slicer-engine.exe` that loads `slicer_core.dll` **inside the engine process** — that is part of the AGPL Program, not a link from the agent into libslic3r.

## Modified work — current position

| Statement | Status |
|-----------|--------|
| We ship an **unmodified** upstream binary | **False** — we build and ship a **modified fork** |
| Product / process rename (Slicer Engine, neutral paths) | **Yes** |
| Build／de-ID changes (visibility, exports, strip, VERSIONINFO, etc.) | **Yes** |
| Optional QA crash harness (compile-time; consumer OFF) | **Yes** (QA flavor only) |

Therefore AGPL **modified Program** obligations apply to the engine artifact:

1. Ship AGPL license text with the binary (`legal/LICENSE`)
2. Ship copyright / prominent modification notice (`legal/NOTICE.md`)
3. Provide Corresponding Source for the **exact** `engine_commit` (`legal/SOURCE_OFFER.md` + email／written offer; public browse URL optional)
4. Do **not** remove or weaken these materials in the name of de-identification (OpenSpec D9 / REQ-DEID-011)

De-identification (L1/L2) only reduces brand fingerprints in OS diagnostics and product UX. Anyone who reads the legal pack can still learn the upstream origin — that is intentional and required.

AGPL-3.0 Section 13 (network interaction) still applies when users interact remotely with a service that runs this modified Program: the operator must offer Corresponding Source. The approved channel for Bundle releases is the written／email offer recorded under `legal/slicer-engine/SOURCE_OFFER.md` (Vance-approved 2026-07-19).

## What remains a separate work

The following are **not** treated as derivative works of the engine solely because they invoke the CLI:

| Component | Reason |
|-----------|--------|
| FastAPI / cloud services | Separate programs; no linking |
| Local agent Python | Invokes CLI via subprocess |
| Frontend (Vue.js) | Browser; no engine link |
| Queue / nginx / job orchestration | Infrastructure / orchestration |
| STL tooling (e.g. trimesh) | Separate libraries |

## Practical guidelines

1. **Never** import engine C++ into Python/JS or link `libslic3r` into the agent
2. **Always** invoke via CLI (`SLICER_ENGINE_BIN` / packaged `slicer-engine`)
3. Keep engine binaries in the staged `slicer-engine/` layout (not mixed into app source as a library)
4. Record `engine_commit` / `engine_build_id` / hashes in `engine-artifact-manifest.json`
5. On every consumer package, include `legal/LICENSE`, `legal/NOTICE.md`, `legal/SOURCE_OFFER.md` (and modification summary when present)
6. Corresponding Source：follow the written／email offer in `SOURCE_OFFER.md`（Vance-approved 2026-07-19；public browse URL optional）
7. Do **not** confuse de-identification with license anonymity — required notices must remain prominent and accurate

## Code touchpoints

| File | Usage |
|------|-------|
| `agent/sla_operations.py` | Calls slicer-engine CLI for hollow / support / slice |
| `agent/config.py` | `SLICER_ENGINE_BIN` (legacy `PRUSA_SLICER_BIN` local fallback only) |
| `scripts/package_slicer_engine_windows.ps1` | Stages consumer PE + legal pack |
| `scripts/package_slicer_engine_macos.sh` / `scripts/stage_slicer_engine_agpl_macos.sh` | Stages macOS consumer + `slicer-engine/legal/` |
| `legal/slicer-engine/*` | Canonical Win／release templates（LICENSE／NOTICE／SOURCE_OFFER） |
| `legal/slicer-engine-agpl/*` | macOS packaging templates staged into artifact `legal/` |

Typical invocation:

```python
subprocess.run([config.SLICER_ENGINE_BIN, "--export-sla", ...])
```

No engine Python bindings, no ctypes load of `slicer_core.dll` from the agent for slicing.

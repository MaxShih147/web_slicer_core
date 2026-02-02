# AGPL Boundary

## Overview

PrusaSlicer is licensed under the **GNU Affero General Public License v3 (AGPL-3.0)**. This license has strong copyleft requirements, particularly for software accessed over a network.

This document defines where PrusaSlicer is used in our system and how the AGPL boundary is maintained.

## Where PrusaSlicer is Used

PrusaSlicer is used **exclusively as a headless CLI binary**. It is invoked by worker processes as an external program.

```
Worker process                    PrusaSlicer CLI
(our code, our license)           (AGPL-3.0)

    job = dequeue()
    prepare_input(job)
    ──── subprocess.run() ──────> prusa-slicer --export-sla model.stl
                                  ... processes geometry ...
    <──── exit code + files ───── output.sl1
    store_output(job)
```

### Interaction boundary

| Aspect | Detail |
|--------|--------|
| **Invocation method** | `subprocess.run()` / `subprocess.Popen()` |
| **Communication** | Command-line arguments + file I/O |
| **No linking** | Our code does not link against PrusaSlicer libraries |
| **No shared memory** | Separate process with separate address space |
| **No code modification** | We use the unmodified PrusaSlicer binary |
| **No embedding** | PrusaSlicer is not imported, loaded, or embedded |

## How the AGPL Boundary is Respected

### What AGPL requires

AGPL-3.0 Section 13 (the "network use" clause):

> If you modify the Program, your modified version must prominently offer all users interacting with it remotely through a computer network an opportunity to receive the Corresponding Source.

### Our position

1. **We do not modify PrusaSlicer** — we use the official binary (or a fork built from public source)
2. **We do not link against PrusaSlicer** — no shared libraries, no dynamic linking, no FFI
3. **PrusaSlicer is an independent program** — invoked via CLI, communicates via files
4. **Our application is a separate work** — it orchestrates PrusaSlicer the same way a shell script would

This is analogous to:
- A web application that calls `ffmpeg` to transcode video
- A CI system that calls `gcc` to compile code
- A script that calls `imagemagick` to resize images

The calling application is not a derivative work of the tool it invokes.

## What Source Code Would Need to Be Disclosed

### If we modify PrusaSlicer

If we fork and modify PrusaSlicer source code, we must:

1. Make the modified source available to any user who interacts with it over the network
2. Include a prominent notice about the modifications
3. Provide source alongside the binary or via a written offer

This applies to our forked PrusaSlicer binary, **not to our web application**.

### If we DO NOT modify PrusaSlicer

No source disclosure obligation for our application. We should:

- Document which version of PrusaSlicer is used
- Provide a link to the upstream source repository
- Include the AGPL license text alongside the binary

## What is NOT a Derived Work

The following are **not** derivative works of PrusaSlicer:

| Component | Reason |
|-----------|--------|
| FastAPI application | Separate program, no linking |
| Worker process | Invokes CLI via subprocess |
| Frontend (Vue.js) | Runs in browser, no interaction with PrusaSlicer |
| Queue system | Infrastructure, no PrusaSlicer code |
| Nginx config | Infrastructure |
| Job management logic | Orchestration, not derivation |
| STL processing (trimesh) | Separate library, separate license |

## Practical Guidelines

1. **Never import PrusaSlicer code** into our Python/JS codebase
2. **Never link against** `libslic3r` or other PrusaSlicer libraries
3. **Always invoke via CLI** — `subprocess.run(["prusa-slicer", ...])`
4. **Keep the binary separate** — stored at a known path, not bundled in our source tree
5. **Document the version** — record which PrusaSlicer version/commit is deployed
6. **If forking**: maintain the fork as a separate repository with full AGPL compliance

## Current PrusaSlicer Usage in Code

| File | Usage |
|------|-------|
| `agent/sla_operations.py` | Calls PrusaSlicer CLI for hollow, support, slicing |
| `agent/config.py` | Stores path to PrusaSlicer binary |

All invocations follow the pattern:
```python
subprocess.run([config.PRUSA_SLICER_PATH, "--export-sla", ...])
```

No PrusaSlicer Python bindings, no ctypes, no shared objects.

# Symbol archive runbook（macOS half）— tasks 5.5

**Status：** draft／macOS operational  
**Date：** 2026-07-19  
**Depends：** D13 `package_slicer_engine_macos.sh`

## What is archived

| Item | Location（local） |
|------|-------------------|
| dSYM | `web_slicer_core/third_party/slicer-engine-symbols/slicer-engine.dSYM` |
| Unstripped Mach-O | `…/slicer-engine-symbols/slicer-engine.unstripped` |
| UUID | in `engine-artifact-manifest.json` → `symbol_archive.uuid_or_guid` |
| build_id | `engine_build_id` / `engine_build_id.txt` |
| post_strip hash | `post_strip_sha256` |
| post_sign hash | recorded by Launcher final scan（outside app） |

Consumer artifact tree **must not** contain `.dSYM`／`.unstripped`.

## Produce archive

```bash
cd web_slicer_core
PACKAGE_SLICER_ENGINE=1 ./scripts/build_prusaslicer_fork_macos.sh
# or package only:
# SLICER_ENGINE_FLAVOR=consumer ./scripts/package_slicer_engine_macos.sh
```

## Lookup for crash symbolication

1. From customer report / Launcher version note `engine_build_id`（or post_sign sha256）.  
2. Locate matching `engine-artifact-manifest.json` + `slicer-engine-symbols/`.  
3. Confirm `symbol_archive.uuid_or_guid` matches crashed binary UUID (`dwarfdump --uuid`).  
4. Symbolicate with matching dSYM（lldb / `atos` / Xcode）.  
5. **Never** copy dSYM into consumer release or next to a stapled app under test.

## Retention / ACL（TODO for full 5.5 close）

- [ ] Upload dSYM + unstripped + manifest to internal artifact store（ACL-restricted）  
- [ ] Retention policy（e.g. N release trains）  
- [ ] Rollback drill documented  
- [ ] Windows PDB half（`/PDB:` staging）paired here  

Until store exists, treat `third_party/slicer-engine-symbols/` as **local-only**（gitignored）and back up off-machine for releases that ship.

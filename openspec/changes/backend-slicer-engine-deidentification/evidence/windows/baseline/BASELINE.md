# Windows Baseline — tasks 1.7

**Status：** captured（2026-07-17）  
**Authority run：** [`win-baseline-20260717T055632Z/`](./win-baseline-20260717T055632Z/)  
**Procedure：** [`acceptance-procedure.md`](../../../acceptance-procedure.md) §5.1  
**Source artifact：** Bundle-Launcher `dist/win-unpacked/.../prusaslicer_build/src/Release/`（consumer-like unpack；非 Authenticode 簽核包）

## 0. Verdict for 1.7

| Item | Result |
|------|--------|
| process／module path | **captured** — `prusa-slicer-console` + `PrusaSlicer.dll` brand paths |
| VERSIONINFO | **captured** — exe fully branded；DLL empty |
| `dumpbin /exports` | **captured** — 470 named exports；`slic3r_main` present；~462 lines contain `Slic3r` |
| WER／dump surface | **captured** — LocalDumps configured；minidump module list + PDB-free stack show brand module names |
| PDB path in PE | **captured** — console exe debug directory → `...\prusa-slicer-console.pdb` under `prusaslicer_build` |
| shim loader error | **captured** — `PrusaSlicer.dll was not loaded` |

**Gate：** tasks **1.7 已關閉**；政策 **2.3 decided**；PoC **2.5 PASS** — [`poc/REPORT-WIN.md`](../../../poc/REPORT-WIN.md)。  
**非本 task：** Authenticode 最終包、export 收斂為 1（→ 5.3）、consumer OFF harness 稽核（→ 5.6）。

## 1. Environment

| Field | Value |
|-------|-------|
| OS | Windows NT 10.0.26200.0（x64） |
| Toolchain probe | VS 2022 Community；`dumpbin` 14.29；`cdb` 10.0.22621 |
| `_NT_SYMBOL_PATH` | empty at capture |
| Private PDB | not injected；analysis used cleared `.sympath` (MS public `srv*` may still resolve ntdll) |
| QA crash harness | **absent** on this Windows build（`BUNDLE_QA_CRASH_MODE=*` → exit 0，正常 `--help`） |

## 2. Artifact hashes（source）

| File | sha256 | bytes |
|------|--------|------:|
| `prusa-slicer-console.exe` | `92F40FD062505FD5494848B0FA22E1484547958076906A5F36DDFA5B89F458DE` | 134144 |
| `prusa-slicer.exe` | `63B53B12772E5C446622BEB517AB06210337682E697B4A1CC8189B70F9AE407E` | 134144 |
| `PrusaSlicer.dll` | `DD998AC8524AB89DC05B1F0DCDB46279BFA5A0B41C80B5CF093AC84ADD55521F` | 16932864 |

## 3. Fingerprint summary（pre-deidentification）

### L1

| Surface | Observed brand |
|---------|----------------|
| Process name | `prusa-slicer-console` |
| Module path | `...\prusa-slicer-console.exe`、`...\PrusaSlicer.dll` |
| Bundle path | `...\third_party\prusaslicer_build\src\Release\...` |
| VERSIONINFO（exe） | Company=`Prusa Research`；Product／Internal／Description=`PrusaSlicer`；Version=`PrusaSlicer-2.9.4+UNKNOWN`；OriginalFilename=`prusa-slicer.exe` |
| VERSIONINFO（DLL） | empty（仍以檔名 `PrusaSlicer.dll` 暴露） |
| CLI banner | `PrusaSlicer-2.9.4+UNKNOWN based on Slic3r`；Usage `prusa-...` |
| Loader error | `PrusaSlicer.dll was not loaded` |

### L2

| Surface | Observed brand |
|---------|----------------|
| Export entry | `slic3r_main`（ordinal／hint 見 `EXPORT_slic3r_main.txt`） |
| Export table | **470** named exports；majority mangled with `Slic3r` |
| PE debug／PDB path（exe） | `C:\...\web_slicer_core\third_party\prusaslicer_build\src\Release\prusa-slicer-console.pdb` |
| Minidump modules | `prusa_slicer_console`、`PrusaSlicer` |
| Minidump stack（no private PDB） | frames named `prusa_slicer_console!wmain+…`（module brand visible） |

## 4. Evidence index

| Path | Purpose |
|------|---------|
| `METADATA.json` | run metadata + source sha256 |
| `static/VERSIONINFO.txt` | PE version resources |
| `static/EXPORTS_PrusaSlicer.dll.txt` | full `dumpbin /exports` |
| `static/EXPORT_slic3r_main.txt` / `EXPORT_COUNTS.txt` | key export hits |
| `static/PDB_PATH_STRINGS_EXE.txt` | embedded PDB path |
| `static/HEADERS_*.txt` | PE headers／debug directory |
| `dynamic/PROCESS_MODULES_help.txt` | live process／module paths |
| `dynamic/SHIM_LOADER_ERROR.txt` | missing-DLL loader message |
| `dynamic/QA_CRASH_MODE_PROBE.txt` | proves no runtime crash harness |
| `dynamic/LOCALDUMPS_CONFIG.txt` | HKCU LocalDumps for console exe |
| `dynamic/WER_METADATA_BASELINE.txt` | dump-surface brand lines |
| `dynamic/MINIDUMP_STACK_PDBFREE.txt` | cdb `lm`＋`k` log |
| `dumps/postload-baseline.dmp` | dump at `PrusaSlicer.dll` load（authoritative for module list） |
| `dumps/forced-av-baseline.dmp` | earlier debugger dump（supplementary） |

## 5. Implications for 2.3／2.5

> **2.3／2.5 已關閉（2026-07-17）：** 政策見 [`windows-policy.md`](../../windows-policy.md)；PoC 見 [`poc/REPORT-WIN.md`](../../../poc/REPORT-WIN.md)。

1. **Rename contract：** ~~baseline 現況~~ → **2.5 PoC 已達** `slicer-engine.exe`／`slicer_core.dll`／`slicer_run_cli`（export=1 → **5.3**）。  
2. **Export surface：** 政策 470 → 1；PoC 入口已更名，殘餘 mangled → **5.3**。  
3. **PDB policy：** `/DEBUG`＋`/PDB:`＋`/PDBALTPATH:` — **2.5 已證 RSDS 短中性名**。  
4. **Crash harness：** compile-time — **2.6／2.5 Done**。  
5. **Loader string：** PoC 已中性化。

## 6. Follow-ups（not blocking 1.7／2.3／2.5）

- Authenticode-signed installer baseline（optional；正式 §7）。  
- ~~**5.3** export=1~~／~~**5.6** consumer OFF~~ → **Done**。  
- ~~Launcher §4／Win 正式組包／post-sign~~ → **Win unsigned＋已簽 Setup lifecycle Done 2026-07-19**；macOS Launcher 仍開。見主 [`PROGRESS.md`](../../PROGRESS.md)。

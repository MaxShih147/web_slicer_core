# macOS productization close notes — tasks 5.2 / 3.5 / 3.6

**Date：** 2026-07-17  
**Binary：** `third_party/slicer-engine/bin/slicer-engine`（post 5.1 nm=0 package）

## 5.2 Thread call sites

| Call site | Status |
|-----------|--------|
| `CLI/Setup.cpp` → `slicer-worker` | OK（consumer `strings` 可見） |
| `libslic3r/Thread.cpp` TBB → `slicer-tbb-N` | OK |
| `GUI/BackgroundSlicingProcess.cpp` | 改 `slicer-bg-slc`（GUI-only；headless 不編入，仍清全 call site） |
| `GUI/Jobs/BoostThreadWorker.cpp` | 透傳名稱；無硬編碼品牌 |

Consumer binary：`slicer-worker`／`slicer-tbb-` 存在；無 `slic3r_main`／`slic3r_Bg*`。

## 3.5 User-visible surfaces（agent／CLI）

| Surface | Action |
|---------|--------|
| Agent job／cut errors | `Slicing engine failed…`／`Slicing engine cut failed…` |
| FastAPI description | 改為 slicer engine CLI |
| Crash sentinel logs | 去 Prusa 字樣 |
| CLI `--help`／missing file | 無 brand token |
| Binary `strings` 殘餘（3MF metadata／`prusaslicer://` 等） | **L3**；本版不清（blacklist／design） |

## 3.6 macOS CLI regression（packaged consumer）

| Case | Result |
|------|--------|
| `--help` | PASS — `Slicer Engine…`／`Usage: slicer-engine` |
| Missing STL | exit 1；stderr 無 brand |
| `--export-sla` + job `5731d266` STL／INI | exit 0；產出 `out.sl1`（~1.6MB） |

**註：** 雙平台完整 regression 與 performance budget 仍見 tasks **2.7／7.6**；本項為 macOS 正式 consumer binary 煙霧／功能抽樣。

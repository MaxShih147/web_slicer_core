# Windows 5.1b probe — RTTI／例外型別名（abort／WER）2026-07-20

**Verdict：** 使用者可見表面（stdout／stderr／WER）**未**出現 demangle 型別名 `Slic3r::…`。  
**Platform note：** `.ips` 僅 macOS；本機為 Windows，對等媒介為 **WER `Report.wer`＋CrashDumps minidump**。

## Setup

| 項 | 值 |
|----|-----|
| Binary | `web_slicer_core/slicer-engine-qa/bin/slicer-engine.exe`（QA harness ON） |
| Trigger | `BUNDLE_QA_CRASH_MODE=exception`＋`--help` |
| Mechanism | `noexcept` lambda 內 `throw ForcedException` → `std::terminate`／abort |
| Exit | `-1073740791`（`0xC0000409` FAST_FAIL／abort） |

## Surfaces scanned

| 表面 | `Slic3r::` demangle？ | 備註 |
|------|----------------------|------|
| stdout | **無**（空檔） | |
| stderr | **無**（空檔） | 非 libstdc++「terminating with uncaught exception of type …」風格 |
| WER `Report.wer` | **無** | App=`slicer-engine.exe`／Friendly=`Slicer Engine`；Fault=`ucrtbase.dll`；Exception=`c0000409`；**無** `ForcedException`／`Slic3r`／`Prusa` 型別名欄位 |
| minidump（CrashDumps） | demangle `Slic3r::` **count=0** | 有 MSVC RTTI **mangled** 字串（見下） |

## Minidump RTTI（非 demangle 訊息）

dump 內可見 MSVC typeinfo 形如：

```text
.?AUForcedException@BundleQa@Slic3r@@
.?AVRuntimeError@Slic3r@@
.?AVException@Slic3r@@
```

這是 **PDB-free 行程記憶體／模組內嵌 RTTI**，不是 WER／對話框印出的 `Slic3r::ForcedException`。  
L2 黑名單對「可讀崩潰報告」的關注點是 WER／stack 文字；本輪 **WER 零命中**。完整 `strings` 清 RTTI 屬 L3／不做範圍。

## Artifacts

| 路徑 | 說明 |
|------|------|
| `stdout/exception-*.txt` | meta／空 stdout／stderr |
| `wer/ReportArchive_exception/Report.wer` | 本輪 WER |
| `dumps/slicer-engine.exe.4368.dmp` | 本機 minidump（約 2MB；**建議勿 commit**） |
| `scan-rtti-tokens.json` | 自動掃描計數 |

## Implication for 5.1b top-level catch

在目前 **Win QA exception→abort** 路徑下，**沒有**觀測到「abort／WER 印出 `Slic3r::` 型別名」→ **Windows 不強制**加 CLI top-level catch。

對照（既有 mac PoC，非本輪）：`poc/evidence/m1-close-…/ips/exception.log` 有  

`libc++abi: terminating due to uncaught exception of type Slic3r::qa::BundleQaForcedException`  

→ **macOS `.ips`／abort 文字會洩漏 demangle 型別名**；若要關 5.1b，優先在 **mac** 做 catch／等效，而非 Win。

## Related

- tasks **5.1b**（Win 表面本證據＝暫不需 catch；mac 仍見 PoC 洩漏）
- 7.3 QA three-crash；PoC `w25-close`／`m1-close`
- design D3 RTTI／例外

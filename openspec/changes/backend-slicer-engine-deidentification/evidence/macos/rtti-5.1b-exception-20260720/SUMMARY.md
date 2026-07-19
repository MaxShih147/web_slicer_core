# macOS 5.1b — RTTI／例外型別名（exception abort／.ips）2026-07-20

**Verdict：** **PASS** — abort 文字與乾淨符號環境下的 `.ips` **無** demangle 型別名 `Slic3r::…`。  
**Fix：** CLI 入口安裝中性 `std::set_terminate`＋`try/catch`（`PrusaSlicer.cpp`）→ 印 `slicer-engine: fatal error` 後 `abort()`，不再走 libc++abi 預設 demangle 訊息。

## Setup

| 項 | 值 |
|----|-----|
| Binary（packaged QA） | `third_party/slicer-engine-qa/bin/slicer-engine` |
| `engine_build_id` | `slicer-engine-qa-2026-07-19T205206Z` |
| Trigger | `BUNDLE_QA_CRASH_MODE=exception`＋`--help` |
| Mechanism | `noexcept` throw `ForcedException` → `std::terminate` → **neutral terminate** → `abort` |
| Exit | `134`（SIGABRT） |

## Baseline（fix前，同日）

| 表面 | 結果 |
|------|------|
| stderr | `libc++abi: terminating due to uncaught exception of type Slic3r::BundleQa::ForcedException: …` |
| `Slic3r::` in stderr | **1** |

Artifacts：`baseline/`

## After fix

### Abort／stdio（`after/`）

| 表面 | `Slic3r::` 型別名？ | 備註 |
|------|-------------------|------|
| stdout | **無**（空） | |
| stderr | **無** | 僅 `slicer-engine: fatal error` |
| libc++abi demangle line | **0** | |

### `.ips`（乾淨符號環境，`after-uuid-clean/`）

PoC 同款：hide dSYM＋**LC_UUID patch**（避免 CoreSymbolication 還原舊 dSYM）。

| 掃描 | 結果 |
|------|------|
| stderr `Slic3r::` | **0** |
| `.ips` `Slic3r::` | **0** |
| `.ips` type-name pats（`ForcedException`／`of type Slic3r::`） | **0** |
| `.ips` 檔 | `after-uuid-clean/ips/exception.ips` |

> **Note：** 若本機留有同 UUID dSYM／快取，`.ips` stack 可能仍出現 `Slic3r::BundleQa::maybe_force_crash` **函式名**（符號還原），那不是 abort 型別名洩漏。正式驗收以 UUID-clean 或無同 UUID dSYM 為準（見 `poc/run_m1_close.sh`）。

## Implication

- **mac 5.1b 可關：** 未捕捉例外路徑不再於 abort／`.ips` 印出 demangle 型別名。  
- Win 既有 probe（WER 無 demangle）仍成立；此修對 Win 入口亦套用同一 guards（對稱、無害）。

## Related

- tasks **5.1b**；design D3 RTTI／例外；REQ-DEID-006  
- Win 對照：`evidence/windows/rtti-5.1b-probe-20260720/`  
- 舊 PoC 洩漏：`poc/evidence/m1-close-…/ips/exception.log`

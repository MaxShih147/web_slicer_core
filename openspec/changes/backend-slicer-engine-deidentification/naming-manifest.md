# 跨平台命名表與 Artifact Manifest

**版本：** 1.3  
**Status：** `approved`（2026-07-17：四項 canonical＋衍生項＋佈局；與 artifact schema 一併簽核）  
**Change：** `backend-slicer-engine-deidentification`  
**適用：** REQ-DEID-004、REQ-DEID-005、REQ-DEID-006（C′）、REQ-DEID-015  
**交接 schema：** [`artifact-manifest.schema.md`](./artifact-manifest.schema.md)  
**命名原則：** 功能性／角色型描述命名（非行銷品牌、非假第三方、不含 `bundle`／`prusa`／`slic3r`）  
**L2 策略：** 精簡版 C′（可見性＋strip＋全部 thread＋Win export）；`slice::` namespace 僅 L3 選配

> **產品確認（2026-07-17）：** 下列四項 canonical 名稱已確認 OK，實作以此為準。  
> AGPL license／NOTICE／Corresponding Source **不在**本表去品牌範圍（見 REQ-DEID-011）。  
> **注意：** `slicer` ≠ `slic3r`；黑名單 token 為 `slic3r`（含數字 3），不得將已核准之 `slicer-*` 中性名判為命中。

---

## 0. 已確認 canonical（四項）

| 項目 | 定案 |
|------|------|
| 執行檔（macOS／Windows shim） | **`slicer-engine`**／**`slicer-engine.exe`** |
| Windows 核心 DLL | **`slicer_core.dll`** |
| Windows 公開 export | **`slicer_run_cli`** |
| 安裝包內目錄（取代 `prusaslicer_build`） | **`slicer-engine/`** |

> 開發機建置目錄 `web_slicer_core/third_party/prusaslicer_build` 可不急於重命名；**正式包／Launcher 複製路徑**必須使用 `slicer-engine/`。

---

## 1. 命名原則（已採納）

1. 使用功能描述命名內部運算元件，不創造第二品牌名稱。
2. 不含 `bundle`／`Bundle`、`prusa`／`Prusa`、`slic3r`／`Slic3r` 及 `blacklist.md` 其他 token（**不含**已核准之 `slicer`）。
3. macOS CLI 為 headless Mach-O，**不是** `.app`：身分字串以「去品牌」為目標，**不要求**法人 reverse-DNS Bundle ID 體系。
4. `codeSigningID` 設為與執行檔名一致的自由字串即可；`CFBundleIdentifier` 以刪除或中性化 Info.plist 來源處理。
5. Windows 對應以 VERSIONINFO 與檔名／export 去品牌，無 Bundle ID 概念。
6. macOS **真實 Mach-O `OUTPUT_NAME`** 必須為中性名（不得僅改 symlink；現況真實檔為 `PrusaSlicer`）。

---

## 2. 跨平台 canonical 名稱

| 項目 | 現況（淘汰） | 定案 | 本版 |
|------|--------------|------|------|
| 內部模組名 | PrusaSlicer / slic3r | **slicer-engine** | L1 必要｜**已確認** |
| macOS CLI 執行檔（真實檔名） | `PrusaSlicer`（`prusa-slicer` 僅 symlink） | **`slicer-engine`**（CMake `OUTPUT_NAME`） | L1 必要｜**已確認** |
| Windows shim exe | `prusa-slicer.exe` | **`slicer-engine.exe`** | L1 必要｜**已確認** |
| Windows 核心 DLL | `PrusaSlicer.dll` | **`slicer_core.dll`** | L1＋C′ 必要｜**已確認** |
| 安裝／資源目錄（正式包） | `prusaslicer_build` | **`slicer-engine`** | L1 必要｜**已確認** |
| Thread 命名規則 | `slic3r_main`、`slic3r_tbb_*` 等 | **`slicer-worker`**（main）；worker：**`slicer-tbb-N`**（≤15 chars） | **C′ 必要（全部 call site）**｜衍生對齊 |
| Loader export（Win） | `slic3r_main` | **`slicer_run_cli`** | **C′ 必要**｜**已確認** |
| Agent env | `PRUSA_SLICER_BIN` | **`SLICER_ENGINE_BIN`** | L1 必要｜衍生對齊 |
| User-visible error | `PrusaSlicer failed…` | **`Slicing engine failed…`** | L1 必要 |
| CMake targets | Prusa／slic3r 相關 | **`slicer-engine`**、**`slicer_core`** | **實作 hygiene** |
| C++ 公開 namespace | `Slic3r::` | （選配）`slice::` | **L3；本版不做** |

### 2.1 macOS 身分字串（CLI，非 .app）

| 項目 | 現況 | 定案 |
|------|------|------|
| `codeSigningID` | `PrusaSlicer` | **`slicer-engine`**（`codesign --identifier slicer-engine`） |
| `Info.plist` / `CFBundleIdentifier` | `com.prusa3d.slic3r/` | **優先刪除**；若需要則 **`slicer-engine`**（不必 reverse-DNS） |
| Version 顯示字串 | `PrusaSlicer-…` | **`Slicer Engine <MAJOR.MINOR.PATCH>+<build_id>`** |

### 2.2 Windows VERSIONINFO

| 欄位 | 定案 |
|------|------|
| CompanyName | **法人正式名稱**（與 Authenticode 主體一致；不得為 Prusa Research） |
| ProductName | `Slicer Engine` |
| FileDescription | `Slicer Engine` |
| InternalName | `slicer-engine` |
| OriginalFilename | `slicer-engine.exe`／`slicer_core.dll` |
| ProductVersion／FileVersion | 與 internal build ID 對齊，不含品牌 token |

### 2.3 精簡版 C′（L2）建置約束

| 約束 | 現況（2026-07-17） | 目標 |
|------|-------------------|------|
| macOS 真實檔名 | `PrusaSlicer` + symlink | `OUTPUT_NAME=slicer-engine`；移除品牌 symlink |
| macOS strip | 未 strip | fork 於簽章前 strip（D13）；Launcher 只驗證 |
| 符號掃描 | 僅看 global 會漏 | local（`nm -U`）＋ global／export 分開掃 |
| macOS dSYM | 嵌在 binary | 先產 dSYM 封存，再 strip consumer |
| Windows PDB | GUI=OFF 時 linker `/DEBUG` 不保證；僅 `/XF *.pdb`（baseline 仍洩漏品牌 PDB path） | **已定案（2.3）：** `/Zi`＋`/DEBUG`＋`/PDB:`＋`/PDBALTPATH:` → 封存 → consumer 無 pdb／無品牌 debug path（見 [`windows-policy.md`](./windows-policy.md)） |
| Thread | `slic3r_main` + `slic3r_tbb_*` | 全部 call site 中性化（`slicer-worker`／`slicer-tbb-N`） |
| Export | `slic3r_main`＋~470 mangled（baseline） | **唯一** `slicer_run_cli`（政策）；**2.5 PoC：** 入口已更名，殘餘 ~470 → **5.3** |

> **本版不做：** 全面 `Slic3r::`→`slice::`、OLLVM。殘餘 `strings` 屬 L3。

---

## 3. In-scope consumer 佈局（Launcher `extraResources` 根）

### 3.1 macOS

```text
slicer-engine/bin/slicer-engine
```

不得保留：`prusaslicer_build/`、`prusa-slicer`、`PrusaSlicer`、品牌化 Info.plist、舊 symlink、建置殘渣（CMakeFiles、含 `prusaslicer_fork` 絕對路徑之 cmake 檔等）。**僅** runtime 必要檔＋法遵文件。

### 3.2 Windows

```text
slicer-engine/bin/slicer-engine.exe
slicer-engine/bin/slicer_core.dll
```

Shim **MUST** 僅載入 `slicer_core.dll`，公開 export **MUST** 為 `slicer_run_cli`。

### 3.3 明確排除（不在去品牌掃描通過條件內，但 MUST 隨包可取得）

- AGPL license／copyright／修改聲明
- Corresponding Source URL／written offer
- 內部-only dSYM／PDB（**不得**進 consumer bundle）

### 3.4 User-visible／loader 錯誤表面

| 表面 | 允許文案範例 | 禁止 |
|------|--------------|------|
| agent job error | `Slicing engine failed (exit N)` | 含 Prusa／slic3r |
| shim／DLL load failure | `Failed to load slicing engine module` | 舊 DLL 品牌名 |
| missing binary | `Slicing engine binary not found` | `PRUSA_SLICER_*` |

### 3.5 機器可驗交接

Launcher 輸入 **MUST** 附 [`artifact-manifest.schema.md`](./artifact-manifest.schema.md) 定義之 `engine-artifact-manifest.json`（含 flavor、pre／post_strip hash、symbol archive、files[]）。

---

## 4. 簽核欄

| 角色 | 姓名 | 日期 | 結果 |
|------|------|------|------|
| Product owner（Vance） | Vance | 2026-07-17 | ☑ **approved**（四項 canonical＋衍生 thread／env／VERSIONINFO／正式包佈局） |
| Backend owner | Vance | 2026-07-17 | ☑ **acknowledged** |
| Release Engineering | — | 2026-07-17 | ☑ **acknowledged**（含 artifact schema；與 schema 一併 approved） |
| Legal／OSS（僅確認 AGPL 揭露未受本表影響） | — | 2026-07-17 | ☑ **acknowledged**（命名不移除 license／NOTICE／Corresponding Source） |

**簽核完成：** `Status`＝`approved`；`tasks.md` 1.3／1.4 已勾選。若有 blacklist fixtures 於同一 PR 更新。

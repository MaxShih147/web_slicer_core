# 去識別化編譯與測試操作手冊（Build & Test Runbook）

> **Change ID：** `backend-slicer-engine-deidentification`
> **用途：** 把散落在 `README.md`、`design.md`（D1–D13）、`naming-manifest.md`、`acceptance-procedure.md`、`blacklist.md`、`tasks.md` 與 `scripts/*` 的操作，收斂成一份「照著打指令就能跑完」的實作手冊（含日常增量重編、crash 取證、7.6 smoke）。
> **語言慣例：** 本文為繁中說明；指令與程式碼註解為英文。
> **入口：** 產品總覽見 repo 根 [`README.md` De-identification notes](../../README.md#de-identification-notes)；本檔為操作細節。
> **規範來源（衝突時以下者為準）：** [`acceptance-procedure.md`](../../openspec/changes/backend-slicer-engine-deidentification/acceptance-procedure.md)、[`blacklist.md`](../../openspec/changes/backend-slicer-engine-deidentification/blacklist.md)、[`naming-manifest.md`](../../openspec/changes/backend-slicer-engine-deidentification/naming-manifest.md)、[`design.md`](../../openspec/changes/backend-slicer-engine-deidentification/design.md)。本手冊為操作彙整，**不新增規範**。

---

## 0. 讀這份文件前你必須先懂的 5 個觀念

| # | 觀念 | 一句話 |
|---|------|--------|
| 1 | **去識別化只作用在「消費者正式包」** | 開發／原始碼／submodule 保留 PrusaSlicer；只有**要出貨的簽署包**需要去品牌。切片行為與參數完全不變（`design.md` D12）。 |
| 2 | **`slicer` ≠ `slic3r`** | 黑名單 token 是 `slic3r`（含數字 3）。核准的中性名 `slicer-engine` / `slicer_core.dll` / `slicer_run_cli` **不是**命中。 |
| 3 | **編譯 ≠ 打包** | 純編譯只輸出 build tree binary（**不 strip、不封 PDB/dSYM**）。正式包要另跑 **package** 步驟（D13 流水線）。 |
| 4 | **兩種 flavor：`consumer` / `qa`** | `consumer`（預設）harness OFF；`qa` 以 **compile-time** `BUNDLE_QA_CRASH_HARNESS=ON` 編入三種故意 crash，只給動態驗收用（`design.md` D7）。consumer 內**不得**有 runtime 可觸發的 crash 路徑。 |
| 5 | **strip / sign 責任單一化（D13）** | fork（本 repo）負責 改名→link unstripped→產 dSYM/PDB 封存→consumer strip→產 manifest（pre/post hash）。Bundle-Launcher **只**複製 post-strip 產物→驗證→簽章，**不得**再 rename / strip / patch。 |

### 名稱與路徑對照（canonical，`naming-manifest.md` §0）

| 項目 | macOS | Windows |
|------|-------|---------|
| 執行檔 | `slicer-engine` | `slicer-engine.exe`（shim） |
| 核心 DLL | —（單一 Mach-O） | `slicer_core.dll` |
| 公開 export | —（`-Wl,-exported_symbol,_main`） | 唯一 `slicer_run_cli` |
| build tree 產物 | `third_party/prusaslicer_build/src/slicer-engine` | `third_party\prusaslicer_build\src\Release\slicer-engine.exe` |
| 正式包目錄 | `third_party/slicer-engine/bin/` | `slicer-engine\bin\` |
| Agent 環境變數 | `SLICER_ENGINE_BIN`（`PRUSA_SLICER_BIN` 僅本機 legacy fallback） | 同左 |

### 角色速讀（先選路徑）

| 角色 | 建議閱讀順序 | 目標 |
|------|-------------|------|
| **開發** | §0 → §1 **A→I** → **§2.4／§2.5** → §3.1／§4.1 → §9／§10 | 改碼、本機跑 agent、快速煙測 |
| **除錯／符號** | §0 → §3.3／§4.3（symbols 在哪）→ **§6.2 符號還原** → §6.1／§7 → §10／§12 | crash 還原函式名、flavor 汙染排查 |
| **SQA／驗收** | §0 → §1 **E→H** → §5 → **§6／§6.1** → **§8／§8.1** → §9 | scan 閘、三 crash、功能最小矩陣（驗收環境**勿**掛私有 dSYM／PDB） |
| **Release／包版** | §0 → §1 **C＋掃描＋合規**（C/D/E/G）→ §3.3／§4.3 → §5 → §7 → §11／§12 | D13 正式包、manifest、合規 |

**反模式（不要做）：**
- 不要把 `prusaslicer_build/`（未 strip）當正式安裝／驗收證據。
- 不要在簽署後再 strip／rename／patch。
- 不要用 `PRUSA_SLICER_BIN` 當出貨預設（僅本機 legacy）。
- 不要在 consumer 建置上沿用 qa 的 CMake cache（切 flavor 必 clean）。

---

## 1. 情境速查表（先看這張，再往下找章節）

| # | 我要做什麼 | 平台 | 一行指令（詳見章節） | 產物 / 驗證 |
|---|-----------|------|----------------------|-------------|
| A | 一般開發編譯（consumer，不 strip） | mac | `./scripts/build_prusaslicer_fork_macos.sh` | build tree binary（§3.1） |
| A | 一般開發編譯（consumer） | win | `scripts\build_prusaslicer_fork_windows.bat` | build tree exe+dll（§4.1） |
| A′ | 改碼後增量重編（不重跑 deps） | 雙 | §2.4（`cmake --build`／package-only） | 更新 build tree／可再 package |
| B | QA flavor 編譯（含三種 crash） | mac | `SLICER_ENGINE_FLAVOR=qa ./scripts/build_prusaslicer_fork_macos.sh` | qa build tree binary（§3.2） |
| B | QA flavor 編譯 | win | `scripts\build_prusaslicer_fork_windows.bat low qa` | qa build tree exe+dll（§4.2） |
| C | 產正式 consumer 包（strip+sign+manifest+scan） | mac | `PACKAGE_SLICER_ENGINE=1 ./scripts/build_prusaslicer_fork_macos.sh` | `third_party/slicer-engine/`（§3.3） |
| C | 產正式 consumer staging | win | `scripts\build_prusaslicer_fork_windows.bat low package`（或先 build 再 `package_…_windows.ps1`） | `slicer-engine\`（§4.3） |
| D | 產 QA 包 | mac | `SLICER_ENGINE_FLAVOR=qa PACKAGE_SLICER_ENGINE=1 ./scripts/build_prusaslicer_fork_macos.sh` | `third_party/slicer-engine-qa/`（§3.3） |
| D | 產 QA staging | win | `scripts\build_prusaslicer_fork_windows.bat qa package`（自動 `-OutRoot slicer-engine-qa`）或手動 `package_… -Flavor qa -OutRoot …\slicer-engine-qa` | `slicer-engine-qa\`（§4.3） |
| E | 只跑掃描閘（fail-closed） | mac | `./scripts/scan_slicer_engine_macos.sh` | `scan-report.json`（§5） |
| E | 只跑掃描閘 | win | `powershell -File scripts\scan_slicer_engine_windows.ps1` | `scan-report.json`（§5） |
| F | 三種 crash 動態驗證 | mac | `BUNDLE_QA_CRASH_MODE=overflow <qa-bin>`（§6） | `.ips`（§6） |
| F | 三種 crash 動態驗證 | win | `set BUNDLE_QA_CRASH_MODE=overflow` + 執行（§6） | WER / minidump（§6） |
| F′ | 日常用 dSYM／PDB 還原函式名 | 雙 | §6.2（`lldb`／`atos`／`cdb`） | 內部除錯（非驗收） |
| G | subprocess/SBOM/symbolication 合規 | mac | `./scripts/run_macos_compliance_5_11_6_x.sh` | evidence（§7） |
| G | symbolication drill / subprocess | win | `drill_symbolication_windows_6_6_6_7.ps1` / `verify_subprocess_boundary_windows.ps1`（§7） | evidence |
| H | 功能回歸（7.6 矩陣） | 雙 | 見 §8 | 對照 tolerance |
| I | 跑 agent 驗 CLI 路徑 | mac/win | `./scripts/run_agent.sh` / `scripts\run_agent.bat`（§9） | `https://127.0.0.1:5179` |

---

## 2. 前置準備（一次性）

### 2.1 共同

```bash
# Fetch the PrusaSlicer fork source (required after a fresh clone)
git submodule update --init --recursive
```

- **CMake：** 必須 **3.27.9**（3.28+ 與 PrusaSlicer 有相容問題）。
  - macOS：`cmake-3.27.9.app/` 放在 repo 根；否則腳本報錯並給下載連結。
  - Windows：`cmake-3.27.9-windows-x86_64\`，或確保 `cmake` 在 PATH。
- 相依（deps）第一次會 build 30–60 分鐘，之後有標記檔就會跳過。

### 2.2 macOS

- Xcode command-line tools（`xcrun --show-sdk-path` 要有效）。
- 腳本會自動 pin 目前 SDK；Xcode 更新後若 cache SDK 失效會自動 reconfigure。

### 2.3 Windows

- Visual Studio 2017/2019/2022/2026（腳本用 `vswhere` 自動選 generator）。
- 記憶體模式：16GB → 用預設 `low`；32GB+ → 用 `full`（見 §4.1）。
- `manifold3d`（agent 端）建議用 Python 3.11/3.12（有 wheel）；否則需 vcpkg 裝 TBB（見 `README.md` Windows setup）。

### 2.4 日常增量重編（改完 fork 原始碼後）

第一次或 clean 後用 §3／§4 全量腳本；**之後改 C++ 只重編，不要每次重跑 deps**。

**macOS**

```bash
# Prefer the repo-pinned CMake 3.27 if present
CMAKE_BIN="$(pwd)/cmake-3.27.9.app/Contents/bin/cmake"
cd third_party/prusaslicer_build
"$CMAKE_BIN" --build . --parallel "$(sysctl -n hw.ncpu)"
# equivalent if Makefile generator: make -j"$(sysctl -n hw.ncpu)"
# binary: third_party/prusaslicer_build/src/slicer-engine
```

若只需重新 package（binary 已在 build tree、且本次**未**改 flavor／visibility／OUTPUT_NAME）：

```bash
./scripts/package_slicer_engine_macos.sh
# or QA:
SLICER_ENGINE_FLAVOR=qa ./scripts/package_slicer_engine_macos.sh
```

**Windows**

```bat
cd third_party\prusaslicer_build
cmake --build . --config Release --target PrusaSlicer_app_console -- /m:1
cmake --build . --config Release --target OCCTWrapper -- /m:1
:: binaries: …\src\Release\slicer-engine.exe + slicer_core.dll + OCCTWrapper.dll
```

或再跑一次建置腳本（會沿用既有 cache；改 flavor／export／VERSIONINFO／icon 時仍用 `clean`）：

```bat
scripts\build_prusaslicer_fork_windows.bat low
:: optional D13 staging after build:
scripts\build_prusaslicer_fork_windows.bat low package
```

> 碰到 `OUTPUT_NAME`、visibility、`BUNDLE_QA_CRASH_HARNESS`、`.def`、VERSIONINFO／`version.inc`、**`SLIC3R_APP_ICON`／`slicer-engine.ico`** → **必須 clean**（mac：`rm -rf third_party/prusaslicer_build`；Win：`…bat low clean`），不可只靠增量。
> Windows 只建 `PrusaSlicer_app_console` **不會**帶出 `OCCTWrapper`（獨立 MODULE）；官方 bat 會在 console 之後明確 `--target OCCTWrapper`。手動增量時兩 target 都要建。

### 2.5 Agent／TLS（跑本機後端）

```bash
# macOS: trust local TLS once if browser／curl rejects the cert
./scripts/trust_dev_tls_macos.sh
export SLICER_ENGINE_BIN="$(pwd)/third_party/prusaslicer_build/src/slicer-engine"
./scripts/run_agent.sh
```

```bat
:: Windows
powershell -File scripts\trust_dev_tls_windows.ps1
set SLICER_ENGINE_BIN=%CD%\third_party\prusaslicer_build\src\Release\slicer-engine.exe
scripts\run_agent.bat
```

cert／key 解析順序（與 `run_agent.sh`／`agent/config.py` 一致）：

1. 環境變數 `AGENT_TLS_CERTFILE`／`AGENT_TLS_KEYFILE`
2. `agent/tls/localhost.crt`＋`agent/tls/localhost.key`
3. `../Bundle-Launcher/bundle-mac/agent/tls/` 或 `bundle-win/agent/tls/`（若並列 checkout）

**cert 找不到時：**
- 從 Bundle-Launcher 複製 `localhost.crt`／`localhost.key` 到 `agent/tls/`，或設上述環境變數。
- 瀏覽器仍不信任：先跑 `trust_dev_tls_macos.sh`／`trust_dev_tls_windows.ps1`（把開發憑證加入系統信任）。
- curl 測試：`curl -vk https://127.0.0.1:5179/`（`-k` 可略過驗證做煙測）。

詳見 `README.md` Development。

---

## 3. macOS 編譯與打包

主腳本：[`scripts/build_prusaslicer_fork_macos.sh`](../../scripts/build_prusaslicer_fork_macos.sh)
打包腳本：[`scripts/package_slicer_engine_macos.sh`](../../scripts/package_slicer_engine_macos.sh)

### 3.1 情境 A — 一般開發編譯（consumer，不 strip）

```bash
./scripts/build_prusaslicer_fork_macos.sh
```

- 預設 `SLICER_ENGINE_BUILD_TYPE=RelWithDebInfo`（讓 `dsymutil` 之後能封 DWARF）、`FLAVOR=consumer`（harness OFF）。
- CMake 關鍵旗標（腳本自動帶）：`-DSLIC3R_GUI=OFF -DSLIC3R_BUILD_TESTS=OFF -DBUNDLE_QA_CRASH_HARNESS=OFF`。
- 產物：`third_party/prusaslicer_build/src/slicer-engine`（**未 strip**、含符號）。
- 腳本會自動刪掉舊品牌名殘檔（`PrusaSlicer` / `prusa-slicer` 等）。
- **此步不會 strip、不封 dSYM、不簽章、不掃描** —— 那是打包步驟（§3.3）。

用它跑 agent：

```bash
export SLICER_ENGINE_BIN="$(pwd)/third_party/prusaslicer_build/src/slicer-engine"
./scripts/run_agent.sh
```

#### 3.1.1 直接對 build tree binary 下 CLI（開發煙測）

不必經過 agent，可直接對 `third_party/prusaslicer_build/src/slicer-engine` 下指令，最快驗證「編出來的引擎能跑、且沒有品牌字串」。以下指令皆已實測可用（產物與 exit code 標於註解）。

```bash
BIN="$(pwd)/third_party/prusaslicer_build/src/slicer-engine"
INI="$(pwd)/third_party/prusaslicer_fork/tests/data/default_fff.ini"
STL="$(pwd)/third_party/prusaslicer_fork/tests/data/test_stl/ASCII/20mmbox-LF.stl"
OUT=/tmp/deid-clitest && mkdir -p "$OUT"

# 1) 版本 / 說明 —— 確認 binary 可執行且品牌已中性化
"$BIN" --help | head -1
#  → Slicer Engine 1.0.5 (without GUI support)   （不應出現 Prusa / Slic3r 字樣）

# 品牌快掃：命中數應為 0
"$BIN" --help 2>&1 | grep -Eic 'prusa|slic3r'
#  → 0

# 2) 實際切一顆 FDM（--load FFF ini + --export-gcode），確認能產出 .gcode
"$BIN" --load "$INI" --export-gcode -o "$OUT/box.gcode" "$STL"
#  → Exporting G-code / Slicing result exported to .../box.gcode
#  → exit 0，產出 ~600 KB .gcode（含 ;LAYER_CHANGE、;TYPE:Perimeter 等）

# 3) 等價短寫（-g 同 --export-gcode / --gcode）
"$BIN" --load "$INI" -g -o "$OUT/box2.gcode" "$STL"
#  → exit 0，產出 .gcode

# 4) 錯誤路徑驗證：輸入不存在時應回非 0
"$BIN" --load "$INI" --export-gcode -o "$OUT/none.gcode" "$OUT/__nope__.stl"; echo "exit=$?"
#  → exit=1
```

> 說明：FDM 煙測須 `--load` 一份 FFF 設定（repo 內建 `tests/data/default_fff.ini`）；`--export-gcode`／`-g` 才會輸出 G-code。正式功能回歸（量測 size ±5% / perf ×1.20）見 §8。

### 3.2 情境 B — QA flavor 編譯

```bash
SLICER_ENGINE_FLAVOR=qa ./scripts/build_prusaslicer_fork_macos.sh
# 相容寫法： ./scripts/build_prusaslicer_fork_macos.sh qa
```

- 帶 `-DBUNDLE_QA_CRASH_HARNESS=ON`，把三種 crash site 以 `#ifdef` 編入（`bundle_qa_crash_probe.cpp`，由 CLI 入口 `PrusaSlicer.cpp` 呼叫 `maybe_force_crash()`）。
- 觸發方式見 §6（`BUNDLE_QA_CRASH_MODE`）。

> ⚠️ **切換 flavor 一定要 clean。** consumer↔qa 切換屬「會改變是否編入 harness」的變更，殘留 cache 會把 harness 帶進 consumer。macOS 沒有 `clean` 參數，直接刪 build tree：
> ```bash
> rm -rf third_party/prusaslicer_build
> ```

### 3.3 情境 C/D — D13 正式打包（strip → sign → manifest → scan）

打包是 **opt-in**：在編譯指令前加 `PACKAGE_SLICER_ENGINE=1`；若 binary 已建好，也可直接跑 `package_slicer_engine_macos.sh`（見 §2.4）。

```bash
# Consumer package (build + package)
PACKAGE_SLICER_ENGINE=1 ./scripts/build_prusaslicer_fork_macos.sh

# QA package (paired to last consumer build id if present)
SLICER_ENGINE_FLAVOR=qa PACKAGE_SLICER_ENGINE=1 ./scripts/build_prusaslicer_fork_macos.sh

# Package only (binary already built)
./scripts/package_slicer_engine_macos.sh
```

`package_slicer_engine_macos.sh` 依 D13 依序做（**這就是「去識別化」真正發生的地方**）：

1. 複製 build binary 到 `bin/slicer-engine`，同時留一份 `*.unstripped` 到 symbols 區。
2. `dsymutil` 產 `slicer-engine.dSYM` → **移到 symbols 區封存**（`third_party/slicer-engine-symbols/`），**不進 consumer 包**。
3. 記 `pre_strip_sha256` 與 `LC_UUID`。
4. `strip`（plain strip；**否決 `strip -x`**，PoC 2.2 定案）。
5. `codesign --force --sign - --identifier slicer-engine`（ad-hoc；正式簽章由 Launcher 用 Developer ID 重簽）。記 `post_strip_sha256`。
6. 寫 `engine-artifact-manifest.json`（flavor、pre/post hash、dSYM UUID/hash、`qa_delta`、SBOM 佔位、`nm` brand 計數）。
7. Stage 去品牌 Resources + AGPL 法遵包（`legal/`）。
8. **內建 fail-closed 檢查**：dSYM 不得洩漏進包、路徑不得含 `prusa`/`slic3r`。
9. 呼叫 `scan_slicer_engine_macos.sh`（§5）做正式掃描閘。

輸出：
- consumer → `third_party/slicer-engine/`（`bin/slicer-engine`、`engine-artifact-manifest.json`、`legal/`、`scan-report.json`）
- qa → `third_party/slicer-engine-qa/`
- 符號 → `third_party/slicer-engine-symbols/`（`.dSYM` + `.unstripped`；**私有 symbol store，不出貨**）

可調環境變數：`SLICER_ENGINE_ARTIFACT_DIR`、`SLICER_ENGINE_SYMBOLS_DIR`、`SLICER_ENGINE_CONSUMER_EQUIVALENT_BUILD_ID`（qa 配對）、`SKIP_SLICER_ENGINE_SCAN=1`（僅除錯用，會跳過閘門）、`SKIP_SLICER_ENGINE_AGPL=1`。

---

## 4. Windows 編譯與打包

主腳本：[`scripts/build_prusaslicer_fork_windows.bat`](../../scripts/build_prusaslicer_fork_windows.bat)
打包腳本：[`scripts/package_slicer_engine_windows.ps1`](../../scripts/package_slicer_engine_windows.ps1)

### 4.1 情境 A — 一般開發編譯（consumer）

```bat
:: low = 16GB RAM (default) / full = 32GB+ RAM
scripts\build_prusaslicer_fork_windows.bat
scripts\build_prusaslicer_fork_windows.bat full
```

- 位置引數：`[full|low|qa] [clean|qa|package] [qa|package] [package]`。
- **Package 預設 OFF。** 編譯後要接續 D13 staging：傳 `package`，或設 `PACKAGE_SLICER_ENGINE=1`（與 macOS 同名環境變數）。
- CMake 關鍵旗標：`-DSLIC3R_GUI=OFF -DSLIC3R_BUILD_TESTS=OFF -DBUNDLE_QA_CRASH_HARNESS=OFF`，記憶體模式決定 `SLIC3R_MSVC_COMPILE_PARALLEL` 與 MSBuild `/m`。
- 產物：`third_party\prusaslicer_build\src\Release\` 下：
  - `slicer-engine.exe` + `slicer_core.dll`
  - **`OCCTWrapper.dll`**（STEP/STP；bat 在 console 之後明確 `--target OCCTWrapper`）
  - 自動複製 `libgmp-10.dll`、`libmpfr-4.dll`
- 編譯 target：`PrusaSlicer_app_console`（內部仍叫 PrusaSlicer 屬正常，`OUTPUT_NAME` 已中性）+ **`OCCTWrapper`**。
- PE icon：link 時由 `SLIC3R_APP_ICON`（`resources/icons/slicer-engine.ico`）寫入 RC；改 icon 需 clean 重編 console。

#### 4.1.1 直接對 build tree binary 下 CLI（開發煙測）

Windows 的引擎與 macOS 同一份 codebase、同一組 CLI 旗標。`slicer-engine.exe` 依賴同目錄的 `slicer_core.dll`、`OCCTWrapper.dll`、`libgmp-10.dll`、`libmpfr-4.dll`，因此**直接在 `Release\` 目錄內執行**（或把該目錄加入 `PATH`）最穩：

```powershell
$Bin = "$PWD\third_party\prusaslicer_build\src\Release\slicer-engine.exe"
$Ini = "$PWD\third_party\prusaslicer_fork\tests\data\default_fff.ini"
$Stl = "$PWD\third_party\prusaslicer_fork\tests\data\test_stl\ASCII\20mmbox-LF.stl"
$Out = "$env:TEMP\deid-clitest"; New-Item -ItemType Directory -Force -Path $Out | Out-Null

# 1) 版本 / 說明 —— 確認可執行且品牌已中性化
& $Bin --help | Select-Object -First 1
#  → Slicer Engine 1.0.5 (without GUI support)

# 品牌快掃：命中數應為 0
(& $Bin --help 2>&1 | Select-String -Pattern 'prusa|slic3r' -AllMatches).Matches.Count
#  → 0

# 2) 實際切一顆 FDM（--load FFF ini + --export-gcode），確認能產出 .gcode
& $Bin --load $Ini --export-gcode -o "$Out\box.gcode" $Stl
#  → Exporting G-code / Slicing result exported（exit 0，產出 .gcode）

# 3) 等價短寫（-g）
& $Bin --load $Ini -g -o "$Out\box2.gcode" $Stl
#  → exit 0，產出 .gcode

# 4) 錯誤路徑驗證：輸入不存在時 $LASTEXITCODE 應為非 0
& $Bin --load $Ini --export-gcode -o "$Out\none.gcode" "$Out\__nope__.stl"; "exit=$LASTEXITCODE"
#  → exit=1
```

> cmd.exe 版：`set BIN=third_party\prusaslicer_build\src\Release\slicer-engine.exe` 後 `%BIN% --help`；離開 `Release\` 目錄執行需確保上述 DLL 在 `PATH` 或同目錄，否則會缺 DLL 無法啟動。

### 4.2 情境 B — QA flavor 編譯

```bat
scripts\build_prusaslicer_fork_windows.bat low qa
:: 或
scripts\build_prusaslicer_fork_windows.bat qa
```

- 帶 `-DBUNDLE_QA_CRASH_HARNESS=ON`。腳本會比對 cache 內 `BUNDLE_QA_CRASH_HARNESS:BOOL` 是否一致，不一致自動 reconfigure。

### 4.3 情境 C/D — consumer / qa staging（D13）

先編譯再打包（兩種等效路徑）：

```bat
:: A) One-shot：build + package（package 預設 OFF，需明確開啟）
scripts\build_prusaslicer_fork_windows.bat low package
scripts\build_prusaslicer_fork_windows.bat qa package
::    qa package 會自動 -OutRoot …\slicer-engine-qa（不會蓋掉 consumer）

:: B) 分開跑
scripts\build_prusaslicer_fork_windows.bat low
powershell -File scripts\package_slicer_engine_windows.ps1

scripts\build_prusaslicer_fork_windows.bat qa
powershell -File scripts\package_slicer_engine_windows.ps1 `
  -Flavor qa `
  -OutRoot "%CD%\slicer-engine-qa" `
  -ConsumerEquivalentBuildId <consumer_build_id>
```

> ⚠️ **Win QA 踩雷（手動 package）：** `-Flavor qa` **不會**自動換目錄；預設 `-OutRoot` 與 consumer 相同（`slicer-engine\`）。手動打包務必 `-OutRoot …\slicer-engine-qa`。用 bat 的 `qa package` 則已自動分開目錄。掃描時也要對同一目錄：
> ```powershell
> $env:SLICER_ENGINE_EXPECT_FLAVOR='qa'
> powershell -File scripts\scan_slicer_engine_windows.ps1 -ArtifactRoot "$PWD\slicer-engine-qa"
> ```

`package_slicer_engine_windows.ps1` 做：

1. **若 `OutRoot` 已存在 → 整棵刪除再重建**（非原地覆蓋；避免舊殘檔）。
2. 複製 `slicer-engine.exe` + `slicer_core.dll` + `OCCTWrapper.dll`（.step/.stp 需要）+ GMP/MPFR 到 `…\bin\`，**排除 `*.pdb` 與品牌殘檔**。
3. Stage 去品牌 resources（`stage_slicer_engine_resources_windows.ps1`）。
4. 把中性 PDB（`slicer-engine.pdb` / `slicer_core.pdb`）封存到 `symbols\`（不進 bin）。
5. Stage AGPL 法遵包（`legal\`：LICENSE / NOTICE.md / SOURCE_OFFER.md）。
6. **PE icon 閘（fail-closed）：** `ExtractAssociatedIcon` hash 必須等於 fork SoT `resources/icons/slicer-engine.ico`（link 時已嵌；**預設不再跑 rcedit**）。急救：`SLICER_ENGINE_ALLOW_RCEDIT_ICON=1` 才允許 rcedit 後再驗一次。
7. **Export 閘**：`dumpbin /EXPORTS` 必須 **恰好 1 個** named export = `slicer_run_cli`，且不得出現 `slic3r_main`/品牌 token。
8. consumer flavor：靜態稽核 DLL 不得含 harness marker。
9. 寫 `engine-artifact-manifest.json`（+ `artifact-manifest.json` alias）、build ID sidecar、SPDX 2.3 SBOM + source-chain。
10. 呼叫 `scan_slicer_engine_windows.ps1`（§5）fail-closed。

輸出：`slicer-engine\` 或 `slicer-engine-qa\`（`bin\`、`symbols\`、`legal\`、`engine-artifact-manifest.json`、`EXPORTS.txt`、`scan-report.json`、`sbom`）。

> ⚠️ **clean rebuild 時機（Windows 有 `clean` 參數）：** 碰到 `OUTPUT_NAME`、visibility、`BUNDLE_QA_CRASH_HARNESS`、`.def` export、VERSIONINFO/`version.inc`、**PE icon / `slicer-engine.ico`** 任一改動，一律 clean 重編避免 stale cache：
> ```bat
> scripts\build_prusaslicer_fork_windows.bat low clean
> ```
> 另 LNK2001/LNK1136（0-byte obj）也用 clean 重試。Explorer 清單小圖可能因 Shell icon cache 仍顯示舊圖；以預覽窗格／`PE icon gate OK` 為準。

---

## 5. 掃描閘（L1/L2 靜態驗收，fail-closed）

打包腳本會自動呼叫；也可單獨對任一 artifact root 執行。掃描規則來自 [`blacklist.md`](../../openspec/changes/backend-slicer-engine-deidentification/blacklist.md)（token substring、NFC、casefold）。

### macOS — `scan_slicer_engine_macos.sh`（tasks 5.4/5.6/5.7）

```bash
./scripts/scan_slicer_engine_macos.sh                                  # 預設掃 third_party/slicer-engine
SLICER_ENGINE_EXPECT_FLAVOR=qa ./scripts/scan_slicer_engine_macos.sh third_party/slicer-engine-qa
```

檢查項：layout/可執行；consumer 樹**無** `.dSYM`/`.pdb`/`.unstripped`；路徑無 `prusa`/`slic3r`；manifest flavor 相符且磁碟 sha256 == `post_strip_sha256`（Developer ID 重簽後用 `SLICER_ENGINE_SKIP_HASH=1` 改記 `post_sign`）；`codesign` Identifier == `slicer-engine`；**`nm -gU` 與 `nm -U` 品牌命中都必須 = 0**（local+global 分開掃）；consumer 無 harness marker（qa 反之必須有）。輸出 `scan-report.json`，`verdict: PASS/FAIL`。

### Windows — `scan_slicer_engine_windows.ps1`（tasks 5.3/5.4/5.7）

```powershell
powershell -File scripts\scan_slicer_engine_windows.ps1
$env:SLICER_ENGINE_EXPECT_FLAVOR='qa'; powershell -File scripts\scan_slicer_engine_windows.ps1 D:\path\to\slicer-engine
```

檢查項：layout；`bin\` 無 `*.pdb`；路徑（含 `bin\resources`）無品牌 token；AGPL `legal\` 齊備（consumer 必要）；manifest flavor/platform、exe+dll 磁碟 sha256 == manifest；VERSIONINFO 六欄去品牌；**`dumpbin` named export == 1 (`slicer_run_cli`)**、PE debug directory 無品牌 PDB 路徑；consumer 無 harness marker。**Authenticode 不在本閘要求**（Windows 簽章手動、由 Launcher 之外處理）。輸出 `scan-report.json`。

> 對照掃描（deny-list 不完整性補強）：`blacklist.md` §2.1 要求除 token 掃描外，另做「與已知乾淨參考報告的正向 diff / 人工複核」。乾淨參考見 [`clean-reference-report.md`](../../openspec/changes/backend-slicer-engine-deidentification/clean-reference-report.md)。中性模組名 + offset（如 `slicer-engine + 0x…`）**不得**判 FAIL。

---

## 6. 三種 crash 動態驗證（qa flavor 專用）

必須用 **qa** 包（release-equivalent，`acceptance-procedure.md` §1.2）。三種 site 都要過（`acceptance-procedure.md` §4.3.7）：

| mode | 觸發 | 主要驗證 |
|------|------|----------|
| `overflow` | 無限遞迴 → stack overflow | thread name、模組名 + offset |
| `segfault` | null-deref (SIGSEGV) | 一般堆疊符號 |
| `exception` | `noexcept` 內拋 C++ 例外 → `std::terminate`/abort | RTTI/typeinfo demangle 型別名（最會洩 `Slic3r::`） |

觸發由環境變數 `BUNDLE_QA_CRASH_MODE` 控制（在 CLI 入口 `maybe_force_crash()` 讀取）：

**macOS**
```bash
QABIN="$(pwd)/third_party/slicer-engine-qa/bin/slicer-engine"
BUNDLE_QA_CRASH_MODE=overflow  "$QABIN" --help   # then collect .ips (below)
BUNDLE_QA_CRASH_MODE=segfault  "$QABIN" --help
BUNDLE_QA_CRASH_MODE=exception "$QABIN" --help
```

**Windows**（先設 LocalDumps，再觸發；QA staging 用 `slicer-engine-qa\bin\`）
```powershell
$exe = "$PWD\slicer-engine-qa\bin\slicer-engine.exe"
$dumpDir = "$PWD\qa-dumps"
New-Item -ItemType Directory -Force -Path $dumpDir | Out-Null
$ld = "HKCU:\Software\Microsoft\Windows\Windows Error Reporting\LocalDumps\slicer-engine.exe"
New-Item -Path $ld -Force | Out-Null
New-ItemProperty -Path $ld -Name DumpFolder -Value $dumpDir -PropertyType ExpandString -Force | Out-Null
New-ItemProperty -Path $ld -Name DumpType -Value 2 -PropertyType DWord -Force | Out-Null

foreach ($mode in @("overflow","segfault","exception")) {
  $env:BUNDLE_QA_CRASH_MODE = $mode
  $p = Start-Process -FilePath $exe -ArgumentList "--help" -WorkingDirectory (Split-Path $exe) -PassThru -Wait -NoNewWindow
  "mode=$mode exit=$($p.ExitCode) pid=$($p.Id)" | Tee-Object -FilePath qa-crash-log.txt -Append
}
Remove-Item Env:BUNDLE_QA_CRASH_MODE -ErrorAction SilentlyContinue
```

### 6.1 Crash 取證最小手順（SQA／除錯）

驗收要點（`acceptance-procedure.md` §1.9 / §4.3）：**乾淨環境**（無私有 dSYM／PDB／`_NT_SYMBOL_PATH`）；以 **pid＋時間** 對那一次崩潰，不可只抓「最新檔」。

**macOS — 找 `.ips` 並掃品牌**

```bash
# 1) Note start time / PID around the crash, then list recent reports
ls -lt ~/Library/Logs/DiagnosticReports/slicer-engine*.ips 2>/dev/null | head
# also check: /Library/Logs/DiagnosticReports/

# 2) Pick the report that matches PID / timestamp, then scan blacklist tokens
IPS=~/Library/Logs/DiagnosticReports/slicer-engine_<pick>.ips
grep -Ei 'prusa|slic3r|PrusaSlicer|com\.prusa3d' "$IPS" && echo "FAIL brand hit" || echo "token scan ok"

# 3) Spot-check key fields (must be neutral)
plutil -p "$IPS" 2>/dev/null | head -80   # or open in Console.app
# expect: procName/path ~ slicer-engine; codeSigningID=slicer-engine;
# thread names ~ slicer-worker / slicer-tbb-*; frames may be "slicer-engine + 0x…" (OK)
```

**Windows — 找 dump／WER 並掃品牌**

```powershell
# LocalDumps folder from above, or WER archive
Get-ChildItem "$PWD\qa-dumps\*.dmp" | Sort-Object LastWriteTime -Descending | Select-Object -First 5
Get-ChildItem "C:\ProgramData\Microsoft\Windows\WER\ReportArchive" -Directory |
  Where-Object { $_.Name -match 'slicer-engine' } | Sort-Object LastWriteTime -Descending | Select-Object -First 3

# Scan Report.wer / stdout for brand tokens (PDB-free surface)
Select-String -Path qa-crash-log.txt -Pattern 'prusa|slic3r|PrusaSlicer' -ErrorAction SilentlyContinue
Get-ChildItem "C:\ProgramData\Microsoft\Windows\WER\ReportArchive" -Recurse -Filter Report.wer -ErrorAction SilentlyContinue |
  Select-Object -First 5 | ForEach-Object {
    Select-String -Path $_.FullName -Pattern 'prusa|slic3r|PrusaSlicer' -ErrorAction SilentlyContinue
  }
```

可選：有 Debugging Tools 時用 `cdb` 看 **PDB-free** 堆疊（驗收用；模組名應為 `slicer-engine`／`slicer_core`，不應出現 `PrusaSlicer`）：

```bat
cdb -z qa-dumps\<dump>.dmp -c "lm m slicer*; k; q"
```

> 要把 `slicer-engine + 0x…` **還原成函式名**（內部除錯）→ 見 **§6.2**（掛 dSYM／PDB）。驗收環境**禁止**這樣做，以免假失敗／假通過。

**PASS 判準（三種 mode 皆要）：**
- 行程／模組名、路徑、VERSIONINFO／`codeSigningID`、thread name、可讀 stack／例外訊息 → **零**未豁免品牌命中。
- 中性 `slicer-engine + 0x…`／`slicer_core.dll` **不得**因此 FAIL（`slicer` ≠ `slic3r`）。
- **consumer 反向驗證**：對 consumer binary 設 `BUNDLE_QA_CRASH_MODE=overflow` 再執行 → **不得**故意崩潰（harness 未編入）。

> consumer 絕不可含 runtime 可啟動的故意 crash（`design.md` D7；舊 `BUNDLE_FORCE_PRUSA_STACK_OVERFLOW` runtime 版**禁止**進任何簽署 release）。  
> 完整證據範例：mac [`poc/evidence/m1-close-…`](../../openspec/changes/backend-slicer-engine-deidentification/poc/evidence/m1-close-20260717T032408Z/)；Win [`poc/evidence/w25-close-…`](../../openspec/changes/backend-slicer-engine-deidentification/poc/evidence/w25-close-20260717T083241Z/)。

### 6.2 日常符號還原（dSYM／PDB + `lldb`／`atos`／`cdb`）

**用途：** 正式包已 strip，OS 報告只剩 `slicer-engine + 0xoffset`。內部用 **同 build** 的封存符號把 offset 還原成函式名。  
**範圍：** 僅內部除錯／事故分析。**不得**在 L2 動態驗收機掛私有 symbol store（見 §6.1 乾淨環境）。

| | macOS | Windows |
|--|-------|---------|
| 符號位置 | `third_party/slicer-engine-symbols/slicer-engine.dSYM`（+ `.unstripped`） | `slicer-engine\symbols\slicer-engine.pdb`、`slicer_core.pdb` |
| 對齊鍵 | Mach-O **UUID**（`dwarfdump --uuid`） | PE **RSDS GUID+Age**（須與 PDB 一致） |
| 工具 | `atos`、`lldb` | `cdb`（Debugging Tools for Windows） |

#### macOS — 先確認 UUID，再用 `atos`／`lldb`

```bash
BIN=third_party/slicer-engine/bin/slicer-engine
DSYM=third_party/slicer-engine-symbols/slicer-engine.dSYM
DWARF="$DSYM/Contents/Resources/DWARF/slicer-engine"

# 1) UUID must match (wrong build_id → wrong symbols → garbage names)
dwarfdump --uuid "$BIN"
dwarfdump --uuid "$DSYM"
# also check engine-artifact-manifest.json → symbol_archive.uuid_or_guid

# 2) From .ips usedImages[]: note slicer-engine base address (= load address)
#    Frame often looks like: slicer-engine + 0x123456
#    Absolute PC ≈ load_address + offset  (or use the absolute address column if present)

# 3) atos — resolve one or more addresses
atos -o "$DWARF" -l <load_address> <pc_or_absolute_addr> [<more_addrs>…]
# example smoke (self-check archive; also run by verify_symbol_archive_macos.sh):
LOAD_HEX=$(nm -gU "$BIN" | awk '/ _main$/{print $1; exit}')
atos -o "$DWARF" -l "0x$LOAD_HEX" "0x$LOAD_HEX"

# 4) lldb — load stripped binary + matching dSYM, then backtrace / resolve
lldb "$BIN"
# (lldb) target modules add "$BIN"
# (lldb) add-dsym "$DSYM"
# (lldb) image list   # confirm UUID / path
# If you have a .ips-derived crash PC:
# (lldb) image lookup --address 0x<pc>
# Or attach to a live QA crash (internal only):
# (lldb) process attach --pid <pid>
# (lldb) bt
```

一鍵核對封存是否可用：

```bash
./scripts/verify_symbol_archive_macos.sh
# or: ./scripts/verify_symbol_archive_macos.sh third_party/slicer-engine third_party/slicer-engine-symbols
```

#### Windows — 掛本地 PDB 再用 `cdb` 還原

```bat
:: 1) PDB next to dump session (do NOT copy PDB into consumer bin/)
set SYM=C:\path\to\web_slicer_core\slicer-engine\symbols
set DUMP=C:\path\to\qa-dumps\slicer-engine.exe.1234.dmp

:: 2) Symbolicate with local PDBs only (internal debug)
cdb -z %DUMP% -y %SYM% -c ".reload /f; lm m slicer*; k; q"

:: Optional: also point _NT_SYMBOL_PATH for a longer session
:: set _NT_SYMBOL_PATH=%SYM%
:: cdb -z %DUMP% -c ".sympath; .reload /f; kn; q"
```

對齊檢查（GUID 必須對得上該 `engine_build_id`；可用 drill 腳本）：

```powershell
powershell -File scripts\drill_symbolication_windows_6_6_6_7.ps1
# proves PE RSDS GUID matches archived PDB; wrong build_id → fail closed
```

**常見失敗：**
- UUID／GUID 對不上 → 拿了別次 package 的 symbols（對 `engine_build_id`／manifest）。
- 驗收機設了 `_NT_SYMBOL_PATH`／Spotlight 掃到 dSYM → 堆疊「太乾淨」或出現 demangle 品牌名 → **假失敗**；驗收請清空私有符號路徑。
- Win 把 `.pdb` 拷進 `bin\` → scan 閘 FAIL（consumer 不得含 PDB）。

---

## 7. 供應鏈 / symbol / subprocess 合規

### macOS 一鍵（tasks 5.11 + 6.4/6.5 + 6.6/6.7）

```bash
./scripts/run_macos_compliance_5_11_6_x.sh
# 或指定 artifact/symbols 根：
./scripts/run_macos_compliance_5_11_6_x.sh third_party/slicer-engine third_party/slicer-engine-symbols
```

產出到 `evidence/macos/`：
- **5.11 subprocess boundary**：以 `asyncio.create_subprocess_exec` 起引擎，證明 engine PID ≠ agent PID、`--help` 無 `PrusaSlicer`、job 崩潰語意正確（維持 AGPL subprocess 邊界，`design.md` D4）。
- **6.4/6.5**：`sbom.spdx.json`（SPDX-2.3）+ `source-chain.json`，建立 binary SHA-256 ↔ `engine_build_id` ↔ `engine_commit`，並確認 `legal/SOURCE-OFFER.md`。
- **6.6/6.7**：`verify_symbol_archive_macos.sh` 驗 consumer 無 dSYM、Mach-O UUID == dSYM UUID == manifest；建 symbol-store mirror；演練「缺 build_id → 查不到」與 rollback。

### Windows 對應腳本

```powershell
powershell -File scripts\verify_subprocess_boundary_windows.ps1      # 5.11
powershell -File scripts\drill_symbolication_windows_6_6_6_7.ps1     # 6.6/6.7 symbolication/rollback
powershell -File scripts\generate_slicer_engine_sbom_windows.ps1     # 6.4 SBOM（打包時已自動跑）
powershell -File scripts\write_engine_build_id_windows.ps1           # 6.5 build id sidecar
```

symbol store：Windows 採 OneDrive 手動封存（PDB GUID+Age 必須對得上該 build）。

---

## 8. 功能回歸（切片行為不得改變，D12 / task 7.6）

門檻（[`functional-budget-2.7-approved-20260719.md`](../../openspec/changes/backend-slicer-engine-deidentification/evidence/functional-budget-2.7-approved-20260719.md)，已 approved）：
- 輸出**非** bit-identical，但大小 **±5%** 內。
- 效能 ≤ 基線 × **1.20**（warm ≤ cold × 1.20）。
- **7.6 最小矩陣 MUST**；`acceptance-procedure.md` §6 延伸項為 SHOULD。

最小矩陣涵蓋（雙平台）：`--help`／`--help-fff`、missing STL、`--export-sla` cold／warm、agent 路徑煙測；延伸 SHOULD：supports／hollow／cut／3MF、timeout／cancel、install→slice→uninstall。

### 8.1 可複製 smoke（本機正式包／staging）

Fixture（repo 內）：`openspec/changes/backend-slicer-engine-deidentification/evidence/windows/functional-7.6-20260719T143000Z/fixture/model.stl`  
（亦可自備小型 SLA STL；成功判準是 exit 0 + 產出 `.sl1` + help 無品牌字串。）

**macOS**

```bash
ROOT="$(pwd)"
ENG="${SLICER_ENGINE_BIN:-$ROOT/third_party/slicer-engine/bin/slicer-engine}"
STL="$ROOT/openspec/changes/backend-slicer-engine-deidentification/evidence/windows/functional-7.6-20260719T143000Z/fixture/model.stl"
OUT="$ROOT/tmp-deid-smoke"; mkdir -p "$OUT"

# 1a/1b help — brand must be 0
"$ENG" --help | tee "$OUT/help.txt" | grep -Ei 'prusa|slic3r' && echo "FAIL help brand" || echo "PASS help"
"$ENG" --help-fff >/dev/null

# 2 missing STL — expect non-zero
"$ENG" --export-sla -o "$OUT/missing.sl1" "$OUT/__no_such__.stl"; test $? -ne 0 && echo "PASS missing" || echo "FAIL missing"

# 3 export-sla cold / warm — size within ±5%; warm ≤ cold×1.20
/usr/bin/time -p "$ENG" --export-sla -o "$OUT/out-cold.sl1" "$STL" 2>"$OUT/cold.time"
/usr/bin/time -p "$ENG" --export-sla -o "$OUT/out-warm.sl1" "$STL" 2>"$OUT/warm.time"
python3 - <<'PY'
import pathlib
cold, warm = pathlib.Path("tmp-deid-smoke/out-cold.sl1"), pathlib.Path("tmp-deid-smoke/out-warm.sl1")
assert cold.is_file() and warm.is_file(), "missing sl1"
cs, ws = cold.stat().st_size, warm.stat().st_size
lo, hi = cs * 0.95, cs * 1.05
print(f"sizes cold={cs} warm={ws} band=[{lo:.0f},{hi:.0f}]")
assert lo <= ws <= hi, "size ±5% FAIL"
print("PASS size ±5%")
PY
```

**Windows**

```powershell
$Root = $PWD
$Eng = if ($env:SLICER_ENGINE_BIN) { $env:SLICER_ENGINE_BIN } else { "$Root\slicer-engine\bin\slicer-engine.exe" }
$Stl = "$Root\openspec\changes\backend-slicer-engine-deidentification\evidence\windows\functional-7.6-20260719T143000Z\fixture\model.stl"
$Out = "$Root\tmp-deid-smoke"; New-Item -ItemType Directory -Force -Path $Out | Out-Null

& $Eng --help 2>&1 | Tee-Object "$Out\help.txt" | Out-Null
if (Select-String -Path "$Out\help.txt" -Pattern 'prusa|slic3r' -Quiet) { "FAIL help brand" } else { "PASS help" }

& $Eng --export-sla -o "$Out\missing.sl1" "$Out\__no_such__.stl"; if ($LASTEXITCODE -ne 0) { "PASS missing" } else { "FAIL missing" }

$sw = [Diagnostics.Stopwatch]::StartNew()
& $Eng --export-sla -o "$Out\out-cold.sl1" $Stl; $coldSec = $sw.Elapsed.TotalSeconds; $sw.Restart()
& $Eng --export-sla -o "$Out\out-warm.sl1" $Stl; $warmSec = $sw.Elapsed.TotalSeconds
$cs = (Get-Item "$Out\out-cold.sl1").Length; $ws = (Get-Item "$Out\out-warm.sl1").Length
"sizes cold=$cs warm=$ws; time cold=${coldSec}s warm=${warmSec}s"
if ($ws -lt $cs*0.95 -or $ws -gt $cs*1.05) { "FAIL size ±5%" } else { "PASS size ±5%" }
if ($warmSec -gt $coldSec*1.20) { "FAIL perf ×1.20" } else { "PASS perf ×1.20" }
```

CLI 參數與 PrusaSlicer 完全相同（`--export-sla` / `--export-support-stl` / `--export-hollow-stl` 等）；只有執行檔名改了。  
正式雙平台證據：[`evidence/macos/functional-7.6-…`](../../openspec/changes/backend-slicer-engine-deidentification/evidence/macos/functional-7.6-20260719/SUMMARY.md)、[`evidence/windows/functional-7.6-…`](../../openspec/changes/backend-slicer-engine-deidentification/evidence/windows/functional-7.6-20260719T143000Z/SUMMARY.md)。

---

## 9. 驗收前自我檢查（雙平台，交件前跑一次）

```bash
# 1) --help 不得印出 PrusaSlicer / slic3r（中性名 slicer-engine 可以）
"$SLICER_ENGINE_BIN" --help | grep -Ei 'prusa|slic3r' && echo "FAIL" || echo "ok"

# 2) 正式包無品牌檔名；Win 無 .pdb、mac 無 .dSYM
#    → 直接看 scan-report.json 的 verdict

# 3) manifest hash 與磁碟一致（scan 會驗）
```

**PASS 條件（`blacklist.md` §5）：** 所有必掃表面零「未豁免」命中 **且** §2.1 品牌歸因正向複核通過 **且** AGPL 文件齊備；任一平台未過即整體 FAIL。

**consumer 正式包必須不含：** `.pdb`(Win) / `.dSYM`・`*.unstripped`(mac) / QA harness / `prusa-slicer*`・`PrusaSlicer.dll` 等品牌殘檔。
**必須隨包附上（不算品牌命中）：** AGPL LICENSE / NOTICE / 修改聲明 / Corresponding Source offer（`legal/`）。

---

## 10. 疑難排解

| 症狀 | 平台 | 處理 |
|------|------|------|
| CMake 3.27 找不到 | 雙 | 下載 3.27.9 放到 repo 指定路徑；勿用 3.28+ |
| SDK 路徑失效（Xcode 更新後） | mac | 腳本會自動 reconfigure；仍失敗則 `rm -rf third_party/prusaslicer_build` 重編 |
| `LNK2001` / `LNK1136`（0-byte obj） | win | `build_..._windows.bat low clean` 重編 |
| Export 閘 FAIL（≠1 或含 `slic3r_main`） | win | clean 重編（`.def`/`OUTPUT_NAME` 改動需 clean）；確認 `slicer_core` 只導出 `slicer_run_cli` |
| consumer 掃到 harness marker | 雙 | flavor 汙染：consumer 一定要 clean 後重編（不可沿用 qa cache） |
| `nm` brand ≠ 0 | mac | 確認有經 `package` 的 strip 步驟；不可拿 build tree 未 strip binary 當正式包 |
| dSYM/PDB 洩漏進包 | 雙 | 走 package 腳本（會 fail-closed）；不要手動 cp 整個 build tree |
| 磁碟 sha256 ≠ manifest（Developer ID 重簽後） | mac | 正常；掃描設 `SLICER_ENGINE_SKIP_HASH=1` 改記 post-sign hash |
| `LoadLibrary` error 126 | win | `slicer_core.dll` 旁缺 `libgmp-10.dll`/`libmpfr-4.dll`/`OCCTWrapper.dll`；bat 會編 OCCT＋copy GMP/MPFR，打包腳本也會帶；手動跑要補齊 |
| PE icon gate FAIL | win | 確認 SoT `resources/icons/slicer-engine.ico` 存在且 clean 重編過 console；勿只改 package／rcedit。Explorer 清單舊圖≠PE 錯（Shell cache） |
| agent 找不到 CLI | 雙 | 設 `SLICER_ENGINE_BIN` 指向 build tree 或正式包 binary |
| Win QA 蓋掉 consumer staging | win | 用 bat `qa package`，或手動 `-OutRoot …\slicer-engine-qa`（見 §4.3） |
| TLS／cert 找不到 | 雙 | 跑 `trust_dev_tls_*`；或準備 `agent/tls/localhost.crt|key`（§2.5） |
| crash 報告抓錯檔 | 雙 | 用 pid＋時間對應；勿只取最新 `.ips`／`.dmp`（§6.1） |
| atos／cdb 還原出亂名或失敗 | 雙 | UUID／GUID 與 `engine_build_id` 不一致；換對次 symbols（§6.2） |
| 驗收堆疊出現 `Slic3r::` 但正式包應已 strip | 雙 | 測試機掛了私有 dSYM／PDB／`_NT_SYMBOL_PATH`；清空後重測（§6.1） |

---

## 11. 對照表（tasks / REQ / 產物）

| 操作 | tasks | 主要 REQ | 腳本 |
|------|-------|----------|------|
| L1 改名/身分（mac） | 3.1/3.2 | REQ-DEID-004/005 | `build_prusaslicer_fork_macos.sh` |
| L1 改名/身分（win） | 3.3 | REQ-DEID-005/006 | `build_prusaslicer_fork_windows.bat` |
| C′ strip/thread/export（mac） | 5.1/5.2/5.1b | REQ-DEID-006 | `package_slicer_engine_macos.sh` |
| C′ export/PDB（win） | 5.3 | REQ-DEID-006 | `package_slicer_engine_windows.ps1` |
| 掃描閘 | 5.4/5.6/5.7 | REQ-DEID-006/009/013 | `scan_slicer_engine_*` |
| 三種 crash | 2.4/2.5/7.3 | REQ-DEID-006/009 | qa 包 + `BUNDLE_QA_CRASH_MODE` |
| subprocess 邊界 | 5.11 | REQ-DEID-008 | `run_macos_compliance_*` / `verify_subprocess_boundary_windows.ps1` |
| AGPL/SBOM/來源鏈 | 6.1–6.7 | REQ-DEID-011/012 | `generate_slicer_engine_sbom_windows.ps1` / compliance script |
| symbol store/rollback | 5.5/6.6/6.7 | REQ-DEID-012 | `verify_symbol_archive_macos.sh` / `drill_symbolication_windows_6_6_6_7.ps1` |
| 功能回歸 | 3.6/7.6 | REQ-DEID-014 | 手動矩陣（門檻 2.7） |
| 最終簽署 artifact 驗收 | 7.1/7.2/7.4/7.5 | REQ-DEID-010/013 | Bundle-Launcher CI gate |

---

## 12. Helper 腳本一覽（去識別化相關）

打包腳本會自動呼叫多數 helper；單獨重跑時用下表。路徑皆相對 repo 根。

| 腳本 | 平台 | 用途 |
|------|------|------|
| `scripts/build_prusaslicer_fork_macos.sh` | mac | 編譯（可選 `PACKAGE_SLICER_ENGINE=1`） |
| `scripts/build_prusaslicer_fork_windows.bat` | win | 編譯 `console`+`OCCTWrapper`（`low`／`full`／`qa`／`clean`；可選 `package` 或 `PACKAGE_SLICER_ENGINE=1`，**預設 OFF**） |
| `scripts/package_slicer_engine_macos.sh` | mac | D13 package：dSYM→strip→codesign→manifest→scan |
| `scripts/package_slicer_engine_windows.ps1` | win | D13 staging：整樹刪再建、copy PE（含 OCCT）、封 PDB、PE icon 閘、export 閘、scan |
| `scripts/stage_slicer_engine_resources_macos.sh` | mac | 去品牌 Resources 進 artifact（package 自動呼叫） |
| `scripts/stage_slicer_engine_resources_windows.ps1` | win | 去品牌 `bin\resources`（package 自動呼叫） |
| `scripts/stage_slicer_engine_agpl_macos.sh` | mac | AGPL `legal/` 進 artifact（package 自動呼叫） |
| `scripts/scan_slicer_engine_macos.sh` | mac | 正式掃描閘 fail-closed |
| `scripts/scan_slicer_engine_windows.ps1` | win | 正式掃描閘 fail-closed |
| `scripts/verify_symbol_archive_macos.sh` | mac | UUID 對齊＋`atos` smoke（§6.2／§7） |
| `scripts/drill_symbolication_windows_6_6_6_7.ps1` | win | PDB GUID 對齊／loss／rollback drill |
| `scripts/verify_subprocess_boundary_windows.ps1` | win | subprocess 邊界（5.11） |
| `scripts/run_macos_compliance_5_11_6_x.sh` | mac | 5.11＋6.4–6.7 一鍵 |
| `scripts/generate_slicer_engine_sbom_windows.ps1` | win | SPDX SBOM（package 自動呼叫） |
| `scripts/write_engine_build_id_windows.ps1` | win | `engine_build_id.txt` sidecar |
| `scripts/run_agent.sh`／`run_agent.bat` | 雙 | 啟動 agent（讀 `SLICER_ENGINE_BIN`） |
| `scripts/trust_dev_tls_macos.sh`／`trust_dev_tls_windows.ps1` | 雙 | 信任本機 HTTPS 開發憑證（§2.5） |

**非去識別化（勿混用）：** `scripts/check_baseline.py` 是 surgical-guide auto-orient 回歸，**與本 change 無關**。`package_slicer_engine_macos_original.sh`／`_stub_backup.sh` 為備份／舊路徑，日常請用 `package_slicer_engine_macos.sh`。

---

**維護：** 若 `naming-manifest.md`、`blacklist.md`、`acceptance-procedure.md` 或任一 `scripts/*` 改動，請同步本手冊並在對應 PR 更新 [`FILE-INDEX.md`](../../openspec/changes/backend-slicer-engine-deidentification/FILE-INDEX.md)。本手冊不覆蓋規範；衝突以規範性附件為準。

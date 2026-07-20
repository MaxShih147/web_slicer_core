# Windows C′／PDB／ABI Policy — tasks 2.3

**Status：** `decided`（2026-07-17）  
**Change：** `backend-slicer-engine-deidentification`  
**依據：** [`naming-manifest.md`](./naming-manifest.md)（approved）、[`design.md`](./design.md) D3／D10／D13、[`artifact-manifest.schema.md`](./artifact-manifest.schema.md)、baseline [`evidence/windows/baseline/BASELINE.md`](./evidence/windows/baseline/BASELINE.md)  
**適用：** REQ-DEID-006／012；解鎖 tasks **2.5**／**5.3**／§3 Windows 實作  
**PoC：** tasks **2.5 PASS** — [`poc/REPORT-WIN.md`](./poc/REPORT-WIN.md)／`poc/evidence/w25-close-20260717T083241Z/`

> 本文件為 **政策定案**（對齊 macOS tasks 2.2）。程式改名／PoC 證據見 2.5；export 收斂為恰好 1 仍歸 **5.3**。

---

## 0. 一句話

Windows consumer 引擎：**單一 shim** `slicer-engine.exe` 只載入 **`slicer_core.dll`**，只解析 **`slicer_run_cli`**；headless 建置**必須**產 PDB→封存→consumer **無 `.pdb`**，且 PE debug directory **不得**含品牌／建置樹路徑（baseline 已證明現況會洩漏 `prusaslicer_build\...\prusa-slicer-console.pdb`）。

---

## 1. DLL／shim ABI 契約（定案）

### 1.1 檔名與佈局（正式包）

```text
slicer-engine/bin/slicer-engine.exe    # shim（取代 prusa-slicer.exe／prusa-slicer-console.exe）
slicer-engine/bin/slicer_core.dll      # 核心（取代 PrusaSlicer.dll）
slicer-engine/bin/OCCTWrapper.dll      # STEP/STP 延遲載入外掛（必帶）
slicer-engine/bin/libgmp-10.dll        # runtime
slicer-engine/bin/libmpfr-4.dll        # runtime
slicer-engine/bin/resources/           # Windows：exe 同目錄 resources（Setup.cpp 硬編；MUST 保留資料夾）
```

| 角色 | 淘汰 | 定案 |
|------|------|------|
| Shim exe | `prusa-slicer.exe`、`prusa-slicer-console.exe` | **`slicer-engine.exe`**（正式包只保留一個 headless shim） |
| Core DLL | `PrusaSlicer.dll` | **`slicer_core.dll`** |
| STEP 外掛 | （無） | **`OCCTWrapper.dll`**（與 exe 同目錄；讀 `.step`／`.stp` 時 `LoadLibrary`；正式包 **MUST** 附帶） |
| Resources | 品牌路徑名（prusa／slic3r） | **`bin/resources/`** MUST 存在（`parent_path()/resources`）；內容經去品牌 stage；SLA 雖以 `--load` INI 為主，**不得**未驗證即整夾刪除（精簡＝另案） |
| 公開 entry | `slic3r_main`／`_slic3r_main@8` | **`slicer_run_cli`**（唯一允許之 GetProcAddress 名） |
| 目錄 | `prusaslicer_build/...` | **`slicer-engine/`**（Launcher `extraResources`） |

**正式包 MUST NOT** 再附 `prusa-gcodeviewer.exe` 作為引擎驗收路徑（若產品仍需 viewer，另開非本 change 範圍；本 change 引擎邊界以 shim＋DLL 為準）。

### 1.2 載入契約（對齊現況 `PrusaSlicer_app_msvc.cpp`）

| 步驟 | 定案行為 | 禁止 |
|------|----------|------|
| DLL 搜尋 | shim **同目錄** `LoadLibraryExW(L"slicer_core.dll", …)`（或等效絕對路徑＝exe 目錄） | 載入 `PrusaSlicer.dll`；依賴 `PATH` 偶然命中舊 DLL |
| Entry | `GetProcAddress(..., "slicer_run_cli")` | 查詢 `slic3r_main`／decorated `_slic3r_main@8`（consumer） |
| 呼叫慣例 | 與現況 `slic3r_main(int argc, wchar_t** argv)` **保持二進位相容簽名**；僅**更名** export（PoC／實作不得擅自改 argc／編碼語意） | 靜默改簽名導致 agent 行為漂移 |
| Loader／printf 錯誤 | 中性文案（見 naming-manifest §3.4），例：`Failed to load slicing engine module`／`could not locate slicer_run_cli` | 字串含 `PrusaSlicer.dll`、`slic3r_main`（baseline：`PrusaSlicer.dll was not loaded`） |

### 1.3 原子遷移順序（實作／2.5 MUST）

同一變更集（或明確標為不可分割之 PR 序列）內完成，**禁止**半套上線：

1. CMake／`.def`：DLL OUTPUT_NAME＝`slicer_core`；export＝`slicer_run_cli`  
2. Shim：檔名、LoadLibrary、GetProcAddress、錯誤字串  
3. Agent／Launcher：路徑改 `slicer-engine/bin/slicer-engine.exe`；env `SLICER_ENGINE_BIN`  
4. VERSIONINFO（exe＋**DLL**；baseline DLL 目前為空，正式 MUST 填中性欄位）  
5. Smoke：`--help`／最小 CLI slice；缺 DLL／缺 export 錯誤為中性文案  

**Rollback：** 整組回退；不得留下「新 shim＋舊 DLL 名」或「新 DLL＋舊 `slic3r_main`」組合進 consumer。

### 1.4 Agent／Launcher 契約

| 項目 | 定案 |
|------|------|
| 預設 CLI 路徑 | `.../slicer-engine/bin/slicer-engine.exe` |
| Env | `SLICER_ENGINE_BIN`（舊 `PRUSA_SLICER_BIN` **不得**寫入 consumer 預設） |
| Manifest files[] | 列 `slicer-engine.exe`、`slicer_core.dll`（及 runtime 依賴 DLL，若有）之 post_strip hash |

---

## 2. 公開 export 政策（定案）

### 2.1 目標狀態（L2）

| 規則 | 定案 |
|------|------|
| Consumer `slicer_core.dll` 公開 export | **僅** `slicer_run_cli`（`dumpbin /exports` 可驗證） |
| Baseline 現況 | **470** named exports；含 `slic3r_main`＋大量 `Slic3r` mangled（見 1.7） |
| 手段（結果導向） | MSVC：**module `.def`**（`EXPORTS slicer_run_cli`）為首選；或等效「僅標註該 entry 為 dllexport、其餘不進 export table」。**不得**只改名 `slic3r_main` 而留下其餘 `Slic3r::*` mangled exports |
| 靜態閘門 | CI／scanner：export table 命中 `slic3r`／`Slic3r`／`Prusa`／`prusa` → **FAIL**；且 named export 數 **MUST** 為 1（或經 Security 簽核之豁免清單，預設無豁免） |

### 2.2 非目標（本版不做）

- 全面 `Slic3r::`→`slice::` namespace（L3）  
- 以 OLLVM／packer 隱藏 export  
- 以「字串歸零」取代 export 收斂  

---

## 3. PDB 產→封存→consumer 排除（定案）

### 3.1 原則（對齊 D10／D13）

```text
link（含 debug） 
  → 產出 program PDB（可控路徑／中性檔名）
  → 上傳 symbol store（GUID+Age + build_id + PE hash）並寫 manifest
  → consumer PE：無品牌 PDB path；bundle 無 .pdb 檔
  → Launcher 只收 post_strip／PDB-excluded PE
```

**否決（baseline 已證偽）：**

| 錯誤假設 | 為何否決 |
|----------|----------|
| `SLIC3R_GUI=OFF` 就一定有完整 PDB | 不保證；MUST 顯式開 `/DEBUG`＋`/PDB:` |
| 組包時只 `/XF *.pdb` | 不足：PE **debug directory** 仍可嵌入品牌完整路徑（1.7：`...\prusaslicer_build\...\prusa-slicer-console.pdb`） |
| 不產 PDB、出事再重編 | 違反 D10（事故診斷能力） |

### 3.2 建置旗標（MSVC／headless Release — 定案）

對 **`slicer-engine.exe`** 與 **`slicer_core.dll`**（及同建置 ID 需 symbolicate 的引擎相關 PE）：

| 階段 | 旗標／動作 | 說明 |
|------|------------|------|
| Compile | `/Zi`（或專案等效 debug info） | 產生可連結進 PDB 的 debug info |
| Link | `/DEBUG` | 產生 program PDB（不得依賴預設「偶爾有 PDB」） |
| Link | `/PDB:<SYMBOL_STAGING>/<build_id>/slicer-engine.pdb`（exe）／`.../slicer_core.pdb`（dll） | 可控封存路徑；檔名**中性** |
| Link | `/PDBALTPATH:slicer-engine.pdb`／`/PDBALTPATH:slicer_core.pdb` | PE 內只寫**短檔名**，禁止嵌入 `prusaslicer_build`／絕對開發機路徑 |
| 封存後 | 上傳 staging PDB → 內部 symbol store；manifest 記錄 GUID+Age、pdb sha256、對應 PE `post_strip_sha256` | Owner＝fork |
| Consumer 包 | **零** `*.pdb`；路徑 walk FAIL 若出現 | Launcher／CI 雙重檢查 |
| 驗證 | `dumpbin /HEADERS` 之 RSDS／debug directory：**無** `prusa`／`slic3r`／`prusaslicer_build`；至多中性短檔名 | 對齊 blacklist §3.4 |

> **工具鏈註記：** 若某 MSVC 版本對 `/PDBALTPATH` 行為異常，允許改用「link 後以受控工具清除／改寫 debug directory 為中性短名」的等效手段，但 **MUST** 在 2.5 PoC evidence 記錄實際旗標與 `dumpbin` 前後對照；不得回退到「只刪檔不處理 directory」。

### 3.3 Manifest 語意（Windows）

依 [`artifact-manifest.schema.md`](./artifact-manifest.schema.md)：

| 欄位 | Windows 語意 |
|------|----------------|
| `pre_strip_sha256` | 連結完成、PDB 已產且**尚未**做 consumer 交付消毒前之主 PE（或文件化之等效點） |
| `post_strip_sha256` | 已套用 `/PDBALTPATH`（或等效）、確認可交付 consumer 之 PE hash（**無**側車 `.pdb`） |
| `flavor` | `consumer`｜`qa`（qa 唯一差異＝compile-time harness，見 D7） |

Launcher **MUST** 驗證 `post_strip_sha256` 與磁碟一致後才 Authenticode。

### 3.4 驗收環境

動態 WER／minidump：**不得**設定指向內部 symbol store 的 `_NT_SYMBOL_PATH`（避免「測試機比使用者更會符號化」）。Evidence 記錄 `clean_env_notes`（與 1.7／macOS PoC 一致）。

---

## 4. VERSIONINFO（Windows L1 — 與 ABI 一併定案）

對齊 naming-manifest §2.2；**exe 與 DLL 皆 MUST**（baseline DLL 為空 → 正式缺口）：

| 欄位 | 定案 |
|------|------|
| CompanyName | 法人正式名稱（＝Authenticode 主體；≠ Prusa Research） |
| ProductName／FileDescription | `Slicer Engine` |
| InternalName | `slicer-engine`／`slicer_core` |
| OriginalFilename | `slicer-engine.exe`／`slicer_core.dll` |
| ProductVersion／FileVersion | 含 build ID；**無** `PrusaSlicer`／`prusa`／`slic3r` token |

---

## 5. 與 2.5 PoC／正式落地的分界

| 項目 | 2.3（本文件） | 2.5 PoC | §3／§5 產品化 |
|------|---------------|---------|----------------|
| ABI／export／PDB／debug 政策文字 | **Done** | **Done**（見 REPORT-WIN） | **5.3／package／scan 已關（2026-07-17～19）** |
| 三種 crash＋WER | — | **Done**（compile-time harness；cdb dump） | 正式 qa／§7 動態仍開 |
| Authenticode 最終包 | — | 可用未簽 PoC | **2026-07-19 手動 Setup Valid＋安裝後 scan PASS**（內嵌 app exe 仍可不簽） |
| Launcher 改路徑 | — | 可最小改 PoC | **Win gate＋lifecycle 已落地**；macOS bundle 待 |

**2.5 狀態（2026-07-17）：** **PASS**。  
**產品化／Launcher（2026-07-19 晚）：** 見 [`PROGRESS.md`](./PROGRESS.md)（5.3＋§4＋post-sign Setup；完成度 ≈83%）。

---

## 6. 驗收閘門（供 scanner／CI 引用）

Windows consumer（或 release-equivalent qa 之靜態面）**FAIL** 若任一成立：

1. 檔名／目錄含 `prusa`／`slic3r`／`PrusaSlicer`／`prusaslicer_build`  
2. VERSIONINFO 任一必掃欄含黑名單 token  
3. `dumpbin /exports` ≠ 單一 `slicer_run_cli`，或仍見 `slic3r_main`／`Slic3r`  
4. Bundle 內存在 `*.pdb`  
5. PE debug directory／RSDS 字串含品牌或建置樹路徑  
6. Shim 錯誤字串含舊 DLL／export 品牌名  

---

## 7. 決策紀錄

| ID | 決策 | 日期 |
|----|------|------|
| W-ABI-1 | 單一 shim＋`slicer_core.dll`＋唯一 export `slicer_run_cli` | 2026-07-17 |
| W-ABI-2 | 原子遷移；簽名語意不變只更名 | 2026-07-17 |
| W-EXP-1 | Consumer export 收斂為 1；否決「只改 slic3r_main」 | 2026-07-17 |
| W-PDB-1 | 顯式 `/DEBUG`＋`/PDB:`＋**`/PDBALTPATH:` 短中性名** | 2026-07-17 |
| W-PDB-2 | 否決「只 XF pdb」；先封存再交付 consumer PE | 2026-07-17 |
| W-VER-1 | DLL VERSIONINFO 不得再空；與 exe 同中性政策 | 2026-07-17 |

**批准角色（政策）：** Backend／Release Engineering（本 change 工程定案）。產品 canonical 名已於 naming-manifest approved；本文件不變更四項 canonical。

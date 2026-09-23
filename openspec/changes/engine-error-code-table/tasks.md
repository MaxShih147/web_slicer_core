## 0. 前置（不做完不要開始）

- [x] 0.1 確認 `merge-engine-result-classifiers` 已關單。**未解開 exit-code 相依就動 C++，`INVALID_MODEL` 與 `MODEL_OUT_OF_BOUNDS` 會退化成 `JOB_FAILED`。**
  - 指令：`pytest agent/tests/test_exit_code_independence.py -q`
  - 預期：全綠（兩例為 `xfail`）
  - **實際結果**：`14 passed, 2 xfailed`（用 `.venv312/Scripts/python.exe -m pytest`；系統 python 缺 numpy 跑不起來）。功能面已完成並已 commit（`fb11a26`），但 openspec 目錄**尚未 archive**——三份 backend change 都還在 `openspec/changes/` 底下，正式關單流程另外處理。
- [x] 0.2 記錄回歸基準。
  - 指令：`pytest agent/tests -q 2>&1 | tail -3`
  - **實際結果（基準）**：`2 failed, 1198 passed, 2 xfailed`。兩個失敗都是既有、與本單無關：
    - `test_prz_print_time.py::test_6_11_single_normal_layer_full_params`：列印時間算出 11.0，期待 14.0。
    - `test_subprocess_boundary_5_11.py::test_engine_runs_as_separate_process`：venv 缺 `pytest-asyncio`，async 測試跑不起來。
  - 過程中另外發現：starlette 1.3.1 的 `TestClient` 需要 `httpx2`，`requirements.txt` 沒列、venv 也沒裝，導致 5 個測試檔在收集階段就 error。已在本機 venv 補裝 `httpx2`，**`requirements.txt` 未修改**（依賴清單變更留給 owner 決定）。
- [x] 0.3 記錄目前 shipped 引擎資訊，交付時要比對。
  - 指令：`cat ../Bundle-Launcher/bundle-win/slicer-engine/engine_build_id.txt; git submodule status third_party/prusaslicer_fork`
  - 預期：記下 build id 與目前指標 commit
  - **實際結果**：
    - `engine_build_id.txt` = `20260724T131327Z`
    - submodule 指標 = `2e10c16d4fc289711831bb0e4bd1183d5a6d0279`（`v1.0.4-rc1-38-g2e10c16d4`）
    - **既有落差**：`source-chain.json` 記錄的 `engine_commit` = `8c94d9bdc5d7a5f516087b19c62cac6174600694`，跟 submodule 指標對不起來。目前 shipped 的供應鏈紀錄本身就已經跟指標不一致——第 7.4 節交付時三方對帳會一併校正。

## 1. 建置環境（兩顆地雷）

- [x] 1.1 **fork 切到分支 tip。** 依作業方式：過程中**不理會** superproject 記錄的指標，直接在 tip 上工作。
  - 指令：`cd third_party/prusaslicer_fork && git fetch origin && git checkout <branch> && git pull && git rev-parse HEAD`
  - 預期：記下這個 commit hash。**第 7 節要用它做一致性驗證。**
  - **實際結果**：分支選 `feature/manual-support-click-mode`（與 superproject 目前工作分支同名；`git merge-base --is-ancestor` 確認原本 pin 的 `2e10c16d4` 是這條分支 tip 的祖先，所以是嚴格延續而非另一條線）。
  - **tip commit = `4c697465de368bab2850295ddc7f9886a14c4bbb`**（`fix(sla): do not throw away supports that never reached the plate`）← 第 7.4 節要對這個。
- [x] 1.2 **CMake 套件登錄檔汙染防護。** 本機有三個 PrusaSlicer 系專案共用登錄檔，會互相汙染依賴路徑，症狀難查。設定階段 MUST 加旗標。
  - 指令：`cmake -B build -DCMAKE_FIND_USE_PACKAGE_REGISTRY=OFF -DCMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY=OFF ...`
  - 預期：依賴路徑全部落在本專案的 deps 目錄，不含其他 PrusaSlicer 專案的路徑
  - **實際結果**：`scripts/build_prusaslicer_fork_windows.bat` 的 deps 與主建置兩處 configure 本來就有 `CMAKE_FIND_PACKAGE_NO_PACKAGE_REGISTRY=ON` 與 `CMAKE_FIND_USE_PACKAGE_REGISTRY=FALSE`，但**兩處都缺 `CMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY=OFF`**（CMake 預設為 ON，系統層登錄檔仍會洩漏進來）。已兩處都補上。建置後 `CMakeCache.txt` 的 `CMAKE_PREFIX_PATH` 只指向本專案 `deps/build/destdir/usr/local`。
- [x] 1.3 先做一次**未修改的基準建置**，確認環境可用。
  - 預期：build 成功，可用現有測試模型跑一次切片
  - **實際結果**：對 `4c697465d` 重新 configure＋build 成功（CMake 3.27.9、Visual Studio 17 2022 產生器，沿用稍早修好的建置環境）。用既有 job 目錄 `agent/jobs/03d2aa9f` 的 `config.ini`＋`model.stl` 直接跑 CLI：挖空 → 鑽孔 → 切層 → 支撐點 → 支撐樹 → 底墊全流程跑到 `100% => Slicing done`，正確匯出支撐 mesh。驗證用的輸出檔已刪除。

## 2. 引擎：string table 與結構化輸出（先不動 return 1）

- [x] 2.1 建立 C++ 側 `code → message` 對照表，涵蓋 `owner=engine` 的 ~~16~~ **15** 個代號（原 ~~14~~ 13 ＋ 單 2 新增的 2 個）。代號字串
  - 指令：`python -c "from agent.error_codes import ALL; print(sum(1 for s in ALL if s.owner=='engine'))"`
  - 預期：~~`16`~~ **`15`**。代號字串**逐字**取自 `agent/error_codes.py`，不自行命名。
  - **訂正**：實際輸出 `15`。原本寫 16 是沿用「原 14」，但 `unify-error-code-registry` 查證時已把 14 更正為 13（見該單 design.md），13 ＋ 2 ＝ 15。依「相信程式碼」原則照 15 做。
  - **實際結果**：新檔 `src/libslic3r/EngineErrorCodes.hpp`，一個 `PHZ_ENGINE_ERROR_CODES(X)` X-macro 列 15 個 `X(CODE, "description")`，展開成 `enum class EngineErrorCode` 與 `engine_error_code_name()`／`engine_error_code_message()`。description 只給 log／CLI 看（design D3）。
  - **刻意不動既有英文訊息**：各失敗點原本的 `_u8L` 字串一字未改——字串層本單還要當對照組（D4、3.6），改字會讓新舊兩層結果分歧。
- [x] 2.2 實作結構化錯誤行輸出：單行 `PHZ_ERROR ` 前綴加 JSON，印到 **stdout**。
  - 格式：`PHZ_ERROR {"code":"...","fields":[...],"values":{...}}`
  - **實際結果**：`engine_error_line()` 產生整行；CLI 的 `print_engine_error()` 印到 `boost::nowide::cout`（D2）。三種失敗型態各自接法：
    - **`validate()` 類**（SUPPORT_POINTS_REQUIRED、ELEVATION_TOO_LOW、PAD_GAP_CONFLICT、PAD_CONFIG_INVALID、EXPOSURE_TIME_OUT_OF_RANGE×2、HEAD_PENETRATION_INVALID、HEAD_TOO_WIDE）：`SLAPrint::validate_error()`／`PadConfig::validate_error()` 回傳結構化結果，原 `validate()` 改為薄包裝回傳同一字串——判斷條件、順序、訊息都不變，唯一呼叫端（CLI）行為不變。
    - **例外類**（MODEL_MESH_UNSLICEABLE、PAD_GENERATION_FAILED、UNPRINTABLE_OBJECT、SUPPORT_POINT_SAMPLING_FAILED）：改丟 `EngineCodedException<原型別>`——**型別不變**（仍是 `SlicingError`／`RuntimeError`），任何照型別 catch 的地方行為相同；CLI 的 catch 用 `dynamic_cast<EngineErrorCarrier*>` 取出代號。
    - **CLI 直接印的**（INVALID_MODEL、MODEL_OUT_OF_BOUNDS、SUPPORT_POINTS_MODEL_MISMATCH、SHRINKAGE_COMPENSATION_INVALID）：在原本印訊息處旁邊多印一行。
  - 成功路徑不印任何 `PHZ_ERROR`。
- [x] 2.3 `fields` 使用後端 `SLAConfig` 的 snake_case 欄位名。**不要自創命名**——前端 `data-field` 已用相同拼法。
  - **實際結果**：各代號的 `fields` 與 `agent/param_rules.py` 的 Python 預檢**完全一致**，前端不論錯誤來自預檢還是引擎，標紅的格子都相同。
  - 兩處刻意只給代號、不給 `fields`：`branching` 前綴的頭部檢查（SLAConfig 沒有對應欄位，給了面板也對不到）；`SHRINKAGE_COMPENSATION_INVALID`（實例縮放為 0 也會走到這裡，無法斷定是哪個設定造成）。`MODEL_MESH_UNSLICEABLE` 也不給——支撐產生路徑上的層高是 agent 的粗略偵測值，不是使用者設定的值，報出來會誤導。
- [x] 2.4 `PAD_CONFIG_INVALID` 的 `values` 攜帶算出的最小合法角度與實際值。
  - **實際結果**：引擎條件 `bottom_offset() > brim + wing_distance()` 化簡為 `thickness / tan(slope) > brim`（與 Python 預檢同式），門檻 `atan(thickness / brim)`，**無條件進位到 0.1 度**（同 Python：往下捨會報出一個自己也不接受的數字）。
  - **key 命名偏離 proposal 範例**：proposal 範例寫 `required_min_slope`／`actual`，實作用 `min_pad_wall_slope`／`pad_wall_slope`——跟 `/support-params/validate` 回傳的 `values` 同名，前端不必分兩套讀法。其他代號同理（`min_support_object_elevation`、`effective_support_base_safety_distance`、`min_exposure_time`／`max_exposure_time`），另附實際值。
- [x] 2.5 提供代號清單的機器可讀匯出（從 header 掃出或編譯期產生）。
  - **實際結果**：選「從 header 掃出」，不另開 CLI 旗標——契約測試（3.4）不必先有編好的引擎就能跑。X-macro 刻意一行一個代號方便掃描。
  - 驗證：以 regex 掃 `EngineErrorCodes.hpp` 得 15 個，與 `error_codes.py` 的 `owner=engine` 子集雙向差集皆為空。
- [x] 2.6 重建，手動驗證輸出格式。
  - 指令：用一組違規底墊參數跑一次 CLI，`grep PHZ_ERROR` stdout
  - 預期：印出一行合法 JSON，`code` 為 `PAD_CONFIG_INVALID`，`values` 含 `51.4`
  - **實際結果**：編譯零錯誤。用既有 job 的 `config.ini`＋`model.stl` 複本（放 scratchpad，驗完已刪）實測：
    - `pad_wall_slope=50` → `PHZ_ERROR {"code":"PAD_CONFIG_INVALID","fields":["pad_wall_slope","pad_wall_thickness","pad_brim_size"],"values":{"min_pad_wall_slope":51.4,"pad_wall_slope":50}}` ✅（51.4 與後端預檢的 worked example 一致）
    - 頭部直徑 2.0＞支柱 1.0 → `SUPPORT_HEAD_TOO_WIDE`＋兩個欄位 ✅
    - 曝光 500（上限 100）→ `EXPOSURE_TIME_OUT_OF_RANGE`＋`min 0／max 100／actual 500` ✅
    - 正常參數 → **無** `PHZ_ERROR` 行 ✅
    - **例外路徑**：墊高 5mm、縮到 0.1mm 高、層高 0.3 → `MODEL_MESH_UNSLICEABLE` ✅（證明 coded 例外穿過 `process()` 後型別與代號都還在）
    - **CLI 直印路徑**：匯出支撐點後對縮放過的模型匯入 → `SUPPORT_POINTS_MODEL_MISMATCH` ✅
    - 以上每一例 stderr 的英文訊息都與改動前相同（字串層仍命中）。
  - **順帶確認了第 4 節的 bug**：所有 `validate()` 類失敗的 exit code 都是 **0**（`return 1` 寫在 `bool` 函式裡）；例外路徑因 catch 裡是 `return false` 才正確回 1。
  - **發現一個既有 crash（非本單造成）**：`--scale 0.0005`（模型約 0.025mm）會 segfault；用改動前打包的 `slicer-engine/bin/slicer-engine.exe` 跑同一指令一樣 segfault，確認是既有問題，未處理。
  - 未能現場觸發：`INVALID_MODEL`（空 STL 在載入階段就丟例外，走不到「檔案無物件」分支）、`MODEL_OUT_OF_BOUNDS`（`--center` 移出平台後引擎仍照切）。兩者**舊字串也同樣沒出現**，新舊兩層一致；這兩個接點都只是在原訊息旁多印一行，3.6 會用輸出樣本再對一次。

## 3. Python：加 EngineCode 比對器（兩層並存）

- [x] 3.1 Write tests：`EngineCode` 命中時採用該代號；無 `PHZ_ERROR` 行時退回字串層；兩層對同一情境結果相同。
  - **實際結果**：新檔 `agent/tests/test_engine_code_matcher.py`（14 則），照 tdd skill 一刀一刀紅→綠：
    - 只有代號、英文被改寫過 → 兩條流程都採代號（8 則，涵蓋 validate 路徑、例外路徑、mismatch、out-of-bounds、empty-model）；先紅後綠
    - 流程路由不變：support 流程的曝光錯誤仍進 `SUPPORT_GENERATION_FAILED`、slice 流程仍給 `EXPOSURE_TIME_OUT_OF_RANGE`（2 則，守門測試，以一次性 mutation 驗證會抓錯，未 commit）
    - 格式壞掉的 `PHZ_ERROR` 行 → 忽略、退回字串層（2 則，守門，同樣做過 mutation 驗證）
    - 「兩層結果相同」由 3.6 的真實輸出測試負責，不在這裡用手寫字串自證
- [x] 3.2 在 `agent/engine_rules.py` 新增 `EngineCode` 比對器，插在每列 `matchers` 的**最前面**。**字串層保留**。
  - **實際結果**：`engine_codes(stdout)` 解析 `PHZ_ERROR ` 行；`EngineCode` 與 `Substring` 都改成 `matches(stderr, stdout)`；9 列有代號的規則改為 `(EngineCode(...), Substring(...))`，tilt 那列不動。
  - `find_code()` 改為**分層**比對：先掃完所有規則的 `EngineCode`，才掃 `Substring`。只是把 `EngineCode` 放在每列最前面不夠：一列規則的字串可能先於另一列的代號命中。
  - 兩個 classifier 裡不走 `ENGINE_RULES` 的判斷（mismatch、out-of-bounds、empty-model、`_PROCESS_CODE_MAP`）也都先看代號、再看字串。
  - 連帶修改：`test_exit_code_independence.py` 取樣本原本用 `rule.matchers[0].text`，現在第一個是 `EngineCode`，改成依型別取 `Substring`；斷言沒動（此檔不在 3.5 的零修改範圍，6.2 本來就會動它）。
- [x] 3.3 未登錄代號的守門：`EngineCode` 命中但代號不在 `error_codes.py` 時退回 fallback，原文保留於 `detail`。
  - **實際結果**：`TestUnregisteredCode`（2 則），先紅後綠。support 流程 → `SUPPORT_GENERATION_FAILED`，`PHZ_ERROR` 原行在 `detail`；slice 流程 → 通用 JOB_FAILED，`PHZ_ERROR` 原行接在 `error` 後（slice 結果沒有 `detail` 欄，用 `_with_engine_lines()` 補上）。
- [x] 3.4 加契約測試：引擎匯出的代號清單 ↔ `error_codes.py` 的 `owner=engine` 子集，雙向對帳。
  - 指令：`pytest agent/tests/test_engine_code_contract.py -q`
  - 預期：全綠
  - **實際結果**：全綠。測試直接讀 `EngineErrorCodes.hpp` 在 `#define PHZ_ENGINE_ERROR_CODES(X)` 與 `// clang-format on` 之間的 `X(CODE,` 行，雙向比對 15 個代號；submodule 不在時 skip。mutation 驗證：刪掉 header 一列、或在 `error_codes.py` 多一個 engine 代號，都會紅。
- [x] 3.5 **檢查點：既有規則測試零修改通過。**
  - 指令：`pytest agent/tests/test_support_classifier.py agent/tests/test_slicing_classifier.py -q; git diff --stat agent/tests/test_support_classifier.py agent/tests/test_slicing_classifier.py`
  - 預期：全綠，且 diff 無輸出
  - **實際結果**：`96 passed`，diff 無輸出 ✅
- [x] 3.6 **檢查點：新舊兩層結果一致。** 對同一組失敗情境，分別用新引擎（有 `PHZ_ERROR`）與舊引擎（只有字串）的輸出樣本跑分類。
  - 預期：**每一組都回同一個代號。** 不一致就代表 2.1 的代號抄錯或 2.2 的觸發點放錯位置。
  - **這一步不過，不得進第 4 節。**
  - **實際結果**：`agent/tests/test_engine_code_two_layers.py` `37 passed` ✅
    - 樣本：`agent/tests/data/engine_outputs.json`，是真實 CLI 輸出 36 筆（新／舊引擎 × support／slice × 9 情境：7 種失敗＋mismatch＋成功），只刪 progress 行，14 KB，不含絕對路徑。擷取腳本放 scratchpad、不進 repo。
    - 預期代號表 `EXPECTED` 是依規則表推導、手寫的，不是從樣本讀出來的；另有一則守門，確認新引擎失敗時確實有 `PHZ_ERROR`、舊引擎完全沒有（否則兩邊其實是同一層）。
    - 每組都驗三件事：新＝舊、新＝預期、新引擎拿掉 stderr 後結果不變（證明新層單獨就夠）。
  - **回頭修了 2.2 的一個副作用**：全套回歸時 `test_param_rules_contract.py` 多紅 2 則。它們釘住 `Pad.cpp` 裡 `if (brim_size_mm < MIN_BRIM_SIZE_MM ||` 與 `bottom_offset() > brim_size_mm + wing_distance() ||` 這兩段原文，用來證明後端公式與引擎一致；2.2 把條件拆成三個 bool，原文就不見了。修法是把原本的 `if (a || b || c)` 原封不動放回去，拆 bool 只用在區塊內判斷該報哪些欄位；測試不改。重建後重新擷取樣本，與修正前**逐位元相同**。
  - 全套回歸：`2 failed, 1251 passed, 2 xfailed`，失敗的 2 則就是 0.2 的基準（`test_prz_print_time`、`test_subprocess_boundary_5_11`）✅

## 4. 引擎：修 15 處回傳型別

- [x] 4.1 `CLI/ProcessActions.cpp` 的 15 處 `return 1` 改為 `return false`：L400 · 417 · 426 · 432 · 436 · 442 · 451 · 457 · 477 · 484 · 500 · 512 · 516 · 679 · 737。
  - 註：行號以查核當時的 tip 為準，分支改動後會位移。以函式與上下文比對，不要只認行號。
  - **實際結果**：15 處全在 `bool process_actions()` 本體內，沒有夾在 lambda 裡（函式內的兩個 lambda 都不含這些行）；檔案其他函式沒有 `return 1;`。`git diff` 計數：刪 15 行 `return 1;`、加 15 行 `return false;`。
  - **先寫會紅的測試**（`agent/tests/test_engine_exit_codes.py`，20 則，跑在真實 CLI 輸出樣本上）：新引擎每個失敗情境都要 exit ≠ 0、成功情境要 exit 0。樣本新增 hollow 流程（牆厚 2mm → interior mesh is empty；0.5mm → 成功），擷取腳本同步擴充，樣本現為 40 筆。
    - 修前：**13 則紅**（support／slice 各 6 個 validate 失敗＋hollow 1 個），都是 exit 0。
    - 只改 validate 那一處（`validation.failed()` 區塊）→ 重建 → 12 則 validate 轉綠，hollow **仍紅**：證明兩組測試量的是不同接點。
    - 其餘 14 處一起改 → 重建 → 全綠。
  - 查核時確認：「檔案無物件」（`LoadPrintData.cpp` 是 `continue`，slice 迴圈零次就回 true）與「模型超出平台」（`print->empty()` 分支沒有 return）**都不經過這 15 處**，修完仍 exit 0。`test_exit_code_independence.py` 文件字串說它們修完會變 exit 1，這個預測不成立；第 6 節拆 legacy 分支時要照實際情況處理。
- [x] 4.2 重建。
  - **實際結果**：編譯零錯誤（`ProcessActions.cpp(254)` 的 signed/unsigned 警告是既有的）。重建兩次（見 4.1 的兩段式驗證）。
  - 重新擷取樣本後，3.6 兩層一致測試照樣 37 passed：新引擎改走 Path A（exit 1）、舊引擎走 Path B（exit 0），分類結果一致。
- [x] 4.3 驗證挖空失敗的訊息變好。
  - 預期：`generate_hollow` 失敗時帶引擎原文（如 `interior mesh is empty. Try reducing wall thickness...`），不再只有罐頭訊息
  - **實際結果**：用真的 `generate_hollow()`（scratchpad 腳本，`SLICER_ENGINE_BIN` 指定引擎）跑同一模型：
    - 舊引擎：`'error: interior mesh is empty. Try reducing wall thickness for smaller models.'`（exit 0，走 `not hollow_stl.exists()` 分支；已帶原文，是 merge-engine-result-classifiers 4.2 補上的）
    - 新引擎：`'Slicing engine failed (exit 1): error: interior mesh is empty. Try reducing wall thickness for smaller models.\r\n'`（走 `returncode != 0` 分支）✅
    - 牆厚 0.5：兩邊都成功。
    - 附註：`returncode != 0` 分支沒有 `.strip()`，訊息尾端多一個 `\r\n`，不影響內容，未處理。
  - 全套回歸：`2 failed, 1271 passed, 2 xfailed`，失敗的 2 則就是 0.2 的基準；2 則 xfail 照舊（第 6 節處理）✅

## 5. D6：支撐 mesh 寫檔失敗改為有代號的失敗

> **範圍訂正（2026-09-23，使用者決定）**：原寫三個訊息都改印錯誤行。查證後 `Support mesh is empty` 與 `Pad skipped: nothing stands on the plate...`（原寫的 `the support tree is empty` 不是實際文字）都是**警告**，引擎會繼續跑完並以 `SUPPORT_NOT_NEEDED` 正常完成；印成錯誤行會把正常完成判成失敗。本節只做第三個。理由與另開單的條件見 proposal D6；spec delta 見 `specs/support-generation-error-codes/spec.md`。

- [x] 5.1 在 `agent/error_codes.py` 新增 `SUPPORT_MESH_EXPORT_FAILED`（`owner=engine`，HTTP 500，retryable：伺服器端 I/O 問題，不是使用者參數錯），needle 為 `Failed to export support mesh`。
  - 指令：`python -m agent.tools.error_codes --write && python -m agent.tools.error_codes --check; echo "exit=$?"`
  - 預期：`exit=0`
  - **實際結果**：`--write` 前 `--check` 回 1（stale），`--write` 後 `exit=0` ✅。`docs/err_code_spec.md` +1 行、`docs/error_codes.json` +7 行。
  - 連帶：`agent/errors.py` 補 factory `support_mesh_export_failed()`（`api_v2.py` 載入時會檢查每個代號都有 factory，沒有就拋錯）；`test_error_code_registry.py` 的總數 31→32、owner 分布 engine 15→16（該檔文件字串明寫「新增代號時刻意更新」），順手訂正文件字串裡本來就寫錯的「15/15」。
- [x] 5.2 引擎側：`EngineErrorCodes.hpp` 加一列；`ProcessActions.cpp` 寫檔失敗處在**支撐專用模式**印結構化錯誤行並 `return false`，切片模式維持只印 stderr。stderr 英文原文不變。
  - 驗證：真實樣本加「寫檔失敗」情境（在 `*_support.stl` 路徑預先建同名資料夾）。支撐模式新引擎 exit ≠ 0、有 `PHZ_ERROR`；切片模式兩個引擎都 exit 0、`.sl1` 照常產出、無 `PHZ_ERROR`。
  - **實際結果**：樣本現為 44 筆。切片模式的情境照 `agent/jobs.py` 的實際指令加 `--export-support-stl`（不加的話切片根本不會去寫支撐 STL）；其他 36 筆的指令不變。
    - 修前（Section 4 的引擎）：四筆全是 exit 0、無 `PHZ_ERROR`。
    - 修後：支撐模式 `exit=1`、stdout `PHZ_ERROR {"code":"SUPPORT_MESH_EXPORT_FAILED"}` ✅；切片模式 `exit=0`、`.sl1` 在、無 `PHZ_ERROR` ✅。
    - 切片模式守門的 mutation 驗證：把該筆改成「exit 1、無 `.sl1`、有 `PHZ_ERROR`」，3 則測試轉紅（守門、兩層一致、切片 exit code），還原後樣本逐位元相同。
  - 範圍外、未處理：同一段的 `Failed to export support pillars / pad mesh / support tree / brace mesh` 也都只印 stderr，照舊沒有代號。
- [x] 5.3 `ENGINE_RULES` 加一列，只掛 `support` 流程，`EngineCode` ＋ `Substring` 兩層。`test_support_classifier.py` 原本斷言此訊息落 fallback 的那則測試，照 spec delta 改為新代號。
  - **實際結果**：先改測試、看它紅（`SUPPORT_GENERATION_FAILED != SUPPORT_MESH_EXPORT_FAILED`），再加規則轉綠。
  - `test_support_classifier.py` 動了兩處：
    - 寫檔失敗那則從 `TestStep5FailClosed` 移到新的 `TestSupportMeshExportFailed`，斷言改為新代號
    - mismatch 組裡「一般失敗不得被判成 mismatch」那則原本拿這句當「一般失敗」的例子，改用另一句沒有代號的真實引擎訊息 `Failed to export support tree ...`，斷言強度不變
  - 真實樣本測試（`test_engine_code_two_layers.py`、`test_engine_exit_codes.py`）先寫、紅在預期的 3 處，Python 側改完剩引擎相關的 4 則紅，重建後全綠。
  - 全套回歸：`2 failed, 1286 passed, 2 xfailed`，失敗的 2 則就是 0.2 的基準 ✅
- [x] 5.4 前端補 `SUPPORT_MESH_EXPORT_FAILED` 的四語系文案（DS-Online 側，先載入 `i18n-key-conventions` skill）。
  - 驗證：前端 `backendErrorKeys.spec.js` 對帳全綠
  - **實際結果**：DS-Online 側 6 個檔案。
    - `api/error_codes.json` 從後端 `docs/error_codes.json` 同步（同步前兩份除新代號外完全相同）
    - `src/services/errors.js` 加 `SUPPORT_MESH_EXPORT_FAILED: 'errors.backend.supportMeshExportFailed'`
    - 四語系 `errors.backend.supportMeshExportFailed`（en: `The supports were generated but could not be saved. Please try again.`）
  - 先同步 `api/error_codes.json`，對帳測試 5 則紅；補 key 與文案後 `9 passed` ✅
  - `npm run test:unit`：`3730 passed / 6 failed / 7 skipped`，與 open-support-param-panel 記錄的基準完全相同（同 3 個檔案、同 6 則），新增失敗 0。
  - `npm run lint`：25 errors 全在未碰過的 3 個檔案（`boundaryBrush.js` 18、`sceneCoordinator.js` 6、`AddPrintersDialog.vue` 1）；碰過的檔案 0 問題；`--fix` 沒有改到任何其他檔案。
  - 未在 dev server 實際觸發：要讓前端看到這個錯誤，得讓後端寫支撐 STL 失敗，UI 操作做不到。留到 8.5／8.6 驗收一起處理。

## 6. 拆除 legacy exit-code 分支

- [x] 6.1 刪除 `slicing_classifier.py` 的 `_LEGACY_EXIT0_ONLY_CODES` 分支。
  - 指令：`grep -n "_LEGACY_EXIT0_ONLY" agent/slicing_classifier.py`
  - 預期：無輸出
  - **實際結果**：無輸出 ✅。
    - 做法：常數刪除；Step 5（超出平台）與 Step 6（檔案無物件）從「exit 0 且無輸出」那條路，移到 exit-code 分岔**之前**，對任何失敗的 run 都檢查（`exit_code != 0 or not output_file_exists`）。
    - 為什麼放分岔前：放在 Path A 裡另寫一份的話，兩條路的判斷順序會不同，同一組輸出配 exit 0 與 exit 1 可能得到不同結果。移上去之後兩條路共用一個順序，而且就是原本 exit 0 那條路的順序（Step 0 → 5 → 6 → validate），`test_slicing_classifier.py` 釘住的順序測試全部照舊通過，零修改。
    - 成功判定不受影響：exit 0 且輸出檔存在，仍直接回成功。
    - 連帶：模組文件字串的判斷順序表、`engine_rules.py` 文件字串裡指向已刪常數的那句，一併改寫。
    - Section 4 已查證：用新引擎，這兩種失敗仍是 exit 0（不經過那 15 處）。所以本節主要是**讓結構不再依賴 exit code**，不是修一個會發生的退化；舊引擎、新引擎都照舊分類得到。
- [x] 6.2 `test_exit_code_independence.py` 的兩個 `xfail` 改為正常斷言。因原標記為 `strict=True`，拆彈後不改標記會直接紅。
  - 指令：`pytest agent/tests/test_exit_code_independence.py -q`
  - 預期：全綠，且無 xfail
  - **實際結果**：先拿掉 xfail、分類器還沒改 → 2 則紅（exit 1 時兩者都回 `None`）；改完分類器 → `15 passed`，無 xfail ✅。原本拿樣本對已刪常數做比對的 sanity 測試一併移除（比對對象不存在了），測試類別改名 `TestNothingToPrintIsExitCodeIndependent`，文件字串改寫成現況。
- [x] 6.3 全套回歸，與 0.2 基準比對。
  - 指令：`pytest agent/tests -q`
  - 預期：無新增失敗
  - **實際結果**：`2 failed, 1287 passed`，**0 xfailed**；失敗的 2 則就是 0.2 的基準 ✅

## 7. 交付：binary、供應鏈紀錄、指標

> **先修了一個供應鏈腳本 bug**：`scripts/package_slicer_engine_windows.ps1` 的 `engine_commit` 取的是 **superproject** 的 `git rev-parse HEAD`，不是 fork 的。0.3 記下的既有落差（`source-chain.json` 的 `8c94d9b` 對不上指標）就是這個原因：`8c94d9b` 是 superproject 的 commit（`chore(agent): 同步 CORS 白名單…`），fork 裡根本沒有。改為讀 `third_party/prusaslicer_fork` 的 HEAD，且 fork 有未 commit 改動時拒絕打包（沒有任何 commit 能描述那樣的 binary）。守門已實測：fork 未 commit 時打包在寫 manifest 前就失敗。
>
> fork 先 commit 成 **`2efc8395206bcae5690d50e78ce2013a1e99fd00`**（`feat(sla): report failures as engine error codes, exit non-zero on failure`，10 個檔案）。建置不嵌入 git hash（`version.inc` 只有版號），且最後一次建置後沒再動過 fork 檔案，所以 commit 前建好的 binary 就是這個 commit 的產物，不需重建。

- [x] 7.1 換 `Bundle-Launcher/bundle-win/slicer-engine/bin/` 底下的執行檔。
  - **實際結果**：先打包到 scratch，腳本內建的關卡全過：PE icon gate OK、Exports `count=1 slicer_run_cli=True`、consumer harness audit PASS、scan `VERDICT: PASS`。
  - `bundle-win/` 在 Bundle-Launcher 是 **untracked**，這一步只是本機檔案替換，沒有 commit。
  - 替換前整包備份到 `Bundle-Launcher/bundle-win/slicer-engine.backup-20260724T131327Z`（1021 個檔案，與原目錄同數）。
  - 用「覆蓋複製」而非「刪目錄重放」：舊 Bundle 的 `legal/NOTICE.md`、`legal/SOURCE_OFFER.md` 是打包腳本現在不產生的檔案，而 `source-chain.json` 的 `source_offer` 指向的正是 `legal/SOURCE_OFFER.md`（底線；腳本產生的是 `SOURCE-OFFER.md` 連字號）。刪目錄會讓這個路徑指向不存在的檔案，所以保留。這個命名落差是既有問題，未處理。
  - 打包產生的 `symbols/`（PDB）舊 Bundle 沒有，不放進 consumer bundle。
  - `bin/slicer-engine.exe`、`bin/slicer_core.dll` 的 hash 與打包產物、建置產物都一致。
  - 冒煙測試（直接跑 Bundle 裡的 exe）：底墊違規 → `exit=1`、`PHZ_ERROR {"code":"PAD_CONFIG_INVALID",...,"values":{"min_pad_wall_slope":51.4,"pad_wall_slope":50}}`；正常參數 → `exit=0`、`Support mesh exported ... (includes supports and pad)` ✅
- [x] 7.2 **同步更新供應鏈紀錄**（只換 binary 會讓稽核紀錄與實物不符）：`engine_build_id.txt`、`artifact-manifest.json`、`engine-artifact-manifest.json`、`sbom.spdx.json`、`source-chain.json`、`scan-report.json`。
  - **實際結果**：六份都由打包腳本重新產生並覆蓋（外加 `bin/engine_build_id.txt`、`EXPORTS.txt`）。新 build id `20260923T094946Z`（原 `20260724T131327Z`）；`engine_commit` = `2efc8395…`。
- [x] 7.3 **更新 superproject 的 submodule 指標**，指向 ~~1.1 記下的 commit~~ **fork 上本單的 commit `2efc8395`**。
  - **訂正**：1.1 記下的 `4c697465d` 是動工前的 tip，不含本單任何引擎改動；指標指過去的話，別人拉下來跑契約測試會對舊 code 執行。正確目標是它的後代 `2efc8395`。
  - 遠端分支另有使用者 2026-09-17 的 `8a1fd0c`（只把指標從 `2e10c16d4` 移到 `4c697465d`），本地合併時指標以 `2efc8395` 為準（它是 `4c697465d` 的後代，git 可直接快轉 submodule）。
- [x] 7.4 **一致性驗證（三者必須相同）**：
  - 指令：`git submodule status third_party/prusaslicer_fork`
  - 指令：`cd third_party/prusaslicer_fork && git rev-parse HEAD`
  - 指令：`grep -i commit ../Bundle-Launcher/bundle-win/slicer-engine/source-chain.json`
  - 預期：**三個 commit hash 完全相同。**
  - **實際結果**：三者都是 `2efc8395206bcae5690d50e78ce2013a1e99fd00` ✅（submodule status 顯示 `v1.0.5-rc3-19-g2efc83952`）。0.3 記下的既有落差一併消除。
- [x] 7.5 **指標更新 MUST 與依賴它的 Python 改動落在同一個 commit / PR。** 分兩次進的話，其他人跑契約測試會對舊 fork code 執行並誤判通過。
  - 檢查：該 PR 的 diff 同時包含 `third_party/prusaslicer_fork` 指標與 `agent/` 的改動
  - **實際結果**：同一個 superproject commit 同時包含指標、`agent/`、測試、樣本、docs、openspec 與兩支 scripts。`.gitmodules` 的 SSH→HTTPS 本機改動依使用者決定**不納入**。
  - **push 狀態**：fork push 被拒（本機 GitHub 帳號 `HeidiiiH` 對 `MaxShih147/PrusaSlicer` 沒有寫入權限，403）。fork 沒 push 之前 superproject 也**不得** push，否則別人會拿到抓不到的指標。兩邊都待處理。

## 8. 驗收

- [ ] 8.1 `pytest agent/tests -q` 與 0.2 基準相比無新增失敗
- [ ] 8.2 `test_exit_code_independence.py` 全綠且無 xfail
- [ ] 8.3 引擎代號清單 ↔ Python 登錄檔雙向對帳測試全綠
- [ ] 8.4 `python -m agent.tools.error_codes --check` 回零
- [ ] 8.5 手動：違規底墊參數跑一次切片，前端顯示的訊息**含具體角度數值**，不是籠統的「參數不正確」
- [ ] 8.6 手動：完整切一次正常模型，確認整套改動未影響正常流程
- [ ] 8.7 三項 commit 一致性驗證通過（7.4）

## 9. 下一版才做（不在本單）

- [ ] 9.1 **刪除字串比對層。** 條件：本單的 3.4 對帳測試全綠，且含新引擎的 bundle 已出過一次。條件未成立前不得刪除——刪了就沒有對照組。
  - 刪除後省下 9 條字串常數、對應契約測試，以及「引擎改寫訊息文字就靜默壞掉」的長期風險。

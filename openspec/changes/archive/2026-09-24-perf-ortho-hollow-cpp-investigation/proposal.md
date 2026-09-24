## Why

Ortho Auto Process 一鍵處理的 Step 1（`run_ortho_pipeline()` → `generate_hollow()` → `run_prusa_cli()` → 依 `agent/config.py` 路徑解析邏輯選定之 executable（本輪量測情境下為封裝版）`slicer-engine.exe --export-hollow-stl`，[agent/ortho_pipeline.py:908-923](../../../agent/ortho_pipeline.py#L908-L923)、[agent/sla_operations.py:401-466](../../../agent/sla_operations.py#L401-L466)）在大面數模型上耗時明顯（探索性 baseline 約 1.3～4.6 秒，視模型面數而定），因此進行了一輪多階段的效能調查：先確認 production 呼叫路徑與封裝版來源限制，再用隔離診斷版對 C++ 子階段拆時，找出 OpenVDB 相關呼叫鏈占絕大多數耗時；針對其中兩個看似可省的候選（CSG union 對空 grid 的 `clone()`、`mesh_to_grid()` 內的 `its_split()`）實測後判定不值得投入；再依指示轉向 `TriangleMesh::ReadSTLFile()` 的 admesh 匯入修復階段，找到一個資料狀態可判定、且在高面數壓力測試模型（由使用者以既有牙科模型拆分三角面增面而成，非一般 production 面數分布之樣本，目前資料夾中找不到對應原始檔）上實測有效（隔離 A/B 約 0.462 秒／8.4%，且完整 Hollow STL 輸出逐位元相同）的候選——**跳過條件式的第二次 `stl_check_facets_exact()`**。

最後一輪用三個新增的一般完整基座代表模型（清理後面數約 16.6 萬～23.9 萬面）重新測試該候選是否有更廣泛的適用性，結果三個模型的第一次 `stl_check_facets_exact()` 後 `degenerate_facets` 皆為 0，因此依事先議定的停止判準，**都沒有觸發**會被跳過的第二次檢查。依此判準，本輪調查以「該優化不予採用」結案。

本提案的目的**不是導入任何程式碼變更**，而是把這一輪調查（production 路徑確認、封裝版來源限制、C++ 子階段拆時、已否決的 OpenVDB 候選、skip-2nd-exact-check 候選的驗證與最終停止判準）以 OpenSpec 形式正式留存，供未來重新評估 Hollow C++ 效能時依循，並明確標示調查中診斷版數字與封裝版數字的區別、以及本輪未經驗證的成本不得誤植為 production 成本。

## What Changes

- **新增一份決策紀錄 capability**，記載 Ortho Hollow C++ 效能調查的結論：
  - Production 呼叫路徑：單一 Ortho job 對 C++ Hollow **最多呼叫一次**（由 `_is_u_arch_from_low_sections()` 前置判斷決定是否呼叫；Hollow-fit 檢查在 C++ 執行**之後**才判斷，不影響是否呼叫）。本輪量測明確清空 `SLICER_ENGINE_BIN`／`PRUSA_SLICER_BIN` 後，由 `agent/config.py` 的路徑解析邏輯選定封裝版 executable；但實際部署環境可由這兩個環境變數覆寫、指向非封裝版（例如 dev-tree build，README 的 Quick Start／Troubleshooting 段落明確教學此設定），本輪未觀察到任何正在執行的 production 後端程序，不宣稱所有部署都使用封裝版。
  - 封裝版 baseline 的來源限制：封裝 manifest 的 `engine_commit` 記錄的是 **parent repo** 的 `git rev-parse HEAD`，並未在 submodule 內獨立記錄建置當下的 SHA，因此封裝版 baseline 數字 SHALL 標示為探索性（exploratory），不得當作已完全可追溯的正式基準。
  - C++ 子階段耗時分布：OpenVDB 的 voxelize／redistance／dilate 呼叫鏈合計占 Hollow subprocess wall time 約 **76.2%～93.8%**（依代表模型面數而異）；其餘子階段在小面數／中面數代表模型上個別皆為個位數百分比，但在**高面數壓力測試模型上 mesh 載入單獨即占約 21.0%**（因該模型清理後仍含約 5,042 個退化面，這段時間內含真正執行的第二次 `stl_check_facets_exact()`，見下）。
  - 兩個已否決的 OpenVDB 候選（CSG union 對空 grid 的 `clone()`；`mesh_to_grid()` 內對單一連通分量網格的 `its_split()`）及其否決依據（皆已實測，成本過小或風險不成比例，非僅憑觀感判斷）。
  - Skip-2nd-exact-check 候選：資料狀態可判定的候選跳過條件（三個代表模型中僅高面數壓力測試模型在驗證中實際觸發過該分支，另兩個模型開關前後走的是同一段程式碼）、其在高面數壓力測試模型上的隔離 A/B 結果（約 0.462 秒／8.4%，開關前後各 5 次、完整 Hollow STL 輸出 SHA-256 逐次逐模型相同）、以及三個新增一般完整基座代表模型上全數未觸發第二次檢查的最終停止判準——**該候選經評估後不予採用，未移植至 production**；開放邊等從未觸發過此分支的輸入型態未經實測。
  - 明確要求：引用本輪任何耗時數字時，SHALL 區分「隔離診斷版（`C:\hdiag\pf` worktree）」與「封裝版（依 `agent/config.py` 設定選定的 executable；本輪量測選用封裝版）」的數字，且 MUST NOT 將本輪新增的診斷快照（FNV hash 狀態比對）本身的耗時（約 15.8～23.0 ms）誤植為第二次 `stl_check_facets_exact()` 或任何 production 成本。
- **不變更任何 production 程式碼、測試或既有 spec**：C++（`third_party/prusaslicer_fork` 主 submodule checkout）與 Python（`agent/`）皆未被修改；本提案純粹是把既有只讀／隔離環境調查的結論正式化、可追溯化。
- **不新增／不修改任何 API、CLI 參數、前端或其他 pipeline 行為**。

## Capabilities

### New Capabilities
- `ortho-hollow-cpp-performance-decision`：記載 Ortho Hollow C++ 效能調查的量化結論（production 路徑、封裝版來源限制、C++ 子階段占比、已否決候選、skip-2nd-exact-check 候選的驗證數據與最終停止判準）與「目前不採用任何 production 優化」的結案決策，作為未來重新評估此路徑效能時的既定基準與觸發條件。

### Modified Capabilities
（無。本提案不變更任何既有 capability 之 requirement-level 行為。）

## Impact

- `agent/ortho_pipeline.py`、`agent/sla_operations.py`、`agent/config.py`：**未修改**（本提案為純文件／決策留存）。
- `third_party/prusaslicer_fork`（主 submodule checkout）：**未修改**，全程維持在 `dev` 分支、既有 pin 的 commit，工作目錄乾淨。所有 C++ 層級的插樁、快照與 prototype 修改都只存在於 repo 外的隔離 git worktree（`C:\hdiag\pf`，detached HEAD 於同一顆 submodule 已 pin 的 commit）與獨立建置目錄（`C:\hdiag\build`），未併入 production。
- 封裝產物（`slicer-engine\bin\slicer-engine.exe` 及其 manifest）：**未修改**，本輪僅讀取其 SHA-256 與 manifest 內容作為 provenance 比對。
- 測試：**未新增／未修改**（無程式碼行為變更，無需回歸測試）。
- 受影響範圍：僅新增 `openspec/specs/ortho-hollow-cpp-performance-decision/spec.md` 一份決策紀錄型 spec；不觸及任何既有 spec 或程式碼路徑。
- 調查依據（隔離環境內產生，不納入本次程式碼變更，僅作為佐證）：
  - `C:\hdiag\pf`（git worktree，detached HEAD，含本輪所有 C++ 插樁／快照／prototype 修改，與 `HOLLOW_PROF`／`HOLLOW_PROTO_SKIP_2ND_EXACT` 兩個環境變數開關）
  - `C:\hdiag\build`（獨立 CMake 建置目錄，重用主 checkout 既有的 deps destdir）
  - 本次對話所附之調查結案報告（含 production 路徑追蹤、C++ 子階段拆時表、OpenVDB 候選否決依據、skip-2nd-exact-check 驗證與 A/B 數據）
  - Skip-2nd-exact-check 的乾淨計時 A/B（開關前後各 5 次＋1 次不計入的暖機）僅印於終端機，未落地為獨立結果檔；`C:\hdiag\equiv\ab\` 下尚存的 36 個輸出 STL 檔案可重新計算 SHA-256 以核對等價性，但無法重新算出當時量到的耗時均值

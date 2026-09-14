## Context

`agent/tests/` 目前有 7 failed + 3 collection errors，且這個狀態已經持續了至少四輪先前的 change（`2026-07-29-fix-rle-layer-count-sync` 起）。每一輪都把 `test_6_11_single_normal_layer_full_params` 與 `test_engine_runs_as_separate_process` 記為「既存失敗、與本次改動無關」，但從未回頭處理，導致失敗清單長期存在、無法再用「失敗數量」判斷是否有新的 regression。

追查後定位三個獨立成因：

1. **Dependency 宣告缺口**：`requirements.txt` 是唯一存在過的宣告檔案（`git log --all --diff-filter=A -- "requirements*"` 只有它），但它只跟著「production 直接 import 到什麼」被動更新（precedent：`c3a2b60 fix: add rtree dependency to requirements`）。`shapely` 已被 `agent/sla_operations.py` / `agent/boundary_detection.py` 直接 import 卻從未補上；`httpx`（`starlette.testclient.TestClient` 的必要相依）與 `pytest`（測試執行器本身）則從未被視為「需要宣告」的對象，因為 repo 從未有測試專用的宣告管道，且本機 `.venv` 早已裝好這些套件，讓問題只在乾淨環境重建（例如換一台機器、CI）時才會現形。

2. **`test_6_11` 的真正根因**：用 `git log --follow -p` 追出此測試在 **2026-05-21**（commit `b6b1b73`）建立，手算註解使用 Case 2 retract 的舊公式 `drop2 = max(0, lift+lift2-dist) = 3.0`。**隔天 2026-05-22**，`openspec/changes/archive/2026-05-22-fix-prz-retract-zero-falsy-supersede` 把 Case 2 行為明確判定為 BREAKING 並取代：「僅傳 dist、未傳 drop2」時 drop2 固定為 `0.0`，其 proposal.md 逐字寫著「舊版 `max(0, lift+lift2-dist)` 公式已廢棄」。這個決策當時只更新了 `test_prz_retract.py` 裡驗證 `_resolve_retract_pair()` 的單元測試，沒有同步更新 `test_prz_print_time.py` 裡驗證 `_compute_print_time()` 端對端輸出的 `test_6_11`。現行 `openspec/specs/prz-motion-time/spec.md` 完整延續了這個決策（第 45-49 行：「drop2 SHALL NOT 等於 `6.0`（舊版公式已廢棄）」），且直接執行 `_get_float`／`_resolve_retract_pair` 也驗證了目前 production 行為與 spec 完全一致——`test_6_11` 期望的 `14.0` 對應的是被明確廢棄的舊公式，`11.0` 才是現行 spec 認定的正確值。此後四輪 archived change 都只做了「這個失敗與我這次的改動無關」的隔離驗證（`git diff HEAD` 為空），從未往前追溯到這次 BREAKING 決策，因此持續把它記成「待修的 production 缺陷」。

3. **`pytest-asyncio` 缺口**：全 repo 只有 `test_subprocess_boundary_5_11.py` 一處使用 `@pytest.mark.asyncio`，但 repo 早在 `openspec/changes/archive/2026-08-04-add-slicing-progress/tasks.md:4` 就記錄了明文慣例：「測試環境未安裝 `pytest-asyncio`，非同步流程一律以 `asyncio.run()` 同步驅動」，並在 `test_run_prusa_cli_streams.py` 示範了這個寫法。這一處測試從未跟上這個既定慣例。

## Goals / Non-Goals

**Goals:**
- `pytest agent/tests/ -q` → 0 failed、0 collection errors。
- Dependency 宣告如實反映目前實際被 import／使用的套件（production + 測試）。
- 不改變任何 production 行為與輸出。
- 修正的每一處測試斷言都能追溯到一個既有、已 archive 的 spec 決策或既有已驗證通過的寫法，不是憑空新訂規則。

**Non-Goals:**
- 不建立 CI（`.github/workflows` 等）。
- 不建立 `requirements-dev.txt` 或任何 production / test 依賴分流機制。
- 不處理與這 10 項既知失敗無關的其他測試或覆蓋率缺口（例如 Ortho / Hollow-fit 子系統）。
- 不評估或變更 Python 版本 / venv 建置流程（README 建議 3.11-3.12，本機為 3.14，此差異不在本 change 範圍）。

## Decisions

**D1 — Dependency 全部併入既有單一 `requirements.txt`，不新建檔案。**
Repo 從未有 production / test 依賴分流的先例（`git log` 上 `requirements.txt` 是唯一存在過的宣告檔案），README 也只記載一個 `pip install -r requirements.txt` 安裝路徑。新建 `requirements-dev.txt` 會是「順便建立一個新慣例」，超出本次「恢復測試 baseline」的範圍，因此選擇對現狀最小、最一致的做法。

**D2 — `shapely` / `pytest` 不加版本號；`httpx` pin `>=0.27.0,<0.29.0`。**
`shapely` 比照 `rtree` 先例（commit `c3a2b60`）：發現遺漏宣告時直接補一行裸套件名，不臆測沒人驗證過的最低版本。`pytest` 同理。`httpx` 的版本區間不是臆測，而是直接取自本機已安裝的 `starlette==0.50.0` 套件自身在 dist-info METADATA 宣告的 `testclient`/`full` extra 相依範圍（`Requires-Dist: httpx<0.29.0,>=0.27.0; extra == 'full'`），是可查證、starlette 自己保證相容的範圍。

**D3 — 不新增 `pytest-asyncio`；`test_engine_runs_as_separate_process` 改用 `asyncio.run()`。**
全 repo 唯一一處用到 `@pytest.mark.asyncio`，且已有明文既定替代慣例（`test_run_prusa_cli_streams.py` + `2026-08-04-add-slicing-progress/tasks.md:4`）。改用既有慣例對齊，不需要新增套件，也不會像安裝 `pytest-asyncio` plugin 那樣可能影響其他純同步測試的 collection 行為。

**D4 — `test_6_11` 判定為 stale test，不修改 `agent/prz_encoder.py`。**
證據鏈：(a) git blame 顯示測試建立於 2026-05-21，(b) 隔天 2026-05-22 的 archived change 明確將 Case 2 舊公式判定為「已廢棄」，(c) 現行 `openspec/specs/prz-motion-time/spec.md` 延續此決策並明文排除舊公式的結果，(d) 直接執行 `_resolve_retract_pair()` 與 `_get_float()` 驗證目前 production 輸出（`drop2=0.0`、`drop2_v=60.0`）完全符合現行 spec，非某處遺漏 default 值造成的意外。四條證據互相獨立且一致指向同一結論。

**D5 — 用 MODIFIED `prz-motion-time` 補一個 Case 2 端對端 scenario，作為本 change 唯一的 spec delta。**
本機安裝的 `@fission-ai/openspec@1.2.0` CLI 的 validator（`totalDeltas === 0` → ERROR）結構性要求每個 change 至少要有一個 spec delta，即使沒有行為變更也一樣。與其為了滿足這個要求新建一個純流程性的 capability（例如「backend-test-baseline」），不如檢查是否有真實、可追溯的 spec 缺口可以掛——結果發現 `prz-motion-time` 的「print_time 計算 SHALL 重用 retract 4-case override」需求確實只驗證過 Case 4 的端對端行為（`spec.md:144-149`），Case 2 自 2026-05-22 BREAKING 決策後從未被同一層級驗證過，這正是 `test_6_11` 的根本缺口所在。補上這個 scenario 既誠實地填補既有 capability 的既知缺口，也自然滿足工具的結構性要求。

## Risks / Trade-offs

- **D4 推翻了四輪前人的既有說法**（先前都記為「待修的 production 缺陷」）。雖然證據鏈完整且可獨立驗證，仍建議在合併前請熟悉 PRZ retract 邏輯的人覆核一次，而不是單憑本次調查直接定案。
- **D2 的 httpx 版本區間**目前只驗證與現有 `fastapi==0.128.0` / `starlette==0.50.0` 組合相容；未來若升級 fastapi/starlette 大版本，需要重新核對這個區間是否仍適用。
- **D1 選擇不分流依賴**代表未來若真的需要純測試依賴（例如新增 mocking 框架），同樣的問題會再次出現；但這是現有 repo 慣例下的合理取捨，分流機制若有必要應該是另一個獨立的討論，不應該搭本次「恢復 baseline」的便車決定。

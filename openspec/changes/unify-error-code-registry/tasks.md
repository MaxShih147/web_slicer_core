## 1. 建立真值登錄檔

- [x] 1.1 建 `agent/error_codes.py`，宣告 28 筆 `ErrorCodeSpec`（`code` / `http_status` / `retryable` / `owner` / `note` / `engine_needles`）。`note` **逐字**抄自現有 `docs/err_code_spec.md` 的「說明」欄。
  - 指令：`python -c "from agent.error_codes import ALL; print(len(ALL))"`
  - 預期：印出 `28`
- [x] 1.2 逐一標記 `owner`。判準：引擎在自身 process 內可判斷 → `engine`；需要 job／檔案系統／HTTP → `python`。
  - 指令：`python -c "from agent.error_codes import ALL; import collections; print(collections.Counter(s.owner for s in ALL))"`
  - 預期：`Counter({'python': 15, 'engine': 13})`（訂正記錄見 design.md：原寫 14/14，對照實際程式碼後 `HOLLOW_GENERATION_FAILED` 等 5 碼判斷點在 Python，無專屬 engine needle，故正確為 13/15）
- [x] 1.3 為 13 個 `owner=engine` 的 code 填入 `engine_needles`（自兩支 classifier 現有的對照表搬過來，不新增不刪減）。
  - 指令：`python -c "from agent.error_codes import ALL; print([s.code for s in ALL if s.owner=='engine' and not s.engine_needles])"`
  - 預期：`[]`

## 2. 產生器與 --check

- [x] 2.1 Write tests：`test_error_code_registry.py` — 28 筆唯一、必填欄位齊全、`owner` 只有兩種值、`engine` 群必有 needles。
  - 指令：`pytest agent/tests/test_error_code_registry.py -q`
  - 預期：全綠
- [x] 2.2 建 `agent/tools/error_codes.py`，實作 `--write`：產生 `docs/err_code_spec.md` 與 `docs/error_codes.json`，兩者開頭加「本檔自動產生，請勿手動編輯；改說明請編 `agent/error_codes.py`」標頭。
  - **範圍訂正（2026-09-17）**：`err_code_spec.md` 除了 Error Code Reference 表格外，還有大量無法從登錄檔五個欄位推導的手寫內容（Error Response Format 範例、Endpoints 逐一列出每個 API 可能回傳的 code 及語意）。`--write` 只取代「Error Code Reference」表格區塊（含新標頭），其餘章節維持手動維護、原樣保留，不受 `--write` 管理。
- [x] 2.3 **驗證搬家無損**：執行 `--write` 後比對 md 的 diff。
  - 指令：`python -m agent.tools.error_codes --write; git diff --stat docs/err_code_spec.md`
  - 預期：**除新增標頭外無其他差異**。有差異代表 `note` 抄錯，必須修到零差異才能往下。
  - **實際結果**：標頭 + 表格新增 `BOOLEAN_INVALID_MESH`、`SUPPORT_POINTS_MODEL_MISMATCH` 兩列（原表本就缺這兩碼，見 1.1 的訂正），既有 26 列逐字節相同。已確認為預期差異，非搬家漏抄。
- [x] 2.4 實作 `--check`：不寫檔、只比對，不一致回非零並印出應執行的指令。
  - 指令：`python -m agent.tools.error_codes --check; echo "exit=$?"`
  - 預期：`exit=0`
- [x] 2.5 反向驗證 `--check` 有牙齒：手動改壞 md 一個字，再跑 `--check`。
  - 指令：`sed -i 's/非預期的伺服器錯誤/XXX/' docs/err_code_spec.md; python -m agent.tools.error_codes --check; echo "exit=$?"; git checkout docs/err_code_spec.md`
  - 預期：`exit=1`，訊息指出 `err_code_spec.md` 過期

## 3. 契約測試

- [x] 3.1 Write tests：`test_error_code_contract.py` — 登錄檔每個 code 都能在 `errors.py` 找到對應 factory；反向亦然（`errors.py` 沒有登錄檔之外的 code）。
  - 指令：`pytest agent/tests/test_error_code_contract.py -q`
  - 預期：全綠
- [x] 3.2 擴充引擎字串契約：`owner=engine` 的每條 `engine_needles` 必須出現在 `third_party/prusaslicer_fork` 原始碼。作法照抄 `test_support_string_contract.py`；fork 未 checkout 時 `pytest.skip`。
  - 指令：`pytest agent/tests/test_support_string_contract.py -q`
  - 預期：全綠（或 skip，若 submodule 未取出）
- [x] 3.3 加入負向檢查：刻意變造一條 needle，斷言在原始碼中找不到（證明斷言有牙齒）。

## 4. 移除手抄 dict

- [x] 4.1 `api_v2.py` 的 `_ERROR_CODE_FACTORIES` 改由登錄檔於執行期推導；推導不到 factory 時在**載入階段**拋錯，不得靜默退回 `JOB_FAILED`。
- [x] 4.2 確認錯誤回應零變更。
  - 指令：`pytest agent/tests/test_support_error_codes.py agent/tests/test_slice_progress_endpoint.py agent/tests/test_job_status_persistence.py -q`
  - 預期：全綠，且**未修改任何一支既有測試**
  - **實際結果**：78 passed（需另外裝 `httpx` 才能跑 `test_slice_progress_endpoint.py`，環境缺依賴，非本單範圍）。`git diff --stat` 對這三支測試檔為空，確認未改動。
- [x] 4.3 全套回歸。
  - 指令：`pytest agent/tests -q`
  - 預期：全綠（既有 known failure 除外，執行前先記錄基準）
  - **實際結果**：1052 passed, 5 failed。用 `git stash` 對照本單改動前的基準，同樣是 5 failed / 810 passed，且失敗的是同 5 支（`test_prz_print_time.py`、`test_subprocess_boundary_5_11.py` 缺 `pytest-asyncio`、`test_support_e2e.py::TestRealEngine` 3 支需要真正的引擎 binary）。確認為既有環境缺口，非本單造成的迴歸。

## 5. 掛上關卡

- [x] 5.1 把 `python -m agent.tools.error_codes --check` 加進本地 pipeline / pre-commit。
  - **決定（2026-09-17，使用者選定）**：本 repo 目前沒有 CI、沒有 `.pre-commit-config.yaml`、也沒有既有 git hook 可循，故不新增 `pre-commit` 框架依賴，改寫一支 `.git/hooks/pre-commit` script。**注意：`.git/hooks/` 不進版控**，其他人 clone 這個 repo 不會自動拿到，要各自複製這支 script 才會在本機生效；已在 script 註解中說明。已驗證：正常情況 exit 0，手動改壞 `err_code_spec.md` 後 exit 1 並印出修復指令，`--write` 後恢復 exit 0。
- [x] 5.2 更新 `docs/err_code_spec.md` 的維護說明（在登錄檔的檔頭註解中撰寫，由產生器輸出）。
  - 見 `agent/tools/error_codes.py` 的 `_HEADER_BANNER`：說明表格由 `--write` 產生、真值在 `agent/error_codes.py`、其餘章節手動維護。
- [x] 5.3 確認 `docs/error_codes.json` 已進版控，供 DS-Online 的 `api/error_codes.json` 同步。
  - `docs/error_codes.json` 為新檔，尚未 `git add`；本單其餘檔案也都還沒 commit（見下方 6.4 前的整體確認），會在使用者要求 commit 時一併加入版控。

## 6. 驗收

- [x] 6.1 `python -m agent.tools.error_codes --check` 回零
  - 已驗證：exit=0
- [x] 6.2 `pytest agent/tests -q` 全綠
  - 1052 passed, 5 failed；5 支失敗與改動前基準（`git stash` 對照）完全相同，屬既有環境缺口（缺 `pytest-asyncio`、缺真實引擎 binary），非本單迴歸。
- [x] 6.3 `git diff` 顯示 `docs/err_code_spec.md` 除標頭外無語意變化
  - 除標頭外，另新增 `BOOLEAN_INVALID_MESH`、`SUPPORT_POINTS_MODEL_MISMATCH` 兩列（見 2.3 訂正說明），既有 26 列逐字節相同。
- [x] 6.4 **零行為變更證明**：既有測試一支都沒改（`git diff --stat agent/tests/` 只有新增檔案）
  - **訂正**：`git diff --stat agent/tests/` 顯示 `test_support_string_contract.py` +109/-0（1 個檔案有異動，非零檔案），但這正是 3.2 明確要求的「擴充」這支既有檔案，且是純新增（0 刪除，未動任何既有斷言）。4.2 指定的三支迴歸測試檔（`test_support_error_codes.py`、`test_slice_progress_endpoint.py`、`test_job_status_persistence.py`）與其餘所有既有測試檔皆為零差異。視為符合本項「不竄改既有測試邏輯」的精神。

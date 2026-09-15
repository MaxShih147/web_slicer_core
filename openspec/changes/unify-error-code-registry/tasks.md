## 1. 建立真值登錄檔

- [ ] 1.1 建 `agent/error_codes.py`，宣告 28 筆 `ErrorCodeSpec`（`code` / `http_status` / `retryable` / `owner` / `note` / `engine_needles`）。`note` **逐字**抄自現有 `docs/err_code_spec.md` 的「說明」欄。
  - 指令：`python -c "from agent.error_codes import ALL; print(len(ALL))"`
  - 預期：印出 `28`
- [ ] 1.2 逐一標記 `owner`。判準：引擎在自身 process 內可判斷 → `engine`；需要 job／檔案系統／HTTP → `python`。
  - 指令：`python -c "from agent.error_codes import ALL; import collections; print(collections.Counter(s.owner for s in ALL))"`
  - 預期：`Counter({'engine': 14, 'python': 14})`
- [ ] 1.3 為 14 個 `owner=engine` 的 code 填入 `engine_needles`（自兩支 classifier 現有的對照表搬過來，不新增不刪減）。
  - 指令：`python -c "from agent.error_codes import ALL; print([s.code for s in ALL if s.owner=='engine' and not s.engine_needles])"`
  - 預期：`[]`

## 2. 產生器與 --check

- [ ] 2.1 Write tests：`test_error_code_registry.py` — 28 筆唯一、必填欄位齊全、`owner` 只有兩種值、`engine` 群必有 needles。
  - 指令：`pytest agent/tests/test_error_code_registry.py -q`
  - 預期：全綠
- [ ] 2.2 建 `agent/tools/error_codes.py`，實作 `--write`：產生 `docs/err_code_spec.md` 與 `docs/error_codes.json`，兩者開頭加「本檔自動產生，請勿手動編輯；改說明請編 `agent/error_codes.py`」標頭。
- [ ] 2.3 **驗證搬家無損**：執行 `--write` 後比對 md 的 diff。
  - 指令：`python -m agent.tools.error_codes --write; git diff --stat docs/err_code_spec.md`
  - 預期：**除新增標頭外無其他差異**。有差異代表 `note` 抄錯，必須修到零差異才能往下。
- [ ] 2.4 實作 `--check`：不寫檔、只比對，不一致回非零並印出應執行的指令。
  - 指令：`python -m agent.tools.error_codes --check; echo "exit=$?"`
  - 預期：`exit=0`
- [ ] 2.5 反向驗證 `--check` 有牙齒：手動改壞 md 一個字，再跑 `--check`。
  - 指令：`sed -i 's/非預期的伺服器錯誤/XXX/' docs/err_code_spec.md; python -m agent.tools.error_codes --check; echo "exit=$?"; git checkout docs/err_code_spec.md`
  - 預期：`exit=1`，訊息指出 `err_code_spec.md` 過期

## 3. 契約測試

- [ ] 3.1 Write tests：`test_error_code_contract.py` — 登錄檔每個 code 都能在 `errors.py` 找到對應 factory；反向亦然（`errors.py` 沒有登錄檔之外的 code）。
  - 指令：`pytest agent/tests/test_error_code_contract.py -q`
  - 預期：全綠
- [ ] 3.2 擴充引擎字串契約：`owner=engine` 的每條 `engine_needles` 必須出現在 `third_party/prusaslicer_fork` 原始碼。作法照抄 `test_support_string_contract.py`；fork 未 checkout 時 `pytest.skip`。
  - 指令：`pytest agent/tests/test_support_string_contract.py -q`
  - 預期：全綠（或 skip，若 submodule 未取出）
- [ ] 3.3 加入負向檢查：刻意變造一條 needle，斷言在原始碼中找不到（證明斷言有牙齒）。

## 4. 移除手抄 dict

- [ ] 4.1 `api_v2.py` 的 `_ERROR_CODE_FACTORIES` 改由登錄檔於執行期推導；推導不到 factory 時在**載入階段**拋錯，不得靜默退回 `JOB_FAILED`。
- [ ] 4.2 確認錯誤回應零變更。
  - 指令：`pytest agent/tests/test_support_error_codes.py agent/tests/test_slice_progress_endpoint.py agent/tests/test_job_status_persistence.py -q`
  - 預期：全綠，且**未修改任何一支既有測試**
- [ ] 4.3 全套回歸。
  - 指令：`pytest agent/tests -q`
  - 預期：全綠（既有 known failure 除外，執行前先記錄基準）

## 5. 掛上關卡

- [ ] 5.1 把 `python -m agent.tools.error_codes --check` 加進本地 pipeline / pre-commit。
- [ ] 5.2 更新 `docs/err_code_spec.md` 的維護說明（在登錄檔的檔頭註解中撰寫，由產生器輸出）。
- [ ] 5.3 確認 `docs/error_codes.json` 已進版控，供 DS-Online 的 `api/error_codes.json` 同步。

## 6. 驗收

- [ ] 6.1 `python -m agent.tools.error_codes --check` 回零
- [ ] 6.2 `pytest agent/tests -q` 全綠
- [ ] 6.3 `git diff` 顯示 `docs/err_code_spec.md` 除標頭外無語意變化
- [ ] 6.4 **零行為變更證明**：既有測試一支都沒改（`git diff --stat agent/tests/` 只有新增檔案）

## 0. 前置（不做完不要開始）

- [ ] 0.1 確認 `merge-engine-result-classifiers` 已關單。**未解開 exit-code 相依就動 C++，`INVALID_MODEL` 與 `MODEL_OUT_OF_BOUNDS` 會退化成 `JOB_FAILED`。**
  - 指令：`pytest agent/tests/test_exit_code_independence.py -q`
  - 預期：全綠（兩例為 `xfail`）
- [ ] 0.2 記錄回歸基準。
  - 指令：`pytest agent/tests -q 2>&1 | tail -3`
- [ ] 0.3 記錄目前 shipped 引擎資訊，交付時要比對。
  - 指令：`cat ../Bundle-Launcher/bundle-win/slicer-engine/engine_build_id.txt; git submodule status third_party/prusaslicer_fork`
  - 預期：記下 build id 與目前指標 commit

## 1. 建置環境（兩顆地雷）

- [ ] 1.1 **fork 切到分支 tip。** 依作業方式：過程中**不理會** superproject 記錄的指標，直接在 tip 上工作。
  - 指令：`cd third_party/prusaslicer_fork && git fetch origin && git checkout <branch> && git pull && git rev-parse HEAD`
  - 預期：記下這個 commit hash。**第 7 節要用它做一致性驗證。**
- [ ] 1.2 **CMake 套件登錄檔汙染防護。** 本機有三個 PrusaSlicer 系專案共用登錄檔，會互相汙染依賴路徑，症狀難查。設定階段 MUST 加旗標。
  - 指令：`cmake -B build -DCMAKE_FIND_USE_PACKAGE_REGISTRY=OFF -DCMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY=OFF ...`
  - 預期：依賴路徑全部落在本專案的 deps 目錄，不含其他 PrusaSlicer 專案的路徑
- [ ] 1.3 先做一次**未修改的基準建置**，確認環境可用。
  - 預期：build 成功，可用現有測試模型跑一次切片

## 2. 引擎：string table 與結構化輸出（先不動 return 1）

- [ ] 2.1 建立 C++ 側 `code → message` 對照表，涵蓋 `owner=engine` 的 16 個代號（原 14 ＋ 單 2 新增的 2 個）。代號字串
  - 指令：`python -c "from agent.error_codes import ALL; print(sum(1 for s in ALL if s.owner=='engine'))"`
  - 預期：`16`**逐字**取自 `agent/error_codes.py`，不自行命名。
- [ ] 2.2 實作結構化錯誤行輸出：單行 `PHZ_ERROR ` 前綴加 JSON，印到 **stdout**。
  - 格式：`PHZ_ERROR {"code":"...","fields":[...],"values":{...}}`
- [ ] 2.3 `fields` 使用後端 `SLAConfig` 的 snake_case 欄位名。**不要自創命名**——前端 `data-field` 已用相同拼法。
- [ ] 2.4 `PAD_CONFIG_INVALID` 的 `values` 攜帶算出的最小合法角度與實際值。
- [ ] 2.5 提供代號清單的機器可讀匯出（從 header 掃出或編譯期產生）。
- [ ] 2.6 重建，手動驗證輸出格式。
  - 指令：用一組違規底墊參數跑一次 CLI，`grep PHZ_ERROR` stdout
  - 預期：印出一行合法 JSON，`code` 為 `PAD_CONFIG_INVALID`，`values` 含 `51.4`

## 3. Python：加 EngineCode 比對器（兩層並存）

- [ ] 3.1 Write tests：`EngineCode` 命中時採用該代號；無 `PHZ_ERROR` 行時退回字串層；兩層對同一情境結果相同。
- [ ] 3.2 在 `agent/engine_rules.py` 新增 `EngineCode` 比對器，插在每列 `matchers` 的**最前面**。**字串層保留**。
- [ ] 3.3 未登錄代號的守門：`EngineCode` 命中但代號不在 `error_codes.py` 時退回 fallback，原文保留於 `detail`。
- [ ] 3.4 加契約測試：引擎匯出的代號清單 ↔ `error_codes.py` 的 `owner=engine` 子集，雙向對帳。
  - 指令：`pytest agent/tests/test_engine_code_contract.py -q`
  - 預期：全綠
- [ ] 3.5 **檢查點：既有規則測試零修改通過。**
  - 指令：`pytest agent/tests/test_support_classifier.py agent/tests/test_slicing_classifier.py -q; git diff --stat agent/tests/test_support_classifier.py agent/tests/test_slicing_classifier.py`
  - 預期：全綠，且 diff 無輸出
- [ ] 3.6 **檢查點：新舊兩層結果一致。** 對同一組失敗情境，分別用新引擎（有 `PHZ_ERROR`）與舊引擎（只有字串）的輸出樣本跑分類。
  - 預期：**每一組都回同一個代號。** 不一致就代表 2.1 的代號抄錯或 2.2 的觸發點放錯位置。
  - **這一步不過，不得進第 4 節。**

## 4. 引擎：修 15 處回傳型別

- [ ] 4.1 `CLI/ProcessActions.cpp` 的 15 處 `return 1` 改為 `return false`：L400 · 417 · 426 · 432 · 436 · 442 · 451 · 457 · 477 · 484 · 500 · 512 · 516 · 679 · 737。
  - 註：行號以查核當時的 tip 為準，分支改動後會位移。以函式與上下文比對，不要只認行號。
- [ ] 4.2 重建。
- [ ] 4.3 驗證挖空失敗的訊息變好。
  - 預期：`generate_hollow` 失敗時帶引擎原文（如 `interior mesh is empty. Try reducing wall thickness...`），不再只有罐頭訊息

## 5. D6：內部警告改印 stdout

- [ ] 5.1 在 `agent/error_codes.py` 新增三個代號（`owner=engine`）：支撐 mesh 為空、底墊因支撐樹為空而跳過、支撐 mesh 匯出失敗。
  - 指令：`python -m agent.tools.error_codes --write && python -m agent.tools.error_codes --check; echo "exit=$?"`
  - 預期：`exit=0`
- [ ] 5.2 引擎側：`Support mesh is empty`、`Pad skipped: the support tree is empty`（目前只進 BOOST_LOG）、`Failed to export support mesh to ...`（目前只印 stderr 無代號）改為輸出結構化錯誤行。
- [ ] 5.3 `ENGINE_RULES` 加對應三列。
- [ ] 5.4 通知前端補三個代號的四語系文案（DS-Online 側）。

## 6. 拆除 legacy exit-code 分支

- [ ] 6.1 刪除 `slicing_classifier.py` 的 `_LEGACY_EXIT0_ONLY_CODES` 分支。
  - 指令：`grep -n "_LEGACY_EXIT0_ONLY" agent/slicing_classifier.py`
  - 預期：無輸出
- [ ] 6.2 `test_exit_code_independence.py` 的兩個 `xfail` 改為正常斷言。因原標記為 `strict=True`，拆彈後不改標記會直接紅。
  - 指令：`pytest agent/tests/test_exit_code_independence.py -q`
  - 預期：全綠，且無 xfail
- [ ] 6.3 全套回歸，與 0.2 基準比對。
  - 指令：`pytest agent/tests -q`
  - 預期：無新增失敗

## 7. 交付：binary、供應鏈紀錄、指標

- [ ] 7.1 換 `Bundle-Launcher/bundle-win/slicer-engine/bin/` 底下的執行檔。
- [ ] 7.2 **同步更新供應鏈紀錄**（只換 binary 會讓稽核紀錄與實物不符）：`engine_build_id.txt`、`artifact-manifest.json`、`engine-artifact-manifest.json`、`sbom.spdx.json`、`source-chain.json`、`scan-report.json`。
- [ ] 7.3 **更新 superproject 的 submodule 指標**，指向 1.1 記下的 commit。
- [ ] 7.4 **一致性驗證（三者必須相同）**：
  - 指令：`git submodule status third_party/prusaslicer_fork`
  - 指令：`cd third_party/prusaslicer_fork && git rev-parse HEAD`
  - 指令：`grep -i commit ../Bundle-Launcher/bundle-win/slicer-engine/source-chain.json`
  - 預期：**三個 commit hash 完全相同。**
- [ ] 7.5 **指標更新 MUST 與依賴它的 Python 改動落在同一個 commit / PR。** 分兩次進的話，其他人跑契約測試會對舊 fork code 執行並誤判通過。
  - 檢查：該 PR 的 diff 同時包含 `third_party/prusaslicer_fork` 指標與 `agent/` 的改動

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

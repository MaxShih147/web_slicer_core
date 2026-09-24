## Context

`merge-engine-result-classifiers` 已經把規則表整理成「code 為主鍵、matchers 為列表、不含 exit_code」的形狀，就是為了讓本單只需**插一層比對器**，不必重做整張表。

已查證的環境事實：

| 項目 | 現況 |
|---|---|
| 引擎與 Python 的出版方式 | **同包**。`Bundle-Launcher/bundle-win/` 底下 `agent/` 與 `slicer-engine/` 在同一個 bundle，版本 `v1.0.5-rc4` |
| 更新機制 | `package.json` 無 auto-updater 設定，整包重裝 |
| 目前 shipped 引擎 | `engine_build_id.txt` = `20260827T113951Z` |
| superproject 記錄的 submodule 指標 | `2e10c16d4`（`v1.0.5-rc3-17-g2e10c16d4`），落後 bundle 版本 |
| fork 來源 | `git@github.com:MaxShih147/PrusaSlicer.git` |

同包出版意味著**正式環境不存在「新 Python ＋ 舊引擎」**，這決定了字串層可以在下一版就退場。

## Goals / Non-Goals

**Goals**

- 錯誤代號的真值方向反轉：引擎宣告代號，Python 只讀取。
- 引擎回報時攜帶動態數值，讓前端能顯示「目前需要 ≥ 51.4°」而非「參數不正確」。
- 修正 15 處回傳型別，讓失敗真的回報失敗。
- 拆除最後一處 exit-code 相依。

**Non-Goals**

- 不搬 `owner=python` 的 14 個代號進 C++。
- 不在本單刪除字串比對層（保留為第二層，下一版再刪）。
- 不改前端的 `BACKEND_ERROR_KEYS` 結構（只補 D6 三個新代號的文案）。
- message 不傳給 Python 或前端——人看的文案由前端 i18n 負責，引擎的 message 只服務 log 與 CLI 使用者。

## Decisions

### D1：工作流程——在分支 tip 上做，最後才更新指標

**決定**（依 RD 的作業方式）：

1. 進 `third_party/prusaslicer_fork`，checkout 對應 branch 並 pull 到 **tip**。**過程中不理會 superproject 記錄的指標。**
2. 在 tip 上完成所有 C++ 修改、建置、回歸。
3. **全部做完之後**，才更新 superproject 的 submodule 指標，並驗證一致性。

**一致性的定義（三者必須指向同一個 commit）**：

| 項目 | 來源 |
|---|---|
| superproject 記錄的 submodule 指標 | `git submodule status` |
| 實際建置所用的 commit | fork 的 `git rev-parse HEAD` |
| 打包進 bundle 的 binary | `slicer-engine/artifact-manifest.json` 與 `source-chain.json` 記載的 commit |

**風險與緩解**：指標更新之前，**其他人跑契約測試會用到舊的 fork code**——他們的測試通過，不代表你的改動正確。因此**指標更新必須與依賴它的 Python 改動落在同一個 commit / PR**，不得分兩次進。

### D2：結構化錯誤行印到 stdout，不印 stderr

**決定**：格式為單行 `PHZ_ERROR ` 前綴加一段 JSON，輸出到 **stdout**。

**理由**：stderr 混了 BOOST_LOG、依賴函式庫的警告、以及各種雜訊；stdout 目前只有少量結構化標記（`(supports only)`、`(pad only)` 等），比較乾淨。

**格式**：

```
PHZ_ERROR {"code":"<CODE>","fields":[...],"values":{...}}
```

- `code`：必填，取自引擎 string table。
- `fields`：選填，使用後端 `SLAConfig` 的 snake_case 欄位名。**前端 `SupportEditor.vue` 的 `data-field` 屬性已用相同命名，不需要任何轉換層。**
- `values`：選填，攜帶動態門檻與實際值。

**為什麼不只傳 code**：`PAD_CONFIG_INVALID` 的門檻由 `pad_wall_thickness / tan(slope) ≤ pad_brim_size` 推導，會隨參數變動。只傳 code，前端顯示不出「目前需要 ≥ 51.4°」，也標不出該紅哪一格。

### D3：message 留在 C++ 與 log，不往上傳

**決定**：引擎 string table 的 message **只服務 log 與 CLI 使用者**。

**理由**：前端早就不吃後端的 message——`axios.js:246` 是 `new BackendError(undefined, data.code, data.data)`，第一個參數（message 的位置）寫死 `undefined`。使用者看到的一律是前端四語系文案。

**但 Python 仍保存引擎原文到 `status.json` 的 `detail`**：那是 RD 除錯的資產，而且 stdout/stderr 本來就在 Python 手上（subprocess 抓的），不是額外傳輸成本。**不上 UI。**

### D4：`EngineCode` 插在 matchers 最前面，字串層保留

**決定**：`matchers = [EngineCode("<CODE>"), Substring("<英文字串>")]`。

**理由**：分層而非取代。本單先讓兩層並存並驗證新層命中率，確認每個 `owner=engine` 的代號都有 code token 之後，下一版才刪字串層（退場條件見 `merge-engine-result-classifiers` design D2）。

**不得在本單刪字串層**：刪了就沒有對照組，無法證明新層覆蓋完整。

### D5：Python 不得無條件信任引擎給的代號

**決定**：`EngineCode` 命中時，Python 仍 MUST 檢查該代號是否在 `error_codes.py` 登錄檔中。不在登錄檔的代號 MUST 退回 fallback，MUST NOT 原封不動往前端丟。

**理由**：引擎可能比 Python 新（開發環境、或未來出版方式改變）。未登錄的代號送到前端會查不到 i18n key，顯示成「未預期的錯誤」，比 fallback 更糟。

### D6：binary 換版要連供應鏈紀錄一起換

**決定**：`slicer-engine/` 底下的 `artifact-manifest.json`、`engine_build_id.txt`、`sbom.spdx.json`、`source-chain.json`、`scan-report.json` 必須與新 binary 同步更新。

**理由**：這些是供應鏈與去識別化的稽核紀錄。只換 `bin/` 底下的執行檔會讓紀錄與實物不符。

## Risks

| 風險 | 影響 | 緩解 |
|---|---|---|
| **CMake 套件登錄檔汙染** | 高（依賴抓到別的專案，症狀難查） | 本機有三個 PrusaSlicer 系專案共用登錄檔。建置前 MUST 加 `NO_PACKAGE_REGISTRY` 旗標。寫進 tasks 第 1 節 |
| 指標未與 Python 改動同批進 | 高（他人測試用舊 code 卻通過） | D1 的一致性三項檢查；指標與 Python 改動同一個 commit |
| 修 15 處 `return 1` 後某個代號退化 | 高 | `test_exit_code_independence.py` 是安全網，本單把兩個 `xfail` 轉正常斷言 |
| D6 三個新代號前端沒文案 | 中 | 登錄檔 `--check` ＋ 前端 `backendErrorKeys.spec.js` 對帳，兩道都會紅 |
| 引擎回歸耗時超出預期 | 中 | 本單刻意不與面板開放同批；回歸時間單獨估 |

## Migration

```
1. fork 分支 tip → 加 string table + 結構化輸出（先不動 return 1）
2. 建置 → Python 加 EngineCode 比對器 → 驗證新舊兩層結果一致
3. 才改 15 處 return 1 → 重建 → 回歸
4. 拆 legacy exit-code 分支、xfail 轉正常斷言
5. 換 bundle binary + 供應鏈紀錄
6. 最後更新 submodule 指標，驗證三項一致
```

**步驟 2 與 3 不可合併**：先讓兩層並存並證明結果相同，才動回傳型別。合併做的話，回歸出問題時分不清是 code table 還是 exit code 造成的。

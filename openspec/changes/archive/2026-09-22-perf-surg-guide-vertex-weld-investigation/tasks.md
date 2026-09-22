## 1. 調查與補正內容確認（已於本提案建立前完成，本節為留存紀錄）

- [x] 1.1 確認 vertex-weld 調查報告（`weld_and_build_vertex_weld_investigation_2026-09-22.md`）與其 JSON 副本存在且可讀取
- [x] 1.2 確認 2026-09-22 文件補正已套用：§8 candidate 2 預估完整 core 改善數字更正為 SurgicalGuide_1～4 約 0.61～0.82%、SurgicalGuide_1M 約 0.146%（標示不穩定）
- [x] 1.3 確認補正公式（`stage_over_core_pct × loop/stage × candidate_loop_improvement_pct/100`）已寫入報告 §8 與 JSON `post_review_correction_2026_09_22` 節點
- [x] 1.4 確認 §6.3 Q4 的 `del vmap` 複雜度敘述已由 `O(1)`／可忽略修正為約 `O(N)`
- [x] 1.5 確認 §6.3 Q3／Q7 記憶體結論已改為明確標示 121.5 MiB 為 structural dead-object estimate，非已證實可回收之 peak-memory 數字
- [x] 1.6 確認 §9 已移除「edge-map `≥5%` 門檻為 vertex-weld 共用正式門檻」之隱含敘述，改以 vertex-weld 自身理論上限與需求作為獨立判斷依據
- [x] 1.7 確認補正未修改任何既有 raw timing／結構統計／記憶體原始資料

## 2. OpenSpec 決策紀錄建立

- [x] 2.1 建立 `proposal.md`，記載 Why／What Changes／Capabilities／Impact，明示本提案不變更任何 production 程式碼
- [x] 2.2 建立 `specs/surgical-guide-vertex-weld-performance-decision/spec.md`，以 `### Requirement:` + `#### Scenario:` 格式記載：理論上限為主要依據、candidate 2 補正公式與數值、記憶體估算用詞收斂、`del vmap` 複雜度收斂、不套用 edge-map 門檻、不影響既有優化與 `STOP_EDGE_MAP`
- [x] 2.3 建立 `design.md`，記載決策脈絡（Context）、範圍界線（Goals／Non-Goals）、四項關鍵決策（D1～D4）與風險／取捨
- [x] 2.4 執行 `openspec validate perf-surg-guide-vertex-weld-investigation --strict`，確認 proposal／specs／design 格式與 delta 皆有效（通過）
- [x] 2.5 執行 `openspec archive perf-surg-guide-vertex-weld-investigation`，將本決策紀錄併入 `openspec/specs/`，完成歸檔——已執行（2026-09-22），封存為 `openspec/changes/archive/2026-09-22-perf-surg-guide-vertex-weld-investigation/`，living spec 已建立於 `openspec/specs/surgical-guide-vertex-weld-performance-decision/spec.md`（含補寫之 Purpose 段落）

## 3. 邊界驗證

- [x] 3.1 確認 `agent/auto_orient_surg_guide.py` 與 `agent/tests/` 沒有任何差異——已執行 scoped 檢查 `git status --short agent/auto_orient_surg_guide.py agent/tests/`，輸出為空。**注意**：這是針對這兩個特定路徑的 scoped 檢查，不代表整個 repository 的 `git status --short` 為空——repository 整體在本次工作開始前已存在 `M third_party/prusaslicer_fork` 及 10 個既有 untracked files，本次另外新增 `openspec/changes/perf-surg-guide-vertex-weld-investigation/` 為 untracked 目錄；repository 整體並非 clean 狀態，僅 production Python 與測試檔案本身沒有因本提案產生新增差異
- [x] 3.2 確認既有四輪 Surgical Guide Auto Orient 優化對應之 spec（`openspec/specs/surgical-guide-grow-patches-performance`、`surgical-guide-drill-patch-pca-performance`、`surgical-guide-bfs-region-growing-performance`、`surgical-guide-concave-chunking-performance`）皆存在且未被本提案修改——已確認（`git status --short openspec/` 僅顯示本次新增之 `openspec/changes/perf-surg-guide-vertex-weld-investigation/`）
- [x] 3.3 確認 `STOP_EDGE_MAP` 決策先前依指示未建立對應 OpenSpec spec，故本提案無「重新開啟」之對象；`openspec/specs/` 下亦無同名項目被本提案觸及——已確認

## 4. 審閱意見核對與修正（使用者審閱後回饋，本節記錄核對結果）

- [x] 4.1 確認 `design.md` D2／Context 對舊版算術錯誤的因果推定在數學上不成立（loop/stage 比例約 0.97～0.98，漏乘該比例至多造成約 2～3% 差異，不足以解釋約 3～4 倍落差）——**成立，已修正**：D2 已移除因果推定敘述並保留數學驗算。**注意**：本項當時的完成狀態記錄不準確——`design.md` 的 Context 實際上有兩段，修正僅套用到第一段（`STOP_EDGE_MAP` 描述），第二段（調查結論段）仍保留舊因果推定句，直到第二次審閱（見 4.9）才發現並修正。特此記錄此落差以供追溯。
- [x] 4.2 確認 `design.md` D4 是否混淆「vertex-weld 理論上限（3.14～3.49%）」與「candidate 2 預估收益（<1%）」——**成立，已修正**：明確拆分為兩個獨立數值並分別標示層級，理論上限本身未低於 1%
- [x] 4.3 確認 `tasks.md` 3.1 的 `git status --short` 敘述是否誤植為整個 repository 為空——**成立，已修正**：改為明示 scoped 檢查範圍，並補充 repository 整體非 clean 狀態之事實
- [x] 4.4 確認 `spec.md` 各 Scenario 是否以 repo 外調查報告作為 WHEN 條件、致使 archived spec 依賴外部檔案才能解讀——**成立，已修正**：全部 Scenario 改寫為「任何人／未來重新評估時」等自足條件，直接陳述應採用的數值本身，不再以「檢視某份外部文件」作為前提
- [x] 4.5 確認 `STOP_EDGE_MAP` 是否被誤述為「不值得投入 prototype」而掩蓋了「prototype 已實際建立並完整量測、僅未達採用門檻」的事實——**成立，已修正**：`proposal.md`、`design.md`、`spec.md` 皆改為明示 Candidate #3 prototype 已建立並完整量測（correctness／downstream／performance／memory A/B），僅因未達門檻而不採用
- [x] 4.6 確認「8/8 synthetic／真實模型 exact match」的描述是否可能被誤讀為 8 個 synthetic 外加真實模型——**成立，已修正**：全部改為「6 個 synthetic cases + 2 個真實模型，合計 8/8 cases exact match」
- [x] 4.7 確認 121.5 MiB 是否被整體描述為「純估算」而未區分量測與估算部分——**部分成立，spec.md 已加強、design.md 當時遺漏**：`spec.md` 原已分別標示 `quant`／`rep_of_vertex`（量測）與 `vmap`（結構性估算）三者組成；但 `design.md` D3 當時仍寫著「121.5 MiB 僅標示為 structural dead-object estimate，**非量測所得**」，把合計數字整體描述為未量測，與 spec.md 的分層敘述不一致，直到第二次審閱（見 4.10）才發現並修正
- [x] 4.8 重新執行 `openspec validate perf-surg-guide-vertex-weld-investigation --strict`，確認修正後格式與 delta 仍有效（通過）

## 5. 第二次審閱意見核對與修正（使用者複查後回饋，發現前一輪修正不完整）

- [x] 4.9 確認 `design.md` Context 第二段（調查結論段）是否仍保留已判定不成立的舊因果推定「把候選方案僅針對 per-vertex loop 量到的改善百分比，直接套用在整個 stage 對 core 的占比上，未先換算 loop 對 stage 的占比」——**成立**：前一輪（4.1）僅修正了 Context 第一段（`STOP_EDGE_MAP` 描述），第二段的因果推定句未被觸及，仍原樣保留。**已修正**：移除該因果推定句，改為與 D2 一致的中性敘述（「換算 loop-level timing 為 full-core gain 時的算術錯誤」＋「現有資料無法可靠還原確切步驟，詳見 D2」）
- [x] 4.10 確認 `design.md` D3 是否仍把整個 121.5 MiB 描述為「非量測所得」——**成立**：D3 條列項第一點原句為「121.5 MiB 僅標示為 structural dead-object estimate，非量測所得、非已證實可回收的 peak-memory 數字」，未區分 `quant`／`rep_of_vertex`（量測）與 `vmap`（結構性估算），與同一小節上方（D3 開場段）及 `spec.md` 的分層敘述不一致。**已修正**：改寫為明確區分三者組成，並說明「非量測所得」指的是「三者合計後能否轉化為可回收 peak-memory reduction」這件事未經 A/B 驗證，而非指三個組成部分本身都是估算值
- [x] 4.11 確認 candidate 2 的「8/8 exact match」描述是否可能讓讀者誤以為整個候選方案（而非僅分組公式的 `rep_of_vertex` 輸出）已通過正確性驗證，且完整 production 整合／downstream bit-exact A/B／memory A/B 已完成——**成立**：`proposal.md`、`spec.md`、`design.md`（Non-Goals 與 D4）原本的措辞未明確限定驗證範圍，容易被讀成「candidate 2 整體已驗證通過」。**已修正**：四處皆改為明確敘述「驗證範圍僅止於分組公式產生的 `rep_of_vertex` 輸出，與 production／mirror 逐元素比對」，並列舉三項明確未執行的項目（完整 `_weld_and_build()` production 整合、downstream bit-exact A/B、peak-memory A/B）；`spec.md` 並新增一條專屬 Scenario（「Candidate 2 正確性驗證範圍不得被誇大」）防止未來誤引用
- [x] 4.12 重新執行 `openspec validate perf-surg-guide-vertex-weld-investigation --strict`，確認二次修正後格式與 delta 仍有效（通過）
- [x] 4.13 重新確認 repository 整體狀態（`git status --short --branch`）與二次審閱前一致，僅本變更目錄本身有內容異動，無其他新增檔案

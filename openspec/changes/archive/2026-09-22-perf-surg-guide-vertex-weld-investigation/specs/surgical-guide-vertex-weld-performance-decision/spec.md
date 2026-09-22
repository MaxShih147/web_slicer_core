## ADDED Requirements

### Requirement: 完整 core 理論改善上限為 `STOP_VERTEX_WELD` 決策的主要依據

Vertex quantization／weld 子階段（`agent/auto_orient_surg_guide.py::_weld_and_build()` L227-243）的停止決策 SHALL 以「即使完全消除該階段，完整 core（`compute_auto_orientation_surg_guide_detail()`）理論改善上限仍僅約 3.14～3.49%（五個代表模型：SurgicalGuide_1～4、SurgicalGuide_1M）」作為主要、不依賴受污染 timing 的判斷依據。此上限數字 SHALL 僅以未受執行環境干擾之基準量測（`_weld_and_build()`／完整 core 各子階段占比基準）為來源，不得以任何受當次執行環境（thermal／contention）干擾之重新量測數值取代或動搖。

#### Scenario: 未來引用此決策時的理論上限數值
- **WHEN** 任何人（含未來重新評估此子階段時）需要引用 vertex-weld 停止決策的完整 core 理論改善上限
- **THEN** 引用值 SHALL 為約 3.14～3.49%（依五個代表模型：SurgicalGuide_1～4、SurgicalGuide_1M）
- **AND** 該數字 SHALL 不依賴任何特定執行環境下（含受 thermal／contention 干擾者）重新量測之 `_weld_and_build()`／完整 core 數值才能成立——即，其正確性不因原始調查報告或其原始資料檔案是否仍可取得而改變

### Requirement: Candidate 2 預估完整 core 改善 SHALL 以補正公式計算並標示不穩定性

`np.unique`-based 向量化分組候選方案的**分組公式產生之 `rep_of_vertex` 輸出**，已通過正確性驗證（與 production／mirror 之 `rep_of_vertex` 逐元素比對，6 個 synthetic cases + 2 個真實模型，合計 8/8 cases exact match）。此驗證範圍 SHALL 明確限定於該公式輸出本身，MUST NOT 被描述或引用為「完整候選方案／完整 prototype 已通過正確性驗證」——該輪調查明確未執行完整 `_weld_and_build()` production 整合、downstream（`_grow_patches()`／`_is_drill_patch_by_edges()`／`detect_concave_faces()`／最終 `rotation_rad`）bit-exact A/B，亦未執行該候選方案的 peak-memory A/B。基於此已驗證範圍，其預估完整 core 改善 SHALL 依下列公式計算：

```text
estimated_core_gain_pct =
    stage_over_core_pct
    × (production_loop_median / vertex_weld_stage_median)
    × (candidate_loop_improvement_pct / 100)
```

補正後數值 SHALL 為：SurgicalGuide_1 約 0.823%、SurgicalGuide_2 約 0.681%、SurgicalGuide_3 約 0.631%、SurgicalGuide_4 約 0.609%（合併敘述為「約 0.61～0.82%」）；SurgicalGuide_1M 約 0.146%，但因其量測輸入受該輪執行環境（thermal／contention）干擾，SHALL 標示為不穩定估算，MUST NOT 當作精確 production 預測。舊版報告曾將此數值誤算為約 0.16～0.22%，該數字 SHALL 視為已撤回的算術錯誤。由於現有資料無法可靠還原舊計算當時實際執行的確切步驟，文件 MUST NOT 對錯誤的具體成因（例如是否漏乘某一項換算比例、是否誤用某個中間變數）做出推定性描述——只要一項推定的因果機制無法在數學上重現舊數字與補正數字間的實際差距，就 MUST NOT 採用。正式紀錄只需保留正確公式、正確輸入與補正後數值本身。

#### Scenario: Candidate 2 正確性驗證範圍不得被誇大
- **WHEN** 任何人描述 candidate 2 的正確性驗證狀態
- **THEN** 該描述 SHALL 明確限定驗證對象為「分組公式產生的 `rep_of_vertex` 輸出，與 production／mirror 逐元素比對」
- **AND** 該描述 MUST NOT 使讀者誤以為完整 `_weld_and_build()` production 整合、downstream bit-exact A/B（`_grow_patches()`／`_is_drill_patch_by_edges()`／`detect_concave_faces()`／`rotation_rad`）或該候選方案的 peak-memory A/B 已經完成——這三項該輪調查皆未執行

#### Scenario: 未來引用此決策時的 candidate 2 預估值
- **WHEN** 任何人需要引用 candidate 2 的預估完整 core 改善數值
- **THEN** SurgicalGuide_1～4 SHALL 引用為約 0.61～0.82%（不得引用約 0.16～0.22% 作為現行結論）
- **AND** SurgicalGuide_1M SHALL 引用為約 0.146%，並同時附帶「量測受當次執行環境干擾、僅能視為不穩定估算，不得當作精確 production 預測」之說明
- **AND** 上述引用 SHALL 不依賴原始調查報告或其 JSON 原始資料檔案是否仍存在或可取得

#### Scenario: 舊版錯誤數字不推定成因
- **WHEN** 任何文件提及舊版約 0.16～0.22% 的數字
- **THEN** 該文件 SHALL 僅將其標示為「換算時的算術錯誤」並予以撤回
- **AND** 該文件 MUST NOT 對該錯誤的具體成因做出推定性敘述，亦 MUST NOT 提出一個無法在數學上重現實際落差（約 3～4 倍）的因果解釋

### Requirement: Vertex-weld 記憶體 dead-object 估算 SHALL 標示為結構性估算，非已證實可回收之 peak-memory 數字

在 SurgicalGuide_1M 上，`quant`（約 11.13 MiB）與 `rep_of_vertex`（約 1.85 MiB）為 NumPy 陣列 `.nbytes` **量測值**；`vmap`（約 108.5 MiB）為 Python dict／tuple／int 物件的 **結構性估算**（非 measured RSS）。三者合計約 121.5 MiB，代表「進入 edge-map 前已不再需要卻仍存活」的物件——這個合計數字本身（quant／rep_of_vertex 部分為量測、vmap 部分為估算）SHALL 明確標示為 structural dead-object estimate，MUST NOT 描述為已證實可回收的 peak-memory 數字，亦 MUST NOT 描述為已證明無效。該輪調查未執行 early-release（提前 `del`）或候選方案的 peak-memory A/B 量測，相關文件 SHALL 註明此事實。

#### Scenario: 記憶體結論不宣稱已證實有效或無效
- **WHEN** 任何人引用約 121.5 MiB 的記憶體機會數字
- **THEN** 引用 SHALL 同時註明其組成：`quant`（約 11.13 MiB，量測）、`rep_of_vertex`（約 1.85 MiB，量測）、`vmap`（約 108.5 MiB，結構性估算）
- **AND** 引用 SHALL 明示該輪調查未執行 early-release 或 candidate 的 peak-memory A/B 量測
- **AND** 引用 MUST NOT 宣稱提前釋放這些物件「已證實」會降低或不會降低最終 peak memory

### Requirement: `del vmap` 的容器解構成本 SHALL 描述為 O(N)，不得寫成 O(1)

若 `del vmap` 使該 dict 的 reference count 歸零，CPython SHALL 需要遍歷並釋放約 486K 筆 dict entries、tuple 與 Python int objects；此容器解構成本 SHALL 描述為約 O(N)（N 為 vertex 數量），MUST NOT 描述為 O(1) 或時間影響可忽略。相關文件 SHALL 同時說明：這些物件原本也會在 `_weld_and_build()` 結束、frame 清理時被釋放，提前刪除主要是將清理時點提前，並可能讓後續 edge-map 重用 allocator 記憶體；在未經 A/B 量測的情況下，MUST NOT 宣稱提前刪除必然降低 wall time、必然沒有時間成本，或必然降低最終 peak memory。

#### Scenario: 複雜度敘述使用 O(N) 而非 O(1)
- **WHEN** 任何人描述 `del vmap` 的效能／記憶體影響
- **THEN** 該描述 SHALL 將其容器解構成本表示為約 O(N)
- **AND** 該描述 MUST NOT 將整個 `del vmap` 動作描述為 O(1) 或時間影響可忽略
- **AND** 該描述 SHALL 同時說明此清理原本就會在函式結束時發生，提前刪除只是移動清理時點，未經量測不得宣稱其必然影響 wall time 或 peak memory

### Requirement: 不得將 edge-map prototype 的 `≥5%` 驗收門檻套用為 vertex-weld 共用正式門檻

Edge-map Candidate #3 prototype 所定義的效能驗收門檻（例如 SurgicalGuide_1M `≥5%` 完整 core 改善）SHALL 僅視為該輪 prototype 自身的驗收設計，MUST NOT 在 vertex-weld 相關文件中被描述為 vertex-weld 的共用或既定正式門檻。`STOP_VERTEX_WELD` 決策 SHALL 僅依據 vertex-weld 自身的兩個獨立數值作出判斷，且 MUST NOT 將兩者混為同一件事：(1) 完整消除整個 stage 的理論上限，約 3.14～3.49%；(2) 唯一其分組公式輸出已驗證正確之候選方案（candidate 2，驗證範圍僅止於 `rep_of_vertex`）的實際可達成預估收益，遠低於該理論上限，約 0.61～0.82%（SurgicalGuide_1-4）與不穩定的約 0.146%（SurgicalGuide_1M）——後者才是低於 1% 的數字，前者本身並未低於 1%，只是同樣偏低。加上「目前無顯著記憶體需求」，三者共同構成停止依據。

#### Scenario: 門檻歸屬不得混淆
- **WHEN** 任何人描述 `STOP_VERTEX_WELD` 決策的理由
- **THEN** 該描述 MUST NOT 將 edge-map 的 `≥5%` 門檻表示為 vertex-weld 的共用或正式驗收門檻
- **AND** 該描述 SHALL 明示該決策是依據 vertex-weld 自身數據獨立作出

#### Scenario: 理論上限與候選方案預估值不得混淆為同一數字
- **WHEN** 任何人在同一段落中同時提及「理論上限」與「候選方案實際預估收益」
- **THEN** 該描述 SHALL 分別標示兩者的數值（理論上限約 3.14～3.49%；候選方案預估收益約 0.61～0.82%／不穩定的約 0.146%）
- **AND** 該描述 MUST NOT 以「理論上限本身低於 1%」之類的敘述，把候選方案層級的數字誤植為理論上限層級的數字

### Requirement: 本決策不影響既有已完成優化，亦不重新開啟 `STOP_EDGE_MAP`

`STOP_VERTEX_WELD` 決策 SHALL 不修改、不重新開啟、也不要求重新驗證下列既有成果：`_grow_patches()` patch statistics 優化、`_is_drill_patch_by_edges()` PCA 優化、fixed-seed BFS region growing 優化、`detect_concave_faces()` 16K chunking 優化，以及先前已結案的 `STOP_EDGE_MAP` 決策（該決策本身代表 Candidate #3 prototype 已實際建立並完整量測，但未達採用門檻而不併入 production——並非未建立 prototype）。本提案本身 SHALL 不對 `agent/auto_orient_surg_guide.py` 或任何測試檔案引入程式碼變更；本提案採納並歸檔後，repository 中除本次新增的 OpenSpec 變更本身外，SHALL 不含任何本提案造成的新增差異——但 repository 整體 SHALL 得以維持先前既有的未提交異動（例如既有 modified／untracked 檔案），本提案 MUST NOT 被解讀為要求 repository 整體處於乾淨（clean）狀態。

#### Scenario: 既有優化與決策維持不變
- **WHEN** 本提案被採納並歸檔
- **THEN** `_grow_patches()`、`_is_drill_patch_by_edges()`、fixed-seed BFS、`detect_concave_faces()` 16K chunking 對應之既有 spec SHALL 維持原狀，不因本提案而變更
- **AND** `STOP_EDGE_MAP` 決策 SHALL 維持結案狀態，不因本提案而重新開啟

#### Scenario: Production 與測試檔案零異動，但 repository 整體不要求乾淨
- **WHEN** 檢查本提案對 repository 的影響
- **THEN** `agent/auto_orient_surg_guide.py` 與所有既有測試檔案 SHALL 沒有因本提案產生任何差異（scoped 檢查：僅比對這些特定路徑）
- **AND** 此檢查 SHALL NOT 等同於「repository 整體 `git status` 為空」——repository 整體可能仍含有本提案之前就存在的 modified／untracked 檔案，這些檔案的存在 SHALL NOT 視為本提案的缺陷

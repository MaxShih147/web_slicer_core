## Context

`_weld_and_build()`（`agent/auto_orient_surg_guide.py:225`）依序執行 vertex quantization／weld（:227-243）、face remap、face properties、edge-map／adjacency 四個子階段。edge-map／adjacency 子階段已於獨立調查結案（`STOP_EDGE_MAP`）：該輪調查實際建立並完整量測了 Candidate #3 prototype（含 correctness suite、downstream bit-exact A/B、performance A/B、memory A/B），但其效能未達預先設定的採用門檻，因此決定不採用、不併入 production，也不再繼續 edge-map 方向的後續最佳化。該輪調查的 corrected report 同時量出 vertex-weld 子階段約占 `_weld_and_build()` 10～13%、完整 core 3.1～3.5%，是僅次於 edge-map 的第二大子階段，因此需要一輪獨立、只讀（read-only）的後續調查。

該調查（2026-09-22）以 repo 外 harness 對五個代表模型（SurgicalGuide_1～4、SurgicalGuide_1M）進行 source／consumer map、量化語意還原、synthetic observation、per-stage timing、memory／lifetime 分析與候選方案比較，結論為 `STOP_VERTEX_WELD`。事後審查發現該報告 §8 的 candidate-2 預估完整 core 改善計算有算術錯誤（換算 loop-level timing 為 full-core gain 時的算術錯誤，舊版誤算約 0.16～0.22%，補正後約 0.61～0.82%），已於同日（2026-09-22）以「純文件補正」方式修正，補正版數字與公式已寫入報告與其 JSON 副本。現有資料無法可靠還原舊版計算當時實際執行的確切步驟，因此不對錯誤的具體成因做出推定性描述——詳見 D2。

本提案的目的是把調查結論（含補正後數字）以 OpenSpec 形式正式留存，作為決策紀錄，供未來重新評估此子階段時依循；**不涉及任何程式碼變更**。

## Goals / Non-Goals

**Goals:**
- 把 vertex-weld 效能調查（含 2026-09-22 補正）的量化結論，以可追溯、可驗證的 OpenSpec 決策紀錄形式留存。
- 明確記載 `STOP_VERTEX_WELD` 的主要依據（完整 core 理論上限 3.14～3.49%）與次要佐證（candidate 2 補正後預估改善），並清楚區分兩者的可信度層級。
- 明確劃定本決策與既有四輪優化、`STOP_EDGE_MAP` 決策之間互不影響的邊界，避免未來誤以為本決策隱含重新開啟或修改它們。
- 記錄「純文件補正」本身的性質（無新量測、不推定舊錯誤成因）以維持補正的可信度與可追溯性。

**Non-Goals:**
- **不**實作任何 vertex-weld 最佳化 prototype（`np.unique`-based 向量化分組候選方案僅其分組公式產生的 `rep_of_vertex` 輸出已完成正確性驗證，並對該公式本身做過初步 timing probe；完整 `_weld_and_build()` production 整合、downstream bit-exact A/B、peak-memory A/B 皆**未執行**，明確不進入 production）。
- **不**重新執行任何 profiling、benchmark 或模型測試（本提案完全基於既有原始資料）。
- **不**變更 `agent/auto_orient_surg_guide.py` 或任何測試檔案。
- **不**補做記憶體 early-release 或 peak-memory A/B（因目前無顯著記憶體需求，且預估完整 core 收益不足以正當化投入）。
- **不**推定 2026-09-22 補正前舊版算術錯誤的具體成因（現有資料無法可靠還原舊計算步驟）。

## Decisions

### D1：`STOP_VERTEX_WELD` 的主要依據為完整 core 理論上限，非 candidate 2 的預估值

即使完整消除整個 vertex-weld 階段，完整 core 改善上限也僅約 **3.14～3.49%**（五模型皆然），此數字完全以既有、未受本輪執行環境干擾之基準量測（corrected edge-map report 的 `_weld_and_build()`／完整 core 基準）為依據，不依賴本輪任何 timing 量測。選擇以此作為主要依據，而非 candidate 2 的預估改善值，是因為理論上限與候選方案是否可行、是否被正確實作皆無關——即使未來出現更好的候選方案，只要 vertex-weld 占比不變，上限依然成立；反之若僅以 candidate 2 的預估值為主要依據，決策的穩健性會被單一候選方案的量測品質（尤其是 SurgicalGuide_1M 的不穩定估算）拖累。

**替代方案考量**：曾考慮以「candidate 2 補正後預估改善（0.61～0.82% / 不穩定的 0.146%）」作為主要依據，但因 SurgicalGuide_1M 該數值受執行環境干擾、可信度較低，若以其為主要依據，決策本身也會連帶被質疑其穩健性；改以不受該干擾影響的理論上限為主要依據，佐以 candidate 2 數字作為次要、支持性的脈絡說明。

### D2：Candidate 2 預估完整 core 改善採用「先還原 loop 對 stage 占比，再乘以 stage 對 core 占比」的兩層換算公式

```text
estimated_core_gain_pct =
    stage_over_core_pct
    × (production_loop_median / vertex_weld_stage_median)
    × (candidate_loop_improvement_pct / 100)
```

candidate 2（`np.unique(axis=0, return_index=True, return_inverse=True)`）僅取代 per-vertex loop（item 4），而非整個 vertex-weld stage（loop 僅占 stage 96.8～98.4%，非 100%），因此正確公式須經過上述兩層換算。

**舊版錯誤的具體成因不予推定**：舊版報告將此數字誤算為約 0.16～0.22%（補正後為約 0.61～0.82%，SurgicalGuide_1-4）。需特別注意：loop 對 stage 的占比在五模型上都接近 1（約 0.97～0.98），若舊版計算僅是「漏乘這一項」，其結果與補正後數值相比至多只會有約 2～3% 的差異，不足以解釋約 3～4 倍的落差；換言之，「漏乘 loop/stage 比例」本身不足以完整說明舊版數字的實際來源。由於現有資料（報告文字、JSON 原始欄位）無法可靠還原舊版計算當時實際執行的確切步驟，本文件與相關 spec 僅記錄「舊版在把 loop-level timing 換算為 full-core gain 時發生算術錯誤、已撤回」，MUST NOT 對錯誤的具體成因（是否漏乘某一項、是否誤用了某個中間變數，或其他可能性）做出推定性描述；正式紀錄只保留正確公式、正確輸入與補正後數值。

補正後數值（皆為既有原始資料重新計算，非新量測）：

| 模型 | stage/core（phase-1 基準） | loop/stage（本輪） | candidate loop 改善（本輪） | 補正後預估完整 core 改善 |
|---|---:|---:|---:|---:|
| SurgicalGuide_1 | 3.266% | 0.9732 | 25.90% | **≈0.823%** |
| SurgicalGuide_2 | 3.348% | 0.9783 | 20.78% | **≈0.681%** |
| SurgicalGuide_3 | 3.138% | 0.9740 | 20.64% | **≈0.631%** |
| SurgicalGuide_4 | 3.279% | 0.9703 | 19.15% | **≈0.609%** |
| SurgicalGuide_1M | 3.494% | 0.9832 | 4.24% | **≈0.146%**（不穩定，受本輪執行環境干擾） |

### D3：記憶體與複雜度敘述改為明確標示「未證實」而非「已證實有利」

原報告 §6.3 曾將約 121.5 MiB（`quant` 11.13 MiB 量測 + `rep_of_vertex` 1.85 MiB 量測 + `vmap` 108.5 MiB **結構性估算**）的 dead-object 機會，以及 `del vmap` 的時間成本（原誤寫為 `O(1)`／可忽略），描述得比實際量測支持的更確定。補正後：

- 121.5 MiB 的組成須分層看待：`quant`（約 11.13 MiB）與 `rep_of_vertex`（約 1.85 MiB）為 NumPy `.nbytes` **量測值**；`vmap`（約 108.5 MiB）為 Python dict／tuple／int 物件的**結構性估算**（非 measured RSS）。三者合計約 121.5 MiB 這個總數，其「能否轉化為可回收的 peak-memory reduction」**未經 A/B 量測**——這是合計數字被標示為 **structural dead-object estimate** 的原因，並非指三個組成部分本身都是估算值；本輪未執行 early-release 或 candidate 的 memory A/B。`PeakWorkingSetSize` 在量測開始前已有較高的 process-lifetime historical peak，因此「vertex-weld 階段本身未推高 peak」不能反向證明「提前釋放對後續 edge-map peak 完全沒有幫助」。
- `del vmap` 若使該 486K-entry dict 的 reference count 歸零，CPython 需遍歷並釋放全部 dict entries／tuple／int objects，此容器解構成本 SHALL 描述為約 **O(N)**，不得寫成 `O(1)`。同時說明：這些物件本來就會在函式結束、frame 清理時被釋放，提前 `del` 主要是把清理時點提前，未經 A/B 量測不能宣稱其必然降低 wall time 或必然降低最終 peak memory。

這兩項修正皆為「收斂用詞的確定性層級」，不改變任何已回報的數字本身（11.13 MiB／1.85 MiB／108.5 MiB／121.5 MiB 皆維持不變）。

### D4：不將 edge-map 的 `≥5%` 門檻套用為 vertex-weld 共用門檻

Edge-map Candidate #3 prototype 的驗收門檻（例如 SurgicalGuide_1M `≥5%` 完整 core 改善）是該輪 prototype 自身針對其候選方案設計的驗收線，兩輪調查的候選方案、風險輪廓、資料規模皆不同，直接套用會造成「vertex-weld 因為沒有明確共用門檻的文件依據就被要求達到別的調查訂的標準」的邏輯混淆。`STOP_VERTEX_WELD` 改以 vertex-weld 自身的兩個獨立數值作為判斷依據，兩者層級不同、不可混用：(1) **完整消除整個 stage 的理論上限**約 3.14～3.49%——這是即使不管任何候選方案是否可行都成立的硬上限；(2) **唯一其分組公式輸出已驗證正確之候選方案（candidate 2，驗證範圍僅止於 `rep_of_vertex`，見 Non-Goals）的實際可達成預估收益**，遠低於該理論上限，僅約 0.61～0.82%（SurgicalGuide_1-4）與不穩定的約 0.146%（SurgicalGuide_1M）——這兩個數字才是低於 1% 的部分，理論上限本身（3.14～3.49%）並未低於 1%，只是本身已偏低。決策同時參考「理論上限偏低」與「已知候選方案的實際收益更低、且不穩定」兩者，並加上「目前無顯著記憶體需求」，三者共同構成停止依據，不引用 edge-map 的數字作為比較基準。

## Risks / Trade-offs

- **[風險] 決策紀錄以 OpenSpec 形式留存，但未來若模型分布大幅改變（例如近重複 vertex 密度遠高於目前 ≤0.0021% 的碰撞率），理論上限與 candidate 2 的預估值可能不再適用 → [緩解] Requirement 中明確記載本決策依據的量化基礎（五模型結構統計、理論上限公式），未來重新評估時可直接比對新模型的碰撞率／占比是否已偏離本次基準，而非重新從零調查。**這不是本提案要處理的事項**，僅留下可比對的基準供未來判斷是否需要重啟調查。
- **[風險] SurgicalGuide_1M 的 candidate 2 估算值（0.146%）本身不穩定，可能被後續讀者誤引為精確數字 → [緩解] Requirement 與本文件皆重複標示其「受執行環境干擾、僅為不穩定估算」，且明確指出決策不依賴此數字。
- **[風險] 記憶體 121.5 MiB 機會未經驗證，可能被誤解為「已知可回收」而被引用於其他決策 → [緩解] Requirement 明確要求 MUST NOT 描述為已證實可回收，且說明未執行 A/B 的事實。
- **[取捨] 本提案不補做任何量測即歸檔，換取的是「不必再次投入 profiling 資源在一個理論上限已經很低的子階段」；代價是記憶體面向的「是否值得回收」問題仍然懸而未決 → 此為刻意的範圍取捨（見 Non-Goals），非遺漏。

## Migration Plan

不適用——本提案不變更任何程式碼、API 或部署行為，僅新增決策紀錄型 spec。歸檔（`openspec archive`）後即完成，無需任何部署或回滾步驟。

## Open Questions

- 若未來 Surgical Guide 模型的近重複 vertex 密度大幅升高，或 `_weld_and_build()` 各子階段占比因其他變更（例如 edge-map 被重新設計）而改變，是否應重新開啟 vertex-weld 調查？（本提案不回答，僅留下可比對基準。）
- 是否需要在未來某次記憶體相關調查中，一併驗證約 121.5 MiB 的 dead-object 機會是否可回收？（本提案明確排除於範圍外，見 Non-Goals。）

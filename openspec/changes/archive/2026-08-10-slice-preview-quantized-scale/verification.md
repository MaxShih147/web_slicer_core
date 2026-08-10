# 驗證結果記錄

執行日期：2026-08-10 ｜ 對應 tasks.md Phase 5

---

## 5.1 全套單元測試

```
python -m pytest agent/tests -q
577 passed, 2 failed, 1 warning in 6.53s
```

新增測試 **80 個**，全數通過：

| 檔案 | 案例數 | 涵蓋 |
| --- | --- | --- |
| `agent/tests/test_preview_scale.py` | 55 | 全機隊表格、N=4 天花板、浮點倒數精確性、快路徑第二道閘門、portrait 交換不變性、N=8 保留枝、量化交界 |
| `agent/tests/test_preview_scale_contract.py` | 25 | 兩個呼叫點的原始碼契約鎖（含負向驗證）、命令列行為、`config is None` 退路 |
| `agent/tests/test_preview_service_fallback.py` | 15 | RLE 非空、空檔不得快取、既有空檔視為 cache miss、box-mean 濾波（含 BILINEAR 對照）、縮放比一致性 |

### 2 個失敗均為 pre-existing，與本變更無關

| 失敗 | 判定依據 |
| --- | --- |
| `test_prz_print_time.py::test_6_11_single_normal_layer_full_params`（`_compute_print_time` 得 11.0、期望 14.0） | 位於 `agent/prz_encoder.py`，本變更的 diff 未觸及該檔。Phase 2 開始前即已存在 |
| `test_subprocess_boundary_5_11.py::test_engine_runs_as_separate_process`（`async def functions are not natively supported`） | 測試環境缺 `pytest-asyncio` 套件，非程式碼失敗 |

---

## 5.2 / 5.3 / 5.4 實跑驗證

以 `sla_operations.slice_model()` 驅動真實引擎 CLI，200 層，同一顆 STL。

| 幅面 | 量化結果 | 預覽尺寸（200/200 影格） | 判定 |
| --- | --- | --- | --- |
| 15120 × 6230 | N=10, `"0.1"` | **1512 × 623** | PASS |
| 7536 × 3240 | N=5, `"0.2"` | **1507 × 648** | PASS |
| 3840 × 2400 | N=4, `"0.25"` | **960 × 600** | PASS |

15120 的 1512 × 623 與 `optimize-slice-performance` tasks.md 3.5 的實測輸出尺寸一致，交叉印證成立。

### 5.3 3840 級機台的位元組不變性

同一組態分別以「量化器產出」與「硬寫 `--export-preview-pngs 0.25`（變更前的命令列）」各跑一次：

```
entries          : 200 vs 200      names equal: True
PNG bytes 相同    : 200/200
解碼後逐位元組相同 : 200/200
ZIP entry CRC 相同 : 200/200
```

**逐影格完全相同。** ZIP 整檔 SHA-256 不同，唯一來源是容器內嵌的建檔時間戳（`(2026,8,10,13,5,28)` vs `(2026,8,10,13,6,34)`）——比對粒度應取影格，與 `optimize-slice-performance` 3.4/3.5 的方法一致。

`N = 4` 天花板「畫質永不退化」的承諾成立。

### 本階段抓到的文件事實錯誤（已修正）

引擎的 ZIP 項目名為 **`model_preview00000.png`**，非先前文件所寫的 `model00000.png`。原因是 [SLAArchiveWriter.cpp:66-69](../../../third_party/prusaslicer_fork/src/libslic3r/Format/SLAArchiveWriter.cpp#L66-L69) 的 `project` 取自**預覽 ZIP 檔名**的 stem（`model_preview.zip` → `model_preview`），而非 `.sl1` 的 stem。已同步修正 `proposal.md`、`design.md` D5 與 delta spec 的 Known Difference 表。

---

## 5.2 未能取得的項目 — 經負責人裁示確認通過

以下兩項**無法在本機環境產出**，如實載明而非以推估數字充數。**2026-08-10 經負責人裁示，以下列替代證據結案。**

### (1) 體積與時間的實測差值

`slicer-engine/bin/` 內的引擎二進位為 **2026-07-30** 的建置，而帶入 SLA 光柵化效能改動（1/N 快路徑、PNG 壓縮等級 1）的 submodule 指標更新 `08ee0ee` 是 **2026-08-06**。本機打包的是**效能改動之前的舊引擎**（`slicer-engine/` 已於 `.gitignore:90` 排除，屬本機產物）。

`proposal.md` 引用的 **−56% 體積 / −18% 時間**基準是「新引擎 @0.25 → 新引擎 @0.10」，取自 `optimize-slice-performance` tasks.md 3.8 的實測表：

| | 新引擎 @0.25 | 新引擎 @0.10 |
| --- | --- | --- |
| 預覽合計（秒） | 9.02 | 7.39 |
| `preview.zip`（MB） | 27.38 | 11.91 |

在舊引擎上量測會得到不可比的數字。該效益數據**沿用前一變更的實測值**，本變更未重新量測。要重新驗證需先以 `08ee0ee` 之後的 fork 重新打包引擎。

### (2) 層檔 SHA-256 對照

`golden-blur0.sha256` 未隨 `optimize-slice-performance` 封存進本 repo，本機無此基準檔，無法執行「`.sl1` 層檔逐層雜湊與基準一致」的比對。

替代證據：本變更的 diff 完全不觸及層檔編碼路徑（僅改變 `--export-preview-pngs` 的引數來源與 Python 備援產線），且 5.3 的 3840 位元組不變性顯示引擎輸出未受非預期影響。

---

## 5.4 7536 機台的處置

- **已完成**：以真實引擎確認尺寸推導正確（1507 × 648）。原本 spec 標註為「由量化規則與快路徑閘門推導、尚未經真機實測」，其中**尺寸推導部分現已有引擎實測支持**。
- **仍缺**：真實 7536 機台上的體積 / 時間量測與目視畫質確認。
- **處置**：spec 場景的註記維持「以推導立約」，但可補記尺寸已獲引擎驗證。單元測試斷言 **未放寬**。

---

## 5.5 目視畫質驗收 — 經負責人裁示確認通過

需要真實 15120 × 6230 機台與 DS-Online 前端環境，**非由本次自動化流程執行**；2026-08-10 經負責人裁示確認通過。

依 delta spec 的驗收 requirement：
- 驗收 MUST 於 15120 機台執行；
- 長邊 ≤ 5760 的機台輸出逐位元組相同（5.3 已證實），其目視結果 **MUST NOT** 被採計為通過依據。

---

## 5.6 對前端 DS-Online 的連動回覆 — 經負責人裁示確認通過

（內容如下，實際送達 DS-Online 由負責人執行）

對應 DS-Online change `remove-wasm-prz-fallback` 的 Task 5.6，三項：

1. **撤銷 5760 機台的品質疑慮警語。** Task 5.6 記載的「5760×3600 單張預覽自 1440×900 降至 576×360，屬可見的 UI 品質變更」**不會發生**。量化機制下 `5760 / 4 = 1440 ≥ 1400`，N 停在 4，與變更前完全相同。3840 級機台已實測逐影格位元組相同（5.3）。

2. **效益數字更正。** 正確表述為 **`preview.zip` −56%、預覽處理時間 −18%**（基準：15120 機台、新引擎）。**不是**「體積與時間皆省約 60%」——`optimize-slice-performance` design D5 已論證，剩餘約 7.4 秒是來源側必須讀滿 94.2 M 像素的固定成本，不隨縮放比下降。

3. **目視驗收需於 15120 機台執行**（5.5），3840 級機台的驗收結果不具驗證力。

---

## 封存前檢查（`/opsx:verify`）發現與處置

| 編號 | 發現 | 處置 |
| --- | --- | --- |
| W-1 | delta spec 的 Known Difference 表宣告備援產線寫 `0.webp`（WebP），但測試只斷言 entry **數量**、未斷言 **名稱與編碼**。引擎側的 `model_preview00000.png` 已由實跑驗證，備援側則無任何東西阻止改名後 spec 表格靜默失真 | **已修正**：新增 `test_fallback_entry_naming_and_encoding_are_pinned`，斷言 `["0.webp", "1.webp", "2.webp"]` 與首張影像 `format == "WEBP"`，同時釘住表格兩欄 |
| W-2 | Requirement「兩條預覽產線的已知差異須明文立約」的義務對象是 DS-Online，本 repo 無從驗證或強制，封存後可能被誤讀為「後端已保證消費端行為」 | **已修正（archive 時）**：於該 requirement 補入「義務對象的歸屬」註記，明確區分「約束消費端、本 repo 無法強制」與「本 repo 能保證且已由測試釘住的產出側兩欄」，並註明前端側義務已於 5.6 連動回覆中知會 |
| S-1 | Requirement 2 的三個 scenario（快路徑一致性、非整數倍走通用路徑、細支撐在 0.10 下可見）證據來自 `optimize-slice-performance` 的 fork 側實測，本變更未重測 | 維持原狀（本變更不動 fork）。惟「細支撐在 0.10 下可見」已由「未來驗收線」轉為 15120 機台的現行約束，日後調整濾波或 `ALLOWED_N` 時須重新取證 |
| S-2 | 「縮放比為 0 時不產生預覽」場景在本 repo 已幾乎不可達（`preview_scale_for` 永不回傳 0，兩呼叫點恆傳旗標），僅能由引擎預設值 `-1` 觸發 | 維持原狀，條文描述的是引擎層契約，仍然正確 |

---

## 5.8 / 5.9 / 5.10 最終驗收

| 項目 | 結果 |
| --- | --- |
| `python -m pytest agent/tests -q` | 577 passed, 2 failed（皆 pre-existing，見 5.1） |
| `openspec validate slice-preview-quantized-scale` | valid |
| `openspec validate --specs` | 19 passed, 0 failed |
| `third_party/prusaslicer_fork` submodule 指標 | **未變動** |

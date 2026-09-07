## Context

牙科模型各種類在幾何上具有可辨識的特徵：基座模型有明顯單側底平面；手術導板含導孔圓柱；牙冠體積小；口腔內掃描具有大型開放邊界（非封閉 mesh）。這些特徵可透過 PCA 主軸尺寸、平面偵測、邊界分析和投影缺口分析取得，無需機器學習即可完成基本分類。

導孔偵測為計算成本較高的演算法（移植自 C++ `auto_orient_surg_guide.cpp` 中的手術導板自動定向邏輯），需要在確認必要時才執行。

## Goals / Non-Goals

**Goals:**
- 實作八種牙科模型類型的幾何特徵提取與啟發式分類
- 提供 `POST /api/v2/classify-model` REST API 端點
- 導孔偵測採條件式執行，只在有需要時才運算

**Non-Goals:**
- 不使用機器學習或訓練資料
- 不在 API 回傳 confidence 分數（僅供內部分類決策與本機測試／校準工具使用，不由 API 回傳）
- 不實作前端串接或根據分類結果自動選擇工作流程
- 不支援 STL 以外的格式

## Decisions

### D1：啟發式幾何規則而非機器學習

**選項：**
- A. 幾何啟發式規則（soft-score + 決策樹）
- B. 機器學習分類模型（SVM、CNN 等）

**選擇 A，理由：** 牙科模型幾何特徵明確且可解釋；啟發式方法可在無訓練資料的情況下部署；分類結果確定性高、易於調試；門檻值可隨樣本累積逐步校準，不需重新訓練。

### D2：Soft-score（0.0–1.0）而非 Hard-rule 布林判斷

每個幾何特徵對應一個 0.0–1.0 的信號分數，使用分段線性函式平滑過渡，避免邊界案例（如 L1 恰好落在牙冠與牙橋交界）產生不穩定結果。分類決策依下列門檻操作：

| 常數 | 值 | 語義 |
|------|----|------|
| `CANDIDATE_GROUP_MIN` | 0.55 | 進入候選群組的最低分數 |
| `STRONG_SIGNAL_MIN` | 0.65 | 視為強信號的最低分數 |
| `LOW_FEATURE_MAX` | 0.35 | 視為特徵不存在的最高分數 |
| `CANDIDATE_MIN_GAP` | 0.10 | 贏家與次名的最小差距（交界案例） |

### D3：條件式導孔偵測

導孔偵測使用頂點合併、鄰接圖成長、PCA 長寬比過濾、掃描線孔洞偵測與連接邊鏈累積轉角（≥ 220°）等步驟，複雜度較高。`_get_drill_detection_plan()` 依下列優先順序決定是否跳過：

1. 單側大平面且符合基座模型尺寸（`base_model_size_score ≥ 0.55` 且 `one_sided_flat_plane_score ≥ 0.65`）→ 跳過
2. 明確牙冠尺寸或交界牙冠（小尺寸且比例偏向牙冠）→ 跳過
3. 大型開放邊界（`large_open_boundary_score ≥ 0.65`）→ 跳過

以上條件均不成立則執行導孔偵測。

### D4：分類決策優先順序

`_decide_model_type_with_details()` 依下列優先順序（P0 > P_base > P2 > P3 > P5）決定類型：

- **P0**：PCA 失敗 → `other`
- **P_base**：導孔跳過（基座判定）→ 依 `u_shape_score` 在 `dental_model` 與 `u_shaped_dental_model` 分流
- **P2**：導孔跳過（明確牙冠）→ `crown`
- **P3**：導孔跳過（大型開放邊界）→ `intraoral_scan`
- **P5（導孔已執行）**：
  - 5.1 找到導孔 → `surgical_guide`（confidence 0.90）
  - 5.2 導孔完成但未找到：
    - A：單側大平面 + 基座尺寸 → `dental_model` / `u_shaped_dental_model`
    - B：splint 尺寸 + U 型 + 無強外側平面 + 無大型開放邊界 + 無投影孔洞 → `splint`
    - C：L1 交界區（12–18mm）→ `crown` 或 `bridge`（依綜合分數比較）
    - D-pre：非單側大型平面 → `surgical_guide`（confidence 0.55）
    - D：bridge 尺寸達候選門檻 → `bridge`
    - E：fallback → `bridge`（低信心 0.45）
  - 5.3 導孔偵測失敗：bridge 尺寸達候選門檻 → `bridge`（信心上限 0.55）；否則 → `surgical_guide`（低信心 0.30）

### D5：19 個 Soft-score 信號

`_ClassificationSignals` dataclass 含 19 個信號，各對映至一個幾何面向：

`small_object_score`、`full_arch_size_score`、`crown_length_score`、`bridge_length_score`、`elongated_score`、`large_open_boundary_score`、`flat_plane_size_score`、`one_sided_flat_plane_score`、`non_one_sided_flat_plane_score`、`strong_outer_flat_plane_score`（`one_sided_flat_plane_score` 的相容性別名）、`u_shape_score`、`splint_size_score`、`bridge_size_score`、`clear_crown_size_score`、`base_model_size_score`、`crown_ratio_score`、`bridge_ratio_score`、`crown_small_score`、`bridge_small_score`。

### D6：asyncio.to_thread 處理 CPU-bound 運算

`classify_dental_model()` 為純 CPU 運算（特徵提取、numpy 計算），不含 I/O 等待。在 FastAPI 的 async handler 中直接呼叫會阻塞事件循環，因此以 `asyncio.to_thread()` 在執行緒池中執行，確保其他請求不受影響。

### D7：導孔演算法移植自 C++

導孔偵測演算法（`detect_drill_holes()`）移植自 `auto_orient_surg_guide.cpp`，邏輯包含：頂點以 1e-4mm 網格合併（精度對齊）、邊界基鄰接圖成長、PCA 長寬比過濾（最大 1.5）、掃描線孔洞偵測（空白 ≥ 2.4mm、實心 ≥ 0.6mm）、連接邊鏈 bbox 過濾（3–35mm）、累積轉角 ≥ 220°。環形直徑有效範圍：5.5–14.0mm。

## 校準區間摘要

以下為各主要尺寸特徵的參考轉折點。詳細計算公式與完整過渡區間請見下方「當前尺寸與比例信號校準快照」。

| 類型/特徵 | 參考區間 |
|-----------|----------|
| Crown L1 全滿分上限 | ≤ 12mm |
| Crown/Bridge L1 分界點（各 0.5） | 15mm |
| Bridge L1 全滿分下限 | ≥ 18mm |
| Full arch L1 全滿分區間 | 45–100mm |
| Full arch L2 全滿分區間 | 30–80mm |
| Full arch L3 全滿分區間 | 12–35mm |
| Splint L3 全滿分區間 | 8–12mm |
| Base model L3 全滿分區間 | 20–40mm |
| 外側大平面面積比例（0.5 分閾值） | 0.05 |
| 大型開放邊界最大 loop 周長（0.5 分閾值） | ≥ 30mm |
| 大型開放邊界 largest_open_ratio（0.5 分閾值） | ≥ 0.5 |
| U 型缺口投影比例（0.5 分閾值） | ≥ 0.20 |
| U 型缺口邊界接觸長度（0.5 分閾值） | ≥ 10mm |
| 導孔環形直徑 | 5.5–14.0mm |

## 當前尺寸與比例信號校準快照

> **適用說明**
>
> 本節記錄本次歸檔版本（2026-07-29）實際使用的初版校準參數，數值在開發期間依既有測試模型反覆調整所得。目前參數只反映既有測試樣本的尺寸與形狀分布，不是牙科模型的通用尺寸定義。對不同掃描來源、建模方式、特殊病例或目前樣本未涵蓋的尺寸範圍，未必具有相同的辨識效果。
>
> 這些參數屬於實作設計快照，不是長期不變的外部 API 契約。後續若調整門檻，應以新的 OpenSpec change 記錄，不回頭修改本次 archive。

### 輔助函式語義摘要

| 函式 | 語義 |
|------|------|
| `_soft_max_with_falloff(v, max, falloff)` | v ≤ max → 1.0；max < v < max+falloff → 線性 1→0；v ≥ max+falloff → 0.0 |
| `_soft_range_with_falloff(v, lo, hi, lo_f, hi_f)` | v < lo−lo_f → 0.0；lo−lo_f 至 lo → 線性 0→1；lo ≤ v ≤ hi → 1.0；hi 至 hi+hi_f → 線性 1→0；v > hi+hi_f → 0.0 |
| `_soft_greater_than(v, thr, tol)` | v ≤ thr−tol → 0.0；v = thr → 0.5；v ≥ thr+tol → 1.0；中間線性 |

---

### small_object_score

**輸入**：L2、L3

兩個截面軸各自計算子分數，取最小值：

| 子分數 | L2（或 L3） | 值 |
|--------|------------|-----|
| `_soft_max_with_falloff(L2, 11.0, 5.0)` | ≤ 11mm | 1.0 |
| | 11–16mm | 線性 1.0 → 0.0 |
| | ≥ 16mm | 0.0 |
| `_soft_max_with_falloff(L3, 11.0, 5.0)` | ≤ 11mm | 1.0 |
| | 11–16mm | 線性 1.0 → 0.0 |
| | ≥ 16mm | 0.0 |

**組合**：`small_object_score = min(_small_l2, _small_l3)`

---

### full_arch_size_score

**輸入**：L1、L2、L3

三軸各自計算子分數 s_l1、s_l2、s_l3（使用 `_soft_range_with_falloff`）：

**L1 子分數（s_l1）**

| L1 | 值 |
|----|----|
| ≤ 39mm | 0.0 |
| 39–45mm | 線性 0.0 → 1.0 |
| 45–100mm | 1.0 |
| 100–115mm | 線性 1.0 → 0.0 |
| ≥ 115mm | 0.0 |

**L2 子分數（s_l2）**

| L2 | 值 |
|----|----|
| ≤ 25mm | 0.0 |
| 25–30mm | 線性 0.0 → 1.0 |
| 30–80mm | 1.0 |
| 80–95mm | 線性 1.0 → 0.0 |
| ≥ 95mm | 0.0 |

**L3 子分數（s_l3）**

| L3 | 值 |
|----|----|
| ≤ 9mm | 0.0 |
| 9–12mm | 線性 0.0 → 1.0 |
| 12–35mm | 1.0 |
| 35–40mm | 線性 1.0 → 0.0 |
| ≥ 40mm | 0.0 |

**組合**：`full_arch_size_score = min(s_l1, s_l2, s_l3) × 0.8 + avg(s_l1, s_l2, s_l3) × 0.2`

min 項（權重 0.8）確保三軸同時落在全弓範圍；avg 項（權重 0.2）避免所有軸恰好在邊界時分數為零。

---

### crown_length_score 與 bridge_length_score（互補分數）

**輸入**：L1

兩個分數由 `_crown_bridge_length_scores(L1)` 一次計算，三段分段線性：

| L1 | crown_length_score | bridge_length_score |
|----|-------------------|---------------------|
| ≤ 12mm | 1.0 | 0.0 |
| 12–15mm | 線性 1.0 → 0.5（`1.0 − 0.5t`，t=(L1−12)/3） | 線性 0.0 → 0.5（`0.5t`） |
| 15mm | 0.5 | 0.5 |
| 15–18mm | 線性 0.5 → 0.0（`0.5 − 0.5t`，t=(L1−15)/3） | 線性 0.5 → 1.0（`0.5 + 0.5t`） |
| ≥ 18mm | 0.0 | 1.0 |

兩者在任意有效 L1 下嚴格互補：`crown_length_score + bridge_length_score = 1.0`。

---

### elongated_score

**輸入**：L1/L2（elongation_ratio）

使用 `_soft_greater_than(ratio, threshold=1.4, tolerance=0.4)`：

| ratio | 值 |
|-------|----|
| ≤ 1.0 | 0.0 |
| 1.0–1.4 | 線性 0.0 → 0.5 |
| 1.4 | 0.5 |
| 1.4–1.8 | 線性 0.5 → 1.0 |
| ≥ 1.8 | 1.0 |

公式：`max(0, min(1, (ratio − 1.0) / 0.8))`

---

### crown_ratio_score 與 bridge_ratio_score（互補分數）

**輸入**：L1/L2（elongation_ratio）

兩個分數由 `_crown_bridge_ratio_scores(ratio)` 一次計算，三段分段線性，轉折點與 L1 長度分數**不對稱**：

| ratio | crown_ratio_score | bridge_ratio_score |
|-------|------------------|--------------------|
| ≤ 1.20 | 1.0 | 0.0 |
| 1.20–1.35 | 線性 1.0 → 0.5（`1.0 − 0.5t`，t=(ratio−1.20)/0.15） | 線性 0.0 → 0.5（`0.5t`） |
| 1.35 | 0.5 | 0.5 |
| 1.35–1.80 | 線性 0.5 → 0.0（`0.5 − 0.5t`，t=(ratio−1.35)/0.45） | 線性 0.5 → 1.0（`0.5 + 0.5t`） |
| ≥ 1.80 | 0.0 | 1.0 |

兩者在任意有效 ratio 下嚴格互補：`crown_ratio_score + bridge_ratio_score = 1.0`。

---

### crown_small_score 與 bridge_small_score（複合信號）

**輸入**：small_object_score、crown_length_score、crown_ratio_score（及 bridge 對應版本）

組合公式：

```
crown_small_score  = min(small_object_score, (crown_length_score  + crown_ratio_score)  / 2.0)
bridge_small_score = min(small_object_score, (bridge_length_score + bridge_ratio_score) / 2.0)
```

語義：以 small_object_score 作為截面尺寸閘門——若 L2 或 L3 過大，即使 L1 長度與比例都偏向牙冠或牙橋，分數也會被壓低。長度分數與比例分數的平均代表「L1 落在此類型範圍」的綜合判斷。

---

### clear_crown_size_score

**輸入**：L1、L2、L3

```
_crown_l1_size = _soft_max_with_falloff(L1, 15.0, 3.0)
clear_crown_size_score = min(_crown_l1_size, _small_l2, _small_l3)
```

L1 子分數（`_soft_max_with_falloff(L1, 15.0, 3.0)`）：

| L1 | 值 |
|----|----|
| ≤ 15mm | 1.0 |
| 15–18mm | 線性 1.0 → 0.0 |
| ≥ 18mm | 0.0 |

`_small_l2`、`_small_l3` 與 `small_object_score` 計算中的子分數相同（L2、L3 各自 ≤11mm 得 1.0，11–16mm 線性降至 0）。

**組合**：三者取最小值，確保 L1 在牙冠上限以內、且 L2 與 L3 都符合小型尺寸，同時達到才有高分。

---

### splint_size_score

**輸入**：L1、L2、L3

L1、L2 子分數（s_l1、s_l2）與 `full_arch_size_score` 計算中的子分數**完全相同**，僅 L3 使用 splint 專屬範圍：

**L3 子分數（s_splint_l3）**：`_soft_range_with_falloff(L3, 8.0, 12.0, 2.0, 8.0)`

| L3 | 值 |
|----|----|
| ≤ 6mm | 0.0 |
| 6–8mm | 線性 0.0 → 1.0 |
| 8–12mm | 1.0 |
| 12–20mm | 線性 1.0 → 0.0 |
| ≥ 20mm | 0.0 |

**組合**：`splint_size_score = min(s_l1, s_l2, s_splint_l3) × 0.8 + avg(s_l1, s_l2, s_splint_l3) × 0.2`

---

### base_model_size_score

**輸入**：L1、L2、L3

L1、L2 子分數（s_l1、s_l2）與 `full_arch_size_score` 計算中的子分數**完全相同**，僅 L3 使用 base model 專屬範圍：

**L3 子分數（s_base_l3）**：`_soft_range_with_falloff(L3, 20.0, 40.0, 10.0, 15.0)`

| L3 | 值 |
|----|----|
| ≤ 10mm | 0.0 |
| 10–20mm | 線性 0.0 → 1.0 |
| 20–40mm | 1.0 |
| 40–55mm | 線性 1.0 → 0.0 |
| ≥ 55mm | 0.0 |

**組合**：`base_model_size_score = min(s_l1, s_l2, s_base_l3) × 0.8 + avg(s_l1, s_l2, s_base_l3) × 0.2`

---

### bridge_size_score

**輸入**：L1、L2、L3（L1 子分數依賴已計算的 bridge_length_score）

L1 子分數（`_bridge_l1`）由兩個上下界取最小：

- 下界：`bridge_length_score`（確保 L1 不過短，≤12mm 時為 0）
- 上界：`_soft_max_with_falloff(L1, 45.0, 10.0)`（確保 L1 不過長，≥55mm 時為 0）

組合後 `_bridge_l1` 的有效形狀：

| L1 | _bridge_l1 |
|----|-----------|
| ≤ 12mm | 0.0 |
| 12–18mm | 線性 0.0 → 1.0（受 bridge_length_score 限制） |
| 18–45mm | 1.0 |
| 45–55mm | 線性 1.0 → 0.0（受上界限制） |
| ≥ 55mm | 0.0 |

L2 子分數（`_bridge_l2`）：`_soft_max_with_falloff(L2, 45.0, 10.0)`

| L2 | 值 |
|----|----|
| ≤ 45mm | 1.0 |
| 45–55mm | 線性 1.0 → 0.0 |
| ≥ 55mm | 0.0 |

L3 子分數（`_bridge_l3`）：`_soft_max_with_falloff(L3, 15.0, 3.0)`

| L3 | 值 |
|----|----|
| ≤ 15mm | 1.0 |
| 15–18mm | 線性 1.0 → 0.0 |
| ≥ 18mm | 0.0 |

**組合**：`bridge_size_score = min(_bridge_l1, _bridge_l2, _bridge_l3) × 0.8 + avg(_bridge_l1, _bridge_l2, _bridge_l3) × 0.2`

---

## Risks / Trade-offs

- **門檻值尚待校準**：當前門檻為初版估計值（見程式碼注解 "Initial values only"）。需累積真實樣本後以統計方式校準。
- **splint 與 u_shaped_dental_model 邊界混淆**：兩者在 L3 與 U 型特徵上有重疊，少數薄型基座可能誤判。
- **導孔偵測對非標準模型可能不穩定**：演算法移植自特定手術導板格式的 C++ 實作，邊界條件需以多樣本驗證。
- **confidence 與 primary_reasons 不對外公開**：僅供內部分類決策與本機測試／校準工具使用，不由 API 回傳；若未來前端需要，需擴充 API 契約。

## Migration Plan

1. 新增 `agent/model_classifier.py`（純加法，不影響現有功能）
2. 在 `agent/api_v2.py` 新增 `POST /api/v2/classify-model` 端點（純加法，不修改現有路由）
3. 無需 rollback 策略（純新增，可直接移除端點與模組回退）

## Open Questions

- 當前門檻值需以實際牙科模型樣本校準，何時安排校準作業？
- 前端是否需要 API 回傳 `confidence` 分數以提供使用者提示？若需要，需擴充 API 契約。

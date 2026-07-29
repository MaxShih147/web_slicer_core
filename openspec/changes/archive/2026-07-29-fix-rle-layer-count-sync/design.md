## Context

`print-time-sync`（commit `8501569`）於切片完成後以 PRZ 物理公式 `_compute_print_time()` 複寫 `status.json["estimated_print_time"]`，作為 Web API 與 PRZ binary 的單一真值來源。其守衛為 `resolve_estimated_print_time()` 中的 `if not prz_config or not total_layers: return fallback`。

其後 `[layer-rle]`（commit `f9bccb9`）讓切片器在 `SLA_LAYER_RLE=1` 下輸出 `model#####.rle` 取代 `.png`，卻未同步更新層數統計。目前層數在三處各自以裸 `endswith` 判斷，且彼此分歧：

```
                          層檔判斷邏輯                          RLE 模式結果
parse_sl1_metadata()   sum(1 for n ... endswith(".png"))       → 0     ✗ bug
encode_prz_streaming() rle_names if rle_names else png_names   → 正確   ✓
get_layer_png_from_sl1 sorted(n ... endswith(".png"))          → 空     ✗
```

於是 `total_layers = 0` → 守衛恆真 → 同步靜默失效，`estimatedPrintTime` 永遠退回 fork SL1 估值。因 fork 估值吃「每層投影面積」（[SLAPrintSteps.cpp:1505](../../../third_party/prusaslicer_fork/src/libslic3r/SLAPrintSteps.cpp)），多物件時 slow layer 暴增而拉開落差，才被使用者察覺。同一 bug 亦使 `layerCount` API 恆 0、`/layers/{idx}.png` 恆 404。

**約束：**
- PRZ 二進位輸出必須保持 byte-identical（下游印表機讀取）。
- 不得改動既有 API 介面與 `resolve_estimated_print_time()` 的守衛語意。
- `jobs.py` 已 import `prz_encoder`，共用 helper 須避免循環相依。

## Goals / Non-Goals

**Goals:**
- 讓 `.rle` 與 `.png` 兩種輸出的層數統計都正確，使 `print-time-sync` 在 RLE 模式下正常啟動。
- 建立單一層檔列舉真值來源，消除三處分歧，並嚴格排除縮圖污染。
- `get_layer_png_from_sl1()` 支援 RLE 單層即時解碼，失敗優雅降級（回 `None` → 404）。
- 保持 PRZ 輸出 byte-identical。

**Non-Goals:**
- 不讓 fork SL1 估值與 PRZ 公式互相靠攏——本變更是「API 一律採 PRZ 值」，fork `printTime` 僅在 `prz_config.json` 缺失時作 fallback。
- 不追求 API float 與 PRZ header int 逐位元相等（採選項 A，接受 <1s 截斷差）。
- 不改前端；不改 `_compute_print_time` / `resolve_estimated_print_time` 的邏輯。

## Decisions

### D1：層檔列舉抽為單一 helper `sl1_layer_names()`，置於 `prz_encoder.py`

以單一 helper 取代三處各自判斷。放 `prz_encoder.py` 而非 `jobs.py`，因為 `jobs.py → prz_encoder`（`_compute_print_time`）的 import 方向已存在，反向會成循環；PRZ 編碼端也本就在此檔。

- **替代方案**：放 `jobs.py` 或新建 `sl1_utils.py`。前者造成 `prz_encoder` 反向 import 循環；後者為單一小函式新增模組，過度切割。
- **語意**：`.rle` 優先，否則 `.png`，`sorted()` 排序——沿用現行 `encode_prz_streaming` 邏輯，確保 PRZ 順序不變。

### D2：以嚴格正則 `^model\d{5}\.(rle|png)$` 取代裸 `endswith`

fork 的 `write_thumbnail` 會把縮圖寫成 `thumbnail/thumbnailNNNxNNN.png` 進同一 .sl1；裸 `endswith(".png")` 在 PNG 模式會誤計縮圖。正則同時鎖定 `model` 前綴、5 位序號與副檔名，一次擋掉縮圖與任何非層檔。

- **替代方案**：「排除含 `/` 的子目錄路徑」為等價備援（縮圖在 `thumbnail/` 子目錄）。選正則因其更精確且自我描述層檔命名。
- **位元不變性論證**：正常 .sl1 的層檔皆為 `model#####.{rle,png}`、設定檔為 `.ini`/`.json`（本就被副檔名排除），故正則選出集合 == 舊 `endswith` 集合 → PRZ 輸出不變。
- **已知耦合**：`model` 前綴綁定固定輸出 `output/model.sl1`（[jobs.py:135](../../../agent/jobs.py)，其 stem 即層檔前綴，見 [SL1.cpp:405-412](../../../third_party/prusaslicer_fork/src/libslic3r/Format/SL1.cpp)）。改輸出名須同步改正則——列入 Risks。

### D3：抽出單層 RLE 解碼 helper，回 `Optional[bytes]`，raise/None 由呼叫端決定

把 `_rle_sl1_to_png_zip()` 內「讀 `prusaslicer.ini` 取 `display_pixels_x/y` → `prz_decoder._rle_decode_layer()` → `PIL.Image.fromarray(gray,"L").save(PNG)`」抽成單層函式，兩個呼叫端共用，不重寫解碼。

- 抽出的 helper 回 `Optional[bytes]`；**失敗語意留給呼叫端**：
  - `get_layer_png_from_sl1()`：回 `None` → 上層 [main.py:690](../../../agent/main.py) 轉 404（既有契約）。
  - `_rle_sl1_to_png_zip()`（整包 layers.zip）：維持 raise `validation_error`（整包壞一顆即無效）。
- **為何不統一失敗行為**：兩端服務語意不同（單層 vs 整包），統一反而破壞其中一方的既有契約。

### D4：時間精度採選項 A（float 不動）

`status.json` 維持 `_compute_print_time` 的 float 原值；PRZ header 端 `int()` 截斷不變。已驗證下載路徑與 status.json 同源（`downloadPrz` 空 body → 讀持久化 `prz_config.json`；`_inject_retract_overrides` 冪等），故差額**只**來自 `int()` 截斷，恆 `0 ≤ 差 < 1s`，前端格式化到分鐘後無感。不新增轉型邏輯，改動面最小。

- **替代方案 B**：status.json 也存 `int()` 求逐位元相等。放棄，因會損失對 SLA 無意義的次秒精度，且不改善使用者可見結果。

## Risks / Trade-offs

- **[前綴耦合] `model` 寫死於正則** → 於 helper 處加註解說明其綁定 `output/model.sl1`；spec 已列回歸保證，改輸出名時測試會捕捉失配。
- **[位元不變性回歸] 改 encode 路徑層檔列舉來源** → 以「改動前後對同一 .sl1 編碼 PRZ 應 byte-identical」的回歸測試守住（spec `sl1-layer-access` 已定義該 scenario）。
- **[外部匯入異常 .sl1] 缺 `prusaslicer.ini`/`display_pixels`** → 單層解碼回 `None` → 404，不使端點崩潰；本專案自切檔因 `fill_slicerconf` 無條件寫入完整 config 而必含該欄位。
- **[混合格式] `.rle` 與 `.png` 並存** → 正常不會發生（`get_encoder()` 二選一）；helper 明確 `.rle` 優先，行為確定。

## Migration Plan

- 純後端修正，無資料模型或 API 介面變更；部署即生效，無需資料遷移。
- 既有已切片 job 的 `status.json` 不回溯重算（其值已寫定）；重新切片即得正確值。
- 回滾：還原 `parse_sl1_metadata` / `get_layer_png_from_sl1` / encode 路徑的層檔列舉來源即可，無殘留狀態。

## Open Questions

- 無。三項質詢決策（解碼失敗回 None、精度選項 A、嚴格正則）已定案並落入 specs。
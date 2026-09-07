## Context

預覽縮放比目前是三處各自獨立的常數：[agent/jobs.py:438](../../../agent/jobs.py#L438) 與 [agent/sla_operations.py:339](../../../agent/sla_operations.py#L339) 的 `--export-preview-pngs "0.25"` 字串引數，以及 [agent/preview_service.py:31](../../../agent/preview_service.py#L31) 的 `scale: float = 0.25` 函式預設值。三者服務同一個 HTTP 端點 `GET /api/v2/slices/{job_id}/preview.zip`（[agent/api_v2.py:951-980](../../../agent/api_v2.py#L951-L980)），該端點優先回傳引擎產出的 `model_preview.zip`，缺席時才落到 Python 備援。

引擎側的降取樣實作在 [RasterBase.cpp](../../../third_party/prusaslicer_fork/src/libslic3r/SLA/RasterBase.cpp) 的 `PNGPreviewEncoder`，前一個變更 `optimize-slice-performance` 已在其中加入固定區塊快路徑：

```cpp
// RasterBase.cpp:134-137
const size_t n = static_cast<size_t>(inv_scale);
const bool   fixed_block = n >= 1 &&
                           inv_scale == static_cast<double>(n) &&
                           new_w * n <= w && new_h * n <= h;
```

本設計的核心約束由此而來——**快路徑只在 `1/scale` 為位元級精確整數時才啟用**，因此可用的縮放比不是連續區間，而是一組離散的 `1/N`。

引擎並不知道「消費端要多大」；DS-Online `SlicePreviewDialog` 的需求（520 CSS px × DPR 2 ≈ 1040 device px）只存在於前端。本變更把這個需求編碼進後端的一個函式。

## Goals / Non-Goals

**Goals:**

- 縮放比由幅面決定，而非硬寫常數；三個呼叫點共用單一真值來源。
- 產出的每一個縮放比都命中 C++ 的 1/N 快路徑，不因動態化而吐掉既有效能收益。
- 任何機台的預覽畫質**不得比今日更差**（`N = 4` 為天花板）。
- 備援產線與引擎產線在**縮放比與濾波語意**上一致。

**Non-Goals:**

- 不修改 `third_party/prusaslicer_fork`。本設計只使用引擎既有的 `--export-preview-pngs` 介面與既有快路徑，submodule 指標不動、不需重新編譯。
- 不統一兩條產線的 ZIP 檔名與編碼格式（見 D5 的 Known Difference）。
- 不改進 box-mean 濾波演算法本身。
- 不處理 3840 級機台低於 1040 device px 的問題（明文接受，見 D3）。

## Decisions

### D1：量化規則——「取最大的 N 使 `long_side / N ≥ 1400`」，找不到則 `N = 4`

`agent/preview_scale.py` 提供唯一入口：

```
preview_scale_for(long_side_px) -> (scale_str, n)

  目標寬        TARGET_WIDTH_PX = 1400
  允許集合      ALLOWED_N = (4, 5, 8, 10)
  選取          max{ N ∈ ALLOWED_N : long_side_px / N >= 1400 }
  無解時        N = 4
```

**為何回傳 `scale_str`（字串）而非 `float`。** CLI 引數終究要序列化成十進位字串交給引擎，而 C++ 端會對該字串做 `strtod` 再取倒數。把字串本身當成契約的一部分回傳，讓「哪個字串對應哪個 N」成為可測試的單一事實（見 D6）；若回傳 float 再由呼叫端各自格式化，格式化方式一分岔，快路徑就可能在其中一條路徑上靜默失效。

四個成員與其字串為 `4 → "0.25"`、`5 → "0.2"`、`8 → "0.125"`、`10 → "0.1"`。

**為何目標值取 1400 而非 1040。** 1040 是 DPR 2 下的**最低**需求；量化後的落點是離散的，取 1040 當門檻會讓 15120 選到 N=10（1512）之外還可能在未來幅面上選到剛好貼著門檻的 N，毫無餘裕。1400 在 15120 上仍選中 N=10，同時對 5760 保留 N=4（1440 ≥ 1400，只差 40 px 就會掉到 N=5 的 1152），是把「機隊現況」與「留餘裕」同時滿足的最小值。

**替代案（未採用）：四捨五入到最近的 N。** `15120 / 1400 = 10.8` 在最近規則下仍得 N=10，但 `7536 / 1400 = 5.38` 會得 N=5、`3840 / 1400 = 2.74` 會得 N=... 集合裡最近的是 4，落點碰巧相同。問題在於「最近」不保證**永不低於目標**——若集合日後加入更大的 N，最近規則會允許產出低於 1400 的預覽。「取最大且不低於目標」是單調且有方向性的保證，值得用它換掉「最近」那點直覺上的對稱性。

### D2：長邊取 `max(display_pixels_x, display_pixels_y)`，因為它對 portrait 交換不變

引擎建立 raster 時的行為在 [SL1.cpp:385-395](../../../third_party/prusaslicer_fork/src/libslic3r/Format/SL1.cpp#L385-L395)：

```cpp
auto ro = m_cfg.display_orientation.getInt();
if (orientation == roPortrait) {
    std::swap(w, h);
    std::swap(pw, ph);      // ← 像素維度也一起交換
}
res = sla::Resolution{pw, ph};
```

因此 raster 寬度並不恆等於 `display_pixels_x`：

```
landscape → raster_w = display_pixels_x
portrait  → raster_w = display_pixels_y      ← 交換了
```

**`max(x, y)` 之所以正確，是因為它對這個交換不變**——`max` 恆等於 raster 的長邊，不論方向如何設定。而長邊正是決定影像在 `<img>` 容器中能被放到多大的那一邊。這個理由必須留在文件裡，否則後人看到 `max()` 只會當成隨手防呆，日後「簡化」成 `display_pixels_x` 就會在 portrait 機台上算錯軸。

三項佐證支撐這條路是安全的：

1. **Python 與引擎讀的是同一份值。** [sla_operations.py:159-166](../../../agent/sla_operations.py#L159-L166) 的 `generate_config_ini()` 是 `for field_name, value in config.model_dump().items()` 全欄位傾印，`display_pixels_x` / `display_pixels_y` / `display_orientation` 都會寫進 INI。不存在「Python 算的幅面與引擎用的幅面不同」的風險。（`README.md:548` 把這件事列為未完成 TODO，是過期敘述，順手清掉。）
2. **目前全機隊都是 landscape。** [models.py:90](../../../agent/models.py#L90) 預設 `"landscape"`，而 mechado 萃取（[api_v2.py:1822-1825](../../../agent/api_v2.py#L1822-L1825)）只設 `display_pixels_x/y`、**從不設 `display_orientation`**。`max()` 在今天與 `display_pixels_x` 等價，是零成本的未來保險。
3. 機隊所有機台皆 `x > y`，`max()` 不會在 landscape 下誤取短邊。

### D3：`N ∈ {4, 5, 8, 10}`，`N = 4` 同時是天花板

集合由兩個條件夾出來：下界是「不得比今日差」（今日即 `N = 4`），上界是「`1/N` 必須讓 `w * scale` 的截斷結果仍滿足 `new_w * n <= w`」。實際驗算（Python 與 C++ 同為 IEEE-754 binary64，可直接互推）：

```
機台            長邊    N    scale     new_w × new_h    快路徑閘門
──────────────────────────────────────────────────────────────────
2560 × 1440     2560    4    "0.25"      640 ×  360      通過
3840 × 2160     3840    4    "0.25"      960 ×  540      通過
3840 × 2400     3840    4    "0.25"      960 ×  600      通過
5760 × 3600     5760    4    "0.25"     1440 ×  900      通過
7536 × 3240     7536    5    "0.2"      1507 ×  648      通過
15120 × 6230   15120   10    "0.1"      1512 ×  623      通過
```

四個 N 全數命中快路徑。`15120 → 1512 × 623` 與 `optimize-slice-performance` tasks.md 3.5 的實測輸出尺寸一致，交叉印證。

**`N = 8` 是目前無機台落入的保留枝。** 它只在長邊 ∈ [11200, 14000) 時被選中，機隊中無此規格。保留它是為了讓集合在該區間出現新機台時不必改碼；但**測試不可寫成「每個 N 都必須有機台命中」**，否則會把一條合法的保留枝誤判為死碼。

**明文接受 `N = 4` 天花板的代價。** 3840 級機台停在 960 px，低於 `optimize-slice-performance` design D4 訂下的 1040 device px 判準。要修只能把 `1/2`、`1/3` 納入集合，那會讓 3840 機台的 `preview.zip` 膨脹為今日的 **4 倍**——一個以降本為目的的變更不該讓一半機台的成本上升。這個缺口寫進 spec 當作已知取捨，不當作待辦。

### D4：兩條引擎產線的接入，與 `config is None` 的退路

```
                        ┌─────────────────────────┐
  api_v2.py:505 ────────┤  jobs.py                │
  (config 必存在)       │  run_slicing()          │──┐
                        │  config: Optional[...]  │  │
  main.py:636 ──────────┤                         │  │
  (config 可為 None)    └─────────────────────────┘  │
                                                     ├──▶ preview_scale_for()
                        ┌─────────────────────────┐  │
  slice_model() ────────┤  sla_operations.py      │──┤
  (config 必存在)       │  config: SLAConfig      │  │
                        └─────────────────────────┘  │
                        ┌─────────────────────────┐  │
  api_v2.py:976 ────────┤  preview_service.py     │──┘
  main.py:752           │  (從 .sl1 讀真實尺寸)    │
                        └─────────────────────────┘
```

**`config is None` 是真實的線上路徑，不是防禦性寫法。** [main.py:612-613](../../../agent/main.py#L612-L613) 的舊版 `POST /api/jobs` 在呼叫端未帶 `config` 時，`sla_config` 保持 `None`；[jobs.py:454](../../../agent/jobs.py#L454) 因此**不傳 `--load`**，引擎改用內建預設 preset，其解析度是 Python 端無從得知的。這種情況下唯一誠實的選擇是 `N = 4`——它恰好等於今日行為，所以退路不引入任何行為變化。既有測試 [test_slice_progress_streams.py](../../../agent/tests/test_slice_progress_streams.py) 大量以 `run_slicing(JOB)` 不帶 config 呼叫，這條路徑本來就在測試覆蓋內。

`sla_operations.slice_model()` 的 `config: SLAConfig` 為必要參數，接入單純，無退路分支。

### D5：備援產線的三項收斂，以及刻意不收斂的兩項

備援產線 [preview_service.py](../../../agent/preview_service.py) 與引擎產線有六項差異，本變更只收斂前三項：

| 項目 | 引擎產線 | 備援產線 | 本變更 |
| --- | --- | --- | --- |
| 縮放比 | CLI 引數 | 函式預設 `0.25` | **收斂**：改由 helper 決定 |
| 降取樣濾波 | box-mean | PIL `BILINEAR` | **收斂**：改用 `Image.BOX` |
| RLE 模式 | 不受影響 | 空 ZIP 且永久快取 | **修正** |
| 編碼格式 | PNG (miniz L1) | WebP (q80) | 維持 |
| ZIP 檔名 | `model_preview00000.png` | `0.webp` | 維持 |
| 觸發時機 | 每次切片 | 僅 `model_preview.zip` 缺席 | 維持 |

**(1) 縮放比。** 備援產線是從 `.sl1` 事後重讀，能直接拿到每張圖的真實尺寸，因此應以 `max(img.width, img.height)` 呼叫同一個 helper，而不是接受一個外部傳入的預設值。`scale: float = 0.25` 這個預設參數本身就是分岔的來源，移除它。

**(2) 濾波。** 現行 [preview_service.py:21](../../../agent/preview_service.py#L21) 用 `Image.BILINEAR`。Pillow 的 `resize()` 在縮小時會依縮放倍率放大濾波支撐，所以 BILINEAR **是有抗鋸齒的**，細支撐不會像樸素 2×2 取樣那樣消失——但它是**三角權重**，不是均勻 box。孤立細特徵落在區塊邊緣時權重偏低，結果會比 box-mean 略暗。`slice-preview-export` 的 box-mean requirement 與 design D4 的實測證據（`0.10` 下可見像素占比 1.12%）講的都是 box-mean，因此備援線目前是**不符自家規格**的。Pillow 的 `Image.BOX` 是 box-mean 的精確對應，改動成本一個常數，能讓契約對兩條產線同時成立。

**(3) RLE 空 ZIP。** 主路徑以 `SLA_LAYER_RLE=1` 執行（[jobs.py:468](../../../agent/jobs.py#L468)），此時 `.sl1` 內只有 `model#####.rle`——[prz_encoder.py:77-81](../../../agent/prz_encoder.py#L77-L81) 的 `sl1_layer_names()` 明確定義「有 `.rle` 就不會有 `.png`」。而 [preview_service.py:75](../../../agent/preview_service.py#L75) 只挑 `n.endswith(".png")`，得到空清單、寫出空 ZIP，再被第 50 行的 `if output_path.exists(): return output_path` **永久快取**——該 job 此後永遠拿到空預覽。修法是重用既有的 [prz_decoder.rle_layer_to_png](../../../agent/prz_decoder.py)（`layers.zip` 端點的 `_rle_sl1_to_png_zip` 已經在用），統一走 `sl1_layer_names()` 列舉層檔。此缺陷先於本變更即存在，只是同一支函式動到了就一併修掉。

**刻意不收斂的兩項（Known Difference）。** 引擎寫 `model_preview00000.png`（[SLAArchiveWriter.cpp:66-78](../../../third_party/prusaslicer_fork/src/libslic3r/Format/SLAArchiveWriter.cpp#L66-L78) 的 `project + "%.5d" + ext`，其中 `project` 取自預覽 ZIP 檔名的 stem，即 `model_preview` 而非 `model`——實跑確認），備援寫 `0.webp`；兩者由同一端點以相同 `filename="preview.zip"` 送出。統一任一邊都會牽動 DS-Online 的解壓邏輯，屬另一次跨 repo 連動，塞進這個已有明確前端契約的變更只會擴大爆炸半徑。改以在 spec 明文立約：**消費端 MUST 以 ZIP 內實際 entry 名稱與副檔名為準**，不得假設固定命名或格式。

### D6：浮點倒數精確性必須有專門的測試，因為它的失敗是靜默的

快路徑閘門要求 `inv_scale == static_cast<double>(n)` **位元級相等**。而我們送出去的是十進位字串，C++ 端做 `strtod(s)` 再算 `1.0 / v`。`0.2` 與 `0.1` 在 binary64 中都不是精確值，其倒數落在 5.0 / 10.0 附近——能不能**捨入回**精確整數，取決於該鄰域的 ULP 寬度，不是可以憑直覺斷言的事。

實測（Python 與 C++ 同為 IEEE-754 binary64，且十進位→double 皆為正確捨入，故 Python 可作為有效代理）：

```
"0.25" → 1.0/v = 4.0   == 4.0    ✓
"0.2"  → 1.0/v = 5.0   == 5.0    ✓
"0.125"→ 1.0/v = 8.0   == 8.0    ✓
"0.1"  → 1.0/v = 10.0  == 10.0   ✓
```

四個成員全數通過——**但這是四次幸運，不是一條定理**。若日後有人往集合裡加一個 `1/3` 並寫成 `"0.333333"`，`1.0 / 0.333333 = 3.000003`，閘門不成立，`fixed_block` 為 false，程式**照常執行、輸出照常正確、不報錯、不寫任何 log，只是慢了**。`optimize-slice-performance` 花了整個階段 3 才換到的收益會就這樣蒸發，而且沒有任何訊號。

因此測試必須直接斷言契約本身：

```
對 ALLOWED_N 中的每個 N：
    scale_str, n = 該 N 對應的輸出
    assert n == N
    assert 1.0 / float(scale_str) == float(N)      ← 守 RasterBase.cpp:136
```

同時斷言快路徑的第二道閘門（`new_w * n <= w and new_h * n <= h`），以全機隊尺寸為表格輸入——這道閘門在 `w` 非 `N` 整數倍時（如 7536 / 5 = 1507.2）才真正有意義。

### D7：呼叫點以原始碼下鎖，防止硬編碼回流

本 repo 已有這個模式的先例：[test_slice_progress_string_contract.py](../../../agent/tests/test_slice_progress_string_contract.py) 直接讀取 `jobs.py` 與 fork 的原始碼字面量來鎖住 `ARCHIVE_DONE_MARKER`。同樣手法適用於此：斷言 `jobs.py` 與 `sla_operations.py` 的原始碼中**不再出現硬寫的 `"0.25"` 作為 `--export-preview-pngs` 的引數**，且兩處都經由 helper 取值。

理由是這類回歸的形狀很特別——它不會讓任何功能測試變紅（輸出仍然合法，只是尺寸錯了），只會讓某台機器的預覽悄悄變糊或變大。行為測試抓不到，原始碼契約測試抓得到。

## Risks / Trade-offs

| 風險 | 緩解 |
| --- | --- |
| 新增的 `1/5` 未經真機驗證（既有實測只涵蓋 `1/4` 與 `1/10`） | 對 7536 機台補一次實跑：確認 `preview.zip` 內每張為 1507 × 648、快路徑命中、層檔 SHA-256 與基準一致 |
| 浮點捨入在未來新增 N 時靜默失效 | D6 的精確性測試對**集合中每個成員**斷言，新增成員時測試自動涵蓋 |
| 有人日後把 `max(x, y)` 「簡化」成 `display_pixels_x` | D2 的理由寫進本文件；測試中加入一組 portrait 輸入（x < y）鎖住行為 |
| `Image.BOX` 改動使備援產線輸出與過去不同 | 這正是目的（讓它符合 box-mean 契約）。備援產線僅在引擎預覽產出失敗時觸發，屬罕見路徑，且沒有位元相等的下游消費者 |
| 三個呼叫點日後再度分岔 | D7 的原始碼契約測試 |
| 「省 60%」的舊敘述已流入前端文件 | proposal 已記載更正值（體積 −56% / 時間 −18%，基準 16K）；回覆前端時明確更正 |

**取捨總結**：本變更實質只改變 7536 與 15120 兩種機台的輸出，3840 級與 5760 機台逐位元組相同。收益集中在 16K；代價是引入一個新的抽象層（helper + 四類測試）來管理一個過去是常數的值。這個代價值得付，因為固定常數在機隊擴張時的失效模式是「某台機器的預覽悄悄變糊」——沒有任何自動化訊號會提醒你。

## Migration Plan

改動全部落在 Python 層，`third_party/prusaslicer_fork` 不動、submodule 指標不變、無需重新編譯引擎。

1. 先落 helper 與其測試（無呼叫端，零行為變化）。
2. 接入 `sla_operations.py`（單純路徑）。
3. 接入 `jobs.py`（含 `config is None` 退路）。
4. 收斂 `preview_service.py` 三項。
5. 更新 spec 與 README。

**回滾**：任一步皆可獨立 revert；helper 為新增檔案，移除呼叫端即回到今日行為。由於 `N = 4` 等於今日的 `0.25`，即使只回滾部分呼叫點，系統仍處於一致的合法狀態。

## Open Questions

- **7536 機台（`N = 5`）的體積與時間實測值尚未取得。** 現有的 `-56% / -18%` 只涵蓋 16K。是否要在本變更內補測，或接受「唯一有數據的是 16K」並在 spec 中如實標註。
- **與前端的目視驗收排程。** 驗收 MUST 在 16K 機台執行（3840 級機台輸出逐位元組相同，驗收不具資訊量），需與 DS-Online 協調可用機台與時程。

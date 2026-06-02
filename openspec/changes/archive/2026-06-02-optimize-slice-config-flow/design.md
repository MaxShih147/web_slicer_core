## Context

現況 `execute_slice_job`（[api_v2.py:436](agent/api_v2.py#L436)）以 `sla_config = _convert_v2_config_to_sla(pending["config"])` 建構切片參數，其中 `pending["config"]` 是前端透過 `PUT /config` 傳入的 snake-case 切片 config；mechado（`prz_config`）只被持久化為 `prz_config.json`，**不參與 SLAConfig 萃取**。

本變更要把萃取真相來源收斂到後端：由完整 mechado config 萃取 SLAConfig（方案 B）。`POST /slices` 已經會收到 mechado（當作 `prz_config`，[api_v2.py:274-275](agent/api_v2.py#L274-L275)），因此「建立時即有完整 mechado」這個前提**今天已成立**，缺的只是後端萃取與一個 per-job 的 `center` 欄位。

既有 `_convert_v2_config_to_sla`（[api_v2.py:1513](agent/api_v2.py#L1513)）只讀 `Print` 區段或頂層 snake，遇到完整三段式 mechado 會丟失 `Machine` / `Advanced` 區段——所以需要**新函式**，而非修改舊函式。

## Goals / Non-Goals

**Goals:**
- 後端新增 `_extract_sla_from_mechado()`，從三段式 mechado 完整萃取切片參數（涵蓋 `Machine` / `Advanced`）。
- `POST /slices` 新增頂層 `center` 欄位；`printer_model` 由後端從 `Machine.machine_type` 萃取。
- execute 階段以「mechado 萃取為 base、PUT snake config 欄位級覆蓋」組裝最終 SLAConfig。
- 保證舊前端流程（POST 空 config + PUT snake + execute）行為不變。

**Non-Goals:**
- 不修改 `SLAConfig` 欄位語意或既有 `sla-slice-config` spec 行為。
- 不移除 `_convert_v2_config_to_sla`（仍為 snake 直讀與舊流程服務）。
- 不在本變更刪除前端 `uiToBackendSlicingConfig`（可留作過渡）。
- `download.prz` 的 optional/fallback 細節屬本變更範圍，但其行為驗收歸 specs 定義，不在此處展開實作。

## Decisions

### D1. 新增 `_extract_sla_from_mechado()`（不動舊函式）

偽代碼（位於 api_v2.py helper 區，約 1513 附近）：

```python
def _extract_sla_from_mechado(mechado: Dict[str, Any],
                              center: Optional[List[float]] = None) -> Dict[str, Any]:
    """從完整三段式 mechado config 萃取 SLAConfig 欄位（回傳 dict，尚未建模）。
    刻度防呆：AA Level / Image Blur Pixel 在 mechado 已是後端刻度 → 直接複製，禁止二次轉換。
    """
    machine  = mechado.get("Machine", {})
    printc   = mechado.get("Print", {})
    advanced = mechado.get("Advanced", {})
    out: Dict[str, Any] = {}

    def put(key, val):              # 僅在來源存在時寫入，缺值留給 SLAConfig 預設
        if val is not None:
            out[key] = val

    # ── 核心 9 欄位（對應前端 uiToBackendSlicing 權威清單）─────────────
    put("layer_height",       printc.get("Layer Height"))                 # 1
    img = machine.get("image_size")
    if isinstance(img, list) and len(img) >= 2:
        put("display_pixels_x", img[0])                                   # 2
        put("display_pixels_y", img[1])                                   # 3
    bed = machine.get("bed_size")                                         # [x0,y0,x1,y1]
    if isinstance(bed, list) and len(bed) >= 4:
        put("display_width",  bed[2])                                     # 4  (索引標準)
        put("display_height", bed[3])                                     # 5  (索引標準)
    put("anti_aliasing",       advanced.get("Anti-aliasing"))            # 6
    put("anti_aliasing_level", advanced.get("Anti-aliasing Level"))     # 7  直接複製
    put("gray_level",          advanced.get("Grey Level"))              # 8
    put("blur",                advanced.get("Image Blur Pixel"))        # 9  直接複製

    # ── 隨附欄位（非幾何 9 欄，但 SLAConfig 需要；沿用既有對照）─────────
    put("printer_model",        machine.get("machine_type"))             # 取代前端另傳
    put("exposure_time",        printc.get("Exposure Time"))
    put("initial_exposure_time",printc.get("Bottom Exposure Time"))
    put("bottom_layer_count",   printc.get("Bottom Layer Count"))
    # retract 4 欄：沿用 _inject_retract_overrides 正規化後的 Print 區段
    for sla_key, mechado_key in _SLA_RETRACT_TO_MECHADO.items():
        put(sla_key, printc.get(mechado_key))

    # ── center：相對位移 → 絕對座標（依賴正確的 display_width/height）──
    if isinstance(center, list) and len(center) >= 2:
        dw = out.get("display_width",  SLAConfig.model_fields["display_width"].default)
        dh = out.get("display_height", SLAConfig.model_fields["display_height"].default)
        out["center_x"] = center[0] + dw / 2
        out["center_y"] = center[1] + dh / 2
    return out
```

9 欄位映射路徑彙整：

| # | SLAConfig 欄位 | mechado 路徑 | 備註 |
|---|---|---|---|
| 1 | `layer_height` | `Print.Layer Height` | |
| 2 | `display_pixels_x` | `Machine.image_size[0]` | |
| 3 | `display_pixels_y` | `Machine.image_size[1]` | |
| 4 | `display_width` | `Machine.bed_size[2]` | **索引標準**（非 [0]）|
| 5 | `display_height` | `Machine.bed_size[3]` | **索引標準**（非 [1]）|
| 6 | `anti_aliasing` | `Advanced.Anti-aliasing` | |
| 7 | `anti_aliasing_level` | `Advanced.Anti-aliasing Level` | 已是後端刻度，直接複製 |
| 8 | `gray_level` | `Advanced.Grey Level` | |
| 9 | `blur` | `Advanced.Image Blur Pixel` | 已是後端刻度，直接複製 |

**Alternatives considered**：修改 `_convert_v2_config_to_sla` 使其同時吃巢狀 mechado。否決——它同時服務 snake 直讀與舊流程，混入巢狀解析會增加迴歸風險；獨立新函式邊界清楚、易測。

### D2. `V2SliceCreateRequest` 欄位擴充

```python
class V2SliceCreateRequest(BaseModel):
    config: Optional[Dict[str, Any]] = None       # 既有：snake-case（舊流程保留）
    prz_config: Optional[Dict[str, Any]] = None   # 既有：完整 mechado（方案 B 主要輸入）
    center: Optional[List[float]] = None          # 新增：per-job 幾何位移 [x, y]
```

`create_slice_job` 對應將 `center` 存入 pending：

```python
_pending_jobs[job_id] = {"config": request.config or {}, "models": [], "status": "created"}
if request.prz_config is not None:
    _pending_jobs[job_id]["prz_config"] = request.prz_config
if request.center is not None:
    _pending_jobs[job_id]["center"] = request.center
```

**理由**：`center` 是 per-job 幾何值，列為**獨立頂層欄位**（型別安全、語意清楚），不塞進 mechado dict 以免污染可重用的印表機 profile。`printer_model` 不另設欄位——由 D1 從 `Machine.machine_type` 萃取，避免雙真相來源。

### D3. execute 合併策略：base(mechado) ← override(snake)

改寫 `execute_slice_job`（[api_v2.py:436](agent/api_v2.py#L436)）的 SLAConfig 組裝：

```python
prz_cfg = pending.get("prz_config")
if prz_cfg is not None:
    _inject_retract_overrides(prz_cfg)
    with open(job_dir / "prz_config.json", "w") as f:
        json.dump(prz_cfg, f)

# ── 方案 B 合併：mechado 萃取為 base，PUT snake config 欄位級覆蓋 ──
merged: Dict[str, Any] = {}
if prz_cfg is not None:
    merged.update(_extract_sla_from_mechado(prz_cfg, pending.get("center")))
snake = pending.get("config") or {}
merged.update({k: v for k, v in snake.items() if v is not None})   # 欄位級 last-write-wins

sla_config = SLAConfig(**merged) if merged else _convert_v2_config_to_sla(snake)
```

合併語意（欄位級，非整包覆蓋）：

```
   _extract_sla_from_mechado(mechado, center)   ← base（新前端唯一來源）
                  │  dict.update()
                  ▼
        PUT /config 的 snake config             ← override（舊前端 / 特例）
                  │  僅覆蓋有提供的欄位
                  ▼
              SLAConfig(**merged)
```

**相容性保證**：
- 新前端：只送 mechado + center → `snake` 為空 → 結果 = 純萃取，符合單一真相。
- 舊前端：mechado 可能缺或為空 → base 空 → `snake` 全量覆蓋 → 退回等同今日 `_convert_v2_config_to_sla(snake)` 的行為（最後一行 fallback 亦保險）。
- `PUT /config` 特例：其 snake 欄位**逐欄覆蓋** mechado 萃取結果（符合「PUT 覆蓋 POST」決策）。

**Alternatives considered**：在 `POST` 當下即萃取並固化 SLAConfig。否決——會使後續 `PUT` 無法覆蓋，且與既有「execute 才建 job 目錄」時序不符。延後到 execute 合併最自然。

## Risks / Trade-offs

- **[萃取器與前端映射表漂移]** 新萃取器的欄位清單必須對齊前端 `uiToBackendSlicing`（9 欄）→ Mitigation：以 round-trip 等價測試（同一 uiParams 經 mechado 萃取 == 舊 snake 結果）作為迴歸守門，列入 tasks。
- **[bed_size 索引取錯]** 若誤用 `[0][1]` 會得到 0 幅面，並連帶使 `center_x/y` 位移錯誤 → Mitigation：以內建 profile（如 `[0,0,134,75]`）斷言 `display_width=134`，並驗證 center 絕對座標。
- **[二次刻度轉換]** 若對 AA Level / blur 再套一次 UI→backend transform 會數值錯誤 → Mitigation：萃取器對該兩欄明確「直接複製」，並於測試固定輸入值比對。
- **[mechado 缺欄位靜默退預設]** 萃取缺值會 fallback 到 SLAConfig 預設而不報錯 → Mitigation：缺關鍵欄位時記 log；新前端送的 mechado 由 `toEngineDefault` 從完整 seed 產出，欄位齊備。
- **[download.prz 改 optional 的行為變動]** 由「body 為唯一真相」改為「缺則 fallback `prz_config.json`」→ Mitigation：保留顯式傳入時仍以 body 優先，僅在缺省時 fallback；行為以 specs 場景固定。

### Known Issue → 疑似已解決：物件平移座標連動失效（先前既有問題）

**狀態：疑似由本變更附帶解決（2026-06-02 端到端驗證）。** 待更多擺位情境回歸後正式結案。

**使用者回饋（原問題）**：在 DS-online 網頁上**平移物件**後，切片結果的物件位置**並未對應位移**——`center` 參數沒有隨擺位更新而連動。此為**本專案進行前即存在的問題**。

**最新發現**：完成階段 6（前端切換單一真相流程）後，使用者實機驗證「切片過程順利、**UI 擺放 = 圖檔位置正確**」，先前的平移未連動問題**已不再重現**。

**推測原因**：舊流程中 `center` 經由 `PUT /config` 的 snake `slicingConfig` 路徑傳遞，疑似在某些情境下未被正確套用（或被 `set_center_defaults` 對 `< 0` 的重置吃掉）。新流程改為 **`POST /slices` 建立時即以頂層 `center` 欄位送出**，並由 `_extract_sla_from_mechado` 統一做 `center_x = center[0] + display_width/2` 換算，注入點單一且明確，連動因而恢復正常。

**結案前建議補驗**：負向位移、多模型擺位、極端邊界位移是否皆正確（注意 `set_center_defaults`（[models.py:120](agent/models.py#L120)）對 `center_x < 0` 仍會重置為顯示中心——若未來允許負絕對座標需再評估）。

## Future Works

### FW1. AA Level 顯示值（2/4/8）與控制值（0/1/2）分離（本變更不處理，僅記錄）

**需求**：DS-online 網頁上 `anti_aliasing_level` 的使用者選項為 `2 / 4 / 8`；未來希望 **PRZ 上呈現的參數顯示值也為 `2 / 4 / 8`**（即使用者看到的原始刻度），但**底層 prusa_slicer_fork 仍須使用控制刻度 `0 / 1 / 2`**，兩者互不影響。

```
        UI 選項            mechado 儲存          本變更萃取            PRZ 顯示
       (顯示刻度)          (已轉控制刻度)        (= 控制刻度)        (未來：顯示刻度)
        2 / 4 / 8   ──▶    0 / 1 / 2     ──▶    0 / 1 / 2     ──▶   ???（盼回 2/4/8）
                  uiToDefault                _extract_sla_      ↑ 目前無原始值可還原
                  已套刻度轉換                from_mechado        （資訊在前端已被壓成控制刻度）
```

**現況限制（本變更的邊界）**：`_extract_sla_from_mechado` 萃取出的 `anti_aliasing_level` **僅為切片控制值（Prusa 刻度 0/1/2）**，供 `SLAConfig` / prusa_slicer_fork 使用，**不代表也不負責** PRZ 最終的顯示內容。由於前端 `uiToDefault`（mappingTables.js:352）在寫入 mechado 時已經把 `2/4/8` 壓成 `0/1/2`，到了後端**原始顯示值已遺失**，無法單向還原（除非靠固定對照表反查）。

**未來若要在 PRZ 顯示原始值（2/4/8），可考慮的方向（擇一，待另案評估）**：
- **(A) mechado 保留原始刻度**：前端在 mechado 另存一欄原始顯示值（例如 `Advanced.Anti-aliasing Level Display = 8`），萃取/PRZ 生成時讀此欄作顯示，控制值仍走既有 0/1/2 欄位。資料最忠實，但 mechado 多一欄。
- **(B) 後端建立對照反查表**：在 PRZ 生成端維護 `{0:2, 1:4, 2:8}` 反查，把控制值還原成顯示值寫入 PRZ。零前端改動，但反查表須與前端 `antiAliasingLevelUiToBackend`（8→2,4→1,2→0）保持同步，有漂移風險。

**為何本變更不處理**：屬 PRZ 顯示層議題，與「config 流程收斂 / 切片正確性」正交；先記錄需求與限制，避免日後誤把控制值當顯示值。

## Open Questions

- `PUT /config` 特例是否需要同步支援 `center` 覆蓋？（目前設計 center 僅於 `POST` 提供；若特例需重新擺位再評估。）
- 前端 `uiToBackendSlicingConfig` 的過渡移除時程（本變更暫保留），待後端萃取驗證穩定後另案處理。
- AA Level 顯示值（2/4/8）回填 PRZ 採方向 (A) 或 (B)？（見 Future Works FW1，另案決定。）
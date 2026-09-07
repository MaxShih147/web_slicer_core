## Context

### 現狀
`POST /api/v2/prz/parse` 已能解析 PRZ V3.0 格式並回傳：
- `header`：全部 42+ 個列印參數
- `preview_small_b64` / `preview_large_b64`：兩張預覽圖（base64 PNG）
- `layer_count`：總層數

但 API 是無狀態的 — `PrzFile` 物件在 response 後即被 GC，後端不留存任何 session 狀態。`prz_decoder.py` 中的 `decode_layer_image(i)` 能 lazy decode 各層（zero-copy memoryview），但目前沒有任何 API endpoint 能呼叫它。

### 技術背景
- `PrzFile._data`：`memoryview`，持有整個 PRZ 原始位元組（零拷貝）
- `decode_layer_image(i)`：每次呼叫都從 memoryview slice 即時解壓 RLE → `(height, width)` uint8 ndarray，不快取結果
- 典型 PRZ 大小：100～500 MB；解碼後單層：1920×1080 × 1 byte ≈ 2 MB
- 前端（DS-Online）：Vue 3 + PrimeVue，`PreviewPage.vue` 已有垂直 Slider + `<img>` 顯示架構

---

## Goals / Non-Goals

**Goals:**
- 上傳 PRZ 一次後，前端能以 Slider 逐層取得各層 PNG，不需重複上傳
- 後端以 session 機制管理快取，並在 TTL 到期或前端主動釋放時自動清理記憶體
- 前端 Slider 體驗流暢（debounce + blob URL 本地快取）

**Non-Goals:**
- 同時支援多個不同 PRZ session（設計允許，但不做 LRU 限制保護，因本地工具單人使用）
- 預先解碼並快取所有層圖（維持 lazy decode，避免初始化時間過長）
- 串流傳輸（Streaming）或 WebSocket 推送層圖
- 支援層圖的壓縮格式之間切換（固定 PNG grayscale）

---

## Decisions

### D1：Session 儲存位置 — 記憶體 dict（選擇）vs 磁碟 vs Redis

**選擇：全域記憶體 dict `_prz_sessions: dict[str, tuple[PrzFile, float]]`**

- **為何不用磁碟**：每次層請求都要讀檔 + RLE 解碼，I/O 延遲高；而且 `memoryview` 本就是對原始 bytes 的零拷貝 — 轉存到磁碟反而多一次複製
- **為何不用 Redis**：本地工具，無分散式需求，引入外部依賴不必要
- **記憶體風險**：單個 PRZ 最大約 500 MB，本地單人使用可接受；TTL 機制確保不長期佔用

**Session ID**：`uuid.uuid4()` — 無法被預測，安全性足夠

---

### D2：TTL 清理機制 — asyncio 背景 task（選擇）vs 請求時觸發清理

**選擇：FastAPI `startup` 事件啟動 asyncio 背景 task，每 5 分鐘掃描一次**

```
條件：time.time() - last_access > 1800 (30分鐘)
```

- **為何不在請求時觸發**：若前端長時間不發層圖請求（使用者去做別的事），session 不會被清理；背景 task 更可靠
- **掃描間隔 5 分鐘**：最壞情況多保留 5 分鐘，可接受

---

### D3：層圖格式 — PNG grayscale（選擇）vs WebP vs JPEG

**選擇：PNG grayscale (8-bit)**

- 與 `decode_layer_image()` 回傳的 uint8 ndarray 直接對應，無需色彩空間轉換
- PNG 無損，不引入壓縮失真（列印層圖需精確灰階值）
- WebP 壓縮率更好，但 Pillow 支援度需確認，且解碼複雜度略高；此處傳輸量不是瓶頸（本地 127.0.0.1）

---

### D4：前端層圖快取 — blob URL Map（選擇）vs Base64 string vs 無快取

**選擇：`Map<number, string>` 儲存 `blobURL`**，key 為層 index，value 為 `URL.createObjectURL(blob)`

- blob URL 比 base64 更省記憶體（不額外編碼）
- 頁面卸載時統一呼叫 `URL.revokeObjectURL()` 釋放
- 快取 hit → 直接設定 `img.src`，不重複請求

**預取策略**：slider change 時，額外預取 `index ± 2` 的層（若尚未快取），提升滑動流暢度

**Debounce**：slider 拖動事件 debounce 150ms，避免快速滑動時打爆 API

---

### D5：前端 UI 位置 — 新元件 vs 複用 PreviewPage.vue

**選擇：新增獨立元件 `PrzViewer.vue`**，在 PRZ 匯入流程中插入

- `PreviewPage.vue` 目前與「切片後的 sliced job」綁定（從 Pinia `sliceStore.sliceJob.pngs` 讀資料），職責不同
- 獨立元件避免污染現有切片預覽流程
- 可在 import 完成後以 Dialog 或獨立頁面展示

---

## Risks / Trade-offs

| 風險 | 說明 | 緩解措施 |
|------|------|----------|
| 記憶體峰值 | 一個 500MB PRZ session + 2MB 解碼緩衝 | TTL 30分鐘自動清理；前端關頁時主動 DELETE |
| Session 洩漏 | 前端意外關閉而未呼叫 DELETE | TTL 背景 task 兜底清理 |
| 並發解碼安全 | 同一 session 同時請求多個層 | `PrzFile.decode_layer_image()` 僅讀 memoryview，天然並發安全（無共享寫入狀態） |
| blob URL 累積 | 前端快取了所有 2000 層的 blob URL | 頁面卸載時統一 revoke；或限制快取最多 N 層（LRU） |

---

## Migration Plan

1. 後端改動不影響現有 `POST /prz/parse` response 結構（只新增 `session_id` 欄位）
2. 既有前端若不使用 `session_id`，行為不變 — 向下相容
3. 部署順序：先部署後端（新增 endpoints），再部署前端（使用新 endpoints）
4. 回滾：前端回退至不顯示層瀏覽的版本；後端 `_prz_sessions` 即使存在也不影響現有功能

---

## Open Questions

- 前端 `PrzViewer.vue` 最終要放在哪個路由或 Dialog？（建議由 DS-Online 維護人員決定 UX 位置）
- 是否需要限制最大並存 session 數（如 LRU(3)）？目前設計不限制，因為本地工具

# imported-support-sanitization Specification

## Purpose

定義以 `--import-support-stl` 匯入的支撐網格在進入切片管線前的清理契約：重複面的判定基準（精確位元相等，明確排除容差合併）、清理必須發生的時機（`attach_imported_support()` 之前）、可觀測性（偵測到重複才輸出一行含前後面數與倍率的記錄），以及「清理 MUST NOT 改變任何切片輸出」這條不變式及其成立基礎。

本能力的定位是**防禦網而非根因修復**。重複面由上游的前端支撐匯出產生，只有上游能真正修好；此處的精確比對只攔得住「同一份幾何被原封不動寫入多次」這一種型態，若上游改為輸出座標經過擾動的近似重複，錯誤幾何仍會整份進入切片。這個限制寫在 requirement 裡，是為了避免後端去重上線後被誤認為根因已解決。

## Requirements

### Requirement: 匯入的支撐網格在進入切片管線前須去除完全重複的面

以 `--import-support-stl` 匯入的支撐網格，SHALL 在附加到 SLA print object 之前去除**完全重複的三角面**。判定基準 SHALL 為三個頂點座標的精確位元相等（含頂點順序）；同一組面出現 N 次時 SHALL 只保留一份。

去重 SHALL 發生在 `attach_imported_support()` 之前，使下游的 `slice_supports` 與 `merge_slices_and_eval_stats` 都作用在去重後的網格上。

#### Scenario: 五倍重複的支撐網格被收斂為單份
- **WHEN** 匯入的 STL 含 1,621,320 個三角面，其中每個唯一面恰好出現 5 次（唯一面數 324,264）
- **THEN** 附加到 print object 的網格 SHALL 只含 324,264 個面
- **AND** 切片產生的支撐交線段數 SHALL 由約 31.3 M 降至約 6.3 M

#### Scenario: 已乾淨的網格不受影響
- **WHEN** 匯入的 STL 不含任何完全重複的面
- **THEN** 網格的面數 SHALL 維持不變
- **AND** 面的順序 SHALL 維持不變

#### Scenario: 未匯入支撐時不執行去重
- **WHEN** 切片未使用 `--import-support-stl`（自產支撐或無支撐）
- **THEN** 系統 MUST NOT 對任何網格執行此去重流程

### Requirement: 去重判定不得使用容差合併

去重 MUST NOT 對頂點座標套用任何容差（tolerance）或就近合併（nearby merge）。只有精確位元相等的面才 SHALL 被視為重複。

此約束存在的理由是代價不對稱：容差合併可能誤刪合法的共面幾何（相鄰支撐柱貼合面、底筏與柱腳交界），而誤刪支撐幾何會直接造成列印失敗；相對地，漏刪非精確重複的面只是少省一些效能。

#### Scenario: 座標極接近但不相等的面不得被合併
- **WHEN** 兩個面的頂點座標差異僅為單一 float 的最低有效位
- **THEN** 兩個面 SHALL 都被保留
- **AND** 系統 MUST NOT 將其視為重複

#### Scenario: 頂點相同但繞序不同的面不得被合併
- **WHEN** 兩個面使用相同的三個頂點座標但繞序相反（法線方向相反）
- **THEN** 兩個面 SHALL 都被保留

### Requirement: 去重必須留下可觀測記錄

執行去重時，系統 SHALL 輸出一行記錄，內容 SHALL 至少包含去重前面數、去重後面數與倍率。當未偵測到任何重複時，系統 SHALL 不輸出該記錄（避免在正常情況下製造雜訊）。

此記錄的目的是讓任何來源的髒網格都留下痕跡，而不是靜靜地讓切片變慢數倍。

#### Scenario: 偵測到重複時輸出記錄
- **WHEN** 匯入的網格含 1,621,320 面、去重後為 324,264 面
- **THEN** 系統 SHALL 輸出一行同時含 `1621320`、`324264` 與倍率 `5.00` 的記錄

#### Scenario: 網格乾淨時不輸出記錄
- **WHEN** 匯入的網格不含任何完全重複的面
- **THEN** 系統 MUST NOT 輸出去重記錄

### Requirement: 去重不得改變任何切片輸出

去重 MUST NOT 改變切片的任何產出。以同一份輸入分別在去重啟用前後執行切片，產出的 `.sl1` 中**每一層層檔的 SHA-256 SHALL 完全一致**；`layer_count`、`resin_volume_ml`、`estimated_print_time` 與 `has_support_mesh` 亦 SHALL 完全一致。

此不變式成立的基礎是既有管線的三個既有機制：完全重疊的多邊形在 `merge_slices_and_eval_stats()` 的 `union_ex()` / `diff_ex()` 後本就收斂為一；`resin_volume_ml` 取自聯集後多邊形面積而非網格體積；支撐分類走 stdout marker 而與面數無關。

#### Scenario: 去重前後層檔逐層位元一致
- **WHEN** 以 5× 重複的支撐 STL 分別在去重啟用前與啟用後切片同一份模型與同一組參數
- **THEN** 兩份 `.sl1` 的層檔數量 SHALL 相等
- **AND** 對應層檔的 SHA-256 SHALL 逐一相等

#### Scenario: 去重前後統計數值一致
- **WHEN** 條件同上
- **THEN** 兩份 `status.json` 的 `layer_count`、`resin_volume_ml`、`estimated_print_time`、`has_support_mesh` SHALL 分別相等

### Requirement: 後端去重為防禦措施，不取代上游修復

此去重 SHALL 被視為**防禦網**而非根因修復。它只能攔截「完全相同的面被重複寫入」這一種型態；若上游改為輸出座標經過位移或擾動的近似重複幾何，去重將無法攔截，錯誤幾何仍會進入切片。

系統的記錄訊息與相關文件 SHALL 明確標示此限制，避免後端去重上線後被誤認為根因已解決。

#### Scenario: 近似重複的幾何無法被攔截
- **WHEN** 匯入的網格含五組幾何上重疊但頂點座標不完全相等的支撐
- **THEN** 去重 SHALL 不移除任何面
- **AND** 此情況 SHALL 被視為上游缺陷，而非本能力的失效


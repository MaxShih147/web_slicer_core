## 1. Phase 1 前置確認

- [x] 1.1 確認 `third_party/prusaslicer_fork` 目前 HEAD 為 commit `2ae9d24`（`git -C third_party/prusaslicer_fork log -1 --format=%H`）
- [x] 1.2 確認 `D:\repos\PhrozenOrca` 存在，可供 diff 參考（commits `2be8e66` shrinkage、`3f8cb9a` tolerance）
- [x] 1.3 確認 CMake build 目錄 `third_party/prusaslicer_build` 可正常執行 `cmake --build . --config Release -- /m:1`（先以現有程式碼做一次基準編譯）

## 2. Phase 1 — PrintConfig.hpp：宣告 11 個新參數

- [x] 2.1 在 `src/libslic3r/PrintConfig.hpp` 的 `PrintObjectConfig` macro 中，定位現有 FDM 參數群末尾
- [x] 2.2 插入說明性注解：`// SLA compensation params: declared here (PrintObjectConfig/FDM tier) rather than SLAPrintObjectConfig to avoid patching the SLA state-invalidation switch. CLI-only usage; changes detected via manual cache in SLAPrint::apply().`
- [x] 2.3 宣告 4 個收縮補償參數：`shrinkage_compensation`（ConfigOptionBool）、`shrinkage_compensation_x`、`shrinkage_compensation_y`、`shrinkage_compensation_z`（ConfigOptionFloat）
- [x] 2.4 宣告 7 個公差補償參數：`tolerance_compensation`、`bottom_tolerance_compensation`（ConfigOptionBool）、`tolerance_compensation_a`、`tolerance_compensation_b`、`bottom_tolerance_compensation_a`、`bottom_tolerance_compensation_b`（ConfigOptionFloat）、`bottom_layer_count`（ConfigOptionInt）

## 3. Phase 1 — PrintConfig.cpp：定義參數 metadata

- [x] 3.1 在 `src/libslic3r/PrintConfig.cpp` 的 `init_sla_params()` 或對應的 PrintObjectConfig 初始化區塊中，定義 `shrinkage_compensation`（label、type、default `false`）
- [x] 3.2 定義 `shrinkage_compensation_x/y/z`（label、type float、default `100.0`、unit `%`）
- [x] 3.3 定義 `tolerance_compensation` 與 `bottom_tolerance_compensation`（label、type bool、default `false`）
- [x] 3.4 定義 `tolerance_compensation_a/b` 與 `bottom_tolerance_compensation_a/b`（label、type float、default `0.0`、unit `mm`），**不加** `def->min = 0`（允許負值）
- [x] 3.5 定義 `bottom_layer_count`（label、type int、default `6`、min `0`）

## 4. Phase 1 — SLAPrint.hpp：新增 cache member variables

- [x] 4.1 在 `src/libslic3r/SLAPrint.hpp` 的 `SLAPrint` class 中新增 4 個收縮補償 cache：`m_shrinkage_compensation`（bool）、`m_shrinkage_compensation_x/y/z`（double）
- [x] 4.2 新增 7 個公差補償 cache：`m_tolerance_compensation`、`m_bottom_tolerance_compensation`（bool）、`m_tolerance_compensation_a/b`、`m_bottom_tolerance_compensation_a/b`（double）、`m_bottom_layer_count`（int）

## 5. Phase 1 — SLAPrint.cpp：apply() manual cache 與 sla_trafo()

- [x] 5.1 在 `src/libslic3r/SLAPrint.cpp` 的 `SLAPrint::apply()` 中，定位現有 manual cache 區塊末尾（約 line 333 附近）
- [x] 5.2 插入 **Shrinkage manual cache 區塊**：以 `config.opt<ConfigOptionBool>("shrinkage_compensation")` 讀取，`!=` 比較後更新 cache；若有變更，呼叫 `invalidate_step(slapsMergeSlicesAndEval)` + 所有 object 的 `invalidate_all_steps()` + `set_trafo()`
- [x] 5.3 同步讀取並比較 `shrinkage_compensation_x/y/z`，納入同一個 shrinkage 變更偵測邏輯
- [x] 5.4 插入 **Tolerance manual cache 區塊**：讀取所有 7 個 tolerance 參數，若有任何變更，呼叫 `invalidate_step(slapsMergeSlicesAndEval)` + 所有 object 的 `invalidate_step(slaposObjectSlice)`；C++ local 初始值加注解 `// Default false (not true as in PhrozenOrca): safe-off when key is absent from config.ini.`
- [x] 5.5 在 `sla_trafo()` 中，於套用 `relative_correction()` 之後插入 shrinkage 縮放：`corr.x() *= m_shrinkage_compensation_x / 100.0`（y/z 同）；guard 以 `m_shrinkage_compensation` 為條件
- [x] 5.6 在 `sla_trafo()` shrinkage 套用處加入日誌：`BOOST_LOG_TRIVIAL(info) << "[shrinkage] applying x=" << m_shrinkage_compensation_x << " y=" << m_shrinkage_compensation_y << " z=" << m_shrinkage_compensation_z;`

## 6. Phase 1 — SLAPrintSteps.cpp：apply_printer_corrections() tolerance 邏輯

- [x] 6.1 在 `src/libslic3r/SLAPrintSteps.cpp` 的 `apply_printer_corrections()` 函式頂端，取得 `SLAPrint` 的 tolerance cache 參照（或透過 `m_print` pointer 存取）
- [x] 6.2 實作 `apply_tc_layer` lambda（參考 PhrozenOrca `3f8cb9a`）：接受 `ExPolygons &layer_slices, coord_t ca, coord_t cb`；若 `ca == 0 && cb == 0` 提前返回；外輪廓 `offset(contour, cb)`；孔洞 `reverse()` 後 `offset(h, -ca)`；以 `diff_ex` 合併
- [x] 6.3 在 `absolute_correction` 之後、`elephant_foot` 之前插入一般層 tolerance 分支：guard 以 `m_tolerance_compensation` 且 `layer_index >= m_bottom_layer_count`；呼叫 `apply_tc_layer` 並加日誌 `[tolerance] applying tc a=? b=? layers=?..?`
- [x] 6.4 緊接著插入底層 tolerance 分支：guard 以 `m_bottom_tolerance_compensation` 且 `layer_index < m_bottom_layer_count`；呼叫 `apply_tc_layer` 並加日誌 `[tolerance] applying btc a=? b=? layers=0..?`

## 7. Phase 1 — 編譯驗證

- [x] 7.1 在 `third_party/prusaslicer_build` 執行 `cmake --build . --config Release -- /m:1`，確認零編譯錯誤、零相關 warning
- [x] 7.2 若有編譯錯誤，修正後重新執行直到通過

## 8. Phase 1 — 執行期驗證

- [x] 8.1 準備 `test_shrinkage.ini`：加入 `shrinkage_compensation = 1`、`shrinkage_compensation_x = 98`，以任意 `.stl` 執行 `prusa-slicer.exe --export-sla --load test_shrinkage.ini <model.stl>`
- [x] 8.2 確認 exit code `0` 且 log output 含有 `[shrinkage] applying` 字串
- [x] 8.3 準備 `test_tolerance.ini`：加入 `tolerance_compensation = 1`、`tolerance_compensation_b = 0.1`、`bottom_layer_count = 3`，執行相同指令
- [x] 8.4 確認 exit code `0` 且 log output 含有 `[tolerance] applying tc` 字串
- [x] 8.5 以 **UVtools** 打開輸出的 `.sl1`，目視確認 tolerance 輪廓偏移效果（每層外輪廓向外擴張約 0.1mm）

## 9. Phase 2 — Python：SLAConfig 新增欄位

> **前提**：Phase 1 第 7 節編譯驗證必須通過後才進行此節以後的工作。

- [x] 9.1 開啟 `agent/models.py`，在 `SLAConfig` class 末尾新增收縮補償欄位：`shrinkage_compensation: bool = False`、`shrinkage_compensation_x: float = 100.0`、`shrinkage_compensation_y: float = 100.0`、`shrinkage_compensation_z: float = 100.0`
- [x] 9.2 緊接著新增公差補償欄位：`tolerance_compensation: bool = False`、`tolerance_compensation_a: float = 0.0`、`tolerance_compensation_b: float = 0.0`、`bottom_tolerance_compensation: bool = False`、`bottom_tolerance_compensation_a: float = 0.0`、`bottom_tolerance_compensation_b: float = 0.0`、`bottom_layer_count: int = 6`
- [x] 9.3 確認新增後 `SLAConfig()` 無引數建構仍可正常執行（Pydantic 預設值驗證）

## 10. Phase 2 — Python：api_v2.py key mapping

- [x] 10.1 開啟 `agent/api_v2.py`，定位 `_convert_v2_config_to_sla()` 函式的 mapping dict（約 line 1188）
- [x] 10.2 新增 4 組收縮補償 mapping：`"Shrinkage Compensation"` → `shrinkage_compensation`、`"Shrinkage Compensation X"` → `shrinkage_compensation_x`、`"Shrinkage Compensation Y"` → `shrinkage_compensation_y`、`"Shrinkage Compensation Z"` → `shrinkage_compensation_z`
- [x] 10.3 新增 6 組公差補償 mapping：`"Tolerance Compensation"` → `tolerance_compensation`、`"Tolerance Compensation A"` → `tolerance_compensation_a`、`"Tolerance Compensation B"` → `tolerance_compensation_b`、`"Bottom Tolerance Compensation"` → `bottom_tolerance_compensation`、`"Bottom Tolerance Compensation A"` → `bottom_tolerance_compensation_a`、`"Bottom Tolerance Compensation B"` → `bottom_tolerance_compensation_b`
- [x] 10.4 新增 `"Bottom Layer Count"` → `bottom_layer_count` mapping（一魚兩吃，既有 PRZ 流程不動）
- [x] 10.5 確認 `prz_encoder.py` 讀取 `"Print.Bottom Layer Count"` 的現有邏輯未受任何修改

## 11. Phase 2 — Python 驗證

- [x] 11.1 送含 `{"Shrinkage Compensation": true, "Shrinkage Compensation X": 98}` 的 API request，確認生成的 `config.ini` 含 `shrinkage_compensation = 1` 與 `shrinkage_compensation_x = 98.0`，數值無任何換算
- [x] 11.2 送含 `{"Tolerance Compensation": true, "Tolerance Compensation B": 0.1, "Bottom Layer Count": 4}` 的 API request，確認 `config.ini` 含 `tolerance_compensation = 1`、`tolerance_compensation_b = 0.1`、`bottom_layer_count = 4`
- [x] 11.3 執行完整端對端切片流程（API request → config.ini → prusa-slicer binary），確認 binary 無錯誤退出（exit code `0`）
- [x] 11.4 確認 `"Bottom Layer Count"` key 的 PRZ 輸出（`.prz` 底層曝光設定）與加入功能前行為相同

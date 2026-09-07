# PrusaSlicer 支撐生成 crash（UniformSupportIsland）— 原因與修正

> 日期：2026-06-13
> 範圍：`third_party/prusaslicer_fork`（C++ fork，branch `master`）
> 檔案：`src/libslic3r/SLA/SupportIslands/UniformSupportIsland.cpp`

## 症狀

特定模型（測試用 `04.stl`，35×35×20 方塊）生 SLA 支撐時，PrusaSlicer 直接
abort（SIGABRT），整個切片程序崩潰。多物件一起生支撐時，只要其中含這類幾何，
**整批一起死**。

錯誤訊息為 heap 損毀：

```
malloc: *** error for object 0x...: pointer being freed was not allocated
```

堆疊頂在：

```
merge_island_parts
  ← Slic3r::sla::uniform_support_island
  ← Slic3r::sla::generate_support_points
  ← SLAPrint::Steps::support_points
```

> 注意：因為是未定義行為（UB），症狀不穩定——同一份壞資料有時是 crash、
> 有時變成無窮迴圈卡在 100% CPU。

## 根本原因

支撐島演算法在**建構階段（Voronoi 圖 BFS）**遇到「迴路接回已處理節點」時，會呼叫
`merge_parts_and_fix_process` 把兩個 island part 合併。合併會從 `island_parts`
陣列**移除一個元素**，因此所有「指向各 part 的索引」都必須跟著修正。

該函式對 **process queue** 內的索引修正是完整的（兩種情況都處理）：

- `== 被移除索引` → 改指向合併後存活的 part（`index`）
- `> 被移除索引`  → 減一

但對「**目前正在處理的 item**」`item.i`，**只做了 `> 被移除索引 → 減一`，
漏掉 `== 被移除索引` 的情況**：

```cpp
// 修正前
// fix indices in process queue
for (ProcessItem &p : process)
    if (p.i == remove_index)      p.i = index;   // ✅ 兩種都修
    else if (p.i > remove_index)  --p.i;

// fix index for current item
if (item.i > remove_index)        --item.i;       // ❌ 漏掉 == 的情況
```

而函式開頭有：

```cpp
if (remove_index < index) std::swap(remove_index, index);
```

當呼叫端傳入的兩個索引是「佇列索引 < 目前 item 索引」時，swap 後 `remove_index`
會**剛好等於原本的 `item.i`**。此時這個 item 指向的正是被移除的 part，卻沒有被
重新指到存活的 part → `item.i` 留下一個**指向已移除 / 不存在 part 的失效索引**
（陣列縮小後，數值正好等於 `size`，超界一格）。

這個帶著失效索引的 item 之後被重新放回佇列；下一次迴路接回時，它的失效索引被當成
「要移除的索引」傳進 `merge_island_parts`，執行：

```cpp
island_parts.erase(island_parts.begin() + remove_index);  // remove_index == size
```

→ 對**超界位置**做 erase → heap 損毀 → abort。

### 診斷方式（供日後參考）

Release build 把 `assert` 與區域變數最佳化掉，lldb 讀不到 `index`/`remove_index`。
最終是靠在 `merge_island_parts` 內**逐步驟加 `fprintf` + `fflush`** 重現崩潰，
觀察「崩潰前最後印出的步驟與索引值」鎖定到：

```
PRE i=0 r=10 sz=10   ← remove_index(10) == size(10)，超界一格
A enter ... rchg=0    ← 已在讀 island_parts[10]（越界，讀到垃圾）
... 然後 island_parts.erase(begin()+10) → crash
```

並由「`island start` 標記在崩潰前**沒有**印出」判定崩潰發生在建構階段
（merge_parts_and_fix_process），而非後段的 merge_middle / merge_same。

## 修正

`merge_parts_and_fix_process` 結尾，讓 `item.i` 比照 process queue 補上
`== remove_index` 分支：

```cpp
// 修正後
if (item.i == remove_index)
    item.i = index;          // 重指到合併後存活的 part
else if (item.i > remove_index)
    --item.i;
```

共 4 行，與既有 process-queue 修正邏輯一致。

## 驗證

重現用 job：`agent/jobs/3c0f9758/`（`input/model.stl` = 04、`config.ini`）

```bash
MACOSX_DEPLOYMENT_TARGET=15.0 \
  third_party/prusaslicer_build/src/prusa-slicer \
  --export-sla --export-support-stl \
  --output output/test.sl1 --load config.ini input/model.stl
```

- 修正前：exit **134**（SIGABRT）
- 修正後：**連續 3 次** exit **0**、`Slicing done`、正常輸出 `*_support.stl`

## 影響範圍

- 純 C++ fork 的支撐演算法修正，**不影響前端 / 多模型邏輯**。
- 補上既有修正邏輯漏掉的一個分支，風險低、行為與正常情況一致。

## Build 備註（與本修正無關，但重編必看）

本機 macOS SDK 由 15.0 升到 15.2，但既有 PCH 仍是 15.0，直接 `make` 會撞
PCH target 不符。增量重編請帶 deployment target：

```bash
cd third_party/prusaslicer_build
MACOSX_DEPLOYMENT_TARGET=15.0 make PrusaSlicer -j7
```

agent 使用 `third_party/prusaslicer_build/src/prusa-slicer`（symlink → PrusaSlicer），
每次切片 spawn 新 CLI，重編後**不需重啟 agent**。

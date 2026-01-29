# 計畫：Hollow Shell Open Bottom（薄殼開底）

> 狀態：待實驗 - 需先驗證 trimesh boolean 效果
> 日期：2025-01-27

## 目標確認

### 我們要達成什麼？

**輸入**：一個 3D 模型（STL）
**輸出**：一個「薄殼、底部開口」的模型

視覺化說明：
```
原始模型          Hollow 結果         我們要的結果
┌─────────┐      ┌─────────┐        ┌─────────┐
│█████████│      │┌───────┐│        │┌───────┐│
│█████████│  →   ││       ││   →    ││       ││
│█████████│      ││       ││        ││       ││
│█████████│      │└───────┘│        │└───────┘│
└─────────┘      └─────────┘        └────   ──┘
  實心            中空但封閉          中空且開底
```

## 調查結論：為什麼不能用 plane-cut？

根據對 PrusaSlicer 原始碼的調查：

1. **plane-cut 的語義是 solid cut**：目標是永遠輸出 watertight solid
2. **補面是無條件的**：`triangulate_caps=true` 是硬編碼預設值
3. **每個 volume 獨立處理**：outer 和 inner mesh 被視為獨立 solid，各自補面
4. **Contour nesting 存在但用途錯誤**：nesting 資訊只用來「補成實心」而非「保留中空」

關鍵程式碼位置：
- `TriangleMeshSlicer.cpp:2445` - `cut_mesh()` 主入口
- `TriangleMeshSlicer.cpp:2312-2413` - `triangulate_slice()` 補面邏輯
- `CutUtils.cpp:335-346` - volume 獨立處理迴圈

## 正確的幾何做法

1. 將 inner mesh **向下延伸**，超過模型底部
2. 用 **boolean subtract**：outer - extended_inner
3. 結果自然產生「環狀開口」

```
Step 1: 延伸 inner       Step 2: Boolean subtract
┌─────────┐              ┌─────────┐
│┌───────┐│              │┌───────┐│
││       ││              ││       ││
││       ││      →       ││       ││
│└───────┘│              │└───────┘│
└─────────┘              └────   ──┘
│         │  ← inner 延伸超過底部
│         │
└─────────┘
```

---

## 技術方案（待驗證）

### 新增依賴

```
trimesh>=4.0.0
```

trimesh 提供：
- 網格讀寫（STL）
- Boolean 操作（基於 manifold3d 或 blender）
- 網格變換（translate, scale）
- 網格修復（fix normals, fill holes）

### 實作步驟

#### 1. 新增函式：`extend_mesh_bottom()`

將 mesh 底部向下延伸指定距離。

```python
def extend_mesh_bottom(mesh: trimesh.Trimesh, extension: float) -> trimesh.Trimesh:
    """
    將 mesh 底部的邊緣向下延伸，形成封閉的延伸體。
    """
```

#### 2. 新增函式：`boolean_subtract()`

```python
def boolean_subtract(mesh_a: trimesh.Trimesh, mesh_b: trimesh.Trimesh) -> trimesh.Trimesh:
    """
    計算 mesh_a - mesh_b（從 A 中挖掉 B）
    """
    return mesh_a.difference(mesh_b, engine='manifold')
```

#### 3. 新增 API：`create_open_bottom_hollow()`

```python
async def create_open_bottom_hollow(
    job_id: str,
    wall_thickness: float = 3.0,
) -> OperationResult:
    """
    建立底部開口的薄殼模型。
    開口永遠在模型最底部（min Z）。
    """
```

---

## 風險與備案

| 風險 | 備案 |
|------|------|
| trimesh boolean 失敗（non-manifold mesh） | 先用 `mesh.fill_holes()` 修復 |
| inner mesh 法線方向錯誤 | 檢查並翻轉法線 |
| 延伸後 mesh 自交 | 調整延伸距離或使用 convex hull |

---

## 目前進度：Open Bottom with Honeycomb

### 完成的流程（整合為一鍵按鈕）

```
1. Generate hollow → H (inner mesh)          ← PrusaSlicer backend
2. Extend H bottom → H_e                     ← 前端 extendBottomVertices()
3. Generate honeycomb cells (raycast heights) → hc  ← 前端 showHexGrid()
4. Extend hc bottom → hc_e                   ← 前端 _buildHexCell(bottomZ)
5. A = H_e ∩ hc_e (intersection)             ← backend boolean API
6. Result = M - A (difference)               ← backend boolean API
```

### 關鍵設計決策

- **所有 boolean 使用前端座標系（matrixWorld）**：因為 outer 和 inner mesh 各自做了 `geometry.center()`，local space 座標不一致。用 matrixWorld 導出可保證 "what you see is what you get"。
- **Intersection 結果用 `addTempPreviewMesh()` 載入**：不做 `center()` 和 landing，保持 world-space 位置。
- **Raycast miss 的 cell 保留**：高度設為 inner mesh 頂部 + 5mm，intersection 會自動裁切。

### 已知問題（待修復）

**M - A (Step 6) 回傳 server 500 error**

- Step 1-5 皆正常完成
- Step 6（M - A difference）呼叫 `POST /api/v2/boolean` 時回傳 HTTP 500

### 檔案結構

| 檔案 | 角色 |
|------|------|
| `DS-Online/src/three/sceneCoordinator.js` | hex grid 建構、cell 底部延伸、temp preview mesh |
| `DS-Online/src/components/features/slicing/BackendSlicerPanel.vue` | UI + 一鍵流程 `handleOpenBottomFull()` |
| `DS-Online/src/services/backendSlicer.js` | `geometryToSTLBlob()`, `performBoolean()` |
| `web_slicer_core/agent/sla_operations.py` | `boolean_operation()` (trimesh + manifold3d) |
| `web_slicer_core/agent/api_v2.py` | `POST /api/v2/boolean` endpoint |

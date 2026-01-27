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

## 下一步：Boolean 實驗

在實作完整功能前，先驗證 trimesh boolean 的效果：

1. 新增獨立的 boolean API endpoint
2. 前端傳入兩個模型
3. 執行 union 或 difference
4. 檢視結果品質

"""Tests for prz_encoder.sl1_layer_names() — the single source of truth for
.sl1 layer-file enumeration (spec: sl1-layer-access, Requirement「統一 .sl1 層檔列舉」).

Covers:
  - 純 .rle：正確列舉並排序，設定檔不納入
  - 純 .png：退回 .png 列舉並排序
  - .rle + .png 並存：.rle 優先，不混入 .png
  - 縮圖不污染：thumbnail/ 子目錄的 .png 被排除
  - 排序：亂序輸入回傳層索引升冪序

No mocks: exercises the real pure function against plain name lists.
"""

from agent.prz_encoder import sl1_layer_names


# 常見的非層檔（設定檔 / 縮圖），任何情況都不應被計入層數。
_CONFIG_FILES = ["config.ini", "prusaslicer.ini", "config.json"]
_THUMBNAIL = "thumbnail/thumbnail400x400.png"


def _rle(n: int) -> str:
    return f"model{n:05d}.rle"


def _png(n: int) -> str:
    return f"model{n:05d}.png"


# ---------------------------------------------------------------------------
# 純 .rle
# ---------------------------------------------------------------------------

def test_pure_rle_lists_and_sorts_excluding_config():
    names = _CONFIG_FILES + [_rle(i) for i in range(200)]
    result = sl1_layer_names(names)
    assert result == [_rle(i) for i in range(200)]
    assert len(result) == 200
    # 設定檔不得混入
    for cfg in _CONFIG_FILES:
        assert cfg not in result


# ---------------------------------------------------------------------------
# 純 .png
# ---------------------------------------------------------------------------

def test_pure_png_falls_back_to_png():
    names = _CONFIG_FILES + [_png(i) for i in range(3)]
    result = sl1_layer_names(names)
    assert result == [_png(0), _png(1), _png(2)]


# ---------------------------------------------------------------------------
# .rle + .png 並存 → .rle 優先
# ---------------------------------------------------------------------------

def test_rle_takes_priority_over_png():
    names = _CONFIG_FILES + [_rle(0), _rle(1), _png(0), _png(1)]
    result = sl1_layer_names(names)
    assert result == [_rle(0), _rle(1)]
    # 不得混入任何 .png
    assert all(n.endswith(".rle") for n in result)


# ---------------------------------------------------------------------------
# 縮圖不污染層數統計
# ---------------------------------------------------------------------------

def test_thumbnail_png_is_excluded():
    names = _CONFIG_FILES + [_THUMBNAIL] + [_png(i) for i in range(5)]
    result = sl1_layer_names(names)
    assert _THUMBNAIL not in result
    assert result == [_png(i) for i in range(5)]
    assert len(result) == 5  # 縮圖不使層數超計


def test_thumbnail_not_counted_in_rle_mode():
    names = _CONFIG_FILES + [_THUMBNAIL] + [_rle(i) for i in range(4)]
    result = sl1_layer_names(names)
    assert _THUMBNAIL not in result
    assert result == [_rle(i) for i in range(4)]


# ---------------------------------------------------------------------------
# 排序：亂序輸入 → 層索引升冪
# ---------------------------------------------------------------------------

def test_unordered_input_is_sorted_by_layer_index():
    names = [_rle(3), _rle(0), _rle(10), _rle(2), _rle(1)]
    result = sl1_layer_names(names)
    assert result == [_rle(0), _rle(1), _rle(2), _rle(3), _rle(10)]


# ---------------------------------------------------------------------------
# 邊界：無層檔 → 空 list
# ---------------------------------------------------------------------------

def test_no_layer_files_returns_empty():
    assert sl1_layer_names(_CONFIG_FILES) == []
    assert sl1_layer_names([]) == []
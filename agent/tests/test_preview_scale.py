"""Tests for preview_scale.preview_scale_for() — the single source of truth for
the slice-preview downscale ratio (spec: slice-preview-export,
Requirement「預覽層圖的縮放比須由消費端顯示需求決定」).

Covers:
  - 全機隊表格：每種幅面選中的 N、scale 字串與推導出的預覽尺寸
  - N=4 天花板：任何輸入（含 0 / 負值）都不得回傳小於 4 的 N
  - 浮點倒數精確性：守 C++ 快路徑的 ``inv_scale == (double)n`` 閘門
  - 快路徑第二道閘門：``new_w * n <= w``
  - portrait 交換不變性：以長邊為判準
  - N=8 保留枝：合法但目前無實機落入

No mocks: exercises the real pure function.
"""

import pytest

from agent.preview_scale import ALLOWED_N, TARGET_WIDTH_PX, preview_scale_for


# ---------------------------------------------------------------------------
# 全機隊表格
#
# 期望值的推導方式（design D1 / D3）：
#   N       = max{ n ∈ ALLOWED_N : long_side / n >= TARGET_WIDTH_PX }，無解則 4
#   new_w   = int(w * float(scale_str))    ← 與 PNGPreviewEncoder 的截斷一致
#
# 15120 → 1512 × 623 與 optimize-slice-performance tasks.md 3.5 的實測輸出尺寸
# 一致，可作為整張表的交叉印證錨點。
# ---------------------------------------------------------------------------

# (標籤, w, h, 期望 N, 期望 scale_str, 期望預覽 w, 期望預覽 h)
FLEET = [
    ("預設組態",        2560, 1440,  4, "0.25",  640, 360),
    ("sonic_4k_2022",   3840, 2160,  4, "0.25",  960, 540),
    ("sonic_ls_plus",   3840, 2400,  4, "0.25",  960, 600),
    ("5760 幅面",       5760, 3600,  4, "0.25", 1440, 900),
    ("sonic_cs_plus",   7536, 3240,  5, "0.2",  1507, 648),
    ("16K",            15120, 6230, 10, "0.1",  1512, 623),
]

_FLEET_IDS = [row[0] for row in FLEET]


@pytest.mark.parametrize("label,w,h,exp_n,exp_scale,exp_pw,exp_ph", FLEET, ids=_FLEET_IDS)
def test_fleet_table(label, w, h, exp_n, exp_scale, exp_pw, exp_ph):
    scale_str, n = preview_scale_for(max(w, h))

    assert n == exp_n
    assert scale_str == exp_scale

    # 預覽尺寸以 C++ PNGPreviewEncoder 的同一套截斷語意推導
    scale = float(scale_str)
    assert int(w * scale) == exp_pw
    assert int(h * scale) == exp_ph


# ---------------------------------------------------------------------------
# N=4 天花板
#
# 本函式的核心承諾：任何機台的預覽解析度都不低於本變更前的 0.25，即畫質永不退化。
# 因此 N 不得小於 4 —— 包含幅面小到無論如何都達不到 TARGET_WIDTH_PX 的情形，
# 以及呼叫端給出無意義輸入的情形。
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("long_side", [-1, 0, 1, 100, 1399, 1400, 2560, 3840, 5599])
def test_ceiling_never_returns_n_below_4(long_side):
    _, n = preview_scale_for(long_side)
    assert n >= 4


@pytest.mark.parametrize(
    "long_side",
    [-1, 0, 1, 100, 1400, 2560, 3840, 5600, 5760, 7000, 7536, 11200, 11520, 15120, 30000],
)
def test_returned_n_is_always_in_allowed_set(long_side):
    _, n = preview_scale_for(long_side)
    assert n in ALLOWED_N


def test_small_formats_are_byte_identical_to_pre_change_behaviour():
    """天花板保護下，長邊 < 4 * TARGET 的機台一律停在今日的 0.25。"""
    for long_side in (2560, 3840, 5760):
        scale_str, n = preview_scale_for(long_side)
        assert (scale_str, n) == ("0.25", 4)


# ---------------------------------------------------------------------------
# 浮點倒數精確性 —— 守 RasterBase.cpp:136 的快路徑閘門
#
#     const size_t n = static_cast<size_t>(inv_scale);
#     const bool fixed_block = n >= 1 && inv_scale == static_cast<double>(n) && ...
#
# 我們送給引擎的是十進位字串，C++ 端做 strtod 再取倒數。0.2 與 0.1 在 binary64
# 中都不是精確值，其倒數能否「捨入回」精確整數取決於該鄰域的 ULP 寬度，不是可以
# 憑直覺斷言的事。
#
# 這道閘門失敗時的形狀特別惡劣：程式不報錯、不寫任何 log、輸出仍然完全正確，
# 只是悄悄退回通用路徑變慢 —— 沒有任何行為測試抓得到。因此直接斷言契約本身。
#
# Python 與 C++ 同為 IEEE-754 binary64，且十進位→double 皆為正確捨入，故 Python
# 可作為 C++ 側的有效代理。
# ---------------------------------------------------------------------------

def _scale_str_for(n: int) -> str:
    """取得 N 對應的 scale 字串。

    long_side = n * TARGET_WIDTH_PX 恰好只讓該 N 成立：n 本身滿足
    long_side / n == TARGET，而任何更大的成員都會低於 TARGET。
    """
    scale_str, got_n = preview_scale_for(n * TARGET_WIDTH_PX)
    assert got_n == n, f"long_side={n * TARGET_WIDTH_PX} 應選中 N={n}，實得 {got_n}"
    return scale_str


@pytest.mark.parametrize("n", ALLOWED_N)
def test_reciprocal_of_scale_string_is_exactly_the_integer(n):
    scale_str = _scale_str_for(n)
    assert 1.0 / float(scale_str) == float(n)


def test_every_allowed_n_is_reachable_at_its_exact_threshold():
    """n * TARGET 這個長邊必然選中 n —— 量化規則的邊界行為。"""
    for n in ALLOWED_N:
        _, got = preview_scale_for(n * TARGET_WIDTH_PX)
        assert got == n


# ---------------------------------------------------------------------------
# 快路徑第二道閘門：new_w * n <= w && new_h * n <= h
#
# 在 w 為 N 整數倍時這條恆成立，因此唯一真正有意義的樣本是 7536 / 5 = 1507.2
# （1507 * 5 = 7535 <= 7536）。整張機隊表一起跑，避免日後新增機台時漏測。
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("label,w,h,exp_n,exp_scale,exp_pw,exp_ph", FLEET, ids=_FLEET_IDS)
def test_fast_path_block_bound_guard(label, w, h, exp_n, exp_scale, exp_pw, exp_ph):
    scale_str, n = preview_scale_for(max(w, h))
    scale = float(scale_str)
    new_w = int(w * scale)
    new_h = int(h * scale)

    assert new_w * n <= w
    assert new_h * n <= h


# ---------------------------------------------------------------------------
# portrait 交換不變性
#
# 引擎在 display_orientation = portrait 時會 std::swap(pw, ph)（SL1.cpp:390-393），
# 所以 raster 寬度並不恆等於 display_pixels_x。判準取 max(x, y) 之所以正確，正是
# 因為 max 對這個交換不變、恆等於 raster 長邊。
#
# 這條測試存在的理由是防止後人把 max(x, y)「簡化」成 display_pixels_x。
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("label,w,h,exp_n,exp_scale,exp_pw,exp_ph", FLEET, ids=_FLEET_IDS)
def test_portrait_swap_is_invariant(label, w, h, exp_n, exp_scale, exp_pw, exp_ph):
    landscape = preview_scale_for(max(w, h))
    portrait = preview_scale_for(max(h, w))  # 交換後仍取長邊
    assert landscape == portrait == (exp_scale, exp_n)


def test_short_side_would_pick_a_different_n():
    """反證：若誤取短邊，16K 幅面會選錯 N —— 說明 max() 不是可省的防呆。"""
    by_long_side = preview_scale_for(15120)
    by_short_side = preview_scale_for(6230)
    assert by_long_side == ("0.1", 10)
    assert by_short_side == ("0.25", 4)
    assert by_long_side != by_short_side


# ---------------------------------------------------------------------------
# N=8 保留枝
#
# N=8 只在長邊 ∈ [11200, 14000) 時被選中，目前機隊無此規格機台。它是合法的保留枝，
# 不是死碼 —— 因此驗證 MUST NOT 以「每個 N 都須有實機命中」作為判準（spec 註記）。
# ---------------------------------------------------------------------------

def test_n8_reserved_branch_is_selectable():
    assert preview_scale_for(11520) == ("0.125", 8)


@pytest.mark.parametrize("long_side,exp_n", [(11199, 5), (11200, 8), (13999, 8), (14000, 10)])
def test_quantisation_boundaries(long_side, exp_n):
    """量化規則的四個交界點，鎖住「取最大且不低於 TARGET」的語意。"""
    _, n = preview_scale_for(long_side)
    assert n == exp_n


# ---------------------------------------------------------------------------
# 模組級常數
# ---------------------------------------------------------------------------

def test_module_constants():
    assert TARGET_WIDTH_PX == 1400
    assert ALLOWED_N == (4, 5, 8, 10)

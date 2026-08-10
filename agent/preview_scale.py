"""預覽層圖縮放比的單一真值來源。

spec: slice-preview-export,「預覽層圖的縮放比須由消費端顯示需求決定」。

縮放比不是任選的：DS-Online 的預覽對話框寬度上限 560 CSS px，扣除內距後 ``<img>``
實際渲染約 520 CSS px，DPR 2 下需要約 1040 device px。固定比例無法同時服務整個
機隊 —— 對 15120 幅面，0.25 產出 3780 px（需求的 3.6 倍）；但同一個 0.10 套到
5760 幅面只剩 576 px，遠低於需求。顯示需求是一個**絕對像素寬**，縮放比卻是一個
**比例**，所以旋鈕必須隨幅面轉。

輸出的縮放比同時受一道引擎側的硬約束：見 ``ALLOWED_N``。
"""

# 量化目標寬度。取 1400 而非推導出的最低需求 1040，是因為量化後的落點是離散的，
# 貼著最低需求會毫無餘裕。1400 在 15120 上仍選中 N=10，同時讓 5760 保住 N=4
# （5760 / 4 = 1440，只差 40 px 就會掉到 N=5 的 1152）。
TARGET_WIDTH_PX = 1400

# 允許的縮放分母。兩個條件把這組數字夾了出來：
#
#   下界 N=4：等於本變更前的 0.25。它同時是**天花板** —— 保證任何機台的預覽解析度
#     都不低於變更前，即畫質永不退化。長邊小於 4 * TARGET_WIDTH_PX 的機台因此
#     停在 0.25（3840 級機台的 960 px 低於 1040 device px 的推導需求，這是明文
#     接受的取捨：要消除它只能納入 1/2、1/3，那會讓該級機台的 preview.zip 膨脹
#     為 4 倍，與降低預覽成本的目的直接衝突）。
#
#   成員必須是 1/N 快路徑：引擎的 PNGPreviewEncoder 只在
#     ``inv_scale == static_cast<double>(n)`` 位元級成立時才走固定 N x N 區塊的
#     快路徑（RasterBase.cpp:135-137）。而我們交給 CLI 的是十進位字串，C++ 端做
#     strtod 再取倒數 —— 見 _SCALE_STR 的註解。
#
# N=8 目前無機台落入（只在長邊 [11200, 14000) 被選中），是合法的保留枝而非死碼。
ALLOWED_N = (4, 5, 8, 10)

# N -> 交給 ``--export-preview-pngs`` 的十進位字串。
#
# 回傳字串而非 float 是刻意的：CLI 引數終究要序列化成十進位字串，讓「哪個字串對應
# 哪個 N」成為此處唯一的、可測試的事實。若改為回傳 float 再由各呼叫端自行格式化，
# 格式化方式一分岔，快路徑就可能在其中一條路徑上靜默失效。
#
# 0.2 與 0.1 在 binary64 中都不是精確值，但其倒數捨入後**恰好**落回 5.0 / 10.0，
# 因此四個成員全數命中快路徑。這是四次幸運，不是一條定理 —— 任何新增成員都必須
# 通過 test_preview_scale.py 的 ``test_reciprocal_of_scale_string_is_exactly_the_integer``。
# 反例：1/3 若寫成 "0.333333"，1.0 / 0.333333 = 3.000003，閘門不成立，程式會照常
# 執行、輸出照常正確、不報錯也不寫 log，只是悄悄變慢。
_SCALE_STR = {
    4: "0.25",
    5: "0.2",
    8: "0.125",
    10: "0.1",
}

_CEILING_N = min(ALLOWED_N)


def preview_scale_for(long_side_px: int) -> tuple[str, int]:
    """依印表機幅面長邊決定預覽縮放比。

    Args:
        long_side_px: 幅面長邊像素數，即 ``max(display_pixels_x, display_pixels_y)``。
            **必須取 max，不可直接用 display_pixels_x** —— 引擎在
            ``display_orientation = portrait`` 時會 ``std::swap(pw, ph)``
            （SL1.cpp:390-393），所以 raster 寬度並不恆等於 display_pixels_x。
            ``max`` 對該交換不變，恆等於 raster 長邊，而長邊正是決定影像在
            ``<img>`` 容器中能被放到多大的那一邊。

    Returns:
        ``(scale_str, n)`` —— 交給 ``--export-preview-pngs`` 的字串，與其分母。
        ``scale_str`` 恆為 ``_SCALE_STR`` 的成員，``n`` 恆屬於 ``ALLOWED_N``
        且不小於 4。

    無效或過小的輸入（0、負值、小到達不到目標寬度的幅面）一律回傳天花板值，
    即今日的 ``0.25`` —— 在無從得知真實幅面時，維持現狀是唯一誠實的選擇。
    """
    candidates = [n for n in ALLOWED_N if long_side_px / n >= TARGET_WIDTH_PX]
    n = max(candidates) if candidates else _CEILING_N
    return _SCALE_STR[n], n

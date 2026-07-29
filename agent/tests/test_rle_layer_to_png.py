"""Tests for prz_decoder.rle_layer_to_png() / sl1_display_resolution()
(spec: sl1-layer-access「單層取用支援 RLE 即時解碼，失敗回 None」, Task 3.1).

The single-layer decode helper is extracted from api_v2._rle_sl1_to_png_zip so
that both the layers.zip path (raise on None) and get_layer_png_from_sl1
(return None → 404) share one decode path.

No mocks: builds real RLE-mode .sl1 zip archives with valid RLE bytes produced
by the real encoder helper.
"""

import io
import zipfile

import numpy as np
from PIL import Image

from agent.prz_encoder import _rle_encode_layer
from agent.prz_decoder import rle_layer_to_png, sl1_display_resolution


_W, _H = 8, 4


def _rle_bytes(gray: np.ndarray) -> bytes:
    return _rle_encode_layer(gray)


def _make_gray() -> np.ndarray:
    # 一張明確的灰階圖案（非全黑），確保解碼後可辨識、可被 PIL 開啟。
    gray = np.zeros((_H, _W), dtype=np.uint8)
    gray[1, 2:5] = 255
    gray[2, :] = 128
    return gray


def _write_sl1(path, *, include_ini=True, ini_body=None, layer_gray=None):
    gray = _make_gray() if layer_gray is None else layer_gray
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("config.ini", "printTime = 100\n")
        if include_ini:
            body = ini_body if ini_body is not None else (
                f"display_pixels_x = {_W}\ndisplay_pixels_y = {_H}\n"
            )
            zf.writestr("prusaslicer.ini", body)
        zf.writestr("model00000.rle", _rle_bytes(gray))
    return path


# ---------------------------------------------------------------------------
# 正常：單層 RLE → 有效 PNG bytes
# ---------------------------------------------------------------------------

def test_valid_rle_layer_decodes_to_png(tmp_path):
    gray = _make_gray()
    sl1 = _write_sl1(tmp_path / "model.sl1", layer_gray=gray)

    with zipfile.ZipFile(sl1) as zf:
        png = rle_layer_to_png(zf, "model00000.rle")

    assert png is not None
    assert isinstance(png, (bytes, bytearray))
    # 可被 PIL 開啟，且解回原始灰階圖案與尺寸。
    img = Image.open(io.BytesIO(png))
    assert img.format == "PNG"
    assert img.size == (_W, _H)          # PIL size == (width, height)
    assert np.array_equal(np.asarray(img.convert("L")), gray)


def test_display_resolution_parsed(tmp_path):
    sl1 = _write_sl1(tmp_path / "model.sl1")
    with zipfile.ZipFile(sl1) as zf:
        assert sl1_display_resolution(zf) == (_W, _H)


# ---------------------------------------------------------------------------
# 失敗：缺 prusaslicer.ini / display_pixels 解析失敗 → None
# ---------------------------------------------------------------------------

def test_missing_prusaslicer_ini_returns_none(tmp_path):
    sl1 = _write_sl1(tmp_path / "model.sl1", include_ini=False)
    with zipfile.ZipFile(sl1) as zf:
        assert sl1_display_resolution(zf) is None
        assert rle_layer_to_png(zf, "model00000.rle") is None


def test_invalid_display_pixels_returns_none(tmp_path):
    # display_pixels_x 非數值 → 解析失敗 → None
    bad = "display_pixels_x = abc\ndisplay_pixels_y = 4\n"
    sl1 = _write_sl1(tmp_path / "model.sl1", ini_body=bad)
    with zipfile.ZipFile(sl1) as zf:
        assert sl1_display_resolution(zf) is None
        assert rle_layer_to_png(zf, "model00000.rle") is None


def test_missing_display_pixels_keys_returns_none(tmp_path):
    # prusaslicer.ini 存在但無 display_pixels_* → None
    sl1 = _write_sl1(tmp_path / "model.sl1", ini_body="layer_height = 0.05\n")
    with zipfile.ZipFile(sl1) as zf:
        assert sl1_display_resolution(zf) is None
        assert rle_layer_to_png(zf, "model00000.rle") is None
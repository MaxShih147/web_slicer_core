"""Tests for the Python preview fallback line — Phase 3
(slice-preview-quantized-scale).

The fallback only runs when the engine's ``model_preview.zip`` is absent, which
is a rare-but-supported state (preview export failure MUST NOT fail a slice).
Being rare is exactly why its defects survived: nothing in the happy path
exercises it.

Three defects are pinned here, all pre-existing:

  RLE      the main slicing path runs with ``SLA_LAYER_RLE=1``, so the .sl1
           holds ``model#####.rle`` and no PNG at all. Filtering on ``.png``
           yields an empty list -> an empty ZIP.
  Cache    that empty ZIP was then written to the cache path, and the
           ``if output_path.exists(): return`` guard served it forever after.
  Filter   PIL BILINEAR is antialiased when downscaling (Pillow scales the
           filter support by the reduction factor), so thin supports do not
           vanish -- but it is a *triangle* weighting, not the uniform box mean
           that slice-preview-export requires of every preview line.

Plus the Phase 3 convergence itself: the scale must come from the shared
quantiser, not from a per-function default.

No mocks: real .sl1 archives with real RLE bytes from the production encoder.
"""

import io
import zipfile

import numpy as np
import pytest
from PIL import Image

from agent import preview_service
from agent.preview_scale import preview_scale_for
from agent.preview_service import generate_preview_zip
from agent.prz_encoder import _rle_encode_layer


# ---------------------------------------------------------------------------
# .sl1 fixtures
# ---------------------------------------------------------------------------

def _png_bytes(gray: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(gray, "L").save(buf, format="PNG")
    return buf.getvalue()


def _write_sl1(path, layers, *, mode: str, ini: bool = True):
    """Build a .sl1 holding ``layers`` (list of 2-D uint8 arrays) as RLE or PNG."""
    h, w = layers[0].shape
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("config.ini", "printTime = 100\n")
        if ini:
            zf.writestr(
                "prusaslicer.ini",
                f"display_pixels_x = {w}\ndisplay_pixels_y = {h}\n",
            )
        for i, gray in enumerate(layers):
            if mode == "rle":
                zf.writestr(f"model{i:05d}.rle", _rle_encode_layer(gray))
            else:
                zf.writestr(f"model{i:05d}.png", _png_bytes(gray))
    return path


def _solid(w: int, h: int, value: int = 200) -> np.ndarray:
    gray = np.zeros((h, w), dtype=np.uint8)
    gray[:, :] = value
    return gray


def _entries(zip_path) -> list[str]:
    with zipfile.ZipFile(zip_path) as zf:
        return zf.namelist()


def _first_image(zip_path) -> Image.Image:
    with zipfile.ZipFile(zip_path) as zf:
        return Image.open(io.BytesIO(zf.read(zf.namelist()[0]))).convert("L")


# ---------------------------------------------------------------------------
# RLE 模式：現行實作在此產出空 ZIP
# ---------------------------------------------------------------------------

def test_rle_mode_produces_one_preview_per_layer(tmp_path):
    layers = [_solid(64, 32) for _ in range(5)]
    sl1 = _write_sl1(tmp_path / "model.sl1", layers, mode="rle")
    out = tmp_path / "preview.zip"

    generate_preview_zip(sl1, out)

    assert len(_entries(out)) == 5, "RLE layers must not be silently skipped"


def test_png_mode_still_produces_one_preview_per_layer(tmp_path):
    """Regression guard: switching the enumeration to sl1_layer_names() must
    not break the PNG-mode archives that already worked."""
    layers = [_solid(64, 32) for _ in range(3)]
    sl1 = _write_sl1(tmp_path / "model.sl1", layers, mode="png")
    out = tmp_path / "preview.zip"

    generate_preview_zip(sl1, out)

    assert len(_entries(out)) == 3


def test_fallback_entry_naming_and_encoding_are_pinned(tmp_path):
    """Pins both columns of the Known Difference table in slice-preview-export.

    The engine line writes ``model_preview00000.png`` (PNG); this line writes
    ``0.webp`` (WebP). The two are deliberately not unified, and consumers are
    required to read the actual entry names and extensions rather than assume
    either shape — so the spec documents both.

    The engine side of that table is checked by a real slice; without this the
    fallback side rests on nothing, and a rename would leave the spec quietly
    wrong. That is exactly the failure shape this change added source-level
    contracts to prevent, so the guarantee this change itself introduced should
    not be the one left unpinned.
    """
    layers = [_solid(64, 32) for _ in range(3)]
    sl1 = _write_sl1(tmp_path / "model.sl1", layers, mode="rle")
    out = tmp_path / "preview.zip"

    generate_preview_zip(sl1, out)

    assert _entries(out) == ["0.webp", "1.webp", "2.webp"]
    with zipfile.ZipFile(out) as zf:
        assert Image.open(io.BytesIO(zf.read("0.webp"))).format == "WEBP"


def test_thumbnails_and_config_are_not_counted_as_layers(tmp_path):
    layers = [_solid(64, 32) for _ in range(2)]
    sl1 = _write_sl1(tmp_path / "model.sl1", layers, mode="png")
    with zipfile.ZipFile(sl1, "a") as zf:
        zf.writestr("thumbnail/thumbnail400x400.png", _png_bytes(_solid(8, 8)))
    out = tmp_path / "preview.zip"

    generate_preview_zip(sl1, out)

    assert len(_entries(out)) == 2


# ---------------------------------------------------------------------------
# 空封存不得被寫入或快取
# ---------------------------------------------------------------------------

def test_source_without_layers_raises_and_leaves_nothing_behind(tmp_path):
    sl1 = tmp_path / "model.sl1"
    with zipfile.ZipFile(sl1, "w") as zf:
        zf.writestr("config.ini", "printTime = 100\n")
    out = tmp_path / "preview.zip"

    with pytest.raises(Exception):
        generate_preview_zip(sl1, out)

    assert not out.exists(), "an empty preview must never reach the cache path"
    assert not out.with_suffix(".zip.tmp").exists(), "temp file must be cleaned up"


def test_preexisting_empty_zip_is_regenerated_not_served(tmp_path):
    """A job sliced before this fix may already hold an empty preview.zip.
    The cache guard must treat it as a miss, otherwise the defect outlives the
    fix for every such job."""
    layers = [_solid(64, 32) for _ in range(4)]
    sl1 = _write_sl1(tmp_path / "model.sl1", layers, mode="rle")
    out = tmp_path / "preview.zip"
    with zipfile.ZipFile(out, "w"):  # the stale empty archive
        pass
    assert _entries(out) == []

    generate_preview_zip(sl1, out)

    assert len(_entries(out)) == 4


def test_non_empty_cache_is_reused(tmp_path):
    """The cache still works — only *empty* archives are treated as misses."""
    layers = [_solid(64, 32) for _ in range(2)]
    sl1 = _write_sl1(tmp_path / "model.sl1", layers, mode="rle")
    out = tmp_path / "preview.zip"

    generate_preview_zip(sl1, out)
    first = out.read_bytes()
    generate_preview_zip(sl1, out)

    assert out.read_bytes() == first


# ---------------------------------------------------------------------------
# 濾波語意：均勻 box mean，而非三角權重
#
# 刻意直接測降取樣這一步，不經過 WebP —— quality 80 是有損編碼，會讓「等於手算
# 區塊平均」這種精確斷言變得不可靠。要驗的是濾波器選擇，不是編碼器。
# ---------------------------------------------------------------------------

def test_resample_filter_is_box():
    assert preview_service._RESAMPLE_FILTER is Image.BOX


def test_configured_filter_computes_exact_block_means():
    """Teeth for the constant above: BILINEAR/BICUBIC weight the block centre
    more heavily and would not reproduce these hand-computed means."""
    # 8 x 8, downscaled by 1/4 -> each destination pixel covers a 4 x 4 block.
    gray = np.zeros((8, 8), dtype=np.uint8)
    gray[0, 0] = 240            # 單一角落亮點：box mean = 240/16 = 15
    gray[4:8, 4:8] = 80         # 整塊均勻：box mean = 80

    out = np.asarray(
        Image.fromarray(gray, "L").resize((2, 2), preview_service._RESAMPLE_FILTER)
    )

    assert out[0, 0] == 15
    assert out[1, 1] == 80
    assert out[0, 1] == 0
    assert out[1, 0] == 0


def test_bilinear_would_not_reproduce_the_block_mean():
    """Prove the assertion above discriminates: the filter we replaced gives a
    different answer for the corner-pixel case."""
    gray = np.zeros((8, 8), dtype=np.uint8)
    gray[0, 0] = 240

    box = np.asarray(Image.fromarray(gray, "L").resize((2, 2), Image.BOX))
    bilinear = np.asarray(Image.fromarray(gray, "L").resize((2, 2), Image.BILINEAR))

    assert box[0, 0] != bilinear[0, 0]


# ---------------------------------------------------------------------------
# 縮放比一致性：與 preview_scale_for 同源
# ---------------------------------------------------------------------------

# (標籤, 來源 w, 來源 h, 期望預覽 w, 期望預覽 h)
_SCALE_CASES = [
    ("16K 長邊",      15120, 8, 1512, 1),
    ("cs_plus 長邊",   7536, 8, 1507, 1),
    ("小幅面長邊",      3840, 8,  960, 2),
]


@pytest.mark.parametrize(
    "label,w,h,exp_w,exp_h", _SCALE_CASES, ids=[c[0] for c in _SCALE_CASES]
)
def test_preview_size_follows_the_quantiser(label, w, h, exp_w, exp_h, tmp_path):
    sl1 = _write_sl1(tmp_path / "model.sl1", [_solid(w, h)], mode="png")
    out = tmp_path / "preview.zip"

    generate_preview_zip(sl1, out)

    assert _first_image(out).size == (exp_w, exp_h)


def test_preview_size_uses_the_long_side_in_portrait(tmp_path):
    """A tall source must be quantised on 15120, not on its width."""
    sl1 = _write_sl1(tmp_path / "model.sl1", [_solid(8, 15120)], mode="png")
    out = tmp_path / "preview.zip"

    generate_preview_zip(sl1, out)

    assert _first_image(out).size == (1, 1512)


def test_scale_is_not_a_caller_supplied_default():
    """The 0.25 default parameter was itself a source of divergence between the
    two preview lines — the scale must come from the shared quantiser only."""
    import inspect

    params = inspect.signature(generate_preview_zip).parameters
    assert "scale" not in params


def test_matches_preview_scale_for_directly(tmp_path):
    sl1 = _write_sl1(tmp_path / "model.sl1", [_solid(7536, 8)], mode="png")
    out = tmp_path / "preview.zip"

    generate_preview_zip(sl1, out)

    scale_str, _ = preview_scale_for(7536)
    assert _first_image(out).size[0] == int(7536 * float(scale_str))

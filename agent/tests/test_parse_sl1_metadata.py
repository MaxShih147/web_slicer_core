"""Tests for jobs.parse_sl1_metadata() layer counting across RLE / PNG output
(spec: sl1-layer-access「層數統計以實際層檔為準」; regression for print-time-sync).

The pre-fix bug: parse_sl1_metadata counted only `.png`, so RLE-mode .sl1
archives (model#####.rle) reported layer_count == 0, silently disabling the
print-time sync guard.

No mocks: builds real .sl1 zip archives under tmp_path.
"""

import zipfile
from pathlib import Path

from agent.jobs import parse_sl1_metadata


_CONFIG_INI = (
    "action = print\n"
    "layerHeight = 0.05\n"
    "printTime = 3347.299999\n"
    "usedMaterial = 1.000000\n"
)


def _write_sl1(path: Path, layer_names: list[str], *, with_thumbnail: bool = False) -> Path:
    """Build a minimal .sl1 zip with config.ini + given layer entries."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("config.ini", _CONFIG_INI)
        zf.writestr("prusaslicer.ini", "display_pixels_x = 100\ndisplay_pixels_y = 100\n")
        for name in layer_names:
            zf.writestr(name, b"\x00")  # payload irrelevant for metadata parsing
        if with_thumbnail:
            zf.writestr("thumbnail/thumbnail400x400.png", b"\x89PNG")
    return path


def test_rle_layer_count_is_n_not_zero(tmp_path):
    names = [f"model{i:05d}.rle" for i in range(200)]
    sl1 = _write_sl1(tmp_path / "model.sl1", names)

    layer_count, print_time, resin_ml = parse_sl1_metadata(sl1)

    assert layer_count == 200          # ← 修復前會是 0
    assert layer_count != 0


def test_png_layer_count_still_works(tmp_path):
    names = [f"model{i:05d}.png" for i in range(12)]
    sl1 = _write_sl1(tmp_path / "model.sl1", names)

    layer_count, _, _ = parse_sl1_metadata(sl1)

    assert layer_count == 12


def test_thumbnail_does_not_inflate_layer_count(tmp_path):
    names = [f"model{i:05d}.png" for i in range(5)]
    sl1 = _write_sl1(tmp_path / "model.sl1", names, with_thumbnail=True)

    layer_count, _, _ = parse_sl1_metadata(sl1)

    assert layer_count == 5            # 縮圖 thumbnail/*.png 不得計入


def test_metadata_parsing_unaffected(tmp_path):
    names = [f"model{i:05d}.rle" for i in range(3)]
    sl1 = _write_sl1(tmp_path / "model.sl1", names)

    _, print_time, resin_ml = parse_sl1_metadata(sl1)

    assert print_time == 3347.299999   # printTime 仍作為 fork fallback 值正確解析
    assert resin_ml == 1.0
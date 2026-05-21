"""
Tests for _resolve_retract_pair() helper and its integration into PRZ encoding.

Covers:
  - 4-case unit tests for _resolve_retract_pair() (3.3 ~ 3.8)
  - _write_header() integration: Case 4 → retract=0, drop2=lift+lift2 (4.4)
  - _write_layer_definition() integration: per-layer retract/drop2 matches header (5.3)
"""

import io
import struct
import zipfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from agent.prz_encoder import _resolve_retract_pair, encode_prz
from agent.prz_decoder import parse_prz
from agent.models import PrzPrintTimingConfig


# ---------------------------------------------------------------------------
# Helpers shared with test_prz_timing.py (duplicated to keep tests self-contained)
# ---------------------------------------------------------------------------

def _make_sl1(num_layers: int, width: int = 8, height: int = 8) -> Path:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for i in range(num_layers):
            img = Image.fromarray(np.zeros((height, width), dtype=np.uint8), mode="L")
            png_buf = io.BytesIO()
            img.save(png_buf, format="PNG")
            zf.writestr(f"{i:08d}.png", png_buf.getvalue())
    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=".sl1")
    os.close(fd)
    with open(path, "wb") as f:
        f.write(buf.getvalue())
    return Path(path)


def _base_config(**print_overrides) -> dict:
    """Minimal DS-Online config. Pass Print-section overrides as kwargs."""
    cfg = {
        "Machine": {
            "Machine Name": "TestPrinter",
            "machine_type": "msla",
            "image_size": [8, 8],
            "bed_size": [0, 0, 120.0, 68.0],
            "machine_z": 175.0,
            "Mirror": 0,
        },
        "Print": {
            "Layer Height": 0.05,
            "Bottom Layer Count": 2,
            "Exposure Time": 2.5,
            "Bottom Exposure Time": 35.0,
            "Transition Layer Count": 0,
            "Lifting Distance": 7.0,
            "Lifting Speed": 50.0,
            "Bottom Lifting Distance": 8.0,
            "Bottom Lifting Speed": 50.0,
            "Normal Retract Speed": 100.0,
            "Bottom Retract Speed": 100.0,
        },
        "Advanced": {
            "Anti-aliasing Level": 0,
            "Grey Level": 0,
            "Image Blur Pixel": 0,
            "Light PWM": 255,
            "Bottom Light PWM": 255,
        },
        "Other": {},
    }
    cfg["Print"].update(print_overrides)
    return cfg


# ---------------------------------------------------------------------------
# 3.3 ~ 3.8  _resolve_retract_pair() unit tests
# ---------------------------------------------------------------------------

class TestResolveRetractPair:
    """直接測試 _resolve_retract_pair() 的 4-case 邏輯。"""

    LIFT = 7.0
    LIFT2 = 3.0

    def _call(self, dist=None, drop2=None):
        # _get_float 使用巢狀 dotpath 查找，config 必須是巢狀 dict
        config = {"Print": {}}
        if dist is not None:
            config["Print"]["Retract Distance"] = dist
        if drop2 is not None:
            config["Print"]["Retract Second Distance"] = drop2
        return _resolve_retract_pair(
            config,
            "Print.Retract Distance",
            "Print.Retract Second Distance",
            self.LIFT, self.LIFT2,
        )

    def test_case1_only_drop2(self):
        """3.3 Case 1：只傳 drop2=3 → retract = max(0, lift+lift2-3), drop2 = 3。"""
        retract, drop2 = self._call(drop2=3.0)
        assert retract == pytest.approx(max(0.0, self.LIFT + self.LIFT2 - 3.0))
        assert drop2 == pytest.approx(3.0)

    def test_case2_only_dist(self):
        """3.4 Case 2：只傳 dist=2 → retract=2, drop2 = max(0, lift+lift2-2)。"""
        retract, drop2 = self._call(dist=2.0)
        assert retract == pytest.approx(2.0)
        assert drop2 == pytest.approx(max(0.0, self.LIFT + self.LIFT2 - 2.0))

    def test_case3_both_dist_wins(self):
        """3.5 Case 3：dist=2, drop2=99 → 與 Case 2 行為相同（drop2 被重算）。"""
        retract, drop2 = self._call(dist=2.0, drop2=99.0)
        assert retract == pytest.approx(2.0)
        assert drop2 == pytest.approx(max(0.0, self.LIFT + self.LIFT2 - 2.0))

    def test_case4_neither(self):
        """3.6 Case 4：兩者皆未傳 → retract=0.0, drop2=lift+lift2。"""
        retract, drop2 = self._call()
        assert retract == pytest.approx(0.0)
        assert drop2 == pytest.approx(self.LIFT + self.LIFT2)

    def test_case1_underflow_clamp(self):
        """3.7 Case 1 underflow：drop2 > lift+lift2 → retract 被 clamp 到 0。"""
        big_drop2 = self.LIFT + self.LIFT2 + 1.0
        retract, drop2 = self._call(drop2=big_drop2)
        assert retract == pytest.approx(0.0)
        assert drop2 == pytest.approx(big_drop2)

    def test_case4_zero_lifts(self):
        """3.8 Case 4 邊界：lift=0, lift2=0 → (0.0, 0.0)。"""
        result = _resolve_retract_pair({"Print": {}}, "Print.a", "Print.b", 0.0, 0.0)
        assert result == (0.0, 0.0)


# ---------------------------------------------------------------------------
# 4.4  _write_header() integration — Case 4 behavior
# ---------------------------------------------------------------------------

def test_header_case4_no_retract_keys():
    """4.4 config 未傳 4 個 retract 欄位 → PRZ header retract=0, drop2=lift+lift2。"""
    sl1 = _make_sl1(num_layers=3)
    config = _base_config()  # 無任何 retract dist/drop2 key

    timing = PrzPrintTimingConfig()
    data = encode_prz(config=config, sl1_path=sl1, timing=timing)
    prz = parse_prz(data)

    # bottom: lift=8.0, lift2=0.0 → retract=0, drop2=8.0
    assert prz.header.bottom_retract_distance == pytest.approx(0.0)
    assert prz.header.bottom_drop2_distance == pytest.approx(8.0)

    # normal: lift=7.0, lift2=0.0 → retract=0, drop2=7.0
    assert prz.header.normal_retract_distance == pytest.approx(0.0)
    assert prz.header.normal_drop2_distance == pytest.approx(7.0)

    sl1.unlink(missing_ok=True)


def test_header_case2_normal_dist_only():
    """11.3 config 傳 Retract Distance=2.0 → normal retract=2.0, drop2=max(0, lift+lift2-2)。"""
    sl1 = _make_sl1(num_layers=3)
    lift = 7.0
    config = _base_config(**{"Retract Distance": 2.0})

    timing = PrzPrintTimingConfig()
    data = encode_prz(config=config, sl1_path=sl1, timing=timing)
    prz = parse_prz(data)

    assert prz.header.normal_retract_distance == pytest.approx(2.0)
    assert prz.header.normal_drop2_distance == pytest.approx(max(0.0, lift - 2.0))

    sl1.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 5.3  _write_layer_definition() integration — per-layer matches header
# ---------------------------------------------------------------------------

def test_layer_retract_matches_header_case4():
    """5.3 per-layer retract/drop2 應與 header 一致（Case 4 場景）。"""
    sl1 = _make_sl1(num_layers=3)
    config = _base_config()  # bottom_layers=2，第 0/1 層為 bottom，第 2 層為 normal

    timing = PrzPrintTimingConfig()
    data = encode_prz(config=config, sl1_path=sl1, timing=timing)
    prz = parse_prz(data)

    hdr = prz.header

    # Layer 0 (bottom)
    l0 = prz.layers[0]
    assert l0.retract_distance == pytest.approx(hdr.bottom_retract_distance)
    assert l0.drop2_distance == pytest.approx(hdr.bottom_drop2_distance)

    # Layer 2 (normal)
    l2 = prz.layers[2]
    assert l2.retract_distance == pytest.approx(hdr.normal_retract_distance)
    assert l2.drop2_distance == pytest.approx(hdr.normal_drop2_distance)

    sl1.unlink(missing_ok=True)

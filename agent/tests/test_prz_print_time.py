"""
Tests for _to_mm_per_sec() and _compute_print_time() helpers.

Covers:
  - 6.9  Unit conversion regression guard: 60 mm/min → 1.0 sec for 1mm lift
  - 6.10 Unit conversion regression guard: 120 mm/min → 0.5 sec for 1mm lift
  - 6.11 1 normal layer full-params hand-calc comparison
  - 6.12 1 bottom layer hand-calc comparison
  - 6.13 Transition layer exposure linear interpolation
  - 6.14 Zero distances/speeds → no NaN / ZeroDivisionError
  - 6.15 PRZ binary speed fields remain raw mm/min (unit conversion isolated to _compute_print_time)
"""

import io
import struct
import zipfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from agent.prz_encoder import _to_mm_per_sec, _compute_print_time, encode_prz
from agent.prz_decoder import parse_prz
from agent.models import PrzPrintTimingConfig


# ---------------------------------------------------------------------------
# Shared helpers
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


def _base_machine() -> dict:
    return {
        "Machine Name": "TestPrinter",
        "machine_type": "msla",
        "image_size": [8, 8],
        "bed_size": [0, 0, 120.0, 68.0],
        "machine_z": 175.0,
        "Mirror": 0,
    }


def _base_advanced() -> dict:
    return {
        "Anti-aliasing Level": 0,
        "Grey Level": 0,
        "Image Blur Pixel": 0,
        "Light PWM": 255,
        "Bottom Light PWM": 255,
    }


def _zero_timing() -> PrzPrintTimingConfig:
    """All-zero timing to isolate motion-only calculations."""
    return PrzPrintTimingConfig(
        exposure_delay_mode=1,
        light_off_delay=0.0,
        rest_before_lift=0.0,
        rest_after_lift=0.0,
        rest_after_retract=0.0,
    )


# ---------------------------------------------------------------------------
# 6.9 & 6.10  Unit conversion regression guards (_to_mm_per_sec)
# ---------------------------------------------------------------------------

class TestToMmPerSec:
    def test_60_mm_per_min(self):
        assert _to_mm_per_sec(60.0) == pytest.approx(1.0)

    def test_120_mm_per_min(self):
        assert _to_mm_per_sec(120.0) == pytest.approx(2.0)

    def test_zero_returns_zero(self):
        assert _to_mm_per_sec(0.0) == 0.0

    def test_falsy_returns_zero(self):
        assert _to_mm_per_sec(0) == 0.0


class TestComputePrintTimeUnitConversion:
    """6.9 & 6.10 — 如果漏掉 ÷60，結果會差 60×，測試必須 fail。"""

    def _single_lift_config(self, lift_speed_mm_per_min: float) -> dict:
        """1 normal layer, only lift distance=1mm set, everything else minimal."""
        return {
            "Machine": _base_machine(),
            "Print": {
                "Layer Height": 0.05,
                "Bottom Layer Count": 0,      # no bottom layers
                "Transition Layer Count": 0,
                "Exposure Time": 0.0,
                "Bottom Exposure Time": 0.0,
                "Lifting Distance": 1.0,
                "Lifting Speed": lift_speed_mm_per_min,
                # No retract keys → Case 4: retract=0, drop2=1.0; drop2_v=0 → motion=0
            },
            "Advanced": _base_advanced(),
            "Other": {},
        }

    def test_6_9_60_mm_per_min_lift_equals_1_sec(self):
        """6.9: 60 mm/min + 1mm → motion_time = 1.0 sec (漏 ÷60 → 0.0167 sec)。"""
        config = self._single_lift_config(60.0)
        timing = _zero_timing()
        t = _compute_print_time(config, total_layers=1, timing=timing)
        assert t == pytest.approx(1.0), (
            f"Expected 1.0 sec but got {t:.6f} — likely missing ÷60 unit conversion"
        )

    def test_6_10_120_mm_per_min_lift_equals_0_5_sec(self):
        """6.10: 120 mm/min + 1mm → motion_time = 0.5 sec (漏 ÷60 → 0.0083 sec)。"""
        config = self._single_lift_config(120.0)
        timing = _zero_timing()
        t = _compute_print_time(config, total_layers=1, timing=timing)
        assert t == pytest.approx(0.5), (
            f"Expected 0.5 sec but got {t:.6f} — likely missing ÷60 unit conversion"
        )


# ---------------------------------------------------------------------------
# 6.11  1 normal layer full-params hand-calc
# ---------------------------------------------------------------------------

def test_6_11_single_normal_layer_full_params():
    """6.11: 1 normal layer with explicit motion params → 手算 vs 公式比對。"""
    # motion params (all speeds in mm/min):
    # lift1: 5mm @ 60 mm/min → 5/(60/60) = 5.0 sec
    # lift2: 2mm @ 120 mm/min → 2/(120/60) = 1.0 sec
    # Case 2 (only Retract Distance set): retract=4mm, drop2=max(0,5+2-4)=3mm
    # retract: 4mm @ 120 mm/min → 4/(120/60) = 2.0 sec
    # drop2: 3mm @ 60 mm/min → 3/(60/60) = 3.0 sec
    # exposure = 3.0
    # all timing delays = 0
    # Expected total = 3.0 + 5.0 + 1.0 + 2.0 + 3.0 = 14.0 sec
    config = {
        "Machine": _base_machine(),
        "Print": {
            "Layer Height": 0.05,
            "Bottom Layer Count": 0,
            "Transition Layer Count": 0,
            "Exposure Time": 3.0,
            "Bottom Exposure Time": 0.0,
            "Lifting Distance": 5.0,
            "Lifting Speed": 60.0,
            "Lifting Second Distance": 2.0,
            "Lifting Second Speed": 120.0,
            "Retract Distance": 4.0,            # Case 2: retract=4, drop2=3
            "Normal Retract Speed": 120.0,
            "Normal Retract Second Speed": 60.0,
        },
        "Advanced": _base_advanced(),
        "Other": {},
    }
    timing = _zero_timing()
    t = _compute_print_time(config, total_layers=1, timing=timing)
    assert t == pytest.approx(14.0)


# ---------------------------------------------------------------------------
# 6.12  1 bottom layer hand-calc
# ---------------------------------------------------------------------------

def test_6_12_single_bottom_layer_hand_calc():
    """6.12: 1 bottom layer → 手算 vs 公式比對（bottom params 路徑）。"""
    # bottom lift: 8mm @ 60 mm/min → 8.0 sec
    # no lift2, no retract keys → Case 4: retract=0, drop2=8.0; drop2_v=0 → 0 sec
    # bottom exposure = 35.0
    # all delays = 0
    # Expected = 35.0 + 8.0 = 43.0 sec
    config = {
        "Machine": _base_machine(),
        "Print": {
            "Layer Height": 0.05,
            "Bottom Layer Count": 1,
            "Transition Layer Count": 0,
            "Exposure Time": 0.0,
            "Bottom Exposure Time": 35.0,
            "Bottom Lifting Distance": 8.0,
            "Bottom Lifting Speed": 60.0,
            "Bottom Retract Speed": 100.0,
        },
        "Advanced": _base_advanced(),
        "Other": {},
    }
    timing = _zero_timing()
    t = _compute_print_time(config, total_layers=1, timing=timing)
    assert t == pytest.approx(43.0)


# ---------------------------------------------------------------------------
# 6.13  Transition layer exposure interpolation
# ---------------------------------------------------------------------------

def test_6_13_transition_exposure_interpolation():
    """6.13: transition layer 的 exposure 線性內插正確。"""
    # 3 layers: layer 0=bottom, layers 1-2=transition (transition_count=2)
    # bottom_exp=30, normal_exp=5
    # layer 0 (bottom):   exposure = 30.0
    # layer 1 (trans 0):  exposure = 30 + (5-30)/(1+2)*1 = 30 - 25/3 = 65/3
    # layer 2 (trans 1):  exposure = 30 + (5-30)/(1+2)*2 = 30 - 50/3 = 40/3
    # total = 30 + 65/3 + 40/3 = 90/3 + 105/3 = 195/3 = 65.0
    config = {
        "Machine": _base_machine(),
        "Print": {
            "Layer Height": 0.05,
            "Bottom Layer Count": 1,
            "Transition Layer Count": 2,
            "Exposure Time": 5.0,
            "Bottom Exposure Time": 30.0,
            # zero all motion to isolate exposure
            "Lifting Distance": 0.0,
            "Bottom Lifting Distance": 0.0,
        },
        "Advanced": _base_advanced(),
        "Other": {},
    }
    timing = _zero_timing()
    t = _compute_print_time(config, total_layers=3, timing=timing)
    assert t == pytest.approx(65.0, rel=1e-5)


# ---------------------------------------------------------------------------
# 6.14  Zero distances / speeds → no NaN / ZeroDivisionError
# ---------------------------------------------------------------------------

def test_6_14_zero_distances_and_speeds_no_error():
    """6.14: lift2=0, drop2=0, speed=0 → 對應段時間為 0，不引發 NaN 或除零。"""
    config = {
        "Machine": _base_machine(),
        "Print": {
            "Layer Height": 0.05,
            "Bottom Layer Count": 0,
            "Transition Layer Count": 0,
            "Exposure Time": 1.0,
            "Bottom Exposure Time": 0.0,
            # All speeds explicitly 0
            "Lifting Distance": 0.0,
            "Lifting Speed": 0.0,
            "Lifting Second Distance": 0.0,
            "Lifting Second Speed": 0.0,
            "Normal Retract Speed": 0.0,
            "Normal Retract Second Speed": 0.0,
        },
        "Advanced": _base_advanced(),
        "Other": {},
    }
    timing = _zero_timing()
    t = _compute_print_time(config, total_layers=2, timing=timing)
    assert not (t != t), "Result is NaN"    # NaN check
    assert t == pytest.approx(2.0)          # only exposure, 2 layers × 1.0


# ---------------------------------------------------------------------------
# 6.15  PRZ binary speed fields remain raw mm/min
# ---------------------------------------------------------------------------

def test_6_15_prz_speed_fields_are_raw_mm_per_min():
    """6.15: PRZ binary の speed 欄位寫入值為 raw mm/min，與 _compute_print_time 內部 ÷60 完全隔離。"""
    sl1 = _make_sl1(num_layers=2)
    config = {
        "Machine": _base_machine(),
        "Print": {
            "Layer Height": 0.05,
            "Bottom Layer Count": 1,
            "Transition Layer Count": 0,
            "Exposure Time": 2.5,
            "Bottom Exposure Time": 35.0,
            "Lifting Distance": 7.0,
            "Lifting Speed": 60.0,            # 60 mm/min raw in binary
            "Bottom Lifting Distance": 8.0,
            "Bottom Lifting Speed": 120.0,    # 120 mm/min raw in binary
            "Normal Retract Speed": 90.0,
            "Bottom Retract Speed": 80.0,
        },
        "Advanced": _base_advanced(),
        "Other": {},
    }
    timing = PrzPrintTimingConfig()
    data = encode_prz(config=config, sl1_path=sl1, timing=timing)
    prz = parse_prz(data)

    # Speeds in PRZ header must be the raw mm/min values — NOT ÷60
    assert prz.header.normal_lift_speed == pytest.approx(60.0), (
        "normal_lift_speed should be raw 60 mm/min, not 1.0 mm/s"
    )
    assert prz.header.bottom_lift_speed == pytest.approx(120.0), (
        "bottom_lift_speed should be raw 120 mm/min, not 2.0 mm/s"
    )

    sl1.unlink(missing_ok=True)

"""
Tests for PRZ print timing configuration and binary encoding.

Covers:
  - PrzPrintTimingConfig validation (unit)
  - _resolve_timing_values() logic (unit)
  - PRZ binary output with custom and default timing params (integration)
"""

import io
import struct
import zipfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from pydantic import ValidationError

from agent.models import PrzPrintTimingConfig
from agent.prz_encoder import (
    LAYER_CONTENT_OFFSET,
    _resolve_timing_values,
    encode_prz,
)
from agent.api_v2 import _extract_prz_timing_config


# ---------------------------------------------------------------------------
# Byte offsets in the PRZ header (see prz_encoder.py _write_header)
# ---------------------------------------------------------------------------

# Delay Mode (1B) and the 7 timing floats that follow it
_HDR_DELAY_MODE      = 195340
_HDR_TURN_OFF        = 195341   # light_off (bottom[0])
_HDR_BTM_BEF_LIFT    = 195345   # bottom before-lift
_HDR_BTM_AFT_LIFT    = 195349   # bottom after-lift
_HDR_BTM_AFT_RETRACT = 195353   # bottom after-retract
_HDR_NRM_BEF_LIFT    = 195357   # normal before-lift
_HDR_NRM_AFT_LIFT    = 195361   # normal after-lift
_HDR_NRM_AFT_RETRACT = 195365   # normal after-retract

# Per-layer definition block starts at LAYER_CONTENT_OFFSET (first layer = layer 0).
# Block layout: PauseFlag(2) PauseZ(4) LayerZ(4) Exposure(4) [4 timing floats] ...
_L0_LIGHT_OFF        = LAYER_CONTENT_OFFSET + 14
_L0_BEF_LIFT         = LAYER_CONTENT_OFFSET + 18
_L0_AFT_LIFT         = LAYER_CONTENT_OFFSET + 22
_L0_AFT_RETRACT      = LAYER_CONTENT_OFFSET + 26


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sl1(num_layers: int, width: int = 8, height: int = 8) -> Path:
    """Create a minimal .sl1 ZIP with *num_layers* solid-black PNG layers."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for i in range(num_layers):
            img = Image.fromarray(
                np.zeros((height, width), dtype=np.uint8), mode="L"
            )
            png_buf = io.BytesIO()
            img.save(png_buf, format="PNG")
            zf.writestr(f"{i:08d}.png", png_buf.getvalue())
    # Write to a temp file that encode_prz can open
    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=".sl1")
    os.close(fd)
    with open(path, "wb") as f:
        f.write(buf.getvalue())
    return Path(path)


def _f(data: bytes, offset: int) -> float:
    return struct.unpack_from(">f", data, offset)[0]


def _b(data: bytes, offset: int) -> int:
    return data[offset]


def _minimal_config(bottom_layers: int = 2) -> dict:
    """Bare DS-Online config dict understood by encode_prz."""
    return {
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
            "Bottom Layer Count": bottom_layers,
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


# ---------------------------------------------------------------------------
# 7.1  Valid construction — all defaults
# ---------------------------------------------------------------------------

def test_timing_config_all_defaults():
    t = PrzPrintTimingConfig()
    assert t.exposure_delay_mode == 1
    assert t.light_off_delay == 1.0
    assert t.rest_before_lift == 0.0
    assert t.rest_after_lift == 0.0
    assert t.rest_after_retract == 1.0
    # bottom fallbacks applied
    assert t.bottom_rest_before_lift == 0.0
    assert t.bottom_rest_after_lift == 0.0
    assert t.bottom_rest_after_retract == 1.0


def test_timing_config_partial_fields():
    t = PrzPrintTimingConfig(rest_before_lift=3.0, rest_after_retract=5.0)
    assert t.rest_before_lift == 3.0
    assert t.rest_after_retract == 5.0
    assert t.rest_after_lift == 0.0         # default
    assert t.bottom_rest_before_lift == 3.0  # fallback
    assert t.bottom_rest_after_retract == 5.0


# ---------------------------------------------------------------------------
# 7.2  Invalid delay mode
# ---------------------------------------------------------------------------

def test_timing_config_invalid_delay_mode():
    with pytest.raises(ValidationError) as exc_info:
        PrzPrintTimingConfig(exposure_delay_mode=2)
    errors = exc_info.value.errors()
    assert any("exposure_delay_mode" in str(e) for e in errors)


# ---------------------------------------------------------------------------
# 7.3  light_off_delay out of range
# ---------------------------------------------------------------------------

def test_timing_config_light_off_delay_too_large():
    with pytest.raises(ValidationError) as exc_info:
        PrzPrintTimingConfig(light_off_delay=150.0)
    errors = exc_info.value.errors()
    assert any("light_off_delay" in str(e) for e in errors)


# ---------------------------------------------------------------------------
# 7.4  rest param out of range
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("field", [
    "rest_before_lift",
    "rest_after_lift",
    "rest_after_retract",
])
def test_timing_config_rest_out_of_range(field):
    with pytest.raises(ValidationError):
        PrzPrintTimingConfig(**{field: 80.0})


# ---------------------------------------------------------------------------
# 7.5  Bottom fallback logic
# ---------------------------------------------------------------------------

def test_timing_config_bottom_fallback_single_field():
    t = PrzPrintTimingConfig(rest_after_retract=2.0)
    assert t.bottom_rest_after_retract == 2.0
    assert t.bottom_rest_before_lift == 0.0   # fallback from default rest_before_lift
    assert t.bottom_rest_after_lift == 0.0


def test_timing_config_bottom_explicit_overrides_fallback():
    t = PrzPrintTimingConfig(rest_after_retract=2.0, bottom_rest_after_retract=4.0)
    assert t.bottom_rest_after_retract == 4.0  # explicit takes precedence


# ---------------------------------------------------------------------------
# 7.6  _resolve_timing_values — delay_mode=0 (lightOff)
# ---------------------------------------------------------------------------

def test_resolve_timing_mode0_forces_zeros():
    t = PrzPrintTimingConfig(
        exposure_delay_mode=0,
        light_off_delay=5.0,
        rest_before_lift=2.0,
        rest_after_lift=3.0,
        rest_after_retract=4.0,
    )
    for is_bottom in (True, False):
        lo, bef, aft, ret = _resolve_timing_values(t, is_bottom=is_bottom)
        assert lo == pytest.approx(5.0), "light_off must equal light_off_delay"
        assert bef == pytest.approx(0.0)
        assert aft == pytest.approx(0.0)
        assert ret == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 7.7  _resolve_timing_values — delay_mode=1 (waitTime)
# ---------------------------------------------------------------------------

def test_resolve_timing_mode1_light_off_is_zero():
    t = PrzPrintTimingConfig(
        exposure_delay_mode=1,
        light_off_delay=5.0,
        rest_before_lift=1.0,
        rest_after_lift=2.0,
        rest_after_retract=3.0,
        bottom_rest_before_lift=10.0,
        bottom_rest_after_lift=11.0,
        bottom_rest_after_retract=12.0,
    )
    lo_n, bef_n, aft_n, ret_n = _resolve_timing_values(t, is_bottom=False)
    assert lo_n == pytest.approx(0.0), "light_off must be 0 in waitTime mode"
    assert bef_n == pytest.approx(1.0)
    assert aft_n == pytest.approx(2.0)
    assert ret_n == pytest.approx(3.0)

    lo_b, bef_b, aft_b, ret_b = _resolve_timing_values(t, is_bottom=True)
    assert lo_b == pytest.approx(0.0)
    assert bef_b == pytest.approx(10.0)
    assert aft_b == pytest.approx(11.0)
    assert ret_b == pytest.approx(12.0)


# ---------------------------------------------------------------------------
# 7.8  Integration — full encode with custom timing → verify binary offsets
# ---------------------------------------------------------------------------

def test_prz_binary_custom_timing(tmp_path):
    sl1 = _make_sl1(num_layers=3)
    config = _minimal_config(bottom_layers=2)

    timing = PrzPrintTimingConfig(
        exposure_delay_mode=1,
        rest_before_lift=1.5,
        rest_after_lift=2.5,
        rest_after_retract=3.5,
        bottom_rest_before_lift=4.5,
        bottom_rest_after_lift=5.5,
        bottom_rest_after_retract=6.5,
    )
    data = encode_prz(config=config, sl1_path=sl1, timing=timing)

    # --- Header verification ---
    assert _b(data, _HDR_DELAY_MODE) == 1, "delay_mode in header"

    # light_off_time must be 0 for mode=1
    assert _f(data, _HDR_TURN_OFF) == pytest.approx(0.0)

    # bottom timing in header
    assert _f(data, _HDR_BTM_BEF_LIFT) == pytest.approx(4.5)
    assert _f(data, _HDR_BTM_AFT_LIFT) == pytest.approx(5.5)
    assert _f(data, _HDR_BTM_AFT_RETRACT) == pytest.approx(6.5)

    # normal timing in header
    assert _f(data, _HDR_NRM_BEF_LIFT) == pytest.approx(1.5)
    assert _f(data, _HDR_NRM_AFT_LIFT) == pytest.approx(2.5)
    assert _f(data, _HDR_NRM_AFT_RETRACT) == pytest.approx(3.5)

    # --- Layer 0 (bottom) per-layer block verification ---
    # Layer 0 definition block starts at LAYER_CONTENT_OFFSET
    assert _f(data, _L0_LIGHT_OFF) == pytest.approx(0.0)
    assert _f(data, _L0_BEF_LIFT) == pytest.approx(4.5)
    assert _f(data, _L0_AFT_LIFT) == pytest.approx(5.5)
    assert _f(data, _L0_AFT_RETRACT) == pytest.approx(6.5)

    sl1.unlink(missing_ok=True)


def test_prz_binary_mode0_light_off(tmp_path):
    sl1 = _make_sl1(num_layers=2)
    config = _minimal_config(bottom_layers=1)

    timing = PrzPrintTimingConfig(
        exposure_delay_mode=0,
        light_off_delay=7.0,
    )
    data = encode_prz(config=config, sl1_path=sl1, timing=timing)

    assert _b(data, _HDR_DELAY_MODE) == 0
    assert _f(data, _HDR_TURN_OFF) == pytest.approx(7.0)

    # All rest times must be 0 when mode=0
    assert _f(data, _HDR_BTM_BEF_LIFT) == pytest.approx(0.0)
    assert _f(data, _HDR_BTM_AFT_RETRACT) == pytest.approx(0.0)
    assert _f(data, _HDR_NRM_AFT_RETRACT) == pytest.approx(0.0)

    assert _f(data, _L0_LIGHT_OFF) == pytest.approx(7.0)
    assert _f(data, _L0_BEF_LIFT) == pytest.approx(0.0)
    assert _f(data, _L0_AFT_RETRACT) == pytest.approx(0.0)

    sl1.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 7.9  Integration — encode without any timing params → verify defaults
# ---------------------------------------------------------------------------

def test_prz_binary_default_timing(tmp_path):
    sl1 = _make_sl1(num_layers=3)
    config = _minimal_config(bottom_layers=2)

    # No timing params in config → extractor uses all Pydantic defaults
    timing = _extract_prz_timing_config(config)

    assert timing.exposure_delay_mode == 1
    assert timing.light_off_delay == pytest.approx(1.0)
    assert timing.rest_after_retract == pytest.approx(1.0)
    assert timing.bottom_rest_after_retract == pytest.approx(1.0)

    data = encode_prz(config=config, sl1_path=sl1, timing=timing)

    assert _b(data, _HDR_DELAY_MODE) == 1
    assert _f(data, _HDR_TURN_OFF) == pytest.approx(0.0)   # mode=1 → light_off=0
    assert _f(data, _HDR_NRM_AFT_RETRACT) == pytest.approx(1.0)
    assert _f(data, _HDR_BTM_AFT_RETRACT) == pytest.approx(1.0)

    # Layer 0 (bottom layer)
    assert _f(data, _L0_LIGHT_OFF) == pytest.approx(0.0)
    assert _f(data, _L0_AFT_RETRACT) == pytest.approx(1.0)

    sl1.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# _extract_prz_timing_config — DS-Online nested config format
# ---------------------------------------------------------------------------

def test_extract_timing_from_nested_config():
    config = {
        "Print": {
            "Exposure Delay Mode": 0,
            "Light-off Delay": 8.0,
            "Rest After Retract": 2.0,
        }
    }
    t = _extract_prz_timing_config(config)
    assert t.exposure_delay_mode == 0
    assert t.light_off_delay == pytest.approx(8.0)
    assert t.rest_after_retract == pytest.approx(2.0)


def test_extract_timing_from_flat_config():
    config = {
        "Rest After Retract": 3.0,
        "Rest Before Lift": 1.0,
    }
    t = _extract_prz_timing_config(config)
    assert t.rest_after_retract == pytest.approx(3.0)
    assert t.rest_before_lift == pytest.approx(1.0)

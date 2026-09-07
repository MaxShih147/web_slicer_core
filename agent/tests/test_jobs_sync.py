"""
Tests for the print-time-sync pure helpers in jobs.py (TDD — written before
implementation, expected RED until `resolve_estimated_print_time` and
`_load_prz_config` exist).

Covers spec `print-time-sync`:
  - 正常同步：resolve == _compute_print_time(config, N, _extract_prz_timing_config(config))
  - Fallback 降級：prz_config 為 None / 觸發萃取·計算例外 → 回傳 fallback
  - 極端邊界：total_layers 為 0 / None、prz_config == {} → 回傳 fallback，不拋例外、不為 NaN
  - _load_prz_config：缺檔 / 壞 JSON → None（吞 OSError / ValueError）

No mocks: all assertions exercise the real pure functions against real dicts /
real files under tmp_path.
"""

import io
import json
import math
import zipfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

# Under test (NOT yet implemented — import is expected to fail until Section 3).
from agent.jobs import resolve_estimated_print_time, _load_prz_config, parse_sl1_metadata

# Real collaborators reused as the single source of truth for the expected value.
from agent.prz_encoder import _compute_print_time, encode_prz
from agent.prz_decoder import parse_prz
from agent.models import _extract_prz_timing_config


# ---------------------------------------------------------------------------
# Fixtures / config builders (no mocks)
# ---------------------------------------------------------------------------

def _valid_prz_config() -> dict:
    """A full frontend-style config (Mechado `Print.*` Title Case keys) whose
    physical print time is non-trivial and clearly distinguishable from any
    fork SL1 fallback value we pass in."""
    return {
        "Machine": {
            "Machine Name": "TestPrinter",
            "machine_type": "msla",
        },
        "Print": {
            "Layer Height": 0.05,
            "Bottom Layer Count": 2,
            "Transition Layer Count": 0,
            "Exposure Time": 3.0,
            "Bottom Exposure Time": 30.0,
            "Lifting Distance": 6.0,
            "Lifting Speed": 60.0,
            "Bottom Lifting Distance": 6.0,
            "Bottom Lifting Speed": 60.0,
            "Retract Distance": 6.0,
            "Normal Retract Speed": 120.0,
            "Bottom Retract Distance": 6.0,
            "Bottom Retract Speed": 120.0,
            "Light-off Delay": 1.0,
            "Rest After Retract": 1.0,
        },
        "Advanced": {"Light PWM": 255, "Bottom Light PWM": 255},
        "Other": {},
    }


# ---------------------------------------------------------------------------
# 2.2  正常同步 — resolve == _compute_print_time(...) via same config
# ---------------------------------------------------------------------------

class TestNormalSync:
    def test_resolve_equals_compute_print_time(self):
        config = _valid_prz_config()
        total_layers = 10

        expected = _compute_print_time(
            config, total_layers, _extract_prz_timing_config(config)
        )
        # fallback deliberately differs from the physical value (fork SL1 estimate).
        fallback = expected + 9999.0

        result = resolve_estimated_print_time(config, total_layers, fallback)

        assert result == pytest.approx(expected)

    def test_normal_sync_does_not_use_fallback(self):
        """正常情況 SHALL NOT 沿用 fork 估值。"""
        config = _valid_prz_config()
        total_layers = 10
        fallback = 1.0  # an obviously wrong / different fork value

        result = resolve_estimated_print_time(config, total_layers, fallback)

        assert result != pytest.approx(fallback)
        assert result > 0.0


# ---------------------------------------------------------------------------
# 2.3  Fallback 降級 — None config / 萃取·計算例外 → fallback
# ---------------------------------------------------------------------------

class TestFallbackDegrade:
    def test_none_config_returns_fallback(self):
        assert resolve_estimated_print_time(None, 10, 1234.0) == 1234.0

    def test_none_config_with_none_fallback_stays_none(self):
        """fork 估值亦為 None → 維持 None（不退化、不報錯）。"""
        assert resolve_estimated_print_time(None, 10, None) is None

    def test_extract_or_compute_exception_returns_fallback(self):
        """內容使 _extract_prz_timing_config / _compute_print_time 拋例外時退回 fallback。

        `Exposure Delay Mode` 必須為 0 或 1；給 99 會在 _extract_prz_timing_config
        建構 PrzPrintTimingConfig 時觸發 pydantic ValidationError（落在 D3 的單一
        try 內），SHALL 退回 fallback 而非向上拋出。
        """
        bad_config = {"Print": {"Exposure Delay Mode": 99}}
        # 先證明此 config 確實會讓萃取拋例外（不被測函式吞例外的前提）。
        with pytest.raises(Exception):
            _extract_prz_timing_config(bad_config)

        result = resolve_estimated_print_time(bad_config, 10, 4321.0)

        assert result == 4321.0


# ---------------------------------------------------------------------------
# 2.4  極端邊界 — 0 / None layers、{} config → fallback，無例外、非 NaN
# ---------------------------------------------------------------------------

class TestBoundaryInputs:
    def test_total_layers_zero_returns_fallback(self):
        result = resolve_estimated_print_time(_valid_prz_config(), 0, 555.0)
        assert result == 555.0
        assert not math.isnan(result)

    def test_total_layers_none_returns_fallback(self):
        result = resolve_estimated_print_time(_valid_prz_config(), None, 555.0)
        assert result == 555.0
        assert not math.isnan(result)

    def test_empty_dict_config_returns_fallback(self):
        result = resolve_estimated_print_time({}, 10, 777.0)
        assert result == 777.0
        assert not math.isnan(result)

    def test_boundary_does_not_raise(self):
        # 任一邊界組合皆不得拋例外。
        for cfg, n in [({}, 10), (None, 0), (_valid_prz_config(), None)]:
            resolve_estimated_print_time(cfg, n, 0.0)


# ---------------------------------------------------------------------------
# 2.5  _load_prz_config — 缺檔 / 壞 JSON → None（吞 OSError / ValueError）
# ---------------------------------------------------------------------------

class TestLoadPrzConfig:
    def test_missing_file_returns_none(self, tmp_path: Path):
        # tmp_path 下沒有 prz_config.json
        assert _load_prz_config(tmp_path) is None

    def test_corrupt_json_returns_none(self, tmp_path: Path):
        (tmp_path / "prz_config.json").write_text("{ this is not valid json ", encoding="utf-8")
        assert _load_prz_config(tmp_path) is None

    def test_valid_json_roundtrips(self, tmp_path: Path):
        config = _valid_prz_config()
        (tmp_path / "prz_config.json").write_text(json.dumps(config), encoding="utf-8")
        assert _load_prz_config(tmp_path) == config


# ---------------------------------------------------------------------------
# 2.6  端到端 — RLE .sl1 經 parse_sl1_metadata → resolve 得物理值而非 fallback
#      （回歸保證：修復前 layer_count 恆 0，同步靜默失效退回 fork 估值）
# ---------------------------------------------------------------------------

def _write_rle_sl1(path: Path, n: int, fork_print_time: float) -> Path:
    """Build a minimal RLE-mode .sl1 with n layer entries + fork printTime."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("config.ini", f"printTime = {fork_print_time}\nusedMaterial = 1.0\n")
        zf.writestr("prusaslicer.ini", "display_pixels_x = 100\ndisplay_pixels_y = 100\n")
        for i in range(n):
            zf.writestr(f"model{i:05d}.rle", b"\x00")
    return path


class TestEndToEndRleSync:
    def test_rle_sl1_syncs_to_physical_formula_not_fork(self, tmp_path: Path):
        config = _valid_prz_config()
        fork_print_time = 1544.0  # fork SL1 估值（面積相關），刻意與物理公式不同

        sl1 = _write_rle_sl1(tmp_path / "model.sl1", 200, fork_print_time)
        layer_count, parsed_fork, _ = parse_sl1_metadata(sl1)

        # 前置：層數正確（非 0）、fork fallback 值正確解析
        assert layer_count == 200
        assert parsed_fork == fork_print_time

        expected = _compute_print_time(
            config, layer_count, _extract_prz_timing_config(config)
        )
        result = resolve_estimated_print_time(config, layer_count, parsed_fork)

        # 同步後 SHALL 等於物理公式值，且 SHALL NOT 退回 fork 估值
        assert result == pytest.approx(expected)
        assert result != pytest.approx(fork_print_time)


# ---------------------------------------------------------------------------
# 2.7  精度選項 A — status.json 存 float、PRZ header 存 int()，兩者差 0 ≤ 差 < 1
#      （spec print-time-sync：「與 PRZ binary 列印時間同源一致」，差額僅來自 int 截斷）
# ---------------------------------------------------------------------------

def _write_png_sl1(path: Path, n: int) -> Path:
    """Build a real PNG-layer .sl1 (production naming) that encode_prz can encode."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("config.ini", "printTime = 1544.0\nusedMaterial = 1.0\n")
        zf.writestr("prusaslicer.ini", "display_pixels_x = 8\ndisplay_pixels_y = 4\n")
        for i in range(n):
            gray = np.zeros((4, 8), dtype=np.uint8)
            gray[1, 2:5] = 255
            buf = io.BytesIO()
            Image.fromarray(gray, "L").save(buf, format="PNG")
            zf.writestr(f"model{i:05d}.png", buf.getvalue())
    return path


class TestPrecisionOptionA:
    def test_status_float_vs_prz_header_int_within_one_second(self, tmp_path: Path):
        config = _valid_prz_config()
        n = 20
        sl1 = _write_png_sl1(tmp_path / "model.sl1", n)

        layer_count, fork, _ = parse_sl1_metadata(sl1)
        timing = _extract_prz_timing_config(config)

        # status.json 端：保存 float 原值
        status_float = resolve_estimated_print_time(config, layer_count, fork)
        assert isinstance(status_float, float)

        # PRZ header 端：由相同公式計算後 int() 截斷寫入
        prz = parse_prz(encode_prz(config=config, sl1_path=sl1, timing=timing))
        header_int = prz.header.print_time
        assert isinstance(header_int, int)

        # 選項 A：兩者同源，差額僅來自 int() 截斷 → 0 ≤ 差 < 1
        assert header_int == int(status_float)
        assert 0.0 <= status_float - header_int < 1.0

"""
Task 5.4 (add-pad-global-params): verify the 2 conversion paths in api_v2.py
correctly accept the 11 new pad_* fields with no whitelist gate.

- `_convert_v2_config_to_sla` (used by /generate-supports, /export-support-points)
- `_build_sla_config` (used by /execute)

F1 (add-support-tree-global-params) already established both functions pick
up new SLAConfig fields dynamically (`_convert_v2_config_to_sla` iterates
`SLAConfig.model_fields`, `_build_sla_config` does `SLAConfig(**merged)`) —
this test only re-verifies that conclusion still holds for the pad_* fields,
per tasks.md 5.4.
"""

import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.api_v2 import _build_sla_config, _convert_v2_config_to_sla
from agent.sla_operations import generate_config_ini

PAD_CUSTOM_VALUES = {
    "pad_wall_thickness": 3.5,
    "pad_wall_height": 2.0,
    "pad_brim_size": 2.5,
    "pad_max_merge_distance": 40.0,
    "pad_wall_slope": 60.0,
    "pad_around_object": True,
    "pad_around_object_everywhere": True,
    "pad_object_gap": 1.5,
    "pad_object_connector_stride": 8.0,
    "pad_object_connector_width": 0.8,
    "pad_object_connector_penetration": 0.4,
}


class TestConvertV2ConfigToSla:
    """`_convert_v2_config_to_sla` — used by /generate-supports path."""

    def test_accepts_all_11_pad_fields_no_whitelist(self):
        config = _convert_v2_config_to_sla(dict(PAD_CUSTOM_VALUES))
        assert config is not None
        for field, value in PAD_CUSTOM_VALUES.items():
            assert getattr(config, field) == value

    def test_ini_content_matches_sent_values(self):
        config = _convert_v2_config_to_sla(dict(PAD_CUSTOM_VALUES))
        with tempfile.TemporaryDirectory() as tmpdir:
            ini_path = Path(tmpdir) / "config.ini"
            generate_config_ini(config, ini_path)
            content = ini_path.read_text()
        assert "pad_wall_thickness = 3.5" in content
        assert "pad_wall_slope = 60.0" in content
        assert "pad_object_connector_penetration = 0.4" in content

    def test_pad_wall_slope_zero_rejected(self):
        with pytest.raises(ValidationError):
            _convert_v2_config_to_sla({"pad_wall_slope": 0})


class TestBuildSlaConfig:
    """`_build_sla_config` — used by /execute path."""

    def test_accepts_all_11_pad_fields_via_snake_config(self):
        config = _build_sla_config(prz_config=None, snake_config=dict(PAD_CUSTOM_VALUES))
        assert config is not None
        for field, value in PAD_CUSTOM_VALUES.items():
            assert getattr(config, field) == value

    def test_ini_content_matches_sent_values(self):
        config = _build_sla_config(prz_config=None, snake_config=dict(PAD_CUSTOM_VALUES))
        with tempfile.TemporaryDirectory() as tmpdir:
            ini_path = Path(tmpdir) / "config.ini"
            generate_config_ini(config, ini_path)
            content = ini_path.read_text()
        assert "pad_brim_size = 2.5" in content
        assert "pad_around_object_everywhere = 1" in content

    def test_pad_wall_slope_zero_rejected(self):
        with pytest.raises(ValidationError):
            _build_sla_config(prz_config=None, snake_config={"pad_wall_slope": 0})

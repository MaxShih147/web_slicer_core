"""
Contract test for the 11 pad_* default values — Task 1.4 (add-pad-global-params).

generate_config_ini (sla_operations.py:294) writes EVERY field of
SLAConfig.model_dump() into config.ini, whether or not the caller supplied it.
So the Python default for each pad_* field does not merely "match" the
engine's default — it REPLACES it once this change ships (before F2, the ini
had no pad_wall_thickness line at all and the engine fell back to its own
2.0mm; after F2, the ini always has one, and it is Python's number that wins).

A wrong default here is silent: no validation error, just every unadjusted
user's pad geometry quietly changing. This test pins SLAConfig's pad_*
defaults directly against PrintConfig.cpp's set_default_value(...) calls, so
drift (an engine upgrade, or someone "fixing" a default to match Pad.hpp's
different struct defaults — see design.md D3) fails loudly here instead of
surfacing as a customer report.

Mirrors the established pattern in test_slice_progress_string_contract.py.

Negative check (bottom of file): a deliberately wrong expected value MUST be
detected as different from both the source and SLAConfig — proving the
comparison has teeth.
"""

import re
from pathlib import Path

import pytest

from agent.models import SLAConfig

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PRINT_CONFIG_CPP = (
    _REPO_ROOT / "third_party" / "prusaslicer_fork" / "src" / "libslic3r" / "PrintConfig.cpp"
)

# The 11 pad_* fields opened by this change. pad_enable is deliberately
# excluded — it predates this change and SLAConfig intentionally defaults it
# to False (does not auto-enable pad generation), unlike the engine's true=1.
PAD_FIELD_NAMES = (
    "pad_wall_thickness",
    "pad_wall_height",
    "pad_brim_size",
    "pad_max_merge_distance",
    "pad_wall_slope",
    "pad_around_object",
    "pad_around_object_everywhere",
    "pad_object_gap",
    "pad_object_connector_stride",
    "pad_object_connector_width",
    "pad_object_connector_penetration",
)

_BLOCK_RE = re.compile(
    r'this->add\("(pad_\w+)",\s*(coFloat|coBool)\);(.*?)(?=this->add\(|\Z)',
    re.DOTALL,
)
_DEFAULT_RE = re.compile(r"set_default_value\(new ConfigOption(?:Float|Bool)\(([^)]+)\)\)")


def _parse_engine_pad_defaults(source: str) -> dict:
    """Parse every registered `pad_*` option's set_default_value from
    PrintConfig.cpp. Commented-out lines are stripped first, so the disabled
    pad_edge_radius block (never registered — commented out in the source)
    is correctly excluded."""
    kept_lines = [line for line in source.splitlines() if not line.strip().startswith("//")]
    filtered = "\n".join(kept_lines)

    defaults = {}
    for match in _BLOCK_RE.finditer(filtered):
        name, option_type, block = match.group(1), match.group(2), match.group(3)
        default_match = _DEFAULT_RE.search(block)
        if not default_match:
            continue
        raw = default_match.group(1).strip()
        defaults[name] = (raw == "true") if option_type == "coBool" else float(raw)
    return defaults


@pytest.fixture(scope="module")
def engine_pad_defaults() -> dict:
    if not _PRINT_CONFIG_CPP.exists():
        pytest.skip(f"fork submodule source not checked out: {_PRINT_CONFIG_CPP}")
    source = _PRINT_CONFIG_CPP.read_text(encoding="utf-8", errors="replace")
    return _parse_engine_pad_defaults(source)


class TestEngineDefaultsParsed:
    def test_all_11_fields_found_in_source(self, engine_pad_defaults):
        for field in PAD_FIELD_NAMES:
            assert field in engine_pad_defaults, (
                f"{field} not found in PrintConfig.cpp — option may have been "
                f"renamed or removed upstream"
            )


class TestPadDefaultsContract:
    """Pins SLAConfig's pad_* defaults against PrintConfig.cpp's
    set_default_value(...) — NOT against Pad.hpp's PadConfig struct, which
    has different values for 4 of these fields (design.md D3)."""

    @pytest.mark.parametrize("field", PAD_FIELD_NAMES)
    def test_default_matches_engine(self, field, engine_pad_defaults):
        config = SLAConfig()
        assert getattr(config, field) == engine_pad_defaults[field], (
            f"SLAConfig.{field} default drifted from PrintConfig.cpp's "
            f"set_default_value — generate_config_ini writes every field "
            f"unconditionally, so this silently changes output for every "
            f"user who never touches {field}"
        )


class TestNegativeCheck:
    """1.4: prove the contract fails when a default drifts."""

    # (field, a plausible wrong value that MUST differ from the real default)
    MUTATIONS = [
        ("pad_wall_thickness", 1.0),  # Pad.hpp's struct default, not PrintConfig.cpp's
        ("pad_wall_height", 1.0),  # Pad.hpp's struct default
        ("pad_object_connector_penetration", 0.1),  # Pad.hpp's struct default
        ("pad_wall_slope", 45.0),  # Pad.hpp's struct default (atan(1.0) in radians ≈ 45°)
    ]

    @pytest.mark.parametrize("field,wrong_value", MUTATIONS)
    def test_wrong_value_differs_from_engine_source(
        self, field, wrong_value, engine_pad_defaults
    ):
        """Sanity: the wrong (Pad.hpp-derived) value is genuinely different
        from what PrintConfig.cpp actually registers."""
        assert engine_pad_defaults[field] != wrong_value

    @pytest.mark.parametrize("field,wrong_value", MUTATIONS)
    def test_wrong_value_would_fail_against_sla_config(self, field, wrong_value):
        """If SLAConfig's default were mistakenly set to Pad.hpp's value
        instead of PrintConfig.cpp's, this comparison — the same one
        test_default_matches_engine performs — must catch it."""
        config = SLAConfig()
        assert getattr(config, field) != wrong_value

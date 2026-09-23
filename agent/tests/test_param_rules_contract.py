"""
Contract tests pinning agent/param_rules.py's formulas and constants against
the actual engine source — Tasks 2.1/2.2 (add-support-param-validation).

Mirrors test_support_string_contract.py's read/skip pattern: each fork file
is read once per module, `pytest.skip`s if the submodule isn't checked out
rather than failing, and a `TestNegativeCheck` class proves the assertions
have teeth (a plausible drift is asserted absent from source).

Unlike that file (English string needles matched against classifier output),
these are numeric constants and formula shapes — a "drift" here would be the
fork changing MIN_BRIM_SIZE_MM, EPSILON, or the is_zero_elevation /
head_fullwidth() logic without agent/param_rules.py being updated to match,
which would make our pre-check silently diverge from the engine's real
verdict (design.md's stated #1 risk).
"""

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FORK = _REPO_ROOT / "third_party" / "prusaslicer_fork" / "src"

_LIBSLIC3R_H = _FORK / "libslic3r" / "libslic3r.h"
_SLAPRINT_CPP = _FORK / "libslic3r" / "SLAPrint.cpp"
_SUPPORT_TREE_HPP = _FORK / "libslic3r" / "SLA" / "SupportTree.hpp"
_PAD_CPP = _FORK / "libslic3r" / "SLA" / "Pad.cpp"
_PAD_HPP = _FORK / "libslic3r" / "SLA" / "Pad.hpp"


def _read_source(path: Path) -> str:
    if not path.exists():
        pytest.skip(f"fork submodule source not checked out: {path}")
    return path.read_text(encoding="utf-8", errors="replace")


@pytest.fixture(scope="module")
def libslic3r_h_src():
    return _read_source(_LIBSLIC3R_H)


@pytest.fixture(scope="module")
def slaprint_cpp_src():
    return _read_source(_SLAPRINT_CPP)


@pytest.fixture(scope="module")
def support_tree_hpp_src():
    return _read_source(_SUPPORT_TREE_HPP)


@pytest.fixture(scope="module")
def pad_cpp_src():
    return _read_source(_PAD_CPP)


@pytest.fixture(scope="module")
def pad_hpp_src():
    return _read_source(_PAD_HPP)


class TestEpsilonConstant:
    """R4: support_base_safety_distance < EPSILON -> clamped to 0.5mm.
    param_rules._ENGINE_SAFETY_DISTANCE_EPSILON = 1e-4 must match EPSILON."""

    def test_epsilon_is_1e_minus_4(self, libslic3r_h_src):
        assert "static constexpr double EPSILON = 1e-4;" in libslic3r_h_src

    def test_param_rules_matches(self):
        from agent.param_rules import _ENGINE_SAFETY_DISTANCE_EPSILON

        assert _ENGINE_SAFETY_DISTANCE_EPSILON == 1e-4


class TestSafetyDistanceClamp:
    """R4: the EPSILON-gated fallback value is 0.5mm."""

    def test_safety_distance_mm_constant_is_half_a_millimeter(self, support_tree_hpp_src):
        assert "static const double constexpr safety_distance_mm = 0.5;" in support_tree_hpp_src

    def test_slaprint_clamps_using_epsilon(self, slaprint_cpp_src):
        assert "c.support_base_safety_distance.getFloat() < EPSILON ?" in slaprint_cpp_src
        assert "scfg.safety_distance_mm : c.support_base_safety_distance.getFloat();" in slaprint_cpp_src

    def test_param_rules_matches(self):
        from agent.param_rules import _ENGINE_DEFAULT_SAFETY_DISTANCE_MM

        assert _ENGINE_DEFAULT_SAFETY_DISTANCE_MM == 0.5


class TestIsZeroElevation:
    """R3/R4's gating condition: pad_enable AND pad_around_object (both)."""

    def test_definition_requires_both_switches(self, slaprint_cpp_src):
        assert "return c.pad_enable.getBool() && c.pad_around_object.getBool();" in slaprint_cpp_src

    def test_param_rules_matches(self):
        from agent.param_rules import _is_zero_elevation

        assert _is_zero_elevation({"pad_enable": True, "pad_around_object": True}) is True
        assert _is_zero_elevation({"pad_enable": True, "pad_around_object": False}) is False
        assert _is_zero_elevation({"pad_enable": False, "pad_around_object": True}) is False


class TestHeadFullwidth:
    """R3: elevation-too-low threshold formula, SupportTree.hpp Rule::head_fullwidth()."""

    def test_formula_shape_in_source(self, support_tree_hpp_src):
        assert "2 * head_front_radius_mm + head_width_mm +" in support_tree_hpp_src
        assert "2 * head_back_radius_mm - head_penetration_mm;" in support_tree_hpp_src

    def test_radii_are_half_the_diameters(self, slaprint_cpp_src):
        """head_front_radius_mm = 0.5*front_diameter, head_back_radius_mm =
        0.5*PILLAR diameter (not a separate 'back diameter' field) — this is
        what lets param_rules._head_fullwidth() sum diameters directly
        instead of doubling radii."""
        assert "scfg.head_front_radius_mm = 0.5*c.support_head_front_diameter.getFloat();" in slaprint_cpp_src
        assert "double pillar_r = 0.5 * c.support_pillar_diameter.getFloat();" in slaprint_cpp_src
        assert "scfg.head_back_radius_mm = pillar_r;" in slaprint_cpp_src

    def test_param_rules_matches_for_a_known_input(self):
        from agent.param_rules import _head_fullwidth

        # 2*0.2 + 1.0 + 2*0.5 - 0.2 = 0.4 + 1.0 + 1.0 - 0.2 = 2.2, using
        # diameters front=0.4, pillar=1.0 directly (halved-then-doubled radii).
        params = {
            "support_head_front_diameter": 0.4,
            "support_pillar_diameter": 1.0,
            "support_head_width": 1.0,
            "support_head_penetration": 0.2,
        }
        assert _head_fullwidth(params) == pytest.approx(2.2)


class TestPadMinBrimSize:
    """R5(PAD_CONFIG_INVALID)'s static floor: Pad.cpp PadConfig::validate()."""

    def test_constant_is_point_one_mm(self, pad_cpp_src):
        assert "static const double constexpr MIN_BRIM_SIZE_MM = .1;" in pad_cpp_src

    def test_validate_rejects_below_the_constant(self, pad_cpp_src):
        assert "if (brim_size_mm < MIN_BRIM_SIZE_MM ||" in pad_cpp_src

    def test_param_rules_matches(self):
        from agent.param_rules import _MIN_BRIM_SIZE_MM

        assert _MIN_BRIM_SIZE_MM == 0.1


class TestPadWallSlopeDegreesToRadians:
    """R5: pad_wall_slope is stored in degrees; the engine converts to
    radians before calling tan()."""

    def test_conversion_uses_pi_over_180(self, slaprint_cpp_src):
        assert "pcfg.wall_slope = c.pad_wall_slope.getFloat() * PI / 180.0;" in slaprint_cpp_src


class TestPadBottomOffsetFormula:
    """R5's dynamic threshold: bottom_offset() > brim_size_mm + wing_distance()
    algebraically reduces to thickness/tan(slope) > brim (wall_height cancels —
    see design derivation in agent/param_rules.py's docstring)."""

    def test_bottom_offset_and_wing_distance_are_tan_based(self, pad_hpp_src):
        assert "std::tan(wall_slope)" in pad_hpp_src

    def test_validate_compares_bottom_offset_against_brim_plus_wing(self, pad_cpp_src):
        assert "bottom_offset() > brim_size_mm + wing_distance() ||" in pad_cpp_src


class TestNegativeCheck:
    """2.2: prove the contract has teeth — a plausible drifted constant/formula
    must NOT be found in source."""

    MUTATIONS = [
        ("static constexpr double EPSILON = 1e-4;", "static constexpr double EPSILON = 1e-5;"),
        ("static const double constexpr safety_distance_mm = 0.5;", "static const double constexpr safety_distance_mm = 0.4;"),
        ("static const double constexpr MIN_BRIM_SIZE_MM = .1;", "static const double constexpr MIN_BRIM_SIZE_MM = .2;"),
        (
            "return c.pad_enable.getBool() && c.pad_around_object.getBool();",
            "return c.pad_enable.getBool() || c.pad_around_object.getBool();",
        ),
    ]

    @pytest.mark.parametrize("original,mutated", MUTATIONS)
    def test_mutation_differs_from_original(self, original, mutated):
        assert mutated != original

    @pytest.mark.parametrize("original,mutated", MUTATIONS)
    def test_mutated_text_is_not_in_source(
        self, original, mutated, libslic3r_h_src, support_tree_hpp_src, pad_cpp_src, slaprint_cpp_src
    ):
        combined = libslic3r_h_src + support_tree_hpp_src + pad_cpp_src + slaprint_cpp_src
        assert original in combined  # the real one is there
        assert mutated not in combined  # the drifted one is not

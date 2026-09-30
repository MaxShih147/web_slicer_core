"""
Tests for agent/param_rules.py — Tasks 1.1/1.5/1.6/1.7 (add-support-param-validation).

Seven pure-arithmetic rules mirror the engine's SLAPrint::validate() /
PadConfig::validate() checks, so bad support/pad parameters can be rejected
before ever invoking the engine. Every boundary value here is derived from
the real C++ constants/formulas (see test_param_rules_contract.py for the
pin against the fork source), not estimated:

  R1 SUPPORT_HEAD_TOO_WIDE            front_diameter > pillar_diameter
  R2 SUPPORT_HEAD_PENETRATION_INVALID head_penetration > head_width
  R3 SUPPORT_ELEVATION_TOO_LOW        elevation < head_fullwidth (unless
                                       pad_enable and pad_around_object)
  R4 SUPPORT_PAD_GAP_CONFLICT         effective_safety_distance < pad_object_gap
                                       (only when pad_enable and pad_around_object)
  R5 PAD_CONFIG_INVALID               brim < 0.1, or thickness/tan(slope) > brim
  R6 SUPPORT_POINTS_REQUIRED          supports_enable, manual points supplied,
                                       and that count is 0
  R7 EXPOSURE_TIME_OUT_OF_RANGE       (slice_only) exposure/initial exposure time
                                       outside the supplied printer profile bounds

Plus two rules with no engine validate() counterpart, added because the
engine silently mishandles them rather than rejecting them:

  R5-density  support_points_density_relative == 0 with no manual points
              supplied silently produces zero support points (float divide
              by the relative density inside SupportPointGenerator.cpp) —
              must not be reported as "supports not needed".
  D9          shrinkage_compensation enabled with any axis at 0% makes the
              object's transform matrix singular (a zero diagonal entry),
              the same failure merge-engine-result-classifiers gave
              SHRINKAGE_COMPENSATION_INVALID for.

`manual_point_count` / `printer_bounds` are the two optional inputs
mentioned in design.md D3 (mirroring the /validate request body) — rules 6,
R5-density and 7 need information `SLAConfig` alone doesn't carry.
"""

import math

import pytest

from agent.models import SLAConfig
from agent.param_rules import RULES, evaluate, rules_for


def _params(**overrides):
    """A full SLAConfig-shaped dict, defaults overridden per test.

    Round-trips through SLAConfig so existing validators (enforce_min_elevation's
    clamp, pad_wall_slope's range check) apply exactly as they would on a real
    request — param_rules.evaluate() is documented to receive already-clamped,
    already-validated values, matching what actually reaches the engine.
    """
    base = SLAConfig().model_dump()
    base.update(overrides)
    return SLAConfig(**base).model_dump()


def _codes(problems):
    return {p.code for p in problems}


class TestR1SupportHeadTooWide:
    def test_equal_diameters_pass(self):
        """Boundary: strict '>' in the C++ check, so equal is legal."""
        params = _params(support_head_front_diameter=1.0, support_pillar_diameter=1.0)
        assert "SUPPORT_HEAD_TOO_WIDE" not in _codes(evaluate("support", params))

    def test_front_diameter_slightly_larger_fails(self):
        params = _params(support_head_front_diameter=1.01, support_pillar_diameter=1.0)
        problems = evaluate("support", params)
        assert "SUPPORT_HEAD_TOO_WIDE" in _codes(problems)
        problem = next(p for p in problems if p.code == "SUPPORT_HEAD_TOO_WIDE")
        assert set(problem.fields) == {"support_head_front_diameter", "support_pillar_diameter"}


class TestR2SupportHeadPenetrationInvalid:
    def test_equal_pass(self):
        params = _params(support_head_penetration=1.0, support_head_width=1.0)
        assert "SUPPORT_HEAD_PENETRATION_INVALID" not in _codes(evaluate("support", params))

    def test_penetration_slightly_larger_fails(self):
        params = _params(support_head_penetration=1.01, support_head_width=1.0)
        assert "SUPPORT_HEAD_PENETRATION_INVALID" in _codes(evaluate("support", params))


class TestR3SupportElevationTooLow:
    # head_fullwidth = front_diameter + pillar_diameter + head_width - penetration
    # Defaults: 0.4 + pillar + 1.0 - 0.2 = pillar + 1.2. Solve pillar so
    # head_fullwidth == 5.0 exactly (elevation floors at 5.0 via enforce_min_elevation).
    PILLAR_AT_BOUNDARY = 5.0 - 1.2

    def test_elevation_equal_to_head_fullwidth_passes(self):
        params = _params(
            supports_enable=True,
            support_pillar_diameter=self.PILLAR_AT_BOUNDARY,
            support_object_elevation=5.0,
            pad_enable=False,
        )
        assert "SUPPORT_ELEVATION_TOO_LOW" not in _codes(evaluate("support", params))

    def test_head_fullwidth_slightly_over_elevation_fails(self):
        params = _params(
            supports_enable=True,
            support_pillar_diameter=self.PILLAR_AT_BOUNDARY + 0.01,
            support_object_elevation=5.0,
            pad_enable=False,
        )
        assert "SUPPORT_ELEVATION_TOO_LOW" in _codes(evaluate("support", params))

    def test_zero_elevation_mode_skips_the_check_entirely(self):
        """pad_enable AND pad_around_object -> builtinpad.enabled -> gate is off."""
        params = _params(
            supports_enable=True,
            support_pillar_diameter=self.PILLAR_AT_BOUNDARY + 50,  # would fail otherwise
            support_object_elevation=5.0,
            pad_enable=True,
            pad_around_object=True,
        )
        assert "SUPPORT_ELEVATION_TOO_LOW" not in _codes(evaluate("support", params))

    def test_supports_disabled_skips_the_check(self):
        params = _params(
            supports_enable=False,
            support_pillar_diameter=self.PILLAR_AT_BOUNDARY + 50,
            support_object_elevation=5.0,
            pad_enable=False,
        )
        assert "SUPPORT_ELEVATION_TOO_LOW" not in _codes(evaluate("support", params))


class TestR4SupportPadGapConflict:
    def test_equal_safety_distance_and_gap_pass(self):
        params = _params(
            supports_enable=True,
            pad_enable=True,
            pad_around_object=True,
            support_base_safety_distance=1.0,
            pad_object_gap=1.0,
        )
        assert "SUPPORT_PAD_GAP_CONFLICT" not in _codes(evaluate("support", params))

    def test_gap_slightly_larger_than_safety_distance_fails(self):
        params = _params(
            supports_enable=True,
            pad_enable=True,
            pad_around_object=True,
            support_base_safety_distance=1.0,
            pad_object_gap=1.01,
        )
        assert "SUPPORT_PAD_GAP_CONFLICT" in _codes(evaluate("support", params))

    def test_not_gated_without_pad_around_object(self):
        params = _params(
            supports_enable=True,
            pad_enable=True,
            pad_around_object=False,
            support_base_safety_distance=1.0,
            pad_object_gap=100.0,
        )
        assert "SUPPORT_PAD_GAP_CONFLICT" not in _codes(evaluate("support", params))

    def test_near_zero_safety_distance_uses_engine_clamp_of_half_mm(self):
        """support_base_safety_distance < EPSILON(1e-4) -> engine clamps to 0.5mm."""
        params = _params(
            supports_enable=True,
            pad_enable=True,
            pad_around_object=True,
            support_base_safety_distance=0.0,
            pad_object_gap=0.5,  # equals the clamped 0.5 -> boundary pass
        )
        assert "SUPPORT_PAD_GAP_CONFLICT" not in _codes(evaluate("support", params))

        params["pad_object_gap"] = 0.51
        assert "SUPPORT_PAD_GAP_CONFLICT" in _codes(evaluate("support", params))


class TestR5PadConfigInvalid:
    def test_brim_at_minimum_passes(self):
        params = _params(pad_brim_size=0.1, pad_wall_thickness=0.0)
        assert "PAD_CONFIG_INVALID" not in _codes(evaluate("support", params))

    def test_brim_below_minimum_fails(self):
        params = _params(pad_brim_size=0.099, pad_wall_thickness=0.0)
        assert "PAD_CONFIG_INVALID" in _codes(evaluate("support", params))

    def test_dynamic_threshold_51_4_passes_51_3_fails(self):
        """design.md's own worked example: thickness=2.0, brim=1.6."""
        base = dict(pad_wall_thickness=2.0, pad_brim_size=1.6)
        assert "PAD_CONFIG_INVALID" not in _codes(
            evaluate("support", _params(pad_wall_slope=51.4, **base))
        )
        assert "PAD_CONFIG_INVALID" in _codes(
            evaluate("support", _params(pad_wall_slope=51.3, **base))
        )

    def test_threshold_moves_when_brim_increases(self):
        """D4: the same slope (50) that fails at brim=1.6 must pass once brim
        is raised to 2.5 — proves the threshold is derived, not a constant."""
        failing = _params(pad_wall_slope=50.0, pad_wall_thickness=2.0, pad_brim_size=1.6)
        assert "PAD_CONFIG_INVALID" in _codes(evaluate("support", failing))

        passing = _params(pad_wall_slope=50.0, pad_wall_thickness=2.0, pad_brim_size=2.5)
        assert "PAD_CONFIG_INVALID" not in _codes(evaluate("support", passing))

    def test_reports_the_computed_minimum_slope(self):
        problems = evaluate(
            "support",
            _params(pad_wall_slope=50.0, pad_wall_thickness=2.0, pad_brim_size=1.6),
        )
        problem = next(p for p in problems if p.code == "PAD_CONFIG_INVALID")
        assert problem.values["min_pad_wall_slope"] == pytest.approx(51.4, abs=0.05)
        assert set(problem.fields) == {"pad_wall_slope", "pad_wall_thickness", "pad_brim_size"}


class TestR6SupportPointsRequired:
    def test_no_manual_point_count_supplied_does_not_fire(self):
        """manual_point_count=None means 'auto-generation path' — rule 6 only
        fires for the imported-points path (C++ PointsStatus::UserModified)."""
        params = _params(supports_enable=True)
        assert "SUPPORT_POINTS_REQUIRED" not in _codes(
            evaluate("support", params, manual_point_count=None)
        )

    def test_one_manual_point_passes(self):
        params = _params(supports_enable=True)
        assert "SUPPORT_POINTS_REQUIRED" not in _codes(
            evaluate("support", params, manual_point_count=1)
        )

    def test_zero_manual_points_fails(self):
        params = _params(supports_enable=True)
        assert "SUPPORT_POINTS_REQUIRED" in _codes(
            evaluate("support", params, manual_point_count=0)
        )

    def test_supports_disabled_skips_the_check(self):
        params = _params(supports_enable=False)
        assert "SUPPORT_POINTS_REQUIRED" not in _codes(
            evaluate("support", params, manual_point_count=0)
        )


class TestR7ExposureTimeOutOfRange:
    BOUNDS = {
        "min_exposure_time": 1.0,
        "max_exposure_time": 120.0,
        "min_initial_exposure_time": 1.0,
        "max_initial_exposure_time": 300.0,
    }

    def test_no_printer_bounds_supplied_does_not_fire(self):
        params = _params(exposure_time=99999.0)
        assert "EXPOSURE_TIME_OUT_OF_RANGE" not in _codes(
            evaluate("slice", params, printer_bounds=None)
        )

    def test_within_bounds_passes(self):
        params = _params(exposure_time=10.0, initial_exposure_time=15.0)
        assert "EXPOSURE_TIME_OUT_OF_RANGE" not in _codes(
            evaluate("slice", params, printer_bounds=self.BOUNDS)
        )

    def test_exposure_time_above_max_fails(self):
        params = _params(exposure_time=121.0, initial_exposure_time=15.0)
        assert "EXPOSURE_TIME_OUT_OF_RANGE" in _codes(
            evaluate("slice", params, printer_bounds=self.BOUNDS)
        )

    def test_initial_exposure_time_below_min_fails(self):
        params = _params(exposure_time=10.0, initial_exposure_time=0.5)
        assert "EXPOSURE_TIME_OUT_OF_RANGE" in _codes(
            evaluate("slice", params, printer_bounds=self.BOUNDS)
        )

    def test_is_slice_only_scope_not_evaluated_for_support_profile(self):
        params = _params(exposure_time=99999.0)
        assert "EXPOSURE_TIME_OUT_OF_RANGE" not in _codes(
            evaluate("support", params, printer_bounds=self.BOUNDS)
        )


class TestR5DensityZeroSilentlyProducesNoSupports:
    def test_zero_density_no_manual_points_is_blocked(self):
        params = _params(supports_enable=True, support_points_density_relative=0)
        problems = evaluate("support", params, manual_point_count=None)
        assert "SUPPORT_POINTS_REQUIRED" in _codes(problems)
        problem = next(p for p in problems if "support_points_density_relative" in p.fields)
        assert "support_points_density_relative" in problem.fields

    def test_zero_density_with_manual_points_is_not_blocked(self):
        """Manual points bypass auto-generation entirely in the engine, so a
        zero relative density is irrelevant when points are supplied."""
        params = _params(supports_enable=True, support_points_density_relative=0)
        problems = evaluate("support", params, manual_point_count=5)
        assert not any("support_points_density_relative" in p.fields for p in problems)

    def test_nonzero_density_passes(self):
        params = _params(supports_enable=True, support_points_density_relative=1)
        problems = evaluate("support", params, manual_point_count=None)
        assert not any("support_points_density_relative" in p.fields for p in problems)


class TestD9ShrinkageCompensationInvalid:
    def test_disabled_compensation_never_fires(self):
        params = _params(shrinkage_compensation=False, shrinkage_compensation_x=0.0)
        assert "SHRINKAGE_COMPENSATION_INVALID" not in _codes(evaluate("support", params))

    def test_nonzero_axes_pass(self):
        params = _params(
            shrinkage_compensation=True,
            shrinkage_compensation_x=99.0,
            shrinkage_compensation_y=100.0,
            shrinkage_compensation_z=101.0,
        )
        assert "SHRINKAGE_COMPENSATION_INVALID" not in _codes(evaluate("support", params))

    @pytest.mark.parametrize("axis", ["shrinkage_compensation_x", "shrinkage_compensation_y", "shrinkage_compensation_z"])
    def test_any_axis_at_zero_fails(self, axis):
        params = _params(shrinkage_compensation=True, **{axis: 0.0})
        problems = evaluate("support", params)
        assert "SHRINKAGE_COMPENSATION_INVALID" in _codes(problems)


class TestAllParamsLegalPasses:
    def test_default_config_has_no_problems(self):
        assert evaluate("support", _params(supports_enable=True)) == []
        assert evaluate("slice", _params(supports_enable=True)) == []


class TestScopeAndProfiles:
    def test_scope_distribution(self):
        """1.3's own checkpoint command (7 engine-mirrored rules only) prints
        Counter({'support_params': 6, 'slice_only': 1}); this test covers the
        final RULES table including D9 (Task 1.7), which adds one more
        support_params entry with no engine validate() counterpart."""
        import collections

        counts = collections.Counter(r.scope for r in RULES)
        assert counts == collections.Counter({"support_params": 7, "slice_only": 1})

    def test_profile_rule_counts(self):
        """1.4's own checkpoint (before D9) prints 6 7 1; final counts are one
        higher for any profile that includes support_params, since D9 has no
        engine validate() counterpart to add elsewhere."""
        assert len(rules_for("support")) == 7
        assert len(rules_for("slice")) == 8
        assert len(rules_for("slice_imported")) == 1

    def test_support_is_a_proper_subset_of_slice(self):
        """1.5: prevents ever going back to parallel tables — support MUST
        remain a strict subset of slice, derived by the union, not hand-synced."""
        assert set(rules_for("support")) < set(rules_for("slice"))

    def test_slice_imported_never_validates_support_params(self):
        """D2: slice_imported must contain zero support_params-scope rules."""
        assert all(r.scope != "support_params" for r in rules_for("slice_imported"))


class TestImportedFlowSkipsSupportParams:
    def test_pad_config_invalid_not_raised_under_slice_imported(self):
        """spec.md: 'WHEN input/support.stl exists AND pad params violate
        PAD_CONFIG_INVALID THEN validation MUST pass'."""
        params = _params(pad_brim_size=0.01, pad_wall_thickness=5.0)  # would fail otherwise
        assert evaluate("slice_imported", params) == []

    def test_pad_config_invalid_still_raised_for_self_generated_supports(self):
        params = _params(pad_brim_size=0.01, pad_wall_thickness=5.0)
        assert "PAD_CONFIG_INVALID" in _codes(evaluate("slice", params))

"""
engine-error-code-table Task 3.6 — the gate before Section 4.

For the same failure, the coded engine (PHZ_ERROR on stdout, English on
stderr) and the pre-change engine (English only) must classify to the same
code. If they disagree, either a code was copied wrong in EngineErrorCodes.hpp
(2.1) or a report sits at the wrong point in the engine (2.2).

data/engine_outputs.json is real CLI output; see its "about" field.
"""
import json
from pathlib import Path

import pytest

from agent.models import JobStatus
from agent.slicing_classifier import classify_slice_result
from agent.support_classifier import classify_support_result

_FIXTURE = Path(__file__).parent / "data" / "engine_outputs.json"
_RECORDS = json.loads(_FIXTURE.read_text(encoding="utf-8"))["records"]

# What each run should classify to, worked out from the rule table and the
# two classifiers rather than read off the fixture. None = no error code:
# a completed support job, or a successful slice.
EXPECTED = {
    ("support", "pad_config_invalid"): "PAD_CONFIG_INVALID",
    ("support", "head_too_wide"): "SUPPORT_HEAD_TOO_WIDE",
    ("support", "head_penetration_invalid"): "SUPPORT_HEAD_PENETRATION_INVALID",
    ("support", "elevation_too_low"): "SUPPORT_ELEVATION_TOO_LOW",
    ("support", "pad_gap_conflict"): "SUPPORT_PAD_GAP_CONFLICT",
    # The support flow has always routed these two to its fallback.
    ("support", "exposure_out_of_range"): "SUPPORT_GENERATION_FAILED",
    ("support", "mesh_unsliceable"): "SUPPORT_GENERATION_FAILED",
    ("support", "support_points_model_mismatch"): "SUPPORT_POINTS_MODEL_MISMATCH",
    ("support", "support_mesh_export_failed"): "SUPPORT_MESH_EXPORT_FAILED",
    ("support", "success"): None,
    ("slice", "pad_config_invalid"): "PAD_CONFIG_INVALID",
    ("slice", "head_too_wide"): "SUPPORT_HEAD_TOO_WIDE",
    ("slice", "head_penetration_invalid"): "SUPPORT_HEAD_PENETRATION_INVALID",
    ("slice", "elevation_too_low"): "SUPPORT_ELEVATION_TOO_LOW",
    ("slice", "pad_gap_conflict"): "SUPPORT_PAD_GAP_CONFLICT",
    ("slice", "exposure_out_of_range"): "EXPOSURE_TIME_OUT_OF_RANGE",
    ("slice", "mesh_unsliceable"): "MODEL_MESH_UNSLICEABLE",
    ("slice", "support_points_model_mismatch"): "SUPPORT_POINTS_MODEL_MISMATCH",
    # The .sl1 is already written when the support STL fails; the slice stands
    # (same as a failed preview ZIP). engine-error-code-table D6.
    ("slice", "support_mesh_export_failed"): None,
    ("slice", "success"): None,
}


def _record(engine, flow, scenario):
    return next(
        r for r in _RECORDS
        if (r["engine"], r["flow"], r["scenario"]) == (engine, flow, scenario)
    )


def _classify(record, *, stderr=None):
    """(status, error_code) the classifier gives this run. `stderr` replaces
    the captured stderr when given."""
    err = record["stderr"] if stderr is None else stderr
    if record["flow"] == "support":
        result = classify_support_result(record["stdout"], err, record["output_exists"])
        return result.status, result.error_code
    result = classify_slice_result(
        record["exit_code"], record["stdout"], err, "model.stl", record["output_exists"]
    )
    if result is None:
        return JobStatus.COMPLETED, None
    return JobStatus.FAILED, result.error_code


def test_fixture_really_holds_two_different_layers():
    """Guards the comparison below: the coded runs must carry PHZ_ERROR lines
    on failure and the legacy runs none, or the two sides are the same layer."""
    for (flow, scenario), expected in EXPECTED.items():
        coded = _record("coded", flow, scenario)
        legacy = _record("legacy", flow, scenario)
        assert "PHZ_ERROR" not in legacy["stdout"], (flow, scenario)
        if expected is None:
            assert "PHZ_ERROR" not in coded["stdout"], (flow, scenario)
        else:
            assert "PHZ_ERROR" in coded["stdout"], (flow, scenario)


@pytest.mark.parametrize("flow,scenario", sorted(EXPECTED))
def test_coded_and_legacy_engine_classify_the_same(flow, scenario):
    coded = _classify(_record("coded", flow, scenario))
    legacy = _classify(_record("legacy", flow, scenario))
    assert coded == legacy
    assert coded[1] == EXPECTED[(flow, scenario)]


@pytest.mark.parametrize("flow,scenario", sorted(EXPECTED))
def test_coded_engine_classifies_the_same_without_its_english_text(flow, scenario):
    """The new layer alone reaches the same answer: drop stderr entirely and
    classify on the coded engine's stdout."""
    record = _record("coded", flow, scenario)
    assert _classify(record, stderr="") == _classify(record)

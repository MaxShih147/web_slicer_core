"""
engine-error-code-table Section 4 — a failed run exits non-zero.

process_actions() is a `bool` function; 15 of its failure paths said
`return 1`, which converts to `true`, so the CLI reported success (exit 0)
while printing an error. Checked on the real CLI output in
data/engine_outputs.json; see its "about" field.

Only the coded engine is checked: the legacy engine is the pre-change binary,
kept in the fixture as the control for the two-layer comparison.
"""
import json
from pathlib import Path

import pytest

_FIXTURE = Path(__file__).parent / "data" / "engine_outputs.json"
_RECORDS = json.loads(_FIXTURE.read_text(encoding="utf-8"))["records"]

# Every failure scenario the fixture captures, per flow. Named here rather
# than read off the fixture, so a run that stops failing cannot quietly
# drop out of the check.
FAILURES = {
    "support": [
        "pad_config_invalid",
        "head_too_wide",
        "head_penetration_invalid",
        "elevation_too_low",
        "pad_gap_conflict",
        "exposure_out_of_range",
        "mesh_unsliceable",
        "support_points_model_mismatch",
        "support_mesh_export_failed",
    ],
    "slice": [
        "pad_config_invalid",
        "head_too_wide",
        "head_penetration_invalid",
        "elevation_too_low",
        "pad_gap_conflict",
        "exposure_out_of_range",
        "mesh_unsliceable",
        "support_points_model_mismatch",
    ],
    "hollow": [
        "interior_mesh_empty",
    ],
}


def _coded(flow, scenario):
    return next(
        r for r in _RECORDS
        if (r["engine"], r["flow"], r["scenario"]) == ("coded", flow, scenario)
    )


@pytest.mark.parametrize(
    "flow,scenario",
    [(flow, s) for flow, scenarios in FAILURES.items() for s in scenarios],
)
def test_a_failed_run_exits_non_zero(flow, scenario):
    record = _coded(flow, scenario)
    assert not record["output_exists"], "not a failure: the output was written"
    assert record["exit_code"] != 0, record["stderr"]


def test_a_support_stl_write_failure_does_not_fail_a_slice():
    """D6: in a slice the .sl1 is written before the support STL, and the STL
    only feeds the UI, so failing to write it leaves the slice standing."""
    record = _coded("slice", "support_mesh_export_failed")
    assert "Failed to export support mesh" in record["stderr"], "scenario did not trigger"
    assert record["output_exists"]
    assert record["exit_code"] == 0, record["stderr"]


@pytest.mark.parametrize("flow", sorted(FAILURES))
def test_a_successful_run_still_exits_zero(flow):
    record = _coded(flow, "success")
    assert record["output_exists"]
    assert record["exit_code"] == 0, record["stderr"]

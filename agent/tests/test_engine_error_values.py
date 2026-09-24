"""
engine-error-code-table Task 8.1: the fields and values the engine reports
reach the classification, so they can be stored with the job and shown.

Checked on the real CLI output in data/engine_outputs.json (see its "about").
The expected numbers are the worked example the backend precheck uses for the
same config (thickness 2 mm, brim 1.6 mm, slope 50 deg), not read off the
fixture.
"""
import json
from pathlib import Path

import pytest

from agent.slicing_classifier import classify_slice_result
from agent.support_classifier import classify_support_result

_FIXTURE = Path(__file__).parent / "data" / "engine_outputs.json"
_RECORDS = json.loads(_FIXTURE.read_text(encoding="utf-8"))["records"]

PAD_FIELDS = ("pad_wall_slope", "pad_wall_thickness", "pad_brim_size")
PAD_VALUES = {"min_pad_wall_slope": 51.4, "pad_wall_slope": 50}


def _record(engine, flow, scenario):
    return next(
        r for r in _RECORDS
        if (r["engine"], r["flow"], r["scenario"]) == (engine, flow, scenario)
    )


def _classify(record):
    if record["flow"] == "support":
        return classify_support_result(
            record["stdout"], record["stderr"], record["output_exists"]
        )
    return classify_slice_result(
        record["exit_code"], record["stdout"], record["stderr"], "model.stl",
        record["output_exists"],
    )


@pytest.mark.parametrize("flow", ["support", "slice"])
def test_the_engine_values_reach_the_classification(flow):
    result = _classify(_record("coded", flow, "pad_config_invalid"))
    assert result.error_code == "PAD_CONFIG_INVALID"
    assert result.fields == PAD_FIELDS
    assert result.values == pytest.approx(PAD_VALUES)


@pytest.mark.parametrize("flow", ["support", "slice"])
def test_an_engine_without_the_line_gives_no_values(flow):
    result = _classify(_record("legacy", flow, "pad_config_invalid"))
    assert result.error_code == "PAD_CONFIG_INVALID"
    assert result.fields is None
    assert result.values is None


def test_values_do_not_ride_on_a_code_the_engine_did_not_declare():
    """The support flow routes an exposure failure to its fallback code. The
    engine's numbers describe EXPOSURE_TIME_OUT_OF_RANGE, not that fallback,
    so they must not be attached to it."""
    result = _classify(_record("coded", "support", "exposure_out_of_range"))
    assert result.error_code == "SUPPORT_GENERATION_FAILED"
    assert result.fields is None
    assert result.values is None

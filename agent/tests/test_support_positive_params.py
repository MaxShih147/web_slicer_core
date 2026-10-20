"""
Tests for fix-support-zero-param-engine-hang Phase 1.

support_max_bridge_length (Max Connector Length) must be finite and >= 1e-4,
support_base_diameter (Base Diameter) finite and >= 2e-4. At 0 the engine's
support clustering predicate (`d < max_bridge_length`) can't even take the seed
point into its own cluster, so the clustering loop never advances and the
engine hangs. The diameter's floor is twice the per-point radius floor (1e-4)
because the engine halves it into the radius it exports with every point.

Covers:
  - 1.1: SLAConfig rejects 0 / -0.0 / negatives / positives below the floor /
    NaN / ±inf / "0" for both fields, with loc[0] naming the field; each
    floor itself and the defaults pass;
    support_max_pillar_link_distance=0 stays legal
  - 1.11: APIError.to_response() is unchanged without details, and emits
    data.errors when details are given
"""

import json
import struct

import pytest
from pydantic import ValidationError

from agent.models import SLAConfig

POSITIVE_FIELDS = ["support_max_bridge_length", "support_base_diameter"]
FLOORS = {"support_max_bridge_length": 1e-4, "support_base_diameter": 2e-4}
BAD_VALUES = [
    0, -0.0, -1, -0.5, float("nan"), float("inf"), float("-inf"), "0",
    # Positive but below the 1e-4 floor. 5e-324 is the one that would still
    # hang the engine under a bare `> 0` check: 0.5 * 5e-324 == 0.0.
    1e-9, 0.00009, 5e-324,
]
# Legal for the connector length, below the base diameter's 2e-4 floor.
BAD_DIAMETERS = [0.0001, 0.00015, 0.00019]


class TestSupportPositiveFields:
    @pytest.mark.parametrize("field", POSITIVE_FIELDS)
    @pytest.mark.parametrize("value", BAD_VALUES, ids=repr)
    def test_rejects_non_positive_or_non_finite(self, field, value):
        """support-param-validation: 負零被拒絕 / 負數被拒絕 / NaN 被拒絕 /
        正負無限大被拒絕 / 字串零被拒絕 / 小於門檻的正數被拒絕"""
        with pytest.raises(ValidationError) as exc_info:
            SLAConfig(**{field: value})
        errors = exc_info.value.errors()
        assert errors, "expected at least one validation error"
        assert all(err["loc"][0] == field for err in errors)

    @pytest.mark.parametrize("value", BAD_DIAMETERS, ids=repr)
    def test_base_diameter_below_its_own_floor(self, value):
        """support-param-validation: 底座直徑小於 2e-4 被拒絕"""
        with pytest.raises(ValidationError) as exc_info:
            SLAConfig(support_base_diameter=value)
        assert [err["loc"][0] for err in exc_info.value.errors()] == ["support_base_diameter"]

    @pytest.mark.parametrize("field", POSITIVE_FIELDS)
    def test_floor_value_passes(self, field):
        """support-param-validation: 門檻值本身可通過 (each field alone)"""
        config = SLAConfig(**{field: FLOORS[field]})
        assert getattr(config, field) == FLOORS[field]

    def test_floor_value_passes_for_both_at_once(self):
        """support-param-validation: 門檻值本身可通過"""
        config = SLAConfig(support_max_bridge_length=0.0001, support_base_diameter=0.0002)
        assert config.support_max_bridge_length == 0.0001
        assert config.support_base_diameter == 0.0002

    def test_defaults_unchanged(self):
        """support-param-validation: 預設值不受影響"""
        config = SLAConfig()
        assert config.support_max_bridge_length == 15.0
        assert config.support_base_diameter == 4.0

    def test_link_distance_zero_still_legal(self):
        """support-param-validation: Link Distance 為 0 仍合法 (model level; the
        PUT /config half is in test_support_param_invalid_api.py)"""
        config = SLAConfig(support_max_pillar_link_distance=0)
        assert config.support_max_pillar_link_distance == 0

    def test_positive_fields_constant(self):
        from agent.models import SUPPORT_POSITIVE_FIELDS

        assert SUPPORT_POSITIVE_FIELDS == frozenset(POSITIVE_FIELDS)

    def test_floor_constants_drive_the_fields(self):
        from agent.models import SUPPORT_BASE_DIAMETER_FLOOR_MM, SUPPORT_SIZE_FLOOR_MM

        assert SUPPORT_SIZE_FLOOR_MM == 1e-4
        assert SUPPORT_BASE_DIAMETER_FLOOR_MM == 2e-4
        for field, floor in FLOORS.items():
            bounds = {type(m).__name__: m for m in SLAConfig.model_fields[field].metadata}
            assert bounds["Ge"].ge == floor

    def test_diameter_floor_halves_to_the_point_radius_floor(self):
        """support-point-api: 引擎匯出的半徑送回可通過 (the arithmetic half): the
        engine's radius is 0.5 * diameter, which at the diameter floor is the
        per-point floor exactly, and its float form is the float floor."""
        from agent.models import (
            SUPPORT_BASE_DIAMETER_FLOOR_MM,
            SUPPORT_POINT_RADIUS_FLOOR_F32,
            SUPPORT_SIZE_FLOOR_MM,
        )

        radius = 0.5 * SUPPORT_BASE_DIAMETER_FLOOR_MM
        assert radius == SUPPORT_SIZE_FLOOR_MM
        as_float = struct.unpack("<f", struct.pack("<f", radius))[0]
        assert as_float == SUPPORT_POINT_RADIUS_FLOOR_F32 < SUPPORT_SIZE_FLOOR_MM


class TestAPIErrorDetails:
    def test_response_without_details_is_unchanged(self):
        from agent.errors import APIError

        err = APIError("CONFIG_VALIDATION_ERROR", "bad", 422, retryable=False)
        body = json.loads(err.to_response().body)
        assert body == {
            "success": False,
            "code": "CONFIG_VALIDATION_ERROR",
            "message": "bad",
            "data": {"retryable": False, "traceId": err.trace_id},
        }

    def test_response_with_details_emits_errors(self):
        from agent.errors import support_param_invalid

        details = [{"loc": ["support_max_bridge_length"], "msg": "must be > 0"}]
        err = support_param_invalid("bad", errors=details)
        body = json.loads(err.to_response().body)
        assert err.to_response().status_code == 422
        assert body["code"] == "SUPPORT_PARAM_INVALID"
        assert body["data"] == {
            "retryable": False,
            "traceId": err.trace_id,
            "errors": details,
        }

    def test_point_factory(self):
        from agent.errors import support_point_param_invalid

        details = [{"loc": ["points", 1, "base_radius_mm"], "msg": "must not be 0"}]
        err = support_point_param_invalid("bad", errors=details)
        body = json.loads(err.to_response().body)
        assert err.http_status == 422
        assert body["code"] == "SUPPORT_POINT_PARAM_INVALID"
        assert body["data"]["retryable"] is False
        assert body["data"]["errors"] == details

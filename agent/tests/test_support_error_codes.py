"""
Tests for support-generation error codes — Task 1
(add-support-generation-error-codes).

Covers:
  - 1.1: each new factory produces the correct code / http_status / retryable
  - 1.2: _ERROR_CODE_FACTORIES resolves every support code to a factory whose
         output carries that same code
"""

import pytest

from agent.errors import (
    APIError,
    model_out_of_bounds,
    support_elevation_too_low,
    support_generation_failed,
    support_head_penetration_invalid,
    support_head_too_wide,
    support_pad_gap_conflict,
    support_points_model_mismatch,
    support_points_required,
)
from agent.api_v2 import _ERROR_CODE_FACTORIES, _error_from_status

# (factory, expected_code, expected_http_status, expected_retryable)
SUPPORT_FACTORY_CASES = [
    (support_head_too_wide, "SUPPORT_HEAD_TOO_WIDE", 422, False),
    (support_head_penetration_invalid, "SUPPORT_HEAD_PENETRATION_INVALID", 422, False),
    (support_elevation_too_low, "SUPPORT_ELEVATION_TOO_LOW", 422, False),
    (support_points_required, "SUPPORT_POINTS_REQUIRED", 422, False),
    (support_pad_gap_conflict, "SUPPORT_PAD_GAP_CONFLICT", 422, False),
    (model_out_of_bounds, "MODEL_OUT_OF_BOUNDS", 422, False),
    (support_generation_failed, "SUPPORT_GENERATION_FAILED", 422, False),
    # 8.1: imported point list does not describe this model. 422 / not retryable
    # for the same reason as the rest of the family — replaying the identical
    # input against the identical model always fails the same way.
    (support_points_model_mismatch, "SUPPORT_POINTS_MODEL_MISMATCH", 422, False),
]

# The support codes that MUST be registered so _error_from_status can return
# a specific error instead of falling back to JOB_FAILED.
REGISTERED_SUPPORT_CODES = [code for (_, code, _, _) in SUPPORT_FACTORY_CASES]


class TestSupportFactoryShape:
    @pytest.mark.parametrize(
        "factory,code,http_status,retryable", SUPPORT_FACTORY_CASES
    )
    def test_factory_fields(self, factory, code, http_status, retryable):
        """1.1: 每個 factory 產出的 code / http_status / retryable 正確。"""
        err = factory()
        assert isinstance(err, APIError)
        assert err.code == code
        assert err.http_status == http_status
        assert err.retryable is retryable

    @pytest.mark.parametrize(
        "factory,code,http_status,retryable", SUPPORT_FACTORY_CASES
    )
    def test_factory_detail_override(self, factory, code, http_status, retryable):
        """1.1: 傳入 detail 時作為 message，但 code/status/retryable 不變。"""
        err = factory("custom detail")
        assert err.message == "custom detail"
        assert err.code == code
        assert err.http_status == http_status
        assert err.retryable is retryable

    @pytest.mark.parametrize(
        "factory,code,http_status,retryable", SUPPORT_FACTORY_CASES
    )
    def test_factory_default_message_nonempty(
        self, factory, code, http_status, retryable
    ):
        """1.1: 未傳 detail 時仍有非空的預設 message。"""
        err = factory()
        assert isinstance(err.message, str)
        assert err.message.strip() != ""


class TestErrorCodeRegistry:
    @pytest.mark.parametrize("code", REGISTERED_SUPPORT_CODES)
    def test_code_registered(self, code):
        """1.2: 每個 support code 都能在 _ERROR_CODE_FACTORIES 查得 factory。"""
        assert code in _ERROR_CODE_FACTORIES

    @pytest.mark.parametrize("code", REGISTERED_SUPPORT_CODES)
    def test_registered_factory_returns_same_code(self, code):
        """1.2: 註冊的 factory 產出的 APIError.code 與註冊鍵一致。"""
        factory = _ERROR_CODE_FACTORIES[code]
        assert factory().code == code

    @pytest.mark.parametrize("code", REGISTERED_SUPPORT_CODES)
    def test_error_from_status_resolves_specific_code(self, code):
        """1.2: _error_from_status 依 stored error_code 回傳具體 code，而非 JOB_FAILED。"""
        err = _error_from_status({"error_code": code, "error": "boom"})
        assert err.code == code

    def test_classifier_code_resolves_to_the_mismatch_factory(self):
        """8.1/8.2: the code the classifier emits must resolve end-to-end.

        Cross-checks the classifier constant against the registry rather than a
        hand-typed string, so renaming one side without the other is caught.
        """
        from agent.support_classifier import MODEL_MISMATCH_CODE

        err = _error_from_status({"error_code": MODEL_MISMATCH_CODE, "error": "boom"})
        assert err.code == MODEL_MISMATCH_CODE
        assert err.code != "JOB_FAILED"
        assert err.http_status == 422
        assert err.retryable is False

    def test_mismatch_response_body_reports_not_retryable(self):
        """8.1: the wire response the caller actually sees carries retryable=false."""
        import json

        from agent.support_classifier import MODEL_MISMATCH_CODE

        response = support_points_model_mismatch().to_response()
        assert response.status_code == 422
        body = json.loads(bytes(response.body))
        assert body["success"] is False
        assert body["code"] == MODEL_MISMATCH_CODE
        assert body["data"]["retryable"] is False

    def test_error_from_status_falls_back_when_code_unknown(self):
        """1.2: 未知/缺 error_code 時回退為 JOB_FAILED（向後相容）。"""
        assert _error_from_status({"error": "boom"}).code == "JOB_FAILED"
        assert (
            _error_from_status({"error_code": "NOPE", "error": "boom"}).code
            == "JOB_FAILED"
        )
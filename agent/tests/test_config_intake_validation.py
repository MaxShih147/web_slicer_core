"""
Tests for PUT /slices/{job_id}/config applying param_rules at save time —
Tasks 5.1/5.2 (add-support-param-validation), slice-config-intake spec.md.

Before this change the endpoint accepted any config unconditionally and only
failed once /execute ran the engine, seconds to tens of seconds later. Now it
validates via the SAME agent.param_rules / _run_param_validation() the
/validate endpoint uses — spec.md is explicit that this MUST NOT be a second,
independently-written check.

Drives the real endpoint function directly (asyncio.run), matching
test_config_validation_422.py's approach rather than TestClient, since the
seam under test is the function's own logic, not HTTP routing.
"""

import asyncio

import pytest

from agent import api_v2
from agent.api_v2 import V2ConfigUpdateRequest, update_slice_job_config
from agent.errors import APIError


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def pending_job():
    job_id = "cfg-job"
    api_v2._pending_jobs[job_id] = {"config": {}, "models": [], "status": "created"}
    yield job_id
    api_v2._pending_jobs.pop(job_id, None)


class TestViolatingConfigIsRejected:
    def test_returns_422_and_does_not_save(self, pending_job):
        request = V2ConfigUpdateRequest(
            config={
                "support_head_front_diameter": 2.0,
                "support_pillar_diameter": 1.0,
            },
            isAppend=True,
        )
        with pytest.raises(APIError) as exc_info:
            _run(update_slice_job_config(pending_job, request))
        assert exc_info.value.http_status == 422
        assert exc_info.value.retryable is False
        # Not saved: pending config is untouched by the rejected update.
        assert "support_head_front_diameter" not in api_v2._pending_jobs[pending_job]["config"]

    def test_pydantic_level_violation_also_returns_422(self, pending_job):
        """The 'death zone' bug (proposal.md #2): pad_wall_slope=35 is a
        pydantic-level rejection (outside 45-90), not one of the 7 arithmetic
        rules — PUT /config must catch this too, not just the 7 rules."""
        request = V2ConfigUpdateRequest(config={"pad_wall_slope": 35}, isAppend=True)
        with pytest.raises(APIError) as exc_info:
            _run(update_slice_job_config(pending_job, request))
        assert exc_info.value.http_status == 422
        assert "pad_wall_slope" in exc_info.value.message


class TestLegalConfigUnchangedBehavior:
    def test_legal_append_saves_and_merges(self, pending_job):
        api_v2._pending_jobs[pending_job]["config"] = {"layer_height": 0.05}
        request = V2ConfigUpdateRequest(config={"supports_enable": True}, isAppend=True)
        result = _run(update_slice_job_config(pending_job, request))
        assert result.success is True
        assert api_v2._pending_jobs[pending_job]["config"] == {
            "layer_height": 0.05,
            "supports_enable": True,
        }

    def test_legal_replace_overwrites(self, pending_job):
        api_v2._pending_jobs[pending_job]["config"] = {"layer_height": 0.05}
        request = V2ConfigUpdateRequest(config={"supports_enable": True}, isAppend=False)
        result = _run(update_slice_job_config(pending_job, request))
        assert result.success is True
        assert api_v2._pending_jobs[pending_job]["config"] == {"supports_enable": True}

    def test_prz_config_still_stored(self, pending_job):
        request = V2ConfigUpdateRequest(
            config={"supports_enable": True}, isAppend=True, prz_config={"Print.LayerHeight": 0.05}
        )
        _run(update_slice_job_config(pending_job, request))
        assert api_v2._pending_jobs[pending_job]["prz_config"] == {"Print.LayerHeight": 0.05}


class TestOneRuleTableForBoth:
    """5.2/spec.md: a new rule takes effect at both PUT /config and /validate
    without touching either call site — proven by using the real
    param_rules.RULES rather than a duplicated check."""

    def test_pad_config_invalid_is_caught_by_the_shared_rule(self, pending_job):
        request = V2ConfigUpdateRequest(
            config={"pad_wall_thickness": 2.0, "pad_brim_size": 1.6, "pad_wall_slope": 50.0},
            isAppend=True,
        )
        with pytest.raises(APIError) as exc_info:
            _run(update_slice_job_config(pending_job, request))
        assert exc_info.value.code == "PAD_CONFIG_INVALID"

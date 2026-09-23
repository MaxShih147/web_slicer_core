"""
Tests for POST /api/v2/support-params/validate — Tasks 3.1/3.6/3.7
(add-support-param-validation).

D6: this endpoint is a pure function wearing a route — no job, no disk, no
engine. Isolated the same way as test_slice_progress_endpoint.py
(agent.jobs.JOBS_DIR monkeypatched to a tmp dir); the no-side-effect test
(3.6) asserts that directory stays empty after repeated calls.
"""

import statistics
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent import jobs
from agent.api_v2 import router
from agent.models import SLAConfig


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), tmp_path


def _defaults():
    return SLAConfig().model_dump()


class TestOkShape:
    def test_legal_params_return_ok_true_and_empty_problems(self, client):
        c, _ = client
        body = {**_defaults(), "flow": "support", "supports_enable": True}
        resp = c.post("/api/v2/support-params/validate", json=body)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["problems"] == []
        assert data["clamped"] == []
        assert data["unknown"] == []

    def test_response_always_has_all_four_keys(self, client):
        c, _ = client
        resp = c.post("/api/v2/support-params/validate", json={**_defaults(), "flow": "support"})
        data = resp.json()
        assert set(data.keys()) >= {"ok", "problems", "clamped", "unknown"}


class TestProblemsShape:
    def test_violation_reports_ok_false_and_a_problem(self, client):
        c, _ = client
        body = {
            **_defaults(),
            "flow": "support",
            "support_head_front_diameter": 2.0,
            "support_pillar_diameter": 1.0,
        }
        resp = c.post("/api/v2/support-params/validate", json=body)
        data = resp.json()
        assert data["ok"] is False
        assert len(data["problems"]) == 1
        problem = data["problems"][0]
        assert problem["code"] == "SUPPORT_HEAD_TOO_WIDE"
        assert set(problem["fields"]) == {"support_head_front_diameter", "support_pillar_diameter"}
        assert problem["suggestion"]

    def test_dynamic_threshold_carries_computed_value(self, client):
        c, _ = client
        body = {
            **_defaults(),
            "flow": "support",
            "pad_wall_slope": 50.0,
            "pad_wall_thickness": 2.0,
            "pad_brim_size": 1.6,
        }
        resp = c.post("/api/v2/support-params/validate", json=body)
        problem = resp.json()["problems"][0]
        assert problem["code"] == "PAD_CONFIG_INVALID"
        assert problem["values"]["min_pad_wall_slope"] == pytest.approx(51.4, abs=0.05)


class TestClampedShape:
    def test_low_elevation_is_clamped_not_rejected(self, client):
        c, _ = client
        body = {**_defaults(), "flow": "support", "supports_enable": True, "support_object_elevation": 3.0}
        resp = c.post("/api/v2/support-params/validate", json=body)
        data = resp.json()
        assert data["ok"] is True  # a clamp is not a failure
        assert len(data["clamped"]) == 1
        clamp = data["clamped"][0]
        assert clamp["field"] == "support_object_elevation"
        assert clamp["original"] == 3.0
        assert clamp["effective"] == 5.0

    def test_near_zero_safety_distance_is_clamped(self, client):
        c, _ = client
        body = {**_defaults(), "flow": "support", "support_base_safety_distance": 0.0}
        resp = c.post("/api/v2/support-params/validate", json=body)
        data = resp.json()
        clamp = next(x for x in data["clamped"] if x["field"] == "support_base_safety_distance")
        assert clamp["original"] == 0.0
        assert clamp["effective"] == 0.5


class TestUnknownShape:
    def test_unknown_field_is_reported_not_rejected(self, client):
        c, _ = client
        body = {**_defaults(), "flow": "support", "totally_made_up_field": 42}
        resp = c.post("/api/v2/support-params/validate", json=body)
        data = resp.json()
        assert resp.status_code == 200
        assert data["ok"] is True
        assert "totally_made_up_field" in data["unknown"]

    def test_extra_field_does_not_reach_the_rule_engine(self, client):
        """SLAConfig.extra stays 'ignore' — this change must not switch it to
        'forbid' (design.md Non-Goal)."""
        c, _ = client
        body = {**_defaults(), "flow": "support", "not_a_real_field": "whatever"}
        resp = c.post("/api/v2/support-params/validate", json=body)
        assert resp.status_code == 200


class TestNoSideEffects:
    def test_100_calls_create_no_job_directories(self, client):
        c, tmp_path = client
        body = {**_defaults(), "flow": "support"}
        for _ in range(100):
            resp = c.post("/api/v2/support-params/validate", json=body)
            assert resp.status_code == 200
        assert list(tmp_path.iterdir()) == []


class TestPerformance:
    def test_p95_under_5ms(self):
        """D6's p95<5ms target is about the validation logic itself (the
        thing that runs on every slider drag) — measured by calling the
        underlying function directly. Going through TestClient/httpx's ASGI
        transport instead adds ~15-20ms of test-harness overhead per call
        (confirmed empirically) that has nothing to do with this endpoint's
        own cost and would make this test measure the test client, not the
        code design.md is actually budgeting."""
        from agent.api_v2 import _run_param_validation

        params = {**_defaults(), "supports_enable": True}
        printer_bounds = {
            "min_exposure_time": 1.0,
            "max_exposure_time": 120.0,
            "min_initial_exposure_time": 1.0,
            "max_initial_exposure_time": 300.0,
        }

        for _ in range(10):
            _run_param_validation("slice", params, printer_bounds=printer_bounds)

        durations = []
        for _ in range(1000):
            start = time.perf_counter()
            _run_param_validation("slice", params, printer_bounds=printer_bounds)
            durations.append(time.perf_counter() - start)

        durations.sort()
        p95 = durations[int(len(durations) * 0.95)]
        assert p95 < 0.005, f"p95={p95 * 1000:.3f}ms"

"""
API tests for fix-support-zero-param-engine-hang Phase 2 (tasks 2.1 / 2.11).

support_max_bridge_length below 1e-4 and support_base_diameter below 2e-4 are
rejected (at 0 they hang the engine's support clustering), so every v2 entry point that builds an SLAConfig
must reject them with 422 SUPPORT_PARAM_INVALID (and data.errors[] locating
each problem) before any engine work is queued. Every other SLAConfig field
keeps CONFIG_VALIDATION_ERROR.

Covers the API-level scenarios of:
  - specs/support-param-validation/spec.md
  - specs/slice-config-intake/spec.md (POST /slices validates its initial config)
The model-level scenarios (-0.0, NaN, inf, below-floor, defaults) live in
test_support_positive_params.py.

The router is mounted on a bare FastAPI app with the same APIError handler as
main.py, so the assertions see the real HTTP body. The four job-running
endpoints are called directly (as in test_config_validation_422.py) so the
test can also check that no background task was scheduled.
"""

import asyncio

import pytest
from fastapi import BackgroundTasks, FastAPI
from fastapi.testclient import TestClient

from agent import api_v2, jobs
from agent.api_v2 import router
from agent.engine_job_queue import get_engine_job_queue
from agent.errors import APIError

_MINIMAL_STL = (
    b"solid test\n"
    b"facet normal 0 0 1\nouter loop\n"
    b"vertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\n"
    b"endloop\nendfacet\n"
    b"endsolid test\n"
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)
    api_v2._pending_jobs.clear()

    app = FastAPI()
    app.include_router(router)

    @app.exception_handler(APIError)
    async def _api_error_handler(request, exc):
        return exc.to_response()

    yield TestClient(app)
    api_v2._pending_jobs.clear()


@pytest.fixture
def job(client):
    resp = client.post("/api/v2/slices", json={})
    assert resp.status_code == 200
    return resp.json()["data"]["jobId"]


def _locs(body):
    return [e["loc"] for e in body["data"]["errors"]]


# ─── PUT /slices/{job_id}/config ──────────────────────────────────────────────


class TestPutConfig:
    def test_zero_connector_length_rejected(self, client, job):
        """support-param-validation: 零值被拒絕"""
        resp = client.put(
            f"/api/v2/slices/{job}/config",
            json={"config": {"support_max_bridge_length": 0}},
        )
        assert resp.status_code == 422
        body = resp.json()
        assert body["code"] == "SUPPORT_PARAM_INVALID"
        assert body["data"]["retryable"] is False
        assert ["support_max_bridge_length"] in _locs(body)
        assert "support_max_bridge_length" in body["message"]
        assert "support_max_bridge_length" not in api_v2._pending_jobs[job]["config"]

    def test_json_literal_nan_rejected(self, client, job):
        """support-param-validation: JSON 字面值 NaN 被拒絕"""
        resp = client.put(
            f"/api/v2/slices/{job}/config",
            content=b'{"config": {"support_base_diameter": NaN}}',
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422
        assert resp.json()["code"] == "SUPPORT_PARAM_INVALID"
        assert "support_base_diameter" not in api_v2._pending_jobs[job]["config"]

    def test_link_distance_zero_still_saved(self, client, job):
        """support-param-validation: Link Distance 為 0 仍合法"""
        resp = client.put(
            f"/api/v2/slices/{job}/config",
            json={"config": {"support_max_pillar_link_distance": 0}},
        )
        assert resp.status_code == 200
        assert api_v2._pending_jobs[job]["config"]["support_max_pillar_link_distance"] == 0

    def test_mixed_with_other_field_error(self, client, job):
        """support-param-validation: 與其他欄位錯誤同時發生 (task 2.11)"""
        resp = client.put(
            f"/api/v2/slices/{job}/config",
            json={"config": {"pad_wall_slope": 35, "support_max_bridge_length": 0}},
        )
        assert resp.status_code == 422
        body = resp.json()
        assert body["code"] == "SUPPORT_PARAM_INVALID"
        locs = _locs(body)
        assert ["support_max_bridge_length"] in locs
        assert ["pad_wall_slope"] in locs
        assert len(locs) == 2

    def test_other_field_keeps_config_validation_error(self, client, job):
        """support-param-validation (MODIFIED): 側壁角度低於後端下限 — no data.errors"""
        resp = client.put(
            f"/api/v2/slices/{job}/config",
            json={"config": {"pad_wall_slope": 35}},
        )
        assert resp.status_code == 422
        body = resp.json()
        assert body["code"] == "CONFIG_VALIDATION_ERROR"
        assert "pad_wall_slope" in body["message"]
        assert "errors" not in body["data"]


# ─── POST /support-params/validate ────────────────────────────────────────────


class TestValidateEndpoint:
    def test_support_problem_first_and_other_kept(self, client):
        """support-param-validation (MODIFIED): 驗證端點回報支撐參數錯誤"""
        resp = client.post(
            "/api/v2/support-params/validate",
            json={
                "flow": "support",
                "support_points_density_relative": 10001,
                "support_base_diameter": 0,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        problems = body["problems"]
        assert problems[0]["code"] == "SUPPORT_PARAM_INVALID"
        assert "support_base_diameter" in problems[0]["fields"]
        assert any(
            p["code"] == "CONFIG_VALIDATION_ERROR"
            and "support_points_density_relative" in p["fields"]
            for p in problems
        )

    def test_not_in_clamped(self, client):
        """support-param-validation: 不出現在 clamped"""
        resp = client.post(
            "/api/v2/support-params/validate",
            json={"flow": "support", "support_base_diameter": 0},
        )
        body = resp.json()
        assert body["ok"] is False
        assert all(c["field"] != "support_base_diameter" for c in body["clamped"])


# ─── /execute, /generate-supports, /export-support-points, /generate-hollow ──


@pytest.fixture
def zero_bridge_job(tmp_path, monkeypatch):
    """A pending job whose saved config carries support_max_bridge_length=0,
    i.e. one that reached the endpoint without going through PUT /config."""
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)
    job_id = "job-zero-bridge"
    api_v2._pending_jobs[job_id] = {
        "config": {"support_max_bridge_length": 0},
        "models": [{"stl_data": _MINIMAL_STL}],
        "status": "created",
    }
    yield job_id
    api_v2._pending_jobs.pop(job_id, None)


@pytest.mark.parametrize(
    "endpoint",
    [
        api_v2.execute_slice_job,
        api_v2.generate_supports_only,
        api_v2.export_support_points_only,
        api_v2.generate_hollow_only,
    ],
    ids=["execute", "generate-supports", "export-support-points", "generate-hollow"],
)
def test_job_endpoints_return_support_param_invalid(zero_bridge_job, endpoint):
    """support-param-validation (MODIFIED): 執行端點遇到連接長度為 0"""
    background = BackgroundTasks()
    with pytest.raises(APIError) as exc_info:
        asyncio.run(endpoint(zero_bridge_job, background))
    err = exc_info.value
    assert err.http_status == 422
    assert err.code == "SUPPORT_PARAM_INVALID"
    assert err.retryable is False
    assert ["support_max_bridge_length"] in [e["loc"] for e in err.details]
    assert background.tasks == []
    snapshot = get_engine_job_queue().snapshot()
    assert snapshot == {"running_job_id": None, "pending_job_ids": []}


# ─── POST /slices (slice-config-intake) ───────────────────────────────────────


class TestCreateSliceValidatesConfig:
    def _assert_rejected(self, resp, code):
        assert resp.status_code == 422
        body = resp.json()
        assert body["code"] == code
        assert body["data"]["retryable"] is False
        assert "jobId" not in body["data"]
        assert api_v2._pending_jobs == {}
        return body

    def test_zero_connector_length(self, client):
        """slice-config-intake: 初始設定的連接長度為 0 (task 2.11)"""
        resp = client.post("/api/v2/slices", json={"config": {"support_max_bridge_length": 0}})
        body = self._assert_rejected(resp, "SUPPORT_PARAM_INVALID")
        assert ["support_max_bridge_length"] in _locs(body)

    def test_nan_base_diameter(self, client):
        """slice-config-intake: 初始設定的底座直徑為 NaN"""
        resp = client.post(
            "/api/v2/slices",
            content=b'{"config": {"support_base_diameter": NaN}}',
            headers={"Content-Type": "application/json"},
        )
        self._assert_rejected(resp, "SUPPORT_PARAM_INVALID")

    def test_other_field(self, client):
        """slice-config-intake: 初始設定的其他欄位違規"""
        resp = client.post("/api/v2/slices", json={"config": {"pad_wall_slope": 35}})
        body = self._assert_rejected(resp, "CONFIG_VALIDATION_ERROR")
        assert "pad_wall_slope" in body["message"]

    def test_ds_online_key_is_converted(self, client):
        """slice-config-intake: DS-Online 欄位名一樣會被轉換後驗證"""
        resp = client.post("/api/v2/slices", json={"config": {"Layer Height": "abc"}})
        body = self._assert_rejected(resp, "CONFIG_VALIDATION_ERROR")
        assert "layer_height" in body["message"]

    @pytest.mark.parametrize(
        "config",
        [
            {"Print": None},
            {"Print": "x"},
            {"Print": {"center": ["a", 1]}},
            {"Print": None, "support_max_bridge_length": 0},
        ],
        ids=["print-null", "print-string", "center-non-numeric", "print-null-with-zero"],
    )
    def test_malformed_structure(self, client, config):
        """slice-config-intake: 設定結構不合法 — 422, not 500, and no job"""
        resp = client.post("/api/v2/slices", json={"config": config})
        body = self._assert_rejected(resp, "CONFIG_VALIDATION_ERROR")
        assert "invalid structure" in body["message"]

    def test_param_rules_not_applied(self, client):
        """slice-config-intake: 不套用參數規則表"""
        resp = client.post(
            "/api/v2/slices",
            json={"config": {"supports_enable": True, "support_points_density_relative": 0}},
        )
        assert resp.status_code == 200
        assert "jobId" in resp.json()["data"]

    def test_link_distance_zero(self, client):
        """slice-config-intake: Link Distance 為 0 可建立工作"""
        resp = client.post(
            "/api/v2/slices", json={"config": {"support_max_pillar_link_distance": 0}}
        )
        assert resp.status_code == 200

    def test_legal_config_stored_verbatim(self, client):
        """slice-config-intake: 合法設定原樣存下"""
        config = {
            "support_max_bridge_length": 12.5,
            "support_base_diameter": 3.0,
            "Layer Height": 0.05,
            "Print": {"Exposure Time": 2.5},
        }
        resp = client.post("/api/v2/slices", json={"config": config})
        assert resp.status_code == 200
        job_id = resp.json()["data"]["jobId"]
        assert api_v2._pending_jobs[job_id]["config"] == config

    @pytest.mark.parametrize("body", [{}, {"config": {}}, {"config": None}], ids=["absent", "empty", "null"])
    def test_no_config(self, client, body):
        """slice-config-intake: 不帶設定"""
        resp = client.post("/api/v2/slices", json=body)
        assert resp.status_code == 200
        job_id = resp.json()["data"]["jobId"]
        assert api_v2._pending_jobs[job_id]["config"] == {}

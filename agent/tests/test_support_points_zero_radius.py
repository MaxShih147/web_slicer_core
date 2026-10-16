"""
POST /slices/{job_id}/support-points rejecting a zero base_radius_mm —
fix-support-zero-param-engine-hang Phase 2 (task 2.7), covering every scenario
of specs/support-point-api/spec.md.

A point's base_radius_mm of 0 hangs the engine's support clustering the same
way a global Base Diameter of 0 does. The engine reads the value as a float
(single precision) and treats `v >= 0` as "this point has its own size", so
the rejected range is `0 <= v < 1e-4` (the floor taken at float precision,
9.999999747e-05, so a radius the engine exported can be sent back): it catches
0, -0.0 and tiny positives that collapse to 0.0f, while negatives (= "follow
the global setting") and a missing key keep passing. NaN also passes this check, but not because the
engine treats it as unset: a NaN literal is not valid JSON to the engine, which
rejects the whole file and fails the job (no hang).

The router is mounted on a bare FastAPI app with main.py's APIError handler,
and the body is posted as raw bytes so the byte-for-byte storage promise can
be checked.
"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent import api_v2, jobs
from agent.api_v2 import router
from agent.errors import APIError


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
    return resp.json()["data"]["jobId"]


def _point(base_radius_mm=None):
    p = {"pos": [1.0, 2.0, 3.0], "type": "manual_add"}
    if base_radius_mm is not None:
        p["base_radius_mm"] = base_radius_mm
    return p


def _body(points) -> bytes:
    return json.dumps({"version": 1, "points": points}).encode()


def _post(client, job, raw: bytes):
    return client.post(
        f"/api/v2/slices/{job}/support-points",
        content=raw,
        headers={"Content-Type": "application/json"},
    )


def _assert_rejected(resp, indexes):
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "SUPPORT_POINT_PARAM_INVALID"
    assert body["data"]["retryable"] is False
    assert [e["loc"] for e in body["data"]["errors"]] == [
        ["points", i, "base_radius_mm"] for i in indexes
    ]
    for i in indexes[:10]:
        assert f"points[{i}].base_radius_mm" in body["message"]
    return body


class TestRejected:
    def test_single_zero_point(self, client, job):
        """support-point-api: 單點底座半徑為 0"""
        resp = _post(client, job, _body([_point(2.0), _point(0), _point(2.0)]))
        _assert_rejected(resp, [1])
        assert "support_points" not in api_v2._pending_jobs[job]

    def test_negative_zero(self, client, job):
        """support-point-api: 負零被拒絕"""
        resp = _post(client, job, _body([_point(-0.0)]))
        _assert_rejected(resp, [0])

    def test_tiny_positive(self, client, job):
        """support-point-api: 極小正數被拒絕"""
        resp = _post(client, job, _body([_point(1e-50)]))
        _assert_rejected(resp, [0])

    def test_all_bad_points_reported(self, client, job):
        """support-point-api: 一次回報所有不合法的點"""
        points = [_point(0), _point(2.0), _point(), _point(-1), _point(0)]
        resp = _post(client, job, _body(points))
        _assert_rejected(resp, [0, 4])

    def test_message_capped_at_ten_points(self, client, job):
        """support-point-api: 超過 10 點時訊息只列前 10 點"""
        resp = _post(client, job, _body([_point(0) for _ in range(15)]))
        body = _assert_rejected(resp, list(range(15)))  # data.errors keeps all 15
        message = body["message"]
        assert "points[9].base_radius_mm" in message
        assert "points[10]" not in message
        assert "and 5 more" in message
        assert message.count("follow the global base diameter") == 1

    def test_rejection_keeps_previous_list(self, client, job):
        """support-point-api: 被拒絕時不覆蓋先前的清單"""
        raw_a = _body([_point(2.0)])
        assert _post(client, job, raw_a).status_code == 200
        resp = _post(client, job, _body([_point(0)]))
        assert resp.status_code == 422
        assert api_v2._pending_jobs[job]["support_points"] == raw_a


class TestThreshold:
    @pytest.mark.parametrize(
        "value, accepted", [(0.00009, False), (0.0001, True)], ids=["0.00009", "0.0001"]
    )
    def test_threshold_boundary(self, client, job, value, accepted):
        """support-point-api: 門檻邊界"""
        resp = _post(client, job, _body([_point(value)]))
        if accepted:
            assert resp.status_code == 200
        else:
            _assert_rejected(resp, [0])

    @pytest.mark.parametrize(
        "radius",
        [0.5 * 2e-4, 9.999999747378752e-05],
        ids=["first-export-double", "later-export-float"],
    )
    def test_engine_exported_radius_round_trips(self, client, job, radius):
        """support-point-api: 引擎匯出的半徑送回可通過

        At the global Base Diameter floor (2e-4) the engine exports a radius of
        0.5 * 2e-4 = 1e-4 at double precision the first time, and the same
        radius held as a float (9.999999747378752e-05) on every export after a
        list was imported. Both must be accepted when sent back.
        """
        assert _post(client, job, _body([_point(radius)])).status_code == 200

    def test_just_below_the_float_floor_is_rejected(self, client, job):
        """support-point-api: 門檻邊界 (the float floor is the real edge)"""
        resp = _post(client, job, _body([_point(9.9999e-05)]))
        _assert_rejected(resp, [0])


class TestAccepted:
    def test_negative_means_global(self, client, job):
        """support-point-api: 負數代表沿用全域"""
        resp = _post(client, job, _body([_point(-1), _point(-0.00005)]))
        assert resp.status_code == 200

    def test_missing_key_means_global(self, client, job):
        """support-point-api: 缺欄位代表沿用全域"""
        resp = _post(client, job, _body([_point(), _point()]))
        assert resp.status_code == 200

    def test_legal_positive(self, client, job):
        """support-point-api: 合法正值"""
        resp = _post(client, job, _body([_point(2.0), _point(2.0)]))
        assert resp.status_code == 200

    def test_nan_not_checked_here(self, client, job):
        """support-point-api requirement: NaN SHALL 被接受（本檢查不處理；引擎讀檔時
        判定為無效 JSON、工作失敗，不會卡死）"""
        raw = b'{"version":1,"points":[{"pos":[1,2,3],"type":"manual_add","base_radius_mm":NaN}]}'
        assert _post(client, job, raw).status_code == 200

    @pytest.mark.parametrize(
        "raw",
        [
            b'{"version":1,"points":[{"pos":[1,2,3],"base_radius_mm":false}]}',
            b'{"version":1,"points":[{"pos":[1,2,3],"base_radius_mm":"0"}]}',
            b'{"version":1,"points":[0]}',
        ],
        ids=["bool", "string", "non-object"],
    )
    def test_out_of_scope_shapes_unchanged(self, client, job, raw):
        """support-point-api requirement: 非物件或非數值的點本需求不檢查"""
        assert _post(client, job, raw).status_code == 200

    def test_stored_verbatim(self, client, job):
        """support-point-api: 通過時原樣存下"""
        raw = b'{ "points" : [ {"base_radius_mm": 2.50, "type":"manual_add", "pos":[1,2,3]} ],\n "version":1 }'
        assert _post(client, job, raw).status_code == 200
        assert api_v2._pending_jobs[job]["support_points"] == raw

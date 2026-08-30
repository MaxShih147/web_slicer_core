"""
API contract tests for the support point endpoints — openspec change
per-point-support-sizing, tasks 7.4 and 7.5.

Two promises are pinned here:

  - GET returns the engine's file VERBATIM. Parsing and re-serializing it would
    be enough to move a float in its last digit, and the fingerprint travelling
    with the list is what decides whether the caller's edits are still valid.
  - POST stores what the caller sent, untouched. A size key the caller left out
    means "fall back to the global setting at build time"; filling one in here
    would freeze a value they never chose.

The router is mounted on a bare FastAPI app and JOBS_DIR is redirected to a tmp
directory, so nothing here touches the real job store or the slicer binary.
"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent import api_v2, jobs
from agent.api_v2 import router
from agent.errors import APIError
from agent.sla_operations import support_points_input_path, support_points_output_path


# Deliberately irregular whitespace and a float with a long tail: if anything
# in the read path re-encodes this, the bytes will not survive.
RAW_EXPORT = (
    b'{"version":1,\n  "model_fingerprint":{"face_count":1908,'
    b'"bbox_min":[-125000,-125000,70000],"bbox_max":[125000,125000,370000],'
    b'"vertex_checksum":"1a205a2be3f13857"},\n'
    b'"points":[{"pos":[9.171710968017578,5.848729133605957,7.0],'
    b'"type":"island","head_front_radius":0.30000001192092896,'
    b'"head_back_radius_mm":0.5,"head_width_mm":1.0,"head_penetration_mm":0.3,'
    b'"contact_sphere_radius":0.0,"base_radius_mm":2.0,'
    b'"support_bracing_angle_deg":45.0}]}'
)

def _one_triangle_stl() -> bytes:
    """A minimal but genuinely valid binary STL.

    The upload endpoints run trimesh over the bytes and reject a mesh with no
    faces, so a "solid ... endsolid" stub is not enough here.
    """
    import struct

    body = struct.pack("<12fH", 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0)
    return bytes(80) + struct.pack("<I", 1) + body


MINIMAL_BODY = {"version": 1, "points": [{"pos": [1.0, 2.0, 3.0], "type": "manual_add"}]}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)
    api_v2._pending_jobs.clear()

    app = FastAPI()
    app.include_router(router)

    # The real app registers this in main.py. Without it an APIError escapes as
    # an exception instead of becoming the HTTP response the caller would see,
    # and every "is this rejected?" assertion below would be meaningless.
    @app.exception_handler(APIError)
    async def _api_error_handler(request, exc):
        return exc.to_response()

    yield TestClient(app)
    api_v2._pending_jobs.clear()


def _executed_job(job_id="done-job"):
    """A job that already ran, with an exported point list on disk."""
    d = jobs.JOBS_DIR / job_id
    (d / "output").mkdir(parents=True, exist_ok=True)
    support_points_output_path(d).write_bytes(RAW_EXPORT)
    return job_id


def _pending_job(client, config=None):
    resp = client.post("/api/v2/slices", json={"config": config or {}})
    assert resp.status_code == 200
    return resp.json()["data"]["jobId"]


# --------------------------------------------------------------------------
# 7.4 — reading the engine's list back out
# --------------------------------------------------------------------------

class TestGetSupportPoints:
    def test_returns_the_file_byte_for_byte(self, client):
        job = _executed_job()

        resp = client.get(f"/api/v2/slices/{job}/support-points")

        assert resp.status_code == 200
        assert resp.content == RAW_EXPORT
        assert resp.headers["content-type"].startswith("application/json")

    def test_the_fingerprint_and_sizes_survive_unchanged(self, client):
        job = _executed_job()

        body = client.get(f"/api/v2/slices/{job}/support-points").json()
        original = json.loads(RAW_EXPORT)

        assert body["model_fingerprint"] == original["model_fingerprint"]
        assert body["points"] == original["points"]
        # And the contract the engine promises: every size is a concrete,
        # non-negative value, never the -1 sentinel.
        for point in body["points"]:
            for key, value in point.items():
                if key != "pos" and isinstance(value, (int, float)):
                    assert value >= 0

    def test_unknown_job_is_404(self, client):
        resp = client.get("/api/v2/slices/nope/support-points")
        assert resp.status_code == 404

    def test_job_without_an_export_is_404(self, client):
        job = "empty-job"
        (jobs.JOBS_DIR / job / "output").mkdir(parents=True)

        resp = client.get(f"/api/v2/slices/{job}/support-points")

        assert resp.status_code == 404


# --------------------------------------------------------------------------
# 7.5 — supplying a custom list
# --------------------------------------------------------------------------

class TestSetSupportPoints:
    def test_body_is_accepted_and_counted(self, client):
        job = _pending_job(client)

        resp = client.post(f"/api/v2/slices/{job}/support-points", json=MINIMAL_BODY)

        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["data"]["points"] == 1

    def test_nothing_is_added_to_the_stored_body(self, client):
        """The heart of the contract: a point given as pos + type must reach the
        engine as pos + type. Any key added here is read as a frozen value the
        caller deliberately chose."""
        job = _pending_job(client)
        client.post(f"/api/v2/slices/{job}/support-points", json=MINIMAL_BODY)

        stored = json.loads(api_v2._pending_jobs[job]["support_points"])

        assert set(stored["points"][0]) == {"pos", "type"}

    def test_malformed_json_is_rejected(self, client):
        job = _pending_job(client)

        resp = client.post(
            f"/api/v2/slices/{job}/support-points",
            content=b"{not json",
            headers={"content-type": "application/json"},
        )

        assert resp.status_code >= 400

    def test_a_body_without_points_is_rejected(self, client):
        job = _pending_job(client)

        resp = client.post(f"/api/v2/slices/{job}/support-points", json={"version": 1})

        assert resp.status_code >= 400

    def test_empty_body_is_rejected(self, client):
        job = _pending_job(client)

        resp = client.post(
            f"/api/v2/slices/{job}/support-points",
            content=b"",
            headers={"content-type": "application/json"},
        )

        assert resp.status_code >= 400


class TestMutualExclusionWithAnUploadedMesh:
    """The engine refuses --import-support-points together with
    --import-support-stl. Caught at the API so the caller hears about it before
    a job runs, and in both orders."""

    def _upload_stl(self, client, job):
        return client.post(
            f"/api/v2/slices/{job}/upload-support",
            files={"file": ("s.stl", _one_triangle_stl(), "application/octet-stream")},
        )

    def test_list_after_mesh_is_rejected(self, client):
        job = _pending_job(client)
        assert self._upload_stl(client, job).status_code == 200

        resp = client.post(f"/api/v2/slices/{job}/support-points", json=MINIMAL_BODY)

        assert resp.status_code >= 400

    def test_mesh_after_list_is_rejected(self, client):
        job = _pending_job(client)
        assert client.post(
            f"/api/v2/slices/{job}/support-points", json=MINIMAL_BODY
        ).status_code == 200

        resp = self._upload_stl(client, job)

        assert resp.status_code >= 400


# --------------------------------------------------------------------------
# The list has to survive all the way to disk, in input/
# --------------------------------------------------------------------------

class TestLandingOnExecute:
    def _add_model(self, client, job):
        stl = _one_triangle_stl()
        return client.post(
            f"/api/v2/slices/{job}/upload",
            files={"file": ("m.stl", stl, "application/octet-stream")},
        )

    def test_execute_lands_the_list_in_input(self, client, monkeypatch):
        job = _pending_job(client)
        self._add_model(client, job)
        client.post(f"/api/v2/slices/{job}/support-points", json=MINIMAL_BODY)

        # Never actually slice.
        async def noop(*args, **kwargs):
            return None

        monkeypatch.setattr(api_v2, "run_slicing", noop)

        resp = client.post(f"/api/v2/slices/{job}/execute")
        assert resp.status_code == 200

        landed = support_points_input_path(jobs.get_job_dir(job))
        assert landed.exists()
        assert landed.parent.name == "input"
        assert set(json.loads(landed.read_text())["points"][0]) == {"pos", "type"}

    def test_generate_supports_lands_the_list_in_input(self, client, monkeypatch):
        job = _pending_job(client)
        self._add_model(client, job)
        client.post(f"/api/v2/slices/{job}/support-points", json=MINIMAL_BODY)

        async def noop(*args, **kwargs):
            return None

        monkeypatch.setattr(api_v2, "run_support_generation", noop)

        resp = client.post(f"/api/v2/slices/{job}/generate-supports")
        assert resp.status_code == 200

        assert support_points_input_path(jobs.get_job_dir(job)).exists()

    def test_no_list_leaves_the_input_directory_alone(self, client, monkeypatch):
        """The existing path must be untouched when the interface is unused."""
        job = _pending_job(client)
        self._add_model(client, job)

        async def noop(*args, **kwargs):
            return None

        monkeypatch.setattr(api_v2, "run_slicing", noop)
        client.post(f"/api/v2/slices/{job}/execute")

        assert not support_points_input_path(jobs.get_job_dir(job)).exists()


class TestExportEndpoint:
    def test_forces_supports_on_in_the_config_it_hands_over(self, client, monkeypatch):
        """Even when the caller explicitly disabled supports: with them off the
        engine skips the support point step and writes an empty list."""
        job = _pending_job(client, config={"supports_enable": False})
        client.post(
            f"/api/v2/slices/{job}/upload",
            files={"file": ("m.stl", _one_triangle_stl(), "application/octet-stream")},
        )

        seen = {}

        async def capture(job_id, config=None):
            seen["config"] = config

        monkeypatch.setattr(api_v2, "run_support_points_export", capture)

        resp = client.post(f"/api/v2/slices/{job}/export-support-points")

        assert resp.status_code == 200
        assert resp.json()["data"]["currentConfig"]["supports_enable"] is True

        # The echoed config is not the one the engine gets. Assert the object
        # actually handed to the runner, which is what decides whether the
        # support point step runs at all.
        assert "config" in seen, "the background task never ran"
        assert seen["config"].supports_enable is True

    def test_unknown_job_is_404(self, client):
        resp = client.post("/api/v2/slices/nope/export-support-points")
        assert resp.status_code == 404


class TestJobIdIsValidated:
    """A job id is a server generated token, so anything else is a probe.

    Backslash is the one that matters: it is not a URL path separator, so
    "..%5Csecret" reaches the handler as a single path segment - and Windows
    then reads it as a directory separator, putting JOBS_DIR / job_id outside
    the job store entirely.
    """

    def test_backslash_traversal_is_refused(self, client, tmp_path):
        outside = tmp_path.parent / "outside" / "output"
        outside.mkdir(parents=True, exist_ok=True)
        (outside / "support_points.json").write_bytes(b'{"SECRET":"leaked"}')

        resp = client.get("/api/v2/slices/..%5Coutside/support-points")

        assert resp.status_code == 404
        assert b"SECRET" not in resp.content

    def test_other_shapes_are_refused(self, client):
        for probe in ["..", ".", "a.b", "a%5Cb", "a b"]:
            resp = client.get(f"/api/v2/slices/{probe}/support-points")
            assert resp.status_code == 404, probe

    def test_a_normal_job_id_still_works(self, client):
        job = _executed_job("abc-123_XYZ")

        resp = client.get(f"/api/v2/slices/{job}/support-points")

        assert resp.status_code == 200
        assert resp.content == RAW_EXPORT


class TestPointsTypeIsValidated:
    """A malformed body is a 400, never a 500."""

    @pytest.mark.parametrize("points", [5, "abc", {"a": 1}, None, True])
    def test_a_non_list_points_is_a_client_error(self, client, points):
        job = _pending_job(client)

        resp = client.post(
            f"/api/v2/slices/{job}/support-points",
            json={"version": 1, "points": points},
        )

        assert 400 <= resp.status_code < 500, f"{points!r} gave {resp.status_code}"

    def test_a_non_object_body_is_a_client_error(self, client):
        job = _pending_job(client)

        resp = client.post(f"/api/v2/slices/{job}/support-points", json=[1, 2, 3])

        assert 400 <= resp.status_code < 500

    def test_an_empty_points_array_is_accepted(self, client):
        """Zero points is a legitimate answer - "this model needs none"."""
        job = _pending_job(client)

        resp = client.post(
            f"/api/v2/slices/{job}/support-points",
            json={"version": 1, "points": []},
        )

        assert resp.status_code == 200
        assert resp.json()["data"]["points"] == 0

"""
End-to-end verification of the support error-code pipeline — Task 8.1
(add-support-generation-error-codes).

Exercises the whole Job-layer path (run_support_generation → generate_supports →
real/stubbed CLI → classify_support_result → write_job_status) and, for the
neutral outcome, the GET status endpoint via TestClient, across the four
scenarios the design calls out:

  1. self-supporting model               → SUPPORT_NOT_NEEDED, hasSupportMesh False
  2. pad_enable=True zero-support model   → SUPPORT_NOT_NEEDED, hasSupportMesh False
  3. pinhead diameter too wide            → FAILED + SUPPORT_HEAD_TOO_WIDE
  4. model that needs supports            → COMPLETED + hasSupportMesh True

Scenarios 3 & 4 run the REAL slicer engine on trimesh-generated STL fixtures
(skipped when the engine binary isn't built). A pad run is also exercised on the
real engine to cover the "(includes supports and pad)" marker.

Scenarios 1 & 2 (zero support pillars) cannot be produced by the real engine
from a closed solid: SLAConfig.enforce_min_elevation forces a >=5mm elevation,
so a solid's bottom face is always an overhang the engine supports. They are
therefore driven through the identical pipeline with the CLI subprocess stubbed
to emit the exact "No support/pad mesh generated" / "(pad only)" markers — the
same literals Task 7's contract test pins against the real fork source — so the
classify → persist → API path is fully real.
"""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent import jobs
from agent import sla_operations
from agent.api_v2 import router
from agent.config import SLICER_ENGINE_CLI
from agent.models import JobStatus, SLAConfig

trimesh = pytest.importorskip("trimesh")

_ENGINE_AVAILABLE = SLICER_ENGINE_CLI.is_file()
_needs_engine = pytest.mark.skipif(
    not _ENGINE_AVAILABLE, reason=f"slicer engine binary not built: {SLICER_ENGINE_CLI}"
)


def _make_job_dir(root, job_id):
    jd = root / job_id
    (jd / "input").mkdir(parents=True)
    (jd / "output").mkdir()
    return jd


def _export_box(path, size=10):
    m = trimesh.creation.box(extents=[size, size, size])
    m.apply_translation([0, 0, size / 2])
    m.export(str(path))


def _export_sphere(path, radius=8, lift=20):
    """A sphere floated above the bed — a reliable 'needs supports' fixture."""
    m = trimesh.creation.icosphere(subdivisions=3, radius=radius)
    m.apply_translation([0, 0, lift])
    m.export(str(path))


def _run(job_id, config):
    asyncio.run(jobs.run_support_generation(job_id, config))
    return jobs.read_job_status(job_id)


def _stub_cli(monkeypatch, *, stdout=b"", stderr=b"", returncode=0):
    async def fake(cmd, stderr_file=None, stdout_file=None):
        if stdout_file:
            with open(stdout_file, "wb") as f:
                f.write(stdout)
        if stderr_file:
            with open(stderr_file, "wb") as f:
                f.write(stderr)
        return returncode, stdout, stderr

    monkeypatch.setattr(sla_operations, "run_prusa_cli", fake)


# ── Scenarios 1 & 2: neutral zero-support outcomes (full pipeline, stubbed CLI) ──


class TestNeutralOutcomes:
    def test_self_supporting_reports_not_needed(self, tmp_path, monkeypatch):
        """Scenario 1: no pad, zero support pillars → COMPLETED + SUPPORT_NOT_NEEDED."""
        monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)
        _make_job_dir(tmp_path, "self-support")
        _stub_cli(monkeypatch, stdout=b"Slicing done\nNo support/pad mesh generated\n")

        data = _run("self-support", SLAConfig(supports_enable=True, pad_enable=False))

        assert data["status"] == JobStatus.COMPLETED.value
        assert data["support_outcome"] == "SUPPORT_NOT_NEEDED"
        assert data["has_support_mesh"] is False
        assert data["error_code"] is None

    def test_pad_only_zero_support_reports_not_needed(self, tmp_path, monkeypatch):
        """Scenario 2: pad_enable=True but zero support pillars → SUPPORT_NOT_NEEDED,
        NOT reported as a real support mesh, and surfaces as success via the API."""
        monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)
        _make_job_dir(tmp_path, "pad-only")
        _stub_cli(
            monkeypatch,
            stdout=b"Generating pad\nSupport mesh exported to model_support.stl (pad only)\n",
        )

        data = _run("pad-only", SLAConfig(supports_enable=True, pad_enable=True))

        assert data["status"] == JobStatus.COMPLETED.value
        assert data["support_outcome"] == "SUPPORT_NOT_NEEDED"
        assert data["has_support_mesh"] is False

        # And the GET status endpoint surfaces it as success (not an error path).
        app = FastAPI()
        app.include_router(router)
        body = TestClient(app).get("/api/v2/slices/pad-only").json()
        assert body["success"] is True
        assert body["data"]["supportOutcome"] == "SUPPORT_NOT_NEEDED"
        assert body["data"]["hasSupportMesh"] is False


# ── Scenarios 3 & 4: real engine on generated STL fixtures ─────────────────────


@_needs_engine
class TestRealEngine:
    def test_pinhead_too_wide_fails_with_specific_code(self, tmp_path, monkeypatch):
        """Scenario 3: front diameter >= pillar diameter → real validate() failure
        classified as SUPPORT_HEAD_TOO_WIDE (survives the exit-0 bug)."""
        monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)
        jd = _make_job_dir(tmp_path, "pinhead")
        _export_sphere(jd / "input" / "model.stl")

        data = _run(
            "pinhead",
            SLAConfig(
                supports_enable=True,
                support_head_front_diameter=1.2,
                support_pillar_diameter=1.0,
            ),
        )

        assert data["status"] == JobStatus.FAILED.value
        assert data["error_code"] == "SUPPORT_HEAD_TOO_WIDE"

        # API surfaces the specific code with success:false.
        app = FastAPI()
        app.include_router(router)
        body = TestClient(app).get("/api/v2/slices/pinhead").json()
        assert body["success"] is False
        assert body["code"] == "SUPPORT_HEAD_TOO_WIDE"

    def test_model_needing_supports_succeeds_with_mesh(self, tmp_path, monkeypatch):
        """Scenario 4: an overhanging model → real supports generated → COMPLETED
        with has_support_mesh True and no neutral outcome."""
        monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)
        jd = _make_job_dir(tmp_path, "needs-support")
        _export_sphere(jd / "input" / "model.stl")

        data = _run("needs-support", SLAConfig(supports_enable=True, pad_enable=False))

        assert data["status"] == JobStatus.COMPLETED.value
        assert data["has_support_mesh"] is True
        assert data["error_code"] is None
        assert data["support_outcome"] is None
        # the real STL landed on disk
        assert (jd / "output" / "model_support.stl").exists()

    def test_pad_model_succeeds_with_supports_and_pad(self, tmp_path, monkeypatch):
        """Real engine with pad_enable on a support-needing model → the
        '(includes supports and pad)' marker → COMPLETED + has_support_mesh."""
        monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)
        jd = _make_job_dir(tmp_path, "supports-and-pad")
        _export_sphere(jd / "input" / "model.stl")

        data = _run("supports-and-pad", SLAConfig(supports_enable=True, pad_enable=True))

        assert data["status"] == JobStatus.COMPLETED.value
        assert data["has_support_mesh"] is True
        assert data["support_outcome"] is None
        stdout_log = (jd / "stdout_support.log").read_text(errors="replace")
        assert "(includes supports and pad)" in stdout_log
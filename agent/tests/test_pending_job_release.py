"""agent-large-model-perf, spec pending-job-memory (design D3, D4).

* After generate-supports / export-support-points / generate-hollow / cut
  land the model as input/model.stl, the pending job stops holding its bytes
  and later calls on the same job reuse that file.
* An idle pending job's bytes move to a spool file; the job stays usable.
* Neither marker can be forged through add_models_to_slice_job().

Calls api_v2's endpoint functions directly (see test_save_model_to_job_validation).
BackgroundTasks() only records tasks, so no engine ever runs.
"""

import asyncio
import io
import shutil
import uuid
from pathlib import Path

import pytest
import trimesh
from fastapi import BackgroundTasks, UploadFile
from fastapi.responses import Response

from agent import api_v2
from agent.api_v2 import V2CutRequest, V2ModelsAddRequest
from agent.errors import APIError
from agent.jobs import get_job_dir


def _stl() -> bytes:
    return trimesh.creation.box(extents=[2, 2, 2]).export(file_type="stl")


@pytest.fixture()
def spool_dir(tmp_path, monkeypatch):
    d = tmp_path / ".pending_spool"
    monkeypatch.setattr(api_v2, "PENDING_SPOOL_DIR", d)
    return d


@pytest.fixture()
def job(spool_dir):
    created = asyncio.run(api_v2.create_slice_job(api_v2.V2SliceCreateRequest()))
    jid = created.data["jobId"]
    yield jid
    api_v2._pending_jobs.pop(jid, None)
    shutil.rmtree(get_job_dir(jid), ignore_errors=True)


def _upload(jid, content=None):
    content = _stl() if content is None else content
    upload = UploadFile(filename="model.stl", file=io.BytesIO(content))
    asyncio.run(api_v2.upload_model_file(jid, upload))
    return content


def _input(jid) -> Path:
    return get_job_dir(jid) / "input" / "model.stl"


def _generate_supports(jid):
    return asyncio.run(api_v2.generate_supports_only(jid, BackgroundTasks()))


def _execute(jid):
    return asyncio.run(api_v2.execute_slice_job(jid, BackgroundTasks(), Response()))


def _api_error(call) -> APIError:
    with pytest.raises(APIError) as excinfo:
        call()
    return excinfo.value


class TestReleaseAfterLanding:
    def test_generate_supports_drops_the_bytes_and_points_at_the_file(self, job):
        _upload(job)
        _generate_supports(job)
        [model] = api_v2._pending_jobs[job]["models"]
        assert "stl_data" not in model
        assert isinstance(model["landed"], api_v2._LandedModel)
        assert model["landed"].path == _input(job)
        assert model["id"] == "file_0" and model["filename"] == "model.stl"

    def test_execute_after_generate_supports_slices_the_uploaded_bytes(self, job):
        content = _upload(job)
        _generate_supports(job)
        result = _execute(job)
        assert result.success
        assert _input(job).read_bytes() == content
        assert job not in api_v2._pending_jobs

    def test_generate_supports_twice_reuses_the_landed_file(self, job):
        content = _upload(job)
        _generate_supports(job)
        mtime = _input(job).stat().st_mtime_ns
        assert _generate_supports(job).success
        assert _input(job).read_bytes() == content
        assert _input(job).stat().st_mtime_ns == mtime  # not rewritten

    @pytest.mark.parametrize(
        "call",
        [
            lambda jid: api_v2.export_support_points_only(jid, BackgroundTasks()),
            lambda jid: api_v2.generate_hollow_only(jid, BackgroundTasks()),
            lambda jid: api_v2.cut_model(jid, V2CutRequest(cut_height=1.0), BackgroundTasks()),
        ],
        ids=["export-support-points", "generate-hollow", "cut"],
    )
    def test_other_keep_pending_endpoints_release_too(self, job, call):
        content = _upload(job)
        asyncio.run(call(job))
        [model] = api_v2._pending_jobs[job]["models"]
        assert "stl_data" not in model
        assert _execute(job).success
        assert _input(job).read_bytes() == content

    def test_failed_save_keeps_the_bytes(self, job):
        bad = b"not an stl"
        asyncio.run(api_v2.add_models_to_slice_job(job, V2ModelsAddRequest(models=[{"stl_data": bad}])))
        assert _api_error(lambda: _generate_supports(job)).code == "INVALID_MODEL"
        assert api_v2._pending_jobs[job]["models"][0]["stl_data"] == bad

    def test_missing_landed_file_is_model_not_found(self, job):
        _upload(job)
        _generate_supports(job)
        _input(job).unlink()
        assert _api_error(lambda: _execute(job)).code == "MODEL_NOT_FOUND"

    def test_landed_copy_to_another_path(self, job, tmp_path):
        content = _upload(job)
        _generate_supports(job)
        target = tmp_path / "elsewhere.stl"
        api_v2._save_model_to_job(api_v2._pending_jobs[job]["models"][0], target)
        assert target.read_bytes() == content

    def test_use_model_from_still_validates_and_then_releases(self, job, monkeypatch):
        source = f"test_src_{uuid.uuid4().hex}"
        out = get_job_dir(source) / "output"
        out.mkdir(parents=True)
        content = _stl()
        (out / "boolean.stl").write_bytes(content)
        calls = []
        real = api_v2._validate_stl_bytes
        monkeypatch.setattr(api_v2, "_validate_stl_bytes", lambda c, f="model": calls.append(f) or real(c, f))
        try:
            asyncio.run(api_v2.use_model_from_job(job, source, "boolean.stl"))
            model = api_v2._pending_jobs[job]["models"][0]
            assert model["validated"] is False and model["stl_data"] == content
            _generate_supports(job)
            assert calls == ["model"]
            assert "stl_data" not in api_v2._pending_jobs[job]["models"][0]
            assert _input(job).read_bytes() == content
        finally:
            shutil.rmtree(get_job_dir(source), ignore_errors=True)


class TestMarkersCannotBeForged:
    def test_landed_key_from_a_request_body_is_ignored(self, job, tmp_path):
        secret = tmp_path / "secret.txt"
        secret.write_text("do not copy")
        forged = {"landed": {"path": str(secret)}, "spooled": str(secret)}
        asyncio.run(api_v2.add_models_to_slice_job(job, V2ModelsAddRequest(models=[forged])))
        error = _api_error(lambda: _generate_supports(job))
        assert error.code != "MODEL_NOT_FOUND"
        assert not _input(job).exists() or _input(job).read_bytes() != secret.read_bytes()

    def test_forged_marker_next_to_real_bytes_uses_the_bytes(self, job, tmp_path):
        secret = tmp_path / "secret.stl"
        secret.write_bytes(_stl() + b"x")
        content = _stl()
        model = {"stl_data": content, "landed": {"path": str(secret)}}
        asyncio.run(api_v2.add_models_to_slice_job(job, V2ModelsAddRequest(models=[model])))
        _generate_supports(job)
        assert _input(job).read_bytes() == content


class TestIdleSpool:
    def _age(self, jid, seconds):
        api_v2._pending_jobs[jid]["last_access"] -= seconds

    def test_idle_job_moves_to_spool_and_still_slices(self, job, spool_dir):
        content = _upload(job)
        self._age(job, 601)
        assert asyncio.run(api_v2._spool_idle_pending_jobs()) == 1
        model = api_v2._pending_jobs[job]["models"][0]
        assert "stl_data" not in model
        spool_file = spool_dir / f"{job}.stl"
        assert spool_file.read_bytes() == content
        assert model["validated"] is True

        assert _execute(job).success
        assert _input(job).read_bytes() == content
        assert not spool_file.exists()

    def test_status_of_a_spooled_job_is_unchanged(self, job):
        _upload(job)
        before = asyncio.run(api_v2.get_slice_job_status(job, Response())).data
        self._age(job, 601)
        asyncio.run(api_v2._spool_idle_pending_jobs())
        after = asyncio.run(api_v2.get_slice_job_status(job, Response())).data
        assert after == before
        assert after["modelCount"] == 1

    def test_recently_used_job_is_left_alone(self, job, spool_dir):
        _upload(job)
        self._age(job, 599)
        assert asyncio.run(api_v2._spool_idle_pending_jobs()) == 0
        assert "stl_data" in api_v2._pending_jobs[job]["models"][0]

    def test_access_resets_the_idle_clock(self, job):
        _upload(job)
        self._age(job, 601)
        asyncio.run(api_v2.get_slice_job_status(job, Response()))
        assert asyncio.run(api_v2._spool_idle_pending_jobs()) == 0

    def test_entry_without_last_access_starts_its_clock(self, spool_dir):
        jid = f"test_spool_{uuid.uuid4().hex}"
        api_v2._pending_jobs[jid] = {"config": {}, "status": "created", "models": [{"stl_data": _stl()}]}
        try:
            assert asyncio.run(api_v2._spool_idle_pending_jobs()) == 0
            assert "last_access" in api_v2._pending_jobs[jid]
        finally:
            api_v2._pending_jobs.pop(jid, None)

    def test_unvalidated_spooled_content_is_validated_on_landing(self, job):
        asyncio.run(api_v2.add_models_to_slice_job(job, V2ModelsAddRequest(models=[{"stl_data": b"junk" * 100}])))
        self._age(job, 601)
        assert asyncio.run(api_v2._spool_idle_pending_jobs()) == 1
        assert _api_error(lambda: _generate_supports(job)).code == "INVALID_MODEL"

    def test_write_failure_keeps_the_bytes(self, job, monkeypatch, caplog):
        _upload(job)
        self._age(job, 601)

        def disk_full(path, data):
            raise OSError("No space left on device")

        monkeypatch.setattr(api_v2, "_write_spool_file", disk_full)
        assert asyncio.run(api_v2._spool_idle_pending_jobs()) == 0
        assert "stl_data" in api_v2._pending_jobs[job]["models"][0]
        assert "No space left" in caplog.text

    def test_job_touched_while_writing_is_not_replaced(self, job, spool_dir, monkeypatch):
        _upload(job)
        self._age(job, 601)
        real_write = api_v2._write_spool_file

        def write_then_touch(path, data):
            real_write(path, data)
            api_v2._touch_pending(job)

        monkeypatch.setattr(api_v2, "_write_spool_file", write_then_touch)
        assert asyncio.run(api_v2._spool_idle_pending_jobs()) == 0
        assert "stl_data" in api_v2._pending_jobs[job]["models"][0]
        assert not (spool_dir / f"{job}.stl").exists()

    def test_job_executed_while_writing_leaves_no_spool(self, job, spool_dir, monkeypatch):
        _upload(job)
        self._age(job, 601)
        real_write = api_v2._write_spool_file

        def write_then_remove(path, data):
            real_write(path, data)
            api_v2._pending_jobs.pop(job)

        monkeypatch.setattr(api_v2, "_write_spool_file", write_then_remove)
        assert asyncio.run(api_v2._spool_idle_pending_jobs()) == 0
        assert not (spool_dir / f"{job}.stl").exists()

    def test_startup_clears_leftover_spool_files(self, spool_dir):
        spool_dir.mkdir(parents=True)
        (spool_dir / "old_job.stl").write_bytes(b"x")
        api_v2.clear_pending_spool()
        assert list(spool_dir.iterdir()) == []

    @pytest.mark.parametrize(
        "raw, expected",
        [(None, 600.0), ("30", 30.0), ("abc", 600.0), ("0", 600.0), ("-5", 600.0)],
    )
    def test_idle_threshold_env(self, monkeypatch, raw, expected):
        if raw is None:
            monkeypatch.delenv("AGENT_PENDING_SPOOL_IDLE_SEC", raising=False)
        else:
            monkeypatch.setenv("AGENT_PENDING_SPOOL_IDLE_SEC", raw)
        assert api_v2._spool_idle_seconds() == expected

    def test_loop_survives_a_failing_scan(self, monkeypatch):
        scans = []

        async def failing_scan(now=None):
            scans.append(1)
            raise RuntimeError("scan broke")

        sleeps = []

        async def fake_sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) > 3:
                raise asyncio.CancelledError

        monkeypatch.setattr(api_v2, "_spool_idle_pending_jobs", failing_scan)
        monkeypatch.setattr(api_v2.asyncio, "sleep", fake_sleep)
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(api_v2.pending_job_spool_loop())
        assert len(scans) == 3

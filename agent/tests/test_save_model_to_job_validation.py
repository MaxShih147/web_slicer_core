"""
Tests for D5 (optimize-auto-process-performance): upload/save duplicate STL
validation dedup.

Covers the "validated" provenance flag on pending["models"] items:
  - upload_model_file() sets validated=True, and _save_model_to_job() skips
    the second full trimesh.load() parse for that item
  - use_model_from_job() never sets validated=True; _save_model_to_job()
    still fully validates it (and still rejects invalid/corrupt content)
  - a validated flag that is missing, False, or any non-True value still
    triggers full validation (fail-safe default)
  - add_models_to_slice_job() accepts an arbitrary client-supplied dict; a
    client that injects "validated": True into its own model body MUST NOT
    be able to skip validation

Follows this repo's existing pattern (see test_prz_download_fallback.py) of
calling api_v2's module-level functions directly instead of going through
fastapi.testclient.TestClient, since httpx is not installed in this venv.
"""
import asyncio
import io
import shutil
import uuid

import pytest
import trimesh
from fastapi import UploadFile

from agent import api_v2
from agent.api_v2 import V2ModelsAddRequest
from agent.errors import APIError
from agent.jobs import get_job_dir


def _valid_stl_bytes() -> bytes:
    mesh = trimesh.creation.box(extents=[2, 2, 2])
    return mesh.export(file_type="stl")


def _spy_on_validate(monkeypatch):
    """Wrap api_v2._validate_stl_bytes with a call-counting spy that still
    delegates to the real implementation, so behavior is unaffected."""
    calls = []
    original = api_v2._validate_stl_bytes

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(api_v2, "_validate_stl_bytes", spy)
    return calls


@pytest.fixture()
def job_id():
    jid = f"test_d5_{uuid.uuid4().hex}"
    api_v2._pending_jobs[jid] = {"config": {}, "models": [], "status": "created"}
    yield jid
    api_v2._pending_jobs.pop(jid, None)


class TestUploadModelFileSetsValidatedFlag:
    def test_validated_true_after_upload(self, job_id):
        content = _valid_stl_bytes()
        upload = UploadFile(filename="model.stl", file=io.BytesIO(content))
        asyncio.run(api_v2.upload_model_file(job_id, upload))
        model_data = api_v2._pending_jobs[job_id]["models"][0]
        assert model_data["validated"] is True

    def test_save_skips_second_parse_for_validated_item(self, job_id, monkeypatch, tmp_path):
        content = _valid_stl_bytes()
        upload = UploadFile(filename="model.stl", file=io.BytesIO(content))
        asyncio.run(api_v2.upload_model_file(job_id, upload))
        model_data = api_v2._pending_jobs[job_id]["models"][0]

        calls = _spy_on_validate(monkeypatch)  # patched only after upload's own validate call
        out_path = tmp_path / "model.stl"
        api_v2._save_model_to_job(model_data, out_path)

        assert calls == []
        assert out_path.read_bytes() == content


class TestUseModelFromJobStillValidates:
    def test_appends_without_validated_true(self, job_id):
        source_job_id = f"test_d5_src_{uuid.uuid4().hex}"
        source_dir = get_job_dir(source_job_id)
        (source_dir / "output").mkdir(parents=True, exist_ok=True)
        content = _valid_stl_bytes()
        (source_dir / "output" / "boolean.stl").write_bytes(content)
        try:
            asyncio.run(api_v2.use_model_from_job(job_id, source_job_id, "boolean.stl"))
            model_data = api_v2._pending_jobs[job_id]["models"][0]
            assert model_data.get("validated") is not True
            assert model_data["stl_data"] == content
        finally:
            shutil.rmtree(source_dir, ignore_errors=True)

    def test_save_still_fully_validates_referenced_content(self, job_id, tmp_path, monkeypatch):
        source_job_id = f"test_d5_src_{uuid.uuid4().hex}"
        source_dir = get_job_dir(source_job_id)
        (source_dir / "output").mkdir(parents=True, exist_ok=True)
        content = _valid_stl_bytes()
        (source_dir / "output" / "boolean.stl").write_bytes(content)
        try:
            asyncio.run(api_v2.use_model_from_job(job_id, source_job_id, "boolean.stl"))
            model_data = api_v2._pending_jobs[job_id]["models"][0]

            calls = _spy_on_validate(monkeypatch)
            api_v2._save_model_to_job(model_data, tmp_path / "model.stl")
            assert len(calls) == 1
        finally:
            shutil.rmtree(source_dir, ignore_errors=True)

    def test_save_still_rejects_corrupt_referenced_content(self, job_id, tmp_path):
        source_job_id = f"test_d5_src_{uuid.uuid4().hex}"
        source_dir = get_job_dir(source_job_id)
        (source_dir / "output").mkdir(parents=True, exist_ok=True)
        (source_dir / "output" / "boolean.stl").write_bytes(b"not a real stl")
        try:
            asyncio.run(api_v2.use_model_from_job(job_id, source_job_id, "boolean.stl"))
            model_data = api_v2._pending_jobs[job_id]["models"][0]

            with pytest.raises(APIError) as excinfo:
                api_v2._save_model_to_job(model_data, tmp_path / "model.stl")
            assert excinfo.value.code == "INVALID_MODEL"
        finally:
            shutil.rmtree(source_dir, ignore_errors=True)


class TestMissingOrFalseFlagStillValidates:
    def test_missing_flag_triggers_validation(self, tmp_path, monkeypatch):
        content = _valid_stl_bytes()
        model_data = {"id": "m0", "stl_data": content}  # no "validated" key at all
        calls = _spy_on_validate(monkeypatch)
        api_v2._save_model_to_job(model_data, tmp_path / "model.stl")
        assert len(calls) == 1

    def test_explicit_false_flag_triggers_validation(self, tmp_path, monkeypatch):
        content = _valid_stl_bytes()
        model_data = {"id": "m0", "stl_data": content, "validated": False}
        calls = _spy_on_validate(monkeypatch)
        api_v2._save_model_to_job(model_data, tmp_path / "model.stl")
        assert len(calls) == 1

    def test_non_bool_truthy_flag_still_validates(self, tmp_path, monkeypatch):
        """Defense in depth: only a literal True skips validation."""
        content = _valid_stl_bytes()
        model_data = {"id": "m0", "stl_data": content, "validated": "yes"}
        calls = _spy_on_validate(monkeypatch)
        api_v2._save_model_to_job(model_data, tmp_path / "model.stl")
        assert len(calls) == 1


class TestAddModelsToSliceJobCannotBypassValidation:
    def test_client_supplied_validated_true_is_overridden_to_false(self, job_id):
        request = V2ModelsAddRequest(models=[{"vertices": [[0, 0, 0]], "validated": True}])
        asyncio.run(api_v2.add_models_to_slice_job(job_id, request))
        model_data = api_v2._pending_jobs[job_id]["models"][0]
        assert model_data["validated"] is False

    def test_client_supplied_validated_true_does_not_skip_save_validation(self, job_id, tmp_path):
        """A client smuggling "validated": True with fabricated stl_data must
        still fail closed: production dict-merge order in
        add_models_to_slice_job() forces "validated": False after the
        client-controlled spread, regardless of what the client sent."""
        request = V2ModelsAddRequest(models=[{"stl_data": "not-real-bytes", "validated": True}])
        asyncio.run(api_v2.add_models_to_slice_job(job_id, request))
        model_data = api_v2._pending_jobs[job_id]["models"][0]

        with pytest.raises(APIError) as excinfo:
            api_v2._save_model_to_job(model_data, tmp_path / "model.stl")
        assert excinfo.value.code == "INVALID_MODEL"

    def test_save_fully_validates_normal_add_models_item(self, job_id, tmp_path, monkeypatch):
        content = _valid_stl_bytes()
        request = V2ModelsAddRequest(models=[{"stl_data": content}])
        asyncio.run(api_v2.add_models_to_slice_job(job_id, request))
        model_data = api_v2._pending_jobs[job_id]["models"][0]
        assert model_data["validated"] is False

        calls = _spy_on_validate(monkeypatch)
        api_v2._save_model_to_job(model_data, tmp_path / "model.stl")
        assert len(calls) == 1

"""download.prz encode timing (add-slice-pipeline-profiling, task 1.6).

StreamingResponse sends its headers before encoding starts, so the encode time
cannot ride on download.prz itself. With SLICE_PROFILING=1 the encoder stream
is wrapped: from the first pull to the end of the stream is recorded as the
prz-encode span (and persisted to profile.json); a later GET /slices/{id}
carries it in Server-Timing. Without the flag the stream is not wrapped.
"""
import asyncio
import json
import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent import api_v2, jobs, prz_encoder, profiling
from agent.api_v2 import router
from agent.models import JobStatus

JOB = "job-prz"
CHUNKS = [b"HEADER", b"LAYER-0", b"LAYER-1", b"FOOTER"]
ENCODE_SLEEP_S = 0.05


@pytest.fixture(autouse=True)
def _reset_profiling():
    profiling.reset_for_tests()
    yield
    profiling.reset_for_tests()


@pytest.fixture
def encoder_threads():
    return []


@pytest.fixture
def client(tmp_path, monkeypatch, encoder_threads):
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)

    def fake_encoder(**kwargs):
        encoder_threads.append(threading.get_ident())
        time.sleep(ENCODE_SLEEP_S)
        yield from CHUNKS

    monkeypatch.setattr(prz_encoder, "encode_prz_streaming", fake_encoder)
    monkeypatch.setattr(api_v2, "_extract_prz_timing_config", lambda config: None)
    monkeypatch.setattr(api_v2, "_inject_retract_overrides", lambda config: None)

    job_dir = jobs.create_job(JOB)
    (job_dir / "output" / "model.sl1").write_bytes(b"")
    jobs.write_job_status(JOB, JobStatus.COMPLETED, layer_count=2)

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture
def flag(monkeypatch):
    def set_flag(on: bool):
        if on:
            monkeypatch.setenv("SLICE_PROFILING", "1")
        else:
            monkeypatch.delenv("SLICE_PROFILING", raising=False)

    return set_flag


def _download(client):
    return client.post(f"/api/v2/slices/{JOB}/download.prz", json={"Print": {}})


def _entries(header: str) -> dict:
    return {
        part.split(";dur=")[0]: float(part.split(";dur=")[1])
        for part in header.split(", ")
    }


def test_download_header_has_no_prz_encode_but_status_does(client, flag):
    flag(True)

    resp = _download(client)

    assert resp.status_code == 200
    assert resp.content == b"".join(CHUNKS)
    assert "prz-encode" not in resp.headers.get("server-timing", "")

    status = client.get(f"/api/v2/slices/{JOB}")
    entries = _entries(status.headers["server-timing"])
    assert entries["prz-encode"] >= ENCODE_SLEEP_S * 1000 * 0.9


def test_prz_encode_is_written_to_profile_json(client, flag):
    flag(True)

    _download(client)

    data = json.loads((jobs.get_job_dir(JOB) / "profile.json").read_text())
    assert data["spans"]["prz-encode"] > 0


def test_encoder_still_runs_off_the_event_loop_thread(client, flag, encoder_threads):
    flag(True)
    _download(client)
    assert encoder_threads and encoder_threads[0] != threading.get_ident()


def test_flag_off_same_bytes_and_nothing_recorded(client, flag):
    flag(False)

    resp = _download(client)

    assert resp.content == b"".join(CHUNKS)
    assert "server-timing" not in resp.headers
    assert not (jobs.get_job_dir(JOB) / "profile.json").exists()
    flag(True)  # peek at the raw store
    assert profiling.snapshot(JOB) is None


# --- the wrapper itself -------------------------------------------------------


def _collect(agen, limit=None):
    async def run():
        out = []
        async for chunk in agen:
            out.append(chunk)
            if limit is not None and len(out) >= limit:
                await agen.aclose()
                break
        return out

    return asyncio.run(run())


def test_wrapper_passes_chunks_through_unchanged(flag, tmp_path):
    flag(True)
    out = _collect(api_v2._timed_prz_stream(JOB, tmp_path, iter(CHUNKS)))
    assert out == CHUNKS
    assert profiling.snapshot(JOB)["spans"]["prz-encode"] >= 0.0


def test_abandoned_stream_records_no_prz_encode(flag, tmp_path):
    """A client that disconnects mid-download did not measure a full encode."""
    flag(True)
    _collect(api_v2._timed_prz_stream(JOB, tmp_path, iter(CHUNKS)), limit=1)
    snap = profiling.snapshot(JOB)
    assert snap is None or "prz-encode" not in snap["spans"]
    assert not (tmp_path / "profile.json").exists()


def test_failing_encoder_records_nothing_and_still_raises(flag, tmp_path):
    flag(True)

    def broken():
        yield b"HEADER"
        raise RuntimeError("encode failed")

    with pytest.raises(RuntimeError):
        _collect(api_v2._timed_prz_stream(JOB, tmp_path, broken()))
    snap = profiling.snapshot(JOB)
    assert snap is None or "prz-encode" not in snap["spans"]


def test_profiling_error_does_not_break_the_stream(flag, tmp_path, monkeypatch):
    flag(True)

    def boom(*args, **kwargs):
        raise RuntimeError("profiling bug")

    monkeypatch.setattr(profiling, "add_span", boom)
    monkeypatch.setattr(profiling, "write_profile_json", boom)

    assert _collect(api_v2._timed_prz_stream(JOB, tmp_path, iter(CHUNKS))) == CHUNKS

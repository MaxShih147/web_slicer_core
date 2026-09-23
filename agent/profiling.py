"""Side-channel timing for the slice pipeline (add-slice-pipeline-profiling).

Measurement only: nothing here may change how a job runs. Every public
function is a no-op unless ``SLICE_PROFILING=1`` is set, and none of them
raise on bad input — a profiling failure must never break a slice.

Records are kept in memory, keyed by ``job_id``:

* ``marks``  — named ``time.perf_counter()`` points (seconds).
* ``spans``  — named durations in milliseconds; the same name accumulates.
* ``stages`` — engine ``STAGE_*`` switch sequence ``[(stage, t), ...]``,
  appended only when the stage changes.

Consumers read them back as a ``Server-Timing`` header value
(``name;dur=<ms>, ...``) or as ``job_dir/profile.json``.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ENV_FLAG = "SLICE_PROFILING"
PROFILE_FILENAME = "profile.json"

_lock = threading.Lock()
_records: dict[str, dict[str, Any]] = {}


def is_enabled() -> bool:
    """Read on every call so tests and restarts pick up the env var."""
    return os.environ.get(ENV_FLAG) == "1"


def _record(job_id: str) -> dict[str, Any]:
    # Caller holds _lock.
    rec = _records.get(job_id)
    if rec is None:
        rec = {"marks": {}, "spans": {}, "stages": []}
        _records[job_id] = rec
    return rec


def mark(job_id: str, name: str, t: float | None = None) -> None:
    """Record a named point; ``t`` defaults to ``time.perf_counter()``."""
    if not is_enabled():
        return
    if t is None:
        t = time.perf_counter()
    with _lock:
        _record(job_id)["marks"][name] = t


def add_span(job_id: str, name: str, dur_ms: float) -> None:
    """Add ``dur_ms`` to the span ``name`` (accumulates on repeat)."""
    if not is_enabled():
        return
    with _lock:
        spans = _record(job_id)["spans"]
        spans[name] = spans.get(name, 0.0) + float(dur_ms)


def measure(job_id: str, name: str, start_mark: str, end_mark: str) -> None:
    """Add the span ``end_mark - start_mark``; skipped if either mark is missing."""
    if not is_enabled():
        return
    with _lock:
        rec = _records.get(job_id)
        if rec is None:
            return
        start = rec["marks"].get(start_mark)
        end = rec["marks"].get(end_mark)
    if start is None or end is None:
        return
    add_span(job_id, name, (end - start) * 1000.0)


def record_stage(job_id: str, stage: str, t: float | None = None) -> None:
    """Append ``(stage, t)`` only when ``stage`` differs from the last one."""
    if not is_enabled():
        return
    if t is None:
        t = time.perf_counter()
    with _lock:
        stages = _record(job_id)["stages"]
        if stages and stages[-1][0] == stage:
            return
        stages.append([stage, t])


def stage_durations(job_id: str) -> dict[str, float]:
    """Milliseconds per stage, summed by name.

    A stage lasts until the next switch. The last stage has no successor and
    gets no duration; stages the engine never emitted are absent, not zero.
    """
    if not is_enabled():
        return {}
    with _lock:
        rec = _records.get(job_id)
        stages = [tuple(s) for s in rec["stages"]] if rec else []
    out: dict[str, float] = {}
    for (stage, t0), (_next, t1) in zip(stages, stages[1:]):
        out[stage] = out.get(stage, 0.0) + (t1 - t0) * 1000.0
    return out


def snapshot(job_id: str) -> dict[str, Any] | None:
    """Copy of the raw record, or ``None`` when disabled / unknown job."""
    if not is_enabled():
        return None
    with _lock:
        rec = _records.get(job_id)
        if rec is None:
            return None
        return {
            "marks": dict(rec["marks"]),
            "spans": dict(rec["spans"]),
            "stages": [list(s) for s in rec["stages"]],
        }


def server_timing(job_id: str, extra: Mapping[str, float] | None = None) -> str:
    """``Server-Timing`` value: spans, then ``stage-<STAGE_*>``, then ``extra``.

    Returns ``""`` when disabled or there is nothing to report, so callers can
    skip setting the header.
    """
    if not is_enabled():
        return ""
    entries: list[tuple[str, float]] = []
    snap = snapshot(job_id)
    if snap is not None:
        entries.extend(snap["spans"].items())
        entries.extend((f"stage-{s}", d) for s, d in stage_durations(job_id).items())
    if extra:
        entries.extend(extra.items())
    return ", ".join(f"{name};dur={float(ms):.1f}" for name, ms in entries)


def write_profile_json(job_id: str, job_dir: str | os.PathLike[str]) -> Path | None:
    """Write (or overwrite) ``job_dir/profile.json``; returns its path.

    Returns ``None`` without writing when disabled, the job is unknown, or the
    write fails. Never raises.
    """
    snap = snapshot(job_id)
    if snap is None:
        return None
    data = {
        "job_id": job_id,
        **snap,
        "stage_durations_ms": stage_durations(job_id),
    }
    path = Path(job_dir) / PROFILE_FILENAME
    tmp = path.with_name(PROFILE_FILENAME + ".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        logger.debug("profile.json write failed for job %s", job_id, exc_info=True)
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return None
    return path


def clear(job_id: str) -> None:
    with _lock:
        _records.pop(job_id, None)


def reset_for_tests() -> None:
    with _lock:
        _records.clear()

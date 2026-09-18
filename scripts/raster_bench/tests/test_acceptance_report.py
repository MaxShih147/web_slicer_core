"""acceptance_report.py: thresholds, rerun rounds, identity, fingerprints, curve and PRZ.

Every test builds a synthetic work directory under tmp_path: fake engine
binaries with their build_info.json, Golden runs, and Phase 3 run directories
holding only the files the report reads (meta.json, timing.json, fingerprints).
The numbers follow the Scenarios of the raster-performance-baseline spec.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import acceptance_report as ar

BASE_ENGINE, FINAL_ENGINE = "base-5bc83b08f", "final-22f2e310a"
PRIMARY, SECONDARY, FULLPLATE, TINY = (
    "primary-16k-guide-x8", "secondary-8k-guide-x3", "fullplate-16k-slab", "tiny-16k-crown-x1")
LAYERS = b"model00000.rle  " + b"a" * 64 + b"\n"
PREVIEW = b"model_preview00000.png  " + b"b" * 64 + b"\n"
TIME_A, TIME_B = b"2026-09-17 10:00:00", b"2026-09-17 10:05:42"


# ── synthetic work directory ──────────────────────────────────────────────────

class Work:
    def __init__(self, root: Path):
        self.root = root
        self.runs = root / "runs"
        self.runs.mkdir(parents=True)
        self.identity = {role: self._engine(name, name.encode())
                         for role, name in (("base", BASE_ENGINE), ("final", FINAL_ENGINE))}
        for case in (PRIMARY, SECONDARY, FULLPLATE, TINY):
            self._write_run(f"windows-base-{case}-tdefault-r1",
                            {"schema_version": 1, "platform": "windows", "build": "base", "case": case},
                            {"rasterizing_wall_s": 22.58, "peak_pagefile_usage_bytes": 8_400_000_000,
                             "peak_working_set_bytes": 1_510_000_000})

    def _engine(self, name: str, tag: bytes) -> dict:
        engine_dir = self.root / "engines" / name
        engine_dir.mkdir(parents=True)
        files = {}
        for filename in ar.ENGINE_FILES.values():
            data = tag + b":" + filename.encode()
            (engine_dir / filename).write_bytes(data)
            files[filename] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
        (engine_dir / "build_info.json").write_text(
            json.dumps({"fork": {"commit": name}, "build": {"files": files}}), encoding="utf-8")
        return {key: files[filename]["sha256"] for key, filename in ar.ENGINE_FILES.items()}

    def _write_run(self, run_id: str, meta: dict, timing: dict, layers=LAYERS, preview=PREVIEW) -> Path:
        run_dir = self.runs / run_id
        run_dir.mkdir()
        (run_dir / "layers.sha256").write_bytes(layers)
        (run_dir / "preview.sha256").write_bytes(preview)
        (run_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        (run_dir / "timing.json").write_text(json.dumps(timing), encoding="utf-8")
        return run_dir

    def run(self, role, round_no, case, repeat, raster, committed=1000, rss=100, threads_requested=None,
            threads=8, env=None, variant=None, schema=2, engine=None, preview=PREVIEW) -> Path:
        effective = threads if threads_requested is None else min(threads, threads_requested)
        label = "t" + (str(threads_requested) if threads_requested is not None else "default")
        suffix = f"-{variant}" if variant else ""
        meta = {
            "schema_version": schema, "platform": "windows", "build": f"p3-{role}-a{round_no}", "case": case,
            "repeat": repeat, "threads": effective, "threads_requested": threads_requested,
            "threads_source": "GetProcessAffinityMask", "env": {"SLA_LAYER_RLE": "1", **(env or {})},
            "variant": {"label": variant}, "engine": dict(engine or self.identity[role]),
        }
        timing = {"rasterizing_wall_s": raster, "peak_pagefile_usage_bytes": committed,
                  "peak_working_set_bytes": rss}
        return self._write_run(f"windows-p3-{role}-a{round_no}-{case}{suffix}-{label}-r{repeat}", meta, timing,
                               preview=preview)

    def round(self, case, round_no, base_times, final_times, base_mem=(8000, 1500), final_mem=(2200, 1500),
              **kwargs):
        """Interleaved base/final repeats 1..3 of one round."""
        for repeat in (1, 2, 3):
            self.run("base", round_no, case, repeat, base_times[repeat - 1], *base_mem, **kwargs)
            self.run("final", round_no, case, repeat, final_times[repeat - 1], *final_mem, **kwargs)

    def passing_gates(self, skip=()):
        steady_base, steady_final = [30.0, 30.2, 30.4], [14.6, 14.8, 14.9]
        for case in (PRIMARY, SECONDARY, FULLPLATE):
            if case not in skip:
                self.round(case, 1, steady_base, steady_final)
        for repeat in (1, 2, 3):
            self.run("final", 1, TINY, repeat, 5.0)

    def passing_curve(self):
        for role in ("base", "final"):
            for threads in (1, 2, 4):
                for repeat in (1, 2, 3):
                    self.run(role, 1, PRIMARY, repeat, 40.0 / threads, threads_requested=threads)

    def prz(self, base: bytes, final: bytes):
        (self.root / "prz").mkdir(exist_ok=True)
        (self.root / "prz" / "base.prz").write_bytes(base)
        (self.root / "prz" / "final.prz").write_bytes(final)

    def judge(self, *sections) -> tuple[int, dict]:
        argv = ["--work", str(self.root), "--out", str(self.root / "out")]
        for section in sections:
            argv += ["--section", section]
        code = ar.main(argv)
        return code, json.loads((self.root / "out" / "summary.json").read_text(encoding="utf-8"))


def prz_bytes(size=4096, time=TIME_A, padding=b"\0" * 5) -> bytearray:
    data = bytearray(size)
    data[:4] = b"V3.0"
    data[68:87] = time
    data[87:92] = padding
    for offset in range(92, size):
        data[offset] = offset % 251
    return data


@pytest.fixture
def work(tmp_path) -> Work:
    return Work(tmp_path / "work")


def gate(summary, case):
    return summary["gates"][case]


def check(summary, case, metric):
    return next(c for c in gate(summary, case)["checks"] if c["metric"] == metric)


# ── rules (pure) ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("limit, base, final, expected", [
    (50, 30.0, 14.8, ar.PASS),         # spec: primary meets the speed gate
    (50, 30.0, 15.5, ar.FAIL),         # spec: primary misses the speed gate
    (50, 30.0, 15.0, ar.PASS),         # exactly 50%
    (50, 21.00, 10.80, ar.FAIL),       # 51.4%
    (100, 8000, 8000, ar.PASS),        # committed memory equal to base
    (100, 8000, 8010, ar.FAIL),        # spec: committed memory above base
    (103, 1500, 1545, ar.PASS),        # RSS exactly 103%, no float rounding
    (103, 1500, 1546, ar.FAIL),
    (103, 1500, 1560, ar.FAIL),        # spec: RSS above the guard
    (103, 40.0, 41.5, ar.FAIL),        # spec: full plate slower than 103%
    (103, 2.18, 2.2454, ar.PASS),      # exactly 103% of a short float time
    (103, 2.18, 2.2455, ar.FAIL),
])
def test_threshold_boundaries(limit, base, final, expected):
    assert ar.judge_threshold("m", limit, base, final)["result"] == expected


@pytest.mark.parametrize("times, expected", [
    ([14.0, 14.5, 15.4], True),    # spec: 1.4 s spread over 5% of 14.5 and over 0.5 s
    ([2.08, 2.18, 2.20], False),   # spec: over 5% but only 0.12 s
    ([22.0, 22.4, 23.6], True),    # spec: one-sided rerun example
    ([10.0, 10.2, 10.5], False),   # 0.5 s is not more than 0.5 s
    ([20.0, 20.5, 21.01], False),  # over 0.5 s but under 5% of 20.5
])
def test_rerun_rule_needs_both_limits(times, expected):
    assert ar.triggers_rerun(times) is expected


def test_group_stats_median_min_max_spread():
    assert ar.group_stats([30.4, 30.0, 30.2]) == {
        "values": [30.4, 30.0, 30.2], "median": 30.2, "min": 30.0, "max": 30.4, "spread": pytest.approx(0.4)}
    assert ar.group_stats([1500, 1440, 1462])["spread"] == 60


def test_worst_status_order():
    assert ar.worst(ar.PASS, ar.INCOMPLETE) == ar.INCOMPLETE
    assert ar.worst(ar.INCOMPLETE, ar.UNSTABLE) == ar.UNSTABLE
    assert ar.worst(ar.UNSTABLE, ar.FAIL, ar.PASS) == ar.FAIL


# ── gates ─────────────────────────────────────────────────────────────────────

def test_everything_passing_exits_zero_and_writes_both_files(work):
    work.passing_gates()
    work.passing_curve()
    work.prz(bytes(prz_bytes(time=TIME_A)), bytes(prz_bytes(time=TIME_B)))
    code, summary = work.judge()

    assert code == 0 and summary["verdict"] == ar.PASS
    assert {case: g["status"] for case, g in summary["gates"].items()} == dict.fromkeys(ar.GATES, ar.PASS)
    assert summary["record_only"][TINY]["status"] == ar.PASS
    assert summary["curve"]["status"] == ar.PASS and summary["prz"]["result"] == ar.PASS
    assert summary["problems"] == []
    assert (work.root / "out" / "report.md").is_file()


def test_spec_primary_passes_with_memory_gates(work):
    work.passing_gates(skip=(PRIMARY,))
    work.round(PRIMARY, 1, [30.0, 30.0, 30.0], [14.8, 14.8, 14.8], base_mem=(8000, 1500), final_mem=(2200, 1540))
    code, summary = work.judge("gates")

    assert code == 0
    assert [(c["metric"], c["result"]) for c in gate(summary, PRIMARY)["checks"]] == [
        ("rasterizing_wall_s", ar.PASS), ("peak_pagefile_usage_bytes", ar.PASS), ("peak_working_set_bytes", ar.PASS)]


@pytest.mark.parametrize("final_times, final_mem, failing", [
    ([15.5, 15.5, 15.5], (2200, 1500), "rasterizing_wall_s"),
    ([14.8, 14.8, 14.8], (8010, 1500), "peak_pagefile_usage_bytes"),
    ([14.8, 14.8, 14.8], (2200, 1560), "peak_working_set_bytes"),
])
def test_each_primary_gate_fails_alone(work, final_times, final_mem, failing):
    work.passing_gates(skip=(PRIMARY,))
    work.round(PRIMARY, 1, [30.0, 30.0, 30.0], final_times, base_mem=(8000, 1500), final_mem=final_mem)
    code, summary = work.judge("gates")

    assert code == 1 and summary["verdict"] == ar.FAIL
    assert gate(summary, PRIMARY)["status"] == ar.FAIL
    assert [c["metric"] for c in gate(summary, PRIMARY)["checks"] if c["result"] == ar.FAIL] == [failing]


def test_rss_exactly_at_guard_passes(work):
    work.passing_gates(skip=(PRIMARY,))
    work.round(PRIMARY, 1, [30.0] * 3, [14.8] * 3, base_mem=(8000, 1500), final_mem=(2200, 1545))
    code, summary = work.judge("gates")

    assert code == 0
    assert check(summary, PRIMARY, "peak_working_set_bytes")["limit"] == 1545.0


def test_fullplate_above_103_percent_fails(work):
    work.passing_gates(skip=(FULLPLATE,))
    work.round(FULLPLATE, 1, [40.0] * 3, [41.5] * 3)
    code, summary = work.judge("gates")

    assert code == 1 and gate(summary, FULLPLATE)["status"] == ar.FAIL


def test_secondary_must_not_be_slower_than_base(work):
    work.passing_gates(skip=(SECONDARY,))
    work.round(SECONDARY, 1, [6.20] * 3, [6.21] * 3)
    code, summary = work.judge("gates")

    assert code == 1 and gate(summary, SECONDARY)["status"] == ar.FAIL


def test_golden_numbers_are_not_the_base(work):
    # The Golden runs hold 22.58 s; 10.80 s would pass against them but not
    # against the 21.00 s measured in the same session.
    work.passing_gates(skip=(PRIMARY,))
    work.round(PRIMARY, 1, [21.00] * 3, [10.80] * 3)
    code, summary = work.judge("gates")

    speed = check(summary, PRIMARY, "rasterizing_wall_s")
    assert code == 1
    assert speed["base_median"] == 21.00 and speed["result"] == ar.FAIL


# ── rounds ────────────────────────────────────────────────────────────────────

def test_one_sided_spread_requires_both_engines_to_rerun(work):
    work.passing_gates(skip=(PRIMARY,))
    work.round(PRIMARY, 1, [22.0, 22.4, 23.6], [4.3, 4.4, 4.5])
    code, summary = work.judge("gates")

    primary = gate(summary, PRIMARY)
    assert code == 4 and summary["verdict"] == ar.INCOMPLETE
    assert primary["status"] == ar.INCOMPLETE and "a2 for both engines" in primary["reason"]
    assert primary["checks"] == []


def test_only_latest_round_is_judged_and_earlier_is_superseded(work):
    work.passing_gates(skip=(PRIMARY,))
    work.round(PRIMARY, 1, [22.0, 22.4, 23.6], [4.3, 4.4, 4.5])
    work.round(PRIMARY, 2, [22.0, 22.2, 22.4], [4.3, 4.4, 4.5])
    code, summary = work.judge("gates")

    primary = gate(summary, PRIMARY)
    assert code == 0 and primary["status"] == ar.PASS and primary["latest_round"] == 2
    assert [(r["round"], r["superseded"]) for r in primary["rounds"]] == [(1, True), (2, False)]
    assert check(summary, PRIMARY, "rasterizing_wall_s")["base_median"] == 22.2
    superseded = {r["run_id"] for r in summary["runs"] if r["superseded"]}
    assert len(superseded) == 6 and all("-a1-" in run_id for run_id in superseded)


def test_rerun_without_trigger_is_refused(work):
    # a1 passed quietly; running a2 anyway would let a case be rerun until it passes.
    work.passing_gates(skip=(PRIMARY,))
    work.round(PRIMARY, 1, [30.0, 30.2, 30.4], [15.5, 15.5, 15.5])
    work.round(PRIMARY, 2, [30.0, 30.2, 30.4], [14.8, 14.8, 14.8])
    code, summary = work.judge("gates")

    assert code == 1
    assert gate(summary, PRIMARY)["status"] == ar.FAIL
    assert "did not require a rerun" in gate(summary, PRIMARY)["reason"]
    assert gate(summary, PRIMARY)["checks"] == []


def test_round_numbers_must_start_at_a1_without_gaps(work):
    work.passing_gates(skip=(PRIMARY,))
    work.round(PRIMARY, 1, [22.0, 22.4, 23.6], [4.3, 4.4, 4.5])
    work.round(PRIMARY, 3, [22.0, 22.2, 22.4], [4.3, 4.4, 4.5])
    code, summary = work.judge("gates")

    assert code == 1 and gate(summary, PRIMARY)["status"] == ar.FAIL


def test_a3_still_spreading_is_unstable(work):
    work.passing_gates(skip=(PRIMARY,))
    for round_no in (1, 2, 3):
        work.round(PRIMARY, round_no, [22.0, 22.4, 23.6], [4.3, 4.4, 4.5])
    code, summary = work.judge("gates")

    primary = gate(summary, PRIMARY)
    assert code == 3 and summary["verdict"] == ar.UNSTABLE
    assert primary["status"] == ar.UNSTABLE and primary["checks"] == []
    assert [r["superseded"] for r in primary["rounds"]] == [True, True, False]


def test_fourth_round_is_refused(work):
    work.passing_gates(skip=(PRIMARY,))
    for round_no in (1, 2, 3, 4):
        work.round(PRIMARY, round_no, [22.0, 22.4, 23.6], [4.3, 4.4, 4.5])
    code, summary = work.judge("gates")

    assert code == 1 and gate(summary, PRIMARY)["status"] == ar.FAIL


def test_round_with_one_engine_missing_a_repeat_is_not_judged(work):
    work.passing_gates(skip=(PRIMARY,))
    for repeat in (1, 2, 3):
        work.run("base", 1, PRIMARY, repeat, 30.0, 8000, 1500)
    for repeat in (1, 2):
        work.run("final", 1, PRIMARY, repeat, 14.8, 2200, 1500)
    code, summary = work.judge("gates")

    primary = gate(summary, PRIMARY)
    assert code == 4 and primary["status"] == ar.INCOMPLETE and primary["checks"] == []
    assert primary["rounds"][0]["missing"] == {"base": [], "final": [3]}


def test_gate_round_mixing_thread_counts_fails(work):
    work.passing_gates(skip=(PRIMARY,))
    for repeat in (1, 2, 3):
        work.run("base", 1, PRIMARY, repeat, 30.0, 8000, 1500, threads=8)
        work.run("final", 1, PRIMARY, repeat, 14.8, 2200, 1500, threads=4 if repeat == 3 else 8)
    code, summary = work.judge("gates")

    assert code == 1 and "mixes thread counts" in gate(summary, PRIMARY)["reason"]


def test_diagnostic_and_variant_runs_are_listed_but_not_judged(work):
    work.passing_gates()
    work.run("final", 1, PRIMARY, 4, 999.0, env={"SLA_RASTER_TIMING": "1"})
    work.run("final", 1, PRIMARY, 1, 999.0, variant="blur1")
    code, summary = work.judge("gates")

    excluded = [r["excluded"] for r in summary["runs"] if r["excluded"]]
    assert code == 0
    assert sorted(excluded) == ["diagnostic environment SLA_RASTER_TIMING", "variant blur1"]


def test_tiny_case_is_recorded_not_judged(work):
    work.passing_gates()
    code, summary = work.judge("gates")

    tiny = summary["record_only"][TINY]
    assert code == 0 and tiny["judged"] is False
    assert tiny["final"]["rasterizing_wall_s"]["median"] == 5.0
    assert TINY not in summary["gates"]


def test_missing_tiny_runs_are_incomplete(work):
    work.passing_gates()
    for run_dir in work.runs.glob(f"windows-p3-final-a1-{TINY}-*"):
        for file in run_dir.iterdir():
            file.unlink()
        run_dir.rmdir()
    code, summary = work.judge("gates")

    assert code == 4 and summary["record_only"][TINY]["status"] == ar.INCOMPLETE


def test_missing_measurement_fails(work):
    work.passing_gates()
    timing = work.runs / f"windows-p3-final-a1-{PRIMARY}-tdefault-r2" / "timing.json"
    timing.write_text(json.dumps({"rasterizing_wall_s": 14.8, "peak_pagefile_usage_bytes": None,
                                  "peak_working_set_bytes": 1500}), encoding="utf-8")
    code, summary = work.judge("gates")

    assert code == 1
    assert [p["kind"] for p in summary["problems"]] == ["missing_measurement"]


# ── identity and fingerprints ─────────────────────────────────────────────────

def test_run_with_another_engine_hash_is_void(work):
    work.passing_gates()
    run_dir = work.runs / f"windows-p3-final-a1-{FULLPLATE}-tdefault-r1"
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    meta["engine"]["core_sha256"] = "0" * 64
    (run_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    code, summary = work.judge("gates")

    run = next(r for r in summary["runs"] if r["run_id"] == run_dir.name)
    assert code == 1 and summary["verdict"] == ar.FAIL
    assert "core_sha256" in run["void"]
    # The void run is not counted, so its round has only two final repeats.
    assert gate(summary, FULLPLATE)["status"] == ar.INCOMPLETE


def test_base_engine_used_as_final_is_void(work):
    work.passing_gates(skip=(SECONDARY,))
    for repeat in (1, 2, 3):
        work.run("base", 1, SECONDARY, repeat, 6.2)
        work.run("final", 1, SECONDARY, repeat, 6.0, engine=work.identity["base"])
    code, summary = work.judge("gates")

    assert code == 1
    assert sum(1 for p in summary["problems"] if p["kind"] == "void_run") == 3


def test_engine_binary_changed_after_build_info_fails(work):
    work.passing_gates()
    (work.root / "engines" / FINAL_ENGINE / "slicer_core.dll").write_bytes(b"rebuilt without a new build_info")
    code, summary = work.judge("gates")

    assert code == 1
    assert any(p["kind"] == "engine_identity" and "no longer matches" in p["detail"] for p in summary["problems"])
    assert all(r["void"] for r in summary["runs"] if r["engine"] == "final")


@pytest.mark.parametrize("build_info", [None, {"fork": {}, "build": {}}])
def test_missing_or_hashless_build_info_fails(work, build_info):
    work.passing_gates()
    path = work.root / "engines" / BASE_ENGINE / "build_info.json"
    if build_info is None:
        path.unlink()
    else:
        path.write_text(json.dumps(build_info), encoding="utf-8")
    code, summary = work.judge("gates")

    assert code == 1
    assert any(p["kind"] == "engine_identity" for p in summary["problems"])
    assert all(r["void"] for r in summary["runs"] if r["engine"] == "base")


def test_schema_1_run_is_void(work):
    work.passing_gates(skip=(SECONDARY,))
    work.round(SECONDARY, 1, [6.2] * 3, [4.6] * 3)
    run_dir = work.runs / f"windows-p3-base-a1-{SECONDARY}-tdefault-r1"
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    meta["schema_version"] = 1
    (run_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    code, summary = work.judge("gates")

    assert code == 1
    assert "schema 1" in next(r for r in summary["runs"] if r["run_id"] == run_dir.name)["void"]


def test_base_rerun_fingerprint_mismatch_fails(work):
    work.passing_gates(skip=(PRIMARY,))
    for repeat in (1, 2, 3):
        preview = PREVIEW.replace(b"b" * 64, b"c" * 64) if repeat == 2 else PREVIEW
        work.run("base", 1, PRIMARY, repeat, 30.0, 8000, 1500, preview=preview)
        work.run("final", 1, PRIMARY, repeat, 14.8, 2200, 1500)
    code, summary = work.judge("gates")

    mismatches = [p for p in summary["problems"] if p["kind"] == "fingerprint_mismatch"]
    assert code == 1 and summary["verdict"] == ar.FAIL
    assert len(mismatches) == 1 and "preview.sha256: 1 differ" in mismatches[0]["detail"]


def test_missing_golden_fails(work):
    work.passing_gates()
    golden = work.runs / f"windows-base-{SECONDARY}-tdefault-r1"
    for file in golden.iterdir():
        file.unlink()
    golden.rmdir()
    code, summary = work.judge("gates")

    assert code == 1
    assert any(p["kind"] == "missing_golden" for p in summary["problems"])


# ── curve ─────────────────────────────────────────────────────────────────────

def test_curve_numbers_never_fail_acceptance(work):
    work.passing_gates()
    for role in ("base", "final"):
        for threads in (1, 2, 4):
            for repeat in (1, 2, 3):
                # The final engine at one thread is far above 50% of base: recorded only.
                work.run(role, 1, PRIMARY, repeat, 100.0 if role == "final" else 40.0, threads_requested=threads)
    code, summary = work.judge("gates", "curve")

    point = next(p for p in summary["curve"]["points"] if p["engine"] == "final" and p["threads"] == 1)
    assert code == 0 and summary["curve"]["judged"] is False
    assert point["rasterizing_wall_s"]["median"] == 100.0


def test_curve_eight_threads_come_from_latest_gate_round(work):
    work.passing_gates()
    work.passing_curve()
    code, summary = work.judge("gates", "curve")

    eight = [p for p in summary["curve"]["points"] if p["threads"] == 8]
    assert code == 0
    assert [p["source"] for p in eight] == ["gate round a1 (default threads, effective 8)"] * 2
    assert eight[1]["rasterizing_wall_s"]["median"] == 14.8


def test_curve_needs_explicit_eight_when_default_was_not_eight(work):
    work.passing_gates(skip=(PRIMARY,))
    work.round(PRIMARY, 1, [30.0] * 3, [14.8] * 3, threads=6)
    work.passing_curve()
    code, summary = work.judge("gates", "curve")
    assert code == 4
    assert all(p["status"] == ar.INCOMPLETE for p in summary["curve"]["points"] if p["threads"] == 8)

    for role in ("base", "final"):
        for repeat in (1, 2, 3):
            work.run(role, 1, PRIMARY, repeat, 20.0, threads_requested=8)
    code, summary = work.judge("gates", "curve")
    assert code == 0
    assert all(p["source"] == "--threads 8, round a1" for p in summary["curve"]["points"] if p["threads"] == 8)


def test_curve_fingerprint_mismatch_fails(work):
    work.passing_gates()
    work.passing_curve()
    run_dir = work.runs / f"windows-p3-final-a1-{PRIMARY}-t2-r3"
    (run_dir / "preview.sha256").write_bytes(PREVIEW.replace(b"b" * 64, b"d" * 64))
    code, summary = work.judge("gates", "curve")

    assert code == 1
    assert [p["run"] for p in summary["problems"] if p["kind"] == "fingerprint_mismatch"] == [run_dir.name]


# ── PRZ ───────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("field, ok", [
    (TIME_A + b"\0" * 5, True),
    (b"2026-13-45 10:00:00" + b"\0" * 5, False),   # month 13
    (b"2026-09-17T10:00:00" + b"\0" * 5, False),   # wrong separator
    (b"2026-09-17 10:00:0\xff" + b"\0" * 5, False),  # not ASCII
    (TIME_A + b"\0\0 \0\0", False),                 # padding not NUL
    (TIME_A + b"\0" * 4, False),                    # 23 bytes
])
def test_prz_time_field_check(field, ok):
    assert (ar.check_prz_time_field(field) is None) is ok


def test_prz_differing_only_in_time_passes(tmp_path):
    base, final = tmp_path / "base.prz", tmp_path / "final.prz"
    base.write_bytes(prz_bytes(time=TIME_A))
    final.write_bytes(prz_bytes(time=TIME_B))
    result = ar.compare_prz(base, final)

    assert result["result"] == ar.PASS and result["problems"] == []
    assert result["mask"] == [68, 92]
    assert result["base"]["sha256"] == hashlib.sha256(base.read_bytes()).hexdigest()
    assert result["base"]["sha256"] != result["final"]["sha256"]


@pytest.mark.parametrize("offset", [0, 67, 92, 4095])
def test_prz_one_byte_outside_mask_fails_with_offset(tmp_path, offset):
    data = prz_bytes()
    base, final = tmp_path / "base.prz", tmp_path / "final.prz"
    base.write_bytes(data)
    data[offset] ^= 0xFF
    final.write_bytes(data)
    result = ar.compare_prz(base, final)

    assert result["result"] == ar.FAIL
    assert result["first_difference_offset"] == offset


def test_prz_difference_beyond_first_chunk_is_found(tmp_path):
    data = prz_bytes(size=ar._CHUNK * 2 + 500)
    base, final = tmp_path / "base.prz", tmp_path / "final.prz"
    base.write_bytes(data)
    data[ar._CHUNK + 123] ^= 0x01
    final.write_bytes(data)

    assert ar.compare_prz(base, final)["first_difference_offset"] == ar._CHUNK + 123


def test_prz_length_difference_fails(tmp_path):
    base, final = tmp_path / "base.prz", tmp_path / "final.prz"
    base.write_bytes(prz_bytes(size=4096))
    final.write_bytes(prz_bytes(size=4097))
    result = ar.compare_prz(base, final)

    assert result["result"] == ar.FAIL
    assert any("lengths differ" in p for p in result["problems"])


@pytest.mark.parametrize("final_data, fragment", [
    (prz_bytes(time=b"2026-13-45 10:00:00"), "final: time text"),
    (prz_bytes(padding=b"\0\0\0\0x"), "final: time padding"),
])
def test_prz_invalid_time_field_fails_even_if_rest_matches(tmp_path, final_data, fragment):
    base, final = tmp_path / "base.prz", tmp_path / "final.prz"
    base.write_bytes(prz_bytes())
    final.write_bytes(final_data)
    result = ar.compare_prz(base, final)

    assert result["result"] == ar.FAIL
    assert result["first_difference_offset"] is None
    assert any(fragment in p for p in result["problems"])


def test_prz_shorter_than_header_fails(tmp_path):
    base, final = tmp_path / "base.prz", tmp_path / "final.prz"
    base.write_bytes(bytes(prz_bytes())[:80])
    final.write_bytes(bytes(prz_bytes())[:80])

    assert ar.compare_prz(base, final)["result"] == ar.FAIL


def test_missing_prz_is_incomplete(work):
    code, summary = work.judge("prz")

    assert code == 4 and summary["prz"]["result"] == ar.INCOMPLETE


def test_prz_section_failure_sets_exit_code(work):
    data = prz_bytes()
    base = bytes(data)
    data[3000] ^= 0x10
    work.prz(base, bytes(data))
    code, summary = work.judge("prz")

    assert code == 1 and summary["prz"]["first_difference_offset"] == 3000


# ── CLI and report ────────────────────────────────────────────────────────────

def test_missing_runs_directory_is_a_usage_error(tmp_path, capsys):
    assert ar.main(["--work", str(tmp_path / "nowhere")]) == ar.EXIT_USAGE
    assert "no runs directory" in capsys.readouterr().err


def test_unreadable_meta_is_a_usage_error(work, capsys):
    run_dir = work.run("final", 1, PRIMARY, 1, 14.8)
    (run_dir / "meta.json").write_text("{not json", encoding="utf-8")
    assert ar.main(["--work", str(work.root), "--out", str(work.root / "out")]) == ar.EXIT_USAGE
    assert not (work.root / "out").exists()


def test_report_numbers_come_from_summary(work):
    work.passing_gates()
    work.passing_curve()
    work.prz(bytes(prz_bytes(time=TIME_A)), bytes(prz_bytes(time=TIME_B)))
    work.judge()
    summary = json.loads((work.root / "out" / "summary.json").read_text(encoding="utf-8"))
    report = (work.root / "out" / "report.md").read_text(encoding="utf-8")

    assert f"verdict: **{summary['verdict']}**" in report
    speed = check(summary, PRIMARY, "rasterizing_wall_s")
    assert f"| {ar._fmt(speed['base_median'])} | {ar._fmt(speed['final_median'])} | {ar._fmt(speed['limit'])} |" in report
    assert summary["prz"]["final"]["sha256"] in report
    assert all(run["run_id"] in report for run in summary["runs"])
    assert ar.render_report(summary) == report


def test_summary_has_no_absolute_paths(work):
    work.passing_gates()
    work.judge("gates")
    text = (work.root / "out" / "summary.json").read_text(encoding="utf-8")

    assert str(work.root) not in text and str(work.root).replace("\\", "\\\\") not in text

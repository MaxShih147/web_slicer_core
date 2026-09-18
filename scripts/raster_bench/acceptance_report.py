#!/usr/bin/env python
"""Judge the Phase 3 acceptance runs and write summary.json and report.md.

Spec: ``raster-performance-baseline`` (openspec change optimize-raster-canvas-scan),
"門檻判定由工具產出結構化結果"; decisions in design.md D12.

  python scripts/raster_bench/acceptance_report.py [--work DIR] [--out DIR]
         [--section gates|curve|prz ...] [--prz-base FILE] [--prz-final FILE]

Only reads what is already under the work directory; it never starts the engine.

Runs are the run_bench.py directories whose build label is ``<base-label>-aN`` or
``<final-label>-aN`` (default ``p3-base`` / ``p3-final``); N is the round. Runs
with a variant or any SLA_RASTER_* variable are diagnostics (tasks 3.4, 3.5) and
are listed but not judged. Every judged run must:

  - be meta.json schema 2 (``threads`` is the effective count),
  - carry the engine identity recorded in its engine's build_info.json, whose
    hashes must in turn match the binaries in that engine directory,
  - have layer and preview fingerprints equal to the Golden run
    ``<platform>-base-<case>-tdefault-r1``.

A run failing identity is void and not counted; any fingerprint mismatch fails
acceptance.

Sections:

  gates  Per gated case, rounds of base/final runs at the default thread count.
         A round needs repeats 1..3 of both engines. A group whose rasterizing
         times spread more than 5% of the median and more than 0.5 s triggers a
         rerun of both groups as the next round; only the latest round is judged,
         earlier ones are superseded. A round aN with N > 1 must follow a round
         that triggered, so a round cannot be rerun until it passes. If a3 still
         triggers the case is UNSTABLE. The tiny case is recorded, not judged.
  curve  Primary case, both engines at --threads 1, 2, 4 and 8, record only. The
         8-thread point is the latest gate round when its runs used 8 threads.
  prz    The two end-to-end PRZ files match except for the File Time field at
         [68, 92), which must hold a valid "YYYY-MM-DD HH:MM:SS" and five NULs.

Exit code (worst result wins): 0 = PASS, 1 = FAIL, 3 = UNSTABLE, 4 = INCOMPLETE
(required runs or files are missing), 2 = usage error or unreadable input.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import statistics
import sys
from decimal import Decimal
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH_DIR))

from compare_fingerprints import FINGERPRINT_FILES, compare_entries  # noqa: E402
from fingerprint import FingerprintError, read_fingerprint  # noqa: E402

DEFAULT_WORK_DIR = BENCH_DIR / "work"
SUMMARY_SCHEMA_VERSION = 1
META_SCHEMA_VERSION = 2
SECTIONS = ("gates", "curve", "prz")

PASS, FAIL, UNSTABLE, INCOMPLETE = "PASS", "FAIL", "UNSTABLE", "INCOMPLETE"
EXIT_CODES = {PASS: 0, FAIL: 1, UNSTABLE: 3, INCOMPLETE: 4}
EXIT_USAGE = 2
_SEVERITY = {PASS: 0, INCOMPLETE: 1, UNSTABLE: 2, FAIL: 3}

ENGINE_FILES = {"exe_sha256": "slicer-engine.exe", "core_sha256": "slicer_core.dll"}
REPEATS = (1, 2, 3)
MAX_ROUNDS = 3
RERUN_SPREAD_PERCENT = Decimal(5)
RERUN_SPREAD_SECONDS = Decimal("0.5")

# Thresholds of the spec table. limit_percent is final median / base median * 100.
GATES = {
    "primary-16k-guide-x8": [
        {"metric": "rasterizing_wall_s", "limit_percent": 50},
        {"metric": "peak_pagefile_usage_bytes", "limit_percent": 100},
        {"metric": "peak_working_set_bytes", "limit_percent": 103},
    ],
    "secondary-8k-guide-x3": [{"metric": "rasterizing_wall_s", "limit_percent": 100}],
    "fullplate-16k-slab": [{"metric": "rasterizing_wall_s", "limit_percent": 103}],
}
RECORD_ONLY_CASES = ("tiny-16k-crown-x1",)
CURVE_CASE = "primary-16k-guide-x8"
CURVE_THREADS = (1, 2, 4, 8)
METRICS = ("rasterizing_wall_s", "peak_pagefile_usage_bytes", "peak_working_set_bytes")

PRZ_TIME_FIELD = (68, 92)
PRZ_TIME_TEXT_BYTES = 19
PRZ_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
_CHUNK = 1 << 20


class UsageError(Exception):
    """Unreadable or inconsistent input; exit code 2."""


def worst(*statuses: str) -> str:
    return max(statuses, key=_SEVERITY.__getitem__) if statuses else PASS


def _dec(value) -> Decimal:
    # repr() keeps the JSON value exactly (4.3972 stays 4.3972) so a limit such
    # as 103% of 1500 is 1545, not 1545.0000000000002.
    return Decimal(repr(value)) if isinstance(value, float) else Decimal(value)


# ── statistics and rules ──────────────────────────────────────────────────────

def group_stats(values: list) -> dict:
    """Median, min, max, spread and whether the spread triggers a rerun."""
    median = statistics.median(values)
    low, high = min(values), max(values)
    spread = _dec(high) - _dec(low)
    return {
        "values": values,
        "median": median,
        "min": low,
        "max": high,
        "spread": float(spread) if isinstance(high, float) or isinstance(low, float) else int(spread),
    }


def triggers_rerun(times: list[float]) -> bool:
    """Spread both over 5% of the median and over 0.5 s (strictly)."""
    median = _dec(statistics.median(times))
    spread = _dec(max(times)) - _dec(min(times))
    return spread > median * RERUN_SPREAD_PERCENT / 100 and spread > RERUN_SPREAD_SECONDS


def judge_threshold(metric: str, limit_percent: int, base_median, final_median) -> dict:
    limit = _dec(base_median) * limit_percent / 100
    ok = _dec(final_median) <= limit
    return {
        "metric": metric,
        "rule": f"final median <= {limit_percent}% of base median",
        "base_median": base_median,
        "final_median": final_median,
        "limit": float(limit),
        "ratio_percent": float(_dec(final_median) * 100 / _dec(base_median)) if base_median else None,
        "result": PASS if ok else FAIL,
    }


# ── PRZ ───────────────────────────────────────────────────────────────────────

def check_prz_time_field(field: bytes) -> str | None:
    """None when the 24-byte File Time field is valid, else the reason."""
    start, end = PRZ_TIME_FIELD
    if len(field) != end - start:
        return f"time field is {len(field)} bytes, expected {end - start}"
    text, padding = field[:PRZ_TIME_TEXT_BYTES], field[PRZ_TIME_TEXT_BYTES:]
    try:
        dt.datetime.strptime(text.decode("ascii"), PRZ_TIME_FORMAT)
    except (UnicodeDecodeError, ValueError):
        return f"time text {text!r} is not {PRZ_TIME_FORMAT}"
    if padding != b"\0" * len(padding):
        return f"time padding {padding!r} is not all NUL"
    return None


def compare_prz(base: Path, final: Path) -> dict:
    """Masked byte comparison of two PRZ files, streamed in 1 MiB chunks."""
    start, end = PRZ_TIME_FIELD
    result = {
        "mask": [start, end],
        "base": {"name": base.name, "bytes": base.stat().st_size},
        "final": {"name": final.name, "bytes": final.stat().st_size},
        "problems": [],
        "first_difference_offset": None,
    }
    digests = {"base": hashlib.sha256(), "final": hashlib.sha256()}
    if result["base"]["bytes"] != result["final"]["bytes"]:
        result["problems"].append(
            f"lengths differ: base {result['base']['bytes']}, final {result['final']['bytes']}")
    with open(base, "rb") as fb, open(final, "rb") as ff:
        head_b, head_f = fb.read(end), ff.read(end)
        digests["base"].update(head_b)
        digests["final"].update(head_f)
        for side, head in (("base", head_b), ("final", head_f)):
            reason = check_prz_time_field(head[start:end])
            if reason is not None:
                result["problems"].append(f"{side}: {reason}")
        for offset in range(min(start, len(head_b), len(head_f))):
            if head_b[offset] != head_f[offset]:
                result["first_difference_offset"] = offset
                break
        offset = end
        while True:
            chunk_b, chunk_f = fb.read(_CHUNK), ff.read(_CHUNK)
            if not chunk_b and not chunk_f:
                break
            digests["base"].update(chunk_b)
            digests["final"].update(chunk_f)
            if result["first_difference_offset"] is None and chunk_b != chunk_f:
                for i in range(min(len(chunk_b), len(chunk_f))):
                    if chunk_b[i] != chunk_f[i]:
                        result["first_difference_offset"] = offset + i
                        break
                # A pure length difference has no differing byte in the common part.
            offset += max(len(chunk_b), len(chunk_f))
    result["base"]["sha256"] = digests["base"].hexdigest()
    result["final"]["sha256"] = digests["final"].hexdigest()
    if result["first_difference_offset"] is not None:
        result["problems"].append(
            f"bytes outside the mask differ; first at offset {result['first_difference_offset']}")
    result["result"] = FAIL if result["problems"] else PASS
    return result


# ── loading ───────────────────────────────────────────────────────────────────

def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UsageError(f"cannot read {path}: {exc}") from exc


def engine_expectation(engines_dir: Path, name: str) -> dict:
    """Identity recorded in build_info.json, checked against the binaries themselves."""
    engine_dir = engines_dir / name
    build_info = engine_dir / "build_info.json"
    entry = {"dir": name, "problems": []}
    if not build_info.is_file():
        entry["problems"].append(f"{name}: missing build_info.json")
        return entry
    info = load_json(build_info)
    files = info.get("build", {}).get("files", {})
    fork = info.get("fork", {})
    entry["fork_commit"] = fork.get("commit") or fork.get("head_commit")
    entry["fork_tree"] = fork.get("tree")
    for key, filename in ENGINE_FILES.items():
        recorded = files.get(filename, {}).get("sha256")
        entry[key] = recorded
        if recorded is None:
            entry["problems"].append(f"{name}: build_info.json records no sha256 for {filename}")
            continue
        binary = engine_dir / filename
        if not binary.is_file():
            entry["problems"].append(f"{name}: {filename} is missing from the engine directory")
        elif sha256_file(binary) != recorded:
            entry["problems"].append(f"{name}: {filename} no longer matches build_info.json")
    return entry


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_fingerprints(run_dir: Path) -> dict:
    try:
        return {name: read_fingerprint(run_dir / name) for name in FINGERPRINT_FILES}
    except (OSError, FingerprintError) as exc:
        raise UsageError(f"cannot read fingerprints of {run_dir.name}: {exc}") from exc


def collect_runs(runs_dir: Path, platform: str, labels: dict[str, str]) -> list[dict]:
    """Phase 3 runs by build label; diagnostics and variants are marked excluded."""
    patterns = {role: re.compile(rf"^{re.escape(label)}-a([1-9][0-9]*)$") for role, label in labels.items()}
    runs = []
    for run_dir in sorted(p for p in runs_dir.iterdir() if p.is_dir() and not p.name.startswith(".")):
        meta_path = run_dir / "meta.json"
        if not meta_path.is_file():
            continue
        meta = load_json(meta_path)
        if meta.get("platform") != platform:
            continue
        role, round_no = None, None
        for candidate, pattern in patterns.items():
            match = pattern.match(meta.get("build", ""))
            if match:
                role, round_no = candidate, int(match.group(1))
        if role is None:
            continue
        run = {
            "run_id": run_dir.name, "dir": run_dir, "meta": meta, "engine": role, "round": round_no,
            "case": meta.get("case"), "repeat": meta.get("repeat"),
            "threads": meta.get("threads"), "threads_requested": meta.get("threads_requested"),
            "threads_source": meta.get("threads_source"),
            "excluded": None, "void": None, "fingerprint_matches_golden": None, "superseded": False,
        }
        diagnostics = sorted(name for name in meta.get("env", {}) if name.startswith("SLA_RASTER_"))
        if (meta.get("variant") or {}).get("label"):
            run["excluded"] = f"variant {meta['variant']['label']}"
        elif diagnostics:
            run["excluded"] = f"diagnostic environment {', '.join(diagnostics)}"
        runs.append(run)
    return runs


# ── checks shared by all sections ─────────────────────────────────────────────

def validate_runs(runs: list[dict], runs_dir: Path, platform: str, engines: dict, problems: list[dict]) -> None:
    """Schema, identity and fingerprints of every judged run. Voids runs in place."""
    golden_cache: dict[str, dict | None] = {}
    for run in runs:
        if run["excluded"]:
            continue
        meta = run["meta"]
        if meta.get("schema_version") != META_SCHEMA_VERSION:
            run["void"] = f"meta.json schema {meta.get('schema_version')}, expected {META_SCHEMA_VERSION}"
        elif run["threads"] is None:
            run["void"] = "meta.json records no effective thread count"
        else:
            expected = engines[run["engine"]]
            actual = meta.get("engine", {})
            mismatched = [key for key in ENGINE_FILES if actual.get(key) != expected.get(key)]
            if expected["problems"] or mismatched:
                run["void"] = "engine identity does not match " + expected["dir"] + (
                    f" ({', '.join(mismatched)})" if mismatched else " (its build_info.json is unusable)")
        if run["void"]:
            problems.append({"kind": "void_run", "run": run["run_id"], "detail": run["void"]})
            continue

        case = run["case"]
        if case not in golden_cache:
            golden_dir = runs_dir / f"{platform}-base-{case}-tdefault-r1"
            golden_cache[case] = load_fingerprints(golden_dir) if golden_dir.is_dir() else None
        golden = golden_cache[case]
        if golden is None:
            problems.append({"kind": "missing_golden", "run": run["run_id"],
                             "detail": f"no Golden run {platform}-base-{case}-tdefault-r1"})
            run["fingerprint_matches_golden"] = False
            continue
        current = load_fingerprints(run["dir"])
        differences = {name: compare_entries(golden[name], current[name]) for name in FINGERPRINT_FILES}
        run["fingerprint_matches_golden"] = all(d["differing_count"] == 0 for d in differences.values())
        if not run["fingerprint_matches_golden"]:
            detail = "; ".join(
                f"{name}: {d['differing_count']} differ, first {d['first_difference']['name']}"
                for name, d in differences.items() if d["differing_count"])
            problems.append({"kind": "fingerprint_mismatch", "run": run["run_id"], "detail": detail})


def timing_of(run: dict) -> dict:
    return load_json(run["dir"] / "timing.json")


def group_metrics(group: list[dict], problems: list[dict]) -> dict | None:
    """Per-metric stats for three runs, or None if a value is missing."""
    values = {metric: [] for metric in METRICS}
    for run in sorted(group, key=lambda r: r["repeat"]):
        timing = timing_of(run)
        for metric in METRICS:
            if timing.get(metric) is None:
                problems.append({"kind": "missing_measurement", "run": run["run_id"],
                                 "detail": f"timing.json has no {metric}"})
                return None
            values[metric].append(timing[metric])
    return {metric: group_stats(vals) for metric, vals in values.items()}


def repeats_complete(group: list[dict]) -> bool:
    return sorted(r["repeat"] for r in group) == list(REPEATS)


# ── gates ─────────────────────────────────────────────────────────────────────

def judge_gate_case(case: str, runs: list[dict], problems: list[dict]) -> dict:
    gate_runs = [r for r in runs if r["case"] == case and r["threads_requested"] is None
                 and not r["excluded"] and not r["void"]]
    rounds = sorted({r["round"] for r in gate_runs})
    entry = {"case": case, "rounds": [], "latest_round": rounds[-1] if rounds else None, "checks": []}
    if not rounds:
        entry.update(status=INCOMPLETE, reason="no gate runs")
        return entry
    if rounds[-1] > MAX_ROUNDS or rounds != list(range(1, rounds[-1] + 1)):
        entry.update(status=FAIL, reason=f"rounds {['a%d' % n for n in rounds]} are not a1..a{len(rounds)} "
                                         f"within a{MAX_ROUNDS}")
        return entry

    for number in rounds:
        members = [r for r in gate_runs if r["round"] == number]
        groups = {role: [r for r in members if r["engine"] == role] for role in ("base", "final")}
        record = {"round": number, "superseded": number != rounds[-1], "complete": False,
                  "triggers_rerun": None, "threads": sorted({r["threads"] for r in members}), "groups": {}}
        entry["rounds"].append(record)
        for run in members:
            run["superseded"] = record["superseded"]
        if not all(repeats_complete(group) for group in groups.values()):
            record["missing"] = {role: sorted(set(REPEATS) - {r["repeat"] for r in group})
                                 for role, group in groups.items()}
            continue
        stats = {role: group_metrics(group, problems) for role, group in groups.items()}
        if any(s is None for s in stats.values()):
            continue
        record["complete"] = True
        record["groups"] = stats
        record["triggers_rerun"] = any(
            triggers_rerun(stats[role]["rasterizing_wall_s"]["values"]) for role in stats)

    latest = entry["rounds"][-1]
    for earlier in entry["rounds"][:-1]:
        if not earlier["complete"] or not earlier["triggers_rerun"]:
            entry.update(status=FAIL, reason=f"round a{earlier['round'] + 1} was run although "
                                             f"a{earlier['round']} was incomplete or did not require a rerun")
            return entry
    if not latest["complete"]:
        entry.update(status=INCOMPLETE, reason=f"round a{latest['round']} is not complete for both engines")
        return entry
    if len(latest["threads"]) != 1:
        entry.update(status=FAIL, reason=f"round a{latest['round']} mixes thread counts {latest['threads']}")
        return entry
    if latest["triggers_rerun"]:
        if latest["round"] >= MAX_ROUNDS:
            entry.update(status=UNSTABLE, reason=f"a{MAX_ROUNDS} still spreads too much; remove the "
                                                 "environment interference and restart this case from a1")
        else:
            entry.update(status=INCOMPLETE, reason=f"a{latest['round']} requires a rerun as "
                                                   f"a{latest['round'] + 1} for both engines")
        return entry

    base, final = latest["groups"]["base"], latest["groups"]["final"]
    entry["checks"] = [
        judge_threshold(gate["metric"], gate["limit_percent"],
                        base[gate["metric"]]["median"], final[gate["metric"]]["median"])
        for gate in GATES[case]
    ]
    entry["status"] = worst(*(check["result"] for check in entry["checks"]))
    return entry


def record_only_case(case: str, runs: list[dict], problems: list[dict]) -> dict:
    final_runs = [r for r in runs if r["case"] == case and r["engine"] == "final"
                  and r["threads_requested"] is None and not r["excluded"] and not r["void"]]
    rounds = sorted({r["round"] for r in final_runs})
    entry = {"case": case, "judged": False, "round": rounds[-1] if rounds else None}
    group = [r for r in final_runs if rounds and r["round"] == rounds[-1]]
    if not group or not repeats_complete(group):
        entry.update(status=INCOMPLETE, reason="final engine needs repeats 1..3 at the default thread count")
        return entry
    stats = group_metrics(group, problems)
    if stats is None:
        entry.update(status=INCOMPLETE, reason="a measurement is missing")
        return entry
    entry.update(status=PASS, final=stats)
    return entry


# ── curve ─────────────────────────────────────────────────────────────────────

def build_curve(runs: list[dict], gates: dict, problems: list[dict]) -> dict:
    usable = [r for r in runs if r["case"] == CURVE_CASE and not r["excluded"] and not r["void"]]
    points, statuses = [], []
    for role in ("base", "final"):
        for threads in CURVE_THREADS:
            point = {"engine": role, "threads": threads}
            group, source = [], None
            if threads == 8:
                latest = (gates.get(CURVE_CASE) or {}).get("latest_round")
                group = [r for r in usable if r["engine"] == role and r["threads_requested"] is None
                         and r["round"] == latest]
                if group and repeats_complete(group) and all(r["threads"] == 8 for r in group):
                    source = f"gate round a{latest} (default threads, effective 8)"
                else:
                    group = []
            if not group:
                explicit = [r for r in usable if r["engine"] == role and r["threads_requested"] == threads]
                rounds = sorted({r["round"] for r in explicit})
                group = [r for r in explicit if rounds and r["round"] == rounds[-1]]
                source = f"--threads {threads}, round a{rounds[-1]}" if rounds else None
            if not group or not repeats_complete(group):
                point.update(status=INCOMPLETE, reason="needs repeats 1..3")
            else:
                stats = group_metrics(group, problems)
                if stats is None:
                    point.update(status=INCOMPLETE, reason="a measurement is missing")
                else:
                    point.update(status=PASS, source=source, runs=[r["run_id"] for r in group],
                                 effective_threads=sorted({r["threads"] for r in group}), **stats)
            statuses.append(point["status"])
            points.append(point)
    return {"case": CURVE_CASE, "judged": False, "status": worst(*statuses), "points": points}


# ── report ────────────────────────────────────────────────────────────────────

def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return f"{value:,}" if isinstance(value, int) else str(value)


def render_report(summary: dict) -> str:
    """report.md, built only from summary.json values."""
    lines = [
        "# Phase 3 acceptance report",
        "",
        f"- generated: {summary['generated_at_utc']}",
        f"- platform: {summary['platform']}",
        f"- sections: {', '.join(summary['sections'])}",
        f"- verdict: **{summary['verdict']}**",
        "",
        "## Engines",
        "",
        "| Role | Directory | slicer-engine.exe | slicer_core.dll | Fork commit |",
        "| --- | --- | --- | --- | --- |",
    ]
    for role, engine in summary["engines"].items():
        lines.append(f"| {role} | {engine['dir']} | {_fmt(engine.get('exe_sha256'))} | "
                     f"{_fmt(engine.get('core_sha256'))} | {_fmt(engine.get('fork_commit'))} |")

    if "gates" in summary:
        lines += ["", "## Gates", ""]
        for case, gate in summary["gates"].items():
            lines.append(f"### {case}: {gate['status']}")
            if gate.get("reason"):
                lines.append(f"\n{gate['reason']}")
            if gate["checks"]:
                lines += ["", "| Metric | Rule | Base median | Final median | Limit | Ratio | Result |",
                          "| --- | --- | ---: | ---: | ---: | ---: | --- |"]
                for check in gate["checks"]:
                    lines.append(
                        f"| {check['metric']} | {check['rule']} | {_fmt(check['base_median'])} | "
                        f"{_fmt(check['final_median'])} | {_fmt(check['limit'])} | "
                        f"{_fmt(check['ratio_percent'])}% | {check['result']} |")
            if gate["rounds"]:
                lines += ["", "| Round | Superseded | Complete | Rerun? | Base s (min~max) | Final s (min~max) |",
                          "| --- | --- | --- | --- | --- | --- |"]
                for rnd in gate["rounds"]:
                    cells = []
                    for role in ("base", "final"):
                        stats = rnd["groups"].get(role, {}).get("rasterizing_wall_s")
                        cells.append(f"{_fmt(stats['median'])} ({_fmt(stats['min'])}~{_fmt(stats['max'])})"
                                     if stats else "-")
                    lines.append(f"| a{rnd['round']} | {rnd['superseded']} | {rnd['complete']} | "
                                 f"{_fmt(rnd['triggers_rerun'])} | {cells[0]} | {cells[1]} |")
            lines.append("")
        for case, record in summary.get("record_only", {}).items():
            lines.append(f"### {case} (record only): {record['status']}")
            stats = record.get("final")
            if stats:
                lines.append(f"\nfinal rasterizing median {_fmt(stats['rasterizing_wall_s']['median'])} s, "
                             f"committed {_fmt(stats['peak_pagefile_usage_bytes']['median'])} B, "
                             f"RSS {_fmt(stats['peak_working_set_bytes']['median'])} B")
            elif record.get("reason"):
                lines.append(f"\n{record['reason']}")
            lines.append("")

    if "curve" in summary:
        curve = summary["curve"]
        lines += [f"## Thread scaling curve (record only): {curve['status']}", "",
                  "| Engine | Threads | Rasterizing median s | Committed median B | RSS median B | Source |",
                  "| --- | ---: | ---: | ---: | ---: | --- |"]
        for point in curve["points"]:
            if point["status"] == PASS:
                lines.append(
                    f"| {point['engine']} | {point['threads']} | {_fmt(point['rasterizing_wall_s']['median'])} | "
                    f"{_fmt(point['peak_pagefile_usage_bytes']['median'])} | "
                    f"{_fmt(point['peak_working_set_bytes']['median'])} | {point['source']} |")
            else:
                lines.append(f"| {point['engine']} | {point['threads']} | - | - | - | {point['status']}: "
                             f"{point['reason']} |")
        lines.append("")

    if "prz" in summary:
        prz = summary["prz"]
        lines += [f"## End-to-end PRZ: {prz['result']}", ""]
        if prz.get("base"):
            lines += [f"- base: {prz['base']['name']}, {_fmt(prz['base']['bytes'])} bytes, {prz['base']['sha256']}",
                      f"- final: {prz['final']['name']}, {_fmt(prz['final']['bytes'])} bytes, "
                      f"{prz['final']['sha256']}",
                      f"- masked bytes: [{prz['mask'][0]}, {prz['mask'][1]})"]
        lines += [f"- {problem}" for problem in prz.get("problems", [])]
        lines.append("")

    lines += ["## Runs", "",
              "| Run | Engine | Round | Threads | Golden | Superseded | Excluded / void |",
              "| --- | --- | --- | ---: | --- | --- | --- |"]
    for run in summary["runs"]:
        lines.append(f"| {run['run_id']} | {run['engine']} | a{run['round']} | {_fmt(run['threads'])} | "
                     f"{_fmt(run['fingerprint_matches_golden'])} | {run['superseded']} | "
                     f"{run['excluded'] or run['void'] or ''} |")
    if summary["problems"]:
        lines += ["", "## Problems", ""]
        lines += [f"- {p['kind']}: " + (f"{p['run']}: " if p.get("run") else "") + p["detail"]
                  for p in summary["problems"]]
    return "\n".join(lines) + "\n"


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--work", default=str(DEFAULT_WORK_DIR), help="working directory (default: %(default)s)")
    parser.add_argument("--out", help="output directory for summary.json and report.md (default: <work>/acceptance)")
    parser.add_argument("--platform", default="windows", help="platform label of the runs (default: %(default)s)")
    parser.add_argument("--section", action="append", choices=SECTIONS,
                        help="section to evaluate; repeatable (default: all). Final acceptance needs all.")
    parser.add_argument("--base-engine", default="base-5bc83b08f", help="engine directory name (default: %(default)s)")
    parser.add_argument("--final-engine", default="final-22f2e310a",
                        help="engine directory name (default: %(default)s)")
    parser.add_argument("--base-label", default="p3-base", help="build label prefix (default: %(default)s)")
    parser.add_argument("--final-label", default="p3-final", help="build label prefix (default: %(default)s)")
    parser.add_argument("--prz-base", help="base engine PRZ (default: <work>/prz/base.prz)")
    parser.add_argument("--prz-final", help="final engine PRZ (default: <work>/prz/final.prz)")
    return parser.parse_args(argv)


def build_summary(args: argparse.Namespace) -> dict:
    work = Path(args.work)
    runs_dir = work / "runs"
    if not runs_dir.is_dir():
        raise UsageError(f"no runs directory: {runs_dir}")
    sections = list(dict.fromkeys(args.section or SECTIONS))
    problems: list[dict] = []

    engines = {"base": engine_expectation(work / "engines", args.base_engine),
               "final": engine_expectation(work / "engines", args.final_engine)}
    for engine in engines.values():
        problems += [{"kind": "engine_identity", "run": None, "detail": d} for d in engine["problems"]]

    runs = collect_runs(runs_dir, args.platform, {"base": args.base_label, "final": args.final_label})
    validate_runs(runs, runs_dir, args.platform, engines, problems)

    statuses = [FAIL if problems else PASS]
    summary = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "tool": "scripts/raster_bench/acceptance_report.py",
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "platform": args.platform,
        "sections": sections,
        "labels": {"base": args.base_label, "final": args.final_label},
        "engines": engines,
    }
    if "gates" in sections:
        summary["gates"] = {case: judge_gate_case(case, runs, problems) for case in GATES}
        summary["record_only"] = {case: record_only_case(case, runs, problems) for case in RECORD_ONLY_CASES}
        statuses += [gate["status"] for gate in summary["gates"].values()]
        statuses += [record["status"] for record in summary["record_only"].values()]
    if "curve" in sections:
        summary["curve"] = build_curve(runs, summary.get("gates", {}), problems)
        statuses.append(summary["curve"]["status"])
    if "prz" in sections:
        prz_base = Path(args.prz_base) if args.prz_base else work / "prz" / "base.prz"
        prz_final = Path(args.prz_final) if args.prz_final else work / "prz" / "final.prz"
        missing = [p.name for p in (prz_base, prz_final) if not p.is_file()]
        summary["prz"] = ({"result": INCOMPLETE, "problems": [f"missing {', '.join(missing)}"]}
                          if missing else compare_prz(prz_base, prz_final))
        statuses.append(summary["prz"]["result"])

    # Problems found while reading measurements are failures too.
    if problems and FAIL not in statuses:
        statuses.append(FAIL)
    summary["runs"] = [
        {key: run[key] for key in ("run_id", "case", "engine", "round", "repeat", "threads", "threads_requested",
                                   "threads_source", "fingerprint_matches_golden", "superseded", "excluded",
                                   "void")}
        for run in runs
    ]
    summary["problems"] = problems
    summary["verdict"] = worst(*statuses)
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        summary = build_summary(args)
    except UsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    out = Path(args.out) if args.out else Path(args.work) / "acceptance"
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "report.md").write_text(render_report(summary), encoding="utf-8")
    print(json.dumps({"verdict": summary["verdict"], "summary": str(out / "summary.json")}))
    return EXIT_CODES[summary["verdict"]]


if __name__ == "__main__":
    sys.exit(main())

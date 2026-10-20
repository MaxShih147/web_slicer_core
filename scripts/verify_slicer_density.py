#!/usr/bin/env python
"""Verify the deployed slicer engine at extreme support point density.

Spec: ``support-param-validation`` (openspec change guard-support-density-bounds,
design.md D4). Run from the repository root:

  python scripts/verify_slicer_density.py [--engine EXE] [--out DIR] [--only A ...]

Builds two 50x50x10 mm boxes in code (flat, and tilted 20 degrees about Y), then
drives the engine with exactly the config the agent would send: SLAConfig with a
0.6 mm head and 1.0 mm pillar, written by generate_config_ini() at the support
detection layer height. Four groups:

  A  flat box, four density/min_distance pairs      points + full support
  B  tilted box, four density/min_distance pairs    points + full support
  C  both boxes x min_distance {0, 1.5} x density sweep up to 10000%   points
  D  tilted box at 10000% / 0 mm                     full support, timed

Hard failures (exit code 1): a non-zero or timed-out engine run, zero points,
point count falling more than 5% below the highest count seen so far as
density rises within one C sweep, a non-finite number anywhere in
support_tree.json or the points file, an engine JSON file that cannot be
parsed, or a support tree with no heads or no pillars although there were
points.

Recorded only, never a failure: the closest same-layer XY pair (the engine's
min_distance moves the spacing, it does not fence it - fork commit 0ed4ec3ce),
the head/point ratio, and the deviation from the reference point counts (a
warning past +/-5%).

Everything is written under --out or a fresh system temp directory, never inside
the repository: .gitignore is off limits, so anything written here would show up
as an untracked file.

Exit code: 0 = all hard checks passed, 1 = a hard check failed, 2 = usage error.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR / "raster_bench"))

import make_fixtures as fx  # noqa: E402  (also puts the repo root on sys.path)
from scipy.spatial import cKDTree  # noqa: E402

from agent.config import SLICER_ENGINE_CLI  # noqa: E402
from agent.models import SLAConfig  # noqa: E402
from agent.sla_operations import (  # noqa: E402
    SUPPORT_DETECTION_LAYER_HEIGHT,
    _english_locale_env,
    generate_config_ini,
)

HEAD_FRONT_DIAMETER = 0.6
PILLAR_DIAMETER = 1.0
BOX_SIZE_MM = [50.0, 50.0, 10.0]
TILT_DEG = 20.0
BOX_TOLERANCE_MM = 0.01
REFERENCE_WARN_PCT = 5.0
# Once a sweep saturates, the slope sampler's count wobbles by about 1% from
# one density to the next (tilted box, min_distance 0: 1522 at 6201%, 1506 at
# 10000%, the same on every rerun). A real loss of points is far larger.
MONOTONIC_DROP_PCT = 5.0

# (density %, min_distance mm) -> points, measured with the fork build of the
# new engine under the same SLAConfig defaults this script uses.
REFERENCE_POINTS = {
    "flat": {(2000, 1.85): 931, (3100, 1.5): 1385, (4200, 1.3): 1817, (2204, 1.5): 1039},
    "tilted": {(200, 3.3): 208, (200, 2.4): 317, (4200, 2.2): 445, (2000, 1.85): 558},
}
GROUP_A = ("flat", list(REFERENCE_POINTS["flat"]))
GROUP_B = ("tilted", list(REFERENCE_POINTS["tilted"]))
# 2205 is the old engine's crash threshold for a 0.6 mm head; 6201 is where the
# island sampler's thick_outline spacing reaches its floor.
SWEEP_DENSITIES = [100, 500, 1000, 2204, 2205, 3100, 4200, 6201, 10000]
SWEEP_MIN_DISTANCES = [0.0, 1.5]
STRESS = ("tilted", 10000, 0.0)

GROUPS = ("A", "B", "C", "D")


# ── geometry ──────────────────────────────────────────────────────────────────

def _face_normals(vertices: np.ndarray) -> np.ndarray:
    """Outward normals from the winding, so they always agree with the vertices."""
    n = np.cross(vertices[:, 1] - vertices[:, 0], vertices[:, 2] - vertices[:, 0])
    return (n / np.linalg.norm(n, axis=1, keepdims=True)).astype(np.float32)


def flat_box():
    _, vertices, _ = fx.slab_geometry(BOX_SIZE_MM)
    return _face_normals(vertices), vertices


def tilted_box():
    """The flat box turned TILT_DEG about Y, then dropped so its lowest point sits at z = 0."""
    _, vertices, _ = fx.slab_geometry(BOX_SIZE_MM)
    t = np.float32(math.radians(TILT_DEG))
    c, s = np.cos(t), np.sin(t)
    rot_y = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=np.float32)
    rotated = (vertices.reshape(-1, 3) @ rot_y.T).astype(np.float32)
    rotated[:, 2] -= rotated[:, 2].min()
    rotated = rotated.reshape(vertices.shape)
    return _face_normals(rotated), rotated


def check_reference_box(path: Path, warnings: list) -> dict:
    """Compare the extent of the box DS-slicer was given with the one built here."""
    triangles = fx.read_binary_stl(path)
    flat = triangles["vertices"].reshape(-1, 3).astype(np.float64)
    extent = sorted((flat.max(axis=0) - flat.min(axis=0)).tolist())
    expected = sorted(BOX_SIZE_MM)
    diff = max(abs(a - b) for a, b in zip(extent, expected))
    if diff > BOX_TOLERANCE_MM:
        warnings.append(
            f"reference box {path} extent {extent} differs from {expected} by {diff:.4f} mm"
        )
    return {"path": str(path), "extent_mm": extent, "max_diff_mm": diff}


# ── engine runs ───────────────────────────────────────────────────────────────

def write_config(path: Path, density: int, min_distance: float) -> None:
    config = SLAConfig(
        supports_enable=True,
        support_head_front_diameter=HEAD_FRONT_DIAMETER,
        support_pillar_diameter=PILLAR_DIAMETER,
        support_points_density_relative=density,
        support_points_min_distance=min_distance,
    )
    # Same coarser detection height generate_supports / export_support_points use.
    config = config.model_copy(update={
        "layer_height": SUPPORT_DETECTION_LAYER_HEIGHT,
        "initial_layer_height": SUPPORT_DETECTION_LAYER_HEIGHT,
    })
    generate_config_ini(config, path)


def run_engine(cmd: list, run_dir: Path, timeout: float, log_name: str) -> dict:
    """Run one engine pass. Logs go to stdout_<log_name>.log / stderr_<log_name>.log,
    so the points pass and the support pass of one run_dir keep their own."""
    start = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, env=_english_locale_env(), cwd=run_dir, timeout=timeout
        )
    except subprocess.TimeoutExpired as exc:
        (run_dir / f"stdout_{log_name}.log").write_bytes(exc.stdout or b"")
        (run_dir / f"stderr_{log_name}.log").write_bytes(exc.stderr or b"")
        return {"exit_code": None, "timed_out": True, "seconds": time.perf_counter() - start}
    (run_dir / f"stdout_{log_name}.log").write_bytes(proc.stdout)
    (run_dir / f"stderr_{log_name}.log").write_bytes(proc.stderr)
    return {"exit_code": proc.returncode, "timed_out": False, "seconds": time.perf_counter() - start}


def export_points(engine: Path, stl: Path, run_dir: Path, timeout: float) -> dict:
    """Points-only fast path, the same command export_support_points builds."""
    points_path = run_dir / "pts.json"
    cmd = [str(engine), "--export-support-points", str(points_path),
           "--load", str(run_dir / "config.ini"), str(stl)]
    result = run_engine(cmd, run_dir, timeout, "points")
    result.update(measure_points(points_path))
    return result


def export_support(engine: Path, stl: Path, run_dir: Path, timeout: float) -> dict:
    """Full support generation, as generate_supports runs it, keeping only the tree."""
    tree_path = run_dir / "tree.json"
    cmd = [str(engine), "--export-support-stl", "--output", str(run_dir / "model.sl1"),
           "--load", str(run_dir / "config.ini"),
           "--export-support-tree", str(tree_path), str(stl)]
    result = run_engine(cmd, run_dir, timeout, "support")
    result["tree"] = measure_tree(tree_path)
    return result


# ── measurements ──────────────────────────────────────────────────────────────

def load_json(path: Path) -> tuple:
    """(parsed engine output, None), or (None, reason) when a run cut the file
    short (timeout, crash mid-write) - the run is then judged a failure instead
    of aborting the whole matrix."""
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def measure_points(path: Path) -> dict:
    empty = {"points": 0, "island": 0, "slope": 0, "min_layer_xy_mm": None, "non_finite": 0}
    if not path.is_file():
        return {**empty, "points_file": False}
    data, error = load_json(path)
    if error is None and not isinstance(data, dict):
        error = "top level is not a JSON object"
    if error is not None:
        return {**empty, "points_file": True, "parse_error": error}
    points = data.get("points", [])
    by_type: dict = {}
    for p in points:
        by_type[p.get("type")] = by_type.get(p.get("type"), 0) + 1
    return {
        "points": len(points),
        "island": by_type.get("island", 0),
        "slope": by_type.get("slope", 0),
        "min_layer_xy_mm": closest_same_layer_xy(points),
        "non_finite": _non_finite(points),
        "points_file": True,
    }


def closest_same_layer_xy(points: list):
    """Smallest XY distance between two points on the same detection layer.
    A point with a null or non-finite coordinate is left out; measure_points
    counts it as non_finite and judge() fails the run on it."""
    layers: dict = {}
    for p in points:
        pos = p.get("pos")
        if not isinstance(pos, list) or len(pos) != 3 or _non_finite(pos):
            continue
        x, y, z = pos
        layers.setdefault(round(z / SUPPORT_DETECTION_LAYER_HEIGHT), []).append((x, y))
    best = None
    for xy in layers.values():
        if len(xy) < 2:
            continue
        distances, _ = cKDTree(np.asarray(xy)).query(xy, k=2)
        nearest = float(distances[:, 1].min())
        best = nearest if best is None else min(best, nearest)
    return best


def _non_finite(value) -> int:
    """Count numbers that are NaN or infinite. JSON writers emit NaN as null, so
    a null where a number belongs counts too."""
    if value is None:
        return 1
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return 0 if math.isfinite(value) else 1
    if isinstance(value, list):
        return sum(_non_finite(v) for v in value)
    if isinstance(value, dict):
        return sum(_non_finite(v) for v in value.values())
    return 0


def measure_tree(path: Path) -> dict:
    if not path.is_file():
        return {"tree_file": False}
    tree, error = load_json(path)
    if error is None and not isinstance(tree, dict):
        error = "top level is not a JSON object"
    if error is not None:
        return {"tree_file": True, "parse_error": error}
    sections = ("heads", "pillars", "junctions", "pedestals", "bridges")
    counts = {name: len(tree.get(name, [])) for name in sections}
    return {
        "tree_file": True,
        **counts,
        "non_finite": sum(_non_finite(tree.get(name, [])) for name in sections),
    }


# ── matrix ────────────────────────────────────────────────────────────────────

def plan(groups: set) -> list:
    """Every run to make, in order: (group, model, density, min_distance, full_support)."""
    runs = []
    for group, (model, pairs) in (("A", GROUP_A), ("B", GROUP_B)):
        if group in groups:
            runs += [(group, model, d, m, True) for d, m in pairs]
    if "C" in groups:
        for model in ("flat", "tilted"):
            for m in SWEEP_MIN_DISTANCES:
                runs += [("C", model, d, m, False) for d in SWEEP_DENSITIES]
    if "D" in groups:
        model, d, m = STRESS
        runs.append(("D", model, d, m, True))
    return runs


def execute(run: tuple, engine: Path, stls: dict, out_dir: Path, timeout: float) -> dict:
    group, model, density, min_distance, full = run
    run_id = f"{group}-{model}-d{density}-m{min_distance:g}"
    run_dir = out_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    write_config(run_dir / "config.ini", density, min_distance)

    record = {"id": run_id, "group": group, "model": model,
              "density": density, "min_distance": min_distance}
    # The stress run's point is the full pipeline; it skips the points-only pass.
    if group != "D":
        record["points_run"] = export_points(engine, stls[model], run_dir, timeout)
    if full:
        record["support_run"] = export_support(engine, stls[model], run_dir, timeout)

    reference = REFERENCE_POINTS.get(model, {}).get((density, min_distance)) if group in ("A", "B") else None
    if reference is not None:
        actual = record["points_run"]["points"]
        deviation = (actual - reference) / reference * 100.0
        record["reference_points"] = reference
        record["deviation_pct"] = deviation
        record["reference_warning"] = abs(deviation) > REFERENCE_WARN_PCT
    if full and "points_run" in record:
        heads = record["support_run"]["tree"].get("heads")
        points = record["points_run"]["points"]
        record["head_point_ratio"] = (heads / points) if heads is not None and points else None
    return record


def _run_failures(label: str, result: dict, need_points: bool) -> list:
    if result["timed_out"]:
        return [f"{label}: TIMEOUT after {result['seconds']:.0f}s"]
    failures = []
    if result["exit_code"] != 0:
        failures.append(f"{label}: exit code {result['exit_code']}")
    if need_points:
        if result.get("parse_error"):
            failures.append(f"{label}: points file unreadable ({result['parse_error']})")
        if result.get("points", 0) <= 0:
            failures.append(f"{label}: no support points")
        if result.get("non_finite"):
            failures.append(f"{label}: {result['non_finite']} non-finite values in the points file")
    return failures


def judge(records: list) -> tuple:
    failures, warnings = [], []
    for r in records:
        if "points_run" in r:
            failures += _run_failures(f"{r['id']} points", r["points_run"], True)
        if "support_run" in r:
            failures += _run_failures(f"{r['id']} support", r["support_run"], False)
            tree = r["support_run"]["tree"]
            if not tree.get("tree_file"):
                failures.append(f"{r['id']} support: no support_tree.json")
            elif tree.get("parse_error"):
                failures.append(f"{r['id']} support: support_tree.json unreadable ({tree['parse_error']})")
            else:
                if tree["non_finite"]:
                    failures.append(f"{r['id']} support: {tree['non_finite']} non-finite values in the tree")
                # Group D has no points pass, so it is checked too: an empty tree
                # on the 50 mm box is never right. Zero points has already failed
                # in the points pass and is not reported twice.
                if r.get("points_run", {}).get("points") != 0:
                    for part in ("heads", "pillars"):
                        if tree[part] == 0:
                            failures.append(f"{r['id']} support: no {part} in the tree")
        if r.get("reference_warning"):
            warnings.append(
                f"{r['id']}: {r['points_run']['points']} points vs reference "
                f"{r['reference_points']} ({r['deviation_pct']:+.1f}%)"
            )

    sweeps: dict = {}
    for r in records:
        if r["group"] == "C":
            sweeps.setdefault((r["model"], r["min_distance"]), []).append(r)
    for (model, md), sweep in sweeps.items():
        sweep.sort(key=lambda r: r["density"])
        # Against the running peak, not the previous step, so a slow slide made
        # of small drops still adds up to a failure.
        peak = None
        for cur in sweep:
            points = cur["points_run"]["points"]
            if peak and points < peak["points_run"]["points"] * (1 - MONOTONIC_DROP_PCT / 100):
                failures.append(
                    f"C {model} min_distance={md:g}: {points} points at {cur['density']}% is more "
                    f"than {MONOTONIC_DROP_PCT:g}% below {peak['points_run']['points']} at "
                    f"{peak['density']}%"
                )
            if peak is None or points > peak["points_run"]["points"]:
                peak = cur
    return failures, warnings


# ── report ────────────────────────────────────────────────────────────────────

def git_state(path: Path) -> dict:
    def git(*args):
        proc = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True)
        return proc.stdout.strip() if proc.returncode == 0 else None

    status = git("status", "--porcelain")
    return {"head": git("rev-parse", "HEAD"), "clean": status == "" if status is not None else None}


def print_summary(records: list) -> None:
    header = (f"{'run':<26} {'exit':>10} {'sec':>7} {'pts':>6} {'isl':>5} {'slp':>5} "
              f"{'ref':>6} {'dev%':>7} {'minXY':>7} {'heads':>6} {'h/p':>5}")
    print(header)
    print("-" * len(header))
    for r in records:
        pr = r.get("points_run", {})
        sr = r.get("support_run", {})
        main = pr or sr
        exit_code = "TIME" if main.get("timed_out") else main.get("exit_code")
        seconds = pr.get("seconds", 0.0) + sr.get("seconds", 0.0)
        ref = r.get("reference_points")
        dev = r.get("deviation_pct")
        min_xy = pr.get("min_layer_xy_mm")
        heads = sr.get("tree", {}).get("heads") if sr else None
        ratio = r.get("head_point_ratio")
        flag = "  ! ref" if r.get("reference_warning") else ""
        print(
            f"{r['id']:<26} {str(exit_code):>10} {seconds:>7.1f} {str(pr.get('points', '-')):>6} "
            f"{str(pr.get('island', '-')):>5} {str(pr.get('slope', '-')):>5} "
            f"{str(ref) if ref is not None else '-':>6} "
            f"{f'{dev:+.1f}' if dev is not None else '-':>7} "
            f"{f'{min_xy:.3f}' if min_xy is not None else '-':>7} "
            f"{str(heads) if heads is not None else '-':>6} "
            f"{f'{ratio:.2f}' if ratio is not None else '-':>5}{flag}"
        )


# ── main ──────────────────────────────────────────────────────────────────────

def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--engine", type=Path, default=SLICER_ENGINE_CLI,
                        help=f"slicer-engine executable (default: {SLICER_ENGINE_CLI})")
    parser.add_argument("--out", type=Path,
                        help="output directory outside the repository (default: a new temp dir)")
    parser.add_argument("--timeout", type=float, default=600.0,
                        help="seconds before one engine run is killed and recorded as TIMEOUT")
    parser.add_argument("--reference-box", type=Path,
                        help="STL of the box DS-slicer was given; only its extent is compared")
    parser.add_argument("--only", action="append", choices=GROUPS,
                        help="run only this group; repeat for several (default: all)")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    sys.stdout.reconfigure(errors="replace")
    args = parse_args(argv)
    engine = args.engine.resolve()
    if not engine.is_file():
        print(f"engine not found: {engine}", file=sys.stderr)
        return 2
    if args.out is not None:
        out_dir = args.out.resolve()
        if out_dir == REPO_ROOT or REPO_ROOT in out_dir.parents:
            print(f"--out must be outside the repository: {out_dir}", file=sys.stderr)
            return 2
        out_dir.mkdir(parents=True, exist_ok=True)
    else:
        out_dir = Path(tempfile.mkdtemp(prefix="verify-slicer-density-"))
    if args.reference_box is not None and not args.reference_box.is_file():
        print(f"reference box not found: {args.reference_box}", file=sys.stderr)
        return 2
    groups = set(args.only or GROUPS)

    warnings: list = []
    models_dir = out_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    stls = {}
    for name, build in (("flat", flat_box), ("tilted", tilted_box)):
        normals, vertices = build()
        stls[name] = models_dir / f"{name}.stl"
        fx.write_binary_stl(stls[name], normals, vertices, f"verify_slicer_density {name}")
    reference_box = check_reference_box(args.reference_box, warnings) if args.reference_box else None

    engine_dir = engine.parent
    print(f"engine: {engine}")
    print(f"output: {out_dir}")
    records = []
    for run in plan(groups):
        record = execute(run, engine, stls, out_dir, args.timeout)
        records.append(record)
        print(f"  done {record['id']}", flush=True)

    failures, run_warnings = judge(records)
    warnings += run_warnings
    report = {
        "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "engine": {
            "path": str(engine),
            "exe_sha256": fx.sha256_file(engine),
            "dll_sha256": fx.sha256_file(engine_dir / "slicer_core.dll")
            if (engine_dir / "slicer_core.dll").is_file() else None,
        },
        "fork": git_state(REPO_ROOT / "third_party" / "prusaslicer_fork"),
        "settings": {
            "head_front_diameter": HEAD_FRONT_DIAMETER,
            "pillar_diameter": PILLAR_DIAMETER,
            "layer_height": SUPPORT_DETECTION_LAYER_HEIGHT,
            "box_mm": BOX_SIZE_MM,
            "tilt_deg_about_y": TILT_DEG,
            "monotonic_drop_pct": MONOTONIC_DROP_PCT,
            "timeout_s": args.timeout,
            "groups": sorted(groups),
        },
        "reference_box": reference_box,
        "runs": records,
        "failures": failures,
        "warnings": warnings,
        "passed": not failures,
    }
    report_path = out_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print()
    print_summary(records)
    print()
    for w in warnings:
        print(f"WARNING: {w}")
    for f in failures:
        print(f"FAIL: {f}")
    print(f"report: {report_path}")
    print("PASSED" if not failures else f"FAILED ({len(failures)} hard check(s))")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())

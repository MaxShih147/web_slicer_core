"""Time support-tree steps 3 and 4 (routing to ground, routing to the model) from
the engine's own log timestamps, and count the heads the engine deleted.

The acceptance cases of openspec change sla-head-bridge-clearance are built in:
each gets a config.ini written from BASE_CONFIG plus its overrides.

Every case IMPORTS a fixed support point list. Point generation and pinhead
placement are not deterministic run to run on every model (China-dragon1 came
out with 817 or 818 points), and that is not this change's to fix; with the
points fixed, the heads come out identical and only steps 3 and 4 can differ.
The lists are exported once per input into <inputs>/pts_<input>.json and then
reused: pass the baseline's --inputs later so the before and after engines are
fed exactly the same points. The mixed-size cases draw every
head_back_radius_mm from 0.25 / 0.4 / 0.75 by random.seed(<seed>) on the
02_e5_d400 list.

Per case: <out>/<case>/config.ini, runs/bench<N>/ (engine output and log), and
bench.json with every run's step durations, T = steps 3 + 4 (median over the
runs), the deleted-head count and each tree's SHA-256.

Usage: bench_steps.py --engine EXE --out DIR [--cases all|NAME,...] [--reps 3]
                      [--inputs DIR]
"""
import argparse
import datetime as dt
import hashlib
import json
import random
import re
import statistics
import subprocess
import sys
from pathlib import Path

STL = Path(r"D:\tool\stl")

# The config every exploration run used (the agent's generated SLA config,
# default support parameters). Cases override support keys only.
BASE_CONFIG = """\
# Generated SLA config
layer_height = 0.15
initial_layer_height = 0.15
exposure_time = 10.0
initial_exposure_time = 15.0
supports_enable = 1
support_head_front_diameter = 0.4
support_head_penetration = 0.2
support_pillar_diameter = 1.0
support_points_density_relative = 100
support_points_min_distance = 0.0
support_object_elevation = 5.0
support_critical_angle = 45.0
support_auxiliary_pillars = 1
support_head_width = 1.0
support_base_diameter = 4.0
support_base_height = 1.0
support_bracing_angle = 45.0
support_max_bridge_length = 15.0
support_max_pillar_link_distance = 10.0
support_max_bridges_on_pillar = 3
support_small_pillar_diameter_percent = 50.0
support_buildplate_only = 0
support_base_safety_distance = 1.0
support_pillar_connection_mode = dynamic
support_tree_type = default
support_enforcers_only = 0
pad_enable = 0
pad_wall_thickness = 2.0
pad_wall_height = 0.0
pad_brim_size = 1.6
pad_max_merge_distance = 50.0
pad_around_object = 0
pad_around_object_everywhere = 0
pad_object_gap = 1.0
pad_object_connector_stride = 10.0
pad_object_connector_width = 0.5
pad_object_connector_penetration = 0.3
pad_wall_slope = 90.0
hollowing_enable = 0
hollowing_min_thickness = 3.0
hollowing_quality = 0.5
hollowing_closing_distance = 2.0
anti_aliasing = 1
anti_aliasing_level = 0
gray_level = 0
blur = 0
gamma_correction = 1.0
printer_model =
sla_material_settings_id =
display_pixels_x = 2560
display_pixels_y = 1440
display_width = 120.0
display_height = 68.0
display_orientation = landscape
center_x = 60.0
center_y = 34.0
shrinkage_compensation = 0
shrinkage_compensation_x = 100.0
shrinkage_compensation_y = 100.0
shrinkage_compensation_z = 100.0
tolerance_compensation = 0
tolerance_compensation_a = 0.0
tolerance_compensation_b = 0.0
bottom_tolerance_compensation = 0
bottom_tolerance_compensation_a = 0.0
bottom_tolerance_compensation_b = 0.0
bottom_layer_count = 6
retract_distance = None
bottom_retract_distance = None
retract_second_distance = None
bottom_retract_second_distance = None
bed_shape = 120.0,68.0
printer_technology = SLA
"""

E10 = {"support_object_elevation": "10.0"}
E10_D400 = {"support_object_elevation": "10.0", "support_points_density_relative": "400"}
MIXED = {"support_points_density_relative": "400", "support_object_elevation": "5.0"}
MIXED_RADII = (0.25, 0.4, 0.75)

# point list name -> (model, config it is exported with)
INPUTS = {
    "02_e5_d100":    (STL / "02.stl", {}),
    "02_e10_d100":   (STL / "02.stl", E10),
    "02_e10_d400":   (STL / "02.stl", E10_D400),
    "02_e5_d400":    (STL / "02.stl", MIXED),
    "China-dragon1": (STL / "China-dragon1.stl", {}),
    "Pikachu":       (STL / "Pikachu.stl", {}),
}

# case -> (model, config overrides, point list name, mixed-size seed or None)
CASES = {
    "02_e5_d100":    (STL / "02.stl", {}, "02_e5_d100", None),
    "02_e10_d100":   (STL / "02.stl", E10, "02_e10_d100", None),
    "02_e10_d400":   (STL / "02.stl", E10_D400, "02_e10_d400", None),
    **{f"02_mixed_s{s}": (STL / "02.stl", MIXED, "02_e5_d400", s) for s in range(1, 6)},
    "China-dragon1": (STL / "China-dragon1.stl", {}, "China-dragon1", None),
    "Pikachu":       (STL / "Pikachu.stl", {}, "Pikachu", None),
}

STEPS = ("Routing to ground", "Routing supports to model surface",
         "Interconnecting pillars", "Merging support mesh")
MARK = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+)\].*"
                  r"Generating support tree: (.+?) WorkingSet")
DELETED = "Failed to route model facing support point"


def config_text(overrides):
    lines = []
    for line in BASE_CONFIG.splitlines():
        k = line.split("=", 1)[0].strip()
        lines.append(f"{k} = {overrides[k]}" if k in overrides else line)
    return "\n".join(lines) + "\n"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def engine_fingerprint(engine):
    """SHA-256 of the launcher and of slicer_core.dll beside it, which is where
    the engine code lives: a rebuild can leave the launcher byte-identical."""
    exe = Path(engine)
    core = exe.with_name("slicer_core.dll")
    return {"exe": sha256(exe), "slicer_core_dll": sha256(core) if core.exists() else None}


def input_points(engine, inputs, name):
    """The fixed point list `name`: reused when present, else exported once."""
    inputs = Path(inputs)
    pts = inputs / f"pts_{name}.json"
    if pts.exists():
        return pts
    inputs.mkdir(parents=True, exist_ok=True)
    model, overrides = INPUTS[name]
    cfg = inputs / f"config_{name}.ini"
    cfg.write_text(config_text(overrides), encoding="utf-8", newline="\n")
    p = subprocess.run([str(engine), "--export-support-points", str(pts), "--load", str(cfg),
                        str(model)], capture_output=True, text=True,
                       errors="replace", cwd=inputs, timeout=1800)
    if p.returncode != 0 or not pts.exists():
        sys.exit(f"exporting support points for {name} failed (exit {p.returncode}):\n"
                 f"{p.stderr[-2000:]}")
    return pts


def prepare_case(name, out, engine, inputs):
    """Write the case's config and point list; return (model, dir, cfg, pts)."""
    model, overrides, src, seed = CASES[name]
    d = Path(out) / name
    d.mkdir(parents=True, exist_ok=True)
    cfg = d / "config.ini"
    cfg.write_text(config_text(overrides), encoding="utf-8", newline="\n")
    pts = input_points(engine, inputs, src)
    if seed is not None:
        data = json.loads(pts.read_text(encoding="utf-8"))
        random.seed(seed)
        for p in data["points"]:
            p["head_back_radius_mm"] = random.choice(MIXED_RADII)
        pts = d / f"points_s{seed}.json"
        pts.write_text(json.dumps(data), encoding="utf-8", newline="\n")
    return model, d, cfg, pts


def run_engine(engine, model, cfg, pts, rundir, threads=None):
    """One generation. Returns a dict of exit code, step durations, deleted
    heads, the tree's path and hash."""
    rundir = Path(rundir)
    rundir.mkdir(parents=True, exist_ok=True)
    tree = rundir / "tree.json"
    cmd = [str(engine), "--loglevel", "4"]
    if threads:
        cmd += ["--threads", str(threads)]
    cmd += ["--export-support-stl", "--output", str(rundir / "m.sl1"), "--load", str(cfg)]
    if pts:
        cmd += ["--import-support-points", str(pts)]
    cmd += ["--export-support-tree", str(tree), str(model)]
    p = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                       cwd=rundir, timeout=3600)
    log = p.stdout + p.stderr
    (rundir / "engine.log").write_text(log, encoding="utf-8", newline="\n")
    marks = {}
    for line in log.splitlines():
        m = MARK.match(line)
        if m and m.group(2) not in marks:
            marks[m.group(2)] = dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S.%f")
    dur = {}
    for a, b in zip(STEPS, STEPS[1:]):
        if a in marks and b in marks:
            dur[a] = (marks[b] - marks[a]).total_seconds()
    t34 = None
    if STEPS[0] in marks and STEPS[2] in marks:
        t34 = (marks[STEPS[2]] - marks[STEPS[0]]).total_seconds()
    return {"exit": p.returncode, "threads": threads, "steps_s": dur, "T_s": t34,
            "deleted_heads": log.count(DELETED),
            "tree": str(tree) if tree.exists() else None,
            "tree_sha256": sha256(tree) if tree.exists() else None}


def pick_cases(arg):
    if arg == "all":
        return list(CASES)
    names = [c.strip() for c in arg.split(",") if c.strip()]
    bad = [c for c in names if c not in CASES]
    if bad:
        sys.exit(f"unknown case(s) {bad}; known: {', '.join(CASES)}")
    return names


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--engine", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cases", default="all")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--inputs", help="fixed point lists (reuse the baseline's); "
                                     "default <out>/inputs")
    a = ap.parse_args()
    names = pick_cases(a.cases)
    inputs = a.inputs or str(Path(a.out) / "inputs")
    for name in names:
        model, d, cfg, pts = prepare_case(name, a.out, a.engine, inputs)
        runs = [run_engine(a.engine, model, cfg, pts, d / "runs" / f"bench{i + 1}")
                for i in range(a.reps)]
        ok = [r for r in runs if r["exit"] == 0 and r["T_s"] is not None]
        res = {"case": name, "model": str(model), "engine": str(a.engine),
               "engine_sha256": engine_fingerprint(a.engine), "reps": a.reps,
               "points": str(pts), "points_sha256": sha256(pts),
               "T_median_s": statistics.median(r["T_s"] for r in ok) if ok else None,
               "step_median_s": {s: statistics.median(r["steps_s"][s] for r in ok)
                                 for s in STEPS[:-1] if ok and all(s in r["steps_s"] for r in ok)},
               "deleted_heads": [r["deleted_heads"] for r in runs],
               "runs": runs}
        (d / "bench.json").write_text(json.dumps(res, indent=1), encoding="utf-8", newline="\n")
        t = res["T_median_s"]
        print(f"{name}: T(3+4) median = {t * 1000:.1f} ms" if t is not None else f"{name}: FAILED",
              f"| deleted heads {res['deleted_heads']} | exits {[r['exit'] for r in runs]}")


if __name__ == "__main__":
    main()

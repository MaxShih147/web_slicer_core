#!/usr/bin/env python
"""Auto-orient regression self-check against the verified-good guide models.

Re-runs surgical-guide auto-orientation on ``test-models/guides/good/guide-*.stl``
and compares the selected drill end-face normal to a stored baseline. Catches
regressions where a code change makes a previously-correct model pick a
different face.

The comparison key is the **decision-face normal** (pre-rotation): a true
regression is when the algorithm now selects a *different* face (dot < 0.99).
Rotation angle is also compared but only as a soft signal — it depends on the
entrance-end tiebreak stage (which face points down), reported as PASS* so it
isn't confused with a face-selection regression.

Usage:
  python scripts/check_baseline.py            # check against baseline.json
  python scripts/check_baseline.py --update   # (re)generate baseline.json
  python scripts/check_baseline.py --good DIR  # override good-models dir

Exit code: 0 = all pass, 1 = regression detected / baseline missing.
"""
import argparse
import glob
import json
import math
import os
import sys

import numpy as np
import trimesh

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent import auto_orient_surg_guide as ao  # noqa: E402

DEFAULT_GOOD = "/Users/max/repo_claude/DS-Online/test-models/guides/good"
DOT_PASS = 0.99    # decision-face normal cosine threshold
ROT_TOL = 1.0      # deg, soft tolerance for rotation comparison


def analyze(path):
    """Return the chosen drill end-face descriptor, or None if none detected."""
    m = trimesh.load(path)
    if isinstance(m, trimesh.Scene):
        m = trimesh.util.concatenate(m.dump())
    v = np.asarray(m.vertices, np.float32)
    f = np.asarray(m.faces, np.uint32)

    mesh = ao._weld_and_build(v, f)
    patches = ao._grow_patches(mesh)
    drill = [P for P in patches
             if len(P.faces) >= 5 and P.area > 0 and ao._is_drill_patch_by_edges(mesh, P)]
    best = ao._pick_best_drill_patch_stage3(drill)
    detail = ao.compute_auto_orientation_surg_guide_detail(v, f)
    deg = [round(x * 180.0 / math.pi, 2) for x in detail["rotation_rad"]]

    if best is None:
        # fallback model (no drill hole): baseline on the resulting orientation,
        # since there is no decision face to compare a normal against.
        return {"type": "fallback", "rotation_deg": deg, "candidates": 0}

    # normal model: baseline on the chosen drill-face normal (PCA outer diameter too)
    axis = ao._normalize(best.avg_normal)
    ex, ey = ao._build_orthonormal_basis(axis)
    vids = np.unique(mesh.fi[np.asarray(best.faces, np.int64)].reshape(-1).astype(np.int64))
    pts = mesh.v[vids].astype(np.float64) - best.center.astype(np.float64)
    p2 = np.stack([pts @ ex.astype(np.float64), pts @ ey.astype(np.float64)], axis=1)
    p2 -= p2.mean(axis=0)
    _ev, vec = np.linalg.eigh(np.cov(p2.T))
    pr = p2 @ vec
    ext = pr.max(axis=0) - pr.min(axis=0)
    return {
        "type": "normal",
        "normal": [float(x) for x in best.avg_normal],
        "center": [round(float(x), 3) for x in best.center],
        "outer_diam": round(float(ext.max()), 2),
        "rotation_deg": deg,
        "candidates": len(drill),
    }


def cmd_update(files, json_path):
    base = {}
    for path in files:
        name = os.path.basename(path)
        r = analyze(path)
        base[name] = r
        if r["type"] == "fallback":
            print(f"  {name}: [FALLBACK] rot={r['rotation_deg']}")
        else:
            n = r["normal"]
            print(f"  {name}: n=({n[0]:+.3f},{n[1]:+.3f},{n[2]:+.3f}) Ø={r['outer_diam']}")
    with open(json_path, "w") as fp:
        json.dump(base, fp, indent=2, ensure_ascii=False)
    print(f"\n✅ wrote baseline for {len(base)} models -> {json_path}")
    return 0


def cmd_check(files, json_path, good):
    if not os.path.exists(json_path):
        print(f"baseline missing: {json_path}\nrun with --update first", file=sys.stderr)
        return 1
    with open(json_path) as fp:
        base = json.load(fp)

    fails = []
    for path in files:
        name = os.path.basename(path)
        if name not in base:
            print(f"[NEW ] {name}: not in baseline (run --update to add)")
            continue
        b = base[name]
        r = analyze(path)
        bt = b.get("type", "normal")
        rt = r["type"]
        if bt == "fallback" or rt == "fallback":
            if bt != rt:
                fails.append(name)
                print(f"[FAIL ] {name}: type changed {bt} -> {rt}")
                continue
            rot_ok = all(abs(a - bb) < ROT_TOL
                         for a, bb in zip(r["rotation_deg"], b["rotation_deg"]))
            if rot_ok:
                print(f"[PASS ] {name}: [fallback] rotation match {r['rotation_deg']}")
            else:
                fails.append(name)
                print(f"[FAIL ] {name}: [fallback] rotation changed "
                      f"{b['rotation_deg']} -> {r['rotation_deg']}")
            continue
        dot = float(np.dot(r["normal"], b["normal"]))
        if dot >= DOT_PASS:
            rot_ok = all(abs(a - bb) < ROT_TOL
                         for a, bb in zip(r["rotation_deg"], b["rotation_deg"]))
            if rot_ok:
                print(f"[PASS ] {name}: dot={dot:.4f} Ø={r['outer_diam']}")
            else:
                print(f"[PASS*] {name}: dot={dot:.4f} (face OK, rotation changed "
                      f"{b['rotation_deg']} -> {r['rotation_deg']})")
        else:
            fails.append(name)
            print(f"[FAIL ] {name}: decision-face CHANGED dot={dot:.4f} "
                  f"(was {b['normal']}, now {r['normal']})")

    missing = [n for n in base if not os.path.exists(os.path.join(good, n))]
    npass = len(files) - len(fails)
    print(f"\n=== {npass}/{len(files)} pass, {len(fails)} regressions ===")
    if missing:
        print(f"baseline models with no file: {missing}")
    if fails:
        print(f"REGRESSIONS: {fails}")
    print("note: PASS* = same face selected but rotation differs "
          "(entrance-tiebreak stage, separate from face detection)")
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--update", action="store_true", help="(re)generate baseline.json")
    ap.add_argument("--good", default=DEFAULT_GOOD, help="good-models directory")
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.good, "guide-*.stl")))
    if not files:
        print(f"no guide-*.stl found in {args.good}", file=sys.stderr)
        return 1
    json_path = os.path.join(args.good, "baseline.json")

    if args.update:
        return cmd_update(files, json_path)
    return cmd_check(files, json_path, args.good)


if __name__ == "__main__":
    sys.exit(main())

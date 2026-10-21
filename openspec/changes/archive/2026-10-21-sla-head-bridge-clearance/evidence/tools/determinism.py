"""Run one input N times with the engine's default threading and once with
--threads 1, and compare the support trees by hash.

Two hashes per run:
  tree        SHA-256 of the whole exported tree.json
  head_paths  SHA-256 of what steps 3 and 4 produce - heads, every pillar that
              is not an auxiliary one (without the bracing counts links/pairs),
              and every head / route bar - canonicalised as JSON. Bracing
              (truss, prop, auxiliary pillars) is left out: planar's own
              determinism is not this change's to guarantee, the head bars are
              (spec "兩階段排程須保證確定性").

Writes <out>/<case>/determinism.json. Cases, configs and the fixed point lists
are bench_steps.py's, so a difference here comes from step 3 onwards.

Usage: determinism.py --engine EXE --out DIR [--cases all|NAME,...] [--runs 4]
                      [--inputs DIR]
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_steps import engine_fingerprint, pick_cases, prepare_case, run_engine  # noqa: E402

PILLAR_KEYS = ("endpt", "height", "r_start", "r_end", "bridges", "head")
BAR_KEYS = ("startp", "endp", "r", "end_r", "a", "b", "kind", "reaches")


def head_paths_hash(tree_path):
    t = json.loads(Path(tree_path).read_text(encoding="utf-8"))
    sub = {
        "heads": t["heads"],
        "pillars": [{k: p[k] for k in PILLAR_KEYS if k in p}
                    for p in t["pillars"] if p.get("props", -1) < 0],
        "bars": [{k: b[k] for k in BAR_KEYS if k in b}
                 for b in t["bridges"] if b.get("kind") in ("head", "route")],
    }
    blob = json.dumps(sub, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--engine", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cases", default="all")
    ap.add_argument("--runs", type=int, default=4)
    ap.add_argument("--inputs", help="fixed point lists (reuse the baseline's); "
                                     "default <out>/inputs")
    a = ap.parse_args()
    names = pick_cases(a.cases)
    inputs = a.inputs or str(Path(a.out) / "inputs")
    for name in names:
        model, d, cfg, pts = prepare_case(name, a.out, a.engine, inputs)
        plan = [(f"mt{i + 1}", None) for i in range(a.runs)] + [("t1", 1)]
        runs = []
        for label, threads in plan:
            r = run_engine(a.engine, model, cfg, pts, d / "runs" / f"det_{label}", threads)
            r["label"] = label
            r["head_paths_sha256"] = head_paths_hash(r["tree"]) if r["tree"] else None
            runs.append(r)
        mt = [r for r in runs if r["threads"] is None]
        res = {
            "case": name, "engine": str(a.engine),
            "engine_sha256": engine_fingerprint(a.engine),
            "runs": runs,
            "distinct_tree": len({r["tree_sha256"] for r in runs}),
            "distinct_head_paths": len({r["head_paths_sha256"] for r in runs}),
            "distinct_tree_multithread": len({r["tree_sha256"] for r in mt}),
            "distinct_head_paths_multithread": len({r["head_paths_sha256"] for r in mt}),
        }
        (d / "determinism.json").write_text(json.dumps(res, indent=1), encoding="utf-8",
                                            newline="\n")
        print(f"{name}: distinct trees {res['distinct_tree']}/{len(runs)}, "
              f"distinct head paths {res['distinct_head_paths']}/{len(runs)} "
              f"(multithread only: {res['distinct_tree_multithread']} / "
              f"{res['distinct_head_paths_multithread']}) | exits {[r['exit'] for r in runs]}")


if __name__ == "__main__":
    main()

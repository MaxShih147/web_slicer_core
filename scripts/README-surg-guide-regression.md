# Surgical-Guide Auto-Orient — Regression Testing

How to run the regression self-check for the surgical-guide auto-orientation
algorithm (`agent/auto_orient_surg_guide.py`), and how to evolve the algorithm
safely.

## Test models (NOT in git)

The verified-good guide models live in
`DS-Online/test-models/guides/good/` and are **gitignored** — they are patient
data and large STLs, so they must never be committed.

Get the whole `test-models/` folder from the internal shared location and drop
it at `DS-Online/test-models/`:

> internal shared location: **<fill in — NAS / cloud drive path>**

It contains:

- `good/guide-01..NN.stl` — anonymized models (`guide-<n>.stl`)
- `good/baseline.json` — machine-readable baseline (used by the checker)
- `good/REGRESSION_BASELINE.md` — human-readable baseline (original names,
  decision-face normals, rotations) — keep this private (contains patient names)

## Model classes (see REGRESSION_BASELINE.md)

| class | what it exercises | baseline compares |
|-------|-------------------|-------------------|
| standard | normal drill-hole detection | decision-face normal |
| critical / entrance | hard "which end faces down" cases (concave vote) | decision-face normal |
| near lower diameter limit | outer Ø close to the 5.5 mm minimum | decision-face normal |
| fallback / no-hole | no drill detected → concave-vote orientation | rotation (no decision face) |

## Workflow when changing the algorithm

Run from `web_slicer_core/` (needs the `.venv` with trimesh + numpy):

```bash
.venv/bin/python scripts/check_baseline.py            # check against baseline
.venv/bin/python scripts/check_baseline.py --update   # regenerate after a deliberate change
```

Reading the result:

- `[PASS ]` — decision face unchanged (and rotation unchanged)
- `[PASS*]` — same face selected, rotation changed (entrance / fallback stage) —
  verify by eye whether the new orientation is better or worse
- `[FAIL ]` — decision face changed (dot < 0.99) or a candidate was lost — a regression

Process:

1. **Before** changing code: confirm all `PASS` (clean baseline).
2. Change the algorithm, **re-run** the check.
3. A `FAIL` must be fixed — or, if the new behaviour is genuinely correct,
   `--update` the baseline (and note why in the commit).
4. **New bad case fixed** → copy its STL into `good/` (renamed `guide-<n>.stl`),
   `--update`, so it is protected by the regression suite forever. This is how
   the suite grew (standard → + critical → + fallback).

## Debug visualization

Set `meshManager.surgGuideDebug = true` (default `false`) in the frontend to
overlay candidate (yellow) / decision (red) / concave (orange) faces + drill
cylinders (cyan) on the model. Off by default — when off, the backend returns
only `rotation_rad` (saves the ~179 KB debug-mesh payload per call).

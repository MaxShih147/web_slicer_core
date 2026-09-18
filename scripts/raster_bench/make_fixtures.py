#!/usr/bin/env python
"""Build the raster benchmark fixtures described by ``manifest.json``.

Spec: ``raster-performance-baseline`` (openspec change optimize-raster-canvas-scan).

Two modes, both run from the repository root:

  python scripts/raster_bench/make_fixtures.py [--models DIR] [--case ID ...]
      Write ``work/fixtures/<case>/{model.stl,config.ini,fixture.json}`` for the
      selected cases (default: all). Layout cases need the source models, found
      under --models or $RASTER_BENCH_MODELS by file name and verified by
      SHA-256. The slab case is generated in code and needs no models.
      The first build records ``model.sha256`` and ``model.geometry_sha256`` in
      manifest.json; later builds must reproduce both or are refused.

  python scripts/raster_bench/make_fixtures.py --freeze-support --engine DIR [--case ID ...]
      Generate ``support.stl`` once for every selected case whose manifest entry
      says ``"support": {"mode": "frozen"}`` (default: all such cases), using the
      pre-change engine in DIR, and write its SHA-256 back into manifest.json
      together with ``model_sha256``, the model it was frozen for.

Determinism is the point of this tool: the same source models always produce
byte-identical ``model.stl`` files. STL bytes are therefore read and written with
numpy directly instead of going through trimesh, whose loader reorders and merges
geometry in version-dependent ways.

Refusals are deliberate. An existing fixture whose bytes differ from what would
be generated, an existing support.stl, or a manifest that already records a
support hash all stop the tool instead of overwriting: silently replacing any of
them would change the basis every later comparison is made against.

Exit code: 0 = success, 1 = refused or failed, 2 = usage error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

BENCH_DIR = Path(__file__).resolve().parent
REPO_ROOT = BENCH_DIR.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agent.models import SLAConfig  # noqa: E402
from agent.sla_operations import (  # noqa: E402
    SUPPORT_DETECTION_LAYER_HEIGHT,
    _english_locale_env,
    generate_config_ini,
)
from agent.support_classifier import classify_support_result  # noqa: E402

MANIFEST_PATH = BENCH_DIR / "manifest.json"
DEFAULT_WORK_DIR = BENCH_DIR / "work"
MODELS_ENV = "RASTER_BENCH_MODELS"
ENGINE_EXE = "slicer-engine.exe" if os.name == "nt" else "slicer-engine"

_STL_HEADER_SIZE = 80
_STL_DTYPE = np.dtype([
    ("normal", "<f4", (3,)),
    ("vertices", "<f4", (3, 3)),
    ("attr", "<u2"),
])


class FixtureError(Exception):
    """A refusal or failure that should end the run with exit code 1."""


# ── manifest ──────────────────────────────────────────────────────────────────

def load_manifest(path: Path = MANIFEST_PATH) -> dict:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    ids = [case["id"] for case in manifest["cases"]]
    if len(ids) != len(set(ids)):
        raise FixtureError(f"{path.name}: duplicate case ids in {ids}")
    for case in manifest["cases"]:
        if case["machine"] not in manifest["machines"]:
            raise FixtureError(f"case {case['id']}: unknown machine {case['machine']!r}")
        geometry = case["geometry"]
        if geometry["type"] == "layout" and geometry["source"] not in manifest["sources"]:
            raise FixtureError(f"case {case['id']}: unknown source {geometry['source']!r}")
        if geometry["type"] not in ("layout", "slab"):
            raise FixtureError(f"case {case['id']}: unknown geometry type {geometry['type']!r}")
        if case["support"]["mode"] not in ("frozen", "none"):
            raise FixtureError(f"case {case['id']}: unknown support mode {case['support']['mode']!r}")
        model = case.get("model")
        if not isinstance(model, dict) or set(model) != {"sha256", "geometry_sha256"} \
                or (model["sha256"] is None) != (model["geometry_sha256"] is None):
            raise FixtureError(
                f"case {case['id']}: 'model' must be {{\"sha256\", \"geometry_sha256\"}}, both null or both set"
            )
        if case["support"]["sha256"] is not None and (
                model["sha256"] is None or case["support"].get("model_sha256") != model["sha256"]):
            raise FixtureError(
                f"case {case['id']}: frozen support is bound to model {case['support'].get('model_sha256')}, "
                f"but the manifest model is {model['sha256']}"
            )
    return manifest


def geometry_sha256(manifest: dict, case: dict) -> str:
    """Digest of everything that defines a case's model.stl: its geometry entry and source model hash.

    Recorded next to the model hash so an edited layout is detected even before
    anyone rebuilds the fixture.
    """
    geometry = case["geometry"]
    source_sha = manifest["sources"][geometry["source"]]["sha256"] if geometry["type"] == "layout" else None
    payload = json.dumps({"geometry": geometry, "source_sha256": source_sha}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def save_manifest(manifest: dict, path: Path = MANIFEST_PATH) -> None:
    _atomic_write_bytes(path, (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def select_cases(manifest: dict, wanted: list[str] | None) -> list[dict]:
    if not wanted:
        return list(manifest["cases"])
    by_id = {case["id"]: case for case in manifest["cases"]}
    unknown = [case_id for case_id in wanted if case_id not in by_id]
    if unknown:
        raise FixtureError(f"unknown case id(s): {unknown}; known: {sorted(by_id)}")
    return [by_id[case_id] for case_id in wanted]


# ── files ─────────────────────────────────────────────────────────────────────

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def place_generated(target: Path, generated: Path, what: str) -> str:
    """Move a freshly generated file into place, never replacing different bytes.

    Returns "created" or "unchanged". Re-running the tool is safe because
    generation is deterministic; a mismatch means the fixture was built from
    something else and must not be overwritten behind the user's back.
    """
    new_sha = sha256_file(generated)
    if target.exists():
        old_sha = sha256_file(target)
        generated.unlink()
        if old_sha != new_sha:
            raise FixtureError(
                f"refusing to overwrite {what} {target}: existing sha256 {old_sha} "
                f"differs from regenerated {new_sha}. Delete it manually if the change is intended."
            )
        return "unchanged"
    os.replace(generated, target)
    return "created"


# ── source models ─────────────────────────────────────────────────────────────

def resolve_models_dir(cli_value: str | None) -> Path:
    raw = cli_value or os.environ.get(MODELS_ENV, "").strip()
    if not raw:
        raise FixtureError(
            f"no models directory: pass --models DIR or set {MODELS_ENV}. "
            "The tool never guesses a default location."
        )
    models_dir = Path(raw)
    if not models_dir.is_dir():
        raise FixtureError(f"models directory does not exist: {models_dir}")
    return models_dir


def find_source(models_dir: Path, source: dict) -> Path:
    """Locate a source model by exact file name anywhere under models_dir and verify it."""
    filename = source["filename"]
    matches = sorted(p for p in models_dir.rglob("*") if p.is_file() and p.name == filename)
    if not matches:
        raise FixtureError(f"source model {filename!r} not found under {models_dir}")
    if len(matches) > 1:
        listed = ", ".join(str(p) for p in matches)
        raise FixtureError(f"source model {filename!r} is ambiguous under {models_dir}: {listed}")
    actual = sha256_file(matches[0])
    if actual != source["sha256"]:
        raise FixtureError(
            f"source model {filename!r} sha256 mismatch: manifest {source['sha256']}, actual {actual}"
        )
    return matches[0]


# ── STL ───────────────────────────────────────────────────────────────────────

def read_binary_stl(path: Path) -> np.ndarray:
    data = path.read_bytes()
    if len(data) < _STL_HEADER_SIZE + 4:
        raise FixtureError(f"{path.name}: too short to be a binary STL")
    count = int(np.frombuffer(data, "<u4", 1, _STL_HEADER_SIZE)[0])
    expected = _STL_HEADER_SIZE + 4 + count * _STL_DTYPE.itemsize
    if len(data) != expected:
        raise FixtureError(
            f"{path.name}: not a well-formed binary STL ({len(data)} bytes, "
            f"header declares {count} triangles = {expected} bytes)"
        )
    return np.frombuffer(data, _STL_DTYPE, count, _STL_HEADER_SIZE + 4)


def write_binary_stl(path: Path, normals: np.ndarray, vertices: np.ndarray, label: str) -> None:
    """Write a binary STL with a fixed header and all attribute bytes zero.

    Source attribute bytes are not carried over: some CAD exporters store colour
    there, the slicer ignores it, and dropping it keeps the fixture independent of
    which exporter produced the source.
    """
    records = np.zeros(len(vertices), dtype=_STL_DTYPE)
    records["normal"] = normals
    records["vertices"] = vertices
    header = label.encode("ascii")[:_STL_HEADER_SIZE].ljust(_STL_HEADER_SIZE, b" ")
    _atomic_write_bytes(path, header + np.uint32(len(records)).tobytes() + records.tobytes())


def layout_geometry(triangles: np.ndarray, offsets_mm: list[list[float]]):
    """Place one copy per offset and centre the plate on the XY origin, Z min at 0.

    Each copy is first moved so its own bounding-box minimum sits at the origin,
    then shifted by its offset. All arithmetic stays in float32 so the result is a
    pure function of the source bytes and the manifest.
    """
    base = triangles["vertices"].astype(np.float32)
    base = base - base.reshape(-1, 3).min(axis=0)
    extent = base.reshape(-1, 3).max(axis=0)

    boxes = [(dx, dy, dx + float(extent[0]), dy + float(extent[1])) for dx, dy in offsets_mm]
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[j]
            if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                raise FixtureError(f"layout copies {i} and {j} overlap (copy extent {extent[:2].tolist()} mm)")

    copies = [base + np.array([dx, dy, 0.0], dtype=np.float32) for dx, dy in offsets_mm]
    vertices = np.concatenate(copies)
    flat = vertices.reshape(-1, 3)
    lo, hi = flat.min(axis=0), flat.max(axis=0)
    centre = np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]], dtype=np.float32)
    vertices = vertices - centre
    normals = np.tile(triangles["normal"].astype(np.float32), (len(offsets_mm), 1))
    return normals, vertices, (hi - lo)


def slab_geometry(size_mm: list[float]):
    """A closed axis-aligned box, XY-centred at the origin with Z from 0 to height."""
    sx, sy, sz = (np.float32(v) for v in size_mm)
    hx, hy = sx / np.float32(2), sy / np.float32(2)
    c = np.array([
        [-hx, -hy, 0], [hx, -hy, 0], [hx, hy, 0], [-hx, hy, 0],
        [-hx, -hy, sz], [hx, -hy, sz], [hx, hy, sz], [-hx, hy, sz],
    ], dtype=np.float32)
    # Counter-clockwise when viewed from outside, so every normal points outward.
    faces = [
        ((0, 2, 1), (0, 0, -1)), ((0, 3, 2), (0, 0, -1)),
        ((4, 5, 6), (0, 0, 1)), ((4, 6, 7), (0, 0, 1)),
        ((0, 1, 5), (0, -1, 0)), ((0, 5, 4), (0, -1, 0)),
        ((1, 2, 6), (1, 0, 0)), ((1, 6, 5), (1, 0, 0)),
        ((2, 3, 7), (0, 1, 0)), ((2, 7, 6), (0, 1, 0)),
        ((3, 0, 4), (-1, 0, 0)), ((3, 4, 7), (-1, 0, 0)),
    ]
    vertices = np.stack([c[list(idx)] for idx, _ in faces])
    normals = np.array([n for _, n in faces], dtype=np.float32)
    return normals, vertices, np.array([sx, sy, sz], dtype=np.float32)


# ── config ────────────────────────────────────────────────────────────────────

def build_sla_config(manifest: dict, case: dict, **overrides) -> SLAConfig:
    """The slicing config for a case. Supports are always off here: the frozen
    support mesh is imported at slice time, exactly as agent/jobs.py run_slicing
    forces supports_enable/pad_enable off when support.stl is present."""
    machine = manifest["machines"][case["machine"]]
    fields = dict(manifest["raster_params"])
    fields.update(
        printer_model=machine["printer_model"],
        display_pixels_x=machine["display_pixels_x"],
        display_pixels_y=machine["display_pixels_y"],
        display_width=machine["display_width"],
        display_height=machine["display_height"],
        display_orientation=machine["display_orientation"],
        center_x=machine["display_width"] / 2,
        center_y=machine["display_height"] / 2,
        supports_enable=False,
        pad_enable=False,
    )
    fields.update(overrides)
    return SLAConfig(**fields)


# ── build mode ────────────────────────────────────────────────────────────────

def build_case(manifest: dict, case: dict, models_dir: Path | None, work_dir: Path) -> dict:
    out_dir = work_dir / "fixtures" / case["id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    geometry = case["geometry"]
    machine = manifest["machines"][case["machine"]]

    source_record = None
    if geometry["type"] == "layout":
        source = manifest["sources"][geometry["source"]]
        source_path = find_source(models_dir, source)
        normals, vertices, extent = layout_geometry(read_binary_stl(source_path), geometry["offsets_mm"])
        source_record = {"filename": source["filename"], "sha256": source["sha256"]}
    else:
        normals, vertices, extent = slab_geometry(geometry["size_mm"])

    if extent[0] > machine["display_width"] or extent[1] > machine["display_height"]:
        raise FixtureError(
            f"case {case['id']}: plate {extent[:2].tolist()} mm does not fit "
            f"{machine['display_width']} x {machine['display_height']} mm"
        )

    generated_stl = out_dir / "model.stl.new"
    write_binary_stl(generated_stl, normals, vertices, f"raster_bench {case['id']}")
    generated_sha = sha256_file(generated_stl)
    current_geometry = geometry_sha256(manifest, case)
    recorded = case["model"]
    if recorded["sha256"] is not None and (recorded["sha256"], recorded["geometry_sha256"]) != (generated_sha, current_geometry):
        generated_stl.unlink()
        raise FixtureError(
            f"case {case['id']}: manifest records model sha256 {recorded['sha256']} for geometry "
            f"{recorded['geometry_sha256']}, but this build gives model {generated_sha} for geometry "
            f"{current_geometry}. If the layout change is intended, set 'model' and any frozen 'support' "
            "hashes back to null, delete the old fixture files and rebuild."
        )
    stl_state = place_generated(out_dir / "model.stl", generated_stl, "model.stl")

    generated_ini = out_dir / "config.ini.new"
    generate_config_ini(build_sla_config(manifest, case), generated_ini)
    ini_state = place_generated(out_dir / "config.ini", generated_ini, "config.ini")

    record = {
        "case": case["id"],
        "machine": case["machine"],
        "source": source_record,
        "model_stl": {
            "sha256": sha256_file(out_dir / "model.stl"),
            "triangles": int(len(vertices)),
            "extent_mm": [round(float(v), 4) for v in extent],
        },
        "config_ini_sha256": sha256_file(out_dir / "config.ini"),
        "support_mode": case["support"]["mode"],
    }
    _atomic_write_bytes(out_dir / "fixture.json", (json.dumps(record, indent=2) + "\n").encode("utf-8"))
    manifest_state = "verified"
    if recorded["sha256"] is None:
        case["model"] = {"sha256": generated_sha, "geometry_sha256": current_geometry}
        manifest_state = "recorded"
    return {"case": case["id"], "model.stl": stl_state, "config.ini": ini_state, "manifest": manifest_state,
            **record["model_stl"]}


# ── freeze-support mode ───────────────────────────────────────────────────────

def freeze_support(manifest: dict, case: dict, work_dir: Path, engine_dir: Path) -> dict:
    case_id = case["id"]
    out_dir = work_dir / "fixtures" / case_id
    support_path = out_dir / "support.stl"
    model_path = out_dir / "model.stl"
    fixture_path = out_dir / "fixture.json"

    if support_path.exists():
        raise FixtureError(f"case {case_id}: refusing to overwrite existing {support_path}")
    if case["support"]["sha256"] is not None:
        raise FixtureError(
            f"case {case_id}: manifest already records a frozen support sha256 "
            f"({case['support']['sha256']}); supports are frozen only once"
        )
    if not model_path.exists() or not fixture_path.exists():
        raise FixtureError(f"case {case_id}: fixture not built yet; run without --freeze-support first")
    recorded = json.loads(fixture_path.read_text(encoding="utf-8"))["model_stl"]["sha256"]
    model_sha = sha256_file(model_path)
    if model_sha != recorded:
        raise FixtureError(f"case {case_id}: model.stl no longer matches fixture.json")
    if (case["model"]["sha256"], case["model"]["geometry_sha256"]) != (model_sha, geometry_sha256(manifest, case)):
        raise FixtureError(
            f"case {case_id}: model.stl {model_sha} is not the model recorded in manifest.json "
            f"({case['model']['sha256']}) for the current geometry; build and record the fixture first"
        )

    engine = engine_dir / ENGINE_EXE
    if not engine.is_file():
        raise FixtureError(f"engine not found: {engine}")

    # Same recipe as agent/sla_operations.py generate_supports: supports on, a
    # coarser detection layer height, --export-support-stl without --export-sla.
    config = build_sla_config(
        manifest, case,
        supports_enable=True,
        layer_height=SUPPORT_DETECTION_LAYER_HEIGHT,
        initial_layer_height=SUPPORT_DETECTION_LAYER_HEIGHT,
    )
    tmp_dir = Path(tempfile.mkdtemp(prefix=".freeze-", dir=out_dir))
    try:
        config_path = tmp_dir / "support_config.ini"
        generate_config_ini(config, config_path)
        cmd = [
            str(engine),
            "--export-support-stl",
            "--output", str(tmp_dir / "model.sl1"),
            "--load", str(config_path),
            str(model_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, env=_english_locale_env(), cwd=tmp_dir)
        (out_dir / "freeze_support.stdout.log").write_bytes(proc.stdout)
        (out_dir / "freeze_support.stderr.log").write_bytes(proc.stderr)

        generated = tmp_dir / "model_support.stl"
        verdict = classify_support_result(
            stdout=proc.stdout, stderr=proc.stderr, support_stl_exists=generated.exists()
        )
        if not verdict.has_support_mesh:
            raise FixtureError(
                f"case {case_id}: engine produced no support mesh (exit {proc.returncode}, "
                f"status {verdict.status.value}, code {verdict.error_code}, "
                f"outcome {verdict.support_outcome}); see freeze_support.*.log"
            )
        os.replace(generated, support_path)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    support_sha = sha256_file(support_path)
    case["support"]["sha256"] = support_sha
    case["support"]["model_sha256"] = model_sha
    case["support"]["frozen_with"] = {
        "engine_exe_sha256": sha256_file(engine),
        "engine_core_sha256": sha256_file(engine_dir / "slicer_core.dll")
        if (engine_dir / "slicer_core.dll").is_file() else None,
    }
    save_manifest(manifest)
    return {"case": case_id, "support.stl": "created", "sha256": support_sha}


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--models", help=f"source models directory (default: ${MODELS_ENV})")
    parser.add_argument("--case", action="append", dest="cases", metavar="ID",
                        help="case id to process; repeatable (default: all applicable cases)")
    parser.add_argument("--work", default=str(DEFAULT_WORK_DIR), help="working directory (default: %(default)s)")
    parser.add_argument("--freeze-support", action="store_true",
                        help="generate and freeze support.stl for cases with support mode 'frozen'")
    parser.add_argument("--engine", help="pre-change engine directory (required with --freeze-support)")
    args = parser.parse_args(argv)
    if args.freeze_support and not args.engine:
        parser.error("--freeze-support requires --engine DIR")
    if args.engine and not args.freeze_support:
        parser.error("--engine is only used with --freeze-support")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    work_dir = Path(args.work)
    try:
        manifest = load_manifest()
        cases = select_cases(manifest, args.cases)
        results = []
        if args.freeze_support:
            frozen = [case for case in cases if case["support"]["mode"] == "frozen"]
            if not frozen:
                raise FixtureError("none of the selected cases uses a frozen support")
            for case in frozen:
                results.append(freeze_support(manifest, case, work_dir, Path(args.engine)))
        else:
            needs_models = any(case["geometry"]["type"] == "layout" for case in cases)
            models_dir = resolve_models_dir(args.models) if needs_models else None
            for case in cases:
                results.append(build_case(manifest, case, models_dir, work_dir))
            if any(result["manifest"] == "recorded" for result in results):
                save_manifest(manifest)
    except FixtureError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for result in results:
        print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())

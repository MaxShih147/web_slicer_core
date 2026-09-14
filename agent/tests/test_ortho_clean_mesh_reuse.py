"""
Regression tests for Ortho cleaned mesh object reuse in ortho_pipeline.py.

``run_ortho_pipeline()`` used to call ``load_trimesh(input_path)`` twice for
the same ``model_clean.stl``: once inside ``_is_u_arch_from_low_sections()``
and again for Step 3 alignment. Both calls happen back-to-back with nothing
in between that could change the file on disk, so the second load was pure
overhead. The fix loads the cleaned STL once and passes that mesh object to
both ``_is_u_arch_from_low_sections()`` (signature changed from
``(input_path: Path)`` to ``(mesh: Trimesh)``) and Step 3/6/10.

These tests pin the two properties that make the reuse safe:
  - reloading the same STL twice independently is deterministic, so reusing
    one load is observationally equivalent to the old two-load behavior
    (``.vertices``/``.faces``/``.bounds`` match exactly)
  - ``_is_u_arch_from_low_sections()`` only reads the mesh (bounds/section),
    never mutates ``.vertices``/``.faces``/``.bounds``, so Step 3 can safely
    reuse the same instance afterwards
and pin the U-arch/non-U-arch classification itself against regression from
the signature/ownership change. One test also drives run_ortho_pipeline()
itself (PrusaSlicer/Boolean stubbed out) to pin that the U-arch=True path
still takes the pre-existing _complete_as_no_hollow() early return and never
reaches Step 1, using only the single shared load.
"""

import asyncio
import json
import re
from pathlib import Path

import numpy as np
import trimesh
from shapely.geometry import Polygon

import agent.ortho_pipeline as ortho_pipeline
from agent.ortho_pipeline import _is_u_arch_from_low_sections
from agent.sla_operations import load_trimesh


def _make_horseshoe(r_out=20.0, r_in=15.0, span_deg=300.0, height=10.0, n=64):
    """Open horseshoe/U-shape prism: large central opening at every Z level,
    so it is detected as U-arch by the low-section fill-ratio heuristic."""
    span = np.radians(span_deg)
    start, end = -span / 2, span / 2
    outer_angles = np.linspace(start, end, n)
    inner_angles = np.linspace(end, start, n)
    outer_pts = np.stack([r_out * np.cos(outer_angles), r_out * np.sin(outer_angles)], axis=1)
    inner_pts = np.stack([r_in * np.cos(inner_angles), r_in * np.sin(inner_angles)], axis=1)
    poly = Polygon(np.vstack([outer_pts, inner_pts]))
    return trimesh.creation.extrude_polygon(poly, height=height)


def test_load_trimesh_reload_is_deterministic(tmp_path):
    """Two independent load_trimesh() calls on the same file must agree
    exactly, so reusing a single load is equivalent to the old two-load
    behavior for whatever Step 3 reads (.vertices/.faces/.bounds)."""
    mesh = trimesh.creation.icosphere(subdivisions=2, radius=5.0)
    stl_path = tmp_path / "model_clean.stl"
    mesh.export(str(stl_path))

    first = load_trimesh(stl_path)
    second = load_trimesh(stl_path)

    assert np.array_equal(first.vertices, second.vertices)
    assert np.array_equal(first.faces, second.faces)
    assert np.array_equal(first.bounds, second.bounds)


def test_u_arch_check_does_not_mutate_mesh():
    """_is_u_arch_from_low_sections() must be read-only: Step 3 reuses the
    same instance afterwards, so any mutation here would leak downstream."""
    mesh = _make_horseshoe()
    verts_before = mesh.vertices.copy()
    faces_before = mesh.faces.copy()
    bounds_before = mesh.bounds.copy()

    _is_u_arch_from_low_sections(mesh)

    assert np.array_equal(mesh.vertices, verts_before)
    assert np.array_equal(mesh.faces, faces_before)
    assert np.array_equal(mesh.bounds, bounds_before)


def test_u_arch_check_does_not_mutate_mesh_non_u_arch_case():
    """Same read-only guarantee on the non-U-arch (full-base) path, which is
    the path that continues on into Steps 1-10 and reuses input_mesh there."""
    mesh = trimesh.creation.cylinder(radius=20.0, height=10.0, sections=64)
    verts_before = mesh.vertices.copy()
    faces_before = mesh.faces.copy()
    bounds_before = mesh.bounds.copy()

    _is_u_arch_from_low_sections(mesh)

    assert np.array_equal(mesh.vertices, verts_before)
    assert np.array_equal(mesh.faces, faces_before)
    assert np.array_equal(mesh.bounds, bounds_before)


def test_u_arch_detection_true_for_horseshoe():
    """A mesh with a large central opening at low Z is still detected as
    U-arch after the (input_path) -> (mesh) signature change."""
    assert _is_u_arch_from_low_sections(_make_horseshoe()) is True


def test_u_arch_detection_false_for_solid_base():
    """A solid full-base mesh (no central opening) is still not detected as
    U-arch after the signature change, so the normal hollow path is taken."""
    solid = trimesh.creation.cylinder(radius=20.0, height=10.0, sections=64)
    assert _is_u_arch_from_low_sections(solid) is False


def test_u_arch_pipeline_takes_early_return_without_second_load(tmp_path, monkeypatch):
    """Integration-style pin on run_ortho_pipeline() itself: on the U-arch
    path it must (a) load the cleaned mesh exactly once, (b) reach
    _complete_as_no_hollow() and return, and (c) never call Step 1's
    generate_hollow() (and by extension never reach Steps 2-10, which all
    run after it). PrusaSlicer/Boolean are stubbed out so this stays a fast,
    isolated control-flow check rather than a full Auto Process run."""
    job_id = "u_arch_test_job"
    job_dir = tmp_path / job_id
    (job_dir / "input").mkdir(parents=True)
    _make_horseshoe().export(str(job_dir / "input" / "model.stl"))

    monkeypatch.setattr(ortho_pipeline, "get_job_dir", lambda jid: job_dir)

    load_calls = []
    real_load_trimesh = ortho_pipeline.load_trimesh

    def _counting_load_trimesh(path):
        load_calls.append(path)
        return real_load_trimesh(path)

    monkeypatch.setattr(ortho_pipeline, "load_trimesh", _counting_load_trimesh)

    async def _fail_if_called(*args, **kwargs):
        raise AssertionError(
            "Step 1 generate_hollow() must not run on the U-arch early-return path"
        )

    monkeypatch.setattr(ortho_pipeline, "generate_hollow", _fail_if_called)

    asyncio.run(ortho_pipeline.run_ortho_pipeline(job_id))

    # Exactly one load_trimesh() call for model_clean.stl: the shared load,
    # reused by the U-arch check. No second (Step 3) load ever happens
    # because the pipeline returns before reaching Step 3.
    assert len(load_calls) == 1

    status = json.loads((job_dir / "status.json").read_text())
    assert status["status"] == "completed"
    assert status.get("has_ortho_result") is True

    result_path = job_dir / "output" / "ortho_result.stl"
    assert result_path.exists()


def test_ortho_pipeline_loads_cleaned_mesh_exactly_once():
    """Source-level pin: between the U-arch check and Step 3 alignment,
    model_clean.stl (input_path after `input_path = cleaned_path`) is only
    passed to load_trimesh() once. Guards against a future edit silently
    reintroducing the duplicate load that this change removes."""
    src = Path(__file__).resolve().parents[1] / "ortho_pipeline.py"
    text = src.read_text(encoding="utf-8")

    assert text.count("load_trimesh(input_path)") == 1

    assert re.search(
        r"_is_u_arch_from_low_sections\(\s*input_mesh\s*\)", text
    ), "U-arch check should be called with the already-loaded mesh, not a path"

    assert re.search(
        r"def _is_u_arch_from_low_sections\(\s*mesh:\s*[\"']?trimesh\.Trimesh[\"']?\s*\)\s*->\s*bool",
        text,
    ), "_is_u_arch_from_low_sections signature should accept a loaded mesh"

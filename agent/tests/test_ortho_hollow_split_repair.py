"""
Regression tests for the Hollow-fit component split in ortho_pipeline.py.

The split call was changed from the trimesh default (``repair=True``) to
``repair=False`` for performance: repair runs ``fill_holes()`` on every
split component before the Hollow-fit logic ever inspects it, even though
that logic only reads component ``.vertices``/``.bounds`` (width + radial
checks) and ``len(component.faces)`` (the 100-face significance gate).

These tests pin the behavior that makes ``repair=False`` safe:
  - the call site actually passes ``repair=False`` (guards against a silent
    revert to the slower default)
  - ``fill_holes()`` never introduces new vertices, only reuses existing
    boundary vertices to close single-triangle/quad holes — so geometry
    read by the width/radial checks is identical either way
"""

import re
from pathlib import Path

import numpy as np
import trimesh


def test_hollow_split_call_site_uses_repair_false():
    """Pin the ortho_pipeline.py call site to repair=False.

    A plain source check (rather than exercising the full async pipeline,
    which needs a job dir and the PrusaSlicer CLI) so a future edit can't
    silently drop back to the slower repair=True default.
    """
    src = Path(__file__).resolve().parents[1] / "ortho_pipeline.py"
    text = src.read_text(encoding="utf-8")
    match = re.search(r"hollow_mesh\.split\(([^)]*)\)", text)
    assert match, "hollow_mesh.split(...) call site not found"
    assert "repair=False" in match.group(1)
    assert "only_watertight=False" in match.group(1)


def test_fill_holes_only_reuses_existing_vertices():
    """fill_holes() may add faces to close small holes, but never adds
    vertices — confirming component .vertices/.bounds (used by the
    Hollow-fit width/radial checks) are identical with repair on or off."""
    sphere = trimesh.creation.icosphere(subdivisions=1, radius=5.0)
    faces = np.delete(sphere.faces.copy(), 0, axis=0)  # single-triangle hole
    holed = trimesh.Trimesh(vertices=sphere.vertices.copy(), faces=faces, process=False)
    assert not holed.is_watertight

    n_verts_before = len(holed.vertices)
    watertight_after = holed.fill_holes()

    assert watertight_after
    assert len(holed.vertices) == n_verts_before
    assert len(holed.faces) == len(sphere.faces)  # hole was re-closed


def test_split_repair_false_matches_repair_true_geometry():
    """On a mesh with a small fillable hole in one component, repair=False
    vs repair=True must agree on vertices/bounds for every component (only
    face count on the holed component may legitimately differ)."""
    sphere = trimesh.creation.icosphere(subdivisions=1, radius=5.0)
    faces = np.delete(sphere.faces.copy(), 0, axis=0)
    holed = trimesh.Trimesh(vertices=sphere.vertices.copy(), faces=faces, process=False)

    box = trimesh.creation.box(extents=[2, 2, 2])
    box.apply_translation([1000, 0, 0])

    combined = trimesh.util.concatenate([holed, box])

    comps_true = combined.split(only_watertight=False, repair=True)
    comps_false = combined.split(only_watertight=False, repair=False)

    assert len(comps_true) == len(comps_false) == 2

    for c_true, c_false in zip(comps_true, comps_false):
        assert np.array_equal(c_true.vertices, c_false.vertices)
        assert np.array_equal(c_true.bounds, c_false.bounds)
        # face count may only differ on the component that had a fillable hole
        assert len(c_true.faces) - len(c_false.faces) in (0, 1)

"""
Regression tests for the specialized vertical-ray broad-phase used by
generate_hex_grid() (agent/sla_operations.py).

generate_hex_grid() raycasts a fixed grid of +Z rays against the hollow
mesh to find each hex cell's ceiling height. Profiling showed trimesh's
default RayMeshIntersector spends 90%+ of that time building a generic 3D
r-tree over every triangle in the mesh, even though it is queried exactly
once per pipeline run with a small, fixed ray batch. Because every ray here
travels in the same +Z direction, trimesh's own r-tree query box for a
vertical ray degenerates to an XY point (padded by its 1e-5 buffer) times
the mesh's *entire* Z range -- so the Z term never excludes a triangle, and
the only real filter is XY bounding-box overlap.

`_hex_grid_vertical_ray_intersects_location()` computes that XY overlap
directly with chunked/vectorized NumPy instead of building the r-tree, then
runs trimesh's own narrow-phase (plane intersection, barycentric test,
epsilon, forward-distance check, multiple-hit dedup) verbatim so results are
identical to `mesh.ray.intersects_location()`, not merely equivalent.

These tests pin:
  - per-ray hit/miss and per-ray max-Z parity against the trimesh reference
    across multi-hit, no-hit, shared-edge, degenerate/vertical-triangle,
    duplicate-triangle, and large-triangle-spanning-multiple-rays cases
  - correctness is independent of `chunk_size`, including chunk boundaries
    and a non-multiple-of-chunk_size (partial final chunk) triangle count
  - the non-vertical-ray fallback returns byte-for-byte the same arrays as
    calling `mesh.ray.intersects_location()` directly
  - generate_hex_grid()'s final mesh (vertices/faces) is byte-for-byte
    identical whether it uses this helper or trimesh's own raycaster
"""

import numpy as np
import trimesh

from agent.sla_operations import (
    _hex_grid_vertical_ray_intersects_location,
    compute_hex_grid_layout,
    generate_hex_grid,
)
import agent.sla_operations as sla_operations


def _reference_intersects_location(mesh, ray_origins, ray_directions):
    return mesh.ray.intersects_location(ray_origins, ray_directions)


def _per_ray_max_z(locations, index_ray, n_rays):
    """Reproduces generate_hex_grid()'s hit-grouping: max Z per ray, or
    None for a ray with zero hits."""
    out = []
    for i in range(n_rays):
        hits = locations[index_ray == i]
        out.append(float(hits[:, 2].max()) if len(hits) > 0 else None)
    return out


def _assert_same_hit_semantics(mesh, ray_origins, ray_directions, chunk_size=16384):
    ref_loc, ref_ray, _ = _reference_intersects_location(mesh, ray_origins, ray_directions)
    new_loc, new_ray, _ = _hex_grid_vertical_ray_intersects_location(
        mesh, ray_origins, ray_directions, chunk_size=chunk_size
    )

    n_rays = len(ray_origins)
    ref_max_z = _per_ray_max_z(ref_loc, ref_ray, n_rays)
    new_max_z = _per_ray_max_z(new_loc, new_ray, n_rays)

    assert len(ref_max_z) == len(new_max_z)
    for i, (r, n) in enumerate(zip(ref_max_z, new_max_z)):
        if r is None:
            assert n is None, f"ray {i}: reference had no hit but new path found one ({n})"
        else:
            assert n is not None, f"ray {i}: reference hit z={r} but new path found no hit"
            assert abs(r - n) < 1e-9, f"ray {i}: max-z mismatch ref={r} new={n}"
    return ref_max_z, new_max_z


def _vertical_rays(xy_points, z_start=-100.0):
    origins = np.array([[x, y, z_start] for x, y in xy_points], dtype=np.float64)
    directions = np.tile([0.0, 0.0, 1.0], (len(xy_points), 1))
    return origins, directions


def _flat_plate(z, half=10.0):
    """Two-triangle horizontal quad centered at origin, at height z."""
    verts = np.array(
        [[-half, -half, z], [half, -half, z], [half, half, z], [-half, half, z]],
        dtype=np.float64,
    )
    faces = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64)
    return trimesh.Trimesh(vertices=verts, faces=faces, process=False)


def test_single_hit_and_miss():
    mesh = _flat_plate(z=5.0, half=10.0)
    origins, directions = _vertical_rays([(0.0, 0.0), (5.0, 5.0), (1000.0, 1000.0)])
    ref_max_z, new_max_z = _assert_same_hit_semantics(mesh, origins, directions)
    assert ref_max_z[0] == 5.0 and new_max_z[0] == 5.0
    assert ref_max_z[2] is None and new_max_z[2] is None  # far outside footprint -> miss


def test_multi_hit_two_stacked_plates():
    bottom = _flat_plate(z=0.0, half=10.0)
    top = _flat_plate(z=10.0, half=10.0)
    mesh = trimesh.util.concatenate([bottom, top])
    origins, directions = _vertical_rays([(0.0, 0.0), (3.0, -2.0)])
    ref_max_z, new_max_z = _assert_same_hit_semantics(mesh, origins, directions)
    # both rays must see the *top* plate as the max-Z hit, not the bottom one
    assert ref_max_z[0] == 10.0 and new_max_z[0] == 10.0
    assert ref_max_z[1] == 10.0 and new_max_z[1] == 10.0


def test_ray_outside_footprint_is_a_miss():
    mesh = _flat_plate(z=5.0, half=2.0)
    origins, directions = _vertical_rays([(50.0, 50.0)])
    ref_max_z, new_max_z = _assert_same_hit_semantics(mesh, origins, directions)
    assert ref_max_z == [None] and new_max_z == [None]


def test_ray_on_shared_edge_between_two_triangles_dedups_consistently():
    # ray goes straight through the diagonal shared edge of the quad's two triangles
    mesh = _flat_plate(z=5.0, half=10.0)
    origins, directions = _vertical_rays([(0.0, 0.0)])  # (0,0) lies on the (0,1)-(2) diagonal? check below
    # the quad is split as (0,1,2) and (0,2,3); the shared edge is v0-v2, i.e. (-10,-10)->(10,10)
    origins, directions = _vertical_rays([(0.0, 0.0)])
    ref_loc, ref_ray, _ = _reference_intersects_location(mesh, origins, directions)
    new_loc, new_ray, _ = _hex_grid_vertical_ray_intersects_location(mesh, origins, directions)
    # whatever trimesh's own dedup behavior is for an on-edge hit, the new
    # path must match it exactly (same hit count after dedup, same location)
    assert len(ref_loc) == len(new_loc)
    if len(ref_loc) > 0:
        assert np.allclose(sorted(ref_loc[:, 2].tolist()), sorted(new_loc[:, 2].tolist()))


def test_vertical_degenerate_triangle_produces_no_hit():
    # a triangle lying in the XZ plane (normal along Y) is parallel to a +Z
    # ray direction -> the ray can never cross its plane transversally.
    vertical_verts = np.array(
        [[-5.0, 0.0, 0.0], [5.0, 0.0, 0.0], [0.0, 0.0, 10.0]], dtype=np.float64
    )
    vertical_tri = trimesh.Trimesh(
        vertices=vertical_verts, faces=np.array([[0, 1, 2]]), process=False
    )
    cap = _flat_plate(z=20.0, half=10.0)
    mesh = trimesh.util.concatenate([vertical_tri, cap])

    origins, directions = _vertical_rays([(0.0, 0.0)])
    ref_max_z, new_max_z = _assert_same_hit_semantics(mesh, origins, directions)
    # only the real horizontal cap should register -- not the vertical triangle
    assert ref_max_z[0] == 20.0 and new_max_z[0] == 20.0


def test_duplicate_triangles_match_reference():
    plate = _flat_plate(z=5.0, half=10.0)
    # duplicate the same two triangles again (identical geometry, distinct face ids)
    mesh = trimesh.util.concatenate([plate, plate])
    origins, directions = _vertical_rays([(0.0, 0.0), (100.0, 100.0)])
    _assert_same_hit_semantics(mesh, origins, directions)


def test_large_triangle_spans_multiple_rays():
    big = np.array(
        [[-50.0, -50.0, 7.0], [50.0, -50.0, 7.0], [0.0, 50.0, 20.0]], dtype=np.float64
    )
    mesh = trimesh.Trimesh(vertices=big, faces=np.array([[0, 1, 2]]), process=False)
    origins, directions = _vertical_rays(
        [(-10.0, -10.0), (10.0, -10.0), (0.0, 10.0), (0.0, -49.0), (0.0, 49.0)]
    )
    _assert_same_hit_semantics(mesh, origins, directions)


def test_chunk_boundary_and_partial_final_chunk():
    # 37 separate quads (74 triangles) at distinct XY offsets so a small
    # chunk_size forces multiple chunk boundaries plus a non-full final chunk.
    plates = [_flat_plate(z=float(i), half=1.0) for i in range(37)]
    for i, p in enumerate(plates):
        p.apply_translation([i * 5.0, 0.0, 0.0])
    mesh = trimesh.util.concatenate(plates)
    assert len(mesh.faces) % 16 != 0  # confirm this exercises a partial final chunk

    xy_points = [(i * 5.0, 0.0) for i in range(37)] + [(1000.0, 1000.0)]
    origins, directions = _vertical_rays(xy_points)

    for chunk_size in (1, 3, 8, 16, 100000):
        ref_max_z, new_max_z = _assert_same_hit_semantics(
            mesh, origins, directions, chunk_size=chunk_size
        )
    # sanity: each plate's own ray should see exactly its own height
    for i in range(37):
        assert new_max_z[i] == float(i)
    assert new_max_z[-1] is None


def test_non_vertical_ray_falls_back_to_reference_exactly():
    mesh = _flat_plate(z=5.0, half=10.0)
    # angled ray direction (not [0, 0, 1]) must take the fallback path and
    # return byte-for-byte what trimesh's own intersects_location() gives.
    origins = np.array([[-20.0, 0.0, 0.0]], dtype=np.float64)
    directions = np.array([[1.0, 0.0, 0.2]], dtype=np.float64)

    ref_loc, ref_ray, ref_tri = _reference_intersects_location(mesh, origins, directions)
    new_loc, new_ray, new_tri = _hex_grid_vertical_ray_intersects_location(
        mesh, origins, directions
    )
    assert np.array_equal(ref_loc, new_loc)
    assert np.array_equal(ref_ray, new_ray)
    assert np.array_equal(ref_tri, new_tri)


def test_no_triangles_returns_empty():
    mesh = trimesh.Trimesh(
        vertices=np.zeros((0, 3)), faces=np.zeros((0, 3), dtype=np.int64), process=False
    )
    origins, directions = _vertical_rays([(0.0, 0.0)])
    locations, index_ray, index_tri = _hex_grid_vertical_ray_intersects_location(
        mesh, origins, directions
    )
    assert len(locations) == 0 and len(index_ray) == 0 and len(index_tri) == 0


def test_generate_hex_grid_end_to_end_byte_for_byte(monkeypatch):
    """Full generate_hex_grid() call: the resulting mesh must be identical
    whether the raycast goes through this helper or trimesh's own path."""
    hollow = trimesh.creation.box(extents=[40.0, 40.0, 20.0])
    hollow.apply_translation([0.0, 0.0, 10.0])  # sits above bottom_z=0

    layout = compute_hex_grid_layout(
        radius=5.0, wall_thickness=1.0, grid_count=5, hollow_mesh=hollow
    )

    def build(use_reference):
        if use_reference:
            monkeypatch.setattr(
                sla_operations,
                "_hex_grid_vertical_ray_intersects_location",
                lambda mesh, o, d, chunk_size=16384: mesh.ray.intersects_location(o, d),
            )
        else:
            monkeypatch.undo()
        return generate_hex_grid(
            radius=5.0,
            pyramid_height=3.0,
            wall_thickness=1.0,
            grid_count=5,
            bottom_z=0.0,
            hollow_mesh=hollow.copy(),
            layout=layout,
        )

    mesh_reference = build(use_reference=True)
    mesh_new = build(use_reference=False)

    assert mesh_reference is not None and mesh_new is not None
    assert np.array_equal(mesh_reference.vertices, mesh_new.vertices)
    assert np.array_equal(mesh_reference.faces, mesh_new.faces)

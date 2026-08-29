"""Convert a CAMair `Mesh` into the binary STL the slicing pipeline consumes.

CAMair hands meshes over as an indexed vertex/facet list rather than a mesh
file, so this is the seam between their protocol and everything we already have.

`facetMarks` — named groups of facet indices such as the margin line or the
occlusal surface — has no place in STL, which carries no per-face metadata. It
is written out separately so Stage 4 can use it instead of re-deriving those
regions from geometry.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

# Binary STL: 80-byte header, uint32 triangle count, then 50 bytes per triangle
# (3 floats normal + 3x3 floats vertices + uint16 attribute byte count).
_STL_HEADER_SIZE = 80
_TRIANGLE_STRUCT = struct.Struct("<12fH")


def _normal_of(facet, vertices) -> tuple[float, float, float]:
    """Use the supplied facet normal; fall back to the cross product."""
    if facet.HasField("normal"):
        n = facet.normal
        if n.x or n.y or n.z:
            return (n.x, n.y, n.z)

    a, b, c = vertices[facet.v0Idx], vertices[facet.v1Idx], vertices[facet.v2Idx]
    ux, uy, uz = b.x - a.x, b.y - a.y, b.z - a.z
    vx, vy, vz = c.x - a.x, c.y - a.y, c.z - a.z
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    length = (nx * nx + ny * ny + nz * nz) ** 0.5
    if length == 0:
        return (0.0, 0.0, 0.0)
    return (nx / length, ny / length, nz / length)


def mesh_to_stl_bytes(mesh, header: str = "CAMair") -> bytes:
    """Serialise a CAMair Mesh to binary STL.

    :raises ValueError: if the mesh is empty or a facet indexes a missing vertex
    """
    vertices = mesh.vertices
    facets = mesh.facets
    if not vertices or not facets:
        raise ValueError("CAMair mesh carries no geometry")

    vertex_count = len(vertices)
    out = bytearray()
    out += header.encode("ascii", "replace")[:_STL_HEADER_SIZE].ljust(_STL_HEADER_SIZE, b"\0")
    out += struct.pack("<I", len(facets))

    for index, facet in enumerate(facets):
        # Bad indices would otherwise surface as a corrupt STL much later.
        for vertex_index in (facet.v0Idx, facet.v1Idx, facet.v2Idx):
            if not 0 <= vertex_index < vertex_count:
                raise ValueError(
                    f"facet {index} references vertex {vertex_index}, mesh has {vertex_count}",
                )
        nx, ny, nz = _normal_of(facet, vertices)
        a, b, c = vertices[facet.v0Idx], vertices[facet.v1Idx], vertices[facet.v2Idx]
        out += _TRIANGLE_STRUCT.pack(
            nx, ny, nz,
            a.x, a.y, a.z,
            b.x, b.y, b.z,
            c.x, c.y, c.z,
            0,
        )

    return bytes(out)


def write_mesh_as_stl(mesh, destination: Path, header: str = "CAMair") -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(mesh_to_stl_bytes(mesh, header))
    return destination


def facet_marks_to_dict(mesh) -> dict[str, list[int]]:
    """Named facet groups (margin line, occlusal surface, ...) keyed by name."""
    return {name: list(ids.ids) for name, ids in mesh.facetMarks.items()}


def write_facet_marks(mesh, destination: Path) -> Path | None:
    """Persist facetMarks alongside the STL, which cannot carry them."""
    marks = facet_marks_to_dict(mesh)
    if not marks:
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(marks))
    return destination

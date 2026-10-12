"""Keep supports out of a surgical guide's drill holes.

A guide's holes are what the drill passes through. A support point on a hole's
inner wall, or a pillar crossing the bore, leaves resin where the drill has to
go - the guide is then unusable, and the fault is invisible until it is on the
patient. Measured on Guided template (短).stl: of 24 automatic support points 3
landed inside the bore, and the support tree ran a pillar and four bars through
it.

So the bore gets a keep-out: a cylinder tight to the measured hole, reaching a
margin past each opening so the rim circles are covered rather than grazed.

WHERE THE BORE COMES FROM, AND WHAT IT IS NOT
---------------------------------------------
auto_orient_surg_guide finds each drill hole's END FACE and fits a cylinder to
it, but that cylinder is deliberately a loose SEARCH ENVELOPE, not the hole:
its radius is the end face's OUTER radius - two to three times the bore on every
guide measured (1.23 vs 4.00, 1.50 vs 3.03) - and its length is a fixed
max(10r, 40) both ways, which leaves the model entirely. Using it as the
keep-out would sweep away most of the guide.

The bore itself is measured from the mesh inside that envelope: the faces whose
normal lies across the axis and faces it are the tunnel wall, and nothing else
in there is. That classified cleanly on all five guides measured, with the bore
radius falling out as the median distance from the axis (1.2-3.4mm) and the
depth as the wall's own extent along it (6.2-10.5mm).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

# A wall face's normal is across the axis. Not zero: the tunnel is a polygon
# mesh, so its facets only approximate a cylinder, and a chamfer at the opening
# tilts further still.
_AXIAL_TOLERANCE = 0.30

# Below this a "wall" is noise - a few stray facets the envelope happened to
# catch - and measuring a bore from it would invent a hole.
_MIN_WALL_FACES = 20

# How far outside the measured bore radius a face may sit and still be taken
# for the wall. The envelope is much wider than the bore, so this is what keeps
# the model's outer surface out of the measurement.
_RADIUS_SLACK = 1.05


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


def _face_geometry(
    vertices: np.ndarray, faces: np.ndarray
) -> Tuple[np.ndarray, np.ndarray]:
    """Per-face centre and unit normal, without pulling in trimesh."""
    v = np.asarray(vertices, dtype=np.float64)
    f = np.asarray(faces, dtype=np.int64)
    a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    centres = (a + b + c) / 3.0
    normals = np.cross(b - a, c - a)
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    # A degenerate facet has no direction; left at zero it simply matches no
    # test below, which is what we want rather than a divide by zero.
    np.divide(normals, lengths, out=normals, where=lengths > 0)
    return centres, normals


def _measure_bore(
    vertices: np.ndarray,
    faces: np.ndarray,
    centres: np.ndarray,
    normals: np.ndarray,
    centre: np.ndarray,
    axis: np.ndarray,
    envelope_radius: float,
    envelope_length: float,
) -> Optional[Dict[str, Any]]:
    """The hole inside one search envelope, or None if there is no wall in it."""
    delta = centres - centre
    along = delta @ axis
    perpendicular = delta - np.outer(along, axis)
    distance = np.linalg.norm(perpendicular, axis=1)

    in_envelope = (distance <= envelope_radius * _RADIUS_SLACK) & (
        np.abs(along) <= envelope_length
    )
    across_axis = np.abs(normals @ axis) <= _AXIAL_TOLERANCE
    # Facing the axis rather than away from it: the tunnel wall looks inward,
    # the model's outside surface looks out.
    facing_in = np.einsum("ij,ij->i", normals, perpendicular) < 0

    wall = in_envelope & across_axis & facing_in
    if int(wall.sum()) < _MIN_WALL_FACES:
        return None

    # How far the wall reaches is measured from its VERTICES, not its face
    # centres. A triangle's centre sits a third of the way in from its corners,
    # so a coarsely tessellated bore measured by centres comes out far shorter
    # than it is - a 10mm bore of one quad per segment measures 3.3mm - and the
    # keep-out would then stop short of the rims, which are exactly what it is
    # there to cover.
    corners = np.asarray(vertices, dtype=np.float64)[np.asarray(faces, dtype=np.int64)[wall]]
    corner_along = (corners.reshape(-1, 3) - centre) @ axis

    # The radius stays the median over the wall's faces: robust to a stray
    # facet the envelope caught, and a faceted tunnel's face centres sit a
    # hair inside its corners, which the margin more than covers.
    return {
        "radius": float(np.median(distance[wall])),
        "low": float(corner_along.min()),
        "high": float(corner_along.max()),
        "wall_faces": int(wall.sum()),
    }


def bores_from_mesh(
    vertices: np.ndarray,
    faces: np.ndarray,
    cylinders: Sequence[Dict[str, Any]],
    margin: float = 0.5,
) -> List[Dict[str, Any]]:
    """The keep-out cylinders, in the mesh's own frame.

    Args:
        vertices: (N,3) model vertices
        faces: (M,3) triangle indices
        cylinders: the search envelopes from auto_orient_surg_guide's
            ``_build_drill_cylinders`` - ``{center, axis, radius, length}``
        margin: how far past the measured bore to reach, so a rim circle is
            covered rather than grazed

    Returns:
        ``{center, axis, radius, low, high}`` per hole, where ``low``/``high``
        bound the keep-out along the axis relative to ``center``. An envelope
        with no measurable wall is dropped rather than guessed at.
    """
    if vertices is None or faces is None or not len(faces) or not cylinders:
        return []

    centres, normals = _face_geometry(vertices, faces)
    out: List[Dict[str, Any]] = []
    for envelope in cylinders:
        centre = np.asarray(envelope["center"], dtype=np.float64)
        axis = _unit(np.asarray(envelope["axis"], dtype=np.float64))
        if not np.any(axis):
            continue
        bore = _measure_bore(
            vertices,
            faces,
            centres,
            normals,
            centre,
            axis,
            float(envelope.get("radius", 0.0)),
            float(envelope.get("length", 0.0)),
        )
        if bore is None:
            continue
        out.append({
            "center": [float(x) for x in centre],
            "axis": [float(x) for x in axis],
            "radius": bore["radius"] + margin,
            "low": bore["low"] - margin,
            "high": bore["high"] + margin,
            "bore_radius": bore["radius"],
            "depth": bore["high"] - bore["low"],
            "wall_faces": bore["wall_faces"],
        })
    return out


def is_in_a_bore(point: Sequence[float], bores: Sequence[Dict[str, Any]]) -> bool:
    """Whether this point sits inside any hole's keep-out."""
    px, py, pz = float(point[0]), float(point[1]), float(point[2])
    for bore in bores:
        cx, cy, cz = bore["center"]
        ax, ay, az = bore["axis"]
        dx, dy, dz = px - cx, py - cy, pz - cz
        along = dx * ax + dy * ay + dz * az
        if not (bore["low"] <= along <= bore["high"]):
            continue
        ex, ey, ez = dx - along * ax, dy - along * ay, dz - along * az
        if math.sqrt(ex * ex + ey * ey + ez * ez) <= bore["radius"]:
            return True
    return False


def drop_points_in_bores(
    document: Dict[str, Any], bores: Sequence[Dict[str, Any]]
) -> Tuple[Dict[str, Any], int]:
    """Remove the support points that fall in a hole.

    The document is the engine's own support point list, returned with its
    ``model_fingerprint`` untouched - the engine checks that the list belongs to
    the model it is given, and a filtered list still does.

    Returns the document and how many points were dropped.
    """
    points = document.get("points") or []
    if not bores or not points:
        return document, 0

    kept = [p for p in points if not is_in_a_bore(p.get("pos", (0, 0, 0)), bores)]
    dropped = len(points) - len(kept)
    if dropped:
        document = {**document, "points": kept}
    return document, dropped

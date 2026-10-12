"""Keep support heads off a surgical guide's drill holes.

A guide's holes are what the drill passes through. A support head landing on a
hole's inner wall, or on the rim where that wall meets the outside, leaves resin
where the drill has to go - the guide is unusable, and nothing says so until it
is on the patient. Measured on Guided template (短).stl, oriented the way
one-click processing orients it: of 24 automatic support points 3 landed inside
the bore, and on 20220708 SurgicalGuide 羅.stl two support heads came within
0.2mm of a bore wall.

WHAT THE KEEP-OUT IS
--------------------
The wall faces themselves, and anything within a margin of them. Not a fitted
cylinder.

A cylinder was tried first and was wrong, in a way worth recording so it is not
tried again. Across all 68 guides in the test set the wall's distance from the
fitted axis spread by a factor of 2.1 at the median and 3.7 at the worst - no
cylinder describes that. Two causes, each of which hid the other: these holes
open onto slots and other features, so a hole's rim is NOT a closed ring (one
guide's two bores came out as 6 and 4 disconnected wall patches with 8 and 4
boundary edges), which puts the end face's centre off the bore's own axis; and
the search envelope is wide enough that the walk takes in nearby inward-facing
surfaces too. Re-fitting the centre did not help, and measuring by first-hit ray
from the axis was worse - on one guide a ray left through the opening and struck
the far side 23.91mm away.

None of that matters to a surface test. Distance to the wall patch covers a
bore of any shape, a rim that is an arc rather than a circle, and a slot; the
rim lines need no special handling because they are the patch's own boundary.
And every support point sits ON the model surface, so a point in a hole is on
that patch by construction - there is no interior to reason about.

WHAT IT APPLIES TO
------------------
The support HEAD - the pin that touches the model. Taking those points off the
list is what the engine is given, and it was measured to be enough: on four
guides, every support element that crossed a bore was there because a point had
been placed inside it, so with the points gone the pillars and bars that grew
from them are not built either.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# A wall face's normal lies across the hole's axis. Not zero: the tunnel is a
# polygon mesh, so its facets only approximate a surface of revolution, and a
# chamfer at the opening tilts further still.
_AXIAL_TOLERANCE = 0.30

# Below this a "wall" is a few stray facets the envelope happened to catch, and
# treating them as a hole would carve supports out of a sound model.
_MIN_WALL_FACES = 20

# How far outside the envelope's own radius a face may still be taken for the
# wall.
_RADIUS_SLACK = 1.05


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


def _face_geometry(
    vertices: np.ndarray, faces: np.ndarray
) -> Tuple[np.ndarray, np.ndarray]:
    """Per-face centre and unit normal."""
    v = np.asarray(vertices, dtype=np.float64)
    f = np.asarray(faces, dtype=np.int64)
    a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    centres = (a + b + c) / 3.0
    normals = np.cross(b - a, c - a)
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    # A degenerate facet has no direction; left at zero it matches no test
    # below, which is what we want rather than a divide by zero.
    np.divide(normals, lengths, out=normals, where=lengths > 0)
    return centres, normals


def wall_faces(
    vertices: np.ndarray,
    faces: np.ndarray,
    cylinders: Sequence[Dict[str, Any]],
) -> np.ndarray:
    """Which faces belong to a drill hole's wall.

    Args:
        vertices: (N,3) model vertices, in the frame the supports are grown in
        faces: (M,3) triangle indices
        cylinders: the search envelopes from auto_orient_surg_guide's
            ``_build_drill_cylinders`` - ``{center, axis, radius, length}``.
            Each is deliberately loose: its radius is the end face's OUTER
            radius and its length a fixed max(10r, 40) both ways, so it bounds
            the search rather than describing the hole.

    Returns:
        Indices into ``faces``. Empty when no hole has a wall worth the name.
    """
    if vertices is None or faces is None or not len(faces) or not cylinders:
        return np.zeros(0, dtype=np.int64)

    centres, normals = _face_geometry(vertices, faces)
    found = np.zeros(len(faces), dtype=bool)

    for envelope in cylinders:
        centre = np.asarray(envelope["center"], dtype=np.float64)
        axis = _unit(np.asarray(envelope["axis"], dtype=np.float64))
        if not np.any(axis):
            continue

        delta = centres - centre
        along = delta @ axis
        perpendicular = delta - np.outer(along, axis)
        distance = np.linalg.norm(perpendicular, axis=1)

        in_envelope = (distance <= float(envelope.get("radius", 0.0)) * _RADIUS_SLACK) & (
            np.abs(along) <= float(envelope.get("length", 0.0))
        )
        across_axis = np.abs(normals @ axis) <= _AXIAL_TOLERANCE
        # Facing the axis rather than away from it: a tunnel wall looks inward,
        # the model's outside surface looks out.
        facing_in = np.einsum("ij,ij->i", normals, perpendicular) < 0

        wall = in_envelope & across_axis & facing_in
        if int(wall.sum()) >= _MIN_WALL_FACES:
            found |= wall

    return np.where(found)[0]


class GuideHoleKeepOut:
    """The surface a support head may not land on, and how near it may come.

    Built from the wall faces as their own patch, so the test is a distance to
    that surface. A head within ``margin`` of it is on the hole as far as this
    is concerned - which covers the wall, the rim lines bounding it, and the
    chamfer between, without any of them being described separately.
    """

    def __init__(self, patch, margin: float):
        self._patch = patch
        self._margin = float(margin)
        # Built once: the queries come in one list per generation, but building
        # the tree per point would be the expensive way round.
        import trimesh

        self._query = trimesh.proximity.ProximityQuery(patch)

    @property
    def face_count(self) -> int:
        return int(len(self._patch.faces))

    @property
    def margin(self) -> float:
        return self._margin

    def are_on_a_hole(self, points: Sequence[Sequence[float]]) -> np.ndarray:
        """Which of these points sit on a hole, as a boolean mask.

        Unsigned distance: a point just inside the wall and one just outside it
        are both on the hole, and the patch is an open surface anyway, so which
        side it is on is neither meaningful nor reliable.
        """
        if not len(points):
            return np.zeros(0, dtype=bool)
        query = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        return np.abs(self._query.signed_distance(query)) <= self._margin


def keepout_from_mesh(
    vertices: np.ndarray,
    faces: np.ndarray,
    cylinders: Sequence[Dict[str, Any]],
    margin: float = 0.5,
) -> Optional[GuideHoleKeepOut]:
    """The keep-out for one model, or None when it has no drill holes.

    None rather than an empty keep-out: a model with no holes should cost
    nothing, and the caller can skip the whole step on it.
    """
    indices = wall_faces(vertices, faces, cylinders)
    if not len(indices):
        return None

    import trimesh

    mesh = trimesh.Trimesh(
        vertices=np.asarray(vertices, dtype=np.float64),
        faces=np.asarray(faces, dtype=np.int64),
        process=False,
    )
    patch = mesh.submesh([indices], append=True)
    return GuideHoleKeepOut(patch, margin)


def drop_points_on_holes(
    document: Dict[str, Any], keepout: Optional[GuideHoleKeepOut]
) -> Tuple[Dict[str, Any], int]:
    """Take the support points that sit on a drill hole off the list.

    The document is the engine's own support point list, returned with its
    ``model_fingerprint`` untouched - the engine checks that a list belongs to
    the model it is given, and a filtered list still does.

    Returns the document and how many points were dropped.
    """
    points: List[Dict[str, Any]] = document.get("points") or []
    if keepout is None or not points:
        return document, 0

    on_a_hole = keepout.are_on_a_hole([p.get("pos", (0.0, 0.0, 0.0)) for p in points])
    kept = [p for p, bad in zip(points, on_a_hole) if not bad]
    dropped = len(points) - len(kept)
    if dropped:
        document = {**document, "points": kept}
    return document, dropped

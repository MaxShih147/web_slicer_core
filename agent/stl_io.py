"""Binary STL read / vertex merge / write with numpy (agent-large-model-perf D5).

boolean_operation() used to go through ``trimesh.load(process=True)`` to read
its inputs (5M faces: 12.4 s) and ``Trimesh(process=True)`` + ``export`` to
write its result. These functions do the same work directly on arrays.

``merge_triangle_vertices`` reproduces what ``trimesh.load(process=True)``
does to a binary STL *exactly* -- same vertices in the same order, same faces
-- so the repair sequence that still runs on trimesh objects (whose steps walk
vertices and edges in order) sees the very arrays it saw before:

1. ``remove_infinite_values``: drop every face with a NaN/Inf corner.
2. ``merge_vertices``: corners equal after ``round(v * 10**digits)`` are one
   vertex (``digits`` from ``trimesh.tol.merge``), kept in order of first
   occurrence (``unique_rows(keep_order=True)``). Degenerate and duplicate
   faces are kept, as ``trimesh.load`` keeps them (``validate=False``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

import numpy as np

HEADER_BYTES = 84
FACE_BYTES = 50

# One binary STL record. Explicit little-endian: the format is, whatever the CPU.
_FACE_DTYPE = np.dtype(
    [("normal", "<f4", (3,)), ("corners", "<f4", (3, 3)), ("attr", "<u2")]
)
assert _FACE_DTYPE.itemsize == FACE_BYTES


def read_binary_stl_triangles(path) -> Optional[np.ndarray]:
    """``(n, 3, 3) float32`` corners of a binary STL, or None.

    None unless the file is exactly ``84 + 50 * n`` bytes with ``n > 0`` --
    ASCII STL, padded or truncated files are left to ``trimesh.load``.
    """
    path = Path(path)
    size = path.stat().st_size
    if size < HEADER_BYTES:
        return None
    with open(path, "rb") as f:
        head = f.read(HEADER_BYTES)
        n = int.from_bytes(head[80:84], "little")
        if n == 0 or size != HEADER_BYTES + n * FACE_BYTES:
            return None
        records = np.fromfile(f, dtype=_FACE_DTYPE, count=n)
    if len(records) != n:
        return None
    return np.ascontiguousarray(records["corners"])


def _merge_digits() -> int:
    import trimesh

    return int(trimesh.util.decimal_to_digits(trimesh.tol.merge))


def merge_triangle_vertices(
    triangles: np.ndarray, digits: Optional[int] = None
) -> Tuple[np.ndarray, np.ndarray]:
    """Weld ``(n, 3, 3)`` triangle corners exactly as ``trimesh.load`` does.

    Returns ``(vertices float64 (v, 3), faces int64 (m, 3))``, element-for-
    element equal to ``trimesh.load(path, process=True)``'s
    ``vertices`` / ``faces`` for the same binary STL.
    """
    digits = _merge_digits() if digits is None else digits
    tris = np.asarray(triangles)
    finite = np.isfinite(tris).all(axis=(1, 2))
    if not finite.all():
        tris = tris[finite]
    corners = tris.reshape(-1, 3).astype(np.float64)
    if len(corners) == 0:
        return np.zeros((0, 3), dtype=np.float64), np.zeros((0, 3), dtype=np.int64)

    keys = np.round(corners * (10 ** digits)).astype(np.int64)
    grouped = _group_by_hash(keys)
    if grouped is None:
        grouped = _group_exact(keys)
    first, inverse = grouped

    # Groups come numbered in sort order; renumber them in order of first
    # occurrence, as unique_rows(keep_order=True) does.
    order = np.argsort(first, kind="stable")
    rank = np.empty_like(order)
    rank[order] = np.arange(len(order))
    vertices = corners[first[order]]
    faces = rank[inverse].reshape(-1, 3).astype(np.int64)
    return vertices, faces


def _mix64_inplace(h: np.ndarray, tmp: np.ndarray) -> None:
    """splitmix64 finalizer on uint64 *h*, in place (a bijection)."""
    for shift, mul in ((30, 0xBF58476D1CE4E5B9), (27, 0x94D049BB133111EB)):
        np.right_shift(h, np.uint64(shift), out=tmp)
        np.bitwise_xor(h, tmp, out=h)
        np.multiply(h, np.uint64(mul), out=h)
    np.right_shift(h, np.uint64(31), out=tmp)
    np.bitwise_xor(h, tmp, out=h)


def _row_hash(u: np.ndarray) -> np.ndarray:
    """One uint64 per (x, y, z) uint64 row: mix(mix(mix(x) ^ y) ^ z).

    Chained, not a xor of per-column products: that cheaper combine collided
    on ~17% of a sphere's vertices (related coordinates), which only costs
    speed -- collisions send the caller to the exact path -- but all of it."""
    h = u[:, 0] + np.uint64(0x9E3779B97F4A7C15)
    tmp = np.empty_like(h)
    _mix64_inplace(h, tmp)
    np.bitwise_xor(h, u[:, 1], out=h)
    _mix64_inplace(h, tmp)
    np.bitwise_xor(h, u[:, 2], out=h)
    _mix64_inplace(h, tmp)
    return h


def _group_by_hash(keys: np.ndarray):
    """Group equal int64 rows by sorting one 64-bit hash per row.

    Returns ``(first, inverse)``: for each group the lowest row index holding
    it, and each row's group number. Returns None if two different rows share
    a hash (then the caller groups exactly); that check makes the result
    exact, the hash only makes it fast.
    """
    u = keys.view(np.uint64)
    with np.errstate(over="ignore"):
        h = _row_hash(u)
    # Stable: within a run of equal hashes rows stay in index order, so a
    # run's first element is that group's first occurrence.
    order = np.argsort(h, kind="stable")
    hs = h[order]
    starts = np.empty(len(hs), dtype=bool)
    starts[0] = True
    np.not_equal(hs[1:], hs[:-1], out=starts[1:])
    # Exactness: every row must equal the row before it in its hash run. One
    # contiguous row gather is far cheaper than per-column fancy indexing.
    ks = keys[order]
    differs = (ks[1:] != ks[:-1]).any(axis=1)
    del ks
    if (differs & ~starts[1:]).any():
        return None
    group_sorted = np.cumsum(starts) - 1
    inverse = np.empty(len(keys), dtype=np.int64)
    inverse[order] = group_sorted
    first = order[starts]
    return first, inverse


def _group_exact(keys: np.ndarray):
    """Exact fallback for a hash collision: np.unique on whole rows."""
    rows = np.ascontiguousarray(keys).view(np.dtype((np.void, keys.dtype.itemsize * 3))).ravel()
    _, first, inverse = np.unique(rows, return_index=True, return_inverse=True)
    return first, inverse.reshape(-1)


def face_normals(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Unit right-hand-rule normals, float32; zero for degenerate faces."""
    v = np.asarray(vertices, dtype=np.float64)
    tri = v[np.asarray(faces)]
    with np.errstate(invalid="ignore", over="ignore"):
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        length = np.linalg.norm(n, axis=1)
    ok = np.isfinite(length) & (length > 0)
    n[ok] /= length[ok, None]
    n[~ok] = 0.0
    return n.astype(np.float32)


def write_binary_stl(path, vertices: np.ndarray, faces: np.ndarray, header: bytes = b"") -> None:
    """Write an indexed mesh as a binary STL in one buffer."""
    faces = np.asarray(faces)
    records = np.zeros(len(faces), dtype=_FACE_DTYPE)
    records["normal"] = face_normals(vertices, faces)
    records["corners"] = np.asarray(vertices, dtype=np.float32)[faces]
    with open(path, "wb") as f:
        f.write(header[:80].ljust(80, b"\x00"))
        f.write(np.uint32(len(faces)).astype("<u4").tobytes())
        records.tofile(f)

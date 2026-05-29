"""Surgical-guide auto-orientation.

1:1 Python port of the C++/WASM module
``wasm-impl/Orientation/Orientation/src/auto_orient_surg_guide.cpp``
(``compute_auto_orientation_SurgGuide_mod``, module = 2).

Goal: find the "drill-hole end face" patch and rotate the model so that face
points to -Z (drill entrance facing down — the print orientation for a guide).

The public entry is :func:`compute_auto_orientation_surg_guide`, which mirrors
the C++ signature: given a float vertex array (N,3) and a uint triangle index
array (M,3), it returns ``[rx, ry, rz]`` Euler radians intended to be applied
with Three.js Euler order ``'ZYX'`` (matching the existing frontend pipeline).

Kept deliberately faithful to the C++ (same thresholds, same vertex-weld eps,
same scanline voxel test) so behaviour can be diffed against the wasm build.
Numerics use float32 to match the original.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

# --------------------------------------------------------------------------- #
#  小工具 / vector helpers (port of dao_math)                                  #
# --------------------------------------------------------------------------- #


def _clampf(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else (hi if x > hi else x)


def _norm(a: np.ndarray) -> float:
    return float(math.sqrt(float(a[0]) * float(a[0])
                           + float(a[1]) * float(a[1])
                           + float(a[2]) * float(a[2])))


def _normalize(a: np.ndarray) -> np.ndarray:
    n = _norm(a)
    if n <= 0.0:
        return np.zeros(3, dtype=np.float32)
    return (a / n).astype(np.float32)


def _cross(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.array([
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ], dtype=np.float32)


def _dot(a: np.ndarray, b: np.ndarray) -> float:
    return float(a[0] * b[0] + a[1] * b[1] + a[2] * b[2])


def _build_orthonormal_basis(n_in: np.ndarray):
    """Port of buildOrthonormalBasis: build (ex, ey) spanning the plane ⟂ n."""
    n = _normalize(n_in)
    if _norm(n) < 1e-6:
        n = np.array([0.0, 0.0, 1.0], dtype=np.float32)

    if abs(float(n[2])) < 0.9:
        t = np.array([0.0, 0.0, 1.0], dtype=np.float32)
    else:
        t = np.array([0.0, 1.0, 0.0], dtype=np.float32)

    ex = _normalize(_cross(t, n))
    ey = _cross(n, ex)
    return ex, ey


def _normal_to_euler_xyz_align_to_minus_z(n_in: np.ndarray) -> np.ndarray:
    """Port of normal_to_euler_XYZ_align_to_minusZ.

    Returns [rx, ry, rz] (radians) for a rotation that maps the input normal
    onto -Z. The decomposition corresponds to R = Rz*Ry*Rx, i.e. Three.js
    Euler order 'ZYX' (despite the legacy "XYZ" in the C++ name, which only
    refers to the [rx,ry,rz] component ordering).
    """
    out = np.zeros(3, dtype=np.float32)

    nx0, ny0, nz0 = float(n_in[0]), float(n_in[1]), float(n_in[2])
    l2 = nx0 * nx0 + ny0 * ny0 + nz0 * nz0
    if l2 <= 0.0:
        return out
    L = math.sqrt(l2)
    nx, ny, nz = nx0 / L, ny0 / L, nz0 / L

    if nz <= -0.999999:
        return out
    if nz >= 0.999999:
        out[1] = math.pi
        return out

    zx, zy, zz = -nx, -ny, -nz

    refx, refy, refz = 1.0, 0.0, 0.0
    if abs(nx) > 0.9 and abs(ny) < 0.5:
        refx, refy, refz = 0.0, 1.0, 0.0

    ndotref = nx * refx + ny * refy + nz * refz
    xx = refx - nx * ndotref
    xy = refy - ny * ndotref
    xz = refz - nz * ndotref
    xlen2 = xx * xx + xy * xy + xz * xz
    if xlen2 < 1e-12:
        refx = 0.0 if refx == 1.0 else 1.0
        refy = 0.0
        refz = 0.0
        ndotref = nx * refx + ny * refy + nz * refz
        xx = refx - nx * ndotref
        xy = refy - ny * ndotref
        xz = refz - nz * ndotref
        xlen2 = xx * xx + xy * xy + xz * xz
    invx = 1.0 / math.sqrt(xlen2)
    xx *= invx
    xy *= invx
    xz *= invx

    yx = zy * xz - zz * xy
    yy = zz * xx - zx * xz
    yz = zx * xy - zy * xx
    ylen2 = yx * yx + yy * yy + yz * yz
    invy = 1.0 / math.sqrt(max(1e-30, ylen2))
    yx *= invy
    yy *= invy
    yz *= invy

    xx = yy * zz - yz * zy
    xy = yz * zx - yx * zz
    xz = yx * zy - yy * zx
    xlen2 = xx * xx + xy * xy + xz * xz
    invx = 1.0 / math.sqrt(max(1e-30, xlen2))
    xx *= invx
    xy *= invx
    xz *= invx

    r00, r01, r02 = xx, xy, xz   # noqa: F841  (kept for parity / clarity)
    r10, r11 = yx, yy
    r20, r21, r22 = zx, zy, zz

    ry = -math.asin(max(-1.0, min(1.0, r20)))
    cy = math.cos(ry)

    if abs(cy) > 1e-6:
        rx = math.atan2(r21, r22)
        rz = math.atan2(r10, r00)
    else:
        rx = 0.0
        rz = math.atan2(-r01, r11)

    out[0] = rx
    out[1] = ry
    out[2] = rz
    return out


# --------------------------------------------------------------------------- #
#  幾何結構 / geometry structures                                              #
# --------------------------------------------------------------------------- #


@dataclass
class _Patch:
    id: int
    faces: list = field(default_factory=list)      # face indices
    avg_normal: np.ndarray = field(default_factory=lambda: np.zeros(3, np.float32))
    area: float = 0.0
    max_angle_deg: float = 0.0
    boundary_edges: int = 0
    vertical_walls: int = 0
    center: np.ndarray = field(default_factory=lambda: np.zeros(3, np.float32))


@dataclass
class _GuideResult:
    found: bool = False
    dir: np.ndarray = field(default_factory=lambda: np.array([0, 0, 1], np.float32))
    # debug/visualization: triangle indices (into the input faces array)
    decision_faces: list = field(default_factory=list)  # chosen drill end-face patch
    step_faces: list = field(default_factory=list)       # internal step faces used for tiebreak


# --------------------------------------------------------------------------- #
#  Mesh container holding the welded topology (built once, shared by stages)   #
# --------------------------------------------------------------------------- #


class _Mesh:
    """Holds welded vertices/faces + face normals/centroids + edge adjacency."""

    def __init__(self, verts: np.ndarray, faces_idx: np.ndarray):
        # verts: original (N,3) float32; faces use *welded* (rep) indices but
        # vertex coordinates are still looked up from the original array, just
        # like load_vtx(v, rep_idx) in the C++.
        self.v = verts
        # per-face welded vertex indices
        self.fi = faces_idx                      # (M,3) uint32
        self.face_n = None                       # (M,3) float32 normals
        self.face_c = None                       # (M,3) float32 centroids
        self.face_area = None                    # (M,) float32 areas
        self.patch_id = None                     # (M,) int32, -1 unassigned / -2 degenerate
        self.edge_faces: dict[tuple, list] = {}  # (a,b)->[f0,f1]
        self.adj: list[list[int]] = []           # face adjacency


def _weld_and_build(vertices: np.ndarray, faces: np.ndarray) -> _Mesh:
    """Step 1-3: vertex weld (eps=1e-4 quantization) + FaceInfo + edge map."""
    v = np.ascontiguousarray(vertices, dtype=np.float32)
    nv = v.shape[0]
    eps = 1e-4
    inv_eps = 1.0 / eps

    # --- Step 1: vertex weld via quantization ---
    quant = np.floor(v * inv_eps + 0.5).astype(np.int64)   # (N,3)
    rep_of_vertex = np.arange(nv, dtype=np.uint32)
    vmap: dict[tuple, int] = {}
    for i in range(nv):
        key = (int(quant[i, 0]), int(quant[i, 1]), int(quant[i, 2]))
        rep = vmap.get(key)
        if rep is None:
            vmap[key] = i
            rep_of_vertex[i] = i
        else:
            rep_of_vertex[i] = rep

    fi = rep_of_vertex[faces.astype(np.int64)]             # (M,3) uint32, welded

    mesh = _Mesh(v, fi)
    m = fi.shape[0]

    # --- Step 2: FaceInfo (normals + centroids) ---
    p0 = v[fi[:, 0].astype(np.int64)]
    p1 = v[fi[:, 1].astype(np.int64)]
    p2 = v[fi[:, 2].astype(np.int64)]
    e1 = p1 - p0
    e2 = p2 - p0
    cr = np.cross(e1, e2)
    L = np.linalg.norm(cr, axis=1)
    n = np.zeros_like(cr)
    nz = L > 0.0
    n[nz] = cr[nz] / L[nz, None]
    mesh.face_n = n.astype(np.float32)
    mesh.face_c = ((p0 + p1 + p2) / 3.0).astype(np.float32)
    mesh.face_area = (L * 0.5).astype(np.float32)
    mesh.patch_id = np.full(m, -1, dtype=np.int32)

    # --- Step 3: edge map + adjacency ---
    edge_faces: dict[tuple, list] = {}
    adj: list[list[int]] = [[] for _ in range(m)]
    fi_arr = fi
    for f in range(m):
        a0, a1, a2 = int(fi_arr[f, 0]), int(fi_arr[f, 1]), int(fi_arr[f, 2])
        for (i0, i1) in ((a0, a1), (a1, a2), (a2, a0)):
            key = (i0, i1) if i0 < i1 else (i1, i0)
            ef = edge_faces.get(key)
            if ef is None:
                edge_faces[key] = [f, -1]
            else:
                if ef[1] == -1:
                    ef[1] = f
                    other = ef[0]
                    if other >= 0:
                        adj[f].append(other)
                        adj[other].append(f)
    mesh.edge_faces = edge_faces
    mesh.adj = adj
    return mesh


def _grow_patches(mesh: _Mesh) -> list[_Patch]:
    """Step 4-5: 2° region growing into flat patches, then per-patch stats."""
    m = mesh.fi.shape[0]
    face_n = mesh.face_n
    patch_id = mesh.patch_id
    adj = mesh.adj
    cos_grow = math.cos(2.0 * math.pi / 180.0)

    patches: list[_Patch] = []
    next_id = 0

    from collections import deque
    for f0 in range(m):
        if patch_id[f0] != -1:
            continue
        if _norm(face_n[f0]) < 0.5:
            patch_id[f0] = -2
            continue

        pid = next_id
        next_id += 1
        P = _Patch(id=pid)
        n_seed = face_n[f0]

        q = deque()
        q.append(f0)
        patch_id[f0] = pid
        while q:
            fidx = q.popleft()
            P.faces.append(fidx)
            for fn in adj[fidx]:
                if patch_id[fn] != -1:
                    continue
                n = face_n[fn]
                if _norm(n) < 0.5:
                    patch_id[fn] = -2
                    continue
                if _dot(n, n_seed) >= cos_grow:
                    patch_id[fn] = pid
                    q.append(fn)
        patches.append(P)

    # --- Step 5: per-patch avgNormal / area / center / maxAngleDeg ---
    v = mesh.v
    fi = mesh.fi
    for P in patches:
        sum_n = np.zeros(3, dtype=np.float64)
        sum_c = np.zeros(3, dtype=np.float64)
        area_sum = 0.0
        for fidx in P.faces:
            i0, i1, i2 = int(fi[fidx, 0]), int(fi[fidx, 1]), int(fi[fidx, 2])
            p0, p1, p2 = v[i0], v[i1], v[i2]
            A = 0.5 * _norm(_cross(p1 - p0, p2 - p0))
            area_sum += A
            sum_n += mesh.face_n[fidx].astype(np.float64) * A
            sum_c += mesh.face_c[fidx].astype(np.float64) * A
        P.area = float(area_sum)
        P.avg_normal = _normalize(sum_n.astype(np.float32))
        if area_sum > 0.0:
            P.center = (sum_c / area_sum).astype(np.float32)
        else:
            P.center = np.zeros(3, dtype=np.float32)

        max_ang = 0.0
        for fidx in P.faces:
            c = _clampf(_dot(mesh.face_n[fidx], P.avg_normal), -1.0, 1.0)
            ang = math.acos(c) * 180.0 / math.pi
            if ang > max_ang:
                max_ang = ang
        P.max_angle_deg = max_ang

    return patches


def _patch_has_hole_by_scanlines(mesh: _Mesh, P: _Patch,
                                 ex: np.ndarray, ey: np.ndarray) -> bool:
    """Port of patch_has_hole_by_scanlines: 2D voxel rasterize + scan for a
    solid → empty → solid pattern (a hole) along rows and columns."""
    if not P.faces:
        return False

    v = mesh.v
    fi = mesh.fi
    origin = P.center

    def project_pos(vid: int) -> tuple:
        p = v[vid]
        qx = float(p[0]) - float(origin[0])
        qy = float(p[1]) - float(origin[1])
        qz = float(p[2]) - float(origin[2])
        u = qx * float(ex[0]) + qy * float(ex[1]) + qz * float(ex[2])
        vv = qx * float(ey[0]) + qy * float(ey[1]) + qz * float(ey[2])
        return u, vv

    umin = vmin = 1e30
    umax = vmax = -1e30
    for fidx in P.faces:
        for k in range(3):
            u, vv = project_pos(int(fi[fidx, k]))
            umin = min(umin, u); umax = max(umax, u)
            vmin = min(vmin, vv); vmax = max(vmax, vv)

    width = umax - umin
    height = vmax - vmin
    if not (width > 0.0 and height > 0.0):
        return False

    voxel = 0.3
    pad = voxel * 0.5
    u0 = umin - pad
    v0 = vmin - pad
    u1 = umax + pad
    v1 = vmax + pad
    nx = int(math.ceil((u1 - u0) / voxel))
    ny = int(math.ceil((v1 - v0) / voxel))
    if nx <= 0 or ny <= 0:
        return False

    occ = np.zeros((ny, nx), dtype=np.uint8)

    def point_in_tri_2d(px, py, ax, ay, bx, by, cx, cy) -> bool:
        v0x = bx - ax; v0y = by - ay
        v1x = cx - ax; v1y = cy - ay
        v2x = px - ax; v2y = py - ay
        dot00 = v0x * v0x + v0y * v0y
        dot01 = v0x * v1x + v0y * v1y
        dot02 = v0x * v2x + v0y * v2y
        dot11 = v1x * v1x + v1y * v1y
        dot12 = v1x * v2x + v1y * v2y
        denom = dot00 * dot11 - dot01 * dot01
        if abs(denom) < 1e-12:
            return False
        inv = 1.0 / denom
        uu = (dot11 * dot02 - dot01 * dot12) * inv
        vv = (dot00 * dot12 - dot01 * dot02) * inv
        eps = -1e-4
        return (uu >= eps) and (vv >= eps) and (uu + vv <= 1.0 - eps)

    # 1) rasterize each patch face into the grid
    for fidx in P.faces:
        u_a, v_a = project_pos(int(fi[fidx, 0]))
        u_b, v_b = project_pos(int(fi[fidx, 1]))
        u_c, v_c = project_pos(int(fi[fidx, 2]))

        tumin = min(u_a, u_b, u_c); tumax = max(u_a, u_b, u_c)
        tvmin = min(v_a, v_b, v_c); tvmax = max(v_a, v_b, v_c)

        ix0 = int(math.floor((tumin - u0) / voxel)) - 1
        ix1 = int(math.floor((tumax - u0) / voxel)) + 1
        iy0 = int(math.floor((tvmin - v0) / voxel)) - 1
        iy1 = int(math.floor((tvmax - v0) / voxel)) + 1
        if ix0 < 0: ix0 = 0
        if iy0 < 0: iy0 = 0
        if ix1 >= nx: ix1 = nx - 1
        if iy1 >= ny: iy1 = ny - 1

        for iy in range(iy0, iy1 + 1):
            for ix in range(ix0, ix1 + 1):
                if occ[iy, ix]:
                    continue
                x0 = u0 + ix * voxel
                y0 = v0 + iy * voxel
                x1 = x0 + voxel
                y1 = y0 + voxel
                xc = 0.5 * (x0 + x1)
                yc = 0.5 * (y0 + y1)
                if (point_in_tri_2d(x0, y0, u_a, v_a, u_b, v_b, u_c, v_c)
                        or point_in_tri_2d(x1, y0, u_a, v_a, u_b, v_b, u_c, v_c)
                        or point_in_tri_2d(x0, y1, u_a, v_a, u_b, v_b, u_c, v_c)
                        or point_in_tri_2d(x1, y1, u_a, v_a, u_b, v_b, u_c, v_c)
                        or point_in_tri_2d(xc, yc, u_a, v_a, u_b, v_b, u_c, v_c)):
                    occ[iy, ix] = 1

    # 2) scan: solid → empty(>=2.4mm) → solid, both side solids >= 0.6mm
    empty_min = 2.4
    solid_min = 0.6
    step = voxel

    def has_hole(horizontal: bool) -> bool:
        outer = ny if horizontal else nx
        inner = nx if horizontal else ny
        for line in range(outer):
            state = 0
            s1 = empty = s2 = 0.0
            for k in range(inner):
                solid = (occ[line, k] != 0) if horizontal else (occ[k, line] != 0)
                if solid:
                    if state == 0:
                        state = 1; s1 = step
                    elif state == 1:
                        s1 += step
                    elif state == 2:
                        state = 3; s2 = step
                    elif state == 3:
                        s2 += step
                else:
                    if state == 1:
                        state = 2; empty = step
                    elif state == 2:
                        empty += step
                    elif state == 3:
                        if empty >= empty_min and s1 >= solid_min and s2 >= solid_min:
                            return True
                        state = 0; s1 = empty = s2 = 0.0
                if state == 3 and empty >= empty_min and s1 >= solid_min and s2 >= solid_min:
                    return True
            if state == 3 and empty >= empty_min and s1 >= solid_min and s2 >= solid_min:
                return True
        return False

    return has_hole(True) or has_hole(False)


def _is_drill_patch_by_edges(mesh: _Mesh, P: _Patch) -> bool:
    """Port of isDrillPatchByEdges (stage 2)."""
    if len(P.faces) < 5 or P.area <= 0.0:
        return False

    n_patch = _normalize(P.avg_normal)
    if _norm(n_patch) < 0.5:
        return False

    ex, ey = _build_orthonormal_basis(n_patch)
    v = mesh.v
    fi = mesh.fi
    center = P.center

    def project_to_plane(vid: int) -> tuple:
        p = v[vid]
        qx = float(p[0]) - float(center[0])
        qy = float(p[1]) - float(center[1])
        qz = float(p[2]) - float(center[2])
        u = qx * float(ex[0]) + qy * float(ex[1]) + qz * float(ex[2])
        vv = qx * float(ey[0]) + qy * float(ey[1]) + qz * float(ey[2])
        return u, vv

    # overall patch 2D bbox size filter
    uminP = vminP = 1e30
    umaxP = vmaxP = -1e30
    for fidx in P.faces:
        for k in range(3):
            u, vv = project_to_plane(int(fi[fidx, k]))
            uminP = min(uminP, u); umaxP = max(umaxP, u)
            vminP = min(vminP, vv); vmaxP = max(vmaxP, vv)
    width = umaxP - uminP
    height = vmaxP - vminP
    if not (width > 0.0 and height > 0.0):
        return False
    long_edge = width if width > height else height
    short_edge = height if width > height else width
    if long_edge < 6.5 or long_edge > 35.0:
        return False
    if short_edge < 4.0 or short_edge > 35.0:
        return False
    if long_edge > 4.0 * short_edge:
        return False

    if not _patch_has_hole_by_scanlines(mesh, P, ex, ey):
        return False

    # collect "connection edges" between patch and ~perpendicular hole walls
    cos_perp = math.cos(87.0 * 3.14159265 / 180.0)
    conn_edges: list[tuple] = []
    umin = vmin = 1e30
    umax = vmax = -1e30
    edge_faces = mesh.edge_faces
    face_n = mesh.face_n
    patch_id = mesh.patch_id

    for fidx in P.faces:
        a0, a1, a2 = int(fi[fidx, 0]), int(fi[fidx, 1]), int(fi[fidx, 2])
        for (a, b) in ((a0, a1), (a1, a2), (a2, a0)):
            key = (a, b) if a < b else (b, a)
            ef = edge_faces.get(key)
            if ef is None:
                continue
            if ef[0] == fidx:
                other = ef[1]
            elif ef[1] == fidx:
                other = ef[0]
            else:
                continue
            if other < 0:
                continue
            if patch_id[other] == P.id:
                continue
            n_wall = face_n[other]
            lw = _norm(n_wall)
            if lw < 0.5:
                continue
            n_wall = n_wall / lw
            d = abs(_dot(n_wall, n_patch))
            if d > cos_perp:
                continue  # not a ~90° wall
            conn_edges.append((a, b))
            ua, va = project_to_plane(a)
            ub, vb = project_to_plane(b)
            umin = min(umin, ua, ub); umax = max(umax, ua, ub)
            vmin = min(vmin, va, vb); vmax = max(vmax, va, vb)

    if len(conn_edges) < 4:
        return False

    min_diameter = 3.0
    max_diameter = 35.0
    dx = umax - umin
    dy = vmax - vmin
    if dx <= 0.0 or dy <= 0.0:
        return False
    minD = min(dx, dy)
    maxD = max(dx, dy)
    if minD < min_diameter or maxD > max_diameter:
        return False

    # walk edge chains; accumulate turning angle; >= 220° → drill end face
    angle_threshold = 220.0 * 3.14159265 / 180.0
    n_edges = len(conn_edges)
    edge_used = [False] * n_edges

    for start in range(n_edges):
        if edge_used[start]:
            continue
        v0 = conn_edges[start][0]
        v1 = conn_edges[start][1]
        seq = [v0, v1]
        edge_used[start] = True

        # forward from v1
        cur = v1
        while True:
            nxt = None
            nxt_idx = -1
            for ei in range(n_edges):
                if edge_used[ei]:
                    continue
                e = conn_edges[ei]
                if e[0] == cur:
                    nxt = e[1]; nxt_idx = ei; break
                if e[1] == cur:
                    nxt = e[0]; nxt_idx = ei; break
            if nxt_idx == -1:
                break
            edge_used[nxt_idx] = True
            seq.append(nxt)
            cur = nxt
            if cur == v0:
                break

        # backward from v0
        cur = v0
        while True:
            prv = None
            prv_idx = -1
            for ei in range(n_edges):
                if edge_used[ei]:
                    continue
                e = conn_edges[ei]
                if e[0] == cur:
                    prv = e[1]; prv_idx = ei; break
                if e[1] == cur:
                    prv = e[0]; prv_idx = ei; break
            if prv_idx == -1:
                break
            edge_used[prv_idx] = True
            seq.insert(0, prv)
            cur = prv

        if len(seq) < 3:
            continue

        accum = 0.0
        for i in range(len(seq) - 2):
            p0u, p0v = project_to_plane(seq[i])
            p1u, p1v = project_to_plane(seq[i + 1])
            p2u, p2v = project_to_plane(seq[i + 2])
            t0x, t0y = p1u - p0u, p1v - p0v
            t1x, t1y = p2u - p1u, p2v - p1v
            len0 = math.sqrt(t0x * t0x + t0y * t0y)
            len1 = math.sqrt(t1x * t1x + t1y * t1y)
            if len0 < 1e-4 or len1 < 1e-4:
                continue
            t0x /= len0; t0y /= len0
            t1x /= len1; t1y /= len1
            d = _clampf(t0x * t1x + t0y * t1y, -1.0, 1.0)
            accum += math.acos(d)

        if accum >= angle_threshold:
            return True

    return False


def _pick_best_drill_patch_stage3(drill_patches: list[_Patch]):
    """Port of pick_best_drill_patch_stage3: choose the patch whose normal best
    agrees (positive dot) with all other drill patches."""
    if not drill_patches:
        return None
    best = None
    best_score = -1e30
    m = len(drill_patches)
    for i in range(m):
        Pi = drill_patches[i]
        ni = _normalize(Pi.avg_normal)
        if _norm(ni) < 1e-6:
            continue
        score = 0.0
        for j in range(m):
            Pj = drill_patches[j]
            nj = _normalize(Pj.avg_normal)
            if _norm(nj) < 1e-6:
                continue
            d = float(ni[0] * nj[0] + ni[1] * nj[1] + ni[2] * nj[2])
            if d < 0.0:
                d = 0.0
            score += d
        if score > best_score:
            best_score = score
            best = Pi
    return best


# ======================== 入口端判別 (解兩端平手) ========================
#
# 已鎖定目標導孔 (best drill patch) 後，剩下的只是「軸的哪一端朝下」。導孔內
# 部不是單純圓筒，而是有階梯狀結構，這些階梯「踏面」幾乎都朝向入口那一側。
# 策略：
#   1. 以導孔軸為中心軸取一個圓柱範圍 (半徑 ≈ 孔半徑 × 1.5)
#   2. 排除「兩端被偵測到的端面平台」本身 (所有 drill patch 的面) —— 它們對稱
#      會互相抵消，無法分辨入口
#   3. 只統計圓柱內、法向接近 ±軸 (夾角 < tol) 的「內部踏面」，面積加權
#   4. 朝 +軸 / -軸 哪邊踏面面積多，那一側就是入口 → 該方向朝下 (-Z)


def _choose_entrance_direction(mesh: _Mesh, drill_patches: list, best: _Patch):
    """Return (entrance_dir, plus_area, minus_area).

    entrance_dir is ±best.avg_normal — the drill entrance side, which should be
    rotated to face -Z (down).
    """
    axis = _normalize(best.avg_normal)
    ax = axis.astype(np.float64)
    center = best.center.astype(np.float64)

    fi = mesh.fi
    # estimate hole radius from the chosen end-face patch (max radial distance)
    vids = np.unique(fi[np.asarray(best.faces, dtype=np.int64)].reshape(-1).astype(np.int64))
    pts = mesh.v[vids].astype(np.float64)
    dd = pts - center
    along_v = dd @ ax
    perp_v = dd - along_v[:, None] * ax
    R = float(np.linalg.norm(perp_v, axis=1).max()) if len(vids) else 0.0
    if R <= 0.0:
        return axis, 0.0, 0.0

    cyl_radius = R * 1.5
    axial_limit = R * 6.0
    cos_tol = math.cos(25.0 * math.pi / 180.0)  # 法向需接近 ±軸 (±25°)

    m = fi.shape[0]
    # 排除兩端端面平台：所有被偵測為 drill patch 的面
    drill_mask = np.zeros(m, dtype=bool)
    drill_faces: list[int] = []
    for P in drill_patches:
        drill_faces.extend(P.faces)
    if drill_faces:
        drill_mask[np.asarray(drill_faces, dtype=np.int64)] = True

    fc = mesh.face_c.astype(np.float64)
    fn = mesh.face_n.astype(np.float64)
    d = fc - center
    along = d @ ax
    perp = d - along[:, None] * ax
    radial = np.linalg.norm(perp, axis=1)
    dotn = fn @ ax

    sel = ((~drill_mask)
           & (radial < cyl_radius)
           & (np.abs(along) < axial_limit)
           & (np.abs(dotn) > cos_tol))

    areas = mesh.face_area
    plus = float(areas[sel & (dotn > 0.0)].sum())    # 踏面朝 +軸
    minus = float(areas[sel & (dotn < 0.0)].sum())   # 踏面朝 -軸

    # 踏面朝向多的那一側 = 入口
    entrance = axis if plus >= minus else (-axis).astype(np.float32)
    step_faces = np.where(sel)[0].tolist()
    return entrance, plus, minus, step_faces


def _find_guide_direction(vertices: np.ndarray, faces: np.ndarray,
                          debug: bool = False) -> _GuideResult:
    """Port of find_guide_direction."""
    res = _GuideResult()
    if vertices is None or faces is None or len(vertices) == 0 or len(faces) == 0:
        return res

    mesh = _weld_and_build(vertices, faces)
    if mesh.fi.shape[0] == 0:
        return res

    patches = _grow_patches(mesh)
    if not patches:
        res.found = True
        res.dir = np.array([0, 0, 1], dtype=np.float32)
        return res

    drill_patches: list[_Patch] = []
    for P in patches:
        if len(P.faces) < 5 or P.area <= 0.0:
            continue
        if not _is_drill_patch_by_edges(mesh, P):
            continue
        drill_patches.append(P)

    if debug:
        print(f"[surg] patches={len(patches)} drill_candidates={len(drill_patches)}")
        for P in drill_patches:
            n = P.avg_normal
            c = P.center
            print(f"  drill patch id={P.id} faces={len(P.faces)} area={P.area:.3f} "
                  f"n=({n[0]:.4f},{n[1]:.4f},{n[2]:.4f}) "
                  f"center=({c[0]:.2f},{c[1]:.2f},{c[2]:.2f})")

    if not drill_patches:
        return res

    best = _pick_best_drill_patch_stage3(drill_patches)
    if best is None:
        return res

    res.found = True
    res.decision_faces = list(best.faces)
    axis = _normalize(best.avg_normal)
    res.dir = axis

    # Tiebreaker: only when the SAME hole's two ends are both detected (i.e. a
    # drill candidate exists whose normal is nearly opposite to best) is the end
    # ambiguous. Only then do we use the internal step faces to decide which end
    # is the entrance (faces down). Otherwise the patch normal is trusted as-is.
    has_opposite_end = any(
        _dot(axis, _normalize(P.avg_normal)) < -0.7
        for P in drill_patches if P is not best
    )
    if has_opposite_end:
        entrance, plus, minus, step_faces = _choose_entrance_direction(mesh, drill_patches, best)
        res.dir = _normalize(entrance)
        res.step_faces = step_faces
        if debug:
            print(f"[surg] ambiguous ends -> entrance vote "
                  f"+axis={plus:.3f} -axis={minus:.3f}")

    if debug:
        n = res.dir
        print(f"[surg] chosen drill patch id={best.id} "
              f"dir=({n[0]:.4f},{n[1]:.4f},{n[2]:.4f})")
    return res


# --------------------------------------------------------------------------- #
#  Public entry                                                                #
# --------------------------------------------------------------------------- #


def compute_auto_orientation_surg_guide(vertices: np.ndarray,
                                        faces: np.ndarray,
                                        debug: bool = False) -> list:
    """Compute surgical-guide auto-orientation Euler angles.

    Parameters
    ----------
    vertices : (N,3) array-like of float — model vertices (local space).
    faces    : (M,3) array-like of int   — triangle vertex indices.
    debug    : if True, print detected drill patches and the chosen direction.

    Returns
    -------
    [rx, ry, rz] : list of 3 floats (radians), to be applied with Euler
    order 'ZYX'. Returns [0,0,0] when no drill end face is found (no rotation),
    mirroring the C++ fallback.
    """
    return compute_auto_orientation_surg_guide_detail(vertices, faces, debug)["rotation_rad"]


def compute_auto_orientation_surg_guide_detail(vertices: np.ndarray,
                                               faces: np.ndarray,
                                               debug: bool = False) -> dict:
    """Same as :func:`compute_auto_orientation_surg_guide` but also returns the
    triangle indices used for debug visualization.

    Returns
    -------
    {
        "rotation_rad": [rx, ry, rz],     # radians, apply with Euler order 'ZYX'
        "decision_faces": [int, ...],      # chosen drill end-face patch triangles
        "step_faces": [int, ...],          # internal step faces (tiebreak only)
    }
    Triangle indices are into the input ``faces`` array.
    """
    v = np.ascontiguousarray(vertices, dtype=np.float32)
    f = np.ascontiguousarray(faces, dtype=np.uint32)
    if v.ndim != 2 or v.shape[1] != 3:
        raise ValueError("vertices must be (N,3)")
    if f.ndim != 2 or f.shape[1] != 3:
        raise ValueError("faces must be (M,3)")

    r = _find_guide_direction(v, f, debug=debug)
    if not r.found:
        return {"rotation_rad": [0.0, 0.0, 0.0], "decision_faces": [], "step_faces": []}

    # drill direction aligned to -Z (entrance facing down)
    out = _normal_to_euler_xyz_align_to_minus_z(r.dir)
    return {
        "rotation_rad": [float(out[0]), float(out[1]), float(out[2])],
        "decision_faces": [int(x) for x in r.decision_faces],
        "step_faces": [int(x) for x in r.step_faces],
    }


# --------------------------------------------------------------------------- #
#  CLI: run against an STL and print the detected orientation                  #
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    import sys
    import trimesh

    if len(sys.argv) < 2:
        print("usage: python -m agent.auto_orient_surg_guide <model.stl>")
        sys.exit(1)

    path = sys.argv[1]
    mesh = trimesh.load(path)
    if isinstance(mesh, trimesh.Scene):
        mesh = trimesh.util.concatenate(mesh.dump())

    verts = np.asarray(mesh.vertices, dtype=np.float32)
    faces = np.asarray(mesh.faces, dtype=np.uint32)
    print(f"loaded {path}: {len(verts)} verts, {len(faces)} faces")

    rad = compute_auto_orientation_surg_guide(verts, faces, debug=True)
    deg = [r * 180.0 / math.pi for r in rad]
    print(f"rotation_rad = {rad}")
    print(f"rotation_deg = {deg}")

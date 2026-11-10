"""Count the head-bridge defects of openspec change sla-head-bridge-clearance on an
exported support tree (--export-support-tree, format version 2).

Every bar is classified by its exported "kind"; nothing is inferred from export
order. Clearance is the 3D distance between two axis segments against
r1 + r2 + margin (equal passes), never a plan-view test. Two elements that share
a pillar P, by index, are clipped outside a vertical cylinder of radius
R_P = r_P + r1 + r2 + 0.2 around P's axis before they are measured (spec
"共用柱接點須以動態半徑 R 豁免").

Counted:
  A        head/route bar x head/route bar of another head's path
  A_prop   head/route bar x prop bar (an auxiliary pillar's bar)
  B        head/route bar x truss, judged the way the bracing planner judges
           it (sla-head-bridge-clearance Task 5): every pillar the head/route
           bar ends on that is in the cluster of one of the truss's two end
           pillars is clipped out, each by its own axis and
           R = max(r_start, r_end) + r1 + r2 + 0.2. Pillars hug, and so are one
           cluster, when their axes are closer in plan view than
           r_start1 + r_start2 + 0.2, directly or through others.
           B_shared_outside_R is the part where such a pillar was clipped and
           the two still collide outside R
  C_pillar head/route bar x a pillar that is not one of its ends (auxiliary
           pillars excluded, see revC)
  C_head   head/route bar x another head (pos -> junction point, r_back)
  revC_aux   an auxiliary pillar or a prop bar x a head, a head/route bar, a
             pillar it does not end on, or another prop bar (A_prop excluded)
  revC_head  any other pillar x a head it does not carry, split into
    revC_head_native  the pillar was grown by a head that is itself natively
                      too close to the head it touches (head_x_head): support
                      point spacing, excluded from acceptance by the ruling of
                      2026-10-19 (proposal non-goal), counted only
    revC_head_net     the rest; this is what acceptance reads
           The export does not say which element came first; only an
           auxiliary pillar is known to have come after every head bar, so a
           bar crossing any other pillar is counted under C_pillar. Acceptance
           reads A + C + revC together.
  head_x_head  two heads closer than the clearance, measured on the bare
           capsules (no shared-carrier R clipping): it depends on the support
           points alone, never on how the heads were routed
  D        heads with more than one way down: head bars, routes leaving the
           junction, and own pillars that no head bar starts from
  thick_on_thin  head bars onto a pillar with r_start < the head's r_back
  dup_truss_pairs / dup_truss_bars  truss bars built twice, same geometry,
           between one pair
  pairs_excess  sum over pillars of `pairs` (one per accepted bracing group)
           minus the distinct pillars its truss bars reach: a second group on
           a pair that already has one shows here even when its bars differ
  warnings  the tree's top level "warnings" (heads kept at L2), and the
           contacts they list

The counts and their names are those of head_bridge_metrics() in the fork's
tests/sla_print/sla_head_bridge_metrics.cpp, which reads the builder instead.

Shared pillars (R clipping, bar-vs-own-end, head-vs-carrier) are decided by the
exported indices. Which head a bar belongs to is not exported, so path
membership is traced: a head bar by its `a` (the head's own short pillar) or by
starting on the head's junction point, a route by chaining from the junction
point, and the pillar a route comes down on by the route bar's `b`.

Known limits of the export, not of this script: anchors (connect_to_model_body)
are not exported and so are not checked; a head whose ground pillar went
through search_widening_path has its `pillar` read from the wrong array
(SupportTree.cpp takes h.bridge_id as an m_bridges index while it holds a
DiffBridge index), so its carrier may be wrong.

Usage: analyze_tree.py TREE.json [--margin 0.2] [--json OUT.json] [--list N]
"""
import argparse
import json
import sys

import numpy as np

SAFETY = 0.2          # mm, the clearance R is built with (fixed by the spec)
POS_TOL = 1e-4        # mm, two exported points are the same point
EPS = 1e-12


# ── geometry ────────────────────────────────────────────────────────────────

def seg_seg(p1, q1, p2, q2):
    """Closest points of two segments (Ericson 5.1.9). Returns (dist, c1, c2)."""
    d1, d2, r = q1 - p1, q2 - p2, p1 - p2
    a, e, f = d1 @ d1, d2 @ d2, d2 @ r
    if a <= EPS and e <= EPS:
        s = t = 0.0
    elif a <= EPS:
        s, t = 0.0, float(np.clip(f / e, 0.0, 1.0))
    else:
        c = d1 @ r
        if e <= EPS:
            t, s = 0.0, float(np.clip(-c / a, 0.0, 1.0))
        else:
            b = d1 @ d2
            den = a * e - b * b
            s = float(np.clip((b * f - c * e) / den, 0.0, 1.0)) if den > EPS else 0.0
            t = (b * s + f) / e
            if t < 0.0:
                t, s = 0.0, float(np.clip(-c / a, 0.0, 1.0))
            elif t > 1.0:
                t, s = 1.0, float(np.clip((b - c) / a, 0.0, 1.0))
    c1, c2 = p1 + s * d1, p2 + t * d2
    return float(np.linalg.norm(c1 - c2)), c1, c2


def inside_interval(s, e, axis_xy, R):
    """Parameter interval of s->e strictly inside the vertical cylinder, or None."""
    d = (e - s)[:2]
    w = s[:2] - axis_xy
    a = d @ d
    c = w @ w - R * R
    if a <= EPS:                       # vertical bar: all in or all out
        return (0.0, 1.0) if c < 0.0 else None
    b = 2.0 * (d @ w)
    disc = b * b - 4.0 * a * c
    if disc <= 0.0:
        return None
    sq = np.sqrt(disc)
    t1, t2 = (-b - sq) / (2.0 * a), (-b + sq) / (2.0 * a)
    lo, hi = max(t1, 0.0), min(t2, 1.0)
    return (lo, hi) if lo < hi else None


def clip_outside(s, e, cylinders):
    """Pieces of s->e left after removing every cylinder (axis_xy, R)."""
    keep = [(0.0, 1.0)]
    for axis_xy, R in cylinders:
        cut = inside_interval(s, e, axis_xy, R)
        if cut is None:
            continue
        lo, hi = cut
        nxt = []
        for a, b in keep:
            if hi <= a or lo >= b:
                nxt.append((a, b))
                continue
            if a < lo:
                nxt.append((a, lo))
            if hi < b:
                nxt.append((hi, b))
        keep = nxt
    return [(s + a * (e - s), s + b * (e - s)) for a, b in keep]


# ── the tree as capsules ────────────────────────────────────────────────────

def junction_point(h):
    full = 2 * h["r_pin"] + h["width"] + 2 * h["r_back"] - h["penetration"]
    return np.array(h["pos"]) + (full - h["r_back"]) * np.array(h["dir"])


class Elem:
    __slots__ = ("kind", "idx", "s", "e", "r", "pillars", "path", "aux", "sub")

    def __init__(self, kind, idx, s, e, r, pillars, sub=None):
        self.kind, self.idx, self.s, self.e, self.r = kind, idx, s, e, r
        self.pillars = pillars      # pillar indices this element touches, by id
        self.path = None            # head index whose path it belongs to
        self.aux = False
        self.sub = sub              # bar kind for bars


def key(p):
    return tuple(np.round(np.asarray(p) / POS_TOL).astype(np.int64))


def load(tree):
    H, P, B = tree["heads"], tree["pillars"], tree["bridges"]
    heads, pillars, bars = [], [], []
    for k, h in enumerate(H):
        car = h.get("pillar", -1)
        heads.append(Elem("head", k, np.array(h["pos"], float), junction_point(h),
                          h["r_back"], {car} - {-1}))
    for i, p in enumerate(P):
        foot = np.array(p["endpt"], float)
        el = Elem("pillar", i, foot, foot + np.array([0.0, 0.0, p["height"]]),
                  max(p["r_start"], p["r_end"]), {i})
        el.aux = p.get("props", -1) >= 0
        el.path = p.get("head", -1) if p.get("head", -1) >= 0 else None
        pillars.append(el)
    missing = 0
    for j, b in enumerate(B):
        kind = b.get("kind")
        if kind is None:
            missing += 1
        r = max(b["r"], b.get("end_r", b["r"]))
        bars.append(Elem("bar", j, np.array(b["startp"], float), np.array(b["endp"], float),
                         r, {b.get("a", -1), b.get("b", -1)} - {-1}, sub=kind))
    if missing:
        sys.exit(f"{missing} bars have no 'kind': this tree predates the planar export; "
                 "rebuild the engine from the merged branch")
    return H, P, B, heads, pillars, bars


def assign_paths(H, P, B, heads, pillars, bars):
    """Tie each head/route bar, and the pillars those grow, to the head it carries."""
    jp_at = {key(h.e): h.idx for h in heads}
    route_from = {}
    for bar in bars:
        if bar.sub == "route":
            route_from.setdefault(key(bar.s), []).append(bar)
    for bar in bars:
        if bar.sub != "head":
            continue
        a = B[bar.idx].get("a", -1)
        if a >= 0 and pillars[a].path is not None:
            bar.path = pillars[a].path             # from the head's own short pillar
        else:
            bar.path = jp_at.get(key(bar.s))
    for h in heads:                                  # routes chain from the junction
        frontier, seen = [key(h.e)], set()
        while frontier:
            k = frontier.pop()
            if k in seen:
                continue
            seen.add(k)
            for bar in route_from.get(k, []):
                if bar.path is None:
                    bar.path = h.idx
                    frontier.append(key(bar.e))
                    tgt = B[bar.idx].get("b", -1)    # the pillar the route came down on
                    if tgt >= 0 and pillars[tgt].path is None and not pillars[tgt].aux:
                        pillars[tgt].path = h.idx
    for h in heads:
        h.path = h.idx


# ── checks ──────────────────────────────────────────────────────────────────

def measure(x, y, margin, pillars, clip_shared=True, shared=None):
    """(violates, dist, required, contact, shared) for two capsules. With
    clip_shared, a pillar both touch (by index) is clipped out to R first;
    `shared`, when given, names the pillars to clip instead."""
    need = x.r + y.r + margin
    if shared is None:
        shared = x.pillars & y.pillars if clip_shared else set()
    if not shared:
        d, c1, _ = seg_seg(x.s, x.e, y.s, y.e)
        return d < need, d, need, c1, False
    cyl = []
    for pid in shared:
        p = pillars[pid]
        cyl.append((p.s[:2], p.r + x.r + y.r + SAFETY))
    px, py = clip_outside(x.s, x.e, cyl), clip_outside(y.s, y.e, cyl)
    best = (np.inf, None)
    for a0, a1 in px:
        for b0, b1 in py:
            d, c1, _ = seg_seg(a0, a1, b0, b1)
            if d < best[0]:
                best = (d, c1)
    return best[0] < need, best[0], need, best[1], True


def broadphase(elems, margin):
    lo = np.array([np.minimum(e.s, e.e) - (e.r + margin / 2) for e in elems])
    hi = np.array([np.maximum(e.s, e.e) + (e.r + margin / 2) for e in elems])
    for i in range(len(elems) - 1):
        m = np.all((lo[i + 1:] <= hi[i]) & (hi[i + 1:] >= lo[i]), axis=1)
        for j in np.nonzero(m)[0]:
            yield elems[i], elems[i + 1 + j]


def is_path_bar(e):
    return e.kind == "bar" and e.sub in ("head", "route")


RANK = {"bar": 0, "pillar": 1, "head": 2}


def category(x, y):
    """Which count a pair falls in (or None), with the pair ordered bar, pillar,
    head. Bar-vs-own-end and head-vs-carrier go by exported index; same-path
    goes by the membership assign_paths() traced."""
    if RANK[x.kind] > RANK[y.kind]:
        x, y = y, x
    # elements of one head's path never count against each other
    if x.path is not None and x.path == y.path:
        return None, x, y
    kinds = (x.kind, y.kind)
    if kinds == ("bar", "bar"):
        if not is_path_bar(x):
            x, y = y, x
        if not is_path_bar(x):
            return ("revC_aux" if x.sub == "prop" and y.sub == "prop" else None), x, y
        if is_path_bar(y):
            return "A", x, y
        if y.sub == "prop":
            return "A_prop", x, y
        if y.sub == "truss":
            return "B", x, y
        return None, x, y
    if kinds == ("bar", "pillar"):
        if y.idx in x.pillars:                           # a bar vs its own end
            return None, x, y
        if x.sub == "prop":
            return "revC_aux", x, y
        if not is_path_bar(x):
            return None, x, y
        return ("revC_aux" if y.aux else "C_pillar"), x, y
    if kinds == ("bar", "head"):
        if x.sub == "prop":
            return "revC_aux", x, y
        return ("C_head" if is_path_bar(x) else None), x, y
    if kinds == ("pillar", "head"):
        if x.idx in y.pillars:                           # a head vs its carrier
            return None, x, y
        return ("revC_aux" if x.aux else "revC_head"), x, y
    if kinds == ("head", "head"):
        return "head_x_head", x, y
    return None, x, y


def cluster_roots(P):
    """The cluster of every pillar, by index: the lowest index in it. Axes
    closer in plan view than r_start1 + r_start2 + 0.2 hug (the bracing
    planner's rule, BracingPlanner::add_pillar)."""
    parent = list(range(len(P)))

    def find(i):
        while parent[i] != i:
            i = parent[i]
        return i

    if not P:
        return []
    xy = np.array([p["endpt"][:2] for p in P], float)
    r = np.array([p["r_start"] for p in P], float)
    for i in range(len(P) - 1):
        d = np.linalg.norm(xy[i + 1:] - xy[i], axis=1)
        for j in np.nonzero(d < r[i] + r[i + 1:] + SAFETY)[0]:
            a, b = find(i), find(i + 1 + int(j))
            if a != b:
                parent[max(a, b)] = min(a, b)
    return [find(i) for i in range(len(P))]


def analyze(tree, margin=0.2, keep=50):
    H, P, B, heads, pillars, bars = load(tree)
    assign_paths(H, P, B, heads, pillars, bars)
    root = cluster_roots(P)

    counts = {c: 0 for c in ("A", "A_prop", "B", "B_shared_outside_R", "C_pillar",
                             "C_head", "revC_aux", "revC_head", "revC_head_native",
                             "revC_head_net", "head_x_head")}
    contacts = {c: [] for c in counts}

    def note(cat, rec):
        counts[cat] += 1
        if len(contacts[cat]) < keep:
            contacts[cat].append(rec)

    # Natively too close: bare capsules, so it cannot depend on routing.
    native = set()
    for x, y in broadphase(heads, margin):
        bad, d, need, at, _ = measure(x, y, margin, pillars, clip_shared=False)
        if bad:
            native.add(frozenset((x.idx, y.idx)))
            note("head_x_head", {"x": ["head", x.idx], "y": ["head", y.idx],
                                 "dist": round(d, 4), "required": round(need, 4),
                                 "at": [round(v, 3) for v in at]})

    for x, y in broadphase(heads + pillars + bars, margin):
        cat, x, y = category(x, y)
        if cat is None or cat == "head_x_head":
            continue
        joints = None
        if cat == "B":   # x the head/route bar, y the truss
            ends = {root[q] for q in y.pillars}
            joints = {pid for pid in x.pillars if root[pid] in ends}
        bad, d, need, at, shared = measure(x, y, margin, pillars, shared=joints)
        if not bad:
            continue
        rec = {"x": [x.kind if x.kind != "bar" else x.sub, x.idx],
               "y": [y.kind if y.kind != "bar" else y.sub, y.idx],
               "dist": round(d, 4), "required": round(need, 4),
               "at": [round(v, 3) for v in at]}
        note(cat, rec)
        if cat == "B" and shared:
            note("B_shared_outside_R", rec)
        if cat == "revC_head":
            grower = P[x.idx].get("head", -1)
            native_pair = grower >= 0 and frozenset((grower, y.idx)) in native
            note("revC_head_native" if native_pair else "revC_head_net", rec)

    # D: more than one way down for one head
    ways = {h.idx: 0 for h in heads}
    bar_from_pillar = {B[b.idx].get("a", -1) for b in bars if b.sub == "head"}
    for b in bars:
        if b.sub == "head" and b.path is not None:
            ways[b.path] += 1
        elif b.sub == "route" and b.path is not None and key(b.s) == key(heads[b.path].e):
            ways[b.path] += 1
    for p in pillars:
        if p.path is not None and P[p.idx].get("head", -1) == p.path \
                and p.idx not in bar_from_pillar:
            ways[p.path] += 1
    d_heads = sorted(k for k, n in ways.items() if n > 1)

    thick = []
    for b in bars:
        tgt = B[b.idx].get("b", -1)
        if b.sub == "head" and b.path is not None and tgt >= 0 \
                and P[tgt]["r_start"] < H[b.path]["r_back"] - 1e-9:
            thick.append([b.idx, b.path, tgt])

    groups = {}
    for b in bars:
        if b.sub != "truss" or len(b.pillars) != 2:
            continue
        pair = tuple(sorted(b.pillars))
        geo = tuple(sorted((key(b.s), key(b.e))))
        groups.setdefault(pair, {}).setdefault(geo, []).append(b.idx)
    dup_pairs = [list(p) for p, g in groups.items() if any(len(v) > 1 for v in g.values())]
    dup_bars = sum(len(v) - 1 for g in groups.values() for v in g.values() if len(v) > 1)
    neighbours = {}
    for a_, b_ in groups:
        neighbours.setdefault(a_, set()).add(b_)
        neighbours.setdefault(b_, set()).add(a_)
    excess = [[i, p["pairs"], len(neighbours.get(i, ()))] for i, p in enumerate(P)
              if p["pairs"] > len(neighbours.get(i, ()))]

    kinds = {}
    for b in bars:
        kinds[b.sub] = kinds.get(b.sub, 0) + 1
    unassigned = sum(1 for b in bars if b.sub in ("head", "route") and b.path is None)
    return {
        "margin": margin,
        "heads": len(H), "pillars": len(P),
        "aux_pillars": sum(1 for p in pillars if p.aux),
        "bars": len(B), "bars_by_kind": kinds,
        "unassigned_path_bars": unassigned,
        **counts,
        "D": len(d_heads),
        "thick_on_thin": len(thick),
        "dup_truss_pairs": len(dup_pairs),
        "dup_truss_bars": dup_bars,
        "pairs_excess": sum(e[1] - e[2] for e in excess),
        "warnings": len(tree.get("warnings", [])),
        "warning_contacts": sum(len(w.get("contacts", [])) for w in tree.get("warnings", [])),
        "detail": {**contacts, "D": d_heads[:keep], "thick_on_thin": thick[:keep],
                   "dup_truss_pairs": dup_pairs[:keep],
                   "pairs_excess": excess[:keep]},
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("tree")
    ap.add_argument("--margin", type=float, default=0.2)
    ap.add_argument("--json", help="write the full result here")
    ap.add_argument("--list", type=int, default=0, help="print up to N contacts per count")
    a = ap.parse_args()
    with open(a.tree, encoding="utf-8") as f:
        res = analyze(json.load(f), a.margin, keep=max(a.list, 50))
    summary = {k: v for k, v in res.items() if k != "detail"}
    print(json.dumps(summary, ensure_ascii=False))
    for k, v in res["detail"].items():
        for rec in v[:a.list]:
            print(f"  {k}: {rec}")
    if a.json:
        with open(a.json, "w", encoding="utf-8", newline="\n") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()

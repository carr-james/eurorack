"""Ratsnest metrics: total length and crossing count, from pad positions."""
import math, itertools

def mst(pts):
    n = len(pts)
    if n < 2: return []
    inside, out, edges = {0}, set(range(1, n)), []
    while out:
        a, b = min(((i, j) for i in inside for j in out),
                   key=lambda e: (pts[e[0]][0]-pts[e[1]][0])**2 + (pts[e[0]][1]-pts[e[1]][1])**2)
        edges.append((a, b)); inside.add(b); out.discard(b)
    return edges

def _crosses(p, q, r, s):
    def o(a, b, c):
        v = (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])
        return 0 if abs(v) < 1e-9 else (1 if v > 0 else -1)
    if p in (r, s) or q in (r, s): return False        # shared pad is not a crossing
    return o(p,q,r) != o(p,q,s) and o(r,s,p) != o(r,s,q)

def evaluate(netlist, padpos):
    """-> (total mm, crossings, segment count). Segments are per-net MST edges,
    which is what KiCad draws as the ratsnest."""
    segs, total = [], 0.0
    for name, nodes in netlist:
        pts = list(dict.fromkeys(padpos[n] for n in nodes if n in padpos))
        for a, b in mst(pts):
            segs.append((pts[a], pts[b], name)); total += math.dist(pts[a], pts[b])
    cross = sum(1 for (p,q,n1), (r,s,n2) in itertools.combinations(segs, 2)
                if n1 != n2 and _crosses(p, q, r, s))
    return total, cross, len(segs)

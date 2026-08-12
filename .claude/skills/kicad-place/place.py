#!/usr/bin/env python3
"""Component placement that minimises ratsnest crossings.

  measure   <pcb> <net>                     report length and crossings
  optimise  <pcb> <net> [opts]              search, write placement JSON
  apply     <pcb> <json>                    write positions back, re-verify

Always run selfcheck.py first. See SKILL.md.
"""
import sys, math, json, time, random, argparse, re
import kicadpcb as K, ratsnest

FIXED_DEFAULT = "J1,J2,J3"
POWER = {"+5V", "+12VA", "-12VA", "+12V", "-12V", "VCC", "VDD"}

class Board:
    def __init__(self, pcb, net, fixed, region, grid=0.635):
        self.src, self.fps = K.load(pcb)
        self.nl = K.nets(net)
        self.grid = grid
        self.X0, self.Y0, self.X1, self.Y1 = region
        self.LR = {r: K.local_rect(self.src, self.fps, r) for r in self.fps}
        self.pos = {r: [self.fps[r]['x'], self.fps[r]['y']] for r in self.fps}
        self.rot = {r: self.fps[r]['rot'] for r in self.fps}
        self.mech = [r for r in self.fps if re.match(r'^(MH|FID)\d+$', r)]
        self.onboard = [r for r in self.fps if r not in self.mech]
        self.fixed = set(fixed) | set(self.mech)
        self.movable = [r for r in self.onboard if r not in self.fixed]

    def rect(self, r, x=None, y=None, rr=None):
        return K.abs_rect(self.LR[r],
                          self.pos[r][0] if x is None else x,
                          self.pos[r][1] if y is None else y,
                          self.rot[r] if rr is None else rr)

    def inside(self, rc):
        return self.X0 <= rc[0] and rc[2] <= self.X1 and self.Y0 <= rc[1] and rc[3] <= self.Y1

    def ok(self, r, x=None, y=None, rr=None):
        rc = self.rect(r, x, y, rr)
        if not self.inside(rc): return False
        return not any(K.overlaps(rc, self.rect(b)) for b in self.onboard if b != r)

    def padpos(self):
        d = {}
        for _, nodes in self.nl:
            for ref, pn in nodes:
                f = self.fps.get(ref)
                if not f: continue
                for q, lx, ly in f['pads']:
                    if q == pn:
                        a = math.radians(-self.rot[ref])
                        d[(ref, pn)] = (self.pos[ref][0]+lx*math.cos(a)-ly*math.sin(a),
                                        self.pos[ref][1]+lx*math.sin(a)+ly*math.cos(a))
                        break
        return d

    def score(self, w_cross):
        t, c, _ = ratsnest.evaluate(self.nl, self.padpos())
        return t + w_cross*c, t, c

    def free_slot(self, r, tx, ty, against, tries=120):
        for i in range(tries):
            rad = i*self.grid
            n = max(1, int(2*math.pi*rad/self.grid)) if rad else 1
            for k in range(n):
                a = 2*math.pi*k/n
                x = round((tx+rad*math.cos(a))/self.grid)*self.grid
                y = round((ty+rad*math.sin(a))/self.grid)*self.grid
                for rr in (self.rot[r], (self.rot[r]+90) % 360):
                    rc = K.abs_rect(self.LR[r], x, y, rr)
                    if not self.inside(rc): continue
                    if any(K.overlaps(rc, self.rect(b)) for b in against): continue
                    return x, y, rr
        return None

def spread(B, blocks, steps=650):
    """Force directed, with a pull toward each block's own centroid."""
    of_block = {r: b for b, rs in (blocks or {}).items() for r in rs}
    for i, r in enumerate(B.movable):
        B.pos[r] = [B.X0+5+(i % 6)*7.0, B.Y0+5+(i//6)*11.0]
    for step in range(steps):
        t = 1-step/steps
        F = {r: [0.0, 0.0] for r in B.movable}
        pp = B.padpos()
        for name, nodes in B.nl:
            w = 0.35 if name in POWER else 1.0
            pts = [pp[n] for n in nodes if n in pp]
            if len(pts) < 2: continue
            cx = sum(p[0] for p in pts)/len(pts); cy = sum(p[1] for p in pts)/len(pts)
            wn = w/math.sqrt(len(pts)-1)
            for ref, pn in nodes:
                if ref in F:
                    px, py = pp[(ref, pn)]
                    F[ref][0] += wn*(cx-px); F[ref][1] += wn*(cy-py)
        cen = {}
        for b, rs in (blocks or {}).items():
            rs = [r for r in rs if r in B.fps]
            if rs: cen[b] = (sum(B.pos[r][0] for r in rs)/len(rs), sum(B.pos[r][1] for r in rs)/len(rs))
        for r in B.movable:
            c = cen.get(of_block.get(r))
            if c: F[r][0] += 0.8*(c[0]-B.pos[r][0]); F[r][1] += 0.8*(c[1]-B.pos[r][1])
        for a in B.movable:
            ra = B.rect(a)
            for b in B.onboard:
                if a == b: continue
                rb = B.rect(b)
                if K.overlaps(ra, rb):
                    ox = min(ra[2],rb[2])-max(ra[0],rb[0]); oy = min(ra[3],rb[3])-max(ra[1],rb[1])
                    if ox < oy: F[a][0] += (1 if (ra[0]+ra[2]) >= (rb[0]+rb[2]) else -1)*ox*2.0
                    else:       F[a][1] += (1 if (ra[1]+ra[3]) >= (rb[1]+rb[3]) else -1)*oy*2.0
        for r in B.movable:
            B.pos[r][0] += 0.25*F[r][0]*t; B.pos[r][1] += 0.25*F[r][1]*t
            rc = B.rect(r)
            B.pos[r][0] += max(0, B.X0-rc[0]) - max(0, rc[2]-B.X1)
            B.pos[r][1] += max(0, B.Y0-rc[1]) - max(0, rc[3]-B.Y1)

def legalise(B):
    placed = [r for r in B.onboard if r in B.fixed]
    area = lambda r: (B.LR[r][2]-B.LR[r][0])*(B.LR[r][3]-B.LR[r][1])
    unplaced = []
    for r in sorted(B.movable, key=lambda q: -area(q)):
        slot = B.free_slot(r, B.pos[r][0], B.pos[r][1], placed)
        if slot: B.pos[r] = [slot[0], slot[1]]; B.rot[r] = slot[2]; placed.append(r)
        else: unplaced.append(r)
    return unplaced

def anneal(B, budget, w_cross):
    cur, t, c = B.score(w_cross)
    best = (cur, {r: list(B.pos[r]) for r in B.movable}, dict(B.rot))
    t0 = time.time(); it = 0
    while time.time()-t0 < budget:
        it += 1; frac = (time.time()-t0)/budget; T = max(0.02, 25.0*(1-frac)**2)
        r = random.choice(B.movable); op, orr = list(B.pos[r]), B.rot[r]
        m = random.random(); partner = pp_old = None
        if m < 0.5:
            s = 9.0*(1-frac)+0.7
            B.pos[r] = [round((op[0]+random.gauss(0, s))/B.grid)*B.grid,
                        round((op[1]+random.gauss(0, s))/B.grid)*B.grid]
        elif m < 0.68:
            B.rot[r] = (B.rot[r] + random.choice([90, 180, 270])) % 360
        else:
            partner = random.choice(B.movable)
            if partner == r: continue
            pp_old = list(B.pos[partner]); B.pos[r], B.pos[partner] = list(pp_old), list(op)
        # both parts already moved: check each against EVERYTHING, including each other
        if B.ok(r) and (partner is None or B.ok(partner)):
            cc, t, c = B.score(w_cross)
            if cc < cur or random.random() < math.exp((cur-cc)/T):
                cur = cc
                if cc < best[0]: best = (cc, {q: list(B.pos[q]) for q in B.movable}, dict(B.rot))
                continue
        B.pos[r] = op; B.rot[r] = orr
        if partner is not None: B.pos[partner] = pp_old
    for r in B.movable: B.pos[r] = best[1][r]; B.rot[r] = best[2][r]
    # repair: the search must never be trusted to emit a legal state on its own
    for r in [q for q in B.movable if not B.ok(q)]:
        slot = B.free_slot(r, B.pos[r][0], B.pos[r][1], [b for b in B.onboard if b != r])
        if slot: B.pos[r] = [slot[0], slot[1]]; B.rot[r] = slot[2]
    return it

def write_back(pcb, placement):
    """Move footprints. Rotating one must also rotate its text items, or KiCad
    reports lib_footprint_mismatch on every rotated part."""
    s = open(pcb).read(); edits = []
    for m in re.finditer(r'\(footprint "', s):
        st = m.start(); en = K.balanced(s, st); blk = s[st:en]
        ref = re.search(r'\(property "Reference" "([^"]+)"', blk)
        if not ref or ref.group(1) not in placement: continue
        x, y, rr = placement[ref.group(1)]
        am = re.search(r'\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)', blk)
        old_rot = float(am.group(3) or 0)
        delta = (float(rr) - old_rot) % 360
        body = blk[:am.start()] + (f'(at {x} {y}' + (f' {int(rr)})' if float(rr) else ')')) + blk[am.end():]
        if delta:
            def bump(t):
                out, i = [], 0
                for tm in re.finditer(r'\((?:property "[^"]*" "[^"]*"|fp_text \w+ "[^"]*")\s*\n\s*\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)', t):
                    ang = (float(tm.group(3) or 0) + delta) % 360
                    a0 = tm.start(1) - len(tm.group(0)) + tm.end(0)
                    inner = re.search(r'\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)', tm.group(0))
                    rep = f'(at {tm.group(1)} {tm.group(2)} {ang:g})'
                    out.append((tm.start(0) + inner.start(), tm.start(0) + inner.end(), rep))
                for a, b, r in sorted(out, reverse=True): t = t[:a] + r + t[b:]
                return t
            body = bump(body)
        edits.append((st, en, body))
    for a, b, newblk in sorted(edits, reverse=True): s = s[:a]+newblk+s[b:]
    open(pcb, "w").write(s)
    return len(edits)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["measure", "optimise", "apply"])
    ap.add_argument("pcb"); ap.add_argument("arg2")
    ap.add_argument("--fixed", default=FIXED_DEFAULT)
    ap.add_argument("--region", default="21.5,21.5,67.5,128.5")
    ap.add_argument("--blocks", default=None, help="JSON {block: [refs]} for cohesion")
    ap.add_argument("--budget", type=float, default=180.0)
    ap.add_argument("--w-cross", type=float, default=30.0)
    ap.add_argument("--out", default="placement.json")
    a = ap.parse_args()
    region = tuple(float(v) for v in a.region.split(","))
    region = (region[0], region[1], region[2], region[3])

    if a.cmd == "apply":
        placement = json.load(open(a.arg2))
        n = write_back(a.pcb, placement)
        B = Board(a.pcb, a.arg2 if False else None, [], region) if False else None
        print(f"applied {n} footprints")
        return

    B = Board(a.pcb, a.arg2, a.fixed.split(","), region)
    if a.cmd == "measure":
        t, c, n = ratsnest.evaluate(B.nl, B.padpos())
        print(f"length {t:8.1f} mm   crossings {c:4d}   segments {n}")
        bad = [r for r in B.onboard if not B.ok(r)]
        print(f"movable {len(B.movable)}   illegal {len(bad)} {bad[:6]}")
        return

    blocks = json.load(open(a.blocks)) if a.blocks else None
    t, c, _ = ratsnest.evaluate(B.nl, B.padpos()); print(f"before     length {t:7.1f}  crossings {c:3d}", flush=True)
    spread(B, blocks)
    un = legalise(B)
    t, c, _ = ratsnest.evaluate(B.nl, B.padpos()); print(f"legalised  length {t:7.1f}  crossings {c:3d}  unplaced {un}", flush=True)
    it = anneal(B, a.budget, a.w_cross)
    t, c, _ = ratsnest.evaluate(B.nl, B.padpos())
    bad = [r for r in B.movable if not B.ok(r)]
    print(f"annealed   length {t:7.1f}  crossings {c:3d}  iters {it}  illegal {len(bad)}", flush=True)
    json.dump({r: [round(B.pos[r][0], 3), round(B.pos[r][1], 3), B.rot[r]] for r in B.movable},
              open(a.out, "w"))

if __name__ == "__main__":
    main()

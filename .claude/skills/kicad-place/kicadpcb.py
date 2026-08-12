"""Read a .kicad_pcb: footprints, pads, courtyards. Geometry lives here."""
import math, re, pathlib

CRT_MARGIN = 0.15      # courtyards already carry their own clearance
PAD_MARGIN = 1.1       # fallback only, when a footprint genuinely has no courtyard

def balanced(s, i):
    """End index of the s-expression starting at s[i] == '('. String aware."""
    d, j, q = 0, i, False
    while j < len(s):
        c = s[j]
        if q:
            if c == '\\': j += 2; continue
            if c == '"': q = False
        elif c == '"': q = True
        elif c == '(': d += 1
        elif c == ')':
            d -= 1
            if d == 0: return j + 1
        j += 1
    raise ValueError("unbalanced s-expression")

def _shapes(blk):
    for m in re.finditer(r'\(fp_(line|rect|poly|circle|arc)\b', blk):
        st = m.start()
        yield m.group(1), blk[st:balanced(blk, st)]

def load(path):
    """-> (source text, {ref: {x,y,rot,pads,start,end}})"""
    s = pathlib.Path(path).read_text()
    fps = {}
    for m in re.finditer(r'\(footprint "', s):
        st = m.start(); en = balanced(s, st); blk = s[st:en]
        at  = re.search(r'\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)', blk)
        ref = re.search(r'\(property "Reference" "([^"]+)"', blk)
        if not (at and ref): continue
        pads = []
        for pm in re.finditer(r'\(pad "([^"]*)"[^\n]*\n\s*\(at ([-\d.]+) ([-\d.]+)[^)]*\)\s*\n\s*\(size ([\d.]+) ([\d.]+)\)', blk):
            pads.append((pm.group(1), float(pm.group(2)), float(pm.group(3)),
                         float(pm.group(4)), float(pm.group(5))))
        fps[ref.group(1)] = dict(x=float(at.group(1)), y=float(at.group(2)),
                                 rot=float(at.group(3) or 0), pads=pads, start=st, end=en)
    return s, fps

def local_rect(src, fps, ref):
    """Courtyard rect RELATIVE TO THE FOOTPRINT ORIGIN.

    Three traps live in this function. See SKILL.md, Known failure modes.
      1. the origin is often pin 1, not the centre, so keep the offsets
      2. the layer token is F.CrtYd / B.CrtYd, never the word "Courtyard"
      3. a circle courtyard is (center)+(end-on-rim), not two corners
    """
    f = fps[ref]; blk = src[f['start']:f['end']]
    xs, ys = [], []
    for kind, sub in _shapes(blk):
        if 'CrtYd' not in sub: continue
        pts = [(float(a), float(b)) for a, b in
               re.findall(r'\((?:start|end|center|mid|xy) ([-\d.]+) ([-\d.]+)\)', sub)]
        if kind == 'circle' and len(pts) >= 2:
            (cx, cy), (ex, ey) = pts[0], pts[1]
            r = math.dist((cx, cy), (ex, ey))
            pts = [(cx - r, cy - r), (cx + r, cy + r)]
        xs += [p[0] for p in pts]; ys += [p[1] for p in pts]
    if xs:
        return (min(xs)-CRT_MARGIN, min(ys)-CRT_MARGIN, max(xs)+CRT_MARGIN, max(ys)+CRT_MARGIN)
    px = [q[1] for q in f['pads']] or [0.0]; py = [q[2] for q in f['pads']] or [0.0]
    return (min(px)-PAD_MARGIN, min(py)-PAD_MARGIN, max(px)+PAD_MARGIN, max(py)+PAD_MARGIN)

def abs_rect(lr, x, y, rot):
    x0, y0, x1, y1 = lr
    a = math.radians(-rot); ca, sa = math.cos(a), math.sin(a)
    rp = [(px*ca - py*sa, px*sa + py*ca) for px, py in ((x0,y0),(x1,y0),(x1,y1),(x0,y1))]
    return (x+min(p[0] for p in rp), y+min(p[1] for p in rp),
            x+max(p[0] for p in rp), y+max(p[1] for p in rp))

def overlaps(r1, r2, gap=0.0):
    return not (r1[2]+gap <= r2[0] or r2[2]+gap <= r1[0] or
                r1[3]+gap <= r2[1] or r2[3]+gap <= r1[1])

def pad_abs(fp, lx, ly):
    a = math.radians(-fp['rot'])
    return (fp['x'] + lx*math.cos(a) - ly*math.sin(a),
            fp['y'] + lx*math.sin(a) + ly*math.cos(a))

def nets(netlist_path, skip=("GND",)):
    """-> [(short_name, [(ref, pad), ...])] for nets worth routing."""
    s = pathlib.Path(netlist_path).read_text(); k = s.index("(nets")
    out = []
    for m in re.finditer(r'\(net\s*\n\s*\(code "\d+"\)\s*\n\s*\(name "([^"]+)"\)(.*?)\n\t\t\)', s[k:], re.S):
        name = m.group(1); short = name.split("/")[-1]
        if short in skip or name.startswith("unconnected-"): continue
        nodes = re.findall(r'\(ref "([^"]+)"\)\s*\n\s*\(pin "([^"]+)"\)', m.group(2))
        if len(nodes) > 1: out.append((short, nodes))
    return out


# ---------------------------------------------------------------- side / flip
FLIP_LAYER = {"F.Cu":"B.Cu","B.Cu":"F.Cu","F.SilkS":"B.SilkS","B.SilkS":"F.SilkS",
              "F.CrtYd":"B.CrtYd","B.CrtYd":"F.CrtYd","F.Fab":"B.Fab","B.Fab":"F.Fab",
              "F.Mask":"B.Mask","B.Mask":"F.Mask","F.Paste":"B.Paste","B.Paste":"F.Paste",
              "F.Adhes":"B.Adhes","B.Adhes":"F.Adhes"}

def side(src, fps, ref):
    """'F' or 'B' — which side the footprint body sits on."""
    blk = src[fps[ref]['start']:fps[ref]['end']]
    m = re.search(r'\(layer "([FB])\.Cu"\)', blk)
    return m.group(1) if m else 'F'

def flip_block(blk):
    """Mirror a footprint block to the other side: negate local Y, swap layers.

    Verified by reproducing a known back-side footprint from its library copy.
    Do not 'simplify' this without re-running that test.
    """
    def swap_layers(t):
        return re.sub(r'\(layer "([FB]\.[A-Za-z]+)"\)',
                      lambda m: f'(layer "{FLIP_LAYER.get(m.group(1), m.group(1))}")', t)
    def neg_y(t):
        # local coordinates of every geometry and text item
        t = re.sub(r'\((at|start|end|center|mid|xy) ([-\d.]+) ([-\d.]+)( [-\d.]+)?\)',
                   lambda m: f'({m.group(1)} {m.group(2)} {-float(m.group(3)):g}'
                             + (f'{m.group(4)})' if m.group(4) else ')'), t)
        return t
    def mirror_text(t):
        # back-side text needs the mirror justify flag
        def fix(m):
            body = m.group(0)
            if 'mirror' in body: return body
            if '(justify' in body:
                return re.sub(r'\(justify ([^)]*)\)', lambda j: f'(justify {j.group(1)} mirror)', body, count=1)
            return body[:-1] + '\n\t\t\t\t(justify mirror)\n\t\t\t)'
        return re.sub(r'\(effects\b(?:[^()]|\([^()]*(?:\([^()]*\)[^()]*)*\))*\)', fix, t)
    head_end = blk.index('\n')
    head, body = blk[:head_end], blk[head_end:]
    # the footprint's own (at x y r) is board level, restore it after mirroring
    own = re.search(r'\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)', body)
    keep = own.group(0)
    body = body[:own.start()] + "@@AT@@" + body[own.end():]
    body = mirror_text(swap_layers(neg_y(body))).replace("@@AT@@", keep)
    return head + body

def pad_rects(fps, ref, x, y, rot, clr=0.2):
    """Absolute rects of each pad, used for collision between opposite sides
    where courtyards do not conflict but the pads and holes still do.

    Must use the pad's real size. A fixed half-size lets 1.6mm pads sit 0.8mm
    apart and short together.
    """
    f = fps[ref]; a = math.radians(-rot); out = []
    for pad in f['pads']:
        lx, ly = pad[1], pad[2]
        w = pad[3] if len(pad) > 3 else 1.6
        h = pad[4] if len(pad) > 4 else 1.6
        px = x + lx*math.cos(a) - ly*math.sin(a)
        py = y + lx*math.sin(a) + ly*math.cos(a)
        hw, hh = (max(w, h)/2 + clr,)*2      # rotation agnostic, slightly conservative
        out.append((px-hw, py-hh, px+hw, py+hh))
    return out

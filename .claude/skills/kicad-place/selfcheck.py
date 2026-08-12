#!/usr/bin/env python3
"""Reconcile the geometry model against KiCad's own DRC. Run this FIRST.

If the model and DRC disagree about overlaps, every placement result is
worthless. This is the step that would have caught three of the four bugs
recorded in SKILL.md.
"""
import subprocess, sys, re, tempfile, os
import kicadpcb as K

def model_overlaps(pcb):
    """Side aware, matching KiCad: courtyards only conflict on the same side.
    Across sides only the pads and holes conflict."""
    src, fps = K.load(pcb)
    onb = [r for r in fps if not re.match(r'^(MH|FID)\d+$', r)]
    rect = {r: K.abs_rect(K.local_rect(src, fps, r), fps[r]['x'], fps[r]['y'], fps[r]['rot'])
            for r in onb}
    side = {r: K.side(src, fps, r) for r in onb}
    pads = {r: K.pad_rects(fps, r, fps[r]['x'], fps[r]['y'], fps[r]['rot']) for r in onb}
    bad = set()
    for i, a in enumerate(onb):
        for b in onb[i+1:]:
            if not K.overlaps(rect[a], rect[b]): continue
            if side[a] == side[b]:
                bad.add(tuple(sorted((a, b))))
            elif any(K.overlaps(pa, pb) for pa in pads[a] for pb in pads[b]):
                bad.add(tuple(sorted((a, b))))
    return bad

def drc_overlaps(pcb):
    rpt = tempfile.mktemp(suffix=".rpt")
    subprocess.run(["kicad-cli", "pcb", "drc", "-o", rpt, pcb],
                   capture_output=True, text=True)
    txt = open(rpt).read(); os.unlink(rpt)
    pairs, cur, inblock = set(), [], False
    for line in txt.splitlines():
        if line.startswith("["):
            inblock = line.startswith("[courtyards_overlap]"); cur = []
            continue
        if not inblock: continue
        m = re.match(r'\s*@\([-\d. ]+mm, [-\d. ]+mm\): Footprint (\S+)', line)
        if m:
            cur.append(m.group(1))
            if len(cur) == 2: pairs.add(tuple(sorted(cur))); cur = []
    return pairs

if __name__ == "__main__":
    pcb = sys.argv[1]
    mine, theirs = model_overlaps(pcb), drc_overlaps(pcb)
    print(f"model says {len(mine):3d} overlapping pairs")
    print(f"DRC   says {len(theirs):3d} overlapping pairs")
    only_drc, only_model = theirs - mine, mine - theirs
    if only_drc:   print(f"  MODEL TOO SMALL, DRC found and model missed: {sorted(only_drc)[:8]}")
    if only_model: print(f"  model too big, model found and DRC did not : {sorted(only_model)[:8]}")
    ok = not only_drc
    print("PASS - safe to optimise" if ok else "FAIL - fix the geometry before optimising")
    sys.exit(0 if ok else 1)

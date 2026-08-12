---
name: kicad-place
description: Place components on a KiCad board to minimise ratsnest crossings before hand routing. Use when asked to arrange, place, or lay out parts on a .kicad_pcb, or to reduce ratsnest crossovers. Carries the geometry parser, the crossing metric and the optimiser.
---

# Placing components to minimise ratsnest crossings

Force-directed spread, then a deterministic legaliser, then annealing whose
objective is `ratsnest length + W x crossings`.

Everything here is measured. Crossings are counted by building the per-net
minimum spanning tree, which is what KiCad draws, and counting properly
intersecting segments from different nets.

## Run it in this order

**1. Reconcile the geometry model against DRC. Never skip this.**

```bash
python3 selfcheck.py board.kicad_pcb
```

It prints the overlapping pairs your model sees and the pairs KiCad's DRC sees.

- **model smaller than DRC** is a FAIL. Your boxes are undersized, and any
  placement you produce will short parts together. Fix the geometry first.
- **model larger than DRC** is fine. You place more conservatively than
  required.

This single step would have caught three of the four geometry bugs below.

**2. Export a netlist from the schematic.**

```bash
kicad-cli sch export netlist --format kicadsexpr -o /tmp/n.net board.kicad_sch
```

**3. Measure the starting point.**

```bash
python3 place.py measure board.kicad_pcb /tmp/n.net --fixed J1,J2,J3
```

**4. Optimise.** Runs for `--budget` seconds; use `run_in_background`.

```bash
python3 place.py optimise board.kicad_pcb /tmp/n.net \
    --fixed J1,J2,J3,C1,C2 --region 21.5,21.5,67.5,128.5 \
    --blocks blocks.json --budget 200 --out placement.json
```

`--blocks` is optional, `{"block name": ["U1","R1",...]}`. It adds a pull
toward each group's own centroid, so parts from one sub-circuit cluster
together. Placement comes out much tidier with it.

**5. Apply, then verify three ways.**

```bash
python3 place.py apply board.kicad_pcb placement.json
python3 selfcheck.py board.kicad_pcb            # model and DRC agree
python3 place.py measure board.kicad_pcb /tmp/n.net --fixed ...
kicad-cli pcb drc --refill-zones --save-board -o drc.rpt board.kicad_pcb
```

The placement is only good if DRC reports **zero** of `clearance`,
`courtyards_overlap`, `shorting_items`, `hole_to_hole`, `pth_inside_courtyard`.
`unconnected_items` is expected: nothing is routed yet.

## Known failure modes

Every one of these produced a wrong answer that looked plausible.

**The footprint origin is not the courtyard centre.** It is often pin 1. A box
centred on the origin puts a 37mm connector half a connector away from where it
really is. Keep the rect as offsets from the origin and rotate the rect, not a
width and height.

**The courtyard layer is `F.CrtYd`, never the word `Courtyard`.** Matching the
long name silently finds nothing, every part falls back to its pad extent, and
everything is placed too tight. The long names exist only in the layer table at
the top of the file.

**A circle courtyard is a centre and a point on the rim.** Reading those two as
opposite corners of a rectangle turned a 5.8 x 5.8mm capacitor into a
0.3mm sliver. Compute the radius and expand.

**A swap move must check both parts against each other.** Excluding the partner
from each check leaves exactly the one pair that can newly collide untested.

**Never trust the search to emit a legal state.** `place.py` runs a repair pass
after annealing that relocates anything still illegal to its nearest free slot.
The guarantee belongs at the output, not only in the acceptance test.

**Silence is not agreement.** A model reporting zero overlaps while DRC reports
39 is a broken model, not a clean board. Reconcile the two numbers.

## Open issue

Rotating a footprint makes KiCad report `lib_footprint_mismatch` for that part.
Confirmed by isolating it: applying translations only gives zero mismatches,
translations plus rotations gives one per rotated part. `write_back` already
rotates the text items with the footprint, which is necessary but not
sufficient, so something else in the footprint body still differs.

It is a warning, not a fault. No copper, drill or courtyard geometry is
affected, and **Update Footprints from Library** in pcbnew clears it while
preserving position and rotation.

If you find the real cause, fix it here and delete this section.

## Tuning

| Option | Meaning |
|---|---|
| `--w-cross` | mm of ratsnest you will spend to remove one crossing. Default 30 |
| `--budget` | anneal seconds. 200 is usually enough for ~50 parts |
| `--region` | `x0,y0,x1,y1` keep-in. Set it inside the board edge |
| `--fixed` | comma separated refs that must not move |

Mechanical parts matching `MH\d+` or `FID\d+` are treated as fixed
automatically and excluded from the board's part list.

## Improving this skill

This is a tool, not a document. When it produces a wrong result:

1. Reproduce it as the smallest check that fails, ideally in `selfcheck.py`.
2. Fix the code.
3. Add the failure to **Known failure modes** in the words that would have
   stopped you making it.

The list above is the point of the skill. The algorithm is ordinary.

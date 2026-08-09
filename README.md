# Eurorack

Meta-repo tying together the Eurorack DIY projects. Each project stays an
independent repo — this one records which combination of them works together.

## Why a meta-repo rather than a monorepo

The projects have to stay separately addressable:

- `eurorack-docs` builds its site by pulling each module repo **by URL**
- CI is per-repo, and modules release on their own cadence
- `eurorack-common-library` is consumed as a **submodule** inside module repos

Merging them would break all three. Submodules give the one thing a loose
collection of repos cannot: **a parent commit pins one known-good combination**,
so a state that was verified end-to-end can be returned to exactly.

## Contents

| repo | what it is |
|---|---|
| [cem3340-vco](https://github.com/carr-james/cem3340-vco) | CEM3340 VCO module |
| [quad-vca-mixer](https://github.com/carr-james/quad-vca-mixer) | Quad VCA mixer module |
| [eurorack-common-library](https://github.com/carr-james/eurorack-common-library) | **parts** — symbols, footprints, 3D models, SPICE |
| [eurorack-blocks](https://github.com/carr-james/eurorack-blocks) | **circuits** — KiCad 10 design blocks + house design rules |
| [eurorack-breakouts](https://github.com/carr-james/eurorack-breakouts) | breadboard-friendly breakout PCBs, milled in-house |
| [eurorack-docs](https://github.com/carr-james/eurorack-docs) | Antora playbook for the unified docs site |
| [eurorack-docs-ui](https://github.com/carr-james/eurorack-docs-ui) | docs site theme + `eurorack-build` |
| [eurorack-docker](https://github.com/carr-james/eurorack-docker) | KiCad 10 + KiBot + Antora build image |
| [eurorack-workflows](https://github.com/carr-james/eurorack-workflows) | reusable GitHub Actions workflows |

The split between **parts**, **circuits** and **boards** is deliberate: they
change at different rates and have different consumers.

## Cloning

```bash
git clone --recurse-submodules git@github.com:carr-james/eurorack.git
```

Already cloned without submodules:

```bash
git submodule update --init --recursive
```

## Working across the repos

Submodules check out detached HEADs by default, which is rarely what you want
for editing:

```bash
# put every submodule on its tracking branch
git submodule foreach 'git checkout $(git rev-parse --abbrev-ref origin/HEAD | sed s@origin/@@) || true'

# status / pull across all of them
git submodule foreach 'git status -s'
git submodule foreach 'git pull --ff-only'
```

Note the two hardware repos develop on **`dev`**, not `main`. CI builds
`[dev, 'v*']`, and `main` can lag.

After committing in a submodule, record the new pin here:

```bash
git add <repo> && git commit -m "Bump <repo>"
```

## Toolchain

- **KiCad 10** — required. Design blocks with layout are a v10 feature, and the
  board files are v10 format, which KiCad 9 cannot read.
- **Docker** — for docs builds. The image is `linux/amd64` only; on Apple
  Silicon set `DOCKER_DEFAULT_PLATFORM=linux/amd64`.
- **Konnect** — KiCad 10 MCP plugin, wired up in `.mcp.json`. Needs KiCad running
  with a board open for the PCB tools, and the IPC API enabled
  (Preferences → Plugins → Enable KiCad API).

### macOS gotcha

`/opt/homebrew/bin/kicad-cli` is a symlink, and KiCad resolves its stock library
paths relative to the executable — so through the symlink it looks in
`/opt/homebrew/bin/SharedSupport/` and finds nothing. Either call the real binary
at `/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli`, or export
`KICAD10_SYMBOL_DIR` / `KICAD10_FOOTPRINT_DIR` / `KICAD10_3DMODEL_DIR` /
`KICAD10_TEMPLATE_DIR` pointing into the app bundle.

## Fabrication targets

Two, with different rules:

| | in-house mill (Carvera Air) | JLCPCB |
|---|---|---|
| track / clearance | 0.2mm | ~0.127mm |
| via | 0.9mm, **unplated** — rivet or wire by hand | 0.3mm, plated |
| soldermask / silkscreen | manual UV mask, laser-cured silk | included |

Shared blocks are designed **mill-safe**, which is the stricter of the two, so
they remain fabbable either way. See
`eurorack-common-library/design-rules/house-mill.kicad_dru`.

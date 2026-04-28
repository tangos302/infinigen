# Procedural Low-Poly Mesh Generators · Survey & Ranking

Survey of external procedural generators we could integrate into Maquette,
across asset categories that scene prompts typically request. Curated
2026-04-28. Source: web research + cross-checks against repo READMEs.

The criteria for ranking each entry:

- **scene-prompt utility** — how often does this asset class appear in
  hypothetical "user prompts a scene" requests
- **integration realism** — how cleanly does it script from
  Blender-Python without a UI in the loop
- **low-poly fit** — naturally low-poly, or requires post-processing
- **decision-tree procedural vs. template-and-randomize** — Maquette
  prefers parametric/code-driven generators; asset-pack-shuffling is
  fine but a different pattern

## Top 8 — most worth integrating

| # | Tool | What it gives us | Story |
|---|---|---|---|
| 1 | [Building Tools (ranjian0)](https://github.com/ranjian0/building_tools) | Houses / walls / doors / windows / roofs / stairs | Pure Python + bmesh, MIT-flavor, parametric. Biggest scene-prompt unlock; most prompts mention structures. |
| 2 | [Infinigen Indoors](https://github.com/princeton-vl/infinigen) | Chairs / tables / shelves / lamps / beds + room layout | We already fork Infinigen; same decision-tree story; BSD. |
| 3 | [Modular Tree — GoodPie fork](https://github.com/GoodPie/modular_tree) | Bushes / shrubs + better leaves than Sapling | GPL, scriptable. Augment our native Sapling-style trees. |
| 4 | A.N.T. Landscape (Blender bundled) | Cliffs / mountains / terrain noise | Zero deps, naturally low-poly at low subdivisions. |
| 5 | [Buildify](https://paveloliva.gumroad.com/l/buildify) | Kit-bash villages / cities | Free GN. Complement to Building Tools when parametric is too rigid. |
| 6 | [MPFB2](https://extensions.blender.org/add-ons/mpfb/) (MakeHuman in Blender) | Stylized humanoids | Slider-driven morphs, decimate for low-poly. The only credible open-source character generator. |
| 7 | [BagaPie](https://extensions.blender.org/add-ons/bagapie/) | Fences / ivy / parametric arrays / scatter | Free Swiss-army for prop gaps. |
| 8 | [Procedural Sword Generator](https://b3d.interplanety.org/en/blender-add-on-swords-constructor/) | Weapons | GN-based, cheap procedural variety. |

## Skip or defer

- **Vehicles** — no decent open-source procedural option. Hand-author
  or buy a paid Blender Market generator. Common in scene prompts
  but a structural gap in the FOSS landscape.
- **Animals / creatures** — Infinigen has a creature module but it's
  heavy and photoreal; nothing FOSS in the stylized space. For
  scenes that need wildlife, fall back to asset-pack swap.

## Maquette integration order (proposed)

1. **`LowPolyHouseFactory`** wrapping `building_tools` — biggest
   utility per unit work. POC branch: `maquette-buildings`.
2. **`LowPolyChairFactory` / `LowPolyTableFactory`** from Infinigen
   Indoors — minimal new install since Infinigen is already a
   dependency.
3. **Bushes via Modular Tree** — replaces or supplements our
   `NativeLowPolyTreeFactory("bush")` archetype with a more flexible
   leaf system.

## How to read the table

The first 4 rows preserve Maquette's "decision-tree procedural"
character — parametric, code-driven, naturally low-poly. Rows 5+
start drifting toward "template-and-randomize" (kit-bash) style;
that's a fine pattern for prop variety but should be documented as
such, not conflated with the parametric core.

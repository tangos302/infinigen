"""Auto-generate FACTORIES_GUIDE.md from the factory module ASTs.

Walks `infinigen/maquette/factories/{*.py, native/*.py}`, extracts:
  - module docstring (sales pitch — what the factory is for)
  - `_<X>_ARCHETYPES` tuple (the list of archetype names)
  - `_ARCHETYPE_DEFAULTS` dict (default knob values per archetype —
    not exhaustively dumped, just shape-summarized for tokens)
  - class docstring's "Constructor knobs" section (parameter list)

Output is a markdown doc that goes to Claude as the catalog. Claude
then writes a build script that calls the factories.

Why AST instead of import: importing the modules pulls in `bpy` which
needs Blender. The pipeline runs from a regular Python env (not inside
Blender), so we keep the guide-gen Blender-free.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path


FORK_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # infinigen-fork/
MAQUETTE_DIR = FORK_ROOT / "infinigen" / "maquette"
FACTORIES_DIR = MAQUETTE_DIR / "factories"
FACTORIES_REALISTIC_DIR = MAQUETTE_DIR / "factories_realistic"

VALID_MODES = ("low_poly", "realistic")


# High-level category for each factory module — used by the /debug/factories
# page to group the catalog into something a designer can scan. Keys are
# module stems (file names without .py); modules not listed default to
# "objects" so a new factory shows up without needing edits here.
FACTORY_CATEGORIES: dict[str, str] = {
    # terrain — vegetation, rock features, things rooted in the ground
    "tree": "terrain",
    "palm_tree": "terrain",
    "cactus": "terrain",
    "rock_spire": "terrain",
    "boulder": "terrain",
    "tumbleweed": "terrain",
    # water — anything water-bound
    "water_surface": "water",
    "boat": "water",
    # objects — small props, scatter, ground furniture
    "barrel": "objects",
    "crate": "objects",
    "fence": "objects",
    "haystack": "objects",
    "lantern_post": "objects",
    "banner": "objects",
    "stall": "objects",
    "wagon": "objects",
    "deck": "objects",
    # landmark — large structures, focal points, civilisation
    "building": "landmark",
    "suspension_bridge": "landmark",
    "cable_car": "landmark",
    "torii": "landmark",
    "well": "landmark",
    "windmill": "landmark",
    "tombstone": "landmark",
}

CATEGORY_ORDER: list[str] = ["terrain", "water", "landmark", "objects"]


def category_for(module_stem: str) -> str:
    """Return the high-level category for a factory module. Falls back to
    'objects' for unmapped modules so new factories show up automatically."""
    return FACTORY_CATEGORIES.get(module_stem, "objects")


def _module_docstring(tree: ast.Module) -> str | None:
    """First-statement string literal at the module level."""
    return ast.get_docstring(tree)


def _find_archetype_tuples(tree: ast.Module) -> list[tuple[str, list[str]]]:
    """Find all module-level `_<NAME>_ARCHETYPES = (...)` assignments.
    Returns [(name, values), ...] in source order. Some factories have
    multiple archetype tuples (e.g. building.py has `_BUILDING_ARCHETYPES`
    and `_ROOF_ARCHETYPES`)."""
    out = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            if isinstance(tgt, ast.Name) and tgt.id.endswith("_ARCHETYPES"):
                if isinstance(node.value, (ast.Tuple, ast.List)):
                    values = []
                    for elt in node.value.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            values.append(elt.value)
                    out.append((tgt.id, values))
    return out


def _find_class_init(tree: ast.Module, class_name: str) -> ast.FunctionDef | None:
    """Find the __init__ method of the given class."""
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef) and sub.name == "__init__":
                    return sub
    return None


def _format_init_params(init_fn: ast.FunctionDef) -> list[str]:
    """Authoritative parameter list, formatted as a markdown bullet list.
    Skips `self` and `coarse` (always present, never useful to scene
    builders)."""
    args = init_fn.args
    all_args = list(args.args)  # positional + keyword-only collapse
    # Defaults align with the *trailing* args; len(defaults) <= len(args)
    defaults = list(args.defaults)
    n_args = len(all_args)
    n_def = len(defaults)
    # Pad defaults so each arg has a default (None if none).
    padded = [None] * (n_args - n_def) + defaults
    out = []
    for arg, default in zip(all_args, padded):
        if arg.arg in ("self", "coarse"):
            continue
        annotation = ""
        if arg.annotation is not None:
            try:
                annotation = ": " + ast.unparse(arg.annotation)
            except Exception:
                annotation = ""
        default_str = ""
        if default is not None:
            try:
                default_str = " = " + ast.unparse(default)
            except Exception:
                default_str = ""
        out.append(f"{arg.arg}{annotation}{default_str}")
    return out


def _find_archetype_defaults_keys(tree: ast.Module) -> list[str]:
    """Return the keys of the `_ARCHETYPE_DEFAULTS` dict's first archetype
    entry — that is, the list of knobs each archetype defaults dict
    declares. Used to surface the per-archetype knob set without dumping
    the full dict to the guide."""
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            if isinstance(tgt, ast.Name) and tgt.id == "_ARCHETYPE_DEFAULTS":
                if isinstance(node.value, ast.Dict):
                    if not node.value.values:
                        return []
                    first_val = node.value.values[0]
                    if isinstance(first_val, ast.Call):
                        return [k.arg for k in first_val.keywords if k.arg]
                    if isinstance(first_val, ast.Dict):
                        return [
                            k.value for k in first_val.keys
                            if isinstance(k, ast.Constant) and isinstance(k.value, str)
                        ]
    return []


def _find_factory_class(tree: ast.Module) -> tuple[str, str] | None:
    """Return (class_name, docstring) for the first class that looks like
    an asset factory.

    Match rule: any class whose name ends in ``Factory`` AND whose first
    base is also a ``*Factory`` (or directly ``AssetFactory``). This picks
    up:
      - direct AssetFactory subclasses (low-poly natives)
      - wrappers around upstream factories (e.g. LowPolyBoulderFactory →
        BoulderFactory, RealisticTreeFactory → TreeFactory)
    while skipping helper classes / dataclasses inside the same module.
    """
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        if not node.name.endswith("Factory"):
            continue
        for base in node.bases:
            base_name = (
                base.attr if isinstance(base, ast.Attribute)
                else base.id if isinstance(base, ast.Name)
                else None
            )
            if base_name and base_name.endswith("Factory"):
                return node.name, ast.get_docstring(node) or ""
    return None


def _factory_files(mode: str = "low_poly") -> list[Path]:
    """Factory files for the given mode.

    low_poly: factories/*.py + factories/native/*.py
    realistic: factories_realistic/*.py
    """
    if mode not in VALID_MODES:
        raise ValueError(f"mode={mode!r} not in {VALID_MODES}")
    out = []
    if mode == "low_poly":
        for p in sorted(FACTORIES_DIR.glob("*.py")):
            if p.stem != "__init__":
                out.append(p)
        for p in sorted((FACTORIES_DIR / "native").glob("*.py")):
            if p.stem != "__init__":
                out.append(p)
    else:  # realistic
        for p in sorted(FACTORIES_REALISTIC_DIR.glob("*.py")):
            if p.stem != "__init__":
                out.append(p)
    return out


def _entry_for(path: Path) -> str | None:
    """Build the markdown entry for a single factory file."""
    src = path.read_text()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    cls = _find_factory_class(tree)
    if cls is None:
        return None
    class_name, _class_doc = cls
    mod_doc = _module_docstring(tree) or ""
    # First non-empty line of module doc as one-line pitch
    mod_pitch = next((ln for ln in mod_doc.splitlines() if ln.strip()), "")
    archetype_tuples = _find_archetype_tuples(tree)
    init_fn = _find_class_init(tree, class_name)

    parts = [f"### `{class_name}`", ""]
    if mod_pitch:
        parts.append(mod_pitch.strip())
        parts.append("")
    for name, values in archetype_tuples:
        # Strip the leading `_` and trailing `_ARCHETYPES` for readability:
        # `_BUILDING_ARCHETYPES` → `building`
        label = name.strip("_").removesuffix("_ARCHETYPES").lower() or "archetype"
        parts.append(f"**{label}** archetypes: `{'` / `'.join(values)}`")
    if archetype_tuples:
        parts.append("")
    if init_fn is not None:
        params = _format_init_params(init_fn)
        if params:
            parts.append("**Constructor parameters:**")
            parts.append("```")
            for p in params:
                parts.append(p)
            parts.append("```")
    parts.append("")
    return "\n".join(parts)


_HEADER = """\
# Maquette Factory Catalog (auto-generated)

This is the procedural-asset catalog for low-poly stylized scene
generation. Each factory below produces ONE class of asset (tree,
boulder, building, etc.) with multiple archetypes selectable via a
`*_archetype` constructor parameter.

## Conventions for build scripts

Every build script you generate MUST follow this skeleton:

```python
import sys, math, random
from pathlib import Path
INFINIGEN_FORK = Path("/home/tang/songe/_artifacts/maquette/infinigen-fork")
if str(INFINIGEN_FORK) not in sys.path:
    sys.path.insert(0, str(INFINIGEN_FORK))

import bpy
from mathutils import Vector

from infinigen.maquette.factories.native.<module> import LowPoly<X>Factory
# ... repeat for each factory you need
from infinigen.maquette.factories.boulder import LowPolyBoulderFactory  # wrapper
from infinigen.maquette.runtime.terrain import make_terrain
# OR — when the prompt mixes biomes (grass + desert, forest + coast, etc.):
# from infinigen.maquette.runtime.terrain import make_multi_biome_terrain
# OR — for SERIOUS terrain (dramatic peaks + river systems + image refs):
# from infinigen.maquette.runtime.eroded_terrain import make_eroded_terrain

rng = random.Random(<seed>)

# 1. Wipe scene + create displaced ground. NEVER build it as a bare plane.
# Pick the helper that fits the prompt:
#   make_terrain(style=...)             — flat/rolling/hilly/alpine/dunes,
#                                         single biome, fast.
#   make_multi_biome_terrain(zones=...) — mixed biomes side-by-side,
#                                         simple zone blender (faceted edges).
#   make_eroded_terrain(peaks=, troughs=) — game-ready quality.
#                                         Hydraulic erosion (landlab) +
#                                         continuous biome colors.
#                                         REQUIRED when the prompt names
#                                         dramatic terrain (mountain ranges,
#                                         river valleys, "vast plains with
#                                         a peak in the distance"), or any
#                                         time an image reference is provided
#                                         showing complex relief.
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
terrain = make_terrain(
    style="<flat|rolling|hilly|alpine|dunes>",
    size=80,                                # half-width in BU; world 160 BU wide
    base_color=(<R>, <G>, <B>, 1.0),
    seed=<scene seed>,
)
# Multi-biome alternative (replace the single-biome call above when needed):
#   terrain = make_multi_biome_terrain(
#       size=80,
#       seed=<seed>,
#       zones=[
#           ("rolling", -30,   0, 25),   # grass headland on the west
#           ("dunes",    20,  -8, 22),   # sandy fringe on the southeast
#           ("flat",      0,  38, 30),   # ocean side (add water plane on top)
#       ],
#   )
# Eroded (game-ready) alternative — peaks + troughs spec:
#   terrain = make_eroded_terrain(
#       size=140,                         # bigger world; relief reads at 280 BU wide
#       seed=<seed>,
#       peaks=[
#           # (cx, cy, sigma, height) — Gaussians for mountain masses.
#           # Heights ≥12 BU get ridged-noise alpine character + snow caps.
#           (115, 50, 25, 18.0),          # hero alpine NE
#           (-110, 70, 18, 4.5),          # secondary western range
#           (-95, -110, 22, 5.0),         # foreground vantage hill (camera vp)
#       ],
#       troughs=[
#           # (cx, cy, sigma, depth NEGATIVE) — chain these to thread a
#           # winding river/lake basin. Erosion will carve drainage from peaks
#           # toward the troughs naturally.
#           (-40, -10, 14, -3.6),
#           ( 5,   5, 12, -3.4),
#           ( 30, 20, 14, -3.2),
#       ],
#       plain_offset=2.4,                  # lift plains so meadow dominates
#       sea_level=0.5,                     # below = lakebed/shore
#       erode_iters=35,                    # 25 soft, 35 default, 60 aggressive
#       # water=True is the default — auto-detects connected basins
#       # below sea_level and drops one translucent blue cube per body.
#       # Pass water=False to suppress (terrain-only renders).
#   )
# After this call: `terrain.height_at(x, y)` returns the eroded surface
# height at any world XY — use it the same way as make_terrain.
# DO NOT add LowPolyWaterSurfaceFactory on top of make_eroded_terrain —
# the helper already places water volumes per basin from the heightmap.

# 1b. Scatter foliage / boulders / grass on the terrain via Geometry Nodes.
#     This is BIOME-AWARE — pass a single template, the helper instances
#     it across all faces matching the biome filter.
# from infinigen.maquette.runtime.scatter import scatter_on_terrain
#
# tree_tmpl = NativeLowPolyTreeFactory(factory_seed=1, foliage_archetype="round_ball",
#                                      trunk_archetype="straight").create_asset(placeholder=None)
# tree_tmpl.scale = (0.4, 0.4, 0.4)        # WORLD_SCALE × 0.25 for size=140
# scatter_on_terrain(
#     terrain_obj=terrain.obj,
#     instance_obj=tree_tmpl,
#     density=0.006,                          # ~600 trees over a 280 BU world's grass band
#     biome_filter="grass",                   # see _BIOME_TESTS in scatter.py
#     seed=42,
# )
# # Boulders on the alpine bands — sparser, slightly larger jitter.
# boulder_tmpl = LowPolyBoulderFactory(factory_seed=2, palette_color="rock_warm").spawn_asset(
#     i=2, loc=(0, 0, 0))
# boulder_tmpl.scale = (0.5, 0.5, 0.5)
# scatter_on_terrain(
#     terrain_obj=terrain.obj, instance_obj=boulder_tmpl,
#     density=0.015, biome_filter="alpine", seed=43,
# )
#
# Biome filters: "grass" (forest+meadow), "meadow", "forest", "stone",
# "alpine", "snow", "shore", "any". Filters key off the per-vertex `Col`
# attribute that make_eroded_terrain writes — they don't work on plain
# make_terrain output.
#
# Density is points per BU² of eligible surface (the band selected by
# biome_filter). Realistic ranges:
#   trees on grass     : 0.003 - 0.010
#   boulders on alpine : 0.010 - 0.025
#   dense forest patch : 0.020 - 0.040
# Density × area > 5000 produces enough geometry to slow Cycles AND
# blow up the OBJ file size — keep it bounded.

# 2. Spawn assets via factories.
#    Pattern: f = FactoryClass(factory_seed=N, archetype="...")
#             obj = f.create_asset(placeholder=None)
#             obj.location = (x, y, terrain.height_at(x, y))   # ride the surface
#             obj.rotation_euler.z = rot_z
#
#    LowPolyBoulderFactory needs spawn_asset (Infinigen wrapper):
#             obj = f.spawn_asset(i=N, loc=(x, y, terrain.height_at(x, y)))
#
#    For water surfaces, sit them slightly below local terrain height
#    so they read as a valley channel:
#             lake_z = terrain.height_at(cx, cy) - 0.3

# 3. Camera + sun + world background
bpy.ops.object.camera_add(location=(<X>, <Y>, <Z>))
cam = bpy.context.active_object
target = Vector((<tx>, <ty>, <tz>))
cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
cam.data.lens = 35
bpy.context.scene.camera = cam

bpy.ops.object.light_add(type="SUN", location=(<X>, <Y>, <Z>))
sun = bpy.context.active_object
sun.data.energy = <energy>            # 2.0 daytime, 2.5 golden, 1.4 twilight, 3.5 harsh
sun.data.color = (<R>, <G>, <B>)      # warm: 1,0.86,0.65; neutral: 1,0.96,0.88; cool: 0.65,0.62,0.78
sun.rotation_euler = (math.radians(<pitch>), math.radians(<roll>), math.radians(<yaw>))

w = bpy.context.scene.world
w.use_nodes = True
w.node_tree.nodes.clear()
out = w.node_tree.nodes.new("ShaderNodeOutputWorld")
bg = w.node_tree.nodes.new("ShaderNodeBackground")
bg.inputs[0].default_value = (<R>, <G>, <B>, 1.0)
bg.inputs[1].default_value = 1.0
w.node_tree.links.new(bg.outputs[0], out.inputs[0])

# 4. Render + save (the pipeline expects these exact paths)
import os
OUT_DIR = Path(os.environ["MAQUETTE_OUT_DIR"])
sc = bpy.context.scene
sc.render.engine = "CYCLES"
sc.cycles.samples = 48
sc.render.resolution_x = 1920
sc.render.resolution_y = 1080
sc.render.resolution_percentage = 100
sc.view_settings.view_transform = "Standard"
sc.render.filepath = str(OUT_DIR / "scene.png")
sc.render.image_settings.file_format = "PNG"
bpy.ops.render.render(write_still=True)
bpy.ops.wm.save_as_mainfile(filepath=str(OUT_DIR / "scene.blend"))
print(f"DONE: {OUT_DIR}/scene.png")
```

### Layout patterns

Use these archetypal patterns rather than reinventing — they read well
at low poly:

  - **Forest ring**: scatter ~15-25 trees in a circle of radius 15-22m
    around the central scene; randomize archetype + scale 0.85-1.2.
  - **Building cluster**: 3-5 houses arranged around a central focal
    point (well, square, plaza), each rotated to face inward.
  - **Path props**: lanterns or torii at regular intervals along the
    travel direction.
  - **Riprap**: scatter 5-10 boulders along the water/wall edge for
    natural transition.
  - **Yard scatter**: barrels + crates in clusters of 3-5 next to
    building doors.

### Material slots

Every factory uses `apply_palette_slots` so caller can override colours
per slot. Most factories have 2-3 slots (body, accent, trim). To pick a
non-default colour, pass `<slot>_color="palette_key"` to the factory.

Available palette keys:
`rock_warm`, `rock_cool`, `rock_pale`, `rock_shadow`, `wood`,
`rust_metal`, `stucco`, `foliage_pine`, `foliage_bush`, `foliage_apple`,
`foliage_mint`, `foliage_amber`, `foliage_rose`, `foliage_amethyst`,
`foliage_lemon`, `foliage_coral`, `ground_sand`, `ground_grass`,
`water`, `sky_warm`, `sky_cool`, `accent_red`.

### Lighting recipes (golden-hour palette baked in)

  - **Daytime / overcast**: sun energy 2.0, color `(1.0, 0.96, 0.88)`,
    rotation `(45°, 15°, 70°)`, sky `(0.78, 0.82, 0.88, 1.0)`
  - **Golden hour / sunset**: energy 2.5, color `(1.0, 0.86, 0.65)`,
    rotation `(60°, 20°, 60°)`, sky `(0.86, 0.78, 0.62, 1.0)`
  - **Dawn**: energy 2.5, color `(1.0, 0.78, 0.55)`,
    rotation `(75°, 15°, 45°)`, sky `(0.78, 0.65, 0.62, 1.0)`
  - **Twilight**: energy 1.4, color `(0.65, 0.62, 0.78)`,
    rotation `(80°, 15°, 120°)`, sky `(0.40, 0.42, 0.55, 1.0)`
  - **Wasteland midday**: energy 3.5, color `(1.0, 0.92, 0.78)`,
    rotation `(80°, 0°, 15°)`, sky `(0.92, 0.78, 0.62, 1.0)`

### Missing factories

If a prompt needs an asset class that's not in the catalog below,
include a comment in the script of the form:

```python
# REQUESTED_ASSET: <FactoryName> — <what it should be>
```

Use the closest existing factory as a stand-in (e.g. crystal-foliage
trees for dead trees, stone_wall fence for tombstones if Tombstone is
missing) and CONTINUE building the scene. Do not refuse to build.

### Camera framing

Use `cam.data.lens = 35` for wide scene shots and `lens = 50` for tight
prop shots. For an oblique-aerial scene view of a size=80 (160 BU wide)
world, the camera at `(40, -44, 26)` looking at `(0, 0, 3)` frames the
full scene cleanly. Scale linearly with terrain size if you change it.

---

## Factories

"""


_HEADER_REALISTIC = """\
# Maquette Factory Catalog — REALISTIC mode (auto-generated)

This is the procedural-asset catalog for **realistic** scene generation.
The factories below delegate to upstream Infinigen — full procedural
genomes, real shaders, no flat-shading, no decimate. Polycount is
naturally high; the post-bake stage (`runtime.lod_bake`) handles LOD +
Draco compression for browser playback.

Realistic mode shares the *structural* rules of low-poly mode (terrain
helpers, scatter, camera/sun/world block) but uses a different factory
import path and a different palette philosophy.

## Conventions for build scripts

Every build script you generate MUST follow this skeleton:

```python
import sys, math, random
from pathlib import Path
INFINIGEN_FORK = Path("/home/tang/songe/_artifacts/maquette/infinigen-fork")
if str(INFINIGEN_FORK) not in sys.path:
    sys.path.insert(0, str(INFINIGEN_FORK))

import bpy
from mathutils import Vector

# Realistic factories live in `infinigen.maquette.factories_realistic`.
# Each one is a thin wrapper over an upstream `infinigen.assets.objects.*`
# factory and accepts (factory_seed, archetype="...").
from infinigen.maquette.factories_realistic import (
    # vegetation
    RealisticTreeFactory,
    RealisticBushFactory,
    RealisticFernFactory,
    RealisticFlowerFactory,
    RealisticFlowerPlantFactory,
    RealisticDandelionFactory,
    RealisticGrassTuftFactory,
    RealisticMushroomFactory,
    # arid / desert
    RealisticCactusFactory,
    RealisticSnakePlantFactory,
    RealisticSpiderPlantFactory,
    RealisticSucculentFactory,
    # rocks
    RealisticBoulderFactory,
    RealisticBoulderPileFactory,
    RealisticBlenderRockFactory,
    RealisticGlowingRocksFactory,
    # underwater (only relevant for ocean / reef scenes)
    RealisticSeaweedFactory,
    RealisticKelpMonocotFactory,
    RealisticCoralFactory,
    RealisticUrchinFactory,
    # masonry / fortifications / structural (wraps Add Mesh Extra Objects)
    RealisticWallFactory,        # 5 archetypes: boundary/fortress/ruin/tower_round/garden_low
    RealisticBeamFactory,        # 6 profiles: box/u/c/l/i/t  — structural beams
    RealisticStepPyramidFactory, # 4 archetypes: small/medium/large/tall — ziggurats
    RealisticPipeJointFactory,   # 3 archetypes: elbow_45/elbow_90/elbow_135 — pipework
    # mechanical / decorative props
    RealisticGearFactory,        # 4 archetypes: small/medium/large/skewed — sprockets, clockwork
    RealisticGemstoneFactory,    # 4 archetypes: diamond_round/diamond_tall/gem_classic/gem_squat
    # geometric / abstract props
    RealisticSolidFactory,       # 7 archetypes: tetra/cube/octa/dodeca/icosa/soccer_ball/snub_cube
    RealisticSupertoroidFactory, # 4 archetypes: torus/ring/halo/donut — sculpture / monument rings
    RealisticHoneycombFactory,   # 4 archetypes: panel_small/panel_large/beehive/tile — hex grids
    RealisticMengerSpongeFactory,    # 3 archetypes: level1/level2/level3 — fractal sci-fi monument
    RealisticFunctionSurfaceFactory, # 4 archetypes: dome/saddle/ripple/hill — math-art surface
    # mechanical (extension of gear family)
    RealisticWormGearFactory,    # 3 archetypes: compact/long/stout — steampunk pair with Gear
    # parametric architecture (wraps building_tools — install required)
    RealisticBToolsBuildingFactory,  # 5 archetypes: cottage/two_storey/barn/tower/longhouse
)
# Landmarks & structures stay low-poly even in realistic mode: upstream
# Infinigen has no procedural outdoor architecture (its focus is nature
# + interiors). The maquette `LowPoly*` landmark factories are native
# implementations and the only procedural source we have. Mixing them
# alongside realistic vegetation is the v1 trade-off — aesthetic
# mismatch is mild since the LowPoly* assets are silhouette-clean.
from infinigen.maquette.factories.native.building import LowPolyHouseFactory
from infinigen.maquette.factories.native.water_tower import LowPolyWaterTowerFactory
from infinigen.maquette.factories.native.well import LowPolyWellFactory
from infinigen.maquette.factories.native.windmill import LowPolyWindmillFactory
from infinigen.maquette.factories.native.suspension_bridge import LowPolySuspensionBridgeFactory
from infinigen.maquette.factories.native.cable_car import LowPolyCableCarFactory
from infinigen.maquette.factories.native.deck import LowPolyDeckFactory
from infinigen.maquette.factories.native.torii import LowPolyToriiFactory
from infinigen.maquette.factories.native.tombstone import LowPolyTombstoneFactory
from infinigen.maquette.factories.native.stall import LowPolyStallFactory
from infinigen.maquette.factories.native.fence import LowPolyFenceFactory
from infinigen.maquette.factories.native.lantern_post import LowPolyLanternPostFactory
from infinigen.maquette.factories.native.banner import LowPolyBannerFactory
from infinigen.maquette.factories.native.boat import LowPolyBoatFactory
from infinigen.maquette.factories.native.wagon import LowPolyWagonFactory
from infinigen.maquette.factories.native.barrel import LowPolyBarrelFactory
from infinigen.maquette.factories.native.crate import LowPolyCrateFactory
from infinigen.maquette.factories.native.haystack import LowPolyHaystackFactory
from infinigen.maquette.runtime.terrain import make_terrain
# OR — when the prompt mixes biomes (grass + desert, forest + coast):
# from infinigen.maquette.runtime.terrain import make_multi_biome_terrain
# OR — for SERIOUS terrain (dramatic peaks + river systems + image refs):
# from infinigen.maquette.runtime.eroded_terrain import make_eroded_terrain

rng = random.Random(<seed>)

# 1. Wipe scene + create displaced ground. NEVER build it as a bare plane.
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
terrain = make_terrain(
    style="<flat|rolling|hilly|alpine|dunes>",
    size=80,                                # half-width in BU; world 160 BU wide
    base_color=(<R>, <G>, <B>, 1.0),
    seed=<scene seed>,
)
# Same multi-biome / eroded helpers are available — see low-poly guide
# for parameter recipes. They are mode-agnostic.

# REALISTIC-MODE TERRAIN (when using make_eroded_terrain): turn on the
# PBR shader + bake-for-export so the GLB ships actual textures
# instead of a flat fallback. The kwargs cost ~5s combined and produce
# a browser-ready terrain GLB:
#
#   from infinigen.maquette.runtime.eroded_terrain import make_eroded_terrain
#   terrain = make_eroded_terrain(
#       size=140, seed=<seed>, peaks=[...], troughs=[...],
#       realistic_textures=True,    # PBR shader (5 biome textures + box projection)
#       bake_for_export=True,       # bake to flat textures so glTF embeds them
#       bake_resolution=1024,       # 1k = ~6.7 MB GLB; 2048 for hero shots only
#   )
#
# If a build script for realistic mode forgets these flags the .blend
# render still looks right (Cycles handles procedural shaders), but
# the browser GLB ends up greyscale because procedural Voronoi +
# splat blends don't survive export_scene.gltf. Don't ship without them.

# CARVING PATHS / ROADS through the eroded terrain — use carve_path so
# a stone trail or plaza sits on a flat corridor rather than bobbing
# over the natural micro-relief:
#
#   from infinigen.maquette.runtime.eroded_terrain import carve_path
#   carve_path(
#       terrain,
#       waypoints=[(-50, -30), (-20, -10), (5, 5), (30, 25)],
#       width=3.0,        # full corridor width in BU
#       blend=2.0,        # feather distance back to natural surface
#       depth=-0.05,      # 0 = flat at surface; -0.05 = recessed track
#   )
#   # Subsequent terrain.height_at(x, y) calls return the carved heights.

# 1b. Scatter foliage / boulders / grass on the terrain via Geometry Nodes.
#     IMPORTANT: RealisticTreeFactory has a seed-dependent upstream bug.
#     Some genome seeds silently kill the script after twig-collection
#     generation. ALWAYS use `factory_seed=1` for the tree template;
#     other seeds (42, 4811) are known-bad. Use scatter helpers for
#     any forest — never spawn more than ONE RealisticTreeFactory.
#
# Two scatter helpers:
#   scatter_template(...)               — GN-based, free polycount,
#                                          for ground cover (grass).
#   scatter_template_with_keepout(...)  — Python-side, slower but
#                                          respects keep-out radii so
#                                          scatter doesn't collide with
#                                          buildings / wells / walls.
#                                          USE FOR TREES + LARGE PROPS.
# from infinigen.maquette.runtime.realistic_scatter import (
#     scatter_template, scatter_template_with_keepout,
# )
#
# # factory_seed=1 is the canonical safe seed; do not use other seeds
# # for trees unless you've verified them.
# tree_tmpl = RealisticTreeFactory(factory_seed=1, archetype="summer").spawn_asset(
#     i=1, loc=(0, 0, 0))
# # Pass landmark positions as keep-out so trees don't grow inside cottages.
# scatter_template_with_keepout(
#     terrain=terrain, template=tree_tmpl, density=0.005,
#     keep_out=[(cx, cy, 4.0) for (cx, cy, _) in cottage_spots]
#              + [(0, 0, 3.0)]   # keep-out for the central well too
#              + [(tx, ty, 5.0)] # tower at (tx, ty)
#     ,
#     seed=1,
# )
# scatter_template(
#     terrain=terrain, template=tree_tmpl,
#     density=0.005, biome_filter="grass", seed=42,
# )
#
# Realistic densities (instances per BU² of eligible surface):
#   trees on grass     : 0.002 - 0.008  (PS3-era, reads as forest)
#   boulders on alpine : 0.005 - 0.020
#   grass tufts        : 0.05  - 0.20
#   flowers            : 0.02  - 0.10
#
# RULE OF THUMB: spawn AT MOST 4 RealisticTreeFactory directly. For more
# than 4 trees ALWAYS use scatter_template instead. Same for ferns +
# mushrooms (they hit the same curve-API issue at high counts).

# 2. Spawn assets via factories.
#    Pattern: f = RealisticXFactory(factory_seed=N, archetype="...")
#             obj = f.spawn_asset(i=N, loc=(x, y, terrain.height_at(x, y)))
#             obj.rotation_euler.z = rot_z
#
#    Realistic factories all use the upstream AssetFactory.spawn_asset
#    flow — placeholder + asset two-step is internal. Do NOT call
#    create_asset(placeholder=None) directly (low-poly native trick); use
#    spawn_asset(i, loc) like upstream Infinigen.

# 3. Camera + sun + world background — same recipes as low-poly mode.
bpy.ops.object.camera_add(location=(<X>, <Y>, <Z>))
cam = bpy.context.active_object
target = Vector((<tx>, <ty>, <tz>))
cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
cam.data.lens = 35
bpy.context.scene.camera = cam

bpy.ops.object.light_add(type="SUN", location=(<X>, <Y>, <Z>))
sun = bpy.context.active_object
sun.data.energy = <energy>
sun.data.color = (<R>, <G>, <B>)
sun.rotation_euler = (math.radians(<pitch>), math.radians(<roll>), math.radians(<yaw>))

w = bpy.context.scene.world
w.use_nodes = True
w.node_tree.nodes.clear()
out = w.node_tree.nodes.new("ShaderNodeOutputWorld")
bg = w.node_tree.nodes.new("ShaderNodeBackground")
bg.inputs[0].default_value = (<R>, <G>, <B>, 1.0)
bg.inputs[1].default_value = 1.0
w.node_tree.links.new(bg.outputs[0], out.inputs[0])

# 4. Render + save (the pipeline expects these exact paths).
import os
OUT_DIR = Path(os.environ["MAQUETTE_OUT_DIR"])
sc = bpy.context.scene
sc.render.engine = "CYCLES"
sc.cycles.samples = 96                         # realistic = more samples
sc.render.resolution_x = 1920
sc.render.resolution_y = 1080
sc.render.resolution_percentage = 100
sc.view_settings.view_transform = "Filmic"     # realistic = Filmic, not Standard
sc.render.filepath = str(OUT_DIR / "scene.png")
sc.render.image_settings.file_format = "PNG"
bpy.ops.render.render(write_still=True)
bpy.ops.wm.save_as_mainfile(filepath=str(OUT_DIR / "scene.blend"))
print(f"DONE: {OUT_DIR}/scene.png")
```

### Hybrid landmark policy (important)

Realistic mode covers **vegetation, rocks, and underwater life only**.
Upstream Infinigen has no procedural outdoor architecture, so for
landmarks and structures (houses, bridges, windmills, torii, fences,
vehicles, props like crates/barrels/haystacks, etc.) you MUST import
the existing low-poly factories and use them as-is. They're listed in
the header import block — `LowPolyHouseFactory`, `LowPolyWindmillFactory`,
`LowPolySuspensionBridgeFactory`, `LowPolyToriiFactory`,
`LowPolyTombstoneFactory`, `LowPolyDeckFactory`, `LowPolyCableCarFactory`,
`LowPolyWaterTowerFactory`, `LowPolyWellFactory`, `LowPolyStallFactory`,
`LowPolyFenceFactory`, `LowPolyLanternPostFactory`, `LowPolyBannerFactory`,
`LowPolyBoatFactory`, `LowPolyWagonFactory`, `LowPolyBarrelFactory`,
`LowPolyCrateFactory`, `LowPolyHaystackFactory`.

These keep their stylized palette (palette_color kwarg). The mild
aesthetic mismatch versus realistic vegetation is intentional — it's
the v1 trade-off until we ship native realistic architecture.

If a prompt is dominated by buildings and the realistic vegetation would
look out of place, prefer using realistic only for the terrain + ground
cover (grass, flowers) and keep all hero-asset categories low-poly.

### Materials

Realistic factories ship their own upstream Infinigen shaders (bark,
foliage, rock, cactus, fern, etc.). Do NOT apply the Maquette palette
to those. The LowPoly* landmark factories (above) DO use the Maquette
palette — keep their `palette_color` kwarg as you would in low-poly mode.

### Lighting

Use Filmic view transform (set in the render block above) and the same
sun-energy / sky-color recipes as low-poly mode — they translate cleanly
because they were calibrated against physical sun strength.

### LOD bake (post-render)

After `bpy.ops.wm.save_as_mainfile`, the pipeline runs
`infinigen.maquette.runtime.lod_bake.bake_for_browser(out_dir)` which
exports GLB, generates 4 LOD levels via `gltf-transform simplify`, applies
Draco + KTX2 compression, and writes a scatter-instance manifest. Don't
do any of this in the build script itself — it's the runner's job.

### Missing factories

If a prompt needs an asset class that's not in the realistic catalog
below, include a comment in the script of the form:

```python
# REQUESTED_ASSET: <FactoryName> — <what it should be>
```

Use the closest existing factory as a stand-in (e.g. RealisticBushFactory
for shrubs, RealisticTreeFactory(archetype="winter") for dead trees) and
CONTINUE building the scene. Do not refuse to build.

### Camera framing

Use `cam.data.lens = 35` for wide scene shots and `lens = 50` for tight
prop shots. For an oblique-aerial scene view of a size=80 (160 BU wide)
world, the camera at `(40, -44, 26)` looking at `(0, 0, 3)` frames the
full scene cleanly. Scale linearly with terrain size if you change it.

---

## Factories

"""


_FOOTER = """\

---

Generated automatically by `infinigen.maquette.pipeline.factories_guide`.
"""


def build_guide(mode: str = "low_poly") -> str:
    """Build the full markdown guide string for the given mode."""
    if mode not in VALID_MODES:
        raise ValueError(f"mode={mode!r} not in {VALID_MODES}")
    header = _HEADER if mode == "low_poly" else _HEADER_REALISTIC
    parts = [header]
    for path in _factory_files(mode):
        entry = _entry_for(path)
        if entry:
            parts.append(entry)
    parts.append(_FOOTER)
    return "\n".join(parts)


def guide_path_for(mode: str) -> Path:
    """Canonical on-disk path for a mode's guide file."""
    if mode not in VALID_MODES:
        raise ValueError(f"mode={mode!r} not in {VALID_MODES}")
    name = "FACTORIES_GUIDE.md" if mode == "low_poly" else "FACTORIES_GUIDE_REALISTIC.md"
    return MAQUETTE_DIR / name


def write_guide(out_path: Path | None = None, mode: str = "low_poly") -> Path:
    """Build and write to disk. Default location depends on mode."""
    if out_path is None:
        out_path = guide_path_for(mode)
    out_path.write_text(build_guide(mode))
    return out_path


def _structured_entry_for(path: Path) -> dict | None:
    """Return a dict describing a single factory module, or None if the
    file isn't a factory. Used by the debug API to render the catalog as
    structured data instead of free-form markdown."""
    src = path.read_text()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    cls = _find_factory_class(tree)
    if cls is None:
        return None
    class_name, class_doc = cls
    mod_doc = _module_docstring(tree) or ""
    archetype_tuples = _find_archetype_tuples(tree)
    init_fn = _find_class_init(tree, class_name)
    params = _format_init_params(init_fn) if init_fn is not None else []
    rel_path = path.relative_to(FORK_ROOT)
    return {
        "module": path.stem,
        "module_path": str(rel_path),
        "class_name": class_name,
        "category": category_for(path.stem),
        "module_doc": mod_doc.strip(),
        "class_doc": (class_doc or "").strip(),
        "archetypes": [
            {"label": name.strip("_").removesuffix("_ARCHETYPES").lower() or "archetype",
             "values": values}
            for name, values in archetype_tuples
        ],
        "constructor_params": params,
        "default_knobs": _find_archetype_defaults_keys(tree),
    }


def list_factories(mode: str = "low_poly") -> list[dict]:
    """Return a structured list of every factory in the catalog for a mode."""
    out: list[dict] = []
    for path in _factory_files(mode):
        entry = _structured_entry_for(path)
        if entry is not None:
            out.append(entry)
    return out


if __name__ == "__main__":
    for mode in VALID_MODES:
        p = write_guide(mode=mode)
        print(f"[{mode}] Wrote {p} ({p.stat().st_size:,} bytes)")

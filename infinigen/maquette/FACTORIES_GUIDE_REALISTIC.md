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

# LOADED CC0 ASSETS — large variety pool of pre-modeled low-poly
# buildings, trees, rocks, and plants from CC0 packs (Kenney "Retro
# Medieval Kit" and "Nature Kit" via OpenGameArt). Use these when the
# scene needs visual variety beyond what the procedural factories give:
#
#   from infinigen.maquette.runtime.loaded_factory import (
#       LoadedMedievalFactory,   # 105 archetypes: walls, towers, columns,
#                                # docks, fences, barrels, ladders, roofs
#       LoadedTreeFactory,       # 61 archetypes: tree variants × season
#                                # (default/dark/fall) × shape (cone/blocks)
#       LoadedRockFactory,       # 30 archetypes: rock_largeA..F + smallA..H
#       LoadedPlantFactory,      # 28 archetypes: plant_*, flower_*,
#                                # mushroom_*, grass_*, lily_*
#   )
#
#   # List archetypes for a category:
#   LoadedMedievalFactory.archetypes()
#
#   # Spawn one (interface matches every other factory in the catalog):
#   f = LoadedTreeFactory(archetype="tree_cone_dark", factory_seed=1, scale=2.5)
#   f.spawn_asset(i=0, loc=(x, y, terrain.height_at(x, y)))
#
#   # archetype=None rolls a random archetype seeded by factory_seed —
#   # cheapest way to get a varied stand of trees:
#   for k in range(20):
#       LoadedTreeFactory(factory_seed=k+1, scale=2.5).spawn_asset(
#           i=k, loc=(x, y, terrain.height_at(x, y)))
#
# Spawned objects share mesh data via ``object.copy()`` so 100 trees of
# the same archetype don't bloat the .blend. They ship at low poly
# count already (~200-500 verts each) — no decimate hook needed.

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


### `RealisticBeamFactory`

RealisticBeamFactory — structural steel beams, wraps Blender's BeamBuilder.

**beam** archetypes: `box` / `u` / `c` / `l` / `i` / `t` / `any`

**Constructor parameters:**
```
factory_seed: int
archetype: str = 'i'
length: float = 4.0
width: float = 0.3
height: float = 0.4
wall_thickness: float = 0.05
edge_taper: float = 100.0
```

### `RealisticBlenderRockFactory`

RealisticBlenderRockFactory — small rock variants, wraps upstream.

**rock** archetypes: `pebble` / `fragment` / `any`

**Constructor parameters:**
```
factory_seed: int
archetype: str = 'any'
detail: int = 1
```

### `RealisticBoulderFactory`

RealisticBoulderFactory — realistic boulder, wraps upstream Infinigen.

**boulder** archetypes: `boulder` / `slab` / `any`

**Constructor parameters:**
```
factory_seed: int
archetype: str = 'any'
do_voronoi: bool = True
```

### `RealisticBoulderPileFactory`

RealisticBoulderPileFactory — clustered rock pile, DISABLED.

**pile** archetypes: `scree` / `cluster` / `any`

**Constructor parameters:**
```
factory_seed: int
archetype: str = 'any'
```

### `RealisticBToolsBuildingFactory`

RealisticBToolsBuildingFactory — parametric building, wraps building_tools.

**building** archetypes: `cottage` / `two_storey` / `barn` / `tower` / `longhouse` / `any`

**Constructor parameters:**
```
factory_seed: int
archetype: str = 'two_storey'
slab: bool = True
```

### `RealisticBushFactory`

RealisticBushFactory — realistic bush, wraps upstream Infinigen.

**bush** archetypes: `leafy` / `sparse` / `any`

**Constructor parameters:**
```
factory_seed: int
archetype: str = 'any'
```

### `RealisticCactusFactory`

RealisticCactusFactory — realistic cactus, wraps upstream Infinigen.

**cactus** archetypes: `globular` / `columnar` / `pricky_pear` / `kalidium` / `any`

**Constructor parameters:**
```
factory_seed: int
archetype: str = 'any'
```

### `RealisticCoralFactory`

RealisticCoralFactory — coral, wraps upstream dispatcher.

**coral** archetypes: `elkhorn` / `star` / `cauliflower` / `tube` / `tree` / `diff_growth` / `reaction_diffusion` / `any`

**Constructor parameters:**
```
factory_seed: int
archetype: str = 'any'
```

### `RealisticDandelionFactory`

RealisticDandelionFactory — wildflower seed-puff, wraps upstream.

**dandelion** archetypes: `yellow` / `puff` / `any`

**Constructor parameters:**
```
factory_seed: int
archetype: str = 'any'
```

### `RealisticFernFactory`

RealisticFernFactory — realistic fern, wraps upstream Infinigen.

**fern** archetypes: `frond` / `shuttlecock` / `any`

**Constructor parameters:**
```
factory_seed: int
archetype: str = 'any'
```

### `RealisticFlowerFactory`

RealisticFlowerFactory — realistic wildflower, wraps upstream Infinigen.

**flower** archetypes: `small` / `medium` / `large` / `any`

**Constructor parameters:**
```
factory_seed: int
archetype: str = 'any'
rad: float | None = None
diversity_fac: float | None = None
```

### `RealisticFlowerPlantFactory`

RealisticFlowerPlantFactory — leafy flowering plant, wraps upstream.

**flower_plant** archetypes: `herb` / `wildflower` / `any`

**Constructor parameters:**
```
factory_seed: int
archetype: str = 'any'
```

### `RealisticFunctionSurfaceFactory`

RealisticFunctionSurfaceFactory — math-art surface, derived from addon.

**fn** archetypes: `dome` / `saddle` / `ripple` / `hill` / `any`

**Constructor parameters:**
```
factory_seed: int
archetype: str = 'dome'
size: float = 2.0
subdivisions: int = 24
```

### `RealisticGearFactory`

RealisticGearFactory — sprocket / mechanical gear, wraps Blender's gear addon.

**gear** archetypes: `small` / `medium` / `large` / `skewed` / `any`

**Constructor parameters:**
```
factory_seed: int
archetype: str = 'medium'
```

### `RealisticGemstoneFactory`

RealisticGemstoneFactory — faceted gem / diamond, wraps gemstones addon.

**gem** archetypes: `diamond_round` / `diamond_tall` / `gem_classic` / `gem_squat` / `any`

**Constructor parameters:**
```
factory_seed: int
archetype: str = 'diamond_round'
```

### `RealisticGlowingRocksFactory`

RealisticGlowingRocksFactory — luminescent gem rocks, wraps upstream.

**glow** archetypes: `dim` / `bright` / `any`

**Constructor parameters:**
```
factory_seed: int
archetype: str = 'any'
```

### `RealisticGrassTuftFactory`

RealisticGrassTuftFactory — realistic grass tuft, wraps upstream Infinigen.

**grass** archetypes: `meadow` / `tall` / `dry` / `any`

**Constructor parameters:**
```
factory_seed: int
archetype: str = 'any'
```

### `RealisticHoneycombFactory`

RealisticHoneycombFactory — hex-grid panel, wraps addon.

**honeycomb** archetypes: `panel_small` / `panel_large` / `beehive` / `tile` / `any`

**Constructor parameters:**
```
factory_seed: int
archetype: str = 'panel_small'
```

### `RealisticKelpMonocotFactory`

RealisticKelpMonocotFactory — tall aquatic monocot, wraps upstream.

**kelp** archetypes: `forest` / `single` / `any`

**Constructor parameters:**
```
factory_seed: int
archetype: str = 'any'
```

### `RealisticMengerSpongeFactory`

RealisticMengerSpongeFactory — fractal cube, wraps addon.

**menger** archetypes: `level1` / `level2` / `level3` / `any`

**Constructor parameters:**
```
factory_seed: int
archetype: str = 'level2'
size: float = 2.0
```

### `RealisticMushroomFactory`

RealisticMushroomFactory — realistic mushroom cluster, wraps upstream Infinigen.

**mushroom** archetypes: `toadstool` / `glowcap` / `cluster` / `any`

**Constructor parameters:**
```
factory_seed: int
archetype: str = 'any'
```

### `RealisticPipeJointFactory`

RealisticPipeJointFactory — pipework joint primitive.

**pipe** archetypes: `elbow_45` / `elbow_90` / `elbow_135` / `any`

**Constructor parameters:**
```
factory_seed: int
archetype: str = 'elbow_90'
radius: float = 0.15
div: int = 16
leg_length: float = 0.6
```

### `RealisticSeaweedFactory`

RealisticSeaweedFactory — branching kelp-like aquatic plant, wraps upstream.

**seaweed** archetypes: `branching` / `frond` / `any`

**Constructor parameters:**
```
factory_seed: int
archetype: str = 'any'
```

### `RealisticSnakePlantFactory`

RealisticSnakePlantFactory — upright variegated succulent, wraps upstream.

**snake** archetypes: `upright` / `fan` / `any`

**Constructor parameters:**
```
factory_seed: int
archetype: str = 'any'
```

### `RealisticSolidFactory`

RealisticSolidFactory — Platonic / Archimedean solids, wraps addon.

**solid** archetypes: `tetrahedron` / `cube` / `octahedron` / `dodecahedron` / `icosahedron` / `soccer_ball` / `snub_cube` / `any`

**Constructor parameters:**
```
factory_seed: int
archetype: str = 'icosahedron'
size: float = 1.0
```

### `RealisticSpiderPlantFactory`

RealisticSpiderPlantFactory — cascading grassy plant, wraps upstream.

**spider** archetypes: `hanging` / `compact` / `any`

**Constructor parameters:**
```
factory_seed: int
archetype: str = 'any'
```

### `RealisticStepPyramidFactory`

RealisticStepPyramidFactory — ziggurat / step pyramid, wraps addon.

**pyramid** archetypes: `small` / `medium` / `large` / `tall` / `any`

**Constructor parameters:**
```
factory_seed: int
archetype: str = 'medium'
```

### `RealisticSucculentFactory`

RealisticSucculentFactory — rosette succulent, wraps upstream.

**succulent** archetypes: `thick` / `thin` / `any`

**Constructor parameters:**
```
factory_seed: int
archetype: str = 'any'
```

### `RealisticSupertoroidFactory`

RealisticSupertoroidFactory — parametric supertoroid, wraps addon.

**toroid** archetypes: `torus` / `ring` / `halo` / `donut` / `any`

**Constructor parameters:**
```
factory_seed: int
archetype: str = 'torus'
```

### `RealisticTreeFactory`

RealisticTreeFactory — realistic tree, wraps upstream Infinigen.

**tree** archetypes: `summer` / `autumn` / `winter` / `spring` / `any`

**Constructor parameters:**
```
factory_seed: int
archetype: str = 'any'
fruit_chance: float = 1.0
```

### `RealisticUrchinFactory`

RealisticUrchinFactory — sea urchin, wraps upstream.

**urchin** archetypes: `spiny` / `flat` / `any`

**Constructor parameters:**
```
factory_seed: int
archetype: str = 'any'
```

### `RealisticWallFactory`

RealisticWallFactory — masonry wall, wraps Blender's Wallfactory addon.

**wall** archetypes: `boundary` / `fortress` / `ruin` / `tower_round` / `garden_low` / `any`

**Constructor parameters:**
```
factory_seed: int
archetype: str = 'boundary'
```

### `RealisticWormGearFactory`

RealisticWormGearFactory — worm gear, wraps Blender's gear addon.

**worm** archetypes: `compact` / `long` / `stout` / `any`

**Constructor parameters:**
```
factory_seed: int
archetype: str = 'compact'
```


---

Generated automatically by `infinigen.maquette.pipeline.factories_guide`.

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
# DEFAULT: painterly Sky-CotL-style terrain (vertex-color biome bands,
# half-Lambert directional shading, crest highlights, per-realm palette).
# Use this unless the camera is far away or the ground is mostly hidden.
from infinigen.maquette.runtime.eroded_terrain import make_eroded_terrain
# Fallback A — single-style flat-shaded ground (faster, lower quality):
# from infinigen.maquette.runtime.terrain import make_terrain
# Fallback B — multi-biome flat-shaded zones (hard color boundaries):
# from infinigen.maquette.runtime.terrain import make_multi_biome_terrain

rng = random.Random(<seed>)

# 1. Wipe scene + create displaced ground. NEVER build it as a bare plane.
# Pick the helper that fits the prompt:
#
# DEFAULT: make_eroded_terrain — this is the painterly Sky-CotL-style
#   terrain pipeline (vertex-color biome bands, half-Lambert directional
#   shading, crest highlights, voronoi territorial drift, per-realm
#   palette dispatch). Use this for ANY prompt that benefits from
#   "painted by light" terrain coloring — i.e., almost everything other
#   than a strict ground tile under hero buildings. See `palette_preset`
#   for realm tuning (alpine/desert/wetland/volcanic/savanna/tundra/tropical).
#
# OTHERWISE:
#   make_terrain(style=...)             — flat/rolling/hilly/alpine/dunes,
#                                         single biome, FLAT-SHADED (single
#                                         Kd per zone, no per-vertex Lambert
#                                         or crest). Use only when the
#                                         camera will be far away or when
#                                         the ground is mostly hidden under
#                                         buildings — otherwise it reads as
#                                         flatter and more generic than the
#                                         eroded path.
#   make_multi_biome_terrain(zones=...) — mixed biomes side-by-side, also
#                                         flat-shaded. Same caveat as above.
#                                         Pick this only when you need a
#                                         hard zone boundary, not a blended
#                                         biome transition.
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
#       # outflow_xy=(140, 0),              # OPTIONAL: river-mouth outlet at this
#       #                                   # world point (must be near a rim).
#       #                                   # Forces drainage to converge on a
#       #                                   # single mouth instead of dispersing.
#       #                                   # Pair with troughs that lead toward it.
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

# 2b. Dress paths with props (lanterns / curb stones / fence posts).
#     ONE call per Composition with paths; runs AFTER apply_composition so
#     terrain.height_at returns the carved saddle.
# from infinigen.maquette.runtime.dress_path import dress_path
# dress_path(composition, archetype="lantern_posts", terrain=terrain)
#   archetype: "lantern_posts" (stone_road/town/temple, 6 BU cadence)
#              "curb_stones"  (dirt_trail/wilderness, 2 BU cadence)
#              "fence_posts"  (farm/pasture, 4 BU cadence)
#   Don't pass `spacing` — defaults are tuned. Skip dress_path entirely
#   when there's no path.

# 3. Camera + sun + world background
# Camera is auto-placed by `place_scene_camera(composition, terrain_size=...,
# terrain=terrain)` — DO NOT call `bpy.ops.object.camera_add`.
# Pass `terrain=terrain` so the helper samples the actual height under
# the hero (otherwise tall heroes get cropped). Don't pass `lens_mm` —
# the 35 mm default is correct.
from infinigen.maquette.runtime.camera import place_scene_camera
place_scene_camera(composition, terrain_size=80, terrain=terrain)

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
    around the central scene. Prefer `LoadedTreeFactory` from
    `infinigen.maquette.runtime.loaded_factory` for leafy trees; these
    are authored low-poly GLB meshes and read better than procedural
    blob foliage. Use `NativeLowPolyTreeFactory` mainly for bare/dead
    procedural silhouettes (`preset="bare_winter"` etc.).
  - **Building cluster**: 3-5 houses arranged around a central focal
    point (well, square, plaza), each rotated to face inward.
  - **Path props**: lanterns or torii at regular intervals along the
    travel direction.
  - **Riprap**: scatter 5-10 boulders along the water/wall edge for
    natural transition.
  - **Yard scatter**: barrels + crates in clusters of 3-5 next to
    building doors.
  - **Fishing village (coastal / fishing / harbour prompts)**: the
    waterline is the focal point, NOT a market plaza. Run a
    `LowPolyDockFactory` pier (`dock_archetype="fishing_wharf"` or
    `"straight_pier"`) out over
    the water; moor 1-3 `LowPolyBoatFactory` rowboats
    (`boat_archetype="rowboat"`) at the dock head and along the shore;
    line the beach with 3-6 `LowPolyFishDryingRackFactory` racks facing
    the water; set `LowPolyHouseFactory` cottages back from the shore,
    gable-end to the sea; scatter `LoadedTreeFactory` palms /
    wind-bent trees on the headland. Keep boats / decks / racks within
    ~8m of the waterline.
  - **Oasis bazaar (oasis / bazaar / caravan prompts)**: the pool is the
    focal point. Ring it with `LowPolyPalmTreeFactory` palms; arrange
    4-8 `LowPolyBazaarTentFactory` tents plus `LowPolyMarketRugFactory`
    rugs in a loose market ring 4-10m back from the water; cluster a rug
    beside each tent (stall + spread goods); use sandstone ruin
    fragments and the occasional `LowPolyHouseFactory` only as secondary
    scatter. Tents + rugs + palms carry the bazaar — do NOT fall back to
    a generic houses-near-water layout.

### Premeshed tree bank

For normal leafy trees, use the shipped GLB tree bank instead of trying
to model foliage by hand:

```python
from infinigen.maquette.runtime.loaded_factory import LoadedTreeFactory

tree = LoadedTreeFactory(
    archetype="tree_oak",          # examples: tree_oak, tree_default,
                                   # tree_blocks, tree_plateau, tree_fat,
                                   # tree_thin, tree_cone,
                                   # tree_pineDefaultA, tree_pineRoundA,
                                   # tree_pineTallA, tree_palmBend
    factory_seed=seed,
    scale=2.0,
    scale_jitter=0.16,             # per-seed overall size variation
    xy_jitter=0.08,                # crown/trunk width variation
    z_jitter=0.12,                 # taller/shorter silhouette variation
    tint_palette=("foliage_pine", "foliage_bush", "foliage_apple"),
    tint_strength=0.55,            # foliage tint; bark stays subtle
).spawn_asset(i=i, loc=(x, y, terrain.height_at(x, y)))
```

Use `NativeLowPolyTreeFactory` only when you need procedural bare/dead
trees, unusual skeletons, or a placeholder variant not present in the
GLB bank.

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

### Camera framing — auto-placed

DO NOT author the camera. Call:

```python
from infinigen.maquette.runtime.camera import place_scene_camera
place_scene_camera(composition, terrain_size=80, terrain=terrain)
```

ALWAYS pass `terrain=terrain` so the helper samples the actual height
under the hero (otherwise a hero on a 12 BU peak gets cropped at the
top of frame). The helper picks framing from your `Composition`:
hero + water → camera past the lake looking at the hero, hero + ridge
→ camera perpendicular to the ridge axis.

DO NOT pass `lens_mm` — the 35 mm default is correct for almost every
prompt. Override only for explicit 4+ hero panoramas (`lens_mm=28`).
Never pass 50 mm; it crops the hero on tall terrain.

---

## Factories


### `LowPolyBoulderFactory`

LowPolyBoulderFactory — Maquette wrapper for upstream BoulderFactory.

**Named presets:** `bleached` / `charred` / `mossy`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
target_face_size: float | None = None
polygon_multiplier: float = 1.0
decimate_ratio: float | None = None
palette_color: str | None = 'rock_warm'
```

### `LowPolyTreeFactory`

LowPolyTreeFactory — bare-trunk Firewatch silhouette.

**Constructor parameters:**
```
factory_seed
season: str | None = None
species: str = 'pine'
target_face_size: float = 0.15
target_polys: int = 1200
palette_color: str | None = None
```

### `LowPolyBambooFactory`

LowPolyBambooFactory — segmented bamboo culms in clumps, groves, screens.

**bamboo** archetypes: `grove_clump` / `single_stalk` / `bent_arch` / `bamboo_screen`

**Named presets:** `garden_grove` / `garden_screen` / `golden_grove` / `path_accent` / `windswept_grove`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
bamboo_archetype: str = 'grove_clump'
culm_color: str | None = None
foliage_color: str | None = None
```

### `LowPolyBannerFactory`

LowPolyBannerFactory — hanging cloth banner / flag.

**banner** archetypes: `hanging` / `flag_pole` / `horizontal`

**Named presets:** `castle_flag` / `festival_street` / `guild_banner` / `heraldic_hanging`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
banner_archetype: str = 'hanging'
length: float | None = None
height: float | None = None
pole_height: float | None = None
n_segments: int | None = None
wave_amplitude: float | None = None
has_crossbar: bool | None = None
crossbar_extra: float | None = None
cloth_color: str | None = None
pole_color: str | None = None
accent_color: str | None = None
```

### `LowPolyBarrelFactory`

LowPolyBarrelFactory — wooden / metal storage barrel.

**barrel** archetypes: `wooden` / `metal_drum`

**Constructor parameters:**
```
factory_seed
barrel_archetype: str = 'wooden'
height: float | None = None
radius: float | None = None
polygon_multiplier: float = 1.0
target_edge: float | None = None
n_staves: int | None = None
n_bands: int | None = None
band_thickness: float | None = None
band_protrusion: float | None = None
on_its_side: bool = False
body_color: str | None = None
band_color: str | None = None
```

### `LowPolyBazaarTentFactory`

LowPolyBazaarTentFactory — desert bazaar / market tent.

**bazaar_tent** archetypes: `peaked` / `ridge` / `awning_open`

**Named presets:** `caravan_ridge` / `oasis_peaked` / `royal_pavilion` / `souk_awning`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
bazaar_tent_archetype: str = 'peaked'
width: float | None = None
depth: float | None = None
eave_height: float | None = None
peak_rise: float | None = None
canopy_color: str | None = None
pole_color: str | None = None
canopy_alt_color: str | None = None
```

### `LowPolyBellFactory`

LowPolyBellFactory — hanging bronze bell on a wooden frame.

**bell** archetypes: `temple` / `belfry` / `cattle`

**Named presets:** `ceremonial` / `monastery` / `village_alarm` / `weathered_cattle`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
bell_archetype: str = 'temple'
n_sides: int = 10
bronze_color: str | None = None
wood_color: str | None = None
roof_color: str | None = None
```

### `LowPolyBoatFactory`

LowPolyBoatFactory — rowboat / dinghy / fishing skiff / pirate brig.

**boat** archetypes: `rowboat` / `dinghy` / `fishing_skiff` / `pirate_brig`

**Named presets:** `beached_dinghy` / `ghost_ship` / `harbor_rowboat` / `pirate_brig` / `village_fishing_skiff`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
boat_archetype: str = 'rowboat'
length: float | None = None
width: float | None = None
height: float | None = None
bow_taper: float | None = None
stern_taper: float | None = None
n_thwarts: int | None = None
has_oars: bool | None = None
oar_length: float | None = None
has_mast: bool | None = None
mast_height: float | None = None
has_sail: bool | None = None
sail_size: tuple[float, float] | None = None
has_bowsprit: bool | None = None
hull_color: str | None = None
trim_color: str | None = None
sail_color: str | None = None
accent_color: str | None = None
```

### `LowPolyHouseFactory`

LowPolyHouseFactory — Sapling-style native low-poly building.

**roof** archetypes: `gabled` / `hipped` / `flat` / `shed` / `gambrel` / `mansard` / `cross_gabled` / `pyramid`
**building** archetypes: `cottage` / `barn` / `tower` / `cabin` / `longhouse` / `townhouse` / `workshop` / `tavern` / `stable`

**Named presets:** `coastal_painted` / `cottage_thatched` / `desert_adobe` / `ruined` / `snowbound`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
building_archetype: str = 'cottage'
roof_archetype: str | None = None
width: float | None = None
depth: float | None = None
wall_height: float | None = None
roof_height: float | None = None
n_windows: int | None = None
has_chimney: bool | None = None
foundation_height: float | None = None
roof_overhang: float | None = None
detail_level: str | None = None
has_awning: bool | None = None
has_side_shed: bool | None = None
storeys: int | None = None
has_balcony: bool | None = None
has_side_stairs: bool | None = None
has_flower_boxes: bool | None = None
has_chairs: bool | None = None
wall_color: str | None = 'rock_pale'
roof_color: str | None = 'rock_shadow'
accent_color: str | None = 'accent_red'
foundation_color: str | None = 'rock_shadow'
window_color: str | None = 'sky_cool'
foliage_color: str | None = 'foliage_rose'
window_glow: bool = False
window_glow_color: str | None = None
window_emission_strength: float = 1.5
emit_window_light: bool = False
window_light_energy: float = 24.0
window_light_radius: float = 2.0
```

### `LowPolyCableCarFactory`

LowPolyCableCarFactory — gondola box hanging from a diagonal cable.

**cable_car** archetypes: `alpine_gondola` / `mining_bucket` / `chair_lift`

**Constructor parameters:**
```
factory_seed
cable_car_archetype: str = 'alpine_gondola'
cabin_length: float | None = None
cabin_width: float | None = None
cabin_height: float | None = None
has_roof: bool | None = None
roof_height: float | None = None
has_walls: bool | None = None
wall_thickness: float | None = None
has_floor: bool | None = None
hanger_length: float | None = None
hanger_thickness: float | None = None
cable_length: float | None = None
cable_slope: float | None = None
cable_thickness: float | None = None
n_cable_segments: int | None = None
body_color: str | None = None
cable_color: str | None = None
roof_color: str | None = None
```

### `LowPolyCactusFactory`

LowPolyCactusFactory — saguaro / barrel cactus.

**cactus** archetypes: `saguaro` / `barrel` / `column_cactus` / `branching`

**Named presets:** `barrel_cactus` / `column_cactus` / `desert_saguaro` / `old_saguaro`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
cactus_archetype: str = 'saguaro'
height: float | None = None
base_radius: float | None = None
top_radius: float | None = None
polygon_multiplier: float = 1.0
target_edge: float | None = None
n_sides: int | None = None
n_layers: int | None = None
rib_amplitude: float | None = None
dome_segments: int | None = None
n_arms: int | None = None
arm_radius_fraction: float | None = None
arm_horizontal_extent: float | None = None
arm_vertical_extent: float | None = None
arm_z_fraction_range: tuple[float, float] | None = None
has_flower: bool | None = None
flower_radius_fraction: float | None = None
body_color: str | None = None
flower_color: str | None = None
```

### `LowPolyCampfireFactory`

LowPolyCampfireFactory — fire ring / travel camp light source.

**campfire** archetypes: `stone_ring` / `log_pile` / `ember_bed`

**Named presets:** `bright_hearth` / `dying_embers` / `traveler_camp`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
campfire_archetype: str = 'stone_ring'
radius: float | None = None
stone_count: int | None = None
log_count: int | None = None
flame_height: float | None = None
flame_radius: float | None = None
stone_color: str | None = None
log_color: str | None = None
flame_color: str | None = None
emit_light: bool = True
light_energy: float | None = None
light_radius: float | None = None
emission_strength: float | None = None
use_loaded_base: bool = True
base_archetype: str | None = None
```

### `LowPolyCandleClusterFactory`

LowPolyCandleClusterFactory — candles for shrines, tables, crypts.

**candle** archetypes: `three_candles` / `altar_row` / `melted_cluster`

**Named presets:** `altar_three` / `chapel_row` / `melted_crypt`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
candle_archetype: str = 'three_candles'
candle_count: int | None = None
wax_color: str = 'stucco'
holder_color: str = 'rust_metal'
flame_color: str = 'foliage_lemon'
emit_light: bool = True
light_energy: float = 28.0
light_radius: float = 0.75
emission_strength: float = 3.4
```

### `LowPolyChapelFactory`

LowPolyChapelFactory — chapel / wayside shrine landmark.

**chapel** archetypes: `village_chapel` / `alpine_chapel` / `ruined_chapel`

**Named presets:** `alpine_snow` / `ruined_wayside` / `village_stone`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
chapel_archetype: str = 'village_chapel'
length: float | None = None
depth: float | None = None
wall_height: float | None = None
roof_height: float | None = None
tower_height: float | None = None
tower_width: float | None = None
roof_overhang: float | None = None
wall_color: str | None = None
roof_color: str | None = None
wood_color: str | None = None
window_color: str | None = None
accent_color: str | None = None
```

### `LowPolyCrateFactory`

LowPolyCrateFactory — wooden / metal storage crate.

**crate** archetypes: `wooden` / `metal` / `fragile`

**Constructor parameters:**
```
factory_seed
crate_archetype: str = 'wooden'
size: float | tuple | None = None
plank_pattern: bool | None = None
edge_strapping: bool | None = None
n_planks: int | None = None
plank_offset: float | None = None
strap_thickness: float | None = None
strap_protrusion: float | None = None
body_color: str | None = None
strap_color: str | None = None
```

### `LowPolyDeckFactory`

LowPolyDeckFactory — pier / boardwalk / dock.

**deck** archetypes: `pier` / `boardwalk` / `dock_railed`

**Constructor parameters:**
```
factory_seed
deck_archetype: str = 'pier'
length: float | None = None
width: float | None = None
deck_height: float | None = None
deck_thickness: float | None = None
post_spacing: float | None = None
post_size: float | None = None
post_depth: float | None = None
n_planks_along: int | None = None
plank_gap: float | None = None
has_railings: bool | None = None
railing_height: float | None = None
deck_color: str | None = None
post_color: str | None = None
rail_color: str | None = None
```

### `LowPolyDockFactory`

LowPolyDockFactory — fishing pier / wharf / ruined jetty.

**dock** archetypes: `straight_pier` / `l_wharf` / `fishing_wharf` / `ruined_jetty`

**Named presets:** `broken_jetty` / `l_shaped_landing` / `straight_fishing_pier` / `working_wharf`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
dock_archetype: str = 'straight_pier'
length: float | None = None
width: float | None = None
side_length: float | None = None
rail: bool | None = None
cargo: int | None = None
broken: float | None = None
plank_color: str = 'wood'
post_color: str = 'rust_metal'
cargo_color: str = 'rock_warm'
```

### `LowPolyFarmAnimalFactory`

LowPolyFarmAnimalFactory — livestock silhouettes for villages.

**farm_animal** archetypes: `sheep` / `goat` / `cow` / `chicken`

**Named presets:** `brown_goat` / `field_cow` / `white_sheep` / `yard_chicken`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
animal_archetype: str = 'sheep'
scale: float | None = None
body_color: str | None = None
accent_color: str | None = None
detail_color: str | None = None
```

### `LowPolyFenceFactory`

LowPolyFenceFactory — straight fence segments.

**fence** archetypes: `picket` / `post_and_rail` / `stone_wall` / `wooden_plank`

**Constructor parameters:**
```
factory_seed
fence_archetype: str = 'picket'
length: float | None = None
height: float | None = None
post_spacing: float | None = None
post_radius: float | None = None
n_rails: int | None = None
slat_density: float | None = None
slat_width: float | None = None
slat_thickness: float | None = None
plank_thickness: float | None = None
crenellated_top: bool | None = None
merlon_height: float | None = None
merlon_width: float | None = None
merlon_gap: float | None = None
wall_color: str | None = None
accent_color: str | None = None
```

### `LowPolyFishDryingRackFactory`

LowPolyFishDryingRackFactory — coastal fish-drying rack.

**fish_rack** archetypes: `single_rail` / `triple_tier` / `wide_double`

**Constructor parameters:**
```
factory_seed
fish_rack_archetype: str = 'single_rail'
post_height: float | None = None
span: float | None = None
n_bays: int | None = None
n_rails: int | None = None
fish_per_rail: int | None = None
frame_color: str | None = None
fish_color: str | None = None
```

### `LowPolyForgeFactory`

LowPolyForgeFactory — blacksmith's forge / masonry fire hearth.

**forge** archetypes: `stone_hearth` / `brick_chimney` / `open_field_forge`

**Named presets:** `banked_coals` / `farrier_camp` / `village_smithy` / `workshop_forge`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
forge_archetype: str = 'stone_hearth'
masonry_color: str | None = None
metal_color: str | None = None
flame_color: str | None = None
emit_light: bool = True
light_energy: float | None = None
light_radius: float | None = None
emission_strength: float | None = None
```

### `LowPolyFountainFactory`

LowPolyFountainFactory — stone fountains and water basins.

**fountain** archetypes: `tiered_basin` / `village_basin` / `wall_spout` / `bamboo_basin`

**Named presets:** `plaza_fountain` / `village_well_fountain` / `wall_fountain` / `zen_water_basin`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
fountain_archetype: str = 'tiered_basin'
stone_color: str | None = None
wood_color: str | None = None
```

### `LowPolyFurnitureFactory`

LowPolyFurnitureFactory — wooden furniture for markets, taverns, gardens.

**furniture** archetypes: `bench` / `trestle_table` / `stool` / `market_counter`

**Named presets:** `market_counter` / `round_stool` / `tavern_bench` / `trestle_table`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
furniture_archetype: str = 'bench'
wood_color: str | None = None
frame_color: str | None = None
```

### `LowPolyHaystackFactory`

LowPolyHaystackFactory — pile of hay / harvest-time silhouette.

**haystack** archetypes: `cone` / `rounded_mound` / `stacked_disks`

**Constructor parameters:**
```
factory_seed
haystack_archetype: str = 'cone'
height: float | None = None
radius: float | None = None
polygon_multiplier: float = 1.0
target_edge: float | None = None
n_sides: int | None = None
n_layers: int | None = None
top_offset: tuple[float, float] | None = None
detail_bands: bool | None = None
hay_color: str | None = None
cap_color: str | None = None
```

### `LowPolyHitchingPostFactory`

LowPolyHitchingPostFactory — wild-west / stable hitching rail.

**hitching** archetypes: `single_rail` / `double_rail`

**Constructor parameters:**
```
factory_seed
hitching_archetype: str = 'single_rail'
rail_length: float | None = None
post_height: float | None = None
post_size: float | None = None
rail_height: float | None = None
rail_thickness: float | None = None
n_rails: int | None = None
wood_color: str | None = None
hardware_color: str | None = None
```

### `LowPolyLanternPostFactory`

LowPolyLanternPostFactory — exterior lantern post / brazier.

**lantern** archetypes: `iron_post` / `wooden_post` / `stone_brazier` / `hanging_lantern`

**Constructor parameters:**
```
factory_seed
lantern_archetype: str = 'iron_post'
post_height: float | None = None
post_radius: float | None = None
post_n_sides: int | None = None
post_archetype: str | None = None
lamp_size: float | None = None
lamp_archetype: str | None = None
post_color: str | None = None
lamp_color: str | None = None
emit_light: bool = True
light_energy: float | None = None
light_radius: float | None = None
emission_strength: float = 3.5
```

### `LowPolyLavaFactory`

LowPolyLavaFactory — molten lava features for the volcanic biome.

**lava** archetypes: `lava_pool` / `lava_crack` / `cooled_flow` / `fumarole`

**Named presets:** `basalt_flow` / `fumarole_vent` / `lava_rift` / `magma_pool`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
lava_archetype: str = 'lava_pool'
crust_color: str | None = None
lava_color: str | None = None
emit_light: bool = True
light_energy: float | None = None
light_radius: float | None = None
emission_strength: float | None = None
```

### `LowPolyMarketGoodsFactory`

LowPolyMarketGoodsFactory — wares to fill market stalls and counters.

**goods** archetypes: `produce_pile` / `pottery_stack` / `sack_cluster` / `basket_group`

**Named presets:** `clay_pots` / `fruit_pile` / `grain_sacks` / `woven_baskets`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
goods_archetype: str = 'produce_pile'
base_color: str | None = None
produce_color: str | None = None
accent_color: str | None = None
```

### `LowPolyMarketRugFactory`

LowPolyMarketRugFactory — bazaar ground rug with wares.

**market_rug** archetypes: `plain` / `bordered` / `goods_pile`

**Constructor parameters:**
```
factory_seed
market_rug_archetype: str = 'plain'
length: float | None = None
width: float | None = None
has_border: bool | None = None
n_goods: int | None = None
field_color: str | None = None
accent_color: str | None = None
```

### `LowPolyMushroomFactory`

LowPolyMushroomFactory — fairy / forest / enchanted mushroom prop.

**mushroom** archetypes: `toadstool` / `glowcap` / `cluster`

**Constructor parameters:**
```
factory_seed
mushroom_archetype: str = 'toadstool'
cap_radius: float | None = None
cap_height: float | None = None
stem_radius: float | None = None
stem_height: float | None = None
n_spots: int | None = None
spot_radius: float | None = None
cap_color: str | None = None
stem_color: str | None = None
spot_color: str | None = None
polygon_multiplier: float = 1.0
```

### `LowPolyNaturalArchFactory`

LowPolyNaturalArchFactory — natural rock arches and dramatic landmarks.

**arch** archetypes: `desert_arch` / `sea_arch` / `sea_stack` / `balanced_rock`

**Named presets:** `balanced_rock` / `desert_arch` / `sea_arch` / `sea_stack`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
formation_archetype: str = 'desert_arch'
rock_color: str | None = None
band_color: str | None = None
```

### `LowPolyPagodaFactory`

LowPolyPagodaFactory — East Asian pagodas, temple halls, pavilions.

**pagoda** archetypes: `tiered_pagoda` / `temple_hall` / `garden_pavilion` / `shrine`

**Named presets:** `red_pagoda` / `tea_pavilion` / `temple_hall` / `wayside_shrine`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
pagoda_archetype: str = 'tiered_pagoda'
body_color: str | None = None
roof_color: str | None = None
wood_color: str | None = None
```

### `LowPolyPalmTreeFactory`

LowPolyPalmTreeFactory — proper palm tree.

**palm** archetypes: `coconut` / `date` / `fan_palm` / `oasis_palm` / `coastal_wind_bent` / `young_palm` / `dead_palm` / `grove_palm`

**Named presets:** `dead_dry` / `grove_medium` / `lush_oasis` / `wind_bent_coastal` / `young_cluster`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
palm_archetype: str = 'coconut'
trunk_height: float | None = None
trunk_base_radius: float | None = None
trunk_top_radius: float | None = None
polygon_multiplier: float = 1.0
target_edge: float | None = None
trunk_segments: int | None = None
trunk_n_sides: int | None = None
trunk_curve: float | None = None
trunk_curve_power: float | None = None
n_fronds: int | None = None
frond_length: float | None = None
frond_base_width: float | None = None
frond_segments: int | None = None
frond_droop: float | None = None
frond_pitch: float | None = None
crown_asymmetry: float | None = None
dead_fronds: int | None = None
fruit_count: int | None = None
bark_band_count: int | None = None
trunk_color: str | None = None
frond_color: str | None = None
dry_color: str | None = None
fruit_color: str | None = None
```

### `LowPolyPathFactory`

LowPolyPathFactory — path, road, and stair segments.

**path** archetypes: `dirt_path` / `cobbled_road` / `stone_steps` / `gravel_lane`

**Named presets:** `cobbled_street` / `garden_steps` / `gravel_track` / `village_path`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
path_archetype: str = 'dirt_path'
surface_color: str | None = None
stone_color: str | None = None
edge_color: str | None = None
```

### `LowPolyPeasantFactory`

LowPolyPeasantFactory — tiny readable settlement people.

**peasant** archetypes: `farmer` / `merchant` / `guard` / `child`

**Named presets:** `farmer_hat` / `market_merchant` / `town_guard` / `village_child`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
peasant_archetype: str = 'farmer'
height: float | None = None
body_color: str | None = None
skin_color: str | None = None
accent_color: str | None = None
hat: bool | None = None
tool: str | None = None
```

### `LowPolyReedsFactory`

LowPolyReedsFactory — wetland reeds, cattails, bulrush, papyrus.

**reed** archetypes: `cattail_clump` / `tall_reeds` / `bulrush` / `papyrus`

**Named presets:** `bulrush_clump` / `cattail_stand` / `dry_reeds` / `marsh_reeds` / `papyrus_stand`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
reed_archetype: str = 'cattail_clump'
stem_color: str | None = None
head_color: str | None = None
```

### `LowPolyRockSpireFactory`

LowPolyRockSpireFactory — tall narrow rock columns / spires / mesas.

**spire** archetypes: `needle` / `mesa` / `citadel` / `hoodoo`

**Named presets:** `badlands_hoodoo` / `canyon_needle` / `citadel_column` / `granite_spire` / `monument_mesa`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
spire_archetype: str = 'citadel'
height: float | None = None
base_radius: float | None = None
top_radius: float | None = None
polygon_multiplier: float = 1.0
target_edge: float | None = None
n_sides: int | None = None
n_layers: int | None = None
layer_jitter: float | None = None
taper_curve: float | None = None
has_cap: bool | None = None
cap_radius: float | None = None
cap_height: float | None = None
pointed_top: bool | None = None
rock_color: str | None = None
cap_color: str | None = None
```

### `LowPolyRuinFactory`

LowPolyRuinFactory — modular ruin fragments.

**ruin** archetypes: `broken_walls` / `column_scatter` / `archway` / `obelisk_fragment`

**Named presets:** `broken_arch` / `buried_obelisk` / `collapsed_wall` / `desert_columns`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
ruin_archetype: str = 'broken_walls'
radius: float | None = None
density: float | None = None
stone_color: str | None = None
shadow_color: str | None = None
accent_color: str | None = None
```

### `LowPolyShopfrontFactory`

LowPolyShopfrontFactory — readable street-front shop module.

**shopfront** archetypes: `awning_shop` / `bakery_front` / `apothecary_front` / `closed_shutters`

**Named presets:** `apothecary_green` / `bakery_counter` / `closed_evening` / `red_awning_shop`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
shopfront_archetype: str = 'awning_shop'
width: float | None = None
depth: float | None = None
height: float | None = None
awning: bool | None = None
counter: bool | None = None
goods: int | None = None
wall_color: str = 'stucco'
cloth_color: str = 'accent_red'
wood_color: str = 'wood'
goods_color: str = 'rock_warm'
```

### `LowPolyShrubFactory`

LowPolyShrubFactory — ground vegetation: bushes and ferns.

**shrub** archetypes: `round_bush` / `flowering_bush` / `forest_fern` / `dead_bush` / `desert_scrub`

**Named presets:** `dead_shrub` / `desert_scrub` / `flowering_shrub` / `garden_bush` / `jungle_fern`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
shrub_archetype: str = 'round_bush'
foliage_color: str | None = None
wood_color: str | None = None
flower_color: str | None = None
```

### `LowPolySignageFactory`

LowPolySignageFactory — painted wooden storefront sign.

**signage** archetypes: `hanging_shingle` / `wall_plank` / `free_standing`

**Constructor parameters:**
```
factory_seed
signage_archetype: str = 'hanging_shingle'
post_height: float | None = None
post_size: float | None = None
board_w: float | None = None
board_h: float | None = None
board_thickness: float | None = None
bracket_length: float | None = None
bracket_thickness: float | None = None
wood_color: str | None = None
board_color: str | None = None
accent_color: str | None = None
```

### `LowPolySmithyPropsFactory`

LowPolySmithyPropsFactory — blacksmith yard prop kit.

**smithy_props** archetypes: `anvil` / `quench_trough` / `grindstone` / `tool_rack` / `coal_pile`

**Named presets:** `coke_heap` / `cooling_trough` / `sharpening_wheel` / `smith_tools` / `working_anvil`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
prop_archetype: str = 'anvil'
wood_color: str | None = None
metal_color: str | None = None
stone_color: str | None = None
coal_color: str | None = None
```

### `LowPolyStableYardFactory`

LowPolyStableYardFactory — stable shed / paddock / cart-yard kit.

**stable_yard** archetypes: `open_stable` / `paddock_yard` / `cart_shelter` / `ruined_stable`

**Named presets:** `cart_shelter` / `collapsed_stable` / `fenced_paddock` / `open_three_bay`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
stable_yard_archetype: str = 'open_stable'
width: float | None = None
depth: float | None = None
shed: bool | None = None
fence: bool | None = None
bays: int | None = None
ruined: float | None = None
roof_color: str = 'rock_warm'
wood_color: str = 'wood'
hay_color: str = 'ground_sand'
stone_color: str = 'rock_pale'
```

### `LowPolyStallFactory`

LowPolyStallFactory — marketplace stall with awning canopy.

**stall** archetypes: `open` / `closed_back` / `double`

**Named presets:** `cloth_merchant` / `festival_double` / `fish_market` / `fruit_stand`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
stall_archetype: str = 'open'
length: float | None = None
width: float | None = None
post_height: float | None = None
post_radius: float | None = None
awning_pitch: float | None = None
awning_overhang: float | None = None
has_table: bool | None = None
table_height: float | None = None
table_thickness: float | None = None
has_back_wall: bool | None = None
back_wall_height: float | None = None
goods_count: int | None = None
frame_color: str | None = None
awning_color: str | None = None
table_color: str | None = None
goods_color: str | None = None
awning_alt_color: str | None = None
```

### `LowPolyStoneBridgeFactory`

LowPolyStoneBridgeFactory — stone arch bridge.

**stone_bridge** archetypes: `single_arch` / `double_arch` / `ruined_arch`

**Named presets:** `broken_old` / `village_arch` / `wide_double`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
stone_bridge_archetype: str = 'single_arch'
length: float | None = None
width: float | None = None
deck_z: float | None = None
arch_radius: float | None = None
arch_count: int | None = None
stone_color: str | None = None
cap_color: str | None = None
shadow_color: str | None = None
rubble_color: str | None = None
```

### `LowPolyStoneLanternFactory`

LowPolyStoneLanternFactory — Japanese stone lantern (tōrō).

**lantern** archetypes: `tachi_gata` / `yukimi_gata` / `kasuga` / `oki_gata`

**Named presets:** `ash_temple` / `formal_avenue` / `kasuga_avenue` / `moss_garden` / `oki_garden` / `snow_garden`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
lantern_archetype: str = 'tachi_gata'
n_sides: int = 6
stone_color: str | None = None
glow_color: str | None = None
emit_light: bool = True
light_energy: float = 38.0
light_radius: float = 0.72
emission_strength: float = 2.6
```

### `LowPolyStringLightsFactory`

LowPolyStringLightsFactory — plaza and camp light spans.

**string_light** archetypes: `market_span` / `festival_arc` / `camp_line`

**Named presets:** `camp_rope` / `festival_square` / `market_evening`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
lights_archetype: str = 'market_span'
span: float | None = None
height: float | None = None
post_thickness: float | None = None
bulb_count: int | None = None
sag: float | None = None
wood_color: str = 'wood'
cable_color: str = 'rust_metal'
glow_color: str = 'foliage_lemon'
emit_light: bool = True
light_energy: float | None = None
light_radius: float | None = None
emission_strength: float = 4.6
```

### `LowPolySuspensionBridgeFactory`

LowPolySuspensionBridgeFactory — rope-and-plank bridge.

**bridge** archetypes: `rope_plank` / `cable_suspension` / `chain_walk`

**Named presets:** `canyon_rope_bridge` / `harbor_cable_span` / `mine_chain_walk`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
bridge_archetype: str = 'rope_plank'
length: float | None = None
width: float | None = None
sag: float | None = None
deck_thickness: float | None = None
n_planks: int | None = None
plank_gap: float | None = None
rope_size: float | None = None
n_rope_segments: int | None = None
has_towers: bool | None = None
tower_height: float | None = None
tower_size: float | None = None
has_suspenders: bool | None = None
n_suspenders: int | None = None
cable_extra_height: float | None = None
deck_color: str | None = None
rope_color: str | None = None
tower_color: str | None = None
```

### `LowPolyTavernFactory`

LowPolyTavernFactory — readable inn / tavern landmark.

**tavern** archetypes: `roadside_inn` / `guildhall` / `riverside_pub` / `ruined_inn`

**Named presets:** `guildhall_tavern` / `riverside_pub` / `roadside_inn` / `ruined_inn`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
tavern_archetype: str = 'roadside_inn'
width: float | None = None
depth: float | None = None
wall_height: float | None = None
roof_height: float | None = None
porch: bool | None = None
balcony: bool | None = None
ruined: float | None = None
wall_color: str = 'stucco'
roof_color: str = 'rock_shadow'
wood_color: str = 'wood'
window_color: str = 'sky_cool'
accent_color: str = 'rock_warm'
```

### `LowPolyTombstoneFactory`

LowPolyTombstoneFactory — graveyard tombstones / monuments.

**tombstone** archetypes: `slab` / `cross` / `arch` / `obelisk` / `flat_marker`

**Constructor parameters:**
```
factory_seed
tombstone_archetype: str = 'slab'
height: float | None = None
width: float | None = None
depth: float | None = None
cross_arm_length: float | None = None
cross_arm_height: float | None = None
arch_height: float | None = None
n_arch_segments: int | None = None
taper: float | None = None
lean_angle: float | None = None
stone_color: str | None = None
accent_color: str | None = None
```

### `LowPolyTorchFactory`

LowPolyTorchFactory — wall, pole, and tripod torches.

**torch** archetypes: `pole` / `wall_sconce` / `tripod`

**Named presets:** `camp_tripod` / `castle_wall` / `village_path`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
torch_archetype: str = 'pole'
height: float | None = None
radius: float | None = None
flame_height: float | None = None
flame_radius: float | None = None
wood_color: str = 'wood'
metal_color: str = 'rust_metal'
flame_color: str = 'foliage_amber'
emit_light: bool = True
light_energy: float | None = None
light_radius: float = 1.25
emission_strength: float = 4.2
```

### `LowPolyToriiFactory`

LowPolyToriiFactory — Japanese-style torii gate.

**torii** archetypes: `myojin` / `shinmei` / `ryobu`

**Named presets:** `grand_ryobu` / `night_gate` / `vermilion_shrine` / `weathered_timber`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
torii_archetype: str = 'myojin'
height: float | None = None
width: float | None = None
pillar_radius: float | None = None
pillar_taper: float | None = None
kasagi_height: float | None = None
kasagi_overhang: float | None = None
kasagi_curve_up: float | None = None
nuki_height: float | None = None
nuki_at_pct: float | None = None
has_bracing: bool | None = None
gate_color: str | None = None
accent_color: str | None = None
base_color: str | None = None
```

### `LowPolyTownBlockFactory`

LowPolyTownBlockFactory — compact multi-building street block.

**town_block** archetypes: `market_row` / `stacked_tenement` / `workshop_courtyard` / `stepped_hillside` / `mudbrick_bazaar` / `coastal_row` / `alpine_chalet_row`

**Named presets:** `alpine_chalet_row` / `busy_market_row` / `coastal_clapboard_row` / `mudbrick_bazaar_row` / `stacked_townhouses` / `stepped_hillside_row` / `workshop_court`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
town_block_archetype: str = 'market_row'
width: float | None = None
depth: float | None = None
module_count: int | None = None
storeys: int | None = None
awnings: bool | None = None
balconies: bool | None = None
stairs: bool | None = None
clutter: int | None = None
wall_color: str = 'stucco'
roof_color: str = 'rock_shadow'
wood_color: str = 'wood'
window_color: str = 'sky_cool'
accent_color: str = 'accent_red'
stone_color: str = 'rock_pale'
window_glow: bool = False
window_glow_color: str = 'sky_warm'
window_emission_strength: float = 1.15
```

### `LowPolyTownGateFactory`

LowPolyTownGateFactory — readable settlement entrance.

**town_gate** archetypes: `timber_palisade` / `stone_arch` / `watch_gate` / `ruined_gate`

**Named presets:** `ruined_entry` / `stone_road_arch` / `timber_palisade` / `watch_gate`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
town_gate_archetype: str = 'timber_palisade'
span: float | None = None
height: float | None = None
width: float | None = None
roof: bool | None = None
stone: bool | None = None
ruined: float | None = None
stone_color: str = 'rock_pale'
wood_color: str = 'wood'
metal_color: str = 'rust_metal'
```

### `NativeLowPolyTreeFactory`

NativeLowPolyTreeFactory — Sapling-derived native low-poly tree.

**trunk** archetypes: `straight` / `no_branch` / `curved`

**Named presets:** `ancient_pine` / `baobab_savanna` / `bare_winter` / `columnar_cypress` / `dead_pine` / `flowering_broadleaf` / `low_scrub` / `lush_pine` / `round_oak` / `thin_sapling` / `umbrella_acacia` / `weeping_willow` / `wind_bent_headland` / `young_pine`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
archetype: str = 'pine'
trunk_archetype: str = 'straight'
trunk_curve_amplitude: float = 0.5
trunk_height: float = 6.0
polygon_multiplier: float = 1.0
target_edge: float | None = None
trunk_segments: int | None = None
trunk_radius_base: float = 0.18
trunk_radius_top: float = 0.06
n_branch_layers: int = 6
branches_per_layer: tuple[int, int] = (3, 5)
branch_length: tuple[float, float] = (0.7, 1.6)
branch_droop: tuple[float, float] = (0.1, 0.55)
branch_taper: float = 0.5
branch_lower_z_fraction: float | None = None
crown_z_fraction: float = 0.45
foliage_archetype: str = 'tiered_cones'
foliage_layers: int = 4
foliage_radius: float = 1.6
foliage_height: float = 3.0
foliage_icosphere_subdivisions: int | None = None
smooth_foliage: bool = False
target_polys: int | None = None
trunk_color: str | None = 'rock_shadow'
palette_color: str | None = 'foliage_pine'
```

### `LowPolyTumbleweedFactory`

LowPolyTumbleweedFactory — round tumbling brush.

**tumbleweed** archetypes: `dry` / `dense` / `sparse` / `green`

**Constructor parameters:**
```
factory_seed
tumbleweed_archetype: str = 'dry'
radius: float | None = None
squash: float | None = None
n_clumps_range: tuple[int, int] | None = None
clump_radius_fraction_range: tuple[float, float] | None = None
offset_fraction: float | None = None
icosphere_subdivisions: int | None = None
accent_fraction: float | None = None
body_color: str | None = None
accent_color: str | None = None
```

### `LowPolyVolcanicRockFactory`

LowPolyVolcanicRockFactory — cooled volcanic rock for the volcanic biome.

**volcanic_rock** archetypes: `basalt_column` / `obsidian_cluster` / `cinder_cone` / `cracked_boulder`

**Named presets:** `basalt_columns` / `lava_boulder` / `obsidian_shards` / `scoria_cone`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
volcanic_archetype: str = 'basalt_column'
rock_color: str | None = None
accent_color: str | None = None
```

### `LowPolyWagonFactory`

LowPolyWagonFactory — covered prairie schooner / buckboard / handcart.

**wagon** archetypes: `prairie_schooner` / `buckboard` / `handcart`

**Named presets:** `farm_buckboard` / `market_handcart` / `settler_schooner`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
wagon_archetype: str = 'prairie_schooner'
length: float | None = None
width: float | None = None
body_height: float | None = None
polygon_multiplier: float = 1.0
target_edge: float | None = None
n_axles: int | None = None
wheel_radius: float | None = None
wheel_thickness: float | None = None
n_wheel_sides: int | None = None
has_cover: bool | None = None
cover_n_arc: int | None = None
cover_n_along: int | None = None
has_tongue: bool | None = None
tongue_length: float | None = None
has_handles: bool | None = None
handle_length: float | None = None
body_color: str | None = None
wheel_color: str | None = None
cover_color: str | None = None
```

### `LowPolyWatchtowerFactory`

LowPolyWatchtowerFactory — freestanding stone tower with parapet.

**watchtower** archetypes: `round_stone` / `square_keep`

**Named presets:** `ancient_ruin` / `lighthouse` / `siege_tower`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
watchtower_archetype: str = 'round_stone'
shaft_radius: float | None = None
shaft_height: float | None = None
n_sides: int | None = None
crenel_height: float | None = None
crenel_count: int | None = None
roof_height: float | None = None
roof_overhang: float | None = None
door_width: float | None = None
door_height: float | None = None
plinth_height: float | None = None
plinth_overhang: float | None = None
band_height: float | None = None
window_count: int | None = None
window_width: float | None = None
window_height: float | None = None
stone_color: str | None = None
wood_color: str | None = None
roof_color: str | None = None
trim_color: str | None = None
```

### `LowPolyWaterSurfaceFactory`

LowPolyWaterSurfaceFactory — flat water plane for streams / lakes / puddles.

**water** archetypes: `still_lake` / `stream` / `puddle`

**Constructor parameters:**
```
factory_seed
water_archetype: str = 'still_lake'
extent: tuple[float, float] | None = None
length: float | None = None
width: float | None = None
edge_lift: float | None = None
edge_jitter: float | None = None
polygon_multiplier: float = 1.0
target_edge: float | None = None
n_segments: int | None = None
water_color: str | None = None
```

### `LowPolyWaterTowerFactory`

LowPolyWaterTowerFactory — frontier water tower on stilts.

**tower** archetypes: `frontier_stilts` / `rail_depot`

**Constructor parameters:**
```
factory_seed
tower_archetype: str = 'frontier_stilts'
leg_height: float | None = None
leg_size: float | None = None
leg_spread: float | None = None
tank_radius: float | None = None
tank_height: float | None = None
tank_n_sides: int | None = None
roof_height: float | None = None
n_braces: int | None = None
brace_size: float | None = None
leg_color: str | None = None
tank_color: str | None = None
roof_color: str | None = None
```

### `LowPolyWaterfallFactory`

LowPolyWaterfallFactory — waterfalls and water sources for steep terrain.

**waterfall** archetypes: `cliff_fall` / `cascade` / `multi_tier` / `spring_source`

**Named presets:** `cliff_waterfall` / `mountain_spring` / `rocky_cascade` / `tiered_falls`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
waterfall_archetype: str = 'cliff_fall'
rock_color: str | None = None
water_color: str | None = None
```

### `LowPolyWatermillFactory`

LowPolyWatermillFactory — riverside watermill landmark.

**watermill** archetypes: `timber_river` / `stone_river` / `half_timber_mill`

**Named presets:** `half_timber` / `stone_river` / `timber_river`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
watermill_archetype: str = 'timber_river'
width: float | None = None
depth: float | None = None
wall_height: float | None = None
roof_height: float | None = None
wheel_radius: float | None = None
wall_color: str | None = None
roof_color: str | None = None
wheel_color: str | None = None
trough_color: str | None = None
window_color: str | None = None
```

### `LowPolyWellFactory`

LowPolyWellFactory — village / farmstead well.

**well** archetypes: `stone_round` / `wooden_box`

**Named presets:** `desert_well` / `farm_windlass` / `old_stone_well` / `village_well`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
well_archetype: str = 'stone_round'
radius: float | None = None
wall_height: float | None = None
polygon_multiplier: float = 1.0
target_edge: float | None = None
n_sides: int | None = None
has_roof: bool | None = None
roof_height: float | None = None
has_bucket: bool | None = None
bucket_size: float | None = None
stone_color: str | None = None
wood_color: str | None = None
roof_color: str | None = None
```

### `LowPolyWindmillFactory`

LowPolyWindmillFactory — windmill / windpump landmark.

**windmill** archetypes: `dutch` / `western_pump` / `stone_mill`

**Named presets:** `desert_mill` / `dutch_grain` / `harbor_red_cap` / `old_stone_mill` / `prairie_pump`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
windmill_archetype: str = 'dutch'
tower_height: float | None = None
tower_top_radius: float | None = None
tower_bottom_radius: float | None = None
polygon_multiplier: float = 1.0
target_edge: float | None = None
n_tower_sides: int | None = None
n_blades: int | None = None
blade_length: float | None = None
blade_width: float | None = None
blade_thickness: float | None = None
blade_phase: float | None = None
hub_radius: float | None = None
has_dome: bool | None = None
dome_height: float | None = None
tower_color: str | None = None
blade_color: str | None = None
roof_color: str | None = None
sail_color: str | None = None
```

### `LowPolyZenGardenGateFactory`

LowPolyZenGardenGateFactory — small traditional wooden garden gate.

**gate** archetypes: `roofed_wood` / `simple_post` / `hagi_arch`

**Named presets:** `festival_gate` / `mountain_path` / `tea_house` / `weathered_temple`
Use a preset when the prompt asks for a coherent look (for example weathered, coastal, dead, young, lush) instead of hand-tuning raw dimensions.

**Constructor parameters:**
```
factory_seed
zen_gate_archetype: str = 'roofed_wood'
span: float | None = None
post_height: float | None = None
post_thickness: float | None = None
beam_thickness: float | None = None
roof_overhang: float | None = None
roof_pitch: float | None = None
wing_length: float | None = None
wing_height: float | None = None
wood_color: str | None = None
roof_color: str | None = None
base_color: str | None = None
```


---

Generated automatically by `infinigen.maquette.pipeline.factories_guide`.

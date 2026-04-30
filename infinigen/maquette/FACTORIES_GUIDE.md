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

rng = random.Random(<seed>)

# 1. Wipe scene + create displaced ground via the terrain helper. NEVER
# build the ground as a bare plane — pick a style preset that matches
# the prompt's mood (flat / rolling / hilly / alpine / dunes). The helper
# returns a height sampler used when placing every other object.
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
terrain = make_terrain(
    style="<flat|rolling|hilly|alpine|dunes>",
    size=40,                                # half-width in BU
    base_color=(<R>, <G>, <B>, 1.0),
    seed=<scene seed>,
)

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
prop shots. For oblique-aerial scene views the camera at `(20, -22, 13)`
looking at `(0, 0, 1.5)` is a good default for a 16-30m wide scene.

---

## Factories


### `LowPolyBannerFactory`

LowPolyBannerFactory — hanging cloth banner / flag.

**banner** archetypes: `hanging` / `flag_pole` / `horizontal`

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

### `LowPolyBoatFactory`

LowPolyBoatFactory — rowboat / dinghy / pirate brig.

**boat** archetypes: `rowboat` / `dinghy` / `pirate_brig`

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
```

### `LowPolyHouseFactory`

LowPolyHouseFactory — Sapling-style native low-poly building.

**roof** archetypes: `gabled` / `hipped` / `flat`
**building** archetypes: `cottage` / `barn` / `tower` / `cabin` / `longhouse`

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
wall_color: str | None = 'rock_pale'
roof_color: str | None = 'rock_shadow'
accent_color: str | None = 'accent_red'
foundation_color: str | None = 'rock_shadow'
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

**cactus** archetypes: `saguaro` / `barrel`

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
hay_color: str | None = None
cap_color: str | None = None
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
```

### `LowPolyPalmTreeFactory`

LowPolyPalmTreeFactory — proper palm tree.

**palm** archetypes: `coconut` / `date` / `fan_palm`

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
trunk_color: str | None = None
frond_color: str | None = None
```

### `LowPolyRockSpireFactory`

LowPolyRockSpireFactory — tall narrow rock columns / spires / mesas.

**spire** archetypes: `needle` / `mesa` / `citadel` / `hoodoo`

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

### `LowPolyStallFactory`

LowPolyStallFactory — marketplace stall with awning canopy.

**stall** archetypes: `open` / `closed_back` / `double`

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
frame_color: str | None = None
awning_color: str | None = None
table_color: str | None = None
```

### `LowPolySuspensionBridgeFactory`

LowPolySuspensionBridgeFactory — rope-and-plank bridge.

**bridge** archetypes: `rope_plank` / `cable_suspension` / `chain_walk`

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

### `LowPolyToriiFactory`

LowPolyToriiFactory — Japanese-style torii gate.

**torii** archetypes: `myojin` / `shinmei` / `ryobu`

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
```

### `NativeLowPolyTreeFactory`

NativeLowPolyTreeFactory — Sapling-derived native low-poly tree.

**trunk** archetypes: `straight` / `no_branch` / `curved`

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
foliage_archetype: str = 'pine_cone'
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

### `LowPolyWagonFactory`

LowPolyWagonFactory — covered prairie schooner / buckboard / handcart.

**wagon** archetypes: `prairie_schooner` / `buckboard` / `handcart`

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

### `LowPolyWellFactory`

LowPolyWellFactory — village / farmstead well.

**well** archetypes: `stone_round` / `wooden_box`

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

LowPolyWindmillFactory — windmill / windpump silhouette.

**windmill** archetypes: `dutch` / `western_pump` / `stone_mill`

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
```


---

Generated automatically by `infinigen.maquette.pipeline.factories_guide`.

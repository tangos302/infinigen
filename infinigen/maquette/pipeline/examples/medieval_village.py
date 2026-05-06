"""Canonical reference build script — "medieval village by a stream".

This is what the pipeline expects Claude to produce. Path discipline:
all outputs go to $MAQUETTE_OUT_DIR (set by the pipeline runner). Render
filename is always scene.png; blend is scene.blend.

The pipeline ships this file to Claude as one example of what a complete
build script looks like, so the reference here matters — keep it
representative of "good" Maquette scene composition (proper layout
patterns, varied props, golden-hour palette).
"""
import math
import os
import random
import sys
from pathlib import Path

INFINIGEN_FORK = Path("/home/tang/songe/_artifacts/maquette/infinigen-fork")
if str(INFINIGEN_FORK) not in sys.path:
    sys.path.insert(0, str(INFINIGEN_FORK))

import bpy
from mathutils import Vector

from infinigen.maquette.factories.boulder import LowPolyBoulderFactory
from infinigen.maquette.factories.native.barrel import LowPolyBarrelFactory
from infinigen.maquette.factories.native.building import LowPolyHouseFactory
from infinigen.maquette.factories.native.crate import LowPolyCrateFactory
from infinigen.maquette.factories.native.fence import LowPolyFenceFactory
from infinigen.maquette.factories.native.lantern_post import LowPolyLanternPostFactory
from infinigen.maquette.factories.native.tree import NativeLowPolyTreeFactory
from infinigen.maquette.factories.native.water_surface import LowPolyWaterSurfaceFactory
from infinigen.maquette.runtime.checkpoint import checkpoint
from infinigen.maquette.runtime.terrain import make_terrain


rng = random.Random(424242)


def place(obj, x, y, z=None, rot_z=0):
    """Default z=None means "let the terrain decide" — sample the
    surface at (x, y). Pass an explicit z for water surfaces (sit
    them slightly below terrain) or for objects that should float."""
    if z is None:
        z = terrain.height_at(x, y)
    obj.location = (x, y, z)
    obj.rotation_euler.z = rot_z


# 1. Wipe + ground — `rolling` for a pastoral village by a stream.
# The terrain helper returns the ground object AND a height sampler;
# every place() below uses `terrain.height_at(x, y)` so objects sit on
# the actual surface instead of clipping into hills.
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
terrain = make_terrain(
    style="rolling",          # pastoral hills; pick alpine/hilly/dunes/flat per-prompt
    size=80,                  # world is -80..+80 BU on each axis (160 BU wide)
    base_color=(0.55, 0.58, 0.40, 1.0),
    seed=424242,
)

checkpoint("terrain")  # ground is in place — frontend hot-swaps OBJ

# 2. Stream cuts west-east through the scene. Place water at a slight
# offset below the local terrain height so it sits in a valley channel.
stream_y = 5
stream_z = terrain.height_at(0, stream_y) - 0.3
stream = LowPolyWaterSurfaceFactory(
    factory_seed=4242, water_archetype="stream", length=40, width=2.4,
).create_asset(placeholder=None)
place(stream, 0, stream_y, stream_z, math.radians(8))

# Lake bulge at the east end
lake_x, lake_y = 16, 7
lake_z = terrain.height_at(lake_x, lake_y) - 0.3
lake = LowPolyWaterSurfaceFactory(
    factory_seed=4243, water_archetype="still_lake", extent=(7, 5),
).create_asset(placeholder=None)
place(lake, lake_x, lake_y, lake_z)

checkpoint("water")  # streams + lake — water reads in the viewer

# 3. Houses south of the stream — building cluster pattern
HOUSES = [
    (101, "cottage",   -8,  -4, math.radians(15)),
    (102, "longhouse",  8,  -3, math.radians(-15)),
    (103, "cabin",     -6,   1, math.radians(-30)),
    (104, "cottage",    7,   1, math.radians(160)),
    (105, "tower",      0, -10, 0),
]
for seed, arch, x, y, rot in HOUSES:
    f = LowPolyHouseFactory(factory_seed=seed, building_archetype=arch)
    obj = f.create_asset(placeholder=None)
    place(obj, x, y, rot_z=rot)  # z defaults to terrain.height_at(x, y)

checkpoint("structures")  # village houses pop in

# 4. Forest ring (varied tree archetypes for visual variety)
TREES = [
    ("pine_cone", "straight"),
    ("round_ball", "curved"),
    ("umbrella", "straight"),
    ("bush", "curved"),
]
# (`"crystal"` is reserved for explicit fantasy/enchanted scenes — its
# faceted icosphere reads as broken texture against natural foliage.)
for i in range(22):
    a = i / 22.0 * 2 * math.pi + rng.uniform(-0.1, 0.1)
    r = rng.uniform(15, 19)
    fx, fy = math.cos(a) * r, math.sin(a) * r
    if abs(fy - 5) < 2.5 and -22 < fx < 22:   # avoid trees in the stream
        continue
    foliage, trunk = rng.choice(TREES)
    tf = NativeLowPolyTreeFactory(
        factory_seed=200 + i, foliage_archetype=foliage, trunk_archetype=trunk
    )
    obj = tf.create_asset(placeholder=None)
    s = rng.uniform(0.85, 1.2)
    obj.scale = (s, s, s)
    place(obj, fx, fy)

checkpoint("foliage")  # forest ring around the village

# 5. Fences (4 archetypes for variety)
def add_fence(seed, archetype, x, y, length, rot_z=0):
    f = LowPolyFenceFactory(factory_seed=seed, fence_archetype=archetype, length=length)
    obj = f.create_asset(placeholder=None)
    place(obj, x, y, rot_z=rot_z)  # ride the terrain surface

add_fence(401, "picket", x=-9, y=-1, length=4.5, rot_z=0)
add_fence(402, "post_and_rail", x=10, y=-6, length=5.5, rot_z=math.radians(90))
add_fence(403, "stone_wall", x=-3, y=-4.5, length=6.0, rot_z=0)
add_fence(404, "wooden_plank", x=-6, y=2.5, length=4.5, rot_z=0)

# 6. Lanterns — village square + by houses
def add_lantern(seed, archetype, x, y):
    f = LowPolyLanternPostFactory(factory_seed=seed, lantern_archetype=archetype)
    place(f.create_asset(placeholder=None), x, y)

add_lantern(501, "iron_post", 2.5, -3.5)
add_lantern(502, "iron_post", -2.5, -3.5)
add_lantern(503, "stone_brazier", 0, -2)

# 7. Yard scatter (barrels + crates near doors)
def add_barrel(seed, x, y, side=False):
    f = LowPolyBarrelFactory(factory_seed=seed, barrel_archetype="wooden", on_its_side=side)
    obj = f.create_asset(placeholder=None)
    obj.location.x += x
    obj.location.y += y

def add_crate(seed, archetype, x, y):
    f = LowPolyCrateFactory(factory_seed=seed, crate_archetype=archetype)
    place(f.create_asset(placeholder=None), x, y)

add_barrel(601, -6.5, -4)
add_barrel(602, -6.5, -4.8, side=True)
add_barrel(603, 6.3, -3)
add_crate(604, "wooden", 6.3, -3.7)
add_crate(605, "fragile", 7.0, -3.7)

# 8. Riprap — boulders along the stream banks
for i in range(10):
    side = rng.choice([1, -1])
    bx = rng.uniform(-15, 15)
    by = 5 + side * rng.uniform(1.4, 1.8)
    f = LowPolyBoulderFactory(factory_seed=700 + i)
    obj = f.spawn_asset(i=700 + i, loc=(bx, by, 0))
    obj.scale = (rng.uniform(0.4, 0.8),) * 3

checkpoint("props")  # fences, lanterns, barrels, crates, riprap — last geometry pass

# 9. Camera + golden-hour sun + warm sky.
# Camera is auto-placed by the runtime helper. ALWAYS pass `terrain=terrain`
# so the camera target Z is sampled from the actual ground (not z=0).
# Real eroded scenes also pass `composition=<your Composition>` so the
# helper picks lake-foreground / ridge-perpendicular framing. Flat
# make_terrain example here uses None for composition.
from infinigen.maquette.runtime.camera import place_scene_camera
place_scene_camera(None, terrain_size=80, terrain=terrain)

bpy.ops.object.light_add(type="SUN", location=(8, -5, 12))
sun = bpy.context.active_object
sun.data.energy = 2.5
sun.data.color = (1.0, 0.86, 0.65)
sun.rotation_euler = (math.radians(60), math.radians(20), math.radians(60))

w = bpy.context.scene.world
w.use_nodes = True
w.node_tree.nodes.clear()
out = w.node_tree.nodes.new("ShaderNodeOutputWorld")
bg = w.node_tree.nodes.new("ShaderNodeBackground")
bg.inputs[0].default_value = (0.86, 0.78, 0.62, 1.0)
bg.inputs[1].default_value = 1.0
w.node_tree.links.new(bg.outputs[0], out.inputs[0])

checkpoint("final")  # final geometry — Cycles render is just lighting

# 10. Render + save (paths from MAQUETTE_OUT_DIR)
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

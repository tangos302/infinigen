"""Multi-biome reference build — "coastal archipelago at golden hour".

Demonstrates `make_multi_biome_terrain` for prompts that mix ground
types: a grassy headland to the west, a sandy beach in the middle, an
ocean side to the east with a few low islands. Heights blend smoothly;
colors snap per-face by dominant zone (matches the faceted low-poly
look). Pair with `LowPolyWaterSurfaceFactory(water_archetype="ocean")`
for the water plane on top.

Use this as the pattern when a prompt asks for biome variety on a single
map — "grassland → desert → archipelago", "forest meets coast",
"alpine valley meets tundra plateau", etc.
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
from infinigen.maquette.factories.native.tree import NativeLowPolyTreeFactory
from infinigen.maquette.factories.native.water_surface import LowPolyWaterSurfaceFactory
from infinigen.maquette.runtime.checkpoint import checkpoint
from infinigen.maquette.runtime.terrain import make_multi_biome_terrain


rng = random.Random(737373)


def place(obj, x, y, z=None, rot_z=0):
    if z is None:
        z = terrain.height_at(x, y)
    obj.location = (x, y, z)
    obj.rotation_euler.z = rot_z


# 1. Wipe + multi-biome ground. Three zones: grass headland on the
# southwest, sandy beach across the middle, ocean side on the northeast.
# Radii overlap a bit so heights blend smoothly across boundaries.
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)

terrain = make_multi_biome_terrain(
    size=80,
    seed=737373,
    zones=[
        ("rolling", -32, -18, 28),   # grassy headland on the southwest
        ("dunes",     0,   0, 22),   # sandy beach through the centre
        ("flat",     32,  22, 32),   # ocean side on the northeast
    ],
)

checkpoint("terrain")

# 2. Ocean plane covering the eastern half. Sit it just below the
# blended terrain height at the ocean centre so it reads as the local
# water level. Islands on the ocean side rise above it.
ocean_cx, ocean_cy = 28, 22
ocean_z = terrain.height_at(ocean_cx, ocean_cy) - 0.15
ocean = LowPolyWaterSurfaceFactory(
    factory_seed=7301, water_archetype="ocean", extent=(36, 28),
).create_asset(placeholder=None)
place(ocean, ocean_cx, ocean_cy, ocean_z)

checkpoint("water")

# 3. Trees only on the grassy headland — sample placements within the
# rolling zone and skip points that drift too close to the beach.
for i in range(14):
    a = i / 14.0 * 2 * math.pi + rng.uniform(-0.2, 0.2)
    r = rng.uniform(8, 18)
    fx = -32 + math.cos(a) * r
    fy = -18 + math.sin(a) * r
    if -10 < fx < 18 and -8 < fy < 12:
        # Inside the dune/beach band — skip, no trees on sand.
        continue
    foliage = rng.choice(["pine_cone", "round_ball", "umbrella", "bush"])
    trunk = rng.choice(["straight", "curved"])
    tf = NativeLowPolyTreeFactory(
        factory_seed=300 + i, foliage_archetype=foliage, trunk_archetype=trunk,
    )
    obj = tf.create_asset(placeholder=None)
    s = rng.uniform(0.85, 1.15)
    obj.scale = (s, s, s)
    place(obj, fx, fy)

# 4. Boulders along the sandy stretch (driftwood-ish riprap on the beach).
for i in range(8):
    bx = rng.uniform(-12, 14)
    by = rng.uniform(-6, 6)
    f = LowPolyBoulderFactory(factory_seed=400 + i, palette_color="rock_pale")
    obj = f.spawn_asset(i=400 + i, loc=(bx, by, terrain.height_at(bx, by)))
    obj.scale = (rng.uniform(0.4, 0.7),) * 3

# 5. Islands on the ocean side — tiny boulder clusters poking above the
# water plane. Place them at z slightly above ocean_z so they read.
for i in range(5):
    ix = ocean_cx + rng.uniform(-12, 12)
    iy = ocean_cy + rng.uniform(-10, 10)
    f = LowPolyBoulderFactory(factory_seed=500 + i, palette_color="rock_warm")
    obj = f.spawn_asset(i=500 + i, loc=(ix, iy, ocean_z + 0.4))
    s = rng.uniform(0.6, 1.1)
    obj.scale = (s, s, s)

checkpoint("props")

# 6. Camera + golden-hour sun + warm sky. Camera sits to the southwest
# so the headland → beach → ocean gradient sweeps left-to-right in frame.
bpy.ops.object.camera_add(location=(-46, -52, 28))
cam = bpy.context.active_object
target = Vector((10, 10, 2))
cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
cam.data.lens = 35
bpy.context.scene.camera = cam

bpy.ops.object.light_add(type="SUN", location=(20, -10, 14))
sun = bpy.context.active_object
sun.data.energy = 2.5
sun.data.color = (1.0, 0.86, 0.65)
sun.rotation_euler = (math.radians(55), math.radians(15), math.radians(40))

w = bpy.context.scene.world
w.use_nodes = True
w.node_tree.nodes.clear()
out = w.node_tree.nodes.new("ShaderNodeOutputWorld")
bg = w.node_tree.nodes.new("ShaderNodeBackground")
bg.inputs[0].default_value = (0.86, 0.78, 0.62, 1.0)
bg.inputs[1].default_value = 1.0
w.node_tree.links.new(bg.outputs[0], out.inputs[0])

checkpoint("final")

# 7. Render + save
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

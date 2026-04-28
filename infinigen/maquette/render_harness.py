"""Side-by-side render harness for Maquette factory development.

Spawns one asset per upstream factory + one per Maquette wrapper, lays
them out in a row, points a camera at them, and renders with Cycles
CPU. Used as the visual smoke test for every new factory wrapper:
"did we keep the silhouette while losing 99.9% of the polys?"

The harness deliberately uses a simple grey world + a single sun light
so the render reflects the GEOMETRY, not the material. Material
treatment will be a separate concern (see palette.py).

Typical usage from inside Blender (e.g. via headless MCP)::

    from infinigen.assets.objects.rocks.boulder import BoulderFactory
    from infinigen.maquette.factories import LowPolyBoulderFactory
    from infinigen.maquette.render_harness import compare_render

    compare_render(
        BoulderFactory,
        LowPolyBoulderFactory,
        seeds=[1, 2, 3],
        out_path="/tmp/compare.png",
        maquette_kwargs={"target_face_size": 0.15},
    )
"""

from __future__ import annotations

import math
from typing import Iterable

import bpy
from mathutils import Vector


def _wipe_scene():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)


def _setup_world_lighting():
    """Flat grey world + single warm sun. Materials-out-of-scope friendly."""
    bpy.ops.object.light_add(type="SUN", location=(3, -2, 6))
    sun = bpy.context.active_object
    sun.data.energy = 4.0
    sun.data.color = (1.0, 0.96, 0.88)
    sun.rotation_euler = (math.radians(45), math.radians(15), math.radians(70))

    bpy.ops.mesh.primitive_plane_add(size=80, location=(0, 0, -0.05))

    w = bpy.context.scene.world
    w.use_nodes = True
    w.node_tree.nodes.clear()
    out = w.node_tree.nodes.new("ShaderNodeOutputWorld")
    bg = w.node_tree.nodes.new("ShaderNodeBackground")
    bg.inputs[0].default_value = (0.78, 0.82, 0.88, 1.0)
    bg.inputs[1].default_value = 1.0
    w.node_tree.links.new(bg.outputs[0], out.inputs[0])


def _frame_camera(targets: list[bpy.types.Object]):
    """Place camera so all `targets` fit in frame. Head-on view from -Y to
    preserve the silhouette of every asset and not foreshorten the row."""
    if not targets:
        return
    xs = [o.location.x for o in targets]
    zs = [o.location.z + o.dimensions.z * 0.5 for o in targets]
    cx = (min(xs) + max(xs)) / 2.0
    cz = (min(zs) + max(zs)) / 2.0
    span_x = max(xs) - min(xs)
    span_z = max(zs) - min(zs)
    # Pull back enough that both rows are in frame. Head-on (no tilt
    # downward) so both rows read cleanly.
    distance = max(span_x, 4.0) * 1.2 + 2.0
    cam_loc = (cx, -distance, cz)
    bpy.ops.object.camera_add(location=cam_loc)
    cam = bpy.context.active_object
    target = Vector((cx, 0, cz))
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
    cam.data.lens = 50
    bpy.context.scene.camera = cam


def _spawn(factory_cls, seed: int, location, factory_kwargs=None, name_prefix=""):
    factory_kwargs = factory_kwargs or {}
    factory = factory_cls(factory_seed=seed, **factory_kwargs)
    obj = factory.spawn_asset(0)
    obj.location = Vector(location)
    if name_prefix:
        obj.name = f"{name_prefix}_seed{seed}"
    return obj


def compare_render(
    upstream_factory_cls,
    maquette_factory_cls,
    seeds: Iterable[int],
    out_path: str,
    maquette_kwargs: dict | None = None,
    upstream_kwargs: dict | None = None,
    spacing: float = 3.5,
    resolution: tuple[int, int] = (1400, 600),
    samples: int = 16,
) -> dict:
    """Render upstream and Maquette versions of `factory_cls` side-by-side.

    Layout: seeds run along +X. For each seed, upstream is at z=0 row
    front, maquette is at z=0 row back (offset on +Y so the camera sees
    both rows separated front-to-back).

    Returns a stats dict: {seed: {upstream: {polys, verts}, maquette: {...}}}
    so callers can log or assert polycount expectations.
    """
    seeds = list(seeds)
    upstream_kwargs = upstream_kwargs or {}
    maquette_kwargs = maquette_kwargs or {}

    _wipe_scene()
    _setup_world_lighting()

    stats: dict = {}
    spawned = []
    # Layout: 5 columns × 2 rows. Upstream on top (elevated), Maquette on
    # bottom (ground level). Camera shoots head-on so both rows show without
    # one occluding the other.
    upstream_z = max(spacing * 0.7, 1.5)  # lift upstream above ground row
    for col, s in enumerate(seeds):
        x = (col - (len(seeds) - 1) / 2) * spacing
        up = _spawn(
            upstream_factory_cls, s, (x, 0, upstream_z),
            factory_kwargs=upstream_kwargs, name_prefix="Upstream",
        )
        mq = _spawn(
            maquette_factory_cls, s, (x, 0, 0),
            factory_kwargs=maquette_kwargs, name_prefix="Maquette",
        )
        spawned.extend([up, mq])
        stats[s] = {
            "upstream": {"polys": len(up.data.polygons), "verts": len(up.data.vertices)},
            "maquette": {"polys": len(mq.data.polygons), "verts": len(mq.data.vertices)},
        }

    _frame_camera(spawned)

    scn = bpy.context.scene
    scn.render.engine = "CYCLES"
    scn.cycles.device = "CPU"
    scn.cycles.samples = samples
    scn.render.resolution_x = resolution[0]
    scn.render.resolution_y = resolution[1]
    scn.render.image_settings.file_format = "PNG"
    scn.render.filepath = out_path
    bpy.ops.render.render(write_still=True)

    return stats

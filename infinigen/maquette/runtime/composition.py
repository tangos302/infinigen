"""Composition helpers for build scripts: atmospheric haze and
walkable-surface markup.

These are stylistic / forward-compatibility additions the LLM build
scripts pull in via top-level imports:

    from infinigen.maquette.runtime.composition import (
        add_aerial_perspective,
        mark_walkable,
    )

Each helper is a single call from the build script. Failures are
non-fatal — they raise but with a short, build-script-friendly
message; if the runtime context is wrong (no scene, no objects) they
silently skip rather than hard-crashing the render.
"""

from __future__ import annotations

import math


def add_aerial_perspective(
    strength: float = 0.6,
    *,
    color: tuple[float, float, float] | None = None,
    falloff: float = 0.012,
    box_size: float = 280.0,
    box_center: tuple[float, float, float] = (0.0, 0.0, 30.0),
) -> None:
    """Spawn a bounded volume cube around the scene so Cycles renders
    sun-lit atmospheric haze without absorbing the sun itself.

    Why a *bounded* cube and not a world-output volume? A world volume
    fills infinite space — sun light (treated as parallel rays from
    infinity) gets absorbed over thousands of BU before ever reaching
    the terrain, blacking the scene out. A bounded cube only attenuates
    rays *inside* its walls, so sun reaches terrain with mild
    attenuation (~15-25 % at default density) and the volume scatters
    sun rays into the camera as golden-hour haze + faint god rays.

    The cube has a Transparent BSDF on its surface (invisible from
    camera, casts no shadow) and Volume Scatter + Volume Absorption on
    its volume output. Camera must be inside the cube — default size
    280 BU centered at (0, 0, 30) safely encloses the standard terrain
    bounds (~120 BU) and a third-person camera (~50-100 BU out).

    Parameters
    ----------
    strength : float
        Density multiplier. 0.3 = subtle haze, 0.6 = clear atmospheric
        perspective (default), 1.0 = heavy fog.
    color : tuple[float, float, float] | None
        Scatter tint. None → warm near-white. Pass ``(1.0, 0.85, 0.7)``
        for golden hour or ``(0.95, 0.7, 0.8)`` for dusk magenta.
    falloff : float
        Reserved (no-op for now); future use is per-height density via
        Texture Coordinate → ColorRamp on the Density socket.
    box_size : float
        Cube edge length in BU. 280 BU comfortably encloses a 120 BU
        terrain plus camera. Bump to 360+ for XL maps.
    box_center : tuple[float, float, float]
        Cube center. Default puts the cube straddling z=-110..170 so
        terrain valleys and sky are both inside.

    Notes
    -----
    Re-callable: replaces any prior `songe_aerial_box` cube.
    """
    import bpy

    scene = bpy.context.scene
    if scene is None:
        return

    # Remove any prior aerial-perspective cube so re-calls don't stack.
    for obj in list(scene.objects):
        if obj.get("songe_aerial_box") == 1:
            bpy.data.objects.remove(obj, do_unlink=True)
    for mat in list(bpy.data.materials):
        if mat.get("songe_aerial_box") == 1 and mat.users == 0:
            bpy.data.materials.remove(mat)

    density = max(0.0, float(strength) * 0.0012)
    if density < 1e-6:
        return  # Volume effectively off — skip cube creation entirely.

    # Spawn cube. `size=N` makes ±N/2 from location.
    bpy.ops.mesh.primitive_cube_add(size=float(box_size), location=tuple(box_center))
    cube = bpy.context.active_object
    cube.name = "AerialPerspectiveBox"
    cube["songe_aerial_box"] = 1
    # Tell the OBJ exporter to skip this cube. The transparent surface
    # + volume scatter are Cycles-only — when the cube survives into
    # the OBJ, MTL strips the volume shader and the geometry becomes
    # a giant grey box wrapped around every browser-loaded scene.
    cube["songe_no_export"] = 1

    # Make the cube invisible to direct rays so it doesn't darken the
    # scene or block the sun. We still want the volume to render — that
    # only requires the surface to be transparent (BSDF) plus the cube
    # being visible to camera so the volume between camera and surfaces
    # contributes scatter.
    if hasattr(cube, "visible_shadow"):
        cube.visible_shadow = False
    if hasattr(cube, "visible_diffuse"):
        cube.visible_diffuse = False
    if hasattr(cube, "visible_glossy"):
        cube.visible_glossy = False
    if hasattr(cube, "visible_transmission"):
        cube.visible_transmission = False

    # Material: Transparent surface + (Scatter + Absorption) volume.
    mat = bpy.data.materials.new("AerialPerspectiveVol")
    mat["songe_aerial_box"] = 1
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (320, 0)

    transparent = nt.nodes.new("ShaderNodeBsdfTransparent")
    transparent.location = (0, 120)

    vol_s = nt.nodes.new("ShaderNodeVolumeScatter")
    vol_s.location = (0, -120)
    if color is None:
        color = (0.92, 0.88, 0.84)  # near-white, slightly warm
    vol_s.inputs["Color"].default_value = (color[0], color[1], color[2], 1.0)
    vol_s.inputs["Density"].default_value = density
    if "Anisotropy" in vol_s.inputs:
        # Forward-scatter so god rays trail away from the sun rather
        # than bloom isotropically.
        vol_s.inputs["Anisotropy"].default_value = 0.6

    vol_a = nt.nodes.new("ShaderNodeVolumeAbsorption")
    vol_a.location = (0, -260)
    vol_a.inputs["Color"].default_value = (0.95, 0.78, 0.65, 1.0)
    vol_a.inputs["Density"].default_value = density * 0.4

    add_v = nt.nodes.new("ShaderNodeAddShader")
    add_v.location = (160, -180)
    nt.links.new(vol_s.outputs["Volume"], add_v.inputs[0])
    nt.links.new(vol_a.outputs["Volume"], add_v.inputs[1])

    nt.links.new(transparent.outputs["BSDF"], out.inputs["Surface"])
    nt.links.new(add_v.outputs["Shader"], out.inputs["Volume"])

    cube.data.materials.clear()
    cube.data.materials.append(mat)

    # Cycles volume sampling — keep modest to bound render time.
    cycles = scene.cycles if hasattr(scene, "cycles") else None
    if cycles is not None:
        if getattr(cycles, "volume_bounces", 0) < 4:
            cycles.volume_bounces = 4
        if getattr(cycles, "volume_step_rate", 1.0) > 0.5:
            cycles.volume_step_rate = 0.5
        if getattr(cycles, "volume_max_steps", 1024) < 64:
            cycles.volume_max_steps = 64

    # `falloff` reserved for future per-height density via Texture
    # Coordinate → Math; not implemented yet.
    _ = falloff


def mark_walkable(obj, *, kind: str = "terrain") -> None:
    """Tag a Blender object as a walkable surface for the future Play
    mode runtime. Writes a custom property ``songe_walkable`` with the
    surface kind so a navmesh/raycast-on-mesh strategy can pick the
    right collider category.

    Parameters
    ----------
    obj
        Any Blender object (typically the terrain mesh, a path ribbon,
        or a bridge mesh). Pass-through if obj is None.
    kind : str
        One of ``terrain`` (the eroded mesh), ``path`` (a ribbon mesh
        baked over the path corridor), ``bridge`` (a structure that
        spans water/gap). Free-form; the runtime treats unknown kinds
        as ``"terrain"``.

    The property is exported via OBJ + .blend round-trip; the frontend
    viewer picks it up by reading `obj.userData?.songe_walkable` (after
    a future GLTF round-trip) or by inspecting the .blend directly via
    a Python sidecar.
    """
    if obj is None:
        return
    obj["songe_walkable"] = str(kind or "terrain")
    # A second property the future Play mode can use to compute spawn
    # heights without raycasting: the obj's lowest local Z. Cheap to
    # write here; saves runtime work later.
    if hasattr(obj, "data") and getattr(obj.data, "vertices", None):
        try:
            obj["songe_walkable_z_min"] = float(min(v.co.z for v in obj.data.vertices))
        except (ValueError, AttributeError):
            pass


def set_time_of_day(
    choice: str,
    *,
    sun_obj=None,
    world_bg_color: tuple[float, float, float] | None = None,
) -> None:
    """Apply a coherent sun + world-color preset matching the requested
    time of day. Build scripts call this AFTER spawning the sun light
    and AFTER wiring the world background node.

    Parameters
    ----------
    choice : str
        One of ``dawn`` | ``morning`` | ``golden`` | ``overcast`` |
        ``dusk`` | ``night``. Anything else falls back to ``morning``.
    sun_obj
        The sun light's Blender object. If None, the function looks up
        the first SUN-type light in the scene.
    world_bg_color : optional override
        Force a specific background color instead of the preset's
        default. Useful when the build script wants the same time-of-day
        sun rig but a different sky tint (e.g. "alpine dawn" vs
        "desert dawn").
    """
    import bpy

    scene = bpy.context.scene
    if scene is None:
        return

    presets = {
        "dawn":     {"alt_deg": 8,  "az_deg": 105, "color": (1.00, 0.78, 0.62), "energy": 1.6, "bg": (0.42, 0.46, 0.62)},
        "morning":  {"alt_deg": 45, "az_deg":  70, "color": (1.00, 0.96, 0.88), "energy": 2.4, "bg": (0.62, 0.74, 0.92)},
        "golden":   {"alt_deg": 18, "az_deg":  55, "color": (1.00, 0.84, 0.58), "energy": 2.8, "bg": (0.78, 0.62, 0.46)},
        "overcast": {"alt_deg": 50, "az_deg":  90, "color": (0.95, 0.96, 1.00), "energy": 1.4, "bg": (0.66, 0.68, 0.72)},
        "dusk":     {"alt_deg": 6,  "az_deg":  60, "color": (1.00, 0.62, 0.42), "energy": 1.5, "bg": (0.58, 0.34, 0.40)},
        "night":    {"alt_deg": -8, "az_deg": 120, "color": (0.62, 0.74, 1.00), "energy": 0.4, "bg": (0.08, 0.10, 0.18)},
    }
    cfg = presets.get((choice or "morning").lower(), presets["morning"])

    if sun_obj is None:
        sun_obj = next(
            (o for o in scene.objects if o.type == "LIGHT" and getattr(o.data, "type", None) == "SUN"),
            None,
        )
    if sun_obj is not None:
        sun_obj.data.color = cfg["color"]
        sun_obj.data.energy = cfg["energy"]
        # altitude (X tilt from horizon up), azimuth (Z rotation around vertical)
        sun_obj.rotation_euler = (
            math.radians(90.0 - cfg["alt_deg"]),
            0.0,
            math.radians(cfg["az_deg"]),
        )

    world = scene.world
    bg_color = world_bg_color if world_bg_color is not None else cfg["bg"]
    if world is not None and world.use_nodes:
        for n in world.node_tree.nodes:
            if n.bl_idname == "ShaderNodeBackground":
                n.inputs[0].default_value = (bg_color[0], bg_color[1], bg_color[2], 1.0)
                break

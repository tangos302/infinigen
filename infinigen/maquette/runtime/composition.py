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
) -> None:
    """Layer a Cycles volumetric scatter on the world output so distant
    geometry fades to sky color, adding film-quality depth.

    This is the "aerial perspective" effect: as light travels through
    air, it scatters and softens distant silhouettes. Practically this
    hides far-mountain triangulation seams, blurs the boundary between
    distant land and sky, and makes the foreground anchor read as
    closer than the mid-ground hero.

    Parameters
    ----------
    strength : float
        Density of the volume scatter. 0.3 = subtle haze, 0.6 = clear
        atmospheric perspective (default), 1.0 = heavy fog. Stay under
        1.5 unless the prompt explicitly asks for soup.
    color : tuple[float, float, float] | None
        Override the scatter color. Defaults to a slightly cool grey
        which reads as natural air. For golden-hour scenes, pass a
        warm peach like ``(1.0, 0.85, 0.7)``; for dusk, a magenta
        like ``(0.95, 0.7, 0.8)``.
    falloff : float
        Density falloff per Z unit (height). Higher = haze concentrates
        near the ground. Default 0.012 keeps haze thickest in the lower
        ~80 BU of the scene, leaving the sky clear.

    Notes
    -----
    Adds the volume world AT THE END of the build script (after world
    background nodes are wired). Re-callable: replaces any prior
    aerial-perspective volume on the world.
    """
    import bpy

    scene = bpy.context.scene
    if scene is None:
        return
    world = scene.world
    if world is None:
        # Build script forgot to author a world — bail rather than
        # constructing one from nothing (the bg color is opinionated).
        return
    world.use_nodes = True
    nt = world.node_tree
    nodes = nt.nodes
    links = nt.links

    # Find existing output + background nodes (build script author
    # already wired them); we just append a Volume Scatter to the
    # output's "Volume" socket without touching surface.
    out_node = None
    for n in nodes:
        if n.bl_idname == "ShaderNodeOutputWorld":
            out_node = n
            break
    if out_node is None:
        return

    # Replace any prior aerial volume so re-calls don't stack.
    for n in list(nodes):
        if n.get("songe_aerial") == 1:
            nodes.remove(n)

    vol = nodes.new("ShaderNodeVolumeScatter")
    vol["songe_aerial"] = 1
    vol.location = (out_node.location.x - 320, out_node.location.y - 220)
    if color is None:
        color = (0.78, 0.84, 0.92)
    vol.inputs["Color"].default_value = (color[0], color[1], color[2], 1.0)
    # Density is in per-BU absorption, applied over the unbounded world
    # volume. The 160 BU scene depth means camera→hero is ~80 BU; at the
    # old 0.06 coefficient, strength=0.6 → density=0.036 → 94% absorption
    # over that distance → black render. Scaled 10× lower so the effect
    # reads as subtle aerial haze on distant geometry without blacking
    # out the foreground. For multi-km landscapes bump back up.
    vol.inputs["Density"].default_value = max(0.0, float(strength) * 0.006)

    links.new(vol.outputs["Volume"], out_node.inputs["Volume"])

    # Cycles needs a few sample bumps to render volumes without
    # massive fireflies. Low limits keep render time sane.
    cycles = scene.cycles if hasattr(scene, "cycles") else None
    if cycles is not None:
        if getattr(cycles, "volume_bounces", 0) < 1:
            cycles.volume_bounces = 1
        if getattr(cycles, "volume_step_rate", 1.0) > 0.5:
            cycles.volume_step_rate = 0.5
        if getattr(cycles, "volume_max_steps", 1024) < 64:
            cycles.volume_max_steps = 64

    # `falloff` reserved for future per-height density via Texture
    # Coordinate → Math; not implemented yet so we keep the signature
    # forward-compatible without behavior. Suppress the unused warning.
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

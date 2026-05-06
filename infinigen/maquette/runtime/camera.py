"""Runtime camera placer — picks framing from Composition state.

Removes camera placement from the LLM's responsibility. The LLM
authors heroes / paths / water; this module picks where the camera
goes so framing rules are mechanical instead of LLM-intuited.

Why we did this: the LLM consistently picked camera positions that
ignored lake placement (alpine-watchtower run shipped a lake the
camera never saw because the cam ray missed it by 2 BU) and
under-framed primary heroes (small silhouette in a vast plate).

Framing algorithm (in order of available context):

  1. **Hero + Water present** — camera sits past the water in the
     direction the water lies from the hero, so water is in the
     foreground and the hero anchors the background. Reads as
     "looking across the lake at the watchtower on the ridge."
  2. **Hero + Ridge present** — camera is perpendicular to the
     ridge axis so the silhouette runs widest in frame.
  3. **Hero only** — camera is in the SW quadrant relative to the
     hero (Sky-CotL convention: warm-key sun rises east, camera
     looks past hero toward sun).
  4. **No composition** — camera at scene-center default
     ``(40, -44, 26) → (0, 0, 3)`` matching the legacy default.

Pitch is fixed at 22° above horizon; lens is 35 mm by default
(wide enough to include hero, water, and the surrounding terrain).
Pass ``lens_mm=50`` for tighter framing on prop-focused shots.

The helper creates a scene Camera if none exists, otherwise it
mutates the existing one — so build scripts can either omit the
camera entirely (recommended) or author one and have us reposition.
"""

from __future__ import annotations

import math
from typing import Any, Optional


def place_scene_camera(
    composition: Any,
    *,
    terrain_size: float,
    lens_mm: float = 35.0,
    pitch_deg: float = 22.0,
    distance_factor: float = 1.45,
) -> Optional[Any]:
    """Position the scene camera with framing chosen from Composition.

    Parameters
    ----------
    composition : Composition | None
        The same ``Composition`` instance you passed to
        ``make_eroded_terrain``. Pass ``None`` to fall back to the
        legacy SW-quadrant default.
    terrain_size : float
        Half-extent of the terrain in BU (the ``size`` you passed to
        ``make_terrain`` / ``make_eroded_terrain``).
    lens_mm : float
        Focal length. 35 mm = wide scene, 50 mm = tighter prop.
    pitch_deg : float
        Above-horizon angle. 22° is the painterly default.
    distance_factor : float
        Camera distance = ``distance_factor × terrain_size``.

    Returns
    -------
    bpy.types.Object | None
        The camera object, or None if Blender state is unusable.
    """
    import bpy
    from mathutils import Vector

    scene = bpy.context.scene
    if scene is None:
        return None

    # 1. Pick target (where the camera looks).
    if composition is not None and getattr(composition, "heroes", None):
        primary = composition.heroes[0]
        target_xy = (float(primary.cx), float(primary.cy))
        # Lift target Z by a few BU so the camera is "looking AT the
        # tower top," not at the ground beneath it.
        target_z_extra = (
            float(getattr(primary, "lift", 0.0)) + 3.5
        )
        target_z = float(getattr(primary, "target_z", None) or 0.0) + target_z_extra
    else:
        target_xy = (0.0, 0.0)
        target_z = 3.0

    # 2. Pick azimuth (compass bearing of the camera relative to target).
    az_rad = _pick_azimuth(composition, target_xy)

    # 3. Place + aim.
    distance = distance_factor * float(terrain_size)
    pitch_rad = math.radians(float(pitch_deg))
    horizontal = distance * math.cos(pitch_rad)
    cam_x = target_xy[0] + horizontal * math.cos(az_rad)
    cam_y = target_xy[1] + horizontal * math.sin(az_rad)
    cam_z = target_z + distance * math.sin(pitch_rad)

    cam = scene.camera
    if cam is None:
        cam = next(
            (o for o in scene.objects if o.type == "CAMERA"), None
        )
    if cam is None:
        bpy.ops.object.camera_add(location=(cam_x, cam_y, cam_z))
        cam = bpy.context.active_object
        scene.camera = cam
    else:
        cam.location = (cam_x, cam_y, cam_z)
        scene.camera = cam

    target_v = Vector((target_xy[0], target_xy[1], target_z))
    direction = target_v - Vector(cam.location)
    if direction.length > 1e-6:
        cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()

    cam.data.lens = float(lens_mm)
    return cam


def _pick_azimuth(composition: Any, target_xy: tuple[float, float]) -> float:
    """Return the camera's compass angle (radians, 0 = +X) chosen from
    composition state. See module docstring for rules."""
    if composition is None:
        # Legacy SW-quadrant default — same vibe as the canonical
        # `(40, -44, 26)` example position relative to origin.
        return math.radians(-132.0)

    heroes = getattr(composition, "heroes", None) or []
    water = getattr(composition, "water", None)
    ridges = getattr(composition, "ridges", None) or []

    if heroes and water is not None:
        # Camera past water in the direction water lies from hero, so
        # water sits in the foreground. Hero anchors the background.
        h = heroes[0]
        dx = float(water.cx) - float(h.cx)
        dy = float(water.cy) - float(h.cy)
        if math.hypot(dx, dy) > 1.0:
            return math.atan2(dy, dx)

    if heroes and ridges:
        # Camera 90° to the ridge axis so the silhouette is widest in
        # frame. Use first ridge's start→end vector.
        wp = list(ridges[0].waypoints)
        if len(wp) >= 2:
            rx = float(wp[-1][0]) - float(wp[0][0])
            ry = float(wp[-1][1]) - float(wp[0][1])
            if math.hypot(rx, ry) > 1.0:
                # Rotate ridge direction 90° CW; pick the side that
                # puts the camera below the target's Y so we look
                # "north" by default (warmer sky in dawn / morning).
                perp = math.atan2(-rx, ry)
                # Wrap to [-π, π] and prefer the south-side variant
                # (cy_camera < cy_target) — sky sits behind the hero
                # not the camera.
                cam_y_offset = math.sin(perp)
                if cam_y_offset > 0:
                    perp += math.pi
                return perp

    return math.radians(-132.0)

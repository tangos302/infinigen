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
    terrain: Any = None,
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
    terrain : terrain handle | None
        The object returned by ``make_eroded_terrain`` (must expose
        ``height_at(x, y)``). When supplied, the camera target Z is
        sampled from terrain at the hero position, so a hero on a
        12 BU peak is centered in frame instead of cropped at the top.
        Without it, target Z falls back to ``hero.target_z + lift``.
    lens_mm : float
        Focal length. 35 mm is the wide scene default and what almost
        every prompt should use. ONLY pass 50 mm for explicit
        single-prop close-ups (rare); 28 mm for 4+ hero panoramas.
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

    plan = _plan_framing(
        composition,
        terrain_size=terrain_size,
        terrain=terrain,
        lens_mm=lens_mm,
        distance_factor=distance_factor,
    )
    target_xy = plan["target_xy"]
    target_z = plan["target_z"]
    az_rad = plan["azimuth"]
    distance = plan["distance"]
    chosen_lens = plan["lens_mm"]

    # Place + aim.
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

    cam.data.lens = float(chosen_lens)
    return cam


def _plan_framing(
    composition: Any,
    *,
    terrain_size: float,
    terrain: Any = None,
    lens_mm: float = 35.0,
    distance_factor: float = 1.45,
) -> dict:
    """Pure-Python framing planner — returns target_xy, target_z, azimuth,
    distance, and lens_mm. Pulled out so the math can be unit-tested
    without Blender, and so panorama / lake branches share one code path.

    Branch selection (in priority order):

      1. **3+ heroes** → panorama: aim at hero centroid, switch to
         28 mm lens, distance scales with the hero bounding-circle
         radius so all heroes fit in frame.
      2. **Hero + large water** → past-water default, but distance is
         pulled back so the lake's diameter projects to ≤ 65 % of the
         frame's horizontal extent. Prevents tall watch-and-water
         scenes from putting the lake off-screen.
      3. **Hero only / hero+ridge / no-comp** → legacy 35 mm framing.
    """
    heroes = []
    water = None
    ridges: list = []
    if composition is not None:
        heroes = list(getattr(composition, "heroes", None) or [])
        water = getattr(composition, "water", None)
        ridges = list(getattr(composition, "ridges", None) or [])

    chosen_lens = float(lens_mm)
    distance = float(distance_factor) * float(terrain_size)

    # Branch 1 — panorama (3+ heroes).
    if len(heroes) >= 3:
        cx = sum(float(h.cx) for h in heroes) / len(heroes)
        cy = sum(float(h.cy) for h in heroes) / len(heroes)
        target_xy = (cx, cy)
        # Bounding-circle radius: max distance from centroid to any hero
        # center, plus that hero's radius.
        bound = 0.0
        for h in heroes:
            d = math.hypot(float(h.cx) - cx, float(h.cy) - cy)
            bound = max(bound, d + float(getattr(h, "radius", 8.0)))
        chosen_lens = 28.0
        # 28 mm on 36 mm sensor → half-FOV ≈ 32.7° → tan ≈ 0.642.
        # Need distance such that bound / distance ≤ 0.55 (55 % of half-frame).
        required = bound / (0.55 * 0.642) if bound > 1e-3 else 0.0
        distance = max(distance, required)
    elif heroes:
        primary = heroes[0]
        target_xy = (float(primary.cx), float(primary.cy))
    else:
        target_xy = (0.0, 0.0)

    # Target Z (height to look at). Same logic as before — sample terrain
    # under the chosen target, then add tower-top offset based on the
    # *primary* hero's radius (or a sensible fallback for panorama /
    # no-hero cases).
    if heroes:
        primary = heroes[0]
        if terrain is not None and hasattr(terrain, "height_at"):
            try:
                ground_z = float(terrain.height_at(target_xy[0], target_xy[1]))
            except Exception:
                ground_z = 0.0
        else:
            ground_z = float(getattr(primary, "target_z", None) or 0.0)
        head_extra = float(getattr(primary, "lift", 0.0)) + max(
            float(getattr(primary, "radius", 8.0)) * 0.4, 4.0
        )
        target_z = ground_z + head_extra
    else:
        target_z = 3.0

    azimuth = _pick_azimuth(composition, target_xy)

    # Branch 2 — lake-aware pullback (single/dual hero + water).
    # Skip for panorama branch (already lens-tuned for fit).
    if len(heroes) < 3 and water is not None and heroes:
        water_radius = float(getattr(water, "radius", 0.0))
        if water_radius > 8.0:  # only bother pulling back for sizeable lakes
            # Distance from camera to lake center along the camera ray.
            # Camera is past the lake along the hero→water direction, so
            # camera-to-lake distance = camera-to-target distance −
            # lake-to-target distance.
            hx, hy = float(heroes[0].cx), float(heroes[0].cy)
            wx, wy = float(getattr(water, "cx", hx)), float(getattr(water, "cy", hy))
            lake_to_target = math.hypot(wx - hx, wy - hy)
            # 35 mm tan(half-FOV) ≈ 0.514. Want lake_radius / cam_to_lake
            # ≤ 0.5 * 0.514 (so lake projects within ~half the frame).
            tan_half = 0.514 if abs(chosen_lens - 35.0) < 0.5 else (
                36.0 / (2.0 * float(chosen_lens))
            )
            cam_to_lake_required = water_radius / (0.5 * tan_half) if tan_half > 1e-3 else 0.0
            required_distance = cam_to_lake_required + lake_to_target
            distance = max(distance, required_distance)

    return {
        "target_xy": target_xy,
        "target_z": target_z,
        "azimuth": azimuth,
        "distance": distance,
        "lens_mm": chosen_lens,
    }


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

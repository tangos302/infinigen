"""Re-render an existing scene.blend with a new camera angle.

Driven by the songe-core ``/pipeline/runs/{id}/reshoot`` route. The
script opens an existing ``scene.blend``, applies a camera preset
(positioned on a ring around the scene's bounding box, aimed at the
center), and re-runs Cycles to write a fresh ``scene.png``.

Skips Claude + factory spawn entirely → ~30 s instead of ~5 min.

Usage (driven by env vars so the orchestrator doesn't have to massage
argparse):

    BLEND_IN=/path/to/scene.blend \\
    OUT_DIR=/path/to/run_dir \\
    RESHOOT_ANGLE=golden_45 \\
    blender --background --python reshoot.py
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import bpy
from mathutils import Vector


# Camera preset → (azimuth_deg, altitude_deg, distance_factor).
# distance_factor multiplies the scene radius (XY extent / 2 + safety).
PRESETS = {
    "front":     (180.0, 22.0, 1.55),
    "back":      (0.0,   22.0, 1.55),
    "left":      (90.0,  22.0, 1.55),
    "right":     (-90.0, 22.0, 1.55),
    "topdown":   (0.0,   85.0, 1.20),
    "golden_45": (135.0, 18.0, 1.65),
    "low_45":    (135.0,  6.0, 1.80),
}


def _scene_center_and_radius() -> tuple[Vector, float]:
    """Compute the world-space bounding box of every visible mesh and
    return its center + a "framing radius" big enough that a camera
    sitting one radius away can frame the whole scene with a 35 mm lens.
    """
    pts: list[Vector] = []
    for o in bpy.data.objects:
        if o.type != "MESH":
            continue
        if o.hide_render:
            continue
        if o.name.startswith("Player_Spawn"):
            continue
        # Skip the small instance templates the build script hides at
        # the world origin — they'd drag the bbox toward 0,0,0 and
        # mis-center the framing on big scenes.
        if o.hide_viewport and o.name.startswith(("Maquette", "scatter_template")):
            continue
        try:
            mat = o.matrix_world
            for corner in o.bound_box:
                pts.append(mat @ Vector(corner))
        except Exception:
            pass
    if not pts:
        return Vector((0, 0, 0)), 40.0
    xs = [p.x for p in pts]
    ys = [p.y for p in pts]
    zs = [p.z for p in pts]
    cx, cy, cz = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2
    half_x = (max(xs) - min(xs)) / 2
    half_y = (max(ys) - min(ys)) / 2
    radius = max(half_x, half_y, 6.0) * 1.15  # safety
    return Vector((cx, cy, cz)), float(radius)


def _apply_camera(angle: str) -> None:
    cfg = PRESETS.get(angle)
    if cfg is None:
        cfg = PRESETS["golden_45"]
    az, alt, dist_factor = cfg

    center, radius = _scene_center_and_radius()
    # Target slightly above the bbox bottom so the horizon doesn't slice
    # the hero in half on low-altitude angles.
    target = Vector((center.x, center.y, center.z + radius * 0.18))

    # Spherical → cartesian. Y-up convention, but Blender is Z-up; we
    # build the cam offset directly in Blender coords.
    az_r = math.radians(az)
    alt_r = math.radians(alt)
    dist = radius * dist_factor
    dx = dist * math.cos(alt_r) * math.sin(az_r)
    dy = -dist * math.cos(alt_r) * math.cos(az_r)  # -cos so az=0 looks toward +Y
    dz = dist * math.sin(alt_r)
    cam_pos = target + Vector((dx, dy, dz))

    cam = bpy.context.scene.camera
    if cam is None:
        bpy.ops.object.camera_add(location=cam_pos)
        cam = bpy.context.active_object
        bpy.context.scene.camera = cam
    else:
        cam.location = cam_pos
    # Aim camera at target. Blender's `to_track_quat('-Z', 'Y')` gives
    # the rotation that makes -Z look toward the target with Y up.
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
    if cam.data is not None:
        cam.data.lens = 35.0


def main() -> None:
    blend_in = Path(os.environ["BLEND_IN"])
    out_dir = Path(os.environ["OUT_DIR"])
    angle = os.environ.get("RESHOOT_ANGLE", "golden_45").strip().lower()

    bpy.ops.wm.open_mainfile(filepath=str(blend_in))
    _apply_camera(angle)

    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    if hasattr(scene, "cycles") and scene.cycles is not None:
        scene.cycles.samples = max(48, int(getattr(scene.cycles, "samples", 48)))
    scene.view_settings.view_transform = "Standard"
    scene.render.resolution_x = 1920
    scene.render.resolution_y = 1080
    scene.render.resolution_percentage = 100
    out_dir.mkdir(parents=True, exist_ok=True)
    scene.render.filepath = str(out_dir / "scene.png")
    scene.render.image_settings.file_format = "PNG"
    bpy.ops.render.render(write_still=True)
    print(f"DONE: {out_dir}/scene.png angle={angle}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERR: {exc}", file=sys.stderr)
        raise

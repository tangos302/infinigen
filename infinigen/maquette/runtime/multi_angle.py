"""Post-build multi-angle render.

Build scripts pick a single hero camera. Shipping just that frame to the
user means scenes that look great from one angle but hollow elsewhere
slip through. This module renders three alternate angles (the hero
rotated 90°/180°/270° around the world Z) and composes a 2×2 grid the
user sees alongside the hero shot.

Usage from the runtime executor:

    from infinigen.maquette.runtime.multi_angle import render_multi_angle

    render_multi_angle(
        blend_path=Path("scene.blend"),
        out_dir=Path("/scene-output"),
        blender_bin="blender",
        samples=24,
    )

After this returns:
    out_dir/
      scene.png         # original hero render (untouched)
      scene_n.png       # original camera rotated 90° around world Z
      scene_s.png       # rotated 180°
      scene_w.png       # rotated 270°
      scene_grid.png    # 2×2 composite (hero top-left, alt1 top-right,
                          alt2 bottom-left, alt3 bottom-right)
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


# Blender side script — runs inside Blender's bundled Python with bpy
# available. Renders the existing scene from 3 rotated copies of the
# hero camera. Single string + format substitution for the out paths.
_RENDER_SCRIPT = r"""
import bpy
import math
from mathutils import Vector

bpy.ops.wm.open_mainfile(filepath=r"{blend_path}")

scn = bpy.context.scene
hero = scn.camera
if hero is None:
    print("[multi_angle] no scene.camera — skipping alt renders")
else:
    # Render uses CYCLES with whatever samples the build set. Bump
    # down a touch for the alternates since 3 of them.
    if scn.cycles.samples > {alt_samples}:
        scn.cycles.samples = {alt_samples}

    hero_loc = hero.location.copy()
    hero_lens = hero.data.lens
    # Estimate the camera's aim point: the build script typically sets
    # rotation_euler from to_track_quat against a target. We can recover
    # the look-at direction from the rotation, project it onto the world
    # Z=0 plane to find where the camera's looking on the ground.
    look_dir = hero.rotation_euler.to_quaternion() @ Vector((0, 0, -1))
    if abs(look_dir.z) > 1e-3:
        t = -hero_loc.z / look_dir.z
        target = hero_loc + look_dir * max(t, 1.0)
    else:
        # Camera horizontal — aim at world origin as a fallback.
        target = Vector((0, 0, hero_loc.z * 0.3))

    rotations = [
        ("n", math.pi * 0.5),
        ("s", math.pi),
        ("w", math.pi * 1.5),
    ]
    for tag, angle in rotations:
        # Rotate the camera location around the target, in world XY.
        dx = hero_loc.x - target.x
        dy = hero_loc.y - target.y
        nx = dx * math.cos(angle) - dy * math.sin(angle)
        ny = dx * math.sin(angle) + dy * math.cos(angle)
        bpy.ops.object.camera_add(
            location=(target.x + nx, target.y + ny, hero_loc.z),
        )
        alt = bpy.context.active_object
        alt.data.lens = hero_lens
        alt.rotation_euler = (target - alt.location).to_track_quat("-Z", "Y").to_euler()
        scn.camera = alt
        scn.render.filepath = r"{out_dir}/scene_" + tag + ".png"
        bpy.ops.render.render(write_still=True)
        # Restore hero camera so the .blend still opens with it.
        scn.camera = hero
print("DONE_MULTI_ANGLE")
"""


def _compose_grid(hero_path: Path, alt_n: Path, alt_s: Path, alt_w: Path,
                  out_path: Path) -> bool:
    """Build a 2×2 PNG. Returns True if Pillow is available, else
    False (callers fall back to the 4 separate files).
    """
    try:
        from PIL import Image
    except ImportError:
        logger.warning("Pillow not installed — skipping scene_grid.png")
        return False

    paths = [hero_path, alt_n, alt_s, alt_w]
    if not all(p.is_file() for p in paths):
        missing = [p.name for p in paths if not p.is_file()]
        logger.warning("multi-angle grid skipped — missing %s", missing)
        return False

    imgs = [Image.open(p).convert("RGB") for p in paths]
    w, h = imgs[0].size
    # All four should be the same resolution since they come from the
    # same scene render settings.
    grid = Image.new("RGB", (w * 2, h * 2), (32, 32, 32))
    grid.paste(imgs[0], (0,     0))     # hero (top-left)
    grid.paste(imgs[1], (w,     0))     # +90° (top-right)
    grid.paste(imgs[2], (0,     h))     # +180° (bottom-left)
    grid.paste(imgs[3], (w,     h))     # +270° (bottom-right)
    grid.save(out_path, "PNG")
    return True


def render_multi_angle(
    blend_path: Path,
    out_dir: Path,
    *,
    blender_bin: str = "blender",
    alt_samples: int = 16,
    timeout_seconds: int = 600,
) -> dict:
    """Render 3 alternate-angle frames + compose a 2×2 grid.

    Returns a dict ``{"alt_paths": [...], "grid_path": Path | None,
    "ok": bool}``. ``ok`` is False if Blender failed; alt frames are
    best-effort (some may be missing if the underlying render hit an
    error).
    """
    blend_path = Path(blend_path)
    out_dir = Path(out_dir)
    if not blend_path.is_file():
        return {"alt_paths": [], "grid_path": None, "ok": False,
                "error": f"blend not found: {blend_path}"}
    if shutil.which(blender_bin) is None:
        return {"alt_paths": [], "grid_path": None, "ok": False,
                "error": f"blender binary {blender_bin!r} not on PATH"}

    script = _RENDER_SCRIPT.format(
        blend_path=str(blend_path),
        out_dir=str(out_dir),
        alt_samples=int(alt_samples),
    )
    try:
        proc = subprocess.run(
            [blender_bin, "--background", "--python-expr", script],
            capture_output=True, text=True, timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        return {"alt_paths": [], "grid_path": None, "ok": False,
                "error": f"timeout: {exc}"}

    if proc.returncode != 0 or "DONE_MULTI_ANGLE" not in proc.stdout:
        return {"alt_paths": [], "grid_path": None, "ok": False,
                "error": proc.stderr[-1500:]}

    alts = [out_dir / f"scene_{tag}.png" for tag in ("n", "s", "w")]
    hero = out_dir / "scene.png"
    grid_path = out_dir / "scene_grid.png"
    grid_ok = _compose_grid(hero, alts[0], alts[1], alts[2], grid_path)

    return {
        "alt_paths": [p for p in alts if p.is_file()],
        "grid_path": grid_path if grid_ok else None,
        "ok": True,
    }

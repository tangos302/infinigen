"""Procedural ground for maquette build scripts.

A maquette scene's ground used to be a flat 100x100 plane — fine for a
courtyard, terrible for "alpine pass" or "fantasy overland panorama".
This helper produces a displaced ground mesh from a 2D noise field
plus a height sampler so the build script can place objects on the
actual surface instead of guessing z=0 everywhere.

Usage:

    from infinigen.maquette.runtime.terrain import make_terrain

    terrain = make_terrain(style="rolling", size=50, base_color=(0.42, 0.50, 0.30, 1.0))
    obj.location = (x, y, terrain.height_at(x, y))

The ``style`` parameter picks an amplitude / frequency preset; ``seed``
controls the noise field so two runs with the same prompt + seed look
identical.

Presets (amplitude in BU, scale = period of biggest hump):
  - flat     0.0 BU, scale 1     — courtyards, plazas, market squares
  - rolling  1.5 BU, scale 14    — gentle valleys, pastoral fields
  - hilly    3.5 BU, scale 10    — green hills, foothills, woodland
  - alpine   8.0 BU, scale 18    — mountainous, dramatic peaks
  - dunes    1.2 BU, scale 6     — sandy waves, desert ripples

Pass ``extra_amp_scale`` to nudge the amplitude (e.g. 1.5 for taller).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

# Imports inside `make_terrain` so this module is importable in pure
# Python (e.g. unit tests) without a Blender process. The factories
# guide imports this for documentation purposes too.


_PRESETS: dict[str, dict[str, float]] = {
    "flat":    {"amp": 0.0, "scale": 1.0,  "octave2_freq": 0.0, "octave2_amp": 0.0},
    "rolling": {"amp": 1.5, "scale": 14.0, "octave2_freq": 2.1, "octave2_amp": 0.4},
    "hilly":   {"amp": 3.5, "scale": 10.0, "octave2_freq": 2.3, "octave2_amp": 0.45},
    "alpine":  {"amp": 8.0, "scale": 18.0, "octave2_freq": 2.0, "octave2_amp": 0.5},
    "dunes":   {"amp": 1.2, "scale": 6.0,  "octave2_freq": 3.5, "octave2_amp": 0.3},
}


@dataclass
class Terrain:
    """Returned by ``make_terrain``. ``height_at(x, y)`` samples the
    same noise field used to displace the mesh, so placed objects
    actually sit on the surface."""
    height_at: Callable[[float, float], float]
    obj: object  # the bpy.types.Object — typed as object to avoid bpy dep at import


def make_terrain(
    *,
    style: str = "flat",
    size: float = 50.0,
    base_color: tuple[float, float, float, float] = (0.42, 0.50, 0.30, 1.0),
    seed: int = 0,
    extra_amp_scale: float = 1.0,
    resolution: int = 64,
    smooth_shading: bool = True,
) -> Terrain:
    """Build a ground mesh of size ``2*size BU`` and return it plus a
    height sampler.

    ``style`` picks a preset (see module docstring). Unknown styles fall
    back to ``flat`` so a typo doesn't crash the build script.

    ``resolution`` is the per-axis vertex count; 64 → 4k verts, plenty
    for low-poly silhouettes without making the OBJ huge.
    """
    import bpy
    from mathutils import noise as bnoise

    preset = _PRESETS.get(style, _PRESETS["flat"])
    amp = preset["amp"] * extra_amp_scale
    scale = preset["scale"]
    o2_freq = preset["octave2_freq"]
    o2_amp = preset["octave2_amp"]
    seed_z = seed * 0.001

    def height_at(x: float, y: float) -> float:
        if amp <= 0.0:
            return 0.0
        nx, ny = x / scale, y / scale
        # mathutils.noise.noise returns roughly [-1, 1]; sum two octaves
        # for variety without paying for a full FBM stack.
        h = bnoise.noise((nx, ny, seed_z)) * amp
        if o2_freq > 0:
            h += (
                bnoise.noise((nx * o2_freq, ny * o2_freq, seed_z + 17.0)) * amp * o2_amp
            )
        return h

    # Build the mesh by hand — primitive_plane + Displace would also work,
    # but the explicit grid lets us share the *exact same* sample function
    # with the build script, so object placements line up to the millimetre.
    res = max(8, int(resolution))
    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    for j in range(res + 1):
        for i in range(res + 1):
            x = -size + 2.0 * size * i / res
            y = -size + 2.0 * size * j / res
            verts.append((x, y, height_at(x, y)))
    for j in range(res):
        for i in range(res):
            a = j * (res + 1) + i
            b = a + 1
            c = a + res + 1
            d = c + 1
            faces.append((a, b, d, c))

    me = bpy.data.meshes.new("ground_mesh")
    me.from_pydata(verts, [], faces)
    me.update()
    obj = bpy.data.objects.new("Ground", me)
    bpy.context.collection.objects.link(obj)

    if smooth_shading:
        for poly in me.polygons:
            poly.use_smooth = True

    mat = bpy.data.materials.new("ground_mat")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = base_color
        bsdf.inputs["Roughness"].default_value = 1.0
    obj.data.materials.append(mat)

    return Terrain(height_at=height_at, obj=obj)

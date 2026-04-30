"""Procedural ground for maquette build scripts.

A maquette scene's ground used to be a flat 100x100 plane — fine for a
courtyard, terrible for "alpine pass" or "fantasy overland panorama".
This helper produces a displaced ground mesh from a 2D noise field
plus a height sampler so the build script can place objects on the
actual surface instead of guessing z=0 everywhere.

Usage (single biome — when one ground type covers the whole map):

    from infinigen.maquette.runtime.terrain import make_terrain

    terrain = make_terrain(style="rolling", size=50, base_color=(0.42, 0.50, 0.30, 1.0))
    obj.location = (x, y, terrain.height_at(x, y))

Usage (multi-biome — when different ground types share the map: e.g.
"grassland headland → sandy beach → ocean archipelago"):

    from infinigen.maquette.runtime.terrain import make_multi_biome_terrain

    terrain = make_multi_biome_terrain(
        size=80,
        seed=42,
        zones=[
            # (style, center_x, center_y, radius)
            ("rolling", -30,  0, 25),   # grass headland on the west
            ("dunes",    20, -8, 22),   # sandy fringe on the southeast
            ("flat",      0, 38, 30),   # ocean side on the north (water added on top)
        ],
    )
    obj.location = (x, y, terrain.height_at(x, y))

Heights blend smoothly between zones (Gaussian RBF weighting); colors
are sharp per-face — each face is assigned the dominant zone's
material, which matches the faceted low-poly style and round-trips
through OBJ/MTL without vertex-color extensions.

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

import math
from dataclasses import dataclass
from typing import Callable, Sequence

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


# Default ground color per style — used when a multi-biome zone doesn't
# specify a `color`. Hand-picked to read distinctly across the OBJ/MTL
# round trip (Kd values map to flat colors in the Three.js viewer).
_DEFAULT_COLORS: dict[str, tuple[float, float, float, float]] = {
    "flat":    (0.50, 0.55, 0.45, 1.0),  # neutral mossy-grey (also used as ocean floor)
    "rolling": (0.42, 0.55, 0.30, 1.0),  # grassland green
    "hilly":   (0.38, 0.50, 0.28, 1.0),  # darker meadow green
    "alpine":  (0.55, 0.55, 0.58, 1.0),  # rocky grey
    "dunes":   (0.85, 0.72, 0.45, 1.0),  # sandy beige
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


# ---------------------------------------------------------------------------
# Multi-biome terrain
# ---------------------------------------------------------------------------


# A zone tuple: (style, center_x, center_y, radius) — minimal — or
# (style, center_x, center_y, radius, color_rgba) — explicit color override.
Zone = tuple  # length 4 or 5 — typed loose to keep prompt-side ergonomics simple


def _zone_color(style: str, override) -> tuple[float, float, float, float]:
    """Resolve the RGBA color for a zone: explicit override wins, else the
    style's default, else the neutral fallback."""
    if override is not None:
        if len(override) == 3:
            return (float(override[0]), float(override[1]), float(override[2]), 1.0)
        return tuple(float(v) for v in override)  # type: ignore[return-value]
    return _DEFAULT_COLORS.get(style, _DEFAULT_COLORS["flat"])


def _zone_height_fn(style: str, cx: float, cy: float, seed_z: float):
    """Return a callable computing the zone's local terrain height at world (x, y).
    Heights are sampled in the zone's local frame so each zone's noise field
    is centered on its own placement, not on the world origin."""
    from mathutils import noise as bnoise

    preset = _PRESETS.get(style, _PRESETS["flat"])
    amp = preset["amp"]
    scale = preset["scale"]
    o2_freq = preset["octave2_freq"]
    o2_amp = preset["octave2_amp"]

    def h(x: float, y: float) -> float:
        if amp <= 0.0:
            return 0.0
        nx = (x - cx) / scale
        ny = (y - cy) / scale
        v = bnoise.noise((nx, ny, seed_z)) * amp
        if o2_freq > 0:
            v += bnoise.noise(
                (nx * o2_freq, ny * o2_freq, seed_z + 17.0)
            ) * amp * o2_amp
        return v
    return h


def make_multi_biome_terrain(
    *,
    size: float = 80.0,
    zones: Sequence[Zone],
    seed: int = 0,
    falloff: float = 1.0,
    resolution: int = 80,
    smooth_shading: bool = True,
) -> Terrain:
    """Build a ground mesh that smoothly blends multiple biome heights and
    splits color regions per-face by dominant zone.

    Each entry in ``zones`` is ``(style, cx, cy, radius)`` or
    ``(style, cx, cy, radius, (r, g, b))``. The blending uses a Gaussian
    RBF: weight_i = exp(-(distance_i / (radius_i * falloff))^2). Heights
    are weighted-summed; colors snap to the argmax zone per face. The
    sharp color boundary follows the faceted low-poly aesthetic and
    round-trips through OBJ/MTL without vertex-color extensions.

    ``size`` is the half-extent in BU (so the world is 2*size BU wide).
    ``resolution`` is the per-axis vertex count — bump it when zones are
    small (under ~10 BU radius) so per-face color regions stay clean.
    ``falloff`` is a multiplier on each zone's radius for the Gaussian
    spread; >1 means more biome interpenetration, <1 means harder edges.
    """
    import bpy

    if not zones:
        raise ValueError("make_multi_biome_terrain requires at least one zone")

    # Normalize to dicts for clarity downstream.
    zone_specs = []
    for i, z in enumerate(zones):
        if len(z) == 4:
            style, cx, cy, radius = z
            color_override = None
        elif len(z) == 5:
            style, cx, cy, radius, color_override = z
        else:
            raise ValueError(
                f"zone[{i}] must be (style, cx, cy, radius) or "
                f"(style, cx, cy, radius, (r,g,b)); got {z!r}"
            )
        if style not in _PRESETS:
            # Fall back to flat — typo shouldn't crash the build script.
            style = "flat"
        zone_specs.append({
            "style": style,
            "cx": float(cx),
            "cy": float(cy),
            "radius": max(float(radius), 1.0),
            "color": _zone_color(style, color_override),
            "height_fn": _zone_height_fn(
                style, float(cx), float(cy),
                (seed + i * 7919) * 0.001,
            ),
        })

    # Per-(x,y) Gaussian RBF weights against each zone's center+radius.
    def _weights(x: float, y: float) -> list[float]:
        ws = []
        for zs in zone_specs:
            dx = x - zs["cx"]
            dy = y - zs["cy"]
            r = zs["radius"] * falloff
            # Gaussian: 1 at center, ~0.37 at one radius, near-0 past 2*radius.
            ws.append(math.exp(-(dx * dx + dy * dy) / (r * r)))
        s = sum(ws)
        if s <= 1e-9:
            return [1.0 / len(zone_specs)] * len(zone_specs)
        return [w / s for w in ws]

    def height_at(x: float, y: float) -> float:
        ws = _weights(x, y)
        h = 0.0
        for zs, w in zip(zone_specs, ws):
            h += w * zs["height_fn"](x, y)
        return h

    # Argmax zone — used per-face to pick the material slot.
    def _dominant_zone(x: float, y: float) -> int:
        ws = _weights(x, y)
        best = 0
        best_w = -1.0
        for i, w in enumerate(ws):
            if w > best_w:
                best_w = w
                best = i
        return best

    # Build the grid mesh. Per-axis vertex count = resolution + 1.
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

    me = bpy.data.meshes.new("multi_biome_mesh")
    me.from_pydata(verts, [], faces)
    me.update()
    obj = bpy.data.objects.new("Ground", me)
    bpy.context.collection.objects.link(obj)

    if smooth_shading:
        for poly in me.polygons:
            poly.use_smooth = True

    # One material per zone, kept in slot order = zone index.
    for idx, zs in enumerate(zone_specs):
        mat = bpy.data.materials.new(f"biome_{idx}_{zs['style']}")
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf is not None:
            bsdf.inputs["Base Color"].default_value = zs["color"]
            bsdf.inputs["Roughness"].default_value = 1.0
        obj.data.materials.append(mat)

    # Per-face material assignment — sample the face center, pick the
    # argmax zone. The grid is dense enough at resolution=80 (≈6500
    # faces over a 160 BU world ≈ 2 BU per face) that per-face snapping
    # gives clean biome regions without obvious staircase artifacts.
    for poly in me.polygons:
        cx_f = sum(verts[v][0] for v in poly.vertices) / len(poly.vertices)
        cy_f = sum(verts[v][1] for v in poly.vertices) / len(poly.vertices)
        poly.material_index = _dominant_zone(cx_f, cy_f)

    return Terrain(height_at=height_at, obj=obj)

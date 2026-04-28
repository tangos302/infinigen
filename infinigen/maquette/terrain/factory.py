"""LowPolyTerrainFactory — drops a procedural ground mesh into the scene.

Usage:

    from infinigen.maquette.terrain import LowPolyTerrainFactory

    f = LowPolyTerrainFactory(
        factory_seed=42,
        terrain_archetype="gorge_with_mesas",
        extent=(80.0, 80.0),
    )
    obj = f.create_asset(placeholder=None)

The factory is itself an `AssetFactory` so it slots into the existing
factory registry / pipeline / scene composer. But it has different
poly-count economics from a typical asset: a terrain is one big mesh,
and a 80×80 m extent at voxel_size=0.5 m emits ~30k–80k tris. The user
explicitly asked for terrain to NOT be polycount-budgeted alongside
small props; the `voxel_size` knob is the single dial.

Archetypes implemented in this PoC:

  flat               — A noise-displaced ground plane. Baseline.
  gorge_with_mesas   — Desert-mesa terrain with a gorge carved through
                       the middle. Test case for the user's
                       "quarry/mining trench in ravine gorge with
                       desert mesas outside" prompt.

Future archetypes (just compose more SDFs):
  cave_pocket, tunnel_under_mesa, cliff_drop, river_valley, …
"""

from __future__ import annotations

import math
import random
from typing import Callable

import bpy
import numpy as np

from infinigen.core.placement.factory import AssetFactory

from . import sdf as sdf_lib
from .marching import build_mesh, mesh_to_blender


_TERRAIN_ARCHETYPES = ("flat", "gorge_with_mesas")


_ARCHETYPE_DEFAULTS = {
    "flat": dict(
        extent=(60.0, 60.0),
        max_height=2.0,
        noise_period=12.0,
    ),
    "gorge_with_mesas": dict(
        extent=(80.0, 80.0),
        # Ground noise — almost-flat desert basin. 0.2m amplitude over a
        # 60m period reads as "the sand drifted slightly" — any bigger
        # and marching cubes makes it look pebbly. Mesas are the
        # vertical-relief storyteller, not the floor.
        max_height=0.2,
        noise_period=60.0,
        # Mesa column knobs.
        n_mesas=6,
        mesa_height_range=(8.0, 18.0),
        mesa_radius_range=(4.0, 9.0),
        mesa_keep_out_radius=14.0,   # mesas don't spawn inside the gorge corridor
        mesa_blend=2.5,              # smooth_union radius for ground↔mesa
        # Gorge knobs — a winding ravine carved through the terrain.
        gorge_depth=10.0,
        gorge_half_width=2.5,         # ravine half-width at top
        gorge_taper=0.35,             # bottom is `taper` × top width
        gorge_n_waypoints=4,
        gorge_lateral_jitter=8.0,
        gorge_blend=1.5,
    ),
}


def _build_gorge_with_mesas(
    seed: int,
    extent: tuple[float, float],
    *,
    max_height: float,
    noise_period: float,
    n_mesas: int,
    mesa_height_range: tuple[float, float],
    mesa_radius_range: tuple[float, float],
    mesa_keep_out_radius: float,
    mesa_blend: float,
    gorge_depth: float,
    gorge_half_width: float,
    gorge_taper: float,
    gorge_n_waypoints: int,
    gorge_lateral_jitter: float,
    gorge_blend: float,
) -> tuple[sdf_lib.SDF, Callable[[np.ndarray, np.ndarray], np.ndarray]]:
    """Compose the gorge-with-mesas SDF. Returns (sdf, height_fn) — `sdf`
    for marching cubes, `height_fn` for asset placement queries.

    The terrain reads bottom-up:
      1. ground noise → a slightly bumpy desert floor
      2. mesa columns added on top via smooth_union (organic blend at the
         skirt, so they look like rock outcrops, not stacked cylinders)
      3. ravine subtracted via smooth_subtract along a winding XY polyline
         (depth tapers and the trench has a slight V-bottom from the
         taper kwarg)
    """
    rng = random.Random(seed)
    sx, sy = extent

    # --- ground noise ------------------------------------------------------
    # 2 octaves only — one big macro dune wave plus a half-amplitude
    # half-period overlay. Anything more reads as gritty rock, not sand.
    noise = sdf_lib.perlin_2d(
        seed=seed, period=noise_period, amplitude=max_height,
        octaves=2, persistence=0.4,
    )

    # --- gorge waypoints — mostly along Y but jittered laterally -----------
    # We walk from -sy/2 to +sy/2 in equal Y steps and jitter X within
    # ±lateral_jitter so the ravine snakes naturally.
    waypoints: list[tuple[float, float]] = []
    n_pts = max(2, gorge_n_waypoints)
    for i in range(n_pts):
        t = i / (n_pts - 1)
        y = (t - 0.5) * sy * 0.95
        x = rng.uniform(-gorge_lateral_jitter, gorge_lateral_jitter)
        waypoints.append((x, y))

    # --- mesa positions — outside the gorge corridor ----------------------
    mesas: list[dict] = []
    attempts = 0
    while len(mesas) < n_mesas and attempts < n_mesas * 30:
        attempts += 1
        cx = rng.uniform(-sx * 0.45, sx * 0.45)
        cy = rng.uniform(-sy * 0.45, sy * 0.45)
        # Reject if too close to any waypoint (i.e., the gorge corridor)
        dist_to_gorge = min(
            math.hypot(cx - wx, cy - wy) for wx, wy in waypoints
        )
        if dist_to_gorge < mesa_keep_out_radius:
            continue
        mesas.append({
            "x": cx, "y": cy,
            "h": rng.uniform(*mesa_height_range),
            "r": rng.uniform(*mesa_radius_range),
        })

    # --- height function (XY → Z) — used by placement queries -------------
    # A heightmap projection of the SDF, ignoring the gorge for the moment;
    # gorge is below z=0 so we want the height that's still on the surface
    # outside the gorge, and inside the gorge the surface is conceptually
    # at the gorge bottom but factories should generally avoid placing
    # anything there. We compute h(x,y) = ground + tallest_mesa_contribution
    # so callers can place assets "on top of" the mesas/ground.
    def height_fn(x: np.ndarray, y: np.ndarray) -> np.ndarray:
        x_arr = np.asarray(x, dtype=np.float32)
        y_arr = np.asarray(y, dtype=np.float32)
        h_ground = noise(x_arr, y_arr)
        h_total = h_ground.copy()
        # Each mesa adds a smooth bump. We model a mesa as a clamped
        # cosine bump of radius r — going from 0 outside to mesa_h at
        # the center, with a smoothstep skirt.
        for m in mesas:
            r2 = (x_arr - m["x"]) ** 2 + (y_arr - m["y"]) ** 2
            d = np.sqrt(r2) / m["r"]
            # Smoothstep mask: 1 inside, smooth falloff to 0 at d=1.2
            t = np.clip(1.0 - (d - 0.7) / 0.5, 0.0, 1.0)
            t = t * t * (3.0 - 2.0 * t)  # smoothstep
            h_total = np.maximum(h_total, h_ground + m["h"] * t)
        return h_total

    # --- SDF composition ---------------------------------------------------
    # Surface = z - h(x,y). We bias the ground to start below z=0 so the
    # marching cubes volume can include a chunk of ground "fill" below.
    # Then carve gorge out of it.
    # Specifically: ground_field = z - h(x,y) (positive above surface).
    # Gorge SDF: a vertical wall capsule along the polyline, radius
    # `gorge_half_width`. We carve via smooth_subtract.
    ground_sdf = sdf_lib.height_field(height_fn)

    # Gorge: a polyline with a tapering capsule. Marching cubes happens
    # in 3D so we want the gorge to be a vertical pit reaching from
    # well above the surface down to z = -gorge_depth.
    gorge_sdf = sdf_lib.line_xy(
        waypoints, radius=gorge_half_width,
        z=-gorge_depth * 0.5, z_extent=gorge_depth * 1.5,
    )
    if gorge_blend > 0:
        terrain = sdf_lib.smooth_subtract(gorge_blend, ground_sdf, gorge_sdf)
    else:
        terrain = sdf_lib.subtract(ground_sdf, gorge_sdf)

    return terrain, height_fn


class LowPolyTerrainFactory(AssetFactory):
    """A procedural terrain mesh — a single large flat-shaded ground.

    Constructor knobs:

        factory_seed           : passed to noise + waypoint RNG
        terrain_archetype      : "flat" | "gorge_with_mesas"
        extent                 : (sx, sy) world-meter span; default per archetype
        voxel_size             : marching-cubes grid spacing (default 0.5 m).
                                 0.25 = denser, 1.0 = blockier.
        z_extent               : (zmin, zmax) sampling range; default
                                 derived from archetype.
        Plus the per-archetype kwargs in `_ARCHETYPE_DEFAULTS`.

    `create_asset` returns a single mesh object. `height_fn` is exposed
    on the factory after `create_asset` so caller can do
    `f.height_fn(x, y) → z` to drop other factories onto the surface.
    """

    def __init__(
        self,
        factory_seed,
        terrain_archetype: str = "gorge_with_mesas",
        extent: tuple[float, float] | None = None,
        # Voxel size = marching-cubes grid spacing in world meters. 0.6 m
        # at 80×80 extent + ~8° decimate → ~10k faces with detailed cliffs
        # and a clean flat floor. Terrain is the largest single mesh in
        # the scene so it gets the lion's share of the polycount budget;
        # objects are bbox-density-budgeted via density.py independently.
        voxel_size: float = 0.6,
        z_extent: tuple[float, float] | None = None,
        coarse: bool = False,
        **archetype_kwargs,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if terrain_archetype not in _TERRAIN_ARCHETYPES:
            raise ValueError(
                f"unknown terrain_archetype {terrain_archetype!r}; "
                f"valid: {_TERRAIN_ARCHETYPES}"
            )
        d = _ARCHETYPE_DEFAULTS[terrain_archetype]
        self.terrain_archetype = terrain_archetype
        self.extent = (
            extent if extent is not None else d["extent"]
        )
        self.voxel_size = float(voxel_size)
        # Merge defaults + caller overrides for archetype-specific params.
        self.archetype_kwargs = {
            k: archetype_kwargs.get(k, v) for k, v in d.items() if k != "extent"
        }
        if z_extent is None:
            # Reasonable Z range based on archetype: tallest mesa + gorge
            # depth + a margin.
            mesa_h = self.archetype_kwargs.get("mesa_height_range", (0, 5))[1]
            gorge_d = self.archetype_kwargs.get("gorge_depth", 0)
            self.z_extent = (
                -gorge_d - 4.0,
                mesa_h + self.archetype_kwargs.get("max_height", 2) + 2.0,
            )
        else:
            self.z_extent = (float(z_extent[0]), float(z_extent[1]))
        self.height_fn: Callable | None = None  # populated in create_asset

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyTerrain({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        if self.terrain_archetype == "flat":
            noise = sdf_lib.perlin_2d(
                seed=self.factory_seed,
                period=self.archetype_kwargs["noise_period"],
                amplitude=self.archetype_kwargs["max_height"],
            )
            self.height_fn = noise
            terrain = sdf_lib.height_field(noise)
        elif self.terrain_archetype == "gorge_with_mesas":
            terrain, hfn = _build_gorge_with_mesas(
                seed=self.factory_seed,
                extent=self.extent,
                **self.archetype_kwargs,
            )
            self.height_fn = hfn
        else:
            raise AssertionError(self.terrain_archetype)

        sx, sy = self.extent
        verts, faces = build_mesh(
            terrain,
            extent=(
                (-sx / 2, sx / 2),
                (-sy / 2, sy / 2),
                self.z_extent,
            ),
            voxel_size=self.voxel_size,
        )
        obj = mesh_to_blender(
            verts, faces,
            name=f"LowPolyTerrain({self.factory_seed})",
            flat_shaded=True,
        )
        return obj

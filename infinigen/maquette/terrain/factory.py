"""LowPolyTerrainFactory — drops a procedural ground mesh into the scene.

The factory takes a `base` (which biome — desert, ocean, alpine, …) and a
list of `features` (composable shapes — Gorge, MesaCluster, Lake,
CaveSystem, MountainPeak, IslandCluster, Cliff). The base provides the
starting SDF + height function; each feature mutates them in order.

Example::

    from infinigen.maquette.terrain import (
        LowPolyTerrainFactory, DesertBase, MesaCluster, Gorge,
    )

    f = LowPolyTerrainFactory(
        factory_seed=42,
        base=DesertBase(max_height=0.2),
        features=[
            MesaCluster(n=6, height_range=(8, 18)),
            Gorge(depth=10, half_width=2.5, axis="y"),
        ],
        extent=(80, 80),
    )
    obj = f.create_asset(placeholder=None)
    # asset placement: f.height_fn(x, y) → z, f.scatter_zones, f.keep_out_zones

`base` may be passed as a string (looked up in `_BASES`) for prompt-side
ergonomics — `base="desert"` is equivalent to `base=DesertBase()`.

Polycount: at the calibrated default voxel_size=0.6 and 80×80m extent the
output is ~10–20k faces depending on feature density. The user explicitly
asked for terrain to *not* be polycount-budgeted alongside small props;
this is the only large mesh in the scene by design.
"""

from __future__ import annotations

from typing import Sequence

import bpy

from infinigen.core.placement.factory import AssetFactory

from . import sdf as sdf_lib
from .bases import TerrainBase, base_from_name
from .composition import BaseSpec, FeatureSpec, HeightFn
from .marching import build_mesh, mesh_to_blender


class LowPolyTerrainFactory(AssetFactory):
    """A procedural terrain mesh built by composing a base + features.

    Constructor knobs:
      factory_seed   : int — passed through to base + each feature's RNG
      base           : str | TerrainBase — biome ground type
      features       : list of feature instances (Gorge, MesaCluster, etc.)
      extent         : (sx, sy) world-meter terrain extent
      voxel_size     : marching-cubes grid spacing in meters; default 0.6.
                       Smaller = denser, sharper detail, more poly. Larger
                       = chunkier silhouette, fewer poly. The terrain is
                       polycount-unbudgeted by design (see module docstring).
      z_extent       : (zmin, zmax) sample range; if None, derived from
                       the assembled features (lowest gorge depth →
                       tallest mesa peak + a few m margin).
      planar_decimate_deg : angle threshold for the planar decimate that
                            removes voxel-stepping artifacts on flat
                            surfaces. Default 7.99° → ~10–15k faces.
                            None to disable.

    After `create_asset`:
      f.height_fn(x, y) → z      — final composed surface height (heightmap-projected)
      f.scatter_zones            — [(cx, cy, r), ...] islands / mesa tops where assets should spawn
      f.keep_out_zones           — [(cx, cy, r), ...] gorge corridors / cave mouths to avoid
    """

    def __init__(
        self,
        factory_seed,
        base: str | TerrainBase = "desert",
        features: Sequence | None = None,
        extent: tuple[float, float] = (80.0, 80.0),
        voxel_size: float = 0.6,
        z_extent: tuple[float, float] | None = None,
        planar_decimate_deg: float | None = 7.99,
        coarse: bool = False,
    ):
        super().__init__(factory_seed, coarse=coarse)
        self.base = base_from_name(base) if isinstance(base, str) else base
        self.features = list(features) if features else []
        self.extent = (float(extent[0]), float(extent[1]))
        self.voxel_size = float(voxel_size)
        self._z_extent_override = z_extent
        self.planar_decimate_deg = planar_decimate_deg

        # Populated after `create_asset`:
        self.height_fn: HeightFn | None = None
        self.scatter_zones: list[tuple[float, float, float]] = []
        self.keep_out_zones: list[tuple[float, float, float]] = []

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyTerrain({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        # Compose the base, then each feature in order.
        base_spec = self.base.to_spec(self.extent, self.factory_seed)
        terrain_sdf = base_spec.sdf
        height_fn = base_spec.height_fn
        scatter_zones: list[tuple[float, float, float]] = []
        keep_out_zones: list[tuple[float, float, float]] = []

        for feature in self.features:
            # Pass running keep-outs so subsequent features can avoid
            # placing geometry inside earlier features' corridors. Used
            # by MesaCluster to keep mesas out of the gorge.
            specs = feature.to_specs(
                self.extent,
                self.factory_seed,
                existing_keep_outs=list(keep_out_zones),
            )
            for spec in specs:
                terrain_sdf = _apply_op(terrain_sdf, spec)
                if spec.height_modifier is not None:
                    height_fn = spec.height_modifier(height_fn)
                scatter_zones.extend(spec.scatter_zones)
                keep_out_zones.extend(spec.keep_out_zones)

        self.height_fn = height_fn
        self.scatter_zones = scatter_zones
        self.keep_out_zones = keep_out_zones

        # Z-extent: prefer caller override, else inspect features for the
        # tallest peak / deepest carve so the marching cubes volume covers
        # the whole iso-surface.
        if self._z_extent_override is None:
            z_extent = self._auto_z_extent()
        else:
            z_extent = self._z_extent_override

        sx, sy = self.extent
        verts, faces = build_mesh(
            terrain_sdf,
            extent=((-sx / 2, sx / 2), (-sy / 2, sy / 2), z_extent),
            voxel_size=self.voxel_size,
        )
        obj = mesh_to_blender(
            verts, faces,
            name=f"LowPolyTerrain({self.factory_seed})",
            flat_shaded=True,
            planar_decimate_deg=self.planar_decimate_deg,
        )
        return obj

    # -----------------------------------------------------------------
    # Internals
    # -----------------------------------------------------------------

    def _auto_z_extent(self) -> tuple[float, float]:
        """Sniff the base AND features list for likely z-bounds.
        Conservative — we'd rather waste a few voxels of vertical
        sampling than have the marching cubes volume miss the top of a
        plateau or the bottom of a canyon.
        """
        def _upper(v) -> float:
            if v is None:
                return 0.0
            if isinstance(v, tuple) and len(v) == 2:
                return float(v[1])
            return float(v)

        z_min = -2.0
        z_max = 2.0
        # Base contributes — MesaPlateauBase has plateau_height,
        # AlpineBase has max_height, etc.
        for attr in ("plateau_height", "max_height", "height", "wave_height"):
            v = getattr(self.base, attr, None)
            if v is not None:
                z_max = max(z_max, _upper(v) + 3.0)
        for f in self.features:
            for attr in ("depth", "total_depth"):
                v = getattr(f, attr, None)
                if v is not None:
                    z_min = min(z_min, -_upper(v) - 4.0)
            for attr in ("height", "height_range", "wall_mesa_height_range"):
                v = getattr(f, attr, None)
                if v is not None:
                    z_max = max(z_max, _upper(v) + 3.0)
        return (z_min, z_max)


def _apply_op(running_sdf, spec: FeatureSpec):
    """Compose `spec.sdf` with `running_sdf` per `spec.op`."""
    if spec.op == "union":
        return sdf_lib.union(running_sdf, spec.sdf)
    if spec.op == "subtract":
        return sdf_lib.subtract(running_sdf, spec.sdf)
    if spec.op == "smooth_union":
        return sdf_lib.smooth_union(spec.blend, running_sdf, spec.sdf)
    if spec.op == "smooth_subtract":
        return sdf_lib.smooth_subtract(spec.blend, running_sdf, spec.sdf)
    raise ValueError(f"unknown compose op {spec.op!r}")

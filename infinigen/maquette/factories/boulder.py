"""LowPolyBoulderFactory — Maquette wrapper for upstream BoulderFactory.

Strategy: keep upstream's *procedural decision tree* (which controls
shape archetype, scale, slab-vs-boulder, etc.) and intercept the
*geometry finalization* phase to drop polycount + faceted shading.

Two interventions:
  1. After `create_placeholder` returns, strip the VORONOI displace
     modifiers — they bake invisible micro-detail at low poly counts.
  2. Override `create_asset` so it calls upstream's create_asset with a
     much larger `face_size` (which is the dominant polycount lever in
     `detail.adapt_mesh_resolution`), then flat-shades and optionally
     decimates the resulting mesh.

The upstream `BoulderFactory` source is not modified.
"""

from __future__ import annotations

import bpy

from infinigen.assets.objects.rocks.boulder import BoulderFactory

from ..lowpoly import decimate, flat_shade, strip_voronoi_displace
from ..materials import apply_palette


class LowPolyBoulderFactory(BoulderFactory):
    """A BoulderFactory that emits faceted low-poly boulders.

    Constructor adds two Maquette knobs on top of the upstream signature:

        target_face_size : float, default 0.15
            Voxel size used by `detail.adapt_mesh_resolution` during
            `create_asset`. Upstream default is 0.01 (1 cm) which produces
            ~10⁶ polys for a ~2 m boulder. 0.15 (15 cm) brings that to
            ~10²–10³ polys — Firewatch territory.

        decimate_ratio : float | None, default None
            If set (e.g. 0.5), runs a final COLLAPSE decimate at this ratio
            to cap polycount further. None = skip.

    All other constructor args are forwarded to the upstream factory; the
    procedural choices made there (slab vs boulder, scale distributions,
    rock surface variant, etc.) are preserved.
    """

    def __init__(
        self,
        factory_seed,
        target_face_size: float = 0.15,
        decimate_ratio: float | None = None,
        palette_color: str | None = None,
        **kwargs,
    ):
        super().__init__(factory_seed, **kwargs)
        self._maquette_target_face_size = float(target_face_size)
        if decimate_ratio is not None:
            decimate_ratio = float(decimate_ratio)
        self._maquette_decimate_ratio = decimate_ratio
        self._maquette_palette_color = palette_color

    def create_placeholder(self, boulder_scale: float = 1, **kwargs) -> bpy.types.Object:
        obj = super().create_placeholder(boulder_scale=boulder_scale, **kwargs)
        # The placeholder still carries unapplied modifiers (DISPLACE
        # voronoi pair, geomod surface tweaks). DISPLACE voronoi adds
        # invisible micro-bumps under flat shading; strip it before the
        # downstream `create_asset` bakes modifiers into the final mesh.
        strip_voronoi_displace(obj)
        return obj

    def create_asset(
        self,
        i: int,
        placeholder: bpy.types.Object,
        face_size: float = 0.01,
        distance: float = 0,
        **params,
    ) -> bpy.types.Object:
        # Force our larger face size regardless of caller. The upstream
        # parent class is unchanged; we just substitute the parameter.
        skin_obj = super().create_asset(
            i,
            placeholder,
            face_size=self._maquette_target_face_size,
            distance=distance,
            **params,
        )
        flat_shade(skin_obj)
        if self._maquette_decimate_ratio is not None:
            decimate(skin_obj, self._maquette_decimate_ratio)
        if self._maquette_palette_color is not None:
            apply_palette(skin_obj, self._maquette_palette_color)
        return skin_obj

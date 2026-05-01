"""RealisticGemstoneFactory — faceted gem / diamond, wraps gemstones addon.

Source: `bl_ext.blender_org.extra_mesh_objects.add_mesh_gemstones`.
Both `add_gem(r1, r2, seg, h1, h2)` and
`add_diamond(segments, girdle_radius, table_radius, crown_height,
pavilion_height)` are pure-Python factored functions returning
`(verts, faces)`.

Use for treasure-chest scatter, accent props on altars / crowns / magic
artifacts. Pair with RealisticGlowingRocksFactory for emissive variants.

Archetype mapping → (function, params):

    "diamond_round"   : add_diamond, classic round-brilliant proportions
    "diamond_tall"    : add_diamond, taller crown for fantasy "magic gem"
    "gem_classic"     : add_gem, traditional faceted teardrop
    "gem_squat"       : add_gem, wide flat-cut for set jewelry
    "any"             : random pick

License: GPL-2.0-or-later (bundled Blender addon).
"""

from __future__ import annotations

import importlib

import bpy
import numpy as np

from infinigen.core.placement.factory import AssetFactory
from infinigen.core.util.math import FixedSeed


_GEM_ARCHETYPES = ("diamond_round", "diamond_tall", "gem_classic", "gem_squat", "any")

# Each preset is (kind, kwargs). kind picks which upstream function.
_ARCHETYPE_PRESETS: dict[str, tuple[str, dict]] = {
    "diamond_round": ("diamond", {
        "segments": 32, "girdle_radius": 0.5, "table_radius": 0.3,
        "crown_height": 0.18, "pavilion_height": 0.4,
    }),
    "diamond_tall": ("diamond", {
        "segments": 24, "girdle_radius": 0.4, "table_radius": 0.18,
        "crown_height": 0.35, "pavilion_height": 0.55,
    }),
    "gem_classic": ("gem", {
        "r1": 0.5, "r2": 0.4, "seg": 16, "h1": 0.5, "h2": 0.25,
    }),
    "gem_squat": ("gem", {
        "r1": 0.6, "r2": 0.55, "seg": 20, "h1": 0.2, "h2": 0.12,
    }),
}


def _get_gem_module():
    import addon_utils
    addon_utils.enable("bl_ext.blender_org.extra_mesh_objects", default_set=False)
    return importlib.import_module(
        "bl_ext.blender_org.extra_mesh_objects.add_mesh_gemstones"
    )


class RealisticGemstoneFactory(AssetFactory):
    """Realistic gemstone factory.

    Constructor knobs:

        factory_seed : int
        archetype : str = "diamond_round"
            One of: diamond_round / diamond_tall / gem_classic / gem_squat / any.
    """

    def __init__(
        self,
        factory_seed: int,
        archetype: str = "diamond_round",
        coarse: bool = False,
    ):
        if archetype not in _GEM_ARCHETYPES:
            raise ValueError(
                f"archetype={archetype!r} not in {_GEM_ARCHETYPES}"
            )
        super().__init__(factory_seed, coarse=coarse)
        if archetype == "any":
            with FixedSeed(factory_seed):
                non_any = [a for a in _GEM_ARCHETYPES if a != "any"]
                archetype = str(np.random.choice(non_any))
        self.archetype = archetype

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        empty = bpy.data.objects.new("GemPlaceholder", None)
        bpy.context.collection.objects.link(empty)
        return empty

    def create_asset(self, i: int = 0, placeholder=None, **params) -> bpy.types.Object:
        mod = _get_gem_module()
        kind, kwargs = _ARCHETYPE_PRESETS[self.archetype]
        if kind == "diamond":
            verts, faces = mod.add_diamond(**kwargs)
        elif kind == "gem":
            verts, faces = mod.add_gem(**kwargs)
        else:  # pragma: no cover — guarded above
            raise ValueError(f"unknown kind {kind!r}")

        mesh = bpy.data.meshes.new(f"Gem.{self.archetype}.{i}")
        # add_gem returns mathutils.Vector, mesh.from_pydata takes tuples
        mesh.from_pydata([tuple(v) for v in verts], [], faces)
        mesh.update()
        obj = bpy.data.objects.new(mesh.name, mesh)
        bpy.context.collection.objects.link(obj)
        return obj

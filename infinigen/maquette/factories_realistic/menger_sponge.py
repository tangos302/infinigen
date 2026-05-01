"""RealisticMengerSpongeFactory — fractal cube, wraps addon.

Source: `bl_ext.blender_org.extra_mesh_objects.add_mesh_menger_sponge`.
Pure-Python class with `create(width, height)` returning `(verts, faces)`.
Level 0 is a single cube; level 1 has 20 sub-cubes; level 2 has 400.
Level 3 (8000 sub-cubes) gets heavy fast — capped via polycap on import.

Use for sci-fi monuments / Escher-style props / fractal sculptures.

Archetype mapping → fractal level:

    "level1"  : 20 sub-cubes — readable Menger silhouette
    "level2"  : 400 sub-cubes — detailed but still snappy
    "level3"  : 8000 sub-cubes — hero monument, heavy
    "any"     : random pick

License: GPL-2.0-or-later (bundled Blender addon).
"""

from __future__ import annotations

import importlib

import bpy
import numpy as np

from infinigen.core.placement.factory import AssetFactory
from infinigen.core.util.math import FixedSeed


_MENGER_ARCHETYPES = ("level1", "level2", "level3", "any")

_ARCHETYPE_TO_LEVEL: dict[str, int] = {"level1": 1, "level2": 2, "level3": 3}


def _get_menger_module():
    import addon_utils
    addon_utils.enable("bl_ext.blender_org.extra_mesh_objects", default_set=False)
    return importlib.import_module(
        "bl_ext.blender_org.extra_mesh_objects.add_mesh_menger_sponge"
    )


class RealisticMengerSpongeFactory(AssetFactory):
    """Realistic Menger-sponge factory.

    Constructor knobs:

        factory_seed : int
        archetype : str = "level2"
            One of: level1 / level2 / level3 / any.
        size : float = 2.0  (cube side length, meters)
    """

    def __init__(
        self,
        factory_seed: int,
        archetype: str = "level2",
        size: float = 2.0,
        coarse: bool = False,
    ):
        if archetype not in _MENGER_ARCHETYPES:
            raise ValueError(
                f"archetype={archetype!r} not in {_MENGER_ARCHETYPES}"
            )
        super().__init__(factory_seed, coarse=coarse)
        if archetype == "any":
            with FixedSeed(factory_seed):
                non_any = list(_ARCHETYPE_TO_LEVEL.keys())
                archetype = str(np.random.choice(non_any))
        self.archetype = archetype
        self.size = size

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        empty = bpy.data.objects.new("MengerPlaceholder", None)
        bpy.context.collection.objects.link(empty)
        return empty

    def create_asset(self, i: int = 0, placeholder=None, **params) -> bpy.types.Object:
        mod = _get_menger_module()
        sponge = mod.MengerSponge(_ARCHETYPE_TO_LEVEL[self.archetype])
        # The addon's `create(width, height)` API uses width=height; the
        # sponge is uniform-scaled by `size` here.
        verts, faces = sponge.create(self.size, self.size)

        mesh = bpy.data.meshes.new(f"Menger.{self.archetype}.{i}")
        mesh.from_pydata(verts, [], faces)
        mesh.update()
        obj = bpy.data.objects.new(mesh.name, mesh)
        bpy.context.collection.objects.link(obj)
        return obj

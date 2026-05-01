"""RealisticWormGearFactory — worm gear, wraps Blender's gear addon.

Source: `bl_ext.blender_org.extra_mesh_objects.add_mesh_gears.AddWormGearMesh`.
Different math from a regular spur gear: cylindrical body wrapped in a
helical screw thread that meshes with a perpendicular spur gear.

Pair with `RealisticGearFactory` for full mechanical assemblies — a
worm + spur is the canonical right-angle reduction pair in steampunk /
clockwork / mill scenes.

Archetype mapping (helix tightness + size):

    "compact"  : 12-tooth, 12 rows, tight helix
    "long"     : 8-tooth, 24 rows, gentle helix — for "screw" presentation
    "stout"    : 16-tooth, 8 rows, tight — wide power-transmission worm
    "any"      : random pick

License: GPL-2.0-or-later (bundled Blender addon).
"""

from __future__ import annotations

import importlib
import math
from types import SimpleNamespace

import bpy
import numpy as np

from infinigen.core.placement.factory import AssetFactory
from infinigen.core.util.math import FixedSeed


_WORM_ARCHETYPES = ("compact", "long", "stout", "any")

# Field names match what AddWormGearMesh reads off self.
_ARCHETYPE_PRESETS: dict[str, dict] = {
    "compact": {
        "number_of_teeth": 12, "number_of_rows": 12, "radius": 0.4,
        "addendum": 0.05, "dedendum": 0.05, "angle": math.radians(20.0),
        "row_height": 0.08, "skew": math.radians(11.0), "crown": 0.0,
    },
    "long": {
        "number_of_teeth": 8, "number_of_rows": 24, "radius": 0.3,
        "addendum": 0.04, "dedendum": 0.04, "angle": math.radians(20.0),
        "row_height": 0.12, "skew": math.radians(8.0), "crown": 0.0,
    },
    "stout": {
        "number_of_teeth": 16, "number_of_rows": 8, "radius": 0.6,
        "addendum": 0.07, "dedendum": 0.07, "angle": math.radians(20.0),
        "row_height": 0.15, "skew": math.radians(15.0), "crown": 0.0,
    },
}


def _get_gear_module():
    import addon_utils
    addon_utils.enable("bl_ext.blender_org.extra_mesh_objects", default_set=False)
    return importlib.import_module(
        "bl_ext.blender_org.extra_mesh_objects.add_mesh_gears"
    )


class RealisticWormGearFactory(AssetFactory):
    """Realistic worm-gear factory.

    Constructor knobs:

        factory_seed : int
        archetype : str = "compact"
            One of: compact / long / stout / any.
    """

    def __init__(
        self,
        factory_seed: int,
        archetype: str = "compact",
        coarse: bool = False,
    ):
        if archetype not in _WORM_ARCHETYPES:
            raise ValueError(
                f"archetype={archetype!r} not in {_WORM_ARCHETYPES}"
            )
        super().__init__(factory_seed, coarse=coarse)
        if archetype == "any":
            with FixedSeed(factory_seed):
                non_any = list(_ARCHETYPE_PRESETS.keys())
                archetype = str(np.random.choice(non_any))
        self.archetype = archetype

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        empty = bpy.data.objects.new("WormGearPlaceholder", None)
        bpy.context.collection.objects.link(empty)
        return empty

    def create_asset(self, i: int = 0, placeholder=None, **params) -> bpy.types.Object:
        gear_mod = _get_gear_module()
        sRef = SimpleNamespace(**_ARCHETYPE_PRESETS[self.archetype])
        mesh, _vt, _vv = gear_mod.AddWormGearMesh(sRef, bpy.context)
        mesh.name = f"WormGear.{self.archetype}.{i}"
        obj = bpy.data.objects.new(mesh.name, mesh)
        bpy.context.collection.objects.link(obj)
        return obj

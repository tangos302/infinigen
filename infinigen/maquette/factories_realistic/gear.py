"""RealisticGearFactory — sprocket / mechanical gear, wraps Blender's gear addon.

Source: `bl_ext.blender_org.extra_mesh_objects.add_mesh_gears`. The
addon's `AddGearMesh(self, context)` takes a settings reference and
returns a Blender Mesh — feed it a SimpleNamespace and skip the
operator.

Use for steampunk / clockwork / industrial machinery / old mill gearing
scenes. Pair with RealisticBeamFactory for full mechanical assemblies.

Archetype mapping (cosmetic geometric presets):

    "small"   : 12-tooth sprocket, ~0.4m radius
    "medium"  : 24-tooth gear, ~0.8m radius (canonical clockwork)
    "large"   : 48-tooth flywheel, ~1.5m radius
    "skewed"  : 18-tooth helical gear (skew=0.5)
    "any"     : random pick

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


_GEAR_ARCHETYPES = ("small", "medium", "large", "skewed", "any")

# Field names match what AddGearMesh reads off self.
_ARCHETYPE_PRESETS: dict[str, dict] = {
    "small":  {"number_of_teeth": 12, "radius": 0.4, "addendum": 0.05, "dedendum": 0.05,
               "base": 0.2, "angle": math.radians(20.0), "width": 0.1, "skew": 0.0,
               "conangle": 0.0, "crown": 0.0},
    "medium": {"number_of_teeth": 24, "radius": 0.8, "addendum": 0.08, "dedendum": 0.08,
               "base": 0.4, "angle": math.radians(20.0), "width": 0.15, "skew": 0.0,
               "conangle": 0.0, "crown": 0.0},
    "large":  {"number_of_teeth": 48, "radius": 1.5, "addendum": 0.12, "dedendum": 0.12,
               "base": 0.8, "angle": math.radians(20.0), "width": 0.2, "skew": 0.0,
               "conangle": 0.0, "crown": 0.0},
    "skewed": {"number_of_teeth": 18, "radius": 0.6, "addendum": 0.06, "dedendum": 0.06,
               "base": 0.3, "angle": math.radians(20.0), "width": 0.18, "skew": 0.5,
               "conangle": 0.0, "crown": 0.0},
}


def _get_gear_module():
    import addon_utils
    addon_utils.enable("bl_ext.blender_org.extra_mesh_objects", default_set=False)
    return importlib.import_module(
        "bl_ext.blender_org.extra_mesh_objects.add_mesh_gears"
    )


class RealisticGearFactory(AssetFactory):
    """Realistic gear factory.

    Constructor knobs:

        factory_seed : int
        archetype : str = "medium"
            One of: small / medium / large / skewed / any.
    """

    def __init__(
        self,
        factory_seed: int,
        archetype: str = "medium",
        coarse: bool = False,
    ):
        if archetype not in _GEAR_ARCHETYPES:
            raise ValueError(
                f"archetype={archetype!r} not in {_GEAR_ARCHETYPES}"
            )
        super().__init__(factory_seed, coarse=coarse)
        if archetype == "any":
            with FixedSeed(factory_seed):
                non_any = [a for a in _GEAR_ARCHETYPES if a != "any"]
                archetype = str(np.random.choice(non_any))
        self.archetype = archetype

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        empty = bpy.data.objects.new("GearPlaceholder", None)
        bpy.context.collection.objects.link(empty)
        return empty

    def create_asset(self, i: int = 0, placeholder=None, **params) -> bpy.types.Object:
        gear_mod = _get_gear_module()
        sRef = SimpleNamespace(**_ARCHETYPE_PRESETS[self.archetype])
        mesh, _vt, _vv = gear_mod.AddGearMesh(sRef, bpy.context)
        mesh.name = f"Gear.{self.archetype}.{i}"
        obj = bpy.data.objects.new(mesh.name, mesh)
        bpy.context.collection.objects.link(obj)
        return obj

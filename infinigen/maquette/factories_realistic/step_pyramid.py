"""RealisticStepPyramidFactory — ziggurat / step pyramid, wraps addon.

Source: `bl_ext.blender_org.extra_mesh_objects.add_mesh_pyramid`. The
addon's `pyramid_mesh(self, context)` reads a small set of attrs off
its operator and returns a Blender Mesh — feed it a SimpleNamespace
to skip the operator entirely.

Use for ancient ruins / temple / desert-civilization scenes. Tier 1
landmark: nobody else ships a procedural pyramid generator in
permissive Python.

Archetype mapping (cosmetic — upstream's only knobs are dimensional):

    "small"   : 4-step modest ziggurat (~6m base)
    "medium"  : 6-step Mesoamerican / Egyptian small (~10m base)
    "large"   : 9-step monumental ziggurat (~18m base)
    "tall"    : narrow 8-step temple-tower (e.g. Babel-style)
    "any"     : random pick at construction

License: GPL-2.0-or-later (bundled Blender addon).
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import bpy
import numpy as np

from infinigen.core.placement.factory import AssetFactory
from infinigen.core.util.math import FixedSeed


_PYRAMID_ARCHETYPES = ("small", "medium", "large", "tall", "any")

# (width, num_steps, step_height, reduce_by, num_sides)
_ARCHETYPE_PRESETS: dict[str, dict] = {
    "small":  {"width": 6.0, "num_steps": 4, "height": 0.6, "reduce_by": 1.2, "num_sides": 4},
    "medium": {"width": 10.0, "num_steps": 6, "height": 0.8, "reduce_by": 1.4, "num_sides": 4},
    "large":  {"width": 18.0, "num_steps": 9, "height": 1.0, "reduce_by": 1.6, "num_sides": 4},
    "tall":   {"width": 8.0, "num_steps": 8, "height": 1.4, "reduce_by": 0.8, "num_sides": 4},
}


def _get_pyramid_module():
    import addon_utils
    addon_utils.enable("bl_ext.blender_org.extra_mesh_objects", default_set=False)
    return importlib.import_module(
        "bl_ext.blender_org.extra_mesh_objects.add_mesh_pyramid"
    )


class RealisticStepPyramidFactory(AssetFactory):
    """Realistic step-pyramid factory.

    Constructor knobs:

        factory_seed : int
        archetype : str = "medium"
            One of: small / medium / large / tall / any.
    """

    def __init__(
        self,
        factory_seed: int,
        archetype: str = "medium",
        coarse: bool = False,
    ):
        if archetype not in _PYRAMID_ARCHETYPES:
            raise ValueError(
                f"archetype={archetype!r} not in {_PYRAMID_ARCHETYPES}"
            )
        super().__init__(factory_seed, coarse=coarse)
        if archetype == "any":
            with FixedSeed(factory_seed):
                non_any = [a for a in _PYRAMID_ARCHETYPES if a != "any"]
                archetype = str(np.random.choice(non_any))
        self.archetype = archetype

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        empty = bpy.data.objects.new("PyramidPlaceholder", None)
        bpy.context.collection.objects.link(empty)
        return empty

    def create_asset(self, i: int = 0, placeholder=None, **params) -> bpy.types.Object:
        pyr_mod = _get_pyramid_module()
        preset = _ARCHETYPE_PRESETS[self.archetype]
        sRef = SimpleNamespace(**preset)
        mesh = pyr_mod.pyramid_mesh(sRef, bpy.context)
        mesh.name = f"Pyramid.{self.archetype}.{i}"
        obj = bpy.data.objects.new(mesh.name, mesh)
        bpy.context.collection.objects.link(obj)
        return obj

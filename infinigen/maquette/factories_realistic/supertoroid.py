"""RealisticSupertoroidFactory — parametric supertoroid, wraps addon.

Source: `bl_ext.blender_org.extra_mesh_objects.add_mesh_supertoroid.supertoroid`.
Returns `(verts, faces)` for a supertoroid (generalized torus where the
cross-section profile can be square-ish, round, or pinched).

Use for sculpture / abstract monuments / sci-fi rings. The two squareness
exponents (n1, n2) control the silhouette: n1=n2=1 is a regular torus;
n1=2 makes the cross-section square; n1=0.5 makes it diamond-pinched.

Archetype mapping (cosmetic preset names):

    "torus"     : standard ring (n1=n2=1)
    "ring"      : large radius / thin tube (decorative)
    "halo"      : square-ish cross-section (n1=2.5, n2=1)
    "donut"     : pinched cross-section (n1=0.6, n2=1)
    "any"       : random pick

License: GPL-2.0-or-later (bundled Blender addon).
"""

from __future__ import annotations

import importlib

import bpy
import numpy as np

from infinigen.core.placement.factory import AssetFactory
from infinigen.core.util.math import FixedSeed


_TOROID_ARCHETYPES = ("torus", "ring", "halo", "donut", "any")

# (R, r, u, v, n1, n2) — see supertoroid() docstring.
# R = big radius, r = small radius, u = ring segments, v = cross-section segments.
_ARCHETYPE_PRESETS: dict[str, tuple[float, float, int, int, float, float]] = {
    "torus":  (1.0,  0.25, 24, 12, 1.0, 1.0),
    "ring":   (1.5,  0.10, 32, 12, 1.0, 1.0),
    "halo":   (1.2,  0.30, 32, 16, 2.5, 1.0),
    "donut":  (1.0,  0.30, 24, 16, 0.6, 1.0),
}


def _get_toroid_module():
    import addon_utils
    addon_utils.enable("bl_ext.blender_org.extra_mesh_objects", default_set=False)
    return importlib.import_module(
        "bl_ext.blender_org.extra_mesh_objects.add_mesh_supertoroid"
    )


class RealisticSupertoroidFactory(AssetFactory):
    """Realistic supertoroid factory.

    Constructor knobs:

        factory_seed : int
        archetype : str = "torus"
            One of: torus / ring / halo / donut / any.
    """

    def __init__(
        self,
        factory_seed: int,
        archetype: str = "torus",
        coarse: bool = False,
    ):
        if archetype not in _TOROID_ARCHETYPES:
            raise ValueError(
                f"archetype={archetype!r} not in {_TOROID_ARCHETYPES}"
            )
        super().__init__(factory_seed, coarse=coarse)
        if archetype == "any":
            with FixedSeed(factory_seed):
                non_any = [a for a in _TOROID_ARCHETYPES if a != "any"]
                archetype = str(np.random.choice(non_any))
        self.archetype = archetype

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        empty = bpy.data.objects.new("SupertoroidPlaceholder", None)
        bpy.context.collection.objects.link(empty)
        return empty

    def create_asset(self, i: int = 0, placeholder=None, **params) -> bpy.types.Object:
        mod = _get_toroid_module()
        R, r, u, v, n1, n2 = _ARCHETYPE_PRESETS[self.archetype]
        verts, faces = mod.supertoroid(R, r, u, v, n1, n2)

        mesh = bpy.data.meshes.new(f"Supertoroid.{self.archetype}.{i}")
        mesh.from_pydata(verts, [], faces)
        mesh.update()
        obj = bpy.data.objects.new(mesh.name, mesh)
        bpy.context.collection.objects.link(obj)
        return obj

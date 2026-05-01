"""RealisticSolidFactory — Platonic / Archimedean solids, wraps addon.

Source: `bl_ext.blender_org.extra_mesh_objects.add_mesh_solid.createSolid`.
Returns `(verts, faces)` for a solid given (plato, vtrunc, etrunc, dual,
snub) — 5 Platonic seeds, optional vertex/edge truncation produces the
13 Archimedean solids and their Catalan duals.

Use for:
- Ancient temple props (icosahedron / dodecahedron — D&D-style "ritual gem")
- Sci-fi monuments (truncated icosahedron / soccer-ball pattern)
- Puzzle scenes (snub cube / rhombicuboctahedron)
- Magical artifacts (combined with RealisticGemstoneFactory)

Archetype mapping → (plato source, vtrunc, etrunc, snub):

    "tetrahedron"    : "4", 0.0, 0.0, "None"
    "cube"           : "6", 0.0, 0.0, "None"
    "octahedron"     : "8", 0.0, 0.0, "None"
    "dodecahedron"   : "12", 0.0, 0.0, "None"
    "icosahedron"    : "20", 0.0, 0.0, "None"
    "soccer_ball"    : "20", 1.0, 0.0, "None"  (truncated icosahedron)
    "snub_cube"      : "6", 0.0, 0.5, "Left"
    "any"            : random pick

License: GPL-2.0-or-later (bundled Blender addon).
"""

from __future__ import annotations

import importlib

import bpy
import numpy as np

from infinigen.core.placement.factory import AssetFactory
from infinigen.core.util.math import FixedSeed


_SOLID_ARCHETYPES = (
    "tetrahedron", "cube", "octahedron", "dodecahedron", "icosahedron",
    "soccer_ball", "snub_cube", "any",
)

# (plato_source, vtrunc, etrunc, snub)
_ARCHETYPE_PRESETS: dict[str, tuple[str, float, float, str]] = {
    "tetrahedron":  ("4",  0.0, 0.0, "None"),
    "cube":         ("6",  0.0, 0.0, "None"),
    "octahedron":   ("8",  0.0, 0.0, "None"),
    "dodecahedron": ("12", 0.0, 0.0, "None"),
    "icosahedron":  ("20", 0.0, 0.0, "None"),
    "soccer_ball":  ("20", 1.0, 0.0, "None"),
    "snub_cube":    ("6",  0.0, 0.5, "Left"),
}


def _get_solid_module():
    import addon_utils
    addon_utils.enable("bl_ext.blender_org.extra_mesh_objects", default_set=False)
    return importlib.import_module(
        "bl_ext.blender_org.extra_mesh_objects.add_mesh_solid"
    )


class RealisticSolidFactory(AssetFactory):
    """Realistic Platonic/Archimedean solid factory.

    Constructor knobs:

        factory_seed : int
        archetype : str = "icosahedron"
            One of: tetrahedron / cube / octahedron / dodecahedron /
            icosahedron / soccer_ball / snub_cube / any.
        size : float = 1.0  (radius of circumscribed sphere)
    """

    def __init__(
        self,
        factory_seed: int,
        archetype: str = "icosahedron",
        size: float = 1.0,
        coarse: bool = False,
    ):
        if archetype not in _SOLID_ARCHETYPES:
            raise ValueError(
                f"archetype={archetype!r} not in {_SOLID_ARCHETYPES}"
            )
        super().__init__(factory_seed, coarse=coarse)
        if archetype == "any":
            with FixedSeed(factory_seed):
                non_any = [a for a in _SOLID_ARCHETYPES if a != "any"]
                archetype = str(np.random.choice(non_any))
        self.archetype = archetype
        self.size = size

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        empty = bpy.data.objects.new("SolidPlaceholder", None)
        bpy.context.collection.objects.link(empty)
        return empty

    def create_asset(self, i: int = 0, placeholder=None, **params) -> bpy.types.Object:
        mod = _get_solid_module()
        plato, vtrunc, etrunc, snub = _ARCHETYPE_PRESETS[self.archetype]
        # createSolid signature: (plato, vtrunc, etrunc, dual, snub)
        # dual=False keeps the primal solid; True flips to the Catalan dual.
        verts, faces = mod.createSolid(plato, vtrunc, etrunc, False, snub)
        # createSolid returns Vector instances scaled to unit-circumsphere.
        scaled = [(self.size * v[0], self.size * v[1], self.size * v[2]) for v in verts]

        mesh = bpy.data.meshes.new(f"Solid.{self.archetype}.{i}")
        mesh.from_pydata(scaled, [], faces)
        mesh.update()
        obj = bpy.data.objects.new(mesh.name, mesh)
        bpy.context.collection.objects.link(obj)
        return obj

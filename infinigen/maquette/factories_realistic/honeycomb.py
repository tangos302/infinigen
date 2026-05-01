"""RealisticHoneycombFactory — hex-grid panel, wraps addon.

Source: `bl_ext.blender_org.extra_mesh_objects.add_mesh_honeycomb.honeycomb_geometry`.
Class with `generate()` method that returns `(verts, faces)` for a flat
hex grid with parametric cell size and wall thickness.

Use for sci-fi panels / decorative tiles / honeycomb structures /
beehive props. The grid is flat — combine with a SOLIDIFY modifier or
offset Z manually for chunky 3D panels.

Archetype mapping:

    "panel_small"  : 8x6 cells, fine — sci-fi computer panel
    "panel_large"  : 16x10 cells — large tile
    "beehive"      : 6x4 chunky cells — beehive comb
    "tile"         : 4x4, square aspect — single decorative panel
    "any"          : random pick

License: GPL-2.0-or-later (bundled Blender addon).
"""

from __future__ import annotations

import importlib

import bpy
import numpy as np

from infinigen.core.placement.factory import AssetFactory
from infinigen.core.util.math import FixedSeed


_HONEYCOMB_ARCHETYPES = ("panel_small", "panel_large", "beehive", "tile", "any")

# (rows, cols, cell_diameter D, edge_thickness E)
_ARCHETYPE_PRESETS: dict[str, tuple[int, int, float, float]] = {
    "panel_small": (6, 8, 0.20, 0.02),
    "panel_large": (10, 16, 0.18, 0.025),
    "beehive":     (4, 6, 0.40, 0.04),
    "tile":        (4, 4, 0.30, 0.03),
}


def _get_honeycomb_module():
    import addon_utils
    addon_utils.enable("bl_ext.blender_org.extra_mesh_objects", default_set=False)
    return importlib.import_module(
        "bl_ext.blender_org.extra_mesh_objects.add_mesh_honeycomb"
    )


class RealisticHoneycombFactory(AssetFactory):
    """Realistic honeycomb-panel factory.

    Constructor knobs:

        factory_seed : int
        archetype : str = "panel_small"
            One of: panel_small / panel_large / beehive / tile / any.
    """

    def __init__(
        self,
        factory_seed: int,
        archetype: str = "panel_small",
        coarse: bool = False,
    ):
        if archetype not in _HONEYCOMB_ARCHETYPES:
            raise ValueError(
                f"archetype={archetype!r} not in {_HONEYCOMB_ARCHETYPES}"
            )
        super().__init__(factory_seed, coarse=coarse)
        if archetype == "any":
            with FixedSeed(factory_seed):
                non_any = [a for a in _HONEYCOMB_ARCHETYPES if a != "any"]
                archetype = str(np.random.choice(non_any))
        self.archetype = archetype

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        empty = bpy.data.objects.new("HoneycombPlaceholder", None)
        bpy.context.collection.objects.link(empty)
        return empty

    def create_asset(self, i: int = 0, placeholder=None, **params) -> bpy.types.Object:
        mod = _get_honeycomb_module()
        rows, cols, D, E = _ARCHETYPE_PRESETS[self.archetype]
        hc = mod.honeycomb_geometry(rows, cols, D, E)
        verts, faces = hc.generate()

        mesh = bpy.data.meshes.new(f"Honeycomb.{self.archetype}.{i}")
        mesh.from_pydata(verts, [], faces)
        mesh.update()
        obj = bpy.data.objects.new(mesh.name, mesh)
        bpy.context.collection.objects.link(obj)
        return obj

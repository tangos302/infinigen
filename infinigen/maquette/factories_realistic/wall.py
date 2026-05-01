"""RealisticWallFactory — masonry wall, wraps Blender's Wallfactory addon.

Source: `bl_ext.blender_org.extra_mesh_objects` (the bundled "Add Mesh
Extra Objects" addon). The addon's `add_mesh_wallb` operator drives a
pure-Python mesh generator in `Blocks.createWall()` that returns
`(verts, faces)` arrays — no bpy.ops, no UI context required.

We bypass the operator entirely and call `createWall()` directly,
mutating the addon's module-level config dicts before each call. Same
geometry, headless-clean.

Archetype mapping → (settings, dims, opening, flags):

    "boundary"     : 12m × 1.8m brick wall, no openings — property line
    "fortress"     : 14m × 5m thick stone wall with crenellations
    "ruin"         : 8m × 3m wall with a doorway opening, low height var
    "tower_round"  : radial 360° wall, dome optional — round tower base
    "garden_low"   : 6m × 0.9m short brick wall — garden boundary

The geometry is real masonry (per-block subdivision, irregular bond),
not a flat plane — much higher fidelity than LowPolyFenceFactory's
stone_wall variant. Use for hero walls / castles / ruins where reading
"made of stones" matters.

License: Wallfactory.py is GPL-2.0-or-later (bundled Blender addon).
Our wrapper inherits GPL when distributed alongside; for songe-core
distribution, treat the realistic-mode wrapper as GPL-licensed too.
"""

from __future__ import annotations

import importlib

import bpy
import numpy as np
from bpy_extras import object_utils
from mathutils import Vector

from infinigen.core.placement.factory import AssetFactory
from infinigen.core.util.math import FixedSeed


_WALL_ARCHETYPES = ("boundary", "fortress", "ruin", "tower_round", "garden_low", "any")


def _get_blocks_module():
    """Import (and lazily enable) the Wallfactory's Blocks module.

    The addon ships as `bl_ext.blender_org.extra_mesh_objects`; we only
    need its Blocks submodule for the mesh generator. Enabling the
    addon idempotent-ly registers its operators too, which is harmless.
    """
    import addon_utils
    addon_utils.enable("bl_ext.blender_org.extra_mesh_objects", default_set=False)
    blocks = importlib.import_module("bl_ext.blender_org.extra_mesh_objects.Blocks")
    return blocks


# Archetype -> (settings overrides, dims, openingSpecs, radial?, slope?)
_ARCHETYPE_PRESETS: dict[str, dict] = {
    "boundary": {
        "settings": {"w": 0.6, "wv": 0.15, "h": 0.3, "hv": 0.05, "d": 0.25, "dv": 0.05,
                      "g": 0.05, "gv": 0.02, "f": 0.05, "fv": 0.02},
        "dims": {"s": -6.0, "e": 6.0, "b": 0.0, "t": 1.8},
        "openings": [],
        "radial": 0, "slope": 0,
    },
    "fortress": {
        "settings": {"w": 1.2, "wv": 0.4, "h": 0.6, "hv": 0.2, "d": 0.5, "dv": 0.1,
                      "g": 0.08, "gv": 0.03, "f": 0.1, "fv": 0.05, "ht": 0.4},
        "dims": {"s": -7.0, "e": 7.0, "b": 0.0, "t": 5.0},
        "openings": [
            # Crenellation: repeating square gaps along the top course.
            {"w": 0.4, "h": 0.4, "x": -6.4, "z": 4.7, "rp": 1, "b": 0.0,
             "v": 0, "vl": 0, "t": 0, "tl": 0},
        ],
        "radial": 0, "slope": 0,
    },
    "ruin": {
        "settings": {"w": 1.0, "wv": 0.5, "h": 0.5, "hv": 0.3, "d": 0.4, "dv": 0.15,
                      "g": 0.12, "gv": 0.06, "f": 0.15, "fv": 0.1},
        "dims": {"s": -4.0, "e": 4.0, "b": 0.0, "t": 3.0},
        "openings": [
            # Doorway-shaped void.
            {"w": 0.9, "h": 1.6, "x": 0.0, "z": 0.8, "rp": 0, "b": 0.05,
             "v": 0.4, "vl": 0, "t": 0.15, "tl": 0},
        ],
        "radial": 0, "slope": 0,
    },
    "tower_round": {
        "settings": {"w": 1.0, "wv": 0.2, "h": 0.5, "hv": 0.1, "d": 0.4, "dv": 0.05,
                      "g": 0.06, "gv": 0.02, "ht": 0.4},
        # Radial: dims s..e is theta range (radians). Full 2pi for a closed tower.
        "dims": {"s": 0.0, "e": float(2 * np.pi), "b": 2.0, "t": 7.0},
        "openings": [
            # Arrow slits: narrow tall openings spaced around.
            {"w": 0.15, "h": 0.8, "x": 0.5, "z": 4.0, "rp": 1.5, "b": 0.05,
             "v": 0.1, "vl": 0, "t": 0.1, "tl": 0},
        ],
        "radial": 1, "slope": 0,
    },
    "garden_low": {
        "settings": {"w": 0.4, "wv": 0.1, "h": 0.2, "hv": 0.05, "d": 0.2, "dv": 0.03,
                      "g": 0.04, "gv": 0.02, "f": 0.04, "fv": 0.02},
        "dims": {"s": -3.0, "e": 3.0, "b": 0.0, "t": 0.9},
        "openings": [],
        "radial": 0, "slope": 0,
    },
}


class RealisticWallFactory(AssetFactory):
    """Realistic masonry wall factory.

    Constructor knobs:

        factory_seed : int
        archetype : str = "boundary"
            One of: boundary / fortress / ruin / tower_round / garden_low / any.

    Returns a single mesh object with per-block geometry.
    """

    def __init__(
        self,
        factory_seed: int,
        archetype: str = "boundary",
        coarse: bool = False,
    ):
        if archetype not in _WALL_ARCHETYPES:
            raise ValueError(
                f"archetype={archetype!r} not in {_WALL_ARCHETYPES}"
            )
        super().__init__(factory_seed, coarse=coarse)
        if archetype == "any":
            with FixedSeed(factory_seed):
                non_any = [a for a in _WALL_ARCHETYPES if a != "any"]
                archetype = str(np.random.choice(non_any))
        self.archetype = archetype

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        # Lightweight Empty so spawn_asset's placeholder->asset bookkeeping
        # can delete it without taking the real mesh with it.
        empty = bpy.data.objects.new("WallPlaceholder", None)
        bpy.context.collection.objects.link(empty)
        return empty

    def create_asset(self, i: int = 0, placeholder=None, **params) -> bpy.types.Object:
        blocks = _get_blocks_module()
        preset = _ARCHETYPE_PRESETS[self.archetype]

        # Mutate module-level config in-place. The addon was designed for
        # a single-threaded UI session so this is the supported entry
        # point; we serialize calls implicitly via Blender's single bpy
        # interpreter.
        with FixedSeed(int(self.factory_seed) + i):
            for k, v in preset["settings"].items():
                blocks.settings[k] = v
            for k, v in preset["dims"].items():
                blocks.dims[k] = v
            blocks.openingSpecs[:] = list(preset["openings"])
            blocks.radialized = preset["radial"]
            blocks.slope = preset["slope"]
            blocks.bigBlock = 0
            blocks.shelfExt = 0
            blocks.stepMod = 0
            blocks.stepLeft = 0
            blocks.stepOnly = 0
            blocks.stepBack = 0
            blocks.shelfBack = 0

            verts, faces = blocks.createWall(
                blocks.radialized, blocks.slope, blocks.openingSpecs,
                blocks.bigBlock, blocks.shelfExt, blocks.shelfBack,
                blocks.stepMod, blocks.stepLeft, blocks.stepOnly,
                blocks.stepBack,
            )

        mesh = bpy.data.meshes.new(f"Wall.{self.archetype}.{i}")
        mesh.from_pydata(verts, [], faces)
        mesh.update()
        obj = bpy.data.objects.new(f"Wall.{self.archetype}.{i}", mesh)
        bpy.context.collection.objects.link(obj)
        return obj

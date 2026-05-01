"""RealisticBeamFactory — structural steel beams, wraps Blender's BeamBuilder.

Source: `bl_ext.blender_org.extra_mesh_objects.add_mesh_beam_builder`.
The addon's `addBeamMesh(sRef, context)` is a clean factored function
returning a Blender Mesh — we feed it a SimpleNamespace with the
beam parameters and skip the Operator UI layer entirely.

Archetype mapping → upstream `Type` enum (str):

    "box"   : "0"  — solid square beam (box profile)
    "u"     : "1"  — U-channel
    "c"     : "2"  — C-channel
    "l"     : "3"  — L-angle
    "i"     : "4"  — I-beam (the canonical structural shape)
    "t"     : "5"  — T-section
    "any"   : random pick at construction

Use for industrial / construction / scaffolding scenes, exposed
structural framework on warehouses or ruins, or props like fallen
girders. Polycount is tiny (~50-200 verts/beam) — instance freely.

License: GPL-2.0-or-later (bundled Blender addon).
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import bpy
import numpy as np

from infinigen.core.placement.factory import AssetFactory
from infinigen.core.util.math import FixedSeed


_BEAM_ARCHETYPES = ("box", "u", "c", "l", "i", "t", "any")

_ARCHETYPE_TO_TYPE: dict[str, str] = {
    "box": "0", "u": "1", "c": "2", "l": "3", "i": "4", "t": "5",
}


def _get_beam_module():
    import addon_utils
    addon_utils.enable("bl_ext.blender_org.extra_mesh_objects", default_set=False)
    return importlib.import_module(
        "bl_ext.blender_org.extra_mesh_objects.add_mesh_beam_builder"
    )


class RealisticBeamFactory(AssetFactory):
    """Realistic structural-beam factory.

    Constructor knobs:

        factory_seed : int
        archetype : str = "i"
            One of: box / u / c / l / i / t / any.
        length : float = 4.0  (beam Y-axis length, meters)
        width : float = 0.3   (beam X profile width)
        height : float = 0.4  (beam Z profile height)
        wall_thickness : float = 0.05  (only used for u/c/l/i/t profiles)
        edge_taper : float = 100.0  (0..100; 100 = sharp 90° flange edges)
    """

    def __init__(
        self,
        factory_seed: int,
        archetype: str = "i",
        length: float = 4.0,
        width: float = 0.3,
        height: float = 0.4,
        wall_thickness: float = 0.05,
        edge_taper: float = 100.0,
        coarse: bool = False,
    ):
        if archetype not in _BEAM_ARCHETYPES:
            raise ValueError(
                f"archetype={archetype!r} not in {_BEAM_ARCHETYPES}"
            )
        super().__init__(factory_seed, coarse=coarse)
        if archetype == "any":
            with FixedSeed(factory_seed):
                non_any = [a for a in _BEAM_ARCHETYPES if a != "any"]
                archetype = str(np.random.choice(non_any))
        self.archetype = archetype
        self.length = length
        self.width = width
        self.height = height
        self.wall_thickness = wall_thickness
        self.edge_taper = edge_taper

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        empty = bpy.data.objects.new("BeamPlaceholder", None)
        bpy.context.collection.objects.link(empty)
        return empty

    def create_asset(self, i: int = 0, placeholder=None, **params) -> bpy.types.Object:
        beam_mod = _get_beam_module()
        sRef = SimpleNamespace(
            Type=_ARCHETYPE_TO_TYPE[self.archetype],
            beamY=self.length,
            beamX=self.width,
            beamZ=self.height,
            beamW=self.wall_thickness,
            edgeA=self.edge_taper,
        )
        mesh = beam_mod.addBeamMesh(sRef, bpy.context)
        # addBeamMesh names the mesh "Beam" — rename for clarity in scene.
        mesh.name = f"Beam.{self.archetype}.{i}"
        obj = bpy.data.objects.new(mesh.name, mesh)
        bpy.context.collection.objects.link(obj)
        return obj

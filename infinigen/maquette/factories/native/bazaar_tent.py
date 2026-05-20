"""LowPolyBazaarTentFactory — desert bazaar / market tent.

The signature shelter of an oasis bazaar. A market stall (awning over a
table) reads as a generic medieval market; a bazaar reads through cloth
*tents* — peaked canopies clustered around the water and palms. Without
this prop an "oasis bazaar" collapses into "houses near a pool".

Build approach: four (or two) timber corner poles plus a cloth roof
built from explicit triangle/quad faces — a pyramidal peak, a ridged
tent, or an open lean-to awning — finished with a thin cloth valance
hanging from the eave. Flat-shaded throughout.

Archetypes:
  peaked       — square plan, four poles, a pyramidal cloth peak.
                 The classic bazaar tent. Default.
  ridge        — rectangular plan, a ridge-line roof with two gable
                 ends — a longer caravan tent.
  awning_open  — a lean-to: two tall back poles, two short front poles,
                 a single sloped canopy. A market-front stall tent.

Material slots:
  slot 0 = cloth canopy (roof + valance)   default `accent_red`
  slot 1 = timber poles                    default `wood`
"""

from __future__ import annotations

import random

import bmesh
import bpy

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_BAZAAR_TENT_ARCHETYPES = ("peaked", "ridge", "awning_open")


_ARCHETYPE_DEFAULTS = {
    "peaked": dict(
        width=3.0, depth=3.0, eave_height=2.3, peak_rise=1.5,
        canopy_color="accent_red", pole_color="wood",
    ),
    "ridge": dict(
        width=4.6, depth=3.0, eave_height=2.2, peak_rise=1.2,
        canopy_color="accent_red", pole_color="wood",
    ),
    "awning_open": dict(
        width=3.2, depth=2.6, eave_height=2.6, peak_rise=1.0,
        canopy_color="accent_red", pole_color="wood",
    ),
}


def _add_box(bm, center, size) -> tuple[int, int]:
    prev = len(bm.faces)
    res = bmesh.ops.create_cube(bm, size=1.0)
    cx, cy, cz = center
    sx, sy, sz = size
    for v in res["verts"]:
        v.co.x = v.co.x * sx + cx
        v.co.y = v.co.y * sy + cy
        v.co.z = v.co.z * sz + cz
    bm.faces.ensure_lookup_table()
    return prev, len(bm.faces)


def _add_face(bm, coords) -> tuple[int, int]:
    """Append one polygon from a list of (x, y, z) tuples."""
    prev = len(bm.faces)
    verts = [bm.verts.new(c) for c in coords]
    bm.faces.new(verts)
    bm.faces.ensure_lookup_table()
    return prev, len(bm.faces)


class LowPolyBazaarTentFactory(AssetFactory):
    """A low-poly cloth bazaar tent — the focal shelter of an oasis
    bazaar.

    The asset origin sits at the ground; all geometry is built upward
    from z=0.

    Constructor knobs:

        factory_seed
        bazaar_tent_archetype : str = "peaked"
                                "peaked" | "ridge" | "awning_open"
        width                 : float  plan width along x (m)
        depth                 : float  plan depth along y (m)
        eave_height           : float  pole / eave height (m)
        peak_rise             : float  roof rise above the eave (m)
        canopy_color          : str    slot 0 palette key
        pole_color            : str    slot 1 palette key
    """

    def __init__(
        self,
        factory_seed,
        bazaar_tent_archetype: str = "peaked",
        width: float | None = None,
        depth: float | None = None,
        eave_height: float | None = None,
        peak_rise: float | None = None,
        canopy_color: str | None = None,
        pole_color: str | None = None,
        coarse: bool = False,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if bazaar_tent_archetype not in _BAZAAR_TENT_ARCHETYPES:
            import sys
            print(
                f"[bazaar_tent_archetype] WARN: unknown bazaar_tent_archetype "
                f"{bazaar_tent_archetype!r}; falling back to {_BAZAAR_TENT_ARCHETYPES[0]!r}. "
                f"Valid: {_BAZAAR_TENT_ARCHETYPES}",
                file=sys.stderr,
            )
            bazaar_tent_archetype = _BAZAAR_TENT_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[bazaar_tent_archetype]
        self.bazaar_tent_archetype = bazaar_tent_archetype
        self.width = float(width if width is not None else d["width"])
        self.depth = float(depth if depth is not None else d["depth"])
        self.eave_height = float(eave_height if eave_height is not None else d["eave_height"])
        self.peak_rise = float(peak_rise if peak_rise is not None else d["peak_rise"])
        self.canopy_color = canopy_color or d["canopy_color"]
        self.pole_color = pole_color or d["pole_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyBazaarTent({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        bm = bmesh.new()
        canopy_faces: list[tuple[int, int]] = []
        pole_faces: list[tuple[int, int]] = []

        hw, hd = self.width / 2.0, self.depth / 2.0
        eh = self.eave_height
        pole_t = 0.13

        def pole(px, py, top):
            pole_faces.append(_add_box(bm, (px, py, top / 2.0), (pole_t, pole_t, top)))

        if self.bazaar_tent_archetype == "awning_open":
            # Lean-to: tall back poles, short front poles, one sloped quad.
            front_h = eh
            back_h = eh + self.peak_rise
            pole(-hw, hd, back_h)
            pole(hw, hd, back_h)
            pole(-hw, -hd, front_h)
            pole(hw, -hd, front_h)
            canopy_faces.append(_add_face(bm, [
                (-hw - 0.2, hd + 0.2, back_h), (hw + 0.2, hd + 0.2, back_h),
                (hw + 0.2, -hd - 0.2, front_h), (-hw - 0.2, -hd - 0.2, front_h),
            ]))
            eave_z = front_h
        elif self.bazaar_tent_archetype == "ridge":
            # Ridge tent: ridge line along x, two slope quads + 2 gables.
            for px in (-hw, hw):
                for py in (-hd, hd):
                    pole(px, py, eh)
            rz = eh + self.peak_rise
            r0 = (-hw, 0.0, rz)
            r1 = (hw, 0.0, rz)
            c = 0.2  # eave overhang
            canopy_faces.append(_add_face(bm, [
                (-hw - c, hd + c, eh), (hw + c, hd + c, eh), r1, r0]))
            canopy_faces.append(_add_face(bm, [
                (hw + c, -hd - c, eh), (-hw - c, -hd - c, eh), r0, r1]))
            canopy_faces.append(_add_face(bm, [
                (-hw - c, -hd - c, eh), (-hw - c, hd + c, eh), r0]))
            canopy_faces.append(_add_face(bm, [
                (hw + c, hd + c, eh), (hw + c, -hd - c, eh), r1]))
            eave_z = eh
        else:
            # Peaked: square plan, four poles, pyramidal cloth peak.
            for px in (-hw, hw):
                for py in (-hd, hd):
                    pole(px, py, eh)
            apex = (0.0, 0.0, eh + self.peak_rise)
            c = 0.2
            corners = [
                (-hw - c, -hd - c, eh), (hw + c, -hd - c, eh),
                (hw + c, hd + c, eh), (-hw - c, hd + c, eh),
            ]
            for k in range(4):
                canopy_faces.append(_add_face(
                    bm, [corners[k], corners[(k + 1) % 4], apex]))
            eave_z = eh

        # Cloth valance — a thin skirt hanging from the eave on all sides.
        val_h = 0.34
        vz = eave_z - val_h / 2.0
        canopy_faces.append(_add_box(bm, (0.0, hd, vz), (self.width + 0.4, 0.04, val_h)))
        canopy_faces.append(_add_box(bm, (0.0, -hd, vz), (self.width + 0.4, 0.04, val_h)))
        if self.bazaar_tent_archetype != "awning_open":
            canopy_faces.append(_add_box(bm, (hw, 0.0, vz), (0.04, self.depth + 0.4, val_h)))
            canopy_faces.append(_add_box(bm, (-hw, 0.0, vz), (0.04, self.depth + 0.4, val_h)))

        me = bpy.data.meshes.new(f"LowPolyBazaarTent({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(f"LowPolyBazaarTent({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)

        while len(obj.data.materials) < 2:
            obj.data.materials.append(None)
        for start, end in pole_faces:
            for i in range(start, end):
                obj.data.polygons[i].material_index = 1
        for start, end in canopy_faces:
            for i in range(start, end):
                obj.data.polygons[i].material_index = 0
        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(obj, [self.canopy_color, self.pole_color])
        return obj

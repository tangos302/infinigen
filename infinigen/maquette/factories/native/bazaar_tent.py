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
        canopy_alt_color="stucco",
    ),
    "ridge": dict(
        width=4.6, depth=3.0, eave_height=2.2, peak_rise=1.2,
        canopy_color="accent_red", pole_color="wood",
        canopy_alt_color="stucco",
    ),
    "awning_open": dict(
        width=3.2, depth=2.6, eave_height=2.6, peak_rise=1.0,
        canopy_color="foliage_amber", pole_color="wood",
        canopy_alt_color="stucco",
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
        canopy_alt_color: str | None = None,
        coarse: bool = False,
        **_unused_kwargs,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if _unused_kwargs:
            from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
            accept_unused_kwargs("LowPolyBazaarTentFactory", _unused_kwargs)
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
        import random as _random
        rng = _random.Random(int(factory_seed) + 28411)
        self._rng = rng

        def _dim(value, key, lo=0.93, hi=1.08):
            if value is not None:
                return float(value)
            return float(d[key]) * rng.uniform(lo, hi)

        self.width = _dim(width, "width")
        self.depth = _dim(depth, "depth")
        self.eave_height = _dim(eave_height, "eave_height", 0.95, 1.05)
        self.peak_rise = _dim(peak_rise, "peak_rise", 0.85, 1.15)
        self.canopy_color = canopy_color or d["canopy_color"]
        self.pole_color = pole_color or d["pole_color"]
        self.canopy_alt_color = canopy_alt_color or d["canopy_alt_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyBazaarTent({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        rng = self._rng
        bm = bmesh.new()
        canopy_faces: list[tuple[int, int]] = []
        alt_faces: list[tuple[int, int]] = []
        pole_faces: list[tuple[int, int]] = []
        striped = rng.random() < 0.72

        hw, hd = self.width / 2.0, self.depth / 2.0
        eh = self.eave_height
        pole_t = 0.13

        def pole(px, py, top):
            pole_faces.append(_add_box(bm, (px, py, top / 2.0), (pole_t, pole_t, top)))

        def cloth(target_idx, coords):
            (canopy_faces if target_idx % 2 == 0 or not striped
             else alt_faces).append(_add_face(bm, coords))

        def lerp(p0, p1, t):
            return tuple(a + (b - a) * t for a, b in zip(p0, p1))

        if self.bazaar_tent_archetype == "awning_open":
            # Lean-to: tall back poles, short front poles, sloped strips.
            front_h = eh
            back_h = eh + self.peak_rise
            pole(-hw, hd, back_h)
            pole(hw, hd, back_h)
            pole(-hw, -hd, front_h)
            pole(hw, -hd, front_h)
            b0 = (-hw - 0.2, hd + 0.2, back_h)
            b1 = (hw + 0.2, hd + 0.2, back_h)
            f1 = (hw + 0.2, -hd - 0.2, front_h)
            f0 = (-hw - 0.2, -hd - 0.2, front_h)
            n_strips = 5 if striped else 1
            for i in range(n_strips):
                t0, t1 = i / n_strips, (i + 1) / n_strips
                cloth(i, [lerp(b0, b1, t0), lerp(b0, b1, t1),
                          lerp(f0, f1, t1), lerp(f0, f1, t0)])
            eave_z = front_h
        elif self.bazaar_tent_archetype == "ridge":
            # Ridge tent: striped slope quads + solid gables.
            for px in (-hw, hw):
                for py in (-hd, hd):
                    pole(px, py, eh)
            rz = eh + self.peak_rise
            r0 = (-hw, 0.0, rz)
            r1 = (hw, 0.0, rz)
            c = 0.2  # eave overhang
            n_strips = 7 if striped else 1
            for (e0, e1, g0, g1) in (
                ((-hw - c, hd + c, eh), (hw + c, hd + c, eh), r0, r1),
                ((hw + c, -hd - c, eh), (-hw - c, -hd - c, eh), r1, r0),
            ):
                for i in range(n_strips):
                    t0, t1 = i / n_strips, (i + 1) / n_strips
                    cloth(i, [lerp(e0, e1, t0), lerp(e0, e1, t1),
                              lerp(g0, g1, t1), lerp(g0, g1, t0)])
            canopy_faces.append(_add_face(bm, [
                (-hw - c, -hd - c, eh), (-hw - c, hd + c, eh), r0]))
            canopy_faces.append(_add_face(bm, [
                (hw + c, hd + c, eh), (hw + c, -hd - c, eh), r1]))
            # Ridge finials.
            for rx in (-hw, hw):
                pole_faces.append(_add_box(bm, (rx, 0.0, rz + 0.05),
                                           (0.08, 0.08, 0.10)))
            eave_z = eh
        else:
            # Peaked: pyramidal cloth as a radial wedge fan — circus-tent
            # stripes — plus an apex finial and a little pennant.
            for px in (-hw, hw):
                for py in (-hd, hd):
                    pole(px, py, eh)
            apex_z = eh + self.peak_rise
            apex = (0.0, 0.0, apex_z)
            c = 0.2
            corners = [
                (-hw - c, -hd - c, eh), (hw + c, -hd - c, eh),
                (hw + c, hd + c, eh), (-hw - c, hd + c, eh),
            ]
            wedges_per_side = 3 if striped else 1
            widx = 0
            for k in range(4):
                c0, c1 = corners[k], corners[(k + 1) % 4]
                for i in range(wedges_per_side):
                    t0, t1 = i / wedges_per_side, (i + 1) / wedges_per_side
                    cloth(widx, [lerp(c0, c1, t0), lerp(c0, c1, t1), apex])
                    widx += 1
            pole_faces.append(_add_box(bm, (0.0, 0.0, apex_z + 0.05),
                                       (0.07, 0.07, 0.12)))
            if rng.random() < 0.6:
                prev = len(bm.faces)
                pz = apex_z + 0.10
                v0 = bm.verts.new((0.0, 0.0, pz + 0.16))
                v1 = bm.verts.new((0.0, 0.0, pz))
                v2 = bm.verts.new((0.42, 0.0, pz + 0.08))
                bm.verts.ensure_lookup_table()
                bm.faces.new((v0, v1, v2))
                bm.faces.ensure_lookup_table()
                alt_faces.append((prev, len(bm.faces)))
            eave_z = eh

        # Cloth valance — a thin skirt hanging from the eave on all sides.
        # Takes the alternate colour when the canopy is striped.
        val_h = 0.34
        vz = eave_z - val_h / 2.0
        val_target = alt_faces if striped else canopy_faces
        val_target.append(_add_box(bm, (0.0, hd, vz), (self.width + 0.4, 0.04, val_h)))
        val_target.append(_add_box(bm, (0.0, -hd, vz), (self.width + 0.4, 0.04, val_h)))
        if self.bazaar_tent_archetype != "awning_open":
            val_target.append(_add_box(bm, (hw, 0.0, vz), (0.04, self.depth + 0.4, val_h)))
            val_target.append(_add_box(bm, (-hw, 0.0, vz), (0.04, self.depth + 0.4, val_h)))

        me = bpy.data.meshes.new(f"LowPolyBazaarTent({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(f"LowPolyBazaarTent({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)

        while len(obj.data.materials) < 3:
            obj.data.materials.append(None)
        for start, end in pole_faces:
            for i in range(start, end):
                obj.data.polygons[i].material_index = 1
        for start, end in canopy_faces:
            for i in range(start, end):
                obj.data.polygons[i].material_index = 0
        for start, end in alt_faces:
            for i in range(start, end):
                obj.data.polygons[i].material_index = 2
        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(
            obj, [self.canopy_color, self.pole_color, self.canopy_alt_color]
        )
        return obj

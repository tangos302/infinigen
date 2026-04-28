"""LowPolyToriiFactory — Japanese-style torii gate.

Iconic Japanese-temple identifier per Attempt 19. Two vertical pillars
+ two horizontal beams (a top "kasagi" beam that curves up at the ends
and a lower "nuki" tie beam between the pillars). The vermilion-red
finish is what makes it instantly recognizable, but the silhouette
alone (Π-shape with overhang) is enough at low poly.

Archetypes:
  myojin     — classic shrine torii: top beam flares wider than pillars,
               with curved-up end "warps" (approximated as thicker end
               caps in low poly)
  shinmei    — simpler austere style: straight beams, no flares
               (older / less ornate)
  ryobu      — double-pillar style with small bracing legs at base
               (less common but distinct silhouette)

Material slots:
  slot 0 = pillars + main beams (default `accent_red` — vermilion)
  slot 1 = trim / accent caps   (default `rock_shadow` — black caps)
"""

from __future__ import annotations

import math

import bmesh
import bpy
from mathutils import Vector

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_TORII_ARCHETYPES = ("myojin", "shinmei", "ryobu")


_ARCHETYPE_DEFAULTS = {
    "myojin": dict(
        height=4.0, width=4.0,
        pillar_radius=0.18, pillar_taper=0.05,
        kasagi_height=0.30, kasagi_overhang=0.5, kasagi_curve_up=0.15,
        nuki_height=0.18, nuki_at_pct=0.78,
        has_bracing=False,
        gate_color="accent_red", accent_color="rock_shadow",
    ),
    "shinmei": dict(
        height=3.6, width=3.5,
        pillar_radius=0.16, pillar_taper=0.0,
        kasagi_height=0.20, kasagi_overhang=0.25, kasagi_curve_up=0.0,
        nuki_height=0.15, nuki_at_pct=0.80,
        has_bracing=False,
        gate_color="wood", accent_color="wood",
    ),
    "ryobu": dict(
        height=4.0, width=4.0,
        pillar_radius=0.20, pillar_taper=0.05,
        kasagi_height=0.30, kasagi_overhang=0.5, kasagi_curve_up=0.15,
        nuki_height=0.18, nuki_at_pct=0.78,
        has_bracing=True,
        gate_color="accent_red", accent_color="rock_shadow",
    ),
}


def _bm_face_count(bm) -> int:
    return len(bm.faces)


def _add_box(bm, cx, cy, cz, sx, sy, sz) -> int:
    n_before = _bm_face_count(bm)
    hx, hy, hz = sx / 2, sy / 2, sz / 2
    b00 = bm.verts.new((cx - hx, cy - hy, cz - hz))
    b10 = bm.verts.new((cx + hx, cy - hy, cz - hz))
    b11 = bm.verts.new((cx + hx, cy + hy, cz - hz))
    b01 = bm.verts.new((cx - hx, cy + hy, cz - hz))
    t00 = bm.verts.new((cx - hx, cy - hy, cz + hz))
    t10 = bm.verts.new((cx + hx, cy - hy, cz + hz))
    t11 = bm.verts.new((cx + hx, cy + hy, cz + hz))
    t01 = bm.verts.new((cx - hx, cy + hy, cz + hz))
    bm.verts.ensure_lookup_table()
    bm.faces.new((b00, b10, t10, t00))
    bm.faces.new((b10, b11, t11, t10))
    bm.faces.new((b11, b01, t01, t11))
    bm.faces.new((b01, b00, t00, t01))
    bm.faces.new((t00, t10, t11, t01))
    bm.faces.new((b00, b01, b11, b10))
    return _bm_face_count(bm) - n_before


def _add_box_slot(bm, slot_ranges, slot, cx, cy, cz, sx, sy, sz) -> None:
    s = _bm_face_count(bm)
    _add_box(bm, cx, cy, cz, sx, sy, sz)
    e = _bm_face_count(bm)
    slot_ranges.append((s, e, slot))


class LowPolyToriiFactory(AssetFactory):
    """A Japanese-style torii gate.

    Layout convention: gate spans along X axis (pillars at ±width/2),
    facing -Y direction. Caller positions and rotates.

    Constructor knobs:

        factory_seed
        torii_archetype : str = "myojin"
                          "myojin" | "shinmei" | "ryobu"
        height, width        : floats
        pillar_radius        : float
        pillar_taper         : float (0..1, narrows toward top)
        kasagi_height        : float (top beam thickness)
        kasagi_overhang      : float (overhang past pillars)
        kasagi_curve_up      : float (end caps lift) — myojin/ryobu only
        nuki_height          : float (tie-beam thickness)
        nuki_at_pct          : float (0..1, height fraction for tie beam)
        has_bracing          : bool  (ryobu small base bracing legs)
        gate_color           : str   slot 0
        accent_color         : str   slot 1
    """

    def __init__(
        self,
        factory_seed,
        torii_archetype: str = "myojin",
        height: float | None = None,
        width: float | None = None,
        pillar_radius: float | None = None,
        pillar_taper: float | None = None,
        kasagi_height: float | None = None,
        kasagi_overhang: float | None = None,
        kasagi_curve_up: float | None = None,
        nuki_height: float | None = None,
        nuki_at_pct: float | None = None,
        has_bracing: bool | None = None,
        gate_color: str | None = None,
        accent_color: str | None = None,
        coarse: bool = False,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if torii_archetype not in _TORII_ARCHETYPES:
            raise ValueError(
                f"unknown torii_archetype {torii_archetype!r}; "
                f"valid: {_TORII_ARCHETYPES}"
            )
        d = _ARCHETYPE_DEFAULTS[torii_archetype]
        self.torii_archetype = torii_archetype
        self.height = float(height if height is not None else d["height"])
        self.width = float(width if width is not None else d["width"])
        self.pillar_radius = float(pillar_radius if pillar_radius is not None else d["pillar_radius"])
        self.pillar_taper = float(pillar_taper if pillar_taper is not None else d["pillar_taper"])
        self.kasagi_height = float(kasagi_height if kasagi_height is not None else d["kasagi_height"])
        self.kasagi_overhang = float(kasagi_overhang if kasagi_overhang is not None else d["kasagi_overhang"])
        self.kasagi_curve_up = float(kasagi_curve_up if kasagi_curve_up is not None else d["kasagi_curve_up"])
        self.nuki_height = float(nuki_height if nuki_height is not None else d["nuki_height"])
        self.nuki_at_pct = float(nuki_at_pct if nuki_at_pct is not None else d["nuki_at_pct"])
        self.has_bracing = (
            bool(has_bracing) if has_bracing is not None else d["has_bracing"]
        )
        self.gate_color = gate_color or d["gate_color"]
        self.accent_color = accent_color or d["accent_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyTorii({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        bm = bmesh.new()
        slot_ranges: list[tuple[int, int, int]] = []

        H, W = self.height, self.width
        pr = self.pillar_radius
        pillar_size = pr * 2
        # Pillars are slightly thicker at the base than at the top (taper)
        # — at low poly we don't actually taper the geometry, just adjust
        # the overall thickness perception by using a single thickness =
        # pillar_radius * (1 - taper/2).
        pillar_thickness = pillar_size

        # Two vertical pillars at ±W/2
        for sign in (-1, 1):
            _add_box_slot(
                bm, slot_ranges, 0,
                sign * W / 2, 0, H / 2,
                pillar_thickness, pillar_thickness, H,
            )

        # Top "kasagi" beam — wider than pillar span, at top z
        kasagi_width = W + 2 * self.kasagi_overhang
        kasagi_z = H + self.kasagi_height / 2
        _add_box_slot(
            bm, slot_ranges, 0,
            0, 0, kasagi_z,
            kasagi_width, pillar_thickness * 1.4, self.kasagi_height,
        )
        # Optional curve-up end caps — thicker boxes at the ends, lifted
        # up by `kasagi_curve_up` to suggest the warped end style
        if self.kasagi_curve_up > 0:
            for sign in (-1, 1):
                end_x = sign * (W / 2 + self.kasagi_overhang)
                _add_box_slot(
                    bm, slot_ranges, 1,
                    end_x, 0, kasagi_z + self.kasagi_curve_up / 2,
                    pillar_thickness * 1.6, pillar_thickness * 1.4,
                    self.kasagi_height + self.kasagi_curve_up,
                )

        # Tie beam "nuki" — between pillars at nuki_at_pct of height
        nuki_z = H * self.nuki_at_pct
        nuki_length = W - pillar_thickness  # spans inside the pillars
        nuki_extra = pillar_thickness * 0.4  # ends poke out a bit
        _add_box_slot(
            bm, slot_ranges, 0,
            0, 0, nuki_z,
            nuki_length + 2 * nuki_extra, pillar_thickness * 1.0, self.nuki_height,
        )

        # Optional bracing legs at the base (ryobu style)
        if self.has_bracing:
            for sign in (-1, 1):
                # Small angled bracing leg — at low poly just a small
                # extra block at the base outside each pillar
                brace_x = sign * (W / 2 + pillar_thickness * 0.7)
                _add_box_slot(
                    bm, slot_ranges, 0,
                    brace_x, 0, H * 0.15,
                    pillar_thickness * 0.7, pillar_thickness * 0.7, H * 0.3,
                )

        me = bpy.data.meshes.new(f"LowPolyTorii({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(f"LowPolyTorii({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)

        while len(obj.data.materials) < 2:
            obj.data.materials.append(None)

        for start, end, slot in slot_ranges:
            for i in range(start, end):
                obj.data.polygons[i].material_index = slot

        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(obj, [self.gate_color, self.accent_color])
        return obj

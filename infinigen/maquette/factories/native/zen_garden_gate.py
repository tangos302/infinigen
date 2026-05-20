"""LowPolyZenGardenGateFactory — small traditional wooden garden gate.

Requested 2026-05-06 (1 attempt, zen garden scene). Distinct from
``LowPolyToriiFactory`` (which is the iconic shrine arch, no roof tiles
and no enclosing fence). This is a *sukiya-mon* style garden gate: two
posts, a small tiled roof, optional low side-walls.

Archetypes:
  roofed_wood — two posts + thick crossbeam + small tiled gable roof,
                low fence wings on either side. Reads "enclosed garden
                entrance".
  simple_post — two posts + horizontal beam + lattice slat between
                them, no roof. Reads "tea-house garden gate".
  hagi_arch  — two posts + curved beam joining them, no roof, no
                wings. Reads "moon gate" / informal garden marker.

Material slots:
  slot 0 = wood (posts + beam + lattice)
  slot 1 = roof tile (rock_shadow by default; only used by roofed_wood)
  slot 2 = stone base (rock_pale; used by roofed_wood for the post bases)
"""

from __future__ import annotations

import math

import bmesh
import bpy

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_GATE_ARCHETYPES = ("roofed_wood", "simple_post", "hagi_arch")


_ARCHETYPE_DEFAULTS = {
    "roofed_wood": dict(
        span=1.50, post_height=2.00, post_thickness=0.18,
        beam_thickness=0.20,
        has_roof=True, roof_overhang=0.35, roof_pitch=0.30,
        has_wings=True, wing_length=1.20, wing_height=0.55,
        has_base=True, base_thickness=0.10,
        wood_color="wood", roof_color="rock_shadow", base_color="rock_pale",
    ),
    "simple_post": dict(
        span=1.30, post_height=1.80, post_thickness=0.14,
        beam_thickness=0.16,
        has_roof=False, roof_overhang=0.0, roof_pitch=0.0,
        has_wings=False, wing_length=0.0, wing_height=0.0,
        has_base=False, base_thickness=0.0,
        wood_color="wood", roof_color="rock_shadow", base_color="rock_pale",
    ),
    "hagi_arch": dict(
        span=1.40, post_height=1.90, post_thickness=0.13,
        beam_thickness=0.14,
        has_roof=False, roof_overhang=0.0, roof_pitch=0.0,
        has_wings=False, wing_length=0.0, wing_height=0.0,
        has_base=False, base_thickness=0.0,
        wood_color="wood", roof_color="rock_shadow", base_color="rock_pale",
    ),
}


def _bm_face_count(bm) -> int:
    return len(bm.faces)


def _add_box(bm, slot_ranges, slot, cx, cy, cz, sx, sy, sz):
    start = _bm_face_count(bm)
    hx, hy, hz = sx / 2, sy / 2, sz / 2
    verts = [
        bm.verts.new((cx - hx, cy - hy, cz - hz)),
        bm.verts.new((cx + hx, cy - hy, cz - hz)),
        bm.verts.new((cx + hx, cy + hy, cz - hz)),
        bm.verts.new((cx - hx, cy + hy, cz - hz)),
        bm.verts.new((cx - hx, cy - hy, cz + hz)),
        bm.verts.new((cx + hx, cy - hy, cz + hz)),
        bm.verts.new((cx + hx, cy + hy, cz + hz)),
        bm.verts.new((cx - hx, cy + hy, cz + hz)),
    ]
    bm.verts.ensure_lookup_table()
    b00, b10, b11, b01, t00, t10, t11, t01 = verts
    bm.faces.new((b00, b10, t10, t00))
    bm.faces.new((b10, b11, t11, t10))
    bm.faces.new((b11, b01, t01, t11))
    bm.faces.new((b01, b00, t00, t01))
    bm.faces.new((t00, t10, t11, t01))
    bm.faces.new((b00, b01, b11, b10))
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))


def _add_gable_roof(bm, slot_ranges, slot, cx, cz, span, depth, pitch):
    """A peaked tile roof centered on x=cx, base at z=cz. Spans (X) is
    the eave-to-eave width; depth (Y) is gable-front-to-back; pitch is
    the height of the ridge above the eave. Two triangular gables + two
    rectangular tile faces."""
    start = _bm_face_count(bm)
    hx = span / 2
    hy = depth / 2
    # Eave corners (z=cz).
    e_fl = bm.verts.new((cx - hx, -hy, cz))
    e_fr = bm.verts.new((cx + hx, -hy, cz))
    e_br = bm.verts.new((cx + hx,  hy, cz))
    e_bl = bm.verts.new((cx - hx,  hy, cz))
    # Ridge ends (z = cz + pitch, at gable midline).
    r_f = bm.verts.new((cx, -hy, cz + pitch))
    r_b = bm.verts.new((cx,  hy, cz + pitch))
    bm.verts.ensure_lookup_table()
    # Two pitched tile faces.
    bm.faces.new((e_fl, e_fr, r_f))    # front gable triangle (front face)
    bm.faces.new((e_bl, r_b, e_br))    # back gable triangle (back face, opposite winding)
    bm.faces.new((e_fl, r_f, r_b, e_bl))  # left slope
    bm.faces.new((e_fr, e_br, r_b, r_f))  # right slope
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))


def _add_arched_beam(bm, slot_ranges, slot, cx, cy, cz, span, rise, thickness):
    """A shallow arched crossbeam from (cx-span/2, cz) to (cx+span/2, cz),
    peaking at (cx, cz+rise). Built as a continuous strip of quads
    swept along a parabola: each segment shares vertices with its
    neighbors so there are no visual gaps. Reads as a smooth low-poly
    arch with ~6 facets.

    The cross-section is a rectangle of size `thickness` in Y (depth)
    and `thickness` in Z (beam height); the upper edge follows the
    parabola, the lower edge runs parallel `thickness` below it. End
    caps are added so the beam reads as solid from any angle."""
    start = _bm_face_count(bm)
    n_seg = 8
    half_y = thickness / 2
    # Build N+1 cross-sections along the parabola, each with 4 verts.
    cross_sections: list[tuple] = []
    for i in range(n_seg + 1):
        t = i / n_seg
        x = cx - span / 2 + span * t
        z_top = cz + 4 * rise * t * (1 - t) + thickness
        z_bot = z_top - thickness
        v_bl = bm.verts.new((x, cy - half_y, z_bot))
        v_br = bm.verts.new((x, cy + half_y, z_bot))
        v_tr = bm.verts.new((x, cy + half_y, z_top))
        v_tl = bm.verts.new((x, cy - half_y, z_top))
        cross_sections.append((v_bl, v_br, v_tr, v_tl))
    bm.verts.ensure_lookup_table()
    # Stitch sections — 4 quads per segment (bottom, +Y side, top, -Y side).
    for i in range(n_seg):
        a_bl, a_br, a_tr, a_tl = cross_sections[i]
        b_bl, b_br, b_tr, b_tl = cross_sections[i + 1]
        bm.faces.new((a_bl, b_bl, b_br, a_br))  # bottom
        bm.faces.new((a_br, b_br, b_tr, a_tr))  # +Y side
        bm.faces.new((a_tr, b_tr, b_tl, a_tl))  # top
        bm.faces.new((a_tl, b_tl, b_bl, a_bl))  # -Y side
    # End caps.
    bl0, br0, tr0, tl0 = cross_sections[0]
    bm.faces.new((bl0, tl0, tr0, br0))  # start cap (faces -X)
    bl1, br1, tr1, tl1 = cross_sections[-1]
    bm.faces.new((bl1, br1, tr1, tl1))  # end cap (faces +X)
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))


class LowPolyZenGardenGateFactory(AssetFactory):
    """A traditional wooden garden gate — roofed, simple-post, or arch.

    Constructor knobs:
        factory_seed
        zen_gate_archetype : "roofed_wood" | "simple_post" | "hagi_arch"
        span : float — distance between post centers
        post_height, post_thickness : float
        beam_thickness : float
        roof_overhang, roof_pitch : float
        wing_length, wing_height : float
        wood_color, roof_color, base_color : palette keys
    """

    def __init__(
        self,
        factory_seed,
        zen_gate_archetype: str = "roofed_wood",
        span: float | None = None,
        post_height: float | None = None,
        post_thickness: float | None = None,
        beam_thickness: float | None = None,
        roof_overhang: float | None = None,
        roof_pitch: float | None = None,
        wing_length: float | None = None,
        wing_height: float | None = None,
        wood_color: str | None = None,
        roof_color: str | None = None,
        base_color: str | None = None,
        coarse: bool = False,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if zen_gate_archetype not in _GATE_ARCHETYPES:
            import sys
            print(
                f"[zen_gate_archetype] WARN: unknown {zen_gate_archetype!r}; "
                f"falling back to {_GATE_ARCHETYPES[0]!r}. "
                f"Valid: {_GATE_ARCHETYPES}",
                file=sys.stderr,
            )
            zen_gate_archetype = _GATE_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[zen_gate_archetype]
        self.zen_gate_archetype = zen_gate_archetype
        self.span = float(span if span is not None else d["span"])
        self.post_height = float(post_height if post_height is not None else d["post_height"])
        self.post_thickness = float(post_thickness if post_thickness is not None else d["post_thickness"])
        self.beam_thickness = float(beam_thickness if beam_thickness is not None else d["beam_thickness"])
        self.has_roof = bool(d["has_roof"])
        self.roof_overhang = float(roof_overhang if roof_overhang is not None else d["roof_overhang"])
        self.roof_pitch = float(roof_pitch if roof_pitch is not None else d["roof_pitch"])
        self.has_wings = bool(d["has_wings"])
        self.wing_length = float(wing_length if wing_length is not None else d["wing_length"])
        self.wing_height = float(wing_height if wing_height is not None else d["wing_height"])
        self.has_base = bool(d["has_base"])
        self.base_thickness = float(d["base_thickness"])
        self.wood_color = wood_color or d["wood_color"]
        self.roof_color = roof_color or d["roof_color"]
        self.base_color = base_color or d["base_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyZenGardenGate({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        bm = bmesh.new()
        slot_ranges: list[tuple[int, int, int]] = []

        half_span = self.span / 2
        pt = self.post_thickness
        bt = self.beam_thickness

        # Optional stone base under each post — roofed_wood only.
        if self.has_base:
            for sign in (-1, 1):
                _add_box(
                    bm, slot_ranges, 2,
                    sign * half_span, 0.0, self.base_thickness / 2,
                    pt * 1.6, pt * 1.6, self.base_thickness,
                )
        base_z = self.base_thickness if self.has_base else 0.0

        # Two posts.
        for sign in (-1, 1):
            _add_box(
                bm, slot_ranges, 0,
                sign * half_span, 0.0, base_z + self.post_height / 2,
                pt, pt, self.post_height,
            )

        beam_z = base_z + self.post_height - bt / 2

        # Crossbeam — straight box for roofed/simple, arched parabola for hagi.
        if self.zen_gate_archetype == "hagi_arch":
            _add_arched_beam(
                bm, slot_ranges, 0,
                cx=0.0, cy=0.0, cz=beam_z - bt / 2,
                span=self.span + pt, rise=0.35, thickness=bt,
            )
        else:
            _add_box(
                bm, slot_ranges, 0,
                0.0, 0.0, beam_z,
                self.span + pt, bt, bt,
            )

        # Lattice infill below the beam — simple_post archetype only.
        if self.zen_gate_archetype == "simple_post":
            # 3 horizontal slats spaced down from beam to ~mid-post.
            slat_top = beam_z - bt * 0.8
            for i in range(3):
                z = slat_top - i * 0.30
                _add_box(
                    bm, slot_ranges, 0,
                    0.0, 0.0, z,
                    self.span - pt, bt * 0.45, bt * 0.45,
                )

        # Gable roof — roofed_wood archetype only.
        if self.has_roof:
            roof_base = beam_z + bt / 2
            _add_gable_roof(
                bm, slot_ranges, 1,
                cx=0.0, cz=roof_base,
                span=self.span + pt + self.roof_overhang * 2,
                depth=self.roof_overhang * 2 + pt * 1.5,
                pitch=self.roof_pitch + 0.25,
            )

        # Low side-wings — roofed_wood archetype only.
        if self.has_wings:
            for sign in (-1, 1):
                wing_cx = sign * (half_span + self.wing_length / 2 + pt / 2)
                _add_box(
                    bm, slot_ranges, 0,
                    wing_cx, 0.0, base_z + self.wing_height / 2,
                    self.wing_length, pt * 0.6, self.wing_height,
                )
                # A thin coping board on top of the wing for shadow line.
                _add_box(
                    bm, slot_ranges, 1,
                    wing_cx, 0.0, base_z + self.wing_height + 0.03,
                    self.wing_length + pt * 0.4, pt * 0.9, 0.06,
                )

        me = bpy.data.meshes.new(f"LowPolyZenGardenGate({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(
            f"LowPolyZenGardenGate({self.factory_seed})", me,
        )
        bpy.context.scene.collection.objects.link(obj)
        while len(obj.data.materials) < 3:
            obj.data.materials.append(None)
        for start, end, slot in slot_ranges:
            for i in range(start, end):
                obj.data.polygons[i].material_index = slot
        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(obj, [self.wood_color, self.roof_color, self.base_color])
        return obj

"""LowPolyBellFactory — hanging bronze bell on a wooden frame.

Invented 2026-05-16. The temple/monastery/church vocabulary in the
catalog is thin; a bell is the strongest single-asset cue. Plausible
LLM request for any monastery, bell tower, watchtower-with-warning,
or village square scene.

Archetypes:
  temple — large hanging bell on a 2-post wooden frame with a small
           tile roof above. Reads "ring this when intruders / dawn".
  belfry — narrower bell on a tall H-frame, no roof. Reads "village
           square / clock tower interior".
  cattle — small cowbell hanging from a single beam, no posts. Reads
           "pasture / farm prop".

Material slots:
  slot 0 = bronze (rust_metal — dark bronze patina)
  slot 1 = wood (frame posts + beam)
  slot 2 = roof tile (rock_shadow — temple archetype only)
"""

from __future__ import annotations

import math

import bmesh
import bpy

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_BELL_ARCHETYPES = ("temple", "belfry", "cattle")


_ARCHETYPE_DEFAULTS = {
    "temple": dict(
        bell_height=0.85, bell_top_radius=0.20, bell_bot_radius=0.45,
        post_height=2.20, post_thickness=0.18,
        frame_span=1.30, beam_thickness=0.22,
        has_roof=True, roof_pitch=0.32, roof_overhang=0.50,
        has_floor_pad=True, pad_radius=0.95,
        bronze_color="rust_metal", wood_color="wood", roof_color="rock_shadow",
    ),
    "belfry": dict(
        bell_height=0.70, bell_top_radius=0.15, bell_bot_radius=0.35,
        post_height=2.50, post_thickness=0.14,
        frame_span=0.95, beam_thickness=0.18,
        has_roof=False, roof_pitch=0.0, roof_overhang=0.0,
        has_floor_pad=False, pad_radius=0.0,
        bronze_color="rust_metal", wood_color="wood", roof_color="rock_shadow",
    ),
    "cattle": dict(
        bell_height=0.20, bell_top_radius=0.05, bell_bot_radius=0.12,
        post_height=0.0, post_thickness=0.0,
        frame_span=0.30, beam_thickness=0.06,
        has_roof=False, roof_pitch=0.0, roof_overhang=0.0,
        has_floor_pad=False, pad_radius=0.0,
        bronze_color="rust_metal", wood_color="wood", roof_color="rock_shadow",
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


def _add_prism(bm, slot_ranges, slot, cz, radius, height, n_sides):
    start = _bm_face_count(bm)
    bot, top = [], []
    for s in range(n_sides):
        a = 2 * math.pi * s / n_sides
        x, y = radius * math.cos(a), radius * math.sin(a)
        bot.append(bm.verts.new((x, y, cz)))
        top.append(bm.verts.new((x, y, cz + height)))
    bm.verts.ensure_lookup_table()
    for s in range(n_sides):
        ns = (s + 1) % n_sides
        bm.faces.new((bot[s], bot[ns], top[ns], top[s]))
    bm.faces.new(list(reversed(bot)))
    bm.faces.new(top)
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))


def _add_bell(bm, slot_ranges, slot, cx, cy, cz_top, height, top_radius, bot_radius, n_sides):
    """A tapered cylinder — wider at the bottom — built as a stack of
    short rings. cz_top is where the bell hangs from (the crown).
    Bottom is at cz_top - height. The lip flares slightly past the
    geometric cone to read as a bell silhouette."""
    n_rings = 5
    start = _bm_face_count(bm)
    rings: list[list] = []
    # Profile points along the bell's height — wider at the bottom with
    # a small concave waist near the top (sounded-bell silhouette).
    # Each tuple is (z_offset_from_top_downward, radius_factor).
    profile = [
        (0.00, 1.00 * top_radius / max(top_radius, 1e-6)),  # crown (top)
        (0.14, top_radius * 1.20),                            # shoulder
        (0.45, top_radius + (bot_radius - top_radius) * 0.55),
        (0.78, top_radius + (bot_radius - top_radius) * 0.85),
        (0.93, bot_radius * 1.05),                            # flared lip
        (1.00, bot_radius * 0.92),                            # lip undercut
    ]
    # Substitute the first entry's radius with top_radius directly to
    # avoid division weirdness when both are tiny.
    profile[0] = (0.00, top_radius)
    for frac, r in profile:
        z = cz_top - frac * height
        ring = []
        for s in range(n_sides):
            a = 2 * math.pi * s / n_sides
            x = cx + r * math.cos(a)
            y = cy + r * math.sin(a)
            ring.append(bm.verts.new((x, y, z)))
        rings.append(ring)
    bm.verts.ensure_lookup_table()
    # Stitch rings.
    for k in range(len(rings) - 1):
        a_ring, b_ring = rings[k], rings[k + 1]
        for s in range(n_sides):
            ns = (s + 1) % n_sides
            bm.faces.new((a_ring[s], a_ring[ns], b_ring[ns], b_ring[s]))
    # Cap the crown (closed top) and leave the bottom open (a bell's
    # rim has thickness but at this poly count the open ring reads fine
    # and avoids a z-fight if/when a clapper gets added).
    bm.faces.new(rings[0])
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))


def _add_gable_roof(bm, slot_ranges, slot, cx, cz, span, depth, pitch):
    """Same gable as zen_garden_gate — kept inline so factories don't
    depend on each other."""
    start = _bm_face_count(bm)
    hx, hy = span / 2, depth / 2
    e_fl = bm.verts.new((cx - hx, -hy, cz))
    e_fr = bm.verts.new((cx + hx, -hy, cz))
    e_br = bm.verts.new((cx + hx,  hy, cz))
    e_bl = bm.verts.new((cx - hx,  hy, cz))
    r_f = bm.verts.new((cx, -hy, cz + pitch))
    r_b = bm.verts.new((cx,  hy, cz + pitch))
    bm.verts.ensure_lookup_table()
    bm.faces.new((e_fl, e_fr, r_f))
    bm.faces.new((e_bl, r_b, e_br))
    bm.faces.new((e_fl, r_f, r_b, e_bl))
    bm.faces.new((e_fr, e_br, r_b, r_f))
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))


class LowPolyBellFactory(AssetFactory):
    """A bronze bell on a wooden frame.

    Constructor knobs:
        factory_seed
        bell_archetype : "temple" | "belfry" | "cattle"
        n_sides : int — bell mesh radial segments (default 10)
        bronze_color, wood_color, roof_color : palette keys
    """

    def __init__(
        self,
        factory_seed,
        bell_archetype: str = "temple",
        n_sides: int = 10,
        bronze_color: str | None = None,
        wood_color: str | None = None,
        roof_color: str | None = None,
        coarse: bool = False,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if bell_archetype not in _BELL_ARCHETYPES:
            import sys
            print(
                f"[bell_archetype] WARN: unknown {bell_archetype!r}; "
                f"falling back to {_BELL_ARCHETYPES[0]!r}. "
                f"Valid: {_BELL_ARCHETYPES}",
                file=sys.stderr,
            )
            bell_archetype = _BELL_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[bell_archetype]
        self.bell_archetype = bell_archetype
        self.n_sides = max(6, int(n_sides))
        self.d = d
        self.bronze_color = bronze_color or d["bronze_color"]
        self.wood_color = wood_color or d["wood_color"]
        self.roof_color = roof_color or d["roof_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyBell({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        bm = bmesh.new()
        slot_ranges: list[tuple[int, int, int]] = []
        d = self.d

        # Optional stone pad under the frame (temple archetype only).
        if d["has_floor_pad"]:
            _add_prism(
                bm, slot_ranges, 1,
                cz=0.0, radius=d["pad_radius"], height=0.08, n_sides=8,
            )
        pad_z = 0.08 if d["has_floor_pad"] else 0.0

        post_h = d["post_height"]
        post_t = d["post_thickness"]
        span = d["frame_span"]
        beam_t = d["beam_thickness"]

        if post_h > 0:
            # Two posts.
            for sign in (-1, 1):
                _add_box(
                    bm, slot_ranges, 1,
                    sign * span / 2, 0.0, pad_z + post_h / 2,
                    post_t, post_t, post_h,
                )
            # Horizontal beam across the top.
            beam_z = pad_z + post_h - beam_t / 2
            _add_box(
                bm, slot_ranges, 1,
                0.0, 0.0, beam_z,
                span + post_t, beam_t, beam_t,
            )
            # Diagonal braces from each post-top to the beam — small
            # silhouette cue, very visible from the side.
            brace_len = post_t * 2.4
            for sign in (-1, 1):
                _add_box(
                    bm, slot_ranges, 1,
                    sign * (span / 2 - brace_len * 0.35),
                    0.0,
                    beam_z - brace_len * 0.25,
                    brace_len, beam_t * 0.55, beam_t * 0.55,
                )
            bell_top_z = beam_z - beam_t / 2
        else:
            # Cattle archetype: no posts, just hang the bell from a tiny
            # ring above. Beam_z is at the bell top.
            beam_z = d["bell_height"] + 0.05
            _add_box(
                bm, slot_ranges, 1,
                0.0, 0.0, beam_z,
                span, beam_t, beam_t,
            )
            bell_top_z = beam_z - beam_t / 2

        # Hanger — a small ring/loop between beam and bell crown.
        hanger_h = 0.10
        _add_box(
            bm, slot_ranges, 0,
            0.0, 0.0, bell_top_z - hanger_h / 2,
            0.06, 0.06, hanger_h,
        )

        # The bell itself.
        bell_top = bell_top_z - hanger_h
        _add_bell(
            bm, slot_ranges, 0,
            cx=0.0, cy=0.0, cz_top=bell_top,
            height=d["bell_height"],
            top_radius=d["bell_top_radius"],
            bot_radius=d["bell_bot_radius"],
            n_sides=self.n_sides,
        )

        # Optional gable roof above the frame (temple archetype only).
        if d["has_roof"]:
            roof_z = pad_z + post_h + beam_t / 2 + 0.05
            _add_gable_roof(
                bm, slot_ranges, 2,
                cx=0.0, cz=roof_z,
                span=span + post_t + d["roof_overhang"] * 2,
                depth=d["roof_overhang"] * 2 + post_t * 2,
                pitch=d["roof_pitch"],
            )

        me = bpy.data.meshes.new(f"LowPolyBell({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(
            f"LowPolyBell({self.factory_seed})", me,
        )
        bpy.context.scene.collection.objects.link(obj)
        while len(obj.data.materials) < 3:
            obj.data.materials.append(None)
        for start, end, slot in slot_ranges:
            for i in range(start, end):
                obj.data.polygons[i].material_index = slot
        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(obj, [self.bronze_color, self.wood_color, self.roof_color])
        return obj

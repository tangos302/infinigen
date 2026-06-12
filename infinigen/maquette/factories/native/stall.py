"""LowPolyStallFactory — marketplace stall with awning canopy.

Top marketplace factory per Attempt 11 — the awning silhouette is the
single biggest visual cue that distinguishes "stall" from "fence with
crates". Reusable across food / fish / textile / fortune-teller stalls
just by varying the `awning_color` slot.

Archetypes:
  open         — 4 corner posts + sloped front-low awning + table
                 (basic market stall — most common)
  closed_back  — same as open + a back wall
                 (small shop, fishmonger, weather-protected goods)
  double       — 6 posts forming two adjacent stalls under a wider
                 awning (food court / butcher's row)

Knobs let callers vary the awning color to spawn a row of varied
stalls without rebuilding the geometry.

Material slots:
  slot 0 = wooden frame (posts, rails)
  slot 1 = awning cloth + side curtain   (default `accent_red`)
  slot 2 = table top / counter / back wall (default same as frame)
  slot 3 = table goods
  slot 4 = awning alternate stripe       (default `stucco`)
"""

from __future__ import annotations

import math
import random

import bmesh
import bpy
from mathutils import Vector

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_STALL_ARCHETYPES = ("open", "closed_back", "double")


_ARCHETYPE_DEFAULTS = {
    "open": dict(
        length=2.25, width=1.35,
        post_height=2.15, post_radius=0.055,
        awning_pitch=0.55, awning_overhang=0.30,
        has_table=True, table_height=0.85, table_thickness=0.05,
        has_back_wall=False, back_wall_height=0.0,
        goods_count=5,
        is_double=False,
        frame_color="wood", awning_color="accent_red", table_color="wood",
        goods_color="foliage_amber", awning_alt_color="stucco",
    ),
    "closed_back": dict(
        length=2.25, width=1.35,
        post_height=2.15, post_radius=0.055,
        awning_pitch=0.55, awning_overhang=0.30,
        has_table=True, table_height=0.85, table_thickness=0.05,
        has_back_wall=True, back_wall_height=1.7,
        goods_count=4,
        is_double=False,
        frame_color="wood", awning_color="foliage_amber", table_color="wood",
        goods_color="ground_sand", awning_alt_color="stucco",
    ),
    "double": dict(
        length=4.0, width=1.35,
        post_height=2.15, post_radius=0.055,
        awning_pitch=0.55, awning_overhang=0.32,
        has_table=True, table_height=0.85, table_thickness=0.05,
        has_back_wall=False, back_wall_height=0.0,
        goods_count=8,
        is_double=True,
        frame_color="wood", awning_color="foliage_apple", table_color="wood",
        goods_color="foliage_lemon", awning_alt_color="stucco",
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


def _add_striped_awning(
    bm, slot_ranges,
    length: float, width: float,
    front_z: float, back_z: float,
    overhang: float,
    *,
    slot_a: int, slot_b: int,
    n_strips: int,
    scallop_drop: float = 0.16,
) -> None:
    """Sloped market awning: alternating colour strips running down the
    slope, with a scalloped (triangle) valance hanging off the front edge.
    With n_strips=1 the cloth is a single colour but keeps the scallops.
    Front of stall is -Y; stall body extends along X."""
    hx = length / 2 + overhang
    front_y = -width / 2 - overhang
    back_y = +width / 2
    step = (2 * hx) / n_strips
    for i in range(n_strips):
        slot = slot_a if i % 2 == 0 else slot_b
        x0 = -hx + i * step
        x1 = x0 + step
        start = _bm_face_count(bm)
        bL = bm.verts.new((x0, back_y, back_z))
        bR = bm.verts.new((x1, back_y, back_z))
        fR = bm.verts.new((x1, front_y, front_z))
        fL = bm.verts.new((x0, front_y, front_z))
        bm.verts.ensure_lookup_table()
        bm.faces.new((bL, bR, fR, fL))
        # Scallop triangle hanging from this strip's front edge.
        s0 = bm.verts.new((x0, front_y, front_z))
        s1 = bm.verts.new((x1, front_y, front_z))
        s2 = bm.verts.new(((x0 + x1) / 2, front_y, front_z - scallop_drop))
        bm.verts.ensure_lookup_table()
        bm.faces.new((s0, s1, s2))
        slot_ranges.append((start, _bm_face_count(bm), slot))


class LowPolyStallFactory(AssetFactory):
    """A marketplace stall — wooden frame + sloped cloth awning + optional
    table + optional back wall.

    Layout convention: front of stall faces -Y direction, length axis is X.
    Caller is expected to rotate / position the result.

    Constructor knobs:

        factory_seed
        stall_archetype : str = "open"
                          "open" | "closed_back" | "double"
        length, width   : float
        post_height     : float
        post_radius     : float
        awning_pitch    : float    front-low: pitch is z-drop from back to front
        awning_overhang : float    awning extends past frame
        has_table       : bool
        table_height    : float
        table_thickness : float
        has_back_wall   : bool
        back_wall_height : float
        frame_color     : str    slot 0
        awning_color    : str    slot 1
        table_color     : str    slot 2 (table + back wall)
        goods_color     : str    slot 3 (visible table goods + signs)
    """

    def __init__(
        self,
        factory_seed,
        stall_archetype: str = "open",
        length: float | None = None,
        width: float | None = None,
        post_height: float | None = None,
        post_radius: float | None = None,
        awning_pitch: float | None = None,
        awning_overhang: float | None = None,
        has_table: bool | None = None,
        table_height: float | None = None,
        table_thickness: float | None = None,
        has_back_wall: bool | None = None,
        back_wall_height: float | None = None,
        goods_count: int | None = None,
        frame_color: str | None = None,
        awning_color: str | None = None,
        table_color: str | None = None,
        goods_color: str | None = None,
        awning_alt_color: str | None = None,
        coarse: bool = False,
        **_unused_kwargs,
    ):
        from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
        accept_unused_kwargs("LowPolyStallFactory", _unused_kwargs)
        super().__init__(factory_seed, coarse=coarse)
        if stall_archetype not in _STALL_ARCHETYPES:
            # Lenient fallback rather than crash. Sonnet has been
            # observed to hallucinate plausible-sounding archetype
            # names despite the factories_guide brief listing the
            # valid set; killing a 6-minute build over a one-line
            # archetype typo wastes a generation. Substitute the
            # canonical default and warn to stderr.
            import sys
            print(
                f"[stall_archetype] WARN: unknown stall_archetype "
                f"{stall_archetype!r}; falling back to {_STALL_ARCHETYPES[0]!r}. "
                f"Valid: {_STALL_ARCHETYPES}",
                file=sys.stderr,
            )
            stall_archetype = _STALL_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[stall_archetype]
        self.stall_archetype = stall_archetype
        self.length = float(length if length is not None else d["length"])
        self.width = float(width if width is not None else d["width"])
        self.post_height = float(post_height if post_height is not None else d["post_height"])
        self.post_radius = float(post_radius if post_radius is not None else d["post_radius"])
        self.awning_pitch = float(awning_pitch if awning_pitch is not None else d["awning_pitch"])
        self.awning_overhang = float(awning_overhang if awning_overhang is not None else d["awning_overhang"])
        self.has_table = (
            bool(has_table) if has_table is not None else d["has_table"]
        )
        self.table_height = float(table_height if table_height is not None else d["table_height"])
        self.table_thickness = float(table_thickness if table_thickness is not None else d["table_thickness"])
        self.has_back_wall = (
            bool(has_back_wall) if has_back_wall is not None else d["has_back_wall"]
        )
        self.back_wall_height = float(back_wall_height if back_wall_height is not None else d["back_wall_height"])
        self.goods_count = int(goods_count if goods_count is not None else d["goods_count"])
        self.is_double = bool(d["is_double"])
        self.frame_color = frame_color or d["frame_color"]
        self.awning_color = awning_color or d["awning_color"]
        self.table_color = table_color or d["table_color"]
        self.goods_color = goods_color or d["goods_color"]
        self.awning_alt_color = awning_alt_color or d["awning_alt_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyStall({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        rng = random.Random(self.factory_seed)
        bm = bmesh.new()
        slot_ranges: list[tuple[int, int, int]] = []

        L, W, H = self.length, self.width, self.post_height
        pr = self.post_radius
        ps = pr * 2  # post side length

        # The awning plane: back edge rides above the back posts, front edge
        # drops by `awning_pitch`. Front posts stop at the cloth so they
        # don't pierce it.
        awn_back_z = H + 0.06
        awn_front_z = H - self.awning_pitch
        awn_back_y = W / 2
        awn_front_y = -W / 2 - self.awning_overhang

        def _cloth_z(y: float) -> float:
            t = (awn_back_y - y) / (awn_back_y - awn_front_y)
            return awn_back_z - (awn_back_z - awn_front_z) * t

        front_post_h = _cloth_z(-W / 2 + pr) - 0.03

        # Posts at corners (and middle for double-stall)
        post_xs = [-L/2 + pr, L/2 - pr]
        if self.is_double:
            post_xs = [-L/2 + pr, 0.0, L/2 - pr]
        for px in post_xs:
            _add_box_slot(bm, slot_ranges, 0, px, -W/2 + pr,
                          front_post_h / 2, ps, ps, front_post_h)
            _add_box_slot(bm, slot_ranges, 0, px, W/2 - pr, H/2, ps, ps, H)

        # Awning — striped sloped cloth with a scalloped valance. The back
        # edge rides above the posts, the front edge drops by `awning_pitch`
        # so the slope reads even from the default high camera.
        striped = rng.random() < 0.70
        if striped:
            n_strips = 9 if self.is_double else 7
        else:
            n_strips = 1
        _add_striped_awning(
            bm, slot_ranges,
            L, W, awn_front_z, awn_back_z, self.awning_overhang,
            slot_a=1, slot_b=4, n_strips=n_strips,
        )

        # Upper wooden rails tie the posts together and improve the silhouette
        # when the stall is seen from a distance. Front + side rails sit
        # below the lowered front posts so nothing pierces the cloth.
        rail_front_z = front_post_h - 0.16
        rail_back_z = H - 0.18
        _add_box_slot(bm, slot_ranges, 0, 0.0, -W / 2 + pr, rail_front_z, L, ps, ps)
        _add_box_slot(bm, slot_ranges, 0, 0.0, +W / 2 - pr, rail_back_z, L, ps, ps)
        _add_box_slot(bm, slot_ranges, 0, -L / 2 + pr, 0.0, rail_front_z, ps, W, ps)
        _add_box_slot(bm, slot_ranges, 0, +L / 2 - pr, 0.0, rail_front_z, ps, W, ps)

        # Table — flat surface inside the stall, with a solid counter front
        # so the stall has body below the tabletop.
        if self.has_table:
            tz = self.table_height
            _add_box_slot(
                bm, slot_ranges, 2,
                0, 0, tz + self.table_thickness / 2,
                L - 2 * pr, W - 2 * pr, self.table_thickness,
            )
            if rng.random() < 0.78:
                panel_h = tz - 0.06
                _add_box_slot(
                    bm, slot_ranges, 2,
                    0, -W / 2 + pr + 0.02, panel_h / 2 + 0.02,
                    L - 2 * pr, 0.045, panel_h,
                )
            for _ in range(max(0, self.goods_count)):
                gx = rng.uniform(-L * 0.36, L * 0.36)
                gy = rng.uniform(-W * 0.30, W * 0.12)  # bias toward the front
                gs = rng.uniform(0.10, 0.18)
                _add_box_slot(
                    bm, slot_ranges, 3,
                    gx, gy, tz + self.table_thickness + gs * 0.5,
                    gs * rng.uniform(1.0, 1.8),
                    gs * rng.uniform(0.9, 1.4),
                    gs * rng.uniform(0.7, 1.6),
                )

        # Side curtain — a tied-back cloth on one end, seed-gated. Adds
        # asymmetry so a row of stalls doesn't read as clones. Its top stays
        # under the sloping cloth at the curtain's front edge.
        if rng.random() < 0.40:
            side = rng.choice((-1.0, 1.0))
            cx = side * (L / 2 - pr - 0.02)
            curt_top = _cloth_z(-W * 0.37) - 0.06
            curt_h = curt_top - 0.35
            _add_box_slot(
                bm, slot_ranges, 1,
                cx, 0.0, 0.35 + curt_h / 2,
                0.04, W * 0.74, curt_h,
            )

        # Back wall — vertical panel along the back edge (+Y)
        if self.has_back_wall and self.back_wall_height > 0:
            wt = 0.04  # wall thickness
            _add_box_slot(
                bm, slot_ranges, 2,
                0, W/2 - wt/2, self.back_wall_height / 2,
                L, wt, self.back_wall_height,
            )

        me = bpy.data.meshes.new(f"LowPolyStall({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(f"LowPolyStall({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)

        while len(obj.data.materials) < 5:
            obj.data.materials.append(None)

        for start, end, slot in slot_ranges:
            for i in range(start, end):
                obj.data.polygons[i].material_index = slot

        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(
            obj, [self.frame_color, self.awning_color, self.table_color,
                  self.goods_color, self.awning_alt_color]
        )
        return obj

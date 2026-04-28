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
  slot 1 = awning cloth                  (default `accent_red`)
  slot 2 = table top + back wall         (default same as frame)
"""

from __future__ import annotations

import math

import bmesh
import bpy
from mathutils import Vector

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_STALL_ARCHETYPES = ("open", "closed_back", "double")


_ARCHETYPE_DEFAULTS = {
    "open": dict(
        length=1.8, width=1.1,
        post_height=2.0, post_radius=0.04,
        awning_pitch=0.3, awning_overhang=0.18,
        has_table=True, table_height=0.85, table_thickness=0.05,
        has_back_wall=False, back_wall_height=0.0,
        is_double=False,
        frame_color="wood", awning_color="accent_red", table_color="wood",
    ),
    "closed_back": dict(
        length=1.8, width=1.1,
        post_height=2.0, post_radius=0.04,
        awning_pitch=0.3, awning_overhang=0.18,
        has_table=True, table_height=0.85, table_thickness=0.05,
        has_back_wall=True, back_wall_height=1.7,
        is_double=False,
        frame_color="wood", awning_color="foliage_amber", table_color="wood",
    ),
    "double": dict(
        length=3.4, width=1.1,
        post_height=2.0, post_radius=0.04,
        awning_pitch=0.3, awning_overhang=0.20,
        has_table=True, table_height=0.85, table_thickness=0.05,
        has_back_wall=False, back_wall_height=0.0,
        is_double=True,
        frame_color="wood", awning_color="foliage_apple", table_color="wood",
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


def _add_awning_quad(
    bm, slot_ranges, slot,
    length: float, width: float,
    front_z: float, back_z: float,
    overhang: float,
) -> None:
    """A single sloped quad — front edge lower than back. Front edge
    overhangs by `overhang` on +Y (front) and slightly on -Y (back).
    Stall body extends along X."""
    start = _bm_face_count(bm)
    hx = length / 2 + overhang
    front_y = -width / 2 - overhang   # front of stall is at -Y
    back_y = +width / 2
    # 4 corners
    fL = bm.verts.new((-hx, front_y, front_z))
    fR = bm.verts.new(( hx, front_y, front_z))
    bR = bm.verts.new(( hx, back_y, back_z))
    bL = bm.verts.new((-hx, back_y, back_z))
    bm.verts.ensure_lookup_table()
    bm.faces.new((fL, fR, bR, bL))
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))


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
        frame_color: str | None = None,
        awning_color: str | None = None,
        table_color: str | None = None,
        coarse: bool = False,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if stall_archetype not in _STALL_ARCHETYPES:
            raise ValueError(
                f"unknown stall_archetype {stall_archetype!r}; "
                f"valid: {_STALL_ARCHETYPES}"
            )
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
        self.is_double = bool(d["is_double"])
        self.frame_color = frame_color or d["frame_color"]
        self.awning_color = awning_color or d["awning_color"]
        self.table_color = table_color or d["table_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyStall({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        bm = bmesh.new()
        slot_ranges: list[tuple[int, int, int]] = []

        L, W, H = self.length, self.width, self.post_height
        pr = self.post_radius
        ps = pr * 2  # post side length

        # Posts at corners (and middle for double-stall)
        post_xs = [-L/2 + pr, L/2 - pr]
        if self.is_double:
            post_xs = [-L/2 + pr, 0.0, L/2 - pr]
        post_ys = [-W/2 + pr, W/2 - pr]
        for px in post_xs:
            for py in post_ys:
                _add_box_slot(bm, slot_ranges, 0, px, py, H/2, ps, ps, H)

        # Awning — sloped quad, front lower than back
        # Back at z = post_height; front at z = post_height - pitch
        front_z = H - self.awning_pitch
        back_z = H
        _add_awning_quad(
            bm, slot_ranges, 1,
            L, W, front_z, back_z, self.awning_overhang,
        )

        # Table — flat surface inside the stall
        if self.has_table:
            tz = self.table_height
            _add_box_slot(
                bm, slot_ranges, 2,
                0, 0, tz + self.table_thickness / 2,
                L - 2 * pr, W - 2 * pr, self.table_thickness,
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

        while len(obj.data.materials) < 3:
            obj.data.materials.append(None)

        for start, end, slot in slot_ranges:
            for i in range(start, end):
                obj.data.polygons[i].material_index = slot

        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(
            obj, [self.frame_color, self.awning_color, self.table_color]
        )
        return obj

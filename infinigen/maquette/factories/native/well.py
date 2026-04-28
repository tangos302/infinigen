"""LowPolyWellFactory — village / farmstead well.

Tier-1 factory by cross-attempt frequency (medieval village +
farmstead = 2 attempts). Classic medieval-village-square / kitchen-
courtyard prop; without it, "village square" reads as "open dirt
patch".

Archetypes:
  stone_round  — circular stone wall + wooden roof + bucket on rope
                 (medieval / fantasy)
  wooden_box   — square wooden curb (no roof) + bucket
                 (farmstead / Wild West)

Material slots:
  slot 0 = stone / curb       (default `rock_pale` or `wood`)
  slot 1 = wood (roof posts + bucket frame) (default `wood`)
  slot 2 = roof / shingles    (default `rock_shadow`)
"""

from __future__ import annotations

import math

import bmesh
import bpy
from mathutils import Vector

from infinigen.core.placement.factory import AssetFactory

from ...density import n_sides_for_radius, target_edge_for_bbox
from ...materials import apply_palette_slots


_WELL_ARCHETYPES = ("stone_round", "wooden_box")


# `n_sides` is bbox-derived when omitted from defaults (round archetypes);
# archetypes that need a fixed shape — e.g. `wooden_box` literally needs
# 4 corners — pin it explicitly.
_ARCHETYPE_DEFAULTS = {
    "stone_round": dict(
        radius=0.8, wall_height=0.7,
        has_roof=True, roof_height=1.2, post_radius=0.06,
        has_bucket=True, bucket_size=0.35,
        stone_color="rock_pale", wood_color="wood", roof_color="rock_shadow",
    ),
    "wooden_box": dict(
        radius=0.7, wall_height=0.55, n_sides=4,
        has_roof=False, roof_height=0.0, post_radius=0.05,
        has_bucket=True, bucket_size=0.32,
        stone_color="wood", wood_color="wood", roof_color="rock_shadow",
    ),
}


def _bm_face_count(bm) -> int:
    return len(bm.faces)


def _add_box(
    bm,
    cx: float, cy: float, cz: float,
    sx: float, sy: float, sz: float,
) -> int:
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


def _add_curb_round(
    bm, slot_ranges, slot,
    radius: float, wall_height: float, n_sides: int,
    wall_thickness: float = 0.12,
) -> None:
    """A short stone wall ring — outer + inner cylinders, capped on top."""
    start = _bm_face_count(bm)
    inner_r = radius - wall_thickness
    outer_top, outer_bot = [], []
    inner_top, inner_bot = [], []
    for s in range(n_sides):
        a = 2 * math.pi * s / n_sides
        ox, oy = radius * math.cos(a), radius * math.sin(a)
        ix, iy = inner_r * math.cos(a), inner_r * math.sin(a)
        outer_bot.append(bm.verts.new((ox, oy, 0)))
        outer_top.append(bm.verts.new((ox, oy, wall_height)))
        inner_bot.append(bm.verts.new((ix, iy, 0)))
        inner_top.append(bm.verts.new((ix, iy, wall_height)))
    bm.verts.ensure_lookup_table()
    for s in range(n_sides):
        ns = (s + 1) % n_sides
        # Outer side
        bm.faces.new((outer_bot[s], outer_bot[ns], outer_top[ns], outer_top[s]))
        # Inner side (reversed normal)
        bm.faces.new((inner_top[s], inner_top[ns], inner_bot[ns], inner_bot[s]))
        # Top ring (stone coping)
        bm.faces.new((outer_top[s], outer_top[ns], inner_top[ns], inner_top[s]))
        # Bottom ring (closing)
        bm.faces.new((outer_bot[ns], outer_bot[s], inner_bot[s], inner_bot[ns]))
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))


def _add_curb_square(
    bm, slot_ranges, slot,
    radius: float, wall_height: float,
    wall_thickness: float = 0.10,
) -> None:
    """4-sided wooden box curb. Built as 4 thin boxes around the perimeter."""
    side = radius
    # Each wall is a thin box. Bottom side
    _add_box_slot(bm, slot_ranges, slot,
                  0, -side, wall_height / 2,
                  side * 2 + wall_thickness, wall_thickness, wall_height)
    _add_box_slot(bm, slot_ranges, slot,
                  0, side, wall_height / 2,
                  side * 2 + wall_thickness, wall_thickness, wall_height)
    _add_box_slot(bm, slot_ranges, slot,
                  -side, 0, wall_height / 2,
                  wall_thickness, side * 2 - wall_thickness, wall_height)
    _add_box_slot(bm, slot_ranges, slot,
                  side, 0, wall_height / 2,
                  wall_thickness, side * 2 - wall_thickness, wall_height)


def _add_roof_posts(
    bm, slot_ranges, slot,
    radius: float, wall_height: float,
    roof_height: float, post_radius: float,
) -> tuple[Vector, Vector]:
    """Two vertical posts on opposite sides of the well, supporting the roof.
    Returns (left_top, right_top) for the roof to attach to."""
    # Posts placed at +X and -X on the curb edge
    h = wall_height + roof_height
    for sign in (-1, 1):
        _add_box_slot(bm, slot_ranges, slot,
                      sign * radius, 0, h / 2,
                      post_radius * 2, post_radius * 2, h)
    return (Vector((-radius, 0, h)), Vector((radius, 0, h)))


def _add_roof(
    bm, slot_ranges, slot,
    radius: float, wall_height: float, roof_height: float,
    post_radius: float,
) -> None:
    """Pitched gable roof spanning across the two posts. Two sloped quads
    + two triangular gable ends."""
    h_base = wall_height + roof_height - post_radius * 2
    h_apex = wall_height + roof_height + radius * 0.4
    overhang = 0.15
    eave_y = radius + overhang
    # Two sloped roof quads + two gable triangles
    p_apex_a = bm.verts.new((-radius - overhang, 0, h_apex))
    p_apex_b = bm.verts.new(( radius + overhang, 0, h_apex))
    p_eave_aL = bm.verts.new((-radius - overhang, -eave_y, h_base))
    p_eave_aR = bm.verts.new((-radius - overhang,  eave_y, h_base))
    p_eave_bL = bm.verts.new(( radius + overhang, -eave_y, h_base))
    p_eave_bR = bm.verts.new(( radius + overhang,  eave_y, h_base))
    bm.verts.ensure_lookup_table()
    start = _bm_face_count(bm)
    # Two roof slopes
    bm.faces.new((p_eave_aL, p_eave_bL, p_apex_b, p_apex_a))
    bm.faces.new((p_apex_a, p_apex_b, p_eave_bR, p_eave_aR))
    # Two gable triangles (front + back)
    bm.faces.new((p_eave_aL, p_apex_a, p_eave_aR))
    bm.faces.new((p_eave_bR, p_apex_b, p_eave_bL))
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))


def _add_bucket(
    bm, slot_ranges, wood_slot,
    radius: float, wall_height: float, roof_height: float, has_roof: bool,
    bucket_size: float,
) -> None:
    """A small bucket hanging from the roof ridge (if has_roof) or just
    sitting on the curb otherwise. Built as a small cylinder."""
    n_sides = 6
    if has_roof:
        # Hang under the apex
        cz = wall_height + roof_height * 0.4
    else:
        # Sitting on the curb edge
        cz = wall_height + bucket_size * 0.3
    half_h = bucket_size / 2
    z0 = cz - half_h
    z1 = cz + half_h
    bot, top = [], []
    start = _bm_face_count(bm)
    for s in range(n_sides):
        a = 2 * math.pi * s / n_sides
        x = bucket_size * 0.3 * math.cos(a)
        y = bucket_size * 0.3 * math.sin(a)
        bot.append(bm.verts.new((x, y, z0)))
        top.append(bm.verts.new((x, y, z1)))
    bm.verts.ensure_lookup_table()
    for s in range(n_sides):
        ns = (s + 1) % n_sides
        bm.faces.new((bot[s], bot[ns], top[ns], top[s]))
    bm.faces.new(top)
    bm.faces.new(list(reversed(bot)))
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, wood_slot))


class LowPolyWellFactory(AssetFactory):
    """A village / farmstead well — circular stone or wooden box curb,
    optional gable roof on two posts, optional bucket.

    Constructor knobs:

        factory_seed
        well_archetype : str = "stone_round"
                         "stone_round" | "wooden_box"
        radius          : float
        wall_height     : float
        n_sides         : int       cylinder side count (round only)
        has_roof        : bool
        roof_height     : float
        has_bucket      : bool
        bucket_size     : float
        stone_color     : str       slot 0
        wood_color      : str       slot 1
        roof_color      : str       slot 2
    """

    def __init__(
        self,
        factory_seed,
        well_archetype: str = "stone_round",
        radius: float | None = None,
        wall_height: float | None = None,
        polygon_multiplier: float = 1.0,
        target_edge: float | None = None,
        n_sides: int | None = None,
        has_roof: bool | None = None,
        roof_height: float | None = None,
        has_bucket: bool | None = None,
        bucket_size: float | None = None,
        stone_color: str | None = None,
        wood_color: str | None = None,
        roof_color: str | None = None,
        coarse: bool = False,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if well_archetype not in _WELL_ARCHETYPES:
            raise ValueError(
                f"unknown well_archetype {well_archetype!r}; "
                f"valid: {_WELL_ARCHETYPES}"
            )
        d = _ARCHETYPE_DEFAULTS[well_archetype]
        self.well_archetype = well_archetype
        self.radius = float(radius if radius is not None else d["radius"])
        self.wall_height = float(
            wall_height if wall_height is not None else d["wall_height"]
        )
        # Bbox-derive n_sides unless caller pinned it OR the archetype
        # defaults pin it (e.g. wooden_box=4).
        edge = (
            float(target_edge) if target_edge is not None
            else target_edge_for_bbox(
                (self.radius * 2, self.radius * 2,
                 self.wall_height + float(d.get("roof_height", 0.0))),
                polygon_multiplier=polygon_multiplier,
            )
        )
        if n_sides is not None:
            self.n_sides = int(n_sides)
        elif "n_sides" in d:
            self.n_sides = int(d["n_sides"])
        else:
            self.n_sides = n_sides_for_radius(self.radius, edge)
        self.has_roof = (
            bool(has_roof) if has_roof is not None else d["has_roof"]
        )
        self.roof_height = float(
            roof_height if roof_height is not None else d["roof_height"]
        )
        self.has_bucket = (
            bool(has_bucket) if has_bucket is not None else d["has_bucket"]
        )
        self.bucket_size = float(
            bucket_size if bucket_size is not None else d["bucket_size"]
        )
        self.post_radius = float(d["post_radius"])
        self.stone_color = stone_color or d["stone_color"]
        self.wood_color = wood_color or d["wood_color"]
        self.roof_color = roof_color or d["roof_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyWell({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        bm = bmesh.new()
        slot_ranges: list[tuple[int, int, int]] = []

        # Curb
        if self.well_archetype == "stone_round":
            _add_curb_round(
                bm, slot_ranges, 0,
                self.radius, self.wall_height, self.n_sides,
            )
        else:  # wooden_box
            _add_curb_square(
                bm, slot_ranges, 0,
                self.radius, self.wall_height,
            )

        # Roof posts + roof
        if self.has_roof and self.roof_height > 0:
            _add_roof_posts(
                bm, slot_ranges, 1,
                self.radius, self.wall_height,
                self.roof_height, self.post_radius,
            )
            _add_roof(
                bm, slot_ranges, 2,
                self.radius, self.wall_height, self.roof_height,
                self.post_radius,
            )

        # Bucket
        if self.has_bucket:
            _add_bucket(
                bm, slot_ranges, 1,
                self.radius, self.wall_height, self.roof_height,
                self.has_roof, self.bucket_size,
            )

        me = bpy.data.meshes.new(f"LowPolyWell({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(f"LowPolyWell({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)

        while len(obj.data.materials) < 3:
            obj.data.materials.append(None)

        for start, end, slot in slot_ranges:
            for i in range(start, end):
                obj.data.polygons[i].material_index = slot

        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(obj, [self.stone_color, self.wood_color, self.roof_color])
        return obj

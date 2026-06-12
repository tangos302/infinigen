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
import random

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
    """4-sided wooden box curb: 4 plank walls + chunky corner posts that
    cover the wall joints (and hide any coplanar seams)."""
    side = radius
    _add_box_slot(bm, slot_ranges, slot,
                  0, -side, wall_height / 2,
                  side * 2 - wall_thickness, wall_thickness, wall_height)
    _add_box_slot(bm, slot_ranges, slot,
                  0, side, wall_height / 2,
                  side * 2 - wall_thickness, wall_thickness, wall_height)
    _add_box_slot(bm, slot_ranges, slot,
                  -side, 0, wall_height / 2,
                  wall_thickness, side * 2 - wall_thickness, wall_height)
    _add_box_slot(bm, slot_ranges, slot,
                  side, 0, wall_height / 2,
                  wall_thickness, side * 2 - wall_thickness, wall_height)
    post_s = wall_thickness * 1.9
    for sx in (-1, 1):
        for sy in (-1, 1):
            _add_box_slot(bm, slot_ranges, slot,
                          sx * side, sy * side, (wall_height + 0.07) / 2,
                          post_s, post_s, wall_height + 0.07)


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


def _add_roller(
    bm, slot_ranges, slot,
    x0: float, x1: float, cz: float, r: float, n_sides: int = 6,
) -> None:
    """Hexagonal windlass roller along the X axis."""
    start = _bm_face_count(bm)
    ring0, ring1 = [], []
    for s in range(n_sides):
        a = 2 * math.pi * s / n_sides
        y, z = r * math.cos(a), cz + r * math.sin(a)
        ring0.append(bm.verts.new((x0, y, z)))
        ring1.append(bm.verts.new((x1, y, z)))
    bm.verts.ensure_lookup_table()
    for s in range(n_sides):
        ns = (s + 1) % n_sides
        bm.faces.new((ring0[s], ring0[ns], ring1[ns], ring1[s]))
    bm.faces.new(list(reversed(ring0)))
    bm.faces.new(ring1)
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))


def _add_hanging_bucket(
    bm, slot_ranges, wood_slot,
    *, cx: float, axle_z: float, bucket_top_z: float, bucket_size: float,
) -> None:
    """Rope from the roller + a tapered bucket hanging from it."""
    # Rope — a thin box from the axle down to the bucket.
    rope_len = axle_z - bucket_top_z
    _add_box_slot(bm, slot_ranges, wood_slot,
                  cx, 0, axle_z - rope_len / 2, 0.025, 0.025, rope_len)
    # Tapered bucket (wider at the top), 6 sides.
    n_sides = 6
    r_top = bucket_size * 0.34
    r_bot = bucket_size * 0.25
    z1 = bucket_top_z
    z0 = bucket_top_z - bucket_size * 0.62
    bot, top = [], []
    start = _bm_face_count(bm)
    for s in range(n_sides):
        a = 2 * math.pi * s / n_sides
        bot.append(bm.verts.new((cx + r_bot * math.cos(a), r_bot * math.sin(a), z0)))
        top.append(bm.verts.new((cx + r_top * math.cos(a), r_top * math.sin(a), z1)))
    bm.verts.ensure_lookup_table()
    for s in range(n_sides):
        ns = (s + 1) % n_sides
        bm.faces.new((bot[s], bot[ns], top[ns], top[s]))
    bm.faces.new(top)
    bm.faces.new(list(reversed(bot)))
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, wood_slot))


def _add_stone_blocks(
    bm, slot_ranges, slot,
    radius: float, wall_height: float, rng: random.Random,
) -> None:
    """A few protruding stones half-embedded in the curb so the ring reads
    as masonry instead of a smooth pipe."""
    for _ in range(rng.randint(5, 8)):
        a = rng.uniform(0, 2 * math.pi)
        z = rng.uniform(0.14, wall_height - 0.12)
        r = radius + 0.012
        _add_box_slot(
            bm, slot_ranges, slot,
            r * math.cos(a), r * math.sin(a), z,
            rng.uniform(0.13, 0.22), rng.uniform(0.10, 0.18),
            rng.uniform(0.10, 0.16),
        )


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
        **_unused_kwargs,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if _unused_kwargs:
            from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
            accept_unused_kwargs("LowPolyWellFactory", _unused_kwargs)
        if well_archetype not in _WELL_ARCHETYPES:
            # Lenient fallback rather than crash. Sonnet has been
            # observed to hallucinate plausible-sounding archetype
            # names despite the factories_guide brief listing the
            # valid set; killing a 6-minute build over a one-line
            # archetype typo wastes a generation. Substitute the
            # canonical default and warn to stderr.
            import sys
            print(
                f"[well_archetype] WARN: unknown well_archetype "
                f"{well_archetype!r}; falling back to {_WELL_ARCHETYPES[0]!r}. "
                f"Valid: {_WELL_ARCHETYPES}",
                file=sys.stderr,
            )
            well_archetype = _WELL_ARCHETYPES[0]
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
        rng = random.Random(int(self.factory_seed) + 33991)

        # Curb
        if self.well_archetype == "stone_round":
            _add_curb_round(
                bm, slot_ranges, 0,
                self.radius, self.wall_height, self.n_sides,
            )
            # Coping lip + a few protruding stones for a masonry read.
            _add_curb_round(
                bm, slot_ranges, 0,
                self.radius * 1.07, 0.09, self.n_sides,
                wall_thickness=0.16,
            )
            # Shift the lip ring up to the top of the wall.
            for v in bm.verts[-self.n_sides * 4:]:
                v.co.z += self.wall_height - 0.045
            _add_stone_blocks(
                bm, slot_ranges, 0, self.radius, self.wall_height, rng,
            )
        else:  # wooden_box
            _add_curb_square(
                bm, slot_ranges, 0,
                self.radius, self.wall_height,
            )

        # Windlass posts — always present; they carry the roller, and the
        # roof when there is one. (A well without its winch never read as
        # a well.)
        if self.has_roof and self.roof_height > 0:
            post_top = self.wall_height + self.roof_height
        else:
            post_top = self.wall_height + max(0.80, self.radius * 1.05)
        # Posts run thicker than the curb wall so their faces never sit
        # coplanar with it (coplanar overlap z-fights as black seams).
        post_t = self.post_radius * 2
        if self.well_archetype == "wooden_box":
            post_t = max(post_t, 0.16)
        for sign in (-1, 1):
            _add_box_slot(bm, slot_ranges, 1,
                          sign * self.radius, 0, post_top / 2,
                          post_t, post_t, post_top)

        if self.has_roof and self.roof_height > 0:
            _add_roof(
                bm, slot_ranges, 2,
                self.radius, self.wall_height, self.roof_height,
                self.post_radius,
            )
            axle_z = self.wall_height + self.roof_height * 0.52
        else:
            axle_z = post_top - 0.14

        # Roller + crank handle.
        span = self.radius - self.post_radius * 1.6
        _add_roller(bm, slot_ranges, 1, -span, span, axle_z, 0.07)
        crank_side = rng.choice((-1.0, 1.0))
        cx = crank_side * (self.radius + 0.10)
        _add_box_slot(bm, slot_ranges, 1, cx, 0, axle_z, 0.20, 0.05, 0.05)
        _add_box_slot(bm, slot_ranges, 1,
                      crank_side * (self.radius + 0.18), 0, axle_z - 0.13,
                      0.05, 0.05, 0.26)

        # Bucket on a rope — hanging height varies with seed; sometimes it
        # rests on the coping instead.
        if self.has_bucket:
            if rng.random() < 0.25:
                # Resting on the curb edge.
                _add_hanging_bucket(
                    bm, slot_ranges, 1,
                    cx=-(self.radius - self.bucket_size * 0.5), axle_z=axle_z,
                    bucket_top_z=self.wall_height + self.bucket_size * 0.60,
                    bucket_size=self.bucket_size,
                )
            else:
                hang = rng.uniform(0.35, 0.75)
                bucket_top = self.wall_height + (axle_z - self.wall_height) * (1 - hang)
                _add_hanging_bucket(
                    bm, slot_ranges, 1,
                    cx=0.0, axle_z=axle_z,
                    bucket_top_z=max(bucket_top, self.wall_height * 0.55),
                    bucket_size=self.bucket_size,
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

"""LowPolyPalmTreeFactory — proper palm tree.

A curved cylindrical trunk topped with a fan of drooping fronds.
Distinct from `NativeLowPolyTreeFactory`'s pine/balloon paradigm —
palms have a single ring of long thin fronds emerging from a single
crown point, not a balloon clump, and the trunk bends rather than
going straight or doing a single S-curve.

Build approach:
  - Trunk is a stack of n_sides-gon rings climbing along a curved
    centerline (lean direction picked per seed). Each ring's centre
    is offset horizontally by `curve * (t ** curve_power)` where t is
    the height fraction — so the lean grows toward the top.
  - Fronds are flat tapered quad strips emerging from the crown at
    even yaw spacing. Each segment's pitch is `base_pitch - droop * u`
    so the frond starts going up-and-out and curls down toward the
    tip — a circular-arc droop that reads as a real palm leaf in
    silhouette.

Archetypes:
  coconut / oasis_palm      — tall readable oasis/beach palm
  date / grove_palm         — medium, denser crown, tuned for clusters
  fan_palm                  — short stout trunk, stiff fan crown
  coastal_wind_bent         — strong lean + asymmetric wind-shaped crown
  young_palm                — short, narrow, fewer fronds
  dead_palm                 — dry trunk + sparse dead crown remnants

Material slots:
  slot 0 = trunk    (default `wood`)
  slot 1 = fronds   (default `foliage_bush`)
  slot 2 = dry/bark  (default `rock_shadow`)
  slot 3 = fruit     (default `ground_sand`)
"""

from __future__ import annotations

import math
import random

import bmesh
import bpy
from mathutils import Vector

from infinigen.core.placement.factory import AssetFactory

from ...density import n_along_axis, n_sides_for_radius, target_edge_for_bbox
from ...materials import apply_palette_slots


_PALM_ARCHETYPES = (
    "coconut",
    "date",
    "fan_palm",
    "oasis_palm",
    "coastal_wind_bent",
    "young_palm",
    "dead_palm",
    "grove_palm",
)


# trunk_segments / trunk_n_sides / frond_segments are bbox-derived. Defaults
# below carry shape + n_fronds counts (those don't scale with size — palm
# species fix frond count, not polygon density).
_ARCHETYPE_DEFAULTS = {
    "coconut": dict(
        trunk_height=8.0,
        trunk_base_radius=0.30,
        trunk_top_radius=0.20,
        trunk_curve=1.6,         # horizontal lean of trunk top, m
        trunk_curve_power=1.4,   # >1 = bend grows faster near the top
        n_fronds=10,
        frond_length=3.5,
        frond_base_width=0.30,
        frond_droop=1.4,         # radians of curve from base→tip
        frond_pitch=0.25,        # base pitch from horizontal (rad, +=up)
        crown_asymmetry=0.16,
        dead_fronds=1,
        fruit_count=5,
        bark_band_count=11,
        trunk_color="wood",
        frond_color="foliage_bush",
        dry_color="rock_shadow",
        fruit_color="ground_sand",
    ),
    "date": dict(
        trunk_height=6.0,
        trunk_base_radius=0.32,
        trunk_top_radius=0.26,
        trunk_curve=0.5,
        trunk_curve_power=1.2,
        n_fronds=14,
        frond_length=2.8,
        frond_base_width=0.26,
        frond_droop=0.9,
        frond_pitch=0.40,
        crown_asymmetry=0.08,
        dead_fronds=2,
        fruit_count=8,
        bark_band_count=9,
        trunk_color="wood",
        frond_color="foliage_bush",
        dry_color="rock_shadow",
        fruit_color="ground_sand",
    ),
    "fan_palm": dict(
        trunk_height=2.2,
        trunk_base_radius=0.32,
        trunk_top_radius=0.28,
        trunk_curve=0.0,
        trunk_curve_power=1.0,
        n_fronds=12,
        frond_length=2.0,
        frond_base_width=0.40,
        frond_droop=0.4,         # less droop, fronds stay more upright
        frond_pitch=0.7,
        crown_asymmetry=0.05,
        dead_fronds=0,
        fruit_count=0,
        bark_band_count=3,
        trunk_color="wood",
        frond_color="foliage_bush",
        dry_color="rock_shadow",
        fruit_color="ground_sand",
    ),
    "oasis_palm": dict(
        trunk_height=7.2,
        trunk_base_radius=0.34,
        trunk_top_radius=0.23,
        trunk_curve=0.9,
        trunk_curve_power=1.35,
        n_fronds=16,
        frond_length=3.25,
        frond_base_width=0.32,
        frond_droop=1.05,
        frond_pitch=0.34,
        crown_asymmetry=0.10,
        dead_fronds=3,
        fruit_count=10,
        bark_band_count=13,
        trunk_color="wood",
        frond_color="foliage_bush",
        dry_color="rock_shadow",
        fruit_color="ground_sand",
    ),
    "coastal_wind_bent": dict(
        trunk_height=7.8,
        trunk_base_radius=0.27,
        trunk_top_radius=0.18,
        trunk_curve=2.65,
        trunk_curve_power=1.55,
        n_fronds=12,
        frond_length=3.35,
        frond_base_width=0.27,
        frond_droop=1.45,
        frond_pitch=0.16,
        crown_asymmetry=0.42,
        dead_fronds=2,
        fruit_count=2,
        bark_band_count=12,
        trunk_color="wood",
        frond_color="foliage_bush",
        dry_color="rock_shadow",
        fruit_color="ground_sand",
    ),
    "young_palm": dict(
        trunk_height=2.9,
        trunk_base_radius=0.19,
        trunk_top_radius=0.14,
        trunk_curve=0.28,
        trunk_curve_power=1.15,
        n_fronds=8,
        frond_length=1.65,
        frond_base_width=0.22,
        frond_droop=0.65,
        frond_pitch=0.55,
        crown_asymmetry=0.07,
        dead_fronds=0,
        fruit_count=0,
        bark_band_count=4,
        trunk_color="wood",
        frond_color="foliage_bush",
        dry_color="rock_shadow",
        fruit_color="ground_sand",
    ),
    "dead_palm": dict(
        trunk_height=5.8,
        trunk_base_radius=0.28,
        trunk_top_radius=0.17,
        trunk_curve=1.1,
        trunk_curve_power=1.35,
        n_fronds=2,
        frond_length=1.25,
        frond_base_width=0.18,
        frond_droop=1.9,
        frond_pitch=-0.25,
        crown_asymmetry=0.22,
        dead_fronds=7,
        fruit_count=0,
        bark_band_count=10,
        trunk_color="rock_shadow",
        frond_color="rock_shadow",
        dry_color="wood",
        fruit_color="ground_sand",
    ),
    "grove_palm": dict(
        trunk_height=5.2,
        trunk_base_radius=0.27,
        trunk_top_radius=0.20,
        trunk_curve=0.55,
        trunk_curve_power=1.2,
        n_fronds=12,
        frond_length=2.45,
        frond_base_width=0.27,
        frond_droop=0.85,
        frond_pitch=0.42,
        crown_asymmetry=0.12,
        dead_fronds=1,
        fruit_count=3,
        bark_band_count=8,
        trunk_color="wood",
        frond_color="foliage_bush",
        dry_color="rock_shadow",
        fruit_color="ground_sand",
    ),
}


def _bm_face_count(bm) -> int:
    return len(bm.faces)


def _build_trunk(
    bm,
    slot_ranges,
    slot,
    height: float,
    base_radius: float,
    top_radius: float,
    n_segments: int,
    n_sides: int,
    curve_amount: float,
    curve_power: float,
    curve_yaw: float,
) -> Vector:
    """Stacked-ring curved trunk. Returns crown center (top of trunk)."""
    start = _bm_face_count(bm)
    rings: list[list] = []
    for i in range(n_segments + 1):
        t = i / n_segments
        offset = curve_amount * (t ** curve_power)
        cx = offset * math.cos(curve_yaw)
        cy = offset * math.sin(curve_yaw)
        z = height * t
        r = base_radius + (top_radius - base_radius) * t
        ring = []
        for s in range(n_sides):
            a = 2 * math.pi * s / n_sides
            x = cx + r * math.cos(a)
            y = cy + r * math.sin(a)
            ring.append(bm.verts.new((x, y, z)))
        rings.append(ring)
    bm.verts.ensure_lookup_table()
    # Side faces between consecutive rings
    for L in range(n_segments):
        a_ring, b_ring = rings[L], rings[L + 1]
        for s in range(n_sides):
            ns = (s + 1) % n_sides
            bm.faces.new((a_ring[s], a_ring[ns], b_ring[ns], b_ring[s]))
    # Bottom n-gon (reversed for outward-facing normal)
    bm.faces.new(list(reversed(rings[0])))
    # Top n-gon — fronds will cover it visually but we still cap so the
    # mesh is closed.
    bm.faces.new(rings[-1])
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))

    top_offset = curve_amount * (1.0 ** curve_power)
    crown = Vector(
        (
            top_offset * math.cos(curve_yaw),
            top_offset * math.sin(curve_yaw),
            height,
        )
    )
    return crown


def _build_frond(
    bm,
    crown_pos: Vector,
    yaw: float,
    base_pitch: float,
    length: float,
    base_width: float,
    segments: int,
    droop: float,
) -> None:
    """One frond: flat tapered quad strip emerging from `crown_pos`,
    yawing along `yaw`, starting at `base_pitch` and curling down by
    `droop` radians over its length.

    The strip is built as two parallel rows of vertices (left/right)
    offset perpendicular to the yaw direction in the horizontal plane;
    quad faces between them. Width tapers from `base_width` at the
    base to ~30% at the tip — at low poly that reads as a leaf without
    needing a real triangle tip.
    """
    # Horizontal perpendicular to the yaw direction (used to offset
    # left/right rows). Frond stays roughly flat in width — we don't
    # roll the strip around its own axis at low poly.
    perp_x = -math.sin(yaw)
    perp_y = math.cos(yaw)

    # Walk the centerline segment-by-segment. Each segment integrates
    # forward at the average pitch over that segment to avoid a
    # systematic over/under-shoot vs. a left-Riemann sum.
    seg_len = length / segments
    centerline: list[Vector] = [Vector(crown_pos)]
    pos = Vector(crown_pos)
    for s in range(1, segments + 1):
        u_mid = (s - 0.5) / segments
        pitch = base_pitch - droop * u_mid
        dh = seg_len * math.cos(pitch)
        dv = seg_len * math.sin(pitch)
        pos = pos + Vector((dh * math.cos(yaw), dh * math.sin(yaw), dv))
        centerline.append(Vector(pos))

    left_verts = []
    right_verts = []
    for i, pt in enumerate(centerline):
        u = i / segments
        # Width tapers linearly from base_width at u=0 to 0.3*base_width at u=1.
        half_w = 0.5 * base_width * (1.0 - 0.7 * u)
        l = bm.verts.new((pt.x + perp_x * half_w, pt.y + perp_y * half_w, pt.z))
        r = bm.verts.new((pt.x - perp_x * half_w, pt.y - perp_y * half_w, pt.z))
        left_verts.append(l)
        right_verts.append(r)
    bm.verts.ensure_lookup_table()

    for i in range(segments):
        bm.faces.new(
            (left_verts[i], left_verts[i + 1], right_verts[i + 1], right_verts[i])
        )


def _build_bark_bands(
    bm,
    slot_ranges,
    slot,
    *,
    height: float,
    base_radius: float,
    top_radius: float,
    n_sides: int,
    curve_amount: float,
    curve_power: float,
    curve_yaw: float,
    band_count: int,
    rng: random.Random,
) -> None:
    """Add thin raised bark bands along the trunk.

    These are deliberately simple horizontal low-poly sleeves, not a
    physically perfect ring around the curved trunk. From the game camera they
    break up the smooth cylinder and read as palm scars.
    """
    if band_count <= 0:
        return
    start = _bm_face_count(bm)
    for band_index in range(band_count):
        t = (band_index + 0.65) / (band_count + 1.1)
        t += rng.uniform(-0.018, 0.018)
        if t <= 0.06 or t >= 0.95:
            continue
        z0 = height * t
        band_h = max(0.045, height * rng.uniform(0.006, 0.010))
        offset = curve_amount * (t ** curve_power)
        cx = offset * math.cos(curve_yaw)
        cy = offset * math.sin(curve_yaw)
        radius = base_radius + (top_radius - base_radius) * t
        radius *= rng.uniform(1.018, 1.045)
        bottom = []
        top = []
        for side in range(n_sides):
            a = 2 * math.pi * side / n_sides
            bottom.append(bm.verts.new((cx + radius * math.cos(a), cy + radius * math.sin(a), z0)))
            top.append(bm.verts.new((cx + radius * math.cos(a), cy + radius * math.sin(a), z0 + band_h)))
        bm.verts.ensure_lookup_table()
        for side in range(n_sides):
            nxt = (side + 1) % n_sides
            bm.faces.new((bottom[side], bottom[nxt], top[nxt], top[side]))
    end = _bm_face_count(bm)
    if end > start:
        slot_ranges.append((start, end, slot))


def _build_octahedron(
    bm,
    center: Vector,
    radius: float,
) -> None:
    """Tiny low-poly fruit cluster element."""
    verts = [
        bm.verts.new((center.x + radius, center.y, center.z)),
        bm.verts.new((center.x - radius, center.y, center.z)),
        bm.verts.new((center.x, center.y + radius, center.z)),
        bm.verts.new((center.x, center.y - radius, center.z)),
        bm.verts.new((center.x, center.y, center.z + radius)),
        bm.verts.new((center.x, center.y, center.z - radius)),
    ]
    bm.verts.ensure_lookup_table()
    for a, b, c in (
        (0, 2, 4), (2, 1, 4), (1, 3, 4), (3, 0, 4),
        (2, 0, 5), (1, 2, 5), (3, 1, 5), (0, 3, 5),
    ):
        bm.faces.new((verts[a], verts[b], verts[c]))


def _build_fruit_cluster(
    bm,
    slot_ranges,
    slot,
    *,
    crown_pos: Vector,
    count: int,
    trunk_radius: float,
    rng: random.Random,
) -> None:
    if count <= 0:
        return
    start = _bm_face_count(bm)
    cluster_yaw = rng.uniform(0, 2 * math.pi)
    for index in range(count):
        yaw = cluster_yaw + index * (math.tau / max(count, 1)) + rng.uniform(-0.22, 0.22)
        radial = rng.uniform(trunk_radius * 0.55, trunk_radius * 1.35)
        z = crown_pos.z - rng.uniform(0.16, 0.55)
        center = Vector((
            crown_pos.x + radial * math.cos(yaw),
            crown_pos.y + radial * math.sin(yaw),
            z,
        ))
        _build_octahedron(bm, center, rng.uniform(0.10, 0.16))
    end = _bm_face_count(bm)
    if end > start:
        slot_ranges.append((start, end, slot))


class LowPolyPalmTreeFactory(AssetFactory):
    """A low-poly palm tree: curved cylindrical trunk + drooping frond fan.

    Constructor knobs:

        factory_seed
        palm_archetype   : str = "coconut"
                           "coconut" | "date" | "fan_palm"
        trunk_height       : float
        trunk_base_radius  : float
        trunk_top_radius   : float
        trunk_segments     : int   stack depth of trunk rings
        trunk_n_sides      : int   trunk cylinder side count
        trunk_curve        : float lean of trunk top relative to base, m
        trunk_curve_power  : float >1 = lean grows faster near the top
        n_fronds           : int   fronds in the crown ring
        frond_length       : float total arc length of each frond
        frond_base_width   : float frond width at base, m
        frond_segments     : int   quads per frond along its length
        frond_droop        : float radians of curl from base pitch to tip
        frond_pitch        : float base pitch above horizontal, rad
        crown_asymmetry    : float directional frond length bias, 0..~0.5
        dead_fronds        : int   dry drooping fronds under the crown
        fruit_count        : int   small octahedral fruit near crown
        bark_band_count    : int   raised trunk scar rings
        trunk_color        : str   slot 0 palette key
        frond_color        : str   slot 1 palette key
        dry_color          : str   slot 2 palette key
        fruit_color        : str   slot 3 palette key
    """

    def __init__(
        self,
        factory_seed,
        palm_archetype: str = "coconut",
        trunk_height: float | None = None,
        trunk_base_radius: float | None = None,
        trunk_top_radius: float | None = None,
        polygon_multiplier: float = 1.0,
        target_edge: float | None = None,
        trunk_segments: int | None = None,
        trunk_n_sides: int | None = None,
        trunk_curve: float | None = None,
        trunk_curve_power: float | None = None,
        n_fronds: int | None = None,
        frond_length: float | None = None,
        frond_base_width: float | None = None,
        frond_segments: int | None = None,
        frond_droop: float | None = None,
        frond_pitch: float | None = None,
        crown_asymmetry: float | None = None,
        dead_fronds: int | None = None,
        fruit_count: int | None = None,
        bark_band_count: int | None = None,
        trunk_color: str | None = None,
        frond_color: str | None = None,
        dry_color: str | None = None,
        fruit_color: str | None = None,
        coarse: bool = False,
        **_unused_kwargs,
    ):
        from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
        accept_unused_kwargs("LowPolyPalmTreeFactory", _unused_kwargs)
        super().__init__(factory_seed, coarse=coarse)
        if palm_archetype not in _PALM_ARCHETYPES:
            # Lenient fallback rather than crash. Sonnet has been
            # observed to hallucinate plausible-sounding archetype
            # names despite the factories_guide brief listing the
            # valid set; killing a 6-minute build over a one-line
            # archetype typo wastes a generation. Substitute the
            # canonical default and warn to stderr.
            import sys
            print(
                f"[palm_archetype] WARN: unknown palm_archetype "
                f"{palm_archetype!r}; falling back to {_PALM_ARCHETYPES[0]!r}. "
                f"Valid: {_PALM_ARCHETYPES}",
                file=sys.stderr,
            )
            palm_archetype = _PALM_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[palm_archetype]
        self.palm_archetype = palm_archetype
        self.trunk_height = float(trunk_height if trunk_height is not None else d["trunk_height"])
        self.trunk_base_radius = float(
            trunk_base_radius if trunk_base_radius is not None else d["trunk_base_radius"]
        )
        self.trunk_top_radius = float(
            trunk_top_radius if trunk_top_radius is not None else d["trunk_top_radius"]
        )
        edge = (
            float(target_edge) if target_edge is not None
            else target_edge_for_bbox(
                (self.trunk_base_radius * 2, self.trunk_base_radius * 2,
                 self.trunk_height),
                polygon_multiplier=polygon_multiplier,
            )
        )
        self.trunk_segments = int(
            trunk_segments if trunk_segments is not None
            else n_along_axis(self.trunk_height, edge, min_n=4)
        )
        self.trunk_n_sides = int(
            trunk_n_sides if trunk_n_sides is not None
            else n_sides_for_radius(self.trunk_base_radius, edge, min_n=6)
        )
        self.trunk_curve = float(trunk_curve if trunk_curve is not None else d["trunk_curve"])
        self.trunk_curve_power = float(
            trunk_curve_power if trunk_curve_power is not None else d["trunk_curve_power"]
        )
        self.n_fronds = int(n_fronds if n_fronds is not None else d["n_fronds"])
        self.frond_length = float(frond_length if frond_length is not None else d["frond_length"])
        self.frond_base_width = float(
            frond_base_width if frond_base_width is not None else d["frond_base_width"]
        )
        self.frond_segments = int(
            frond_segments if frond_segments is not None
            else n_along_axis(self.frond_length, edge, min_n=4)
        )
        self.frond_droop = float(frond_droop if frond_droop is not None else d["frond_droop"])
        self.frond_pitch = float(frond_pitch if frond_pitch is not None else d["frond_pitch"])
        self.crown_asymmetry = float(
            crown_asymmetry if crown_asymmetry is not None else d["crown_asymmetry"]
        )
        self.dead_fronds = int(dead_fronds if dead_fronds is not None else d["dead_fronds"])
        self.fruit_count = int(fruit_count if fruit_count is not None else d["fruit_count"])
        self.bark_band_count = int(
            bark_band_count if bark_band_count is not None else d["bark_band_count"]
        )
        self.trunk_color = trunk_color or d["trunk_color"]
        self.frond_color = frond_color or d["frond_color"]
        self.dry_color = dry_color or d["dry_color"]
        self.fruit_color = fruit_color or d["fruit_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyPalmTree({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        rng = random.Random(self.factory_seed)
        bm = bmesh.new()
        slot_ranges: list[tuple[int, int, int]] = []

        # Pick a per-seed lean direction so different palms in a
        # scatter face different ways. Skipped if curve_amount = 0.
        curve_yaw = rng.uniform(0, 2 * math.pi)

        crown_pos = _build_trunk(
            bm, slot_ranges, 0,
            self.trunk_height, self.trunk_base_radius, self.trunk_top_radius,
            self.trunk_segments, self.trunk_n_sides,
            self.trunk_curve, self.trunk_curve_power, curve_yaw,
        )

        # Bark scars break up the trunk cylinder before crown geometry.
        _build_bark_bands(
            bm,
            slot_ranges,
            2,
            height=self.trunk_height,
            base_radius=self.trunk_base_radius,
            top_radius=self.trunk_top_radius,
            n_sides=self.trunk_n_sides,
            curve_amount=self.trunk_curve,
            curve_power=self.trunk_curve_power,
            curve_yaw=curve_yaw,
            band_count=self.bark_band_count,
            rng=rng,
        )

        # Fronds: distribute around the crown at even yaw spacing with a
        # small per-frond yaw/pitch/length jitter so the fan doesn't
        # look mechanically symmetric. Crown asymmetry biases length in
        # the trunk-lean direction for wind/coastal archetypes.
        frond_start = _bm_face_count(bm)
        base_yaw = rng.uniform(0, 2 * math.pi)
        for i in range(self.n_fronds):
            yaw = base_yaw + i * (2 * math.pi / self.n_fronds) + rng.uniform(-0.12, 0.12)
            wind_alignment = math.cos(yaw - curve_yaw)
            pitch = self.frond_pitch + rng.uniform(-0.10, 0.10) - max(0.0, wind_alignment) * self.crown_asymmetry * 0.10
            length = self.frond_length * rng.uniform(0.85, 1.05)
            length *= max(0.45, 1.0 + wind_alignment * self.crown_asymmetry)
            droop = self.frond_droop + rng.uniform(-0.10, 0.10) + max(0.0, wind_alignment) * self.crown_asymmetry * 0.35
            _build_frond(
                bm,
                crown_pos=crown_pos,
                yaw=yaw,
                base_pitch=pitch,
                length=length,
                base_width=self.frond_base_width,
                segments=self.frond_segments,
                droop=droop,
            )
        frond_end = _bm_face_count(bm)
        slot_ranges.append((frond_start, frond_end, 1))

        if self.dead_fronds > 0:
            dry_start = _bm_face_count(bm)
            dry_base_yaw = base_yaw + rng.uniform(-0.2, 0.2)
            for i in range(self.dead_fronds):
                yaw = dry_base_yaw + i * (2 * math.pi / max(self.dead_fronds, 1)) + rng.uniform(-0.24, 0.24)
                _build_frond(
                    bm,
                    crown_pos=crown_pos + Vector((0.0, 0.0, -0.08)),
                    yaw=yaw,
                    base_pitch=rng.uniform(-0.45, -0.05),
                    length=self.frond_length * rng.uniform(0.38, 0.66),
                    base_width=self.frond_base_width * rng.uniform(0.45, 0.70),
                    segments=max(2, min(self.frond_segments, 5)),
                    droop=self.frond_droop * rng.uniform(0.9, 1.35),
                )
            dry_end = _bm_face_count(bm)
            if dry_end > dry_start:
                slot_ranges.append((dry_start, dry_end, 2))

        _build_fruit_cluster(
            bm,
            slot_ranges,
            3,
            crown_pos=crown_pos,
            count=self.fruit_count,
            trunk_radius=self.trunk_top_radius,
            rng=rng,
        )

        me = bpy.data.meshes.new(f"LowPolyPalmTree({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(f"LowPolyPalmTree({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)

        while len(obj.data.materials) < 4:
            obj.data.materials.append(None)

        for start, end, slot in slot_ranges:
            for i in range(start, end):
                obj.data.polygons[i].material_index = slot

        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(obj, [
            self.trunk_color,
            self.frond_color,
            self.dry_color,
            self.fruit_color,
        ])
        return obj

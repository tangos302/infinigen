"""LowPolyCactusFactory — saguaro / barrel cactus.

Desert hero plant. Tall ribbed column (saguaro) with optional upward-
curving arms, or a short fat ribbed barrel cactus with a domed top
and a flower crown.

Cross-prompt value: any desert / Wild West / canyon / Sonoran scene
needs cacti to read as "American Southwest". Saguaro carries the
iconic silhouette; barrel adds ground-level scatter variety.

Archetypes:
  saguaro    — tall column ~4-5 m, 1-3 upward-curving arms branching
               off the upper trunk. No flower crown by default.
  barrel     — short fat ribbed cylinder ~1 m, no arms, flower crown
               on by default.

Build approach: ribbed n-sided column built via stacked rings whose
radii alternate per side index (even sides at full radius, odd sides
pulled inward by `rib_amplitude`). This produces vertical fluting
that survives flat-shading without separate geometry. Top is closed
with a quarter-circle dome (rings narrowing along sin(θ)/cos(θ)) to
an apex. Saguaro arms are tubes built along a horizontal-then-bend-
then-vertical centerline using a fixed lateral perpendicular in the
bend plane (so the ribs don't twist during the bend).

Material slots:
  slot 0 = cactus body  (default `foliage_bush`)
  slot 1 = flower crown (default `accent_red`)
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


_CACTUS_ARCHETYPES = ("saguaro", "barrel")


# n_sides + n_layers are bbox-derived. Defaults are dimensional only.
# Cactus prefers a higher min_n on sides (8) so ribs read as ribs, not
# pyramids.
_ARCHETYPE_DEFAULTS = {
    "saguaro": dict(
        height=4.5,
        base_radius=0.50,
        top_radius=0.42,
        rib_amplitude=0.10,
        dome_segments=2,
        n_arms=2,
        arm_radius_fraction=0.55,
        arm_horizontal_extent=0.7,
        arm_vertical_extent=1.4,
        arm_z_fraction_range=(0.45, 0.75),
        has_flower=False,
        flower_radius_fraction=0.35,
        body_color="foliage_bush",
        flower_color="accent_red",
    ),
    "barrel": dict(
        height=0.9,
        base_radius=0.55,
        top_radius=0.45,
        rib_amplitude=0.15,
        dome_segments=2,
        n_arms=0,
        arm_radius_fraction=0.0,
        arm_horizontal_extent=0.0,
        arm_vertical_extent=0.0,
        arm_z_fraction_range=(0.0, 0.0),
        has_flower=True,
        flower_radius_fraction=0.55,
        body_color="foliage_bush",
        flower_color="accent_red",
    ),
}


def _bm_face_count(bm) -> int:
    return len(bm.faces)


def _build_ribbed_column(
    bm,
    slot_ranges,
    slot,
    height: float,
    base_radius: float,
    top_radius: float,
    n_sides: int,
    n_layers: int,
    rib_amplitude: float,
    dome_segments: int,
) -> Vector:
    """Build a ribbed n-sided column with a quarter-circle domed top.
    Returns the apex position so the caller can place a flower crown."""
    start = _bm_face_count(bm)
    rings: list[list] = []
    for L in range(n_layers + 1):
        t = L / n_layers
        r = base_radius + (top_radius - base_radius) * t
        z = height * t
        ring = []
        for s in range(n_sides):
            a = 2 * math.pi * s / n_sides
            rib = 1.0 if (s % 2 == 0) else (1.0 - rib_amplitude)
            ring.append(
                bm.verts.new((r * rib * math.cos(a), r * rib * math.sin(a), z))
            )
        rings.append(ring)
    bm.verts.ensure_lookup_table()
    for L in range(n_layers):
        a_ring, b_ring = rings[L], rings[L + 1]
        for s in range(n_sides):
            ns = (s + 1) % n_sides
            bm.faces.new((a_ring[s], a_ring[ns], b_ring[ns], b_ring[s]))
    # Bottom n-gon (reversed for outward-facing normal)
    bm.faces.new(list(reversed(rings[0])))

    # Domed top: a stack of dome_segments-1 narrowing rings followed by an apex
    # vertex. dome_segments == 0 falls back to a flat n-gon top.
    dome_height = top_radius * 0.85
    prev_ring = rings[-1]
    if dome_segments <= 0:
        bm.faces.new(prev_ring)
        apex_z = height
    else:
        for i in range(1, dome_segments):
            t = i / dome_segments
            theta = (math.pi / 2) * t
            r = top_radius * math.cos(theta)
            z_off = dome_height * math.sin(theta)
            new_ring = []
            for s in range(n_sides):
                a = 2 * math.pi * s / n_sides
                rib = 1.0 if (s % 2 == 0) else (1.0 - rib_amplitude)
                new_ring.append(
                    bm.verts.new(
                        (r * rib * math.cos(a), r * rib * math.sin(a), height + z_off)
                    )
                )
            bm.verts.ensure_lookup_table()
            for s in range(n_sides):
                ns = (s + 1) % n_sides
                bm.faces.new(
                    (prev_ring[s], prev_ring[ns], new_ring[ns], new_ring[s])
                )
            prev_ring = new_ring
        apex_z = height + dome_height
        apex = bm.verts.new((0, 0, apex_z))
        bm.verts.ensure_lookup_table()
        for s in range(n_sides):
            ns = (s + 1) % n_sides
            bm.faces.new((prev_ring[s], prev_ring[ns], apex))

    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))
    return Vector((0, 0, apex_z))


def _build_saguaro_arm(
    bm,
    slot_ranges,
    slot,
    base_pos: Vector,
    yaw: float,
    arm_radius: float,
    horizontal_extent: float,
    vertical_extent: float,
    n_sides: int,
    rib_amplitude: float,
) -> None:
    """An arm: tube going outward then bending up. Built along a
    centerline of (position, tangent) pairs with a fixed lateral
    perpendicular (horizontal, perpendicular to the bend plane) so the
    rib pattern doesn't twist along the bend.

    The start of the tube is intentionally NOT capped — the arm
    overlaps the trunk volume so the open end is hidden inside the
    trunk wall. The top is capped with an apex vertex (small dome).
    """
    yaw_dir = Vector((math.cos(yaw), math.sin(yaw), 0))
    # Lateral axis perpendicular to the bend plane — stays constant
    # through the bend, so the rib pattern is consistent.
    side_dir = Vector((-math.sin(yaw), math.cos(yaw), 0))

    bend_r = min(horizontal_extent, vertical_extent) * 0.5
    bend_r = max(bend_r, arm_radius * 1.5)

    n_horiz_segs = 2
    n_bend_segs = 4
    n_vert_segs = 3

    h_pre = max(0.0, horizontal_extent - bend_r)
    v_post = max(0.0, vertical_extent - bend_r)

    centerline: list[tuple[Vector, Vector]] = []

    # Horizontal segment, going outward along yaw_dir
    for i in range(n_horiz_segs + 1):
        t = i / n_horiz_segs
        pos = base_pos + yaw_dir * (h_pre * t)
        centerline.append((pos, yaw_dir.copy()))

    # 90° bend in the (yaw_dir, +z) plane.
    # Arc center is one bend_r above the corner where horizontal meets the
    # vertical leg, i.e., bend_center = (base + h_pre·yaw_dir) + bend_r·z.
    # At theta=0 we're directly under the arc center (matches end of
    # horizontal); at theta=pi/2 we're horizontally offset by +bend_r·yaw_dir
    # (start of vertical segment).
    bend_center = base_pos + yaw_dir * h_pre + Vector((0, 0, bend_r))
    for i in range(1, n_bend_segs + 1):
        theta = (math.pi / 2) * (i / n_bend_segs)
        pos = (
            bend_center
            + yaw_dir * (bend_r * math.sin(theta))
            + Vector((0, 0, -bend_r * math.cos(theta)))
        )
        tangent = (
            yaw_dir * math.cos(theta) + Vector((0, 0, math.sin(theta)))
        ).normalized()
        centerline.append((pos, tangent))

    # Vertical segment, going straight up
    bend_end = bend_center + yaw_dir * bend_r
    for i in range(1, n_vert_segs + 1):
        t = i / n_vert_segs
        pos = bend_end + Vector((0, 0, v_post * t))
        centerline.append((pos, Vector((0, 0, 1))))

    start = _bm_face_count(bm)
    rings: list[list] = []
    for pos, tangent in centerline:
        # Other ring axis = tangent × side_dir, in the bend plane.
        other_dir = tangent.cross(side_dir).normalized()
        ring = []
        for s in range(n_sides):
            a = 2 * math.pi * s / n_sides
            rib = 1.0 if (s % 2 == 0) else (1.0 - rib_amplitude)
            local_x = math.cos(a) * arm_radius * rib
            local_y = math.sin(a) * arm_radius * rib
            ring.append(bm.verts.new(pos + side_dir * local_x + other_dir * local_y))
        rings.append(ring)
    bm.verts.ensure_lookup_table()
    for L in range(len(rings) - 1):
        a_ring, b_ring = rings[L], rings[L + 1]
        for s in range(n_sides):
            ns = (s + 1) % n_sides
            bm.faces.new((a_ring[s], a_ring[ns], b_ring[ns], b_ring[s]))
    # Cap top with an apex vertex (small rounded tip)
    top_pos, top_tangent = centerline[-1]
    apex = bm.verts.new(top_pos + top_tangent * (arm_radius * 0.7))
    bm.verts.ensure_lookup_table()
    last_ring = rings[-1]
    for s in range(n_sides):
        ns = (s + 1) % n_sides
        bm.faces.new((last_ring[s], last_ring[ns], apex))

    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))


def _build_flower_crown(
    bm,
    slot_ranges,
    slot,
    apex_pos: Vector,
    radius: float,
) -> None:
    """A small squashed icosphere on top of the cactus, indicating a
    cluster of flowers. Tagged on slot 1 so palette can color it red."""
    start = _bm_face_count(bm)
    result = bmesh.ops.create_icosphere(bm, subdivisions=1, radius=1.0)
    new_verts = result["verts"]
    for v in new_verts:
        v.co.x = v.co.x * radius + apex_pos.x
        v.co.y = v.co.y * radius + apex_pos.y
        v.co.z = v.co.z * (radius * 0.6) + apex_pos.z + radius * 0.3
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))


class LowPolyCactusFactory(AssetFactory):
    """A low-poly desert cactus: saguaro column with arms, or barrel
    cactus with a flower crown.

    Constructor knobs:

        factory_seed
        cactus_archetype       : str = "saguaro"  "saguaro" | "barrel"
        height                 : float
        base_radius            : float
        top_radius             : float
        n_sides                : int     ribbed cylinder side count
        n_layers               : int     trunk ring-stack depth
        rib_amplitude          : float   inward pull on odd sides (0..1)
        dome_segments          : int     quarter-circle rings closing the top
        n_arms                 : int     saguaro arm count
        arm_radius_fraction    : float   arm radius / trunk top radius
        arm_horizontal_extent  : float   how far each arm reaches outward
        arm_vertical_extent    : float   how far each arm rises after the bend
        arm_z_fraction_range   : (float, float)  z-fraction range where
                                                  arms attach to the trunk
        has_flower             : bool    flower crown on top
        flower_radius_fraction : float   flower radius / top_radius
        body_color             : str     slot 0 palette key
        flower_color           : str     slot 1 palette key
    """

    def __init__(
        self,
        factory_seed,
        cactus_archetype: str = "saguaro",
        height: float | None = None,
        base_radius: float | None = None,
        top_radius: float | None = None,
        polygon_multiplier: float = 1.0,
        target_edge: float | None = None,
        n_sides: int | None = None,
        n_layers: int | None = None,
        rib_amplitude: float | None = None,
        dome_segments: int | None = None,
        n_arms: int | None = None,
        arm_radius_fraction: float | None = None,
        arm_horizontal_extent: float | None = None,
        arm_vertical_extent: float | None = None,
        arm_z_fraction_range: tuple[float, float] | None = None,
        has_flower: bool | None = None,
        flower_radius_fraction: float | None = None,
        body_color: str | None = None,
        flower_color: str | None = None,
        coarse: bool = False,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if cactus_archetype not in _CACTUS_ARCHETYPES:
            raise ValueError(
                f"unknown cactus_archetype {cactus_archetype!r}; "
                f"valid: {_CACTUS_ARCHETYPES}"
            )
        d = _ARCHETYPE_DEFAULTS[cactus_archetype]
        self.cactus_archetype = cactus_archetype
        self.height = float(height if height is not None else d["height"])
        self.base_radius = float(base_radius if base_radius is not None else d["base_radius"])
        self.top_radius = float(top_radius if top_radius is not None else d["top_radius"])
        edge = (
            float(target_edge) if target_edge is not None
            else target_edge_for_bbox(
                (self.base_radius * 2, self.base_radius * 2, self.height),
                polygon_multiplier=polygon_multiplier,
            )
        )
        # Cactus ribs need at least 8 sides to read as ribs not facets.
        self.n_sides = int(
            n_sides if n_sides is not None
            else n_sides_for_radius(self.base_radius, edge, min_n=8)
        )
        self.n_layers = int(
            n_layers if n_layers is not None
            else n_along_axis(self.height, edge, min_n=4)
        )
        self.rib_amplitude = float(
            rib_amplitude if rib_amplitude is not None else d["rib_amplitude"]
        )
        self.dome_segments = int(
            dome_segments if dome_segments is not None else d["dome_segments"]
        )
        self.n_arms = int(n_arms if n_arms is not None else d["n_arms"])
        self.arm_radius_fraction = float(
            arm_radius_fraction
            if arm_radius_fraction is not None
            else d["arm_radius_fraction"]
        )
        self.arm_horizontal_extent = float(
            arm_horizontal_extent
            if arm_horizontal_extent is not None
            else d["arm_horizontal_extent"]
        )
        self.arm_vertical_extent = float(
            arm_vertical_extent
            if arm_vertical_extent is not None
            else d["arm_vertical_extent"]
        )
        self.arm_z_fraction_range = tuple(
            arm_z_fraction_range
            if arm_z_fraction_range is not None
            else d["arm_z_fraction_range"]
        )
        self.has_flower = (
            bool(has_flower) if has_flower is not None else d["has_flower"]
        )
        self.flower_radius_fraction = float(
            flower_radius_fraction
            if flower_radius_fraction is not None
            else d["flower_radius_fraction"]
        )
        self.body_color = body_color or d["body_color"]
        self.flower_color = flower_color or d["flower_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyCactus({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        rng = random.Random(self.factory_seed)
        bm = bmesh.new()
        slot_ranges: list[tuple[int, int, int]] = []

        apex_pos = _build_ribbed_column(
            bm,
            slot_ranges,
            0,
            self.height,
            self.base_radius,
            self.top_radius,
            self.n_sides,
            self.n_layers,
            self.rib_amplitude,
            self.dome_segments,
        )

        if (
            self.n_arms > 0
            and self.arm_horizontal_extent > 0
            and self.arm_vertical_extent > 0
        ):
            base_yaw = rng.uniform(0, 2 * math.pi)
            for i in range(self.n_arms):
                yaw = (
                    base_yaw
                    + i * (2 * math.pi / max(self.n_arms, 1))
                    + rng.uniform(-0.3, 0.3)
                )
                z_frac = rng.uniform(*self.arm_z_fraction_range)
                attach_z = self.height * z_frac
                attach_r = (
                    self.base_radius
                    + (self.top_radius - self.base_radius) * z_frac
                )
                attach_pos = Vector(
                    (
                        attach_r * math.cos(yaw),
                        attach_r * math.sin(yaw),
                        attach_z,
                    )
                )
                arm_radius = self.top_radius * self.arm_radius_fraction
                h_ext = self.arm_horizontal_extent * rng.uniform(0.85, 1.10)
                v_ext = self.arm_vertical_extent * rng.uniform(0.85, 1.15)
                _build_saguaro_arm(
                    bm,
                    slot_ranges,
                    0,
                    attach_pos,
                    yaw,
                    arm_radius,
                    h_ext,
                    v_ext,
                    self.n_sides,
                    self.rib_amplitude,
                )

        if self.has_flower and self.flower_radius_fraction > 0:
            flower_radius = self.top_radius * self.flower_radius_fraction
            _build_flower_crown(bm, slot_ranges, 1, apex_pos, flower_radius)

        me = bpy.data.meshes.new(f"LowPolyCactus({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(f"LowPolyCactus({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)

        while len(obj.data.materials) < 2:
            obj.data.materials.append(None)

        for start, end, slot in slot_ranges:
            for i in range(start, end):
                obj.data.polygons[i].material_index = slot

        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(obj, [self.body_color, self.flower_color])
        return obj

"""LowPolyHaystackFactory — pile of hay / harvest-time silhouette.

Surfaced in Attempt 9 (farmstead at harvest) as the dominant missing
prop. Without it any "harvest" or "farm" scene reads as just "buildings
on grass" instead of "this place produces food".

Archetypes:
  cone           — classic conical haystack with flat-shaded sides
                   (medieval / European-rural read)
  rounded_mound  — tilted ellipsoid, "slumped" haystack
                   (more naturalistic, post-rain look)
  stacked_disks  — 3-4 cylindrical disks of decreasing radius stacked
                   (more stylized, Studio Ghibli / Sable read)

Knobs let the caller pick proportions and "lean" the stack — slightly
askew haystacks read as "in use" rather than ornamental.

Material slots:
  slot 0 = hay body                 (default `foliage_lemon` — straw)
  slot 1 = binding / shadow detail  (default `wood`, optional)
"""

from __future__ import annotations

import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector

from infinigen.core.placement.factory import AssetFactory

from ...density import (
    n_along_axis,
    n_sides_for_radius,
    target_edge_for_bbox,
)
from ...materials import apply_palette_slots


_HAYSTACK_ARCHETYPES = ("cone", "rounded_mound", "stacked_disks")


# Polygon counts (n_sides, n_layers) are derived from bbox via density.py
# at instantiation time. Defaults here are dimensional only.
_ARCHETYPE_DEFAULTS = {
    "cone": dict(
        height=1.8, radius=1.2,
        top_offset=(0.0, 0.0),
        detail_bands=True,
        hay_color="foliage_lemon", cap_color="wood",
    ),
    "rounded_mound": dict(
        height=1.4, radius=1.3,
        top_offset=(0.15, 0.0),  # slight lean
        detail_bands=True,
        hay_color="foliage_lemon", cap_color="foliage_amber",
    ),
    "stacked_disks": dict(
        height=2.0, radius=1.4,
        top_offset=(0.0, 0.0),
        detail_bands=True,
        hay_color="foliage_lemon", cap_color="wood",
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


def _add_box_slot(
    bm,
    slot_ranges: list[tuple[int, int, int]],
    slot: int,
    cx: float, cy: float, cz: float,
    sx: float, sy: float, sz: float,
) -> None:
    start = _bm_face_count(bm)
    _add_box(bm, cx, cy, cz, sx, sy, sz)
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))


def _add_binding_details(
    bm,
    slot_ranges: list[tuple[int, int, int]],
    radius: float,
    height: float,
) -> None:
    """Small tied bands and fallen straw strips.

    These are intentionally boxy so they survive distant isometric renders;
    they turn a pure cone/mound into an authored farm prop without adding
    expensive curved geometry.
    """
    band_h = max(0.035, height * 0.035)
    band_t = max(0.035, radius * 0.035)
    for t in (0.34, 0.58):
        z = height * t
        span = radius * (1.62 - 0.55 * t)
        offset = radius * (0.33 - 0.12 * t)
        _add_box_slot(bm, slot_ranges, 1, 0.0, offset, z, span, band_t, band_h)
        _add_box_slot(bm, slot_ranges, 1, 0.0, -offset, z + band_h * 0.7, span * 0.78, band_t, band_h)

    # A few short straw flecks around the base. Body slot, slightly raised.
    for i, angle in enumerate((0.25, 1.55, 2.75, 4.15)):
        r = radius * (0.72 + 0.08 * (i % 2))
        x = r * math.cos(angle)
        y = r * math.sin(angle)
        _add_box_slot(
            bm, slot_ranges, 0,
            x, y, band_h * 0.45,
            radius * 0.42, band_t * 0.7, band_h * 0.7,
        )


def _add_cone(
    bm,
    base_z: float,
    height: float,
    radius: float,
    n_sides: int,
    apex_offset_x: float,
    apex_offset_y: float,
) -> int:
    """A flat-shaded cone — n triangular sides + bottom n-gon. Apex can
    be offset horizontally for a leaning silhouette."""
    n_before = _bm_face_count(bm)
    apex = bm.verts.new((apex_offset_x, apex_offset_y, base_z + height))
    base_ring = []
    for s in range(n_sides):
        a = 2 * math.pi * s / n_sides
        x = radius * math.cos(a)
        y = radius * math.sin(a)
        base_ring.append(bm.verts.new((x, y, base_z)))
    bm.verts.ensure_lookup_table()
    for s in range(n_sides):
        ns = (s + 1) % n_sides
        bm.faces.new((base_ring[s], base_ring[ns], apex))
    bm.faces.new(list(reversed(base_ring)))
    return _bm_face_count(bm) - n_before


def _add_dome(
    bm,
    base_z: float,
    height: float,
    radius_x: float,
    radius_y: float,
    n_sides: int,
    n_rings: int,
    apex_offset_x: float,
    apex_offset_y: float,
) -> int:
    """A flattened ellipsoid (top half) — for rounded_mound. Built as
    n_rings horizontal rings narrowing toward the top."""
    n_before = _bm_face_count(bm)
    rings: list[list] = []
    # Bottom ring at base_z
    bottom_ring = []
    for s in range(n_sides):
        a = 2 * math.pi * s / n_sides
        bottom_ring.append(
            bm.verts.new((radius_x * math.cos(a), radius_y * math.sin(a), base_z))
        )
    rings.append(bottom_ring)
    # Intermediate rings narrowing toward the top
    for r in range(1, n_rings):
        t = r / n_rings
        z = base_z + height * t
        # cosine taper for ellipsoid look
        scale = math.cos(t * math.pi / 2)
        # Center each upper ring shifts toward the apex offset
        cx = apex_offset_x * t
        cy = apex_offset_y * t
        ring = []
        for s in range(n_sides):
            a = 2 * math.pi * s / n_sides
            ring.append(
                bm.verts.new((
                    cx + radius_x * scale * math.cos(a),
                    cy + radius_y * scale * math.sin(a),
                    z,
                ))
            )
        rings.append(ring)
    # Apex
    apex = bm.verts.new((apex_offset_x, apex_offset_y, base_z + height))
    bm.verts.ensure_lookup_table()
    # Side faces between consecutive rings
    for r in range(len(rings) - 1):
        a_ring = rings[r]
        b_ring = rings[r + 1]
        for s in range(n_sides):
            ns = (s + 1) % n_sides
            bm.faces.new((a_ring[s], a_ring[ns], b_ring[ns], b_ring[s]))
    # Top fan from last ring to apex
    top_ring = rings[-1]
    for s in range(n_sides):
        ns = (s + 1) % n_sides
        bm.faces.new((top_ring[s], top_ring[ns], apex))
    # Bottom n-gon
    bm.faces.new(list(reversed(rings[0])))
    return _bm_face_count(bm) - n_before


def _add_stacked_disks(
    bm,
    base_z: float,
    height: float,
    radius: float,
    n_sides: int,
    n_layers: int,
) -> int:
    """N stacked cylindrical disks of decreasing radius. Each disk is a
    short flat-shaded cylinder."""
    n_before = _bm_face_count(bm)
    disk_h = height / n_layers
    for layer in range(n_layers):
        # Radius shrinks toward the top: 1.0 → 0.4
        r_factor = 1.0 - (layer / n_layers) * 0.6
        r = radius * r_factor
        z0 = base_z + layer * disk_h
        z1 = z0 + disk_h
        bot = []
        top = []
        for s in range(n_sides):
            a = 2 * math.pi * s / n_sides
            bot.append(bm.verts.new((r * math.cos(a), r * math.sin(a), z0)))
            top.append(bm.verts.new((r * math.cos(a), r * math.sin(a), z1)))
        bm.verts.ensure_lookup_table()
        for s in range(n_sides):
            ns = (s + 1) % n_sides
            bm.faces.new((bot[s], bot[ns], top[ns], top[s]))
        # Cap top + bottom
        bm.faces.new(top)
        if layer == 0:
            bm.faces.new(list(reversed(bot)))
    return _bm_face_count(bm) - n_before


class LowPolyHaystackFactory(AssetFactory):
    """A pile of hay — cone, mound, or stacked disks.

    Constructor knobs:

        factory_seed
        haystack_archetype : str = "cone"
                             "cone" | "rounded_mound" | "stacked_disks"
        height             : float
        radius             : float
        polygon_multiplier : float = 1.0   <1 = denser, >1 = chunkier
        target_edge        : float         absolute world-edge override
        n_sides            : int           hard override of derived count
        n_layers           : int           hard override of derived count
        top_offset         : (dx, dy)  apex lateral offset for "lean"
        hay_color          : str    slot 0
        cap_color          : str    slot 1 (default same as hay_color)
    """

    def __init__(
        self,
        factory_seed,
        haystack_archetype: str = "cone",
        height: float | None = None,
        radius: float | None = None,
        polygon_multiplier: float = 1.0,
        target_edge: float | None = None,
        n_sides: int | None = None,
        n_layers: int | None = None,
        top_offset: tuple[float, float] | None = None,
        detail_bands: bool | None = None,
        hay_color: str | None = None,
        cap_color: str | None = None,
        coarse: bool = False,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if haystack_archetype not in _HAYSTACK_ARCHETYPES:
            # Lenient fallback rather than crash. Sonnet has been
            # observed to hallucinate plausible-sounding archetype
            # names despite the factories_guide brief listing the
            # valid set; killing a 6-minute build over a one-line
            # archetype typo wastes a generation. Substitute the
            # canonical default and warn to stderr.
            import sys
            print(
                f"[haystack_archetype] WARN: unknown haystack_archetype "
                f"{haystack_archetype!r}; falling back to {_HAYSTACK_ARCHETYPES[0]!r}. "
                f"Valid: {_HAYSTACK_ARCHETYPES}",
                file=sys.stderr,
            )
            haystack_archetype = _HAYSTACK_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[haystack_archetype]
        self.haystack_archetype = haystack_archetype
        self.height = float(height if height is not None else d["height"])
        self.radius = float(radius if radius is not None else d["radius"])
        edge = (
            float(target_edge) if target_edge is not None
            else target_edge_for_bbox(
                (self.radius * 2, self.radius * 2, self.height),
                polygon_multiplier=polygon_multiplier,
            )
        )
        self.n_sides = int(
            n_sides if n_sides is not None
            else n_sides_for_radius(self.radius, edge)
        )
        self.n_layers = int(
            n_layers if n_layers is not None
            else n_along_axis(self.height, edge)
        )
        offset = top_offset if top_offset is not None else d["top_offset"]
        self.top_offset = (float(offset[0]), float(offset[1]))
        self.detail_bands = (
            bool(detail_bands) if detail_bands is not None else bool(d["detail_bands"])
        )
        self.hay_color = hay_color or d["hay_color"]
        self.cap_color = cap_color or d["cap_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyHaystack({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        bm = bmesh.new()
        slot_ranges: list[tuple[int, int, int]] = []

        if self.haystack_archetype == "cone":
            _add_cone(
                bm, 0.0, self.height, self.radius, self.n_sides,
                self.top_offset[0], self.top_offset[1],
            )
        elif self.haystack_archetype == "rounded_mound":
            _add_dome(
                bm, 0.0, self.height, self.radius, self.radius * 0.85,
                self.n_sides, n_rings=3,
                apex_offset_x=self.top_offset[0],
                apex_offset_y=self.top_offset[1],
            )
        elif self.haystack_archetype == "stacked_disks":
            _add_stacked_disks(
                bm, 0.0, self.height, self.radius, self.n_sides, self.n_layers,
            )
        else:
            raise AssertionError(self.haystack_archetype)

        if self.detail_bands:
            _add_binding_details(bm, slot_ranges, self.radius, self.height)

        me = bpy.data.meshes.new(f"LowPolyHaystack({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(f"LowPolyHaystack({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)

        # 2 slots even if cap defaults to same as body — lets caller swap
        # cap_color independently without rebuilding.
        while len(obj.data.materials) < 2:
            obj.data.materials.append(None)

        for start, end, slot in slot_ranges:
            for i in range(start, end):
                obj.data.polygons[i].material_index = slot

        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(obj, [self.hay_color, self.cap_color])
        return obj

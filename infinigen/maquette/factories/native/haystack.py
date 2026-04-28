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
  slot 1 = cap / pole tip           (default same as body, optional)
"""

from __future__ import annotations

import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_HAYSTACK_ARCHETYPES = ("cone", "rounded_mound", "stacked_disks")


_ARCHETYPE_DEFAULTS = {
    "cone": dict(
        height=1.8, radius=1.2, n_sides=8, n_layers=1,
        top_offset=(0.0, 0.0),
        hay_color="foliage_lemon", cap_color="foliage_lemon",
    ),
    "rounded_mound": dict(
        height=1.4, radius=1.3, n_sides=10, n_layers=1,
        top_offset=(0.15, 0.0),  # slight lean
        hay_color="foliage_lemon", cap_color="foliage_lemon",
    ),
    "stacked_disks": dict(
        height=2.0, radius=1.4, n_sides=8, n_layers=4,
        top_offset=(0.0, 0.0),
        hay_color="foliage_lemon", cap_color="foliage_lemon",
    ),
}


def _bm_face_count(bm) -> int:
    return len(bm.faces)


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
        n_sides            : int    cylinder/cone side count
        n_layers           : int    disks for stacked_disks
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
        n_sides: int | None = None,
        n_layers: int | None = None,
        top_offset: tuple[float, float] | None = None,
        hay_color: str | None = None,
        cap_color: str | None = None,
        coarse: bool = False,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if haystack_archetype not in _HAYSTACK_ARCHETYPES:
            raise ValueError(
                f"unknown haystack_archetype {haystack_archetype!r}; "
                f"valid: {_HAYSTACK_ARCHETYPES}"
            )
        d = _ARCHETYPE_DEFAULTS[haystack_archetype]
        self.haystack_archetype = haystack_archetype
        self.height = float(height if height is not None else d["height"])
        self.radius = float(radius if radius is not None else d["radius"])
        self.n_sides = int(n_sides if n_sides is not None else d["n_sides"])
        self.n_layers = int(n_layers if n_layers is not None else d["n_layers"])
        offset = top_offset if top_offset is not None else d["top_offset"]
        self.top_offset = (float(offset[0]), float(offset[1]))
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

        me = bpy.data.meshes.new(f"LowPolyHaystack({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(f"LowPolyHaystack({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)

        # 2 slots even if cap defaults to same as body — lets caller swap
        # cap_color independently without rebuilding.
        while len(obj.data.materials) < 2:
            obj.data.materials.append(None)

        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(obj, [self.hay_color, self.cap_color])
        return obj

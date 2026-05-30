"""LowPolyHouseFactory — Sapling-style native low-poly building.

Architectural design loosely follows ranjian0/building_tools' patterns
(parametric floorplan → walls → roof → openings) but reimplemented from
scratch in pure bmesh. The vendored btools dependency was attempted
first and reverted because btools relies on bpy.ops + interactive
operator context, which fails reliably in headless --background mode.

What this generates (v0a):
  - Rectangular footprint (width × depth)
  - Walls extruded up to wall_height, single mesh
  - One of three roof archetypes:
      gabled   — triangular prism along the long axis
      hipped   — pyramidal roof (4 triangular faces)
      flat     — no roof; tiny rim cap to read as a flat-roof house
  - One door cutout on the long front wall (decorative — no actual
    boolean, just a colored panel inset)
  - n_windows windows distributed on the two side walls

All geometry is one mesh with six material slots:
  slot 0 = walls          (default rock_pale)
  slot 1 = roof           (default rock_shadow)
  slot 2 = trim/details   (door + timber trim; default accent_red)
  slot 3 = foundation     (default rock_shadow)
  slot 4 = windows        (default sky_cool; optionally emissive)
  slot 5 = foliage/accent (default foliage_rose)

Single-archetype "house" only for v0a; barns / towers / ruins are
parameter-tuning + topology variants on top of the same skeleton.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

import bmesh
import bpy
from mathutils import Vector

from infinigen.core.placement.factory import AssetFactory

from ...materials import (
    add_palette_point_light,
    apply_emission_palette_slot,
    apply_palette_slots,
)


_ROOF_ARCHETYPES = (
    "gabled",
    "hipped",
    "flat",
    "shed",
    "gambrel",
    "mansard",
    "cross_gabled",
    "pyramid",
)

_BUILDING_ARCHETYPES = (
    "cottage",
    "barn",
    "tower",
    "cabin",
    "longhouse",
    "townhouse",
    "workshop",
    "tavern",
    "stable",
)


# Per-archetype default proportions / roof / window count. The user can
# still override any individual knob; archetype just provides sensible
# defaults so the silhouettes read as DIFFERENT BUILDINGS, not just a
# rectangle in different dimensions.
_ARCHETYPE_DEFAULTS = {
    "cottage": dict(
        width=4.0, depth=3.0, wall_height=2.5, roof_height=1.6,
        roof_archetype="cross_gabled", n_windows=4, has_chimney=True,
        foundation_height=0.4, roof_overhang=0.35,
        detail_level="rich", storeys=1,
        has_awning=False, has_side_shed=False,
        has_balcony=False, has_side_stairs=False,
        has_flower_boxes=True, has_chairs=True,
    ),
    "barn": dict(
        # Long + low + steep gabled — silhouette dominated by the roof
        width=7.0, depth=3.5, wall_height=2.2, roof_height=2.6,
        roof_archetype="gambrel", n_windows=2, has_chimney=False,
        foundation_height=0.0, roof_overhang=0.45,  # barns sit directly on dirt
        detail_level="medium", storeys=1,
        has_awning=False, has_side_shed=True,
        has_balcony=False, has_side_stairs=False,
        has_flower_boxes=False, has_chairs=False,
    ),
    "tower": dict(
        # Square footprint, tall walls, peaked hipped — guard tower feel
        width=2.6, depth=2.6, wall_height=5.0, roof_height=2.0,
        roof_archetype="pyramid", n_windows=4, has_chimney=False,
        foundation_height=0.8, roof_overhang=0.18,  # tall foundation reads as fortified base
        detail_level="medium", storeys=3,
        has_awning=False, has_side_shed=False,
        has_balcony=True, has_side_stairs=True,
        has_flower_boxes=False, has_chairs=False,
    ),
    "cabin": dict(
        # Small, snug, basic gabled — Firewatch lookout cabin
        width=3.0, depth=3.0, wall_height=2.2, roof_height=1.4,
        roof_archetype="gabled", n_windows=2, has_chimney=True,
        foundation_height=0.3, roof_overhang=0.32,
        detail_level="medium", storeys=1,
        has_awning=False, has_side_shed=False,
        has_balcony=False, has_side_stairs=False,
        has_flower_boxes=True, has_chairs=True,
    ),
    "longhouse": dict(
        # 2-story-ish wide rectangle, hipped — manor / lodge feel
        width=6.0, depth=4.0, wall_height=3.5, roof_height=1.8,
        roof_archetype="hipped", n_windows=6, has_chimney=True,
        foundation_height=0.5, roof_overhang=0.38,
        detail_level="rich", storeys=2,
        has_awning=False, has_side_shed=False,
        has_balcony=True, has_side_stairs=False,
        has_flower_boxes=True, has_chairs=False,
    ),
    "townhouse": dict(
        # Taller street-facing house; good for denser WFC rows.
        width=4.1, depth=3.4, wall_height=4.0, roof_height=1.4,
        roof_archetype="mansard", n_windows=8, has_chimney=True,
        foundation_height=0.35, roof_overhang=0.26,
        detail_level="rich", storeys=2,
        has_awning=False, has_side_shed=False,
        has_balcony=True, has_side_stairs=True,
        has_flower_boxes=True, has_chairs=False,
    ),
    "workshop": dict(
        # Broad front + side lean-to reads as smithy/craft shed.
        width=5.2, depth=3.8, wall_height=2.8, roof_height=1.35,
        roof_archetype="shed", n_windows=4, has_chimney=True,
        foundation_height=0.25, roof_overhang=0.42,
        detail_level="rich", storeys=1,
        has_awning=False, has_side_shed=True,
        has_balcony=False, has_side_stairs=False,
        has_flower_boxes=False, has_chairs=True,
    ),
    "tavern": dict(
        # Large public-facing building with a small front awning.
        width=5.5, depth=4.2, wall_height=3.1, roof_height=1.75,
        roof_archetype="cross_gabled", n_windows=6, has_chimney=True,
        foundation_height=0.45, roof_overhang=0.42,
        detail_level="rich", storeys=2,
        has_awning=True, has_side_shed=False,
        has_balcony=True, has_side_stairs=False,
        has_flower_boxes=True, has_chairs=True,
    ),
    "stable": dict(
        # Long, low service building; useful for outskirts/farms.
        width=6.4, depth=3.2, wall_height=2.25, roof_height=2.05,
        roof_archetype="gambrel", n_windows=2, has_chimney=False,
        foundation_height=0.0, roof_overhang=0.46,
        detail_level="medium", storeys=1,
        has_awning=False, has_side_shed=True,
        has_balcony=False, has_side_stairs=False,
        has_flower_boxes=False, has_chairs=False,
    ),
}


@dataclass
class _BuildingMesh:
    """Internal carrier for the partial bmesh build state — accumulates
    face indices per material slot so we can set polygon material_index
    after bm.to_mesh."""

    bm: bmesh.types.BMesh
    wall_face_indices: list[int]
    roof_face_indices: list[int]
    opening_face_indices: list[int]


def _bm_face_count(bm) -> int:
    return len(bm.faces)


def _add_box(
    bm: bmesh.types.BMesh,
    *,
    center: tuple[float, float, float],
    size: tuple[float, float, float],
) -> int:
    """Add a small rectangular prism to the active mesh."""

    cx, cy, cz = center
    sx, sy, sz = max(size[0], 0.01), max(size[1], 0.01), max(size[2], 0.01)
    hx, hy, hz = sx * 0.5, sy * 0.5, sz * 0.5
    n_before = _bm_face_count(bm)
    v000 = bm.verts.new((cx - hx, cy - hy, cz - hz))
    v100 = bm.verts.new((cx + hx, cy - hy, cz - hz))
    v110 = bm.verts.new((cx + hx, cy + hy, cz - hz))
    v010 = bm.verts.new((cx - hx, cy + hy, cz - hz))
    v001 = bm.verts.new((cx - hx, cy - hy, cz + hz))
    v101 = bm.verts.new((cx + hx, cy - hy, cz + hz))
    v111 = bm.verts.new((cx + hx, cy + hy, cz + hz))
    v011 = bm.verts.new((cx - hx, cy + hy, cz + hz))
    bm.verts.ensure_lookup_table()
    bm.faces.new((v000, v100, v110, v010))
    bm.faces.new((v001, v011, v111, v101))
    bm.faces.new((v000, v001, v101, v100))
    bm.faces.new((v100, v101, v111, v110))
    bm.faces.new((v110, v111, v011, v010))
    bm.faces.new((v010, v011, v001, v000))
    return _bm_face_count(bm) - n_before


def _add_rect_prism_faces(
    bm: bmesh.types.BMesh,
    *,
    z0: float,
    z1: float,
    hw: float,
    hd: float,
) -> list:
    """Create a rectangular ring pair and close its side faces.

    Used for fascia/plinth-like roof pieces. Returns the top ring.
    """
    b00 = bm.verts.new((-hw, -hd, z0))
    b10 = bm.verts.new((+hw, -hd, z0))
    b11 = bm.verts.new((+hw, +hd, z0))
    b01 = bm.verts.new((-hw, +hd, z0))
    t00 = bm.verts.new((-hw, -hd, z1))
    t10 = bm.verts.new((+hw, -hd, z1))
    t11 = bm.verts.new((+hw, +hd, z1))
    t01 = bm.verts.new((-hw, +hd, z1))
    bm.verts.ensure_lookup_table()
    bm.faces.new((b00, b10, t10, t00))
    bm.faces.new((b10, b11, t11, t10))
    bm.faces.new((b11, b01, t01, t11))
    bm.faces.new((b01, b00, t00, t01))
    return [t00, t10, t11, t01]


def _add_roof_fascia(
    bm: bmesh.types.BMesh,
    *,
    hw: float,
    hd: float,
    z: float,
    height: float,
) -> None:
    """Vertical eave skirt. This is the practical gap fix: roof geometry
    now visibly intersects/overlaps the wall top instead of ending at a
    paper-thin perimeter."""
    _add_rect_prism_faces(bm, z0=z - height, z1=z, hw=hw, hd=hd)


def _add_roof_strip(
    bm: bmesh.types.BMesh,
    *,
    center: tuple[float, float, float],
    size: tuple[float, float, float],
) -> None:
    _add_box(bm, center=center, size=size)


def _roof_base(top_ring: list, width: float, depth: float, overhang: float) -> tuple[float, float, float]:
    z = top_ring[0].co.z
    return width / 2 + max(overhang, 0.0), depth / 2 + max(overhang, 0.0), z


def _add_gabled_roof_core(
    bm: bmesh.types.BMesh,
    *,
    width: float,
    depth: float,
    z: float,
    roof_height: float,
    overhang: float,
    cross_axis: str = "auto",
    tile_strips: bool = True,
) -> None:
    """Closed gabled roof with expanded eave vertices and a ridge cap.

    cross_axis controls ridge direction:
      - "x": ridge runs along X
      - "y": ridge runs along Y
      - "auto": ridge runs along the longer footprint axis
    """
    hw, hd = width / 2 + max(overhang, 0.0), depth / 2 + max(overhang, 0.0)
    eave_z = z - 0.035
    _add_roof_fascia(bm, hw=hw, hd=hd, z=eave_z, height=max(0.12, overhang * 0.36))
    z_ridge = eave_z + roof_height
    long_along_x = width >= depth if cross_axis == "auto" else cross_axis == "x"
    if long_along_x:
        s_w = bm.verts.new((-hw, -hd, eave_z))
        s_e = bm.verts.new((+hw, -hd, eave_z))
        n_e = bm.verts.new((+hw, +hd, eave_z))
        n_w = bm.verts.new((-hw, +hd, eave_z))
        r_w = bm.verts.new((-hw, 0.0, z_ridge))
        r_e = bm.verts.new((+hw, 0.0, z_ridge))
        bm.verts.ensure_lookup_table()
        bm.faces.new((s_w, s_e, r_e, r_w))
        bm.faces.new((r_w, r_e, n_e, n_w))
        bm.faces.new((s_e, n_e, r_e))
        bm.faces.new((n_w, s_w, r_w))
        _add_roof_strip(bm, center=(0.0, 0.0, z_ridge + 0.045), size=(hw * 2.03, 0.13, 0.09))
        if tile_strips:
            for side in (-1.0, 1.0):
                for t in (0.28, 0.56, 0.80):
                    y = side * hd * t
                    strip_z = eave_z + roof_height * (1.0 - abs(y) / max(hd, 1e-6)) + 0.035
                    _add_roof_strip(
                        bm,
                        center=(0.0, y, strip_z),
                        size=(hw * 1.92, 0.055, 0.055),
                    )
    else:
        e_s = bm.verts.new((0.0, -hd, z_ridge))
        e_n = bm.verts.new((0.0, +hd, z_ridge))
        s_w = bm.verts.new((-hw, -hd, eave_z))
        s_e = bm.verts.new((+hw, -hd, eave_z))
        n_e = bm.verts.new((+hw, +hd, eave_z))
        n_w = bm.verts.new((-hw, +hd, eave_z))
        bm.verts.ensure_lookup_table()
        bm.faces.new((s_e, n_e, e_n, e_s))
        bm.faces.new((e_s, e_n, n_w, s_w))
        bm.faces.new((s_w, s_e, e_s))
        bm.faces.new((e_n, n_e, n_w))
        _add_roof_strip(bm, center=(0.0, 0.0, z_ridge + 0.045), size=(0.13, hd * 2.03, 0.09))
        if tile_strips:
            for side in (-1.0, 1.0):
                for t in (0.28, 0.56, 0.80):
                    x = side * hw * t
                    strip_z = eave_z + roof_height * (1.0 - abs(x) / max(hw, 1e-6)) + 0.035
                    _add_roof_strip(
                        bm,
                        center=(x, 0.0, strip_z),
                        size=(0.055, hd * 1.92, 0.055),
                    )


def _add_front_gable_accent(
    bm: bmesh.types.BMesh,
    *,
    width: float,
    depth: float,
    z: float,
    roof_height: float,
    overhang: float,
) -> None:
    """Small cross-gable/dormer mass on the front roof face.

    It is roof-colored here by design because it is emitted inside the
    roof range. The trim system adds wall-color frontage underneath.
    """
    dormer_w = min(width * 0.42, 2.4)
    dormer_d = min(depth * 0.46, 1.8)
    y = -(depth / 2 + overhang * 0.78)
    base_z = z + roof_height * 0.34
    before_verts = len(bm.verts)
    _add_gabled_roof_core(
        bm,
        width=dormer_w,
        depth=dormer_d,
        z=base_z,
        roof_height=roof_height * 0.42,
        overhang=max(0.08, overhang * 0.34),
        cross_axis="y",
        tile_strips=False,
    )
    # Move the vertices just emitted for the dormer to the front by
    # translating only the vertices created above since the base helper
    # emits centered.
    bm.verts.ensure_lookup_table()
    for v in list(bm.verts)[before_verts:]:
        v.co.y += y


def _add_walls(
    bm: bmesh.types.BMesh,
    width: float,
    depth: float,
    wall_height: float,
    foundation_height: float = 0.0,
) -> tuple[list, int, int]:
    """Build the wall box. If foundation_height > 0, the lower band of
    each wall is split into a separate quad strip so the caller can
    assign it a different material slot.

    Returns (wall_top_ring, n_main_wall_faces, n_foundation_faces).
    Foundation faces are added FIRST so the caller can assign them to
    a dedicated slot via index range."""
    hw, hd = width / 2, depth / 2
    has_foundation = foundation_height > 1e-4
    n_foundation_faces = 0
    n_before_walls = _bm_face_count(bm)

    # Bottom ring (z=0)
    b00 = bm.verts.new((-hw, -hd, 0))
    b10 = bm.verts.new((+hw, -hd, 0))
    b11 = bm.verts.new((+hw, +hd, 0))
    b01 = bm.verts.new((-hw, +hd, 0))

    if has_foundation:
        # Mid ring (z=foundation_height) — splits walls into foundation strip + main
        m00 = bm.verts.new((-hw, -hd, foundation_height))
        m10 = bm.verts.new((+hw, -hd, foundation_height))
        m11 = bm.verts.new((+hw, +hd, foundation_height))
        m01 = bm.verts.new((-hw, +hd, foundation_height))
    else:
        m00, m10, m11, m01 = b00, b10, b11, b01

    # Top ring (z=wall_height)
    t00 = bm.verts.new((-hw, -hd, wall_height))
    t10 = bm.verts.new((+hw, -hd, wall_height))
    t11 = bm.verts.new((+hw, +hd, wall_height))
    t01 = bm.verts.new((-hw, +hd, wall_height))

    bm.verts.ensure_lookup_table()

    # Foundation strip (4 quads) — added first so material slot tagging
    # by index range is clean.
    if has_foundation:
        n_before_foundation = _bm_face_count(bm)
        bm.faces.new((b00, b10, m10, m00))   # south foundation
        bm.faces.new((b10, b11, m11, m10))   # east
        bm.faces.new((b11, b01, m01, m11))   # north
        bm.faces.new((b01, b00, m00, m01))   # west
        n_foundation_faces = _bm_face_count(bm) - n_before_foundation

    # Floor (z=0)
    bm.faces.new((b00, b10, b11, b01))
    # Main wall strip (4 quads from mid → top)
    bm.faces.new((m00, m10, t10, t00))   # south
    bm.faces.new((m10, m11, t11, t10))   # east
    bm.faces.new((m11, m01, t01, t11))   # north
    bm.faces.new((m01, m00, t00, t01))   # west

    n_walls = _bm_face_count(bm) - n_before_walls - n_foundation_faces
    return [t00, t10, t11, t01], n_walls, n_foundation_faces


def _add_roof_gabled(
    bm: bmesh.types.BMesh,
    top_ring: list,
    width: float,
    depth: float,
    roof_height: float,
    overhang: float = 0.0,
) -> int:
    """Closed triangular-prism roof with real eaves, fascia, ridge cap,
    and low-poly batten strips."""
    n_before = _bm_face_count(bm)
    _, _, z = _roof_base(top_ring, width, depth, overhang)
    _add_gabled_roof_core(
        bm,
        width=width,
        depth=depth,
        z=z,
        roof_height=roof_height,
        overhang=overhang,
    )
    return _bm_face_count(bm) - n_before


def _add_roof_hipped(
    bm: bmesh.types.BMesh,
    top_ring: list,
    width: float,
    depth: float,
    roof_height: float,
    overhang: float = 0.0,
) -> int:
    """Hipped roof with a short ridge on the long axis, not a pyramid."""
    n_before = _bm_face_count(bm)
    hw, hd, z = _roof_base(top_ring, width, depth, overhang)
    eave_z = z - 0.035
    _add_roof_fascia(bm, hw=hw, hd=hd, z=eave_z, height=max(0.12, overhang * 0.36))
    z_ridge = eave_z + roof_height
    long_along_x = width >= depth
    if long_along_x:
        s_w = bm.verts.new((-hw, -hd, eave_z))
        s_e = bm.verts.new((+hw, -hd, eave_z))
        n_e = bm.verts.new((+hw, +hd, eave_z))
        n_w = bm.verts.new((-hw, +hd, eave_z))
        inset = min(hw * 0.45, hd * 0.95)
        r_w = bm.verts.new((-hw + inset, 0.0, z_ridge))
        r_e = bm.verts.new((+hw - inset, 0.0, z_ridge))
        bm.verts.ensure_lookup_table()
        bm.faces.new((s_w, s_e, r_e, r_w))
        bm.faces.new((r_w, r_e, n_e, n_w))
        bm.faces.new((s_e, n_e, r_e))
        bm.faces.new((n_w, s_w, r_w))
        _add_roof_strip(bm, center=(0.0, 0.0, z_ridge + 0.045), size=(max(0.2, (hw - inset) * 2.05), 0.13, 0.09))
    else:
        s_w = bm.verts.new((-hw, -hd, eave_z))
        s_e = bm.verts.new((+hw, -hd, eave_z))
        n_e = bm.verts.new((+hw, +hd, eave_z))
        n_w = bm.verts.new((-hw, +hd, eave_z))
        inset = min(hd * 0.45, hw * 0.95)
        r_s = bm.verts.new((0.0, -hd + inset, z_ridge))
        r_n = bm.verts.new((0.0, +hd - inset, z_ridge))
        bm.verts.ensure_lookup_table()
        bm.faces.new((s_e, n_e, r_n, r_s))
        bm.faces.new((r_s, r_n, n_w, s_w))
        bm.faces.new((s_w, s_e, r_s))
        bm.faces.new((r_n, n_e, n_w))
        _add_roof_strip(bm, center=(0.0, 0.0, z_ridge + 0.045), size=(0.13, max(0.2, (hd - inset) * 2.05), 0.09))
    for side in (-1.0, 1.0):
        for t in (0.36, 0.68):
            if long_along_x:
                y = side * hd * t
                _add_roof_strip(bm, center=(0.0, y, eave_z + roof_height * (1 - t) + 0.035), size=(hw * 1.55, 0.05, 0.05))
            else:
                x = side * hw * t
                _add_roof_strip(bm, center=(x, 0.0, eave_z + roof_height * (1 - t) + 0.035), size=(0.05, hd * 1.55, 0.05))
    return _bm_face_count(bm) - n_before


def _add_roof_pyramid(
    bm: bmesh.types.BMesh,
    top_ring: list,
    width: float,
    depth: float,
    roof_height: float,
    overhang: float = 0.0,
) -> int:
    """Pyramid roof for towers/small square buildings."""
    n_before = _bm_face_count(bm)
    hw, hd, z = _roof_base(top_ring, width, depth, overhang)
    eave_z = z - 0.035
    _add_roof_fascia(bm, hw=hw, hd=hd, z=eave_z, height=max(0.10, overhang * 0.32))
    t00 = bm.verts.new((-hw, -hd, eave_z))
    t10 = bm.verts.new((+hw, -hd, eave_z))
    t11 = bm.verts.new((+hw, +hd, eave_z))
    t01 = bm.verts.new((-hw, +hd, eave_z))
    apex = bm.verts.new((0.0, 0.0, eave_z + roof_height))
    bm.verts.ensure_lookup_table()
    bm.faces.new((t00, t10, apex))
    bm.faces.new((t10, t11, apex))
    bm.faces.new((t11, t01, apex))
    bm.faces.new((t01, t00, apex))
    _add_roof_strip(bm, center=(0.0, 0.0, eave_z + roof_height * 0.96), size=(0.18, 0.18, 0.10))
    return _bm_face_count(bm) - n_before


def _add_roof_shed(
    bm: bmesh.types.BMesh,
    top_ring: list,
    width: float,
    depth: float,
    roof_height: float,
    overhang: float = 0.0,
) -> int:
    """Single-slope service-building roof."""
    n_before = _bm_face_count(bm)
    hw, hd, z = _roof_base(top_ring, width, depth, overhang)
    eave_z = z - 0.035
    _add_roof_fascia(bm, hw=hw, hd=hd, z=eave_z, height=max(0.12, overhang * 0.34))
    low_s_w = bm.verts.new((-hw, -hd, eave_z))
    low_s_e = bm.verts.new((+hw, -hd, eave_z))
    high_n_e = bm.verts.new((+hw, +hd, eave_z + roof_height))
    high_n_w = bm.verts.new((-hw, +hd, eave_z + roof_height))
    bm.verts.ensure_lookup_table()
    bm.faces.new((low_s_w, low_s_e, high_n_e, high_n_w))
    bm.faces.new((low_s_e, high_n_e, bm.verts.new((+hw, +hd, eave_z)), bm.verts.new((+hw, -hd, eave_z))))
    bm.faces.new((bm.verts.new((-hw, -hd, eave_z)), bm.verts.new((-hw, +hd, eave_z)), high_n_w, low_s_w))
    _add_roof_strip(bm, center=(0.0, +hd, eave_z + roof_height + 0.045), size=(hw * 2.02, 0.12, 0.09))
    for t in (0.28, 0.56, 0.82):
        y = -hd + 2 * hd * t
        _add_roof_strip(bm, center=(0.0, y, eave_z + roof_height * t + 0.035), size=(hw * 1.9, 0.05, 0.05))
    return _bm_face_count(bm) - n_before


def _add_roof_gambrel(
    bm: bmesh.types.BMesh,
    top_ring: list,
    width: float,
    depth: float,
    roof_height: float,
    overhang: float = 0.0,
) -> int:
    """Two-slope barn roof. Much stronger than a plain triangle for farms."""
    n_before = _bm_face_count(bm)
    hw, hd, z = _roof_base(top_ring, width, depth, overhang)
    eave_z = z - 0.035
    _add_roof_fascia(bm, hw=hw, hd=hd, z=eave_z, height=max(0.12, overhang * 0.34))
    long_x = width >= depth
    if long_x:
        b_s_w = bm.verts.new((-hw, -hd, eave_z)); b_s_e = bm.verts.new((+hw, -hd, eave_z))
        b_n_e = bm.verts.new((+hw, +hd, eave_z)); b_n_w = bm.verts.new((-hw, +hd, eave_z))
        m_s_w = bm.verts.new((-hw, -hd * 0.54, eave_z + roof_height * 0.58)); m_s_e = bm.verts.new((+hw, -hd * 0.54, eave_z + roof_height * 0.58))
        m_n_e = bm.verts.new((+hw, +hd * 0.54, eave_z + roof_height * 0.58)); m_n_w = bm.verts.new((-hw, +hd * 0.54, eave_z + roof_height * 0.58))
        r_w = bm.verts.new((-hw, 0.0, eave_z + roof_height)); r_e = bm.verts.new((+hw, 0.0, eave_z + roof_height))
        bm.verts.ensure_lookup_table()
        bm.faces.new((b_s_w, b_s_e, m_s_e, m_s_w))
        bm.faces.new((m_s_w, m_s_e, r_e, r_w))
        bm.faces.new((r_w, r_e, m_n_e, m_n_w))
        bm.faces.new((m_n_w, m_n_e, b_n_e, b_n_w))
        bm.faces.new((b_s_e, b_n_e, m_n_e, r_e, m_s_e))
        bm.faces.new((b_n_w, b_s_w, m_s_w, r_w, m_n_w))
        _add_roof_strip(bm, center=(0.0, 0.0, eave_z + roof_height + 0.045), size=(hw * 2.02, 0.13, 0.09))
        for y, zf in ((-hd * 0.54, 0.60), (+hd * 0.54, 0.60), (-hd * 0.80, 0.30), (+hd * 0.80, 0.30)):
            _add_roof_strip(bm, center=(0.0, y, eave_z + roof_height * zf + 0.035), size=(hw * 1.92, 0.055, 0.055))
    else:
        _add_gabled_roof_core(bm, width=width, depth=depth, z=z, roof_height=roof_height, overhang=overhang, cross_axis="y")
    return _bm_face_count(bm) - n_before


def _add_roof_mansard(
    bm: bmesh.types.BMesh,
    top_ring: list,
    width: float,
    depth: float,
    roof_height: float,
    overhang: float = 0.0,
) -> int:
    """Mansard roof: steep lower hip with a small flat top."""
    n_before = _bm_face_count(bm)
    hw, hd, z = _roof_base(top_ring, width, depth, overhang)
    eave_z = z - 0.035
    _add_roof_fascia(bm, hw=hw, hd=hd, z=eave_z, height=max(0.10, overhang * 0.32))
    mid_hw, mid_hd = hw * 0.68, hd * 0.68
    top_z = eave_z + roof_height
    mid_z = eave_z + roof_height * 0.78
    b00 = bm.verts.new((-hw, -hd, eave_z)); b10 = bm.verts.new((+hw, -hd, eave_z))
    b11 = bm.verts.new((+hw, +hd, eave_z)); b01 = bm.verts.new((-hw, +hd, eave_z))
    m00 = bm.verts.new((-mid_hw, -mid_hd, mid_z)); m10 = bm.verts.new((+mid_hw, -mid_hd, mid_z))
    m11 = bm.verts.new((+mid_hw, +mid_hd, mid_z)); m01 = bm.verts.new((-mid_hw, +mid_hd, mid_z))
    t00 = bm.verts.new((-mid_hw * 0.82, -mid_hd * 0.82, top_z)); t10 = bm.verts.new((+mid_hw * 0.82, -mid_hd * 0.82, top_z))
    t11 = bm.verts.new((+mid_hw * 0.82, +mid_hd * 0.82, top_z)); t01 = bm.verts.new((-mid_hw * 0.82, +mid_hd * 0.82, top_z))
    bm.verts.ensure_lookup_table()
    for a, b, c, d in ((b00, b10, m10, m00), (b10, b11, m11, m10), (b11, b01, m01, m11), (b01, b00, m00, m01)):
        bm.faces.new((a, b, c, d))
    for a, b, c, d in ((m00, m10, t10, t00), (m10, m11, t11, t10), (m11, m01, t01, t11), (m01, m00, t00, t01)):
        bm.faces.new((a, b, c, d))
    bm.faces.new((t00, t10, t11, t01))
    for y in (-hd * 0.72, hd * 0.72):
        _add_roof_strip(bm, center=(0.0, y, eave_z + roof_height * 0.48), size=(hw * 1.62, 0.05, 0.05))
    return _bm_face_count(bm) - n_before


def _add_roof_cross_gabled(
    bm: bmesh.types.BMesh,
    top_ring: list,
    width: float,
    depth: float,
    roof_height: float,
    overhang: float = 0.0,
) -> int:
    n_before = _bm_face_count(bm)
    _, _, z = _roof_base(top_ring, width, depth, overhang)
    _add_gabled_roof_core(
        bm,
        width=width,
        depth=depth,
        z=z,
        roof_height=roof_height,
        overhang=overhang,
    )
    _add_front_gable_accent(
        bm,
        width=width,
        depth=depth,
        z=z,
        roof_height=roof_height,
        overhang=overhang,
    )
    return _bm_face_count(bm) - n_before


def _add_roof_flat(
    bm: bmesh.types.BMesh,
    top_ring: list,
    overhang: float = 0.0,
) -> int:
    """No real roof — just a closed cap at wall_height. Optionally a
    1-vertex bump in the centre to give a slight shadow under flat
    shading. Keeping it dead flat for v0a."""
    n_before = _bm_face_count(bm)
    if overhang > 1e-4:
        z = top_ring[0].co.z
        xs = [v.co.x for v in top_ring]
        ys = [v.co.y for v in top_ring]
        t00 = bm.verts.new((min(xs) - overhang, min(ys) - overhang, z))
        t10 = bm.verts.new((max(xs) + overhang, min(ys) - overhang, z))
        t11 = bm.verts.new((max(xs) + overhang, max(ys) + overhang, z))
        t01 = bm.verts.new((min(xs) - overhang, max(ys) + overhang, z))
        bm.verts.ensure_lookup_table()
    else:
        t00, t10, t11, t01 = top_ring
    bm.faces.new((t00, t10, t11, t01))
    return _bm_face_count(bm) - n_before


def _add_door(
    bm: bmesh.types.BMesh,
    width: float,
    depth: float,
    wall_height: float,
    door_w: float = 0.9,
    door_h: float = 1.9,
    inset: float = 0.02,
) -> int:
    """Decorative door panel on the SOUTH wall (−Y face), inset slightly
    so it's not z-fighting. Single quad. v0a doesn't bool-cut the wall
    — at low poly the inset reads as a closed door visually."""
    hw, hd = width / 2, depth / 2
    n_before = _bm_face_count(bm)
    z0 = 0.05  # raise off the floor a hair
    y = -hd - inset  # poke OUT of south wall (towards camera)
    door_left = -door_w / 2
    door_right = +door_w / 2
    v0 = bm.verts.new((door_left, y, z0))
    v1 = bm.verts.new((door_right, y, z0))
    v2 = bm.verts.new((door_right, y, z0 + door_h))
    v3 = bm.verts.new((door_left, y, z0 + door_h))
    bm.verts.ensure_lookup_table()
    bm.faces.new((v0, v1, v2, v3))
    return _bm_face_count(bm) - n_before


def _add_chimney(
    bm: bmesh.types.BMesh,
    width: float,
    depth: float,
    wall_height: float,
    roof_height: float,
    chimney_w: float = 0.45,
    chimney_h: float = 1.6,
    side_offset: float = 0.6,
) -> int:
    """Square chimney box rising from the roof. Placed offset toward one
    side of the building (not centered) for character. Sized for visible
    silhouette without dominating."""
    n_before = _bm_face_count(bm)
    # Anchor point: on the roof, offset along X toward one wall
    base_x = width / 2 - side_offset - chimney_w / 2
    base_y = 0.0
    base_z = wall_height + roof_height * 0.45  # plant chimney mid-roof
    hx = chimney_w / 2
    hy = chimney_w / 2
    z0 = base_z
    z1 = base_z + chimney_h
    # 8 corners of a small box
    v000 = bm.verts.new((base_x - hx, base_y - hy, z0))
    v100 = bm.verts.new((base_x + hx, base_y - hy, z0))
    v110 = bm.verts.new((base_x + hx, base_y + hy, z0))
    v010 = bm.verts.new((base_x - hx, base_y + hy, z0))
    v001 = bm.verts.new((base_x - hx, base_y - hy, z1))
    v101 = bm.verts.new((base_x + hx, base_y - hy, z1))
    v111 = bm.verts.new((base_x + hx, base_y + hy, z1))
    v011 = bm.verts.new((base_x - hx, base_y + hy, z1))
    bm.verts.ensure_lookup_table()
    # 4 sides + top (skip bottom — buried in roof)
    bm.faces.new((v000, v100, v101, v001))
    bm.faces.new((v100, v110, v111, v101))
    bm.faces.new((v110, v010, v011, v111))
    bm.faces.new((v010, v000, v001, v011))
    bm.faces.new((v001, v101, v111, v011))
    return _bm_face_count(bm) - n_before


def _add_windows(
    bm: bmesh.types.BMesh,
    width: float,
    depth: float,
    wall_height: float,
    n_windows: int,
    rng: random.Random,
    storeys: int = 1,
    win_w: float = 0.46,
    win_h: float = 0.50,
    inset: float = 0.02,
) -> int:
    """Decorative window panels on the two side (east/west) walls. Equally
    spaced along the wall length. Same inset trick as the door."""
    hw, hd = width / 2, depth / 2
    n_before = _bm_face_count(bm)
    # Distribute n_windows along Y on each of west(−X) and east(+X)
    if n_windows <= 0:
        return 0
    z_levels = _storey_window_levels(wall_height, storeys)
    per_side = max(1, min(3, math.ceil(max(n_windows, 1) / (2 * len(z_levels)))))
    margin = 0.6
    span = max(depth - 2 * margin, 0.1)
    for side, x_face in (("west", -hw), ("east", +hw)):
        for z in z_levels:
            for i in range(per_side):
                t = (i + 1) / (per_side + 1)
                cy = -hd + margin + t * span
                x = x_face + (-inset if side == "east" else +inset)
                # Window face is in the YZ plane; quad runs along Y
                v0 = bm.verts.new((x, cy - win_w / 2, z - win_h / 2))
                v1 = bm.verts.new((x, cy + win_w / 2, z - win_h / 2))
                v2 = bm.verts.new((x, cy + win_w / 2, z + win_h / 2))
                v3 = bm.verts.new((x, cy - win_w / 2, z + win_h / 2))
                bm.verts.ensure_lookup_table()
                bm.faces.new((v0, v1, v2, v3))
    return _bm_face_count(bm) - n_before


def _clamped_storeys(storeys: int | None, wall_height: float) -> int:
    if storeys is None:
        storeys = 2 if wall_height > 3.25 else 1
    return max(1, min(3, int(storeys)))


def _storey_window_levels(wall_height: float, storeys: int | None) -> list[float]:
    """Window center heights by floor.

    The factory is intentionally low-poly, so storeys are expressed as
    facade grammar rather than literal interior floors. This is the same
    component idea as the castle kit: stacked readable modules, not one
    hand-authored building per variant.
    """
    storeys_i = _clamped_storeys(storeys, wall_height)
    if storeys_i <= 1:
        return [min(wall_height * 0.56, wall_height - 0.52)]
    bottom = min(1.35, wall_height * 0.36)
    top = max(bottom + 0.45, wall_height - 0.72)
    if storeys_i == 2:
        return [bottom, top]
    mid = bottom + (top - bottom) * 0.50
    return [bottom, mid, top]


def _add_facade_windows(
    bm: bmesh.types.BMesh,
    width: float,
    depth: float,
    wall_height: float,
    n_windows: int,
    rng: random.Random,
    storeys: int = 1,
    win_w: float = 0.42,
    win_h: float = 0.48,
    inset: float = 0.026,
) -> int:
    """Front/back wall windows.

    The old factory mostly decorated side walls, which made default
    camera-facing facades read as blank boxes. These panels deliberately
    avoid the central door bay.
    """
    if n_windows <= 2:
        return 0
    hw, hd = width / 2, depth / 2
    n_before = _bm_face_count(bm)
    z_levels = _storey_window_levels(wall_height, storeys)
    x_positions = [-width * 0.28, width * 0.28]
    if width > 5.4:
        x_positions = [-width * 0.34, 0.0, width * 0.34]
    for face, y in (("front", -hd - inset), ("back", +hd + inset)):
        for z in z_levels:
            for x in x_positions:
                if face == "front" and abs(x) < width * 0.16 and z < wall_height * 0.58:
                    continue
                jitter = rng.uniform(-0.04, 0.04)
                v0 = bm.verts.new((x - win_w / 2, y, z - win_h / 2 + jitter))
                v1 = bm.verts.new((x + win_w / 2, y, z - win_h / 2 + jitter))
                v2 = bm.verts.new((x + win_w / 2, y, z + win_h / 2 + jitter))
                v3 = bm.verts.new((x - win_w / 2, y, z + win_h / 2 + jitter))
                bm.verts.ensure_lookup_table()
                if face == "front":
                    bm.faces.new((v0, v1, v2, v3))
                else:
                    bm.faces.new((v3, v2, v1, v0))
    return _bm_face_count(bm) - n_before


def _add_storey_bands(
    bm: bmesh.types.BMesh,
    *,
    width: float,
    depth: float,
    wall_height: float,
    storeys: int,
) -> None:
    storeys_i = _clamped_storeys(storeys, wall_height)
    if storeys_i <= 1:
        return
    hw, hd = width / 2, depth / 2
    out = 0.074
    band_h = 0.08
    for floor_idx in range(1, storeys_i):
        z = wall_height * floor_idx / storeys_i
        _add_box(bm, center=(0.0, -hd - out, z), size=(width + 0.22, 0.09, band_h))
        _add_box(bm, center=(0.0, +hd + out, z), size=(width + 0.22, 0.09, band_h))
        _add_box(bm, center=(-hw - out, 0.0, z), size=(0.09, depth + 0.22, band_h))
        _add_box(bm, center=(+hw + out, 0.0, z), size=(0.09, depth + 0.22, band_h))


def _add_balcony(
    bm: bmesh.types.BMesh,
    *,
    width: float,
    depth: float,
    wall_height: float,
    storeys: int,
) -> None:
    hw, hd = width / 2, depth / 2
    levels = _storey_window_levels(wall_height, storeys)
    target_z = levels[min(1, len(levels) - 1)] - 0.42
    deck_z = max(1.62, min(wall_height - 0.68, target_z))
    deck_w = min(width * 0.62, 3.15)
    deck_d = min(depth * 0.28, 0.88)
    y = -hd - deck_d * 0.42
    _add_box(bm, center=(0.0, y, deck_z), size=(deck_w, deck_d, 0.12))
    # Brackets under the deck.
    for x in (-deck_w * 0.38, deck_w * 0.38):
        _add_box(bm, center=(x, y + deck_d * 0.16, deck_z - 0.28), size=(0.12, 0.14, 0.55))
    # Railing posts and rails. Chunky enough to read at camera distance.
    rail_z = deck_z + 0.42
    post_h = 0.78
    for x in (-deck_w * 0.48, 0.0, deck_w * 0.48):
        _add_box(bm, center=(x, y - deck_d * 0.44, deck_z + post_h * 0.5), size=(0.08, 0.08, post_h))
    _add_box(bm, center=(0.0, y - deck_d * 0.46, rail_z), size=(deck_w * 0.98, 0.07, 0.08))
    _add_box(bm, center=(-deck_w * 0.51, y - deck_d * 0.08, rail_z), size=(0.07, deck_d * 0.78, 0.08))
    _add_box(bm, center=(+deck_w * 0.51, y - deck_d * 0.08, rail_z), size=(0.07, deck_d * 0.78, 0.08))


def _add_side_stairs(
    bm: bmesh.types.BMesh,
    *,
    width: float,
    depth: float,
    wall_height: float,
    storeys: int,
    side: float,
) -> None:
    hw, hd = width / 2, depth / 2
    levels = _storey_window_levels(wall_height, storeys)
    landing_z = max(1.45, min(wall_height - 0.75, levels[min(1, len(levels) - 1)] - 0.42))
    x = side * (hw + 0.48)
    stair_len = min(depth * 0.94, 3.25)
    start_y = -hd + 0.25
    step_count = 7
    step_y = stair_len / step_count
    step_w = 0.72
    for i in range(step_count):
        t = (i + 1) / step_count
        y = start_y + (i + 0.5) * step_y
        z = max(0.08, landing_z * t * 0.5)
        _add_box(
            bm,
            center=(x, y, z),
            size=(step_w, step_y * 0.86, max(0.10, landing_z / step_count * 0.54)),
        )
    _add_box(
        bm,
        center=(x, start_y + stair_len + 0.12, landing_z),
        size=(step_w * 1.06, 0.52, 0.12),
    )
    rail_x = x + side * (step_w * 0.48)
    _add_box(
        bm,
        center=(rail_x, start_y + stair_len * 0.52, landing_z * 0.58),
        size=(0.07, stair_len * 0.96, 0.10),
    )


def _add_flower_boxes(
    bm: bmesh.types.BMesh,
    *,
    width: float,
    depth: float,
    wall_height: float,
    storeys: int,
    rng: random.Random,
) -> tuple[int, int]:
    """Add wooden planters plus small flower clumps.

    Returns (planter_face_count, flower_face_count) so the caller can put
    flowers in the foliage material slot while keeping the boxes as timber.
    """
    if width < 2.7:
        return (0, 0)
    n_before = _bm_face_count(bm)
    hw, hd = width / 2, depth / 2
    z = _storey_window_levels(wall_height, storeys)[0] - 0.36
    x_positions = [-width * 0.28, width * 0.28]
    if width > 5.3:
        x_positions = [-width * 0.34, 0.0, width * 0.34]
    for x in x_positions:
        if abs(x) < width * 0.16:
            continue
        _add_box(bm, center=(x, -hd - 0.082, z), size=(0.58, 0.13, 0.14))
    n_planter = _bm_face_count(bm) - n_before
    for x in x_positions:
        if abs(x) < width * 0.16:
            continue
        for dx in (-0.19, 0.0, 0.19):
            _add_box(
                bm,
                center=(x + dx, -hd - 0.16, z + 0.13 + rng.uniform(-0.015, 0.025)),
                size=(0.09, 0.09, 0.09),
            )
    n_flower = _bm_face_count(bm) - n_before - n_planter
    return (n_planter, n_flower)


def _add_chairs_and_table(
    bm: bmesh.types.BMesh,
    *,
    width: float,
    depth: float,
    rng: random.Random,
) -> None:
    hd = depth / 2
    side = -1.0 if rng.random() < 0.5 else 1.0
    x0 = side * min(width * 0.34, 1.45)
    y0 = -hd - 0.78
    # Tiny cafe/front-yard read: table top, stem, and two chairs.
    _add_box(bm, center=(x0, y0, 0.40), size=(0.46, 0.46, 0.08))
    _add_box(bm, center=(x0, y0, 0.22), size=(0.10, 0.10, 0.36))
    for sx in (-1.0, 1.0):
        _add_box(bm, center=(x0 + sx * 0.46, y0, 0.23), size=(0.28, 0.26, 0.10))
        _add_box(bm, center=(x0 + sx * 0.52, y0 + 0.13, 0.46), size=(0.08, 0.08, 0.42))


def _add_architectural_trim(
    bm: bmesh.types.BMesh,
    *,
    width: float,
    depth: float,
    wall_height: float,
    storeys: int,
    detail_level: str,
    has_awning: bool,
    has_side_shed: bool,
    has_balcony: bool,
    has_side_stairs: bool,
    has_chairs: bool,
    rng: random.Random,
) -> int:
    """Add timber/trim geometry that makes houses read as authored pieces.

    These are intentionally chunky low-poly prisms rather than texture detail:
    they survive the default camera distance and match the modular castle kit's
    readable silhouette language.
    """

    if detail_level == "plain":
        return 0
    n_before = _bm_face_count(bm)
    hw, hd = width / 2, depth / 2
    out = 0.055
    post = 0.16 if detail_level == "medium" else 0.20
    band = 0.14 if detail_level == "medium" else 0.18
    _add_storey_bands(
        bm,
        width=width,
        depth=depth,
        wall_height=wall_height,
        storeys=storeys,
    )

    # Corner posts.
    z_mid = wall_height * 0.5
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            _add_box(
                bm,
                center=(sx * (hw + out), sy * (hd + out), z_mid),
                size=(post, post, wall_height + 0.08),
            )

    # Front/back and side upper bands under the roofline.
    z_band = max(wall_height - 0.28, wall_height * 0.78)
    _add_box(bm, center=(0.0, -hd - out, z_band), size=(width + 0.30, band, band))
    _add_box(bm, center=(0.0, +hd + out, z_band), size=(width + 0.30, band, band))
    _add_box(bm, center=(-hw - out, 0.0, z_band), size=(band, depth + 0.30, band))
    _add_box(bm, center=(+hw + out, 0.0, z_band), size=(band, depth + 0.30, band))

    if detail_level == "rich":
        # A lower belt and two asymmetric front braces prevent the facade
        # from reading as one flat rectangle.
        _add_box(bm, center=(0.0, -hd - out * 1.15, wall_height * 0.34), size=(width * 0.72, band * 0.82, band * 0.72))
        brace_z = wall_height * 0.58
        for x in (-width * 0.28, width * 0.28):
            _add_box(bm, center=(x, -hd - out * 1.35, brace_z), size=(post * 0.75, band * 0.85, wall_height * 0.42))

    # Door frame and lintel on the front face.
    door_w = min(1.0, width * 0.28)
    door_h = min(1.95, wall_height * 0.78)
    for x in (-door_w * 0.62, door_w * 0.62):
        _add_box(bm, center=(x, -hd - out * 1.8, door_h * 0.5), size=(0.11, 0.12, door_h))
    _add_box(bm, center=(0.0, -hd - out * 1.85, door_h + 0.08), size=(door_w * 1.55, 0.13, 0.13))

    # Simple shutters / mullions around the most camera-facing windows.
    if detail_level == "rich":
        frame_w = 0.52
        frame_h = 0.58
        bar = 0.045
        x_positions = [-width * 0.28, width * 0.28]
        if width > 5.4:
            x_positions = [-width * 0.34, 0.0, width * 0.34]
        for z in _storey_window_levels(wall_height, storeys):
            for x in x_positions:
                if abs(x) < width * 0.16 and z < wall_height * 0.58:
                    continue
                y = -hd - out * 1.95
                _add_box(bm, center=(x - frame_w * 0.5, y, z), size=(bar, 0.09, frame_h))
                _add_box(bm, center=(x + frame_w * 0.5, y, z), size=(bar, 0.09, frame_h))
                _add_box(bm, center=(x, y, z + frame_h * 0.5), size=(frame_w + bar, 0.09, bar))
                _add_box(bm, center=(x, y, z - frame_h * 0.5), size=(frame_w + bar, 0.09, bar))

    if has_balcony:
        _add_balcony(
            bm,
            width=width,
            depth=depth,
            wall_height=wall_height,
            storeys=storeys,
        )

    if has_side_stairs:
        _add_side_stairs(
            bm,
            width=width,
            depth=depth,
            wall_height=wall_height,
            storeys=storeys,
            side=-1.0 if rng.random() < 0.5 else 1.0,
        )

    if has_awning:
        _add_box(
            bm,
            center=(0.0, -hd - 0.42, min(wall_height * 0.86, 2.55)),
            size=(min(width * 0.72, 3.8), 0.72, 0.10),
        )
        for x in (-min(width * 0.26, 1.25), min(width * 0.26, 1.25)):
            _add_box(
                bm,
                center=(x, -hd - 0.72, min(wall_height * 0.48, 1.55)),
                size=(0.10, 0.10, min(wall_height * 0.55, 1.8)),
            )

    if has_side_shed:
        side = -1.0 if rng.random() < 0.5 else 1.0
        shed_w = min(depth * 0.70, 2.5)
        shed_d = min(width * 0.38, 2.4)
        shed_x = side * (hw + shed_d * 0.45)
        shed_y = rng.uniform(-depth * 0.18, depth * 0.18)
        shed_body_h = max(0.55, wall_height * 0.44)
        shed_body_z = max(0.55, wall_height * 0.22)
        _add_box(
            bm,
            center=(shed_x, shed_y, shed_body_z),
            size=(shed_d, shed_w, shed_body_h),
        )
        shed_top = shed_body_z + shed_body_h * 0.5
        _add_box(
            bm,
            center=(shed_x, shed_y, shed_top + 0.07),
            size=(shed_d * 1.25, shed_w * 1.10, 0.12),
        )

    if has_chairs:
        _add_chairs_and_table(bm, width=width, depth=depth, rng=rng)

    return _bm_face_count(bm) - n_before


class LowPolyHouseFactory(AssetFactory):
    """A flat-shaded low-poly stylized cottage.

    Constructor knobs:

        factory_seed
        roof_archetype : "gabled" | "hipped" | "flat" — default "gabled"
        width, depth   : footprint dims, m
        wall_height    : extruded wall height, m
        roof_height    : ridge / apex height above wall top, m
        n_windows      : total windows distributed on side walls
        wall_color     : palette key for walls (slot 0)
        roof_color     : palette key for roof  (slot 1)
        accent_color   : palette key for door + windows (slot 2)
    """

    def __init__(
        self,
        factory_seed,
        building_archetype: str = "cottage",
        roof_archetype: str | None = None,
        width: float | None = None,
        depth: float | None = None,
        wall_height: float | None = None,
        roof_height: float | None = None,
        n_windows: int | None = None,
        has_chimney: bool | None = None,
        foundation_height: float | None = None,
        roof_overhang: float | None = None,
        detail_level: str | None = None,
        has_awning: bool | None = None,
        has_side_shed: bool | None = None,
        storeys: int | None = None,
        has_balcony: bool | None = None,
        has_side_stairs: bool | None = None,
        has_flower_boxes: bool | None = None,
        has_chairs: bool | None = None,
        wall_color: str | None = "rock_pale",
        roof_color: str | None = "rock_shadow",
        accent_color: str | None = "accent_red",
        foundation_color: str | None = "rock_shadow",
        window_color: str | None = "sky_cool",
        foliage_color: str | None = "foliage_rose",
        window_glow: bool = False,
        window_glow_color: str | None = None,
        window_emission_strength: float = 1.5,
        emit_window_light: bool = False,
        window_light_energy: float = 24.0,
        window_light_radius: float = 2.0,
        coarse: bool = False,
        **_unused_kwargs,
    ):
        from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
        accept_unused_kwargs("LowPolyHouseFactory", _unused_kwargs)
        super().__init__(factory_seed, coarse=coarse)
        if building_archetype not in _BUILDING_ARCHETYPES:
            # Lenient fallback rather than crash. Sonnet has been
            # observed to hallucinate plausible-sounding archetype
            # names despite the factories_guide brief listing the
            # valid set; killing a 6-minute build over a one-line
            # archetype typo wastes a generation. Substitute the
            # canonical default and warn to stderr.
            import sys
            print(
                f"[building_archetype] WARN: unknown building_archetype "
                f"{building_archetype!r}; falling back to {_BUILDING_ARCHETYPES[0]!r}. "
                f"Valid: {_BUILDING_ARCHETYPES}",
                file=sys.stderr,
            )
            building_archetype = _BUILDING_ARCHETYPES[0]
        # Pull archetype defaults; explicit kwargs override.
        d = _ARCHETYPE_DEFAULTS[building_archetype]
        self.building_archetype = building_archetype
        roof_archetype = roof_archetype or d["roof_archetype"]
        if roof_archetype not in _ROOF_ARCHETYPES:
            # Lenient fallback rather than crash. Sonnet has been
            # observed to hallucinate plausible-sounding archetype
            # names despite the factories_guide brief listing the
            # valid set; killing a 6-minute build over a one-line
            # archetype typo wastes a generation. Substitute the
            # canonical default and warn to stderr.
            import sys
            print(
                f"[roof_archetype] WARN: unknown roof_archetype "
                f"{roof_archetype!r}; falling back to {_ROOF_ARCHETYPES[0]!r}. "
                f"Valid: {_ROOF_ARCHETYPES}",
                file=sys.stderr,
            )
            roof_archetype = _ROOF_ARCHETYPES[0]
        self.roof_archetype = roof_archetype
        self.width = float(width if width is not None else d["width"])
        self.depth = float(depth if depth is not None else d["depth"])
        self.wall_height = float(wall_height if wall_height is not None else d["wall_height"])
        self.roof_height = float(roof_height if roof_height is not None else d["roof_height"])
        self.n_windows = int(n_windows if n_windows is not None else d["n_windows"])
        self.has_chimney = bool(has_chimney if has_chimney is not None else d["has_chimney"])
        self.foundation_height = float(
            foundation_height if foundation_height is not None else d["foundation_height"]
        )
        self.roof_overhang = float(
            roof_overhang if roof_overhang is not None else d["roof_overhang"]
        )
        self.detail_level = str(detail_level if detail_level is not None else d["detail_level"])
        if self.detail_level not in {"plain", "medium", "rich"}:
            self.detail_level = "rich"
        self.has_awning = bool(has_awning if has_awning is not None else d["has_awning"])
        self.has_side_shed = bool(has_side_shed if has_side_shed is not None else d["has_side_shed"])
        self.storeys = _clamped_storeys(
            int(storeys if storeys is not None else d["storeys"]),
            self.wall_height,
        )
        self.has_balcony = bool(has_balcony if has_balcony is not None else d["has_balcony"])
        self.has_side_stairs = bool(
            has_side_stairs if has_side_stairs is not None else d["has_side_stairs"]
        )
        self.has_flower_boxes = bool(
            has_flower_boxes if has_flower_boxes is not None else d["has_flower_boxes"]
        )
        self.has_chairs = bool(has_chairs if has_chairs is not None else d["has_chairs"])
        self.wall_color = wall_color
        self.roof_color = roof_color
        self.accent_color = accent_color
        self.foundation_color = foundation_color
        self.window_glow = bool(window_glow)
        self.window_glow_color = window_glow_color or "sky_warm"
        self.window_emission_strength = max(0.0, float(window_emission_strength))
        self.emit_window_light = bool(emit_window_light)
        self.window_light_energy = max(0.0, float(window_light_energy))
        self.window_light_radius = max(0.05, float(window_light_radius))
        self.window_color = self.window_glow_color if self.window_glow else window_color
        self.foliage_color = foliage_color

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyHouse({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        rng = random.Random(self.factory_seed)
        bm = bmesh.new()

        # 1. Walls (+ optional foundation strip, returned in face_count
        # via the n_foundation_faces channel; foundation faces are
        # FIRST, walls follow).
        face_count_walls_start = _bm_face_count(bm)
        top_ring, _, n_foundation_faces = _add_walls(
            bm, self.width, self.depth, self.wall_height,
            foundation_height=self.foundation_height,
        )
        face_count_walls_end = _bm_face_count(bm)
        # Range for foundation slot reassignment (slot 3)
        face_count_foundation_start = face_count_walls_start
        face_count_foundation_end = face_count_walls_start + n_foundation_faces

        # 2. Roof
        face_count_roof_start = face_count_walls_end
        if self.roof_archetype == "gabled":
            _add_roof_gabled(
                bm,
                top_ring,
                self.width,
                self.depth,
                self.roof_height,
                overhang=self.roof_overhang,
            )
        elif self.roof_archetype == "hipped":
            _add_roof_hipped(
                bm,
                top_ring,
                self.width,
                self.depth,
                self.roof_height,
                overhang=self.roof_overhang,
            )
        elif self.roof_archetype == "pyramid":
            _add_roof_pyramid(
                bm,
                top_ring,
                self.width,
                self.depth,
                self.roof_height,
                overhang=self.roof_overhang,
            )
        elif self.roof_archetype == "shed":
            _add_roof_shed(
                bm,
                top_ring,
                self.width,
                self.depth,
                self.roof_height,
                overhang=self.roof_overhang,
            )
        elif self.roof_archetype == "gambrel":
            _add_roof_gambrel(
                bm,
                top_ring,
                self.width,
                self.depth,
                self.roof_height,
                overhang=self.roof_overhang,
            )
        elif self.roof_archetype == "mansard":
            _add_roof_mansard(
                bm,
                top_ring,
                self.width,
                self.depth,
                self.roof_height,
                overhang=self.roof_overhang,
            )
        elif self.roof_archetype == "cross_gabled":
            _add_roof_cross_gabled(
                bm,
                top_ring,
                self.width,
                self.depth,
                self.roof_height,
                overhang=self.roof_overhang,
            )
        else:  # flat
            _add_roof_flat(bm, top_ring, overhang=self.roof_overhang)
        face_count_roof_end = _bm_face_count(bm)

        # 3. Door + windows. These are intentionally separate material
        # ranges: doors/trim remain timber/accent, windows get a muted
        # glass slot so facades stop reading as red/brown stamps.
        face_count_door_start = face_count_roof_end
        _add_door(bm, self.width, self.depth, self.wall_height)
        face_count_door_end = _bm_face_count(bm)
        face_count_window_start = face_count_door_end
        _add_windows(
            bm,
            self.width,
            self.depth,
            self.wall_height,
            self.n_windows,
            rng,
            storeys=self.storeys,
        )
        _add_facade_windows(
            bm,
            self.width,
            self.depth,
            self.wall_height,
            self.n_windows,
            rng,
            storeys=self.storeys,
        )
        face_count_window_end = _bm_face_count(bm)

        # 4. Optional chimney (rises from roof; chimney faces inherit the
        # default material_index=0, so they pick up the wall_color slot).
        if self.has_chimney and self.roof_archetype != "flat":
            _add_chimney(bm, self.width, self.depth,
                         self.wall_height, self.roof_height)

        # 5. Chunky trim/lean-to/awning detail. This is the main v1
        # quality bump: actual silhouette geometry instead of paper-flat
        # building boxes.
        face_count_detail_start = _bm_face_count(bm)
        _add_architectural_trim(
            bm,
            width=self.width,
            depth=self.depth,
            wall_height=self.wall_height,
            storeys=self.storeys,
            detail_level=self.detail_level,
            has_awning=self.has_awning,
            has_side_shed=self.has_side_shed,
            has_balcony=self.has_balcony,
            has_side_stairs=self.has_side_stairs,
            has_chairs=self.has_chairs,
            rng=rng,
        )
        face_count_detail_end = _bm_face_count(bm)

        face_count_flower_start = _bm_face_count(bm)
        planter_faces = 0
        flower_faces = 0
        if self.has_flower_boxes:
            planter_faces, flower_faces = _add_flower_boxes(
                bm,
                width=self.width,
                depth=self.depth,
                wall_height=self.wall_height,
                storeys=self.storeys,
                rng=rng,
            )
        face_count_flower_planter_end = face_count_flower_start + planter_faces
        face_count_flower_end = face_count_flower_planter_end + flower_faces

        # Convert to mesh + object
        me = bpy.data.meshes.new(f"LowPolyHouse({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(
            f"LowPolyHouse({self.factory_seed})", me
        )
        bpy.context.scene.collection.objects.link(obj)

        # Pre-allocate 6 material slots so polygon.material_index sticks.
        # Slots:
        #   0 walls, 1 roof, 2 trim/details, 3 foundation, 4 windows,
        #   5 foliage/flowers.
        while len(obj.data.materials) < 6:
            obj.data.materials.append(None)

        # Assign material_index per face based on the recorded ranges.
        # Default = slot 0 (walls). Override:
        #   - foundation strip   → slot 3
        #   - roof faces         → slot 1
        #   - door/trim/details  → slot 2
        #   - windows            → slot 4
        #   - flowers            → slot 5
        if face_count_foundation_end > face_count_foundation_start:
            for i in range(face_count_foundation_start, face_count_foundation_end):
                obj.data.polygons[i].material_index = 3
        for i in range(face_count_roof_start, face_count_roof_end):
            obj.data.polygons[i].material_index = 1
        for i in range(face_count_door_start, face_count_door_end):
            obj.data.polygons[i].material_index = 2
        for i in range(face_count_window_start, face_count_window_end):
            obj.data.polygons[i].material_index = 4
        for i in range(face_count_detail_start, face_count_detail_end):
            obj.data.polygons[i].material_index = 2
        for i in range(face_count_flower_start, face_count_flower_planter_end):
            obj.data.polygons[i].material_index = 2
        for i in range(face_count_flower_planter_end, face_count_flower_end):
            obj.data.polygons[i].material_index = 5

        # Flat shading on every poly — Maquette-canonical low-poly read.
        for p in obj.data.polygons:
            p.use_smooth = False

        # Apply 6-slot palette
        slot_colors = [
            self.wall_color or "rock_pale",
            self.roof_color or "rock_shadow",
            self.accent_color or "accent_red",
            self.foundation_color or "rock_shadow",
            self.window_color or "sky_cool",
            self.foliage_color or "foliage_rose",
        ]
        apply_palette_slots(obj, slot_colors)
        if self.window_glow:
            apply_emission_palette_slot(
                obj,
                4,
                self.window_glow_color,
                strength=self.window_emission_strength,
            )
        if self.window_glow and self.emit_window_light:
            add_palette_point_light(
                name=f"{obj.name}_window_glow",
                location=(
                    0.0,
                    -self.depth * 0.5 - 0.35,
                    min(self.wall_height * 0.58, self.wall_height - 0.25),
                ),
                palette_key=self.window_glow_color,
                energy=self.window_light_energy,
                radius=self.window_light_radius,
                parent=obj,
            )
        return obj


# Compatibility re-export. LLM-generated build scripts sometimes write
# ``from infinigen.maquette.factories.native.building import LowPolyChapelFactory``
# because the model conflates "chapel" with the generic "building" module —
# the canonical class lives in ``factories.native.chapel``. Keep that path
# working so a good scene does not crash before Blender even starts (same
# pattern as ``factories/boat.py`` and ``factories/wagon.py`` compat shims).
from infinigen.maquette.factories.native.chapel import LowPolyChapelFactory  # noqa: E402

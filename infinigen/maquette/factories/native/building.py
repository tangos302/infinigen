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

All geometry is one mesh with three material slots:
  slot 0 = walls          (default rock_pale)
  slot 1 = roof           (default rock_shadow)
  slot 2 = openings       (door + windows; default accent_red)

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

from ...materials import apply_palette_slots


_ROOF_ARCHETYPES = ("gabled", "hipped", "flat")

_BUILDING_ARCHETYPES = ("cottage", "barn", "tower", "cabin", "longhouse")


# Per-archetype default proportions / roof / window count. The user can
# still override any individual knob; archetype just provides sensible
# defaults so the silhouettes read as DIFFERENT BUILDINGS, not just a
# rectangle in different dimensions.
_ARCHETYPE_DEFAULTS = {
    "cottage": dict(
        width=4.0, depth=3.0, wall_height=2.5, roof_height=1.6,
        roof_archetype="gabled", n_windows=4,
    ),
    "barn": dict(
        # Long + low + steep gabled — silhouette dominated by the roof
        width=7.0, depth=3.5, wall_height=2.2, roof_height=2.6,
        roof_archetype="gabled", n_windows=2,
    ),
    "tower": dict(
        # Square footprint, tall walls, peaked hipped — guard tower feel
        width=2.6, depth=2.6, wall_height=5.0, roof_height=2.0,
        roof_archetype="hipped", n_windows=4,
    ),
    "cabin": dict(
        # Small, snug, basic gabled — Firewatch lookout cabin
        width=3.0, depth=3.0, wall_height=2.2, roof_height=1.4,
        roof_archetype="gabled", n_windows=2,
    ),
    "longhouse": dict(
        # 2-story-ish wide rectangle, hipped — manor / lodge feel
        width=6.0, depth=4.0, wall_height=3.5, roof_height=1.8,
        roof_archetype="hipped", n_windows=6,
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


def _add_walls(
    bm: bmesh.types.BMesh,
    width: float,
    depth: float,
    wall_height: float,
) -> tuple[list, int]:
    """Build 4 wall quads + a floor (hidden underneath). Returns
    (wall_top_ring, n_wall_faces) — the top-ring verts are the anchor
    for whichever roof archetype runs next."""
    hw, hd = width / 2, depth / 2
    # Bottom ring (floor corners)
    b00 = bm.verts.new((-hw, -hd, 0))
    b10 = bm.verts.new((+hw, -hd, 0))
    b11 = bm.verts.new((+hw, +hd, 0))
    b01 = bm.verts.new((-hw, +hd, 0))
    # Top ring (wall tops)
    t00 = bm.verts.new((-hw, -hd, wall_height))
    t10 = bm.verts.new((+hw, -hd, wall_height))
    t11 = bm.verts.new((+hw, +hd, wall_height))
    t01 = bm.verts.new((-hw, +hd, wall_height))
    bm.verts.ensure_lookup_table()
    n_before = _bm_face_count(bm)
    # Floor (skip — invisible from outside, but include for closed mesh)
    bm.faces.new((b00, b10, b11, b01))
    # 4 walls (front=south=−Y, back=+Y, left=−X, right=+X)
    bm.faces.new((b00, b10, t10, t00))   # south wall
    bm.faces.new((b10, b11, t11, t10))   # east
    bm.faces.new((b11, b01, t01, t11))   # north
    bm.faces.new((b01, b00, t00, t01))   # west
    return [t00, t10, t11, t01], _bm_face_count(bm) - n_before


def _add_roof_gabled(
    bm: bmesh.types.BMesh,
    top_ring: list,
    width: float,
    depth: float,
    roof_height: float,
) -> int:
    """Triangular-prism roof along the LONG axis. Long axis = whichever of
    width/depth is larger. Ridge runs along that axis at height
    wall_height + roof_height."""
    t00, t10, t11, t01 = top_ring
    n_before = _bm_face_count(bm)
    hw, hd = width / 2, depth / 2
    z_ridge = top_ring[0].co.z + roof_height
    long_along_x = width >= depth
    if long_along_x:
        # Ridge runs along X. Ridge endpoints at midpoints of the two
        # narrow (east/west) walls.
        ridge_w = bm.verts.new((-hw, 0, z_ridge))
        ridge_e = bm.verts.new((+hw, 0, z_ridge))
        bm.verts.ensure_lookup_table()
        # South slope: t00, t10, ridge_e, ridge_w
        bm.faces.new((t00, t10, ridge_e, ridge_w))
        # North slope: ridge_w, ridge_e, t11, t01
        bm.faces.new((ridge_w, ridge_e, t11, t01))
        # Triangular gables (east + west walls' tops)
        bm.faces.new((t10, t11, ridge_e))
        bm.faces.new((t01, t00, ridge_w))
    else:
        # Ridge runs along Y. Same logic rotated 90°.
        ridge_s = bm.verts.new((0, -hd, z_ridge))
        ridge_n = bm.verts.new((0, +hd, z_ridge))
        bm.verts.ensure_lookup_table()
        bm.faces.new((t10, t11, ridge_n, ridge_s))
        bm.faces.new((ridge_s, ridge_n, t01, t00))
        bm.faces.new((t00, t10, ridge_s))
        bm.faces.new((ridge_n, t11, t01))
    return _bm_face_count(bm) - n_before


def _add_roof_hipped(
    bm: bmesh.types.BMesh,
    top_ring: list,
    roof_height: float,
) -> int:
    """4-sided pyramid (hipped) roof — apex at the centroid of the wall
    top ring, raised by roof_height."""
    t00, t10, t11, t01 = top_ring
    n_before = _bm_face_count(bm)
    cx = (t00.co.x + t10.co.x + t11.co.x + t01.co.x) / 4
    cy = (t00.co.y + t10.co.y + t11.co.y + t01.co.y) / 4
    apex = bm.verts.new((cx, cy, top_ring[0].co.z + roof_height))
    bm.verts.ensure_lookup_table()
    bm.faces.new((t00, t10, apex))
    bm.faces.new((t10, t11, apex))
    bm.faces.new((t11, t01, apex))
    bm.faces.new((t01, t00, apex))
    return _bm_face_count(bm) - n_before


def _add_roof_flat(
    bm: bmesh.types.BMesh,
    top_ring: list,
) -> int:
    """No real roof — just a closed cap at wall_height. Optionally a
    1-vertex bump in the centre to give a slight shadow under flat
    shading. Keeping it dead flat for v0a."""
    n_before = _bm_face_count(bm)
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


def _add_windows(
    bm: bmesh.types.BMesh,
    width: float,
    depth: float,
    wall_height: float,
    n_windows: int,
    rng: random.Random,
    win_w: float = 0.7,
    win_h: float = 0.7,
    inset: float = 0.02,
) -> int:
    """Decorative window panels on the two side (east/west) walls. Equally
    spaced along the wall length. Same inset trick as the door."""
    hw, hd = width / 2, depth / 2
    n_before = _bm_face_count(bm)
    z = wall_height * 0.55  # window center height
    # Distribute n_windows along Y on each of west(−X) and east(+X)
    if n_windows <= 0:
        return 0
    per_side = max(1, n_windows // 2)
    margin = 0.6
    span = max(depth - 2 * margin, 0.1)
    for side, x_face in (("west", -hw), ("east", +hw)):
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
        wall_color: str | None = "rock_pale",
        roof_color: str | None = "rock_shadow",
        accent_color: str | None = "accent_red",
        coarse: bool = False,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if building_archetype not in _BUILDING_ARCHETYPES:
            raise ValueError(
                f"unknown building_archetype {building_archetype!r}; "
                f"valid: {_BUILDING_ARCHETYPES}"
            )
        # Pull archetype defaults; explicit kwargs override.
        d = _ARCHETYPE_DEFAULTS[building_archetype]
        self.building_archetype = building_archetype
        roof_archetype = roof_archetype or d["roof_archetype"]
        if roof_archetype not in _ROOF_ARCHETYPES:
            raise ValueError(
                f"unknown roof_archetype {roof_archetype!r}; "
                f"valid: {_ROOF_ARCHETYPES}"
            )
        self.roof_archetype = roof_archetype
        self.width = float(width if width is not None else d["width"])
        self.depth = float(depth if depth is not None else d["depth"])
        self.wall_height = float(wall_height if wall_height is not None else d["wall_height"])
        self.roof_height = float(roof_height if roof_height is not None else d["roof_height"])
        self.n_windows = int(n_windows if n_windows is not None else d["n_windows"])
        self.wall_color = wall_color
        self.roof_color = roof_color
        self.accent_color = accent_color

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

        # 1. Walls
        face_count_walls_start = _bm_face_count(bm)
        top_ring, _ = _add_walls(bm, self.width, self.depth, self.wall_height)
        face_count_walls_end = _bm_face_count(bm)

        # 2. Roof
        face_count_roof_start = face_count_walls_end
        if self.roof_archetype == "gabled":
            _add_roof_gabled(bm, top_ring, self.width, self.depth, self.roof_height)
        elif self.roof_archetype == "hipped":
            _add_roof_hipped(bm, top_ring, self.roof_height)
        else:  # flat
            _add_roof_flat(bm, top_ring)
        face_count_roof_end = _bm_face_count(bm)

        # 3. Door + windows (the "openings" slot)
        face_count_open_start = face_count_roof_end
        _add_door(bm, self.width, self.depth, self.wall_height)
        _add_windows(bm, self.width, self.depth, self.wall_height,
                     self.n_windows, rng)
        face_count_open_end = _bm_face_count(bm)

        # Convert to mesh + object
        me = bpy.data.meshes.new(f"LowPolyHouse({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(
            f"LowPolyHouse({self.factory_seed})", me
        )
        bpy.context.scene.collection.objects.link(obj)

        # Pre-allocate 3 material slots so polygon.material_index sticks
        while len(obj.data.materials) < 3:
            obj.data.materials.append(None)

        # Assign material_index per face based on the recorded ranges.
        # All polys default to slot 0 (walls). Override the roof + opening
        # ranges.
        for i in range(face_count_roof_start, face_count_roof_end):
            obj.data.polygons[i].material_index = 1
        for i in range(face_count_open_start, face_count_open_end):
            obj.data.polygons[i].material_index = 2

        # Flat shading on every poly — Maquette-canonical low-poly read.
        for p in obj.data.polygons:
            p.use_smooth = False

        # Apply 3-slot palette
        slot_colors = [
            self.wall_color or "rock_pale",
            self.roof_color or "rock_shadow",
            self.accent_color or "accent_red",
        ]
        apply_palette_slots(obj, slot_colors)
        return obj

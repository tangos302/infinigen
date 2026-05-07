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
        roof_archetype="gabled", n_windows=4, has_chimney=True,
        foundation_height=0.4,
    ),
    "barn": dict(
        # Long + low + steep gabled — silhouette dominated by the roof
        width=7.0, depth=3.5, wall_height=2.2, roof_height=2.6,
        roof_archetype="gabled", n_windows=2, has_chimney=False,
        foundation_height=0.0,  # barns sit directly on dirt
    ),
    "tower": dict(
        # Square footprint, tall walls, peaked hipped — guard tower feel
        width=2.6, depth=2.6, wall_height=5.0, roof_height=2.0,
        roof_archetype="hipped", n_windows=4, has_chimney=False,
        foundation_height=0.8,  # tall foundation reads as fortified base
    ),
    "cabin": dict(
        # Small, snug, basic gabled — Firewatch lookout cabin
        width=3.0, depth=3.0, wall_height=2.2, roof_height=1.4,
        roof_archetype="gabled", n_windows=2, has_chimney=True,
        foundation_height=0.3,
    ),
    "longhouse": dict(
        # 2-story-ish wide rectangle, hipped — manor / lodge feel
        width=6.0, depth=4.0, wall_height=3.5, roof_height=1.8,
        roof_archetype="hipped", n_windows=6, has_chimney=True,
        foundation_height=0.5,
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
        has_chimney: bool | None = None,
        foundation_height: float | None = None,
        wall_color: str | None = "rock_pale",
        roof_color: str | None = "rock_shadow",
        accent_color: str | None = "accent_red",
        foundation_color: str | None = "rock_shadow",
        coarse: bool = False,
    ):
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
        self.wall_color = wall_color
        self.roof_color = roof_color
        self.accent_color = accent_color
        self.foundation_color = foundation_color

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

        # 4. Optional chimney (rises from roof; chimney faces inherit the
        # default material_index=0, so they pick up the wall_color slot).
        if self.has_chimney and self.roof_archetype != "flat":
            _add_chimney(bm, self.width, self.depth,
                         self.wall_height, self.roof_height)

        # Convert to mesh + object
        me = bpy.data.meshes.new(f"LowPolyHouse({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(
            f"LowPolyHouse({self.factory_seed})", me
        )
        bpy.context.scene.collection.objects.link(obj)

        # Pre-allocate 4 material slots so polygon.material_index sticks
        # (slot 3 = foundation, even when foundation_height=0 we keep
        # the slot count consistent for predictable indexing).
        while len(obj.data.materials) < 4:
            obj.data.materials.append(None)

        # Assign material_index per face based on the recorded ranges.
        # Default = slot 0 (walls). Override:
        #   - foundation strip   → slot 3
        #   - roof faces         → slot 1
        #   - door + windows     → slot 2
        if face_count_foundation_end > face_count_foundation_start:
            for i in range(face_count_foundation_start, face_count_foundation_end):
                obj.data.polygons[i].material_index = 3
        for i in range(face_count_roof_start, face_count_roof_end):
            obj.data.polygons[i].material_index = 1
        for i in range(face_count_open_start, face_count_open_end):
            obj.data.polygons[i].material_index = 2

        # Flat shading on every poly — Maquette-canonical low-poly read.
        for p in obj.data.polygons:
            p.use_smooth = False

        # Apply 4-slot palette
        slot_colors = [
            self.wall_color or "rock_pale",
            self.roof_color or "rock_shadow",
            self.accent_color or "accent_red",
            self.foundation_color or "rock_shadow",
        ]
        apply_palette_slots(obj, slot_colors)
        return obj

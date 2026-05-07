"""LowPolyLanternPostFactory — exterior lantern post / brazier.

Most-needed Tier-1 factory per empirical attempt log: missing in 5/6
prompt attempts (medieval village, abandoned campsite, Wild West town,
fishing village, monastery). Adds verticality + narrative "this is a
lit place" without needing actual emission.

Archetypes:
  iron_post        — thin cylindrical post + boxy cage lamp on top
  wooden_post      — thicker square post + lantern with sloped roof
  stone_brazier    — squat stone pedestal + wide fire bowl
  hanging_lantern  — no post; just a lamp box for mounting on building

Material slots:
  slot 0 = post / pedestal       (default rust_metal / wood / rock_pale)
  slot 1 = lamp / glass / flame  (default foliage_lemon — warm yellow)

The "glow" is just a colored material in v0; emission is out of scope
(matches Maquette's no-lighting v0 mandate). Future enhancement: opt
into an actual emission node + linkage with the scene's light setup.
"""

from __future__ import annotations

import math
import random

import bmesh
import bpy
from mathutils import Vector

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_LANTERN_ARCHETYPES = ("iron_post", "wooden_post", "stone_brazier", "hanging_lantern")


# Per-archetype default proportions + colors. Caller can override any
# individual knob; archetype is just sensible defaults.
_ARCHETYPE_DEFAULTS = {
    "iron_post": dict(
        post_height=2.6, post_radius=0.05, post_n_sides=6,
        post_archetype="cylinder",
        lamp_size=0.32, lamp_archetype="cage",
        post_color="rust_metal", lamp_color="foliage_lemon",
    ),
    "wooden_post": dict(
        post_height=2.4, post_radius=0.08, post_n_sides=4,
        post_archetype="square",
        lamp_size=0.36, lamp_archetype="lantern",
        post_color="wood", lamp_color="foliage_amber",
    ),
    "stone_brazier": dict(
        # Short pedestal + wide bowl
        post_height=1.0, post_radius=0.22, post_n_sides=8,
        post_archetype="cylinder",
        lamp_size=0.55, lamp_archetype="bowl",
        post_color="rock_pale", lamp_color="accent_red",
    ),
    "hanging_lantern": dict(
        # No post — caller should position it where they want it
        post_height=0.0, post_radius=0.0, post_n_sides=0,
        post_archetype="none",
        lamp_size=0.30, lamp_archetype="lantern",
        post_color="rust_metal", lamp_color="foliage_lemon",
    ),
}


def _bm_face_count(bm) -> int:
    return len(bm.faces)


def _add_post_cylinder(
    bm,
    height: float,
    radius: float,
    n_sides: int,
) -> tuple[Vector, int]:
    """A cylindrical post from z=0 to z=height. Returns (top_center,
    faces_added)."""
    if height <= 0 or radius <= 0:
        return Vector((0, 0, 0)), 0
    n_before = _bm_face_count(bm)
    bottom_ring = []
    top_ring = []
    for s in range(n_sides):
        a = 2 * math.pi * s / n_sides
        x, y = radius * math.cos(a), radius * math.sin(a)
        bottom_ring.append(bm.verts.new((x, y, 0)))
        top_ring.append(bm.verts.new((x, y, height)))
    bm.verts.ensure_lookup_table()
    for s in range(n_sides):
        ns = (s + 1) % n_sides
        bm.faces.new((bottom_ring[s], bottom_ring[ns], top_ring[ns], top_ring[s]))
    bm.faces.new(top_ring)
    return Vector((0, 0, height)), _bm_face_count(bm) - n_before


def _add_post_square(
    bm,
    height: float,
    half_size: float,
) -> tuple[Vector, int]:
    """A square cross-section post (4-sided box) from z=0 to z=height."""
    if height <= 0 or half_size <= 0:
        return Vector((0, 0, 0)), 0
    n_before = _bm_face_count(bm)
    h = half_size
    b00 = bm.verts.new((-h, -h, 0)); b10 = bm.verts.new((+h, -h, 0))
    b11 = bm.verts.new((+h, +h, 0)); b01 = bm.verts.new((-h, +h, 0))
    t00 = bm.verts.new((-h, -h, height)); t10 = bm.verts.new((+h, -h, height))
    t11 = bm.verts.new((+h, +h, height)); t01 = bm.verts.new((-h, +h, height))
    bm.verts.ensure_lookup_table()
    bm.faces.new((b00, b10, t10, t00))
    bm.faces.new((b10, b11, t11, t10))
    bm.faces.new((b11, b01, t01, t11))
    bm.faces.new((b01, b00, t00, t01))
    bm.faces.new((t00, t10, t11, t01))
    return Vector((0, 0, height)), _bm_face_count(bm) - n_before


def _add_lamp_cage(bm, top: Vector, size: float) -> int:
    """A boxy cage lamp — 8-vert open box with thin frame implied via
    flat-shaded edges. Single solid box at low poly."""
    n_before = _bm_face_count(bm)
    h = size / 2
    z0 = top.z + 0.05
    z1 = z0 + size
    cx, cy = top.x, top.y
    b00 = bm.verts.new((cx - h, cy - h, z0))
    b10 = bm.verts.new((cx + h, cy - h, z0))
    b11 = bm.verts.new((cx + h, cy + h, z0))
    b01 = bm.verts.new((cx - h, cy + h, z0))
    t00 = bm.verts.new((cx - h, cy - h, z1))
    t10 = bm.verts.new((cx + h, cy - h, z1))
    t11 = bm.verts.new((cx + h, cy + h, z1))
    t01 = bm.verts.new((cx - h, cy + h, z1))
    bm.verts.ensure_lookup_table()
    bm.faces.new((b00, b10, t10, t00))
    bm.faces.new((b10, b11, t11, t10))
    bm.faces.new((b11, b01, t01, t11))
    bm.faces.new((b01, b00, t00, t01))
    bm.faces.new((t00, t10, t11, t01))
    bm.faces.new((b00, b01, b11, b10))
    return _bm_face_count(bm) - n_before


def _add_lamp_lantern(bm, top: Vector, size: float) -> int:
    """A lantern with a sloped pyramid roof — 4 walls + 4 sloped roof
    triangles. Reads as a stylized fence-top lantern."""
    n_before = _bm_face_count(bm)
    h = size / 2
    z0 = top.z + 0.05
    z1 = z0 + size * 0.7
    z2 = z1 + size * 0.4  # roof apex
    cx, cy = top.x, top.y
    b00 = bm.verts.new((cx - h, cy - h, z0))
    b10 = bm.verts.new((cx + h, cy - h, z0))
    b11 = bm.verts.new((cx + h, cy + h, z0))
    b01 = bm.verts.new((cx - h, cy + h, z0))
    m00 = bm.verts.new((cx - h, cy - h, z1))
    m10 = bm.verts.new((cx + h, cy - h, z1))
    m11 = bm.verts.new((cx + h, cy + h, z1))
    m01 = bm.verts.new((cx - h, cy + h, z1))
    apex = bm.verts.new((cx, cy, z2))
    bm.verts.ensure_lookup_table()
    # Walls
    bm.faces.new((b00, b10, m10, m00))
    bm.faces.new((b10, b11, m11, m10))
    bm.faces.new((b11, b01, m01, m11))
    bm.faces.new((b01, b00, m00, m01))
    # Roof (4 triangular slopes)
    bm.faces.new((m00, m10, apex))
    bm.faces.new((m10, m11, apex))
    bm.faces.new((m11, m01, apex))
    bm.faces.new((m01, m00, apex))
    # Floor
    bm.faces.new((b00, b01, b11, b10))
    return _bm_face_count(bm) - n_before


def _add_lamp_bowl(bm, top: Vector, size: float) -> int:
    """A wide shallow bowl on top of a brazier pedestal — half-icosphere
    flipped so opening faces up. Implemented as a low-cylinder + dome."""
    n_before = _bm_face_count(bm)
    radius = size
    # Wide cylinder body
    z0 = top.z + 0.02
    z1 = z0 + radius * 0.4
    bottom_ring, top_ring = [], []
    n_sides = 8
    for s in range(n_sides):
        a = 2 * math.pi * s / n_sides
        x = top.x + radius * math.cos(a)
        y = top.y + radius * math.sin(a)
        bottom_ring.append(bm.verts.new((x, y, z0)))
        top_ring.append(bm.verts.new((x, y, z1)))
    bm.verts.ensure_lookup_table()
    for s in range(n_sides):
        ns = (s + 1) % n_sides
        bm.faces.new((bottom_ring[s], bottom_ring[ns], top_ring[ns], top_ring[s]))
    # Floor (closed bottom)
    bm.faces.new(list(reversed(bottom_ring)))
    # Open top — instead of capping, leave open so it reads as a bowl.
    # Add a small "flame" cone in the center for the bowl archetype
    flame_apex = bm.verts.new((top.x, top.y, z1 + radius * 0.6))
    bm.verts.ensure_lookup_table()
    flame_base_z = z1 + 0.02
    flame_ring = []
    for s in range(n_sides):
        a = 2 * math.pi * s / n_sides
        x = top.x + radius * 0.45 * math.cos(a)
        y = top.y + radius * 0.45 * math.sin(a)
        flame_ring.append(bm.verts.new((x, y, flame_base_z)))
    bm.verts.ensure_lookup_table()
    for s in range(n_sides):
        ns = (s + 1) % n_sides
        bm.faces.new((flame_ring[s], flame_ring[ns], flame_apex))
    return _bm_face_count(bm) - n_before


_LAMP_BUILDERS = {
    "cage":    _add_lamp_cage,
    "lantern": _add_lamp_lantern,
    "bowl":    _add_lamp_bowl,
}


class LowPolyLanternPostFactory(AssetFactory):
    """A vertical post topped with a lamp / lantern / fire bowl. Reads as
    "this is a lit place" without needing emission.

    Constructor knobs:

        factory_seed
        lantern_archetype  : str = "iron_post"
                             "iron_post" | "wooden_post" |
                             "stone_brazier" | "hanging_lantern"
        post_height        : float (archetype default)
        post_radius        : float
        post_n_sides       : int (cylinders only)
        post_archetype     : str = "cylinder" | "square" | "none"
        lamp_size          : float
        lamp_archetype     : str = "cage" | "lantern" | "bowl"
        post_color         : str        slot 0
        lamp_color         : str        slot 1
    """

    def __init__(
        self,
        factory_seed,
        lantern_archetype: str = "iron_post",
        post_height: float | None = None,
        post_radius: float | None = None,
        post_n_sides: int | None = None,
        post_archetype: str | None = None,
        lamp_size: float | None = None,
        lamp_archetype: str | None = None,
        post_color: str | None = None,
        lamp_color: str | None = None,
        coarse: bool = False,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if lantern_archetype not in _LANTERN_ARCHETYPES:
            # Lenient fallback rather than crash. Sonnet has been
            # observed to hallucinate plausible-sounding archetype
            # names despite the factories_guide brief listing the
            # valid set; killing a 6-minute build over a one-line
            # archetype typo wastes a generation. Substitute the
            # canonical default and warn to stderr.
            import sys
            print(
                f"[lantern_archetype] WARN: unknown lantern_archetype "
                f"{lantern_archetype!r}; falling back to {_LANTERN_ARCHETYPES[0]!r}. "
                f"Valid: {_LANTERN_ARCHETYPES}",
                file=sys.stderr,
            )
            lantern_archetype = _LANTERN_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[lantern_archetype]
        self.lantern_archetype = lantern_archetype
        self.post_height = float(post_height if post_height is not None else d["post_height"])
        self.post_radius = float(post_radius if post_radius is not None else d["post_radius"])
        self.post_n_sides = int(post_n_sides if post_n_sides is not None else d["post_n_sides"])
        self.post_archetype = post_archetype or d["post_archetype"]
        self.lamp_size = float(lamp_size if lamp_size is not None else d["lamp_size"])
        self.lamp_archetype = lamp_archetype or d["lamp_archetype"]
        if self.lamp_archetype not in _LAMP_BUILDERS:
            # Lenient fallback rather than crash — see other archetype
            # validators in this package for the rationale.
            import sys
            _fallback = next(iter(_LAMP_BUILDERS))
            print(
                f"[lamp_archetype] WARN: unknown lamp_archetype "
                f"{self.lamp_archetype!r}; falling back to {_fallback!r}. "
                f"Valid: {list(_LAMP_BUILDERS)}",
                file=sys.stderr,
            )
            self.lamp_archetype = _fallback
        self.post_color = post_color or d["post_color"]
        self.lamp_color = lamp_color or d["lamp_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyLanternPost({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        bm = bmesh.new()

        # Post
        face_count_post_start = _bm_face_count(bm)
        if self.post_archetype == "cylinder":
            top, _ = _add_post_cylinder(
                bm, self.post_height, self.post_radius, self.post_n_sides
            )
        elif self.post_archetype == "square":
            top, _ = _add_post_square(
                bm, self.post_height, self.post_radius
            )
        else:  # "none"
            top = Vector((0, 0, 0))
        face_count_post_end = _bm_face_count(bm)

        # Lamp
        face_count_lamp_start = face_count_post_end
        builder = _LAMP_BUILDERS[self.lamp_archetype]
        builder(bm, top, self.lamp_size)
        face_count_lamp_end = _bm_face_count(bm)

        # Convert to mesh + object
        me = bpy.data.meshes.new(f"LowPolyLanternPost({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(
            f"LowPolyLanternPost({self.factory_seed})", me
        )
        bpy.context.scene.collection.objects.link(obj)

        # Pre-allocate 2 material slots so polygon.material_index sticks
        while len(obj.data.materials) < 2:
            obj.data.materials.append(None)

        # Lamp faces → slot 1 (post stays at default 0)
        for i in range(face_count_lamp_start, face_count_lamp_end):
            obj.data.polygons[i].material_index = 1

        # Flat shading throughout
        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(obj, [self.post_color, self.lamp_color])
        return obj

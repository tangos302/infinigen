"""LowPolyWindmillFactory — windmill / windpump silhouette.

Surfaced in farmstead (Attempt 9) and Wild West (Attempt 3) — also a
strong silhouette element for fishing villages with grain mills.
The blade ring is what makes the silhouette read; without spinning
animation a fixed pose works fine for the static-scene aesthetic.

Archetypes:
  dutch          — tapered cylindrical tower + onion-cap dome +
                   4 long blades (Dutch / European mill)
  western_pump   — thin 4-post lattice truss + 6-blade fan
                   (Wild West windpump / homestead water tower)
  stone_mill     — short stone tower + simple sloped cap + 4 blades
                   (medieval / fantasy mill)

The 4 long-blade variants are positioned with a slight tilt around
the hub (just enough to read as 3D rather than flat) and one blade
points straight up by default — feel free to override `blade_phase`
to set a different "frozen" rotation.

Material slots:
  slot 0 = tower / structure       (default `rock_pale`, `wood`, or `rock_warm`)
  slot 1 = blades + hub            (default `wood`)
  slot 2 = roof / dome             (default `rock_shadow`)
"""

from __future__ import annotations

import math

import bmesh
import bpy
from mathutils import Matrix, Vector

from infinigen.core.placement.factory import AssetFactory

from ...density import n_sides_for_radius, target_edge_for_bbox
from ...materials import apply_palette_slots


_WINDMILL_ARCHETYPES = ("dutch", "western_pump", "stone_mill")


# n_tower_sides for round-tower archetypes is bbox-derived. western_pump
# uses a 4-post lattice tower, where n_tower_sides is unused.
_ARCHETYPE_DEFAULTS = {
    "dutch": dict(
        tower_height=5.5, tower_top_radius=0.7, tower_bottom_radius=1.2,
        n_blades=4, blade_length=2.8, blade_width=0.45,
        blade_thickness=0.08, blade_phase=0.0, hub_radius=0.18,
        has_dome=True, dome_height=0.8,
        tower_color="rock_pale", blade_color="wood", roof_color="rock_shadow",
    ),
    "western_pump": dict(
        tower_height=4.5, tower_top_radius=0.35, tower_bottom_radius=0.9,
        n_blades=6, blade_length=0.9, blade_width=0.18,
        blade_thickness=0.04, blade_phase=0.0, hub_radius=0.1,
        has_dome=False, dome_height=0.0,
        tower_color="rust_metal", blade_color="rust_metal",
        roof_color="rock_shadow",
    ),
    "stone_mill": dict(
        tower_height=3.5, tower_top_radius=1.0, tower_bottom_radius=1.4,
        n_blades=4, blade_length=2.2, blade_width=0.4,
        blade_thickness=0.08, blade_phase=0.0, hub_radius=0.18,
        has_dome=False, dome_height=0.6,
        tower_color="rock_warm", blade_color="wood",
        roof_color="rock_shadow",
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


def _add_tapered_tower(
    bm, slot_ranges, slot,
    height: float, top_r: float, bot_r: float, n_sides: int,
) -> Vector:
    """Tapered cylindrical tower from z=0 to z=height. Returns top center."""
    start = _bm_face_count(bm)
    bot, top = [], []
    for s in range(n_sides):
        a = 2 * math.pi * s / n_sides
        bot.append(bm.verts.new((bot_r * math.cos(a), bot_r * math.sin(a), 0)))
        top.append(bm.verts.new((top_r * math.cos(a), top_r * math.sin(a), height)))
    bm.verts.ensure_lookup_table()
    for s in range(n_sides):
        ns = (s + 1) % n_sides
        bm.faces.new((bot[s], bot[ns], top[ns], top[s]))
    bm.faces.new(top)
    bm.faces.new(list(reversed(bot)))
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))
    return Vector((0, 0, height))


def _add_lattice_tower(
    bm, slot_ranges, slot,
    height: float, top_size: float, bot_size: float, post_thickness: float,
) -> Vector:
    """Western windpump lattice — 4 angled posts forming a truncated
    pyramid, plus 2 horizontal cross-braces. Reads as "thin truss"
    silhouette."""
    # 4 corner posts: each post is a thin tilted box from corner to corner
    # We'll use simple boxes positioned along the 4 edges.
    bot_h = bot_size / 2
    top_h = top_size / 2
    corners_bot = [
        (-bot_h, -bot_h), (+bot_h, -bot_h),
        (+bot_h, +bot_h), (-bot_h, +bot_h),
    ]
    corners_top = [
        (-top_h, -top_h), (+top_h, -top_h),
        (+top_h, +top_h), (-top_h, +top_h),
    ]
    # Each post is a long box with center at (avg(b,t), avg_z), oriented
    # by Euler. Easier: just place a tall thin box at each midpoint with
    # a slight tilt — but bmesh transformation per-face is annoying. We
    # cheat by using straight vertical posts at the bottom positions —
    # the silhouette still reads as a lattice tower at low poly.
    start = _bm_face_count(bm)
    for (cx, cy) in corners_bot:
        # Slightly bring each post toward center as it goes up — emulate
        # truss taper by positioning the post at the AVERAGE of its bot/top
        # corner, slightly inside the bottom corner.
        avg_x = (cx + cx * (top_size / bot_size)) / 2
        avg_y = (cy + cy * (top_size / bot_size)) / 2
        _add_box(bm, avg_x, avg_y, height / 2,
                 post_thickness, post_thickness, height)
    # Horizontal cross-braces at 1/3 and 2/3 height — 4 boxes per ring
    # forming the perimeter at that elevation
    for t in (0.33, 0.66):
        z = height * t
        # Interpolated half-size at that height
        h = bot_h + (top_h - bot_h) * t
        side = 2 * h
        _add_box(bm, 0, -h, z, side, post_thickness, post_thickness)
        _add_box(bm, 0, +h, z, side, post_thickness, post_thickness)
        _add_box(bm, -h, 0, z, post_thickness, side, post_thickness)
        _add_box(bm, +h, 0, z, post_thickness, side, post_thickness)
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))
    return Vector((0, 0, height))


def _add_dome(
    bm, slot_ranges, slot,
    base_z: float, height: float, radius: float, n_sides: int,
) -> None:
    """Onion-cap dome — simple half-ellipsoid built from 2 narrowing rings + apex."""
    start = _bm_face_count(bm)
    rings = []
    base_ring = []
    for s in range(n_sides):
        a = 2 * math.pi * s / n_sides
        base_ring.append(
            bm.verts.new((radius * math.cos(a), radius * math.sin(a), base_z))
        )
    rings.append(base_ring)
    n_rings = 2
    for r in range(1, n_rings):
        t = r / n_rings
        z = base_z + height * t
        scale = math.cos(t * math.pi / 2)
        ring = []
        for s in range(n_sides):
            a = 2 * math.pi * s / n_sides
            ring.append(
                bm.verts.new((radius * scale * math.cos(a),
                              radius * scale * math.sin(a), z))
            )
        rings.append(ring)
    apex = bm.verts.new((0, 0, base_z + height))
    bm.verts.ensure_lookup_table()
    for r in range(len(rings) - 1):
        a_ring, b_ring = rings[r], rings[r + 1]
        for s in range(n_sides):
            ns = (s + 1) % n_sides
            bm.faces.new((a_ring[s], a_ring[ns], b_ring[ns], b_ring[s]))
    top_ring = rings[-1]
    for s in range(n_sides):
        ns = (s + 1) % n_sides
        bm.faces.new((top_ring[s], top_ring[ns], apex))
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))


def _add_blades(
    bm, slot_ranges, slot,
    hub_pos: Vector,
    n_blades: int,
    blade_length: float,
    blade_width: float,
    blade_thickness: float,
    hub_radius: float,
    blade_phase: float,
) -> None:
    """N blades arranged radially around the hub (which sits on +Y of the
    tower top). Blade plane = XZ; hub axis = +Y so it points away from
    the tower for a head-on read."""
    start = _bm_face_count(bm)
    # Hub itself — a small disc / box at hub_pos, axis along +Y
    hub_thickness = hub_radius * 1.2
    _add_box(bm, hub_pos.x, hub_pos.y - hub_thickness / 2, hub_pos.z,
             hub_radius * 2, hub_thickness, hub_radius * 2)
    # Each blade: thin box centered (length/2) outward from hub, rotated.
    # The blade plane is the X-Z plane; rotation is around Y axis.
    for i in range(n_blades):
        a = blade_phase + 2 * math.pi * i / n_blades
        # Local blade points along +X, length away. After rotating by `a`
        # around Y axis: blade extends from hub along (cos(a), 0, sin(a)).
        dx = math.cos(a)
        dz = math.sin(a)
        # Center of the blade box
        bx = hub_pos.x + dx * blade_length / 2
        bz = hub_pos.z + dz * blade_length / 2
        by = hub_pos.y + hub_thickness  # in front of hub on +Y
        # Build the box rotated. Easiest: 4 + 4 corner verts via rotation
        # matrix around Y at hub origin.
        rot = Matrix.Rotation(a, 4, 'Y')
        # Local corners (length along X, width along Z, thickness along Y)
        L, W, T = blade_length, blade_width, blade_thickness
        local_corners = [
            (-L/2, -T/2, -W/2), (+L/2, -T/2, -W/2),
            (+L/2, +T/2, -W/2), (-L/2, +T/2, -W/2),
            (-L/2, -T/2, +W/2), (+L/2, -T/2, +W/2),
            (+L/2, +T/2, +W/2), (-L/2, +T/2, +W/2),
        ]
        # Anchor: blade extends from x=0 (hub) outward, so shift +X by L/2
        # and place the hub at hub_pos
        verts_world = []
        for lc in local_corners:
            v_local = Vector((lc[0] + L/2, lc[1], lc[2]))
            v_rot = rot @ v_local
            v_world = (hub_pos.x + v_rot.x,
                       hub_pos.y + hub_thickness + v_rot.y,
                       hub_pos.z + v_rot.z)
            verts_world.append(bm.verts.new(v_world))
        bm.verts.ensure_lookup_table()
        b00, b10, b11, b01, t00, t10, t11, t01 = verts_world
        bm.faces.new((b00, b10, t10, t00))
        bm.faces.new((b10, b11, t11, t10))
        bm.faces.new((b11, b01, t01, t11))
        bm.faces.new((b01, b00, t00, t01))
        bm.faces.new((t00, t10, t11, t01))
        bm.faces.new((b00, b01, b11, b10))
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))


class LowPolyWindmillFactory(AssetFactory):
    """A windmill / windpump — tapered tower or lattice truss + blade ring.

    Constructor knobs:

        factory_seed
        windmill_archetype : str = "dutch"
                             "dutch" | "western_pump" | "stone_mill"
        tower_height          : float
        tower_top_radius      : float
        tower_bottom_radius   : float
        n_tower_sides         : int
        n_blades              : int
        blade_length          : float
        blade_width           : float
        blade_thickness       : float
        blade_phase           : float    radians; rotates the blade ring
        hub_radius            : float
        has_dome              : bool
        dome_height           : float
        tower_color           : str    slot 0
        blade_color           : str    slot 1
        roof_color            : str    slot 2
    """

    def __init__(
        self,
        factory_seed,
        windmill_archetype: str = "dutch",
        tower_height: float | None = None,
        tower_top_radius: float | None = None,
        tower_bottom_radius: float | None = None,
        polygon_multiplier: float = 1.0,
        target_edge: float | None = None,
        n_tower_sides: int | None = None,
        n_blades: int | None = None,
        blade_length: float | None = None,
        blade_width: float | None = None,
        blade_thickness: float | None = None,
        blade_phase: float | None = None,
        hub_radius: float | None = None,
        has_dome: bool | None = None,
        dome_height: float | None = None,
        tower_color: str | None = None,
        blade_color: str | None = None,
        roof_color: str | None = None,
        coarse: bool = False,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if windmill_archetype not in _WINDMILL_ARCHETYPES:
            # Lenient fallback rather than crash. Sonnet has been
            # observed to hallucinate plausible-sounding archetype
            # names despite the factories_guide brief listing the
            # valid set; killing a 6-minute build over a one-line
            # archetype typo wastes a generation. Substitute the
            # canonical default and warn to stderr.
            import sys
            print(
                f"[windmill_archetype] WARN: unknown windmill_archetype "
                f"{windmill_archetype!r}; falling back to {_WINDMILL_ARCHETYPES[0]!r}. "
                f"Valid: {_WINDMILL_ARCHETYPES}",
                file=sys.stderr,
            )
            windmill_archetype = _WINDMILL_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[windmill_archetype]
        self.windmill_archetype = windmill_archetype
        self.tower_height = float(
            tower_height if tower_height is not None else d["tower_height"]
        )
        self.tower_top_radius = float(
            tower_top_radius if tower_top_radius is not None else d["tower_top_radius"]
        )
        self.tower_bottom_radius = float(
            tower_bottom_radius if tower_bottom_radius is not None else d["tower_bottom_radius"]
        )
        # Tower n_sides bbox-derived from the larger (bottom) radius.
        # western_pump uses a lattice tower so the value is unused there.
        edge = (
            float(target_edge) if target_edge is not None
            else target_edge_for_bbox(
                (self.tower_bottom_radius * 2, self.tower_bottom_radius * 2,
                 self.tower_height),
                polygon_multiplier=polygon_multiplier,
            )
        )
        if n_tower_sides is not None:
            self.n_tower_sides = int(n_tower_sides)
        elif "n_tower_sides" in d:
            self.n_tower_sides = int(d["n_tower_sides"])
        else:
            self.n_tower_sides = n_sides_for_radius(
                self.tower_bottom_radius, edge, min_n=6,
            )
        self.n_blades = int(n_blades if n_blades is not None else d["n_blades"])
        self.blade_length = float(
            blade_length if blade_length is not None else d["blade_length"]
        )
        self.blade_width = float(
            blade_width if blade_width is not None else d["blade_width"]
        )
        self.blade_thickness = float(
            blade_thickness if blade_thickness is not None else d["blade_thickness"]
        )
        self.blade_phase = float(
            blade_phase if blade_phase is not None else d["blade_phase"]
        )
        self.hub_radius = float(
            hub_radius if hub_radius is not None else d["hub_radius"]
        )
        self.has_dome = (
            bool(has_dome) if has_dome is not None else d["has_dome"]
        )
        self.dome_height = float(
            dome_height if dome_height is not None else d["dome_height"]
        )
        self.tower_color = tower_color or d["tower_color"]
        self.blade_color = blade_color or d["blade_color"]
        self.roof_color = roof_color or d["roof_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyWindmill({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        bm = bmesh.new()
        slot_ranges: list[tuple[int, int, int]] = []

        # Tower
        if self.windmill_archetype == "western_pump":
            top = _add_lattice_tower(
                bm, slot_ranges, 0,
                self.tower_height,
                self.tower_top_radius * 2,    # treat as full top side length
                self.tower_bottom_radius * 2, # full bottom side length
                post_thickness=0.06,
            )
        else:
            top = _add_tapered_tower(
                bm, slot_ranges, 0,
                self.tower_height,
                self.tower_top_radius,
                self.tower_bottom_radius,
                self.n_tower_sides,
            )

        # Dome / roof
        hub_z = self.tower_height
        if self.has_dome and self.dome_height > 0:
            _add_dome(
                bm, slot_ranges, 2,
                self.tower_height,
                self.dome_height,
                self.tower_top_radius,
                self.n_tower_sides,
            )
            hub_z = self.tower_height + self.dome_height * 0.4

        # Blades + hub at top
        hub_pos = Vector((0, 0, hub_z))
        _add_blades(
            bm, slot_ranges, 1,
            hub_pos,
            self.n_blades,
            self.blade_length,
            self.blade_width,
            self.blade_thickness,
            self.hub_radius,
            self.blade_phase,
        )

        me = bpy.data.meshes.new(f"LowPolyWindmill({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(f"LowPolyWindmill({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)

        while len(obj.data.materials) < 3:
            obj.data.materials.append(None)

        for start, end, slot in slot_ranges:
            for i in range(start, end):
                obj.data.polygons[i].material_index = slot

        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(
            obj, [self.tower_color, self.blade_color, self.roof_color]
        )
        return obj

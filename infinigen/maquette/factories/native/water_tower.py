"""LowPolyWaterTowerFactory — frontier water tower on stilts.

Requested 2026-04-28 (Wild West / fishing village). Tall wooden tank
on four cross-braced legs, conical roof — the signature silhouette of
a frontier town.

Archetypes:
  frontier_stilts — 4 legs, vertical tank, conical roof (wild west)
  rail_depot      — taller, square tank, flat roof (industrial /
                     railway)

Material slots:
  slot 0 = legs / cross braces (default `wood`)
  slot 1 = tank shell          (default `wood` warm)
  slot 2 = roof / metal bands  (default `rust_metal`)
"""

from __future__ import annotations

import math

import bmesh
import bpy

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_TOWER_ARCHETYPES = ("frontier_stilts", "rail_depot")


_ARCHETYPE_DEFAULTS = {
    "frontier_stilts": dict(
        leg_height=3.6, leg_size=0.18, leg_spread=1.6,
        tank_radius=1.30, tank_height=2.20, tank_n_sides=10,
        roof_height=0.85,
        n_braces=2, brace_size=0.10,
        leg_color="wood", tank_color="wood", roof_color="rust_metal",
        tank_shape="round",
    ),
    "rail_depot": dict(
        leg_height=4.4, leg_size=0.22, leg_spread=1.9,
        tank_radius=1.55, tank_height=2.60, tank_n_sides=4,
        roof_height=0.30,
        n_braces=3, brace_size=0.12,
        leg_color="rust_metal", tank_color="wood", roof_color="rust_metal",
        tank_shape="square",
    ),
}


def _bm_face_count(bm) -> int:
    return len(bm.faces)


def _add_box(bm, slot_ranges, slot, cx, cy, cz, sx, sy, sz):
    start = _bm_face_count(bm)
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
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))


def _add_diagonal_brace(bm, slot_ranges, slot,
                        x0, y0, x1, y1, z, length_z, thickness):
    """Approximate a slanted square brace as an axis-aligned box.
    Cheap but adequate for the low-poly read."""
    cx = (x0 + x1) / 2
    cy = (y0 + y1) / 2
    sx = max(abs(x1 - x0), thickness)
    sy = max(abs(y1 - y0), thickness)
    _add_box(bm, slot_ranges, slot, cx, cy, z, sx, sy, length_z)


def _add_round_tank(bm, slot_ranges, slot, cz, radius, height, n_sides):
    """Cylindrical tank centered at z=cz."""
    start = _bm_face_count(bm)
    z0 = cz - height / 2
    z1 = cz + height / 2
    bot, top = [], []
    for s in range(n_sides):
        a = 2 * math.pi * s / n_sides
        bot.append(bm.verts.new(
            (radius * math.cos(a), radius * math.sin(a), z0)
        ))
        top.append(bm.verts.new(
            (radius * math.cos(a), radius * math.sin(a), z1)
        ))
    bm.verts.ensure_lookup_table()
    for s in range(n_sides):
        ns = (s + 1) % n_sides
        bm.faces.new((bot[s], bot[ns], top[ns], top[s]))
    bm.faces.new(top)
    bm.faces.new(list(reversed(bot)))
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))


def _add_conical_roof(bm, slot_ranges, slot, cz, radius, height, n_sides):
    """Cone above the tank. cz is the base of the cone."""
    start = _bm_face_count(bm)
    eave_overhang = 0.18
    base_r = radius + eave_overhang
    apex = bm.verts.new((0.0, 0.0, cz + height))
    base = []
    for s in range(n_sides):
        a = 2 * math.pi * s / n_sides
        base.append(bm.verts.new(
            (base_r * math.cos(a), base_r * math.sin(a), cz)
        ))
    bm.verts.ensure_lookup_table()
    for s in range(n_sides):
        ns = (s + 1) % n_sides
        bm.faces.new((base[s], base[ns], apex))
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))


def _add_pyramid_roof(bm, slot_ranges, slot, cz, half, height):
    """Square pyramid roof for square tanks."""
    start = _bm_face_count(bm)
    a = bm.verts.new((-half, -half, cz))
    b = bm.verts.new(( half, -half, cz))
    c = bm.verts.new(( half,  half, cz))
    d = bm.verts.new((-half,  half, cz))
    apex = bm.verts.new((0.0, 0.0, cz + height))
    bm.verts.ensure_lookup_table()
    bm.faces.new((a, b, apex))
    bm.faces.new((b, c, apex))
    bm.faces.new((c, d, apex))
    bm.faces.new((d, a, apex))
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))


class LowPolyWaterTowerFactory(AssetFactory):
    """Frontier water tower — 4 legs + tank + roof.

    Constructor knobs:

        factory_seed
        tower_archetype : str = "frontier_stilts" | "rail_depot"
        leg_height, leg_size, leg_spread : float
        tank_radius, tank_height, tank_n_sides : float / int
        roof_height : float
        n_braces, brace_size : int / float
        leg_color, tank_color, roof_color : palette keys
    """

    def __init__(
        self,
        factory_seed,
        tower_archetype: str = "frontier_stilts",
        leg_height: float | None = None,
        leg_size: float | None = None,
        leg_spread: float | None = None,
        tank_radius: float | None = None,
        tank_height: float | None = None,
        tank_n_sides: int | None = None,
        roof_height: float | None = None,
        n_braces: int | None = None,
        brace_size: float | None = None,
        leg_color: str | None = None,
        tank_color: str | None = None,
        roof_color: str | None = None,
        coarse: bool = False,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if tower_archetype not in _TOWER_ARCHETYPES:
            raise ValueError(
                f"unknown tower_archetype {tower_archetype!r}; "
                f"valid: {_TOWER_ARCHETYPES}"
            )
        d = _ARCHETYPE_DEFAULTS[tower_archetype]
        self.tower_archetype = tower_archetype
        self.leg_height = float(leg_height if leg_height is not None else d["leg_height"])
        self.leg_size = float(leg_size if leg_size is not None else d["leg_size"])
        self.leg_spread = float(leg_spread if leg_spread is not None else d["leg_spread"])
        self.tank_radius = float(tank_radius if tank_radius is not None else d["tank_radius"])
        self.tank_height = float(tank_height if tank_height is not None else d["tank_height"])
        self.tank_n_sides = int(tank_n_sides if tank_n_sides is not None else d["tank_n_sides"])
        self.roof_height = float(roof_height if roof_height is not None else d["roof_height"])
        self.n_braces = int(n_braces if n_braces is not None else d["n_braces"])
        self.brace_size = float(brace_size if brace_size is not None else d["brace_size"])
        self.tank_shape = d["tank_shape"]
        self.leg_color = leg_color or d["leg_color"]
        self.tank_color = tank_color or d["tank_color"]
        self.roof_color = roof_color or d["roof_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyWaterTower({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        bm = bmesh.new()
        slot_ranges: list[tuple[int, int, int]] = []

        half = self.leg_spread / 2
        # Four legs at the corners of a square footprint
        for sx in (-1, 1):
            for sy in (-1, 1):
                _add_box(
                    bm, slot_ranges, 0,
                    sx * half, sy * half, self.leg_height / 2,
                    self.leg_size, self.leg_size, self.leg_height,
                )

        # Horizontal cross braces at evenly spaced heights
        for i in range(1, self.n_braces + 1):
            z = self.leg_height * i / (self.n_braces + 1)
            # X-direction braces (between front and back legs on each side)
            for sy in (-1, 1):
                _add_box(
                    bm, slot_ranges, 0,
                    0.0, sy * half, z,
                    self.leg_spread, self.brace_size, self.brace_size,
                )
            # Y-direction braces (between left and right legs)
            for sx in (-1, 1):
                _add_box(
                    bm, slot_ranges, 0,
                    sx * half, 0.0, z,
                    self.brace_size, self.leg_spread, self.brace_size,
                )

        # Tank platform (a flat slab on top of the legs, slot 0 = wood)
        platform_t = self.brace_size * 1.4
        platform_size = self.leg_spread + self.leg_size * 1.5
        _add_box(
            bm, slot_ranges, 0,
            0.0, 0.0, self.leg_height + platform_t / 2,
            platform_size, platform_size, platform_t,
        )

        # Tank
        tank_base = self.leg_height + platform_t
        tank_centre_z = tank_base + self.tank_height / 2
        if self.tank_shape == "round":
            _add_round_tank(
                bm, slot_ranges, 1,
                tank_centre_z, self.tank_radius, self.tank_height,
                self.tank_n_sides,
            )
        else:  # square
            _add_box(
                bm, slot_ranges, 1,
                0.0, 0.0, tank_centre_z,
                self.tank_radius * 2, self.tank_radius * 2, self.tank_height,
            )

        # Metal hoops on a round tank (slot 2)
        if self.tank_shape == "round":
            for hoop_t in (0.20, 0.55, 0.85):
                _add_round_tank(
                    bm, slot_ranges, 2,
                    tank_base + self.tank_height * hoop_t,
                    self.tank_radius * 1.04,
                    0.10,
                    self.tank_n_sides,
                )

        # Roof
        roof_base_z = tank_base + self.tank_height
        if self.tank_shape == "round":
            _add_conical_roof(
                bm, slot_ranges, 2,
                roof_base_z, self.tank_radius, self.roof_height,
                self.tank_n_sides,
            )
        else:
            _add_pyramid_roof(
                bm, slot_ranges, 2,
                roof_base_z, self.tank_radius * 1.05, self.roof_height,
            )

        me = bpy.data.meshes.new(f"LowPolyWaterTower({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()
        obj = bpy.data.objects.new(
            f"LowPolyWaterTower({self.factory_seed})", me,
        )
        bpy.context.scene.collection.objects.link(obj)
        while len(obj.data.materials) < 3:
            obj.data.materials.append(None)
        for start, end, slot in slot_ranges:
            for i in range(start, end):
                obj.data.polygons[i].material_index = slot
        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(obj, [self.leg_color, self.tank_color, self.roof_color])
        return obj

"""LowPolyFurnitureFactory — wooden furniture for markets, taverns, gardens.

Seating and tables to dress settlement interiors and squares — the
catalog had stalls and counters-as-buildings but no standalone
furniture. Plain plank-and-leg carpentry, lightly two-toned (lighter
tops, darker frames).

Archetypes:
  bench          — a long seat with a back, four uprights
  trestle_table  — a plank top on two trestle ends with a stretcher
  stool          — a small round seat on three legs
  market_counter — a wide counter with a solid front and end panels

Material slots:
  slot 0 = wood (tops, seats, counter front)
  slot 1 = frame (legs, uprights, trestle ends, rails)
"""

from __future__ import annotations

import math
import random

import bmesh
import bpy

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_FURNITURE_ARCHETYPES = ("bench", "trestle_table", "stool", "market_counter")


def _face_count(bm: bmesh.types.BMesh) -> int:
    return len(bm.faces)


def _add_box(
    bm: bmesh.types.BMesh,
    *,
    cx: float,
    cy: float,
    z0: float,
    sx: float,
    sy: float,
    sz: float,
    slot: int,
    slot_ranges: list[tuple[int, int, int]],
) -> None:
    """A plain axis-aligned box from z0 to z0+sz."""
    start = _face_count(bm)
    hx, hy = sx * 0.5, sy * 0.5
    corners = ((-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy))
    bot = [bm.verts.new((cx + lx, cy + ly, z0)) for lx, ly in corners]
    top = [bm.verts.new((cx + lx, cy + ly, z0 + sz)) for lx, ly in corners]
    bm.verts.ensure_lookup_table()
    for i in range(4):
        ni = (i + 1) % 4
        bm.faces.new((bot[i], bot[ni], top[ni], top[i]))
    bm.faces.new(tuple(reversed(bot)))
    bm.faces.new(tuple(top))
    slot_ranges.append((start, _face_count(bm), int(slot)))


def _add_cylinder(
    bm: bmesh.types.BMesh,
    *,
    cx: float,
    cy: float,
    z0: float,
    radius: float,
    height: float,
    n_sides: int,
    slot: int,
    slot_ranges: list[tuple[int, int, int]],
) -> None:
    """A round prism — the stool seat."""
    start = _face_count(bm)
    bot = []
    top = []
    for i in range(n_sides):
        a = 2.0 * math.pi * i / n_sides
        bot.append(bm.verts.new((cx + radius * math.cos(a), cy + radius * math.sin(a), z0)))
        top.append(
            bm.verts.new((cx + radius * math.cos(a), cy + radius * math.sin(a), z0 + height))
        )
    bm.verts.ensure_lookup_table()
    for i in range(n_sides):
        ni = (i + 1) % n_sides
        bm.faces.new((bot[i], bot[ni], top[ni], top[i]))
    bm.faces.new(tuple(reversed(bot)))
    bm.faces.new(tuple(top))
    slot_ranges.append((start, _face_count(bm), int(slot)))


class LowPolyFurnitureFactory(AssetFactory):
    """Wooden furniture — benches, tables, stools, market counters.

    Constructor knobs:
        factory_seed
        furniture_archetype : "bench" | "trestle_table" | "stool"
                              | "market_counter"
        wood_color, frame_color
    """

    def __init__(
        self,
        factory_seed,
        furniture_archetype: str = "bench",
        wood_color: str | None = None,
        frame_color: str | None = None,
        coarse: bool = False,
        **_unused_kwargs,
    ) -> None:
        super().__init__(factory_seed, coarse=coarse)
        if _unused_kwargs:
            from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
            accept_unused_kwargs("LowPolyFurnitureFactory", _unused_kwargs)
        if furniture_archetype not in _FURNITURE_ARCHETYPES:
            import sys
            print(
                f"[furniture_archetype] WARN: unknown {furniture_archetype!r}; "
                f"falling back to {_FURNITURE_ARCHETYPES[0]!r}. "
                f"Valid: {_FURNITURE_ARCHETYPES}",
                file=sys.stderr,
            )
            furniture_archetype = _FURNITURE_ARCHETYPES[0]
        self.furniture_archetype = furniture_archetype
        self.wood_color = wood_color or "wood"
        self.frame_color = frame_color or "rock_shadow"

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(f"LowPolyFurniture({self.factory_seed})_placeholder", None)
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        rng = random.Random(int(self.factory_seed) + 19463)
        builders = {
            "bench": self._build_bench,
            "trestle_table": self._build_trestle_table,
            "stool": self._build_stool,
            "market_counter": self._build_market_counter,
        }
        return builders[self.furniture_archetype](rng)

    def _finalize(
        self, bm: bmesh.types.BMesh, slot_ranges: list[tuple[int, int, int]]
    ) -> bpy.types.Object:
        me = bpy.data.meshes.new(f"LowPolyFurniture({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()
        obj = bpy.data.objects.new(
            f"LowPolyFurniture({self.factory_seed})_{self.furniture_archetype}", me
        )
        bpy.context.scene.collection.objects.link(obj)
        while len(obj.data.materials) < 2:
            obj.data.materials.append(None)
        for start, end, slot in slot_ranges:
            for face_idx in range(start, end):
                obj.data.polygons[face_idx].material_index = slot
        for poly in obj.data.polygons:
            poly.use_smooth = False
        apply_palette_slots(obj, [self.wood_color, self.frame_color])
        return obj

    # -- archetype builders ------------------------------------------------

    def _build_bench(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        length = rng.uniform(1.4, 2.0)
        depth = 0.36
        seat_h = rng.uniform(0.44, 0.50)
        back_h = rng.uniform(0.42, 0.52)
        leg = 0.09

        _add_box(bm, cx=0.0, cy=0.0, z0=seat_h, sx=length, sy=depth, sz=0.08,
                 slot=0, slot_ranges=sr)
        # two short front legs
        for sx_sign in (-1.0, 1.0):
            _add_box(bm, cx=sx_sign * (length * 0.5 - 0.14), cy=-(depth * 0.5 - 0.08),
                     z0=0.0, sx=leg, sy=leg, sz=seat_h, slot=1, slot_ranges=sr)
        # two full-height back uprights (back legs + backrest posts in one)
        post_y = depth * 0.5 - 0.06
        for sx_sign in (-1.0, 1.0):
            _add_box(bm, cx=sx_sign * (length * 0.5 - 0.16), cy=post_y, z0=0.0,
                     sx=leg, sy=leg, sz=seat_h + back_h, slot=1, slot_ranges=sr)
        # two horizontal back rails
        for frac in (0.45, 0.85):
            _add_box(bm, cx=0.0, cy=post_y, z0=seat_h + back_h * frac,
                     sx=length * 0.88, sy=0.06, sz=0.08, slot=1, slot_ranges=sr)
        return self._finalize(bm, sr)

    def _build_trestle_table(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        length = rng.uniform(1.6, 2.2)
        depth = rng.uniform(0.72, 0.92)
        table_h = rng.uniform(0.72, 0.78)

        _add_box(bm, cx=0.0, cy=0.0, z0=table_h, sx=length, sy=depth, sz=0.10,
                 slot=0, slot_ranges=sr)
        # two trestle end planks
        for sx_sign in (-1.0, 1.0):
            _add_box(bm, cx=sx_sign * (length * 0.5 - 0.22), cy=0.0, z0=0.0,
                     sx=0.09, sy=depth * 0.78, sz=table_h, slot=1, slot_ranges=sr)
        # stretcher beam linking the trestles
        _add_box(bm, cx=0.0, cy=0.0, z0=table_h * 0.30, sx=length - 0.5, sy=0.10,
                 sz=0.12, slot=1, slot_ranges=sr)
        return self._finalize(bm, sr)

    def _build_stool(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        seat_h = rng.uniform(0.42, 0.50)
        seat_r = rng.uniform(0.20, 0.26)

        _add_cylinder(bm, cx=0.0, cy=0.0, z0=seat_h, radius=seat_r, height=0.07,
                      n_sides=10, slot=0, slot_ranges=sr)
        for i in range(3):
            a = 2.0 * math.pi * i / 3.0 + rng.uniform(-0.2, 0.2)
            rr = seat_r * 0.62
            _add_box(bm, cx=rr * math.cos(a), cy=rr * math.sin(a), z0=0.0,
                     sx=0.07, sy=0.07, sz=seat_h, slot=1, slot_ranges=sr)
        return self._finalize(bm, sr)

    def _build_market_counter(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        length = rng.uniform(1.7, 2.2)
        depth = rng.uniform(0.60, 0.75)
        counter_h = rng.uniform(0.88, 0.98)
        panel_h = counter_h - 0.05

        _add_box(bm, cx=0.0, cy=0.0, z0=counter_h, sx=length, sy=depth, sz=0.10,
                 slot=0, slot_ranges=sr)
        # solid customer-facing front panel
        _add_box(bm, cx=0.0, cy=-(depth * 0.5 - 0.05), z0=0.0, sx=length, sy=0.08,
                 sz=panel_h, slot=0, slot_ranges=sr)
        # two end panels
        for sx_sign in (-1.0, 1.0):
            _add_box(bm, cx=sx_sign * (length * 0.5 - 0.05), cy=0.0, z0=0.0,
                     sx=0.08, sy=depth, sz=panel_h, slot=1, slot_ranges=sr)
        return self._finalize(bm, sr)

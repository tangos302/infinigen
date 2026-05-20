"""LowPolyWaterfallFactory — waterfalls and water sources for steep terrain.

LowPolyWaterSurfaceFactory only makes flat water; alpine and jungle
scenes need vertical water. Each archetype is dark wet rock plus pale
falling-water sheets; the still pools are a child mesh carrying the
Maquette translucent water material.

Archetypes:
  cliff_fall     — a single tall sheer drop into a plunge pool
  cascade        — whitewater tumbling down a boulder-strewn slope
  multi_tier     — stacked drops with ledge pools between them
  spring_source  — a small spring welling from rocks with a short fall

Material slots:
  slot 0 = wet rock (cliff, boulders, ledges)
  slot 1 = falling water + foam (pale)
The still pools are a separate child object (Maquette water shader).
"""

from __future__ import annotations

import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots, apply_water_material


_WATERFALL_ARCHETYPES = ("cliff_fall", "cascade", "multi_tier", "spring_source")


def _face_count(bm: bmesh.types.BMesh) -> int:
    return len(bm.faces)


def _add_rock_chunk(
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
    rng: random.Random,
    rot_z: float = 0.0,
) -> None:
    """An irregular angular rock — a crag, boulder, or ledge."""
    start = _face_count(bm)
    rot = Matrix.Rotation(float(rot_z), 4, "Z")
    bot = []
    top = []
    for i in range(n_sides):
        a = 2.0 * math.pi * i / n_sides
        rb = radius * (1.0 + rng.uniform(-0.32, 0.32))
        rt = rb * rng.uniform(0.55, 0.92)
        lb = rot @ Vector((rb * math.cos(a), rb * math.sin(a), 0.0))
        lt = rot @ Vector((rt * math.cos(a), rt * math.sin(a), 0.0))
        bot.append(bm.verts.new((cx + lb.x, cy + lb.y, z0)))
        top.append(bm.verts.new((cx + lt.x, cy + lt.y, z0 + height * rng.uniform(0.7, 1.18))))
    bm.verts.ensure_lookup_table()
    for i in range(n_sides):
        ni = (i + 1) % n_sides
        bm.faces.new((bot[i], bot[ni], top[ni], top[i]))
    bm.faces.new(tuple(reversed(bot)))
    bm.faces.new(tuple(top))
    slot_ranges.append((start, _face_count(bm), int(slot)))


def _add_water_sheet(
    bm: bmesh.types.BMesh,
    *,
    cx: float,
    top_y: float,
    top_z: float,
    bot_y: float,
    bot_z: float,
    width: float,
    n_seg: int,
    slot: int,
    slot_ranges: list[tuple[int, int, int]],
    rng: random.Random,
) -> None:
    """A falling-water curtain — a quad ribbon from a top edge to a bottom
    edge, bulging forward mid-fall and fanning slightly wider at the base."""
    left = []
    right = []
    for k in range(n_seg + 1):
        f = k / n_seg
        y = top_y + (bot_y - top_y) * f + math.sin(f * math.pi) * rng.uniform(0.04, 0.13)
        z = top_z + (bot_z - top_z) * f
        w = width * (1.0 + 0.22 * f) * (1.0 + rng.uniform(-0.10, 0.10))
        left.append(bm.verts.new((cx - w * 0.5, y, z)))
        right.append(bm.verts.new((cx + w * 0.5, y, z)))
    bm.verts.ensure_lookup_table()
    start = _face_count(bm)
    for k in range(n_seg):
        bm.faces.new((left[k], right[k], right[k + 1], left[k + 1]))
    slot_ranges.append((start, _face_count(bm), int(slot)))


def _add_disc(
    bm: bmesh.types.BMesh,
    *,
    cx: float,
    cy: float,
    z0: float,
    radius: float,
    n_sides: int,
    thickness: float,
    jitter: float,
    slot: int,
    slot_ranges: list[tuple[int, int, int]],
    rng: random.Random,
) -> None:
    """A thin irregular disc slab — a still pool surface with a bit of
    thickness so it reads as a body of water, not a flat plane."""
    rim_top = []
    rim_bot = []
    for i in range(n_sides):
        a = 2.0 * math.pi * i / n_sides
        r = radius * (1.0 + rng.uniform(-jitter, jitter))
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        rim_bot.append(bm.verts.new((x, y, z0)))
        rim_top.append(bm.verts.new((x, y, z0 + thickness)))
    center = bm.verts.new(
        (cx + rng.uniform(-0.08, 0.08), cy + rng.uniform(-0.08, 0.08), z0 + thickness)
    )
    bm.verts.ensure_lookup_table()
    start = _face_count(bm)
    for i in range(n_sides):
        ni = (i + 1) % n_sides
        bm.faces.new((rim_top[i], rim_top[ni], center))
    for i in range(n_sides):
        ni = (i + 1) % n_sides
        bm.faces.new((rim_bot[i], rim_bot[ni], rim_top[ni], rim_top[i]))
    bm.faces.new(tuple(reversed(rim_bot)))
    slot_ranges.append((start, _face_count(bm), int(slot)))


class LowPolyWaterfallFactory(AssetFactory):
    """Procedural waterfalls — cliffs, cascades, tiered falls, springs.

    Constructor knobs:
        factory_seed
        waterfall_archetype : "cliff_fall" | "cascade" | "multi_tier"
                              | "spring_source"
        rock_color, water_color
    """

    def __init__(
        self,
        factory_seed,
        waterfall_archetype: str = "cliff_fall",
        rock_color: str | None = None,
        water_color: str | None = None,
        coarse: bool = False,
        **_unused_kwargs,
    ) -> None:
        super().__init__(factory_seed, coarse=coarse)
        if _unused_kwargs:
            from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
            accept_unused_kwargs("LowPolyWaterfallFactory", _unused_kwargs)
        if waterfall_archetype not in _WATERFALL_ARCHETYPES:
            import sys
            print(
                f"[waterfall_archetype] WARN: unknown {waterfall_archetype!r}; "
                f"falling back to {_WATERFALL_ARCHETYPES[0]!r}. "
                f"Valid: {_WATERFALL_ARCHETYPES}",
                file=sys.stderr,
            )
            waterfall_archetype = _WATERFALL_ARCHETYPES[0]
        self.waterfall_archetype = waterfall_archetype
        self.rock_color = rock_color or "rock_cool"
        self.water_color = water_color or "foliage_mint"

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(f"LowPolyWaterfall({self.factory_seed})_placeholder", None)
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        rng = random.Random(int(self.factory_seed) + 33967)
        builders = {
            "cliff_fall": self._build_cliff_fall,
            "cascade": self._build_cascade,
            "multi_tier": self._build_multi_tier,
            "spring_source": self._build_spring_source,
        }
        return builders[self.waterfall_archetype](rng)

    def _finalize(
        self,
        bm: bmesh.types.BMesh,
        slot_ranges: list[tuple[int, int, int]],
        water_bm: bmesh.types.BMesh,
    ) -> bpy.types.Object:
        me = bpy.data.meshes.new(f"LowPolyWaterfall({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()
        obj = bpy.data.objects.new(
            f"LowPolyWaterfall({self.factory_seed})_{self.waterfall_archetype}", me
        )
        bpy.context.scene.collection.objects.link(obj)
        while len(obj.data.materials) < 2:
            obj.data.materials.append(None)
        for start, end, slot in slot_ranges:
            for face_idx in range(start, end):
                obj.data.polygons[face_idx].material_index = slot
        for poly in obj.data.polygons:
            poly.use_smooth = False
        apply_palette_slots(obj, [self.rock_color, self.water_color])

        if len(water_bm.faces) > 0:
            wme = bpy.data.meshes.new(f"LowPolyWaterfall({self.factory_seed})_PoolMesh")
            water_bm.to_mesh(wme)
            water = bpy.data.objects.new(
                f"LowPolyWaterfall({self.factory_seed})_Pool", wme
            )
            bpy.context.scene.collection.objects.link(water)
            water.parent = obj
            for poly in water.data.polygons:
                poly.use_smooth = False
            apply_water_material(water)
        water_bm.free()
        return obj

    def _add_foam(
        self,
        bm: bmesh.types.BMesh,
        slot_ranges: list[tuple[int, int, int]],
        *,
        cx: float,
        cy: float,
        z0: float,
        spread: float,
        count: int,
        rng: random.Random,
    ) -> None:
        """A scatter of small pale chunks where falling water hits."""
        for _ in range(count):
            a = rng.uniform(0.0, 2.0 * math.pi)
            rr = spread * math.sqrt(rng.uniform(0.0, 1.0))
            _add_rock_chunk(
                bm, cx=cx + rr * math.cos(a), cy=cy + rr * math.sin(a) * 0.7, z0=z0,
                radius=rng.uniform(0.12, 0.24), height=rng.uniform(0.07, 0.16),
                n_sides=5, slot=1, slot_ranges=slot_ranges, rng=rng,
                rot_z=rng.uniform(0.0, math.pi),
            )

    # -- archetype builders ------------------------------------------------

    def _build_cliff_fall(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        wbm = bmesh.new()
        wsr: list[tuple[int, int, int]] = []

        cliff_h = rng.uniform(2.8, 3.8)
        _add_rock_chunk(bm, cx=0.0, cy=1.0, z0=0.0, radius=rng.uniform(1.2, 1.5),
                        height=cliff_h, n_sides=7, slot=0, slot_ranges=sr, rng=rng,
                        rot_z=rng.uniform(0.0, math.pi))
        for _ in range(rng.randint(2, 4)):
            a = rng.uniform(0.0, 2.0 * math.pi)
            _add_rock_chunk(bm, cx=math.cos(a) * rng.uniform(0.6, 1.3),
                            cy=-0.55 + abs(math.sin(a)) * 0.5, z0=-0.05,
                            radius=rng.uniform(0.30, 0.55), height=rng.uniform(0.3, 0.6),
                            n_sides=rng.choice((5, 6)), slot=0, slot_ranges=sr, rng=rng,
                            rot_z=rng.uniform(0.0, math.pi))
        _add_water_sheet(bm, cx=0.0, top_y=-0.18, top_z=cliff_h - 0.18,
                         bot_y=-0.48, bot_z=0.20, width=rng.uniform(0.9, 1.3),
                         n_seg=6, slot=1, slot_ranges=sr, rng=rng)
        self._add_foam(bm, sr, cx=0.0, cy=-0.42, z0=0.12, spread=0.55,
                       count=rng.randint(4, 7), rng=rng)
        _add_disc(wbm, cx=0.0, cy=0.45, z0=cliff_h - 0.30, radius=0.5, n_sides=8,
                  thickness=0.10, jitter=0.22, slot=0, slot_ranges=wsr, rng=rng)
        _add_disc(wbm, cx=0.0, cy=-0.62, z0=0.0, radius=rng.uniform(1.0, 1.3),
                  n_sides=12, thickness=0.12, jitter=0.16, slot=0, slot_ranges=wsr, rng=rng)
        return self._finalize(bm, sr, wbm)

    def _build_cascade(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        wbm = bmesh.new()
        wsr: list[tuple[int, int, int]] = []

        n_steps = rng.randint(5, 7)
        top_z = rng.uniform(2.0, 2.7)
        steps = []
        for k in range(n_steps):
            f = k / (n_steps - 1)
            z = top_z * (1.0 - f)
            cy = 1.0 - 2.0 * f
            cx = rng.uniform(-0.35, 0.35)
            radius = rng.uniform(0.5, 0.8)
            _add_rock_chunk(bm, cx=cx, cy=cy, z0=z, radius=radius,
                            height=rng.uniform(0.5, 0.8), n_sides=rng.choice((5, 6)),
                            slot=0, slot_ranges=sr, rng=rng, rot_z=rng.uniform(0.0, math.pi))
            steps.append((cx, cy, z + 0.45))
        for k in range(n_steps - 1):
            x0, y0, z0 = steps[k]
            x1, y1, z1 = steps[k + 1]
            _add_water_sheet(bm, cx=0.5 * (x0 + x1), top_y=y0, top_z=z0,
                             bot_y=y1, bot_z=z1, width=rng.uniform(0.55, 0.8),
                             n_seg=3, slot=1, slot_ranges=sr, rng=rng)
        self._add_foam(bm, sr, cx=steps[-1][0], cy=steps[-1][1] - 0.3, z0=0.1,
                       spread=0.5, count=rng.randint(3, 6), rng=rng)
        _add_disc(wbm, cx=0.0, cy=-1.4, z0=0.0, radius=rng.uniform(0.9, 1.2),
                  n_sides=11, thickness=0.12, jitter=0.18, slot=0, slot_ranges=wsr, rng=rng)
        return self._finalize(bm, sr, wbm)

    def _build_multi_tier(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        wbm = bmesh.new()
        wsr: list[tuple[int, int, int]] = []

        ledges = [
            (0.9, rng.uniform(2.2, 2.6), rng.uniform(0.85, 1.05)),
            (0.0, rng.uniform(1.1, 1.4), rng.uniform(0.95, 1.15)),
            (-1.0, rng.uniform(0.15, 0.3), rng.uniform(1.05, 1.30)),
        ]
        for (cy, z, radius) in ledges:
            _add_rock_chunk(bm, cx=rng.uniform(-0.2, 0.2), cy=cy, z0=0.0
                            if cy < -0.5 else z - rng.uniform(0.5, 0.8),
                            radius=radius, height=rng.uniform(0.55, 0.95),
                            n_sides=rng.choice((6, 7)), slot=0, slot_ranges=sr, rng=rng,
                            rot_z=rng.uniform(0.0, math.pi))
        for i in range(len(ledges) - 1):
            cy0, z0, _ = ledges[i]
            cy1, z1, _ = ledges[i + 1]
            _add_water_sheet(bm, cx=rng.uniform(-0.15, 0.15), top_y=cy0 - 0.45,
                             top_z=z0, bot_y=cy1 - 0.2, bot_z=z1 + 0.08,
                             width=rng.uniform(0.7, 1.0), n_seg=4, slot=1,
                             slot_ranges=sr, rng=rng)
        self._add_foam(bm, sr, cx=0.0, cy=ledges[1][0] - 0.4, z0=ledges[1][1],
                       spread=0.4, count=rng.randint(3, 5), rng=rng)
        _add_disc(wbm, cx=0.0, cy=ledges[0][0] - 0.05, z0=ledges[0][1],
                  radius=0.6, n_sides=9, thickness=0.10, jitter=0.2, slot=0,
                  slot_ranges=wsr, rng=rng)
        _add_disc(wbm, cx=0.0, cy=ledges[1][0] - 0.05, z0=ledges[1][1],
                  radius=0.62, n_sides=9, thickness=0.10, jitter=0.2, slot=0,
                  slot_ranges=wsr, rng=rng)
        _add_disc(wbm, cx=0.0, cy=ledges[2][0] - 0.55, z0=0.05,
                  radius=rng.uniform(0.95, 1.2), n_sides=12, thickness=0.12,
                  jitter=0.16, slot=0, slot_ranges=wsr, rng=rng)
        return self._finalize(bm, sr, wbm)

    def _build_spring_source(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        wbm = bmesh.new()
        wsr: list[tuple[int, int, int]] = []

        mound_h = rng.uniform(0.8, 1.2)
        _add_rock_chunk(bm, cx=0.0, cy=0.55, z0=0.0, radius=rng.uniform(0.8, 1.05),
                        height=mound_h, n_sides=7, slot=0, slot_ranges=sr, rng=rng,
                        rot_z=rng.uniform(0.0, math.pi))
        for _ in range(rng.randint(2, 3)):
            a = rng.uniform(0.0, 2.0 * math.pi)
            _add_rock_chunk(bm, cx=math.cos(a) * rng.uniform(0.5, 0.95),
                            cy=-0.3 + abs(math.sin(a)) * 0.4, z0=-0.04,
                            radius=rng.uniform(0.22, 0.4), height=rng.uniform(0.2, 0.4),
                            n_sides=5, slot=0, slot_ranges=sr, rng=rng,
                            rot_z=rng.uniform(0.0, math.pi))
        _add_water_sheet(bm, cx=0.0, top_y=0.05, top_z=mound_h - 0.18,
                         bot_y=-0.28, bot_z=0.12, width=rng.uniform(0.4, 0.6),
                         n_seg=4, slot=1, slot_ranges=sr, rng=rng)
        self._add_foam(bm, sr, cx=0.0, cy=-0.26, z0=0.08, spread=0.32,
                       count=rng.randint(3, 5), rng=rng)
        _add_disc(wbm, cx=0.0, cy=-0.4, z0=0.0, radius=rng.uniform(0.6, 0.85),
                  n_sides=10, thickness=0.10, jitter=0.18, slot=0,
                  slot_ranges=wsr, rng=rng)
        return self._finalize(bm, sr, wbm)

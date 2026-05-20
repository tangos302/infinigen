"""LowPolyCandleClusterFactory — candles for shrines, tables, crypts.

This is the small-scale complement to torches and campfires. It provides
readable warm light for interiors, altar props, market stalls, monastery
steps, and ruined chambers.
"""

from __future__ import annotations

import math
import random

import bmesh
import bpy

from infinigen.core.placement.factory import AssetFactory

from ...materials import (
    add_palette_point_light,
    apply_emission_palette_slot,
    apply_palette_slots,
)


_CANDLE_ARCHETYPES = ("three_candles", "altar_row", "melted_cluster")


def _face_count(bm: bmesh.types.BMesh) -> int:
    return len(bm.faces)


def _add_cylinder(
    bm: bmesh.types.BMesh,
    x: float,
    y: float,
    z0: float,
    radius: float,
    height: float,
    n_sides: int,
    slots: list[tuple[int, int, int]],
    slot: int,
) -> None:
    start = _face_count(bm)
    bot = []
    top = []
    for i in range(n_sides):
        a = 2.0 * math.pi * i / n_sides
        bot.append(bm.verts.new((x + radius * math.cos(a), y + radius * math.sin(a), z0)))
        top.append(bm.verts.new((x + radius * math.cos(a), y + radius * math.sin(a), z0 + height)))
    bm.verts.ensure_lookup_table()
    for i in range(n_sides):
        ni = (i + 1) % n_sides
        bm.faces.new((bot[i], bot[ni], top[ni], top[i]))
    bm.faces.new(list(reversed(bot)))
    bm.faces.new(top)
    slots.append((start, _face_count(bm), slot))


def _add_tiny_flame(
    bm: bmesh.types.BMesh,
    x: float,
    y: float,
    z: float,
    radius: float,
    height: float,
    slots: list[tuple[int, int, int]],
) -> None:
    start = _face_count(bm)
    ring = []
    for i in range(5):
        a = 2.0 * math.pi * i / 5.0
        ring.append(bm.verts.new((x + radius * math.cos(a), y + radius * math.sin(a), z)))
    apex = bm.verts.new((x, y, z + height))
    bm.verts.ensure_lookup_table()
    for i in range(5):
        ni = (i + 1) % 5
        bm.faces.new((ring[i], ring[ni], apex))
    slots.append((start, _face_count(bm), 2))


class LowPolyCandleClusterFactory(AssetFactory):
    """Clustered candles with emission and one shared point light."""

    def __init__(
        self,
        factory_seed,
        candle_archetype: str = "three_candles",
        candle_count: int | None = None,
        wax_color: str = "stucco",
        holder_color: str = "rust_metal",
        flame_color: str = "foliage_lemon",
        emit_light: bool = True,
        light_energy: float = 28.0,
        light_radius: float = 0.75,
        emission_strength: float = 3.4,
        coarse: bool = False,
        **_unused_kwargs,
    ) -> None:
        super().__init__(factory_seed, coarse=coarse)
        if _unused_kwargs:
            from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
            accept_unused_kwargs("LowPolyCandleClusterFactory", _unused_kwargs)
        if candle_archetype not in _CANDLE_ARCHETYPES:
            import sys
            print(
                f"[candle_archetype] WARN: unknown {candle_archetype!r}; "
                f"falling back to {_CANDLE_ARCHETYPES[0]!r}. Valid: {_CANDLE_ARCHETYPES}",
                file=sys.stderr,
            )
            candle_archetype = _CANDLE_ARCHETYPES[0]
        self.candle_archetype = candle_archetype
        self.candle_count = int(candle_count if candle_count is not None else (
            3 if candle_archetype == "three_candles" else 5 if candle_archetype == "altar_row" else 7
        ))
        self.wax_color = wax_color
        self.holder_color = holder_color
        self.flame_color = flame_color
        self.emit_light = bool(emit_light)
        self.light_energy = float(light_energy)
        self.light_radius = float(light_radius)
        self.emission_strength = float(emission_strength)

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(f"LowPolyCandleCluster({self.factory_seed})_placeholder", None)
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        rng = random.Random(int(self.factory_seed) + 48109)
        bm = bmesh.new()
        slots: list[tuple[int, int, int]] = []

        positions: list[tuple[float, float]] = []
        if self.candle_archetype == "altar_row":
            step = 0.18
            start = -step * (self.candle_count - 1) * 0.5
            positions = [(start + i * step, rng.uniform(-0.03, 0.03)) for i in range(self.candle_count)]
        else:
            for i in range(self.candle_count):
                a = 2.0 * math.pi * i / max(1, self.candle_count) + rng.uniform(-0.22, 0.22)
                r = rng.uniform(0.04, 0.24 if self.candle_archetype == "melted_cluster" else 0.18)
                positions.append((r * math.cos(a), r * math.sin(a)))

        _add_cylinder(bm, 0.0, 0.0, 0.0, 0.34, 0.035, 10, slots, 1)
        top_zs: list[float] = []
        for x, y in positions:
            height = rng.uniform(0.20, 0.48)
            if self.candle_archetype == "melted_cluster":
                height *= rng.uniform(0.55, 0.95)
            radius = rng.uniform(0.035, 0.055)
            _add_cylinder(bm, x, y, 0.035, radius, height, 8, slots, 0)
            top_z = 0.035 + height
            top_zs.append(top_z)
            _add_tiny_flame(bm, x, y, top_z, radius * 0.45, 0.10, slots)

        mesh = bpy.data.meshes.new(f"LowPolyCandleCluster({self.factory_seed})_Mesh")
        bm.to_mesh(mesh)
        bm.free()
        obj = bpy.data.objects.new(f"LowPolyCandleCluster({self.factory_seed})", mesh)
        bpy.context.scene.collection.objects.link(obj)
        while len(obj.data.materials) < 3:
            obj.data.materials.append(None)
        for start, end, slot in slots:
            for face_idx in range(start, end):
                obj.data.polygons[face_idx].material_index = slot
        for poly in obj.data.polygons:
            poly.use_smooth = False
        apply_palette_slots(obj, [self.wax_color, self.holder_color, self.flame_color])
        apply_emission_palette_slot(obj, 2, self.flame_color, strength=self.emission_strength)
        if self.emit_light:
            add_palette_point_light(
                name=f"{obj.name}_PointLight",
                location=(0.0, 0.0, (max(top_zs) if top_zs else 0.35) + 0.08),
                palette_key=self.flame_color,
                energy=self.light_energy,
                radius=self.light_radius,
                parent=obj,
            )
        return obj

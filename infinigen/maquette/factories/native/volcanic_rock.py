"""LowPolyVolcanicRockFactory — cooled volcanic rock for the volcanic biome.

The solid, non-glowing half of the volcanic kit (LowPolyLavaFactory is
the molten half). Dark angular rock with a lighter weathered accent.

Archetypes:
  basalt_column    — a tight cluster of hexagonal columns at stepped
                     heights, Giant's-Causeway style
  obsidian_cluster — sharp angular glassy shards jutting at angles
  cinder_cone      — a scoria cone with an open crater and loose
                     cinder rubble on the slopes
  cracked_boulder  — one big faceted volcanic boulder with rubble at
                     its base

Material slots:
  slot 0 = volcanic rock (dark basalt / obsidian / cinder)
  slot 1 = weathered accent (column tops, ash dusting, lighter rubble)
"""

from __future__ import annotations

import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_VOLCANIC_ROCK_ARCHETYPES = ("basalt_column", "obsidian_cluster", "cinder_cone", "cracked_boulder")

# Per-archetype (rock_color, accent_color) defaults — basalt reads as grey
# stone with bleached tops, obsidian near-black, cinder dark with rust-red
# oxidised scoria, boulders grey volcanic stone.
_ARCHETYPE_COLORS = {
    "basalt_column": ("rock_cool", "stucco"),
    "obsidian_cluster": ("rock_shadow", "rock_cool"),
    "cinder_cone": ("rock_shadow", "rock_warm"),
    "cracked_boulder": ("rock_cool", "rock_shadow"),
}


def _face_count(bm: bmesh.types.BMesh) -> int:
    return len(bm.faces)


def _add_hex_column(
    bm: bmesh.types.BMesh,
    *,
    cx: float,
    cy: float,
    z0: float,
    radius: float,
    height: float,
    slot_wall: int,
    slot_top: int,
    slot_ranges: list[tuple[int, int, int]],
    rng: random.Random,
    rot_z: float = 0.0,
) -> None:
    """A basalt column — a 6-sided prism, walls one slot and the flat top
    another so the columns read with lighter weathered crowns."""
    n = 6
    rot = Matrix.Rotation(float(rot_z), 4, "Z")
    bot = []
    top = []
    for i in range(n):
        a = 2.0 * math.pi * i / n
        r = radius * (1.0 + rng.uniform(-0.06, 0.06))
        loc = rot @ Vector((r * math.cos(a), r * math.sin(a), 0.0))
        bot.append(bm.verts.new((cx + loc.x, cy + loc.y, z0)))
        top.append(bm.verts.new((cx + loc.x, cy + loc.y, z0 + height)))
    bm.verts.ensure_lookup_table()
    start = _face_count(bm)
    for i in range(n):
        ni = (i + 1) % n
        bm.faces.new((bot[i], bot[ni], top[ni], top[i]))
    bm.faces.new(tuple(reversed(bot)))
    slot_ranges.append((start, _face_count(bm), int(slot_wall)))
    cap_start = _face_count(bm)
    bm.faces.new(tuple(top))
    slot_ranges.append((cap_start, _face_count(bm), int(slot_top)))


def _add_shard(
    bm: bmesh.types.BMesh,
    *,
    cx: float,
    cy: float,
    z0: float,
    base_radius: float,
    height: float,
    lean_x: float,
    lean_y: float,
    n_sides: int,
    slot: int,
    slot_ranges: list[tuple[int, int, int]],
    rng: random.Random,
    rot_z: float = 0.0,
) -> None:
    """A sharp angular shard — a jittered base polygon tapering to a
    leaned point. Obsidian."""
    start = _face_count(bm)
    rot = Matrix.Rotation(float(rot_z), 4, "Z")
    base = []
    for i in range(n_sides):
        a = 2.0 * math.pi * i / n_sides
        r = base_radius * (1.0 + rng.uniform(-0.25, 0.25))
        loc = rot @ Vector((r * math.cos(a), r * math.sin(a), 0.0))
        base.append(bm.verts.new((cx + loc.x, cy + loc.y, z0)))
    apex = bm.verts.new((cx + lean_x, cy + lean_y, z0 + height))
    bm.verts.ensure_lookup_table()
    for i in range(n_sides):
        ni = (i + 1) % n_sides
        bm.faces.new((base[i], base[ni], apex))
    bm.faces.new(tuple(reversed(base)))
    slot_ranges.append((start, _face_count(bm), int(slot)))


def _add_cone(
    bm: bmesh.types.BMesh,
    *,
    cx: float,
    cy: float,
    z0: float,
    base_radius: float,
    top_radius: float,
    height: float,
    n_sides: int,
    cap_top: bool,
    slot: int,
    slot_ranges: list[tuple[int, int, int]],
    rng: random.Random,
) -> None:
    """A rough truncated cone — the cinder cone (open crater)."""
    start = _face_count(bm)
    bot = []
    top = []
    for i in range(n_sides):
        a = 2.0 * math.pi * i / n_sides
        rb = base_radius * (1.0 + rng.uniform(-0.10, 0.10))
        rt = top_radius * (1.0 + rng.uniform(-0.16, 0.16))
        bot.append(bm.verts.new((cx + rb * math.cos(a), cy + rb * math.sin(a), z0)))
        top.append(
            bm.verts.new(
                (cx + rt * math.cos(a), cy + rt * math.sin(a), z0 + height * rng.uniform(0.94, 1.06))
            )
        )
    bm.verts.ensure_lookup_table()
    for i in range(n_sides):
        ni = (i + 1) % n_sides
        bm.faces.new((bot[i], bot[ni], top[ni], top[i]))
    bm.faces.new(tuple(reversed(bot)))
    if cap_top:
        bm.faces.new(tuple(top))
    slot_ranges.append((start, _face_count(bm), int(slot)))


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
    """An irregular angular rock — a faceted boulder or loose rubble."""
    start = _face_count(bm)
    rot = Matrix.Rotation(float(rot_z), 4, "Z")
    bot = []
    top = []
    for i in range(n_sides):
        a = 2.0 * math.pi * i / n_sides
        rb = radius * (1.0 + rng.uniform(-0.34, 0.34))
        rt = rb * rng.uniform(0.45, 0.88)
        lb = rot @ Vector((rb * math.cos(a), rb * math.sin(a), 0.0))
        lt = rot @ Vector((rt * math.cos(a), rt * math.sin(a), 0.0))
        bot.append(bm.verts.new((cx + lb.x, cy + lb.y, z0)))
        top.append(bm.verts.new((cx + lt.x, cy + lt.y, z0 + height * rng.uniform(0.6, 1.22))))
    bm.verts.ensure_lookup_table()
    for i in range(n_sides):
        ni = (i + 1) % n_sides
        bm.faces.new((bot[i], bot[ni], top[ni], top[i]))
    bm.faces.new(tuple(reversed(bot)))
    bm.faces.new(tuple(top))
    slot_ranges.append((start, _face_count(bm), int(slot)))


class LowPolyVolcanicRockFactory(AssetFactory):
    """Cooled volcanic rock — basalt columns, obsidian, cinder cones, boulders.

    Constructor knobs:
        factory_seed
        volcanic_archetype : "basalt_column" | "obsidian_cluster"
                             | "cinder_cone" | "cracked_boulder"
        rock_color, accent_color
    """

    def __init__(
        self,
        factory_seed,
        volcanic_archetype: str = "basalt_column",
        rock_color: str | None = None,
        accent_color: str | None = None,
        coarse: bool = False,
        **_unused_kwargs,
    ) -> None:
        super().__init__(factory_seed, coarse=coarse)
        if _unused_kwargs:
            from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
            accept_unused_kwargs("LowPolyVolcanicRockFactory", _unused_kwargs)
        if volcanic_archetype not in _VOLCANIC_ROCK_ARCHETYPES:
            import sys
            print(
                f"[volcanic_archetype] WARN: unknown {volcanic_archetype!r}; "
                f"falling back to {_VOLCANIC_ROCK_ARCHETYPES[0]!r}. "
                f"Valid: {_VOLCANIC_ROCK_ARCHETYPES}",
                file=sys.stderr,
            )
            volcanic_archetype = _VOLCANIC_ROCK_ARCHETYPES[0]
        self.volcanic_archetype = volcanic_archetype
        _rock_default, _accent_default = _ARCHETYPE_COLORS[volcanic_archetype]
        self.rock_color = rock_color or _rock_default
        self.accent_color = accent_color or _accent_default

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyVolcanicRock({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        rng = random.Random(int(self.factory_seed) + 91577)
        builders = {
            "basalt_column": self._build_basalt_column,
            "obsidian_cluster": self._build_obsidian_cluster,
            "cinder_cone": self._build_cinder_cone,
            "cracked_boulder": self._build_cracked_boulder,
        }
        return builders[self.volcanic_archetype](rng)

    def _finalize(
        self, bm: bmesh.types.BMesh, slot_ranges: list[tuple[int, int, int]]
    ) -> bpy.types.Object:
        me = bpy.data.meshes.new(f"LowPolyVolcanicRock({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()
        obj = bpy.data.objects.new(
            f"LowPolyVolcanicRock({self.factory_seed})_{self.volcanic_archetype}", me
        )
        bpy.context.scene.collection.objects.link(obj)
        while len(obj.data.materials) < 2:
            obj.data.materials.append(None)
        for start, end, slot in slot_ranges:
            for face_idx in range(start, end):
                obj.data.polygons[face_idx].material_index = slot
        for poly in obj.data.polygons:
            poly.use_smooth = False
        apply_palette_slots(obj, [self.rock_color, self.accent_color])
        return obj

    # -- archetype builders ------------------------------------------------

    def _build_basalt_column(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        cluster_r = rng.uniform(0.6, 0.95)
        for _ in range(rng.randint(9, 16)):
            a = rng.uniform(0.0, 2.0 * math.pi)
            rr = cluster_r * math.sqrt(rng.uniform(0.0, 1.0))
            _add_hex_column(
                bm, cx=rr * math.cos(a), cy=rr * math.sin(a), z0=0.0,
                radius=rng.uniform(0.17, 0.27), height=rng.uniform(0.7, 2.6),
                slot_wall=0, slot_top=1, slot_ranges=sr, rng=rng,
                rot_z=rng.uniform(0.0, math.pi),
            )
        return self._finalize(bm, sr)

    def _build_obsidian_cluster(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        cluster_r = rng.uniform(0.55, 0.85)
        for _ in range(rng.randint(6, 11)):
            a = rng.uniform(0.0, 2.0 * math.pi)
            rr = cluster_r * math.sqrt(rng.uniform(0.0, 1.0))
            px, py = rr * math.cos(a), rr * math.sin(a)
            h = rng.uniform(0.6, 1.9)
            lean = h * rng.uniform(0.05, 0.32)
            ldir = rng.uniform(0.0, 2.0 * math.pi)
            _add_shard(
                bm, cx=px, cy=py, z0=0.0,
                base_radius=rng.uniform(0.12, 0.26), height=h,
                lean_x=math.cos(ldir) * lean, lean_y=math.sin(ldir) * lean,
                n_sides=rng.choice((4, 5)), slot=0, slot_ranges=sr, rng=rng,
                rot_z=rng.uniform(0.0, math.pi),
            )
        return self._finalize(bm, sr)

    def _build_cinder_cone(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        base_r = rng.uniform(1.3, 2.0)
        height = rng.uniform(1.2, 2.0)
        top_r = base_r * rng.uniform(0.22, 0.34)
        _add_cone(
            bm, cx=0.0, cy=0.0, z0=0.0, base_radius=base_r, top_radius=top_r,
            height=height, n_sides=11, cap_top=False, slot=0, slot_ranges=sr, rng=rng,
        )
        for _ in range(rng.randint(8, 14)):
            a = rng.uniform(0.0, 2.0 * math.pi)
            f = rng.uniform(0.0, 0.85)
            rr = base_r * (1.0 - f) + top_r * f + rng.uniform(0.02, 0.16)
            _add_rock_chunk(
                bm, cx=rr * math.cos(a), cy=rr * math.sin(a), z0=height * f - 0.05,
                radius=rng.uniform(0.08, 0.18), height=rng.uniform(0.07, 0.16),
                n_sides=rng.choice((5, 6)), slot=rng.choice((0, 0, 1)),
                slot_ranges=sr, rng=rng, rot_z=rng.uniform(0.0, math.pi),
            )
        return self._finalize(bm, sr)

    def _build_cracked_boulder(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        _add_rock_chunk(
            bm, cx=0.0, cy=0.0, z0=0.0,
            radius=rng.uniform(1.0, 1.5), height=rng.uniform(1.2, 1.9),
            n_sides=rng.choice((7, 8, 9)), slot=0, slot_ranges=sr, rng=rng,
            rot_z=rng.uniform(0.0, math.pi),
        )
        for _ in range(rng.randint(4, 8)):
            a = rng.uniform(0.0, 2.0 * math.pi)
            rr = rng.uniform(1.0, 1.7)
            _add_rock_chunk(
                bm, cx=rr * math.cos(a), cy=rr * math.sin(a), z0=-0.04,
                radius=rng.uniform(0.18, 0.42), height=rng.uniform(0.18, 0.5),
                n_sides=rng.choice((5, 6)), slot=rng.choice((0, 0, 1)),
                slot_ranges=sr, rng=rng, rot_z=rng.uniform(0.0, math.pi),
            )
        return self._finalize(bm, sr)

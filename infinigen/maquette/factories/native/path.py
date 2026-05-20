"""LowPolyPathFactory — path, road, and stair segments.

Ground-level path segments to give scenes routes and direction. Each is
a straight segment running along +X (placement orients it); the pipeline
can chain several. `road_crossing` stays a descriptive enrichment
feature — these are the placeable objects the LLM can lay down directly.

Archetypes:
  dirt_path     — a worn earthen strip with irregular edges + loose stones
  cobbled_road  — a paved strip tiled with cobblestones and a stone curb
  stone_steps   — a short flight of solid stone steps
  gravel_lane   — a gravel strip framed by timber edging boards

Material slots:
  slot 0 = surface (path bed / step stone)
  slot 1 = stone (cobbles, gravel, loose stones)
  slot 2 = edge (curb stones, timber edging)
"""

from __future__ import annotations

import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_PATH_ARCHETYPES = ("dirt_path", "cobbled_road", "stone_steps", "gravel_lane")

# Per-archetype (surface, stone, edge) palette keys.
_ARCHETYPE_COLORS = {
    "dirt_path": ("ground_sand", "rock_cool", "rock_shadow"),
    "cobbled_road": ("rock_shadow", "rock_cool", "rock_pale"),
    "stone_steps": ("rock_pale", "rock_cool", "rock_shadow"),
    "gravel_lane": ("ground_sand", "rock_pale", "wood"),
}


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


def _add_strip(
    bm: bmesh.types.BMesh,
    *,
    length: float,
    width: float,
    thickness: float,
    n_seg: int,
    edge_jitter: float,
    slot: int,
    slot_ranges: list[tuple[int, int, int]],
    rng: random.Random,
) -> None:
    """A thin path-bed slab running along +X, with irregularly jittered
    side edges so a dirt/gravel path doesn't read as a clean board."""
    left, right, left_b, right_b = [], [], [], []
    for k in range(n_seg + 1):
        x = -length * 0.5 + length * k / n_seg
        wl = width * 0.5 * (1.0 + rng.uniform(-edge_jitter, edge_jitter))
        wr = width * 0.5 * (1.0 + rng.uniform(-edge_jitter, edge_jitter))
        zt = thickness + rng.uniform(-thickness * 0.2, thickness * 0.2)
        left.append(bm.verts.new((x, wl, zt)))
        right.append(bm.verts.new((x, -wr, zt)))
        left_b.append(bm.verts.new((x, wl, 0.0)))
        right_b.append(bm.verts.new((x, -wr, 0.0)))
    bm.verts.ensure_lookup_table()
    start = _face_count(bm)
    for k in range(n_seg):
        bm.faces.new((left[k], left[k + 1], right[k + 1], right[k]))
        bm.faces.new((left_b[k], left[k], left[k + 1], left_b[k + 1]))
        bm.faces.new((right_b[k + 1], right[k + 1], right[k], right_b[k]))
        bm.faces.new((left_b[k + 1], right_b[k + 1], right_b[k], left_b[k]))
    bm.faces.new((left_b[0], right_b[0], right[0], left[0]))
    bm.faces.new((left[n_seg], right[n_seg], right_b[n_seg], left_b[n_seg]))
    slot_ranges.append((start, _face_count(bm), int(slot)))


def _add_pebble(
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
    """A small irregular low rock — a cobble, gravel bit, or loose stone."""
    start = _face_count(bm)
    rot = Matrix.Rotation(float(rot_z), 4, "Z")
    bot = []
    top = []
    for i in range(n_sides):
        a = 2.0 * math.pi * i / n_sides
        rb = radius * (1.0 + rng.uniform(-0.28, 0.28))
        rt = rb * rng.uniform(0.6, 0.95)
        lb = rot @ Vector((rb * math.cos(a), rb * math.sin(a), 0.0))
        lt = rot @ Vector((rt * math.cos(a), rt * math.sin(a), 0.0))
        bot.append(bm.verts.new((cx + lb.x, cy + lb.y, z0)))
        top.append(bm.verts.new((cx + lt.x, cy + lt.y, z0 + height * rng.uniform(0.7, 1.15))))
    bm.verts.ensure_lookup_table()
    for i in range(n_sides):
        ni = (i + 1) % n_sides
        bm.faces.new((bot[i], bot[ni], top[ni], top[i]))
    bm.faces.new(tuple(reversed(bot)))
    bm.faces.new(tuple(top))
    slot_ranges.append((start, _face_count(bm), int(slot)))


class LowPolyPathFactory(AssetFactory):
    """Path / road / stair segments.

    Constructor knobs:
        factory_seed
        path_archetype : "dirt_path" | "cobbled_road" | "stone_steps"
                         | "gravel_lane"
        surface_color, stone_color, edge_color
    """

    def __init__(
        self,
        factory_seed,
        path_archetype: str = "dirt_path",
        surface_color: str | None = None,
        stone_color: str | None = None,
        edge_color: str | None = None,
        coarse: bool = False,
        **_unused_kwargs,
    ) -> None:
        super().__init__(factory_seed, coarse=coarse)
        if _unused_kwargs:
            from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
            accept_unused_kwargs("LowPolyPathFactory", _unused_kwargs)
        if path_archetype not in _PATH_ARCHETYPES:
            import sys
            print(
                f"[path_archetype] WARN: unknown {path_archetype!r}; "
                f"falling back to {_PATH_ARCHETYPES[0]!r}. Valid: {_PATH_ARCHETYPES}",
                file=sys.stderr,
            )
            path_archetype = _PATH_ARCHETYPES[0]
        self.path_archetype = path_archetype
        _surface, _stone, _edge = _ARCHETYPE_COLORS[path_archetype]
        self.surface_color = surface_color or _surface
        self.stone_color = stone_color or _stone
        self.edge_color = edge_color or _edge

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(f"LowPolyPath({self.factory_seed})_placeholder", None)
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        rng = random.Random(int(self.factory_seed) + 13877)
        builders = {
            "dirt_path": self._build_dirt_path,
            "cobbled_road": self._build_cobbled_road,
            "stone_steps": self._build_stone_steps,
            "gravel_lane": self._build_gravel_lane,
        }
        return builders[self.path_archetype](rng)

    def _finalize(
        self, bm: bmesh.types.BMesh, slot_ranges: list[tuple[int, int, int]]
    ) -> bpy.types.Object:
        me = bpy.data.meshes.new(f"LowPolyPath({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()
        obj = bpy.data.objects.new(
            f"LowPolyPath({self.factory_seed})_{self.path_archetype}", me
        )
        bpy.context.scene.collection.objects.link(obj)
        while len(obj.data.materials) < 3:
            obj.data.materials.append(None)
        for start, end, slot in slot_ranges:
            for face_idx in range(start, end):
                obj.data.polygons[face_idx].material_index = slot
        for poly in obj.data.polygons:
            poly.use_smooth = False
        apply_palette_slots(
            obj, [self.surface_color, self.stone_color, self.edge_color]
        )
        return obj

    # -- archetype builders ------------------------------------------------

    def _build_dirt_path(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        length = rng.uniform(4.5, 6.0)
        width = rng.uniform(1.6, 2.4)
        _add_strip(bm, length=length, width=width, thickness=0.10, n_seg=8,
                   edge_jitter=0.22, slot=0, slot_ranges=sr, rng=rng)
        for _ in range(rng.randint(6, 12)):
            _add_pebble(
                bm, cx=rng.uniform(-length * 0.5, length * 0.5),
                cy=rng.uniform(-width * 0.4, width * 0.4), z0=0.06,
                radius=rng.uniform(0.05, 0.12), height=rng.uniform(0.04, 0.10),
                n_sides=5, slot=1, slot_ranges=sr, rng=rng,
                rot_z=rng.uniform(0.0, math.pi),
            )
        return self._finalize(bm, sr)

    def _build_cobbled_road(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        length = rng.uniform(4.5, 6.0)
        width = rng.uniform(1.8, 2.6)
        _add_strip(bm, length=length, width=width, thickness=0.08, n_seg=8,
                   edge_jitter=0.08, slot=0, slot_ranges=sr, rng=rng)
        cell = 0.40
        nx = max(1, int(length / cell))
        ny = max(1, int(width * 0.84 / cell))
        for ix in range(nx):
            for iy in range(ny):
                cx = -length * 0.5 + cell * (ix + 0.5) + rng.uniform(-0.05, 0.05)
                cy = -width * 0.42 + cell * (iy + 0.5) + rng.uniform(-0.05, 0.05)
                _add_pebble(
                    bm, cx=cx, cy=cy, z0=0.05, radius=cell * 0.42,
                    height=rng.uniform(0.06, 0.12), n_sides=rng.choice((4, 5, 6)),
                    slot=1, slot_ranges=sr, rng=rng, rot_z=rng.uniform(0.0, math.pi),
                )
        for side in (-1.0, 1.0):
            for ix in range(max(1, int(length / 0.55))):
                cx = -length * 0.5 + 0.55 * (ix + 0.5)
                _add_pebble(
                    bm, cx=cx, cy=side * width * 0.5, z0=0.05,
                    radius=rng.uniform(0.16, 0.24), height=rng.uniform(0.14, 0.22),
                    n_sides=rng.choice((5, 6)), slot=2, slot_ranges=sr, rng=rng,
                    rot_z=rng.uniform(0.0, math.pi),
                )
        return self._finalize(bm, sr)

    def _build_stone_steps(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        n_steps = rng.randint(4, 7)
        step_w = rng.uniform(1.8, 2.6)
        step_run = rng.uniform(0.50, 0.70)
        step_rise = rng.uniform(0.22, 0.32)
        for k in range(n_steps):
            _add_box(bm, cx=(k + 0.5) * step_run, cy=0.0, z0=0.0, sx=step_run,
                     sy=step_w, sz=(k + 1) * step_rise, slot=0, slot_ranges=sr)
        # a few loose stones flanking the foot of the flight
        for _ in range(rng.randint(2, 4)):
            side = rng.choice((-1.0, 1.0))
            _add_pebble(
                bm, cx=rng.uniform(0.0, step_run * 1.5),
                cy=side * (step_w * 0.5 + rng.uniform(0.05, 0.25)), z0=0.0,
                radius=rng.uniform(0.14, 0.26), height=rng.uniform(0.14, 0.30),
                n_sides=rng.choice((5, 6)), slot=2, slot_ranges=sr, rng=rng,
                rot_z=rng.uniform(0.0, math.pi),
            )
        return self._finalize(bm, sr)

    def _build_gravel_lane(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        length = rng.uniform(4.5, 6.0)
        width = rng.uniform(1.6, 2.2)
        _add_strip(bm, length=length, width=width, thickness=0.09, n_seg=8,
                   edge_jitter=0.12, slot=0, slot_ranges=sr, rng=rng)
        for _ in range(rng.randint(34, 52)):
            _add_pebble(
                bm, cx=rng.uniform(-length * 0.5, length * 0.5),
                cy=rng.uniform(-width * 0.42, width * 0.42), z0=0.06,
                radius=rng.uniform(0.04, 0.085), height=rng.uniform(0.03, 0.07),
                n_sides=rng.choice((4, 5)), slot=1, slot_ranges=sr, rng=rng,
                rot_z=rng.uniform(0.0, math.pi),
            )
        for side in (-1.0, 1.0):
            _add_box(bm, cx=0.0, cy=side * width * 0.5, z0=0.0, sx=length,
                     sy=0.12, sz=0.15, slot=2, slot_ranges=sr)
        return self._finalize(bm, sr)

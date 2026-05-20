"""LowPolyFountainFactory — stone fountains and water basins.

A plaza / garden / village-square centrepiece, missing from the catalog
entirely. Each archetype is stone masonry holding one or more water
surfaces; the water is a child mesh carrying the Maquette translucent
water material.

Archetypes:
  tiered_basin  — a classic three-tier stone fountain: ground basin,
                  central pillar, two flared upper bowls, a finial
  village_basin — a single octagonal basin with a central spout column
  wall_spout    — a wall-mounted fountain: backplate, spout, catch basin
  bamboo_basin  — a zen tsukubai: a low stone basin fed by a bamboo
                  spout pipe off an upright post

Material slots:
  slot 0 = stone masonry
  slot 1 = wood / bamboo (bamboo_basin spout + post)
The water surfaces are a separate child object (Maquette water shader).
"""

from __future__ import annotations

import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots, apply_water_material


_FOUNTAIN_ARCHETYPES = ("tiered_basin", "village_basin", "wall_spout", "bamboo_basin")


def _face_count(bm: bmesh.types.BMesh) -> int:
    return len(bm.faces)


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
    top_scale: float = 1.0,
    rot_z: float = 0.0,
) -> None:
    """A round prism from z0 to z0+height; top_scale flares the top ring
    (a bowl) or pinches it (a finial)."""
    start = _face_count(bm)
    rot = Matrix.Rotation(float(rot_z), 4, "Z")
    bot = []
    top = []
    for i in range(n_sides):
        a = 2.0 * math.pi * i / n_sides
        lb = rot @ Vector((radius * math.cos(a), radius * math.sin(a), 0.0))
        lt = rot @ Vector(
            (radius * top_scale * math.cos(a), radius * top_scale * math.sin(a), 0.0)
        )
        bot.append(bm.verts.new((cx + lb.x, cy + lb.y, z0)))
        top.append(bm.verts.new((cx + lt.x, cy + lt.y, z0 + height)))
    bm.verts.ensure_lookup_table()
    for i in range(n_sides):
        ni = (i + 1) % n_sides
        bm.faces.new((bot[i], bot[ni], top[ni], top[i]))
    bm.faces.new(tuple(reversed(bot)))
    bm.faces.new(tuple(top))
    slot_ranges.append((start, _face_count(bm), int(slot)))


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
    """A plain axis-aligned box."""
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


def _add_pipe(
    bm: bmesh.types.BMesh,
    *,
    p0: tuple[float, float, float],
    p1: tuple[float, float, float],
    radius: float,
    n_sides: int,
    slot: int,
    slot_ranges: list[tuple[int, int, int]],
) -> None:
    """A round pipe between two arbitrary points — the bamboo spout."""
    start = _face_count(bm)
    v0, v1 = Vector(p0), Vector(p1)
    axis = v1 - v0
    if axis.length < 1e-6:
        return
    axis.normalize()
    ref = Vector((0.0, 0.0, 1.0))
    if abs(axis.dot(ref)) > 0.95:
        ref = Vector((1.0, 0.0, 0.0))
    u = axis.cross(ref).normalized()
    w = axis.cross(u).normalized()
    ring0 = []
    ring1 = []
    for i in range(n_sides):
        a = 2.0 * math.pi * i / n_sides
        offset = u * (radius * math.cos(a)) + w * (radius * math.sin(a))
        ring0.append(bm.verts.new(tuple(v0 + offset)))
        ring1.append(bm.verts.new(tuple(v1 + offset)))
    bm.verts.ensure_lookup_table()
    for i in range(n_sides):
        ni = (i + 1) % n_sides
        bm.faces.new((ring0[i], ring0[ni], ring1[ni], ring1[i]))
    bm.faces.new(tuple(reversed(ring0)))
    bm.faces.new(tuple(ring1))
    slot_ranges.append((start, _face_count(bm), int(slot)))


class LowPolyFountainFactory(AssetFactory):
    """Stone fountains with translucent water basins.

    Constructor knobs:
        factory_seed
        fountain_archetype : "tiered_basin" | "village_basin"
                             | "wall_spout" | "bamboo_basin"
        stone_color, wood_color
    """

    def __init__(
        self,
        factory_seed,
        fountain_archetype: str = "tiered_basin",
        stone_color: str | None = None,
        wood_color: str | None = None,
        coarse: bool = False,
        **_unused_kwargs,
    ) -> None:
        super().__init__(factory_seed, coarse=coarse)
        if _unused_kwargs:
            from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
            accept_unused_kwargs("LowPolyFountainFactory", _unused_kwargs)
        if fountain_archetype not in _FOUNTAIN_ARCHETYPES:
            import sys
            print(
                f"[fountain_archetype] WARN: unknown {fountain_archetype!r}; "
                f"falling back to {_FOUNTAIN_ARCHETYPES[0]!r}. "
                f"Valid: {_FOUNTAIN_ARCHETYPES}",
                file=sys.stderr,
            )
            fountain_archetype = _FOUNTAIN_ARCHETYPES[0]
        self.fountain_archetype = fountain_archetype
        self.stone_color = stone_color or "rock_pale"
        self.wood_color = wood_color or "wood"

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(f"LowPolyFountain({self.factory_seed})_placeholder", None)
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        rng = random.Random(int(self.factory_seed) + 70411)
        builders = {
            "tiered_basin": self._build_tiered_basin,
            "village_basin": self._build_village_basin,
            "wall_spout": self._build_wall_spout,
            "bamboo_basin": self._build_bamboo_basin,
        }
        return builders[self.fountain_archetype](rng)

    def _finalize(
        self,
        bm: bmesh.types.BMesh,
        slot_ranges: list[tuple[int, int, int]],
        water_bm: bmesh.types.BMesh,
    ) -> bpy.types.Object:
        me = bpy.data.meshes.new(f"LowPolyFountain({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()
        obj = bpy.data.objects.new(
            f"LowPolyFountain({self.factory_seed})_{self.fountain_archetype}", me
        )
        bpy.context.scene.collection.objects.link(obj)
        while len(obj.data.materials) < 2:
            obj.data.materials.append(None)
        for start, end, slot in slot_ranges:
            for face_idx in range(start, end):
                obj.data.polygons[face_idx].material_index = slot
        for poly in obj.data.polygons:
            poly.use_smooth = False
        apply_palette_slots(obj, [self.stone_color, self.wood_color])

        if len(water_bm.faces) > 0:
            wme = bpy.data.meshes.new(f"LowPolyFountain({self.factory_seed})_WaterMesh")
            water_bm.to_mesh(wme)
            water = bpy.data.objects.new(
                f"LowPolyFountain({self.factory_seed})_Water", wme
            )
            bpy.context.scene.collection.objects.link(water)
            water.parent = obj
            for poly in water.data.polygons:
                poly.use_smooth = False
            apply_water_material(water)
        water_bm.free()
        return obj

    # -- archetype builders ------------------------------------------------

    def _build_tiered_basin(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        wbm = bmesh.new()
        wsr: list[tuple[int, int, int]] = []

        basin_r = rng.uniform(1.4, 1.7)
        basin_h = 0.46
        _add_cylinder(bm, cx=0.0, cy=0.0, z0=0.0, radius=basin_r, height=basin_h,
                      n_sides=12, slot=0, slot_ranges=sr)
        _add_cylinder(wbm, cx=0.0, cy=0.0, z0=basin_h - 0.10, radius=basin_r - 0.18,
                      height=0.11, n_sides=12, slot=0, slot_ranges=wsr)

        _add_cylinder(bm, cx=0.0, cy=0.0, z0=basin_h - 0.05, radius=0.22, height=1.05,
                      n_sides=8, slot=0, slot_ranges=sr)

        t1_z = basin_h - 0.05 + 1.05 - 0.03
        t1_r = rng.uniform(0.78, 0.92)
        _add_cylinder(bm, cx=0.0, cy=0.0, z0=t1_z, radius=t1_r * 0.7, height=0.26,
                      n_sides=10, slot=0, slot_ranges=sr, top_scale=1.4)
        _add_cylinder(wbm, cx=0.0, cy=0.0, z0=t1_z + 0.26 - 0.08, radius=t1_r * 0.92,
                      height=0.09, n_sides=10, slot=0, slot_ranges=wsr)

        p2_z = t1_z + 0.26 - 0.04
        _add_cylinder(bm, cx=0.0, cy=0.0, z0=p2_z, radius=0.13, height=0.52,
                      n_sides=8, slot=0, slot_ranges=sr)

        t2_z = p2_z + 0.52 - 0.03
        t2_r = rng.uniform(0.42, 0.52)
        _add_cylinder(bm, cx=0.0, cy=0.0, z0=t2_z, radius=t2_r * 0.65, height=0.20,
                      n_sides=8, slot=0, slot_ranges=sr, top_scale=1.5)
        _add_cylinder(wbm, cx=0.0, cy=0.0, z0=t2_z + 0.20 - 0.07, radius=t2_r * 0.92,
                      height=0.08, n_sides=8, slot=0, slot_ranges=wsr)

        _add_cylinder(bm, cx=0.0, cy=0.0, z0=t2_z + 0.20 - 0.02, radius=0.13,
                      height=0.22, n_sides=8, slot=0, slot_ranges=sr, top_scale=0.3)
        return self._finalize(bm, sr, wbm)

    def _build_village_basin(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        wbm = bmesh.new()
        wsr: list[tuple[int, int, int]] = []

        basin_r = rng.uniform(1.2, 1.5)
        basin_h = rng.uniform(0.55, 0.70)
        _add_cylinder(bm, cx=0.0, cy=0.0, z0=0.0, radius=basin_r, height=basin_h,
                      n_sides=8, slot=0, slot_ranges=sr, rot_z=rng.uniform(0.0, 0.4))
        _add_cylinder(wbm, cx=0.0, cy=0.0, z0=basin_h - 0.10, radius=basin_r - 0.17,
                      height=0.11, n_sides=8, slot=0, slot_ranges=wsr)

        col_h = rng.uniform(0.55, 0.82)
        _add_cylinder(bm, cx=0.0, cy=0.0, z0=basin_h - 0.06, radius=0.27, height=col_h,
                      n_sides=6, slot=0, slot_ranges=sr)
        _add_cylinder(bm, cx=0.0, cy=0.0, z0=basin_h - 0.06 + col_h - 0.02,
                      radius=0.17, height=0.15, n_sides=6, slot=0, slot_ranges=sr,
                      top_scale=0.45)
        return self._finalize(bm, sr, wbm)

    def _build_wall_spout(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        wbm = bmesh.new()
        wsr: list[tuple[int, int, int]] = []

        back_w = rng.uniform(1.4, 1.7)
        back_h = rng.uniform(1.9, 2.4)
        _add_box(bm, cx=0.0, cy=0.34, z0=0.0, sx=back_w, sy=0.3, sz=back_h,
                 slot=0, slot_ranges=sr)
        _add_box(bm, cx=0.0, cy=0.34, z0=back_h - 0.02, sx=back_w + 0.18, sy=0.44,
                 sz=0.16, slot=0, slot_ranges=sr)
        _add_box(bm, cx=0.0, cy=0.04, z0=back_h * 0.54, sx=0.26, sy=0.42, sz=0.20,
                 slot=0, slot_ranges=sr)

        basin_r = rng.uniform(0.62, 0.78)
        basin_h = 0.50
        _add_cylinder(bm, cx=0.0, cy=-0.16, z0=0.0, radius=basin_r, height=basin_h,
                      n_sides=8, slot=0, slot_ranges=sr)
        _add_cylinder(wbm, cx=0.0, cy=-0.16, z0=basin_h - 0.10, radius=basin_r - 0.15,
                      height=0.11, n_sides=8, slot=0, slot_ranges=wsr)
        return self._finalize(bm, sr, wbm)

    def _build_bamboo_basin(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        wbm = bmesh.new()
        wsr: list[tuple[int, int, int]] = []

        basin_r = rng.uniform(0.44, 0.58)
        basin_h = rng.uniform(0.30, 0.38)
        _add_cylinder(bm, cx=0.0, cy=0.0, z0=0.0, radius=basin_r, height=basin_h,
                      n_sides=7, slot=0, slot_ranges=sr, rot_z=rng.uniform(0.0, 0.5))
        _add_cylinder(wbm, cx=0.0, cy=0.0, z0=basin_h - 0.09, radius=basin_r - 0.12,
                      height=0.10, n_sides=7, slot=0, slot_ranges=wsr)

        post_x = basin_r + 0.26
        post_h = rng.uniform(0.95, 1.25)
        _add_cylinder(bm, cx=post_x, cy=0.0, z0=0.0, radius=0.052, height=post_h,
                      n_sides=6, slot=1, slot_ranges=sr)
        # bamboo spout pipe — from near the post top down over the basin centre
        _add_pipe(
            bm,
            p0=(post_x - 0.02, 0.0, post_h - 0.06),
            p1=(0.05, 0.0, basin_h + 0.12),
            radius=0.047,
            n_sides=6,
            slot=1,
            slot_ranges=sr,
        )
        return self._finalize(bm, sr, wbm)

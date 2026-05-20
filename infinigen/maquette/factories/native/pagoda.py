"""LowPolyPagodaFactory — East Asian pagodas, temple halls, pavilions.

A hero building for zen-garden and Asian-themed scenes — the catalog had
torii gates, stone lanterns, and zen garden gates but no actual temple
building. The signature element is the wide overhanging tiered roof: a
thin eave slab plus a frustum cap.

Archetypes:
  tiered_pagoda   — a tall multi-storey tower of diminishing roofed
                    storeys topped with a finial
  temple_hall     — a single broad storey under one big sweeping roof
  garden_pavilion — an open four-post pavilion on a platform, no walls
  shrine          — a tiny roofed wayside shrine on a post

Material slots:
  slot 0 = wall / body
  slot 1 = roof
  slot 2 = timber (posts, plinth, finial)
"""

from __future__ import annotations

import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_PAGODA_ARCHETYPES = ("tiered_pagoda", "temple_hall", "garden_pavilion", "shrine")

# Per-archetype (body_color, roof_color, wood_color).
_ARCHETYPE_COLORS = {
    "tiered_pagoda": ("stucco", "accent_red", "rock_shadow"),
    "temple_hall": ("stucco", "rock_shadow", "wood"),
    "garden_pavilion": ("stucco", "foliage_pine", "wood"),
    "shrine": ("wood", "accent_red", "rock_shadow"),
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
    top_scale_x: float = 1.0,
    top_scale_y: float = 1.0,
    rot_z: float = 0.0,
) -> None:
    """A box from z0 to z0+sz; the top face can be scaled (frustum bodies,
    pyramid roof caps, tapered finials)."""
    start = _face_count(bm)
    rot = Matrix.Rotation(float(rot_z), 4, "Z")
    hx, hy = sx * 0.5, sy * 0.5
    txh, tyh = hx * top_scale_x, hy * top_scale_y
    bottom_local = ((-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy))
    top_local = ((-txh, -tyh), (txh, -tyh), (txh, tyh), (-txh, tyh))
    bottom = []
    top = []
    for lx, ly in bottom_local:
        p = rot @ Vector((lx, ly, 0.0))
        bottom.append(bm.verts.new((cx + p.x, cy + p.y, z0)))
    for lx, ly in top_local:
        p = rot @ Vector((lx, ly, 0.0))
        top.append(bm.verts.new((cx + p.x, cy + p.y, z0 + sz)))
    bm.verts.ensure_lookup_table()
    for i in range(4):
        ni = (i + 1) % 4
        bm.faces.new((bottom[i], bottom[ni], top[ni], top[i]))
    bm.faces.new(tuple(reversed(bottom)))
    bm.faces.new(tuple(top))
    slot_ranges.append((start, _face_count(bm), int(slot)))


def _add_roof_tier(
    bm: bmesh.types.BMesh,
    *,
    cx: float,
    cy: float,
    z0: float,
    eave_w: float,
    eave_d: float,
    pitch: float,
    slot: int,
    slot_ranges: list[tuple[int, int, int]],
    rot_z: float = 0.0,
    top_scale: float = 0.5,
) -> float:
    """One tiered roof — a thin overhanging eave slab plus a frustum cap.
    Returns the Z of the cap top so storeys can stack."""
    _add_box(bm, cx=cx, cy=cy, z0=z0, sx=eave_w, sy=eave_d, sz=0.10,
             slot=slot, slot_ranges=slot_ranges, rot_z=rot_z)
    _add_box(bm, cx=cx, cy=cy, z0=z0 + 0.10, sx=eave_w * 0.86, sy=eave_d * 0.86,
             sz=pitch, slot=slot, slot_ranges=slot_ranges,
             top_scale_x=top_scale, top_scale_y=top_scale, rot_z=rot_z)
    return z0 + 0.10 + pitch


class LowPolyPagodaFactory(AssetFactory):
    """East Asian temple buildings — pagodas, halls, pavilions, shrines.

    Constructor knobs:
        factory_seed
        pagoda_archetype : "tiered_pagoda" | "temple_hall"
                           | "garden_pavilion" | "shrine"
        body_color, roof_color, wood_color
    """

    def __init__(
        self,
        factory_seed,
        pagoda_archetype: str = "tiered_pagoda",
        body_color: str | None = None,
        roof_color: str | None = None,
        wood_color: str | None = None,
        coarse: bool = False,
        **_unused_kwargs,
    ) -> None:
        super().__init__(factory_seed, coarse=coarse)
        if _unused_kwargs:
            from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
            accept_unused_kwargs("LowPolyPagodaFactory", _unused_kwargs)
        if pagoda_archetype not in _PAGODA_ARCHETYPES:
            import sys
            print(
                f"[pagoda_archetype] WARN: unknown {pagoda_archetype!r}; "
                f"falling back to {_PAGODA_ARCHETYPES[0]!r}. Valid: {_PAGODA_ARCHETYPES}",
                file=sys.stderr,
            )
            pagoda_archetype = _PAGODA_ARCHETYPES[0]
        self.pagoda_archetype = pagoda_archetype
        _body, _roof, _wood = _ARCHETYPE_COLORS[pagoda_archetype]
        self.body_color = body_color or _body
        self.roof_color = roof_color or _roof
        self.wood_color = wood_color or _wood

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(f"LowPolyPagoda({self.factory_seed})_placeholder", None)
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        rng = random.Random(int(self.factory_seed) + 82051)
        builders = {
            "tiered_pagoda": self._build_tiered_pagoda,
            "temple_hall": self._build_temple_hall,
            "garden_pavilion": self._build_garden_pavilion,
            "shrine": self._build_shrine,
        }
        return builders[self.pagoda_archetype](rng)

    def _finalize(
        self, bm: bmesh.types.BMesh, slot_ranges: list[tuple[int, int, int]]
    ) -> bpy.types.Object:
        me = bpy.data.meshes.new(f"LowPolyPagoda({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()
        obj = bpy.data.objects.new(
            f"LowPolyPagoda({self.factory_seed})_{self.pagoda_archetype}", me
        )
        bpy.context.scene.collection.objects.link(obj)
        while len(obj.data.materials) < 3:
            obj.data.materials.append(None)
        for start, end, slot in slot_ranges:
            for face_idx in range(start, end):
                obj.data.polygons[face_idx].material_index = slot
        for poly in obj.data.polygons:
            poly.use_smooth = False
        apply_palette_slots(obj, [self.body_color, self.roof_color, self.wood_color])
        return obj

    # -- archetype builders ------------------------------------------------

    def _build_tiered_pagoda(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        n_storeys = rng.randint(3, 5)
        base_w = rng.uniform(1.7, 2.2)
        plinth_h = 0.26
        _add_box(bm, cx=0.0, cy=0.0, z0=0.0, sx=base_w * 1.15, sy=base_w * 1.15,
                 sz=plinth_h, slot=2, slot_ranges=sr)
        z = plinth_h
        body_w = base_w
        for k in range(n_storeys):
            body_h = rng.uniform(0.70, 0.95) * (0.92 ** k)
            _add_box(bm, cx=0.0, cy=0.0, z0=z, sx=body_w, sy=body_w, sz=body_h,
                     slot=0, slot_ranges=sr)
            z += body_h
            is_top = k == n_storeys - 1
            z = _add_roof_tier(
                bm, cx=0.0, cy=0.0, z0=z, eave_w=body_w * 1.55, eave_d=body_w * 1.55,
                pitch=body_w * 0.32, slot=1, slot_ranges=sr,
                top_scale=0.16 if is_top else 0.55,
            )
            body_w *= 0.80
        _add_box(bm, cx=0.0, cy=0.0, z0=z, sx=0.18, sy=0.18, sz=0.42, slot=2,
                 slot_ranges=sr, top_scale_x=0.32, top_scale_y=0.32)
        _add_box(bm, cx=0.0, cy=0.0, z0=z + 0.42, sx=0.11, sy=0.11, sz=0.28,
                 slot=2, slot_ranges=sr, top_scale_x=0.25, top_scale_y=0.25)
        return self._finalize(bm, sr)

    def _build_temple_hall(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        width = rng.uniform(2.6, 3.4)
        depth = width * rng.uniform(0.60, 0.75)
        plinth_h = 0.30
        _add_box(bm, cx=0.0, cy=0.0, z0=0.0, sx=width * 1.10, sy=depth * 1.15,
                 sz=plinth_h, slot=2, slot_ranges=sr)
        body_h = rng.uniform(1.3, 1.7)
        _add_box(bm, cx=0.0, cy=0.0, z0=plinth_h, sx=width, sy=depth, sz=body_h,
                 slot=0, slot_ranges=sr)
        z = _add_roof_tier(
            bm, cx=0.0, cy=0.0, z0=plinth_h + body_h, eave_w=width * 1.40,
            eave_d=depth * 1.55, pitch=depth * 0.45, slot=1, slot_ranges=sr,
            top_scale=0.34,
        )
        # ridge beam along the roof crest
        _add_box(bm, cx=0.0, cy=0.0, z0=z - 0.06, sx=width * 0.5, sy=0.12,
                 sz=0.12, slot=2, slot_ranges=sr)
        return self._finalize(bm, sr)

    def _build_garden_pavilion(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        base_w = rng.uniform(1.6, 2.1)
        plat_h = 0.22
        _add_box(bm, cx=0.0, cy=0.0, z0=0.0, sx=base_w, sy=base_w, sz=plat_h,
                 slot=2, slot_ranges=sr)
        post_h = rng.uniform(1.5, 1.9)
        inset = base_w * 0.5 - 0.18
        for sx_sign in (-1.0, 1.0):
            for sy_sign in (-1.0, 1.0):
                _add_box(bm, cx=sx_sign * inset, cy=sy_sign * inset, z0=plat_h,
                         sx=0.13, sy=0.13, sz=post_h, slot=2, slot_ranges=sr)
        _add_roof_tier(
            bm, cx=0.0, cy=0.0, z0=plat_h + post_h, eave_w=base_w * 1.42,
            eave_d=base_w * 1.42, pitch=base_w * 0.42, slot=1, slot_ranges=sr,
            top_scale=0.2,
        )
        return self._finalize(bm, sr)

    def _build_shrine(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        post_h = rng.uniform(0.40, 0.70)
        _add_box(bm, cx=0.0, cy=0.0, z0=0.0, sx=0.34, sy=0.34, sz=post_h,
                 slot=2, slot_ranges=sr)
        body_w = rng.uniform(0.50, 0.70)
        body_h = rng.uniform(0.45, 0.60)
        _add_box(bm, cx=0.0, cy=0.0, z0=post_h, sx=body_w, sy=body_w * 0.8,
                 sz=body_h, slot=0, slot_ranges=sr)
        _add_roof_tier(
            bm, cx=0.0, cy=0.0, z0=post_h + body_h, eave_w=body_w * 1.7,
            eave_d=body_w * 1.5, pitch=body_w * 0.5, slot=1, slot_ranges=sr,
            top_scale=0.18,
        )
        return self._finalize(bm, sr)

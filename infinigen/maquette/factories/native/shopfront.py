"""LowPolyShopfrontFactory — readable street-front shop module.

Market towns currently have stalls and houses, but few middle-scale
commerce pieces. A shopfront provides an awning, display counter, sign,
shutters, and goods arranged as one coherent facade that can sit along a
road or against a building row.

Archetypes:
  awning_shop       — cloth awning over counter and crates.
  bakery_front      — warm shop with bread/display trays and chimney box.
  apothecary_front  — narrow facade with sign jars and shelves.
  closed_shutters   — shut shop / evening street dressing.

Material slots:
  slot 0 = wall / facade
  slot 1 = awning / cloth / paint
  slot 2 = wood trim / shelves
  slot 3 = goods / sign accents
"""

from __future__ import annotations

import random

import bmesh
import bpy

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_SHOPFRONT_ARCHETYPES = ("awning_shop", "bakery_front", "apothecary_front", "closed_shutters")

_ARCHETYPE_DEFAULTS = {
    "awning_shop": dict(width=3.8, depth=1.25, height=2.6, awning=True, counter=True, goods=5),
    "bakery_front": dict(width=3.5, depth=1.35, height=2.8, awning=True, counter=True, goods=6),
    "apothecary_front": dict(width=3.0, depth=1.15, height=3.1, awning=False, counter=True, goods=7),
    "closed_shutters": dict(width=3.4, depth=0.95, height=2.65, awning=False, counter=False, goods=1),
}


def _face_count(bm: bmesh.types.BMesh) -> int:
    return len(bm.faces)


def _add_box(
    bm: bmesh.types.BMesh,
    ranges: list[tuple[int, int, int]],
    slot: int,
    center: tuple[float, float, float],
    size: tuple[float, float, float],
) -> None:
    start = _face_count(bm)
    res = bmesh.ops.create_cube(bm, size=1.0)
    cx, cy, cz = center
    sx, sy, sz = size
    for v in res["verts"]:
        v.co.x = v.co.x * sx + cx
        v.co.y = v.co.y * sy + cy
        v.co.z = v.co.z * sz + cz
    bm.faces.ensure_lookup_table()
    ranges.append((start, _face_count(bm), int(slot)))


def _add_sloped_awning(
    bm: bmesh.types.BMesh,
    ranges: list[tuple[int, int, int]],
    *,
    width: float,
    y: float,
    z: float,
    depth: float,
) -> None:
    start = _face_count(bm)
    hx = width * 0.5
    verts = [
        bm.verts.new((-hx, y, z)),
        bm.verts.new((hx, y, z)),
        bm.verts.new((hx, y - depth, z - 0.36)),
        bm.verts.new((-hx, y - depth, z - 0.36)),
    ]
    bm.verts.ensure_lookup_table()
    bm.faces.new(tuple(verts))
    ranges.append((start, _face_count(bm), 1))
    # Valance edge.
    _add_box(bm, ranges, 1, (0.0, y - depth, z - 0.46), (width, 0.06, 0.22))


class LowPolyShopfrontFactory(AssetFactory):
    """Street-facing shop facade with awning, counter, sign, and goods.

    Constructor knobs:
        factory_seed
        shopfront_archetype : "awning_shop" | "bakery_front" | "apothecary_front" | "closed_shutters"
        width, depth, height
        awning, counter, goods
        wall_color, cloth_color, wood_color, goods_color
    """

    def __init__(
        self,
        factory_seed,
        shopfront_archetype: str = "awning_shop",
        width: float | None = None,
        depth: float | None = None,
        height: float | None = None,
        awning: bool | None = None,
        counter: bool | None = None,
        goods: int | None = None,
        wall_color: str = "stucco",
        cloth_color: str = "accent_red",
        wood_color: str = "wood",
        goods_color: str = "rock_warm",
        coarse: bool = False,
        **_unused_kwargs,
    ) -> None:
        super().__init__(factory_seed, coarse=coarse)
        if _unused_kwargs:
            from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
            accept_unused_kwargs("LowPolyShopfrontFactory", _unused_kwargs)
        if shopfront_archetype not in _SHOPFRONT_ARCHETYPES:
            import sys
            print(
                f"[shopfront_archetype] WARN: unknown {shopfront_archetype!r}; "
                f"falling back to {_SHOPFRONT_ARCHETYPES[0]!r}. Valid: {_SHOPFRONT_ARCHETYPES}",
                file=sys.stderr,
            )
            shopfront_archetype = _SHOPFRONT_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[shopfront_archetype]
        self.shopfront_archetype = shopfront_archetype
        self.width = float(width if width is not None else d["width"])
        self.depth = float(depth if depth is not None else d["depth"])
        self.height = float(height if height is not None else d["height"])
        self.awning = bool(awning if awning is not None else d["awning"])
        self.counter = bool(counter if counter is not None else d["counter"])
        self.goods = int(goods if goods is not None else d["goods"])
        self.wall_color = wall_color
        self.cloth_color = cloth_color
        self.wood_color = wood_color
        self.goods_color = goods_color

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(f"LowPolyShopfront({self.factory_seed})_placeholder", None)
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        rng = random.Random(self.factory_seed)
        bm = bmesh.new()
        ranges: list[tuple[int, int, int]] = []
        w = self.width * rng.uniform(0.92, 1.10)
        d = self.depth * rng.uniform(0.90, 1.16)
        h = self.height * rng.uniform(0.94, 1.10)
        lean = rng.uniform(-0.05, 0.05)
        # Thin back wall/facade.
        _add_box(bm, ranges, 0, (0.0, 0.0, h * 0.5), (w, 0.28, h))
        # Shallow side returns keep the shop from reading as a cardboard wall.
        if self.shopfront_archetype != "closed_shutters" or rng.random() < 0.65:
            side_depth = d * rng.uniform(0.42, 0.72)
            _add_box(bm, ranges, 0, (-w * 0.50, -side_depth * 0.42, h * 0.44), (0.18, side_depth, h * 0.88))
            if rng.random() < 0.75:
                _add_box(bm, ranges, 0, (w * 0.50, -side_depth * 0.38, h * 0.38), (0.16, side_depth * 0.78, h * 0.76))
        # Small roof cap and base.
        _add_box(bm, ranges, 2, (lean, 0.05, h + 0.12), (w * rng.uniform(1.04, 1.14), 0.42, 0.24))
        _add_box(bm, ranges, 2, (0.0, -0.04, 0.12), (w * 1.06, 0.38, 0.24))
        # Door + windows/shutters.
        door_x = -w * rng.uniform(0.23, 0.34)
        _add_box(bm, ranges, 2, (door_x, -0.18, 0.82), (rng.uniform(0.48, 0.64), 0.08, 1.35))
        if self.shopfront_archetype == "closed_shutters":
            for x in (rng.uniform(-w * 0.03, w * 0.05), w * rng.uniform(0.22, 0.34)):
                _add_box(bm, ranges, 2, (x, -0.19, 1.62), (0.58, 0.09, 0.76))
                _add_box(bm, ranges, 2, (x, -0.25, 1.62), (0.70, 0.06, 0.10))
        else:
            window_count = 1 if self.shopfront_archetype == "bakery_front" and rng.random() < 0.35 else 2
            xs = [w * 0.12] if window_count == 1 else [w * rng.uniform(0.02, 0.10), w * rng.uniform(0.24, 0.36)]
            for x in xs:
                _add_box(bm, ranges, 3, (x, -0.19, 1.78), (rng.uniform(0.46, 0.62), 0.07, rng.uniform(0.50, 0.68)))
                _add_box(bm, ranges, 2, (x, -0.23, 1.48), (0.68, 0.06, 0.08))
        if self.awning:
            _add_sloped_awning(bm, ranges, width=w * rng.uniform(0.78, 0.98), y=-0.16, z=h * rng.uniform(0.72, 0.80), depth=d)
            if rng.random() < 0.55:
                for x in (-w * 0.36, 0.0, w * 0.36):
                    _add_box(bm, ranges, 1, (x, -d * 0.92, h * 0.58), (0.08, 0.08, rng.uniform(0.70, 1.05)))
        if self.counter:
            _add_box(bm, ranges, 2, (w * 0.20, -d * 0.58, 0.72), (w * 0.52, 0.44, 0.44))
            _add_box(bm, ranges, 2, (w * 0.20, -d * 0.82, 1.00), (w * 0.60, 0.14, 0.12))
        # Hanging/free sign.
        sign_x = -w * rng.uniform(0.02, 0.12) if self.shopfront_archetype == "apothecary_front" else -w * rng.uniform(0.36, 0.46)
        _add_box(bm, ranges, 2, (sign_x, -0.30, h * 0.78), (0.08, 0.55, 0.08))
        _add_box(bm, ranges, 3, (sign_x, -0.58, h * 0.62), (0.58, 0.10, 0.34))
        # Goods: bread/wares/jars as small boxes in front.
        for i in range(self.goods):
            if self.shopfront_archetype == "closed_shutters" and i > 0:
                break
            t = (i + 0.5) / max(1, self.goods)
            x = -w * 0.08 + (w * 0.54) * t
            y = -d * rng.uniform(0.72, 1.05)
            if self.shopfront_archetype == "apothecary_front":
                sx, sy, sz = 0.18, 0.18, rng.uniform(0.22, 0.40)
            elif self.shopfront_archetype == "bakery_front":
                sx, sy, sz = rng.uniform(0.24, 0.42), rng.uniform(0.18, 0.30), 0.16
            else:
                sx, sy, sz = rng.uniform(0.22, 0.38), rng.uniform(0.22, 0.34), rng.uniform(0.20, 0.38)
            _add_box(bm, ranges, 3, (x, y, 0.26 + sz * 0.5), (sx, sy, sz))

        me = bpy.data.meshes.new(f"LowPolyShopfront({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()
        obj = bpy.data.objects.new(f"LowPolyShopfront({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)
        while len(obj.data.materials) < 4:
            obj.data.materials.append(None)
        for start, end, slot in ranges:
            for i in range(start, min(end, len(obj.data.polygons))):
                obj.data.polygons[i].material_index = slot
        for p in obj.data.polygons:
            p.use_smooth = False
        apply_palette_slots(obj, [self.wall_color, self.cloth_color, self.wood_color, self.goods_color])
        return obj

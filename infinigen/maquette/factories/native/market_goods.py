"""LowPolyMarketGoodsFactory — wares to fill market stalls and counters.

Stalls, counters, and carts existed but had nothing to sell. These are
the goods that dress a market: heaped produce, stacked pottery, grain
sacks, woven baskets.

Archetypes:
  produce_pile  — a heap of round fruit/veg on a wooden tray
  pottery_stack — a cluster of clay jars with flared rims
  sack_cluster  — bulging cloth sacks with cinched tops
  basket_group  — open woven baskets, some heaped with produce

Material slots (per-archetype meaning, set from _ARCHETYPE_COLORS):
  slot 0 = base    — tray wood / pot clay / sack cloth / basket weave
  slot 1 = produce — fruit, or a second cloth tone
  slot 2 = accent  — pot rims, sack ties, basket rims, a 2nd produce hue
"""

from __future__ import annotations

import math
import random

import bmesh
import bpy

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_GOODS_ARCHETYPES = ("produce_pile", "pottery_stack", "sack_cluster", "basket_group")

# Per-archetype (base, produce, accent) palette keys.
_ARCHETYPE_COLORS = {
    "produce_pile": ("wood", "foliage_apple", "accent_red"),
    "pottery_stack": ("rock_warm", "foliage_apple", "rock_shadow"),
    "sack_cluster": ("stucco", "ground_sand", "wood"),
    "basket_group": ("ground_sand", "foliage_apple", "accent_red"),
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
    cap_top: bool = True,
    cap_bottom: bool = True,
) -> None:
    """A round prism — pot bodies (capped), basket bodies (open top)."""
    start = _face_count(bm)
    bot = []
    top = []
    for i in range(n_sides):
        a = 2.0 * math.pi * i / n_sides
        bot.append(bm.verts.new((cx + radius * math.cos(a), cy + radius * math.sin(a), z0)))
        top.append(
            bm.verts.new(
                (cx + radius * top_scale * math.cos(a),
                 cy + radius * top_scale * math.sin(a), z0 + height)
            )
        )
    bm.verts.ensure_lookup_table()
    for i in range(n_sides):
        ni = (i + 1) % n_sides
        bm.faces.new((bot[i], bot[ni], top[ni], top[i]))
    if cap_bottom:
        bm.faces.new(tuple(reversed(bot)))
    if cap_top:
        bm.faces.new(tuple(top))
    slot_ranges.append((start, _face_count(bm), int(slot)))


def _add_icosphere_blob(
    bm: bmesh.types.BMesh,
    *,
    cx: float,
    cy: float,
    cz: float,
    sx: float,
    sy: float,
    sz: float,
    slot: int,
    slot_ranges: list[tuple[int, int, int]],
    rng: random.Random,
) -> None:
    """A jittered low-poly icosphere — a piece of produce or a cloth sack."""
    start = _face_count(bm)
    result = bmesh.ops.create_icosphere(bm, subdivisions=1, radius=1.0)
    for v in result["verts"]:
        nx = cx + v.co.x * sx + rng.uniform(-sx * 0.12, sx * 0.12)
        ny = cy + v.co.y * sy + rng.uniform(-sy * 0.12, sy * 0.12)
        nz = cz + v.co.z * sz + rng.uniform(-sz * 0.12, sz * 0.12)
        v.co = (nx, ny, nz)
    slot_ranges.append((start, _face_count(bm), int(slot)))


class LowPolyMarketGoodsFactory(AssetFactory):
    """Market wares — produce, pottery, sacks, baskets.

    Constructor knobs:
        factory_seed
        goods_archetype : "produce_pile" | "pottery_stack" | "sack_cluster"
                          | "basket_group"
        base_color, produce_color, accent_color
    """

    def __init__(
        self,
        factory_seed,
        goods_archetype: str = "produce_pile",
        base_color: str | None = None,
        produce_color: str | None = None,
        accent_color: str | None = None,
        coarse: bool = False,
        **_unused_kwargs,
    ) -> None:
        super().__init__(factory_seed, coarse=coarse)
        if _unused_kwargs:
            from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
            accept_unused_kwargs("LowPolyMarketGoodsFactory", _unused_kwargs)
        if goods_archetype not in _GOODS_ARCHETYPES:
            import sys
            print(
                f"[goods_archetype] WARN: unknown {goods_archetype!r}; "
                f"falling back to {_GOODS_ARCHETYPES[0]!r}. Valid: {_GOODS_ARCHETYPES}",
                file=sys.stderr,
            )
            goods_archetype = _GOODS_ARCHETYPES[0]
        self.goods_archetype = goods_archetype
        _base, _produce, _accent = _ARCHETYPE_COLORS[goods_archetype]
        self.base_color = base_color or _base
        self.produce_color = produce_color or _produce
        self.accent_color = accent_color or _accent

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyMarketGoods({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        rng = random.Random(int(self.factory_seed) + 56131)
        builders = {
            "produce_pile": self._build_produce_pile,
            "pottery_stack": self._build_pottery_stack,
            "sack_cluster": self._build_sack_cluster,
            "basket_group": self._build_basket_group,
        }
        return builders[self.goods_archetype](rng)

    def _finalize(
        self, bm: bmesh.types.BMesh, slot_ranges: list[tuple[int, int, int]]
    ) -> bpy.types.Object:
        me = bpy.data.meshes.new(f"LowPolyMarketGoods({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()
        obj = bpy.data.objects.new(
            f"LowPolyMarketGoods({self.factory_seed})_{self.goods_archetype}", me
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
            obj, [self.base_color, self.produce_color, self.accent_color]
        )
        return obj

    # -- archetype builders ------------------------------------------------

    def _build_produce_pile(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        tray_w = rng.uniform(0.80, 1.00)
        tray_d = rng.uniform(0.60, 0.80)
        _add_box(bm, cx=0.0, cy=0.0, z0=0.0, sx=tray_w, sy=tray_d, sz=0.10,
                 slot=0, slot_ranges=sr)
        heap_r = min(tray_w, tray_d) * 0.42
        for i in range(rng.randint(14, 22)):
            t = rng.random()
            z = 0.12 + t * 0.28
            max_r = heap_r * (1.0 - t * 0.7)
            a = rng.uniform(0.0, 2.0 * math.pi)
            rr = max_r * math.sqrt(rng.uniform(0.0, 1.0))
            item_r = rng.uniform(0.08, 0.13)
            _add_icosphere_blob(
                bm, cx=rr * math.cos(a), cy=rr * math.sin(a), cz=z,
                sx=item_r, sy=item_r, sz=item_r * rng.uniform(0.85, 1.05),
                slot=1 if i % 2 == 0 else 2, slot_ranges=sr, rng=rng,
            )
        return self._finalize(bm, sr)

    def _build_pottery_stack(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        for _ in range(rng.randint(3, 6)):
            a = rng.uniform(0.0, 2.0 * math.pi)
            rr = rng.uniform(0.0, 0.55)
            cx, cy = rr * math.cos(a), rr * math.sin(a)
            radius = rng.uniform(0.14, 0.24)
            height = rng.uniform(0.30, 0.55)
            _add_cylinder(bm, cx=cx, cy=cy, z0=0.0, radius=radius, height=height,
                          n_sides=9, slot=0, slot_ranges=sr, top_scale=0.72)
            _add_cylinder(bm, cx=cx, cy=cy, z0=height - 0.03, radius=radius * 0.78,
                          height=0.06, n_sides=9, slot=2, slot_ranges=sr, top_scale=1.15)
        return self._finalize(bm, sr)

    def _build_sack_cluster(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        for i in range(rng.randint(3, 6)):
            a = rng.uniform(0.0, 2.0 * math.pi)
            rr = rng.uniform(0.0, 0.34)
            cx, cy = rr * math.cos(a), rr * math.sin(a)
            sack_w = rng.uniform(0.16, 0.24)
            sack_h = rng.uniform(0.40, 0.62)
            _add_icosphere_blob(
                bm, cx=cx, cy=cy, cz=sack_h * 0.5,
                sx=sack_w, sy=sack_w * rng.uniform(0.9, 1.1), sz=sack_h * 0.5,
                slot=0 if i % 2 == 0 else 1, slot_ranges=sr, rng=rng,
            )
            _add_cylinder(bm, cx=cx, cy=cy, z0=sack_h - 0.05, radius=sack_w * 0.4,
                          height=0.09, n_sides=6, slot=2, slot_ranges=sr, top_scale=0.65)
        return self._finalize(bm, sr)

    def _build_basket_group(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        for _ in range(rng.randint(2, 4)):
            a = rng.uniform(0.0, 2.0 * math.pi)
            rr = rng.uniform(0.0, 0.42)
            cx, cy = rr * math.cos(a), rr * math.sin(a)
            radius = rng.uniform(0.18, 0.28)
            height = rng.uniform(0.22, 0.38)
            _add_cylinder(bm, cx=cx, cy=cy, z0=0.0, radius=radius * 0.8, height=height,
                          n_sides=9, slot=0, slot_ranges=sr, top_scale=1.25,
                          cap_top=False)
            _add_cylinder(bm, cx=cx, cy=cy, z0=height - 0.04, radius=radius,
                          height=0.06, n_sides=9, slot=2, slot_ranges=sr, cap_top=False)
            if rng.random() < 0.6:
                for j in range(rng.randint(4, 8)):
                    ia = rng.uniform(0.0, 2.0 * math.pi)
                    irr = radius * rng.uniform(0.0, 0.6)
                    _add_icosphere_blob(
                        bm, cx=cx + irr * math.cos(ia), cy=cy + irr * math.sin(ia),
                        cz=height + rng.uniform(0.0, 0.09), sx=0.075, sy=0.075,
                        sz=0.07, slot=1 if j % 2 == 0 else 2, slot_ranges=sr, rng=rng,
                    )
        return self._finalize(bm, sr)

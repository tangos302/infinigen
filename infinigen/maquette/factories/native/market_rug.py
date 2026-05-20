"""LowPolyMarketRugFactory — bazaar ground rug with wares.

A ground-level dressing prop for an oasis bazaar. Bazaar trade happens
on rugs spread on the sand, not only at timber stalls. A scatter of
patterned rugs — some bare, some piled with goods — around the bazaar
tents turns "tents near a pool" into a readable marketplace floor.

Build approach: a thin flat rug slab a few centimetres above ground,
an optional raised border frame, and optional low goods piles (folded
cloth bolts, fruit baskets) as small boxes resting on the rug. All
axis-aligned, flat-shaded.

Archetypes:
  plain        — a single flat patterned rug. Default.
  bordered     — rug plus a raised border frame for a richer read.
  goods_pile   — bordered rug carrying 2-3 low piles of wares.

Material slots:
  slot 0 = rug field                       default `accent_red`
  slot 1 = border + goods piles            default `rock_warm`
"""

from __future__ import annotations

import random

import bmesh
import bpy

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_MARKET_RUG_ARCHETYPES = ("plain", "bordered", "goods_pile")


_ARCHETYPE_DEFAULTS = {
    "plain": dict(
        length=2.4, width=1.6, has_border=False, n_goods=0,
        field_color="accent_red", accent_color="rock_warm",
    ),
    "bordered": dict(
        length=2.6, width=1.8, has_border=True, n_goods=0,
        field_color="accent_red", accent_color="rock_warm",
    ),
    "goods_pile": dict(
        length=2.8, width=1.9, has_border=True, n_goods=3,
        field_color="accent_red", accent_color="rock_warm",
    ),
}


def _add_box(bm, center, size) -> tuple[int, int]:
    prev = len(bm.faces)
    res = bmesh.ops.create_cube(bm, size=1.0)
    cx, cy, cz = center
    sx, sy, sz = size
    for v in res["verts"]:
        v.co.x = v.co.x * sx + cx
        v.co.y = v.co.y * sy + cy
        v.co.z = v.co.z * sz + cz
    bm.faces.ensure_lookup_table()
    return prev, len(bm.faces)


class LowPolyMarketRugFactory(AssetFactory):
    """A low-poly bazaar ground rug, optionally bordered and laden with
    wares. Origin at the ground; the rug slab rests just above z=0.

    Constructor knobs:

        factory_seed
        market_rug_archetype : str = "plain"
                               "plain" | "bordered" | "goods_pile"
        length               : float  rug length along x (m)
        width                : float  rug width along y (m)
        has_border           : bool    add a raised border frame
        n_goods              : int     low goods piles resting on the rug
        field_color          : str     slot 0 palette key
        accent_color         : str     slot 1 palette key
    """

    def __init__(
        self,
        factory_seed,
        market_rug_archetype: str = "plain",
        length: float | None = None,
        width: float | None = None,
        has_border: bool | None = None,
        n_goods: int | None = None,
        field_color: str | None = None,
        accent_color: str | None = None,
        coarse: bool = False,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if market_rug_archetype not in _MARKET_RUG_ARCHETYPES:
            import sys
            print(
                f"[market_rug_archetype] WARN: unknown market_rug_archetype "
                f"{market_rug_archetype!r}; falling back to {_MARKET_RUG_ARCHETYPES[0]!r}. "
                f"Valid: {_MARKET_RUG_ARCHETYPES}",
                file=sys.stderr,
            )
            market_rug_archetype = _MARKET_RUG_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[market_rug_archetype]
        self.market_rug_archetype = market_rug_archetype
        self.length = float(length if length is not None else d["length"])
        self.width = float(width if width is not None else d["width"])
        self.has_border = bool(has_border if has_border is not None else d["has_border"])
        self.n_goods = int(n_goods if n_goods is not None else d["n_goods"])
        self.field_color = field_color or d["field_color"]
        self.accent_color = accent_color or d["accent_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyMarketRug({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        rng = random.Random(self.factory_seed)
        bm = bmesh.new()
        field_faces: list[tuple[int, int]] = []
        accent_faces: list[tuple[int, int]] = []

        hl, hw = self.length / 2.0, self.width / 2.0
        rug_t = 0.05
        # Rug field slab, resting just above the ground.
        field_faces.append(_add_box(bm, (0.0, 0.0, rug_t / 2.0), (self.length, self.width, rug_t)))

        if self.has_border:
            # A slightly taller border frame, slot 1.
            b = 0.18           # border band width
            bt = rug_t * 1.6   # border thickness
            bz = bt / 2.0
            accent_faces.append(_add_box(bm, (0.0, hw - b / 2.0, bz), (self.length, b, bt)))
            accent_faces.append(_add_box(bm, (0.0, -hw + b / 2.0, bz), (self.length, b, bt)))
            accent_faces.append(_add_box(bm, (hl - b / 2.0, 0.0, bz), (b, self.width, bt)))
            accent_faces.append(_add_box(bm, (-hl + b / 2.0, 0.0, bz), (b, self.width, bt)))

        # Low goods piles resting on the rug — stacked cloth bolts / baskets.
        for g in range(self.n_goods):
            t = (g + 0.5) / max(1, self.n_goods)
            gx = -hl * 0.55 + (self.length * 0.55) * t
            gy = rng.uniform(-hw * 0.35, hw * 0.35)
            pile_h = rng.uniform(0.22, 0.42)
            gw = rng.uniform(0.30, 0.46)
            accent_faces.append(_add_box(
                bm, (gx, gy, rug_t + pile_h / 2.0), (gw, gw * 0.8, pile_h)
            ))
            # A small second tier on roughly half the piles.
            if rng.random() < 0.5:
                accent_faces.append(_add_box(
                    bm, (gx, gy, rug_t + pile_h + 0.12), (gw * 0.7, gw * 0.55, 0.24)
                ))

        me = bpy.data.meshes.new(f"LowPolyMarketRug({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(f"LowPolyMarketRug({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)

        while len(obj.data.materials) < 2:
            obj.data.materials.append(None)
        for start, end in field_faces:
            for i in range(start, end):
                obj.data.polygons[i].material_index = 0
        for start, end in accent_faces:
            for i in range(start, end):
                obj.data.polygons[i].material_index = 1
        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(obj, [self.field_color, self.accent_color])
        return obj

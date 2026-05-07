"""LowPolyRockSpireFactory — tall narrow rock columns / spires / mesas.

Surfaced in Attempt 21 (Mad Max Citadel) — boulders scaled to tall
proportions go wide-flat, not tall-narrow. Need dedicated geometry.

Cross-prompt value: Mad Max citadel pillars, Monument Valley mesas,
canyon spires, fantasy wizard towers, lava pillars, geological
showcase rocks. Wherever the silhouette is a tall narrow geological
column.

Archetypes:
  needle    — narrow vertical column, sharp pointed top
              (sandstone spire / Devils Tower)
  mesa      — wide flat top, vertical sides, wider at the base
              (Monument Valley)
  citadel   — like needle but wider top (suitable for building
              shanties on); slight asymmetric bulges. Default for
              Mad Max.
  hoodoo    — narrow column with a wider "cap" rock on top
              (Bryce Canyon)

Build approach: stack of N hexagonal/octagonal layers (frustums)
stacked vertically with per-layer radius variation. Each layer
takes a small XY jitter so the column reads as eroded rock not
a smooth cylinder. Keeps polycount manageable — a 6-layer 8-sided
spire is ~120 faces.

Material slots:
  slot 0 = main rock body          (default `rock_warm` — sandstone)
  slot 1 = top cap / accent        (default `rock_shadow` — dark
                                    weathering at top)
"""

from __future__ import annotations

import math
import random

import bmesh
import bpy
from mathutils import Vector

from infinigen.core.placement.factory import AssetFactory

from ...density import (
    n_along_axis,
    n_sides_for_radius,
    target_edge_for_bbox,
)
from ...materials import apply_palette_slots


_SPIRE_ARCHETYPES = ("needle", "mesa", "citadel", "hoodoo")


# n_sides / n_layers are derived from bbox at instantiation time. Defaults
# here are dimensional + behavioral only.
_ARCHETYPE_DEFAULTS = {
    "needle": dict(
        height=18.0, base_radius=2.5, top_radius=0.6,
        layer_jitter=0.15, taper_curve=1.5,    # >1 = narrow faster at top
        has_cap=False, cap_radius=0.0, cap_height=0.0,
        pointed_top=True,
        rock_color="rock_warm", cap_color="rock_shadow",
    ),
    "mesa": dict(
        height=10.0, base_radius=5.0, top_radius=4.5,
        layer_jitter=0.1, taper_curve=0.8,
        has_cap=False, cap_radius=0.0, cap_height=0.0,
        pointed_top=False,
        rock_color="rock_warm", cap_color="rock_shadow",
    ),
    "citadel": dict(
        # Mad Max-style: tall + narrow but wider top so shanties can sit
        height=22.0, base_radius=3.5, top_radius=2.2,
        layer_jitter=0.2, taper_curve=0.6,
        has_cap=False, cap_radius=0.0, cap_height=0.0,
        pointed_top=False,
        rock_color="rock_warm", cap_color="rock_shadow",
    ),
    "hoodoo": dict(
        height=8.0, base_radius=1.0, top_radius=0.5,
        layer_jitter=0.10, taper_curve=1.2,
        has_cap=True, cap_radius=1.4, cap_height=0.7,
        pointed_top=False,
        rock_color="rock_warm", cap_color="rock_shadow",
    ),
}


def _bm_face_count(bm) -> int:
    return len(bm.faces)


def _build_spire(
    bm, slot_ranges, slot,
    height: float, base_radius: float, top_radius: float,
    n_sides: int, n_layers: int,
    layer_jitter: float, taper_curve: float,
    pointed_top: bool,
    rng: random.Random,
) -> Vector:
    """Stacked frustum spire. Returns top-center vertex position so
    callers can attach caps."""
    start = _bm_face_count(bm)
    rings: list[list] = []
    for L in range(n_layers + 1):
        t = L / n_layers
        # Radius interpolates non-linearly via taper_curve power
        r = base_radius + (top_radius - base_radius) * (t ** taper_curve)
        z = height * t
        ring = []
        # Per-ring small XY jitter that's consistent across all sides at
        # this height (to avoid scrambling the topology). Each ring gets
        # a different center offset so the spire reads as crooked.
        cx_off = rng.uniform(-layer_jitter, layer_jitter) * base_radius
        cy_off = rng.uniform(-layer_jitter, layer_jitter) * base_radius
        for s in range(n_sides):
            a = 2 * math.pi * s / n_sides
            # Per-vertex jitter on radius so each side varies
            r_jit = r * (1 + rng.uniform(-layer_jitter * 0.5, layer_jitter * 0.5))
            x = cx_off + r_jit * math.cos(a)
            y = cy_off + r_jit * math.sin(a)
            ring.append(bm.verts.new((x, y, z)))
        rings.append(ring)
    bm.verts.ensure_lookup_table()
    # Side faces between consecutive rings
    for L in range(n_layers):
        a_ring, b_ring = rings[L], rings[L + 1]
        for s in range(n_sides):
            ns = (s + 1) % n_sides
            bm.faces.new((a_ring[s], a_ring[ns], b_ring[ns], b_ring[s]))
    # Top — either pointed apex or flat n-gon
    top_ring = rings[-1]
    top_z = height
    if pointed_top:
        apex = bm.verts.new((0, 0, top_z + base_radius * 0.5))
        bm.verts.ensure_lookup_table()
        for s in range(n_sides):
            ns = (s + 1) % n_sides
            bm.faces.new((top_ring[s], top_ring[ns], apex))
    else:
        bm.faces.new(top_ring)
    # Bottom — flat n-gon
    bottom_ring = rings[0]
    bm.faces.new(list(reversed(bottom_ring)))
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))
    return Vector((0, 0, top_z))


def _build_cap(
    bm, slot_ranges, slot,
    top_pos: Vector, cap_radius: float, cap_height: float, n_sides: int,
) -> None:
    """Wider rock cap on top of a hoodoo spire — shorter cylinder of larger
    radius, sits on top of the spire."""
    start = _bm_face_count(bm)
    z0 = top_pos.z
    z1 = top_pos.z + cap_height
    bot, top = [], []
    for s in range(n_sides):
        a = 2 * math.pi * s / n_sides
        x = cap_radius * math.cos(a)
        y = cap_radius * math.sin(a)
        bot.append(bm.verts.new((x, y, z0)))
        top.append(bm.verts.new((x, y, z1)))
    bm.verts.ensure_lookup_table()
    for s in range(n_sides):
        ns = (s + 1) % n_sides
        bm.faces.new((bot[s], bot[ns], top[ns], top[s]))
    bm.faces.new(top)
    bm.faces.new(list(reversed(bot)))
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))


class LowPolyRockSpireFactory(AssetFactory):
    """A tall narrow rock column / spire / mesa. Geological hero feature
    for Mad Max citadel, Monument Valley, canyon scenes, wizard towers.

    Constructor knobs:

        factory_seed
        spire_archetype : str = "needle"
                          "needle" | "mesa" | "citadel" | "hoodoo"
        height           : float
        base_radius      : float
        top_radius       : float
        polygon_multiplier : float = 1.0   <1 = chunkier, >1 = denser
        target_edge        : float         absolute world-edge override
        n_sides          : int     hard override of derived count
        n_layers         : int     hard override of derived count
        layer_jitter     : float (0..1) per-vertex/ring radial jitter
        taper_curve      : float    >1 narrows faster at top
        has_cap          : bool    hoodoo cap rock
        cap_radius       : float
        cap_height       : float
        pointed_top      : bool    apex point (needle only)
        rock_color       : str     slot 0
        cap_color        : str     slot 1
    """

    def __init__(
        self,
        factory_seed,
        spire_archetype: str = "citadel",
        height: float | None = None,
        base_radius: float | None = None,
        top_radius: float | None = None,
        polygon_multiplier: float = 1.0,
        target_edge: float | None = None,
        n_sides: int | None = None,
        n_layers: int | None = None,
        layer_jitter: float | None = None,
        taper_curve: float | None = None,
        has_cap: bool | None = None,
        cap_radius: float | None = None,
        cap_height: float | None = None,
        pointed_top: bool | None = None,
        rock_color: str | None = None,
        cap_color: str | None = None,
        coarse: bool = False,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if spire_archetype not in _SPIRE_ARCHETYPES:
            # Lenient fallback rather than crash. Sonnet has been
            # observed to hallucinate plausible-sounding archetype
            # names despite the factories_guide brief listing the
            # valid set; killing a 6-minute build over a one-line
            # archetype typo wastes a generation. Substitute the
            # canonical default and warn to stderr.
            import sys
            print(
                f"[spire_archetype] WARN: unknown spire_archetype "
                f"{spire_archetype!r}; falling back to {_SPIRE_ARCHETYPES[0]!r}. "
                f"Valid: {_SPIRE_ARCHETYPES}",
                file=sys.stderr,
            )
            spire_archetype = _SPIRE_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[spire_archetype]
        self.spire_archetype = spire_archetype
        self.height = float(height if height is not None else d["height"])
        self.base_radius = float(base_radius if base_radius is not None else d["base_radius"])
        self.top_radius = float(top_radius if top_radius is not None else d["top_radius"])
        edge = (
            float(target_edge) if target_edge is not None
            else target_edge_for_bbox(
                (self.base_radius * 2, self.base_radius * 2, self.height),
                polygon_multiplier=polygon_multiplier,
            )
        )
        self.n_sides = int(
            n_sides if n_sides is not None
            else n_sides_for_radius(self.base_radius, edge)
        )
        self.n_layers = int(
            n_layers if n_layers is not None
            else n_along_axis(self.height, edge)
        )
        self.layer_jitter = float(layer_jitter if layer_jitter is not None else d["layer_jitter"])
        self.taper_curve = float(taper_curve if taper_curve is not None else d["taper_curve"])
        self.has_cap = (
            bool(has_cap) if has_cap is not None else d["has_cap"]
        )
        self.cap_radius = float(cap_radius if cap_radius is not None else d["cap_radius"])
        self.cap_height = float(cap_height if cap_height is not None else d["cap_height"])
        self.pointed_top = (
            bool(pointed_top) if pointed_top is not None else d["pointed_top"]
        )
        self.rock_color = rock_color or d["rock_color"]
        self.cap_color = cap_color or d["cap_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyRockSpire({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        rng = random.Random(self.factory_seed)
        bm = bmesh.new()
        slot_ranges: list[tuple[int, int, int]] = []

        top_pos = _build_spire(
            bm, slot_ranges, 0,
            self.height, self.base_radius, self.top_radius,
            self.n_sides, self.n_layers,
            self.layer_jitter, self.taper_curve,
            self.pointed_top, rng,
        )

        if self.has_cap and self.cap_radius > 0 and self.cap_height > 0:
            _build_cap(
                bm, slot_ranges, 1,
                top_pos, self.cap_radius, self.cap_height, self.n_sides,
            )

        me = bpy.data.meshes.new(f"LowPolyRockSpire({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(
            f"LowPolyRockSpire({self.factory_seed})", me
        )
        bpy.context.scene.collection.objects.link(obj)

        while len(obj.data.materials) < 2:
            obj.data.materials.append(None)

        for start, end, slot in slot_ranges:
            for i in range(start, end):
                obj.data.polygons[i].material_index = slot

        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(obj, [self.rock_color, self.cap_color])
        return obj

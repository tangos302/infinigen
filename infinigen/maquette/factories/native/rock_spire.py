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
    bm, slot_ranges, slot, base_slot,
    height: float, base_radius: float, top_radius: float,
    n_sides: int, n_layers: int,
    layer_jitter: float, taper_curve: float,
    pointed_top: bool, flat_plateau: bool,
    rng: random.Random,
) -> Vector:
    """Faceted-shell spire (Forge v2). The old smooth-ring build read as a
    stack of donuts; this one borrows the faceted-peak language from the
    terrain recipes:

      - per-SIDE radius multipliers frozen across strata, so the column
        gets vertical facet planes (half-space-intersection read)
      - few, unevenly spaced strata; at each break some panels re-roll and
        the band may flare into a ledge
      - per-stratum twist shear + a whole-column lean
      - the base band takes the accent slot so the foot reads shadowed

    Returns the top-center position so callers can attach caps."""
    n_sides = max(5, min(8, n_sides))
    n_layers = max(3, min(6, n_layers))
    jit = max(0.18, layer_jitter * 1.6)

    panel = [1.0 + rng.uniform(-jit, jit) for _ in range(n_sides)]
    lean_dir = rng.uniform(0, 2 * math.pi)
    lean_amt = rng.uniform(0.02, 0.10) * (0.3 if flat_plateau else 1.0)
    lx, ly = math.cos(lean_dir) * lean_amt, math.sin(lean_dir) * lean_amt

    # Uneven strata heights; the first stratum stays short so the dark
    # base band reads as a shadowed foot, not a planter pot.
    weights = [rng.uniform(0.6, 1.5) for _ in range(n_layers)]
    weights[0] *= 0.40
    total = sum(weights)
    layer_ts = [0.0]
    acc = 0.0
    for w in weights:
        acc += w / total
        layer_ts.append(min(1.0, acc))

    rings: list[list] = []
    twist = rng.uniform(0, math.pi / n_sides)
    ledge = 1.0
    for L, t in enumerate(layer_ts):
        if L > 0:
            # Strata break: shear a little, re-roll some facet panels, and
            # occasionally flare the band into a ledge.
            twist += rng.uniform(0.03, 0.14) * rng.choice((-1.0, 1.0))
            for s in range(n_sides):
                if rng.random() < 0.45:
                    panel[s] = 1.0 + rng.uniform(-jit, jit)
            ledge = 1.0 + (rng.uniform(0.06, 0.16) if rng.random() < 0.35 else 0.0)
        r = base_radius + (top_radius - base_radius) * (t ** taper_curve)
        r *= ledge
        z = height * t
        cx, cy = lx * z, ly * z
        ring = []
        for s in range(n_sides):
            a = twist + 2 * math.pi * s / n_sides
            r_s = max(r * panel[s], top_radius * 0.25)
            ring.append(bm.verts.new((cx + r_s * math.cos(a),
                                      cy + r_s * math.sin(a), z)))
        rings.append(ring)
    bm.verts.ensure_lookup_table()

    # Side faces, recorded per stratum so the base band can take the
    # accent slot (seed-gated — some spires stay uniform).
    use_base_band = rng.random() < 0.75
    for L in range(len(rings) - 1):
        seg_start = _bm_face_count(bm)
        a_ring, b_ring = rings[L], rings[L + 1]
        for s in range(n_sides):
            ns = (s + 1) % n_sides
            bm.faces.new((a_ring[s], a_ring[ns], b_ring[ns], b_ring[s]))
        slot_ranges.append((
            seg_start, _bm_face_count(bm),
            base_slot if (L == 0 and use_base_band) else slot,
        ))

    top_ring = rings[-1]
    top_z = height
    top_center = Vector((lx * top_z, ly * top_z, top_z))
    start = _bm_face_count(bm)
    if pointed_top:
        # Offset, slightly tilted apex — a centred cone tip reads machined.
        aa = rng.uniform(0, 2 * math.pi)
        ar = top_radius * rng.uniform(0.2, 0.45)
        apex = bm.verts.new((top_center.x + math.cos(aa) * ar,
                             top_center.y + math.sin(aa) * ar,
                             top_z + base_radius * rng.uniform(0.35, 0.6)))
        bm.verts.ensure_lookup_table()
        for s in range(n_sides):
            ns = (s + 1) % n_sides
            bm.faces.new((top_ring[s], top_ring[ns], apex))
    elif flat_plateau:
        bm.faces.new(top_ring)
    else:
        # Crowned irregular top: fan to an off-centre point just above.
        aa = rng.uniform(0, 2 * math.pi)
        ar = top_radius * rng.uniform(0.15, 0.35)
        crown = bm.verts.new((top_center.x + math.cos(aa) * ar,
                              top_center.y + math.sin(aa) * ar,
                              top_z + top_radius * rng.uniform(0.10, 0.22)))
        bm.verts.ensure_lookup_table()
        for s in range(n_sides):
            ns = (s + 1) % n_sides
            bm.faces.new((top_ring[s], top_ring[ns], crown))
    bottom_ring = rings[0]
    bm.faces.new(list(reversed(bottom_ring)))
    slot_ranges.append((start, _bm_face_count(bm), slot))
    return top_center


def _build_cap(
    bm, slot_ranges, slot,
    top_pos: Vector, cap_radius: float, cap_height: float, n_sides: int,
    rng: random.Random,
) -> None:
    """Hoodoo caprock — a faceted lozenge (widest at mid-height) instead of
    the old straight cylinder, with per-vertex jitter so it reads as a
    perched boulder."""
    n_sides = max(5, min(8, n_sides))
    start = _bm_face_count(bm)
    z0 = top_pos.z - cap_height * 0.12  # sink slightly into the column
    levels = (
        (z0, cap_radius * 0.55),
        (z0 + cap_height * 0.45, cap_radius),
        (z0 + cap_height, cap_radius * 0.5),
    )
    twist = rng.uniform(0, math.pi / n_sides)
    rings = []
    for z, r in levels:
        ring = []
        for s in range(n_sides):
            a = twist + 2 * math.pi * s / n_sides
            r_s = r * (1 + rng.uniform(-0.18, 0.18))
            ring.append(bm.verts.new((top_pos.x + r_s * math.cos(a),
                                      top_pos.y + r_s * math.sin(a), z)))
        rings.append(ring)
    bm.verts.ensure_lookup_table()
    for r0, r1 in zip(rings, rings[1:]):
        for s in range(n_sides):
            ns = (s + 1) % n_sides
            bm.faces.new((r0[s], r0[ns], r1[ns], r1[s]))
    bm.faces.new(rings[-1])
    bm.faces.new(list(reversed(rings[0])))
    slot_ranges.append((start, _bm_face_count(bm), slot))


def _add_talus(
    bm, slot_ranges, slot,
    base_radius: float, rng: random.Random,
) -> None:
    """A few half-buried rubble blocks around the foot of the spire —
    yaw-rotated boxes with squashed proportions."""
    for _ in range(rng.randint(2, 4)):
        a = rng.uniform(0, 2 * math.pi)
        dist = base_radius * rng.uniform(1.15, 1.55)
        cx, cy = dist * math.cos(a), dist * math.sin(a)
        sx = base_radius * rng.uniform(0.28, 0.50)
        sy = sx * rng.uniform(0.6, 1.1)
        sz = sx * rng.uniform(0.45, 0.8)
        yaw = rng.uniform(0, math.pi)
        ca, sa = math.cos(yaw), math.sin(yaw)
        start = _bm_face_count(bm)
        corners = []
        for dz in (-0.4, 1.0):
            for dx, dy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                x = dx * sx / 2
                y = dy * sy / 2
                corners.append(bm.verts.new((
                    cx + x * ca - y * sa,
                    cy + x * sa + y * ca,
                    sz * dz * 0.5 + sz * 0.25,
                )))
        bm.verts.ensure_lookup_table()
        b, t = corners[:4], corners[4:]
        for i in range(4):
            ni = (i + 1) % 4
            bm.faces.new((b[i], b[ni], t[ni], t[i]))
        bm.faces.new(tuple(t))
        bm.faces.new(tuple(reversed(b)))
        slot_ranges.append((start, _bm_face_count(bm), slot))


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
        **_unused_kwargs,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if _unused_kwargs:
            from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
            accept_unused_kwargs("LowPolyRockSpireFactory", _unused_kwargs)
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

        flat_plateau = self.spire_archetype == "mesa"
        top_pos = _build_spire(
            bm, slot_ranges, 0, 1,
            self.height, self.base_radius, self.top_radius,
            self.n_sides, self.n_layers,
            self.layer_jitter, self.taper_curve,
            self.pointed_top, flat_plateau, rng,
        )

        if self.has_cap and self.cap_radius > 0 and self.cap_height > 0:
            _build_cap(
                bm, slot_ranges, 1,
                top_pos, self.cap_radius, self.cap_height, self.n_sides,
                rng,
            )

        # Rubble at the foot grounds the column (skip for hoodoos — they
        # stand on smooth badland floors).
        if self.spire_archetype != "hoodoo":
            _add_talus(bm, slot_ranges, 1, self.base_radius, rng)

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

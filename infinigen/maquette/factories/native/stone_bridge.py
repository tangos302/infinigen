"""LowPolyStoneBridgeFactory — stone arch bridge.

The current deck/boardwalk factory is excellent for wooden docks, but
medieval towns, castle approaches, rivers, and old roads need a heavier
stone bridge silhouette. This factory authors the readable pieces:
abutments, piers, an elevated road deck, parapets, and visible arch
voussoirs on both sides.

Archetypes:
  single_arch  — one wide span, village road / small river.
  double_arch  — two lower spans with a central pier.
  ruined_arch  — broken parapet, missing stones, irregular rubble.

Material slots:
  slot 0 = stone body / piers
  slot 1 = road cap / parapet cap
  slot 2 = dark arch shadow
  slot 3 = loose rubble / accent stones
"""

from __future__ import annotations

import math
import random

import bmesh
import bpy
from mathutils import Vector

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_STONE_BRIDGE_ARCHETYPES = ("single_arch", "double_arch", "ruined_arch")

_ARCHETYPE_DEFAULTS = {
    "single_arch": dict(
        length=8.8,
        width=2.45,
        deck_z=1.55,
        arch_radius=2.25,
        arch_count=1,
        stone_color="rock_pale",
        cap_color="rock_warm",
        shadow_color="rock_shadow",
        rubble_color="rock_cool",
    ),
    "double_arch": dict(
        length=11.2,
        width=2.65,
        deck_z=1.45,
        arch_radius=1.72,
        arch_count=2,
        stone_color="rock_cool",
        cap_color="rock_pale",
        shadow_color="rock_shadow",
        rubble_color="rock_warm",
    ),
    "ruined_arch": dict(
        length=8.2,
        width=2.25,
        deck_z=1.36,
        arch_radius=1.95,
        arch_count=1,
        stone_color="rock_warm",
        cap_color="rock_pale",
        shadow_color="rock_shadow",
        rubble_color="rock_pale",
    ),
}


def _face_count(bm: bmesh.types.BMesh) -> int:
    return len(bm.faces)


def _add_oriented_box(
    bm: bmesh.types.BMesh,
    slot_ranges: list[tuple[int, int, int]],
    slot: int,
    center: Vector,
    axis_a: Vector,
    axis_b: Vector,
    axis_c: Vector,
) -> None:
    start = _face_count(bm)
    verts = []
    for sa, sb, sc in (
        (-1, -1, -1),
        (1, -1, -1),
        (1, 1, -1),
        (-1, 1, -1),
        (-1, -1, 1),
        (1, -1, 1),
        (1, 1, 1),
        (-1, 1, 1),
    ):
        p = center + axis_a * sa + axis_b * sb + axis_c * sc
        verts.append(bm.verts.new((p.x, p.y, p.z)))
    bm.verts.ensure_lookup_table()
    b00, b10, b11, b01, t00, t10, t11, t01 = verts
    bm.faces.new((b00, b10, t10, t00))
    bm.faces.new((b10, b11, t11, t10))
    bm.faces.new((b11, b01, t01, t11))
    bm.faces.new((b01, b00, t00, t01))
    bm.faces.new((t00, t10, t11, t01))
    bm.faces.new((b00, b01, b11, b10))
    slot_ranges.append((start, _face_count(bm), int(slot)))


def _add_box(
    bm: bmesh.types.BMesh,
    slot_ranges: list[tuple[int, int, int]],
    slot: int,
    center: tuple[float, float, float],
    size: tuple[float, float, float],
) -> None:
    cx, cy, cz = center
    sx, sy, sz = size
    _add_oriented_box(
        bm,
        slot_ranges,
        slot,
        Vector((cx, cy, cz)),
        Vector((sx * 0.5, 0.0, 0.0)),
        Vector((0.0, sy * 0.5, 0.0)),
        Vector((0.0, 0.0, sz * 0.5)),
    )


def _add_arch_blocks(
    bm: bmesh.types.BMesh,
    slot_ranges: list[tuple[int, int, int]],
    *,
    center_x: float,
    y: float,
    base_z: float,
    radius: float,
    side_thickness: float,
    slot: int,
    rng: random.Random,
    ruined: bool,
) -> None:
    # Visible voussoirs: a semicircular necklace of blocks on one side.
    n = 11
    for i in range(n):
        if ruined and i in {1, 8} and rng.random() < 0.8:
            continue
        a = math.pi * (i + 0.5) / n
        tangent = Vector((-math.sin(a), 0.0, math.cos(a)))
        radial = Vector((math.cos(a), 0.0, math.sin(a)))
        center = Vector((
            center_x + radius * math.cos(a),
            y,
            base_z + radius * math.sin(a),
        ))
        block_len = radius * math.pi / n * 0.80
        _add_oriented_box(
            bm,
            slot_ranges,
            slot,
            center,
            tangent * (block_len * 0.5),
            Vector((0.0, side_thickness * 0.5, 0.0)),
            radial * 0.17,
        )


class LowPolyStoneBridgeFactory(AssetFactory):
    """Low-poly stone road bridge with explicit arch stones.

    Constructor knobs:
        factory_seed
        stone_bridge_archetype : "single_arch" | "double_arch" | "ruined_arch"
        length, width, deck_z, arch_radius, arch_count
        stone_color, cap_color, shadow_color, rubble_color
    """

    def __init__(
        self,
        factory_seed,
        stone_bridge_archetype: str = "single_arch",
        length: float | None = None,
        width: float | None = None,
        deck_z: float | None = None,
        arch_radius: float | None = None,
        arch_count: int | None = None,
        stone_color: str | None = None,
        cap_color: str | None = None,
        shadow_color: str | None = None,
        rubble_color: str | None = None,
        coarse: bool = False,
        **_unused_kwargs,
    ) -> None:
        super().__init__(factory_seed, coarse=coarse)
        if _unused_kwargs:
            from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
            accept_unused_kwargs("LowPolyStoneBridgeFactory", _unused_kwargs)
        if stone_bridge_archetype not in _STONE_BRIDGE_ARCHETYPES:
            import sys
            print(
                f"[stone_bridge_archetype] WARN: unknown {stone_bridge_archetype!r}; "
                f"falling back to {_STONE_BRIDGE_ARCHETYPES[0]!r}. "
                f"Valid: {_STONE_BRIDGE_ARCHETYPES}",
                file=sys.stderr,
            )
            stone_bridge_archetype = _STONE_BRIDGE_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[stone_bridge_archetype]
        self.stone_bridge_archetype = stone_bridge_archetype
        self.length = float(length if length is not None else d["length"])
        self.width = float(width if width is not None else d["width"])
        self.deck_z = float(deck_z if deck_z is not None else d["deck_z"])
        self.arch_radius = float(arch_radius if arch_radius is not None else d["arch_radius"])
        self.arch_count = int(arch_count if arch_count is not None else d["arch_count"])
        self.stone_color = stone_color or d["stone_color"]
        self.cap_color = cap_color or d["cap_color"]
        self.shadow_color = shadow_color or d["shadow_color"]
        self.rubble_color = rubble_color or d["rubble_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(f"LowPolyStoneBridge({self.factory_seed})_placeholder", None)
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        rng = random.Random(int(self.factory_seed))
        bm = bmesh.new()
        slot_ranges: list[tuple[int, int, int]] = []
        ruined = self.stone_bridge_archetype == "ruined_arch"

        L, W, dz = self.length, self.width, self.deck_z
        # Road/deck and side parapets.
        _add_box(bm, slot_ranges, 0, (0.0, 0.0, dz - 0.18), (L, W, 0.36))
        _add_box(bm, slot_ranges, 1, (0.0, 0.0, dz + 0.05), (L * 0.94, W * 0.62, 0.10))
        parapet_len = L * (0.80 if ruined else 1.0)
        for side in (-1, 1):
            y = side * (W * 0.5 + 0.08)
            _add_box(bm, slot_ranges, 0, (0.0, y, dz + 0.33), (parapet_len, 0.22, 0.66))
            _add_box(bm, slot_ranges, 1, (0.0, y, dz + 0.72), (parapet_len, 0.30, 0.12))

        # End abutments and pier(s).
        _add_box(bm, slot_ranges, 0, (-L * 0.48, 0.0, dz * 0.42), (0.62, W * 1.12, dz * 0.84))
        _add_box(bm, slot_ranges, 0, (L * 0.48, 0.0, dz * 0.42), (0.62, W * 1.12, dz * 0.84))
        if self.arch_count >= 2:
            _add_box(bm, slot_ranges, 0, (0.0, 0.0, dz * 0.42), (0.56, W * 1.08, dz * 0.84))

        # Dark panels behind each arch opening make the arch cut read even
        # though this is a low-poly additive mesh.
        centers = [0.0]
        if self.arch_count >= 2:
            centers = [-L * 0.235, L * 0.235]
        for cx in centers:
            _add_box(
                bm,
                slot_ranges,
                2,
                (cx, -W * 0.5 - 0.025, dz * 0.48),
                (self.arch_radius * 1.55, 0.035, dz * 0.88),
            )
            _add_box(
                bm,
                slot_ranges,
                2,
                (cx, W * 0.5 + 0.025, dz * 0.48),
                (self.arch_radius * 1.55, 0.035, dz * 0.88),
            )
            for side in (-1, 1):
                _add_arch_blocks(
                    bm,
                    slot_ranges,
                    center_x=cx,
                    y=side * (W * 0.5 + 0.16),
                    base_z=0.10,
                    radius=self.arch_radius,
                    side_thickness=0.28,
                    slot=0,
                    rng=rng,
                    ruined=ruined,
                )

        if ruined:
            # Missing parapet chunks and loose stones at the approaches.
            for _ in range(14):
                sx = rng.uniform(0.22, 0.62)
                sy = rng.uniform(0.18, 0.48)
                sz = rng.uniform(0.12, 0.32)
                x = rng.choice((-1, 1)) * rng.uniform(L * 0.35, L * 0.58)
                y = rng.uniform(-W * 0.72, W * 0.72)
                _add_box(bm, slot_ranges, 3, (x, y, sz * 0.5), (sx, sy, sz))

        me = bpy.data.meshes.new(f"LowPolyStoneBridge({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()
        obj = bpy.data.objects.new(f"LowPolyStoneBridge({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)

        while len(obj.data.materials) < 4:
            obj.data.materials.append(None)
        for start, end, slot in slot_ranges:
            for i in range(start, end):
                obj.data.polygons[i].material_index = slot
        for poly in obj.data.polygons:
            poly.use_smooth = False
        apply_palette_slots(
            obj,
            [self.stone_color, self.cap_color, self.shadow_color, self.rubble_color],
        )
        return obj

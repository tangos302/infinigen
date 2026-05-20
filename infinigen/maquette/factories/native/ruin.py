"""LowPolyRuinFactory — modular ruin fragments.

This is the catch-all ruin kit for prompts requesting old ruins,
buried structures, broken arches, obelisks, collapsed walls, or desert
temple fragments. It is intentionally a cluster factory: one spawned
object should already read as a small ruin vignette, while multiple
spawns can form a larger archaeological site.

Archetypes:
  broken_walls     — collapsed wall corners and rubble.
  column_scatter   — standing and broken columns.
  archway          — two piers with a broken stone arch.
  obelisk_fragment — snapped obelisk and base blocks.

Material slots:
  slot 0 = main stone
  slot 1 = shadow/worn sides
  slot 2 = accent cap / carved pieces
"""

from __future__ import annotations

import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_RUIN_ARCHETYPES = ("broken_walls", "column_scatter", "archway", "obelisk_fragment")

_ARCHETYPE_DEFAULTS = {
    "broken_walls": dict(
        radius=3.8,
        density=1.0,
        stone_color="rock_warm",
        shadow_color="rock_shadow",
        accent_color="rock_pale",
    ),
    "column_scatter": dict(
        radius=3.5,
        density=1.0,
        stone_color="rock_pale",
        shadow_color="rock_cool",
        accent_color="rock_warm",
    ),
    "archway": dict(
        radius=3.2,
        density=1.0,
        stone_color="rock_warm",
        shadow_color="rock_shadow",
        accent_color="rock_pale",
    ),
    "obelisk_fragment": dict(
        radius=3.2,
        density=1.0,
        stone_color="rock_pale",
        shadow_color="rock_shadow",
        accent_color="rock_warm",
    ),
}


def _face_count(bm: bmesh.types.BMesh) -> int:
    return len(bm.faces)


def _add_box(
    bm: bmesh.types.BMesh,
    slot_ranges: list[tuple[int, int, int]],
    slot: int,
    center: tuple[float, float, float],
    size: tuple[float, float, float],
    rot_z: float = 0.0,
) -> None:
    start = _face_count(bm)
    cx, cy, cz = center
    sx, sy, sz = size
    hx, hy, hz = sx * 0.5, sy * 0.5, sz * 0.5
    rot = Matrix.Rotation(float(rot_z), 4, "Z")
    verts = []
    for x, y, z in (
        (-hx, -hy, -hz),
        (hx, -hy, -hz),
        (hx, hy, -hz),
        (-hx, hy, -hz),
        (-hx, -hy, hz),
        (hx, -hy, hz),
        (hx, hy, hz),
        (-hx, hy, hz),
    ):
        p = Vector((cx, cy, cz)) + (rot @ Vector((x, y, z)))
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


def _add_prism(
    bm: bmesh.types.BMesh,
    slot_ranges: list[tuple[int, int, int]],
    slot: int,
    *,
    center: tuple[float, float, float],
    radius: float,
    height: float,
    sides: int,
    scale_y: float = 1.0,
    rot_z: float = 0.0,
) -> None:
    start = _face_count(bm)
    cx, cy, cz = center
    bottom = []
    top = []
    rot = Matrix.Rotation(float(rot_z), 4, "Z")
    for i in range(int(sides)):
        a = 2.0 * math.pi * i / int(sides)
        local = Vector((radius * math.cos(a), radius * scale_y * math.sin(a), 0.0))
        p = Vector((cx, cy, cz - height * 0.5)) + (rot @ local)
        bottom.append(bm.verts.new((p.x, p.y, p.z)))
        top.append(bm.verts.new((p.x, p.y, p.z + height)))
    bm.verts.ensure_lookup_table()
    for i in range(int(sides)):
        ni = (i + 1) % int(sides)
        bm.faces.new((bottom[i], bottom[ni], top[ni], top[i]))
    bm.faces.new(list(reversed(bottom)))
    bm.faces.new(top)
    slot_ranges.append((start, _face_count(bm), int(slot)))


def _add_arch(
    bm: bmesh.types.BMesh,
    slot_ranges: list[tuple[int, int, int]],
    *,
    span: float,
    base_z: float,
    center_y: float,
    rng: random.Random,
) -> None:
    # Two piers.
    for x in (-span * 0.5, span * 0.5):
        _add_box(bm, slot_ranges, 0, (x, center_y, base_z + 0.95), (0.42, 0.58, 1.9))
        _add_box(bm, slot_ranges, 2, (x, center_y, base_z + 1.95), (0.62, 0.68, 0.18))
    # Voussoirs.
    radius = span * 0.5
    n = 9
    for i in range(n):
        if i in {1, 7} and rng.random() < 0.50:
            continue
        a = math.pi * (i + 0.5) / n
        x = radius * math.cos(a)
        z = base_z + 1.92 + radius * math.sin(a)
        _add_box(
            bm,
            slot_ranges,
            0,
            (x, center_y, z),
            (0.34, 0.72, 0.30),
            rot_z=-a + math.pi * 0.5,
        )


class LowPolyRuinFactory(AssetFactory):
    """Clustered ruin vignette.

    Constructor knobs:
        factory_seed
        ruin_archetype : "broken_walls" | "column_scatter" | "archway" | "obelisk_fragment"
        radius, density
        stone_color, shadow_color, accent_color
    """

    def __init__(
        self,
        factory_seed,
        ruin_archetype: str = "broken_walls",
        radius: float | None = None,
        density: float | None = None,
        stone_color: str | None = None,
        shadow_color: str | None = None,
        accent_color: str | None = None,
        coarse: bool = False,
        **_unused_kwargs,
    ) -> None:
        super().__init__(factory_seed, coarse=coarse)
        if _unused_kwargs:
            from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
            accept_unused_kwargs("LowPolyRuinFactory", _unused_kwargs)
        if ruin_archetype not in _RUIN_ARCHETYPES:
            import sys
            print(
                f"[ruin_archetype] WARN: unknown {ruin_archetype!r}; "
                f"falling back to {_RUIN_ARCHETYPES[0]!r}. "
                f"Valid: {_RUIN_ARCHETYPES}",
                file=sys.stderr,
            )
            ruin_archetype = _RUIN_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[ruin_archetype]
        self.ruin_archetype = ruin_archetype
        self.radius = float(radius if radius is not None else d["radius"])
        self.density = float(density if density is not None else d["density"])
        self.stone_color = stone_color or d["stone_color"]
        self.shadow_color = shadow_color or d["shadow_color"]
        self.accent_color = accent_color or d["accent_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(f"LowPolyRuin({self.factory_seed})_placeholder", None)
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _add_rubble(self, bm, slot_ranges, rng, count: int) -> None:
        for _ in range(int(count * self.density)):
            r = rng.uniform(self.radius * 0.12, self.radius)
            a = rng.uniform(0.0, math.tau)
            sx = rng.uniform(0.16, 0.62)
            sy = rng.uniform(0.14, 0.48)
            sz = rng.uniform(0.08, 0.30)
            _add_box(
                bm,
                slot_ranges,
                rng.choice((0, 1, 2)),
                (r * math.cos(a), r * math.sin(a), sz * 0.5),
                (sx, sy, sz),
                rot_z=rng.uniform(0.0, math.tau),
            )

    def _build(self) -> bpy.types.Object:
        rng = random.Random(int(self.factory_seed))
        bm = bmesh.new()
        slot_ranges: list[tuple[int, int, int]] = []

        if self.ruin_archetype == "broken_walls":
            # Broken L-corner wall, built from stepped chunks with real
            # height changes instead of one clean rectangle.
            wall_a = [
                (-1.95, 0.58, 1.28),
                (-1.12, 0.72, 1.72),
                (-0.18, 0.82, 1.42),
                (0.82, 0.62, 0.94),
            ]
            for x, length, height in wall_a:
                _add_box(
                    bm,
                    slot_ranges,
                    0,
                    (x, -1.1, height * 0.5),
                    (length, 0.38, height),
                    rot_z=0.10,
                )
                if height > 1.2:
                    _add_box(
                        bm,
                        slot_ranges,
                        2,
                        (x, -1.1, height + 0.09),
                        (length * 0.72, 0.46, 0.18),
                        rot_z=0.10,
                    )
            wall_b = [
                (-0.78, 0.74, 0.92),
                (0.12, 0.72, 1.38),
                (1.02, 0.58, 1.05),
            ]
            for y, length, height in wall_b:
                _add_box(
                    bm,
                    slot_ranges,
                    0,
                    (1.15, y, height * 0.5),
                    (0.38, length, height),
                    rot_z=-0.06,
                )
            # One dark missing-window panel sells "habitable ruin" at
            # scene-camera distance.
            _add_box(bm, slot_ranges, 1, (-1.10, -1.32, 0.92), (0.34, 0.06, 0.64), rot_z=0.10)
            self._add_rubble(bm, slot_ranges, rng, 20)
        elif self.ruin_archetype == "column_scatter":
            for x, y, h in [(-1.2, -0.8, 2.2), (0.2, -1.0, 1.45), (1.25, 0.4, 2.0), (-0.7, 0.9, 0.85)]:
                _add_prism(
                    bm,
                    slot_ranges,
                    0,
                    center=(x, y, h * 0.5),
                    radius=0.22,
                    height=h,
                    sides=8,
                    scale_y=0.88,
                    rot_z=rng.uniform(0.0, math.tau),
                )
                _add_box(bm, slot_ranges, 2, (x, y, h + 0.10), (0.55, 0.55, 0.16), rot_z=rng.uniform(0.0, math.tau))
            _add_box(bm, slot_ranges, 1, (0.55, 1.25, 0.18), (1.45, 0.32, 0.32), rot_z=0.65)
            self._add_rubble(bm, slot_ranges, rng, 18)
        elif self.ruin_archetype == "archway":
            _add_arch(bm, slot_ranges, span=2.2, base_z=0.0, center_y=0.0, rng=rng)
            _add_box(bm, slot_ranges, 0, (-1.65, 0.0, 0.62), (1.30, 0.42, 1.24), rot_z=0.08)
            _add_box(bm, slot_ranges, 0, (1.65, 0.0, 0.52), (1.05, 0.42, 1.04), rot_z=-0.08)
            self._add_rubble(bm, slot_ranges, rng, 16)
        else:
            # Snapped obelisk: upright stump + fallen tapered shard.
            _add_prism(
                bm,
                slot_ranges,
                0,
                center=(-0.65, -0.1, 1.05),
                radius=0.40,
                height=2.10,
                sides=4,
                scale_y=0.88,
                rot_z=math.radians(45),
            )
            _add_prism(
                bm,
                slot_ranges,
                2,
                center=(-0.65, -0.1, 2.35),
                radius=0.29,
                height=0.48,
                sides=4,
                scale_y=0.88,
                rot_z=math.radians(45),
            )
            _add_box(bm, slot_ranges, 0, (0.85, 0.45, 0.28), (1.85, 0.48, 0.36), rot_z=-0.42)
            _add_box(bm, slot_ranges, 2, (-0.65, -0.1, 0.12), (1.00, 1.00, 0.24), rot_z=math.radians(45))
            self._add_rubble(bm, slot_ranges, rng, 22)

        me = bpy.data.meshes.new(f"LowPolyRuin({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()
        obj = bpy.data.objects.new(f"LowPolyRuin({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)

        while len(obj.data.materials) < 3:
            obj.data.materials.append(None)
        for start, end, slot in slot_ranges:
            for i in range(start, end):
                obj.data.polygons[i].material_index = slot
        for poly in obj.data.polygons:
            poly.use_smooth = False
        apply_palette_slots(obj, [self.stone_color, self.shadow_color, self.accent_color])
        return obj

"""LowPolyTownGateFactory — readable settlement entrance.

Roads currently run into towns without a threshold object, so settlement
edges feel unfinished. This factory makes a road entrance: timber posts,
palisade doors, stone arch, or a watch-gate with a small roofed platform.

Archetypes:
  timber_palisade  — rural gate with pointed stakes and cross beam.
  stone_arch       — masonry road arch with keystone blocks.
  watch_gate       — gate plus raised timber watch platform and roof.
  ruined_gate      — broken side piers and fallen gate planks.

Material slots:
  slot 0 = stone / main body
  slot 1 = wood / doors / roof
  slot 2 = metal / dark accents
"""

from __future__ import annotations

import random

import bmesh
import bpy

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_TOWN_GATE_ARCHETYPES = ("timber_palisade", "stone_arch", "watch_gate", "ruined_gate")

_ARCHETYPE_DEFAULTS = {
    "timber_palisade": dict(span=3.7, height=3.3, width=1.0, roof=False, stone=False, ruined=0.0),
    "stone_arch": dict(span=3.5, height=3.7, width=1.15, roof=False, stone=True, ruined=0.0),
    "watch_gate": dict(span=4.0, height=4.2, width=1.25, roof=True, stone=False, ruined=0.0),
    "ruined_gate": dict(span=3.6, height=2.6, width=1.05, roof=False, stone=True, ruined=0.52),
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


def _add_roof(
    bm: bmesh.types.BMesh,
    ranges: list[tuple[int, int, int]],
    *,
    z: float,
    span: float,
    depth: float,
    height: float,
) -> None:
    start = _face_count(bm)
    hx = span * 0.5
    hy = depth * 0.5
    south0 = bm.verts.new((-hx, -hy, z))
    south1 = bm.verts.new((hx, -hy, z))
    north1 = bm.verts.new((hx, hy, z))
    north0 = bm.verts.new((-hx, hy, z))
    ridge0 = bm.verts.new((-hx, 0.0, z + height))
    ridge1 = bm.verts.new((hx, 0.0, z + height))
    bm.verts.ensure_lookup_table()
    bm.faces.new((south0, south1, ridge1, ridge0))
    bm.faces.new((north1, north0, ridge0, ridge1))
    bm.faces.new((south0, ridge0, north0))
    bm.faces.new((south1, north1, ridge1))
    ranges.append((start, _face_count(bm), 1))


class LowPolyTownGateFactory(AssetFactory):
    """Low-poly entry gate for towns, castles, and roads.

    Constructor knobs:
        factory_seed
        town_gate_archetype : "timber_palisade" | "stone_arch" | "watch_gate" | "ruined_gate"
        span, height, width
        roof
        stone
        ruined
        stone_color, wood_color, metal_color
    """

    def __init__(
        self,
        factory_seed,
        town_gate_archetype: str = "timber_palisade",
        span: float | None = None,
        height: float | None = None,
        width: float | None = None,
        roof: bool | None = None,
        stone: bool | None = None,
        ruined: float | None = None,
        stone_color: str = "rock_pale",
        wood_color: str = "wood",
        metal_color: str = "rust_metal",
        coarse: bool = False,
        **_unused_kwargs,
    ) -> None:
        super().__init__(factory_seed, coarse=coarse)
        if _unused_kwargs:
            from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
            accept_unused_kwargs("LowPolyTownGateFactory", _unused_kwargs)
        if town_gate_archetype not in _TOWN_GATE_ARCHETYPES:
            import sys
            print(
                f"[town_gate_archetype] WARN: unknown {town_gate_archetype!r}; "
                f"falling back to {_TOWN_GATE_ARCHETYPES[0]!r}. Valid: {_TOWN_GATE_ARCHETYPES}",
                file=sys.stderr,
            )
            town_gate_archetype = _TOWN_GATE_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[town_gate_archetype]
        self.town_gate_archetype = town_gate_archetype
        self.span = float(span if span is not None else d["span"])
        self.height = float(height if height is not None else d["height"])
        self.width = float(width if width is not None else d["width"])
        self.roof = bool(roof if roof is not None else d["roof"])
        self.stone = bool(stone if stone is not None else d["stone"])
        self.ruined = max(0.0, min(0.85, float(ruined if ruined is not None else d["ruined"])))
        self.stone_color = stone_color
        self.wood_color = wood_color
        self.metal_color = metal_color

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(f"LowPolyTownGate({self.factory_seed})_placeholder", None)
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        rng = random.Random(self.factory_seed)
        bm = bmesh.new()
        ranges: list[tuple[int, int, int]] = []
        slot_main = 0 if self.stone else 1
        side_gap = self.span * 0.5 + self.width * 0.34
        pier_w = self.width * 0.56
        pier_h = self.height * (0.75 if self.town_gate_archetype == "ruined_gate" else 1.0)

        for sign in (-1.0, 1.0):
            h = pier_h * (rng.uniform(0.66, 1.0) if rng.random() < self.ruined else 1.0)
            _add_box(bm, ranges, slot_main, (sign * side_gap, 0.0, h * 0.5), (pier_w, self.width, h))
            if not self.stone:
                # Pointed palisade caps.
                _add_box(bm, ranges, 1, (sign * side_gap, 0.0, h + 0.18), (pier_w * 0.72, self.width * 0.72, 0.36))

        # Lintel / arch top. Ruined gates may only keep one broken beam.
        if self.stone:
            if self.ruined < 0.5 or rng.random() > 0.35:
                _add_box(
                    bm,
                    ranges,
                    0,
                    (0.0, 0.0, self.height * 0.83),
                    (self.span + pier_w * 1.8, self.width * 1.04, self.height * 0.18),
                )
            # Keystone blocks along arch top.
            for i in range(5):
                x = -self.span * 0.34 + i * self.span * 0.17
                if rng.random() < self.ruined * 0.45:
                    continue
                _add_box(bm, ranges, 2, (x, -self.width * 0.54, self.height * 0.72), (0.26, 0.10, 0.40))
                _add_box(bm, ranges, 2, (x, self.width * 0.54, self.height * 0.72), (0.26, 0.10, 0.40))
        else:
            _add_box(
                bm,
                ranges,
                1,
                (0.0, 0.0, self.height * 0.76),
                (self.span + pier_w * 1.5, self.width * 0.42, self.height * 0.10),
            )

        # Door leaves / broken planks under the opening.
        door_h = self.height * 0.47
        if self.town_gate_archetype != "stone_arch":
            for i, x in enumerate((-self.span * 0.18, self.span * 0.18)):
                if rng.random() < self.ruined * 0.55:
                    continue
                _add_box(bm, ranges, 1, (x, -self.width * 0.04, door_h * 0.5), (self.span * 0.28, 0.10, door_h))
            _add_box(bm, ranges, 2, (0.0, -self.width * 0.12, door_h * 0.55), (self.span * 0.62, 0.08, 0.10))

        if self.roof:
            platform_z = self.height * 0.78
            _add_box(bm, ranges, 1, (0.0, 0.0, platform_z), (self.span + 1.3, self.width * 1.34, 0.18))
            _add_roof(
                bm,
                ranges,
                z=platform_z + 0.28,
                span=self.span + 1.8,
                depth=self.width * 1.55,
                height=0.95,
            )
            # Rail teeth on the platform.
            for i in range(5):
                x = -self.span * 0.45 + i * self.span * 0.225
                _add_box(bm, ranges, 1, (x, -self.width * 0.72, platform_z + 0.35), (0.12, 0.10, 0.55))

        # Fallen rubble/planks for ruined variant.
        if self.ruined > 0.1:
            for _ in range(5):
                _add_box(
                    bm,
                    ranges,
                    rng.choice([0, 1]),
                    (rng.uniform(-self.span * 0.65, self.span * 0.65), rng.uniform(-self.width, self.width), 0.08),
                    (rng.uniform(0.32, 0.70), rng.uniform(0.12, 0.26), rng.uniform(0.10, 0.20)),
                )

        me = bpy.data.meshes.new(f"LowPolyTownGate({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()
        obj = bpy.data.objects.new(f"LowPolyTownGate({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)
        while len(obj.data.materials) < 3:
            obj.data.materials.append(None)
        for start, end, slot in ranges:
            for i in range(start, min(end, len(obj.data.polygons))):
                obj.data.polygons[i].material_index = slot
        for p in obj.data.polygons:
            p.use_smooth = False
        apply_palette_slots(obj, [self.stone_color, self.wood_color, self.metal_color])
        return obj

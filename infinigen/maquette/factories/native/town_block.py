"""LowPolyTownBlockFactory — compact multi-building street block.

Single houses still look like repeated game pieces when a settlement
needs density. This factory emits a composed low-poly block: attached
narrow buildings, varied rooflines, awnings, balconies, exterior stairs,
shop counters, chimneys, crates, and small service yards.

Archetypes:
  market_row        — 3-4 attached shop houses with awnings/signs.
  stacked_tenement  — taller town block with balconies and exterior stairs.
  workshop_courtyard — craft/workshop compound with shed, chimney, clutter.
  stepped_hillside  — terraced houses with small height offsets and stairs.
  mudbrick_bazaar   — flat-roof desert row with parapets and shade cloth.
  coastal_row       — painted clapboard row with balconies and service clutter.
  alpine_chalet_row — steep-roof chalet row with timber balconies.

Material slots:
  slot 0 = walls
  slot 1 = roofs
  slot 2 = timber / trim / stairs / balconies
  slot 3 = windows
  slot 4 = cloth / signs / goods
  slot 5 = stone / foundation / rubble
"""

from __future__ import annotations

import random

import bmesh
import bpy

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_emission_palette_slot, apply_palette_slots


_TOWN_BLOCK_ARCHETYPES = (
    "market_row",
    "stacked_tenement",
    "workshop_courtyard",
    "stepped_hillside",
    "mudbrick_bazaar",
    "coastal_row",
    "alpine_chalet_row",
)

_ARCHETYPE_DEFAULTS = {
    "market_row": dict(width=8.2, depth=3.4, module_count=3, storeys=2, awnings=True, balconies=False, stairs=False, clutter=5),
    "stacked_tenement": dict(width=6.6, depth=4.1, module_count=2, storeys=3, awnings=False, balconies=True, stairs=True, clutter=3),
    "workshop_courtyard": dict(width=7.4, depth=4.4, module_count=2, storeys=2, awnings=True, balconies=False, stairs=False, clutter=8),
    "stepped_hillside": dict(width=8.4, depth=3.8, module_count=3, storeys=2, awnings=False, balconies=True, stairs=True, clutter=4),
    "mudbrick_bazaar": dict(width=8.0, depth=3.6, module_count=3, storeys=1, awnings=True, balconies=False, stairs=False, clutter=8),
    "coastal_row": dict(width=8.1, depth=3.3, module_count=3, storeys=2, awnings=True, balconies=True, stairs=False, clutter=5),
    "alpine_chalet_row": dict(width=8.6, depth=4.0, module_count=3, storeys=2, awnings=False, balconies=True, stairs=True, clutter=4),
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
    sx, sy, sz = max(float(size[0]), 0.01), max(float(size[1]), 0.01), max(float(size[2]), 0.01)
    for v in res["verts"]:
        v.co.x = v.co.x * sx + cx
        v.co.y = v.co.y * sy + cy
        v.co.z = v.co.z * sz + cz
    bm.faces.ensure_lookup_table()
    ranges.append((start, _face_count(bm), int(slot)))


def _add_gabled_roof(
    bm: bmesh.types.BMesh,
    ranges: list[tuple[int, int, int]],
    *,
    slot: int,
    cx: float,
    cy: float,
    z: float,
    width: float,
    depth: float,
    height: float,
    overhang: float,
    ridge_axis: str,
) -> None:
    start = _face_count(bm)
    hx = width * 0.5 + overhang
    hy = depth * 0.5 + overhang
    if ridge_axis == "x":
        s0 = bm.verts.new((cx - hx, cy - hy, z))
        s1 = bm.verts.new((cx + hx, cy - hy, z))
        n1 = bm.verts.new((cx + hx, cy + hy, z))
        n0 = bm.verts.new((cx - hx, cy + hy, z))
        r0 = bm.verts.new((cx - hx, cy, z + height))
        r1 = bm.verts.new((cx + hx, cy, z + height))
        bm.verts.ensure_lookup_table()
        bm.faces.new((s0, s1, r1, r0))
        bm.faces.new((r0, r1, n1, n0))
        bm.faces.new((s0, r0, n0))
        bm.faces.new((s1, n1, r1))
        ranges.append((start, _face_count(bm), int(slot)))
        _add_box(bm, ranges, slot, (cx, cy, z + height + 0.035), (hx * 2.0, 0.11, 0.07))
    else:
        w0 = bm.verts.new((cx - hx, cy - hy, z))
        e0 = bm.verts.new((cx + hx, cy - hy, z))
        e1 = bm.verts.new((cx + hx, cy + hy, z))
        w1 = bm.verts.new((cx - hx, cy + hy, z))
        r0 = bm.verts.new((cx, cy - hy, z + height))
        r1 = bm.verts.new((cx, cy + hy, z + height))
        bm.verts.ensure_lookup_table()
        bm.faces.new((e0, e1, r1, r0))
        bm.faces.new((r0, r1, w1, w0))
        bm.faces.new((w0, e0, r0))
        bm.faces.new((e1, w1, r1))
        ranges.append((start, _face_count(bm), int(slot)))
        _add_box(bm, ranges, slot, (cx, cy, z + height + 0.035), (0.11, hy * 2.0, 0.07))
    _add_box(bm, ranges, slot, (cx, cy - hy, z - 0.07), (hx * 2.0, 0.08, 0.14))
    _add_box(bm, ranges, slot, (cx, cy + hy, z - 0.07), (hx * 2.0, 0.08, 0.14))


def _add_shed_roof(
    bm: bmesh.types.BMesh,
    ranges: list[tuple[int, int, int]],
    *,
    cx: float,
    cy: float,
    z: float,
    width: float,
    depth: float,
    height: float,
    overhang: float,
) -> None:
    start = _face_count(bm)
    hx = width * 0.5 + overhang
    hy = depth * 0.5 + overhang
    verts = [
        bm.verts.new((cx - hx, cy - hy, z)),
        bm.verts.new((cx + hx, cy - hy, z)),
        bm.verts.new((cx + hx, cy + hy, z + height)),
        bm.verts.new((cx - hx, cy + hy, z + height)),
    ]
    bm.verts.ensure_lookup_table()
    bm.faces.new(tuple(verts))
    ranges.append((start, _face_count(bm), 1))
    _add_box(bm, ranges, 1, (cx, cy - hy, z - 0.06), (hx * 2.0, 0.08, 0.12))
    _add_box(bm, ranges, 1, (cx, cy + hy, z + height - 0.06), (hx * 2.0, 0.08, 0.12))


def _add_front_window(
    bm: bmesh.types.BMesh,
    ranges: list[tuple[int, int, int]],
    *,
    x: float,
    y: float,
    z: float,
    width: float = 0.42,
    height: float = 0.50,
) -> None:
    _add_box(bm, ranges, 3, (x, y, z), (width, 0.055, height))
    _add_box(bm, ranges, 2, (x - width * 0.56, y - 0.015, z), (0.045, 0.07, height * 1.08))
    _add_box(bm, ranges, 2, (x + width * 0.56, y - 0.015, z), (0.045, 0.07, height * 1.08))


def _add_awning(
    bm: bmesh.types.BMesh,
    ranges: list[tuple[int, int, int]],
    *,
    cx: float,
    y: float,
    z: float,
    width: float,
    depth: float,
) -> None:
    start = _face_count(bm)
    hx = width * 0.5
    verts = [
        bm.verts.new((cx - hx, y, z)),
        bm.verts.new((cx + hx, y, z)),
        bm.verts.new((cx + hx, y - depth, z - 0.30)),
        bm.verts.new((cx - hx, y - depth, z - 0.30)),
    ]
    bm.verts.ensure_lookup_table()
    bm.faces.new(tuple(verts))
    ranges.append((start, _face_count(bm), 4))
    _add_box(bm, ranges, 4, (cx, y - depth, z - 0.39), (width, 0.06, 0.18))
    for x in (cx - hx * 0.82, cx + hx * 0.82):
        _add_box(bm, ranges, 2, (x, y - depth * 0.92, z - 0.85), (0.08, 0.08, 0.9))


def _add_balcony(
    bm: bmesh.types.BMesh,
    ranges: list[tuple[int, int, int]],
    *,
    cx: float,
    y: float,
    z: float,
    width: float,
) -> None:
    _add_box(bm, ranges, 2, (cx, y, z), (width, 0.55, 0.12))
    _add_box(bm, ranges, 2, (cx, y - 0.28, z + 0.55), (width * 0.98, 0.07, 0.08))
    for x in (cx - width * 0.42, cx, cx + width * 0.42):
        _add_box(bm, ranges, 2, (x, y - 0.30, z + 0.34), (0.065, 0.065, 0.58))


def _add_side_stairs(
    bm: bmesh.types.BMesh,
    ranges: list[tuple[int, int, int]],
    *,
    x: float,
    y0: float,
    z_top: float,
    side: float,
) -> None:
    step_count = 6
    for i in range(step_count):
        t = (i + 1) / step_count
        _add_box(
            bm,
            ranges,
            2,
            (x, y0 + i * 0.34, z_top * t * 0.50),
            (0.70, 0.30, max(0.10, z_top / step_count * 0.52)),
        )
    _add_box(bm, ranges, 2, (x, y0 + step_count * 0.34 + 0.16, z_top), (0.78, 0.48, 0.12))
    _add_box(bm, ranges, 2, (x + side * 0.40, y0 + 1.08, z_top * 0.55), (0.06, 2.10, 0.10))


class LowPolyTownBlockFactory(AssetFactory):
    """Low-poly compound building block for denser town districts.

    Constructor knobs:
        factory_seed
        town_block_archetype : "market_row" | "stacked_tenement" | "workshop_courtyard" | "stepped_hillside" | "mudbrick_bazaar" | "coastal_row" | "alpine_chalet_row"
        width, depth, module_count, storeys
        awnings, balconies, stairs, clutter
        wall_color, roof_color, wood_color, window_color, accent_color, stone_color
        window_glow, window_glow_color, window_emission_strength
    """

    def __init__(
        self,
        factory_seed,
        town_block_archetype: str = "market_row",
        width: float | None = None,
        depth: float | None = None,
        module_count: int | None = None,
        storeys: int | None = None,
        awnings: bool | None = None,
        balconies: bool | None = None,
        stairs: bool | None = None,
        clutter: int | None = None,
        wall_color: str = "stucco",
        roof_color: str = "rock_shadow",
        wood_color: str = "wood",
        window_color: str = "sky_cool",
        accent_color: str = "accent_red",
        stone_color: str = "rock_pale",
        window_glow: bool = False,
        window_glow_color: str = "sky_warm",
        window_emission_strength: float = 1.15,
        coarse: bool = False,
        **_unused_kwargs,
    ) -> None:
        super().__init__(factory_seed, coarse=coarse)
        if _unused_kwargs:
            from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
            accept_unused_kwargs("LowPolyTownBlockFactory", _unused_kwargs)
        if town_block_archetype not in _TOWN_BLOCK_ARCHETYPES:
            import sys
            print(
                f"[town_block_archetype] WARN: unknown {town_block_archetype!r}; "
                f"falling back to {_TOWN_BLOCK_ARCHETYPES[0]!r}. Valid: {_TOWN_BLOCK_ARCHETYPES}",
                file=sys.stderr,
            )
            town_block_archetype = _TOWN_BLOCK_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[town_block_archetype]
        self.town_block_archetype = town_block_archetype
        self.width = float(width if width is not None else d["width"])
        self.depth = float(depth if depth is not None else d["depth"])
        self.module_count = max(1, min(4, int(module_count if module_count is not None else d["module_count"])))
        self.storeys = max(1, min(3, int(storeys if storeys is not None else d["storeys"])))
        self.awnings = bool(awnings if awnings is not None else d["awnings"])
        self.balconies = bool(balconies if balconies is not None else d["balconies"])
        self.stairs = bool(stairs if stairs is not None else d["stairs"])
        self.clutter = max(0, min(12, int(clutter if clutter is not None else d["clutter"])))
        self.wall_color = wall_color
        self.roof_color = roof_color
        self.wood_color = wood_color
        self.window_color = window_glow_color if window_glow else window_color
        self.accent_color = accent_color
        self.stone_color = stone_color
        self.window_glow = bool(window_glow)
        self.window_glow_color = window_glow_color
        self.window_emission_strength = max(0.0, float(window_emission_strength))

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(f"LowPolyTownBlock({self.factory_seed})_placeholder", None)
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        rng = random.Random(self.factory_seed)
        bm = bmesh.new()
        ranges: list[tuple[int, int, int]] = []
        w = self.width * rng.uniform(0.94, 1.08)
        d = self.depth * rng.uniform(0.92, 1.08)
        module_count = self.module_count
        if self.town_block_archetype in {"market_row", "coastal_row"} and rng.random() < 0.45:
            module_count = min(4, module_count + 1)
        module_w = w / module_count
        x0 = -w * 0.5
        front_y = -d * 0.5
        module_centers: list[tuple[float, float, float, float]] = []

        for i in range(module_count):
            cx = x0 + module_w * (i + 0.5)
            local_storeys = self.storeys
            if self.town_block_archetype in {"market_row", "stepped_hillside", "coastal_row", "alpine_chalet_row"}:
                local_storeys = max(1, min(3, self.storeys + rng.choice([-1, 0, 0, 1])))
            base_z = 0.0
            if self.town_block_archetype in {"stepped_hillside", "alpine_chalet_row"}:
                base_z = i * rng.uniform(0.18, 0.34)
            wall_h = 1.85 + local_storeys * rng.uniform(0.82, 0.96)
            body_w = module_w * rng.uniform(0.92, 1.03)
            body_d = d * rng.uniform(0.82, 1.02)
            _add_box(bm, ranges, 5, (cx, 0.0, base_z + 0.16), (body_w * 1.02, body_d * 1.02, 0.32))
            _add_box(bm, ranges, 0, (cx, 0.0, base_z + 0.32 + wall_h * 0.5), (body_w, body_d, wall_h))
            roof_h = rng.uniform(0.72, 1.28) + 0.12 * local_storeys
            if self.town_block_archetype == "alpine_chalet_row":
                roof_h *= 1.55
            roof_axis = "x" if body_w >= body_d or self.town_block_archetype == "market_row" else "y"
            if self.town_block_archetype == "mudbrick_bazaar":
                _add_box(
                    bm, ranges, 1,
                    (cx, 0.0, base_z + 0.32 + wall_h + 0.10),
                    (body_w * 1.05, body_d * 1.05, 0.20),
                )
                # Low parapet blocks around the flat roof.
                z_par = base_z + 0.32 + wall_h + 0.36
                _add_box(bm, ranges, 5, (cx, -body_d * 0.52, z_par), (body_w * 1.05, 0.12, 0.34))
                _add_box(bm, ranges, 5, (cx, body_d * 0.52, z_par), (body_w * 1.05, 0.12, 0.34))
                _add_box(bm, ranges, 5, (cx - body_w * 0.52, 0.0, z_par), (0.12, body_d * 0.90, 0.30))
                _add_box(bm, ranges, 5, (cx + body_w * 0.52, 0.0, z_par), (0.12, body_d * 0.90, 0.30))
            elif self.town_block_archetype == "workshop_courtyard" and i == module_count - 1:
                _add_shed_roof(
                    bm, ranges, cx=cx, cy=0.0, z=base_z + 0.32 + wall_h,
                    width=body_w, depth=body_d, height=roof_h * 0.70, overhang=0.24,
                )
            else:
                _add_gabled_roof(
                    bm, ranges, slot=1, cx=cx, cy=0.0, z=base_z + 0.32 + wall_h,
                    width=body_w, depth=body_d, height=roof_h, overhang=0.22,
                    ridge_axis=roof_axis,
                )
            module_centers.append((cx, base_z, wall_h, body_w))

            # Door and facade windows.
            door_x = cx + rng.uniform(-body_w * 0.12, body_w * 0.12)
            _add_box(bm, ranges, 2, (door_x, front_y - 0.035, base_z + 0.92), (0.52, 0.07, 1.32))
            for floor in range(local_storeys):
                z = base_z + 1.25 + floor * max(0.72, wall_h / max(1, local_storeys))
                if z > base_z + wall_h - 0.35:
                    continue
                for wx in (cx - body_w * 0.25, cx + body_w * 0.25):
                    if floor == 0 and abs(wx - door_x) < body_w * 0.20:
                        continue
                    _add_front_window(bm, ranges, x=wx, y=front_y - 0.065, z=z)
                    if self.town_block_archetype in {"market_row", "stacked_tenement"} and rng.random() < 0.45:
                        _add_box(bm, ranges, 4, (wx, front_y - 0.14, z - 0.38), (0.48, 0.12, 0.12))

            if self.awnings and (i == 0 or rng.random() < 0.82):
                _add_awning(
                    bm, ranges, cx=cx, y=front_y - 0.06,
                    z=base_z + min(wall_h * 0.58, 2.35),
                    width=body_w * rng.uniform(0.72, 0.98) if self.town_block_archetype == "mudbrick_bazaar" else body_w * rng.uniform(0.66, 0.88),
                    depth=rng.uniform(0.82, 1.22) if self.town_block_archetype == "mudbrick_bazaar" else rng.uniform(0.70, 1.0),
                )
            if self.balconies and local_storeys >= 2 and rng.random() < 0.82:
                _add_balcony(
                    bm, ranges, cx=cx, y=front_y - 0.34,
                    z=base_z + min(wall_h * 0.62, 2.55),
                    width=body_w * rng.uniform(0.58, 0.86) if self.town_block_archetype == "alpine_chalet_row" else body_w * rng.uniform(0.48, 0.70),
                )
            if rng.random() < (0.70 if self.town_block_archetype in {"alpine_chalet_row", "stacked_tenement"} else 0.55):
                chimney_x = cx + rng.choice([-1.0, 1.0]) * body_w * rng.uniform(0.20, 0.34)
                _add_box(bm, ranges, 5, (chimney_x, rng.uniform(-d * 0.16, d * 0.20), base_z + wall_h + 1.02), (0.34, 0.32, 1.24))
            if self.town_block_archetype == "coastal_row" and rng.random() < 0.70:
                _add_box(bm, ranges, 2, (cx, d * 0.52, base_z + 0.72), (body_w * 0.62, 0.42, 0.12))
                _add_box(bm, ranges, 5, (cx + body_w * 0.22, d * 0.72, base_z + 0.18), (0.52, 0.30, 0.36))

        if self.stairs:
            side = rng.choice([-1.0, 1.0])
            _add_side_stairs(
                bm,
                ranges,
                x=side * (w * 0.5 + 0.45),
                y0=front_y + 0.32,
                z_top=2.15 if self.storeys < 3 else 2.75,
                side=side,
            )

        if self.town_block_archetype == "workshop_courtyard":
            # Back service shed and strong chimney make the craft district read.
            _add_box(bm, ranges, 0, (-w * 0.12, d * 0.62, 0.78), (w * 0.54, d * 0.38, 1.56))
            _add_box(bm, ranges, 1, (-w * 0.12, d * 0.62, 1.72), (w * 0.62, d * 0.48, 0.18))
            _add_box(bm, ranges, 5, (w * 0.25, d * 0.48, 2.40), (0.42, 0.42, 1.70))
            _add_box(bm, ranges, 5, (w * 0.33, d * 0.20, 0.26), (1.0, 0.55, 0.52))

        # Thin vertical seams between modules and a continuous top timber band.
        for i in range(1, module_count):
            x = x0 + module_w * i
            _add_box(bm, ranges, 2, (x, front_y - 0.07, 1.55), (0.10, 0.08, 2.60))
        _add_box(bm, ranges, 2, (0.0, front_y - 0.08, 2.18), (w * 0.92, 0.08, 0.12))

        # Clutter: crates/goods/signs are part of the block, not separate scatter.
        for i in range(self.clutter):
            cx = rng.uniform(-w * 0.45, w * 0.45)
            cy = front_y - rng.uniform(0.55, 1.32)
            if self.town_block_archetype == "workshop_courtyard" and i % 3 == 0:
                cy = rng.uniform(-d * 0.10, d * 0.68)
            _add_box(
                bm,
                ranges,
                rng.choice([2, 4, 5]),
                (cx, cy, rng.uniform(0.13, 0.30)),
                (rng.uniform(0.24, 0.62), rng.uniform(0.22, 0.50), rng.uniform(0.18, 0.46)),
            )
        if self.town_block_archetype == "mudbrick_bazaar":
            # Rooftop jars and shade anchors.
            for cx, base_z, wall_h, body_w in module_centers:
                if rng.random() < 0.65:
                    _add_box(bm, ranges, 4, (cx + body_w * rng.uniform(-0.22, 0.22), rng.uniform(-d * 0.18, d * 0.24), base_z + wall_h + 0.78), (0.28, 0.28, 0.34))
        if self.town_block_archetype in {"market_row", "stacked_tenement", "coastal_row", "alpine_chalet_row"}:
            for cx, base_z, wall_h, body_w in module_centers[: min(3, len(module_centers))]:
                _add_box(bm, ranges, 4, (cx - body_w * 0.28, front_y - 0.32, base_z + min(wall_h * 0.70, 2.65)), (0.42, 0.08, 0.30))

        me = bpy.data.meshes.new(f"LowPolyTownBlock({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()
        obj = bpy.data.objects.new(f"LowPolyTownBlock({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)
        while len(obj.data.materials) < 6:
            obj.data.materials.append(None)
        for start, end, slot in ranges:
            for idx in range(start, min(end, len(obj.data.polygons))):
                obj.data.polygons[idx].material_index = slot
        for p in obj.data.polygons:
            p.use_smooth = False
        apply_palette_slots(
            obj,
            [
                self.wall_color,
                self.roof_color,
                self.wood_color,
                self.window_color,
                self.accent_color,
                self.stone_color,
            ],
        )
        if self.window_glow:
            apply_emission_palette_slot(
                obj,
                3,
                self.window_glow_color,
                strength=self.window_emission_strength,
            )
        return obj

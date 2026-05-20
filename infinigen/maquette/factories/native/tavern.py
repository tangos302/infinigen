"""LowPolyTavernFactory — readable inn / tavern landmark.

The generic house factory can produce a tavern-like building, but towns
need one public building that reads at a glance: taller body, broad roof,
hanging sign, porch/awning, chimney, balcony rail, barrels, and benches.

Archetypes:
  roadside_inn    — broad two-storey inn with front porch and sign.
  guildhall       — taller civic tavern with balcony and banners.
  riverside_pub   — squat public house with side awning and barrel stack.
  ruined_inn      — damaged roof, partial sign, scattered debris.

Material slots:
  slot 0 = walls
  slot 1 = roof
  slot 2 = wood trim / porch / balcony
  slot 3 = windows / sign accent
  slot 4 = barrels / rubble accents
"""

from __future__ import annotations

import random

import bmesh
import bpy

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_TAVERN_ARCHETYPES = ("roadside_inn", "guildhall", "riverside_pub", "ruined_inn")

_ARCHETYPE_DEFAULTS = {
    "roadside_inn": dict(width=6.2, depth=4.3, wall_height=4.0, roof_height=1.75, porch=True, balcony=False, ruined=0.0),
    "guildhall": dict(width=5.4, depth=4.6, wall_height=4.8, roof_height=1.45, porch=False, balcony=True, ruined=0.0),
    "riverside_pub": dict(width=5.8, depth=3.8, wall_height=3.25, roof_height=1.35, porch=True, balcony=False, ruined=0.0),
    "ruined_inn": dict(width=5.8, depth=4.1, wall_height=3.1, roof_height=1.2, porch=True, balcony=False, ruined=0.42),
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


def _add_gabled_roof(
    bm: bmesh.types.BMesh,
    ranges: list[tuple[int, int, int]],
    slot: int,
    *,
    width: float,
    depth: float,
    z: float,
    height: float,
    overhang: float,
    missing_side: bool = False,
) -> None:
    start = _face_count(bm)
    hx = width * 0.5 + overhang
    hy = depth * 0.5 + overhang
    south0 = bm.verts.new((-hx, -hy, z))
    south1 = bm.verts.new((hx, -hy, z))
    north1 = bm.verts.new((hx, hy, z))
    north0 = bm.verts.new((-hx, hy, z))
    ridge0 = bm.verts.new((-hx, 0.0, z + height))
    ridge1 = bm.verts.new((hx, 0.0, z + height))
    bm.verts.ensure_lookup_table()
    if not missing_side:
        bm.faces.new((south0, south1, ridge1, ridge0))
    bm.faces.new((north1, north0, ridge0, ridge1))
    bm.faces.new((south0, ridge0, north0))
    bm.faces.new((south1, north1, ridge1))
    ranges.append((start, _face_count(bm), int(slot)))
    # Thick fascia prevents paper-roof read.
    _add_box(bm, ranges, slot, (0.0, -hy, z - 0.09), (hx * 2.0, 0.08, 0.18))
    _add_box(bm, ranges, slot, (0.0, hy, z - 0.09), (hx * 2.0, 0.08, 0.18))


def _add_barrel(
    bm: bmesh.types.BMesh,
    ranges: list[tuple[int, int, int]],
    x: float,
    y: float,
    z: float,
    scale: float,
) -> None:
    _add_box(bm, ranges, 4, (x, y, z + 0.22 * scale), (0.32 * scale, 0.32 * scale, 0.44 * scale))
    _add_box(bm, ranges, 2, (x, y - 0.17 * scale, z + 0.22 * scale), (0.35 * scale, 0.035 * scale, 0.36 * scale))


class LowPolyTavernFactory(AssetFactory):
    """Low-poly tavern/inn landmark with sign, porch, and props.

    Constructor knobs:
        factory_seed
        tavern_archetype : "roadside_inn" | "guildhall" | "riverside_pub" | "ruined_inn"
        width, depth, wall_height, roof_height
        porch, balcony, ruined
        wall_color, roof_color, wood_color, window_color, accent_color
    """

    def __init__(
        self,
        factory_seed,
        tavern_archetype: str = "roadside_inn",
        width: float | None = None,
        depth: float | None = None,
        wall_height: float | None = None,
        roof_height: float | None = None,
        porch: bool | None = None,
        balcony: bool | None = None,
        ruined: float | None = None,
        wall_color: str = "stucco",
        roof_color: str = "rock_shadow",
        wood_color: str = "wood",
        window_color: str = "sky_cool",
        accent_color: str = "rock_warm",
        coarse: bool = False,
        **_unused_kwargs,
    ) -> None:
        super().__init__(factory_seed, coarse=coarse)
        if _unused_kwargs:
            from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
            accept_unused_kwargs("LowPolyTavernFactory", _unused_kwargs)
        if tavern_archetype not in _TAVERN_ARCHETYPES:
            import sys
            print(
                f"[tavern_archetype] WARN: unknown {tavern_archetype!r}; "
                f"falling back to {_TAVERN_ARCHETYPES[0]!r}. Valid: {_TAVERN_ARCHETYPES}",
                file=sys.stderr,
            )
            tavern_archetype = _TAVERN_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[tavern_archetype]
        self.tavern_archetype = tavern_archetype
        self.width = float(width if width is not None else d["width"])
        self.depth = float(depth if depth is not None else d["depth"])
        self.wall_height = float(wall_height if wall_height is not None else d["wall_height"])
        self.roof_height = float(roof_height if roof_height is not None else d["roof_height"])
        self.porch = bool(porch if porch is not None else d["porch"])
        self.balcony = bool(balcony if balcony is not None else d["balcony"])
        self.ruined = max(0.0, min(0.85, float(ruined if ruined is not None else d["ruined"])))
        self.wall_color = wall_color
        self.roof_color = roof_color
        self.wood_color = wood_color
        self.window_color = window_color
        self.accent_color = accent_color

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(f"LowPolyTavern({self.factory_seed})_placeholder", None)
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        rng = random.Random(self.factory_seed)
        bm = bmesh.new()
        ranges: list[tuple[int, int, int]] = []
        # Presets define the archetype. Per-seed jitter keeps repeated inns from
        # cloning too obviously in town rows while preserving the authored role.
        w = self.width * rng.uniform(0.94, 1.08)
        d = self.depth * rng.uniform(0.94, 1.06)
        h = self.wall_height * rng.uniform(0.96, 1.08)
        roof_height = self.roof_height * rng.uniform(0.90, 1.16)
        trim_scale = rng.uniform(0.88, 1.14)
        # Main mass and optional side wing.
        _add_box(bm, ranges, 0, (0.0, 0.0, h * 0.5), (w, d, h))
        if self.tavern_archetype in {"roadside_inn", "guildhall"}:
            wing_x = rng.choice([-1.0, 1.0]) * w * rng.uniform(0.22, 0.32)
            _add_box(bm, ranges, 0, (wing_x, d * 0.52, h * 0.37), (w * rng.uniform(0.30, 0.42), d * 0.52, h * 0.74))
        _add_gabled_roof(
            bm,
            ranges,
            1,
            width=w,
            depth=d,
            z=h,
            height=roof_height,
            overhang=0.36,
            missing_side=self.ruined > 0.35,
        )
        # Cross dormer/wing roof for public-building silhouette.
        if self.tavern_archetype == "guildhall" or (self.tavern_archetype == "roadside_inn" and rng.random() < 0.35):
            _add_box(bm, ranges, 1, (rng.uniform(-w * 0.10, w * 0.10), -d * 0.52, h + 0.22), (w * rng.uniform(0.42, 0.66), 0.46, 0.44))
        if self.tavern_archetype in {"roadside_inn", "riverside_pub"} and rng.random() < 0.55:
            _add_box(bm, ranges, 1, (-w * 0.34, d * 0.07, h + roof_height * 0.34), (w * 0.22, d * 0.16, roof_height * 0.32))

        # Foundation and front door.
        _add_box(bm, ranges, 2, (0.0, -d * 0.51, 0.18), (w * 1.05, 0.12, 0.36))
        door_x = rng.uniform(-w * 0.07, w * 0.07)
        _add_box(bm, ranges, 2, (door_x, -d * 0.515, 0.88), (0.70 * trim_scale, 0.10, 1.45))
        # Windows front and sides.
        floors = 2 if h > 3.35 else 1
        for floor in range(floors):
            wz = 1.65 + floor * 1.45
            for x in (-w * rng.uniform(0.26, 0.36), w * rng.uniform(0.26, 0.36)):
                if rng.random() < self.ruined * 0.35:
                    continue
                _add_box(bm, ranges, 3, (x, -d * 0.522, wz), (0.48, 0.075, 0.56))
                _add_box(bm, ranges, 2, (x, -d * 0.535, wz + 0.34), (0.58, 0.06, 0.06))
        for y in (-d * 0.22, d * 0.22):
            _add_box(bm, ranges, 3, (w * 0.505, y, 1.75), (0.075, 0.46, 0.54))

        # Hanging tavern sign from a bracket.
        sign_x = rng.choice([-1.0, 1.0]) * w * rng.uniform(0.34, 0.44)
        sign_z = h * 0.62
        _add_box(bm, ranges, 2, (sign_x, -d * 0.67, sign_z + 0.34), (0.08, 0.68, 0.08))
        _add_box(bm, ranges, 3, (sign_x, -d * 0.88, sign_z), (0.54, 0.10, 0.42))

        if self.porch:
            porch_y = -d * 0.76
            porch_w = w * rng.uniform(0.46, 0.68)
            _add_box(bm, ranges, 2, (0.0, porch_y, 0.55), (porch_w, 1.1, 0.14))
            for x in (-porch_w * 0.45, porch_w * 0.45):
                _add_box(bm, ranges, 2, (x, porch_y - 0.42, 1.35), (0.12, 0.12, 1.6))
            _add_box(bm, ranges, 1, (0.0, porch_y - 0.20, 2.20), (porch_w * 1.12, 1.24, 0.20))
            # Benches.
            for x in (-porch_w * 0.35, porch_w * 0.35):
                _add_box(bm, ranges, 2, (x, porch_y - 0.30, 0.86), (0.80, 0.18, 0.14))
                _add_box(bm, ranges, 2, (x, porch_y - 0.40, 1.06), (0.80, 0.12, 0.28))

        if self.balcony:
            by = -d * 0.58
            bz = h * 0.58
            balcony_w = w * rng.uniform(0.55, 0.74)
            _add_box(bm, ranges, 2, (0.0, by, bz), (balcony_w, 0.42, 0.14))
            for x in (-balcony_w * 0.38, -balcony_w * 0.18, balcony_w * 0.18, balcony_w * 0.38):
                _add_box(bm, ranges, 2, (x, by - 0.20, bz + 0.38), (0.06, 0.06, 0.62))
            _add_box(bm, ranges, 2, (0.0, by - 0.20, bz + 0.72), (balcony_w * 0.92, 0.06, 0.08))

        # Chimney and barrels.
        chimney_x = rng.choice([-1.0, 1.0]) * w * rng.uniform(0.24, 0.38)
        _add_box(bm, ranges, 4, (chimney_x, rng.uniform(-d * 0.10, d * 0.16), h + roof_height * 0.55), (0.36, 0.34, 1.15))
        for i in range(3 if self.tavern_archetype != "ruined_inn" else 2):
            _add_barrel(bm, ranges, w * 0.42 - i * 0.36, -d * 0.72, 0.0, rng.uniform(0.9, 1.08))
        if self.ruined > 0.1:
            for _ in range(6):
                _add_box(
                    bm,
                    ranges,
                    rng.choice([1, 2, 4]),
                    (rng.uniform(-w * 0.48, w * 0.48), rng.uniform(-d * 0.74, d * 0.58), 0.08),
                    (rng.uniform(0.28, 0.76), rng.uniform(0.14, 0.34), rng.uniform(0.10, 0.24)),
                )

        me = bpy.data.meshes.new(f"LowPolyTavern({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()
        obj = bpy.data.objects.new(f"LowPolyTavern({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)
        while len(obj.data.materials) < 5:
            obj.data.materials.append(None)
        for start, end, slot in ranges:
            for i in range(start, min(end, len(obj.data.polygons))):
                obj.data.polygons[i].material_index = slot
        for p in obj.data.polygons:
            p.use_smooth = False
        apply_palette_slots(obj, [self.wall_color, self.roof_color, self.wood_color, self.window_color, self.accent_color])
        return obj

"""LowPolyChapelFactory — chapel / wayside shrine landmark.

Small religious/civic focal points show up in market towns, alpine
villages, cemeteries, castle outskirts, and ruined scenes. A generic
house with a cross does not read strongly enough from the default
Maquette camera, so this factory authors the full chapel grammar:
nave, steep roof, bell tower, apse, buttresses, arched openings, and
a small cross.

Archetypes:
  village_chapel — stone nave, front bell tower, rear apse.
  alpine_chapel  — smaller footprint, steeper roof, timber trim.
  ruined_chapel  — partial walls, broken tower stump, scattered blocks.

Material slots:
  slot 0 = stone / wall body
  slot 1 = roof
  slot 2 = wood trim / doors
  slot 3 = dark windows
  slot 4 = accent details / cross
"""

from __future__ import annotations

import math
import random

import bmesh
import bpy

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_CHAPEL_ARCHETYPES = ("village_chapel", "alpine_chapel", "ruined_chapel")

_ARCHETYPE_DEFAULTS = {
    "village_chapel": dict(
        length=6.4,
        depth=3.2,
        wall_height=2.7,
        roof_height=1.5,
        tower_height=4.2,
        tower_width=1.65,
        roof_overhang=0.28,
        wall_color="rock_pale",
        roof_color="rock_shadow",
        wood_color="wood",
        window_color="water",
        accent_color="stucco",
    ),
    "alpine_chapel": dict(
        length=5.7,
        depth=3.0,
        wall_height=2.45,
        roof_height=1.85,
        tower_height=4.7,
        tower_width=1.38,
        roof_overhang=0.42,
        wall_color="stucco",
        roof_color="rock_shadow",
        wood_color="wood",
        window_color="water",
        accent_color="rock_pale",
    ),
    "ruined_chapel": dict(
        length=6.0,
        depth=3.1,
        wall_height=2.05,
        roof_height=0.9,
        tower_height=2.8,
        tower_width=1.55,
        roof_overhang=0.18,
        wall_color="rock_warm",
        roof_color="rock_shadow",
        wood_color="wood",
        window_color="rock_shadow",
        accent_color="rock_pale",
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
) -> None:
    start = _face_count(bm)
    cx, cy, cz = center
    sx, sy, sz = size
    hx, hy, hz = sx * 0.5, sy * 0.5, sz * 0.5
    b00 = bm.verts.new((cx - hx, cy - hy, cz - hz))
    b10 = bm.verts.new((cx + hx, cy - hy, cz - hz))
    b11 = bm.verts.new((cx + hx, cy + hy, cz - hz))
    b01 = bm.verts.new((cx - hx, cy + hy, cz - hz))
    t00 = bm.verts.new((cx - hx, cy - hy, cz + hz))
    t10 = bm.verts.new((cx + hx, cy - hy, cz + hz))
    t11 = bm.verts.new((cx + hx, cy + hy, cz + hz))
    t01 = bm.verts.new((cx - hx, cy + hy, cz + hz))
    bm.verts.ensure_lookup_table()
    bm.faces.new((b00, b10, t10, t00))
    bm.faces.new((b10, b11, t11, t10))
    bm.faces.new((b11, b01, t01, t11))
    bm.faces.new((b01, b00, t00, t01))
    bm.faces.new((t00, t10, t11, t01))
    bm.faces.new((b00, b01, b11, b10))
    slot_ranges.append((start, _face_count(bm), int(slot)))


def _add_gabled_roof(
    bm: bmesh.types.BMesh,
    slot_ranges: list[tuple[int, int, int]],
    slot: int,
    *,
    center_x: float,
    length: float,
    depth: float,
    z: float,
    height: float,
    overhang: float,
) -> None:
    """Closed gabled roof with ridge along X."""
    start = _face_count(bm)
    hx = length * 0.5 + overhang
    hy = depth * 0.5 + overhang
    x0 = center_x - hx
    x1 = center_x + hx
    south0 = bm.verts.new((x0, -hy, z))
    south1 = bm.verts.new((x1, -hy, z))
    north1 = bm.verts.new((x1, hy, z))
    north0 = bm.verts.new((x0, hy, z))
    ridge0 = bm.verts.new((x0, 0.0, z + height))
    ridge1 = bm.verts.new((x1, 0.0, z + height))
    bm.verts.ensure_lookup_table()
    bm.faces.new((south0, south1, ridge1, ridge0))
    bm.faces.new((north1, north0, ridge0, ridge1))
    bm.faces.new((south0, ridge0, north0))
    bm.faces.new((south1, north1, ridge1))
    # A shallow fascia under the eaves removes the paper-thin roof read.
    fascia_h = max(0.10, overhang * 0.32)
    for cy in (-hy, hy):
        _add_box(
            bm,
            slot_ranges,
            slot,
            (center_x, cy, z - fascia_h * 0.5),
            (hx * 2.0, 0.06, fascia_h),
        )
    slot_ranges.append((start, _face_count(bm), int(slot)))


def _add_pyramid_roof(
    bm: bmesh.types.BMesh,
    slot_ranges: list[tuple[int, int, int]],
    slot: int,
    *,
    center: tuple[float, float],
    size: float,
    z: float,
    height: float,
    overhang: float,
) -> None:
    start = _face_count(bm)
    cx, cy = center
    h = size * 0.5 + overhang
    corners = [
        bm.verts.new((cx - h, cy - h, z)),
        bm.verts.new((cx + h, cy - h, z)),
        bm.verts.new((cx + h, cy + h, z)),
        bm.verts.new((cx - h, cy + h, z)),
    ]
    apex = bm.verts.new((cx, cy, z + height))
    bm.verts.ensure_lookup_table()
    for i in range(4):
        bm.faces.new((corners[i], corners[(i + 1) % 4], apex))
    slot_ranges.append((start, _face_count(bm), int(slot)))


def _add_apse(
    bm: bmesh.types.BMesh,
    slot_ranges: list[tuple[int, int, int]],
    slot: int,
    *,
    x0: float,
    depth: float,
    height: float,
    radius: float,
) -> None:
    """Six-sided rear apse extruded upward from z=0."""
    start = _face_count(bm)
    hd = depth * 0.5
    pts = [
        (x0, -hd),
        (x0 + radius * 0.64, -hd * 0.78),
        (x0 + radius, -hd * 0.25),
        (x0 + radius, hd * 0.25),
        (x0 + radius * 0.64, hd * 0.78),
        (x0, hd),
    ]
    bottom = [bm.verts.new((x, y, 0.0)) for x, y in pts]
    top = [bm.verts.new((x, y, height)) for x, y in pts]
    bm.verts.ensure_lookup_table()
    for i in range(len(pts)):
        ni = (i + 1) % len(pts)
        bm.faces.new((bottom[i], bottom[ni], top[ni], top[i]))
    bm.faces.new(top)
    bm.faces.new(list(reversed(bottom)))
    slot_ranges.append((start, _face_count(bm), int(slot)))


def _add_cross(
    bm: bmesh.types.BMesh,
    slot_ranges: list[tuple[int, int, int]],
    *,
    x: float,
    y: float,
    z: float,
    height: float,
    slot: int,
) -> None:
    stem_w = height * 0.10
    _add_box(bm, slot_ranges, slot, (x, y, z + height * 0.5), (stem_w, stem_w, height))
    _add_box(
        bm,
        slot_ranges,
        slot,
        (x, y, z + height * 0.67),
        (height * 0.55, stem_w * 0.92, stem_w),
    )


class LowPolyChapelFactory(AssetFactory):
    """Low-poly chapel landmark.

    Constructor knobs:
        factory_seed
        chapel_archetype : "village_chapel" | "alpine_chapel" | "ruined_chapel"
        length, depth, wall_height, roof_height
        tower_height, tower_width, roof_overhang
        wall_color, roof_color, wood_color, window_color, accent_color
    """

    def __init__(
        self,
        factory_seed,
        chapel_archetype: str = "village_chapel",
        length: float | None = None,
        depth: float | None = None,
        wall_height: float | None = None,
        roof_height: float | None = None,
        tower_height: float | None = None,
        tower_width: float | None = None,
        roof_overhang: float | None = None,
        wall_color: str | None = None,
        roof_color: str | None = None,
        wood_color: str | None = None,
        window_color: str | None = None,
        accent_color: str | None = None,
        coarse: bool = False,
        **_unused_kwargs,
    ) -> None:
        super().__init__(factory_seed, coarse=coarse)
        if _unused_kwargs:
            from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
            accept_unused_kwargs("LowPolyChapelFactory", _unused_kwargs)
        if chapel_archetype not in _CHAPEL_ARCHETYPES:
            import sys
            print(
                f"[chapel_archetype] WARN: unknown {chapel_archetype!r}; "
                f"falling back to {_CHAPEL_ARCHETYPES[0]!r}. "
                f"Valid: {_CHAPEL_ARCHETYPES}",
                file=sys.stderr,
            )
            chapel_archetype = _CHAPEL_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[chapel_archetype]
        self.chapel_archetype = chapel_archetype
        self.length = float(length if length is not None else d["length"])
        self.depth = float(depth if depth is not None else d["depth"])
        self.wall_height = float(wall_height if wall_height is not None else d["wall_height"])
        self.roof_height = float(roof_height if roof_height is not None else d["roof_height"])
        self.tower_height = float(tower_height if tower_height is not None else d["tower_height"])
        self.tower_width = float(tower_width if tower_width is not None else d["tower_width"])
        self.roof_overhang = float(roof_overhang if roof_overhang is not None else d["roof_overhang"])
        self.wall_color = wall_color or d["wall_color"]
        self.roof_color = roof_color or d["roof_color"]
        self.wood_color = wood_color or d["wood_color"]
        self.window_color = window_color or d["window_color"]
        self.accent_color = accent_color or d["accent_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(f"LowPolyChapel({self.factory_seed})_placeholder", None)
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        rng = random.Random(int(self.factory_seed))
        bm = bmesh.new()
        slot_ranges: list[tuple[int, int, int]] = []

        L, D, H = self.length, self.depth, self.wall_height
        front_x = -L * 0.5
        back_x = L * 0.5
        ruin = self.chapel_archetype == "ruined_chapel"

        if ruin:
            # Ruined nave as separate wall chunks so it reads broken, not
            # as a closed house. Leave the center open.
            _add_box(bm, slot_ranges, 0, (0.0, -D * 0.5, H * 0.47), (L * 0.90, 0.28, H * 0.94))
            _add_box(bm, slot_ranges, 0, (-L * 0.15, D * 0.5, H * 0.42), (L * 0.62, 0.28, H * 0.84))
            _add_box(bm, slot_ranges, 0, (front_x, 0.0, H * 0.48), (0.28, D, H * 0.96))
            _add_box(bm, slot_ranges, 0, (back_x, -D * 0.18, H * 0.35), (0.25, D * 0.54, H * 0.70))
            _add_box(
                bm,
                slot_ranges,
                1,
                (-L * 0.10, -D * 0.18, H + self.roof_height * 0.28),
                (L * 0.42, D * 0.28, 0.16),
            )
        else:
            _add_box(bm, slot_ranges, 0, (0.0, 0.0, H * 0.5), (L, D, H))
            _add_gabled_roof(
                bm,
                slot_ranges,
                1,
                center_x=0.0,
                length=L,
                depth=D,
                z=H,
                height=self.roof_height,
                overhang=self.roof_overhang,
            )
            _add_apse(
                bm,
                slot_ranges,
                0,
                x0=back_x - 0.05,
                depth=D * 0.72,
                height=H * 0.88,
                radius=0.95,
            )
            _add_gabled_roof(
                bm,
                slot_ranges,
                1,
                center_x=back_x + 0.42,
                length=0.95,
                depth=D * 0.72,
                z=H * 0.88,
                height=self.roof_height * 0.48,
                overhang=self.roof_overhang * 0.55,
            )

        # Front tower.
        tw = self.tower_width
        tower_x = front_x - tw * 0.24
        tower_h = self.tower_height if not ruin else self.tower_height * 0.62
        _add_box(bm, slot_ranges, 0, (tower_x, 0.0, tower_h * 0.5), (tw, tw, tower_h))
        if not ruin:
            _add_pyramid_roof(
                bm,
                slot_ranges,
                1,
                center=(tower_x, 0.0),
                size=tw,
                z=tower_h,
                height=self.roof_height * 0.92,
                overhang=self.roof_overhang * 0.55,
            )
            _add_cross(
                bm,
                slot_ranges,
                x=tower_x,
                y=0.0,
                z=tower_h + self.roof_height * 0.86,
                height=0.55,
                slot=4,
            )

        # Buttresses and lower trim.
        for x in (-L * 0.28, L * 0.08, L * 0.38):
            for y in (-D * 0.5 - 0.12, D * 0.5 + 0.12):
                if ruin and rng.random() < 0.35:
                    continue
                _add_box(bm, slot_ranges, 0, (x, y, H * 0.34), (0.22, 0.22, H * 0.68))
        _add_box(bm, slot_ranges, 2, (front_x - 0.02, 0.0, 0.86), (0.08, 0.92, 1.42))

        # Dark arched windows are low-relief panels. They deliberately sit
        # proud of the walls so they read from a screenshot.
        for x in (-L * 0.24, L * 0.18):
            for y, sy in ((-D * 0.5 - 0.022, 0.035), (D * 0.5 + 0.022, 0.035)):
                if ruin and rng.random() < 0.45:
                    continue
                _add_box(bm, slot_ranges, 3, (x, y, H * 0.58), (0.52, sy, 0.82))
                _add_box(bm, slot_ranges, 4, (x, y, H * 0.99), (0.34, sy, 0.16))

        # Rubble around ruined chapel.
        if ruin:
            for _ in range(16):
                x = rng.uniform(-L * 0.58, L * 0.65)
                y = rng.uniform(-D * 0.78, D * 0.78)
                sx = rng.uniform(0.18, 0.50)
                sy = rng.uniform(0.16, 0.42)
                sz = rng.uniform(0.10, 0.34)
                _add_box(bm, slot_ranges, 0, (x, y, sz * 0.5), (sx, sy, sz))
            _add_cross(bm, slot_ranges, x=tower_x + 0.25, y=0.12, z=tower_h, height=0.42, slot=4)

        me = bpy.data.meshes.new(f"LowPolyChapel({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()
        obj = bpy.data.objects.new(f"LowPolyChapel({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)

        while len(obj.data.materials) < 5:
            obj.data.materials.append(None)
        for start, end, slot in slot_ranges:
            for i in range(start, end):
                obj.data.polygons[i].material_index = slot
        for poly in obj.data.polygons:
            poly.use_smooth = False

        apply_palette_slots(
            obj,
            [
                self.wall_color,
                self.roof_color,
                self.wood_color,
                self.window_color,
                self.accent_color,
            ],
        )
        return obj

"""LowPolyWatermillFactory — riverside watermill landmark.

A watermill turns "house near river" into a specific scene beat. The
asset is built as a compound: mill house, gabled roof, wheel housing,
wood water wheel with spokes and paddles, and a small sluice trough.

Archetypes:
  timber_river     — wood body, simple rural mill.
  stone_river      — heavier stone mill, darker wheel.
  half_timber_mill — plaster body, visible timber braces.

Material slots:
  slot 0 = walls / tower body
  slot 1 = roof
  slot 2 = wheel / timber frame
  slot 3 = water trough / dark trim
  slot 4 = windows
"""

from __future__ import annotations

import math
import random

import bmesh
import bpy
from mathutils import Vector

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_WATERMILL_ARCHETYPES = ("timber_river", "stone_river", "half_timber_mill")

_ARCHETYPE_DEFAULTS = {
    "timber_river": dict(
        width=4.4,
        depth=3.4,
        wall_height=2.65,
        roof_height=1.35,
        wheel_radius=1.18,
        wall_color="wood",
        roof_color="rock_shadow",
        wheel_color="wood",
        trough_color="rock_shadow",
        window_color="water",
    ),
    "stone_river": dict(
        width=4.8,
        depth=3.55,
        wall_height=2.85,
        roof_height=1.25,
        wheel_radius=1.35,
        wall_color="rock_pale",
        roof_color="rock_warm",
        wheel_color="wood",
        trough_color="rock_shadow",
        window_color="water",
    ),
    "half_timber_mill": dict(
        width=4.55,
        depth=3.35,
        wall_height=2.75,
        roof_height=1.45,
        wheel_radius=1.25,
        wall_color="stucco",
        roof_color="rock_shadow",
        wheel_color="wood",
        trough_color="rust_metal",
        window_color="water",
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


def _add_gabled_roof(
    bm: bmesh.types.BMesh,
    slot_ranges: list[tuple[int, int, int]],
    slot: int,
    *,
    width: float,
    depth: float,
    z: float,
    height: float,
    overhang: float,
) -> None:
    start = _face_count(bm)
    hx = width * 0.5 + overhang
    hy = depth * 0.5 + overhang
    west0 = bm.verts.new((-hx, -hy, z))
    east0 = bm.verts.new((hx, -hy, z))
    east1 = bm.verts.new((hx, hy, z))
    west1 = bm.verts.new((-hx, hy, z))
    ridge_w = bm.verts.new((-hx, 0.0, z + height))
    ridge_e = bm.verts.new((hx, 0.0, z + height))
    bm.verts.ensure_lookup_table()
    bm.faces.new((west0, east0, ridge_e, ridge_w))
    bm.faces.new((east1, west1, ridge_w, ridge_e))
    bm.faces.new((west0, ridge_w, west1))
    bm.faces.new((east0, east1, ridge_e))
    slot_ranges.append((start, _face_count(bm), int(slot)))


def _add_wheel(
    bm: bmesh.types.BMesh,
    slot_ranges: list[tuple[int, int, int]],
    *,
    center: Vector,
    radius: float,
    thickness: float,
    slot: int,
    phase: float,
) -> None:
    # The wheel sits in the XZ plane, thickness along Y.
    n = 14
    for i in range(n):
        a = phase + 2.0 * math.pi * i / n
        tangent = Vector((-math.sin(a), 0.0, math.cos(a)))
        radial = Vector((math.cos(a), 0.0, math.sin(a)))
        seg_center = center + radial * radius
        seg_len = radius * 2.0 * math.pi / n * 0.78
        _add_oriented_box(
            bm,
            slot_ranges,
            slot,
            seg_center,
            tangent * (seg_len * 0.5),
            Vector((0.0, thickness * 0.5, 0.0)),
            radial * 0.055,
        )
    for i in range(8):
        a = phase + 2.0 * math.pi * i / 8
        radial = Vector((math.cos(a), 0.0, math.sin(a)))
        spoke_center = center + radial * (radius * 0.42)
        _add_oriented_box(
            bm,
            slot_ranges,
            slot,
            spoke_center,
            radial * (radius * 0.42),
            Vector((0.0, thickness * 0.35, 0.0)),
            Vector((-radial.z, 0.0, radial.x)) * 0.035,
        )
    # Paddle boards mounted tangent to the rim.
    for i in range(8):
        a = phase + 2.0 * math.pi * (i + 0.5) / 8
        tangent = Vector((-math.sin(a), 0.0, math.cos(a)))
        radial = Vector((math.cos(a), 0.0, math.sin(a)))
        _add_oriented_box(
            bm,
            slot_ranges,
            slot,
            center + radial * (radius * 1.08),
            tangent * 0.27,
            Vector((0.0, thickness * 0.58, 0.0)),
            radial * 0.055,
        )
    _add_oriented_box(
        bm,
        slot_ranges,
        slot,
        center,
        Vector((0.17, 0.0, 0.0)),
        Vector((0.0, thickness * 0.60, 0.0)),
        Vector((0.0, 0.0, 0.17)),
    )


class LowPolyWatermillFactory(AssetFactory):
    """Low-poly watermill with side wheel and sluice.

    Constructor knobs:
        factory_seed
        watermill_archetype : "timber_river" | "stone_river" | "half_timber_mill"
        width, depth, wall_height, roof_height, wheel_radius
        wall_color, roof_color, wheel_color, trough_color, window_color
    """

    def __init__(
        self,
        factory_seed,
        watermill_archetype: str = "timber_river",
        width: float | None = None,
        depth: float | None = None,
        wall_height: float | None = None,
        roof_height: float | None = None,
        wheel_radius: float | None = None,
        wall_color: str | None = None,
        roof_color: str | None = None,
        wheel_color: str | None = None,
        trough_color: str | None = None,
        window_color: str | None = None,
        coarse: bool = False,
        **_unused_kwargs,
    ) -> None:
        super().__init__(factory_seed, coarse=coarse)
        if _unused_kwargs:
            from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
            accept_unused_kwargs("LowPolyWatermillFactory", _unused_kwargs)
        if watermill_archetype not in _WATERMILL_ARCHETYPES:
            import sys
            print(
                f"[watermill_archetype] WARN: unknown {watermill_archetype!r}; "
                f"falling back to {_WATERMILL_ARCHETYPES[0]!r}. "
                f"Valid: {_WATERMILL_ARCHETYPES}",
                file=sys.stderr,
            )
            watermill_archetype = _WATERMILL_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[watermill_archetype]
        self.watermill_archetype = watermill_archetype
        self.width = float(width if width is not None else d["width"])
        self.depth = float(depth if depth is not None else d["depth"])
        self.wall_height = float(wall_height if wall_height is not None else d["wall_height"])
        self.roof_height = float(roof_height if roof_height is not None else d["roof_height"])
        self.wheel_radius = float(wheel_radius if wheel_radius is not None else d["wheel_radius"])
        self.wall_color = wall_color or d["wall_color"]
        self.roof_color = roof_color or d["roof_color"]
        self.wheel_color = wheel_color or d["wheel_color"]
        self.trough_color = trough_color or d["trough_color"]
        self.window_color = window_color or d["window_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(f"LowPolyWatermill({self.factory_seed})_placeholder", None)
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        rng = random.Random(int(self.factory_seed))
        bm = bmesh.new()
        slot_ranges: list[tuple[int, int, int]] = []
        W, D, H = self.width, self.depth, self.wall_height

        _add_box(bm, slot_ranges, 0, (0.0, 0.0, H * 0.5), (W, D, H))
        _add_gabled_roof(
            bm,
            slot_ranges,
            1,
            width=W,
            depth=D,
            z=H,
            height=self.roof_height,
            overhang=0.34,
        )

        # Wheel side housing and water wheel.
        side_y = -D * 0.5 - 0.28
        wheel_center = Vector((W * 0.27, side_y - 0.16, self.wheel_radius + 0.18))
        _add_box(
            bm,
            slot_ranges,
            3,
            (wheel_center.x, side_y + 0.03, wheel_center.z),
            (self.wheel_radius * 2.15, 0.18, self.wheel_radius * 2.05),
        )
        _add_wheel(
            bm,
            slot_ranges,
            center=wheel_center,
            radius=self.wheel_radius,
            thickness=0.34,
            slot=2,
            phase=rng.uniform(-0.12, 0.12),
        )
        # Sluice trough leading into the wheel.
        _add_oriented_box(
            bm,
            slot_ranges,
            3,
            Vector((wheel_center.x - self.wheel_radius * 0.78, side_y - 0.54, wheel_center.z + self.wheel_radius * 0.52)),
            Vector((self.wheel_radius * 0.95, 0.0, -0.12)),
            Vector((0.0, 0.16, 0.0)),
            Vector((0.0, 0.0, 0.08)),
        )

        # Door and windows.
        _add_box(bm, slot_ranges, 2, (-W * 0.34, -D * 0.5 - 0.03, 0.82), (0.74, 0.06, 1.42))
        for x in (-W * 0.15, W * 0.25):
            _add_box(bm, slot_ranges, 4, (x, D * 0.5 + 0.03, H * 0.58), (0.55, 0.06, 0.62))
        _add_box(bm, slot_ranges, 4, (-W * 0.46, 0.0, H * 0.60), (0.06, 0.58, 0.62))

        if self.watermill_archetype == "half_timber_mill":
            # Timber braces over stucco walls.
            for y in (-D * 0.5 - 0.04, D * 0.5 + 0.04):
                _add_box(bm, slot_ranges, 2, (0.0, y, H * 0.50), (W * 0.92, 0.07, 0.08))
                _add_box(bm, slot_ranges, 2, (-W * 0.28, y, H * 0.50), (0.08, 0.07, H * 0.76))
                _add_box(bm, slot_ranges, 2, (W * 0.28, y, H * 0.50), (0.08, 0.07, H * 0.76))

        me = bpy.data.meshes.new(f"LowPolyWatermill({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()
        obj = bpy.data.objects.new(f"LowPolyWatermill({self.factory_seed})", me)
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
                self.wheel_color,
                self.trough_color,
                self.window_color,
            ],
        )
        return obj

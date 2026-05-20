"""LowPolyWatchtowerFactory — freestanding stone tower with parapet.

Requested 2026-05-06 (1 attempt, watchtower scene). Reads as "this is
where guards watch from" — fits castle compounds, abandoned cliffs,
coastal headlands, monastery perimeter walls.

Archetypes:
  round_stone — octagonal stone shaft, conical wooden roof, battlements
                between shaft and roof. Classic "fairy-tale" silhouette.
  square_keep — square stone tower, flat crenellated top, taller door,
                no roof. Reads more military / Norman.

Material slots:
  slot 0 = stone (rock_pale by default)
  slot 1 = wood (door)
  slot 2 = roof (rock_shadow — used by round_stone only)
  slot 3 = shadow / stone trim
"""

from __future__ import annotations

import math

import bmesh
import bpy

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_WATCHTOWER_ARCHETYPES = ("round_stone", "square_keep")


_ARCHETYPE_DEFAULTS = {
    "round_stone": dict(
        shaft_radius=1.10, shaft_height=4.20, n_sides=8,
        crenel_height=0.40, crenel_count=8,
        roof_height=1.60, roof_overhang=0.20,
        door_width=0.55, door_height=1.10,
        plinth_height=0.34, plinth_overhang=0.16,
        band_height=0.12, window_count=4,
        window_width=0.16, window_height=0.55,
        stone_color="rock_pale", wood_color="wood", roof_color="rock_shadow",
        trim_color="rock_shadow",
    ),
    "square_keep": dict(
        shaft_radius=1.20, shaft_height=4.80, n_sides=4,
        crenel_height=0.46, crenel_count=12,
        roof_height=0.0, roof_overhang=0.0,
        door_width=0.60, door_height=1.30,
        plinth_height=0.42, plinth_overhang=0.20,
        band_height=0.14, window_count=6,
        window_width=0.18, window_height=0.62,
        stone_color="rock_cool", wood_color="wood", roof_color="rock_shadow",
        trim_color="rock_shadow",
    ),
}


def _bm_face_count(bm) -> int:
    return len(bm.faces)


def _add_box(bm, slot_ranges, slot, cx, cy, cz, sx, sy, sz):
    start = _bm_face_count(bm)
    hx, hy, hz = sx / 2, sy / 2, sz / 2
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
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))


def _add_cardinal_patch(
    bm, slot_ranges, slot,
    side: str,
    radius: float,
    z: float,
    width: float,
    height: float,
    thickness: float = 0.035,
) -> None:
    """Add a small rectangular patch to one cardinal side of the tower.

    This avoids arbitrary rotated boxes while still giving the tower
    readable arrow slits from normal isometric cameras.
    """
    r = radius + thickness * 0.55
    if side == "+y":
        _add_box(bm, slot_ranges, slot, 0.0, r, z, width, thickness, height)
    elif side == "-y":
        _add_box(bm, slot_ranges, slot, 0.0, -r, z, width, thickness, height)
    elif side == "+x":
        _add_box(bm, slot_ranges, slot, r, 0.0, z, thickness, width, height)
    elif side == "-x":
        _add_box(bm, slot_ranges, slot, -r, 0.0, z, thickness, width, height)


def _add_prism(bm, slot_ranges, slot, cz, radius, height, n_sides, *, capped_top=True):
    """Vertical n-sided prism — used for the tower shaft. Cap top optional
    so the square_keep flat-top can have its own crenellated rim added
    on top without two coincident faces."""
    start = _bm_face_count(bm)
    bot = []
    top = []
    for s in range(n_sides):
        a = 2 * math.pi * s / n_sides
        x, y = radius * math.cos(a), radius * math.sin(a)
        bot.append(bm.verts.new((x, y, cz)))
        top.append(bm.verts.new((x, y, cz + height)))
    bm.verts.ensure_lookup_table()
    for s in range(n_sides):
        ns = (s + 1) % n_sides
        bm.faces.new((bot[s], bot[ns], top[ns], top[s]))
    # Bottom n-gon (face winding flipped so normal points down).
    bm.faces.new(list(reversed(bot)))
    if capped_top:
        bm.faces.new(top)
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))


def _add_cone(bm, slot_ranges, slot, cz, base_radius, tip_height, n_sides):
    """Conical roof — n triangles meeting at an apex above (0,0)."""
    start = _bm_face_count(bm)
    rim = []
    for s in range(n_sides):
        a = 2 * math.pi * s / n_sides
        x, y = base_radius * math.cos(a), base_radius * math.sin(a)
        rim.append(bm.verts.new((x, y, cz)))
    apex = bm.verts.new((0.0, 0.0, cz + tip_height))
    bm.verts.ensure_lookup_table()
    for s in range(n_sides):
        ns = (s + 1) % n_sides
        bm.faces.new((rim[s], rim[ns], apex))
    # Bottom rim n-gon (faces down so the roof underside reads dark from
    # below).
    bm.faces.new(list(reversed(rim)))
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))


class LowPolyWatchtowerFactory(AssetFactory):
    """A stone watchtower — octagonal or square shaft, battlements,
    optional conical roof.

    Constructor knobs:
        factory_seed
        watchtower_archetype : "round_stone" | "square_keep"
        shaft_radius, shaft_height : float
        n_sides : int (cylinder shaft segments)
        crenel_height : float
        crenel_count : int (number of merlons around the rim)
        roof_height, roof_overhang : float (0 → no roof)
        door_width, door_height : float
        plinth_height, plinth_overhang : float
        band_height : float
        window_count, window_width, window_height : arrow-slit details
        stone_color, wood_color, roof_color, trim_color : palette keys
    """

    def __init__(
        self,
        factory_seed,
        watchtower_archetype: str = "round_stone",
        shaft_radius: float | None = None,
        shaft_height: float | None = None,
        n_sides: int | None = None,
        crenel_height: float | None = None,
        crenel_count: int | None = None,
        roof_height: float | None = None,
        roof_overhang: float | None = None,
        door_width: float | None = None,
        door_height: float | None = None,
        plinth_height: float | None = None,
        plinth_overhang: float | None = None,
        band_height: float | None = None,
        window_count: int | None = None,
        window_width: float | None = None,
        window_height: float | None = None,
        stone_color: str | None = None,
        wood_color: str | None = None,
        roof_color: str | None = None,
        trim_color: str | None = None,
        coarse: bool = False,
        **_unused_kwargs,
    ):
        from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
        accept_unused_kwargs("LowPolyWatchtowerFactory", _unused_kwargs)
        super().__init__(factory_seed, coarse=coarse)
        if watchtower_archetype not in _WATCHTOWER_ARCHETYPES:
            import sys
            print(
                f"[watchtower_archetype] WARN: unknown {watchtower_archetype!r}; "
                f"falling back to {_WATCHTOWER_ARCHETYPES[0]!r}. "
                f"Valid: {_WATCHTOWER_ARCHETYPES}",
                file=sys.stderr,
            )
            watchtower_archetype = _WATCHTOWER_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[watchtower_archetype]
        self.watchtower_archetype = watchtower_archetype
        self.shaft_radius = float(shaft_radius if shaft_radius is not None else d["shaft_radius"])
        self.shaft_height = float(shaft_height if shaft_height is not None else d["shaft_height"])
        self.n_sides = int(n_sides if n_sides is not None else d["n_sides"])
        self.crenel_height = float(crenel_height if crenel_height is not None else d["crenel_height"])
        self.crenel_count = int(crenel_count if crenel_count is not None else d["crenel_count"])
        self.roof_height = float(roof_height if roof_height is not None else d["roof_height"])
        self.roof_overhang = float(roof_overhang if roof_overhang is not None else d["roof_overhang"])
        self.door_width = float(door_width if door_width is not None else d["door_width"])
        self.door_height = float(door_height if door_height is not None else d["door_height"])
        self.plinth_height = float(plinth_height if plinth_height is not None else d["plinth_height"])
        self.plinth_overhang = float(plinth_overhang if plinth_overhang is not None else d["plinth_overhang"])
        self.band_height = float(band_height if band_height is not None else d["band_height"])
        self.window_count = int(window_count if window_count is not None else d["window_count"])
        self.window_width = float(window_width if window_width is not None else d["window_width"])
        self.window_height = float(window_height if window_height is not None else d["window_height"])
        self.stone_color = stone_color or d["stone_color"]
        self.wood_color = wood_color or d["wood_color"]
        self.roof_color = roof_color or d["roof_color"]
        self.trim_color = trim_color or d["trim_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyWatchtower({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        bm = bmesh.new()
        slot_ranges: list[tuple[int, int, int]] = []

        # 1. Base plinth + shaft. The plinth seats hero-scale towers into
        # the terrain instead of leaving a plain tube poked through it.
        base_z = max(0.0, self.plinth_height)
        if base_z > 0:
            _add_prism(
                bm, slot_ranges, 0,
                cz=0.0,
                radius=self.shaft_radius + self.plinth_overhang,
                height=base_z,
                n_sides=max(self.n_sides, 8),
                capped_top=True,
            )

        # capped_top=False because the crenellation ring sits on top.
        _add_prism(
            bm, slot_ranges, 0,
            cz=base_z, radius=self.shaft_radius,
            height=self.shaft_height, n_sides=self.n_sides,
            capped_top=False,
        )
        # Darker stone courses break up the plain shaft and read as
        # masonry bands from the default isometric camera.
        for t in (0.36, 0.70):
            _add_prism(
                bm, slot_ranges, 3,
                cz=base_z + self.shaft_height * t,
                radius=self.shaft_radius * 1.012,
                height=self.band_height,
                n_sides=self.n_sides,
                capped_top=True,
            )
        # A flat cap at shaft top — sits BELOW the crenellations to close
        # the shaft's interior view, so peering between merlons doesn't
        # reveal a hollow tube.
        cap_z = base_z + self.shaft_height
        _add_prism(
            bm, slot_ranges, 0,
            cz=cap_z - 0.05, radius=self.shaft_radius * 0.97,
            height=0.05, n_sides=self.n_sides, capped_top=True,
        )

        # 2. Crenellations — merlons evenly spaced around the rim. Each
        # merlon is a small box tangent to the rim.
        c = self.crenel_count
        for i in range(c):
            a = 2 * math.pi * (i + 0.5) / c
            cx = self.shaft_radius * 0.92 * math.cos(a)
            cy = self.shaft_radius * 0.92 * math.sin(a)
            # Merlon footprint: ~circumference/(2c) wide tangentially,
            # narrow radially so it reads as a "tooth" on the wall.
            tangential = (2 * math.pi * self.shaft_radius) / (c * 2.1)
            box_w = max(0.22, tangential)
            box_d = 0.30
            _add_box(
                bm, slot_ranges, 0,
                cx, cy, cap_z + self.crenel_height / 2,
                box_w, box_d, self.crenel_height,
            )

        # 3. Optional conical roof above the battlements.
        if self.roof_height > 0:
            roof_z = cap_z + self.crenel_height + 0.02
            roof_n = max(self.n_sides, 8)
            _add_cone(
                bm, slot_ranges, 2,
                cz=roof_z,
                base_radius=self.shaft_radius + self.roof_overhang,
                tip_height=self.roof_height,
                n_sides=roof_n,
            )

        # 4. Door at the base — a flat rectangular "patch" pasted onto
        # the shaft. Wood-colored so it reads against the stone. Y-axis
        # so it's on the +Y face (faces the camera at default azimuth).
        door_y = self.shaft_radius * 0.99
        _add_box(
            bm, slot_ranges, 1,
            0.0, door_y, base_z + self.door_height / 2,
            self.door_width, 0.04, self.door_height,
        )

        # 5. Arrow slits. These are small dark patches on cardinal faces,
        # avoiding rotated geometry while giving the tower a readable
        # fortified surface.
        sides = ["+y", "-x", "+x", "-y"]
        for i in range(max(0, self.window_count)):
            side = sides[i % len(sides)]
            level = 0.42 if i < len(sides) else 0.66
            _add_cardinal_patch(
                bm, slot_ranges, 3,
                side=side,
                radius=self.shaft_radius,
                z=base_z + self.shaft_height * level,
                width=self.window_width,
                height=self.window_height,
            )

        me = bpy.data.meshes.new(f"LowPolyWatchtower({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(
            f"LowPolyWatchtower({self.factory_seed})", me,
        )
        bpy.context.scene.collection.objects.link(obj)
        while len(obj.data.materials) < 4:
            obj.data.materials.append(None)
        for start, end, slot in slot_ranges:
            for i in range(start, end):
                obj.data.polygons[i].material_index = slot
        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(
            obj,
            [self.stone_color, self.wood_color, self.roof_color, self.trim_color],
        )
        return obj

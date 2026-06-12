"""LowPolyWagonFactory — covered prairie schooner / buckboard / handcart.

Wild West / pioneer / agricultural prop. Reads as cargo, settler
journey, or farm vehicle silhouette. Replaces the stall+barrel
cluster stand-in the Maquette pipeline used while this factory was
missing.

Archetypes:
  prairie_schooner — Conestoga-style covered wagon. Arched canvas
                     cover, 4 wheels, wagon tongue. Iconic settler
                     silhouette.
  buckboard        — open flat-bed wagon. 4 wheels, tongue, no cover.
  handcart         — small 2-wheeled cart with handles trailing
                     backward. Hand-drawn cargo hauler.

Knobs let the caller toggle the cover, tongue, and handles, plus
resize the body and wheels.

Material slots:
  slot 0 = wooden body / sideboards / tongue / handles / wheel hubs
           (default `wood`)
  slot 1 = wheel rims / iron bands           (default `rust_metal`)
  slot 2 = canvas cover                      (default `stucco`)
"""

from __future__ import annotations

import math

import bmesh
import bpy

from infinigen.core.placement.factory import AssetFactory

from ...density import n_along_axis, n_sides_for_radius, target_edge_for_bbox
from ...materials import apply_palette_slots


_WAGON_ARCHETYPES = ("prairie_schooner", "buckboard", "handcart")


# n_wheel_sides + cover arc/along subdivisions are bbox-derived. Defaults
# below are dimensional + behavioral only.
_ARCHETYPE_DEFAULTS = {
    "prairie_schooner": dict(
        length=2.6, width=1.2, body_height=0.45,
        n_axles=2,
        wheel_radius=0.50, wheel_thickness=0.10,
        has_cover=True,
        has_tongue=True, tongue_length=1.4,
        has_handles=False, handle_length=0.0,
        body_color="wood", wheel_color="rust_metal", cover_color="stucco",
    ),
    "buckboard": dict(
        length=2.4, width=1.1, body_height=0.30,
        n_axles=2,
        wheel_radius=0.46, wheel_thickness=0.08,
        has_cover=False,
        has_tongue=True, tongue_length=1.4,
        has_handles=False, handle_length=0.0,
        body_color="wood", wheel_color="rust_metal", cover_color="stucco",
    ),
    "handcart": dict(
        length=1.3, width=0.75, body_height=0.30,
        n_axles=1,
        wheel_radius=0.40, wheel_thickness=0.07,
        has_cover=False,
        has_tongue=False, tongue_length=0.0,
        has_handles=True, handle_length=1.1,
        body_color="wood", wheel_color="rust_metal", cover_color="stucco",
    ),
}


def _bm_face_count(bm) -> int:
    return len(bm.faces)


def _add_box(bm, cx, cy, cz, sx, sy, sz) -> int:
    n_before = _bm_face_count(bm)
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
    return _bm_face_count(bm) - n_before


def _add_box_slot(bm, slot_ranges, slot, cx, cy, cz, sx, sy, sz) -> None:
    s = _bm_face_count(bm)
    _add_box(bm, cx, cy, cz, sx, sy, sz)
    e = _bm_face_count(bm)
    slot_ranges.append((s, e, slot))


def _add_wheel(
    bm, slot_ranges,
    rim_slot, hub_slot,
    cx, cy, cz,
    radius, thickness, n_sides,
) -> None:
    """A spoked wheel with axis along Y: an open rim ring (outer + inner
    band with side rings), two crossing spoke bars, and a proud hub box.
    Solid-disc wheels read as drums; the open ring + spokes is what makes
    a cart read as a cart."""
    start = _bm_face_count(bm)
    y0 = cy - thickness / 2
    y1 = cy + thickness / 2
    inner_r = radius * 0.74
    outer0, outer1, inner0, inner1 = [], [], [], []
    for s in range(n_sides):
        a = 2 * math.pi * s / n_sides
        ox = cx + radius * math.cos(a)
        oz = cz + radius * math.sin(a)
        ix = cx + inner_r * math.cos(a)
        iz = cz + inner_r * math.sin(a)
        outer0.append(bm.verts.new((ox, y0, oz)))
        outer1.append(bm.verts.new((ox, y1, oz)))
        inner0.append(bm.verts.new((ix, y0, iz)))
        inner1.append(bm.verts.new((ix, y1, iz)))
    bm.verts.ensure_lookup_table()
    for s in range(n_sides):
        ns = (s + 1) % n_sides
        # Tread (outer band) + inner band + the two side rings.
        bm.faces.new((outer0[s], outer0[ns], outer1[ns], outer1[s]))
        bm.faces.new((inner1[s], inner1[ns], inner0[ns], inner0[s]))
        bm.faces.new((outer0[ns], outer0[s], inner0[s], inner0[ns]))
        bm.faces.new((outer1[s], outer1[ns], inner1[ns], inner1[s]))
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, rim_slot))

    # Two crossing spoke bars (reads as 4 spokes) + proud hub box.
    spoke_t = max(0.045, radius * 0.16)
    spoke_y = thickness * 0.72
    _add_box_slot(bm, slot_ranges, hub_slot,
                  cx, cy, cz, (inner_r + 0.02) * 2, spoke_y, spoke_t)
    _add_box_slot(bm, slot_ranges, hub_slot,
                  cx, cy, cz, spoke_t, spoke_y, (inner_r + 0.02) * 2)
    hub_size = radius * 0.32
    _add_box_slot(
        bm, slot_ranges, hub_slot,
        cx, cy, cz,
        hub_size, thickness * 1.7, hub_size,
    )


def _add_arched_cover(
    bm, slot_ranges, slot,
    x_min: float, x_max: float,
    width: float, base_z: float,
    n_arc: int, n_along: int,
) -> None:
    """Half-cylinder canvas cover spanning x_min..x_max in X, with a
    semicircular profile of radius width/2 centered at z=base_z. End caps
    are filled half-discs (triangle fans), so the cover reads as a closed
    canvas tunnel rather than an open arch."""
    if n_arc < 2 or n_along < 1:
        return
    radius = width / 2
    start = _bm_face_count(bm)
    grid: list[list] = []
    for i in range(n_along + 1):
        x = x_min + (x_max - x_min) * i / n_along
        row = []
        for j in range(n_arc + 1):
            theta = math.pi * j / n_arc
            y = -radius * math.cos(theta)
            z = base_z + radius * math.sin(theta)
            row.append(bm.verts.new((x, y, z)))
        grid.append(row)
    bm.verts.ensure_lookup_table()
    for i in range(n_along):
        for j in range(n_arc):
            v00 = grid[i][j]
            v10 = grid[i + 1][j]
            v11 = grid[i + 1][j + 1]
            v01 = grid[i][j + 1]
            bm.faces.new((v00, v10, v11, v01))
    # Front cap (x = x_max), normals +X — wind so e1 × e2 = +X.
    front_center = bm.verts.new((x_max, 0, base_z))
    bm.verts.ensure_lookup_table()
    front_row = grid[-1]
    for j in range(n_arc):
        bm.faces.new((front_center, front_row[j + 1], front_row[j]))
    # Back cap (x = x_min), normals -X.
    back_center = bm.verts.new((x_min, 0, base_z))
    bm.verts.ensure_lookup_table()
    back_row = grid[0]
    for j in range(n_arc):
        bm.faces.new((back_center, back_row[j], back_row[j + 1]))
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))


class LowPolyWagonFactory(AssetFactory):
    """A covered prairie schooner / open buckboard / handcart.

    Layout convention: length axis is X (front of wagon at +X). Wheel
    axles are along Y. The body sits above its wheels — body bottom at
    z = wheel_radius — so the asset rests on z=0 ground naturally.

    Constructor knobs:

        factory_seed
        wagon_archetype : str = "prairie_schooner"
                          "prairie_schooner" | "buckboard" | "handcart"
        length, width, body_height : floats
        n_axles         : int    1 (handcart) or 2 (front + back wheels)
        wheel_radius    : float
        wheel_thickness : float
        n_wheel_sides   : int    flat-cylinder side count
        has_cover       : bool   arched canvas top
        cover_n_arc     : int    cover arc segment count
        cover_n_along   : int    cover along-length segment count
        has_tongue      : bool   forward draft pole
        tongue_length   : float
        has_handles     : bool   trailing handcart handles
        handle_length   : float
        body_color      : str    slot 0
        wheel_color     : str    slot 1
        cover_color     : str    slot 2
    """

    def __init__(
        self,
        factory_seed,
        wagon_archetype: str = "prairie_schooner",
        length: float | None = None,
        width: float | None = None,
        body_height: float | None = None,
        polygon_multiplier: float = 1.0,
        target_edge: float | None = None,
        n_axles: int | None = None,
        wheel_radius: float | None = None,
        wheel_thickness: float | None = None,
        n_wheel_sides: int | None = None,
        has_cover: bool | None = None,
        cover_n_arc: int | None = None,
        cover_n_along: int | None = None,
        has_tongue: bool | None = None,
        tongue_length: float | None = None,
        has_handles: bool | None = None,
        handle_length: float | None = None,
        body_color: str | None = None,
        wheel_color: str | None = None,
        cover_color: str | None = None,
        coarse: bool = False,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if wagon_archetype not in _WAGON_ARCHETYPES:
            # Lenient fallback rather than crash. Sonnet has been
            # observed to hallucinate plausible-sounding archetype
            # names despite the factories_guide brief listing the
            # valid set; killing a 6-minute build over a one-line
            # archetype typo wastes a generation. Substitute the
            # canonical default and warn to stderr.
            import sys
            print(
                f"[wagon_archetype] WARN: unknown wagon_archetype "
                f"{wagon_archetype!r}; falling back to {_WAGON_ARCHETYPES[0]!r}. "
                f"Valid: {_WAGON_ARCHETYPES}",
                file=sys.stderr,
            )
            wagon_archetype = _WAGON_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[wagon_archetype]
        self.wagon_archetype = wagon_archetype
        self.length = float(length if length is not None else d["length"])
        self.width = float(width if width is not None else d["width"])
        self.body_height = float(
            body_height if body_height is not None else d["body_height"]
        )
        self.n_axles = int(n_axles if n_axles is not None else d["n_axles"])
        self.wheel_radius = float(
            wheel_radius if wheel_radius is not None else d["wheel_radius"]
        )
        self.wheel_thickness = float(
            wheel_thickness if wheel_thickness is not None else d["wheel_thickness"]
        )
        # Bbox-derive wheel + cover subdivisions from the wagon body envelope.
        edge = (
            float(target_edge) if target_edge is not None
            else target_edge_for_bbox(
                (self.length, self.width,
                 self.body_height + self.wheel_radius * 2),
                polygon_multiplier=polygon_multiplier,
            )
        )
        self.n_wheel_sides = int(
            n_wheel_sides if n_wheel_sides is not None
            else n_sides_for_radius(self.wheel_radius, edge, min_n=8)
        )
        self.has_cover = (
            bool(has_cover) if has_cover is not None else d["has_cover"]
        )
        # Cover arc spans ~half a circle of cover_radius ≈ width/2; along
        # spans the wagon length.
        cover_arc_span = math.pi * (self.width / 2)
        self.cover_n_arc = int(
            cover_n_arc if cover_n_arc is not None
            else (n_along_axis(cover_arc_span, edge, min_n=4)
                  if self.has_cover else 0)
        )
        self.cover_n_along = int(
            cover_n_along if cover_n_along is not None
            else (n_along_axis(self.length, edge, min_n=2)
                  if self.has_cover else 0)
        )
        self.has_tongue = (
            bool(has_tongue) if has_tongue is not None else d["has_tongue"]
        )
        self.tongue_length = float(
            tongue_length if tongue_length is not None else d["tongue_length"]
        )
        self.has_handles = (
            bool(has_handles) if has_handles is not None else d["has_handles"]
        )
        self.handle_length = float(
            handle_length if handle_length is not None else d["handle_length"]
        )
        self.body_color = body_color or d["body_color"]
        self.wheel_color = wheel_color or d["wheel_color"]
        self.cover_color = cover_color or d["cover_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyWagon({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        bm = bmesh.new()
        slot_ranges: list[tuple[int, int, int]] = []

        L, W, BH = self.length, self.width, self.body_height
        wr = self.wheel_radius
        wt = self.wheel_thickness
        body_bottom_z = wr
        body_top_z = body_bottom_z + BH
        body_cz = (body_bottom_z + body_top_z) / 2

        # Wagon bed — main flat box
        _add_box_slot(
            bm, slot_ranges, 0,
            0, 0, body_cz,
            L, W, BH,
        )

        # Sideboards + endboards — short walls around the bed for an
        # open-top cargo box read. The handcart skips these (its body
        # already reads as a contained crate).
        if self.wagon_archetype != "handcart":
            wall_h = BH * 0.5
            wall_t = 0.05
            wall_cz = body_top_z + wall_h / 2
            for sign in (-1, 1):
                _add_box_slot(
                    bm, slot_ranges, 0,
                    0, sign * (W / 2 - wall_t / 2), wall_cz,
                    L, wall_t, wall_h,
                )
            for sign in (-1, 1):
                _add_box_slot(
                    bm, slot_ranges, 0,
                    sign * (L / 2 - wall_t / 2), 0, wall_cz,
                    wall_t, W - 2 * wall_t, wall_h,
                )

        # Wheels — sit just outside the body on either side along Y.
        wheel_cy = W / 2 + wt / 2
        wheel_cz = wr
        if self.n_axles >= 2:
            front_cx = L * 0.32
            back_cx = -L * 0.32
            for cx in (front_cx, back_cx):
                for sign in (-1, 1):
                    _add_wheel(
                        bm, slot_ranges, 1, 0,
                        cx, sign * wheel_cy, wheel_cz,
                        wr, wt, self.n_wheel_sides,
                    )
        elif self.n_axles == 1:
            for sign in (-1, 1):
                _add_wheel(
                    bm, slot_ranges, 1, 0,
                    0, sign * wheel_cy, wheel_cz,
                    wr, wt, self.n_wheel_sides,
                )

        # Canvas cover — arched half-cylinder spanning the bed, slightly
        # inset from the end boards so it doesn't poke past them.
        if self.has_cover and self.cover_n_arc > 0 and self.cover_n_along > 0:
            inset = 0.05
            cover_x_min = -L / 2 + inset
            cover_x_max = L / 2 - inset
            cover_w = W * 0.95
            _add_arched_cover(
                bm, slot_ranges, 2,
                cover_x_min, cover_x_max,
                cover_w, body_top_z,
                self.cover_n_arc, self.cover_n_along,
            )

        # Tongue — draft pole extending forward from the front (+X).
        if self.has_tongue and self.tongue_length > 0:
            t_thick = 0.08
            t_cx = L / 2 + self.tongue_length / 2
            _add_box_slot(
                bm, slot_ranges, 0,
                t_cx, 0, body_bottom_z + t_thick / 2,
                self.tongue_length, t_thick, t_thick,
            )

        # Handles — two parallel poles trailing back (-X) from the body
        # at gunwale height.
        if self.has_handles and self.handle_length > 0:
            h_thick = 0.05
            h_cx = -L / 2 - self.handle_length / 2
            for sign in (-1, 1):
                _add_box_slot(
                    bm, slot_ranges, 0,
                    h_cx, sign * (W / 2 - h_thick), body_top_z,
                    self.handle_length, h_thick, h_thick,
                )

        me = bpy.data.meshes.new(f"LowPolyWagon({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(f"LowPolyWagon({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)

        while len(obj.data.materials) < 3:
            obj.data.materials.append(None)

        for start, end, slot in slot_ranges:
            for i in range(start, end):
                obj.data.polygons[i].material_index = slot

        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(
            obj, [self.body_color, self.wheel_color, self.cover_color]
        )
        return obj

"""LowPolyCableCarFactory — gondola box hanging from a diagonal cable.

A single visible cable car / aerial-tram cabin suspended below a
diagonal cable segment. Reads as alpine ski resort, industrial mining
operation, or backcountry chairlift depending on archetype.

Archetypes:
  alpine_gondola  — Enclosed boxy passenger cabin (Firewatch / ski
                    resort silhouette). Curved hanger arm reaching up
                    to the cable. Pitched roof. Iconic gondola read.
  mining_bucket   — Rust open-topped ore bucket. No roof. Single
                    vertical hanger arm. Industrial / Wild West /
                    quarry feel.
  chair_lift      — Open seat + backrest. No walls, no roof. Single
                    hanger arm. Reads as backcountry / ski-lift chair.

Layout convention: cable runs along X axis. The cable is rendered as
a polyline along ±cable_length/2 at a diagonal — the +X end sits at
+cable_slope * cable_length/2 above the -X end, so the asset shows
the characteristic diagonal sag of a span between two pylons that
the caller has placed elsewhere. The gondola hangs below mid-span
(x=0) so its bottom rests at z=0; caller translates the whole asset
into world space.

Material slots:
  slot 0 = cabin body / seat / bucket walls   (default per archetype)
  slot 1 = cable + hanger arm + iron fittings (default `rust_metal`)
  slot 2 = roof / accent stripe / canopy      (default per archetype)
"""

from __future__ import annotations

import math

import bmesh
import bpy

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_CABLE_CAR_ARCHETYPES = ("alpine_gondola", "mining_bucket", "chair_lift")


_ARCHETYPE_DEFAULTS = {
    "alpine_gondola": dict(
        cabin_length=1.4, cabin_width=1.1, cabin_height=1.4,
        has_roof=True, roof_height=0.30,
        has_walls=True, wall_thickness=0.04,
        has_floor=True,
        hanger_length=0.9, hanger_thickness=0.10,
        cable_length=6.0, cable_slope=0.35, cable_thickness=0.06,
        n_cable_segments=12,
        body_color="stucco", cable_color="rust_metal", roof_color="accent_red",
    ),
    "mining_bucket": dict(
        cabin_length=1.1, cabin_width=1.0, cabin_height=0.85,
        has_roof=False, roof_height=0.0,
        has_walls=True, wall_thickness=0.05,
        has_floor=True,
        hanger_length=0.7, hanger_thickness=0.08,
        cable_length=5.5, cable_slope=0.30, cable_thickness=0.05,
        n_cable_segments=10,
        body_color="rust_metal", cable_color="rust_metal", roof_color="rock_shadow",
    ),
    "chair_lift": dict(
        cabin_length=1.0, cabin_width=0.9, cabin_height=0.5,
        has_roof=False, roof_height=0.0,
        has_walls=False, wall_thickness=0.0,
        has_floor=True,
        hanger_length=1.0, hanger_thickness=0.06,
        cable_length=5.0, cable_slope=0.40, cable_thickness=0.04,
        n_cable_segments=10,
        body_color="wood", cable_color="rust_metal", roof_color="accent_red",
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


def _add_pitched_roof(
    bm, slot_ranges, slot,
    cx: float, cy: float, base_z: float,
    sx: float, sy: float, sz: float,
) -> None:
    """A simple gabled / pitched roof: rectangular base at base_z with
    a ridge running along Y at z = base_z + sz. Two sloped roof planes
    plus two triangular gable ends. Used for alpine gondola cabins so
    the silhouette doesn't read as a featureless box."""
    start = _bm_face_count(bm)
    hx, hy = sx / 2, sy / 2
    z0 = base_z
    z1 = base_z + sz
    b00 = bm.verts.new((cx - hx, cy - hy, z0))
    b10 = bm.verts.new((cx + hx, cy - hy, z0))
    b11 = bm.verts.new((cx + hx, cy + hy, z0))
    b01 = bm.verts.new((cx - hx, cy + hy, z0))
    r0 = bm.verts.new((cx, cy - hy, z1))
    r1 = bm.verts.new((cx, cy + hy, z1))
    bm.verts.ensure_lookup_table()
    # Sloped roof planes
    bm.faces.new((b00, b10, r0))
    bm.faces.new((b11, b01, r1))
    bm.faces.new((b10, b11, r1, r0))
    bm.faces.new((b01, b00, r0, r1))
    # Floor (so the roof reads as solid from below if seen from underneath)
    bm.faces.new((b00, b01, b11, b10))
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))


def _add_diag_box(
    bm, slot_ranges, slot,
    x0: float, y0: float, z0: float,
    x1: float, y1: float, z1: float,
    thickness: float,
) -> None:
    """A thin box-section beam between (x0,y0,z0) and (x1,y1,z1). The
    cross-section is a `thickness`-square perpendicular to the X-Z
    plane (Y axis stays axis-aligned). Used for diagonal cable
    polyline segments and angled hanger arms."""
    if thickness <= 0:
        return
    dx = x1 - x0
    dz = z1 - z0
    seg_len = math.sqrt(dx * dx + dz * dz)
    if seg_len <= 0:
        return
    cx = (x0 + x1) / 2
    cy = (y0 + y1) / 2
    cz = (z0 + z1) / 2
    # Perpendicular in the X-Z plane, normalized.
    nx = -dz / seg_len
    nz = dx / seg_len
    half_t = thickness / 2
    half_y = thickness / 2
    half_l = seg_len / 2
    # Tangent (along the beam, X-Z plane)
    tx = dx / seg_len
    tz = dz / seg_len
    start = _bm_face_count(bm)

    def corner(s_t: float, s_n: float, s_y: float):
        x = cx + s_t * half_l * tx + s_n * half_t * nx
        y = cy + s_y * half_y
        z = cz + s_t * half_l * tz + s_n * half_t * nz
        return bm.verts.new((x, y, z))

    # 8 corners of the box: tangent (s_t = ±1) × normal (s_n = ±1) ×
    # Y (s_y = ±1).
    v_mnm = corner(-1, -1, -1); v_pnm = corner(+1, -1, -1)
    v_ppm = corner(+1, +1, -1); v_mpm = corner(-1, +1, -1)
    v_mnp = corner(-1, -1, +1); v_pnp = corner(+1, -1, +1)
    v_ppp = corner(+1, +1, +1); v_mpp = corner(-1, +1, +1)
    bm.verts.ensure_lookup_table()
    # -normal side (s_n = -1)
    bm.faces.new((v_mnm, v_pnm, v_pnp, v_mnp))
    # +normal side (s_n = +1)
    bm.faces.new((v_mpm, v_mpp, v_ppp, v_ppm))
    # +tangent end cap (s_t = +1)
    bm.faces.new((v_pnm, v_ppm, v_ppp, v_pnp))
    # -tangent end cap (s_t = -1)
    bm.faces.new((v_mnm, v_mnp, v_mpp, v_mpm))
    # -Y cap (s_y = -1)
    bm.faces.new((v_mnm, v_mpm, v_ppm, v_pnm))
    # +Y cap (s_y = +1)
    bm.faces.new((v_mnp, v_pnp, v_ppp, v_mpp))
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))


def _add_diagonal_cable(
    bm, slot_ranges, slot,
    cable_length: float, cable_slope: float, thickness: float,
    n_segments: int, attach_z: float,
) -> None:
    """Polyline cable spanning x ∈ [-L/2, +L/2] at a constant slope.
    The cable's mid-span (x=0) sits at z = attach_z, with the +X end
    higher and -X end lower by ±slope * L/2. Built as box segments so
    it reads as a continuous diagonal at low poly."""
    if n_segments <= 0 or thickness <= 0 or cable_length <= 0:
        return
    half = cable_length / 2
    for i in range(n_segments):
        t0 = i / n_segments
        t1 = (i + 1) / n_segments
        x0 = -half + cable_length * t0
        x1 = -half + cable_length * t1
        z0 = attach_z + (t0 - 0.5) * cable_slope * cable_length
        z1 = attach_z + (t1 - 0.5) * cable_slope * cable_length
        _add_diag_box(
            bm, slot_ranges, slot,
            x0, 0, z0, x1, 0, z1, thickness,
        )


class LowPolyCableCarFactory(AssetFactory):
    """A gondola / bucket / chair suspended below a diagonal cable.

    Layout: cable axis is X. The gondola hangs from the cable at
    midspan (x=0) so its bottom sits at z=0. A vertical (or diagonal)
    hanger arm connects the cabin's top to the cable. The cable runs
    diagonally — +X end is `cable_slope * cable_length / 2` above the
    midspan attach point, -X end the same below — so the asset visibly
    reads as suspended on a sloping line.

    Constructor knobs:

        factory_seed
        cable_car_archetype : str = "alpine_gondola"
                              "alpine_gondola" | "mining_bucket" | "chair_lift"
        cabin_length      : float
        cabin_width       : float
        cabin_height      : float
        has_roof          : bool      pitched roof on top of cabin
        roof_height       : float
        has_walls         : bool      side walls (false = open seat)
        wall_thickness    : float
        has_floor         : bool
        hanger_length     : float    vertical drop from cable to cabin top
        hanger_thickness  : float
        cable_length      : float    visible cable extent along X
        cable_slope       : float    rise/run of the cable
        cable_thickness   : float
        n_cable_segments  : int      polyline segment count
        body_color        : str   slot 0
        cable_color       : str   slot 1
        roof_color        : str   slot 2
    """

    def __init__(
        self,
        factory_seed,
        cable_car_archetype: str = "alpine_gondola",
        cabin_length: float | None = None,
        cabin_width: float | None = None,
        cabin_height: float | None = None,
        has_roof: bool | None = None,
        roof_height: float | None = None,
        has_walls: bool | None = None,
        wall_thickness: float | None = None,
        has_floor: bool | None = None,
        hanger_length: float | None = None,
        hanger_thickness: float | None = None,
        cable_length: float | None = None,
        cable_slope: float | None = None,
        cable_thickness: float | None = None,
        n_cable_segments: int | None = None,
        body_color: str | None = None,
        cable_color: str | None = None,
        roof_color: str | None = None,
        coarse: bool = False,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if cable_car_archetype not in _CABLE_CAR_ARCHETYPES:
            # Lenient fallback rather than crash. Sonnet has been
            # observed to hallucinate plausible-sounding archetype
            # names despite the factories_guide brief listing the
            # valid set; killing a 6-minute build over a one-line
            # archetype typo wastes a generation. Substitute the
            # canonical default and warn to stderr.
            import sys
            print(
                f"[cable_car_archetype] WARN: unknown cable_car_archetype "
                f"{cable_car_archetype!r}; falling back to {_CABLE_CAR_ARCHETYPES[0]!r}. "
                f"Valid: {_CABLE_CAR_ARCHETYPES}",
                file=sys.stderr,
            )
            cable_car_archetype = _CABLE_CAR_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[cable_car_archetype]
        self.cable_car_archetype = cable_car_archetype
        self.cabin_length = float(
            cabin_length if cabin_length is not None else d["cabin_length"]
        )
        self.cabin_width = float(
            cabin_width if cabin_width is not None else d["cabin_width"]
        )
        self.cabin_height = float(
            cabin_height if cabin_height is not None else d["cabin_height"]
        )
        self.has_roof = (
            bool(has_roof) if has_roof is not None else d["has_roof"]
        )
        self.roof_height = float(
            roof_height if roof_height is not None else d["roof_height"]
        )
        self.has_walls = (
            bool(has_walls) if has_walls is not None else d["has_walls"]
        )
        self.wall_thickness = float(
            wall_thickness if wall_thickness is not None else d["wall_thickness"]
        )
        self.has_floor = (
            bool(has_floor) if has_floor is not None else d["has_floor"]
        )
        self.hanger_length = float(
            hanger_length if hanger_length is not None else d["hanger_length"]
        )
        self.hanger_thickness = float(
            hanger_thickness if hanger_thickness is not None else d["hanger_thickness"]
        )
        self.cable_length = float(
            cable_length if cable_length is not None else d["cable_length"]
        )
        self.cable_slope = float(
            cable_slope if cable_slope is not None else d["cable_slope"]
        )
        self.cable_thickness = float(
            cable_thickness if cable_thickness is not None else d["cable_thickness"]
        )
        self.n_cable_segments = int(
            n_cable_segments if n_cable_segments is not None else d["n_cable_segments"]
        )
        self.body_color = body_color or d["body_color"]
        self.cable_color = cable_color or d["cable_color"]
        self.roof_color = roof_color or d["roof_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyCableCar({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        bm = bmesh.new()
        slot_ranges: list[tuple[int, int, int]] = []

        L = self.cabin_length
        W = self.cabin_width
        H = self.cabin_height
        wt = max(self.wall_thickness, 0.0)

        cabin_bottom_z = 0.0
        cabin_top_z = cabin_bottom_z + H

        # Floor — solid slab at the cabin base. Open seats still want a
        # floor so the chair has something to sit on.
        if self.has_floor:
            floor_t = max(wt, 0.04)
            _add_box_slot(
                bm, slot_ranges, 0,
                0, 0, cabin_bottom_z + floor_t / 2,
                L, W, floor_t,
            )

        # Walls — four thin walls on the cabin perimeter. For chair_lift
        # we skip walls (open seat read).
        if self.has_walls and wt > 0 and H > 0:
            wall_h = H - (max(wt, 0.04) if self.has_floor else 0.0)
            wall_cz = cabin_bottom_z + (max(wt, 0.04) if self.has_floor else 0.0) + wall_h / 2
            # +Y / -Y walls
            for sign in (-1, 1):
                _add_box_slot(
                    bm, slot_ranges, 0,
                    0, sign * (W / 2 - wt / 2), wall_cz,
                    L, wt, wall_h,
                )
            # +X / -X walls (shorter so corners don't double up)
            for sign in (-1, 1):
                _add_box_slot(
                    bm, slot_ranges, 0,
                    sign * (L / 2 - wt / 2), 0, wall_cz,
                    wt, W - 2 * wt, wall_h,
                )

        # Backrest for the chair_lift archetype — a vertical board
        # behind the seat (at -X side) so the open chair has a clear
        # "this is a seat" silhouette.
        if not self.has_walls and self.has_floor:
            back_h = max(H * 0.9, 0.4)
            back_t = 0.05
            back_cz = cabin_bottom_z + back_h / 2
            _add_box_slot(
                bm, slot_ranges, 0,
                -L / 2 + back_t / 2, 0, back_cz,
                back_t, W, back_h,
            )

        # Roof — pitched gable for the alpine gondola. Other archetypes
        # skip the roof; mining bucket reads as open-topped.
        if self.has_roof and self.roof_height > 0:
            _add_pitched_roof(
                bm, slot_ranges, 2,
                0, 0, cabin_top_z,
                L * 1.04, W * 1.04, self.roof_height,
            )
            cable_attach_top = cabin_top_z + self.roof_height
        else:
            cable_attach_top = cabin_top_z

        # Hanger arm — vertical thin box from cabin top up to the
        # cable. Slot 1 (cable / iron color).
        hanger_bottom_z = cable_attach_top
        hanger_top_z = hanger_bottom_z + self.hanger_length
        if self.hanger_length > 0 and self.hanger_thickness > 0:
            _add_box_slot(
                bm, slot_ranges, 1,
                0, 0, (hanger_bottom_z + hanger_top_z) / 2,
                self.hanger_thickness, self.hanger_thickness,
                self.hanger_length,
            )

        # Cable — diagonal polyline anchored at the top of the hanger.
        _add_diagonal_cable(
            bm, slot_ranges, 1,
            self.cable_length, self.cable_slope, self.cable_thickness,
            self.n_cable_segments, hanger_top_z,
        )

        me = bpy.data.meshes.new(f"LowPolyCableCar({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(
            f"LowPolyCableCar({self.factory_seed})", me
        )
        bpy.context.scene.collection.objects.link(obj)

        while len(obj.data.materials) < 3:
            obj.data.materials.append(None)

        for start, end, slot in slot_ranges:
            for i in range(start, end):
                obj.data.polygons[i].material_index = slot

        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(
            obj, [self.body_color, self.cable_color, self.roof_color]
        )
        return obj

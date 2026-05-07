"""LowPolyBoatFactory — rowboat / dinghy / pirate brig.

Top coastal-scene factory per Attempt 13 + Attempt 4 (fishing village).
Without boats, any waterfront scene reads as "village by water" instead
of "fishing harbor" / "pirate cove" / "river crossing".

Archetypes:
  rowboat       — small open boat, 2 thwart seats, 2 oars on the side
                  (~2.5m long, fishing village or moored at piers)
  dinghy        — bare-bones hull, no seats, no oars — beached or
                  upturned (~1.8m long, scattered prop)
  pirate_brig   — larger ship-shaped hull + mast + square sail
                  + bowsprit (~5m long, the "pirate ship at anchor"
                  silhouette)

Knobs let the caller resize freely; hull proportions auto-scale.

Material slots:
  slot 0 = hull (planks)            (default `wood`)
  slot 1 = trim / mast / oar handles (default `rust_metal`)
  slot 2 = sail / cloth             (default `stucco` — off-white)
"""

from __future__ import annotations

import math

import bmesh
import bpy
from mathutils import Vector

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_BOAT_ARCHETYPES = ("rowboat", "dinghy", "pirate_brig")


_ARCHETYPE_DEFAULTS = {
    "rowboat": dict(
        length=2.6, width=0.95, height=0.45,
        bow_taper=0.6, stern_taper=0.5,
        n_thwarts=2, has_oars=True, oar_length=1.6,
        has_mast=False, mast_height=0.0,
        has_sail=False, sail_size=(0, 0),
        has_bowsprit=False,
        hull_color="wood", trim_color="rust_metal", sail_color="stucco",
    ),
    "dinghy": dict(
        length=1.9, width=0.85, height=0.4,
        bow_taper=0.7, stern_taper=0.7,
        n_thwarts=1, has_oars=False, oar_length=0.0,
        has_mast=False, mast_height=0.0,
        has_sail=False, sail_size=(0, 0),
        has_bowsprit=False,
        hull_color="wood", trim_color="rust_metal", sail_color="stucco",
    ),
    "pirate_brig": dict(
        length=5.5, width=1.6, height=0.85,
        bow_taper=0.5, stern_taper=0.55,
        n_thwarts=0, has_oars=False, oar_length=0.0,
        has_mast=True, mast_height=4.0,
        has_sail=True, sail_size=(2.0, 2.5),
        has_bowsprit=True,
        hull_color="wood", trim_color="rust_metal", sail_color="stucco",
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


def _add_hull(
    bm, slot_ranges, slot,
    length: float, width: float, height: float,
    bow_taper: float, stern_taper: float,
) -> None:
    """Boat hull — open-top stretched hexagon with pointed bow + stern.
    Length axis is X. Bow is +X, stern is -X. The hull has 8 verts at the
    waterline (top edge of gunwale) + a single "keel" line of 4 verts at
    the bottom (less wide, lower z). This gives a 6-faced hull (2 sides,
    2 ends, 1 keel bottom).
    """
    start = _bm_face_count(bm)
    L, W, H = length / 2, width / 2, height
    # Top ring (gunwale) — 6 verts: stern-port, mid-port, bow-port,
    # bow-stbd, mid-stbd, stern-stbd
    bow_x = L
    stern_x = -L
    bow_y = W * (1.0 - bow_taper)   # narrow at the bow
    stern_y = W * (1.0 - stern_taper)
    mid_y = W
    g_stern_p = bm.verts.new((stern_x,  stern_y, H))
    g_mid_p   = bm.verts.new((0,        mid_y,   H))
    g_bow_p   = bm.verts.new((bow_x,    bow_y,   H))
    g_bow_s   = bm.verts.new((bow_x,   -bow_y,   H))
    g_mid_s   = bm.verts.new((0,       -mid_y,   H))
    g_stern_s = bm.verts.new((stern_x, -stern_y, H))
    # Bottom keel — narrower, lower
    keel_W = W * 0.35
    keel_z = 0.0
    k_stern_p = bm.verts.new((stern_x * 0.95,  keel_W, keel_z))
    k_bow_p   = bm.verts.new((bow_x * 0.95,    keel_W, keel_z))
    k_bow_s   = bm.verts.new((bow_x * 0.95,   -keel_W, keel_z))
    k_stern_s = bm.verts.new((stern_x * 0.95, -keel_W, keel_z))
    bm.verts.ensure_lookup_table()
    # Side panels — port (3 quads from gunwale to keel)
    bm.faces.new((g_stern_p, g_mid_p, k_bow_p, k_stern_p))
    bm.faces.new((g_mid_p, g_bow_p, k_bow_p))   # triangle bow
    # Side panels — starboard
    bm.faces.new((k_stern_s, k_bow_s, g_mid_s, g_stern_s))
    bm.faces.new((k_bow_s, g_bow_s, g_mid_s))   # triangle bow
    # Bow end — quad between port-bow gunwale, stbd-bow gunwale, stbd-bow
    # keel, port-bow keel
    bm.faces.new((g_bow_p, g_bow_s, k_bow_s, k_bow_p))
    # Stern end
    bm.faces.new((k_stern_p, k_stern_s, g_stern_s, g_stern_p))
    # Keel bottom
    bm.faces.new((k_bow_p, k_bow_s, k_stern_s, k_stern_p))
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))


def _add_thwarts(
    bm, slot_ranges, slot,
    length: float, width: float, height: float,
    n_thwarts: int,
) -> None:
    """Cross-seats (thwarts) inside the hull at evenly spaced X positions."""
    if n_thwarts <= 0:
        return
    th_thickness = 0.04
    th_z = height * 0.85
    for i in range(n_thwarts):
        u = (i + 1) / (n_thwarts + 1)
        x = -length / 2 + length * u
        # Width at that point — taper between bow_taper(.6) and stern_taper(.5)
        # Use mid-width minus a small taper at extremes.
        local_w = width * (0.85 - 0.15 * abs(u - 0.5) * 2)
        _add_box_slot(
            bm, slot_ranges, slot,
            x, 0, th_z + th_thickness / 2,
            0.06, local_w, th_thickness,
        )


def _add_oars(
    bm, slot_ranges, slot,
    length: float, width: float, height: float,
    oar_length: float,
) -> None:
    """Two oars resting in the boat — angled across the gunwale on both
    sides."""
    oar_thickness = 0.025
    blade_w = 0.09
    blade_l = 0.3
    handle_l = oar_length - blade_l
    # Each oar sits diagonally — one end inside boat, one end outside
    for sign in (-1, 1):
        # Handle
        cx = -length * 0.1
        cy = sign * width * 0.55
        cz = height + oar_thickness / 2
        _add_box_slot(
            bm, slot_ranges, slot,
            cx, cy, cz,
            handle_l, oar_thickness, oar_thickness,
        )
        # Blade
        bx = cx + handle_l / 2 + blade_l / 2
        by = cy + sign * 0.04
        _add_box_slot(
            bm, slot_ranges, slot,
            bx, by, cz,
            blade_l, blade_w, oar_thickness,
        )


def _add_mast_and_sail(
    bm, slot_ranges, mast_slot, sail_slot,
    length: float, height: float,
    mast_height: float,
    has_sail: bool,
    sail_size: tuple[float, float],
    has_bowsprit: bool,
) -> None:
    """Mast at amidships + optional square sail on a yard + optional
    bowsprit."""
    mast_thickness = 0.10
    mast_base_z = height
    _add_box_slot(
        bm, slot_ranges, mast_slot,
        0, 0, mast_base_z + mast_height / 2,
        mast_thickness, mast_thickness, mast_height,
    )
    if has_sail and sail_size[0] > 0 and sail_size[1] > 0:
        sail_w, sail_h = sail_size
        # Yard (horizontal cross-bar holding the sail)
        yard_z = mast_base_z + mast_height * 0.85
        _add_box_slot(
            bm, slot_ranges, mast_slot,
            0, 0, yard_z,
            sail_w + 0.2, mast_thickness * 0.7, mast_thickness * 0.7,
        )
        # Sail — flat quad hanging below yard, length axis = X (matches
        # boat travel direction). Use Y dimension for cloth thickness.
        sail_thickness = 0.02
        _add_box_slot(
            bm, slot_ranges, sail_slot,
            0, 0, yard_z - sail_h / 2,
            sail_w, sail_thickness, sail_h,
        )
    if has_bowsprit:
        # Bowsprit — angled spar from the bow up and forward
        bowsprit_len = length * 0.3
        bowsprit_thick = mast_thickness * 0.7
        # Place at +X edge, angle up by ~20°
        cx = length / 2 + bowsprit_len / 2
        cz = height + bowsprit_len * 0.18
        _add_box_slot(
            bm, slot_ranges, mast_slot,
            cx, 0, cz,
            bowsprit_len, bowsprit_thick, bowsprit_thick,
        )


class LowPolyBoatFactory(AssetFactory):
    """A boat — rowboat, dinghy, or pirate brig.

    Layout convention: length axis is X (bow at +X, stern at -X).
    Hull rests on z=0; gunwale (top edge) at z=height. The keel is
    above z=0 by design (boat sits "on" the water plane the caller
    places it on).

    Constructor knobs:

        factory_seed
        boat_archetype : str = "rowboat"
                         "rowboat" | "dinghy" | "pirate_brig"
        length, width, height : floats
        bow_taper, stern_taper : float (0..1) — how much the ends pinch
        n_thwarts        : int     cross seats
        has_oars         : bool
        oar_length       : float
        has_mast         : bool
        mast_height      : float
        has_sail         : bool
        sail_size        : (w, h)
        has_bowsprit     : bool
        hull_color       : str   slot 0
        trim_color       : str   slot 1 (mast, oars)
        sail_color       : str   slot 2
    """

    def __init__(
        self,
        factory_seed,
        boat_archetype: str = "rowboat",
        length: float | None = None,
        width: float | None = None,
        height: float | None = None,
        bow_taper: float | None = None,
        stern_taper: float | None = None,
        n_thwarts: int | None = None,
        has_oars: bool | None = None,
        oar_length: float | None = None,
        has_mast: bool | None = None,
        mast_height: float | None = None,
        has_sail: bool | None = None,
        sail_size: tuple[float, float] | None = None,
        has_bowsprit: bool | None = None,
        hull_color: str | None = None,
        trim_color: str | None = None,
        sail_color: str | None = None,
        coarse: bool = False,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if boat_archetype not in _BOAT_ARCHETYPES:
            # Lenient fallback rather than crash. Sonnet has been
            # observed to hallucinate plausible-sounding archetype
            # names despite the factories_guide brief listing the
            # valid set; killing a 6-minute build over a one-line
            # archetype typo wastes a generation. Substitute the
            # canonical default and warn to stderr.
            import sys
            print(
                f"[boat_archetype] WARN: unknown boat_archetype "
                f"{boat_archetype!r}; falling back to {_BOAT_ARCHETYPES[0]!r}. "
                f"Valid: {_BOAT_ARCHETYPES}",
                file=sys.stderr,
            )
            boat_archetype = _BOAT_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[boat_archetype]
        self.boat_archetype = boat_archetype
        self.length = float(length if length is not None else d["length"])
        self.width = float(width if width is not None else d["width"])
        self.height = float(height if height is not None else d["height"])
        self.bow_taper = float(bow_taper if bow_taper is not None else d["bow_taper"])
        self.stern_taper = float(stern_taper if stern_taper is not None else d["stern_taper"])
        self.n_thwarts = int(n_thwarts if n_thwarts is not None else d["n_thwarts"])
        self.has_oars = (
            bool(has_oars) if has_oars is not None else d["has_oars"]
        )
        self.oar_length = float(oar_length if oar_length is not None else d["oar_length"])
        self.has_mast = (
            bool(has_mast) if has_mast is not None else d["has_mast"]
        )
        self.mast_height = float(mast_height if mast_height is not None else d["mast_height"])
        self.has_sail = (
            bool(has_sail) if has_sail is not None else d["has_sail"]
        )
        ss = sail_size if sail_size is not None else d["sail_size"]
        self.sail_size = (float(ss[0]), float(ss[1]))
        self.has_bowsprit = (
            bool(has_bowsprit) if has_bowsprit is not None else d["has_bowsprit"]
        )
        self.hull_color = hull_color or d["hull_color"]
        self.trim_color = trim_color or d["trim_color"]
        self.sail_color = sail_color or d["sail_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyBoat({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        bm = bmesh.new()
        slot_ranges: list[tuple[int, int, int]] = []

        # Hull
        _add_hull(
            bm, slot_ranges, 0,
            self.length, self.width, self.height,
            self.bow_taper, self.stern_taper,
        )

        # Thwarts
        if self.n_thwarts > 0:
            _add_thwarts(
                bm, slot_ranges, 0,
                self.length, self.width, self.height,
                self.n_thwarts,
            )

        # Oars
        if self.has_oars and self.oar_length > 0:
            _add_oars(
                bm, slot_ranges, 1,
                self.length, self.width, self.height,
                self.oar_length,
            )

        # Mast + sail + bowsprit
        if self.has_mast and self.mast_height > 0:
            _add_mast_and_sail(
                bm, slot_ranges, 1, 2,
                self.length, self.height,
                self.mast_height,
                self.has_sail, self.sail_size,
                self.has_bowsprit,
            )

        me = bpy.data.meshes.new(f"LowPolyBoat({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(f"LowPolyBoat({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)

        while len(obj.data.materials) < 3:
            obj.data.materials.append(None)

        for start, end, slot in slot_ranges:
            for i in range(start, end):
                obj.data.polygons[i].material_index = slot

        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(
            obj, [self.hull_color, self.trim_color, self.sail_color]
        )
        return obj

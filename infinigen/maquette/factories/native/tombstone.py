"""LowPolyTombstoneFactory — graveyard tombstones / monuments.

Top graveyard factory per Attempt 17. Without it any cemetery scene
reads as "stone field" because tiny stone-wall stand-ins look like
rocks, not graves. Also reusable for the ruins prompt (Attempt 6
gap: Tombstone) and the monastery prompt.

Archetypes:
  slab        — flat rectangular slab, rounded top
                (most common — generic 1700s-style headstone)
  cross       — vertical pillar with crossbar
                (Christian cemetery)
  arch        — slab with pointed/gothic arch top
                (Victorian or fantasy graveyard)
  obelisk     — tall tapered four-sided pillar with pyramid cap
                (Victorian wealthy plot, also Egyptian / military)
  flat_marker — short flat plaque sitting on the ground
                (modern / military cemetery look)

The `lean_angle` parameter rotates the stone slightly off-vertical —
old graveyards have weathered stones leaning every direction. Set per
instance via different factory_seed.

Material slots:
  slot 0 = stone body          (default `rock_pale` — weathered stone)
  slot 1 = engraved-text patch (default same as body; exposed so caller
                                can highlight cross / inscription
                                differently)
"""

from __future__ import annotations

import math
import random

import bmesh
import bpy
from mathutils import Vector

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_TOMBSTONE_ARCHETYPES = ("slab", "cross", "arch", "obelisk", "flat_marker")


_ARCHETYPE_DEFAULTS = {
    "slab": dict(
        height=0.9, width=0.55, depth=0.12,
        cross_arm_length=0.0, cross_arm_height=0.0,
        arch_height=0.18, n_arch_segments=4,
        taper=0.0, lean_angle=0.0,
        stone_color="rock_pale", accent_color="rock_pale",
    ),
    "cross": dict(
        height=1.2, width=0.18, depth=0.12,
        cross_arm_length=0.7, cross_arm_height=0.18,
        arch_height=0.0, n_arch_segments=0,
        taper=0.0, lean_angle=0.0,
        stone_color="rock_pale", accent_color="rock_pale",
    ),
    "arch": dict(
        height=1.0, width=0.5, depth=0.12,
        cross_arm_length=0.0, cross_arm_height=0.0,
        arch_height=0.25, n_arch_segments=4,
        taper=0.0, lean_angle=0.0,
        stone_color="rock_pale", accent_color="rock_pale",
    ),
    "obelisk": dict(
        height=1.6, width=0.25, depth=0.25,
        cross_arm_length=0.0, cross_arm_height=0.0,
        arch_height=0.0, n_arch_segments=0,
        taper=0.5, lean_angle=0.0,
        stone_color="rock_pale", accent_color="rock_shadow",
    ),
    "flat_marker": dict(
        height=0.18, width=0.5, depth=0.35,
        cross_arm_length=0.0, cross_arm_height=0.0,
        arch_height=0.0, n_arch_segments=0,
        taper=0.0, lean_angle=0.0,
        stone_color="rock_pale", accent_color="rock_pale",
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


def _add_arch_top(
    bm, slot_ranges, slot,
    base_z: float, width: float, depth: float, arch_height: float,
    n_segments: int,
) -> None:
    """Rounded arch on top of a slab — n_segments triangle fan from the
    top of the slab to the apex."""
    if arch_height <= 0 or n_segments <= 0:
        return
    start = _bm_face_count(bm)
    # Build N+1 points along a half-circle from -width/2 to +width/2,
    # apex at z=base_z + arch_height.
    half_w = width / 2
    half_d = depth / 2
    front_pts = []
    back_pts = []
    for s in range(n_segments + 1):
        t = s / n_segments
        # Interpolate along a half-arc; use cos for height curve
        x = -half_w + width * t
        # Height is sinusoidal — peaks at middle
        z = base_z + arch_height * math.sin(t * math.pi)
        front_pts.append(bm.verts.new((x, -half_d, z)))
        back_pts.append(bm.verts.new((x,  half_d, z)))
    # Bottom corners of the slab top (where the arch meets the rectangle)
    bL_f = bm.verts.new((-half_w, -half_d, base_z))
    bR_f = bm.verts.new(( half_w, -half_d, base_z))
    bL_b = bm.verts.new((-half_w,  half_d, base_z))
    bR_b = bm.verts.new(( half_w,  half_d, base_z))
    bm.verts.ensure_lookup_table()
    # Front arc face — triangle fan from a center point at base mid
    base_mid_f = bm.verts.new((0, -half_d, base_z))
    base_mid_b = bm.verts.new((0,  half_d, base_z))
    bm.verts.ensure_lookup_table()
    # Front quads from each adjacent pair of arc verts down to base line
    for s in range(n_segments):
        bm.faces.new((front_pts[s], front_pts[s + 1], base_mid_f))
    # Same on back
    for s in range(n_segments):
        bm.faces.new((base_mid_b, back_pts[s + 1], back_pts[s]))
    # Side faces between front and back at each arc vertex (the "depth"
    # of the arch). Pair each front_pts[s] with back_pts[s].
    for s in range(n_segments):
        bm.faces.new((front_pts[s], back_pts[s], back_pts[s + 1], front_pts[s + 1]))
    # Cap the bottom of the arch where it meets the slab — quad
    bm.faces.new((bL_f, base_mid_f, base_mid_b, bL_b))
    bm.faces.new((base_mid_f, bR_f, bR_b, base_mid_b))
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))


def _add_obelisk(
    bm, slot_ranges, slot,
    height: float, base_w: float, base_d: float, taper: float,
    accent_slot: int,
) -> None:
    """Tall tapered four-sided pillar + pyramid cap. Taper = 0 → no
    taper, taper = 1 → cone."""
    start = _bm_face_count(bm)
    cap_h = height * 0.12
    body_h = height - cap_h
    top_w = base_w * (1.0 - taper)
    top_d = base_d * (1.0 - taper)
    # Body — frustum, 8 verts
    bw_h, bd_h = base_w / 2, base_d / 2
    tw_h, td_h = top_w / 2, top_d / 2
    b00 = bm.verts.new((-bw_h, -bd_h, 0))
    b10 = bm.verts.new(( bw_h, -bd_h, 0))
    b11 = bm.verts.new(( bw_h,  bd_h, 0))
    b01 = bm.verts.new((-bw_h,  bd_h, 0))
    t00 = bm.verts.new((-tw_h, -td_h, body_h))
    t10 = bm.verts.new(( tw_h, -td_h, body_h))
    t11 = bm.verts.new(( tw_h,  td_h, body_h))
    t01 = bm.verts.new((-tw_h,  td_h, body_h))
    bm.verts.ensure_lookup_table()
    bm.faces.new((b00, b10, t10, t00))
    bm.faces.new((b10, b11, t11, t10))
    bm.faces.new((b11, b01, t01, t11))
    bm.faces.new((b01, b00, t00, t01))
    bm.faces.new((b00, b01, b11, b10))  # bottom
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))
    # Pyramid cap (slot 1 — accent)
    cap_start = _bm_face_count(bm)
    apex = bm.verts.new((0, 0, height))
    bm.verts.ensure_lookup_table()
    bm.faces.new((t00, t10, apex))
    bm.faces.new((t10, t11, apex))
    bm.faces.new((t11, t01, apex))
    bm.faces.new((t01, t00, apex))
    cap_end = _bm_face_count(bm)
    slot_ranges.append((cap_start, cap_end, accent_slot))


class LowPolyTombstoneFactory(AssetFactory):
    """A graveyard tombstone / monument — slab / cross / arch / obelisk /
    flat_marker.

    Constructor knobs:

        factory_seed
        tombstone_archetype : str = "slab"
                              "slab" | "cross" | "arch" |
                              "obelisk" | "flat_marker"
        height, width, depth   : floats
        cross_arm_length       : float (cross only)
        cross_arm_height       : float (cross only)
        arch_height            : float (arch only)
        n_arch_segments        : int   (arch only)
        taper                  : float (obelisk: 0..1)
        lean_angle             : float (radians; tilts the whole stone)
        stone_color            : str   slot 0
        accent_color           : str   slot 1 (obelisk cap, etc.)
    """

    def __init__(
        self,
        factory_seed,
        tombstone_archetype: str = "slab",
        height: float | None = None,
        width: float | None = None,
        depth: float | None = None,
        cross_arm_length: float | None = None,
        cross_arm_height: float | None = None,
        arch_height: float | None = None,
        n_arch_segments: int | None = None,
        taper: float | None = None,
        lean_angle: float | None = None,
        stone_color: str | None = None,
        accent_color: str | None = None,
        coarse: bool = False,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if tombstone_archetype not in _TOMBSTONE_ARCHETYPES:
            # Lenient fallback rather than crash. Sonnet has been
            # observed to hallucinate plausible-sounding archetype
            # names despite the factories_guide brief listing the
            # valid set; killing a 6-minute build over a one-line
            # archetype typo wastes a generation. Substitute the
            # canonical default and warn to stderr.
            import sys
            print(
                f"[tombstone_archetype] WARN: unknown tombstone_archetype "
                f"{tombstone_archetype!r}; falling back to {_TOMBSTONE_ARCHETYPES[0]!r}. "
                f"Valid: {_TOMBSTONE_ARCHETYPES}",
                file=sys.stderr,
            )
            tombstone_archetype = _TOMBSTONE_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[tombstone_archetype]
        self.tombstone_archetype = tombstone_archetype
        self.height = float(height if height is not None else d["height"])
        self.width = float(width if width is not None else d["width"])
        self.depth = float(depth if depth is not None else d["depth"])
        self.cross_arm_length = float(cross_arm_length if cross_arm_length is not None else d["cross_arm_length"])
        self.cross_arm_height = float(cross_arm_height if cross_arm_height is not None else d["cross_arm_height"])
        self.arch_height = float(arch_height if arch_height is not None else d["arch_height"])
        self.n_arch_segments = int(n_arch_segments if n_arch_segments is not None else d["n_arch_segments"])
        self.taper = float(taper if taper is not None else d["taper"])
        self.lean_angle = float(lean_angle if lean_angle is not None else d["lean_angle"])
        self.stone_color = stone_color or d["stone_color"]
        self.accent_color = accent_color or d["accent_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyTombstone({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        bm = bmesh.new()
        slot_ranges: list[tuple[int, int, int]] = []

        if self.tombstone_archetype == "slab":
            # Base rectangular slab + optional arched top
            body_h = self.height - self.arch_height
            _add_box_slot(
                bm, slot_ranges, 0,
                0, 0, body_h / 2,
                self.width, self.depth, body_h,
            )
            if self.arch_height > 0 and self.n_arch_segments > 0:
                _add_arch_top(
                    bm, slot_ranges, 0,
                    body_h, self.width, self.depth,
                    self.arch_height, self.n_arch_segments,
                )

        elif self.tombstone_archetype == "arch":
            body_h = self.height - self.arch_height
            _add_box_slot(
                bm, slot_ranges, 0,
                0, 0, body_h / 2,
                self.width, self.depth, body_h,
            )
            _add_arch_top(
                bm, slot_ranges, 0,
                body_h, self.width, self.depth,
                self.arch_height, self.n_arch_segments,
            )

        elif self.tombstone_archetype == "cross":
            # Vertical pillar
            _add_box_slot(
                bm, slot_ranges, 0,
                0, 0, self.height / 2,
                self.width, self.depth, self.height,
            )
            # Horizontal crossbar at 75% height
            crossbar_z = self.height * 0.75
            _add_box_slot(
                bm, slot_ranges, 0,
                0, 0, crossbar_z,
                self.cross_arm_length, self.depth, self.cross_arm_height,
            )

        elif self.tombstone_archetype == "obelisk":
            _add_obelisk(
                bm, slot_ranges, 0,
                self.height, self.width, self.depth, self.taper,
                accent_slot=1,
            )

        elif self.tombstone_archetype == "flat_marker":
            _add_box_slot(
                bm, slot_ranges, 0,
                0, 0, self.height / 2,
                self.width, self.depth, self.height,
            )

        me = bpy.data.meshes.new(f"LowPolyTombstone({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(f"LowPolyTombstone({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)

        while len(obj.data.materials) < 2:
            obj.data.materials.append(None)

        for start, end, slot in slot_ranges:
            for i in range(start, end):
                obj.data.polygons[i].material_index = slot

        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(obj, [self.stone_color, self.accent_color])

        # Optional lean
        if self.lean_angle != 0.0:
            obj.rotation_euler.x = self.lean_angle

        return obj

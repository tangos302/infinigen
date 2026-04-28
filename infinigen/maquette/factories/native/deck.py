"""LowPolyDeckFactory — pier / boardwalk / dock.

Surfaced in Attempt 13 (pirate cove) AND earlier in Attempt 3
(Wild West boardwalk). Both have the same underlying geometry —
row of vertical posts + horizontal plank deck on top — so they
share a single factory with different archetype defaults.

Archetypes:
  pier        — rectangular dock extending into water; tall posts
                go below deck (representing posts driven into the
                seabed); usually no railings
  boardwalk   — sidewalk-style raised plank walkway in front of
                buildings; shorter posts; usually no railings
  dock_railed — same as pier but with handrails along both sides
                (more "modern marina" or fortified pier feel)

Layout convention: length axis is X, width axis is Y. Caller
positions and rotates the result. The deck top sits at z=deck_height
(positive); posts extend below (negative z = underwater for pier).

Material slots:
  slot 0 = deck planks       (default `wood`)
  slot 1 = posts             (default `rock_shadow` — wet/dark wood)
  slot 2 = railings          (default `wood`)
"""

from __future__ import annotations

import math

import bmesh
import bpy
from mathutils import Vector

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_DECK_ARCHETYPES = ("pier", "boardwalk", "dock_railed")


_ARCHETYPE_DEFAULTS = {
    "pier": dict(
        length=8.0, width=1.6,
        deck_height=0.3, deck_thickness=0.08,
        post_spacing=2.0, post_size=0.12, post_depth=1.2,
        n_planks_along=12, plank_gap=0.02,
        has_railings=False, railing_height=0.0,
        deck_color="wood", post_color="rock_shadow", rail_color="wood",
    ),
    "boardwalk": dict(
        length=6.0, width=1.4,
        deck_height=0.2, deck_thickness=0.06,
        post_spacing=1.5, post_size=0.10, post_depth=0.3,
        n_planks_along=10, plank_gap=0.02,
        has_railings=False, railing_height=0.0,
        deck_color="wood", post_color="rock_shadow", rail_color="wood",
    ),
    "dock_railed": dict(
        length=8.0, width=1.6,
        deck_height=0.3, deck_thickness=0.08,
        post_spacing=2.0, post_size=0.12, post_depth=1.2,
        n_planks_along=12, plank_gap=0.02,
        has_railings=True, railing_height=0.9,
        deck_color="wood", post_color="rock_shadow", rail_color="wood",
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


class LowPolyDeckFactory(AssetFactory):
    """A pier / boardwalk / dock — posts + plank deck.

    Constructor knobs:

        factory_seed
        deck_archetype : str = "pier"
                         "pier" | "boardwalk" | "dock_railed"
        length, width      : floats
        deck_height        : float    deck top z above ground
        deck_thickness     : float    plank thickness
        post_spacing       : float    distance between posts along length
        post_size          : float    post side length
        post_depth         : float    how far below deck the posts go
        n_planks_along     : int      plank count across the deck
        plank_gap          : float    gap between planks (visual seam)
        has_railings       : bool
        railing_height     : float
        deck_color         : str  slot 0
        post_color         : str  slot 1
        rail_color         : str  slot 2
    """

    def __init__(
        self,
        factory_seed,
        deck_archetype: str = "pier",
        length: float | None = None,
        width: float | None = None,
        deck_height: float | None = None,
        deck_thickness: float | None = None,
        post_spacing: float | None = None,
        post_size: float | None = None,
        post_depth: float | None = None,
        n_planks_along: int | None = None,
        plank_gap: float | None = None,
        has_railings: bool | None = None,
        railing_height: float | None = None,
        deck_color: str | None = None,
        post_color: str | None = None,
        rail_color: str | None = None,
        coarse: bool = False,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if deck_archetype not in _DECK_ARCHETYPES:
            raise ValueError(
                f"unknown deck_archetype {deck_archetype!r}; "
                f"valid: {_DECK_ARCHETYPES}"
            )
        d = _ARCHETYPE_DEFAULTS[deck_archetype]
        self.deck_archetype = deck_archetype
        self.length = float(length if length is not None else d["length"])
        self.width = float(width if width is not None else d["width"])
        self.deck_height = float(deck_height if deck_height is not None else d["deck_height"])
        self.deck_thickness = float(deck_thickness if deck_thickness is not None else d["deck_thickness"])
        self.post_spacing = float(post_spacing if post_spacing is not None else d["post_spacing"])
        self.post_size = float(post_size if post_size is not None else d["post_size"])
        self.post_depth = float(post_depth if post_depth is not None else d["post_depth"])
        self.n_planks_along = int(n_planks_along if n_planks_along is not None else d["n_planks_along"])
        self.plank_gap = float(plank_gap if plank_gap is not None else d["plank_gap"])
        self.has_railings = (
            bool(has_railings) if has_railings is not None else d["has_railings"]
        )
        self.railing_height = float(railing_height if railing_height is not None else d["railing_height"])
        self.deck_color = deck_color or d["deck_color"]
        self.post_color = post_color or d["post_color"]
        self.rail_color = rail_color or d["rail_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyDeck({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        bm = bmesh.new()
        slot_ranges: list[tuple[int, int, int]] = []

        L, W = self.length, self.width
        deck_top_z = self.deck_height
        deck_center_z = deck_top_z - self.deck_thickness / 2
        deck_z_low = deck_top_z - self.deck_thickness

        # Deck — N planks running along X, each plank-strip is a thin
        # box. Planks have small Y gap between them for the seam read.
        n = self.n_planks_along
        plank_w = (W - (n - 1) * self.plank_gap) / n
        for i in range(n):
            py = -W / 2 + plank_w / 2 + i * (plank_w + self.plank_gap)
            _add_box_slot(
                bm, slot_ranges, 0,
                0, py, deck_center_z,
                L, plank_w, self.deck_thickness,
            )

        # Posts — at regular intervals along X, at both ±Y edges
        n_post_pairs = max(2, int(L / self.post_spacing) + 1)
        for j in range(n_post_pairs):
            u = j / (n_post_pairs - 1)
            px = -L / 2 + L * u
            for sign in (-1, 1):
                py = sign * (W / 2 - self.post_size / 2)
                # Post extends from deck_z_low DOWN by post_depth
                post_top_z = deck_z_low
                post_bottom_z = deck_z_low - self.post_depth
                cz = (post_top_z + post_bottom_z) / 2
                sz = post_top_z - post_bottom_z
                _add_box_slot(
                    bm, slot_ranges, 1,
                    px, py, cz,
                    self.post_size, self.post_size, sz,
                )

        # Railings — top rails + railing posts at corners
        if self.has_railings and self.railing_height > 0:
            rail_thick = 0.05
            # Top rail along each side
            for sign in (-1, 1):
                rail_y = sign * (W / 2 - rail_thick / 2)
                rail_z = deck_top_z + self.railing_height
                _add_box_slot(
                    bm, slot_ranges, 2,
                    0, rail_y, rail_z,
                    L, rail_thick, rail_thick,
                )
            # Vertical railing posts
            for j in range(n_post_pairs):
                u = j / (n_post_pairs - 1)
                px = -L / 2 + L * u
                for sign in (-1, 1):
                    py = sign * (W / 2 - rail_thick / 2)
                    cz = deck_top_z + self.railing_height / 2
                    _add_box_slot(
                        bm, slot_ranges, 2,
                        px, py, cz,
                        rail_thick, rail_thick, self.railing_height,
                    )

        me = bpy.data.meshes.new(f"LowPolyDeck({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(f"LowPolyDeck({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)

        while len(obj.data.materials) < 3:
            obj.data.materials.append(None)

        for start, end, slot in slot_ranges:
            for i in range(start, end):
                obj.data.polygons[i].material_index = slot

        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(
            obj, [self.deck_color, self.post_color, self.rail_color]
        )
        return obj

"""LowPolyCrateFactory — wooden / metal storage crate.

Tier-1 factory per empirical-attempt frequency (3/6 prompts:
medieval, campsite, Wild West). Pairs naturally with barrel —
stacks of crates and barrels are the universal "this is a place
people store things" tell.

Archetypes:
  wooden    — visible plank seams on top + sides
              (medieval / fishing / Wild West)
  metal     — smooth box with optional rivets at corners
              (industrial / sci-fi)
  fragile   — wooden + edge strapping (corner reinforcement)
              for "this is shipped goods" feel

The seams are baked into the geometry as subdivided strips on the
top face, slightly offset in Z so they read as planks at flat-
shaded low poly. Side faces stay simple cubes — adding seams to
all 6 faces overcrowds the silhouette.

Material slots:
  slot 0 = body / planks         (default `wood` or `rust_metal`)
  slot 1 = strapping / accents   (default `rust_metal`)
"""

from __future__ import annotations

import math

import bmesh
import bpy
from mathutils import Vector

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_CRATE_ARCHETYPES = ("wooden", "metal", "fragile")


_ARCHETYPE_DEFAULTS = {
    "wooden": dict(
        size=(0.7, 0.7, 0.6),
        plank_pattern=True, edge_strapping=False,
        n_planks=3, plank_offset=0.015,
        strap_thickness=0.03, strap_protrusion=0.012,
        body_color="wood", strap_color="rust_metal",
    ),
    "metal": dict(
        size=(0.7, 0.7, 0.6),
        plank_pattern=False, edge_strapping=True,
        n_planks=0, plank_offset=0.0,
        strap_thickness=0.04, strap_protrusion=0.015,
        body_color="rust_metal", strap_color="rust_metal",
    ),
    "fragile": dict(
        # A bit smaller, with corner reinforcement for "shipped goods" feel
        size=(0.55, 0.55, 0.5),
        plank_pattern=True, edge_strapping=True,
        n_planks=3, plank_offset=0.015,
        strap_thickness=0.03, strap_protrusion=0.012,
        body_color="wood", strap_color="rust_metal",
    ),
}


def _bm_face_count(bm) -> int:
    return len(bm.faces)


def _add_box(
    bm,
    cx: float, cy: float, cz: float,
    sx: float, sy: float, sz: float,
) -> int:
    """Axis-aligned box centered at (cx, cy, cz). Returns face count added."""
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


def _add_box_slot(
    bm, slot_ranges, slot,
    cx, cy, cz, sx, sy, sz,
) -> None:
    start = _bm_face_count(bm)
    _add_box(bm, cx, cy, cz, sx, sy, sz)
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))


def _add_plank_top(
    bm, slot_ranges, slot,
    cx: float, cy: float, top_z: float,
    sx: float, sy: float,
    n_planks: int, plank_offset: float,
) -> None:
    """Replace the implicit top face of a box with N raised plank strips.
    Each plank gets the box's body slot. The seams between them read as
    plank gaps because they're physically offset in Z and have a small
    Y gap."""
    if n_planks <= 0:
        return
    plank_w = sy / n_planks
    seam_gap = plank_w * 0.06   # tiny gap between planks
    for i in range(n_planks):
        py = cy - sy / 2 + plank_w * (i + 0.5)
        # Alternate plank Z offset so reads as slightly uneven boards
        z_lift = plank_offset * (1 if i % 2 == 0 else 0.5)
        plank_h = plank_offset * 1.2
        _add_box_slot(
            bm, slot_ranges, slot,
            cx, py, top_z + z_lift / 2 + plank_h / 2,
            sx, plank_w - seam_gap, plank_h,
        )


def _add_corner_straps(
    bm, slot_ranges, slot,
    cx: float, cy: float, cz: float,
    sx: float, sy: float, sz: float,
    strap_thickness: float, strap_protrusion: float,
) -> None:
    """Add 4 vertical corner straps (at the 4 vertical edges) that wrap a
    little bit onto the adjacent faces — reads as corner reinforcement."""
    hx, hy = sx / 2, sy / 2
    t = strap_thickness
    p = strap_protrusion
    for sign_x in (-1, 1):
        for sign_y in (-1, 1):
            cx_strap = cx + sign_x * (hx + p / 2)
            cy_strap = cy + sign_y * (hy - t / 2)
            _add_box_slot(
                bm, slot_ranges, slot,
                cx_strap, cy_strap, cz,
                p, t, sz * 0.95,
            )
            cx_strap2 = cx + sign_x * (hx - t / 2)
            cy_strap2 = cy + sign_y * (hy + p / 2)
            _add_box_slot(
                bm, slot_ranges, slot,
                cx_strap2, cy_strap2, cz,
                t, p, sz * 0.95,
            )


class LowPolyCrateFactory(AssetFactory):
    """A storage crate — cube body with optional plank seams + corner straps.

    Constructor knobs:

        factory_seed
        crate_archetype  : str = "wooden"  "wooden" | "metal" | "fragile"
        size             : float | tuple   cube edge or (sx, sy, sz)
        plank_pattern    : bool             raised plank strips on top
        edge_strapping   : bool             corner straps
        n_planks         : int              planks on top (if plank_pattern)
        plank_offset     : float            plank Z lift
        strap_thickness  : float
        strap_protrusion : float
        body_color       : str              slot 0
        strap_color      : str              slot 1
    """

    def __init__(
        self,
        factory_seed,
        crate_archetype: str = "wooden",
        size: float | tuple | None = None,
        plank_pattern: bool | None = None,
        edge_strapping: bool | None = None,
        n_planks: int | None = None,
        plank_offset: float | None = None,
        strap_thickness: float | None = None,
        strap_protrusion: float | None = None,
        body_color: str | None = None,
        strap_color: str | None = None,
        coarse: bool = False,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if crate_archetype not in _CRATE_ARCHETYPES:
            # Lenient fallback rather than crash. Sonnet has been
            # observed to hallucinate plausible-sounding archetype
            # names despite the factories_guide brief listing the
            # valid set; killing a 6-minute build over a one-line
            # archetype typo wastes a generation. Substitute the
            # canonical default and warn to stderr.
            import sys
            print(
                f"[crate_archetype] WARN: unknown crate_archetype "
                f"{crate_archetype!r}; falling back to {_CRATE_ARCHETYPES[0]!r}. "
                f"Valid: {_CRATE_ARCHETYPES}",
                file=sys.stderr,
            )
            crate_archetype = _CRATE_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[crate_archetype]
        self.crate_archetype = crate_archetype
        s = size if size is not None else d["size"]
        if isinstance(s, (int, float)):
            s = (float(s), float(s), float(s))
        self.size = (float(s[0]), float(s[1]), float(s[2]))
        self.plank_pattern = (
            bool(plank_pattern) if plank_pattern is not None else d["plank_pattern"]
        )
        self.edge_strapping = (
            bool(edge_strapping) if edge_strapping is not None else d["edge_strapping"]
        )
        self.n_planks = int(n_planks if n_planks is not None else d["n_planks"])
        self.plank_offset = float(
            plank_offset if plank_offset is not None else d["plank_offset"]
        )
        self.strap_thickness = float(
            strap_thickness if strap_thickness is not None else d["strap_thickness"]
        )
        self.strap_protrusion = float(
            strap_protrusion if strap_protrusion is not None else d["strap_protrusion"]
        )
        self.body_color = body_color or d["body_color"]
        self.strap_color = strap_color or d["strap_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyCrate({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        sx, sy, sz = self.size
        bm = bmesh.new()
        slot_ranges: list[tuple[int, int, int]] = []

        # Main body (centered laterally; sits on z=0)
        cz = sz / 2
        _add_box_slot(bm, slot_ranges, 0, 0, 0, cz, sx, sy, sz)

        # Top planks
        if self.plank_pattern and self.n_planks > 0:
            _add_plank_top(
                bm, slot_ranges, 0,
                0, 0, sz, sx, sy,
                self.n_planks, self.plank_offset,
            )

        # Corner straps
        if self.edge_strapping:
            _add_corner_straps(
                bm, slot_ranges, 1,
                0, 0, cz, sx, sy, sz,
                self.strap_thickness, self.strap_protrusion,
            )

        me = bpy.data.meshes.new(f"LowPolyCrate({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(f"LowPolyCrate({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)

        while len(obj.data.materials) < 2:
            obj.data.materials.append(None)

        for start, end, slot in slot_ranges:
            for i in range(start, end):
                obj.data.polygons[i].material_index = slot

        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(obj, [self.body_color, self.strap_color])
        return obj

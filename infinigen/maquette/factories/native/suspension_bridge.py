"""LowPolySuspensionBridgeFactory — rope-and-plank bridge.

Spans between elevated platforms with characteristic catenary sag.
Reads as jungle gorge crossing, alpine cable bridge, or industrial
chain walkway depending on archetype materials.

Archetypes:
  rope_plank       — minimal jungle bridge: two side rope rails +
                     plank deck slung between. No towers, no vertical
                     suspenders. Iconic Indiana-Jones gorge crossing.
  cable_suspension — full suspension bridge: end towers + sagging
                     main cables overhead + vertical suspender drops
                     + plank deck. Iconic suspension silhouette.
  chain_walk       — same shape as rope_plank but with iron-coloured
                     chain side rails instead of rope. Industrial /
                     Victorian feel.

Layout convention: span axis is X (deck runs from -L/2 to +L/2),
width axis is Y. End anchors at ±L/2; deck top at z=0 with catenary
sag down to z=-sag at midspan. Towers (when present) sit at the
endpoints extending up from z=0. Caller translates / rotates the
result into world space between two platforms.

Material slots:
  slot 0 = deck planks                       (default `wood`)
  slot 1 = ropes / cables / chains           (default `rock_shadow`
                                              for hemp, `rust_metal`
                                              for chain/cable)
  slot 2 = towers / anchor posts             (default `wood`)
"""

from __future__ import annotations

import math

import bmesh
import bpy

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_BRIDGE_ARCHETYPES = ("rope_plank", "cable_suspension", "chain_walk")


_ARCHETYPE_DEFAULTS = {
    "rope_plank": dict(
        length=8.0, width=1.2, sag=0.6,
        deck_thickness=0.06, n_planks=20, plank_gap=0.04,
        rope_size=0.05, n_rope_segments=16,
        has_towers=False, tower_height=0.0, tower_size=0.0,
        has_suspenders=False, n_suspenders=0,
        cable_extra_height=0.0,
        deck_color="wood", rope_color="rock_shadow", tower_color="wood",
    ),
    "cable_suspension": dict(
        length=10.0, width=1.6, sag=0.4,
        deck_thickness=0.08, n_planks=22, plank_gap=0.04,
        rope_size=0.06, n_rope_segments=20,
        has_towers=True, tower_height=2.4, tower_size=0.25,
        has_suspenders=True, n_suspenders=10,
        cable_extra_height=1.6,
        deck_color="wood", rope_color="rust_metal", tower_color="wood",
    ),
    "chain_walk": dict(
        length=7.0, width=1.1, sag=0.5,
        deck_thickness=0.06, n_planks=18, plank_gap=0.04,
        rope_size=0.05, n_rope_segments=18,
        has_towers=False, tower_height=0.0, tower_size=0.0,
        has_suspenders=False, n_suspenders=0,
        cable_extra_height=0.0,
        deck_color="wood", rope_color="rust_metal", tower_color="wood",
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


def _sag_z(t: float, sag: float) -> float:
    """Catenary-ish sag profile, parameterised so t in [0, 1] runs
    from the left anchor to the right anchor. Returns the z OFFSET
    (zero at the anchors, -sag at midspan)."""
    u = 2.0 * t - 1.0
    return -sag * (1.0 - u * u)


def _add_rope(
    bm, slot_ranges, slot,
    x_start: float, x_end: float, y: float,
    z_start: float, z_end: float, sag: float,
    n_segments: int, rope_size: float,
) -> None:
    """A polyline rope built from short axis-aligned box segments.
    Each segment spans between two consecutive samples on the
    parabolic sag curve. The boxes are slightly inflated along X so
    consecutive segments overlap and read as continuous despite the
    visible bends — at low poly that reads as a rope, not stairsteps."""
    if n_segments <= 0 or rope_size <= 0:
        return
    pts = []
    for i in range(n_segments + 1):
        t = i / n_segments
        x = x_start + (x_end - x_start) * t
        z_lin = z_start + (z_end - z_start) * t
        pts.append((x, y, z_lin + _sag_z(t, sag)))
    for i in range(n_segments):
        x0, _, z0 = pts[i]
        x1, _, z1 = pts[i + 1]
        cx = (x0 + x1) / 2
        cz = (z0 + z1) / 2
        dx = x1 - x0
        dz = z1 - z0
        seg_len = math.sqrt(dx * dx + dz * dz)
        sx = max(seg_len, rope_size) * 1.05
        _add_box_slot(
            bm, slot_ranges, slot,
            cx, y, cz,
            sx, rope_size, rope_size,
        )


class LowPolySuspensionBridgeFactory(AssetFactory):
    """A rope-and-plank suspension bridge spanning between elevated
    platforms. The deck sags catenary-style; optional end towers carry
    main cables when archetype = `cable_suspension`.

    Layout: span axis is X (length), width axis is Y. The deck top at
    the endpoints sits at z=0 and dips down by `sag` at midspan.
    Towers (when present) extend upward from z=0 at x=±L/2.

    Constructor knobs:

        factory_seed
        bridge_archetype : str = "rope_plank"
                          "rope_plank" | "cable_suspension" | "chain_walk"
        length             : float
        width              : float
        sag                : float    deck dip at midspan (positive)
        deck_thickness     : float
        n_planks           : int      plank count along span
        plank_gap          : float    gap between planks
        rope_size          : float    rope/cable square-section side
        n_rope_segments    : int      polyline segment count
        has_towers         : bool
        tower_height       : float    tower height above deck endpoint
        tower_size         : float    tower square-section side
        has_suspenders     : bool     verticals from main cable to deck
        n_suspenders       : int
        cable_extra_height : float    main cable apex above deck endpoint
        deck_color         : str   slot 0
        rope_color         : str   slot 1
        tower_color        : str   slot 2
    """

    def __init__(
        self,
        factory_seed,
        bridge_archetype: str = "rope_plank",
        length: float | None = None,
        width: float | None = None,
        sag: float | None = None,
        deck_thickness: float | None = None,
        n_planks: int | None = None,
        plank_gap: float | None = None,
        rope_size: float | None = None,
        n_rope_segments: int | None = None,
        has_towers: bool | None = None,
        tower_height: float | None = None,
        tower_size: float | None = None,
        has_suspenders: bool | None = None,
        n_suspenders: int | None = None,
        cable_extra_height: float | None = None,
        deck_color: str | None = None,
        rope_color: str | None = None,
        tower_color: str | None = None,
        coarse: bool = False,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if bridge_archetype not in _BRIDGE_ARCHETYPES:
            # Lenient fallback rather than crash. Sonnet has been
            # observed to hallucinate plausible-sounding archetype
            # names despite the factories_guide brief listing the
            # valid set; killing a 6-minute build over a one-line
            # archetype typo wastes a generation. Substitute the
            # canonical default and warn to stderr.
            import sys
            print(
                f"[bridge_archetype] WARN: unknown bridge_archetype "
                f"{bridge_archetype!r}; falling back to {_BRIDGE_ARCHETYPES[0]!r}. "
                f"Valid: {_BRIDGE_ARCHETYPES}",
                file=sys.stderr,
            )
            bridge_archetype = _BRIDGE_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[bridge_archetype]
        self.bridge_archetype = bridge_archetype
        self.length = float(length if length is not None else d["length"])
        self.width = float(width if width is not None else d["width"])
        self.sag = float(sag if sag is not None else d["sag"])
        self.deck_thickness = float(
            deck_thickness if deck_thickness is not None else d["deck_thickness"]
        )
        self.n_planks = int(n_planks if n_planks is not None else d["n_planks"])
        self.plank_gap = float(plank_gap if plank_gap is not None else d["plank_gap"])
        self.rope_size = float(rope_size if rope_size is not None else d["rope_size"])
        self.n_rope_segments = int(
            n_rope_segments if n_rope_segments is not None else d["n_rope_segments"]
        )
        self.has_towers = (
            bool(has_towers) if has_towers is not None else d["has_towers"]
        )
        self.tower_height = float(
            tower_height if tower_height is not None else d["tower_height"]
        )
        self.tower_size = float(
            tower_size if tower_size is not None else d["tower_size"]
        )
        self.has_suspenders = (
            bool(has_suspenders) if has_suspenders is not None else d["has_suspenders"]
        )
        self.n_suspenders = int(
            n_suspenders if n_suspenders is not None else d["n_suspenders"]
        )
        self.cable_extra_height = float(
            cable_extra_height if cable_extra_height is not None
            else d["cable_extra_height"]
        )
        self.deck_color = deck_color or d["deck_color"]
        self.rope_color = rope_color or d["rope_color"]
        self.tower_color = tower_color or d["tower_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolySuspensionBridge({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        bm = bmesh.new()
        slot_ranges: list[tuple[int, int, int]] = []

        L, W = self.length, self.width
        deck_top_z = 0.0

        # Plank deck — N short planks stepping along X. Each plank's
        # top z follows the sag profile so the deck visibly dips.
        n = max(1, self.n_planks)
        plank_w_along = (L - (n - 1) * self.plank_gap) / n
        for i in range(n):
            t = (i + 0.5) / n
            x = -L / 2 + L * t
            z_top = deck_top_z + _sag_z(t, self.sag)
            z_center = z_top - self.deck_thickness / 2
            _add_box_slot(
                bm, slot_ranges, 0,
                x, 0, z_center,
                plank_w_along, W, self.deck_thickness,
            )

        # Side rope rails — at deck level along ±Y. Sit slightly above
        # the deck top so they read as a hand-rail rather than the deck
        # edge. End z stays at deck_top_z + offset; sag matches deck.
        rail_offset = max(self.rope_size * 0.6, 0.04)
        rail_y = W / 2 + self.rope_size / 2
        for sign in (-1, 1):
            _add_rope(
                bm, slot_ranges, 1,
                -L / 2, L / 2, sign * rail_y,
                deck_top_z + rail_offset, deck_top_z + rail_offset,
                self.sag,
                self.n_rope_segments, self.rope_size,
            )

        # Towers — paired square posts at each end (one per ±Y corner).
        if self.has_towers and self.tower_height > 0 and self.tower_size > 0:
            ts = self.tower_size
            tower_y = W / 2 + ts / 2
            for x_sign in (-1, 1):
                for y_sign in (-1, 1):
                    _add_box_slot(
                        bm, slot_ranges, 2,
                        x_sign * L / 2, y_sign * tower_y,
                        deck_top_z + self.tower_height / 2,
                        ts, ts, self.tower_height,
                    )

        # Main suspension cables — sag between tower tops, deeper than
        # the deck so the cable approaches the deck mid. Vertical
        # suspenders drop from cable to plank deck.
        if (
            self.has_towers and self.has_suspenders
            and self.cable_extra_height > 0 and self.n_suspenders > 0
        ):
            cable_top_z = deck_top_z + self.tower_height
            cable_sag = self.cable_extra_height * 0.85
            cable_y = W / 2 + self.rope_size / 2
            for sign in (-1, 1):
                _add_rope(
                    bm, slot_ranges, 1,
                    -L / 2, L / 2, sign * cable_y,
                    cable_top_z, cable_top_z,
                    cable_sag,
                    self.n_rope_segments, self.rope_size,
                )
            # Vertical drops, evenly spaced; skip the endpoints so they
            # don't merge into the towers.
            n_s = self.n_suspenders
            sus_size = self.rope_size * 0.7
            for k in range(n_s):
                t = (k + 1) / (n_s + 1)
                x = -L / 2 + L * t
                cable_z = cable_top_z + _sag_z(t, cable_sag)
                deck_z = deck_top_z + _sag_z(t, self.sag)
                if cable_z <= deck_z:
                    continue
                cz = (cable_z + deck_z) / 2
                sz = cable_z - deck_z
                for sign in (-1, 1):
                    _add_box_slot(
                        bm, slot_ranges, 1,
                        x, sign * cable_y, cz,
                        sus_size, sus_size, sz,
                    )

        me = bpy.data.meshes.new(
            f"LowPolySuspensionBridge({self.factory_seed})_Mesh"
        )
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(
            f"LowPolySuspensionBridge({self.factory_seed})", me
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
            obj, [self.deck_color, self.rope_color, self.tower_color]
        )
        return obj

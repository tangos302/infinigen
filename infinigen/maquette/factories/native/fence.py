"""LowPolyFenceFactory — straight fence segments.

Tier-1 factory per empirical attempt log: missing in 4/6 prompt
attempts (medieval village, Wild West, fishing village, monastery).
Defines property lines, livestock pens, garden plots — narrative-
critical for "this is an inhabited place".

Archetypes:
  picket          — thin vertical slats between square posts
                    (suburban / cottage front yard)
  post_and_rail   — sparse posts + N horizontal rails
                    (corral / ranch / Wild West)
  stone_wall      — sequence of slightly displaced low cubes
                    (monastery / boundary wall)
  wooden_plank    — horizontal plank rows between posts
                    (fishing village / boardwalk railing)

Knobs let the caller stretch a fence along an arbitrary length
without re-deriving spacing — post density auto-adapts. Layout
is along +X (length axis); the caller is expected to translate /
rotate the resulting object into world space.

Material slots:
  slot 0 = posts + main wall material   (default `wood`)
  slot 1 = accent (top rail caps, etc.) (default same as slot 0)

The accent slot exists to let some archetypes (e.g. picket) get
a contrast top cap without forcing every archetype to use it.
"""

from __future__ import annotations

import math
import random

import bmesh
import bpy
from mathutils import Vector

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_FENCE_ARCHETYPES = ("picket", "post_and_rail", "stone_wall", "wooden_plank")


# Per-archetype default proportions + colors. Caller can override any
# individual knob; archetype is just sensible defaults.
_ARCHETYPE_DEFAULTS = {
    "picket": dict(
        length=6.0, height=1.0,
        post_spacing=1.5, post_radius=0.05,
        n_rails=2, slat_density=4.0, slat_width=0.06, slat_thickness=0.03,
        plank_thickness=0.03,
        wall_color="wood", accent_color="wood",
    ),
    "post_and_rail": dict(
        length=6.0, height=1.2,
        post_spacing=2.0, post_radius=0.07,
        n_rails=3, slat_density=0.0, slat_width=0.0, slat_thickness=0.06,
        plank_thickness=0.04,
        wall_color="wood", accent_color="wood",
    ),
    "stone_wall": dict(
        length=6.0, height=0.8,
        post_spacing=0.5, post_radius=0.22,  # post_radius repurposed as stone size
        n_rails=0, slat_density=0.0, slat_width=0.0, slat_thickness=0.0,
        plank_thickness=0.0,
        crenellated_top=False, merlon_height=0.4,
        merlon_width=0.5, merlon_gap=0.4,
        wall_color="rock_pale", accent_color="rock_shadow",
    ),
    "wooden_plank": dict(
        length=6.0, height=1.1,
        post_spacing=2.0, post_radius=0.06,
        n_rails=0, slat_density=0.0, slat_width=0.0, slat_thickness=0.0,
        plank_thickness=0.05,
        wall_color="wood", accent_color="wood",
    ),
}


def _bm_face_count(bm) -> int:
    return len(bm.faces)


def _add_box(
    bm,
    cx: float, cy: float, cz: float,
    sx: float, sy: float, sz: float,
) -> int:
    """Axis-aligned box centered at (cx, cy, cz) with full sizes (sx, sy, sz).
    Returns face count added (always 6)."""
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


def _post_xs(length: float, post_spacing: float) -> list[float]:
    """X-coordinates of posts along the fence. Always a post at each end;
    intermediate posts are evenly spaced as close to `post_spacing` as
    possible."""
    if length <= 0 or post_spacing <= 0:
        return [0.0]
    n_intervals = max(1, round(length / post_spacing))
    return [length * i / n_intervals for i in range(n_intervals + 1)]


def _add_box_slot(
    bm, slot_ranges: list[tuple[int, int, int]], slot: int,
    cx: float, cy: float, cz: float,
    sx: float, sy: float, sz: float,
) -> None:
    """Add a box and record its (start, end, slot) face range. The caller
    later iterates these ranges to set polygon.material_index."""
    start = _bm_face_count(bm)
    _add_box(bm, cx, cy, cz, sx, sy, sz)
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))


def _build_picket(
    bm, slot_ranges, length: float, height: float, post_spacing: float,
    post_radius: float, slat_density: float, slat_width: float,
    slat_thickness: float, plank_thickness: float, n_rails: int,
) -> None:
    """Picket fence: square posts + thin vertical slats + 1-2 horizontal
    rails. Posts and pickets → slot 0; rails → slot 1."""
    post_size = post_radius * 2
    for x in _post_xs(length, post_spacing):
        _add_box_slot(bm, slot_ranges, 0, x, 0, height / 2, post_size, post_size, height)
    rail_z_positions = [height * (i + 1) / (n_rails + 1) for i in range(n_rails)]
    for rz in rail_z_positions:
        _add_box_slot(bm, slot_ranges, 1, length / 2, 0, rz,
                      length, plank_thickness, plank_thickness * 1.2)
    n_slats = max(1, int(round(length * slat_density)))
    margin = post_size * 1.5
    usable_length = length - margin
    if usable_length > 0 and n_slats > 0:
        gap_x = usable_length / (n_slats + 1)
        for i in range(1, n_slats + 1):
            x = margin / 2 + gap_x * i
            slat_height = height * 0.95
            _add_box_slot(bm, slot_ranges, 0, x, 0, slat_height / 2,
                          slat_width, slat_thickness, slat_height)


def _build_post_and_rail(
    bm, slot_ranges, length: float, height: float, post_spacing: float,
    post_radius: float, n_rails: int, slat_thickness: float,
) -> None:
    """Corral fence: square posts + N horizontal rails. No slats."""
    post_size = post_radius * 2
    posts = _post_xs(length, post_spacing)
    for x in posts:
        _add_box_slot(bm, slot_ranges, 0, x, 0, height / 2,
                      post_size, post_size, height)
    rail_z_positions = [height * (i + 1) / (n_rails + 1) for i in range(n_rails)]
    for j in range(len(posts) - 1):
        x_a, x_b = posts[j], posts[j + 1]
        cx = (x_a + x_b) / 2
        rail_length = (x_b - x_a) - post_size
        if rail_length <= 0:
            continue
        for rz in rail_z_positions:
            _add_box_slot(bm, slot_ranges, 1, cx, 0, rz,
                          rail_length, slat_thickness, slat_thickness)


def _build_stone_wall(
    bm, slot_ranges, length: float, height: float, stone_size: float,
    rng: random.Random, crenellated_top: bool = False,
    merlon_height: float = 0.4, merlon_width: float = 0.5,
    merlon_gap: float = 0.4,
) -> None:
    """A run of slightly varied stones, 1-2 layers tall. Top layer (if
    multi-layer) goes to slot 1 as coping.

    If `crenellated_top=True`, adds a row of merlons (rectangular tooth
    blocks) on top of the wall — the iconic castle-battlement silhouette.
    Merlons go to slot 1 (so they can be coloured differently from the
    base wall if desired)."""
    n_layers = max(1, int(round(height / max(stone_size * 0.85, 0.01))))
    layer_height = height / n_layers
    for layer in range(n_layers):
        x_offset = (stone_size * 0.5) if (layer % 2) else 0.0
        x = x_offset
        slot = 1 if (n_layers > 1 and layer == n_layers - 1) else 0
        while x < length:
            sx = stone_size * rng.uniform(0.7, 1.2)
            sx = min(sx, length - x)
            if sx < stone_size * 0.3:
                break
            sy = stone_size * rng.uniform(0.85, 1.15)
            sz = layer_height * rng.uniform(0.85, 1.05)
            cx = x + sx / 2
            cz = layer * layer_height + sz / 2
            _add_box_slot(bm, slot_ranges, slot, cx, 0, cz, sx, sy, sz)
            x += sx + stone_size * rng.uniform(0.0, 0.1)
    # Crenellations — row of merlons on top, evenly spaced.
    if crenellated_top:
        period = merlon_width + merlon_gap
        n_merlons = max(1, int(round(length / period)))
        # Recompute spacing so merlons distribute evenly along length.
        actual_period = length / n_merlons
        actual_merlon_w = actual_period * (merlon_width / period)
        for k in range(n_merlons):
            mx = (k + 0.5) * actual_period
            _add_box_slot(
                bm, slot_ranges, 1,
                mx, 0, height + merlon_height / 2,
                actual_merlon_w, stone_size, merlon_height,
            )


def _build_wooden_plank(
    bm, slot_ranges, length: float, height: float, post_spacing: float,
    post_radius: float, plank_thickness: float,
) -> None:
    """Horizontal-plank fence: posts + horizontal boards stacked between."""
    post_size = post_radius * 2
    posts = _post_xs(length, post_spacing)
    for x in posts:
        _add_box_slot(bm, slot_ranges, 0, x, 0, height / 2,
                      post_size, post_size, height)
    plank_spacing = plank_thickness * 1.3
    n_planks = max(1, int(height / plank_spacing) - 1)
    for i in range(n_planks):
        z = (i + 1) * (height / (n_planks + 1))
        _add_box_slot(bm, slot_ranges, 0, length / 2, 0, z,
                      length, plank_thickness, plank_thickness)


class LowPolyFenceFactory(AssetFactory):
    """A linear fence segment along the +X axis. Reads as boundary,
    livestock pen, or property line.

    Constructor knobs:

        factory_seed
        fence_archetype : str = "picket"
                          "picket" | "post_and_rail" |
                          "stone_wall" | "wooden_plank"
        length          : float = archetype default
        height          : float
        post_spacing    : float (also stone gap for stone_wall)
        post_radius     : float (also stone size for stone_wall)
        n_rails         : int    horizontal rails (post_and_rail)
        slat_density    : float  pickets per metre (picket)
        slat_width      : float  picket width
        slat_thickness  : float
        plank_thickness : float
        wall_color      : str    slot 0
        accent_color    : str    slot 1 (rails / coping)
    """

    def __init__(
        self,
        factory_seed,
        fence_archetype: str = "picket",
        length: float | None = None,
        height: float | None = None,
        post_spacing: float | None = None,
        post_radius: float | None = None,
        n_rails: int | None = None,
        slat_density: float | None = None,
        slat_width: float | None = None,
        slat_thickness: float | None = None,
        plank_thickness: float | None = None,
        crenellated_top: bool | None = None,
        merlon_height: float | None = None,
        merlon_width: float | None = None,
        merlon_gap: float | None = None,
        wall_color: str | None = None,
        accent_color: str | None = None,
        coarse: bool = False,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if fence_archetype not in _FENCE_ARCHETYPES:
            # Lenient fallback rather than crash. Sonnet has been
            # observed to hallucinate plausible-sounding archetype
            # names despite the factories_guide brief listing the
            # valid set; killing a 6-minute build over a one-line
            # archetype typo wastes a generation. Substitute the
            # canonical default and warn to stderr.
            import sys
            print(
                f"[fence_archetype] WARN: unknown fence_archetype "
                f"{fence_archetype!r}; falling back to {_FENCE_ARCHETYPES[0]!r}. "
                f"Valid: {_FENCE_ARCHETYPES}",
                file=sys.stderr,
            )
            fence_archetype = _FENCE_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[fence_archetype]
        self.fence_archetype = fence_archetype
        self.length = float(length if length is not None else d["length"])
        self.height = float(height if height is not None else d["height"])
        self.post_spacing = float(post_spacing if post_spacing is not None else d["post_spacing"])
        self.post_radius = float(post_radius if post_radius is not None else d["post_radius"])
        self.n_rails = int(n_rails if n_rails is not None else d["n_rails"])
        self.slat_density = float(slat_density if slat_density is not None else d["slat_density"])
        self.slat_width = float(slat_width if slat_width is not None else d["slat_width"])
        self.slat_thickness = float(slat_thickness if slat_thickness is not None else d["slat_thickness"])
        self.plank_thickness = float(plank_thickness if plank_thickness is not None else d["plank_thickness"])
        # Crenellation params only meaningful for stone_wall but exposed
        # uniformly. Default `False` for non-stone_wall archetypes.
        self.crenellated_top = (
            bool(crenellated_top) if crenellated_top is not None
            else d.get("crenellated_top", False)
        )
        self.merlon_height = float(
            merlon_height if merlon_height is not None
            else d.get("merlon_height", 0.4)
        )
        self.merlon_width = float(
            merlon_width if merlon_width is not None
            else d.get("merlon_width", 0.5)
        )
        self.merlon_gap = float(
            merlon_gap if merlon_gap is not None
            else d.get("merlon_gap", 0.4)
        )
        self.wall_color = wall_color or d["wall_color"]
        self.accent_color = accent_color or d["accent_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyFence({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        rng = random.Random(self.factory_seed)
        bm = bmesh.new()
        slot_ranges: list[tuple[int, int, int]] = []

        if self.fence_archetype == "picket":
            _build_picket(
                bm, slot_ranges, self.length, self.height, self.post_spacing,
                self.post_radius, self.slat_density, self.slat_width,
                self.slat_thickness, self.plank_thickness, self.n_rails,
            )
        elif self.fence_archetype == "post_and_rail":
            _build_post_and_rail(
                bm, slot_ranges, self.length, self.height, self.post_spacing,
                self.post_radius, self.n_rails, self.slat_thickness,
            )
        elif self.fence_archetype == "stone_wall":
            _build_stone_wall(
                bm, slot_ranges, self.length, self.height, self.post_radius, rng,
                crenellated_top=self.crenellated_top,
                merlon_height=self.merlon_height,
                merlon_width=self.merlon_width,
                merlon_gap=self.merlon_gap,
            )
        elif self.fence_archetype == "wooden_plank":
            _build_wooden_plank(
                bm, slot_ranges, self.length, self.height, self.post_spacing,
                self.post_radius, self.plank_thickness,
            )
        else:
            raise AssertionError(self.fence_archetype)

        me = bpy.data.meshes.new(f"LowPolyFence({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(f"LowPolyFence({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)

        while len(obj.data.materials) < 2:
            obj.data.materials.append(None)

        for start, end, slot in slot_ranges:
            for i in range(start, end):
                obj.data.polygons[i].material_index = slot

        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(obj, [self.wall_color, self.accent_color])
        return obj

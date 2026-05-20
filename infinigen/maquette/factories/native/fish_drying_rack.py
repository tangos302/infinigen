"""LowPolyFishDryingRackFactory — coastal fish-drying rack.

The signature prop of a fishing village. Without it a "fishing village"
reads as a generic market town that happens to sit by water — houses and
stalls give no fishing story. A timber rack hung with split fish drying
in the sun is the single object that says "this settlement lives off the
sea". Place these on the shoreline / dock approach, never in a plaza.

Build approach: axis-aligned timber boxes only — vertical posts plus
horizontal cross-rails — with small two-box fish (body + tail wedge)
hung in a row beneath each rail. Flat-shaded chunky timber + pale fish
reads as low-poly without any skew/rotation maths.

Archetypes:
  single_rail  — two posts, one rail near the top, a row of fish.
                 The small everyday rack. Default.
  triple_tier  — two taller posts, three stacked rails, fish on each —
                 a productive rack for a busy harbour.
  wide_double  — four posts in two bays, two long rails, the most fish.
                 A focal rack for the dock front.

Material slots:
  slot 0 = timber frame (posts + rails)   default `wood`
  slot 1 = hanging fish                    default `rock_pale`
"""

from __future__ import annotations

import random

import bmesh
import bpy

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_FISH_RACK_ARCHETYPES = ("single_rail", "triple_tier", "wide_double")


_ARCHETYPE_DEFAULTS = {
    "single_rail": dict(
        post_height=1.9, span=2.6, n_bays=1, n_rails=1, fish_per_rail=5,
        frame_color="wood", fish_color="rock_pale",
    ),
    "triple_tier": dict(
        post_height=2.7, span=2.8, n_bays=1, n_rails=3, fish_per_rail=5,
        frame_color="wood", fish_color="rock_pale",
    ),
    "wide_double": dict(
        post_height=2.1, span=5.2, n_bays=2, n_rails=2, fish_per_rail=8,
        frame_color="wood", fish_color="rock_pale",
    ),
}


def _add_box(bm, center, size) -> tuple[int, int]:
    """Append an axis-aligned box. Returns (start_face, end_face)."""
    prev = len(bm.faces)
    res = bmesh.ops.create_cube(bm, size=1.0)
    cx, cy, cz = center
    sx, sy, sz = size
    for v in res["verts"]:
        v.co.x = v.co.x * sx + cx
        v.co.y = v.co.y * sy + cy
        v.co.z = v.co.z * sz + cz
    bm.faces.ensure_lookup_table()
    return prev, len(bm.faces)


class LowPolyFishDryingRackFactory(AssetFactory):
    """A low-poly timber fish-drying rack — the focal storytelling prop
    of a fishing village.

    The asset origin sits at the ground; all geometry is built upward
    from z=0 so callers can drop it straight onto terrain.

    Constructor knobs:

        factory_seed
        fish_rack_archetype : str = "single_rail"
                              "single_rail" | "triple_tier" | "wide_double"
        post_height         : float  post height (m)
        span                : float  rack length along x (m)
        n_bays              : int     1 or 2 post bays
        n_rails             : int     stacked horizontal rails
        fish_per_rail       : int     fish hung per rail
        frame_color         : str     slot 0 palette key
        fish_color          : str     slot 1 palette key
    """

    def __init__(
        self,
        factory_seed,
        fish_rack_archetype: str = "single_rail",
        post_height: float | None = None,
        span: float | None = None,
        n_bays: int | None = None,
        n_rails: int | None = None,
        fish_per_rail: int | None = None,
        frame_color: str | None = None,
        fish_color: str | None = None,
        coarse: bool = False,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if fish_rack_archetype not in _FISH_RACK_ARCHETYPES:
            # Lenient fallback — an LLM archetype typo must not kill a build.
            import sys
            print(
                f"[fish_rack_archetype] WARN: unknown fish_rack_archetype "
                f"{fish_rack_archetype!r}; falling back to {_FISH_RACK_ARCHETYPES[0]!r}. "
                f"Valid: {_FISH_RACK_ARCHETYPES}",
                file=sys.stderr,
            )
            fish_rack_archetype = _FISH_RACK_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[fish_rack_archetype]
        self.fish_rack_archetype = fish_rack_archetype
        self.post_height = float(post_height if post_height is not None else d["post_height"])
        self.span = float(span if span is not None else d["span"])
        self.n_bays = int(n_bays if n_bays is not None else d["n_bays"])
        self.n_rails = int(n_rails if n_rails is not None else d["n_rails"])
        self.fish_per_rail = int(fish_per_rail if fish_per_rail is not None else d["fish_per_rail"])
        self.frame_color = frame_color or d["frame_color"]
        self.fish_color = fish_color or d["fish_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyFishDryingRack({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        rng = random.Random(self.factory_seed)
        bm = bmesh.new()
        frame_faces: list[tuple[int, int]] = []
        fish_faces: list[tuple[int, int]] = []

        post_t = 0.12          # post cross-section
        rail_t = 0.08          # rail cross-section
        h = self.post_height
        half = self.span / 2.0
        # x positions of the post rows: 2 for one bay, 3 for two bays.
        n_posts = self.n_bays + 1
        post_x = [-half + (self.span * k / self.n_bays) for k in range(n_posts)]

        for px in post_x:
            frame_faces.append(_add_box(bm, (px, 0.0, h / 2.0), (post_t, post_t, h)))

        # Stacked horizontal rails spanning the full rack length.
        rail_zs: list[float] = []
        low = h * 0.42
        for r in range(self.n_rails):
            frac = r / max(1, self.n_rails - 1) if self.n_rails > 1 else 1.0
            rz = low + (h * 0.96 - low) * frac
            rail_zs.append(rz)
            frame_faces.append(_add_box(bm, (0.0, 0.0, rz), (self.span + post_t, rail_t, rail_t)))

        # Hang fish (body + tail) in a row beneath each rail.
        fish_len = 0.34
        for rz in rail_zs:
            for f in range(self.fish_per_rail):
                t = (f + 0.5) / self.fish_per_rail
                fx = -half * 0.86 + (self.span * 0.86) * t
                drop = rz - 0.22 - rng.uniform(0.0, 0.06)
                # Body — a flat elongated box.
                fish_faces.append(_add_box(
                    bm, (fx, 0.0, drop), (fish_len, 0.07, 0.16)
                ))
                # Tail — a smaller wedge box at the rear.
                fish_faces.append(_add_box(
                    bm, (fx - fish_len * 0.62, 0.0, drop), (fish_len * 0.32, 0.05, 0.20)
                ))

        me = bpy.data.meshes.new(f"LowPolyFishDryingRack({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(f"LowPolyFishDryingRack({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)

        while len(obj.data.materials) < 2:
            obj.data.materials.append(None)
        for start, end in frame_faces:
            for i in range(start, end):
                obj.data.polygons[i].material_index = 0
        for start, end in fish_faces:
            for i in range(start, end):
                obj.data.polygons[i].material_index = 1
        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(obj, [self.frame_color, self.fish_color])
        return obj

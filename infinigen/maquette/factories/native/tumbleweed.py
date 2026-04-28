"""LowPolyTumbleweedFactory — round tumbling brush.

Surfaced when a desert / Wild West / wasteland scene needs the classic
tumbleweed prop rolling across the ground. Without it the silhouette
language for "abandoned dusty road" is missing — boulders read as
geological, bushes read as alive, but tumbleweeds read as
"transient, desiccated, in motion".

Build approach: a clump of overlapping low-subdivision icospheres
packed inside a roughly spherical bounding region (so the silhouette
stays round, not sprawling like a ground bush). The icosphere overlap
gives the lumpy boulder-like profile, the multiplicity reads as
tangled brushwork, and flat-shaded chunky facets sell "low-poly dry
plant" rather than "smooth stylized boulder".

Archetypes:
  dry      — classic dead tumbleweed. Yellow-tan, ~5-7 overlapping
             spheres of varied size, slightly squashed sphere envelope
             (sits stable on the ground). Default.
  dense    — packed denser tumbleweed, more (and slightly smaller)
             icospheres, fuller silhouette. Same color family.
  sparse   — wispy, fewer larger icospheres, more open silhouette.
             Used for half-disintegrated tumbleweeds at the side of
             the road.
  green    — alive / young tumbleweed (Russian thistle still rooted),
             muted green palette.

Material slots:
  slot 0 = brush body              (default `foliage_lemon` for dry,
                                    `foliage_bush` for green)
  slot 1 = darker accent / shadow  (default `wood` — twiggy core
                                    showing through; same across
                                    archetypes)

The accent slot covers ~1/3 of the icospheres (chosen by index) to
give per-clump tonal variety without instancing separate materials.
"""

from __future__ import annotations

import math
import random

import bmesh
import bpy
from mathutils import Vector

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_TUMBLEWEED_ARCHETYPES = ("dry", "dense", "sparse", "green")


_ARCHETYPE_DEFAULTS = {
    "dry": dict(
        radius=0.55,
        squash=0.85,
        n_clumps_range=(5, 7),
        clump_radius_fraction_range=(0.45, 0.75),
        offset_fraction=0.55,
        icosphere_subdivisions=1,
        accent_fraction=0.35,
        body_color="foliage_lemon",
        accent_color="wood",
    ),
    "dense": dict(
        radius=0.50,
        squash=0.90,
        n_clumps_range=(7, 10),
        clump_radius_fraction_range=(0.40, 0.65),
        offset_fraction=0.45,
        icosphere_subdivisions=1,
        accent_fraction=0.30,
        body_color="foliage_lemon",
        accent_color="wood",
    ),
    "sparse": dict(
        radius=0.60,
        squash=0.80,
        n_clumps_range=(3, 5),
        clump_radius_fraction_range=(0.55, 0.85),
        offset_fraction=0.60,
        icosphere_subdivisions=1,
        accent_fraction=0.40,
        body_color="foliage_lemon",
        accent_color="wood",
    ),
    "green": dict(
        radius=0.50,
        squash=0.90,
        n_clumps_range=(5, 7),
        clump_radius_fraction_range=(0.50, 0.75),
        offset_fraction=0.50,
        icosphere_subdivisions=1,
        accent_fraction=0.30,
        body_color="foliage_bush",
        accent_color="wood",
    ),
}


def _bm_face_count(bm) -> int:
    return len(bm.faces)


def _add_icosphere_clump(
    bm,
    center: Vector,
    rxy: float,
    rz: float,
    subdivisions: int,
) -> int:
    """Append a single ellipsoidal icosphere to `bm`. Returns the
    number of faces added."""
    prev = _bm_face_count(bm)
    result = bmesh.ops.create_icosphere(bm, subdivisions=subdivisions, radius=1.0)
    new_verts = result["verts"]
    for v in new_verts:
        v.co.x = v.co.x * rxy + center.x
        v.co.y = v.co.y * rxy + center.y
        v.co.z = v.co.z * rz + center.z
    bm.faces.ensure_lookup_table()
    return _bm_face_count(bm) - prev


class LowPolyTumbleweedFactory(AssetFactory):
    """A low-poly desert tumbleweed: a roughly-spherical clump of
    overlapping icospheres that reads as tangled dry brush.

    The asset's origin sits at the ground; the clump's center is
    lifted by `radius * squash` so the bottom of the bounding ball
    rests on z=0 (callers can place it directly without offsetting).

    Constructor knobs:

        factory_seed
        tumbleweed_archetype          : str = "dry"
                                        "dry" | "dense" | "sparse" | "green"
        radius                        : float  bounding-ball radius (m)
        squash                        : float  vertical-radius fraction
                                                (1.0 = sphere, <1.0 = squashed)
        n_clumps_range                : (int, int) sphere-count range
        clump_radius_fraction_range   : (float, float) per-sphere radius as
                                                       fraction of `radius`
        offset_fraction               : float  max sphere-center offset from
                                                bounding-ball center, as
                                                fraction of `radius`
        icosphere_subdivisions        : int    1 = 80 polys per sphere
        accent_fraction               : float  fraction of clumps tagged on
                                                slot 1 for tonal variety
        body_color                    : str    slot 0 palette key
        accent_color                  : str    slot 1 palette key
    """

    def __init__(
        self,
        factory_seed,
        tumbleweed_archetype: str = "dry",
        radius: float | None = None,
        squash: float | None = None,
        n_clumps_range: tuple[int, int] | None = None,
        clump_radius_fraction_range: tuple[float, float] | None = None,
        offset_fraction: float | None = None,
        icosphere_subdivisions: int | None = None,
        accent_fraction: float | None = None,
        body_color: str | None = None,
        accent_color: str | None = None,
        coarse: bool = False,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if tumbleweed_archetype not in _TUMBLEWEED_ARCHETYPES:
            raise ValueError(
                f"unknown tumbleweed_archetype {tumbleweed_archetype!r}; "
                f"valid: {_TUMBLEWEED_ARCHETYPES}"
            )
        d = _ARCHETYPE_DEFAULTS[tumbleweed_archetype]
        self.tumbleweed_archetype = tumbleweed_archetype
        self.radius = float(radius if radius is not None else d["radius"])
        self.squash = float(squash if squash is not None else d["squash"])
        self.n_clumps_range = tuple(
            n_clumps_range if n_clumps_range is not None else d["n_clumps_range"]
        )
        self.clump_radius_fraction_range = tuple(
            clump_radius_fraction_range
            if clump_radius_fraction_range is not None
            else d["clump_radius_fraction_range"]
        )
        self.offset_fraction = float(
            offset_fraction if offset_fraction is not None else d["offset_fraction"]
        )
        self.icosphere_subdivisions = int(
            icosphere_subdivisions
            if icosphere_subdivisions is not None
            else d["icosphere_subdivisions"]
        )
        self.accent_fraction = float(
            accent_fraction if accent_fraction is not None else d["accent_fraction"]
        )
        self.body_color = body_color or d["body_color"]
        self.accent_color = accent_color or d["accent_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyTumbleweed({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        rng = random.Random(self.factory_seed)
        bm = bmesh.new()
        slot_ranges: list[tuple[int, int, int]] = []

        rz_envelope = self.radius * self.squash
        # Lift the cluster center so the bottom of the bounding ball rests
        # at z=0 — callers can drop the asset onto the ground without
        # vertical offset bookkeeping.
        center_z = rz_envelope

        n_clumps = rng.randint(*self.n_clumps_range)
        # Reserve at least one accent clump when accent_fraction > 0; this
        # avoids the common case of small n_clumps rounding to zero accents
        # and the slot 1 region staying empty.
        n_accent = max(1, round(n_clumps * self.accent_fraction)) if self.accent_fraction > 0 else 0
        accent_idx = set(rng.sample(range(n_clumps), min(n_accent, n_clumps)))

        for i in range(n_clumps):
            f_min, f_max = self.clump_radius_fraction_range
            clump_r = self.radius * rng.uniform(f_min, f_max)
            # Random offset inside an ellipsoidal envelope (cube-rejection
            # would be tighter but with n<=10 a simple per-axis uniform
            # sample with the offset_fraction bound is fine — the
            # icosphere overlap forgives small protrusions).
            ox = rng.uniform(-1, 1) * self.radius * self.offset_fraction
            oy = rng.uniform(-1, 1) * self.radius * self.offset_fraction
            oz = rng.uniform(-1, 1) * rz_envelope * self.offset_fraction
            center = Vector((ox, oy, center_z + oz))
            # Each clump is itself slightly squashed so the overall
            # silhouette doesn't gain isolated tall spires.
            clump_rxy = clump_r
            clump_rz = clump_r * rng.uniform(0.75, 1.0)

            start = _bm_face_count(bm)
            _add_icosphere_clump(
                bm, center, clump_rxy, clump_rz, self.icosphere_subdivisions
            )
            end = _bm_face_count(bm)
            slot = 1 if i in accent_idx else 0
            slot_ranges.append((start, end, slot))

        me = bpy.data.meshes.new(f"LowPolyTumbleweed({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(f"LowPolyTumbleweed({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)

        while len(obj.data.materials) < 2:
            obj.data.materials.append(None)

        for start, end, slot in slot_ranges:
            for i in range(start, end):
                obj.data.polygons[i].material_index = slot

        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(obj, [self.body_color, self.accent_color])
        return obj

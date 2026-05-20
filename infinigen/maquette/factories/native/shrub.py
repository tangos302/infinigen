"""LowPolyShrubFactory — ground vegetation: bushes and ferns.

Low foliage to fill the floor between hero trees — jungle understorey,
temperate hedgerows, desert scrub. Leafy bushes are clusters of faceted
foliage clumps; ferns are rosettes of arching fronds; the dry archetypes
are bare twig clusters.

Archetypes:
  round_bush      — a rounded leafy bush, a cluster of foliage clumps
  flowering_bush  — a leafy bush dotted with flower clumps
  forest_fern     — a rosette of arching fronds; jungle understorey
  dead_bush       — a bare twiggy shrub, no foliage
  desert_scrub    — a low scraggly shrub: sparse foliage plus dry twigs

Material slots:
  slot 0 = foliage (bush leaves, fern fronds)
  slot 1 = wood (twigs, dry branches)
  slot 2 = flower accent (flowering_bush)
"""

from __future__ import annotations

import math
import random

import bmesh
import bpy

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_SHRUB_ARCHETYPES = ("round_bush", "flowering_bush", "forest_fern", "dead_bush", "desert_scrub")

# Per-archetype (foliage_color, wood_color) defaults.
_ARCHETYPE_COLORS = {
    "round_bush": ("foliage_bush", "wood"),
    "flowering_bush": ("foliage_bush", "wood"),
    "forest_fern": ("foliage_apple", "wood"),
    "dead_bush": ("foliage_bush", "wood"),
    "desert_scrub": ("foliage_bush", "wood"),
}


def _face_count(bm: bmesh.types.BMesh) -> int:
    return len(bm.faces)


def _add_foliage_clump(
    bm: bmesh.types.BMesh,
    *,
    cx: float,
    cy: float,
    cz: float,
    radius: float,
    flatten: float,
    slot: int,
    slot_ranges: list[tuple[int, int, int]],
    rng: random.Random,
) -> None:
    """A faceted low-poly foliage blob — a jittered 20-face icosphere."""
    start = _face_count(bm)
    result = bmesh.ops.create_icosphere(bm, subdivisions=1, radius=1.0)
    sx = radius * rng.uniform(0.85, 1.15)
    sy = radius * rng.uniform(0.85, 1.15)
    sz = radius * flatten * rng.uniform(0.85, 1.10)
    for v in result["verts"]:
        nx = cx + v.co.x * sx + rng.uniform(-radius * 0.14, radius * 0.14)
        ny = cy + v.co.y * sy + rng.uniform(-radius * 0.14, radius * 0.14)
        nz = cz + v.co.z * sz + rng.uniform(-radius * 0.12, radius * 0.12)
        v.co = (nx, ny, nz)
    slot_ranges.append((start, _face_count(bm), int(slot)))


def _add_twig(
    bm: bmesh.types.BMesh,
    *,
    base_x: float,
    base_y: float,
    base_z: float,
    length: float,
    base_radius: float,
    lean_x: float,
    lean_y: float,
    n_sides: int,
    slot: int,
    slot_ranges: list[tuple[int, int, int]],
    rng: random.Random,
) -> None:
    """A thin tapered twig — a polygon base rising to a leaned point."""
    start = _face_count(bm)
    base = []
    for i in range(n_sides):
        a = 2.0 * math.pi * i / n_sides
        r = base_radius * (1.0 + rng.uniform(-0.2, 0.2))
        base.append(bm.verts.new((base_x + r * math.cos(a), base_y + r * math.sin(a), base_z)))
    tip = bm.verts.new((base_x + lean_x, base_y + lean_y, base_z + length))
    bm.verts.ensure_lookup_table()
    for i in range(n_sides):
        ni = (i + 1) % n_sides
        bm.faces.new((base[i], base[ni], tip))
    bm.faces.new(tuple(reversed(base)))
    slot_ranges.append((start, _face_count(bm), int(slot)))


def _add_frond(
    bm: bmesh.types.BMesh,
    *,
    base_x: float,
    base_y: float,
    base_z: float,
    out_dir: tuple[float, float],
    out_reach: float,
    rise: float,
    droop: float,
    base_width: float,
    n_seg: int,
    slot: int,
    slot_ranges: list[tuple[int, int, int]],
) -> None:
    """A fern frond — a flat blade arcing up and out, the tip drooping
    back down, tapering from base_width to a point."""
    odx, ody = out_dir
    perp_x, perp_y = -ody, odx
    pairs = []
    for k in range(n_seg):
        f = k / n_seg
        out = out_reach * (f ** 0.85)
        z = base_z + rise * f - droop * (f ** 2.4)
        x = base_x + odx * out
        y = base_y + ody * out
        w = base_width * (1.0 - 0.8 * f)
        pairs.append(
            (
                bm.verts.new((x + perp_x * w, y + perp_y * w, z)),
                bm.verts.new((x - perp_x * w, y - perp_y * w, z)),
            )
        )
    tip = bm.verts.new(
        (base_x + odx * out_reach, base_y + ody * out_reach, base_z + rise - droop)
    )
    bm.verts.ensure_lookup_table()
    start = _face_count(bm)
    for k in range(n_seg - 1):
        l0, r0 = pairs[k]
        l1, r1 = pairs[k + 1]
        bm.faces.new((l0, r0, r1, l1))
    l_last, r_last = pairs[-1]
    bm.faces.new((l_last, r_last, tip))
    slot_ranges.append((start, _face_count(bm), int(slot)))


class LowPolyShrubFactory(AssetFactory):
    """Procedural ground vegetation — bushes and ferns.

    Constructor knobs:
        factory_seed
        shrub_archetype : "round_bush" | "flowering_bush" | "forest_fern"
                          | "dead_bush" | "desert_scrub"
        foliage_color, wood_color, flower_color
    """

    def __init__(
        self,
        factory_seed,
        shrub_archetype: str = "round_bush",
        foliage_color: str | None = None,
        wood_color: str | None = None,
        flower_color: str | None = None,
        coarse: bool = False,
        **_unused_kwargs,
    ) -> None:
        super().__init__(factory_seed, coarse=coarse)
        if _unused_kwargs:
            from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
            accept_unused_kwargs("LowPolyShrubFactory", _unused_kwargs)
        if shrub_archetype not in _SHRUB_ARCHETYPES:
            import sys
            print(
                f"[shrub_archetype] WARN: unknown {shrub_archetype!r}; "
                f"falling back to {_SHRUB_ARCHETYPES[0]!r}. Valid: {_SHRUB_ARCHETYPES}",
                file=sys.stderr,
            )
            shrub_archetype = _SHRUB_ARCHETYPES[0]
        self.shrub_archetype = shrub_archetype
        _foliage_default, _wood_default = _ARCHETYPE_COLORS[shrub_archetype]
        self.foliage_color = foliage_color or _foliage_default
        self.wood_color = wood_color or _wood_default
        self.flower_color = flower_color or "foliage_rose"

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(f"LowPolyShrub({self.factory_seed})_placeholder", None)
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        rng = random.Random(int(self.factory_seed) + 24859)
        builders = {
            "round_bush": self._build_round_bush,
            "flowering_bush": self._build_flowering_bush,
            "forest_fern": self._build_forest_fern,
            "dead_bush": self._build_dead_bush,
            "desert_scrub": self._build_desert_scrub,
        }
        return builders[self.shrub_archetype](rng)

    def _finalize(
        self, bm: bmesh.types.BMesh, slot_ranges: list[tuple[int, int, int]]
    ) -> bpy.types.Object:
        me = bpy.data.meshes.new(f"LowPolyShrub({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()
        obj = bpy.data.objects.new(
            f"LowPolyShrub({self.factory_seed})_{self.shrub_archetype}", me
        )
        bpy.context.scene.collection.objects.link(obj)
        while len(obj.data.materials) < 3:
            obj.data.materials.append(None)
        for start, end, slot in slot_ranges:
            for face_idx in range(start, end):
                obj.data.polygons[face_idx].material_index = slot
        for poly in obj.data.polygons:
            poly.use_smooth = False
        apply_palette_slots(
            obj, [self.foliage_color, self.wood_color, self.flower_color]
        )
        return obj

    def _bush_mass(
        self,
        bm: bmesh.types.BMesh,
        slot_ranges: list[tuple[int, int, int]],
        rng: random.Random,
        *,
        radius: float,
        height: float,
        n_clumps: int,
    ) -> None:
        """A rounded bush — a cluster of overlapping foliage clumps."""
        for _ in range(n_clumps):
            a = rng.uniform(0.0, 2.0 * math.pi)
            rr = radius * 0.55 * math.sqrt(rng.uniform(0.0, 1.0))
            cz = height * rng.uniform(0.34, 0.86)
            _add_foliage_clump(
                bm, cx=rr * math.cos(a), cy=rr * math.sin(a), cz=cz,
                radius=radius * rng.uniform(0.40, 0.62), flatten=0.85,
                slot=0, slot_ranges=slot_ranges, rng=rng,
            )

    # -- archetype builders ------------------------------------------------

    def _build_round_bush(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        radius = rng.uniform(0.5, 0.72)
        height = rng.uniform(0.7, 1.05)
        self._bush_mass(bm, sr, rng, radius=radius, height=height,
                        n_clumps=rng.randint(5, 8))
        return self._finalize(bm, sr)

    def _build_flowering_bush(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        radius = rng.uniform(0.5, 0.7)
        height = rng.uniform(0.7, 1.0)
        self._bush_mass(bm, sr, rng, radius=radius, height=height,
                        n_clumps=rng.randint(5, 8))
        # flower clumps ride the outer / upper surface of the bush, big
        # enough to clearly distinguish it from a plain round_bush
        for _ in range(rng.randint(11, 17)):
            a = rng.uniform(0.0, 2.0 * math.pi)
            rr = radius * rng.uniform(0.55, 0.92)
            cz = height * rng.uniform(0.50, 1.02)
            _add_foliage_clump(
                bm, cx=rr * math.cos(a), cy=rr * math.sin(a), cz=cz,
                radius=rng.uniform(0.09, 0.14), flatten=0.85,
                slot=2, slot_ranges=sr, rng=rng,
            )
        return self._finalize(bm, sr)

    def _build_forest_fern(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        n = rng.randint(8, 13)
        for i in range(n):
            a = 2.0 * math.pi * i / n + rng.uniform(-0.25, 0.25)
            rise = rng.uniform(0.55, 0.88)
            _add_frond(
                bm,
                base_x=rng.uniform(-0.05, 0.05),
                base_y=rng.uniform(-0.05, 0.05),
                base_z=rng.uniform(0.0, 0.07),
                out_dir=(math.cos(a), math.sin(a)),
                out_reach=rng.uniform(0.50, 0.88),
                rise=rise,
                droop=rise * rng.uniform(0.5, 0.85),
                base_width=rng.uniform(0.07, 0.11),
                n_seg=5,
                slot=0,
                slot_ranges=sr,
            )
        return self._finalize(bm, sr)

    def _build_dead_bush(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        for _ in range(rng.randint(9, 15)):
            a = rng.uniform(0.0, 2.0 * math.pi)
            rr = rng.uniform(0.0, 0.13)
            length = rng.uniform(0.5, 1.05)
            lean = length * rng.uniform(0.15, 0.55)
            ldir = a + rng.uniform(-0.5, 0.5)
            _add_twig(
                bm, base_x=rr * math.cos(a), base_y=rr * math.sin(a), base_z=0.0,
                length=length, base_radius=rng.uniform(0.025, 0.045),
                lean_x=math.cos(ldir) * lean, lean_y=math.sin(ldir) * lean,
                n_sides=4, slot=1, slot_ranges=sr, rng=rng,
            )
        return self._finalize(bm, sr)

    def _build_desert_scrub(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        for _ in range(rng.randint(2, 4)):
            a = rng.uniform(0.0, 2.0 * math.pi)
            rr = rng.uniform(0.0, 0.28)
            _add_foliage_clump(
                bm, cx=rr * math.cos(a), cy=rr * math.sin(a),
                cz=rng.uniform(0.22, 0.42), radius=rng.uniform(0.18, 0.28),
                flatten=0.7, slot=0, slot_ranges=sr, rng=rng,
            )
        for _ in range(rng.randint(5, 9)):
            a = rng.uniform(0.0, 2.0 * math.pi)
            rr = rng.uniform(0.0, 0.20)
            length = rng.uniform(0.32, 0.62)
            lean = length * rng.uniform(0.25, 0.65)
            ldir = a + rng.uniform(-0.5, 0.5)
            _add_twig(
                bm, base_x=rr * math.cos(a), base_y=rr * math.sin(a), base_z=0.0,
                length=length, base_radius=rng.uniform(0.020, 0.034),
                lean_x=math.cos(ldir) * lean, lean_y=math.sin(ldir) * lean,
                n_sides=4, slot=1, slot_ranges=sr, rng=rng,
            )
        return self._finalize(bm, sr)

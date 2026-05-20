"""LowPolyNaturalArchFactory — natural rock arches and dramatic landmarks.

Hero rock formations that anchor a landscape — distinct from the spiky
LowPolyRockSpireFactory. The lower band of each formation takes a second
palette tone so it reads as base strata or a wet waterline.

Archetypes:
  desert_arch    — a tall slender sandstone arch
  sea_arch       — a thick, broad wave-cut coastal arch
  sea_stack      — a tall isolated rock pillar (with a companion stack)
  balanced_rock  — a big boulder perched on a slim eroded pedestal

Material slots:
  slot 0 = rock
  slot 1 = base band — lower strata / waterline / rubble
"""

from __future__ import annotations

import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_ARCH_ARCHETYPES = ("desert_arch", "sea_arch", "sea_stack", "balanced_rock")

# Per-archetype (rock_color, band_color).
_ARCHETYPE_COLORS = {
    "desert_arch": ("rock_warm", "rock_pale"),
    "sea_arch": ("rock_cool", "rock_shadow"),
    "sea_stack": ("rock_cool", "rock_shadow"),
    "balanced_rock": ("rock_pale", "rock_warm"),
}


def _face_count(bm: bmesh.types.BMesh) -> int:
    return len(bm.faces)


def _add_arch_band(
    bm: bmesh.types.BMesh,
    *,
    span_half: float,
    leg_height: float,
    arch_rise: float,
    cross_radius: float,
    depth_scale: float,
    n_path: int,
    n_sides: int,
    band_z: float,
    slot_main: int,
    slot_band: int,
    slot_ranges: list[tuple[int, int, int]],
    rng: random.Random,
) -> None:
    """A chunky rock band swept along a leg-span-leg arch curve. The
    centerline is two vertical legs joined by a half-sine span; a jittered
    polygon cross-section is carried along it."""
    n_leg = max(2, n_path // 5)
    centerline: list[tuple[float, float]] = []
    for k in range(n_leg):
        centerline.append((-span_half, leg_height * (k / n_leg)))
    for k in range(n_path + 1):
        ang = math.pi * (k / n_path)
        centerline.append(
            (-span_half * math.cos(ang), leg_height + arch_rise * math.sin(ang))
        )
    for k in range(1, n_leg + 1):
        centerline.append((span_half, leg_height * (1.0 - k / n_leg)))

    n_total = len(centerline)
    rings: list[tuple[list[bmesh.types.BMVert], float]] = []
    for idx, (x, z) in enumerate(centerline):
        px, pz = centerline[max(0, idx - 1)]
        nx, nz = centerline[min(n_total - 1, idx + 1)]
        tx, tz = nx - px, nz - pz
        tl = math.hypot(tx, tz) or 1.0
        tx, tz = tx / tl, tz / tl
        perp_x, perp_z = -tz, tx
        r = cross_radius * (1.0 + rng.uniform(-0.18, 0.18))
        ring = []
        for i in range(n_sides):
            a = 2.0 * math.pi * i / n_sides
            c, s = math.cos(a), math.sin(a)
            ring.append(
                bm.verts.new(
                    (x + perp_x * r * c, r * depth_scale * s, z + perp_z * r * c)
                )
            )
        rings.append((ring, z))
    bm.verts.ensure_lookup_table()
    for k in range(len(rings) - 1):
        ring0, z0 = rings[k]
        ring1, z1 = rings[k + 1]
        seg_slot = slot_band if (z0 + z1) * 0.5 < band_z else slot_main
        start = _face_count(bm)
        for i in range(n_sides):
            ni = (i + 1) % n_sides
            bm.faces.new((ring0[i], ring0[ni], ring1[ni], ring1[i]))
        slot_ranges.append((start, _face_count(bm), int(seg_slot)))
    for ring, _z in (rings[0], rings[-1]):
        start = _face_count(bm)
        bm.faces.new(tuple(ring))
        slot_ranges.append((start, _face_count(bm), int(slot_band)))


def _add_rock_column(
    bm: bmesh.types.BMesh,
    *,
    cx: float,
    cy: float,
    base_radius: float,
    height: float,
    taper: float = 0.5,
    n_rings: int,
    n_sides: int,
    band_z: float,
    slot_main: int,
    slot_band: int,
    slot_ranges: list[tuple[int, int, int]],
    rng: random.Random,
) -> None:
    """A tall irregular tapered rock column — a sea stack or a pedestal."""
    rings: list[tuple[list[bmesh.types.BMVert], float]] = []
    for k in range(n_rings + 1):
        f = k / n_rings
        z = height * f
        r = base_radius * (1.0 - taper * f) * (1.0 + rng.uniform(-0.16, 0.16))
        dx = rng.uniform(-base_radius * 0.12, base_radius * 0.12)
        dy = rng.uniform(-base_radius * 0.12, base_radius * 0.12)
        ring = []
        for i in range(n_sides):
            a = 2.0 * math.pi * i / n_sides + rng.uniform(-0.1, 0.1)
            ring.append(
                bm.verts.new((cx + dx + r * math.cos(a), cy + dy + r * math.sin(a), z))
            )
        rings.append((ring, z))
    bm.verts.ensure_lookup_table()
    for k in range(n_rings):
        ring0, z0 = rings[k]
        ring1, z1 = rings[k + 1]
        seg_slot = slot_band if (z0 + z1) * 0.5 < band_z else slot_main
        start = _face_count(bm)
        for i in range(n_sides):
            ni = (i + 1) % n_sides
            bm.faces.new((ring0[i], ring0[ni], ring1[ni], ring1[i]))
        slot_ranges.append((start, _face_count(bm), int(seg_slot)))
    start = _face_count(bm)
    bm.faces.new(tuple(reversed(rings[0][0])))
    slot_ranges.append((start, _face_count(bm), int(slot_band)))
    start = _face_count(bm)
    bm.faces.new(tuple(rings[-1][0]))
    slot_ranges.append((start, _face_count(bm), int(slot_main)))


def _add_rock_chunk(
    bm: bmesh.types.BMesh,
    *,
    cx: float,
    cy: float,
    z0: float,
    radius: float,
    height: float,
    n_sides: int,
    slot: int,
    slot_ranges: list[tuple[int, int, int]],
    rng: random.Random,
    rot_z: float = 0.0,
) -> None:
    """An irregular angular rock — a perched boulder or rubble."""
    start = _face_count(bm)
    rot = Matrix.Rotation(float(rot_z), 4, "Z")
    bot = []
    top = []
    for i in range(n_sides):
        a = 2.0 * math.pi * i / n_sides
        rb = radius * (1.0 + rng.uniform(-0.30, 0.30))
        rt = rb * rng.uniform(0.6, 0.96)
        lb = rot @ Vector((rb * math.cos(a), rb * math.sin(a), 0.0))
        lt = rot @ Vector((rt * math.cos(a), rt * math.sin(a), 0.0))
        bot.append(bm.verts.new((cx + lb.x, cy + lb.y, z0)))
        top.append(bm.verts.new((cx + lt.x, cy + lt.y, z0 + height * rng.uniform(0.7, 1.18))))
    bm.verts.ensure_lookup_table()
    for i in range(n_sides):
        ni = (i + 1) % n_sides
        bm.faces.new((bot[i], bot[ni], top[ni], top[i]))
    bm.faces.new(tuple(reversed(bot)))
    bm.faces.new(tuple(top))
    slot_ranges.append((start, _face_count(bm), int(slot)))


class LowPolyNaturalArchFactory(AssetFactory):
    """Natural rock landmarks — arches, sea stacks, balanced rocks.

    Constructor knobs:
        factory_seed
        formation_archetype : "desert_arch" | "sea_arch" | "sea_stack"
                              | "balanced_rock"
        rock_color, band_color
    """

    def __init__(
        self,
        factory_seed,
        formation_archetype: str = "desert_arch",
        rock_color: str | None = None,
        band_color: str | None = None,
        coarse: bool = False,
        **_unused_kwargs,
    ) -> None:
        super().__init__(factory_seed, coarse=coarse)
        if _unused_kwargs:
            from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
            accept_unused_kwargs("LowPolyNaturalArchFactory", _unused_kwargs)
        if formation_archetype not in _ARCH_ARCHETYPES:
            import sys
            print(
                f"[formation_archetype] WARN: unknown {formation_archetype!r}; "
                f"falling back to {_ARCH_ARCHETYPES[0]!r}. Valid: {_ARCH_ARCHETYPES}",
                file=sys.stderr,
            )
            formation_archetype = _ARCH_ARCHETYPES[0]
        self.formation_archetype = formation_archetype
        _rock, _band = _ARCHETYPE_COLORS[formation_archetype]
        self.rock_color = rock_color or _rock
        self.band_color = band_color or _band

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyNaturalArch({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        rng = random.Random(int(self.factory_seed) + 47729)
        if self.formation_archetype == "sea_stack":
            return self._build_sea_stack(rng)
        if self.formation_archetype == "balanced_rock":
            return self._build_balanced_rock(rng)
        return self._build_arch(rng)

    def _finalize(
        self, bm: bmesh.types.BMesh, slot_ranges: list[tuple[int, int, int]]
    ) -> bpy.types.Object:
        me = bpy.data.meshes.new(f"LowPolyNaturalArch({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()
        obj = bpy.data.objects.new(
            f"LowPolyNaturalArch({self.factory_seed})_{self.formation_archetype}", me
        )
        bpy.context.scene.collection.objects.link(obj)
        while len(obj.data.materials) < 2:
            obj.data.materials.append(None)
        for start, end, slot in slot_ranges:
            for face_idx in range(start, end):
                obj.data.polygons[face_idx].material_index = slot
        for poly in obj.data.polygons:
            poly.use_smooth = False
        apply_palette_slots(obj, [self.rock_color, self.band_color])
        return obj

    def _base_rubble(
        self,
        bm: bmesh.types.BMesh,
        slot_ranges: list[tuple[int, int, int]],
        rng: random.Random,
        *,
        cx: float,
        cy: float,
        spread: float,
        count: int,
    ) -> None:
        for _ in range(count):
            a = rng.uniform(0.0, 2.0 * math.pi)
            rr = spread * math.sqrt(rng.uniform(0.0, 1.0))
            _add_rock_chunk(
                bm, cx=cx + rr * math.cos(a), cy=cy + rr * math.sin(a), z0=-0.04,
                radius=rng.uniform(0.18, 0.38), height=rng.uniform(0.18, 0.42),
                n_sides=rng.choice((5, 6)), slot=1, slot_ranges=slot_ranges, rng=rng,
                rot_z=rng.uniform(0.0, math.pi),
            )

    # -- archetype builders ------------------------------------------------

    def _build_arch(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        if self.formation_archetype == "sea_arch":
            span_half = rng.uniform(1.5, 1.9)
            leg_height = rng.uniform(0.85, 1.15)
            arch_rise = rng.uniform(1.0, 1.3)
            cross_radius = rng.uniform(0.55, 0.72)
            band_z = 0.5
        else:  # desert_arch
            span_half = rng.uniform(1.2, 1.5)
            leg_height = rng.uniform(1.5, 1.9)
            arch_rise = rng.uniform(0.9, 1.2)
            cross_radius = rng.uniform(0.36, 0.48)
            band_z = 0.55
        _add_arch_band(
            bm, span_half=span_half, leg_height=leg_height, arch_rise=arch_rise,
            cross_radius=cross_radius, depth_scale=0.9, n_path=18, n_sides=6,
            band_z=band_z, slot_main=0, slot_band=1, slot_ranges=sr, rng=rng,
        )
        for leg_x in (-span_half, span_half):
            self._base_rubble(bm, sr, rng, cx=leg_x, cy=0.0, spread=0.55,
                              count=rng.randint(2, 4))
        return self._finalize(bm, sr)

    def _build_sea_stack(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        # tall, slim, near-columnar — a dramatic pillar, not a chunky rock
        _add_rock_column(
            bm, cx=0.0, cy=0.0, base_radius=rng.uniform(0.42, 0.60),
            height=rng.uniform(3.2, 4.6), taper=0.30, n_rings=rng.randint(6, 8),
            n_sides=7, band_z=0.5, slot_main=0, slot_band=1, slot_ranges=sr, rng=rng,
        )
        if rng.random() < 0.7:
            a = rng.uniform(0.0, 2.0 * math.pi)
            d = rng.uniform(0.9, 1.4)
            _add_rock_column(
                bm, cx=d * math.cos(a), cy=d * math.sin(a),
                base_radius=rng.uniform(0.26, 0.42), height=rng.uniform(1.3, 2.4),
                taper=0.35, n_rings=rng.randint(4, 6), n_sides=6, band_z=0.5,
                slot_main=0, slot_band=1, slot_ranges=sr, rng=rng,
            )
        self._base_rubble(bm, sr, rng, cx=0.0, cy=0.0, spread=0.95,
                          count=rng.randint(3, 6))
        return self._finalize(bm, sr)

    def _build_balanced_rock(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        # a tall, strongly tapered pedestal so the boulder reads as balanced
        # on a slim point rather than sitting on a pile of rubble
        ped_h = rng.uniform(0.95, 1.40)
        _add_rock_column(
            bm, cx=0.0, cy=0.0, base_radius=rng.uniform(0.34, 0.46), height=ped_h,
            taper=0.58, n_rings=4, n_sides=6, band_z=0.3, slot_main=0, slot_band=1,
            slot_ranges=sr, rng=rng,
        )
        # the big perched boulder — its wide base overhangs the slim pedestal
        _add_rock_chunk(
            bm, cx=rng.uniform(-0.10, 0.10), cy=rng.uniform(-0.10, 0.10),
            z0=ped_h - 0.06, radius=rng.uniform(0.80, 1.05),
            height=rng.uniform(0.75, 1.0), n_sides=rng.choice((6, 7)),
            slot=0, slot_ranges=sr, rng=rng, rot_z=rng.uniform(0.0, math.pi),
        )
        self._base_rubble(bm, sr, rng, cx=0.0, cy=0.0, spread=0.6,
                          count=rng.randint(2, 3))
        return self._finalize(bm, sr)

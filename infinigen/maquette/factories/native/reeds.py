"""LowPolyReedsFactory — wetland reeds, cattails, bulrush, papyrus.

Fills the `riverbank_reeds` enrichment slot, which had no factory behind
it. Reed clumps line ponds, streams, oasis pools, and marsh edges. Each
archetype is a clump of thin stalks; the read comes from the silhouette
of the seed heads.

Archetypes:
  cattail_clump  — round stalks, brown sausage seed heads, strappy base
                   leaves arcing out of the water
  tall_reeds     — a fan of flat grass-like blades plus a few taller
                   stalks carrying drooping feathery plumes
  bulrush        — stiff round stalks with small brown seed tufts
  papyrus        — tall stalks each crowned with a radiating umbel burst

Material slots:
  slot 0 = stalk / blade (green)
  slot 1 = seed head — cattail sausage, plume, tuft, or papyrus umbel
"""

from __future__ import annotations

import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_REED_ARCHETYPES = ("cattail_clump", "tall_reeds", "bulrush", "papyrus")

# Seed-head palette key per archetype (overridable via head_color kwarg).
_HEAD_COLORS = {
    "cattail_clump": "rock_shadow",   # dark-brown cattail sausage
    "tall_reeds": "stucco",           # pale silvery plume
    "bulrush": "wood",                # mid-brown seed tuft
    "papyrus": "foliage_lemon",       # sunlit straw-green umbel
}


def _face_count(bm: bmesh.types.BMesh) -> int:
    return len(bm.faces)


def _disc_points(
    rng: random.Random, count: int, radius: float
) -> list[tuple[float, float]]:
    """`count` random points in a disc of `radius`, area-uniform."""
    pts = []
    for _ in range(max(0, count)):
        a = rng.uniform(0.0, 2.0 * math.pi)
        r = radius * math.sqrt(rng.uniform(0.0, 1.0))
        pts.append((r * math.cos(a), r * math.sin(a)))
    return pts


def _outward(px: float, py: float, rng: random.Random) -> tuple[float, float]:
    """Unit direction pointing away from the clump centre — reeds fan out.
    Near the centre the direction is undefined, so pick one at random."""
    d = math.hypot(px, py)
    if d < 0.06:
        a = rng.uniform(0.0, 2.0 * math.pi)
        return (math.cos(a), math.sin(a))
    return (px / d, py / d)


def _add_prism(
    bm: bmesh.types.BMesh,
    *,
    center: tuple[float, float, float],
    radius: float,
    height: float,
    n_sides: int,
    slot: int,
    slot_ranges: list[tuple[int, int, int]],
    rot_z: float = 0.0,
) -> None:
    start = _face_count(bm)
    cx, cy, cz = center
    rot = Matrix.Rotation(float(rot_z), 4, "Z")
    bottom = []
    top = []
    for i in range(n_sides):
        a = 2.0 * math.pi * i / n_sides
        local = Vector((radius * math.cos(a), radius * math.sin(a), 0.0))
        p = Vector((cx, cy, cz)) + (rot @ local)
        bottom.append(bm.verts.new((p.x, p.y, p.z)))
        top.append(bm.verts.new((p.x, p.y, p.z + height)))
    bm.verts.ensure_lookup_table()
    for i in range(n_sides):
        ni = (i + 1) % n_sides
        bm.faces.new((bottom[i], bottom[ni], top[ni], top[i]))
    bm.faces.new(tuple(reversed(bottom)))
    bm.faces.new(tuple(top))
    slot_ranges.append((start, _face_count(bm), int(slot)))


def _add_stem(
    bm: bmesh.types.BMesh,
    *,
    base_x: float,
    base_y: float,
    height: float,
    base_radius: float,
    curve_x: float,
    curve_y: float,
    n_seg: int,
    slot: int,
    slot_ranges: list[tuple[int, int, int]],
) -> list[tuple[float, float, float, float]]:
    """A thin tapered round stalk along a gently arcing path. Returns the
    (x, y, z, r) path points so the caller can crown it with a seed head."""
    n_sides = 5
    pts: list[tuple[float, float, float, float]] = []
    for k in range(n_seg + 1):
        f = k / n_seg
        drift = f ** 1.5
        pts.append(
            (
                base_x + curve_x * drift,
                base_y + curve_y * drift,
                height * f,
                base_radius * (1.0 - 0.55 * f),
            )
        )
    rings: list[list[bmesh.types.BMVert]] = []
    for (x, y, z, r) in pts:
        ring = []
        for i in range(n_sides):
            a = 2.0 * math.pi * i / n_sides
            ring.append(bm.verts.new((x + r * math.cos(a), y + r * math.sin(a), z)))
        rings.append(ring)
    bm.verts.ensure_lookup_table()
    start = _face_count(bm)
    for k in range(n_seg):
        lo, hi = rings[k], rings[k + 1]
        for i in range(n_sides):
            ni = (i + 1) % n_sides
            bm.faces.new((lo[i], lo[ni], hi[ni], hi[i]))
    bm.faces.new(tuple(reversed(rings[0])))
    bm.faces.new(tuple(rings[-1]))
    slot_ranges.append((start, _face_count(bm), int(slot)))
    return pts


def _add_blade(
    bm: bmesh.types.BMesh,
    *,
    base_x: float,
    base_y: float,
    height: float,
    base_width: float,
    curve_x: float,
    curve_y: float,
    n_seg: int,
    slot: int,
    slot_ranges: list[tuple[int, int, int]],
) -> None:
    """A flat grass-like blade: a ribbon arcing along its curve path,
    tapering from base_width to a point at the tip."""
    clen = math.hypot(curve_x, curve_y)
    if clen < 1e-6:
        perp_x, perp_y = 1.0, 0.0
    else:
        perp_x, perp_y = -curve_y / clen, curve_x / clen
    pairs: list[tuple[bmesh.types.BMVert, bmesh.types.BMVert]] = []
    for k in range(n_seg):
        f = k / n_seg
        drift = f ** 1.5
        x = base_x + curve_x * drift
        y = base_y + curve_y * drift
        z = height * f
        w = base_width * (1.0 - f) ** 0.85
        pairs.append(
            (
                bm.verts.new((x + perp_x * w, y + perp_y * w, z)),
                bm.verts.new((x - perp_x * w, y - perp_y * w, z)),
            )
        )
    tip = bm.verts.new((base_x + curve_x, base_y + curve_y, height))
    bm.verts.ensure_lookup_table()
    start = _face_count(bm)
    for k in range(n_seg - 1):
        l0, r0 = pairs[k]
        l1, r1 = pairs[k + 1]
        bm.faces.new((l0, r0, r1, l1))
    l_last, r_last = pairs[-1]
    bm.faces.new((l_last, r_last, tip))
    slot_ranges.append((start, _face_count(bm), int(slot)))


def _add_strand_cluster(
    bm: bmesh.types.BMesh,
    *,
    x: float,
    y: float,
    z: float,
    count: int,
    length: float,
    elevation: float,
    droop: float,
    slot: int,
    slot_ranges: list[tuple[int, int, int]],
    rng: random.Random,
) -> None:
    """A burst of thin strands from a point — a papyrus umbel (steep
    elevation, little droop), a reed plume (low elevation, heavy droop),
    or a bulrush tuft (small + short)."""
    start = _face_count(bm)
    for _ in range(max(0, count)):
        az = rng.uniform(0.0, 2.0 * math.pi)
        elev = elevation + rng.uniform(-0.32, 0.32)
        length_j = length * rng.uniform(0.7, 1.3)
        dx = math.cos(az) * math.cos(elev)
        dy = math.sin(az) * math.cos(elev)
        dz = math.sin(elev)
        tx = x + dx * length_j
        ty = y + dy * length_j
        tz = z + dz * length_j - droop * length_j
        half_w = 0.013
        perp_x, perp_y = -math.sin(az), math.cos(az)
        b1 = bm.verts.new((x + perp_x * half_w, y + perp_y * half_w, z))
        b2 = bm.verts.new((x - perp_x * half_w, y - perp_y * half_w, z))
        t1 = bm.verts.new((tx + perp_x * half_w * 0.2, ty + perp_y * half_w * 0.2, tz))
        t2 = bm.verts.new((tx - perp_x * half_w * 0.2, ty - perp_y * half_w * 0.2, tz))
        bm.verts.ensure_lookup_table()
        bm.faces.new((b1, b2, t2, t1))
    slot_ranges.append((start, _face_count(bm), int(slot)))


class LowPolyReedsFactory(AssetFactory):
    """Procedural wetland reed clumps — cattails, reeds, bulrush, papyrus.

    Constructor knobs:
        factory_seed
        reed_archetype : "cattail_clump" | "tall_reeds" | "bulrush" | "papyrus"
        stem_color, head_color
    """

    def __init__(
        self,
        factory_seed,
        reed_archetype: str = "cattail_clump",
        stem_color: str | None = None,
        head_color: str | None = None,
        coarse: bool = False,
        **_unused_kwargs,
    ) -> None:
        super().__init__(factory_seed, coarse=coarse)
        if _unused_kwargs:
            from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
            accept_unused_kwargs("LowPolyReedsFactory", _unused_kwargs)
        if reed_archetype not in _REED_ARCHETYPES:
            import sys
            print(
                f"[reed_archetype] WARN: unknown {reed_archetype!r}; "
                f"falling back to {_REED_ARCHETYPES[0]!r}. Valid: {_REED_ARCHETYPES}",
                file=sys.stderr,
            )
            reed_archetype = _REED_ARCHETYPES[0]
        self.reed_archetype = reed_archetype
        self.stem_color = stem_color or "foliage_bush"
        self.head_color = head_color or _HEAD_COLORS[reed_archetype]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(f"LowPolyReeds({self.factory_seed})_placeholder", None)
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        rng = random.Random(int(self.factory_seed) + 60223)
        builders = {
            "cattail_clump": self._build_cattail_clump,
            "tall_reeds": self._build_tall_reeds,
            "bulrush": self._build_bulrush,
            "papyrus": self._build_papyrus,
        }
        return builders[self.reed_archetype](rng)

    def _finalize(
        self, bm: bmesh.types.BMesh, slot_ranges: list[tuple[int, int, int]]
    ) -> bpy.types.Object:
        me = bpy.data.meshes.new(f"LowPolyReeds({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()
        obj = bpy.data.objects.new(
            f"LowPolyReeds({self.factory_seed})_{self.reed_archetype}", me
        )
        bpy.context.scene.collection.objects.link(obj)
        while len(obj.data.materials) < 2:
            obj.data.materials.append(None)
        for start, end, slot in slot_ranges:
            for face_idx in range(start, end):
                obj.data.polygons[face_idx].material_index = slot
        for poly in obj.data.polygons:
            poly.use_smooth = False
        apply_palette_slots(obj, [self.stem_color, self.head_color])
        return obj

    # -- archetype builders ------------------------------------------------

    def _build_cattail_clump(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        radius = rng.uniform(0.5, 0.72)
        for (px, py) in _disc_points(rng, rng.randint(7, 12), radius):
            h = rng.uniform(1.8, 2.8)
            odir = _outward(px, py, rng)
            cmag = h * rng.uniform(0.04, 0.11)
            pts = _add_stem(
                bm,
                base_x=px,
                base_y=py,
                height=h,
                base_radius=rng.uniform(0.022, 0.032),
                curve_x=odir[0] * cmag,
                curve_y=odir[1] * cmag,
                n_seg=5,
                slot=0,
                slot_ranges=sr,
            )
            if rng.random() < 0.62:
                head_len = rng.uniform(0.30, 0.46)
                spike = rng.uniform(0.10, 0.18)
                head_bottom = pts[-1][2] - spike - head_len
                _add_prism(
                    bm,
                    center=(pts[-2][0], pts[-2][1], head_bottom),
                    radius=rng.uniform(0.052, 0.066),
                    height=head_len,
                    n_sides=8,
                    slot=1,
                    slot_ranges=sr,
                )
        for (bx, by) in _disc_points(rng, rng.randint(8, 14), radius * 1.05):
            odir = _outward(bx, by, rng)
            bh = rng.uniform(0.9, 1.7)
            cmag = bh * rng.uniform(0.22, 0.40)
            _add_blade(
                bm,
                base_x=bx,
                base_y=by,
                height=bh,
                base_width=rng.uniform(0.040, 0.062),
                curve_x=odir[0] * cmag,
                curve_y=odir[1] * cmag,
                n_seg=5,
                slot=0,
                slot_ranges=sr,
            )
        return self._finalize(bm, sr)

    def _build_tall_reeds(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        radius = rng.uniform(0.6, 0.85)
        for (bx, by) in _disc_points(rng, rng.randint(18, 30), radius):
            odir = _outward(bx, by, rng)
            bh = rng.uniform(1.5, 2.6)
            cmag = bh * rng.uniform(0.16, 0.32)
            _add_blade(
                bm,
                base_x=bx,
                base_y=by,
                height=bh,
                base_width=rng.uniform(0.030, 0.050),
                curve_x=odir[0] * cmag,
                curve_y=odir[1] * cmag,
                n_seg=5,
                slot=0,
                slot_ranges=sr,
            )
        for (px, py) in _disc_points(rng, rng.randint(3, 7), radius * 0.75):
            h = rng.uniform(2.0, 2.9)
            odir = _outward(px, py, rng)
            cmag = h * rng.uniform(0.05, 0.13)
            pts = _add_stem(
                bm,
                base_x=px,
                base_y=py,
                height=h,
                base_radius=rng.uniform(0.018, 0.028),
                curve_x=odir[0] * cmag,
                curve_y=odir[1] * cmag,
                n_seg=5,
                slot=0,
                slot_ranges=sr,
            )
            _add_strand_cluster(
                bm,
                x=pts[-1][0],
                y=pts[-1][1],
                z=pts[-1][2] - 0.04,
                count=rng.randint(10, 15),
                length=0.34,
                elevation=0.15,
                droop=0.55,
                slot=1,
                slot_ranges=sr,
                rng=rng,
            )
        return self._finalize(bm, sr)

    def _build_bulrush(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        radius = rng.uniform(0.45, 0.65)
        for (px, py) in _disc_points(rng, rng.randint(10, 16), radius):
            h = rng.uniform(1.7, 2.5)
            odir = _outward(px, py, rng)
            cmag = h * rng.uniform(0.02, 0.07)
            pts = _add_stem(
                bm,
                base_x=px,
                base_y=py,
                height=h,
                base_radius=rng.uniform(0.022, 0.030),
                curve_x=odir[0] * cmag,
                curve_y=odir[1] * cmag,
                n_seg=4,
                slot=0,
                slot_ranges=sr,
            )
            if rng.random() < 0.78:
                _add_strand_cluster(
                    bm,
                    x=pts[-1][0],
                    y=pts[-1][1],
                    z=pts[-1][2] - 0.05,
                    count=rng.randint(5, 8),
                    length=0.13,
                    elevation=0.5,
                    droop=0.3,
                    slot=1,
                    slot_ranges=sr,
                    rng=rng,
                )
        for (bx, by) in _disc_points(rng, rng.randint(3, 6), radius * 0.9):
            odir = _outward(bx, by, rng)
            bh = rng.uniform(0.5, 0.95)
            cmag = bh * rng.uniform(0.20, 0.36)
            _add_blade(
                bm,
                base_x=bx,
                base_y=by,
                height=bh,
                base_width=rng.uniform(0.025, 0.040),
                curve_x=odir[0] * cmag,
                curve_y=odir[1] * cmag,
                n_seg=4,
                slot=0,
                slot_ranges=sr,
            )
        return self._finalize(bm, sr)

    def _build_papyrus(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        radius = rng.uniform(0.6, 0.85)
        for (px, py) in _disc_points(rng, rng.randint(6, 11), radius):
            h = rng.uniform(2.4, 3.5)
            odir = _outward(px, py, rng)
            cmag = h * rng.uniform(0.03, 0.09)
            pts = _add_stem(
                bm,
                base_x=px,
                base_y=py,
                height=h,
                base_radius=rng.uniform(0.028, 0.040),
                curve_x=odir[0] * cmag,
                curve_y=odir[1] * cmag,
                n_seg=5,
                slot=0,
                slot_ranges=sr,
            )
            _add_strand_cluster(
                bm,
                x=pts[-1][0],
                y=pts[-1][1],
                z=pts[-1][2],
                count=rng.randint(16, 24),
                length=0.40,
                elevation=0.95,
                droop=0.14,
                slot=1,
                slot_ranges=sr,
                rng=rng,
            )
        return self._finalize(bm, sr)

"""LowPolyBambooFactory — segmented bamboo culms in clumps, groves, screens.

Iconic vegetation for zen gardens, tea houses, and jungle understorey —
none of which had bamboo before. A culm is the bamboo read: a thin
tapered stalk broken into internode sections by slightly-bulged node
collars, with sparse drooping leaf blades near the top.

Archetypes:
  grove_clump    — a dense patch of many vertical culms of varied height
  single_stalk   — one to three tall isolated culms; a path accent
  bent_arch      — taller culms arcing over in a shared direction
  bamboo_screen  — a planted row of culms lashed by two horizontal rails;
                   a garden fence / sode-gaki screen

Material slots:
  slot 0 = culm (stalks, node collars, screen rails)
  slot 1 = foliage (leaf blades)
"""

from __future__ import annotations

import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_BAMBOO_ARCHETYPES = ("grove_clump", "single_stalk", "bent_arch", "bamboo_screen")


_ARCHETYPE_DEFAULTS = {
    "grove_clump": dict(
        is_row=False,
        has_rails=False,
        culm_count=(9, 15),
        patch_radius=1.05,
        row_length=0.0,
        height_range=(2.6, 4.2),
        base_radius_range=(0.045, 0.07),
        node_count=(5, 7),
        curve_amount=0.0,
        foliage_per_culm=2,
        foliage_blades=(5, 8),
        foliage_length=0.42,
        culm_color="foliage_bush",
        foliage_color="foliage_apple",
    ),
    "single_stalk": dict(
        is_row=False,
        has_rails=False,
        culm_count=(1, 3),
        patch_radius=0.22,
        row_length=0.0,
        height_range=(3.6, 5.0),
        base_radius_range=(0.05, 0.075),
        node_count=(6, 8),
        curve_amount=0.0,
        foliage_per_culm=3,
        foliage_blades=(5, 8),
        foliage_length=0.46,
        culm_color="foliage_bush",
        foliage_color="foliage_apple",
    ),
    "bent_arch": dict(
        is_row=False,
        has_rails=False,
        culm_count=(4, 8),
        patch_radius=0.72,
        row_length=0.0,
        height_range=(3.4, 4.6),
        base_radius_range=(0.045, 0.065),
        node_count=(6, 8),
        curve_amount=0.20,
        foliage_per_culm=3,
        foliage_blades=(5, 8),
        foliage_length=0.44,
        culm_color="foliage_bush",
        foliage_color="foliage_mint",
    ),
    "bamboo_screen": dict(
        is_row=True,
        has_rails=True,
        culm_count=(6, 9),
        patch_radius=0.0,
        row_length=2.4,
        height_range=(2.0, 2.7),
        base_radius_range=(0.05, 0.07),
        node_count=(4, 6),
        curve_amount=0.0,
        foliage_per_culm=0,
        foliage_blades=(0, 0),
        foliage_length=0.0,
        culm_color="ground_sand",
        foliage_color="foliage_apple",
    ),
}


def _face_count(bm: bmesh.types.BMesh) -> int:
    return len(bm.faces)


def _add_box(
    bm: bmesh.types.BMesh,
    *,
    cx: float,
    cy: float,
    z0: float,
    sx: float,
    sy: float,
    sz: float,
    slot: int,
    slot_ranges: list[tuple[int, int, int]],
) -> None:
    """A plain axis-aligned box — used for the screen's lashing rails."""
    start = _face_count(bm)
    hx, hy = sx * 0.5, sy * 0.5
    corners = ((-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy))
    bottom = [bm.verts.new((cx + lx, cy + ly, z0)) for lx, ly in corners]
    top = [bm.verts.new((cx + lx, cy + ly, z0 + sz)) for lx, ly in corners]
    bm.verts.ensure_lookup_table()
    for i in range(4):
        ni = (i + 1) % 4
        bm.faces.new((bottom[i], bottom[ni], top[ni], top[i]))
    bm.faces.new(tuple(reversed(bottom)))
    bm.faces.new(tuple(top))
    slot_ranges.append((start, _face_count(bm), int(slot)))


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


def _add_culm(
    bm: bmesh.types.BMesh,
    *,
    base_x: float,
    base_y: float,
    height: float,
    base_radius: float,
    n_nodes: int,
    curve_x: float,
    curve_y: float,
    slot: int,
    slot_ranges: list[tuple[int, int, int]],
    rng: random.Random,
) -> list[tuple[float, float, float, float]]:
    """One bamboo culm: a tapered 6-sided stalk built as `n_nodes` internode
    sections along a (possibly curved) path, with a bulged node collar at
    each interior joint. Returns the (x, y, z, r) path points so the caller
    can hang leaf clusters off the upper ones."""
    n_sides = 6
    pts: list[tuple[float, float, float, float]] = []
    for k in range(n_nodes + 1):
        f = k / n_nodes
        # drift grows faster up high → a gentle arc, not a uniform lean
        drift = f ** 1.7
        x = base_x + curve_x * drift
        y = base_y + curve_y * drift
        z = height * f
        r = base_radius * (1.0 - 0.46 * f)
        pts.append((x, y, z, r))
    rings: list[list[bmesh.types.BMVert]] = []
    for (x, y, z, r) in pts:
        ring = []
        for i in range(n_sides):
            a = 2.0 * math.pi * i / n_sides
            ring.append(bm.verts.new((x + r * math.cos(a), y + r * math.sin(a), z)))
        rings.append(ring)
    bm.verts.ensure_lookup_table()
    start = _face_count(bm)
    for k in range(n_nodes):
        lo, hi = rings[k], rings[k + 1]
        for i in range(n_sides):
            ni = (i + 1) % n_sides
            bm.faces.new((lo[i], lo[ni], hi[ni], hi[i]))
    bm.faces.new(tuple(reversed(rings[0])))
    bm.faces.new(tuple(rings[-1]))
    slot_ranges.append((start, _face_count(bm), int(slot)))
    for k in range(1, n_nodes):
        x, y, z, r = pts[k]
        _add_prism(
            bm,
            center=(x, y, z - 0.03),
            radius=r * 1.3,
            height=0.06,
            n_sides=n_sides,
            slot=slot,
            slot_ranges=slot_ranges,
            rot_z=rng.uniform(0.0, 0.5),
        )
    return pts


def _add_leaf_cluster(
    bm: bmesh.types.BMesh,
    *,
    x: float,
    y: float,
    z: float,
    count: int,
    length: float,
    slot: int,
    slot_ranges: list[tuple[int, int, int]],
    rng: random.Random,
) -> None:
    """A spray of thin drooping bamboo leaf blades fanning out from a point."""
    start = _face_count(bm)
    for _ in range(max(0, count)):
        ang = rng.uniform(0.0, 2.0 * math.pi)
        dx, dy = math.cos(ang), math.sin(ang)
        length_j = length * rng.uniform(0.7, 1.25)
        droop = rng.uniform(0.25, 0.6)
        half_w = 0.035
        perp_x, perp_y = -dy, dx
        bz = z + rng.uniform(-0.05, 0.08)
        tx = x + dx * length_j
        ty = y + dy * length_j
        tz = bz - droop * length_j
        v_b1 = bm.verts.new((x + perp_x * half_w, y + perp_y * half_w, bz))
        v_b2 = bm.verts.new((x - perp_x * half_w, y - perp_y * half_w, bz))
        v_t1 = bm.verts.new((tx + perp_x * half_w * 0.25, ty + perp_y * half_w * 0.25, tz))
        v_t2 = bm.verts.new((tx - perp_x * half_w * 0.25, ty - perp_y * half_w * 0.25, tz))
        bm.verts.ensure_lookup_table()
        bm.faces.new((v_b1, v_b2, v_t2, v_t1))
    slot_ranges.append((start, _face_count(bm), int(slot)))


class LowPolyBambooFactory(AssetFactory):
    """Procedural bamboo — clumps, groves, screens.

    Constructor knobs:
        factory_seed
        bamboo_archetype : "grove_clump" | "single_stalk" | "bent_arch"
                           | "bamboo_screen"
        culm_color, foliage_color
    """

    def __init__(
        self,
        factory_seed,
        bamboo_archetype: str = "grove_clump",
        culm_color: str | None = None,
        foliage_color: str | None = None,
        coarse: bool = False,
        **_unused_kwargs,
    ) -> None:
        super().__init__(factory_seed, coarse=coarse)
        if _unused_kwargs:
            from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
            accept_unused_kwargs("LowPolyBambooFactory", _unused_kwargs)
        if bamboo_archetype not in _BAMBOO_ARCHETYPES:
            import sys
            print(
                f"[bamboo_archetype] WARN: unknown {bamboo_archetype!r}; "
                f"falling back to {_BAMBOO_ARCHETYPES[0]!r}. Valid: {_BAMBOO_ARCHETYPES}",
                file=sys.stderr,
            )
            bamboo_archetype = _BAMBOO_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[bamboo_archetype]
        self.bamboo_archetype = bamboo_archetype
        self.is_row = bool(d["is_row"])
        self.has_rails = bool(d["has_rails"])
        self.culm_count = d["culm_count"]
        self.patch_radius = float(d["patch_radius"])
        self.row_length = float(d["row_length"])
        self.height_range = d["height_range"]
        self.base_radius_range = d["base_radius_range"]
        self.node_count = d["node_count"]
        self.curve_amount = float(d["curve_amount"])
        self.foliage_per_culm = int(d["foliage_per_culm"])
        self.foliage_blades = d["foliage_blades"]
        self.foliage_length = float(d["foliage_length"])
        self.culm_color = culm_color or d["culm_color"]
        self.foliage_color = foliage_color or d["foliage_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(f"LowPolyBamboo({self.factory_seed})_placeholder", None)
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        rng = random.Random(int(self.factory_seed) + 40961)
        bm = bmesh.new()
        slot_ranges: list[tuple[int, int, int]] = []

        n_culms = rng.randint(*self.culm_count)
        positions: list[tuple[float, float]] = []
        if self.is_row:
            for i in range(n_culms):
                f = i / max(1, n_culms - 1)
                positions.append(
                    (
                        (f - 0.5) * self.row_length + rng.uniform(-0.06, 0.06),
                        rng.uniform(-0.035, 0.035),
                    )
                )
        else:
            for _ in range(n_culms):
                a = rng.uniform(0.0, 2.0 * math.pi)
                r = self.patch_radius * math.sqrt(rng.uniform(0.0, 1.0))
                positions.append((r * math.cos(a), r * math.sin(a)))

        arch_dir = rng.uniform(0.0, 2.0 * math.pi)
        culms: list[tuple[list[tuple[float, float, float, float]], float]] = []
        for (x, y) in positions:
            height = rng.uniform(*self.height_range)
            n_nodes = rng.randint(*self.node_count)
            base_radius = rng.uniform(*self.base_radius_range)
            if self.curve_amount > 0.0:
                cdir = arch_dir + rng.uniform(-0.7, 0.7)
                cmag = height * self.curve_amount * rng.uniform(0.75, 1.2)
            else:
                cdir = rng.uniform(0.0, 2.0 * math.pi)
                cmag = height * rng.uniform(0.0, 0.05)
            pts = _add_culm(
                bm,
                base_x=x,
                base_y=y,
                height=height,
                base_radius=base_radius,
                n_nodes=n_nodes,
                curve_x=math.cos(cdir) * cmag,
                curve_y=math.sin(cdir) * cmag,
                slot=0,
                slot_ranges=slot_ranges,
                rng=rng,
            )
            culms.append((pts, height))

        if self.has_rails and positions:
            xs = [p[0] for p in positions]
            x_lo, x_hi = min(xs), max(xs)
            min_h = min(h for (_, h) in culms)
            for frac in (0.36, 0.70):
                _add_box(
                    bm,
                    cx=0.5 * (x_lo + x_hi),
                    cy=0.0,
                    z0=min_h * frac,
                    sx=(x_hi - x_lo) + 0.32,
                    sy=0.07,
                    sz=0.06,
                    slot=0,
                    slot_ranges=slot_ranges,
                )

        for (pts, _height) in culms:
            for j in range(self.foliage_per_culm):
                attach = pts[-(j + 1)]
                _add_leaf_cluster(
                    bm,
                    x=attach[0],
                    y=attach[1],
                    z=attach[2],
                    count=rng.randint(*self.foliage_blades),
                    length=self.foliage_length,
                    slot=1,
                    slot_ranges=slot_ranges,
                    rng=rng,
                )

        me = bpy.data.meshes.new(f"LowPolyBamboo({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(f"LowPolyBamboo({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)
        while len(obj.data.materials) < 2:
            obj.data.materials.append(None)
        for start, end, slot in slot_ranges:
            for face_idx in range(start, end):
                obj.data.polygons[face_idx].material_index = slot
        for poly in obj.data.polygons:
            poly.use_smooth = False

        apply_palette_slots(obj, [self.culm_color, self.foliage_color])
        return obj

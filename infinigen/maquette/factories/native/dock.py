"""LowPolyDockFactory — fishing pier / wharf / ruined jetty.

Coastal and river settlements need a water-edge grammar stronger than
"deck rectangle." This factory authors posts, uneven planks, rail posts,
rope rails, fish crates, and optional broken/missing boards so a shoreline
immediately reads as a working dock.

Archetypes:
  straight_pier  — narrow pier jutting into water.
  l_wharf        — pier with a side landing / L-shaped working edge.
  fishing_wharf  — wider platform with rails, crates, and bollards.
  ruined_jetty   — broken posts and missing planks.

Material slots:
  slot 0 = planks / deck boards
  slot 1 = posts / rails / rope
  slot 2 = crates / cargo accents
"""

from __future__ import annotations

import random

import bmesh
import bpy

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_DOCK_ARCHETYPES = ("straight_pier", "l_wharf", "fishing_wharf", "ruined_jetty")

_ARCHETYPE_DEFAULTS = {
    "straight_pier": dict(length=7.5, width=1.65, side_length=0.0, rail=True, cargo=2, broken=0.0),
    "l_wharf": dict(length=7.0, width=1.85, side_length=4.0, rail=True, cargo=3, broken=0.0),
    "fishing_wharf": dict(length=6.2, width=3.1, side_length=2.8, rail=True, cargo=5, broken=0.0),
    "ruined_jetty": dict(length=6.8, width=1.55, side_length=0.0, rail=False, cargo=1, broken=0.38),
}


def _face_count(bm: bmesh.types.BMesh) -> int:
    return len(bm.faces)


def _add_box(
    bm: bmesh.types.BMesh,
    ranges: list[tuple[int, int, int]],
    slot: int,
    center: tuple[float, float, float],
    size: tuple[float, float, float],
) -> None:
    start = _face_count(bm)
    res = bmesh.ops.create_cube(bm, size=1.0)
    cx, cy, cz = center
    sx, sy, sz = size
    for v in res["verts"]:
        v.co.x = v.co.x * sx + cx
        v.co.y = v.co.y * sy + cy
        v.co.z = v.co.z * sz + cz
    bm.faces.ensure_lookup_table()
    ranges.append((start, _face_count(bm), int(slot)))


class LowPolyDockFactory(AssetFactory):
    """Low-poly shoreline dock with posts, planks, rails, and cargo.

    Constructor knobs:
        factory_seed
        dock_archetype : "straight_pier" | "l_wharf" | "fishing_wharf" | "ruined_jetty"
        length, width, side_length
        rail
        cargo
        broken
        plank_color, post_color, cargo_color
    """

    def __init__(
        self,
        factory_seed,
        dock_archetype: str = "straight_pier",
        length: float | None = None,
        width: float | None = None,
        side_length: float | None = None,
        rail: bool | None = None,
        cargo: int | None = None,
        broken: float | None = None,
        plank_color: str = "wood",
        post_color: str = "rust_metal",
        cargo_color: str = "rock_warm",
        coarse: bool = False,
        **_unused_kwargs,
    ) -> None:
        super().__init__(factory_seed, coarse=coarse)
        if _unused_kwargs:
            from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
            accept_unused_kwargs("LowPolyDockFactory", _unused_kwargs)
        if dock_archetype not in _DOCK_ARCHETYPES:
            import sys
            print(
                f"[dock_archetype] WARN: unknown {dock_archetype!r}; "
                f"falling back to {_DOCK_ARCHETYPES[0]!r}. Valid: {_DOCK_ARCHETYPES}",
                file=sys.stderr,
            )
            dock_archetype = _DOCK_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[dock_archetype]
        self.dock_archetype = dock_archetype
        self.length = float(length if length is not None else d["length"])
        self.width = float(width if width is not None else d["width"])
        self.side_length = float(side_length if side_length is not None else d["side_length"])
        self.rail = bool(rail if rail is not None else d["rail"])
        self.cargo = int(cargo if cargo is not None else d["cargo"])
        self.broken = max(0.0, min(0.85, float(broken if broken is not None else d["broken"])))
        self.plank_color = plank_color
        self.post_color = post_color
        self.cargo_color = cargo_color

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(f"LowPolyDock({self.factory_seed})_placeholder", None)
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        rng = random.Random(self.factory_seed)
        bm = bmesh.new()
        ranges: list[tuple[int, int, int]] = []

        plank_t = 0.13
        plank_w = 0.32
        post_t = 0.18
        z = 0.62
        half_w = self.width * 0.5
        n = max(5, int(self.length / 0.55))
        for i in range(n):
            x = -self.length * 0.5 + (i + 0.5) * self.length / n
            if rng.random() < self.broken:
                continue
            y_jitter = rng.uniform(-0.025, 0.025)
            _add_box(
                bm,
                ranges,
                0,
                (x, y_jitter, z),
                (self.length / n * 0.78, self.width * rng.uniform(0.88, 1.0), plank_t),
            )
        # Cross beams under the boards.
        for x in (-self.length * 0.38, 0.0, self.length * 0.38):
            _add_box(bm, ranges, 1, (x, 0.0, z - 0.20), (0.18, self.width + 0.28, 0.18))

        # L-shaped side landing.
        if self.side_length > 0.25:
            side_x = self.length * 0.18
            side_y = half_w + self.side_length * 0.5 - 0.08
            side_n = max(3, int(self.side_length / 0.55))
            for j in range(side_n):
                y = half_w + (j + 0.5) * self.side_length / side_n
                if rng.random() < self.broken * 0.65:
                    continue
                _add_box(
                    bm,
                    ranges,
                    0,
                    (side_x, y, z + rng.uniform(-0.015, 0.015)),
                    (self.width * 0.74, self.side_length / side_n * 0.78, plank_t),
                )
            _add_box(bm, ranges, 1, (side_x, side_y, z - 0.20), (self.width + 0.18, 0.18, 0.18))

        # Posts along edges, extending below deck so water-line placement reads.
        post_xs = [-self.length * 0.46, -self.length * 0.18, self.length * 0.18, self.length * 0.46]
        for x in post_xs:
            for y in (-half_w - 0.13, half_w + 0.13):
                if self.dock_archetype == "ruined_jetty" and rng.random() < 0.22:
                    continue
                top_extra = rng.uniform(0.2, 0.55)
                _add_box(bm, ranges, 1, (x, y, z - 0.42 + top_extra * 0.5), (post_t, post_t, 1.35 + top_extra))
        if self.side_length > 0.25:
            for y in (half_w + self.side_length * 0.35, half_w + self.side_length * 0.88):
                for x in (self.length * 0.18 - self.width * 0.45, self.length * 0.18 + self.width * 0.45):
                    _add_box(bm, ranges, 1, (x, y, z - 0.25), (post_t, post_t, 1.2))

        # Rail/rope bands.
        if self.rail:
            rail_z = z + 0.62
            for y in (-half_w - 0.13, half_w + 0.13):
                _add_box(bm, ranges, 1, (0.0, y, rail_z), (self.length * 0.82, 0.07, 0.07))
            if self.side_length > 0.25:
                _add_box(
                    bm,
                    ranges,
                    1,
                    (self.length * 0.18 - self.width * 0.45, half_w + self.side_length * 0.56, rail_z),
                    (0.07, self.side_length * 0.74, 0.07),
                )

        # Cargo clusters on the wider/working side.
        for c in range(self.cargo):
            x = rng.uniform(-self.length * 0.35, self.length * 0.36)
            y = rng.choice([-1.0, 1.0]) * rng.uniform(0.0, half_w * 0.55)
            sx = rng.uniform(0.34, 0.55)
            sy = rng.uniform(0.30, 0.48)
            sz = rng.uniform(0.24, 0.46)
            _add_box(bm, ranges, 2, (x, y, z + plank_t * 0.5 + sz * 0.5), (sx, sy, sz))
        # Bollards read better than rails at distance.
        for x in (-self.length * 0.22, self.length * 0.32):
            _add_box(bm, ranges, 1, (x, -half_w * 0.62, z + 0.24), (0.20, 0.20, 0.48))

        me = bpy.data.meshes.new(f"LowPolyDock({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()
        obj = bpy.data.objects.new(f"LowPolyDock({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)
        while len(obj.data.materials) < 3:
            obj.data.materials.append(None)
        for start, end, slot in ranges:
            for i in range(start, min(end, len(obj.data.polygons))):
                obj.data.polygons[i].material_index = slot
        for p in obj.data.polygons:
            p.use_smooth = False
        apply_palette_slots(obj, [self.plank_color, self.post_color, self.cargo_color])
        return obj

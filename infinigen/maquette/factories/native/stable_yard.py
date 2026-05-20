"""LowPolyStableYardFactory — stable shed / paddock / cart-yard kit.

Farm belts and town outskirts need non-living support objects that imply
work and travel without spawning animals. This factory makes a coherent
stable-yard compound: roofed shed, stall bays, fence rails, hay storage,
trough, tack posts, and optional cart shelter.

Archetypes:
  open_stable   — roofed three-bay stable with front posts.
  paddock_yard  — low fenced yard with hay and trough.
  cart_shelter  — service shed sized for carts/wagons.
  ruined_stable — collapsed roof pieces and partial fence.

Material slots:
  slot 0 = roof
  slot 1 = timber / fence / posts
  slot 2 = hay / trough / clutter
  slot 3 = stone base / rubble
"""

from __future__ import annotations

import random

import bmesh
import bpy

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_STABLE_YARD_ARCHETYPES = ("open_stable", "paddock_yard", "cart_shelter", "ruined_stable")

_ARCHETYPE_DEFAULTS = {
    "open_stable": dict(width=6.4, depth=3.2, shed=True, fence=True, bays=3, ruined=0.0),
    "paddock_yard": dict(width=6.8, depth=4.8, shed=False, fence=True, bays=1, ruined=0.0),
    "cart_shelter": dict(width=5.7, depth=3.7, shed=True, fence=False, bays=2, ruined=0.0),
    "ruined_stable": dict(width=6.2, depth=3.9, shed=True, fence=True, bays=2, ruined=0.48),
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


def _add_shed_roof(
    bm: bmesh.types.BMesh,
    ranges: list[tuple[int, int, int]],
    *,
    width: float,
    depth: float,
    z_front: float,
    z_back: float,
) -> None:
    start = _face_count(bm)
    hx = width * 0.5
    hy = depth * 0.5
    verts = [
        bm.verts.new((-hx, -hy, z_front)),
        bm.verts.new((hx, -hy, z_front)),
        bm.verts.new((hx, hy, z_back)),
        bm.verts.new((-hx, hy, z_back)),
    ]
    bm.verts.ensure_lookup_table()
    bm.faces.new(tuple(verts))
    ranges.append((start, _face_count(bm), 0))
    _add_box(bm, ranges, 0, (0.0, -hy, z_front - 0.08), (width, 0.10, 0.16))
    _add_box(bm, ranges, 0, (0.0, hy, z_back - 0.08), (width, 0.10, 0.16))


class LowPolyStableYardFactory(AssetFactory):
    """Stable/paddock service compound without living animals.

    Constructor knobs:
        factory_seed
        stable_yard_archetype : "open_stable" | "paddock_yard" | "cart_shelter" | "ruined_stable"
        width, depth
        shed, fence, bays, ruined
        roof_color, wood_color, hay_color, stone_color
    """

    def __init__(
        self,
        factory_seed,
        stable_yard_archetype: str = "open_stable",
        width: float | None = None,
        depth: float | None = None,
        shed: bool | None = None,
        fence: bool | None = None,
        bays: int | None = None,
        ruined: float | None = None,
        roof_color: str = "rock_warm",
        wood_color: str = "wood",
        hay_color: str = "ground_sand",
        stone_color: str = "rock_pale",
        coarse: bool = False,
        **_unused_kwargs,
    ) -> None:
        super().__init__(factory_seed, coarse=coarse)
        if _unused_kwargs:
            from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
            accept_unused_kwargs("LowPolyStableYardFactory", _unused_kwargs)
        if stable_yard_archetype not in _STABLE_YARD_ARCHETYPES:
            import sys
            print(
                f"[stable_yard_archetype] WARN: unknown {stable_yard_archetype!r}; "
                f"falling back to {_STABLE_YARD_ARCHETYPES[0]!r}. Valid: {_STABLE_YARD_ARCHETYPES}",
                file=sys.stderr,
            )
            stable_yard_archetype = _STABLE_YARD_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[stable_yard_archetype]
        self.stable_yard_archetype = stable_yard_archetype
        self.width = float(width if width is not None else d["width"])
        self.depth = float(depth if depth is not None else d["depth"])
        self.shed = bool(shed if shed is not None else d["shed"])
        self.fence = bool(fence if fence is not None else d["fence"])
        self.bays = int(bays if bays is not None else d["bays"])
        self.ruined = max(0.0, min(0.85, float(ruined if ruined is not None else d["ruined"])))
        self.roof_color = roof_color
        self.wood_color = wood_color
        self.hay_color = hay_color
        self.stone_color = stone_color

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(f"LowPolyStableYard({self.factory_seed})_placeholder", None)
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        rng = random.Random(self.factory_seed)
        bm = bmesh.new()
        ranges: list[tuple[int, int, int]] = []
        w = self.width * rng.uniform(0.94, 1.08)
        d = self.depth * rng.uniform(0.92, 1.10)
        shed_h = rng.uniform(2.05, 2.48)
        if self.shed:
            # Back wall + posts.
            _add_box(bm, ranges, 1, (0.0, d * 0.36, shed_h * 0.46), (w, 0.18, shed_h * 0.92))
            bay_count = max(1, self.bays)
            for i in range(bay_count + 1):
                x = -w * 0.5 + w * i / bay_count
                if rng.random() < self.ruined * 0.25:
                    continue
                _add_box(bm, ranges, 1, (x, -d * 0.32, shed_h * 0.5), (0.14, 0.14, shed_h))
                _add_box(bm, ranges, 1, (x, d * 0.32, shed_h * 0.5), (0.14, 0.14, shed_h))
            if self.ruined < 0.6:
                _add_shed_roof(bm, ranges, width=w * 1.08, depth=d * 0.88, z_front=shed_h + 0.12, z_back=shed_h + 0.62)
            else:
                _add_box(bm, ranges, 0, (-w * 0.20, -d * 0.05, shed_h + 0.08), (w * 0.45, d * 0.52, 0.14))
            # Bay dividers.
            for i in range(1, bay_count):
                x = -w * 0.5 + w * i / bay_count
                _add_box(bm, ranges, 1, (x, 0.0, 0.85), (0.10, d * 0.72, 0.16))

        if self.fence:
            # Three sides of paddock fence, front left open as a gate.
            rail_zs = (0.65, 1.15)
            for z in rail_zs:
                _add_box(bm, ranges, 1, (0.0, -d * 0.52, z), (w * 0.64, 0.08, 0.08))
                _add_box(bm, ranges, 1, (-w * 0.52, 0.0, z), (0.08, d, 0.08))
                _add_box(bm, ranges, 1, (w * 0.52, 0.0, z), (0.08, d, 0.08))
            for x in (-w * 0.52, -w * 0.18, w * 0.18, w * 0.52):
                for y in (-d * 0.52, d * 0.52):
                    _add_box(bm, ranges, 1, (x, y, 0.62), (0.13, 0.13, 1.24))
            if rng.random() < 0.55:
                # A slanted spare rail/tool breaks the rectangle without
                # needing fragile rotated geometry.
                _add_box(bm, ranges, 1, (w * rng.uniform(-0.22, 0.28), -d * 0.58, 0.32), (rng.uniform(1.0, 1.7), 0.08, 0.10))

        # Trough and hay/clutter.
        trough_x = w * rng.uniform(0.08, 0.28)
        trough_y = -d * rng.uniform(0.12, 0.24)
        _add_box(bm, ranges, 3, (trough_x, trough_y, 0.20), (rng.uniform(1.10, 1.45), 0.38, 0.40))
        _add_box(bm, ranges, 2, (trough_x, trough_y, 0.46), (rng.uniform(0.95, 1.25), 0.24, 0.12))
        hay_count = 4 if self.stable_yard_archetype != "cart_shelter" else 2
        for i in range(hay_count):
            _add_box(
                bm,
                ranges,
                2,
                (rng.uniform(-w * 0.36, w * 0.36), rng.uniform(-d * 0.18, d * 0.38), 0.22),
                (rng.uniform(0.46, 0.72), rng.uniform(0.36, 0.56), rng.uniform(0.30, 0.50)),
            )
        # Tack rail / tools.
        _add_box(bm, ranges, 1, (-w * 0.28, d * 0.48, 1.30), (1.20, 0.08, 0.08))
        for i in range(3):
            _add_box(bm, ranges, 1, (-w * 0.50 + i * 0.24, d * 0.53, 0.74), (0.06, 0.06, 0.95))

        if self.ruined > 0.1:
            for _ in range(6):
                _add_box(
                    bm,
                    ranges,
                    rng.choice([0, 1, 3]),
                    (rng.uniform(-w * 0.50, w * 0.50), rng.uniform(-d * 0.55, d * 0.55), 0.08),
                    (rng.uniform(0.30, 0.80), rng.uniform(0.10, 0.26), rng.uniform(0.10, 0.22)),
                )

        me = bpy.data.meshes.new(f"LowPolyStableYard({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()
        obj = bpy.data.objects.new(f"LowPolyStableYard({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)
        while len(obj.data.materials) < 4:
            obj.data.materials.append(None)
        for start, end, slot in ranges:
            for i in range(start, min(end, len(obj.data.polygons))):
                obj.data.polygons[i].material_index = slot
        for p in obj.data.polygons:
            p.use_smooth = False
        apply_palette_slots(obj, [self.roof_color, self.wood_color, self.hay_color, self.stone_color])
        return obj

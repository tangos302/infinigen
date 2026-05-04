"""LowPolyMushroomFactory — fairy / forest / enchanted mushroom prop.

Requested 2026-04-29 for fairy-village scenes. Reads as fantasy ground
flora — placed under trees, along paths, around clearings.

Archetypes:
  toadstool — red cap with white spots (stylized via vertex group +
              second material slot for spots), short white stem
  glowcap   — tall thin stem, narrow purple/amber cap, magical
              forest read (use foliage_amethyst or foliage_amber)
  cluster   — three small bonus mushrooms on one base; wider bbox

Material slots:
  slot 0 = cap   (default red `accent_red` / `foliage_amethyst`)
  slot 1 = stem  (default `stucco` for whites, `wood` otherwise)
  slot 2 = spots (toadstool only — defaults to `stucco`)
"""

from __future__ import annotations

import math

import bmesh
import bpy
from mathutils import Vector

from infinigen.core.placement.factory import AssetFactory

from ...density import n_sides_for_radius, target_edge_for_bbox
from ...materials import apply_palette_slots


_MUSHROOM_ARCHETYPES = ("toadstool", "glowcap", "cluster")


_ARCHETYPE_DEFAULTS = {
    "toadstool": dict(
        cap_radius=0.32, cap_height=0.20, stem_radius=0.10, stem_height=0.30,
        n_spots=4, spot_radius=0.045,
        cap_color="accent_red", stem_color="stucco", spot_color="stucco",
    ),
    "glowcap": dict(
        cap_radius=0.18, cap_height=0.32, stem_radius=0.05, stem_height=0.55,
        n_spots=0, spot_radius=0.0,
        cap_color="foliage_amethyst", stem_color="stucco", spot_color="stucco",
    ),
    "cluster": dict(
        cap_radius=0.20, cap_height=0.13, stem_radius=0.07, stem_height=0.20,
        n_spots=2, spot_radius=0.03,
        cap_color="foliage_amber", stem_color="stucco", spot_color="stucco",
    ),
}


def _bm_face_count(bm) -> int:
    return len(bm.faces)


def _add_stem(
    bm, slot_ranges, slot,
    cx: float, cy: float, base_z: float,
    radius: float, height: float, n_sides: int,
) -> float:
    """Tapered cylinder stem. Returns top-Z so the cap can sit on it."""
    start = _bm_face_count(bm)
    bot, top = [], []
    top_radius = radius * 0.85   # slight taper
    for s in range(n_sides):
        a = 2 * math.pi * s / n_sides
        bot.append(bm.verts.new(
            (cx + radius * math.cos(a),
             cy + radius * math.sin(a),
             base_z)
        ))
        top.append(bm.verts.new(
            (cx + top_radius * math.cos(a),
             cy + top_radius * math.sin(a),
             base_z + height)
        ))
    bm.verts.ensure_lookup_table()
    for s in range(n_sides):
        ns = (s + 1) % n_sides
        bm.faces.new((bot[s], bot[ns], top[ns], top[s]))
    bm.faces.new(list(reversed(bot)))   # closed bottom
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))
    return base_z + height


def _add_dome_cap(
    bm, slot_ranges, slot,
    cx: float, cy: float, base_z: float,
    radius: float, height: float, n_sides: int,
) -> tuple[float, float]:
    """Half-dome cap as a stack of rings climbing to a single apex.
    Returns (apex_z, average_top_radius) so spots can be placed on it.
    """
    start = _bm_face_count(bm)
    n_rings = 3
    rings: list[list] = []
    for r in range(n_rings):
        t = r / n_rings   # 0 at base, approaching 1 at apex
        # cap profile: bulge outward at base, taper to apex
        profile = math.cos(t * math.pi / 2)
        ring_radius = radius * profile
        ring_z = base_z + height * math.sin(t * math.pi / 2)
        ring = []
        for s in range(n_sides):
            a = 2 * math.pi * s / n_sides
            ring.append(bm.verts.new(
                (cx + ring_radius * math.cos(a),
                 cy + ring_radius * math.sin(a),
                 ring_z)
            ))
        rings.append(ring)
    apex = bm.verts.new((cx, cy, base_z + height))
    bm.verts.ensure_lookup_table()
    for r in range(n_rings - 1):
        for s in range(n_sides):
            ns = (s + 1) % n_sides
            bm.faces.new((rings[r][s], rings[r][ns],
                          rings[r + 1][ns], rings[r + 1][s]))
    # Top ring → apex (triangle fan)
    for s in range(n_sides):
        ns = (s + 1) % n_sides
        bm.faces.new((rings[-1][s], rings[-1][ns], apex))
    # Underside (dark gills) — flat ring back to centre
    under_centre = bm.verts.new((cx, cy, base_z))
    for s in range(n_sides):
        ns = (s + 1) % n_sides
        bm.faces.new((rings[0][ns], rings[0][s], under_centre))
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))
    return base_z + height, radius * 0.7


def _add_spot(
    bm, slot_ranges, slot,
    cx: float, cy: float, cz: float,
    radius: float,
) -> None:
    """A small flattened pyramid spot welded to the cap surface."""
    start = _bm_face_count(bm)
    n_sides = 5
    base = []
    for s in range(n_sides):
        a = 2 * math.pi * s / n_sides
        base.append(bm.verts.new(
            (cx + radius * math.cos(a),
             cy + radius * math.sin(a),
             cz)
        ))
    apex = bm.verts.new((cx, cy, cz + radius * 0.4))
    bm.verts.ensure_lookup_table()
    for s in range(n_sides):
        ns = (s + 1) % n_sides
        bm.faces.new((base[s], base[ns], apex))
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))


class LowPolyMushroomFactory(AssetFactory):
    """A stylized mushroom — toadstool / glowcap / cluster.

    Constructor knobs:

        factory_seed
        mushroom_archetype : str = "toadstool" | "glowcap" | "cluster"
        cap_radius, cap_height, stem_radius, stem_height : float
        n_spots, spot_radius : int / float
        cap_color, stem_color, spot_color : palette keys
    """

    def __init__(
        self,
        factory_seed,
        mushroom_archetype: str = "toadstool",
        cap_radius: float | None = None,
        cap_height: float | None = None,
        stem_radius: float | None = None,
        stem_height: float | None = None,
        n_spots: int | None = None,
        spot_radius: float | None = None,
        cap_color: str | None = None,
        stem_color: str | None = None,
        spot_color: str | None = None,
        polygon_multiplier: float = 1.0,
        coarse: bool = False,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if mushroom_archetype not in _MUSHROOM_ARCHETYPES:
            raise ValueError(
                f"unknown mushroom_archetype {mushroom_archetype!r}; "
                f"valid: {_MUSHROOM_ARCHETYPES}"
            )
        d = _ARCHETYPE_DEFAULTS[mushroom_archetype]
        self.mushroom_archetype = mushroom_archetype
        self.cap_radius = float(cap_radius if cap_radius is not None else d["cap_radius"])
        self.cap_height = float(cap_height if cap_height is not None else d["cap_height"])
        self.stem_radius = float(stem_radius if stem_radius is not None else d["stem_radius"])
        self.stem_height = float(stem_height if stem_height is not None else d["stem_height"])
        self.n_spots = int(n_spots if n_spots is not None else d["n_spots"])
        self.spot_radius = float(spot_radius if spot_radius is not None else d["spot_radius"])
        self.cap_color = cap_color or d["cap_color"]
        self.stem_color = stem_color or d["stem_color"]
        self.spot_color = spot_color or d["spot_color"]
        edge = target_edge_for_bbox(
            (self.cap_radius * 2, self.cap_radius * 2,
             self.cap_height + self.stem_height),
            polygon_multiplier=polygon_multiplier,
        )
        self.n_sides = max(6, n_sides_for_radius(self.cap_radius, edge))

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyMushroom({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build_one(
        self, bm, slot_ranges,
        cx: float, cy: float,
        cap_r: float, cap_h: float,
        stem_r: float, stem_h: float,
        n_spots: int, spot_r: float,
    ) -> None:
        top_z = _add_stem(
            bm, slot_ranges, 1, cx, cy, 0.0,
            stem_r, stem_h, self.n_sides,
        )
        apex_z, spot_band_r = _add_dome_cap(
            bm, slot_ranges, 0, cx, cy, top_z,
            cap_r, cap_h, self.n_sides,
        )
        if n_spots > 0 and spot_r > 0:
            for k in range(n_spots):
                a = 2 * math.pi * k / n_spots + 0.4
                t = 0.55   # fraction of cap height to plant the spot
                spot_z = top_z + cap_h * t
                # Spot sits on cap surface — derive radius from ring formula
                profile = math.cos(t * math.pi / 2)
                ring_r = cap_r * profile
                _add_spot(
                    bm, slot_ranges, 2,
                    cx + ring_r * math.cos(a) * 0.85,
                    cy + ring_r * math.sin(a) * 0.85,
                    spot_z, spot_r,
                )

    def _build(self) -> bpy.types.Object:
        bm = bmesh.new()
        slot_ranges: list[tuple[int, int, int]] = []

        if self.mushroom_archetype == "cluster":
            # Three mushrooms of varying sizes on a small footprint
            scales = (1.0, 0.7, 0.55)
            offsets = ((0.0, 0.0), (0.32, 0.10), (-0.18, 0.28))
            for s, (ox, oy) in zip(scales, offsets):
                self._build_one(
                    bm, slot_ranges, ox, oy,
                    self.cap_radius * s, self.cap_height * s,
                    self.stem_radius * s, self.stem_height * s,
                    self.n_spots, self.spot_radius * s,
                )
        else:
            self._build_one(
                bm, slot_ranges, 0.0, 0.0,
                self.cap_radius, self.cap_height,
                self.stem_radius, self.stem_height,
                self.n_spots, self.spot_radius,
            )

        me = bpy.data.meshes.new(f"LowPolyMushroom({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(f"LowPolyMushroom({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)

        while len(obj.data.materials) < 3:
            obj.data.materials.append(None)
        for start, end, slot in slot_ranges:
            for i in range(start, end):
                obj.data.polygons[i].material_index = slot
        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(obj, [self.cap_color, self.stem_color, self.spot_color])
        return obj

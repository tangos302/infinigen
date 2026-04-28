"""LowPolyBarrelFactory — wooden / metal storage barrel.

Tier-1 factory per empirical-attempt frequency (4/6 prompts:
medieval, campsite, Wild West, fishing). Reads as cargo, supplies,
or industrial storage in any inhabited scene.

Archetypes:
  wooden     — vertical staves + 2 metal hoops (medieval / fishing)
  metal_drum — smooth single-piece metal drum (Wild West / industrial)

Knobs let the caller stand the barrel up or lie it on its side
(with a 90° X-rotation), which is the most-requested variation in
prop scatters.

Material slots:
  slot 0 = body / staves     (default `wood` or `rust_metal`)
  slot 1 = bands             (default `rust_metal` for wooden archetype;
                              same as body for metal_drum)
"""

from __future__ import annotations

import math

import bmesh
import bpy
from mathutils import Matrix, Vector

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_BARREL_ARCHETYPES = ("wooden", "metal_drum")


_ARCHETYPE_DEFAULTS = {
    "wooden": dict(
        height=1.0, radius=0.4, n_staves=12, n_bands=2,
        band_thickness=0.05, band_protrusion=0.02,
        body_color="wood", band_color="rust_metal",
    ),
    "metal_drum": dict(
        height=0.95, radius=0.32, n_staves=12, n_bands=2,
        band_thickness=0.04, band_protrusion=0.015,
        body_color="rust_metal", band_color="rust_metal",
    ),
}


def _bm_face_count(bm) -> int:
    return len(bm.faces)


def _add_cylinder_section(
    bm,
    z0: float, z1: float,
    radius: float,
    n_sides: int,
) -> tuple[list, list, int]:
    """A ring of vertices at z0 and z1 with side faces between them. Returns
    (bottom_ring, top_ring, faces_added)."""
    n_before = _bm_face_count(bm)
    bottom = []
    top = []
    for s in range(n_sides):
        a = 2 * math.pi * s / n_sides
        x, y = radius * math.cos(a), radius * math.sin(a)
        bottom.append(bm.verts.new((x, y, z0)))
        top.append(bm.verts.new((x, y, z1)))
    bm.verts.ensure_lookup_table()
    for s in range(n_sides):
        ns = (s + 1) % n_sides
        bm.faces.new((bottom[s], bottom[ns], top[ns], top[s]))
    return bottom, top, _bm_face_count(bm) - n_before


class LowPolyBarrelFactory(AssetFactory):
    """A barrel — cylindrical body with optional metal hoops.

    Constructor knobs:

        factory_seed
        barrel_archetype  : str = "wooden"  "wooden" | "metal_drum"
        height            : float
        radius            : float
        n_staves          : int    cylinder side count
        n_bands           : int    metal hoops
        band_thickness    : float  hoop vertical thickness
        band_protrusion   : float  hoop sticks out by this much
        on_its_side       : bool   rotate 90° around X
        body_color        : str    slot 0
        band_color        : str    slot 1
    """

    def __init__(
        self,
        factory_seed,
        barrel_archetype: str = "wooden",
        height: float | None = None,
        radius: float | None = None,
        n_staves: int | None = None,
        n_bands: int | None = None,
        band_thickness: float | None = None,
        band_protrusion: float | None = None,
        on_its_side: bool = False,
        body_color: str | None = None,
        band_color: str | None = None,
        coarse: bool = False,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if barrel_archetype not in _BARREL_ARCHETYPES:
            raise ValueError(
                f"unknown barrel_archetype {barrel_archetype!r}; "
                f"valid: {_BARREL_ARCHETYPES}"
            )
        d = _ARCHETYPE_DEFAULTS[barrel_archetype]
        self.barrel_archetype = barrel_archetype
        self.height = float(height if height is not None else d["height"])
        self.radius = float(radius if radius is not None else d["radius"])
        self.n_staves = int(n_staves if n_staves is not None else d["n_staves"])
        self.n_bands = int(n_bands if n_bands is not None else d["n_bands"])
        self.band_thickness = float(
            band_thickness if band_thickness is not None else d["band_thickness"]
        )
        self.band_protrusion = float(
            band_protrusion if band_protrusion is not None else d["band_protrusion"]
        )
        self.on_its_side = bool(on_its_side)
        self.body_color = body_color or d["body_color"]
        self.band_color = band_color or d["band_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyBarrel({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        bm = bmesh.new()
        slot_ranges: list[tuple[int, int, int]] = []

        # Barrel body — single cylinder from 0 to height
        n_sides = self.n_staves
        body_start = _bm_face_count(bm)
        bottom_ring, top_ring, _ = _add_cylinder_section(
            bm, 0.0, self.height, self.radius, n_sides
        )
        # Cap top + bottom
        bm.faces.new(list(reversed(bottom_ring)))
        bm.faces.new(top_ring)
        body_end = _bm_face_count(bm)
        slot_ranges.append((body_start, body_end, 0))

        # Bands — protruding rings at evenly spaced heights, leaving
        # a margin from top + bottom so they read as belt hoops.
        if self.n_bands > 0 and self.band_thickness > 0:
            band_radius = self.radius + self.band_protrusion
            margin = self.height * 0.15
            usable = self.height - 2 * margin
            for k in range(self.n_bands):
                if self.n_bands == 1:
                    cz = self.height / 2
                else:
                    cz = margin + usable * k / (self.n_bands - 1)
                z0 = cz - self.band_thickness / 2
                z1 = cz + self.band_thickness / 2
                band_start = _bm_face_count(bm)
                b_ring, t_ring, _ = _add_cylinder_section(
                    bm, z0, z1, band_radius, n_sides
                )
                # Cap bands top + bottom so they're closed rings (not just
                # cylindrical sleeves) — looks more solid at low poly.
                bm.faces.new(list(reversed(b_ring)))
                bm.faces.new(t_ring)
                band_end = _bm_face_count(bm)
                slot_ranges.append((band_start, band_end, 1))

        # Convert to mesh + object
        me = bpy.data.meshes.new(f"LowPolyBarrel({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(f"LowPolyBarrel({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)

        while len(obj.data.materials) < 2:
            obj.data.materials.append(None)

        for start, end, slot in slot_ranges:
            for i in range(start, end):
                obj.data.polygons[i].material_index = slot

        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(obj, [self.body_color, self.band_color])

        if self.on_its_side:
            # 90° around X axis, then lift by radius so it rests on z=0
            obj.rotation_euler = (math.radians(90), 0, 0)
            obj.location.z = self.radius

        return obj

"""LowPolyHitchingPostFactory — wild-west / stable hitching rail.

Requested 2026-04-28 (2 attempts: Wild West, fishing village). Two
short wooden posts joined by a horizontal rail; reads as "this is
where horses get tied", instantly Western/medieval-stable.

Archetypes:
  single_rail — two posts + one rail (compact, ~1.6 BU long)
  double_rail — two posts + two stacked rails (taller, fancier)

Material slots:
  slot 0 = wood (post + rail)
  slot 1 = rope wrap / hardware (rust_metal accent on rail tips)
"""

from __future__ import annotations

import bmesh
import bpy

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_HITCHING_ARCHETYPES = ("single_rail", "double_rail")


_ARCHETYPE_DEFAULTS = {
    "single_rail": dict(
        rail_length=1.6, post_height=1.05, post_size=0.10,
        rail_height=0.85, rail_thickness=0.07,
        n_rails=1,
        wood_color="wood", hardware_color="rust_metal",
    ),
    "double_rail": dict(
        rail_length=1.8, post_height=1.20, post_size=0.10,
        rail_height=0.95, rail_thickness=0.07,
        n_rails=2,
        wood_color="wood", hardware_color="rust_metal",
    ),
}


def _bm_face_count(bm) -> int:
    return len(bm.faces)


def _add_box(bm, slot_ranges, slot,
             cx, cy, cz, sx, sy, sz):
    start = _bm_face_count(bm)
    hx, hy, hz = sx / 2, sy / 2, sz / 2
    b00 = bm.verts.new((cx - hx, cy - hy, cz - hz))
    b10 = bm.verts.new((cx + hx, cy - hy, cz - hz))
    b11 = bm.verts.new((cx + hx, cy + hy, cz - hz))
    b01 = bm.verts.new((cx - hx, cy + hy, cz - hz))
    t00 = bm.verts.new((cx - hx, cy - hy, cz + hz))
    t10 = bm.verts.new((cx + hx, cy - hy, cz + hz))
    t11 = bm.verts.new((cx + hx, cy + hy, cz + hz))
    t01 = bm.verts.new((cx - hx, cy + hy, cz + hz))
    bm.verts.ensure_lookup_table()
    bm.faces.new((b00, b10, t10, t00))
    bm.faces.new((b10, b11, t11, t10))
    bm.faces.new((b11, b01, t01, t11))
    bm.faces.new((b01, b00, t00, t01))
    bm.faces.new((t00, t10, t11, t01))
    bm.faces.new((b00, b01, b11, b10))
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))


class LowPolyHitchingPostFactory(AssetFactory):
    """A wild-west / stable hitching rail — two posts + 1 or 2 rails.

    Constructor knobs:

        factory_seed
        hitching_archetype : str = "single_rail" | "double_rail"
        rail_length, post_height, post_size : float
        rail_height, rail_thickness : float
        n_rails : int
        wood_color, hardware_color : palette keys
    """

    def __init__(
        self,
        factory_seed,
        hitching_archetype: str = "single_rail",
        rail_length: float | None = None,
        post_height: float | None = None,
        post_size: float | None = None,
        rail_height: float | None = None,
        rail_thickness: float | None = None,
        n_rails: int | None = None,
        wood_color: str | None = None,
        hardware_color: str | None = None,
        coarse: bool = False,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if hitching_archetype not in _HITCHING_ARCHETYPES:
            raise ValueError(
                f"unknown hitching_archetype {hitching_archetype!r}; "
                f"valid: {_HITCHING_ARCHETYPES}"
            )
        d = _ARCHETYPE_DEFAULTS[hitching_archetype]
        self.hitching_archetype = hitching_archetype
        self.rail_length = float(rail_length if rail_length is not None else d["rail_length"])
        self.post_height = float(post_height if post_height is not None else d["post_height"])
        self.post_size = float(post_size if post_size is not None else d["post_size"])
        self.rail_height = float(rail_height if rail_height is not None else d["rail_height"])
        self.rail_thickness = float(rail_thickness if rail_thickness is not None else d["rail_thickness"])
        self.n_rails = int(n_rails if n_rails is not None else d["n_rails"])
        self.wood_color = wood_color or d["wood_color"]
        self.hardware_color = hardware_color or d["hardware_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyHitchingPost({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        bm = bmesh.new()
        slot_ranges: list[tuple[int, int, int]] = []
        half_len = self.rail_length / 2

        # Two posts on the X axis
        for sign in (-1, 1):
            _add_box(
                bm, slot_ranges, 0,
                sign * half_len, 0.0, self.post_height / 2,
                self.post_size, self.post_size, self.post_height,
            )

        # Rail(s) connecting the posts
        rail_z_top = self.rail_height
        for i in range(self.n_rails):
            z = rail_z_top - i * (self.rail_thickness * 2.5)
            _add_box(
                bm, slot_ranges, 0,
                0.0, 0.0, z,
                self.rail_length, self.rail_thickness, self.rail_thickness,
            )

        # Hardware caps on rail tips (small bands of rust_metal)
        cap_t = self.rail_thickness * 1.3
        for sign in (-1, 1):
            _add_box(
                bm, slot_ranges, 1,
                sign * (half_len - cap_t * 0.5), 0.0, rail_z_top,
                cap_t, cap_t, self.rail_thickness * 1.05,
            )

        me = bpy.data.meshes.new(f"LowPolyHitchingPost({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(
            f"LowPolyHitchingPost({self.factory_seed})", me,
        )
        bpy.context.scene.collection.objects.link(obj)
        while len(obj.data.materials) < 2:
            obj.data.materials.append(None)
        for start, end, slot in slot_ranges:
            for i in range(start, end):
                obj.data.polygons[i].material_index = slot
        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(obj, [self.wood_color, self.hardware_color])
        return obj

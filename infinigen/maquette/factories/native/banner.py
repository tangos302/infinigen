"""LowPolyBannerFactory — hanging cloth banner / flag.

Second marketplace factory per Attempt 11. Banners hang from
buildings, towers, and stall corners and add the festive read that
the marketplace prompt wants. Same factory covers castle banners,
guild colours, and military flags by varying the `cloth_color`.

Archetypes:
  hanging      — vertical narrow banner with optional T-crossbar
                 from which it hangs (medieval / heraldry / market)
  flag_pole    — tall vertical pole + horizontal flag at the top
                 (Wild West / civic / castle)
  horizontal   — wide rectangle banner suspended from a horizontal
                 bar between 2 vertical posts (festival / market
                 entrance)

The cloth is a flat-shaded quad subdivided into N vertical segments;
each interior column gets a small alternating Y offset so the
silhouette reads as cloth-in-a-breeze rather than a flat board.

Material slots:
  slot 0 = cloth                 (default `accent_red` for high-contrast)
  slot 1 = pole / crossbar       (default `wood`)
"""

from __future__ import annotations

import math

import bmesh
import bpy
from mathutils import Vector

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_BANNER_ARCHETYPES = ("hanging", "flag_pole", "horizontal")


_ARCHETYPE_DEFAULTS = {
    "hanging": dict(
        length=0.8, height=2.0, pole_height=0.0,
        n_segments=3, wave_amplitude=0.06,
        has_crossbar=True, crossbar_extra=0.2,
        cloth_color="accent_red", pole_color="wood",
    ),
    "flag_pole": dict(
        length=1.6, height=0.9, pole_height=3.5,
        n_segments=3, wave_amplitude=0.08,
        has_crossbar=False, crossbar_extra=0.0,
        cloth_color="accent_red", pole_color="rust_metal",
    ),
    "horizontal": dict(
        length=3.0, height=0.7, pole_height=2.6,
        n_segments=5, wave_amplitude=0.05,
        has_crossbar=False, crossbar_extra=0.0,
        cloth_color="foliage_amber", pole_color="wood",
    ),
}


def _bm_face_count(bm) -> int:
    return len(bm.faces)


def _add_box(bm, cx, cy, cz, sx, sy, sz) -> int:
    n_before = _bm_face_count(bm)
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
    return _bm_face_count(bm) - n_before


def _add_box_slot(bm, slot_ranges, slot, cx, cy, cz, sx, sy, sz) -> None:
    s = _bm_face_count(bm)
    _add_box(bm, cx, cy, cz, sx, sy, sz)
    e = _bm_face_count(bm)
    slot_ranges.append((s, e, slot))


def _add_cloth_quad(
    bm, slot_ranges, slot,
    length: float, height: float,
    base_x: float, base_y: float, top_z: float,
    n_segments: int,
    wave_amplitude: float,
    is_horizontal: bool,
) -> None:
    """Cloth as N+1 vertical strips. For "hanging" archetype the cloth
    drops from top_z; for "horizontal" it stretches along X with
    interior columns wave-offset on Y. is_horizontal toggles which axis
    the wave is applied to.

    For non-horizontal (vertical hanging) banner: cloth drops in -Z
    from base_z=top_z, length is along X, wave on Y per column.
    For horizontal: cloth stretches along X at constant Z=top_z (the
    banner top edge attaches to a horizontal pole), wave on Y per column.
    """
    start = _bm_face_count(bm)
    n_cols = n_segments + 1
    bot_verts, top_verts = [], []
    for c in range(n_cols):
        u = c / n_segments  # 0 to 1 along length
        x = base_x - length / 2 + length * u
        # Wave on Y: alternating columns deflect ±wave_amplitude
        y = base_y + (wave_amplitude if (c % 2) else -wave_amplitude)
        # Top edge stays straight (attached to pole/crossbar)
        if c == 0 or c == n_cols - 1:
            y = base_y  # ends pinned
        if is_horizontal:
            # Horizontal banner: cloth stretches X at top_z, drops a
            # FIXED height in -Z. So bot/top are just (top_z - height) /
            # (top_z) — no per-column Z difference. Y wave still applies.
            top_verts.append(bm.verts.new((x, base_y, top_z)))  # top edge straight
            bot_verts.append(bm.verts.new((x, y, top_z - height)))
        else:
            # Vertical/hanging: cloth length along X, drops from top_z.
            top_verts.append(bm.verts.new((x, base_y, top_z)))
            bot_verts.append(bm.verts.new((x, y, top_z - height)))
    bm.verts.ensure_lookup_table()
    for c in range(n_cols - 1):
        bm.faces.new((bot_verts[c], bot_verts[c + 1],
                      top_verts[c + 1], top_verts[c]))
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))


class LowPolyBannerFactory(AssetFactory):
    """A hanging cloth banner / flag.

    Layout convention: the banner faces -Y (wave deflects on Y axis).
    For "flag_pole" the pole stands at origin and the flag projects in +X.
    For "horizontal" the bar runs along X, banner hangs in -Z.
    For "hanging" the banner drops in -Z from a crossbar at top_z.

    Constructor knobs:

        factory_seed
        banner_archetype : str = "hanging"
                           "hanging" | "flag_pole" | "horizontal"
        length, height   : float    cloth dimensions
        pole_height      : float    for flag_pole / horizontal stand height
        n_segments       : int      cloth subdivisions
        wave_amplitude   : float    Y offset amplitude
        has_crossbar     : bool     T-cross above hanging banner
        crossbar_extra   : float    crossbar overhangs cloth by this much
        cloth_color      : str      slot 0
        pole_color       : str      slot 1
    """

    def __init__(
        self,
        factory_seed,
        banner_archetype: str = "hanging",
        length: float | None = None,
        height: float | None = None,
        pole_height: float | None = None,
        n_segments: int | None = None,
        wave_amplitude: float | None = None,
        has_crossbar: bool | None = None,
        crossbar_extra: float | None = None,
        cloth_color: str | None = None,
        pole_color: str | None = None,
        coarse: bool = False,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if banner_archetype not in _BANNER_ARCHETYPES:
            # Lenient fallback rather than crash. Sonnet has been
            # observed to hallucinate plausible-sounding archetype
            # names despite the factories_guide brief listing the
            # valid set; killing a 6-minute build over a one-line
            # archetype typo wastes a generation. Substitute the
            # canonical default and warn to stderr.
            import sys
            print(
                f"[banner_archetype] WARN: unknown banner_archetype "
                f"{banner_archetype!r}; falling back to {_BANNER_ARCHETYPES[0]!r}. "
                f"Valid: {_BANNER_ARCHETYPES}",
                file=sys.stderr,
            )
            banner_archetype = _BANNER_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[banner_archetype]
        self.banner_archetype = banner_archetype
        self.length = float(length if length is not None else d["length"])
        self.height = float(height if height is not None else d["height"])
        self.pole_height = float(pole_height if pole_height is not None else d["pole_height"])
        self.n_segments = int(n_segments if n_segments is not None else d["n_segments"])
        self.wave_amplitude = float(wave_amplitude if wave_amplitude is not None else d["wave_amplitude"])
        self.has_crossbar = (
            bool(has_crossbar) if has_crossbar is not None else d["has_crossbar"]
        )
        self.crossbar_extra = float(crossbar_extra if crossbar_extra is not None else d["crossbar_extra"])
        self.cloth_color = cloth_color or d["cloth_color"]
        self.pole_color = pole_color or d["pole_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyBanner({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        bm = bmesh.new()
        slot_ranges: list[tuple[int, int, int]] = []

        if self.banner_archetype == "hanging":
            # Cloth drops from top_z to top_z - height
            top_z = 2.5  # default attach height
            if self.has_crossbar:
                # Crossbar: thin horizontal box across top of cloth
                cb_length = self.length + 2 * self.crossbar_extra
                cb_thickness = 0.04
                _add_box_slot(
                    bm, slot_ranges, 1,
                    0, 0, top_z + cb_thickness / 2,
                    cb_length, cb_thickness, cb_thickness,
                )
            _add_cloth_quad(
                bm, slot_ranges, 0,
                self.length, self.height,
                base_x=0, base_y=0, top_z=top_z,
                n_segments=self.n_segments,
                wave_amplitude=self.wave_amplitude,
                is_horizontal=False,
            )
        elif self.banner_archetype == "flag_pole":
            # Tall vertical pole + horizontal flag at the top.
            pole_radius = 0.04
            _add_box_slot(
                bm, slot_ranges, 1,
                0, 0, self.pole_height / 2,
                pole_radius * 2, pole_radius * 2, self.pole_height,
            )
            # Flag: rectangle attached on +X side at the top
            flag_top_z = self.pole_height
            flag_base_x = self.length / 2 + pole_radius
            _add_cloth_quad(
                bm, slot_ranges, 0,
                self.length, self.height,
                base_x=flag_base_x, base_y=0, top_z=flag_top_z,
                n_segments=self.n_segments,
                wave_amplitude=self.wave_amplitude,
                is_horizontal=False,
            )
        elif self.banner_archetype == "horizontal":
            # Two vertical posts + horizontal bar between them, banner
            # hangs from the bar.
            pole_radius = 0.05
            for sign in (-1, 1):
                _add_box_slot(
                    bm, slot_ranges, 1,
                    sign * self.length / 2, 0, self.pole_height / 2,
                    pole_radius * 2, pole_radius * 2, self.pole_height,
                )
            # Horizontal bar across top
            bar_thickness = 0.05
            _add_box_slot(
                bm, slot_ranges, 1,
                0, 0, self.pole_height + bar_thickness / 2,
                self.length + pole_radius * 2, bar_thickness, bar_thickness,
            )
            # Banner hanging from the bar
            _add_cloth_quad(
                bm, slot_ranges, 0,
                self.length * 0.95, self.height,
                base_x=0, base_y=0, top_z=self.pole_height,
                n_segments=self.n_segments,
                wave_amplitude=self.wave_amplitude,
                is_horizontal=True,
            )

        me = bpy.data.meshes.new(f"LowPolyBanner({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(f"LowPolyBanner({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)

        while len(obj.data.materials) < 2:
            obj.data.materials.append(None)

        for start, end, slot in slot_ranges:
            for i in range(start, end):
                obj.data.polygons[i].material_index = slot

        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(obj, [self.cloth_color, self.pole_color])
        return obj

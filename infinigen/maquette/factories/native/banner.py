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


def _add_cloth_grid(
    bm, slot_ranges, slot, stripe_slot,
    *,
    length: float, height: float,
    base_x: float, base_y: float, top_z: float,
    n_cols: int, amp: float,
    rng,
    hoist_pinned_col: int | None = None,
    stripe_row: int | None = None,
    fringe: bool = False,
    sag: float = 0.0,
    pennant: bool = False,
) -> None:
    """Draped cloth as a rows x cols grid. The wave is a sine over the
    column axis whose amplitude grows toward the bottom edge, so the cloth
    visibly billows instead of staying a board. Options: one grid row in a
    contrasting stripe slot, hanging fringe triangles, a catenary sag of
    the bottom edge, or a tapered pennant with a tip triangle."""
    n_rows = 3
    n_cols = max(4, n_cols)
    phase = rng.uniform(0.0, math.tau)
    freq = rng.uniform(1.2, 2.2)
    taper = 0.82 if pennant else 0.0

    grid: list[list] = []
    for ri in range(n_rows + 1):
        tv = ri / n_rows
        row = []
        for ci in range(n_cols + 1):
            u = ci / n_cols
            x = base_x - length / 2 + length * u
            wave = amp * math.sin(phase + u * freq * math.tau) * (tv ** 1.25)
            if hoist_pinned_col is not None:
                # Damp the wave near the pinned (hoist) edge.
                dist = abs(ci - hoist_pinned_col) / n_cols
                wave *= 0.25 + 0.75 * dist
            h_local = height * (1.0 - taper * u)
            z = top_z - h_local * tv - sag * math.sin(math.pi * u) * tv
            row.append(bm.verts.new((x, base_y + wave, z)))
        grid.append(row)
    bm.verts.ensure_lookup_table()
    for ri in range(n_rows):
        row_start = _bm_face_count(bm)
        for ci in range(n_cols):
            bm.faces.new((grid[ri + 1][ci], grid[ri + 1][ci + 1],
                          grid[ri][ci + 1], grid[ri][ci]))
        row_slot = stripe_slot if (stripe_row is not None and ri == stripe_row) else slot
        slot_ranges.append((row_start, _bm_face_count(bm), row_slot))

    if pennant:
        # Tip triangle continuing the taper to a point.
        start = _bm_face_count(bm)
        u = 1.0
        x_end = base_x + length / 2
        top_v = grid[0][n_cols]
        bot_v = grid[n_rows][n_cols]
        tip_z = (top_v.co.z + bot_v.co.z) / 2
        tip = bm.verts.new((x_end + length * 0.22,
                            (top_v.co.y + bot_v.co.y) / 2, tip_z))
        bm.verts.ensure_lookup_table()
        bm.faces.new((bot_v, tip, top_v))
        slot_ranges.append((start, _bm_face_count(bm), slot))

    if fringe:
        # Hanging triangles off the bottom edge.
        start = _bm_face_count(bm)
        bottom = grid[n_rows]
        for ci in range(n_cols):
            v0 = bottom[ci]
            v1 = bottom[ci + 1]
            tipv = bm.verts.new((
                (v0.co.x + v1.co.x) / 2,
                (v0.co.y + v1.co.y) / 2,
                min(v0.co.z, v1.co.z) - height * 0.10,
            ))
            bm.verts.ensure_lookup_table()
            bm.faces.new((v0, v1, tipv))
        slot_ranges.append((start, _bm_face_count(bm), stripe_slot))


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
        accent_color: str | None = None,
        coarse: bool = False,
        **_unused_kwargs,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if _unused_kwargs:
            from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
            accept_unused_kwargs("LowPolyBannerFactory", _unused_kwargs)
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
        self.accent_color = accent_color or d.get("accent_color", "stucco")

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyBanner({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        import random as _random
        rng = _random.Random(int(self.factory_seed) + 47093)
        bm = bmesh.new()
        slot_ranges: list[tuple[int, int, int]] = []
        amp = self.wave_amplitude * rng.uniform(1.6, 2.6)

        if self.banner_archetype == "hanging":
            # Heraldic drop banner: crossbar, stripe band, fringed hem.
            top_z = 2.5  # default attach height
            if self.has_crossbar:
                cb_length = self.length + 2 * self.crossbar_extra
                _add_box_slot(
                    bm, slot_ranges, 1,
                    0, 0, top_z + 0.02, cb_length, 0.05, 0.05,
                )
                # Finial knobs on the crossbar ends.
                for sign in (-1, 1):
                    _add_box_slot(
                        bm, slot_ranges, 1,
                        sign * cb_length / 2, 0, top_z + 0.02,
                        0.08, 0.08, 0.08,
                    )
            _add_cloth_grid(
                bm, slot_ranges, 0, 2,
                length=self.length, height=self.height,
                base_x=0, base_y=0, top_z=top_z,
                n_cols=max(4, self.n_segments + 1), amp=amp * 0.7,
                rng=rng,
                stripe_row=1 if rng.random() < 0.75 else None,
                fringe=rng.random() < 0.65,
            )
        elif self.banner_archetype == "flag_pole":
            # Tall pole + finial; flag flies from the hoist edge, 35% of
            # seeds get a tapered pennant instead of a rectangle.
            pole_radius = 0.04
            _add_box_slot(
                bm, slot_ranges, 1,
                0, 0, self.pole_height / 2,
                pole_radius * 2, pole_radius * 2, self.pole_height,
            )
            _add_box_slot(
                bm, slot_ranges, 1,
                0, 0, self.pole_height + 0.07, 0.09, 0.09, 0.14,
            )
            pennant = rng.random() < 0.35
            flag_base_x = self.length / 2 + pole_radius
            _add_cloth_grid(
                bm, slot_ranges, 0, 2,
                length=self.length, height=self.height,
                base_x=flag_base_x, base_y=0, top_z=self.pole_height - 0.05,
                n_cols=max(4, self.n_segments + 1), amp=amp,
                rng=rng,
                hoist_pinned_col=0,
                stripe_row=None if pennant else (1 if rng.random() < 0.5 else None),
                pennant=pennant,
            )
        elif self.banner_archetype == "horizontal":
            # Festival street banner: posts with caps, sagging cloth,
            # stripe band.
            pole_radius = 0.05
            for sign in (-1, 1):
                _add_box_slot(
                    bm, slot_ranges, 1,
                    sign * self.length / 2, 0, self.pole_height / 2,
                    pole_radius * 2, pole_radius * 2, self.pole_height,
                )
                _add_box_slot(
                    bm, slot_ranges, 1,
                    sign * self.length / 2, 0, self.pole_height + 0.05,
                    0.10, 0.10, 0.10,
                )
            bar_thickness = 0.05
            _add_box_slot(
                bm, slot_ranges, 1,
                0, 0, self.pole_height + bar_thickness / 2,
                self.length + pole_radius * 2, bar_thickness, bar_thickness,
            )
            _add_cloth_grid(
                bm, slot_ranges, 0, 2,
                length=self.length * 0.95, height=self.height,
                base_x=0, base_y=0, top_z=self.pole_height,
                n_cols=max(5, self.n_segments + 1), amp=amp * 0.6,
                rng=rng,
                stripe_row=1 if rng.random() < 0.7 else None,
                sag=self.height * rng.uniform(0.10, 0.22),
                fringe=rng.random() < 0.35,
            )

        me = bpy.data.meshes.new(f"LowPolyBanner({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(f"LowPolyBanner({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)

        while len(obj.data.materials) < 3:
            obj.data.materials.append(None)

        for start, end, slot in slot_ranges:
            for i in range(start, end):
                obj.data.polygons[i].material_index = slot

        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(
            obj, [self.cloth_color, self.pole_color, self.accent_color]
        )
        return obj

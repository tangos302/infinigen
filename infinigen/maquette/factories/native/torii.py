"""LowPolyToriiFactory — Japanese-style torii gate.

Iconic Japanese-temple identifier per Attempt 19. Forge v2 rebuild:
the first pass was two posts + two straight boxes (it read as a soccer
goal). This version models the real anatomy that makes the silhouette:

  - kasagi   : top lintel lofted so its tips sweep UP and outward
  - shimaki  : the second beam directly under the kasagi (myojin/ryobu)
  - nuki     : tie beam whose ends pierce past the pillars
  - gakuzuka : short centre strut between nuki and shimaki, with the
               little name-plaque (gaku) on the front
  - uchikorobi: pillars lean inward — wider stance at the ground
  - kamebara : octagonal base stones under the pillars

Archetypes:
  myojin     — classic vermilion shrine torii: double top beam, swept
               tips, black kasagi cap, plaque
  shinmei    — austere plain-timber style: straight kasagi, no shimaki,
               no plaque, minimal lean
  ryobu      — myojin plus auxiliary support posts (4 small posts with
               tie beams) around each pillar — the "floating gate" style

Material slots:
  slot 0 = pillars + beams      (default `accent_red` — vermilion)
  slot 1 = kasagi cap / accents (default `rock_shadow` — near-black)
  slot 2 = base stones          (default `rock_pale`)
"""

from __future__ import annotations

import math
import random

import bmesh
import bpy
from mathutils import Vector

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_TORII_ARCHETYPES = ("myojin", "shinmei", "ryobu")


_ARCHETYPE_DEFAULTS = {
    "myojin": dict(
        height=4.0, width=4.0,
        pillar_radius=0.18, pillar_taper=0.05,
        kasagi_height=0.30, kasagi_overhang=0.62, kasagi_curve_up=0.26,
        nuki_height=0.20, nuki_at_pct=0.74,
        has_bracing=False,
        gate_color="accent_red", accent_color="rock_shadow",
        base_color="rock_pale",
    ),
    "shinmei": dict(
        height=3.6, width=3.5,
        pillar_radius=0.16, pillar_taper=0.0,
        kasagi_height=0.22, kasagi_overhang=0.38, kasagi_curve_up=0.0,
        nuki_height=0.16, nuki_at_pct=0.78,
        has_bracing=False,
        gate_color="wood", accent_color="wood",
        base_color="rock_cool",
    ),
    "ryobu": dict(
        height=4.2, width=4.0,
        pillar_radius=0.20, pillar_taper=0.05,
        kasagi_height=0.32, kasagi_overhang=0.70, kasagi_curve_up=0.30,
        nuki_height=0.20, nuki_at_pct=0.72,
        has_bracing=True,
        gate_color="accent_red", accent_color="rock_shadow",
        base_color="rock_pale",
    ),
}


def _face_count(bm) -> int:
    return len(bm.faces)


def _add_box(bm, sr, slot, cx, cy, cz, sx, sy, sz) -> None:
    start = _face_count(bm)
    hx, hy, hz = sx / 2, sy / 2, sz / 2
    b = [bm.verts.new((cx + dx * hx, cy + dy * hy, cz - hz))
         for dx, dy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    t = [bm.verts.new((cx + dx * hx, cy + dy * hy, cz + hz))
         for dx, dy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    bm.verts.ensure_lookup_table()
    for i in range(4):
        ni = (i + 1) % 4
        bm.faces.new((b[i], b[ni], t[ni], t[i]))
    bm.faces.new((t[0], t[1], t[2], t[3]))
    bm.faces.new((b[3], b[2], b[1], b[0]))
    sr.append((start, _face_count(bm), slot))


def _add_strut(bm, sr, slot, p0, p1, thickness: float) -> None:
    """Oriented square-section box from p0 to p1 (leaning pillars, braces)."""
    start = _face_count(bm)
    p0 = Vector(p0)
    p1 = Vector(p1)
    d = p1 - p0
    length = d.length
    if length < 1e-6:
        return
    d = d / length
    up = Vector((0, 0, 1)) if abs(d.z) < 0.99 else Vector((1, 0, 0))
    u = d.cross(up).normalized() * (thickness / 2)
    w = d.cross(u).normalized() * (thickness / 2)
    base = [p0 - u - w, p0 + u - w, p0 + u + w, p0 - u + w]
    vb = [bm.verts.new(tuple(p)) for p in base]
    vt = [bm.verts.new(tuple(p + d * length)) for p in base]
    bm.verts.ensure_lookup_table()
    for i in range(4):
        ni = (i + 1) % 4
        bm.faces.new((vb[i], vb[ni], vt[ni], vt[i]))
    bm.faces.new(tuple(vt))
    bm.faces.new(tuple(reversed(vb)))
    sr.append((start, _face_count(bm), slot))


def _add_kasagi(
    bm, sr, slot,
    half_span: float, z_base: float, height: float, depth: float,
    curve_up: float,
) -> None:
    """Top lintel lofted from 5 cross-sections so the tips sweep upward.
    Sections are rectangles in the YZ plane; the tip sections rise by
    `curve_up` and thin out slightly — the classic swept-roof profile."""
    start = _face_count(bm)
    # (x, z_bottom, section_height, section_depth)
    secs = [
        (-half_span, z_base + curve_up, height * 0.72, depth * 0.86),
        (-half_span * 0.52, z_base, height, depth),
        (0.0, z_base - height * 0.06, height * 1.10, depth),
        (half_span * 0.52, z_base, height, depth),
        (half_span, z_base + curve_up, height * 0.72, depth * 0.86),
    ]
    rings = []
    for (x, zb, h, dp) in secs:
        ring = [
            bm.verts.new((x, -dp / 2, zb)),
            bm.verts.new((x, dp / 2, zb)),
            bm.verts.new((x, dp / 2, zb + h)),
            bm.verts.new((x, -dp / 2, zb + h)),
        ]
        rings.append(ring)
    bm.verts.ensure_lookup_table()
    for r0, r1 in zip(rings, rings[1:]):
        for i in range(4):
            ni = (i + 1) % 4
            bm.faces.new((r0[i], r0[ni], r1[ni], r1[i]))
    bm.faces.new(tuple(reversed(rings[0])))
    bm.faces.new(tuple(rings[-1]))
    sr.append((start, _face_count(bm), slot))


def _add_base_stone(bm, sr, slot, cx: float, r: float, h: float) -> None:
    """Octagonal pedestal stone under a pillar."""
    start = _face_count(bm)
    n = 8
    bot, top = [], []
    for s in range(n):
        a = 2 * math.pi * (s + 0.5) / n
        bot.append(bm.verts.new((cx + r * math.cos(a), r * math.sin(a), 0)))
        top.append(bm.verts.new((cx + r * 0.82 * math.cos(a),
                                 r * 0.82 * math.sin(a), h)))
    bm.verts.ensure_lookup_table()
    for s in range(n):
        ns = (s + 1) % n
        bm.faces.new((bot[s], bot[ns], top[ns], top[s]))
    bm.faces.new(top)
    bm.faces.new(list(reversed(bot)))
    sr.append((start, _face_count(bm), slot))


class LowPolyToriiFactory(AssetFactory):
    """A Japanese-style torii gate with real torii anatomy.

    Layout convention: gate spans along X axis (pillars at ±width/2),
    facing -Y direction. Caller positions and rotates.

    Constructor knobs:

        factory_seed
        torii_archetype : str = "myojin"
                          "myojin" | "shinmei" | "ryobu"
        height, width        : floats
        pillar_radius        : float
        pillar_taper         : float (0..1) — also drives the inward lean
        kasagi_height        : float (top beam thickness)
        kasagi_overhang      : float (overhang past pillars)
        kasagi_curve_up      : float (tip sweep) — myojin/ryobu only
        nuki_height          : float (tie-beam thickness)
        nuki_at_pct          : float (0..1, height fraction for tie beam)
        has_bracing          : bool  (ryobu auxiliary posts)
        gate_color           : str   slot 0
        accent_color         : str   slot 1 (kasagi cap, plaque)
        base_color           : str   slot 2 (pedestal stones)
    """

    def __init__(
        self,
        factory_seed,
        torii_archetype: str = "myojin",
        height: float | None = None,
        width: float | None = None,
        pillar_radius: float | None = None,
        pillar_taper: float | None = None,
        kasagi_height: float | None = None,
        kasagi_overhang: float | None = None,
        kasagi_curve_up: float | None = None,
        nuki_height: float | None = None,
        nuki_at_pct: float | None = None,
        has_bracing: bool | None = None,
        gate_color: str | None = None,
        accent_color: str | None = None,
        base_color: str | None = None,
        coarse: bool = False,
        **_unused_kwargs,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if _unused_kwargs:
            from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
            accept_unused_kwargs("LowPolyToriiFactory", _unused_kwargs)
        if torii_archetype not in _TORII_ARCHETYPES:
            # Lenient fallback rather than crash — see factory_kwargs_compat.
            import sys
            print(
                f"[torii_archetype] WARN: unknown torii_archetype "
                f"{torii_archetype!r}; falling back to {_TORII_ARCHETYPES[0]!r}. "
                f"Valid: {_TORII_ARCHETYPES}",
                file=sys.stderr,
            )
            torii_archetype = _TORII_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[torii_archetype]
        self.torii_archetype = torii_archetype
        rng = random.Random(int(factory_seed) + 61211)

        def _dim(value, key, lo=0.95, hi=1.06):
            if value is not None:
                return float(value)
            return float(d[key]) * rng.uniform(lo, hi)

        self.height = _dim(height, "height")
        self.width = _dim(width, "width")
        self.pillar_radius = float(pillar_radius if pillar_radius is not None else d["pillar_radius"])
        self.pillar_taper = float(pillar_taper if pillar_taper is not None else d["pillar_taper"])
        self.kasagi_height = float(kasagi_height if kasagi_height is not None else d["kasagi_height"])
        self.kasagi_overhang = float(kasagi_overhang if kasagi_overhang is not None else d["kasagi_overhang"])
        self.kasagi_curve_up = float(kasagi_curve_up if kasagi_curve_up is not None else d["kasagi_curve_up"])
        self.nuki_height = float(nuki_height if nuki_height is not None else d["nuki_height"])
        self.nuki_at_pct = float(nuki_at_pct if nuki_at_pct is not None else d["nuki_at_pct"])
        self.has_bracing = (
            bool(has_bracing) if has_bracing is not None else d["has_bracing"]
        )
        self.gate_color = gate_color or d["gate_color"]
        self.accent_color = accent_color or d["accent_color"]
        self.base_color = base_color or d["base_color"]
        self._has_plaque = torii_archetype != "shinmei" and rng.random() < 0.8

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyTorii({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []

        H, W = self.height, self.width
        pt = self.pillar_radius * 2
        is_plain = self.torii_archetype == "shinmei"

        # Pillars with inward lean (uchikorobi): wider stance at the base.
        lean = 0.0 if is_plain else H * 0.045
        stone_h = 0.16 if is_plain else 0.22
        for sign in (-1, 1):
            base = (sign * (W / 2 + lean), 0.0, stone_h * 0.6)
            top = (sign * W / 2, 0.0, H)
            _add_strut(bm, sr, 0, base, top, pt)
            _add_base_stone(bm, sr, 2, sign * (W / 2 + lean), pt * 1.05, stone_h)

        # Shimaki (lower top beam) + kasagi (upper, swept). Shinmei keeps a
        # single straight kasagi.
        if is_plain:
            kasagi_z = H
        else:
            shimaki_h = self.kasagi_height * 0.72
            _add_box(bm, sr, 0, 0, 0, H + shimaki_h / 2,
                     W + 2 * self.kasagi_overhang * 0.62, pt * 1.25, shimaki_h)
            kasagi_z = H + shimaki_h
        _add_kasagi(
            bm, sr, 1 if not is_plain else 0,
            W / 2 + self.kasagi_overhang, kasagi_z,
            self.kasagi_height, pt * 1.45, self.kasagi_curve_up,
        )

        # Nuki tie beam — ends pierce past the pillars.
        nuki_z = H * self.nuki_at_pct
        _add_box(bm, sr, 0, 0, 0, nuki_z,
                 W + pt * 1.7, pt * 0.85, self.nuki_height)

        # Gakuzuka centre strut + the little gaku plaque.
        if not is_plain:
            gap_lo = nuki_z + self.nuki_height / 2
            gap_hi = H
            _add_box(bm, sr, 0, 0, 0, (gap_lo + gap_hi) / 2,
                     pt * 0.8, pt * 0.8, gap_hi - gap_lo)
            if self._has_plaque:
                _add_box(bm, sr, 1, 0, -pt * 0.55, (gap_lo + gap_hi) / 2,
                         pt * 1.5, 0.05, (gap_hi - gap_lo) * 0.85)

        # Ryobu auxiliary posts: a smaller post fore and aft of each pillar,
        # tied to it with a short beam.
        if self.has_bracing:
            aux_h = H * 0.62
            for sign in (-1, 1):
                px = sign * (W / 2 + lean * (1 - aux_h / H))
                for ysign in (-1, 1):
                    ay = ysign * pt * 2.1
                    _add_strut(bm, sr, 0,
                               (sign * (W / 2 + lean) + 0.0, ay, 0.0),
                               (sign * W / 2 * (1 - 0.02), ay, aux_h),
                               pt * 0.55)
                # Tie beam through the pillar connecting both aux posts.
                _add_box(bm, sr, 0, px, 0, aux_h * 0.82,
                         pt * 0.6, pt * 5.0, pt * 0.6)

        me = bpy.data.meshes.new(f"LowPolyTorii({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(f"LowPolyTorii({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)

        while len(obj.data.materials) < 3:
            obj.data.materials.append(None)
        for start, end, slot in sr:
            for i in range(start, end):
                obj.data.polygons[i].material_index = slot
        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(obj, [self.gate_color, self.accent_color, self.base_color])
        return obj

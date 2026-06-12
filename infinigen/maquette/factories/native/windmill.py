"""LowPolyWindmillFactory — windmill / windpump landmark.

Surfaced in farmstead (Attempt 9) and Wild West (Attempt 3) — also a
strong silhouette element for fishing villages with grain mills.
The sail cross is what makes the silhouette read; without spinning
animation a fixed pose works fine for the static-scene aesthetic.

Forge v2 rebuild: the first pass was a bare cone with plank blades.
This version models real mill anatomy — tarred base course, smock
tower with door and windows, optional gallery stage, overhanging
onion cap, and proper sails (stock + crossbar lattice + cloth panel)
on a windshaft raked ~12 degrees up so the sails clear the tower the
way real mills do.

Archetypes:
  dutch          — octagonal smock tower + gallery stage + onion cap +
                   4 lattice-and-cloth sails (Dutch / European mill)
  western_pump   — slanted-leg truss tower + platform + multi-blade
                   fan + tail vane (Wild West windpump)
  stone_mill     — squat round stone tower + overhanging cone cap +
                   4 sails, optional lean-to annex (medieval mill)

One sail may be left bare (cloth furled) by seed — real mills are
rarely fully dressed. Override `blade_phase` to pick a "frozen"
rotor angle; by default it is seeded per factory.

Material slots:
  slot 0 = tower / structure   (default `rock_pale` / `rust_metal` / `rock_cool`)
  slot 1 = timber: sails, door, stage, windows  (default `wood`)
  slot 2 = roof / cap / base course             (default `rock_shadow`)
  slot 3 = sail cloth / painted vane            (default `stucco`)
"""

from __future__ import annotations

import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector

from infinigen.core.placement.factory import AssetFactory

from ...density import n_sides_for_radius, target_edge_for_bbox
from ...materials import apply_palette_slots


_WINDMILL_ARCHETYPES = ("dutch", "western_pump", "stone_mill")


_ARCHETYPE_DEFAULTS = {
    "dutch": dict(
        tower_height=5.2, tower_top_radius=0.78, tower_bottom_radius=1.30,
        n_blades=4, blade_length=3.0, blade_width=0.85,
        blade_thickness=0.07, blade_phase=None, hub_radius=0.16,
        has_dome=True, dome_height=0.95,
        tower_color="rock_pale", blade_color="wood", roof_color="rock_shadow",
        sail_color="stucco",
    ),
    "western_pump": dict(
        tower_height=4.6, tower_top_radius=0.34, tower_bottom_radius=0.95,
        n_blades=14, blade_length=0.95, blade_width=0.16,
        blade_thickness=0.03, blade_phase=None, hub_radius=0.12,
        has_dome=False, dome_height=0.0,
        tower_color="rust_metal", blade_color="rust_metal",
        roof_color="rock_shadow", sail_color="stucco",
    ),
    "stone_mill": dict(
        tower_height=3.7, tower_top_radius=1.02, tower_bottom_radius=1.42,
        n_blades=4, blade_length=2.5, blade_width=0.78,
        blade_thickness=0.07, blade_phase=None, hub_radius=0.15,
        has_dome=True, dome_height=1.05,
        tower_color="rock_cool", blade_color="wood",
        roof_color="rock_shadow", sail_color="stucco",
    ),
}


def _face_count(bm) -> int:
    return len(bm.faces)


def _add_box(bm, sr, slot, cx, cy, cz, sx, sy, sz) -> None:
    """Axis-aligned box centered at (cx, cy, cz)."""
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


def _add_strut(bm, sr, slot, p0, p1, thickness: float, *, t2: float | None = None) -> None:
    """Oriented box of square section `thickness` (optionally thickness x t2)
    connecting points p0 -> p1. Used for slanted posts, braces, rails,
    sail stocks, the windshaft."""
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
    w = d.cross(u).normalized() * ((t2 if t2 is not None else thickness) / 2)
    b = [p0 - u - w, p0 + u - w, p0 + u + w, p0 - u + w]
    t = [p + d * length for p in b]
    vb = [bm.verts.new(tuple(p)) for p in b]
    vt = [bm.verts.new(tuple(p)) for p in t]
    bm.verts.ensure_lookup_table()
    for i in range(4):
        ni = (i + 1) % 4
        bm.faces.new((vb[i], vb[ni], vt[ni], vt[i]))
    bm.faces.new(tuple(vt))
    bm.faces.new(tuple(reversed(vb)))
    sr.append((start, _face_count(bm), slot))


def _add_frustum(
    bm, sr, slot,
    cx: float, cy: float, z0: float,
    r_bot: float, r_top: float, height: float, n: int,
    *, cap_bottom: bool = True, cap_top: bool = True, rot: float = 0.0,
) -> None:
    """N-gon frustum from z0 to z0+height (tower shells, eave rings, cones)."""
    start = _face_count(bm)
    bot, top = [], []
    for s in range(n):
        a = rot + 2 * math.pi * s / n
        bot.append(bm.verts.new((cx + r_bot * math.cos(a),
                                 cy + r_bot * math.sin(a), z0)))
        top.append(bm.verts.new((cx + max(r_top, 1e-4) * math.cos(a),
                                 cy + max(r_top, 1e-4) * math.sin(a),
                                 z0 + height)))
    bm.verts.ensure_lookup_table()
    for s in range(n):
        ns = (s + 1) % n
        bm.faces.new((bot[s], bot[ns], top[ns], top[s]))
    if cap_top and r_top > 1e-3:
        bm.faces.new(top)
    if cap_bottom:
        bm.faces.new(list(reversed(bot)))
    sr.append((start, _face_count(bm), slot))


def _add_onion_cap(
    bm, sr, slot,
    cx: float, cy: float, z0: float,
    radius: float, height: float, n_sides: int,
) -> None:
    """Bulged onion cap: rings following a (t, scale) profile + apex."""
    start = _face_count(bm)
    profile = ((0.0, 1.0), (0.30, 1.06), (0.58, 0.80), (0.82, 0.42))
    rings = []
    for t, scale in profile:
        ring = []
        for s in range(n_sides):
            a = 2 * math.pi * s / n_sides
            ring.append(bm.verts.new((cx + radius * scale * math.cos(a),
                                      cy + radius * scale * math.sin(a),
                                      z0 + height * t)))
        rings.append(ring)
    apex = bm.verts.new((cx, cy, z0 + height))
    bm.verts.ensure_lookup_table()
    for r in range(len(rings) - 1):
        ra, rb = rings[r], rings[r + 1]
        for s in range(n_sides):
            ns = (s + 1) % n_sides
            bm.faces.new((ra[s], ra[ns], rb[ns], rb[s]))
    last = rings[-1]
    for s in range(n_sides):
        ns = (s + 1) % n_sides
        bm.faces.new((last[s], last[ns], apex))
    bm.faces.new(list(reversed(rings[0])))
    sr.append((start, _face_count(bm), slot))


class LowPolyWindmillFactory(AssetFactory):
    """A windmill / windpump — smock or stone tower with cloth sails, or a
    truss windpump with a fan and tail vane.

    Constructor knobs:

        factory_seed
        windmill_archetype : str = "dutch"
                             "dutch" | "western_pump" | "stone_mill"
        tower_height          : float
        tower_top_radius      : float
        tower_bottom_radius   : float
        n_tower_sides         : int
        n_blades              : int      sails (dutch/stone) or fan blades (pump)
        blade_length          : float
        blade_width           : float
        blade_thickness       : float
        blade_phase           : float    radians; rotates the rotor (seeded if unset)
        hub_radius            : float
        has_dome              : bool     cap on round towers
        dome_height           : float
        tower_color           : str    slot 0
        blade_color           : str    slot 1 (timber: sails/door/stage)
        roof_color            : str    slot 2 (cap + tarred base course)
        sail_color            : str    slot 3 (sail cloth / painted vane)
    """

    def __init__(
        self,
        factory_seed,
        windmill_archetype: str = "dutch",
        tower_height: float | None = None,
        tower_top_radius: float | None = None,
        tower_bottom_radius: float | None = None,
        polygon_multiplier: float = 1.0,
        target_edge: float | None = None,
        n_tower_sides: int | None = None,
        n_blades: int | None = None,
        blade_length: float | None = None,
        blade_width: float | None = None,
        blade_thickness: float | None = None,
        blade_phase: float | None = None,
        hub_radius: float | None = None,
        has_dome: bool | None = None,
        dome_height: float | None = None,
        tower_color: str | None = None,
        blade_color: str | None = None,
        roof_color: str | None = None,
        sail_color: str | None = None,
        coarse: bool = False,
        **_unused_kwargs,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if _unused_kwargs:
            from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
            accept_unused_kwargs("LowPolyWindmillFactory", _unused_kwargs)
        if windmill_archetype not in _WINDMILL_ARCHETYPES:
            # Lenient fallback rather than crash — LLMs have been observed
            # to hallucinate plausible-sounding archetype names; killing a
            # 6-minute build over a one-line typo wastes a generation.
            import sys
            print(
                f"[windmill_archetype] WARN: unknown windmill_archetype "
                f"{windmill_archetype!r}; falling back to {_WINDMILL_ARCHETYPES[0]!r}. "
                f"Valid: {_WINDMILL_ARCHETYPES}",
                file=sys.stderr,
            )
            windmill_archetype = _WINDMILL_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[windmill_archetype]
        self.windmill_archetype = windmill_archetype
        rng = random.Random(int(factory_seed) + 51317)
        self._rng = rng

        # Seed jitter applies only when the caller didn't pin a value.
        def _dim(value, key, lo=0.92, hi=1.08):
            if value is not None:
                return float(value)
            return float(d[key]) * rng.uniform(lo, hi)

        self.tower_height = _dim(tower_height, "tower_height")
        self.tower_top_radius = _dim(tower_top_radius, "tower_top_radius", 0.95, 1.05)
        self.tower_bottom_radius = _dim(tower_bottom_radius, "tower_bottom_radius", 0.95, 1.05)
        edge = (
            float(target_edge) if target_edge is not None
            else target_edge_for_bbox(
                (self.tower_bottom_radius * 2, self.tower_bottom_radius * 2,
                 self.tower_height),
                polygon_multiplier=polygon_multiplier,
            )
        )
        if n_tower_sides is not None:
            self.n_tower_sides = int(n_tower_sides)
        elif windmill_archetype == "dutch":
            self.n_tower_sides = 8  # smock mills are octagonal
        else:
            self.n_tower_sides = n_sides_for_radius(
                self.tower_bottom_radius, edge, min_n=8,
            )
        self.n_blades = int(n_blades if n_blades is not None else d["n_blades"])
        self.blade_length = _dim(blade_length, "blade_length", 0.95, 1.06)
        self.blade_width = float(blade_width if blade_width is not None else d["blade_width"])
        self.blade_thickness = float(
            blade_thickness if blade_thickness is not None else d["blade_thickness"]
        )
        if blade_phase is not None:
            self.blade_phase = float(blade_phase)
        else:
            self.blade_phase = rng.uniform(0.1, math.pi / 2)
        self.hub_radius = float(hub_radius if hub_radius is not None else d["hub_radius"])
        self.has_dome = bool(has_dome) if has_dome is not None else d["has_dome"]
        self.dome_height = float(
            dome_height if dome_height is not None else d["dome_height"]
        )
        self.tower_color = tower_color or d["tower_color"]
        self.blade_color = blade_color or d["blade_color"]
        self.roof_color = roof_color or d["roof_color"]
        self.sail_color = sail_color or d["sail_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyWindmill({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    # -- rotor ---------------------------------------------------------------

    def _add_sail_rotor(self, bm, sr, *, center: Vector, sail_len: float,
                        sail_w: float, rng: random.Random) -> None:
        """Classic 4-sail rotor: windshaft raked ~12 deg up, each sail =
        stock + crossbar lattice + trapezoid cloth panel. Cloth sits on the
        trailing side of the stock like a real common sail; one sail may be
        left bare (furled)."""
        rake = math.radians(12.0)
        tilt = Matrix.Rotation(-rake, 4, "X")  # +Y axis noses upward
        axis = tilt @ Vector((0.0, 1.0, 0.0))

        # Windshaft from inside the cap out to the hub.
        neck = 0.55
        hub_pos = center + axis * neck
        _add_strut(bm, sr, 1, center - axis * 0.25, hub_pos + axis * 0.10, 0.16)
        # Hub block.
        start = _face_count(bm)
        hb = self.hub_radius
        hub_verts_b = []
        hub_verts_t = []
        for dx, dz in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            lo = tilt @ Vector((dx * hb, -0.10, dz * hb)) + hub_pos
            hi = tilt @ Vector((dx * hb, 0.10, dz * hb)) + hub_pos
            hub_verts_b.append(bm.verts.new(tuple(lo)))
            hub_verts_t.append(bm.verts.new(tuple(hi)))
        bm.verts.ensure_lookup_table()
        for i in range(4):
            ni = (i + 1) % 4
            bm.faces.new((hub_verts_b[i], hub_verts_b[ni],
                          hub_verts_t[ni], hub_verts_t[i]))
        bm.faces.new(tuple(hub_verts_t))
        bm.faces.new(tuple(reversed(hub_verts_b)))
        sr.append((start, _face_count(bm), 1))

        n_sails = max(2, min(6, self.n_blades))
        bare_sail = rng.randrange(n_sails) if rng.random() < 0.30 else -1
        for i in range(n_sails):
            a = self.blade_phase + 2 * math.pi * i / n_sails
            spin = Matrix.Rotation(a, 4, "Y")
            xf = tilt @ spin

            def W(x, y, z):
                return hub_pos + xf @ Vector((x, y, z))

            # Stock: heel just past the hub to the tip.
            _add_strut(bm, sr, 1, W(-0.25, 0.0, 0.0), W(sail_len, 0.0, 0.0), 0.07)
            inner = sail_len * 0.30
            # Crossbars stick out past the cloth on both sides.
            for fx in (0.45, 0.62, 0.79, 0.96):
                x = sail_len * fx
                _add_strut(bm, sr, 1,
                           W(x, 0.0, -sail_w * 0.20), W(x, 0.0, sail_w * 0.80),
                           0.035)
            # Hemlath (outer stringer) along the lattice edge.
            _add_strut(bm, sr, 1,
                       W(inner, 0.0, sail_w * 0.74), W(sail_len, 0.0, sail_w * 0.74),
                       0.035)
            if i == bare_sail:
                continue
            # Cloth: thin trapezoid panel on the trailing side of the stock,
            # slightly behind the lattice plane. Narrows toward the hub.
            start = _face_count(bm)
            y = 0.045
            c0 = bm.verts.new(tuple(W(inner, y, 0.03)))
            c1 = bm.verts.new(tuple(W(sail_len * 0.99, y, 0.03)))
            c2 = bm.verts.new(tuple(W(sail_len * 0.99, y, sail_w * 0.72)))
            c3 = bm.verts.new(tuple(W(inner, y, sail_w * 0.45)))
            bm.verts.ensure_lookup_table()
            bm.faces.new((c0, c1, c2, c3))  # single quad; Cycles shades both sides
            sr.append((start, _face_count(bm), 3))

    # -- archetype builds ------------------------------------------------------

    def _build_dutch(self, bm, sr, rng: random.Random) -> None:
        h = self.tower_height
        r_bot = self.tower_bottom_radius
        r_top = self.tower_top_radius
        n = self.n_tower_sides
        base_h = 0.55
        # Tarred base course, slightly flared.
        _add_frustum(bm, sr, 2, 0, 0, 0, r_bot * 1.06, r_bot * 0.98, base_h, n)
        # Smock body.
        _add_frustum(bm, sr, 0, 0, 0, base_h, r_bot * 0.98, r_top, h - base_h, n)
        # Door (front = -Y, proud of the wall).
        _add_box(bm, sr, 1, 0, -(r_bot * 0.97), base_h * 0.5 + 0.42,
                 0.52, 0.22, 1.05)
        # 1-2 windows at seeded heights/sides.
        for k in range(rng.randint(1, 2)):
            t = rng.uniform(0.45, 0.78)
            ang = rng.choice((-0.5, 0.0, 0.5)) + (0 if k == 0 else math.pi)
            rr = r_bot * 0.98 + (r_top - r_bot * 0.98) * t
            wx = math.sin(ang) * rr * 0.97
            wy = -math.cos(ang) * rr * 0.97
            _add_box(bm, sr, 1, wx, wy, base_h + (h - base_h) * t,
                     0.30, 0.30, 0.38)
        # Gallery stage (smock-mill balcony) ~38% up, seed-gated.
        if rng.random() < 0.72:
            tz = 0.38
            z = base_h + (h - base_h) * tz
            rr = (r_bot * 0.98 + (r_top - r_bot * 0.98) * tz) + 0.42
            _add_frustum(bm, sr, 1, 0, 0, z, rr, rr, 0.07, n)
            for s in range(n):
                a = 2 * math.pi * (s + 0.5) / n
                px, py = (rr - 0.05) * math.cos(a), (rr - 0.05) * math.sin(a)
                _add_strut(bm, sr, 1, (px, py, z + 0.07), (px, py, z + 0.50), 0.05)
            ring = []
            for s in range(n):
                a = 2 * math.pi * (s + 0.5) / n
                ring.append(((rr - 0.05) * math.cos(a), (rr - 0.05) * math.sin(a)))
            for s in range(n):
                x0, y0 = ring[s]
                x1, y1 = ring[(s + 1) % n]
                _add_strut(bm, sr, 1, (x0, y0, z + 0.50), (x1, y1, z + 0.50), 0.04)
        # Cap: eave ring + onion dome + finial.
        cap_h = self.dome_height if self.has_dome else 0.55
        _add_frustum(bm, sr, 2, 0, 0, h, r_top * 1.22, r_top * 1.12, 0.10, n)
        _add_onion_cap(bm, sr, 2, 0, 0, h + 0.10, r_top * 1.12, cap_h, n)
        _add_strut(bm, sr, 1, (0, 0, h + 0.10 + cap_h - 0.02),
                   (0, 0, h + 0.10 + cap_h + 0.30), 0.05)
        # Rotor on the -Y face, centered in the cap.
        center = Vector((0.0, -(r_top * 0.55), h + 0.10 + cap_h * 0.38))
        center.y -= 0.1
        rot_center = Vector((0.0, center.y, center.z))
        # build with +Y pointing away from tower: mirror by spinning 180 deg
        self._mirror_rotor(bm, sr, rot_center, rng)

    def _mirror_rotor(self, bm, sr, center: Vector, rng: random.Random) -> None:
        """Place the sail rotor on the -Y side (front) of the cap."""
        n0 = len(bm.verts)
        self._add_sail_rotor(bm, sr, center=Vector((0, 0, 0)),
                             sail_len=self.blade_length,
                             sail_w=self.blade_width, rng=rng)
        flip = Matrix.Rotation(math.pi, 4, "Z")
        bm.verts.ensure_lookup_table()
        for v in bm.verts[n0:]:
            v.co = flip @ v.co + center

    def _build_stone_mill(self, bm, sr, rng: random.Random) -> None:
        h = self.tower_height
        r_bot = self.tower_bottom_radius
        r_top = self.tower_top_radius
        n = self.n_tower_sides
        # Battered round tower with a slight base flare.
        _add_frustum(bm, sr, 0, 0, 0, 0, r_bot * 1.08, r_bot, 0.4, n)
        _add_frustum(bm, sr, 0, 0, 0, 0.4, r_bot, r_top, h - 0.4, n)
        # Stone door surround + timber door.
        _add_box(bm, sr, 2, 0, -(r_bot * 0.92), 0.62, 0.72, 0.30, 1.24)
        _add_box(bm, sr, 1, 0, -(r_bot * 0.92) - 0.06, 0.55, 0.46, 0.26, 1.00)
        # One small window.
        t = rng.uniform(0.55, 0.75)
        rr = r_bot + (r_top - r_bot) * t
        ang = rng.choice((-0.7, 0.7))
        _add_box(bm, sr, 1, math.sin(ang) * rr * 0.95, -math.cos(ang) * rr * 0.95,
                 h * t, 0.26, 0.26, 0.34)
        # Overhanging conical cap.
        cap_h = self.dome_height if self.has_dome else 0.9
        _add_frustum(bm, sr, 2, 0, 0, h, r_top * 1.30, r_top * 1.18, 0.10, n)
        _add_frustum(bm, sr, 2, 0, 0, h + 0.10, r_top * 1.18, 0.04, cap_h, n,
                     cap_top=False)
        # Lean-to annex, seed-gated.
        if rng.random() < 0.55:
            side = rng.choice((-1.0, 1.0))
            ax = side * (r_bot * 0.85 + 0.55)
            _add_box(bm, sr, 0, ax, 0.1, 0.55, 1.30, 1.05, 1.10)
            start = _face_count(bm)
            sl0 = bm.verts.new((ax - side * 0.75, -0.50, 1.10))
            sl1 = bm.verts.new((ax - side * 0.75, 0.70, 1.10))
            sl2 = bm.verts.new((ax + side * 0.78, 0.70, 1.42))
            sl3 = bm.verts.new((ax + side * 0.78, -0.50, 1.42))
            bm.verts.ensure_lookup_table()
            bm.faces.new((sl0, sl1, sl2, sl3))
            sr.append((start, _face_count(bm), 2))
        # Rotor.
        center = Vector((0.0, -(r_top * 0.50) - 0.1, h + 0.10 + cap_h * 0.30))
        self._mirror_rotor(bm, sr, center, rng)

    def _build_western_pump(self, bm, sr, rng: random.Random) -> None:
        h = self.tower_height
        bot = self.tower_bottom_radius
        top = self.tower_top_radius
        # Four slanted legs.
        corners = ((-1, -1), (1, -1), (1, 1), (-1, 1))
        for dx, dy in corners:
            _add_strut(bm, sr, 0,
                       (dx * bot, dy * bot, 0.0), (dx * top, dy * top, h), 0.07)
        # Horizontal girts at 3 levels + alternating diagonals.
        for li, tlev in enumerate((0.28, 0.55, 0.80)):
            z = h * tlev
            s = bot + (top - bot) * tlev
            pts = [(dx * s, dy * s, z) for dx, dy in corners]
            for i in range(4):
                _add_strut(bm, sr, 0, pts[i], pts[(i + 1) % 4], 0.045)
            if li < 2:
                t2 = (0.28, 0.55, 0.80)[li + 1]
                z2 = h * t2
                s2 = bot + (top - bot) * t2
                p_lo = [(dx * s, dy * s, z) for dx, dy in corners]
                p_hi = [(dx * s2, dy * s2, z2) for dx, dy in corners]
                for i in range(4):
                    j = (i + 1) % 4
                    if (i + li) % 2 == 0:
                        _add_strut(bm, sr, 0, p_lo[i], p_hi[j], 0.035)
                    else:
                        _add_strut(bm, sr, 0, p_lo[j], p_hi[i], 0.035)
        # Platform deck + gear house.
        _add_box(bm, sr, 1, 0, 0, h + 0.03, top * 2 + 0.55, top * 2 + 0.55, 0.06)
        _add_box(bm, sr, 0, 0, 0.02, h + 0.20, 0.30, 0.42, 0.26)
        # Ladder up one leg, seed-gated.
        if rng.random() < 0.7:
            lx = bot * 0.55
            _add_strut(bm, sr, 1, (lx - 0.12, -bot - 0.18, 0.05),
                       (lx - 0.12, -top - 0.18, h - 0.1), 0.035)
            _add_strut(bm, sr, 1, (lx + 0.12, -bot - 0.18, 0.05),
                       (lx + 0.12, -top - 0.18, h - 0.1), 0.035)
            for tt in (0.2, 0.4, 0.6, 0.8):
                y = -bot - 0.18 + (-top - 0.18 - (-bot - 0.18)) * tt
                _add_strut(bm, sr, 1, (lx - 0.12, y, 0.05 + (h - 0.15) * tt),
                           (lx + 0.12, y, 0.05 + (h - 0.15) * tt), 0.03)
        # Fan rotor: hub + n narrow blades + rim, on -Y side of the head.
        hub = Vector((0.0, -0.55, h + 0.30))
        _add_strut(bm, sr, 0, (0.0, -0.05, h + 0.30), hub + Vector((0, -0.06, 0)), 0.09)
        nb = max(8, self.n_blades)
        tips = []
        for i in range(nb):
            a = self.blade_phase + 2 * math.pi * i / nb
            ca, sa = math.cos(a), math.sin(a)
            r0, r1 = self.hub_radius + 0.02, self.blade_length
            p0 = hub + Vector((ca * r0, 0.0, sa * r0))
            p1 = hub + Vector((ca * r1, -0.02, sa * r1))
            _add_strut(bm, sr, 1, p0, p1, self.blade_width, t2=self.blade_thickness)
            tips.append(p1)
        for i in range(nb):
            _add_strut(bm, sr, 0, tips[i], tips[(i + 1) % nb], 0.025)
        # Tail vane: boom + painted fin.
        boom_end = Vector((0.0, 1.35, h + 0.32))
        _add_strut(bm, sr, 0, (0.0, 0.15, h + 0.30), boom_end, 0.05)
        start = _face_count(bm)
        f0 = bm.verts.new((0.0, 0.85, h + 0.18))
        f1 = bm.verts.new((0.0, 1.55, h + 0.05))
        f2 = bm.verts.new((0.0, 1.62, h + 0.62))
        f3 = bm.verts.new((0.0, 0.92, h + 0.55))
        bm.verts.ensure_lookup_table()
        bm.faces.new((f0, f1, f2, f3))
        sr.append((start, _face_count(bm), 3))

    # -- assembly --------------------------------------------------------------

    def _build(self) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        rng = random.Random(int(self.factory_seed) + 90211)

        if self.windmill_archetype == "western_pump":
            self._build_western_pump(bm, sr, rng)
        elif self.windmill_archetype == "stone_mill":
            self._build_stone_mill(bm, sr, rng)
        else:
            self._build_dutch(bm, sr, rng)

        me = bpy.data.meshes.new(f"LowPolyWindmill({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(f"LowPolyWindmill({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)

        while len(obj.data.materials) < 4:
            obj.data.materials.append(None)
        for start, end, slot in sr:
            for i in range(start, end):
                obj.data.polygons[i].material_index = slot
        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(
            obj, [self.tower_color, self.blade_color, self.roof_color,
                  self.sail_color]
        )
        return obj

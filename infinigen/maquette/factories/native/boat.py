"""LowPolyBoatFactory — rowboat / dinghy / fishing skiff / pirate brig.

Top coastal-scene factory per Attempt 13 + Attempt 4 (fishing village).
Without boats, any waterfront scene reads as "village by water" instead
of "fishing harbor" / "pirate cove" / "river crossing".

Forge v2 rebuild: the first pass was a 7-face wedge ("paper hat") with a
single box sail. This version lofts a real hull — stations with a rising
sheer line, hard chine, pointed stem, flat transom — plus a contrasting
gunwale rim, interior floor, and per-archetype rigging.

Archetypes:
  rowboat       — open boat, gunwale rim, 2 thwarts, oars shipped
                  across the gunwales (~2.6m)
  dinghy        — bare small hull; by seed it may lie UPTURNED
                  (keel-up on the beach) (~1.9m)
  fishing_skiff — working boat: mast + boom with a furled lug sail,
                  rudder, foredeck (~3.2m) — the fishing-village hero
  pirate_brig   — two-masted ship: bulwarks, forecastle + quarterdeck,
                  square sails, bowsprit, pennant (~5.5m)

Layout convention: length axis is X (bow at +X, stern at -X). Hull
rests on z=0; the caller sinks it slightly when floating it on water.

Material slots:
  slot 0 = hull planks       (default `wood`)
  slot 1 = spars / oars / interior  (default `rust_metal`)
  slot 2 = sail cloth        (default `stucco`)
  slot 3 = gunwale rim / accent stripe (default `rock_pale`)
"""

from __future__ import annotations

import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_BOAT_ARCHETYPES = ("rowboat", "dinghy", "fishing_skiff", "pirate_brig")


_ARCHETYPE_DEFAULTS = {
    "rowboat": dict(
        length=2.6, width=0.95, height=0.45,
        bow_taper=0.6, stern_taper=0.5,
        n_thwarts=2, has_oars=True, oar_length=1.6,
        has_mast=False, mast_height=0.0,
        has_sail=False, sail_size=(0, 0),
        has_bowsprit=False,
        hull_color="wood", trim_color="rust_metal", sail_color="stucco",
        accent_color="rock_pale",
    ),
    "dinghy": dict(
        length=1.9, width=0.85, height=0.38,
        bow_taper=0.7, stern_taper=0.7,
        n_thwarts=1, has_oars=False, oar_length=0.0,
        has_mast=False, mast_height=0.0,
        has_sail=False, sail_size=(0, 0),
        has_bowsprit=False,
        hull_color="wood", trim_color="rust_metal", sail_color="stucco",
        accent_color="rock_pale",
    ),
    "fishing_skiff": dict(
        length=3.2, width=1.10, height=0.52,
        bow_taper=0.6, stern_taper=0.45,
        n_thwarts=1, has_oars=False, oar_length=0.0,
        has_mast=True, mast_height=2.6,
        has_sail=True, sail_size=(1.6, 0.16),  # furled: along-boom length x roll
        has_bowsprit=False,
        hull_color="wood", trim_color="rust_metal", sail_color="stucco",
        accent_color="rock_pale",
    ),
    "pirate_brig": dict(
        length=5.5, width=1.7, height=0.95,
        bow_taper=0.5, stern_taper=0.55,
        n_thwarts=0, has_oars=False, oar_length=0.0,
        has_mast=True, mast_height=4.2,
        has_sail=True, sail_size=(2.0, 1.3),
        has_bowsprit=True,
        hull_color="wood", trim_color="rust_metal", sail_color="stucco",
        accent_color="accent_red",
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


def _add_strut(bm, sr, slot, p0, p1, thickness: float, *, t2: float | None = None) -> None:
    """Oriented square-section box from p0 to p1 (masts, yards, booms, oars)."""
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


def _add_quad(bm, sr, slot, p0, p1, p2, p3) -> None:
    start = _face_count(bm)
    verts = [bm.verts.new(tuple(p)) for p in (p0, p1, p2, p3)]
    bm.verts.ensure_lookup_table()
    bm.faces.new(verts)
    sr.append((start, _face_count(bm), slot))


class _Hull:
    """Lofted hard-chine hull. Stations run stern -> bow; the bow station
    collapses to a stem line. Exposes the gunwale ring so the rim strip and
    bulwarks can follow the same curve."""

    def __init__(self, length: float, width: float, height: float,
                 bow_taper: float, stern_taper: float):
        L, W, H = length / 2, width / 2, height
        # (x, top_half_width, gunwale_z, chine_half_width, chine_z)
        stern_w = max(0.30, 1.0 - stern_taper * 0.85)
        self.stations = [
            (-L, W * stern_w, H * 1.04, W * stern_w * 0.45, H * 0.30),
            (-L * 0.50, W * 0.96, H * 0.94, W * 0.46, H * 0.12),
            (0.0, W, H * 0.92, W * 0.48, H * 0.10),
            (L * 0.55, W * (1.0 - bow_taper * 0.45), H * 1.02, W * 0.34, H * 0.16),
        ]
        self.bow = (L, H * 1.22, H * 0.52)  # x, stem top z, stem bottom z

    def build(self, bm, sr, slot) -> None:
        start = _face_count(bm)
        rings = []
        for (x, wt, zg, wb, zc) in self.stations:
            gp = bm.verts.new((x, +wt, zg))
            cp = bm.verts.new((x, +wb, zc))
            cs = bm.verts.new((x, -wb, zc))
            gs = bm.verts.new((x, -wt, zg))
            rings.append((gp, cp, cs, gs))
        bx, bzt, bzb = self.bow
        stem_t = bm.verts.new((bx, 0.0, bzt))
        stem_b = bm.verts.new((bx, 0.0, bzb))
        bm.verts.ensure_lookup_table()
        for r0, r1 in zip(rings, rings[1:]):
            bm.faces.new((r0[0], r1[0], r1[1], r0[1]))  # port topside
            bm.faces.new((r0[1], r1[1], r1[2], r0[2]))  # bottom
            bm.faces.new((r0[2], r1[2], r1[3], r0[3]))  # starboard topside
        last = rings[-1]
        bm.faces.new((last[0], stem_t, stem_b, last[1]))   # port bow
        bm.faces.new((last[1], stem_b, last[2]))           # bow bottom tri
        bm.faces.new((last[2], stem_b, stem_t, last[3]))   # starboard bow
        first = rings[0]
        bm.faces.new((first[3], first[2], first[1], first[0]))  # transom
        sr.append((start, _face_count(bm), slot))
        self.rings = rings
        self.stem_top = stem_t

    def gunwale_path(self):
        """[(x, half_width, z), ...] stern -> bow tip for rim/bulwark lofts."""
        pts = [(x, wt, zg) for (x, wt, zg, _, _) in self.stations]
        pts.append((self.bow[0], 0.0, self.bow[1]))
        return pts


def _add_rim(bm, sr, slot, hull: _Hull, *, lift: float = 0.045,
             flare: float = 0.05) -> None:
    """Contrasting cap strip along the gunwale — both sides + transom cap."""
    start = _face_count(bm)
    path = hull.gunwale_path()
    for sign in (1.0, -1.0):
        lo = [bm.verts.new((x, sign * w, z)) for (x, w, z) in path]
        hi = [bm.verts.new((x, sign * (w + flare), z + lift)) for (x, w, z) in path]
        bm.verts.ensure_lookup_table()
        for i in range(len(path) - 1):
            quad = (lo[i], lo[i + 1], hi[i + 1], hi[i]) if sign > 0 else \
                   (hi[i], hi[i + 1], lo[i + 1], lo[i])
            bm.faces.new(quad)
    # transom cap strip
    x0, w0, z0 = path[0]
    a = bm.verts.new((x0, +w0, z0))
    b = bm.verts.new((x0, +w0 + flare, z0 + lift))
    c = bm.verts.new((x0, -w0 - flare, z0 + lift))
    d = bm.verts.new((x0, -w0, z0))
    bm.verts.ensure_lookup_table()
    bm.faces.new((a, b, c, d))
    sr.append((start, _face_count(bm), slot))


class LowPolyBoatFactory(AssetFactory):
    """A boat — rowboat, dinghy, fishing skiff, or pirate brig.

    Constructor knobs:

        factory_seed
        boat_archetype : str = "rowboat"
                         "rowboat" | "dinghy" | "fishing_skiff" | "pirate_brig"
        length, width, height : floats
        bow_taper, stern_taper : float (0..1) — how much the ends pinch
        n_thwarts        : int     cross seats
        has_oars         : bool
        oar_length       : float
        has_mast         : bool
        mast_height      : float
        has_sail         : bool
        sail_size        : (w, h)  square-sail size (brig) / furl size (skiff)
        has_bowsprit     : bool
        hull_color       : str   slot 0
        trim_color       : str   slot 1 (spars, oars, interior)
        sail_color       : str   slot 2
        accent_color     : str   slot 3 (gunwale rim / stern stripe / pennant)
    """

    def __init__(
        self,
        factory_seed,
        boat_archetype: str = "rowboat",
        length: float | None = None,
        width: float | None = None,
        height: float | None = None,
        bow_taper: float | None = None,
        stern_taper: float | None = None,
        n_thwarts: int | None = None,
        has_oars: bool | None = None,
        oar_length: float | None = None,
        has_mast: bool | None = None,
        mast_height: float | None = None,
        has_sail: bool | None = None,
        sail_size: tuple[float, float] | None = None,
        has_bowsprit: bool | None = None,
        hull_color: str | None = None,
        trim_color: str | None = None,
        sail_color: str | None = None,
        accent_color: str | None = None,
        coarse: bool = False,
        **_unused_kwargs,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if _unused_kwargs:
            from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
            accept_unused_kwargs("LowPolyBoatFactory", _unused_kwargs)
        if boat_archetype not in _BOAT_ARCHETYPES:
            # Lenient fallback rather than crash — see factory_kwargs_compat.
            import sys
            print(
                f"[boat_archetype] WARN: unknown boat_archetype "
                f"{boat_archetype!r}; falling back to {_BOAT_ARCHETYPES[0]!r}. "
                f"Valid: {_BOAT_ARCHETYPES}",
                file=sys.stderr,
            )
            boat_archetype = _BOAT_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[boat_archetype]
        self.boat_archetype = boat_archetype
        rng = random.Random(int(factory_seed) + 70993)
        self._rng = rng

        def _dim(value, key, lo=0.92, hi=1.08):
            if value is not None:
                return float(value)
            return float(d[key]) * rng.uniform(lo, hi)

        self.length = _dim(length, "length")
        self.width = _dim(width, "width", 0.94, 1.06)
        self.height = _dim(height, "height", 0.95, 1.05)
        self.bow_taper = float(bow_taper if bow_taper is not None else d["bow_taper"])
        self.stern_taper = float(stern_taper if stern_taper is not None else d["stern_taper"])
        self.n_thwarts = int(n_thwarts if n_thwarts is not None else d["n_thwarts"])
        self.has_oars = bool(has_oars) if has_oars is not None else d["has_oars"]
        self.oar_length = float(oar_length if oar_length is not None else d["oar_length"])
        self.has_mast = bool(has_mast) if has_mast is not None else d["has_mast"]
        self.mast_height = float(mast_height if mast_height is not None else d["mast_height"])
        self.has_sail = bool(has_sail) if has_sail is not None else d["has_sail"]
        ss = sail_size if sail_size is not None else d["sail_size"]
        self.sail_size = (float(ss[0]), float(ss[1]))
        self.has_bowsprit = (
            bool(has_bowsprit) if has_bowsprit is not None else d["has_bowsprit"]
        )
        self.hull_color = hull_color or d["hull_color"]
        self.trim_color = trim_color or d["trim_color"]
        self.sail_color = sail_color or d["sail_color"]
        self.accent_color = accent_color or d["accent_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyBoat({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    # -- shared dressing -------------------------------------------------------

    def _add_floor_and_thwarts(self, bm, sr, hull: _Hull) -> None:
        L, W, H = self.length, self.width, self.height
        _add_box(bm, sr, 1, -L * 0.04, 0, H * 0.13, L * 0.74, W * 0.44, 0.03)
        for i in range(self.n_thwarts):
            u = (i + 1) / (self.n_thwarts + 1)
            x = -L / 2 + L * (0.15 + 0.7 * u)
            _add_box(bm, sr, 1, x, 0, H * 0.72, 0.09, W * 0.78, 0.045)

    def _add_oars(self, bm, sr, rng: random.Random) -> None:
        L, W, H = self.length, self.width, self.height
        for sign in (-1, 1):
            ang = rng.uniform(0.28, 0.45) * sign
            pivot = Vector((-L * 0.08, sign * W * 0.52, H * 0.98))
            d = Vector((math.cos(ang), math.sin(ang), -0.06))
            d.normalize()
            inboard = pivot - d * (self.oar_length * 0.35)
            tip = pivot + d * (self.oar_length * 0.65)
            _add_strut(bm, sr, 1, inboard, tip - d * 0.30, 0.035)
            _add_strut(bm, sr, 1, tip - d * 0.32, tip, 0.10, t2=0.025)

    # -- archetype dressings ---------------------------------------------------

    def _dress_fishing_skiff(self, bm, sr, hull: _Hull, rng: random.Random) -> None:
        L, W, H = self.length, self.width, self.height
        # Foredeck plate.
        _add_quad(bm, sr, 0,
                  (L * 0.20, W * 0.40, H * 0.97),
                  (L * 0.20, -W * 0.40, H * 0.97),
                  (L * 0.48, -W * 0.12, H * 1.06),
                  (L * 0.48, W * 0.12, H * 1.06))
        # Mast just aft of the foredeck.
        mx = L * 0.12
        mtop = Vector((mx, 0, H + self.mast_height))
        _add_strut(bm, sr, 1, (mx, 0, H * 0.2), mtop, 0.07)
        # Boom angled down toward the stern, with a furled sail roll on it.
        boom_len, furl_r = self.sail_size
        boom_end = Vector((mx - boom_len, 0, H + self.mast_height * 0.42 - 0.48))
        boom_start = Vector((mx, 0, H + self.mast_height * 0.42))
        _add_strut(bm, sr, 1, boom_start, boom_end, 0.05)
        if self.has_sail:
            roll0 = boom_start + (boom_end - boom_start) * 0.08
            roll1 = boom_start + (boom_end - boom_start) * 0.97
            _add_strut(bm, sr, 2, roll0, roll1, furl_r * 2.2, t2=furl_r * 1.7)
            # Tie straps over the furl.
            for t in (0.3, 0.7):
                p = roll0.lerp(roll1, t)
                _add_box(bm, sr, 1, p.x, p.y, p.z, 0.05, furl_r * 2.6, furl_r * 2.0)
        # Rudder on the transom.
        x0 = -L / 2
        _add_quad(bm, sr, 1,
                  (x0 - 0.02, 0.03, H * 0.9), (x0 - 0.02, -0.03, H * 0.9),
                  (x0 - 0.30, -0.03, H * 0.15), (x0 - 0.30, 0.03, H * 0.15))
        # A crate of catch amidships, seed-gated.
        if rng.random() < 0.6:
            _add_box(bm, sr, 1, -L * 0.18, W * 0.18, H * 0.40,
                     0.36, 0.30, 0.24)

    def _dress_brig(self, bm, sr, hull: _Hull, rng: random.Random) -> None:
        L, W, H = self.length, self.width, self.height
        # Bulwark band following the gunwale (a second, vertical strip).
        path = hull.gunwale_path()[:-1]  # skip stem point
        start = _face_count(bm)
        bw_h = H * 0.22
        for sign in (1.0, -1.0):
            lo = [bm.verts.new((x, sign * w, z)) for (x, w, z) in path]
            hi = [bm.verts.new((x, sign * w * 0.97, z + bw_h)) for (x, w, z) in path]
            bm.verts.ensure_lookup_table()
            for i in range(len(path) - 1):
                quad = (lo[i], lo[i + 1], hi[i + 1], hi[i]) if sign > 0 else \
                       (hi[i], hi[i + 1], lo[i + 1], lo[i])
                bm.faces.new(quad)
        sr.append((start, _face_count(bm), 0))
        # Accent stripe along the hull side (thin loft just under gunwale).
        start = _face_count(bm)
        for sign in (1.0, -1.0):
            lo = [bm.verts.new((x, sign * (w + 0.015), z - H * 0.16)) for (x, w, z) in path]
            hi = [bm.verts.new((x, sign * (w + 0.015), z - H * 0.05)) for (x, w, z) in path]
            bm.verts.ensure_lookup_table()
            for i in range(len(path) - 1):
                quad = (lo[i], lo[i + 1], hi[i + 1], hi[i]) if sign > 0 else \
                       (hi[i], hi[i + 1], lo[i + 1], lo[i])
                bm.faces.new(quad)
        sr.append((start, _face_count(bm), 3))
        # Quarterdeck (stern) and forecastle (bow) blocks — kept inside the
        # hull beam so they read as decks, not crates.
        _add_box(bm, sr, 0, -L * 0.36, 0, H * 1.12, L * 0.26, W * 0.88, H * 0.42)
        _add_box(bm, sr, 0, L * 0.32, 0, H * 1.06, L * 0.16, W * 0.62, H * 0.28)
        # Two masts with yards + square sails.
        sail_w, sail_h = self.sail_size
        for mi, (mx, mh_scale) in enumerate(((L * 0.16, 1.0), (-L * 0.14, 1.12))):
            mh = self.mast_height * mh_scale
            _add_strut(bm, sr, 1, (mx, 0, H * 0.6), (mx, 0, H + mh), 0.10)
            n_sails = 2
            for si in range(n_sails):
                yz = H + mh * (0.52 + 0.34 * si)
                yw = sail_w * (1.0 - 0.22 * si)
                _add_strut(bm, sr, 1, (mx, -yw * 0.62, yz), (mx, yw * 0.62, yz), 0.05)
                # Sail: slightly billowed quad (bottom corners pulled aft).
                start = _face_count(bm)
                sh = sail_h * (1.0 - 0.18 * si)
                billow = 0.16 + 0.1 * rng.random()
                v0 = bm.verts.new((mx, -yw * 0.55, yz - 0.02))
                v1 = bm.verts.new((mx, yw * 0.55, yz - 0.02))
                v2 = bm.verts.new((mx - billow, yw * 0.48, yz - sh))
                v3 = bm.verts.new((mx - billow, -yw * 0.48, yz - sh))
                bm.verts.ensure_lookup_table()
                bm.faces.new((v0, v1, v2, v3))
                sr.append((start, _face_count(bm), 2))
        # Pennant on the mainmast.
        start = _face_count(bm)
        px = -L * 0.14
        pz = H + self.mast_height * 1.12
        p0 = bm.verts.new((px, 0, pz + 0.16))
        p1 = bm.verts.new((px, 0, pz + 0.02))
        p2 = bm.verts.new((px - 0.55, 0, pz + 0.09))
        bm.verts.ensure_lookup_table()
        bm.faces.new((p0, p1, p2))
        sr.append((start, _face_count(bm), 3))
        # Bowsprit.
        if self.has_bowsprit:
            _add_strut(bm, sr, 1, (L * 0.40, 0, H * 1.10),
                       (L * 0.86, 0, H * 1.62), 0.06)

    # -- assembly --------------------------------------------------------------

    def _build(self) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        rng = random.Random(int(self.factory_seed) + 14431)

        hull = _Hull(self.length, self.width, self.height,
                     self.bow_taper, self.stern_taper)
        hull.build(bm, sr, 0)
        _add_rim(bm, sr, 3, hull)

        upturned = False
        if self.boat_archetype == "dinghy":
            upturned = rng.random() < 0.45
            if not upturned:
                self._add_floor_and_thwarts(bm, sr, hull)
        elif self.boat_archetype == "rowboat":
            self._add_floor_and_thwarts(bm, sr, hull)
            if self.has_oars and self.oar_length > 0:
                self._add_oars(bm, sr, rng)
        elif self.boat_archetype == "fishing_skiff":
            self._add_floor_and_thwarts(bm, sr, hull)
            if self.has_mast and self.mast_height > 0:
                self._dress_fishing_skiff(bm, sr, hull, rng)
        elif self.boat_archetype == "pirate_brig":
            self._dress_brig(bm, sr, hull, rng)

        if upturned:
            # Keel-up on the beach: rotate pi about the X axis, rest on rim.
            zs = [v.co.z for v in bm.verts]
            z_top = max(zs)
            for v in bm.verts:
                v.co.y = -v.co.y
                v.co.z = z_top - v.co.z

        me = bpy.data.meshes.new(f"LowPolyBoat({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(f"LowPolyBoat({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)

        while len(obj.data.materials) < 4:
            obj.data.materials.append(None)
        for start, end, slot in sr:
            for i in range(start, end):
                obj.data.polygons[i].material_index = slot
        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(
            obj, [self.hull_color, self.trim_color, self.sail_color,
                  self.accent_color]
        )
        return obj

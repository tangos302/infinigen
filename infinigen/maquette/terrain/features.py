"""Terrain features — composable shapes that modify a base.

Every feature is a dataclass that, given the terrain extent + a seed,
returns a list of `FeatureSpec`s describing how it composes with the
running terrain SDF. The factory runs them in order; smooth ops at the
boundaries give organic blending so features read as eroded rather than
pasted-in.

Two design principles, baked in across every feature:

  1. **Procedural variation by default.** Every magnitude parameter
     accepts EITHER a scalar (fixed) OR a `(min, max)` tuple (sampled
     uniformly per spawn from the seed). Defaults are tuples — calling
     `Gorge()` on two seeds gives noticeably different ravines without
     any caller intervention. Pass a scalar to lock a specific value.

  2. **List-returning specs.** Some features compose multiple SDFs
     (Canyon = subtractive carve + additive walls). `to_specs` always
     returns a list[FeatureSpec]; single-spec features wrap [spec].

Available features (subtractive: carve out of base; additive: rise above):

  Subtractive: Gorge, Lake, CaveSystem, Canyon (also additive walls), Quarry
  Additive:    MesaCluster, IslandCluster, MountainPeak, Cliff
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Sequence, Union

import numpy as np

from . import sdf as sdf_lib
from .composition import FeatureSpec, HeightFn


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# Type alias for params that accept a fixed value or a uniform-sample range
ScalarOrRange = Union[float, tuple[float, float]]
IntOrRange = Union[int, tuple[int, int]]


def _sample(value, rng: random.Random):
    """If `value` is a (min, max) tuple, sample uniformly; else return as-is."""
    if isinstance(value, tuple) and len(value) == 2:
        a, b = value
        if isinstance(a, int) and isinstance(b, int):
            return rng.randint(a, b)
        return rng.uniform(float(a), float(b))
    return value


def _smoothstep(t: np.ndarray) -> np.ndarray:
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


# ---------------------------------------------------------------------------
# Mesa shape primitives — used by MesaCluster + Canyon walls
# ---------------------------------------------------------------------------


def _build_mesa_sdf(
    style: str,
    cx: float,
    cy: float,
    radius: float,
    height: float,
    rng: random.Random,
):
    """Build one mesa SDF in the chosen style. Returns the SDF for a
    single mesa column, z-centered at z=0 (top at z=height, bottom at
    z=-height; the base ground trims the bottom).

    Three styles, ordered by visual richness:
      "round"     — clean cylinder. Use as occasional accent.
      "natural"   — gently asymmetric outline (multi-harmonic radius).
                    Reads as a slightly-weathered cylinder.
      "weathered" — natural + vertical fluting (erosion channels) +
                    talus skirt at the base (slight outward flare).
                    Default for desert-mesa scenes — closest to what
                    real eroded mesas actually look like.
    """
    h2 = height * 2
    if style == "round":
        return sdf_lib.cylinder(radius=radius, height=h2, center=(cx, cy, 0))
    if style == "natural":
        components = []
        for _ in range(3):
            n = rng.randint(1, 3)
            amp = rng.uniform(0.03, 0.07) * radius
            phase = rng.uniform(0, 2 * math.pi)
            components.append((n, amp, phase))
        shift_theta = rng.uniform(0, 2 * math.pi)
        shift_mag = rng.uniform(0.0, 0.10) * radius
        radial_shift = (
            shift_mag * math.cos(shift_theta),
            shift_mag * math.sin(shift_theta),
        )
        return sdf_lib.cylinder_organic(
            radius=radius, height=h2, center=(cx, cy, 0),
            components=components,
            radial_shift=radial_shift,
        )
    if style == "weathered":
        # Horizontal silhouette — a strong n=1 component (dominant
        # ellipse axis) plus a smaller n=2 component (asymmetric bulge).
        # AVOID n=3+ harmonics — they produce triangular/square outlines
        # that read as geometric, not natural. The combination of n=1
        # and n=2 with random phases gives the "potato silhouette" look.
        # n=1 dominates → "egg" axis. n=2 adds an asymmetric bulge.
        # Amplitudes are a fraction of radius; combined ~25-40% peak-to-peak
        # is enough to read as potato silhouette from top-down without
        # producing geometric outlines. Lower amplitudes (~10%) read as
        # circles at typical 5-10m mesa radii.
        horizontal = [
            (1, rng.uniform(0.18, 0.30) * radius, rng.uniform(0, 2 * math.pi)),
            (2, rng.uniform(0.06, 0.12) * radius, rng.uniform(0, 2 * math.pi)),
        ]
        shift_theta = rng.uniform(0, 2 * math.pi)
        shift_mag = rng.uniform(0.0, 0.08) * radius
        radial_shift = (
            shift_mag * math.cos(shift_theta),
            shift_mag * math.sin(shift_theta),
        )
        # Vertical fluting — 3 components at different (n_theta, n_z).
        fluting = []
        for _ in range(3):
            n_t = rng.randint(8, 16)
            n_z = rng.randint(1, 3)
            amp = rng.uniform(0.015, 0.035) * radius
            phase_t = rng.uniform(0, 2 * math.pi)
            phase_z = rng.uniform(0, 2 * math.pi)
            fluting.append((n_t, n_z, amp, phase_t, phase_z))
        # Talus skirt + subtle top taper.
        base_flare = rng.uniform(0.05, 0.10)
        flare_height_frac = rng.uniform(0.25, 0.40)
        top_taper = rng.uniform(0.0, 0.04)
        # NEW: column tilt — 70% of mesas get a small tilt (0-7% of
        # height = 0-4° lean). 30% stay perfectly upright. Direction
        # uniformly distributed.
        if rng.random() < 0.7:
            column_tilt_amount = rng.uniform(0.02, 0.07)
            column_tilt_direction = rng.uniform(0, 2 * math.pi)
        else:
            column_tilt_amount = 0.0
            column_tilt_direction = 0.0
        # Top slope — linear tilt of the cap, one side a bit higher than
        # the other. Up to ±0.4m drop across the radius keeps it as a
        # subtle "dip" rather than a leaning roof.
        top_slope_amount = rng.uniform(-0.4, 0.4)
        top_slope_direction = rng.uniform(0, 2 * math.pi)
        # Top relief — a SINGLE low-frequency cosine bump (n=1 or n=2).
        # Multiple stacked cosines created radial-ridge patterns that
        # read as star/flower-shaped tops from above. One bump at low
        # amplitude (5-15 cm) just breaks the perfect-flat read without
        # producing visible patterns.
        top_relief = [(
            rng.randint(1, 2),
            rng.uniform(0.05, 0.15),
            rng.uniform(0, 2 * math.pi),
        )]
        return sdf_lib.cylinder_weathered(
            radius=radius, height=h2, center=(cx, cy, 0),
            horizontal_components=horizontal,
            radial_shift=radial_shift,
            base_flare=base_flare,
            flare_height_frac=flare_height_frac * (height / h2),
            fluting_components=fluting,
            top_taper=top_taper,
            column_tilt_amount=column_tilt_amount,
            column_tilt_direction=column_tilt_direction,
            top_slope_amount=top_slope_amount,
            top_slope_direction=top_slope_direction,
            top_relief_components=top_relief,
        )
    raise ValueError(f"unknown mesa style {style!r}")


# Weathered dominates — most natural-looking. `round` rare accent.
# `natural` removed from defaults but still callable.
_MESA_STYLE_DEFAULTS = {"weathered": 9.0, "round": 1.0}


# ---------------------------------------------------------------------------
# Subtractive features — ravines, lakes, caves
# ---------------------------------------------------------------------------


@dataclass
class Gorge:
    """A winding ravine — typically the main "breach" of a canyon scene
    where objects (roads, structures, settlements) are placed.

    The default `half_width` is intentionally wide (4-7 m → 8-14 m floor
    width) so the gorge reads as the central terrain feature rather than
    a slim crack. Pass scalars / smaller ranges to lock specific values.

    `top_clearance` controls how far ABOVE z=0 the carver extends. Set
    high enough to cut through any plateau in the base. Default 30m
    handles `MesaPlateauBase` (plateau heights up to ~25m) cleanly.

    Each waypoint along the gorge path is published as a keep-out
    zone so subsequent features (MesaCluster, etc.) can avoid placing
    objects in the canyon's right-of-way.
    """

    depth: ScalarOrRange = (10.0, 16.0)
    half_width: ScalarOrRange = (6.0, 10.0)
    n_waypoints: IntOrRange = (3, 5)
    lateral_jitter: ScalarOrRange = (6.0, 12.0)
    blend: ScalarOrRange = (1.5, 2.5)
    axis: str = "y"
    top_clearance: float = 30.0
    # Extra padding around the gorge corridor that downstream features
    # are expected to keep mesas clear of. The published keep-out zones
    # have radius `half_width + keep_out_margin`.
    keep_out_margin: ScalarOrRange = (3.0, 5.0)

    def to_specs(self, extent, seed, **_kwargs) -> list[FeatureSpec]:
        sx, sy = extent
        rng = random.Random(seed * 1000 + 1)
        depth = _sample(self.depth, rng)
        half_w = _sample(self.half_width, rng)
        n_pts = max(2, _sample(self.n_waypoints, rng))
        jitter = _sample(self.lateral_jitter, rng)
        blend = _sample(self.blend, rng)
        top_clearance = float(self.top_clearance)
        keep_out_margin = _sample(self.keep_out_margin, rng)

        waypoints: list[tuple[float, float]] = []
        for i in range(n_pts):
            t = i / (n_pts - 1)
            if self.axis == "y":
                main = (t - 0.5) * sy * 0.95
                cross = rng.uniform(-jitter, jitter)
                waypoints.append((cross, main))
            elif self.axis == "x":
                main = (t - 0.5) * sx * 0.95
                cross = rng.uniform(-jitter, jitter)
                waypoints.append((main, cross))
            elif self.axis == "diagonal":
                m = (t - 0.5) * 0.95
                jit = rng.uniform(-jitter, jitter) * 0.5
                waypoints.append((m * sx + jit, m * sy - jit))
            else:
                raise ValueError(f"Gorge.axis must be y|x|diagonal, got {self.axis!r}")

        # Carver active z ∈ [-depth-2, +top_clearance]. Floor closes at
        # z = -depth-2 so marching cubes finds a clean canyon bottom;
        # top extends up to `top_clearance` so the carver also slices
        # through plateau material when the base is `MesaPlateauBase`.
        z_center = (top_clearance - depth) / 2
        z_half_extent = (top_clearance + depth) / 2 + 2
        carver = sdf_lib.line_xy(
            waypoints, radius=half_w,
            z=z_center, z_extent=z_half_extent,
        )
        # Keep-out radius covers the canyon floor + the talus skirt
        # margin. Mesas placed beyond this won't overlap the canyon.
        keep_outs = [(x, y, half_w + keep_out_margin) for x, y in waypoints]
        # Also publish midpoints so a long segment between waypoints
        # also has keep-outs (otherwise mesas can spawn in the middle
        # of a long canyon stretch).
        midpoints = []
        for i in range(len(waypoints) - 1):
            ax, ay = waypoints[i]
            bx, by = waypoints[i + 1]
            midpoints.append((
                (ax + bx) * 0.5,
                (ay + by) * 0.5,
                half_w + keep_out_margin,
            ))
        return [FeatureSpec(
            sdf=carver, op="smooth_subtract", blend=blend,
            keep_out_zones=keep_outs + midpoints,
        )]


@dataclass
class Lake:
    """A circular depression carved out of the terrain. The water
    surface itself lands separately via `LowPolyWaterSurfaceFactory`."""

    center: tuple[float, float] = (0.0, 0.0)
    radius: ScalarOrRange = (8.0, 14.0)
    depth: ScalarOrRange = (3.0, 6.0)
    blend: ScalarOrRange = (1.5, 3.0)

    def to_specs(self, extent, seed, **_kwargs) -> list[FeatureSpec]:
        rng = random.Random(seed * 1000 + 5)
        radius = _sample(self.radius, rng)
        depth = _sample(self.depth, rng)
        blend = _sample(self.blend, rng)
        cx, cy = self.center
        carver = sdf_lib.cylinder(
            radius=radius, height=depth * 2.5, center=(cx, cy, -depth),
        )
        return [FeatureSpec(
            sdf=carver, op="smooth_subtract", blend=blend,
            keep_out_zones=[(cx, cy, radius + 2)],
        )]


@dataclass
class CaveSystem:
    """A chain of overlapping spheres hollowed below the surface — the
    canonical use case for SDF since heightmaps can't do overhangs.
    Mouth(s) are exposed by carving down from the surface."""

    n_chambers: IntOrRange = (3, 5)
    chamber_radius_range: tuple[float, float] = (3.5, 6.0)
    depth: ScalarOrRange = (4.0, 7.0)
    region: tuple[tuple[float, float], tuple[float, float]] = ((-25, 25), (-25, 25))
    blend: ScalarOrRange = (0.8, 1.5)

    def to_specs(self, extent, seed, **_kwargs) -> list[FeatureSpec]:
        rng = random.Random(seed * 1000 + 2)
        n = max(1, _sample(self.n_chambers, rng))
        depth = _sample(self.depth, rng)
        blend = _sample(self.blend, rng)
        spheres: list = []
        keep_outs: list[tuple[float, float, float]] = []
        prev_xy: tuple[float, float] | None = None
        for _ in range(n):
            (xa, xb), (ya, yb) = self.region
            if prev_xy is None:
                cx = rng.uniform(xa, xb)
                cy = rng.uniform(ya, yb)
            else:
                cx = max(xa, min(xb, prev_xy[0] + rng.uniform(-5, 5)))
                cy = max(ya, min(yb, prev_xy[1] + rng.uniform(-5, 5)))
            r = rng.uniform(*self.chamber_radius_range)
            cz = -rng.uniform(depth * 0.5, depth * 1.2)
            spheres.append(sdf_lib.sphere(r, center=(cx, cy, cz)))
            keep_outs.append((cx, cy, r + 1))
            prev_xy = (cx, cy)
        if spheres:
            cx, cy = keep_outs[0][0], keep_outs[0][1]
            mouth = sdf_lib.cylinder(
                radius=self.chamber_radius_range[0] * 0.5,
                height=depth * 4,
                center=(cx, cy, 0),
            )
            spheres.append(mouth)
        carver = sdf_lib.union(*spheres) if spheres else sdf_lib.sphere(0.01)
        return [FeatureSpec(
            sdf=carver, op="smooth_subtract", blend=blend,
            keep_out_zones=keep_outs,
        )]


@dataclass
class Quarry:
    """A terraced cylindrical pit — N stacked rings of decreasing radius
    carved progressively deeper. Reads as a man-made excavation: each
    ring is a wider cylinder above a narrower one, giving the classic
    stepped-quarry silhouette.

    `n_terraces` = number of step rings. `top_radius` = diameter at
    surface. `bottom_radius` = diameter at the deepest level (typically
    half the top). `total_depth` = full pit depth. Each terrace is
    (total_depth / n_terraces) tall.
    """

    center: tuple[float, float] = (0.0, 0.0)
    top_radius: ScalarOrRange = (8.0, 12.0)
    bottom_radius: ScalarOrRange = (3.0, 5.0)
    total_depth: ScalarOrRange = (6.0, 10.0)
    n_terraces: IntOrRange = (3, 5)
    blend: ScalarOrRange = (0.4, 0.9)

    def to_specs(self, extent, seed, **_kwargs) -> list[FeatureSpec]:
        rng = random.Random(seed * 1000 + 6)
        top_r = _sample(self.top_radius, rng)
        bot_r = _sample(self.bottom_radius, rng)
        depth = _sample(self.total_depth, rng)
        n_t = max(1, _sample(self.n_terraces, rng))
        blend = _sample(self.blend, rng)
        cx, cy = self.center

        # Stack of cylinders — each terrace cuts a deeper, narrower hole.
        # Terrace k (0-indexed): radius interpolates top→bottom; cylinder
        # top is at z=0, bottom at z=-(k+1)*step. We use overlapping
        # cylinders: each one is full-height-from-surface so unioning
        # creates the stepped sides naturally.
        cylinders = []
        step = depth / n_t
        for k in range(n_t):
            t = (k + 1) / n_t
            r = top_r * (1 - t) + bot_r * t
            # Each terrace is a cylinder from z=0 down to z=-(k+1)*step
            cyl_h = (k + 1) * step
            cylinders.append(sdf_lib.cylinder(
                radius=r, height=cyl_h * 2,  # ×2 so the top is at z=0
                center=(cx, cy, -cyl_h * 0.5 + cyl_h * 0.5 * 0.0),
            ))
            # Actually cylinder is z-centered, so center.z = -cyl_h/2
            # gives top at z=0 and bottom at z=-cyl_h. Fix:
            cylinders[-1] = sdf_lib.cylinder(
                radius=r, height=cyl_h * 2,
                center=(cx, cy, -cyl_h / 2),
            )

        carver = sdf_lib.union(*cylinders) if cylinders else sdf_lib.sphere(0.01)
        return [FeatureSpec(
            sdf=carver, op="smooth_subtract", blend=blend,
            keep_out_zones=[(cx, cy, top_r + 2)],
        )]


# ---------------------------------------------------------------------------
# Additive features — mesas, peaks, cliffs, islands
# ---------------------------------------------------------------------------


@dataclass
class MesaCluster:
    """N flat-topped mesa columns scattered in the extent.

    Each mesa picks a SHAPE STYLE from `style_weights` per-instance: most
    are `lobed` (eroded radius profile) so the cluster looks natural;
    others get `eroded` (asymmetric multi-cylinder), `round` (clean
    cylinder for accent mesas), or `rounded_square` (boxy variants
    rotated at random).
    """

    n: IntOrRange = (5, 8)
    height_range: tuple[float, float] = (8.0, 18.0)
    radius_range: tuple[float, float] = (4.0, 9.0)
    blend: ScalarOrRange = (2.0, 3.5)
    keep_out_radius: float = 14.0
    # Extra buffer to maintain between mesa edge and any existing
    # keep-out zone (e.g. gorge corridor). Default 1m so mesas don't
    # kiss the gorge edge.
    avoid_buffer: float = 1.0
    # Style weights — `weathered` dominates for natural-mesa look.
    style_weights: dict = field(default_factory=lambda: dict(_MESA_STYLE_DEFAULTS))

    def to_specs(
        self,
        extent,
        seed,
        existing_keep_outs: list[tuple[float, float, float]] | None = None,
        **_kwargs,
    ) -> list[FeatureSpec]:
        sx, sy = extent
        rng = random.Random(seed * 1000 + 3)
        n_target = _sample(self.n, rng)
        blend = _sample(self.blend, rng)
        existing_keep_outs = existing_keep_outs or []

        mesas: list[dict] = []
        attempts = 0
        styles = list(self.style_weights.keys())
        weights = list(self.style_weights.values())
        while len(mesas) < n_target and attempts < n_target * 30:
            attempts += 1
            cx = rng.uniform(-sx * 0.45, sx * 0.45)
            cy = rng.uniform(-sy * 0.45, sy * 0.45)
            new_r = rng.uniform(*self.radius_range)
            # Reject if too close to an upstream keep-out (e.g. gorge).
            in_keep_out = any(
                math.hypot(cx - kx, cy - ky) < (kr + new_r + self.avoid_buffer)
                for kx, ky, kr in existing_keep_outs
            )
            if in_keep_out:
                continue
            too_close = any(
                math.hypot(cx - m["x"], cy - m["y"]) < (m["r"] + new_r * 0.6)
                for m in mesas
            )
            if too_close:
                continue
            mesas.append({
                "x": cx, "y": cy,
                "h": rng.uniform(*self.height_range),
                "r": new_r,
                "style": rng.choices(styles, weights=weights)[0],
            })

        sdfs = [
            _build_mesa_sdf(m["style"], m["x"], m["y"], m["r"], m["h"], rng)
            for m in mesas
        ]
        if not sdfs:
            mesa_sdf: sdf_lib.SDF = lambda p: np.full(p.shape[:-1], 1e6, dtype=np.float32)
        else:
            mesa_sdf = sdf_lib.union(*sdfs)

        def make_height_modifier(prev_h: HeightFn) -> HeightFn:
            def h_with_mesas(x: np.ndarray, y: np.ndarray) -> np.ndarray:
                base_h = prev_h(x, y)
                out = base_h.copy() if hasattr(base_h, "copy") else np.array(base_h)
                for m in mesas:
                    r2 = (x - m["x"]) ** 2 + (y - m["y"]) ** 2
                    d_norm = np.sqrt(r2) / m["r"]
                    mask = _smoothstep(1.0 - (d_norm - 0.7) / 0.5)
                    out = np.maximum(out, base_h + m["h"] * mask)
                return out
            return h_with_mesas

        scatter = [(m["x"], m["y"], m["r"] * 0.5) for m in mesas]  # mesa tops
        return [FeatureSpec(
            sdf=mesa_sdf, op="smooth_union", blend=blend,
            height_modifier=make_height_modifier,
            scatter_zones=scatter,
        )]


def _build_island_sdf(
    style: str,
    cx: float,
    cy: float,
    radius: float,
    height: float,
    rng: random.Random,
    *,
    seed: int = 0,
    warp_amplitude: float = 0.0,
    warp_period: float = 35.0,
):
    """Build one island SDF in the chosen style. Center at (cx, cy, 0)
    with the visible land emerging above z=0 (the waterline).

    Styles:
      "plateau" — flat-topped island, beach-slope rim. The default —
                  reads as walkable land with sandy/grassy edges.
      "dome"    — sphere-cap rounded hill (legacy; still callable).
      "spit"    — flat low sandbar; very wide, low height, elongated.
      "rocky"   — small mesa-ish flat-topped rock outcrop with cliff
                  edges and a talus skirt. Reads as a stone islet.
      "twin"    — two merged plateaus — peninsula / chain feel.
      "ridge"   — long narrow plateau, strong n=1 anisotropy. Reads
                  as a peninsula or volcanic crest.

    `warp_amplitude` > 0 wraps the result with a domain-warp using two
    seeded perlin noises so the silhouette gains low-frequency fractal
    irregularity (fjord-carved coastline). 0 = no warp.
    """
    base_sdf: sdf_lib.SDF
    if style == "spit":
        # Flat low sandbar — strong n=1 (elongated axis), low height,
        # gentle plateau (sandy beach grade).
        horizontal = [
            (1, rng.uniform(0.35, 0.55) * radius, rng.uniform(0, 2 * math.pi)),
            (2, rng.uniform(0.08, 0.15) * radius, rng.uniform(0, 2 * math.pi)),
        ]
        base_sdf = sdf_lib.island_plateau(
            radius=radius, height=height * 0.45,
            center=(cx, cy, 0.0),
            plateau_frac=0.55,
            transition_softness=1.4,
            horizontal_components=horizontal,
        )
    elif style == "rocky":
        # Cliff-edged stone islet — sharp transition, talus skirt via
        # weathered-cylinder primitive.
        horizontal = [
            (1, rng.uniform(0.12, 0.22) * radius, rng.uniform(0, 2 * math.pi)),
            (2, rng.uniform(0.05, 0.10) * radius, rng.uniform(0, 2 * math.pi)),
        ]
        fluting = [
            (rng.randint(6, 12), rng.randint(1, 2),
             rng.uniform(0.02, 0.05) * radius,
             rng.uniform(0, 2 * math.pi),
             rng.uniform(0, 2 * math.pi))
            for _ in range(2)
        ]
        h2 = max(height * 2, 1.0)
        base_sdf = sdf_lib.cylinder_weathered(
            radius=radius, height=h2, center=(cx, cy, height - h2 / 2),
            horizontal_components=horizontal,
            base_flare=rng.uniform(0.10, 0.18),
            flare_height_frac=rng.uniform(0.30, 0.45),
            fluting_components=fluting,
            top_taper=rng.uniform(0.0, 0.05),
            top_relief_components=[(
                rng.randint(1, 2),
                rng.uniform(0.05, 0.15),
                rng.uniform(0, 2 * math.pi),
            )],
        )
    elif style == "twin":
        # Two overlapping plateaus — peninsula / dumbbell shape.
        offset_theta = rng.uniform(0, 2 * math.pi)
        offset_mag = rng.uniform(0.55, 0.85) * radius
        ox = offset_mag * math.cos(offset_theta) * 0.5
        oy = offset_mag * math.sin(offset_theta) * 0.5
        h1 = rng.uniform(0.85, 1.0) * height
        h_b = rng.uniform(0.7, 0.95) * height
        r1 = rng.uniform(0.85, 1.0) * radius
        r2 = rng.uniform(0.65, 0.85) * radius
        d1 = sdf_lib.island_plateau(
            radius=r1, height=h1, center=(cx + ox, cy + oy, 0.0),
            plateau_frac=0.55, transition_softness=1.7,
            horizontal_components=[
                (1, rng.uniform(0.15, 0.28) * r1, rng.uniform(0, 2 * math.pi)),
                (2, rng.uniform(0.06, 0.12) * r1, rng.uniform(0, 2 * math.pi)),
            ],
        )
        d2 = sdf_lib.island_plateau(
            radius=r2, height=h_b, center=(cx - ox, cy - oy, 0.0),
            plateau_frac=0.55, transition_softness=1.7,
            horizontal_components=[
                (1, rng.uniform(0.15, 0.28) * r2, rng.uniform(0, 2 * math.pi)),
                (2, rng.uniform(0.06, 0.12) * r2, rng.uniform(0, 2 * math.pi)),
            ],
        )
        base_sdf = sdf_lib.smooth_union(rng.uniform(1.5, 3.0), d1, d2)
    elif style == "ridge":
        # Long narrow plateau — peninsula / island ridge. Built as a
        # capsule-shaped plateau height-field with a drop-band past
        # the rim (same construction as island_plateau, but distance
        # is measured from a 1D spine segment instead of a point).
        spine_theta = rng.uniform(0, 2 * math.pi)
        length = radius * rng.uniform(1.5, 2.0)
        width = radius * rng.uniform(0.40, 0.55)
        ax = length * 0.5 * math.cos(spine_theta)
        ay = length * 0.5 * math.sin(spine_theta)
        h_eff = float(height)
        plateau_w = width * rng.uniform(0.50, 0.65)
        transition = max(width - plateau_w, 0.5)
        drop_band = max(transition * 1.2, 1.5)
        drop_depth = 80.0
        ax_arr = np.array([cx - ax, cy - ay], dtype=np.float32)
        bx_arr = np.array([cx + ax, cy + ay], dtype=np.float32)
        ab = bx_arr - ax_arr
        ab_len2 = float(np.dot(ab, ab)) + 1e-8
        cz = 0.0

        def ridge_sdf(p, ax_arr=ax_arr, ab=ab, ab_len2=ab_len2,
                      width=float(width), transition=float(transition),
                      drop_band=float(drop_band), drop_depth=drop_depth,
                      h_eff=h_eff, cz=cz):
            x = p[..., 0]
            y = p[..., 1]
            z = p[..., 2]
            px = (x - ax_arr[0]).astype(np.float32)
            py = (y - ax_arr[1]).astype(np.float32)
            t = np.clip(
                (px * ab[0] + py * ab[1]) / np.float32(ab_len2),
                0.0, 1.0,
            ).astype(np.float32)
            qx = px - t * np.float32(ab[0])
            qy = py - t * np.float32(ab[1])
            d_xy = np.sqrt(qx * qx + qy * qy + 1e-8).astype(np.float32)
            plateau_t = np.clip((width - d_xy) / max(transition, 0.5), 0.0, 1.0).astype(np.float32)
            plateau_t = (plateau_t * plateau_t * (3.0 - 2.0 * plateau_t)).astype(np.float32)
            drop_t = np.clip((d_xy - width) / np.float32(drop_band), 0.0, 1.0).astype(np.float32)
            drop_t = (drop_t * drop_t * (3.0 - 2.0 * drop_t)).astype(np.float32)
            surface_z = (cz + h_eff * plateau_t - drop_depth * drop_t).astype(np.float32)
            return (z - surface_z).astype(np.float32)

        base_sdf = ridge_sdf
    elif style == "dome":
        # Legacy sphere-cap dome (kept for variety / backwards compat).
        horizontal = [
            (1, rng.uniform(0.18, 0.32) * radius, rng.uniform(0, 2 * math.pi)),
            (2, rng.uniform(0.06, 0.14) * radius, rng.uniform(0, 2 * math.pi)),
        ]
        shift_theta = rng.uniform(0, 2 * math.pi)
        shift_mag = rng.uniform(0.0, 0.08) * radius
        radial_shift = (
            shift_mag * math.cos(shift_theta),
            shift_mag * math.sin(shift_theta),
        )
        base_sdf = sdf_lib.island_dome(
            radius=radius, height=height, center=(cx, cy, 0.0),
            horizontal_components=horizontal,
            radial_shift=radial_shift,
        )
    else:
        # default = "plateau" — flat-topped potato island.
        horizontal = [
            (1, rng.uniform(0.18, 0.32) * radius, rng.uniform(0, 2 * math.pi)),
            (2, rng.uniform(0.06, 0.14) * radius, rng.uniform(0, 2 * math.pi)),
        ]
        shift_theta = rng.uniform(0, 2 * math.pi)
        shift_mag = rng.uniform(0.0, 0.06) * radius
        radial_shift = (
            shift_mag * math.cos(shift_theta),
            shift_mag * math.sin(shift_theta),
        )
        base_sdf = sdf_lib.island_plateau(
            radius=radius, height=height,
            center=(cx, cy, 0.0),
            # Wider beach-grade rim (transition 1.6-2.2x base) so
            # marching cubes doesn't alias the steep drop into
            # gear-tooth facets. Lower plateau_frac = bigger sloped
            # band, more "real" looking shoreline.
            plateau_frac=rng.uniform(0.45, 0.60),
            transition_softness=rng.uniform(1.6, 2.2),
            horizontal_components=horizontal,
            radial_shift=radial_shift,
        )

    if warp_amplitude > 0.0:
        # `perlin_2d` always uses a 64x64 grid regardless of period →
        # cell spacing of ~period/64m, which is high-frequency content
        # that aliases against the marching-cubes voxel grid and
        # produces gear-tooth rim fringes. `low_freq_noise_2d` ties
        # cell spacing directly to feature_scale/grid_size — at
        # grid_size=8, period=80m gives 10m cells = genuine
        # low-frequency noise = clean fjord coastlines.
        nx = sdf_lib.low_freq_noise_2d(
            seed=seed * 31 + 11, feature_scale=warp_period,
            amplitude=1.0, grid_size=8,
        )
        ny = sdf_lib.low_freq_noise_2d(
            seed=seed * 31 + 73, feature_scale=warp_period,
            amplitude=1.0, grid_size=8,
        )
        return sdf_lib.warp_xy(
            base_sdf, noise_x=nx, noise_y=ny, amplitude=warp_amplitude,
        )
    return base_sdf


# Default mix favors plateaus + organic shapes. Adjust per-scene via
# `style_weights` (e.g. all rocky for stone-stack archipelagos).
_ISLAND_STYLE_DEFAULTS = {
    "plateau": 4.0,
    "rocky": 2.0,
    "spit": 2.0,
    "twin": 1.5,
    "ridge": 1.5,
}


@dataclass
class IslandCluster:
    """N varied-shape islands rising from the water.

    Islands spawn over the FULL terrain extent (rectangular sampling
    with a small margin), not a sub-radius — pair with `EmptyBase`
    and a translucent water box for the canonical archipelago scene.

    Default style mix favours flat-topped plateau islands (most
    natural / walkable) plus a sprinkle of cliff/rocky, low sandy
    spits, twin peninsulas, and long ridges. Pass `style_weights` to
    bias.

    `warp_amplitude` (default 0.30 of mean radius) wraps each island
    silhouette in a low-frequency domain warp (research item
    `island_techniques` #2) so coastlines read as fractal/fjorded
    rather than smooth ovals. Set to 0 to disable.

    `edge_margin` is the inset from the extent boundary (so islands
    don't get clipped by the extent walls when marching cubes runs).
    """

    n: IntOrRange = (3, 6)
    # Bigger islands — at 80m extent these reach proper land-mass scale.
    height_range: tuple[float, float] = (3.0, 6.0)
    radius_range: tuple[float, float] = (16.0, 32.0)
    blend: ScalarOrRange = (1.5, 2.5)
    keep_out_radius: float = 6.0
    edge_margin: float = 6.0
    style_weights: dict[str, float] | None = None
    # Domain-warp amplitude as a fraction of each island's radius, and
    # period in meters. The combination matters: LOW frequency (period
    # >> radius) + MODEST amplitude (15-25% of radius) produces a few
    # big bays/headlands per island — fjord-carved coastline. High
    # frequency at any amplitude produces "cookie crumb" rim noise.
    warp_amplitude: ScalarOrRange = (0.15, 0.25)
    warp_period: ScalarOrRange = (70.0, 100.0)

    def to_specs(self, extent, seed, **_kwargs) -> list[FeatureSpec]:
        rng = random.Random(seed * 1000 + 4)
        n_target = _sample(self.n, rng)
        blend = _sample(self.blend, rng)
        warp_amp_frac = _sample(self.warp_amplitude, rng)
        warp_period = _sample(self.warp_period, rng)
        weights = self.style_weights or _ISLAND_STYLE_DEFAULTS
        style_names = list(weights.keys())
        style_probs = list(weights.values())
        sx, sy = extent

        # Stratified-grid spawning with peripheral bias.
        #
        # Divide the extent into a grid of cells, then visit them in an
        # order that PREFERS edges and corners first — random uniform
        # shuffling tends to leave the corners empty because central
        # cells are equally likely to be picked, but humans read the
        # map as "empty corners" if any cell is left out. Distance
        # from the map center, descending, gets the corner cells
        # placed first; remaining cells fill in toward the middle.
        #
        # Use a slightly oversized grid (~1.4×n) so the user gets one
        # island per cell with empty cells acting as ocean breaks.
        grid_n = max(2, int(math.ceil(math.sqrt(n_target * 1.4))))
        cell_w = sx / grid_n
        cell_h = sy / grid_n
        cells = [(i, j) for i in range(grid_n) for j in range(grid_n)]

        def _cell_priority(cell):
            i, j = cell
            cx_norm = (i + 0.5) / grid_n - 0.5
            cy_norm = (j + 0.5) / grid_n - 0.5
            # Negate so larger distance => smaller priority value =>
            # picked first when sorted ascending.
            return -(cx_norm * cx_norm + cy_norm * cy_norm) + rng.uniform(0, 0.02)

        cells.sort(key=_cell_priority)

        islands: list[dict] = []
        for (gi, gj) in cells:
            if len(islands) >= n_target:
                break
            new_r = rng.uniform(*self.radius_range)
            cell_cx = -sx / 2 + (gi + 0.5) * cell_w
            cell_cy = -sy / 2 + (gj + 0.5) * cell_h
            # Jitter within the cell. Allow generous in-cell drift —
            # islands can poke a little into neighboring cells, giving
            # the spread a less-grid-y look.
            jitter_x = cell_w * 0.55
            jitter_y = cell_h * 0.55
            cx = cell_cx + rng.uniform(-jitter_x, jitter_x)
            cy = cell_cy + rng.uniform(-jitter_y, jitter_y)
            # Clamp to extent (with margin); a big island in a small map
            # can otherwise drift out.
            margin = self.edge_margin + new_r
            cx = float(np.clip(cx, -sx / 2 + margin, sx / 2 - margin))
            cy = float(np.clip(cy, -sy / 2 + margin, sy / 2 - margin))
            # Reject when centers are closer than r₁+r₂ + keep_out —
            # i.e. islands stay distinct with a clear water gap. The
            # "twin" style provides intentional overlap when wanted.
            too_close = any(
                math.hypot(cx - i["x"], cy - i["y"])
                < (i["r"] + new_r) + self.keep_out_radius
                for i in islands
            )
            if too_close:
                continue
            islands.append({
                "x": cx, "y": cy,
                "h": rng.uniform(*self.height_range),
                "r": new_r,
                "style": rng.choices(style_names, weights=style_probs)[0],
            })

        sdfs = [
            _build_island_sdf(
                i["style"], i["x"], i["y"], i["r"], i["h"], rng,
                seed=seed + idx,
                warp_amplitude=warp_amp_frac * i["r"],
                warp_period=warp_period,
            )
            for idx, i in enumerate(islands)
        ]
        if not sdfs:
            island_sdf: sdf_lib.SDF = lambda p: np.full(p.shape[:-1], 1e6, dtype=np.float32)
        else:
            island_sdf = sdf_lib.union(*sdfs)

        def make_h(prev_h: HeightFn) -> HeightFn:
            def h_with_islands(x: np.ndarray, y: np.ndarray) -> np.ndarray:
                base_h = prev_h(x, y)
                out = base_h.copy() if hasattr(base_h, "copy") else np.array(base_h)
                for i in islands:
                    r2 = (x - i["x"]) ** 2 + (y - i["y"]) ** 2
                    d_norm = np.sqrt(r2) / i["r"]
                    mask = _smoothstep(1.0 - d_norm)
                    h_eff = i["h"] * (0.45 if i["style"] == "spit" else 1.0)
                    out = np.maximum(out, base_h + h_eff * mask)
                return out
            return h_with_islands

        scatter = [(i["x"], i["y"], i["r"] * 0.7) for i in islands]
        return [FeatureSpec(
            sdf=island_sdf, op="smooth_union", blend=blend,
            height_modifier=make_h,
            scatter_zones=scatter,
        )]


def _faceted_peak_sdf(
    cx: float, cy: float, h_total: float, base_r: float,
    *,
    n_facets: int = 8,
    tilt_min: float = 55.0,
    tilt_max: float = 70.0,
    apex_lateral_jitter: float = 0.20,
    apex_vertical_jitter: float = 0.15,
    rng: random.Random | None = None,
):
    """A faceted alpine peak built as the intersection of `n_facets`
    tilted half-planes — each plane IS a facet, every edge between
    adjacent planes is a mathematically sharp ridge. Marching cubes +
    planar decimate preserves these almost losslessly.

    Construction (per `project_faceted_peak_recipe`):
      - Azimuths sampled at golden-angle increments (137.5°) for
        natural-looking irregular spacing — pure uniform reads as
        rotational symmetry / "procedural pinwheel".
      - Tilts in [tilt_min, tilt_max]° from horizontal; varied per
        plane so adjacent slabs meet at non-uniform ridge angles.
      - Per-plane apex offsets (lateral + vertical) break the perfect
        cone apex into a small jagged crown — Matterhorn / Eiger
        silhouette.

    The SDF is `max_i (dot(p - anchor_i, n_i))` for the upper facets,
    clipped from below by the ground (`z`). Returned SDF is well-
    behaved as a vertical-distance proxy near the iso-surface — does
    NOT compute Euclidean distance globally, but iso-surface position
    is correct.
    """
    if rng is None:
        rng = random.Random()
    apex_x = float(cx)
    apex_y = float(cy)
    apex_z = float(h_total)
    base_r_f = float(base_r)
    h_f = float(h_total)
    far_below = -500.0

    # Build planes: each plane is defined by an azimuth, tilt, and
    # an apex anchor offset. Plane equation: dot(p - anchor, n) = 0,
    # where n points OUTWARD from the peak interior.
    GOLDEN_ANGLE = math.pi * (3.0 - math.sqrt(5.0))  # ~137.5° in radians
    az0 = rng.uniform(0.0, 2.0 * math.pi)
    planes = []
    for i in range(n_facets):
        az = (az0 + i * GOLDEN_ANGLE) % (2.0 * math.pi)
        tilt = rng.uniform(tilt_min, tilt_max)
        # Tilt is angle of FACE (slope). The outward normal is tilted
        # back from horizontal by (90 - tilt)°. So normal makes angle
        # (90 - tilt)° with horizontal, projected on (cos az, sin az)
        # in the radial direction, with positive Z.
        face_slope_rad = math.radians(tilt)
        nz = math.cos(face_slope_rad)  # ~0.34-0.57
        n_horizontal = math.sin(face_slope_rad)  # ~0.82-0.94
        nx = n_horizontal * math.cos(az)
        ny = n_horizontal * math.sin(az)
        # Per-plane apex jitter
        lat_mag = rng.uniform(0.0, apex_lateral_jitter * base_r_f)
        lat_az = rng.uniform(0.0, 2.0 * math.pi)
        ax = apex_x + lat_mag * math.cos(lat_az)
        ay = apex_y + lat_mag * math.sin(lat_az)
        az_z = apex_z + rng.uniform(-apex_vertical_jitter * h_f,
                                    apex_vertical_jitter * h_f)
        # Pre-compute the constant term so SDF is just nx*x + ny*y + nz*z + c
        c = -(nx * ax + ny * ay + nz * az_z)
        planes.append((float(nx), float(ny), float(nz), float(c)))

    # XY footprint check: outside base_r * some_factor, "no surface".
    # We use a soft outer cylinder cutoff so the peak doesn't extend
    # infinitely along all the half-spaces.
    cutoff_r = base_r_f * 1.05

    def f(p):
        x = p[..., 0]
        y = p[..., 1]
        z = p[..., 2]
        dx = x - np.float32(apex_x)
        dy = y - np.float32(apex_y)
        r_xy = np.sqrt(dx * dx + dy * dy + 1e-8).astype(np.float32)
        # Half-space intersection: SDF = max over all planes of
        # nx*x + ny*y + nz*z + c. Negative inside the convex peak
        # region, positive outside any plane.
        intersection = np.full_like(x, -1e9, dtype=np.float32)
        for nx, ny, nz, c in planes:
            val = (np.float32(nx) * x + np.float32(ny) * y + np.float32(nz) * z + np.float32(c)).astype(np.float32)
            intersection = np.maximum(intersection, val)
        # Outer cutoff — outside the cylinder radius, surface drops to
        # far_below so the peak silhouette terminates at the apron.
        outside_mask = r_xy > cutoff_r
        return np.where(
            outside_mask,
            np.float32(1e3) + r_xy - cutoff_r,
            intersection,
        ).astype(np.float32)

    return f


def _ridged_cone_sdf(
    cx: float, cy: float, h_total: float, base_r: float,
    *,
    tip_frac: float = 0.06,
    taper: float = 0.90,
    ridge_amp: float = 0.25,
    ridge_freq: float = 1.0,
    ridge_octaves: int = 1,
    ridge_persistence: float = 0.20,
    apex_sharp: float = 0.7,
    seed: int = 0,
):
    """Build the SDF of a single ridged cone (cone profile + Musgrave
    `1 - |noise|` ridges in cylindrical theta-h space). Used as the
    building block for `MountainPeak` — a peak is composed of a main
    ridged cone + sub-summit cones + thin spike cones + flat ledge
    cylinders, all smooth-unioned.
    """
    far_below = -500.0
    ridge_grids = []
    for o in range(ridge_octaves):
        ridge_grids.append(sdf_lib.low_freq_noise_2d(
            seed=seed + 7 * o, feature_scale=1.0, amplitude=1.0, grid_size=5,
        ))
    theta_warp = sdf_lib.low_freq_noise_2d(
        seed=seed + 999, feature_scale=1.0, amplitude=1.0, grid_size=8,
    )
    base_r_f = float(base_r)
    cx_f = float(cx)
    cy_f = float(cy)
    h_f = float(h_total)
    taper_f = float(taper)
    tip_frac_f = float(tip_frac)
    ridge_amp_f = float(ridge_amp)
    ridge_freq_f = float(ridge_freq)
    apex_sharp_f = float(apex_sharp)
    persistence = float(ridge_persistence)

    def f(p):
        x = p[..., 0]
        y = p[..., 1]
        z = p[..., 2]
        dx = (x - cx_f).astype(np.float32)
        dy = (y - cy_f).astype(np.float32)
        r_xy = np.sqrt(dx * dx + dy * dy + 1e-8).astype(np.float32)
        theta = np.arctan2(dy, dx).astype(np.float32)
        theta_norm = (theta / np.float32(2.0 * np.pi)) % 1.0
        cone_ratio_pre = np.clip(
            (base_r_f - r_xy) / max(base_r_f * taper_f, 0.001),
            0.0, 1.0,
        )
        h_norm = cone_ratio_pre.astype(np.float32)
        theta_warp_amount = theta_warp(theta_norm * 1.0, h_norm * 1.0)
        theta_warped = (theta_norm + np.float32(0.06) * theta_warp_amount) % 1.0
        ridge_value = np.zeros_like(theta_norm, dtype=np.float32)
        ridge_weight_sum = np.float32(0.0)
        weight = np.float32(1.0)
        freq = np.float32(ridge_freq_f)
        for grid_fn in ridge_grids:
            n = grid_fn(theta_warped * freq, h_norm * freq * 0.4)
            ridge_value = ridge_value + weight * (np.float32(1.0) - np.abs(n))
            ridge_weight_sum = ridge_weight_sum + weight
            weight = weight * np.float32(persistence)
            freq = freq * np.float32(2.5)
        ridge_value = ridge_value / ridge_weight_sum
        amp_at_h = np.float32(ridge_amp_f) * np.power(
            1.0 - h_norm, np.float32(apex_sharp_f)
        ).astype(np.float32)
        r_eff_base = base_r_f * (1.0 - amp_at_h * ridge_value)
        denom = np.maximum(r_eff_base * np.float32(taper_f), 0.001)
        ratio = np.clip((r_eff_base - r_xy) / denom, 0.0, 1.0)
        cap = 1.0 - np.float32(tip_frac_f)
        tip_band = np.float32(tip_frac_f)
        in_tip = ratio > cap
        tip_t = np.clip((ratio - cap) / np.maximum(tip_band, 0.001), 0.0, 1.0)
        tip_t_smooth = tip_t * tip_t * (3.0 - 2.0 * tip_t)
        ratio_eff = np.where(in_tip, cap + tip_band * tip_t_smooth, ratio).astype(np.float32)
        surface_z = np.where(
            r_xy < r_eff_base,
            h_f * ratio_eff,
            np.float32(far_below),
        ).astype(np.float32)
        return (z - surface_z).astype(np.float32)
    return f


def _ledge_disk_sdf(cx: float, cy: float, top_z: float, radius: float, rim_band: float = 1.5):
    """A small flat-topped disk used as a "walkable plateau" appendage
    on the side of a peak. Height-field SDF — surface at top_z within
    the disk, smoothly drops to far_below outside.
    """
    far_below = -500.0
    cx_f, cy_f, top_zf, r_f, rim_f = float(cx), float(cy), float(top_z), float(radius), float(rim_band)

    def f(p):
        x = p[..., 0]
        y = p[..., 1]
        z = p[..., 2]
        dx = (x - cx_f).astype(np.float32)
        dy = (y - cy_f).astype(np.float32)
        r_xy = np.sqrt(dx * dx + dy * dy + 1e-8).astype(np.float32)
        # Inside the disk (r_xy < r_f): surface at top_z.
        # Smooth drop band: r_f to r_f + rim_f, surface from top_z to far_below.
        plateau_t = np.clip((r_f - r_xy) / max(rim_f, 0.5), 0.0, 1.0).astype(np.float32)
        plateau_t = (plateau_t * plateau_t * (3.0 - 2.0 * plateau_t)).astype(np.float32)
        drop_t = np.clip((r_xy - r_f) / max(rim_f, 0.5), 0.0, 1.0).astype(np.float32)
        drop_t = (drop_t * drop_t * (3.0 - 2.0 * drop_t)).astype(np.float32)
        surface_z = (
            np.float32(top_zf) * plateau_t
            + np.float32(far_below) * drop_t
        ).astype(np.float32)
        return (z - surface_z).astype(np.float32)
    return f


@dataclass
class MountainPeak:
    """A composite alpine peak — main summit + sub-summits + thin
    rocky spike outcrops + small walkable ledge plateaus, all
    smooth-unioned. Each cone uses Musgrave ridged noise (theta-h
    space) for faceted spine ridges. The composition gives the
    multi-spire silhouette real mountains have (Matterhorn /
    Mont Blanc / Mt. Cook style).

    Per user direction (2026-04-29 — "they should not just be cones,
    they should be composed of several sub peaks, rocky spikes, and
    even some walkable small plateau area around it").

    Tuning knobs:
      `n_sub_summits` — 1-3 secondary lower summits offset around main
      `n_spikes`      — 2-4 thin tall spikes scattered on upper slopes
      `n_ledges`      — 1-2 walkable flat plateaus at intermediate z
      The cone-shape knobs (tip_frac, cone_taper, ridge_*, apex_sharp)
      apply to the main summit; sub-summits inherit a randomised version.
    """

    center: tuple[float, float] = (0.0, 0.0)
    height: ScalarOrRange = (20.0, 30.0)
    base_radius: ScalarOrRange = (12.0, 18.0)
    tip_frac: ScalarOrRange = (0.04, 0.10)
    cone_taper: ScalarOrRange = (0.85, 0.95)
    # Default to FEW, BIG ridges (not many small spikes) — that's what
    # reads as rocky alpine peak. Ridge_freq=2 gives ~4-5 main spines
    # per face; octaves=2 adds a single secondary detail band. Higher
    # numbers produce "crumpled cauliflower" under marching-cubes /
    # decimate.
    ridge_amplitude: ScalarOrRange = (0.22, 0.32)
    # 2 octaves: dominant ~5-spine silhouette + a secondary detail
    # band that breaks the smooth slabs between ridges into small
    # rocky irregularities (per user direction 2026-04-29 — "rocky
    # irregularities like actual mountains").
    ridge_octaves: int = 2
    ridge_freq: ScalarOrRange = (0.9, 1.2)
    # Persistence drops second octave's contribution — keep it subtle
    # so we don't slip back into the v9-v11 cauliflower territory.
    # 0.20 gives just enough rocky variation to read as "actual
    # mountain" without flooding the slope-snow shader with steep
    # micro-facets.
    ridge_persistence: float = 0.20
    apex_sharpness: ScalarOrRange = (0.65, 0.85)
    blend: ScalarOrRange = (1.5, 3.0)
    n_sub_summits: IntOrRange = (1, 3)
    n_spikes: IntOrRange = (2, 4)
    n_ledges: IntOrRange = (1, 2)

    def to_specs(self, extent, seed, **_kwargs) -> list[FeatureSpec]:
        rng = random.Random(seed * 1000 + 7)
        h = _sample(self.height, rng)
        base_r = _sample(self.base_radius, rng)
        tip_frac = _sample(self.tip_frac, rng)
        taper = _sample(self.cone_taper, rng)
        ridge_amp = _sample(self.ridge_amplitude, rng)
        ridge_freq = _sample(self.ridge_freq, rng)
        apex_sharp = _sample(self.apex_sharpness, rng)
        blend = _sample(self.blend, rng)
        n_subs = _sample(self.n_sub_summits, rng)
        n_spikes = _sample(self.n_spikes, rng)
        n_ledges = _sample(self.n_ledges, rng)
        cx, cy = self.center

        components = []
        # Component construction follows the research recipe in
        # `project_faceted_peak_recipe` — multi-summit composition with
        # power-law height hierarchy, faceted half-plane shells for the
        # primary summit shape, and walkable disk ledges as terraces.
        #
        # The faceted SDF is the primary architecture (planar shells
        # survive marching-cubes + planar-decimate cleanly as sharp
        # ridges); ridged-noise cones are kept only for the small
        # spike outcrops where their organic look helps.

        # 1. Main faceted summit at h=1.0. Tight vertical jitter so
        # the planes converge near the apex instead of capping the
        # peak at the lowest plane's anchor.
        components.append(_faceted_peak_sdf(
            cx, cy, h, base_r,
            n_facets=8,
            tilt_min=62.0, tilt_max=76.0,
            apex_lateral_jitter=0.10,
            apex_vertical_jitter=0.04,
            rng=random.Random(seed * 31 + 100),
        ))

        # 2. Sub-summits at h=0.78-0.88 of main, placed 0.45-0.65 of
        # base_r away — close enough to share the base block.
        for i in range(n_subs):
            ang = rng.uniform(0, 2 * math.pi)
            mag = rng.uniform(0.45, 0.65) * base_r
            sub_cx = cx + mag * math.cos(ang)
            sub_cy = cy + mag * math.sin(ang)
            sub_h = h * rng.uniform(0.78, 0.88)
            sub_r = base_r * rng.uniform(0.45, 0.65)
            components.append(_faceted_peak_sdf(
                sub_cx, sub_cy, sub_h, sub_r,
                n_facets=rng.randint(6, 8),
                tilt_min=58.0, tilt_max=72.0,
                apex_lateral_jitter=0.10,
                apex_vertical_jitter=0.05,
                rng=random.Random(seed * 31 + 200 + i),
            ))

        # 3. Spires/shoulders at h=0.45-0.65 — tall narrow rocky
        # outcrops on the upper slopes. Use FACETED half-plane spikes
        # (no ridged noise) — research recipe warns that noise on cones
        # produces jitter that fights planar decimate, collapsing into
        # vertical fluting on the cliff faces.
        for i in range(n_spikes):
            ang = rng.uniform(0, 2 * math.pi)
            mag = rng.uniform(0.30, 0.55) * base_r
            spike_cx = cx + mag * math.cos(ang)
            spike_cy = cy + mag * math.sin(ang)
            spike_h = h * rng.uniform(0.45, 0.65)
            spike_r = base_r * rng.uniform(0.08, 0.16)
            components.append(_faceted_peak_sdf(
                spike_cx, spike_cy, spike_h, spike_r,
                n_facets=rng.randint(5, 7),
                tilt_min=68.0, tilt_max=82.0,
                apex_lateral_jitter=0.05,
                apex_vertical_jitter=0.04,
                rng=random.Random(seed * 31 + 300 + i),
            ))

        # 4. Walkable ledge plateaus — small flat-topped disks at
        # intermediate heights on the side of the main cone.
        for i in range(n_ledges):
            ang = rng.uniform(0, 2 * math.pi)
            mag = rng.uniform(0.60, 0.85) * base_r
            ledge_cx = cx + mag * math.cos(ang)
            ledge_cy = cy + mag * math.sin(ang)
            ledge_top = h * rng.uniform(0.30, 0.55)
            ledge_r = base_r * rng.uniform(0.14, 0.22)
            components.append(_ledge_disk_sdf(
                ledge_cx, ledge_cy, ledge_top, ledge_r, rim_band=1.5,
            ))

        # Smooth-union with SMALL k — research warns smin destroys the
        # sharp ridges between facets. Keep blend tight.
        peak_blend = max(blend * 0.4, 0.8)
        peak_sdf = sdf_lib.smooth_union(peak_blend, *components)

        h_total = float(h)
        base_r_f = float(base_r)
        cx_f = float(cx)
        cy_f = float(cy)
        taper_f = float(taper)

        def make_h(prev_h: HeightFn) -> HeightFn:
            def h_with_peak(x, y):
                base_h = prev_h(x, y)
                dx = x - cx_f
                dy = y - cy_f
                r = np.sqrt(dx * dx + dy * dy + 1e-8)
                ratio = np.clip((base_r_f - r) / max(base_r_f * taper_f, 0.001), 0.0, 1.0)
                cone_h = h_total * ratio
                return np.maximum(base_h, base_h + cone_h)
            return h_with_peak

        return [FeatureSpec(
            sdf=peak_sdf, op="smooth_union", blend=blend,
            height_modifier=make_h,
            keep_out_zones=[(cx_f, cy_f, base_r_f * 0.6)],
        )]


@dataclass
class Trail:
    """A subtly carved hiking trail through flat-ish terrain — meandering
    polyline with a smoothstep-falloff depression that LOWERS the height
    field in a corridor, instead of subtracting a 3D mass like `Gorge`.

    Use Trail for: paths on flat or gently rolling ground (alpine apron,
    desert floor, meadow). Use Gorge for: deep canyons in tall plateau
    bases where you want hard cliff walls.

    The carver is implemented as a height_modifier (`h(x,y) -= depth(s) *
    falloff(d/width)`) per the standard procedural-trail recipe (Inigo
    Quilez sdSegment + smoothstep falloff). Path is auto-generated as a
    Catmull-Rom-ish chain of fbm-perturbed waypoints; depth tapers to
    zero at both endpoints so the trail "fades in/out" at the corridor
    edges.

    Researched 2026-04-29 (subagent + IQ articles + Sebastian Lague).
    """

    depth: ScalarOrRange = (1.5, 3.0)
    half_width: ScalarOrRange = (3.0, 6.0)
    n_waypoints: IntOrRange = (8, 12)
    lateral_jitter: ScalarOrRange = (8.0, 14.0)
    axis: str = "x"
    end_taper_frac: float = 0.15  # outer 15% on each end fades to zero depth
    # Top of the carver volume in world Z. Should sit just above local
    # ground so we slice the apron without punching into nearby peaks.
    # 5m default works for AlpineBase (ground 0-2m). Bump higher if the
    # base has tall ground variation.
    trail_top: float = 5.0
    keep_out_margin: ScalarOrRange = (1.0, 2.5)
    blend: ScalarOrRange = (1.0, 2.0)

    def to_specs(self, extent, seed, **kwargs) -> list[FeatureSpec]:
        sx, sy = extent
        rng = random.Random(seed * 1000 + 23)
        depth = float(_sample(self.depth, rng))
        half_w = float(_sample(self.half_width, rng))
        n_pts = int(max(2, _sample(self.n_waypoints, rng)))
        jitter = float(_sample(self.lateral_jitter, rng))
        keep_out_margin = float(_sample(self.keep_out_margin, rng))
        blend = float(_sample(self.blend, rng))
        end_taper = float(self.end_taper_frac)
        prev_height_fn = kwargs.get("prev_height_fn", None)
        existing_keep_outs = kwargs.get("existing_keep_outs", []) or []

        # Auto-generate waypoints along the corridor axis with lateral
        # noise. After generating, push any waypoint that lands inside
        # an existing keep-out (e.g. a peak's footprint) radially OUT
        # of that zone — so the trail routes around hills instead of
        # tunneling through them.
        waypoints: list[tuple[float, float]] = []
        for i in range(n_pts):
            t = i / (n_pts - 1)
            if self.axis == "y":
                main = (t - 0.5) * sy * 0.95
                cross = rng.uniform(-jitter, jitter)
                waypoints.append((cross, main))
            elif self.axis == "x":
                main = (t - 0.5) * sx * 0.95
                cross = rng.uniform(-jitter, jitter)
                waypoints.append((main, cross))
            else:
                raise ValueError(f"Trail.axis must be y|x, got {self.axis!r}")

        if existing_keep_outs:
            avoid_pad = 1.5  # extra clearance beyond the keep-out radius
            for _it in range(4):  # iterate to handle multi-zone overlaps
                changed = False
                for i, (wx, wy) in enumerate(waypoints):
                    for cx, cy, r in existing_keep_outs:
                        dx = wx - cx; dy = wy - cy
                        d = (dx * dx + dy * dy) ** 0.5
                        target_r = r + avoid_pad
                        if d < target_r and d > 1e-3:
                            push = (target_r - d) / d
                            wx = wx + dx * push
                            wy = wy + dy * push
                            changed = True
                        elif d < target_r:
                            # waypoint exactly at center — push perpendicular
                            wx = cx + target_r
                            wy = cy
                            changed = True
                    waypoints[i] = (wx, wy)
                if not changed:
                    break

        # Trail SDF — when `prev_height_fn` is supplied (factory passes
        # it), the carver is GROUND-FOLLOWING: surface lowered by
        # `trail_offset(x,y)` relative to whatever the terrain height was
        # at that XY. The hills RISE OUT of the trail instead of being
        # sliced (per user direction 2026-04-29 — "the hills should rise
        # out of the trails, cause now it looks like a gorge").
        # When prev_height_fn is None, falls back to the legacy fixed-
        # vertical-range cylinder carve (keeps Gorge-style behavior for
        # callers that don't have access to a terrain height).

        # height_modifier mirrors the SDF carve for asset-placement
        # queries (so anything spawned in the corridor sits on the
        # lowered floor, not on the original ground).
        pts = np.asarray(waypoints, dtype=np.float32)
        seg_starts = pts[:-1]
        seg_ends = pts[1:]
        seg_vecs = seg_ends - seg_starts
        seg_lens = np.sqrt((seg_vecs * seg_vecs).sum(axis=-1))
        seg_lens_safe = np.maximum(seg_lens, 1e-6)
        cum_starts = np.concatenate([[0.0], np.cumsum(seg_lens[:-1])])
        total_len = float(seg_lens.sum())
        depth_f = np.float32(depth)
        half_w_f = np.float32(half_w)

        def _trail_offset(x: np.ndarray, y: np.ndarray) -> np.ndarray:
            x32 = np.asarray(x, dtype=np.float32)
            y32 = np.asarray(y, dtype=np.float32)
            shape = x32.shape
            flat_x = x32.ravel()
            flat_y = y32.ravel()
            n = flat_x.size
            P = np.stack([flat_x, flat_y], axis=-1).astype(np.float32)
            S = seg_starts.astype(np.float32)[None, :, :]
            V = seg_vecs.astype(np.float32)[None, :, :]
            L2 = (seg_lens_safe.astype(np.float32) ** 2)[None, :]
            PS = P[:, None, :] - S
            t_proj = np.clip((PS * V).sum(axis=-1) / L2, 0.0, 1.0)
            closest = S + V * t_proj[..., None]
            diff = P[:, None, :] - closest
            d2 = (diff * diff).sum(axis=-1)
            seg_idx = np.argmin(d2, axis=1)
            d_min = np.sqrt(d2[np.arange(n), seg_idx]).astype(np.float32)
            t_at_seg = t_proj[np.arange(n), seg_idx]
            arc = (cum_starts[seg_idx] + t_at_seg * seg_lens[seg_idx]) / max(total_len, 1e-6)
            arc = arc.astype(np.float32).reshape(shape)
            d_min = d_min.reshape(shape)
            # Flat-top profile: full depth in the inner zone, smoothstep
            # only in the outer rim. Inner zone = 65% of half_width, outer
            # rim = 35%. Result: a flat-floored path with small shoulder
            # transitions on each side, NOT a V-shaped river channel.
            inner_frac = 0.65
            inner_w = half_w_f * inner_frac
            rim_w = max(half_w_f - inner_w, 0.1)
            # 1 inside inner zone, smoothstep down through the rim, 0 beyond
            t_w = np.clip((half_w_f - d_min) / rim_w, 0.0, 1.0).astype(np.float32)
            inside_inner = (d_min <= inner_w)
            t_w_smooth = (t_w * t_w * (3.0 - 2.0 * t_w)).astype(np.float32)
            falloff_w = np.where(inside_inner, np.float32(1.0), t_w_smooth).astype(np.float32)
            ttp = np.clip(arc / max(end_taper, 1e-3), 0.0, 1.0).astype(np.float32)
            ttp_in = (ttp * ttp * (3.0 - 2.0 * ttp))
            tte = np.clip((1.0 - arc) / max(end_taper, 1e-3), 0.0, 1.0).astype(np.float32)
            tte_out = (tte * tte * (3.0 - 2.0 * tte))
            falloff_arc = (ttp_in * tte_out).astype(np.float32)
            return depth_f * falloff_w * falloff_arc

        def make_h(prev_h: HeightFn) -> HeightFn:
            def h_with_trail(x, y):
                return prev_h(x, y) - _trail_offset(x, y)
            return h_with_trail

        # Stash the resolved polyline + width so callers can bake a
        # trail-proximity vertex attribute on the final mesh (used to
        # color the entire path width as gravel, not just the floor).
        self._last_polyline = list(waypoints)
        self._last_half_width = float(half_w)
        self._last_inner_frac = 0.65

        if prev_height_fn is not None:
            # Ground-following: trail SDF is `z - (h_base - offset)`.
            # Combined with prev terrain SDF via `smooth_intersect` (max),
            # the iso-surface lands at the LOWER of (original, lowered)
            # — so outside the corridor offset=0 → no change, inside
            # corridor surface lowered by offset.
            prev_h_local = prev_height_fn

            def trail_sdf(p):
                x = p[..., 0]; y = p[..., 1]; z = p[..., 2]
                base_h = prev_h_local(x, y)
                offset = _trail_offset(x, y)
                return (z - (base_h - offset)).astype(np.float32)

            keep_outs = [(float(x), float(y), half_w + keep_out_margin) for x, y in waypoints]
            return [FeatureSpec(
                sdf=trail_sdf, op="smooth_intersect", blend=blend,
                height_modifier=make_h,
                keep_out_zones=keep_outs,
            )]

        # Legacy fixed-z fallback (kept for callers without prev_height_fn)
        trail_floor = -depth
        trail_top = float(getattr(self, "trail_top", 5.0))
        z_center = (trail_floor + trail_top) / 2.0
        z_extent_carver = (trail_top - trail_floor) / 2.0 + 0.5
        carver = sdf_lib.line_xy(
            waypoints, radius=half_w,
            z=z_center, z_extent=z_extent_carver,
        )
        keep_outs = [(float(x), float(y), half_w + keep_out_margin) for x, y in waypoints]
        return [FeatureSpec(
            sdf=carver, op="smooth_subtract", blend=blend,
            height_modifier=make_h,
            keep_out_zones=keep_outs,
        )]


# ---------------------------------------------------------------------------
# Lobed-terraced peak — user-validated 2026-04-29 as the "best" alpine peak
# silhouette. Heightfield approach (NOT SDF half-plane intersection):
#   - radial profile = 1 - r_norm^exp (concave: gentle base, steep apex)
#   - lobe-union: max over N off-center lobes for multi-summit massif
#   - terrace lower zone via sigmoid quantisation → walkable benches
#   - apex truncation cap → broken summit (peaks don't fully peak)
# Replaces the v17 _faceted_peak_sdf for production use.
# ---------------------------------------------------------------------------
def _terrace_quantize(z_norm: np.ndarray, n_steps: int, sharpness: float = 10.0) -> np.ndarray:
    """Snap z_norm in [0,1] to stepped levels via per-bin sigmoid — produces
    flat shelves at each 1/n_steps interval. Higher sharpness = crisper
    bench edges. Used for walkable-bench lower zone."""
    z = np.asarray(z_norm, dtype=np.float32)
    step = 1.0 / max(n_steps, 1)
    b = z / step
    bf = np.floor(b)
    frac = b - bf
    sm = 1.0 / (1.0 + np.exp(-sharpness * (frac - 0.5)))
    return ((bf + sm) * step).astype(np.float32)


@dataclass
class TerracedPeak:
    """Single-point alpine peak built as the max-union of N lobes around a
    nominal centre, with each lobe's lower zone terraced into walkable
    benches and the apex truncated for a broken-summit silhouette.

    User-validated 2026-04-29 as the production approach for alpine peaks.
    Heightfield SDF (`p.z - h(x,y)`); marching cubes + planar decimate
    preserves the bench shelves cleanly.

    Knobs (all randomization-friendly):
      n_lobes              — 2-4 typical; biggest silhouette driver
      lobe_spread          — (lo, hi) of offset_magnitude / base_radius
      main_h_frac          — main lobe height as frac of `height`
      secondary_h_frac     — range for non-main lobe heights
      secondary_r_frac     — range for non-main lobe radii / base_radius
      benches_per_lobe     — 2-4 typical
      bench_zone           — z-norm threshold below which terracing applies
      bench_sharpness      — soft step (~6) vs crisp shelf (~14)
      apex_cap             — global height cap as frac of `height`
                              (0.78-0.85 typical) — controls how truncated
                              the summit is
      surface_noise_amp    — small global fBm overlay magnitude
      radial_exp           — concavity of the radial profile
                              (>2 pointier; <2 flatter top)
    """

    center: tuple[float, float] = (0.0, 0.0)
    height: ScalarOrRange = (40.0, 60.0)
    base_radius: ScalarOrRange = (24.0, 32.0)
    n_lobes: IntOrRange = (2, 4)
    lobe_spread: tuple[float, float] = (0.40, 0.65)
    main_h_frac: ScalarOrRange = (0.72, 0.82)
    secondary_h_frac: tuple[float, float] = (0.42, 0.62)
    secondary_r_frac: tuple[float, float] = (0.40, 0.55)
    benches_per_lobe: IntOrRange = (3, 4)
    bench_zone: ScalarOrRange = (0.55, 0.62)
    bench_sharpness: ScalarOrRange = (8.0, 12.0)
    apex_cap: ScalarOrRange = (0.78, 0.85)
    surface_noise_amp: ScalarOrRange = (0.04, 0.07)
    radial_exp: ScalarOrRange = (1.9, 2.2)
    blend: ScalarOrRange = (1.0, 2.0)

    def to_specs(self, extent, seed, **_kwargs) -> list[FeatureSpec]:
        cx_, cy_ = float(self.center[0]), float(self.center[1])
        # Mix center coordinates into the per-instance RNG so multiple
        # TerracedPeaks placed at different positions in one scene get
        # distinct lobe counts / placements / heights — otherwise they'd
        # all share factory_seed and look identical.
        per_inst_seed = (seed * 1000 + 17 + int(cx_ * 131.0) + int(cy_ * 977.0)) % (2 ** 31)
        rng = random.Random(per_inst_seed)
        h_total = float(_sample(self.height, rng))
        base_r = float(_sample(self.base_radius, rng))
        n_lobes = int(_sample(self.n_lobes, rng))
        main_h = float(_sample(self.main_h_frac, rng))
        benches = int(_sample(self.benches_per_lobe, rng))
        bench_zone = float(_sample(self.bench_zone, rng))
        bench_sharpness = float(_sample(self.bench_sharpness, rng))
        apex_cap = float(_sample(self.apex_cap, rng))
        surface_amp = float(_sample(self.surface_noise_amp, rng))
        radial_exp = float(_sample(self.radial_exp, rng))
        blend = float(_sample(self.blend, rng))

        # Sample lobes deterministically for this seed
        main_offset = rng.uniform(0.0, 3.0)
        main_ang = rng.uniform(0.0, 2.0 * math.pi)
        lobes: list[tuple[float, float, float, float]] = [(
            cx_ + main_offset * math.cos(main_ang),
            cy_ + main_offset * math.sin(main_ang),
            base_r * 0.70,
            h_total * main_h,
        )]
        for _ in range(max(n_lobes - 1, 0)):
            ang = rng.uniform(0, 2 * math.pi)
            mag = rng.uniform(*self.lobe_spread) * base_r
            lobes.append((
                cx_ + mag * math.cos(ang),
                cy_ + mag * math.sin(ang),
                base_r * rng.uniform(*self.secondary_r_frac),
                h_total * rng.uniform(*self.secondary_h_frac),
            ))

        noise = sdf_lib.low_freq_noise_2d(
            seed=per_inst_seed * 31 + 17,
            feature_scale=base_r * 1.5,
            amplitude=1.0,
            grid_size=8,
        )

        def height_fn(x: np.ndarray, y: np.ndarray) -> np.ndarray:
            x32 = np.asarray(x, dtype=np.float32)
            y32 = np.asarray(y, dtype=np.float32)
            z_total = np.zeros_like(x32)
            for lcx, lcy, lr, lh in lobes:
                dx = x32 - np.float32(lcx)
                dy = y32 - np.float32(lcy)
                d = np.sqrt(dx * dx + dy * dy + 1e-6)
                r_norm = np.clip(d / np.float32(lr), 0.0, 1.0)
                radial = 1.0 - np.power(r_norm, np.float32(radial_exp))
                radial = np.clip(radial, 0.0, 1.0).astype(np.float32)
                rt = np.where(
                    radial < bench_zone,
                    _terrace_quantize(radial / bench_zone, benches,
                                      sharpness=bench_sharpness) * bench_zone,
                    radial,
                ).astype(np.float32)
                z_total = np.maximum(z_total, np.float32(lh) * rt)
            # Surface noise — masked by total height so it dies outside footprint
            n = noise(x32, y32)
            footprint_mask = (z_total > 0).astype(np.float32)
            z_total = z_total + np.float32(surface_amp * h_total) * n * footprint_mask
            z_total = np.minimum(z_total, np.float32(h_total * apex_cap))
            # Outside any lobe (z_total still 0) return a large negative so
            # the height_field SDF says "no surface" there. Otherwise
            # the peak emits a flat z=0 sheet covering the whole extent
            # when used over EmptyBase / OceanBase.
            outside = z_total <= 0
            return np.where(outside, np.float32(-1e6), z_total).astype(np.float32)

        peak_sdf = sdf_lib.height_field(height_fn)

        def make_h(prev_h: HeightFn) -> HeightFn:
            def h_with_peak(x, y):
                return np.maximum(prev_h(x, y), height_fn(x, y))
            return h_with_peak

        return [FeatureSpec(
            sdf=peak_sdf, op="smooth_union", blend=blend,
            height_modifier=make_h,
            keep_out_zones=[(cx_, cy_, base_r * 0.6)],
        )]


# ---------------------------------------------------------------------------
# Mountain ridge — peak built around a polyline rather than a single apex.
# Uses distance-to-polyline as the radial parameter; height-along-arc
# samples summit positions along the line for natural multi-summit chains
# (Aiguilles-de-Chamonix / Cuillin Ridge / Mont Blanc style).
# ---------------------------------------------------------------------------
@dataclass
class MountainRidge:
    """An alpine ridgeline — multi-summit chain built around a polyline.

    Same lobed-terraced apparatus as `TerracedPeak`, but the radial
    parameter is distance-to-polyline instead of distance-to-apex, and
    summit heights are sampled along the line's arc-length so the ridge
    has natural undulating crest with multiple summits separated by
    saddles. Use for: linear cliff walls flanking a pass, long
    chains of jagged peaks, T-shape spurs.

    polyline       — list of (x, y) waypoints in world coords (≥ 2)
    arc_summits    — list of (t ∈ [0, 1], height_frac) — summit count
                      and distribution along the ridge. height_frac is
                      relative to `height`. Saddles fall between samples.
    ridge_radius   — perpendicular extent (one side) — typical 15-25m
    benches/bench_zone/bench_sharpness/apex_cap/surface_noise_amp/radial_exp
                     — same semantics as TerracedPeak
    """

    polyline: list[tuple[float, float]] = field(default_factory=lambda: [(-30.0, 0.0), (30.0, 0.0)])
    arc_summits: list[tuple[float, float]] = field(default_factory=lambda: [(0.20, 0.95), (0.55, 0.78), (0.85, 0.85)])
    ridge_radius: ScalarOrRange = (16.0, 22.0)
    height: ScalarOrRange = (40.0, 60.0)
    benches: IntOrRange = (3, 4)
    bench_zone: ScalarOrRange = (0.50, 0.60)
    bench_sharpness: ScalarOrRange = (8.0, 12.0)
    apex_cap: ScalarOrRange = (0.80, 0.90)
    surface_noise_amp: ScalarOrRange = (0.04, 0.07)
    radial_exp: ScalarOrRange = (1.9, 2.3)
    blend: ScalarOrRange = (1.0, 2.0)

    def to_specs(self, extent, seed, **_kwargs) -> list[FeatureSpec]:
        # Mix polyline centroid into the per-instance seed so multiple
        # MountainRidges in one scene get distinct samplings.
        pts_for_seed = np.asarray(self.polyline, dtype=np.float32)
        seed_cx = float(pts_for_seed[:, 0].mean())
        seed_cy = float(pts_for_seed[:, 1].mean())
        per_inst_seed = (seed * 1000 + 19 + int(seed_cx * 131.0) + int(seed_cy * 977.0)) % (2 ** 31)
        rng = random.Random(per_inst_seed)
        h_total = float(_sample(self.height, rng))
        ridge_r = float(_sample(self.ridge_radius, rng))
        benches = int(_sample(self.benches, rng))
        bench_zone = float(_sample(self.bench_zone, rng))
        bench_sharpness = float(_sample(self.bench_sharpness, rng))
        apex_cap = float(_sample(self.apex_cap, rng))
        surface_amp = float(_sample(self.surface_noise_amp, rng))
        radial_exp = float(_sample(self.radial_exp, rng))
        blend = float(_sample(self.blend, rng))

        pts = np.asarray(self.polyline, dtype=np.float32)
        if pts.shape[0] < 2:
            raise ValueError("MountainRidge needs at least 2 polyline waypoints")
        seg_starts = pts[:-1]
        seg_ends = pts[1:]
        seg_vecs = seg_ends - seg_starts
        seg_lens = np.sqrt((seg_vecs * seg_vecs).sum(axis=-1))
        seg_lens_safe = np.maximum(seg_lens, 1e-6)
        cum_starts = np.concatenate([[0.0], np.cumsum(seg_lens[:-1])])
        total_len = float(seg_lens.sum())

        # arc-summit gaussian profile
        summit_t = np.asarray([s[0] for s in self.arc_summits], dtype=np.float32)
        summit_h = np.asarray([s[1] for s in self.arc_summits], dtype=np.float32)
        bandwidths = np.zeros_like(summit_t)
        for i in range(len(summit_t)):
            d = np.abs(summit_t - summit_t[i]).copy()
            d[i] = 1.0
            bandwidths[i] = max(float(d.min()) * 0.55, 0.05)

        cx_centroid = float(pts[:, 0].mean())
        cy_centroid = float(pts[:, 1].mean())
        max_extent = float(max(
            pts[:, 0].max() - pts[:, 0].min(),
            pts[:, 1].max() - pts[:, 1].min(),
        ))
        keep_out_r = max(max_extent * 0.5, ridge_r * 0.6)

        noise = sdf_lib.low_freq_noise_2d(
            seed=per_inst_seed * 31 + 19,
            feature_scale=ridge_r * 2.0,
            amplitude=1.0,
            grid_size=8,
        )

        def _polyline_dist_t(x: np.ndarray, y: np.ndarray):
            x32 = np.asarray(x, dtype=np.float32); y32 = np.asarray(y, dtype=np.float32)
            shape = x32.shape
            flat_x = x32.ravel(); flat_y = y32.ravel()
            n_pts = flat_x.size
            P = np.stack([flat_x, flat_y], axis=-1).astype(np.float32)
            S = seg_starts.astype(np.float32)[None, :, :]
            V = seg_vecs.astype(np.float32)[None, :, :]
            L2 = (seg_lens_safe.astype(np.float32) ** 2)[None, :]
            PS = P[:, None, :] - S
            t_proj = np.clip((PS * V).sum(axis=-1) / L2, 0.0, 1.0)
            closest = S + V * t_proj[..., None]
            diff = P[:, None, :] - closest
            d2 = (diff * diff).sum(axis=-1)
            seg_idx = np.argmin(d2, axis=1)
            d_min = np.sqrt(d2[np.arange(n_pts), seg_idx]).astype(np.float32)
            t_at_seg = t_proj[np.arange(n_pts), seg_idx]
            arc = (cum_starts[seg_idx] + t_at_seg * seg_lens[seg_idx]) / max(total_len, 1e-6)
            return d_min.reshape(shape), arc.astype(np.float32).reshape(shape)

        def _arc_height(t: np.ndarray) -> np.ndarray:
            t32 = np.asarray(t, dtype=np.float32)
            out = np.zeros_like(t32)
            for ti, hi, bi in zip(summit_t, summit_h, bandwidths):
                d = (t32 - ti) / bi
                out = np.maximum(out, hi * np.exp(-d * d).astype(np.float32))
            return out

        def height_fn(x: np.ndarray, y: np.ndarray) -> np.ndarray:
            d, t = _polyline_dist_t(x, y)
            d_norm = np.clip(d / np.float32(ridge_r), 0.0, 1.0).astype(np.float32)
            radial = 1.0 - np.power(d_norm, np.float32(radial_exp))
            radial = np.clip(radial, 0.0, 1.0).astype(np.float32)
            rt = np.where(
                radial < bench_zone,
                _terrace_quantize(radial / bench_zone, benches,
                                  sharpness=bench_sharpness) * bench_zone,
                radial,
            ).astype(np.float32)
            h_t = _arc_height(t)
            z = np.float32(h_total) * h_t * rt
            n = noise(np.asarray(x, dtype=np.float32), np.asarray(y, dtype=np.float32))
            z = z + np.float32(surface_amp * h_total) * n * radial
            z = np.minimum(z, np.float32(h_total * apex_cap))
            # Outside the ridge footprint (d > ridge_r) return a large
            # negative so the height_field SDF (`z - h`) is always positive
            # there — i.e. "no surface" outside the ridge. Otherwise
            # MountainRidge produces a flat z=0 sheet covering the whole
            # extent, which shows up as a giant sea-floor rectangle when
            # paired with EmptyBase / OceanBase.
            outside = d > ridge_r
            return np.where(outside, np.float32(-1e6), z).astype(np.float32)

        ridge_sdf = sdf_lib.height_field(height_fn)

        def make_h(prev_h: HeightFn) -> HeightFn:
            def h_with_ridge(x, y):
                return np.maximum(prev_h(x, y), height_fn(x, y))
            return h_with_ridge

        return [FeatureSpec(
            sdf=ridge_sdf, op="smooth_union", blend=blend,
            height_modifier=make_h,
            keep_out_zones=[(cx_centroid, cy_centroid, keep_out_r)],
        )]


@dataclass
class Cliff:
    """A vertical drop along a line — half the extent is N meters higher
    than the other half."""

    height: ScalarOrRange = (4.0, 8.0)
    axis: str = "x"
    position: float = 0.0
    side: str = "high_x_pos"
    blend: ScalarOrRange = (1.0, 2.0)

    def to_specs(self, extent, seed, **_kwargs) -> list[FeatureSpec]:
        rng = random.Random(seed * 1000 + 8)
        height = _sample(self.height, rng)
        blend = _sample(self.blend, rng)
        sx, sy = extent
        if self.side == "high_x_pos":
            cliff_box = sdf_lib.box(
                size=(sx, sy * 2, height * 2),
                center=(self.position + sx * 0.5, 0.0, height * 0.5),
            )
        elif self.side == "high_x_neg":
            cliff_box = sdf_lib.box(
                size=(sx, sy * 2, height * 2),
                center=(self.position - sx * 0.5, 0.0, height * 0.5),
            )
        elif self.side == "high_y_pos":
            cliff_box = sdf_lib.box(
                size=(sx * 2, sy, height * 2),
                center=(0.0, self.position + sy * 0.5, height * 0.5),
            )
        elif self.side == "high_y_neg":
            cliff_box = sdf_lib.box(
                size=(sx * 2, sy, height * 2),
                center=(0.0, self.position - sy * 0.5, height * 0.5),
            )
        else:
            raise ValueError(
                f"Cliff.side must be high_x_pos|high_x_neg|high_y_pos|high_y_neg, "
                f"got {self.side!r}"
            )

        def make_h(prev_h: HeightFn) -> HeightFn:
            def h_with_cliff(x: np.ndarray, y: np.ndarray) -> np.ndarray:
                base_h = prev_h(x, y)
                if self.side == "high_x_pos":
                    raised = (x > self.position).astype(np.float32) * height
                elif self.side == "high_x_neg":
                    raised = (x < self.position).astype(np.float32) * height
                elif self.side == "high_y_pos":
                    raised = (y > self.position).astype(np.float32) * height
                else:
                    raised = (y < self.position).astype(np.float32) * height
                return base_h + raised
            return h_with_cliff

        return [FeatureSpec(
            sdf=cliff_box, op="smooth_union", blend=blend,
            height_modifier=make_h,
        )]


# ---------------------------------------------------------------------------
# Composite feature — Canyon (subtractive carve + additive walls)
# ---------------------------------------------------------------------------


@dataclass
class Canyon:
    """A wide canyon flanked by mesa walls.

    Composes two FeatureSpecs:
      1. SUBTRACT a wide trench (the canyon floor).
      2. ADD a row of mesa columns along each side of the trench (the
         walls). Mesas pick from the same shape styles as MesaCluster
         (lobed / eroded / round / rounded_square) so the walls read as
         natural rock.

    This is the answer to prompts like "deep canyon with mesa walls all
    around" — Gorge alone gives a slit; Canyon gives the slit plus
    aligned wall geometry.
    """

    depth: ScalarOrRange = (10.0, 18.0)
    floor_half_width: ScalarOrRange = (5.0, 9.0)         # canyon floor width
    n_waypoints: IntOrRange = (3, 5)
    lateral_jitter: ScalarOrRange = (4.0, 9.0)
    axis: str = "y"
    carve_blend: ScalarOrRange = (1.5, 2.5)
    # Wall mesas
    wall_mesa_density: ScalarOrRange = (1.0, 1.6)        # mesas per 10m of canyon length
    wall_mesa_height_range: tuple[float, float] = (10.0, 22.0)
    wall_mesa_radius_range: tuple[float, float] = (3.5, 7.0)
    wall_offset: ScalarOrRange = (1.5, 4.0)              # wall mesa center vs canyon edge
    wall_blend: ScalarOrRange = (2.0, 3.5)
    wall_style_weights: dict = field(default_factory=lambda: dict(_MESA_STYLE_DEFAULTS))

    def to_specs(self, extent, seed, **_kwargs) -> list[FeatureSpec]:
        sx, sy = extent
        rng = random.Random(seed * 1000 + 9)
        depth = _sample(self.depth, rng)
        floor_w = _sample(self.floor_half_width, rng)
        n_pts = max(2, _sample(self.n_waypoints, rng))
        jitter = _sample(self.lateral_jitter, rng)
        carve_blend = _sample(self.carve_blend, rng)
        density = _sample(self.wall_mesa_density, rng)
        offset = _sample(self.wall_offset, rng)
        wall_blend = _sample(self.wall_blend, rng)

        # 1) Build the canyon path.
        waypoints: list[tuple[float, float]] = []
        for i in range(n_pts):
            t = i / (n_pts - 1)
            if self.axis == "y":
                main = (t - 0.5) * sy * 0.95
                cross = rng.uniform(-jitter, jitter)
                waypoints.append((cross, main))
            elif self.axis == "x":
                main = (t - 0.5) * sx * 0.95
                cross = rng.uniform(-jitter, jitter)
                waypoints.append((main, cross))
            elif self.axis == "diagonal":
                m = (t - 0.5) * 0.95
                jit = rng.uniform(-jitter, jitter) * 0.5
                waypoints.append((m * sx + jit, m * sy - jit))
            else:
                raise ValueError(f"Canyon.axis must be y|x|diagonal, got {self.axis!r}")

        # 2) Subtractive spec — the canyon trench. z_extent tight to
        # the canyon depth so the marching-cubes floor closes (same fix
        # as Gorge — buffer of 2m below depth keeps the carver from
        # extending past the sample volume).
        carver = sdf_lib.line_xy(
            waypoints, radius=floor_w,
            z=-depth * 0.5, z_extent=depth * 0.5 + 2.0,
        )
        keep_outs = [(x, y, floor_w + 2) for x, y in waypoints]
        carve_spec = FeatureSpec(
            sdf=carver, op="smooth_subtract", blend=carve_blend,
            keep_out_zones=keep_outs,
        )

        # 3) Additive spec — mesa walls along each side.
        # Sample mesa positions perpendicular to the local canyon
        # direction at each waypoint span.
        styles = list(self.wall_style_weights.keys())
        weights = list(self.wall_style_weights.values())
        wall_mesas: list[dict] = []
        for i in range(len(waypoints) - 1):
            ax, ay = waypoints[i]
            bx, by = waypoints[i + 1]
            seg_len = math.hypot(bx - ax, by - ay)
            n_mesas_per_side = max(1, int(seg_len * density / 10))
            # Local perpendicular (unit) vector — turn left/right of canyon dir
            dx = bx - ax
            dy = by - ay
            seg_norm = math.hypot(dx, dy) or 1.0
            perp_x = -dy / seg_norm
            perp_y = dx / seg_norm
            for j in range(n_mesas_per_side):
                t = (j + 0.5) / n_mesas_per_side
                base_x = ax + dx * t
                base_y = ay + dy * t
                for sign in (+1, -1):
                    mesa_r = rng.uniform(*self.wall_mesa_radius_range)
                    mesa_h = rng.uniform(*self.wall_mesa_height_range)
                    cx = base_x + sign * (floor_w + offset + mesa_r * 0.4) * perp_x
                    cy = base_y + sign * (floor_w + offset + mesa_r * 0.4) * perp_y
                    # Skip if outside extent
                    if abs(cx) > sx * 0.5 - mesa_r or abs(cy) > sy * 0.5 - mesa_r:
                        continue
                    # Skip overlap with existing wall mesa
                    if any(
                        math.hypot(cx - m["x"], cy - m["y"]) < (m["r"] + mesa_r * 0.7)
                        for m in wall_mesas
                    ):
                        continue
                    wall_mesas.append({
                        "x": cx, "y": cy, "r": mesa_r, "h": mesa_h,
                        "style": rng.choices(styles, weights=weights)[0],
                    })

        sdfs = [
            _build_mesa_sdf(m["style"], m["x"], m["y"], m["r"], m["h"], rng)
            for m in wall_mesas
        ]
        if sdfs:
            walls_sdf = sdf_lib.union(*sdfs)
        else:
            walls_sdf = lambda p: np.full(p.shape[:-1], 1e6, dtype=np.float32)

        def make_h(prev_h: HeightFn) -> HeightFn:
            def h_with_walls(x: np.ndarray, y: np.ndarray) -> np.ndarray:
                base_h = prev_h(x, y)
                out = base_h.copy() if hasattr(base_h, "copy") else np.array(base_h)
                for m in wall_mesas:
                    r2 = (x - m["x"]) ** 2 + (y - m["y"]) ** 2
                    d_norm = np.sqrt(r2) / m["r"]
                    mask = _smoothstep(1.0 - (d_norm - 0.7) / 0.5)
                    out = np.maximum(out, base_h + m["h"] * mask)
                return out
            return h_with_walls

        wall_scatter = [(m["x"], m["y"], m["r"] * 0.5) for m in wall_mesas]
        walls_spec = FeatureSpec(
            sdf=walls_sdf, op="smooth_union", blend=wall_blend,
            height_modifier=make_h,
            scatter_zones=wall_scatter,
        )

        # Order matters: walls first (additive raises the ground), then
        # carve (subtract the trench through walls + base).
        return [walls_spec, carve_spec]

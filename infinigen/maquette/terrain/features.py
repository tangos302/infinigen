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


@dataclass
class MountainPeak:
    """A single tall conical peak — for hero summit shots."""

    center: tuple[float, float] = (0.0, 0.0)
    height: ScalarOrRange = (20.0, 30.0)
    base_radius: ScalarOrRange = (12.0, 18.0)
    peak_radius: ScalarOrRange = (1.0, 2.5)
    blend: ScalarOrRange = (3.0, 5.0)

    def to_specs(self, extent, seed, **_kwargs) -> list[FeatureSpec]:
        rng = random.Random(seed * 1000 + 7)
        h = _sample(self.height, rng)
        base_r = _sample(self.base_radius, rng)
        peak_r = _sample(self.peak_radius, rng)
        blend = _sample(self.blend, rng)
        cx, cy = self.center

        lower = sdf_lib.cylinder(
            radius=base_r, height=h * 0.4,
            center=(cx, cy, h * 0.2),
        )
        upper = sdf_lib.cylinder(
            radius=(base_r + peak_r) * 0.5, height=h * 0.4,
            center=(cx, cy, h * 0.6),
        )
        tip = sdf_lib.cylinder(
            radius=peak_r, height=h * 0.2,
            center=(cx, cy, h * 0.9),
        )
        peak_sdf = sdf_lib.union(lower, upper, tip)

        def make_h(prev_h: HeightFn) -> HeightFn:
            def h_with_peak(x: np.ndarray, y: np.ndarray) -> np.ndarray:
                base_h = prev_h(x, y)
                r = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)
                cone_h = np.maximum(0.0, h * (1.0 - r / base_r))
                return np.maximum(base_h, base_h + cone_h)
            return h_with_peak

        return [FeatureSpec(
            sdf=peak_sdf, op="smooth_union", blend=blend,
            height_modifier=make_h,
            keep_out_zones=[(cx, cy, base_r * 0.7)],
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

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
    single mesa column, vertically z-centered at z=0 (top at z=height,
    bottom at z=-height; the base ground trims the bottom).

    Two styles, both designed to read as natural eroded rock:
      "natural" — cylinder with a multi-frequency cosine perturbation
                  on its radius (random phases per harmonic, low
                  amplitude). Asymmetric, smooth, organic.
      "round"   — clean cylinder. Useful as an occasional accent;
                  reads as an unweathered rock pillar. Use sparingly.

    The earlier `lobed` (single cos → flower-petals), `rounded_square`
    (rotated cube), and `eroded` (multi-cylinder lump) styles produced
    visibly artificial / toy-looking mesas. They've been removed in
    favor of `natural`, which uses a sum of 3 cosines with random
    phases — perceptually equivalent to perlin-noise on the radius
    profile but cheaper to evaluate.
    """
    h2 = height * 2
    if style == "round":
        return sdf_lib.cylinder(radius=radius, height=h2, center=(cx, cy, 0))
    if style == "natural":
        # 3 random cosine harmonics give a smooth asymmetric outline.
        # Frequencies kept LOW (n=1..3) so the mesa silhouette has broad
        # bumps rather than fine ribbing — fine ribbing reads as machined.
        # Amplitudes are 3-7% of radius — enough irregularity to escape
        # "perfect cylinder" without becoming starfish-shaped.
        components = []
        for _ in range(3):
            n = rng.randint(1, 3)
            amp = rng.uniform(0.03, 0.07) * radius
            phase = rng.uniform(0, 2 * math.pi)
            components.append((n, amp, phase))
        # A small radial shift gives the mesa an overall lean — one side
        # naturally wider than the other.
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
    raise ValueError(f"unknown mesa style {style!r}")


# 90/10 weight split — most mesas natural, occasional clean cylinder.
_MESA_STYLE_DEFAULTS = {"natural": 9.0, "round": 1.0}


# ---------------------------------------------------------------------------
# Subtractive features — ravines, lakes, caves
# ---------------------------------------------------------------------------


@dataclass
class Gorge:
    """A winding ravine carved through the terrain.

    Reads as a deep, narrow trench snaking from one edge to the other.
    All magnitude params accept scalar OR `(min, max)` tuple; defaults
    are tuples → seed-to-seed variation by default.
    """

    depth: ScalarOrRange = (8.0, 14.0)
    half_width: ScalarOrRange = (2.0, 3.5)
    n_waypoints: IntOrRange = (3, 5)
    lateral_jitter: ScalarOrRange = (5.0, 10.0)
    blend: ScalarOrRange = (1.0, 2.0)
    axis: str = "y"

    def to_specs(self, extent, seed) -> list[FeatureSpec]:
        sx, sy = extent
        rng = random.Random(seed * 1000 + 1)
        depth = _sample(self.depth, rng)
        half_w = _sample(self.half_width, rng)
        n_pts = max(2, _sample(self.n_waypoints, rng))
        jitter = _sample(self.lateral_jitter, rng)
        blend = _sample(self.blend, rng)

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

        # z_extent must be tight enough that the carver STOPS carving below
        # the canyon floor — otherwise marching cubes never finds a closed
        # mesh at z = -depth, and the result has a hole through to the
        # world background. half-extent = depth/2 + 2m buffer:
        # carver active z ∈ [-depth-2, +2], floor closes at z = -depth-2.
        carver = sdf_lib.line_xy(
            waypoints, radius=half_w,
            z=-depth * 0.5, z_extent=depth * 0.5 + 2.0,
        )
        keep_outs = [(x, y, half_w + 1.5) for x, y in waypoints]
        return [FeatureSpec(
            sdf=carver, op="smooth_subtract", blend=blend,
            keep_out_zones=keep_outs,
        )]


@dataclass
class Lake:
    """A circular depression carved out of the terrain. The water
    surface itself lands separately via `LowPolyWaterSurfaceFactory`."""

    center: tuple[float, float] = (0.0, 0.0)
    radius: ScalarOrRange = (8.0, 14.0)
    depth: ScalarOrRange = (3.0, 6.0)
    blend: ScalarOrRange = (1.5, 3.0)

    def to_specs(self, extent, seed) -> list[FeatureSpec]:
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

    def to_specs(self, extent, seed) -> list[FeatureSpec]:
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

    def to_specs(self, extent, seed) -> list[FeatureSpec]:
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
    # Style weights — `lobed` dominates because it reads most natural.
    style_weights: dict = field(default_factory=lambda: dict(_MESA_STYLE_DEFAULTS))

    def to_specs(self, extent, seed) -> list[FeatureSpec]:
        sx, sy = extent
        rng = random.Random(seed * 1000 + 3)
        n_target = _sample(self.n, rng)
        blend = _sample(self.blend, rng)

        mesas: list[dict] = []
        attempts = 0
        styles = list(self.style_weights.keys())
        weights = list(self.style_weights.values())
        while len(mesas) < n_target and attempts < n_target * 30:
            attempts += 1
            cx = rng.uniform(-sx * 0.45, sx * 0.45)
            cy = rng.uniform(-sy * 0.45, sy * 0.45)
            new_r = rng.uniform(*self.radius_range)
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


@dataclass
class IslandCluster:
    """N rounded dome-shaped islands rising out of an ocean base."""

    n: IntOrRange = (5, 8)
    height_range: tuple[float, float] = (1.5, 4.5)
    radius_range: tuple[float, float] = (5.0, 10.0)
    blend: ScalarOrRange = (1.2, 2.0)
    spread_radius: ScalarOrRange = (25.0, 35.0)
    keep_out_radius: float = 4.0

    def to_specs(self, extent, seed) -> list[FeatureSpec]:
        rng = random.Random(seed * 1000 + 4)
        n_target = _sample(self.n, rng)
        blend = _sample(self.blend, rng)
        spread = _sample(self.spread_radius, rng)

        islands: list[dict] = []
        attempts = 0
        while len(islands) < n_target and attempts < n_target * 30:
            attempts += 1
            theta = rng.uniform(0, 2 * math.pi)
            r = rng.uniform(0, spread)
            cx = r * math.cos(theta)
            cy = r * math.sin(theta)
            new_r = rng.uniform(*self.radius_range)
            too_close = any(
                math.hypot(cx - i["x"], cy - i["y"])
                < (i["r"] + new_r + self.keep_out_radius)
                for i in islands
            )
            if too_close:
                continue
            islands.append({
                "x": cx, "y": cy,
                "h": rng.uniform(*self.height_range),
                "r": new_r,
            })

        spheres = []
        for i in islands:
            sphere_r = (i["r"] ** 2 + i["h"] ** 2) / (2 * max(i["h"], 0.01))
            sphere_cz = i["h"] - sphere_r
            spheres.append(sdf_lib.sphere(sphere_r, center=(i["x"], i["y"], sphere_cz)))

        if not spheres:
            island_sdf: sdf_lib.SDF = lambda p: np.full(p.shape[:-1], 1e6, dtype=np.float32)
        else:
            island_sdf = sdf_lib.union(*spheres)

        def make_h(prev_h: HeightFn) -> HeightFn:
            def h_with_islands(x: np.ndarray, y: np.ndarray) -> np.ndarray:
                base_h = prev_h(x, y)
                out = base_h.copy() if hasattr(base_h, "copy") else np.array(base_h)
                for i in islands:
                    r2 = (x - i["x"]) ** 2 + (y - i["y"]) ** 2
                    d_norm = np.sqrt(r2) / i["r"]
                    mask = _smoothstep(1.0 - d_norm)
                    out = np.maximum(out, base_h + i["h"] * mask)
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

    def to_specs(self, extent, seed) -> list[FeatureSpec]:
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

    def to_specs(self, extent, seed) -> list[FeatureSpec]:
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

    def to_specs(self, extent, seed) -> list[FeatureSpec]:
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

"""Terrain features — composable shapes that modify a base.

Each feature is an instance class that, given the terrain extent + a
seed, returns a `FeatureSpec` describing how it composes with the
running terrain SDF. The factory runs them in order, smooth-ops at the
boundaries giving organic blending where appropriate.

Available features:
  Gorge        — winding ravine carved through the terrain (subtractive).
  MesaCluster  — N flat-topped mesas placed inside a region (additive).
  MountainPeak — single tall conical peak (additive).
  Lake         — circular depression carved out (subtractive).
  CaveSystem   — sphere chain hollowed below the surface (subtractive,
                 fully 3D, breaks heightmap-only assumption).
  Cliff        — straight-line cliff drop along an axis (additive on one side).

Composing rules:
  - Gorge / Lake / CaveSystem subtract from the base.
  - MesaCluster / MountainPeak / Cliff add to the base.
  - Smooth ops are used everywhere a feature meets the base, so the
    blend reads as "the rock weathered and joined the ground" instead
    of as pasted-in geometry.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from . import sdf as sdf_lib
from .composition import FeatureSpec, HeightFn


# ---------------------------------------------------------------------------
# Helpers — internal. _smooth_max etc. duplicated cheaply to keep features
# self-contained and avoid scattering 3-line numpy ops through callers.
# ---------------------------------------------------------------------------


def _smoothstep(t: np.ndarray) -> np.ndarray:
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


# ---------------------------------------------------------------------------
# Subtractive features — ravines, lakes, caves
# ---------------------------------------------------------------------------


@dataclass
class Gorge:
    """A winding ravine carved through the terrain.

    Reads as a deep, narrow trench that snakes from one edge of the
    extent to the other. `n_waypoints` controls how many control points
    define the path — more = curvier; `lateral_jitter` controls how far
    each waypoint can shift off the centerline (m).

    Future polish — taper the bottom, add bedrock-scour bumps, route
    around a fixed obstacle. For now: straight tube of constant width.
    """

    depth: float = 10.0
    half_width: float = 2.5
    n_waypoints: int = 4
    lateral_jitter: float = 8.0
    blend: float = 1.5
    # Direction the gorge runs: "y" runs north-south, "x" runs east-west,
    # "diagonal" cuts corner to corner. Strings stay simple for Claude.
    axis: str = "y"

    def to_spec(self, extent, seed):
        sx, sy = extent
        rng = random.Random(seed * 1000 + 1)
        n_pts = max(2, self.n_waypoints)
        waypoints: list[tuple[float, float]] = []
        for i in range(n_pts):
            t = i / (n_pts - 1)
            if self.axis == "y":
                main = (t - 0.5) * sy * 0.95
                cross = rng.uniform(-self.lateral_jitter, self.lateral_jitter)
                waypoints.append((cross, main))
            elif self.axis == "x":
                main = (t - 0.5) * sx * 0.95
                cross = rng.uniform(-self.lateral_jitter, self.lateral_jitter)
                waypoints.append((main, cross))
            elif self.axis == "diagonal":
                m = (t - 0.5) * 0.95
                jitter = rng.uniform(-self.lateral_jitter, self.lateral_jitter) * 0.5
                waypoints.append((m * sx + jitter, m * sy - jitter))
            else:
                raise ValueError(f"Gorge.axis must be y|x|diagonal, got {self.axis!r}")

        carver = sdf_lib.line_xy(
            waypoints, radius=self.half_width,
            z=-self.depth * 0.5, z_extent=self.depth * 1.5,
        )
        keep_outs = [(x, y, self.half_width + 1.5) for x, y in waypoints]
        return FeatureSpec(
            sdf=carver, op="smooth_subtract", blend=self.blend,
            keep_out_zones=keep_outs,
        )


@dataclass
class Lake:
    """A circular depression carved out of the terrain — not the water
    surface itself; that lands separately via LowPolyWaterSurfaceFactory.
    The depression provides the bowl the water sits in."""

    center: tuple[float, float] = (0.0, 0.0)
    radius: float = 12.0
    depth: float = 4.0
    blend: float = 2.0

    def to_spec(self, extent, seed):
        # A flattened ellipsoidal carve — wider than tall, bottom flat-ish.
        # Modeled as a cylinder of (radius, depth) sitting at z = -depth.
        cx, cy = self.center
        carver = sdf_lib.cylinder(
            radius=self.radius,
            height=self.depth * 2.5,
            center=(cx, cy, -self.depth),
        )
        return FeatureSpec(
            sdf=carver, op="smooth_subtract", blend=self.blend,
            keep_out_zones=[(cx, cy, self.radius + 2)],
        )


@dataclass
class CaveSystem:
    """A chain of overlapping spheres hollowed below the surface — the
    canonical use case for the SDF approach since heightmaps can't do
    overhangs. Mouth(s) are exposed by carving down from the surface;
    the rest of the chain is internal."""

    n_chambers: int = 4
    chamber_radius_range: tuple[float, float] = (3.5, 6.0)
    depth: float = 5.0
    region: tuple[tuple[float, float], tuple[float, float]] = ((-25, 25), (-25, 25))

    def to_spec(self, extent, seed):
        rng = random.Random(seed * 1000 + 2)
        spheres: list = []
        keep_outs: list[tuple[float, float, float]] = []
        prev_xy: tuple[float, float] | None = None
        for _ in range(self.n_chambers):
            (xa, xb), (ya, yb) = self.region
            if prev_xy is None:
                cx = rng.uniform(xa, xb)
                cy = rng.uniform(ya, yb)
            else:
                # Walk from previous chamber so the chain stays connected.
                cx = prev_xy[0] + rng.uniform(-5, 5)
                cy = prev_xy[1] + rng.uniform(-5, 5)
                cx = max(xa, min(xb, cx))
                cy = max(ya, min(yb, cy))
            r = rng.uniform(*self.chamber_radius_range)
            cz = -rng.uniform(self.depth * 0.5, self.depth * 1.2)
            spheres.append(sdf_lib.sphere(r, center=(cx, cy, cz)))
            keep_outs.append((cx, cy, r + 1))
            prev_xy = (cx, cy)
        # First chamber gets a vertical mouth shaft up through the surface.
        if spheres:
            cx, cy = keep_outs[0][0], keep_outs[0][1]
            mouth = sdf_lib.cylinder(
                radius=self.chamber_radius_range[0] * 0.5,
                height=abs(self.depth) * 4,
                center=(cx, cy, 0),
            )
            spheres.append(mouth)
        carver = sdf_lib.union(*spheres) if spheres else sdf_lib.sphere(0.01)
        return FeatureSpec(
            sdf=carver, op="smooth_subtract", blend=1.0,
            keep_out_zones=keep_outs,
        )


# ---------------------------------------------------------------------------
# Additive features — mesas, peaks, cliffs
# ---------------------------------------------------------------------------


@dataclass
class MesaCluster:
    """N flat-topped mesa columns scattered in the extent, avoiding any
    pre-declared keep-out zones. Adds to the base via smooth-union so the
    skirt blends into the ground.

    Each mesa is a vertical cylinder topped with a slight cap; the SDF
    here is a stack of cylinders rising to the chosen heights, height
    function is a smooth max of the base + per-mesa contribution so
    factories can ask "is x,y on top of a mesa, and how high?"
    """

    n: int = 6
    height_range: tuple[float, float] = (8.0, 18.0)
    radius_range: tuple[float, float] = (4.0, 9.0)
    blend: float = 2.5
    keep_out_radius: float = 14.0  # mesas avoid any feature within this

    def to_spec(self, extent, seed):
        sx, sy = extent
        rng = random.Random(seed * 1000 + 3)
        mesas: list[dict] = []
        # NB: at to_spec time we don't know the OTHER features' keep-out
        # zones — that's OK for now. Most callers add MesaCluster first
        # so it can see the full extent. The factory could pass keep-outs
        # explicitly later if collision becomes an issue.
        attempts = 0
        while len(mesas) < self.n and attempts < self.n * 30:
            attempts += 1
            cx = rng.uniform(-sx * 0.45, sx * 0.45)
            cy = rng.uniform(-sy * 0.45, sy * 0.45)
            # Self-spacing: don't pile mesas on top of each other.
            too_close = any(
                math.hypot(cx - m["x"], cy - m["y"]) < (m["r"] + self.keep_out_radius * 0.5)
                for m in mesas
            )
            if too_close:
                continue
            mesas.append({
                "x": cx, "y": cy,
                "h": rng.uniform(*self.height_range),
                "r": rng.uniform(*self.radius_range),
            })

        # SDF: union of vertical cylinders centered at z = h/2, height h.
        cylinders = [
            sdf_lib.cylinder(
                radius=m["r"], height=m["h"] * 2,
                center=(m["x"], m["y"], 0.0),
            )
            for m in mesas
        ]
        if not cylinders:
            mesa_sdf: sdf_lib.SDF = lambda p: np.full(p.shape[:-1], 1e6, dtype=np.float32)
        else:
            mesa_sdf = sdf_lib.union(*cylinders)

        # Height modifier: layer mesa peaks on top of the base height.
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

        keep_outs = [(m["x"], m["y"], m["r"] + 1.5) for m in mesas]
        return FeatureSpec(
            sdf=mesa_sdf, op="smooth_union", blend=self.blend,
            height_modifier=make_height_modifier,
            keep_out_zones=keep_outs,
        )


@dataclass
class MountainPeak:
    """A single tall conical peak — for hero summit shots. Reads as a
    distinct mountain rising above the base. Use sparingly; multiple
    peaks should usually be MesaCluster or AlpineBase + a few peaks."""

    center: tuple[float, float] = (0.0, 0.0)
    height: float = 25.0
    base_radius: float = 14.0
    peak_radius: float = 1.5
    blend: float = 4.0

    def to_spec(self, extent, seed):
        # A capsule from base to apex isn't ideal (cylindrical); we want
        # a cone. Approximate as a tapered stack of two cylinders for
        # simplicity. Not exact but reads correctly under marching cubes.
        cx, cy = self.center
        h = self.height
        # Wide base cylinder (lower half) + narrow upper cylinder (upper
        # half) gives a 2-step cone silhouette.
        lower = sdf_lib.cylinder(
            radius=self.base_radius, height=h * 0.4,
            center=(cx, cy, h * 0.2),
        )
        upper = sdf_lib.cylinder(
            radius=(self.base_radius + self.peak_radius) * 0.5, height=h * 0.4,
            center=(cx, cy, h * 0.6),
        )
        tip = sdf_lib.cylinder(
            radius=self.peak_radius, height=h * 0.2,
            center=(cx, cy, h * 0.9),
        )
        peak_sdf = sdf_lib.union(lower, upper, tip)

        def make_h(prev_h: HeightFn) -> HeightFn:
            def h_with_peak(x: np.ndarray, y: np.ndarray) -> np.ndarray:
                base_h = prev_h(x, y)
                r = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)
                cone_h = np.maximum(0.0, h * (1.0 - r / self.base_radius))
                return np.maximum(base_h, base_h + cone_h)

            return h_with_peak

        return FeatureSpec(
            sdf=peak_sdf, op="smooth_union", blend=self.blend,
            height_modifier=make_h,
            keep_out_zones=[(cx, cy, self.base_radius * 0.7)],
        )


@dataclass
class IslandCluster:
    """N rounded dome-shaped islands rising out of an ocean base.

    Reads as an archipelago: each island is a wide, low-relief dome
    (sphere-derived) so the silhouette is rounded rather than the sheer
    cliffs of MesaCluster. Place above an OceanBase to get the
    classic "island poking out of water" composition.

    Heights are above the base water level; radii are the visual
    above-water radius. The underlying sphere is wider than that so the
    shoreline transitions smoothly.
    """

    n: int = 6
    height_range: tuple[float, float] = (1.5, 4.5)
    radius_range: tuple[float, float] = (5.0, 10.0)
    blend: float = 1.5
    spread_radius: float = 30.0       # islands stay within this radius of center
    keep_out_radius: float = 4.0      # min spacing between island centers (extra)

    def to_spec(self, extent, seed):
        rng = random.Random(seed * 1000 + 4)
        islands: list[dict] = []
        attempts = 0
        while len(islands) < self.n and attempts < self.n * 30:
            attempts += 1
            # Polar sampling within spread_radius — islands cluster near
            # the center rather than scattering to the corners.
            theta = rng.uniform(0, 2 * math.pi)
            r = rng.uniform(0, self.spread_radius)
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

        # SDF: each island is a sphere whose center sits BELOW water so the
        # cap above z=0 has the chosen height + radius proportions.
        spheres: list = []
        for i in islands:
            # Sphere of radius R centered at z = h - R gives a cap
            # extending from z=0 up to z=h, with above-water radius
            # ≈ sqrt(R² − (R−h)²) = sqrt(2 R h − h²).
            # We pick R so that radius_above_water ≈ i["r"]:
            # i["r"]² = 2 R i["h"] − i["h"]² → R = (i["r"]² + i["h"]²) / (2 i["h"])
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
                    # Smooth dome falloff — peak at center, 0 at radius.
                    mask = _smoothstep(1.0 - d_norm)
                    out = np.maximum(out, base_h + i["h"] * mask)
                return out

            return h_with_islands

        # Scatter zones — islands ARE where caller-side scattering should
        # spawn assets (trees, boulders, houses). Use a slightly inset
        # radius so trees don't clip off the dome edge.
        scatter = [(i["x"], i["y"], i["r"] * 0.7) for i in islands]
        return FeatureSpec(
            sdf=island_sdf, op="smooth_union", blend=self.blend,
            height_modifier=make_h,
            scatter_zones=scatter,
        )


@dataclass
class Cliff:
    """A vertical drop along a line — half the extent is N meters higher
    than the other half. Useful for coastal cliffs, table-mountain edges,
    canyon walls.

    `axis="x"` means the cliff runs along Y (climbing in +X). `position`
    is the X (or Y, for axis="y") coordinate of the cliff line. `side`
    is which half is raised: "high_x_pos" / "high_x_neg" / "high_y_pos"
    / "high_y_neg".
    """

    height: float = 6.0
    axis: str = "x"
    position: float = 0.0
    side: str = "high_x_pos"
    blend: float = 1.5

    def to_spec(self, extent, seed):
        sx, sy = extent
        # Build a half-space box that adds `height` on the chosen side.
        # We fake "infinite half-space" with a giant box.
        if self.side == "high_x_pos":
            cliff_box = sdf_lib.box(
                size=(sx, sy * 2, self.height * 2),
                center=(self.position + sx * 0.5, 0.0, self.height * 0.5),
            )
        elif self.side == "high_x_neg":
            cliff_box = sdf_lib.box(
                size=(sx, sy * 2, self.height * 2),
                center=(self.position - sx * 0.5, 0.0, self.height * 0.5),
            )
        elif self.side == "high_y_pos":
            cliff_box = sdf_lib.box(
                size=(sx * 2, sy, self.height * 2),
                center=(0.0, self.position + sy * 0.5, self.height * 0.5),
            )
        elif self.side == "high_y_neg":
            cliff_box = sdf_lib.box(
                size=(sx * 2, sy, self.height * 2),
                center=(0.0, self.position - sy * 0.5, self.height * 0.5),
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
                    raised = (x > self.position).astype(np.float32) * self.height
                elif self.side == "high_x_neg":
                    raised = (x < self.position).astype(np.float32) * self.height
                elif self.side == "high_y_pos":
                    raised = (y > self.position).astype(np.float32) * self.height
                else:  # high_y_neg
                    raised = (y < self.position).astype(np.float32) * self.height
                return base_h + raised

            return h_with_cliff

        return FeatureSpec(
            sdf=cliff_box, op="smooth_union", blend=self.blend,
            height_modifier=make_h,
        )

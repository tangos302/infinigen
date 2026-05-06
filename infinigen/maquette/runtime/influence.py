"""Constraint-aware terrain shaping primitives.

Exposes a small set of numpy operators that bend a heightfield to fit
known scene composition — hero plateaus, path corridors, water basins.
The build script declares a ``Composition`` up-front and passes it into
``make_eroded_terrain``; the heightfield synthesis blends the operators
into the base noise after erosion runs (with hero/path footprints
optionally masked out of the erosion pass so they don't get washed back
into noise).

Design constraints:
  * Idempotent: same composition + seed → same heightmap.
  * Pure numpy: no Blender / scipy / dataclass-only deps so the module
    imports cleanly outside Blender for tests.
  * LLM-friendly surface: 4 named primitives, all accepting world-XY
    coordinates so the brief stays terse.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Sequence

import numpy as np


# ───────────────────────── Composition API ──────────────────────────

@dataclass
class Hero:
    """A hero landmark whose footprint shapes the terrain.

    ``radius`` defines the outer extent of the influence. ``target_z``
    forces a specific elevation; pass ``None`` to flatten toward the
    natural terrain height at the center (the LLM rarely wants to
    specify Z explicitly). ``hardness`` controls the falloff curve:
    1.0 = soft Gaussian dome, 2.0 = sharp plateau with cliff edges
    (mesa, fortress base), 0.5 = very gradual blend.
    """
    cx: float
    cy: float
    radius: float
    target_z: float | None = None
    # Default hardness 1.2 (Gaussian dome → soft cliff edges) for the
    # painterly Sky-CotL look. 2.0 = mesa-like sharp plateau (used for
    # fortress / monastery bases when the prompt explicitly calls for it).
    hardness: float = 1.2
    # ``lift`` adds elevation above the local terrain BEFORE flattening,
    # so the plateau sits ABOVE its surroundings. Default 0.0 = pure
    # flatten (smooth out roughness, no elevation change). Use 1-3 BU
    # for subtle elevated plateaus, 4+ BU for visible mesa lifts.
    # Cap ``lift / radius < 0.4`` to avoid Gaussian-splat reading.
    lift: float = 0.0
    # ``mode``: "flatten" (default — destructive, plateau replaces local
    # terrain via flatten_radial) or "dome" (additive — Gaussian dome
    # added on top of existing terrain, no destruction). Use "dome" for
    # painterly soft heroes that should blend INTO the terrain rather
    # than carve a flat shelf out of it. ``lift`` becomes the dome
    # height in dome mode.
    mode: str = "flatten"


@dataclass
class Pathway:
    """A walkable corridor that shapes the terrain into a saddle along
    its polyline. Named ``Pathway`` rather than ``Path`` to avoid
    shadowing ``pathlib.Path`` when both are imported in the build
    script (the LLM uses ``pathlib.Path`` for output dirs).

    ``width`` is the full corridor width in BU. Heights inside the
    corridor are interpolated linearly along the polyline from the
    natural height at each waypoint, with ``depth`` subtracted (pass
    -0.05 for a slight worn track, 0.0 for level cobble, +0.0 for
    boardwalk). ``blend`` is the soft falloff distance outside the
    corridor edge.
    """
    waypoints: Sequence[tuple[float, float]]
    width: float = 2.5
    depth: float = 0.0
    blend: float = 1.5
    # Visual archetype — drives the colour painted into the corridor's
    # vertex-colour band. ``dirt`` (warm tan), ``stone`` (cool grey),
    # ``wood`` (boardwalk plank), ``sand`` (desert track). Anything else
    # falls through to dirt. The LLM picks this from prompt context;
    # match the ``# PATH_ARCHETYPE`` tag for consistency.
    archetype: str = "dirt"


@dataclass
class Ridge:
    """A sweeping primary ridge that gives the scene structural backbone.

    Sky CotL scenes always frame ONE dominant silhouette curve — the
    eye reads it as the scene's spine. This primitive lays a Catmull-Rom-
    smoothed curve through your waypoints and adds Gaussian elevation
    along it, so the heightmap has a long flowing ridge instead of
    isolated peaks.

    Use this BEFORE heroes — heroes can sit on top of the ridge for
    even more dramatic silhouettes. Pair with broad, soft heroes
    (``Hero.hardness=1.0``).

    ``height`` is the peak elevation along the centerline (in BU above
    the surrounding terrain). ``width`` is the falloff radius — at this
    distance from the centerline, contribution is ~37 % (Gaussian).
    ``hardness`` shapes the Gaussian: 1.0 = soft dome, 1.5 = standard,
    2.5 = sharp ridge.
    """
    waypoints: Sequence[tuple[float, float]]
    # Ridge height was 8 BU (1/40 of a 320 BU world span) — barely
    # visible as a bump. Bumped to 16 BU so the ridge reads as a
    # genuine silhouette feature without going Skyrim-vertical.
    height: float = 16.0
    width: float = 25.0
    hardness: float = 1.4


@dataclass
class Water:
    """A water body that carves a basin into the terrain.

    Basin is a smooth bowl centered at ``(cx, cy)`` of ``radius`` BU,
    dipping ``depth`` below the natural surface at the perimeter.
    """
    cx: float
    cy: float
    radius: float
    depth: float = 0.4


@dataclass
class Composition:
    """Bundle of constraints applied to a heightfield before meshing.

    Pass to ``make_eroded_terrain(..., composition=Composition(...))``.
    The heightmap is shaped to match these constraints AFTER the base
    erosion pass, so hero plateaus / path saddles / water basins survive
    the erosion as authored.
    """
    heroes: list[Hero] = field(default_factory=list)
    paths: list[Pathway] = field(default_factory=list)
    ridges: list[Ridge] = field(default_factory=list)
    water: Water | None = None
    # SDF landmark forms (Hoodoo / Arch / Pillar) — full 3D shapes
    # built via marching cubes and added as separate Blender objects.
    # Use these for distinctive features the heightmap can't represent
    # (overhangs, mushroom caps, gateway openings). Imported lazily
    # since ``runtime.landmarks`` depends on this module.
    landmarks: list = field(default_factory=list)


# ───────────────────────── Math primitives ──────────────────────────

def _smoothstep(edge0: float, edge1: float, x: np.ndarray) -> np.ndarray:
    """Cubic smoothstep, vectorized. Returns 0 below ``edge0``, 1 above
    ``edge1``, smooth cubic transition in between."""
    if edge1 <= edge0:
        return np.where(x <= edge0, 0.0, 1.0).astype(np.float32)
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return (t * t * (3.0 - 2.0 * t)).astype(np.float32)


def _resample_catmull(waypoints: Sequence[tuple[float, float]],
                      *,
                      samples_per_segment: int = 16,
                      jitter: float = 0.0,
                      seed: int = 0) -> list[tuple[float, float]]:
    """Smooth a coarse LLM polyline into a dense centripetal Catmull-Rom
    curve, optionally perturbed along its binormal by a low-frequency
    sine so straight runs read as natural footpaths instead of laser
    cuts.

    Centripetal (alpha=0.5) Catmull-Rom avoids overshoot near sharp
    turns — the standard pitfall of uniform CR splines. End-anchor
    handling: duplicate the first/last point so the curve actually
    starts/ends on the user-given waypoints.

    ``jitter`` is the maximum binormal displacement in BU. Set 0 (or
    leave default) for ``stone`` archetype paths that should stay
    straight; 0.4 BU is a pleasant default for dirt trails.
    """
    pts = [tuple(map(float, p)) for p in waypoints]
    if len(pts) < 2:
        return pts
    if len(pts) == 2:
        # Two-point case has no curvature to interpolate; emit
        # straight-line samples then jitter.
        ax, ay = pts[0]
        bx, by = pts[1]
        out: list[tuple[float, float]] = []
        n = max(2, samples_per_segment)
        for i in range(n + 1):
            t = i / n
            out.append((ax + (bx - ax) * t, ay + (by - ay) * t))
        if jitter > 0:
            out = _jitter_along_binormal(out, jitter=jitter, seed=seed)
        return out

    # Pad with duplicated endpoints so segment 0 and segment n are
    # well-defined for the 4-point CR formula.
    padded = [pts[0]] + pts + [pts[-1]]
    out2: list[tuple[float, float]] = []

    def _cr(p0, p1, p2, p3, t, alpha=0.5):
        # Compute knot deltas using the centripetal exponent.
        def _d(a, b):
            return max(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5, 1e-3) ** alpha
        t01 = _d(p0, p1)
        t12 = _d(p1, p2)
        t23 = _d(p2, p3)
        t = t01 + (t12 * t)  # parameterise t in the [t01, t01+t12] segment
        # Standard non-uniform CR via De Casteljau.
        def _lerp(a, b, t1, t2, ts):
            den = (t2 - t1) if abs(t2 - t1) > 1e-9 else 1e-9
            f = (ts - t1) / den
            return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
        A1 = _lerp(p0, p1, 0.0, t01, t)
        A2 = _lerp(p1, p2, t01, t01 + t12, t)
        A3 = _lerp(p2, p3, t01 + t12, t01 + t12 + t23, t)
        B1 = _lerp(A1, A2, 0.0, t01 + t12, t)
        B2 = _lerp(A2, A3, t01, t01 + t12 + t23, t)
        return _lerp(B1, B2, t01, t01 + t12, t)

    for i in range(len(padded) - 3):
        n = max(2, samples_per_segment)
        for s in range(n):
            t = s / n
            out2.append(_cr(padded[i], padded[i + 1], padded[i + 2], padded[i + 3], t))
    out2.append(pts[-1])

    if jitter > 0:
        out2 = _jitter_along_binormal(out2, jitter=jitter, seed=seed)
    return out2


def _jitter_along_binormal(pts: list[tuple[float, float]], *,
                            jitter: float, seed: int) -> list[tuple[float, float]]:
    """Perturb each interior point along its segment's binormal by a
    low-frequency sine. Endpoints are anchored. Seed makes it
    deterministic; same seed + same input → same output.
    """
    if len(pts) < 3 or jitter <= 0:
        return pts
    out = [pts[0]]
    # Phase + frequency derived from seed so each path's wiggle is
    # different but reproducible.
    phase = (seed * 0.137) % 6.2831853
    freq = 0.65 + (seed % 11) * 0.04
    for i in range(1, len(pts) - 1):
        ax, ay = pts[i - 1]
        bx, by = pts[i + 1]
        # Tangent direction; binormal is the perpendicular in 2D.
        tx, ty = bx - ax, by - ay
        ll = (tx * tx + ty * ty) ** 0.5 + 1e-9
        nx, ny = -ty / ll, tx / ll  # rotate tangent 90°
        # Sine with per-index phase advance — produces an organic wave.
        amp = jitter * (0.6 + 0.4 * np.cos(phase + i * freq))
        amp *= np.sin(phase * 2.0 + i * 0.93)  # second harmonic
        px, py = pts[i]
        out.append((float(px + nx * amp), float(py + ny * amp)))
    out.append(pts[-1])
    return out


def _polyline_distance(X: np.ndarray, Y: np.ndarray,
                       waypoints: Sequence[tuple[float, float]]) -> np.ndarray:
    """Per-cell minimum distance to the polyline. Returns same-shape grid.

    Uses parametric segment-distance with vectorized numpy ops; complexity
    O(N² · K) for an N×N grid and K polyline segments.
    """
    pts = np.asarray(list(waypoints), dtype=np.float32)
    if len(pts) == 0:
        return np.full(X.shape, np.inf, dtype=np.float32)
    if len(pts) == 1:
        return np.hypot(X - float(pts[0, 0]), Y - float(pts[0, 1])).astype(np.float32)
    min_d = np.full(X.shape, np.inf, dtype=np.float32)
    for i in range(len(pts) - 1):
        ax, ay = float(pts[i, 0]), float(pts[i, 1])
        bx, by = float(pts[i + 1, 0]), float(pts[i + 1, 1])
        dx, dy = bx - ax, by - ay
        ll = dx * dx + dy * dy + 1e-9
        t = np.clip(((X - ax) * dx + (Y - ay) * dy) / ll, 0.0, 1.0)
        cx = ax + t * dx
        cy = ay + t * dy
        d = np.hypot(X - cx, Y - cy)
        min_d = np.minimum(min_d, d)
    return min_d.astype(np.float32)


def _polyline_height(X: np.ndarray, Y: np.ndarray,
                     waypoints: Sequence[tuple[float, float]],
                     waypoint_z: np.ndarray) -> np.ndarray:
    """Per-cell linearly-interpolated waypoint height along the polyline.

    For each cell, find the nearest segment, project onto it, and lerp
    the segment's start and end z values. Used by ``valley_along`` so
    the carved corridor follows a natural sloping path between
    waypoints.
    """
    pts = np.asarray(list(waypoints), dtype=np.float32)
    if len(pts) == 0:
        return np.zeros(X.shape, dtype=np.float32)
    if len(pts) == 1:
        return np.full(X.shape, float(waypoint_z[0]), dtype=np.float32)
    out = np.zeros(X.shape, dtype=np.float32)
    min_d = np.full(X.shape, np.inf, dtype=np.float32)
    for i in range(len(pts) - 1):
        ax, ay = float(pts[i, 0]), float(pts[i, 1])
        bx, by = float(pts[i + 1, 0]), float(pts[i + 1, 1])
        dx, dy = bx - ax, by - ay
        ll = dx * dx + dy * dy + 1e-9
        t = np.clip(((X - ax) * dx + (Y - ay) * dy) / ll, 0.0, 1.0)
        cx = ax + t * dx
        cy = ay + t * dy
        d = np.hypot(X - cx, Y - cy)
        seg_z = float(waypoint_z[i]) * (1.0 - t) + float(waypoint_z[i + 1]) * t
        mask = d < min_d
        out = np.where(mask, seg_z, out)
        min_d = np.where(mask, d, min_d)
    return out.astype(np.float32)


# ───────────────────────── Influence operators ──────────────────────────

def flatten_radial(H: np.ndarray, X: np.ndarray, Y: np.ndarray,
                   cx: float, cy: float, radius: float,
                   target_z: float, hardness: float = 2.0) -> np.ndarray:
    """Flatten a circular footprint toward ``target_z`` with falloff.

    Influence weight is ``exp(-(d/radius)^hardness)`` where ``d`` is the
    Euclidean XY distance to ``(cx, cy)``. ``hardness=2.0`` gives a
    Gaussian dome; higher values produce flatter centers with sharper
    edges. Returns a NEW heightfield (does not mutate ``H``).
    """
    d = np.hypot(X - cx, Y - cy) / max(float(radius), 1e-6)
    w = np.exp(-(d ** float(hardness))).astype(np.float32)
    return (H * (1.0 - w) + float(target_z) * w).astype(np.float32)


def valley_along(H: np.ndarray, X: np.ndarray, Y: np.ndarray,
                 waypoints: Sequence[tuple[float, float]],
                 width: float = 2.5,
                 depth: float = 0.0,
                 blend: float = 1.5,
                 base_height_at: Callable[[float, float], float] | None = None) -> np.ndarray:
    """Carve a smooth saddle along a polyline.

    Inside ``width/2`` from the centerline, height is fully replaced by
    the linearly-interpolated waypoint heights (sampled via
    ``base_height_at``) shifted by ``depth``. From ``width/2`` to
    ``width/2 + blend``, the influence smoothsteps back to the base.

    ``base_height_at`` is a callable like ``lambda x, y: float`` — used
    to sample waypoint heights so the path follows the surrounding
    terrain rather than imposing an arbitrary Z. If ``None``, the
    function is a no-op (returns ``H`` unchanged).
    """
    pts = list(waypoints)
    if len(pts) < 2 or base_height_at is None:
        return H
    waypoint_z = np.array(
        [float(base_height_at(x, y)) + float(depth) for x, y in pts],
        dtype=np.float32,
    )
    d = _polyline_distance(X, Y, pts)
    target_z = _polyline_height(X, Y, pts, waypoint_z)
    half = float(width) * 0.5
    w = (1.0 - _smoothstep(half, half + float(blend), d)).astype(np.float32)
    return (H * (1.0 - w) + target_z * w).astype(np.float32)


def ridge_along(H: np.ndarray, X: np.ndarray, Y: np.ndarray,
                waypoints: Sequence[tuple[float, float]],
                *,
                height: float = 8.0,
                width: float = 25.0,
                hardness: float = 1.4) -> np.ndarray:
    """Add a sweeping Gaussian-falloff ridge along a polyline.

    For each cell, distance to the polyline is ``d``; elevation
    contribution is ``height * exp(-(d/width)^hardness)``. Adds (does
    not replace) so the ridge layers on top of existing terrain.

    Use this for the scene's structural backbone — Sky CotL's spine
    ridges. Pass through the same Catmull-Rom resampling we use for
    paths so the silhouette is smooth.
    """
    pts = list(waypoints)
    if len(pts) < 1:
        return H
    smoothed = _resample_catmull(pts, samples_per_segment=12, jitter=0.0)
    d = _polyline_distance(X, Y, smoothed) / max(float(width), 1e-6)
    contrib = (np.exp(-(d ** float(hardness))) * float(height)).astype(np.float32)
    return (H + contrib).astype(np.float32)


def basin_radial(H: np.ndarray, X: np.ndarray, Y: np.ndarray,
                 cx: float, cy: float, radius: float,
                 depth: float = 0.4) -> np.ndarray:
    """Carve a rounded basin centered at ``(cx, cy)``.

    Basin floor is ``depth`` BU below the natural terrain at the center,
    rising along a half-cosine to meet the surrounding surface at
    ``radius``. Useful for oasis pools, lake basins, courtyard plazas.
    """
    d = np.hypot(X - cx, Y - cy) / max(float(radius), 1e-6)
    w = np.where(d < 1.0, 0.5 * (1.0 + np.cos(np.pi * d)), 0.0).astype(np.float32)
    return (H - float(depth) * w).astype(np.float32)


def clamp_above(H: np.ndarray, mask: np.ndarray, min_z: float) -> np.ndarray:
    """Lift any cell where ``mask > 0`` to at least ``min_z``."""
    return np.where(mask > 0, np.maximum(H, float(min_z)), H).astype(np.float32)


# ───────────────────────── Composition driver ──────────────────────────

def apply_composition(H: np.ndarray, X: np.ndarray, Y: np.ndarray,
                       comp: Composition,
                       base_height_at: Callable[[float, float], float]) -> np.ndarray:
    """Run all constraints in canonical order and return the new H.

    Order matters:
      0. **Ridges first** — sweeping backbone shapes for the scene
         silhouette. Heroes can then sit on top.
      1. Heroes (so paths thread through plateaus, not around them).
      2. Paths (using post-hero heights for waypoint sampling so the
         path lands ON the plateau surface, not under it).
      3. Water last (so the basin can dip below paths that cross it
         without the path carving fighting back).

    ``base_height_at`` samples the *pre-composition* heightmap; it's
    used to resolve hero ``target_z=None`` to the natural local height.
    Path waypoints are re-sampled internally from the running ``H_out``
    so they ride the plateaus.
    """
    if comp is None:
        return H
    H_out = H.astype(np.float32)
    for ridge in comp.ridges:
        H_out = ridge_along(H_out, X, Y, ridge.waypoints,
                            height=ridge.height, width=ridge.width,
                            hardness=ridge.hardness)

    # If ridges modified the terrain, build a post-ridge sampler so
    # heroes flatten toward the *post-ridge* height (otherwise a hero
    # on a ridge would carve back to the original valley elevation).
    def _post_ridge_sample(x: float, y: float) -> float:
        res = H_out.shape[0]
        half = float((np.max(X) - np.min(X)) * 0.5)
        fi = (x + half) / (2.0 * half) * (res - 1)
        fj = (y + half) / (2.0 * half) * (res - 1)
        i = int(np.clip(round(fi), 0, res - 1))
        j = int(np.clip(round(fj), 0, res - 1))
        return float(H_out[j, i])
    hero_height_sampler = _post_ridge_sample if comp.ridges else base_height_at

    for hero in comp.heroes:
        mode = getattr(hero, "mode", "flatten")
        if mode == "dome":
            # Additive Gaussian — adds a dome on top of existing terrain,
            # no destruction. Reads as a soft hill the building sits on
            # rather than a carved mesa. ``lift`` is the peak height.
            d = np.hypot(X - hero.cx, Y - hero.cy) / max(float(hero.radius), 1e-6)
            dome = np.exp(-(d ** float(hero.hardness))).astype(np.float32)
            H_out = (H_out + float(getattr(hero, "lift", 1.5)) * dome).astype(np.float32)
        else:
            # Default: flatten (destructive). Plateau replaces local
            # terrain at target_z + lift.
            target_z = hero.target_z
            if target_z is None:
                target_z = float(hero_height_sampler(hero.cx, hero.cy))
            target_z += float(getattr(hero, "lift", 0.0))
            H_out = flatten_radial(H_out, X, Y, hero.cx, hero.cy,
                                   hero.radius, target_z, hero.hardness)
    if comp.paths:
        res = H_out.shape[0]
        # Recover half-extent from grid (X / Y are linspace -size..+size).
        half_extent = float((np.max(X) - np.min(X)) * 0.5)

        def _sample_h(x: float, y: float) -> float:
            fi = (x + half_extent) / (2.0 * half_extent) * (res - 1)
            fj = (y + half_extent) / (2.0 * half_extent) * (res - 1)
            i = int(np.clip(round(fi), 0, res - 1))
            j = int(np.clip(round(fj), 0, res - 1))
            return float(H_out[j, i])

        for path_idx, path in enumerate(comp.paths):
            # Zero-depth path → colour-only band (apply_path_tint paints
            # the corridor; no height carving). Sky paths are visible
            # paint, not trenches. Skip valley_along entirely so we
            # don't introduce resampling drift on what should be a
            # geometric no-op.
            if abs(float(path.depth)) < 1e-4:
                continue
            # Resample with centripetal Catmull-Rom + binormal jitter so
            # straight LLM polylines bend organically. Stone roads stay
            # rigid (Romans graded their roads) — no jitter for stone.
            jitter = 0.0 if path.archetype == "stone" else 0.45
            smoothed = _resample_catmull(
                path.waypoints,
                samples_per_segment=12,
                jitter=jitter,
                seed=path_idx * 7919 + 13,
            )
            H_out = valley_along(H_out, X, Y, smoothed,
                                 width=path.width, depth=path.depth,
                                 blend=path.blend,
                                 base_height_at=_sample_h)
    if comp.water is not None:
        w = comp.water
        H_out = basin_radial(H_out, X, Y, w.cx, w.cy, w.radius, w.depth)
    return H_out


# Path archetype → linear-RGB tint applied inside the corridor mask.
# These are sRGB-intent values; eroded_terrain.py converts via the same
# linear pipeline as the biome palette before writing to vertex colours.
_PATH_COLORS: dict[str, tuple[float, float, float]] = {
    "dirt":  (0.42, 0.32, 0.20),  # warm tan, slightly damp
    "stone": (0.50, 0.48, 0.44),  # cool grey cobble
    "wood":  (0.45, 0.30, 0.18),  # boardwalk plank
    "sand":  (0.78, 0.68, 0.46),  # desert track, bright
}


def apply_plateau_edge_ring(col: np.ndarray, X: np.ndarray, Y: np.ndarray,
                             comp: Composition | None,
                             *,
                             ring_width: float = 1.5,
                             darken: float = 0.18) -> np.ndarray:
    """Paint a thin darker ring around each Hero plateau perimeter so the
    plateau reads as a soft cliff rather than a stack of pancakes.

    For each Hero, builds a smooth annulus mask at radius ``hero.radius``,
    width ``ring_width`` BU, and multiplies ``col`` by ``(1 - darken * mask)``.
    No-op when no heroes are passed.
    """
    if comp is None or not comp.heroes:
        return col
    import numpy as _np
    out = _np.array(col, dtype=_np.float32, copy=True)
    for hero in comp.heroes:
        d = _np.hypot(X - hero.cx, Y - hero.cy)
        # Annulus: 1 at r=radius, 0 outside [radius - ring_width, radius + ring_width]
        inner = _smoothstep(hero.radius - ring_width, hero.radius, d)
        outer = 1.0 - _smoothstep(hero.radius, hero.radius + ring_width, d)
        ring = (inner * outer).astype(_np.float32)
        out = out * (1.0 - float(darken) * ring[..., None])
    return _np.clip(out, 0, 1)


def apply_path_tint(col: np.ndarray, X: np.ndarray, Y: np.ndarray,
                    comp: Composition | None,
                    *,
                    strength: float = 0.85) -> np.ndarray:
    """Paint each ``Pathway`` corridor with its archetype colour.

    For every cell within ``width/2`` of the path's polyline, the
    biome colour is lerped toward the archetype's tint by
    ``mask * strength``. Outside the corridor and through the ``blend``
    feather, no change. Returns a NEW colour grid; does not mutate
    ``col``. Operates in linear RGB to match the eroded_terrain
    palette pipeline.
    """
    if comp is None or not comp.paths:
        return col
    import numpy as _np
    out = _np.array(col, dtype=_np.float32, copy=True)
    for path_idx, path in enumerate(comp.paths):
        # Match the resample done in ``apply_composition`` so the colour
        # band follows the carved curve, not the raw LLM polyline (which
        # for two-waypoint paths would still read as a straight line of
        # tinted cells).
        jitter = 0.0 if path.archetype == "stone" else 0.45
        smoothed = _resample_catmull(
            path.waypoints,
            samples_per_segment=12,
            jitter=jitter,
            seed=path_idx * 7919 + 13,
        )
        d = _polyline_distance(X, Y, smoothed)
        half = float(path.width) * 0.5
        mask = 1.0 - _smoothstep(half, half + float(path.blend), d)
        w = (mask * float(strength))[..., None]
        rgb_srgb = _PATH_COLORS.get(path.archetype, _PATH_COLORS["dirt"])
        # Convert sRGB-intent to linear so the path colour sits on the
        # same scale as the biome palette (which is already linear).
        target = _np.array([_srgb_to_linear(c) for c in rgb_srgb], dtype=_np.float32)
        out = out * (1.0 - w) + target * w
    return out.astype(_np.float32)


def _srgb_to_linear(c: float) -> float:
    """Local copy of the sRGB→linear conversion (the eroded_terrain
    palette uses the same formula). Kept here so influence.py stays
    free of cross-module imports."""
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def erosion_mask(X: np.ndarray, Y: np.ndarray,
                 comp: Composition | None) -> np.ndarray:
    """Return a (N, N) mask in [0, 1]: 0 freezes erosion (hero footprint
    + path corridor), 1 lets it run normally. Multiply uplift /
    erodibility by this mask in the Fastscape pass so plateaus and
    saddles don't get washed back into the noise.
    """
    if comp is None:
        return np.ones_like(X, dtype=np.float32)
    mask = np.ones_like(X, dtype=np.float32)
    for hero in comp.heroes:
        d = np.hypot(X - hero.cx, Y - hero.cy) / max(float(hero.radius), 1e-6)
        m = (1.0 - np.exp(-(d ** float(hero.hardness)))).astype(np.float32)
        mask = np.minimum(mask, m)
    for path in comp.paths:
        d = _polyline_distance(X, Y, path.waypoints)
        half = float(path.width) * 0.5
        m = _smoothstep(half, half + float(path.blend), d)
        mask = np.minimum(mask, m)
    return mask

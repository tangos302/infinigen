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
    hardness: float = 2.0


@dataclass
class Path:
    """A walkable corridor that shapes the terrain into a saddle along
    its polyline.

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
    paths: list[Path] = field(default_factory=list)
    water: Water | None = None


# ───────────────────────── Math primitives ──────────────────────────

def _smoothstep(edge0: float, edge1: float, x: np.ndarray) -> np.ndarray:
    """Cubic smoothstep, vectorized. Returns 0 below ``edge0``, 1 above
    ``edge1``, smooth cubic transition in between."""
    if edge1 <= edge0:
        return np.where(x <= edge0, 0.0, 1.0).astype(np.float32)
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return (t * t * (3.0 - 2.0 * t)).astype(np.float32)


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
      1. Heroes first (so paths thread through plateaus, not around them).
      2. Paths next (using post-hero heights for waypoint sampling so the
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
    for hero in comp.heroes:
        target_z = hero.target_z
        if target_z is None:
            target_z = float(base_height_at(hero.cx, hero.cy))
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

        for path in comp.paths:
            H_out = valley_along(H_out, X, Y, path.waypoints,
                                 width=path.width, depth=path.depth,
                                 blend=path.blend,
                                 base_height_at=_sample_h)
    if comp.water is not None:
        w = comp.water
        H_out = basin_radial(H_out, X, Y, w.cx, w.cy, w.radius, w.depth)
    return H_out


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

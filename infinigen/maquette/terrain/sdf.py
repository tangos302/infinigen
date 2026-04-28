"""Tiny signed-distance-function library.

A compact, dependency-free SDF library — enough primitives to express
ground + mesas + ravines + caves + tunnels by composition. We could have
pulled fogleman/sdf, but a 200-line homegrown library lets us control
semantics (consistent Vec3 conventions, vectorized over numpy arrays of
sample points, no surprise allocations) and avoids an external GitHub
dependency.

Convention:
  - All primitives are functions that return a callable
    `f(p: np.ndarray[N, 3]) -> np.ndarray[N]` returning the signed
    distance to the surface, negative inside.
  - `f(p)` is broadcast-friendly: pass any (..., 3) array and get the
    matching scalar shape back.
  - Composition operators (union, subtract, etc.) take SDFs and return
    a new SDF. Smooth variants take a `k` blend radius (m).

Reference: Inigo Quilez's SDF compendium
(https://iquilezles.org/articles/distfunctions/) — the math is standard.
"""

from __future__ import annotations

from typing import Callable, Sequence

import numpy as np


SDF = Callable[[np.ndarray], np.ndarray]
Vec3 = tuple[float, float, float]


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


def sphere(radius: float, center: Vec3 = (0.0, 0.0, 0.0)) -> SDF:
    """A sphere of given radius centered at `center`."""
    c = np.asarray(center, dtype=np.float32)

    def f(p: np.ndarray) -> np.ndarray:
        return np.linalg.norm(p - c, axis=-1) - radius

    return f


def box(size: Vec3, center: Vec3 = (0.0, 0.0, 0.0)) -> SDF:
    """An axis-aligned box of full extents `size` centered at `center`.

    Slightly rounded — uses iq's standard `length(max(q,0)) + min(max(q),0)`
    so corners are technically a touch sharp but distance remains
    Lipschitz, which marching cubes prefers.
    """
    half = np.asarray(size, dtype=np.float32) * 0.5
    c = np.asarray(center, dtype=np.float32)

    def f(p: np.ndarray) -> np.ndarray:
        q = np.abs(p - c) - half
        outside = np.linalg.norm(np.maximum(q, 0.0), axis=-1)
        inside = np.minimum(np.max(q, axis=-1), 0.0)
        return outside + inside

    return f


def cylinder(radius: float, height: float, center: Vec3 = (0.0, 0.0, 0.0)) -> SDF:
    """A z-axis-aligned cylinder."""
    c = np.asarray(center, dtype=np.float32)
    half_h = height * 0.5

    def f(p: np.ndarray) -> np.ndarray:
        d = p - c
        radial = np.linalg.norm(d[..., :2], axis=-1) - radius
        vertical = np.abs(d[..., 2]) - half_h
        outside = np.linalg.norm(
            np.stack([np.maximum(radial, 0.0), np.maximum(vertical, 0.0)], axis=-1),
            axis=-1,
        )
        inside = np.minimum(np.maximum(radial, vertical), 0.0)
        return outside + inside

    return f


def plane(normal: Vec3 = (0.0, 0.0, 1.0), offset: float = 0.0) -> SDF:
    """An infinite plane. `normal` should be unit length; `offset` is the
    signed distance from origin along the normal. Default = ground at z=0."""
    n = np.asarray(normal, dtype=np.float32)
    n = n / np.linalg.norm(n)

    def f(p: np.ndarray) -> np.ndarray:
        return np.einsum("...i,i->...", p, n) - offset

    return f


def capsule(a: Vec3, b: Vec3, radius: float) -> SDF:
    """A capsule from segment `a`→`b` with given radius."""
    a_ = np.asarray(a, dtype=np.float32)
    b_ = np.asarray(b, dtype=np.float32)
    ab = b_ - a_
    ab_len2 = float(np.dot(ab, ab))

    def f(p: np.ndarray) -> np.ndarray:
        ap = p - a_
        # Project ap onto ab, clamp to [0, 1] = parameter along segment
        t = np.einsum("...i,i->...", ap, ab) / max(ab_len2, 1e-9)
        t = np.clip(t, 0.0, 1.0)
        closest = a_ + t[..., None] * ab
        return np.linalg.norm(p - closest, axis=-1) - radius

    return f


def line_xy(
    points_xy: Sequence[Vec3],
    radius: float,
    z: float = 0.0,
    z_extent: float = 1e3,
) -> SDF:
    """A polyline-in-XY swept as a vertical capsule wall — useful for carving
    ravines. `points_xy` is a list of (x, y) (or (x, y, _) — z ignored).
    Distance is measured in XY only and the SDF is constant along Z (so
    the carved trench has vertical walls that go from -z_extent to
    +z_extent), matching how a ravine reads.

    `radius` = half-width of the trench. `z` shifts the SDF up/down for
    height-banded use cases; default 0 = the full vertical column.
    """
    pts = np.asarray([(p[0], p[1]) for p in points_xy], dtype=np.float32)
    if len(pts) < 2:
        raise ValueError("line_xy needs at least 2 points")

    def f(p: np.ndarray) -> np.ndarray:
        xy = p[..., :2]
        # Distance from each query point to each segment, take minimum.
        # Vectorized: compute distance from xy to every (a,b) segment.
        out = np.full(xy.shape[:-1], np.inf, dtype=np.float32)
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            ab = b - a
            ab_len2 = float(np.dot(ab, ab)) + 1e-9
            ap = xy - a
            t = np.einsum("...i,i->...", ap, ab) / ab_len2
            t = np.clip(t, 0.0, 1.0)
            closest = a + t[..., None] * ab
            d = np.linalg.norm(xy - closest, axis=-1)
            out = np.minimum(out, d)
        # Convert XY distance to a 3D capsule-along-Z: distance to the
        # vertical wall at radius `radius`. Z coordinate is mostly irrelevant
        # over [-z_extent, +z_extent], so we use a thin 2D-ish field.
        if z_extent < 1e3:
            z_dist = np.maximum(np.abs(p[..., 2] - z) - z_extent, 0.0)
            return np.sqrt((np.maximum(out - radius, 0.0)) ** 2 + z_dist ** 2) + np.minimum(
                np.maximum(out - radius, np.abs(p[..., 2] - z) - z_extent), 0.0
            )
        return out - radius

    return f


# ---------------------------------------------------------------------------
# Procedural noise — used to displace ground heights
# ---------------------------------------------------------------------------


def perlin_2d(
    seed: int = 0,
    period: float = 40.0,
    amplitude: float = 1.0,
    octaves: int = 2,
    persistence: float = 0.5,
) -> Callable[[np.ndarray, np.ndarray], np.ndarray]:
    """Smooth fractal-Brownian-motion noise on the XY plane.

    Per-cell value noise interpolated with a quintic smoothstep
    (Perlin's `6t⁵−15t⁴+10t³`) — first and second derivatives go to
    zero at cell boundaries, eliminating the ridge artifacts that
    plain bilinear interpolation produces. That's what gave the
    initial PoC its "spiky" desert-floor look.

    Defaults are tuned for a *dune-ish* desert look: long period (40m),
    only 2 octaves so high-frequency chatter is gone. Caller can pass
    octaves=1 for pure rolling dunes, or octaves=3+ for grittier terrain.
    """
    rng_master = np.random.default_rng(seed)
    octave_grids = []
    for o in range(octaves):
        side = max(8, int(64 / (2 ** o)))
        grid = rng_master.random((side, side), dtype=np.float32) * 2.0 - 1.0
        octave_grids.append(grid)

    def h(x: np.ndarray, y: np.ndarray) -> np.ndarray:
        total = np.zeros_like(x, dtype=np.float32)
        amp = amplitude
        per = period
        for grid in octave_grids:
            side = grid.shape[0]
            u = (x / per) % 1.0 * (side - 1)
            v = (y / per) % 1.0 * (side - 1)
            i = u.astype(np.int32)
            j = v.astype(np.int32)
            i1 = (i + 1) % side
            j1 = (j + 1) % side
            fu = u - i
            fv = v - j
            # Quintic smoothstep: derivatives vanish at the cell corners,
            # so adjacent cells join without visible seams.
            sfu = fu * fu * fu * (fu * (fu * 6 - 15) + 10)
            sfv = fv * fv * fv * (fv * (fv * 6 - 15) + 10)
            v00 = grid[j, i]
            v10 = grid[j, i1]
            v01 = grid[j1, i]
            v11 = grid[j1, i1]
            a = v00 * (1 - sfu) + v10 * sfu
            b = v01 * (1 - sfu) + v11 * sfu
            total += amp * (a * (1 - sfv) + b * sfv)
            amp *= persistence
            per *= 0.5
        return total

    return h


def height_field(
    height_fn: Callable[[np.ndarray, np.ndarray], np.ndarray],
) -> SDF:
    """Wrap an XY→Z function as a 3D SDF. The result is `f(p) = p.z - h(p.x, p.y)`,
    which is signed-distance-ish along the vertical axis (not a true Lipschitz
    distance, but marching cubes works correctly because the sign change is
    exactly at z = h(x, y))."""

    def f(p: np.ndarray) -> np.ndarray:
        return p[..., 2] - height_fn(p[..., 0], p[..., 1])

    return f


# ---------------------------------------------------------------------------
# Operators — set algebra on SDFs
# ---------------------------------------------------------------------------


def union(*sdfs: SDF) -> SDF:
    """`min` across all distances — set union, sharp seams."""
    if not sdfs:
        raise ValueError("union needs ≥1 sdf")

    def f(p: np.ndarray) -> np.ndarray:
        d = sdfs[0](p)
        for s in sdfs[1:]:
            d = np.minimum(d, s(p))
        return d

    return f


def subtract(a: SDF, b: SDF) -> SDF:
    """A minus B (carve B out of A). `max(a, -b)`."""

    def f(p: np.ndarray) -> np.ndarray:
        return np.maximum(a(p), -b(p))

    return f


def intersect(a: SDF, b: SDF) -> SDF:
    """A intersected with B."""

    def f(p: np.ndarray) -> np.ndarray:
        return np.maximum(a(p), b(p))

    return f


def smooth_union(k: float, *sdfs: SDF) -> SDF:
    """Smooth-min union — `k` is the blend radius in world meters. Soft
    seams between mesas + ground, etc."""
    if k <= 0:
        return union(*sdfs)
    if not sdfs:
        raise ValueError("smooth_union needs ≥1 sdf")

    def f(p: np.ndarray) -> np.ndarray:
        d = sdfs[0](p)
        for s in sdfs[1:]:
            db = s(p)
            h = np.clip(0.5 + 0.5 * (db - d) / k, 0.0, 1.0)
            d = (db * (1 - h) + d * h) - k * h * (1 - h)
        return d

    return f


def smooth_subtract(k: float, a: SDF, b: SDF) -> SDF:
    """Smooth A minus B — soft-edged ravine carve."""
    if k <= 0:
        return subtract(a, b)

    def f(p: np.ndarray) -> np.ndarray:
        da = a(p)
        db = b(p)
        h = np.clip(0.5 - 0.5 * (db + da) / k, 0.0, 1.0)
        return (da * (1 - h) + (-db) * h) + k * h * (1 - h)

    return f


def translate(sdf: SDF, offset: Vec3) -> SDF:
    """Translate the field by `offset`."""
    o = np.asarray(offset, dtype=np.float32)

    def f(p: np.ndarray) -> np.ndarray:
        return sdf(p - o)

    return f


def rotate_z(sdf: SDF, angle: float) -> SDF:
    """Rotate around the Z axis (most common case for terrain features)."""
    cos_a = float(np.cos(angle))
    sin_a = float(np.sin(angle))

    def f(p: np.ndarray) -> np.ndarray:
        x = p[..., 0] * cos_a + p[..., 1] * sin_a
        y = -p[..., 0] * sin_a + p[..., 1] * cos_a
        q = np.stack([x, y, p[..., 2]], axis=-1)
        return sdf(q)

    return f

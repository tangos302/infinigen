"""Adaptive polygon density for low-poly factories.

The principle (mirrored from Infinigen's `core.placement.detail` but
bbox-driven instead of camera-driven): every polygon should be roughly
the same size in world units, regardless of which factory or which
asset spawned it. So a 10m haystack ends up with more rings than a 1m
one, a 4m boulder has more facets than a 0.5m one, and the silhouette
"density" reads consistent across the scene.

The single dial is `target_edge` in world meters — the desired edge
length for one polygon. Derived per-instance from the asset's
bounding box and a `polygon_multiplier` (1.0 default). Factories
internally convert to `n_sides`, `n_layers`, `n_segments`, etc. via the
helpers below.

This module has zero Blender dependencies — pure math. Factories import
the helpers and pass the derived counts into their bmesh builders.

Reference: `infinigen/core/placement/detail.py` does the same job for
camera-distance-driven LOD; we use bbox size instead because Maquette
is a static-scene low-poly fork, not real-time.
"""

from __future__ import annotations

import math


# Tunable defaults. Per-factory callers can override via the
# `target_edge` kwarg; users can also hot-tune by setting these globals.
DEFAULT_TARGET_EDGE = 0.175
"""World-space target edge length in meters. 0.175 gives a Firewatch-ish
mid-low-poly silhouette; 0.5 → chunky/blocky; 0.1 → high-poly stylized.
Calibrated from the magical-fairy-village scene 2026-04-29 — value 0.5
read too coarse on small props."""

DEFAULT_MIN_EDGE = 0.10
DEFAULT_MAX_EDGE = 2.0
"""Bounds on per-instance target_edge. Tiny props (a small basket) get
clipped UP to MIN_EDGE so they don't end up with absurdly fine
geometry; huge props (a 30m rock spire) get clipped DOWN to MAX_EDGE
so they don't explode the polycount."""


def target_edge_for_bbox(
    dims: tuple[float, float, float],
    polygon_multiplier: float = 1.0,
    *,
    min_edge: float = DEFAULT_MIN_EDGE,
    max_edge: float = DEFAULT_MAX_EDGE,
    base_target_edge: float = DEFAULT_TARGET_EDGE,
) -> float:
    """Derive a per-instance target edge length from an asset's bounding
    box.

    The bbox surface area is the canonical "size" measure (polygons are
    2D, so area not volume). We scale `base_target_edge` by the cube
    root of the bbox size relative to a 1m unit cube, so a 10× larger
    asset gets a target_edge ~2.15× larger (proportional to L). That
    keeps poly count growing roughly with surface area, not volume.

    `polygon_multiplier` > 1 → more polygons (smaller edges); < 1 →
    fewer (bigger edges). Default 1.0. Mnemonic: it multiplies the
    polygon count, not the edge length.
    """
    L, W, H = dims
    if L <= 0 or W <= 0 or H <= 0:
        return base_target_edge
    # Geometric mean of dims is a good linear-scale proxy for "size"
    geo_mean = (L * W * H) ** (1.0 / 3.0)
    # Step 1 — bbox-derived target edge, clipped to keep both tiny and
    # huge assets in a reasonable absolute polycount band.
    bbox_edge = max(min_edge, min(max_edge, base_target_edge * geo_mean))
    # Step 2 — apply the user-supplied multiplier on top, deliberately
    # NOT re-clipped: a caller passing mult=4.0 on a 30m spire is opting
    # in to denser polys past the bbox-band cap.
    return bbox_edge / max(polygon_multiplier, 1e-3)


def n_along_axis(
    length: float,
    target_edge: float,
    *,
    min_n: int = 2,
    max_n: int = 64,
) -> int:
    """How many segments along a length so each is ~target_edge wide.

    Use for: stack n_layers (length=height), grid subdivisions
    (length=plane_width), plank counts along a deck (length=deck_length).
    """
    if length <= 0 or target_edge <= 0:
        return min_n
    n = math.ceil(length / target_edge)
    return max(min_n, min(max_n, n))


def n_sides_for_radius(
    radius: float,
    target_edge: float,
    *,
    min_n: int = 4,
    max_n: int = 32,
) -> int:
    """How many sides for a cylinder/cone of given radius so each side
    edge is ~target_edge long.

    Use for: cylinder n_sides (barrel, lantern post), spire n_sides,
    well curb n_sides, dome n_sides.
    """
    if radius <= 0 or target_edge <= 0:
        return min_n
    circumference = 2 * math.pi * radius
    n = math.ceil(circumference / target_edge)
    return max(min_n, min(max_n, n))


def n_subdivisions(
    from_edge: float,
    to_edge: float,
    *,
    max_levels: int = 4,
) -> int:
    """Number of midpoint subdivisions to go from `from_edge` to
    `to_edge`. Same formula Infinigen uses for SUBSURF level.
    """
    if from_edge <= 0 or to_edge <= 0 or to_edge >= from_edge:
        return 0
    return min(max_levels, math.ceil(math.log2(from_edge / to_edge)))


def polys_budget(surface_area: float, target_edge: float) -> int:
    """Sanity-check estimate of total polygon count for a given surface
    area at a given edge length. Useful in tests and for warning when
    a factory blows past the budget."""
    if surface_area <= 0 or target_edge <= 0:
        return 0
    return max(1, math.ceil(surface_area / (target_edge ** 2)))


def resolve_subdivisions(
    *,
    dims: tuple[float, float, float],
    polygon_multiplier: float = 1.0,
    target_edge: float | None = None,
) -> float:
    """Resolve the per-instance target_edge for a factory call.

    If `target_edge` is given, use it directly (bypass bbox derivation).
    Otherwise derive from `dims` via `target_edge_for_bbox`. Wraps the
    common boilerplate in factories' __init__.
    """
    if target_edge is not None:
        return float(target_edge)
    return target_edge_for_bbox(dims, polygon_multiplier=polygon_multiplier)

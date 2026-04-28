"""Spec types shared by bases and features.

A `BaseSpec` is what a `TerrainBase.to_spec(...)` returns: the SDF that
defines the ground starting point + a height function for asset
placement.

A `FeatureSpec` is what a `TerrainFeature.to_spec(...)` returns: an SDF
to compose with the running terrain SDF, plus the operator used to
compose it (union/subtract/smooth-variants), and an optional height-fn
modifier so factory callers can still query surface height after the
feature is applied.

Why dataclass specs and not just naked SDFs: features need to declare
*how* they compose (additive mountain peak vs. subtractive cave vs.
smooth-blended mesa skirt), and the factory needs to apply them in
order. Stuffing the operator in a side-channel keeps each feature class
self-contained.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

import numpy as np

from .sdf import SDF


HeightFn = Callable[[np.ndarray, np.ndarray], np.ndarray]
ComposeOp = Literal["union", "subtract", "smooth_union", "smooth_subtract"]


@dataclass
class BaseSpec:
    """The ground starting point. Returned by `TerrainBase.to_spec`."""

    sdf: SDF
    height_fn: HeightFn


@dataclass
class FeatureSpec:
    """One composable terrain modifier. Returned by `TerrainFeature.to_spec`."""

    sdf: SDF
    op: ComposeOp = "union"
    blend: float = 0.0  # only used for smooth_union / smooth_subtract
    # Optional callable that takes a height_fn and returns a new height_fn.
    # Lets a feature update the placement-query function (e.g. a MesaCluster
    # pushes mesa peaks above the current surface, a Gorge can leave it
    # alone since you don't usually place assets in the gorge bottom).
    height_modifier: Callable[[HeightFn], HeightFn] | None = None
    # Optional list of "no-place" XY bounding circles — features publish
    # the regions where assets shouldn't spawn (e.g. gorge corridor, cave
    # mouths). Caller-side asset scattering uses this to filter
    # candidate positions. Each entry is (cx, cy, radius).
    keep_out_zones: list[tuple[float, float, float]] = field(default_factory=list)
    # Optional list of "DO place here" XY bounding circles — features that
    # exist as scatter targets (islands rising from ocean, mesa tops, ridge
    # plateaus) publish the safe-radius circles where caller-side asset
    # scattering is encouraged. Each entry is (cx, cy, radius).
    scatter_zones: list[tuple[float, float, float]] = field(default_factory=list)

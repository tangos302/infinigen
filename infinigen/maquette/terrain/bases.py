"""Terrain bases — the ground starting point before features compose on top.

A base defines the *biome* shape: how the ground is laid out before any
features (mesas, gorges, caves) carve or augment it. Each base produces
an SDF and a height function for asset placement.

Available bases:
  DesertBase       — almost-flat sand basin with optional gentle dunes.
  OceanBase        — flat water plane at z=0; assets that float reference it.
  RollingHillsBase — broad smooth hills with low-frequency noise.
  AlpineBase       — sharp tall noisy mountain mass.

Each base takes an `extent` and a `seed` at construction time (rather
than `to_spec` time) so they can be configured once and reused.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Union

import numpy as np

from . import sdf as sdf_lib
from .composition import BaseSpec


# Type aliases matching features.py — params accept scalar OR (min, max) range.
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


class TerrainBase:
    """Abstract: every base produces a (sdf, height_fn) pair."""

    def to_spec(self, extent: tuple[float, float], seed: int) -> BaseSpec:
        raise NotImplementedError


@dataclass
class DesertBase(TerrainBase):
    """A near-flat desert basin.

    Default values were calibrated against the gorge/mesa scene
    (2026-04-29) — bigger noise reads as pebbly under marching cubes.
    Bump `max_height` for actual rolling sand dunes; keep the period
    long so dune crests are tens of meters apart.
    """

    max_height: float = 0.2
    noise_period: float = 60.0
    noise_octaves: int = 2
    noise_persistence: float = 0.4

    def to_spec(self, extent, seed):
        noise = sdf_lib.perlin_2d(
            seed=seed,
            period=self.noise_period,
            amplitude=self.max_height,
            octaves=self.noise_octaves,
            persistence=self.noise_persistence,
        )
        return BaseSpec(
            sdf=sdf_lib.height_field(noise),
            height_fn=noise,
        )


@dataclass
class OceanBase(TerrainBase):
    """A flat water plane at z=0 with imperceptible wave noise.

    Use sparingly as a *terrain* base — the asset side of Maquette also
    has `LowPolyWaterSurfaceFactory` which builds a small flat plane
    cheaper. This base exists for prompts that ask for a sea/ocean as the
    primary ground, where features (islands, cliffs) will rise out of
    the water.
    """

    wave_height: float = 0.1
    wave_period: float = 30.0

    def to_spec(self, extent, seed):
        noise = sdf_lib.perlin_2d(
            seed=seed, period=self.wave_period, amplitude=self.wave_height,
            octaves=1, persistence=0.5,
        )
        return BaseSpec(
            sdf=sdf_lib.height_field(noise),
            height_fn=noise,
        )


@dataclass
class RollingHillsBase(TerrainBase):
    """Broad smooth hills — for grassland, valleys, gentle countryside."""

    max_height: float = 4.0
    noise_period: float = 35.0
    noise_octaves: int = 2
    noise_persistence: float = 0.5

    def to_spec(self, extent, seed):
        noise = sdf_lib.perlin_2d(
            seed=seed, period=self.noise_period, amplitude=self.max_height,
            octaves=self.noise_octaves, persistence=self.noise_persistence,
        )
        return BaseSpec(
            sdf=sdf_lib.height_field(noise),
            height_fn=noise,
        )


@dataclass
class MesaPlateauBase(TerrainBase):
    """Eroded plateau — the geologically natural way to get mesa terrain.

    Real mesas form when a horizontal rock layer (caprock) is cut away
    by water/wind, leaving flat-topped islands of harder rock surrounded
    by lower terrain. The mesas ARE the un-eroded remainder of a once-
    continuous plateau. They naturally:
      - cluster following the rock-resistance pattern (which we model
        as smooth low-freq noise);
      - share the same flat top elevation (the original caprock layer);
      - spread organically across the terrain — not drawn next to
        canyons, scattered however nature placed them.

    Parameters:
      plateau_height : top elevation of the caprock layer (m)
      floor_height   : low-elevation terrain between mesas (m, can be ≤0)
      mesa_period    : length scale of the noise threshold — bigger
                       gives wider, more separated mesas
      coverage       : fraction of XY area where caprock survives.
                       0.2 = sparse mesas; 0.5 = mostly plateau with
                       eroded gaps. Real mesa landscapes ~0.25-0.4.
      cliff_softness : transition distance at the cliff edge (in noise
                       units). Small = vertical cliff; large = sloped
                       talus skirt. Default ~0.05 for sharp cliffs.
      top_variation  : amplitude of small-scale noise on plateau tops
                       (so the caprock isn't perfectly flat).
      floor_variation: amplitude of noise on the low-elevation floor
                       (gentle desert undulation between mesas).

    All numeric params accept scalar or (min, max) tuple → procedural
    seed-to-seed variation.
    """

    plateau_height: ScalarOrRange = (14.0, 20.0)
    floor_height: ScalarOrRange = (-0.5, 1.0)
    mesa_period: ScalarOrRange = (35.0, 55.0)
    coverage: ScalarOrRange = (0.30, 0.45)
    # Subtle top + floor noise. Marching cubes at 0.6m voxel turns
    # higher-frequency variation into stippled artifacts.
    top_variation: ScalarOrRange = (0.05, 0.20)
    floor_variation: ScalarOrRange = (0.05, 0.20)
    # Morphological opening — erodes the noise-threshold mask by N
    # cells, then dilates back. Removes thin "finger" features without
    # eroding the bulk mesa shapes. 1-2 cells (0.5-1m) is enough to
    # kill the noise-marginal-crossing artifacts. Bigger eats into
    # legitimate mesa silhouettes.
    opening_radius_cells: IntOrRange = (1, 2)
    # Gaussian-blur sigma applied AFTER the morphological mask. ~0.5
    # cells = ~0.25m blur — enough to smooth out marching-cubes
    # zigzag at cliff edges, NOT so much that mesa tops round off.
    cliff_smooth_sigma: ScalarOrRange = (0.5, 0.9)
    # Resolution of the precomputed mesa mask grid, in meters per cell.
    # Smaller = sharper mask but more memory. 0.5m balances quality
    # against the ~80×80m extent → 160×160 grid (~25k cells).
    mask_resolution: float = 0.5

    def to_spec(self, extent, seed):
        from scipy.ndimage import binary_dilation, binary_erosion, gaussian_filter

        rng = random.Random(seed * 1000 + 100)
        plateau_h = _sample(self.plateau_height, rng)
        floor_h = _sample(self.floor_height, rng)
        period = _sample(self.mesa_period, rng)
        coverage = _sample(self.coverage, rng)
        top_amp = _sample(self.top_variation, rng)
        floor_amp = _sample(self.floor_variation, rng)
        opening_r = max(1, _sample(self.opening_radius_cells, rng))
        smooth_sigma = _sample(self.cliff_smooth_sigma, rng)

        sx, sy = extent
        res = float(self.mask_resolution)
        nx = int(sx / res) + 1
        ny = int(sy / res) + 1
        xs = np.linspace(-sx / 2, sx / 2, nx, dtype=np.float32)
        ys = np.linspace(-sy / 2, sy / 2, ny, dtype=np.float32)
        # 2D grid for the precomputed mask (indexing="ij" → mask[i, j] = mask at (xs[i], ys[j]))
        X, Y = np.meshgrid(xs, ys, indexing="ij")

        # Mesa-presence noise — controls WHERE the plateau is preserved.
        mesa_noise = sdf_lib.low_freq_noise_2d(
            seed=seed, feature_scale=period, amplitude=1.0, grid_size=10,
        )
        n_grid = mesa_noise(X, Y)

        # Threshold: roughly `coverage` fraction above. Compute it
        # empirically from the noise sample so the coverage matches
        # regardless of noise distribution quirks.
        threshold = float(np.quantile(n_grid, 1.0 - coverage))

        # Binary mask + morphological opening: remove thin features.
        # Opening = erosion → dilation. After opening, any feature
        # narrower than 2 × opening_r cells is gone.
        mask_raw = (n_grid > threshold).astype(np.float32)
        mask_eroded = binary_erosion(mask_raw, iterations=opening_r).astype(np.float32)
        mask_opened = binary_dilation(mask_eroded, iterations=opening_r).astype(np.float32)
        # Gaussian blur for smooth cliff transition. Cell width = res.
        mask_smooth = gaussian_filter(mask_opened, sigma=smooth_sigma).astype(np.float32)

        # Texture noise for the plateau tops and the lower floor.
        top_noise = sdf_lib.low_freq_noise_2d(
            seed=seed * 17 + 1, feature_scale=period * 0.5,
            amplitude=top_amp, grid_size=8,
        )
        floor_noise = sdf_lib.low_freq_noise_2d(
            seed=seed * 17 + 2, feature_scale=period * 0.4,
            amplitude=floor_amp, grid_size=8,
        )

        x0, y0 = float(xs[0]), float(ys[0])

        def _bilinear(grid: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
            """Bilinear sample of the 2D mask grid at world (x, y)."""
            u = (x - x0) / res
            v = (y - y0) / res
            # Clamp to grid bounds
            u = np.clip(u, 0.0, nx - 1.001)
            v = np.clip(v, 0.0, ny - 1.001)
            i = u.astype(np.int32)
            j = v.astype(np.int32)
            fu = u - i
            fv = v - j
            v00 = grid[i, j]
            v10 = grid[i + 1, j]
            v01 = grid[i, j + 1]
            v11 = grid[i + 1, j + 1]
            a = v00 * (1 - fu) + v10 * fu
            b = v01 * (1 - fu) + v11 * fu
            return a * (1 - fv) + b * fv

        def height_fn(x, y):
            x_arr = np.asarray(x, dtype=np.float32)
            y_arr = np.asarray(y, dtype=np.float32)
            mask = _bilinear(mask_smooth, x_arr, y_arr)
            t_var = top_noise(x_arr, y_arr)
            f_var = floor_noise(x_arr, y_arr)
            return mask * (plateau_h + t_var) + (1.0 - mask) * (floor_h + f_var)

        return BaseSpec(
            sdf=sdf_lib.height_field(height_fn),
            height_fn=height_fn,
        )


@dataclass
class AlpineBase(TerrainBase):
    """Tall jagged mountain terrain — alpine, fjord, rocky.

    Sharper feel than RollingHillsBase: more octaves, higher amplitude,
    shorter period. Combined with a `MountainPeak` feature for hero
    summits.
    """

    max_height: float = 14.0
    noise_period: float = 22.0
    noise_octaves: int = 3
    noise_persistence: float = 0.55

    def to_spec(self, extent, seed):
        noise = sdf_lib.perlin_2d(
            seed=seed, period=self.noise_period, amplitude=self.max_height,
            octaves=self.noise_octaves, persistence=self.noise_persistence,
        )
        return BaseSpec(
            sdf=sdf_lib.height_field(noise),
            height_fn=noise,
        )


# ---------------------------------------------------------------------------
# Convenience: string → base instance, for caller convenience and for
# the runner/Claude side that picks bases by name.
# ---------------------------------------------------------------------------


_BASES = {
    "desert": DesertBase,
    "ocean": OceanBase,
    "rolling_hills": RollingHillsBase,
    "alpine": AlpineBase,
    "mesa_plateau": MesaPlateauBase,
}


def base_from_name(name: str, **kwargs) -> TerrainBase:
    """Look up a base class by name and instantiate it. Used by the
    factory to accept either a `TerrainBase` instance or a string."""
    if name not in _BASES:
        raise ValueError(f"unknown base {name!r}; valid: {list(_BASES)}")
    return _BASES[name](**kwargs)

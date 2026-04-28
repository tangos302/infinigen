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

from dataclasses import dataclass

import numpy as np

from . import sdf as sdf_lib
from .composition import BaseSpec


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
}


def base_from_name(name: str, **kwargs) -> TerrainBase:
    """Look up a base class by name and instantiate it. Used by the
    factory to accept either a `TerrainBase` instance or a string."""
    if name not in _BASES:
        raise ValueError(f"unknown base {name!r}; valid: {list(_BASES)}")
    return _BASES[name](**kwargs)

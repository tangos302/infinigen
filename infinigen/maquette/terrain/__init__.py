"""Maquette terrain — SDF-driven procedural ground meshes.

Terrain is composed in two layers: a `base` (biome — desert, ocean, alpine,
rolling hills) provides the starting ground field, and a list of `features`
(Gorge, MesaCluster, MountainPeak, Lake, CaveSystem, IslandCluster, Cliff)
mutate it via signed-distance set ops.

Public surface:

    from infinigen.maquette.terrain import (
        LowPolyTerrainFactory,
        # Bases
        DesertBase, OceanBase, RollingHillsBase, AlpineBase,
        # Features — subtractive
        Gorge, Lake, CaveSystem,
        # Features — additive
        MesaCluster, IslandCluster, MountainPeak, Cliff,
        # SDF library (low-level)
        sdf,
        # Mesh helpers
        build_mesh, mesh_to_blender, surface_height_at,
    )

Asset placement: after `create_asset`, the factory exposes
`height_fn(x, y)` for surface lookups, plus `scatter_zones` (place HERE)
and `keep_out_zones` (avoid HERE) — derived from the features list.
"""

from . import sdf  # re-export the SDF library as a submodule
from .bases import (
    AlpineBase,
    DesertBase,
    MesaPlateauBase,
    OceanBase,
    RollingHillsBase,
    TerrainBase,
    base_from_name,
)
from .composition import BaseSpec, FeatureSpec, HeightFn
from .factory import LowPolyTerrainFactory
from .features import (
    Canyon,
    CaveSystem,
    Cliff,
    Gorge,
    IslandCluster,
    Lake,
    MesaCluster,
    MountainPeak,
    Quarry,
)
from .marching import build_mesh, mesh_to_blender, surface_height_at

__all__ = [
    "AlpineBase",
    "BaseSpec",
    "Canyon",
    "CaveSystem",
    "Cliff",
    "DesertBase",
    "FeatureSpec",
    "Gorge",
    "HeightFn",
    "IslandCluster",
    "Lake",
    "LowPolyTerrainFactory",
    "MesaCluster",
    "MesaPlateauBase",
    "MountainPeak",
    "OceanBase",
    "Quarry",
    "RollingHillsBase",
    "TerrainBase",
    "base_from_name",
    "build_mesh",
    "mesh_to_blender",
    "sdf",
    "surface_height_at",
]

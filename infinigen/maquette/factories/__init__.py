"""Maquette factory wrappers.

Each module here defines a `LowPolyXxxFactory` class that subclasses
the upstream `XxxFactory` from `infinigen.assets.objects.*`. The
upstream class is left untouched; the subclass overrides the
geometry-finalize phase to produce low-poly, faceted output.
"""

"""Maquette factories.

Two tree backends are exposed and pick which based on the use case:

  LowPolyTreeFactory          (factories/tree.py)
    Wraps Infinigen's GenericTreeFactory. Inherits Infinigen's
    procedural-choice variety (species, season, bark surfaces) and
    decimates the resulting mesh down to a low-poly target. Best
    when you want Infinigen's full species palette and don't mind
    spiky-branch artifacts at low poly. ~1.1 s per spawn.

  NativeLowPolyTreeFactory    (factories/native/tree.py)
    Sapling/MTree-derived native low-poly generator. Builds the
    skeleton + skin from scratch with parametric trunk + branch
    layers, plus a stacked-icosphere foliage clump for proper
    Firewatch deformed-balloon foliage. SINGLE MESH per tree.
    Best when you want a clean Firewatch silhouette and don't
    need broadleaf species variety. ~0.01 s per spawn.

Boulder factory has only one backend (the wrapper); Infinigen's
boulder pipeline is shallow enough that wrapping + decimating is
fine.
"""

from .boulder import LowPolyBoulderFactory
from .native import (
    LowPolyBarrelFactory,
    LowPolyCrateFactory,
    LowPolyFenceFactory,
    LowPolyHouseFactory,
    LowPolyLanternPostFactory,
    LowPolyWaterSurfaceFactory,
    NativeLowPolyTreeFactory,
)
from .tree import LowPolyTreeFactory

__all__ = [
    "LowPolyBarrelFactory",
    "LowPolyBoulderFactory",
    "LowPolyCrateFactory",
    "LowPolyFenceFactory",
    "LowPolyHouseFactory",
    "LowPolyLanternPostFactory",
    "LowPolyTreeFactory",
    "LowPolyWaterSurfaceFactory",
    "NativeLowPolyTreeFactory",
]

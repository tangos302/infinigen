"""Maquette native low-poly factories.

These factories don't wrap Infinigen's pipeline — they implement
their own procedural-skeleton + mesh-from-skin algorithm in the
spirit of Blender's Sapling Tree Gen and MTree, but emit low-poly,
flat-shaded geometry from the start instead of as an afterthought.

Why a parallel native path:
  - Infinigen's foliage system is leaf-instanced on a geometry-node
    branch graph; that's incompatible with Firewatch foliage which
    is a single deformed-balloon mesh per tree.
  - Infinigen's branch system has photoreal-density skinning that
    fragments at low poly. Cleaner to build from low-poly first
    than to decimate-down million-poly intermediates.
  - The procedural-decision-tree story (different species, sizes,
    spread variants) is preserved by parameterizing the native
    generators just like Sapling does.

Eventually `LowPolyTreeFactory(species="native")` will route
through this package.
"""

from .banner import LowPolyBannerFactory
from .barrel import LowPolyBarrelFactory
from .boat import LowPolyBoatFactory
from .building import LowPolyHouseFactory
from .crate import LowPolyCrateFactory
from .deck import LowPolyDeckFactory
from .fence import LowPolyFenceFactory
from .haystack import LowPolyHaystackFactory
from .lantern_post import LowPolyLanternPostFactory
from .stall import LowPolyStallFactory
from .tombstone import LowPolyTombstoneFactory
from .torii import LowPolyToriiFactory
from .tree import NativeLowPolyTreeFactory
from .water_surface import LowPolyWaterSurfaceFactory
from .well import LowPolyWellFactory
from .windmill import LowPolyWindmillFactory

__all__ = [
    "LowPolyBannerFactory",
    "LowPolyBarrelFactory",
    "LowPolyBoatFactory",
    "LowPolyCrateFactory",
    "LowPolyDeckFactory",
    "LowPolyFenceFactory",
    "LowPolyHaystackFactory",
    "LowPolyHouseFactory",
    "LowPolyLanternPostFactory",
    "LowPolyStallFactory",
    "LowPolyTombstoneFactory",
    "LowPolyToriiFactory",
    "LowPolyWaterSurfaceFactory",
    "LowPolyWellFactory",
    "LowPolyWindmillFactory",
    "NativeLowPolyTreeFactory",
]

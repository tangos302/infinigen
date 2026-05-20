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

from .bamboo import LowPolyBambooFactory
from .banner import LowPolyBannerFactory
from .barrel import LowPolyBarrelFactory
from .bazaar_tent import LowPolyBazaarTentFactory
from .bell import LowPolyBellFactory
from .boat import LowPolyBoatFactory
from .campfire import LowPolyCampfireFactory
from .building import LowPolyHouseFactory
from .cable_car import LowPolyCableCarFactory
from .candle_cluster import LowPolyCandleClusterFactory
from .cactus import LowPolyCactusFactory
from .chapel import LowPolyChapelFactory
from .crate import LowPolyCrateFactory
from .deck import LowPolyDeckFactory
from .dock import LowPolyDockFactory
from .farm_animal import LowPolyFarmAnimalFactory
from .fence import LowPolyFenceFactory
from .fish_drying_rack import LowPolyFishDryingRackFactory
from .forge import LowPolyForgeFactory
from .fountain import LowPolyFountainFactory
from .furniture import LowPolyFurnitureFactory
from .haystack import LowPolyHaystackFactory
from .lantern_post import LowPolyLanternPostFactory
from .lava import LowPolyLavaFactory
from .market_goods import LowPolyMarketGoodsFactory
from .market_rug import LowPolyMarketRugFactory
from .natural_arch import LowPolyNaturalArchFactory
from .pagoda import LowPolyPagodaFactory
from .palm_tree import LowPolyPalmTreeFactory
from .path import LowPolyPathFactory
from .peasant import LowPolyPeasantFactory
from .reeds import LowPolyReedsFactory
from .rock_spire import LowPolyRockSpireFactory
from .ruin import LowPolyRuinFactory
from .shrub import LowPolyShrubFactory
from .smithy_props import LowPolySmithyPropsFactory
from .stall import LowPolyStallFactory
from .stable_yard import LowPolyStableYardFactory
from .stone_bridge import LowPolyStoneBridgeFactory
from .stone_lantern import LowPolyStoneLanternFactory
from .string_lights import LowPolyStringLightsFactory
from .suspension_bridge import LowPolySuspensionBridgeFactory
from .tombstone import LowPolyTombstoneFactory
from .torii import LowPolyToriiFactory
from .torch import LowPolyTorchFactory
from .shopfront import LowPolyShopfrontFactory
from .tavern import LowPolyTavernFactory
from .town_gate import LowPolyTownGateFactory
from .town_block import LowPolyTownBlockFactory
from .tree import LowPolyTreeFactory, NativeLowPolyTreeFactory
from .tumbleweed import LowPolyTumbleweedFactory
from .volcanic_rock import LowPolyVolcanicRockFactory
from .wagon import LowPolyWagonFactory
from .watchtower import LowPolyWatchtowerFactory
from .water_surface import LowPolyWaterSurfaceFactory
from .waterfall import LowPolyWaterfallFactory
from .watermill import LowPolyWatermillFactory
from .well import LowPolyWellFactory
from .windmill import LowPolyWindmillFactory
from .zen_garden_gate import LowPolyZenGardenGateFactory

__all__ = [
    "LowPolyBambooFactory",
    "LowPolyBannerFactory",
    "LowPolyBarrelFactory",
    "LowPolyBazaarTentFactory",
    "LowPolyBellFactory",
    "LowPolyBoatFactory",
    "LowPolyCampfireFactory",
    "LowPolyCableCarFactory",
    "LowPolyCandleClusterFactory",
    "LowPolyCactusFactory",
    "LowPolyChapelFactory",
    "LowPolyCrateFactory",
    "LowPolyDeckFactory",
    "LowPolyDockFactory",
    "LowPolyFarmAnimalFactory",
    "LowPolyFenceFactory",
    "LowPolyFishDryingRackFactory",
    "LowPolyForgeFactory",
    "LowPolyFountainFactory",
    "LowPolyFurnitureFactory",
    "LowPolyHaystackFactory",
    "LowPolyHouseFactory",
    "LowPolyLanternPostFactory",
    "LowPolyLavaFactory",
    "LowPolyMarketGoodsFactory",
    "LowPolyMarketRugFactory",
    "LowPolyNaturalArchFactory",
    "LowPolyPagodaFactory",
    "LowPolyPalmTreeFactory",
    "LowPolyPathFactory",
    "LowPolyPeasantFactory",
    "LowPolyReedsFactory",
    "LowPolyRockSpireFactory",
    "LowPolyRuinFactory",
    "LowPolyShrubFactory",
    "LowPolySmithyPropsFactory",
    "LowPolyStallFactory",
    "LowPolyStableYardFactory",
    "LowPolyStoneBridgeFactory",
    "LowPolyStoneLanternFactory",
    "LowPolyStringLightsFactory",
    "LowPolySuspensionBridgeFactory",
    "LowPolyTombstoneFactory",
    "LowPolyToriiFactory",
    "LowPolyTorchFactory",
    "LowPolyShopfrontFactory",
    "LowPolyTavernFactory",
    "LowPolyTownBlockFactory",
    "LowPolyTownGateFactory",
    "LowPolyTumbleweedFactory",
    "LowPolyTreeFactory",
    "LowPolyVolcanicRockFactory",
    "LowPolyWagonFactory",
    "LowPolyWatchtowerFactory",
    "LowPolyWaterSurfaceFactory",
    "LowPolyWaterfallFactory",
    "LowPolyWatermillFactory",
    "LowPolyWellFactory",
    "LowPolyWindmillFactory",
    "LowPolyZenGardenGateFactory",
    "NativeLowPolyTreeFactory",
]

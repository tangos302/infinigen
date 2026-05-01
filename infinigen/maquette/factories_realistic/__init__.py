"""Realistic-mode factory adapters.

Mirror of `infinigen.maquette.factories` — same class-name shape (so build
scripts read identically except for the import path) but each adapter
delegates to upstream `infinigen.assets.objects.*` factories without the
maquette flat-shade / decimate / palette overrides.

The adapters are deliberately thin: they exist to (a) give the LLM a
stable archetype kwarg matching the low-poly factories, and (b) map our
archetype names onto whatever genome / season / morphology hook upstream
exposes, so a realistic-mode build can iterate the same way a low-poly
one does.

Re-export upstream factories rather than reinventing them. See each
module's docstring for the upstream class it wraps.

Polycount caps
--------------
Realistic-mode targets PS3-era polycounts (a few thousand triangles per
hero asset, a few hundred per ground-cover prop). Each factory's
spawn_asset() output is post-processed via DECIMATE COLLAPSE to a
per-factory budget; see `_polycap.with_polycap` and the budget table at
the bottom of this file.
"""

from ._materials import with_default_material as _mat
from ._polycap import with_polycap as _cap

# Underlying classes — we re-export wrapped versions below.
from .beam import RealisticBeamFactory as _Beam
from .blender_rock import RealisticBlenderRockFactory as _BlenderRock
from .boulder import RealisticBoulderFactory as _Boulder
from .btools_building import RealisticBToolsBuildingFactory as _Building
from .boulder_pile import RealisticBoulderPileFactory as _BoulderPile
from .bush import RealisticBushFactory as _Bush
from .cactus import RealisticCactusFactory as _Cactus
from .coral import RealisticCoralFactory as _Coral
from .dandelion import RealisticDandelionFactory as _Dandelion
from .fern import RealisticFernFactory as _Fern
from .flower import RealisticFlowerFactory as _Flower
from .flower_plant import RealisticFlowerPlantFactory as _FlowerPlant
from .function_surface import RealisticFunctionSurfaceFactory as _FnSurface
from .gear import RealisticGearFactory as _Gear
from .gemstone import RealisticGemstoneFactory as _Gem
from .glowing_rocks import RealisticGlowingRocksFactory as _Glow
from .grass import RealisticGrassTuftFactory as _Grass
from .honeycomb import RealisticHoneycombFactory as _Honey
from .kelp import RealisticKelpMonocotFactory as _Kelp
from .menger_sponge import RealisticMengerSpongeFactory as _Menger
from .mushroom import RealisticMushroomFactory as _Mushroom
from .pipe_joint import RealisticPipeJointFactory as _Pipe
from .seaweed import RealisticSeaweedFactory as _Seaweed
from .snake_plant import RealisticSnakePlantFactory as _Snake
from .solid import RealisticSolidFactory as _Solid
from .spider_plant import RealisticSpiderPlantFactory as _Spider
from .step_pyramid import RealisticStepPyramidFactory as _Pyramid
from .succulent import RealisticSucculentFactory as _Succ
from .supertoroid import RealisticSupertoroidFactory as _Toroid
from .tree import RealisticTreeFactory as _Tree
from .urchin import RealisticUrchinFactory as _Urchin
from .wall import RealisticWallFactory as _Wall
from .worm_gear import RealisticWormGearFactory as _Worm


# ---------------------------------------------------------------------------
# Per-factory polycount budgets (target VERTEX count, not triangle count).
#
# Tier rationale (PS3-era stylized realistic):
#   hero vegetation (tree)        : ~4000  — readable canopy at distance
#   medium vegetation (bush, cactus, fern, kelp, coral, seaweed)
#                                 : ~1500  — dense enough to silhouette
#   ground cover (mushroom, flower, succulent, snake/spider plant,
#                 dandelion, flower_plant, urchin, glowing_rocks)
#                                 : ~600   — small, often instanced
#   grass tuft                    : ~300   — many per scene; cheap each
#   hero rock (boulder, boulder_pile)
#                                 : ~800-1500
#   pebble (blender_rock)         : ~200   — small accent rocks
#
# Structural / abstract factories already emit <1k verts (Wall: ~5k for
# fortress, but it's hand-tuned masonry — leave uncapped). Set their
# budget to None so we don't decimate clean primitive geometry.
# ---------------------------------------------------------------------------

# Polycap targets — halved 2026-05-01 from PS3-era to PS2-era
# polycount, since trees were reading as too detailed at typical
# camera distances. Hero meshes still legible; ground-cover instances
# (which scatter into hundreds of copies) get the biggest wins.
RealisticTreeFactory          = _cap(_Tree,         2500)
RealisticBushFactory          = _cap(_Bush,          700)
RealisticBoulderFactory       = _cap(_Boulder,       500)
RealisticBoulderPileFactory   = _cap(_BoulderPile,   700)
RealisticBlenderRockFactory   = _cap(_BlenderRock,   100)
RealisticGlowingRocksFactory  = _cap(_Glow,          300)
RealisticCactusFactory        = _cap(_Cactus,        500)
RealisticSnakePlantFactory    = _cap(_Snake,         300)
RealisticSpiderPlantFactory   = _cap(_Spider,        300)
RealisticSucculentFactory     = _cap(_Succ,          300)
RealisticFernFactory          = _cap(_Fern,          700)
RealisticFlowerFactory        = _cap(_Flower,        300)
RealisticFlowerPlantFactory   = _cap(_FlowerPlant,   400)
RealisticDandelionFactory     = _cap(_Dandelion,     200)
RealisticGrassTuftFactory     = _cap(_Grass,         150)
RealisticMushroomFactory      = _cap(_Mushroom,      300)
RealisticSeaweedFactory       = _cap(_Seaweed,       500)
RealisticKelpMonocotFactory   = _cap(_Kelp,          700)
RealisticCoralFactory         = _cap(_Coral,         700)
RealisticUrchinFactory        = _cap(_Urchin,        300)

# Structural / abstract — already low-poly by construction. No polycap;
# wrap with default PBR material so they don't render as flat grey.
RealisticWallFactory             = _mat(_cap(_Wall,         None))
RealisticBeamFactory             = _mat(_cap(_Beam,         None))
RealisticStepPyramidFactory      = _mat(_cap(_Pyramid,      None))
RealisticPipeJointFactory        = _mat(_cap(_Pipe,         None))
RealisticGearFactory             = _mat(_cap(_Gear,         None))
RealisticWormGearFactory         = _mat(_cap(_Worm,         None))
RealisticGemstoneFactory         = _mat(_cap(_Gem,          None))
RealisticSolidFactory            = _mat(_cap(_Solid,        None))
RealisticSupertoroidFactory      = _mat(_cap(_Toroid,       None))
RealisticHoneycombFactory        = _mat(_cap(_Honey,        None))
# Menger level-3 hits ~80k verts — cap it so it stays browser-friendly.
RealisticMengerSpongeFactory     = _mat(_cap(_Menger,       3000))
RealisticFunctionSurfaceFactory  = _mat(_cap(_FnSurface,    None))
# Building Tools wrapper — already silhouette-clean (<500 verts) and
# applies its own multi-slot materials inside the factory body.
RealisticBToolsBuildingFactory   = _cap(_Building,     None)


__all__ = [
    "RealisticBeamFactory",
    "RealisticBlenderRockFactory",
    "RealisticBoulderFactory",
    "RealisticBToolsBuildingFactory",
    "RealisticBoulderPileFactory",
    "RealisticBushFactory",
    "RealisticCactusFactory",
    "RealisticCoralFactory",
    "RealisticDandelionFactory",
    "RealisticFernFactory",
    "RealisticFlowerFactory",
    "RealisticFlowerPlantFactory",
    "RealisticFunctionSurfaceFactory",
    "RealisticGearFactory",
    "RealisticGemstoneFactory",
    "RealisticGlowingRocksFactory",
    "RealisticGrassTuftFactory",
    "RealisticHoneycombFactory",
    "RealisticKelpMonocotFactory",
    "RealisticMengerSpongeFactory",
    "RealisticMushroomFactory",
    "RealisticPipeJointFactory",
    "RealisticSeaweedFactory",
    "RealisticSnakePlantFactory",
    "RealisticSolidFactory",
    "RealisticSpiderPlantFactory",
    "RealisticStepPyramidFactory",
    "RealisticSucculentFactory",
    "RealisticSupertoroidFactory",
    "RealisticTreeFactory",
    "RealisticUrchinFactory",
    "RealisticWallFactory",
    "RealisticWormGearFactory",
]

"""RealisticFlowerPlantFactory — leafy flowering plant, wraps upstream.

Distinct from RealisticFlowerFactory: this is a full plant (leaves + stem
+ flower head) rather than a single-flower geometry. Use for medium
ground cover with visible foliage; FlowerFactory is the close-up bloom.
"""

from __future__ import annotations

from infinigen.assets.objects.grassland.flowerplant import FlowerPlantFactory


_FLOWER_PLANT_ARCHETYPES = ("herb", "wildflower", "any")


class RealisticFlowerPlantFactory(FlowerPlantFactory):
    """Realistic flower-plant factory.

    Constructor knobs:

        factory_seed : int
        archetype : str = "any"
            Label only — herb / wildflower / any.
        coarse : bool = False
    """

    def __init__(
        self,
        factory_seed: int,
        archetype: str = "any",
        coarse: bool = False,
        **kwargs,
    ):
        if archetype not in _FLOWER_PLANT_ARCHETYPES:
            raise ValueError(
                f"archetype={archetype!r} not in {_FLOWER_PLANT_ARCHETYPES}"
            )
        salt = sum(ord(c) for c in archetype) * 3911
        super().__init__(factory_seed + salt, coarse=coarse, **kwargs)

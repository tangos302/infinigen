"""RealisticSpiderPlantFactory — cascading grassy plant, wraps upstream."""

from __future__ import annotations

from infinigen.assets.objects.small_plants.spider_plant import SpiderPlantFactory


_SPIDER_ARCHETYPES = ("hanging", "compact", "any")


class RealisticSpiderPlantFactory(SpiderPlantFactory):
    """Realistic spider-plant factory.

    Thin grass-like leaves arching outward, sometimes with runners.
    Good for shaded forest floor / cabin-porch scenes.

    Constructor knobs:

        factory_seed : int
        archetype : str = "any"
            Label only — hanging / compact / any.
        coarse : bool = False
    """

    def __init__(
        self,
        factory_seed: int,
        archetype: str = "any",
        coarse: bool = False,
        **kwargs,
    ):
        if archetype not in _SPIDER_ARCHETYPES:
            raise ValueError(
                f"archetype={archetype!r} not in {_SPIDER_ARCHETYPES}"
            )
        salt = sum(ord(c) for c in archetype) * 8011
        super().__init__(factory_seed + salt, coarse=coarse, **kwargs)

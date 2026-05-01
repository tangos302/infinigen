"""RealisticSucculentFactory — rosette succulent, wraps upstream."""

from __future__ import annotations

from infinigen.assets.objects.small_plants.succulent import SucculentFactory


_SUCCULENT_ARCHETYPES = ("thick", "thin", "any")


class RealisticSucculentFactory(SucculentFactory):
    """Realistic succulent factory.

    Rosette form with thick or thin petals. Pairs with Cactus / SnakePlant
    for desert + arid scenes.

    Constructor knobs:

        factory_seed : int
        archetype : str = "any"
            Label only — thick / thin / any.
        coarse : bool = False
    """

    def __init__(
        self,
        factory_seed: int,
        archetype: str = "any",
        coarse: bool = False,
        **kwargs,
    ):
        if archetype not in _SUCCULENT_ARCHETYPES:
            raise ValueError(
                f"archetype={archetype!r} not in {_SUCCULENT_ARCHETYPES}"
            )
        salt = sum(ord(c) for c in archetype) * 5701
        super().__init__(factory_seed + salt, coarse=coarse, **kwargs)

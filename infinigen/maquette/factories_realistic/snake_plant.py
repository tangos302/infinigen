"""RealisticSnakePlantFactory — upright variegated succulent, wraps upstream."""

from __future__ import annotations

from infinigen.assets.objects.small_plants.snake_plant import SnakePlantFactory


_SNAKE_ARCHETYPES = ("upright", "fan", "any")


class RealisticSnakePlantFactory(SnakePlantFactory):
    """Realistic snake-plant factory.

    Tall pointed leaves with edge variegation. Reads as desert / dry
    indoor succulent in scenes; pairs naturally with Cactus.

    Constructor knobs:

        factory_seed : int
        archetype : str = "any"
            Label only — upright / fan / any.
        coarse : bool = False
    """

    def __init__(
        self,
        factory_seed: int,
        archetype: str = "any",
        coarse: bool = False,
        **kwargs,
    ):
        if archetype not in _SNAKE_ARCHETYPES:
            raise ValueError(
                f"archetype={archetype!r} not in {_SNAKE_ARCHETYPES}"
            )
        salt = sum(ord(c) for c in archetype) * 7393
        super().__init__(factory_seed + salt, coarse=coarse, **kwargs)

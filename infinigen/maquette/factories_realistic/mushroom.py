"""RealisticMushroomFactory — realistic mushroom cluster, wraps upstream Infinigen.

Delegates to `infinigen.assets.objects.mushroom.generate.MushroomFactory`.
Upstream produces a 1–6 mushroom cluster via MushroomGrowthFactory; cap
shape, stem curvature and shader colours are sampled per seed.

Archetype is a label that hashes into the seed so an LLM can request
visually distinct mushroom moods without upstream needing knobs.
"""

from __future__ import annotations

from infinigen.assets.objects.mushroom.generate import MushroomFactory


_MUSHROOM_ARCHETYPES = ("toadstool", "glowcap", "cluster", "any")


class RealisticMushroomFactory(MushroomFactory):
    """Realistic mushroom factory.

    Constructor knobs:

        factory_seed : int
        archetype : str = "any"
            Label only — toadstool / glowcap / cluster / any.
        coarse : bool = False
    """

    def __init__(
        self,
        factory_seed: int,
        archetype: str = "any",
        coarse: bool = False,
        **kwargs,
    ):
        if archetype not in _MUSHROOM_ARCHETYPES:
            raise ValueError(
                f"archetype={archetype!r} not in {_MUSHROOM_ARCHETYPES}"
            )
        salt = sum(ord(c) for c in archetype) * 6151
        super().__init__(factory_seed + salt, coarse=coarse, **kwargs)

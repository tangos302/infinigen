"""RealisticSeaweedFactory — branching kelp-like aquatic plant, wraps upstream."""

from __future__ import annotations

from infinigen.assets.objects.underwater.seaweed import SeaweedFactory


_SEAWEED_ARCHETYPES = ("branching", "frond", "any")


class RealisticSeaweedFactory(SeaweedFactory):
    """Realistic seaweed factory.

    Branching aquatic growth via differential-growth algorithm.
    Use for underwater scenes; pair with KelpMonocot for variety.

    Constructor knobs:

        factory_seed : int
        archetype : str = "any"
            Label only — branching / frond / any.
        coarse : bool = False
    """

    def __init__(
        self,
        factory_seed: int,
        archetype: str = "any",
        coarse: bool = False,
        **kwargs,
    ):
        if archetype not in _SEAWEED_ARCHETYPES:
            raise ValueError(
                f"archetype={archetype!r} not in {_SEAWEED_ARCHETYPES}"
            )
        salt = sum(ord(c) for c in archetype) * 9181
        super().__init__(factory_seed + salt, coarse=coarse, **kwargs)

"""RealisticKelpMonocotFactory — tall aquatic monocot, wraps upstream.

Distinct from RealisticSeaweedFactory: kelp uses a monocot growth
algorithm (long ribbon-like blades from a holdfast) — better for
forest-of-kelp underwater scenes. Seaweed is bushier branching growth.
"""

from __future__ import annotations

from infinigen.assets.objects.monocot.kelp import KelpMonocotFactory


_KELP_ARCHETYPES = ("forest", "single", "any")


class RealisticKelpMonocotFactory(KelpMonocotFactory):
    """Realistic kelp factory.

    Constructor knobs:

        factory_seed : int
        archetype : str = "any"
            Label only — forest / single / any.
        coarse : bool = False
    """

    def __init__(
        self,
        factory_seed: int,
        archetype: str = "any",
        coarse: bool = False,
        **kwargs,
    ):
        if archetype not in _KELP_ARCHETYPES:
            raise ValueError(
                f"archetype={archetype!r} not in {_KELP_ARCHETYPES}"
            )
        salt = sum(ord(c) for c in archetype) * 6529
        super().__init__(factory_seed + salt, coarse=coarse, **kwargs)

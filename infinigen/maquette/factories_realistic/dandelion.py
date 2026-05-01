"""RealisticDandelionFactory — wildflower seed-puff, wraps upstream."""

from __future__ import annotations

from infinigen.assets.objects.grassland.dandelion import DandelionFactory


_DANDELION_ARCHETYPES = ("yellow", "puff", "any")


class RealisticDandelionFactory(DandelionFactory):
    """Realistic dandelion factory.

    Constructor knobs:

        factory_seed : int
        archetype : str = "any"
            Label only — yellow / puff / any.
        coarse : bool = False
    """

    def __init__(
        self,
        factory_seed: int,
        archetype: str = "any",
        coarse: bool = False,
        **kwargs,
    ):
        if archetype not in _DANDELION_ARCHETYPES:
            raise ValueError(
                f"archetype={archetype!r} not in {_DANDELION_ARCHETYPES}"
            )
        salt = sum(ord(c) for c in archetype) * 4283
        super().__init__(factory_seed + salt, coarse=coarse, **kwargs)

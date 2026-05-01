"""RealisticBushFactory — realistic bush, wraps upstream Infinigen.

Delegates to `infinigen.assets.objects.trees.generate.BushFactory`. Bush
shares the GenericTreeFactory genome path with trees but with shorter
trunk + denser foliage; upstream samples species automatically. We just
surface a uniform archetype kwarg for catalog parity.

Archetype mapping (cosmetic only — upstream samples species jointly):

    "leafy"  : default, full broadleaf bush
    "sparse" : reduced leaf density via fruit_chance=0
    "any"    : upstream defaults
"""

from __future__ import annotations

from infinigen.assets.objects.trees.generate import BushFactory


_BUSH_ARCHETYPES = ("leafy", "sparse", "any")


class RealisticBushFactory(BushFactory):
    """Realistic bush factory.

    Constructor knobs:

        factory_seed : int
        archetype : str = "any"
            One of: leafy / sparse / any.
        coarse : bool = False
            Pass-through for upstream's coarse-mode flag.
    """

    def __init__(
        self,
        factory_seed: int,
        archetype: str = "any",
        coarse: bool = False,
        **kwargs,
    ):
        if archetype not in _BUSH_ARCHETYPES:
            raise ValueError(
                f"archetype={archetype!r} not in {_BUSH_ARCHETYPES}"
            )
        super().__init__(factory_seed, coarse=coarse, **kwargs)

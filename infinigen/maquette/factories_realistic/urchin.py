"""RealisticUrchinFactory — sea urchin, wraps upstream."""

from __future__ import annotations

from infinigen.assets.objects.underwater.urchin import UrchinFactory


_URCHIN_ARCHETYPES = ("spiny", "flat", "any")


class RealisticUrchinFactory(UrchinFactory):
    """Realistic sea-urchin factory.

    Radially symmetric body with spine quills. Reads as a benthic
    (sea-floor) detail; place sparsely on submerged rocks/reef.

    Constructor knobs:

        factory_seed : int
        archetype : str = "any"
            Label only — spiny / flat / any.
        coarse : bool = False
    """

    def __init__(
        self,
        factory_seed: int,
        archetype: str = "any",
        coarse: bool = False,
        **kwargs,
    ):
        if archetype not in _URCHIN_ARCHETYPES:
            raise ValueError(
                f"archetype={archetype!r} not in {_URCHIN_ARCHETYPES}"
            )
        salt = sum(ord(c) for c in archetype) * 4831
        super().__init__(factory_seed + salt, coarse=coarse, **kwargs)

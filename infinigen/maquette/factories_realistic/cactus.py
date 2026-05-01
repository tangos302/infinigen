"""RealisticCactusFactory — realistic cactus, wraps upstream Infinigen.

Upstream `CactusFactory` is a dispatcher that uniformly samples from
GlobularBaseCactusFactory / ColumnarBaseCactusFactory /
PrickyPearBaseCactusFactory at construction time (and KalidiumBase is
defined but commented out of the default sampler). Our archetype kwarg
pins which morphology gets used so a desert scatter can mix in
deliberate proportions instead of relying on the random pick.

Archetype mapping → upstream Base class fed to factory_method:

    "globular"   : GlobularBaseCactusFactory   (round barrel cactus)
    "columnar"   : ColumnarBaseCactusFactory   (tall saguaro-like)
    "pricky_pear": PrickyPearBaseCactusFactory (paddle / opuntia)
    "kalidium"   : KalidiumBaseCactusFactory   (segmented twiggy)
    "any"        : upstream's uniform sampler over the first three
"""

from __future__ import annotations

from infinigen.assets.objects.cactus.columnar import ColumnarBaseCactusFactory
from infinigen.assets.objects.cactus.generate import CactusFactory
from infinigen.assets.objects.cactus.globular import GlobularBaseCactusFactory
from infinigen.assets.objects.cactus.kalidium import KalidiumBaseCactusFactory
from infinigen.assets.objects.cactus.pricky_pear import PrickyPearBaseCactusFactory


_CACTUS_ARCHETYPES = ("globular", "columnar", "pricky_pear", "kalidium", "any")

_ARCHETYPE_TO_BASE: dict[str, type] = {
    "globular": GlobularBaseCactusFactory,
    "columnar": ColumnarBaseCactusFactory,
    "pricky_pear": PrickyPearBaseCactusFactory,
    "kalidium": KalidiumBaseCactusFactory,
}


class RealisticCactusFactory(CactusFactory):
    """Realistic cactus factory.

    Constructor knobs:

        factory_seed : int
        archetype : str = "any"
            One of: globular / columnar / pricky_pear / kalidium / any.
        coarse : bool = False
    """

    def __init__(
        self,
        factory_seed: int,
        archetype: str = "any",
        coarse: bool = False,
        **kwargs,
    ):
        if archetype not in _CACTUS_ARCHETYPES:
            raise ValueError(
                f"archetype={archetype!r} not in {_CACTUS_ARCHETYPES}"
            )
        factory_method = _ARCHETYPE_TO_BASE.get(archetype)  # None → upstream samples
        super().__init__(
            factory_seed,
            coarse=coarse,
            factory_method=factory_method,
            **kwargs,
        )

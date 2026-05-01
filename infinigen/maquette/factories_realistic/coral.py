"""RealisticCoralFactory — coral, wraps upstream dispatcher.

Same dispatcher pattern as CactusFactory: upstream `CoralFactory` picks
a Base*CoralFactory at construction (DiffGrowth / Tube / Tree /
Cauliflower / Elkhorn / Star / ReactionDiffusion). Our archetype kwarg
pins which morphology gets used so a reef scatter can mix in deliberate
proportions.
"""

from __future__ import annotations

from infinigen.assets.objects.corals.diff_growth import DiffGrowthBaseCoralFactory
from infinigen.assets.objects.corals.elkhorn import ElkhornBaseCoralFactory
from infinigen.assets.objects.corals.generate import CoralFactory
from infinigen.assets.objects.corals.laplacian import CauliflowerBaseCoralFactory
from infinigen.assets.objects.corals.reaction_diffusion import (
    ReactionDiffusionBaseCoralFactory,
)
from infinigen.assets.objects.corals.star import StarBaseCoralFactory
from infinigen.assets.objects.corals.tree import TreeBaseCoralFactory
from infinigen.assets.objects.corals.tube import TubeBaseCoralFactory


_CORAL_ARCHETYPES = (
    "elkhorn", "star", "cauliflower", "tube", "tree",
    "diff_growth", "reaction_diffusion", "any",
)

_ARCHETYPE_TO_BASE: dict[str, type] = {
    "elkhorn": ElkhornBaseCoralFactory,
    "star": StarBaseCoralFactory,
    "cauliflower": CauliflowerBaseCoralFactory,
    "tube": TubeBaseCoralFactory,
    "tree": TreeBaseCoralFactory,
    "diff_growth": DiffGrowthBaseCoralFactory,
    "reaction_diffusion": ReactionDiffusionBaseCoralFactory,
}


class RealisticCoralFactory(CoralFactory):
    """Realistic coral factory.

    Constructor knobs:

        factory_seed : int
        archetype : str = "any"
            One of: elkhorn / star / cauliflower / tube / tree /
            diff_growth / reaction_diffusion / any.
        coarse : bool = False
    """

    def __init__(
        self,
        factory_seed: int,
        archetype: str = "any",
        coarse: bool = False,
        **kwargs,
    ):
        if archetype not in _CORAL_ARCHETYPES:
            raise ValueError(
                f"archetype={archetype!r} not in {_CORAL_ARCHETYPES}"
            )
        factory_method = _ARCHETYPE_TO_BASE.get(archetype)
        super().__init__(
            factory_seed,
            coarse=coarse,
            factory_method=factory_method,
            **kwargs,
        )

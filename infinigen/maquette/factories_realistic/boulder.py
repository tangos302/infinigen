"""RealisticBoulderFactory — realistic boulder, wraps upstream Infinigen.

Delegates to `infinigen.assets.objects.rocks.boulder.BoulderFactory`.
Upstream picks slab vs boulder morphology (80/20) and a rock surface
shader per seed; we surface that as an archetype kwarg for the LLM
without changing the underlying genome.

Archetype mapping → upstream `do_voronoi` + slab forcing:

    "boulder" : convex-hull rock, voronoi displacement on
    "slab"    : flat slab variant (forces upstream's slab path)
    "any"     : sample from upstream's 80/20 distribution
"""

from __future__ import annotations

import bpy
import numpy as np

from infinigen.assets.objects.rocks.boulder import BoulderFactory


_BOULDER_ARCHETYPES = ("boulder", "slab", "any")


class RealisticBoulderFactory(BoulderFactory):
    """Realistic boulder factory — full upstream Infinigen geometry.

    Constructor knobs:

        factory_seed : int
        archetype : str = "any"
            One of: boulder / slab / any.
        do_voronoi : bool = True
            Voronoi displacement for surface micro-detail.
        coarse : bool = False
            Pass-through for upstream's coarse-mode flag.

    All other knobs are forwarded to upstream `BoulderFactory.__init__`.
    """

    def __init__(
        self,
        factory_seed: int,
        archetype: str = "any",
        do_voronoi: bool = True,
        coarse: bool = False,
        **kwargs,
    ):
        if archetype not in _BOULDER_ARCHETYPES:
            raise ValueError(
                f"archetype={archetype!r} not in {_BOULDER_ARCHETYPES}"
            )
        super().__init__(
            factory_seed,
            do_voronoi=do_voronoi,
            coarse=coarse,
            **kwargs,
        )
        # Override upstream's stochastic morphology pick if archetype pins it.
        if archetype == "slab":
            self.has_horizontal_cut, self.is_slab = False, True
        elif archetype == "boulder":
            self.has_horizontal_cut, self.is_slab = True, False

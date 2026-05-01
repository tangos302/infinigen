"""RealisticTreeFactory — realistic tree, wraps upstream Infinigen.

Delegates to `infinigen.assets.objects.trees.generate.TreeFactory`. We do
*not* override its geometry pipeline (no decimate, no flat-shade, no
palette) — the upstream species sampler picks a leaf type, twig genome,
bark surface and fruit chance per seed, and we keep all of that.

Archetype mapping → upstream `season` arg:

    "summer" : leafy broadleaf, full canopy
    "autumn" : same broadleaf with autumn shader tint
    "winter" : bare branches (TreeFactory drops leaves)
    "spring" : flower-bearing variant
    "any"    : let upstream sample season uniformly

Why pin season instead of leaf-type? `random_species` already picks
leaf_type, twig_params, leaf_params jointly with high covariance. Bypassing
that and forcing a single leaf would produce off-distribution genomes.
Season is the one knob upstream actually exposes that's safe to set.
"""

from __future__ import annotations

import bpy

from infinigen.assets.objects.trees.generate import TreeFactory


_TREE_ARCHETYPES = ("summer", "autumn", "winter", "spring", "any")


class RealisticTreeFactory(TreeFactory):
    """Realistic tree factory — full upstream Infinigen geometry, no
    low-poly post-processing.

    Constructor knobs:

        factory_seed : int
        archetype : str = "any"
            One of: summer / autumn / winter / spring / any.
            Maps to upstream TreeFactory's `season` argument.
        fruit_chance : float = 1.0
            Probability of fruit-bearing variant (apples, durians, etc).
        coarse : bool = False
            Pass-through for upstream's coarse-mode flag.

    All other knobs are forwarded to upstream `TreeFactory.__init__`.
    """

    def __init__(
        self,
        factory_seed: int,
        archetype: str = "any",
        fruit_chance: float = 1.0,
        coarse: bool = False,
        **kwargs,
    ):
        if archetype not in _TREE_ARCHETYPES:
            raise ValueError(
                f"archetype={archetype!r} not in {_TREE_ARCHETYPES}"
            )
        season = None if archetype == "any" else archetype
        super().__init__(
            factory_seed,
            season=season,
            coarse=coarse,
            fruit_chance=fruit_chance,
            **kwargs,
        )

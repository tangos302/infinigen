"""RealisticGrassTuftFactory — realistic grass tuft, wraps upstream Infinigen.

Delegates to `infinigen.assets.objects.grassland.grass_tuft.GrassTuftFactory`.
Upstream generates 30–60 curve-based blades per tuft with tapered widths
and a per-tuft colour shader. There are no geometric knobs to expose
beyond the seed; archetype is purely a label so the LLM can pick a
mood-fit but maps to a stochastic re-seed under the hood.

Used via scatter: spawn one tuft template, instance via the existing
`runtime.scatter.scatter_on_terrain` helper or via upstream
`infinigen.assets.scatters.grass.apply()` for biome-aware density.
"""

from __future__ import annotations

from infinigen.assets.objects.grassland.grass_tuft import GrassTuftFactory


_GRASS_ARCHETYPES = ("meadow", "tall", "dry", "any")


class RealisticGrassTuftFactory(GrassTuftFactory):
    """Realistic grass tuft factory.

    Constructor knobs:

        factory_seed : int
        archetype : str = "any"
            Label only — meadow / tall / dry / any. Upstream has no
            morphology knob; we hash the archetype into the seed so each
            archetype draws a different but deterministic genome.
    """

    def __init__(
        self,
        factory_seed: int,
        archetype: str = "any",
        **kwargs,
    ):
        if archetype not in _GRASS_ARCHETYPES:
            raise ValueError(
                f"archetype={archetype!r} not in {_GRASS_ARCHETYPES}"
            )
        # Hash archetype into seed so different archetypes deterministically
        # diverge — upstream has no other knob to vary mood.
        salt = sum(ord(c) for c in archetype) * 7919
        super().__init__(factory_seed + salt, **kwargs)

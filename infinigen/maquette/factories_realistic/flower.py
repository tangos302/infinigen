"""RealisticFlowerFactory — realistic wildflower, wraps upstream Infinigen.

Delegates to `infinigen.assets.objects.grassland.flower.FlowerFactory`.
Upstream procedurally generates spiral-phyllo petal arrangements; the
species variation is shader-driven, not geometric. The one geometric
knob worth surfacing is petal radius.

Archetype mapping → upstream `rad` + `diversity_fac`:

    "small"  : rad=0.08, tighter color (diversity_fac=0.15)
    "medium" : rad=0.15, default
    "large"  : rad=0.25, wider color spread
    "any"    : medium defaults
"""

from __future__ import annotations

from infinigen.assets.objects.grassland.flower import FlowerFactory


_FLOWER_ARCHETYPES = ("small", "medium", "large", "any")

_ARCHETYPE_TO_PARAMS: dict[str, dict[str, float]] = {
    "small": {"rad": 0.08, "diversity_fac": 0.15},
    "medium": {"rad": 0.15, "diversity_fac": 0.25},
    "large": {"rad": 0.25, "diversity_fac": 0.35},
    "any": {"rad": 0.15, "diversity_fac": 0.25},
}


class RealisticFlowerFactory(FlowerFactory):
    """Realistic wildflower factory.

    Constructor knobs:

        factory_seed : int
        archetype : str = "any"
            One of: small / medium / large / any.
        rad : float | None = None
            Override petal radius. If set, ignores archetype's default.
        diversity_fac : float | None = None
            Override per-flower color diversity multiplier.
    """

    def __init__(
        self,
        factory_seed: int,
        archetype: str = "any",
        rad: float | None = None,
        diversity_fac: float | None = None,
        **kwargs,
    ):
        if archetype not in _FLOWER_ARCHETYPES:
            raise ValueError(
                f"archetype={archetype!r} not in {_FLOWER_ARCHETYPES}"
            )
        defaults = _ARCHETYPE_TO_PARAMS[archetype]
        super().__init__(
            factory_seed,
            rad=rad if rad is not None else defaults["rad"],
            diversity_fac=(
                diversity_fac if diversity_fac is not None else defaults["diversity_fac"]
            ),
            **kwargs,
        )

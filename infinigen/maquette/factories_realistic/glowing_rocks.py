"""RealisticGlowingRocksFactory — luminescent gem rocks, wraps upstream.

Specialty asset: emissive shader baked in for magical / cave / fantasy
scenes. Watt power tunable. Use sparingly — these are visual focal
points, not fill detail.
"""

from __future__ import annotations

from infinigen.assets.objects.rocks.glowing_rocks import GlowingRocksFactory


_GLOW_ARCHETYPES = ("dim", "bright", "any")

_ARCHETYPE_TO_WATT: dict[str, tuple[float, float]] = {
    "dim": (200.0, 400.0),
    "bright": (600.0, 1200.0),
    "any": (400.0, 800.0),
}


class RealisticGlowingRocksFactory(GlowingRocksFactory):
    """Realistic glowing-rock factory.

    Constructor knobs:

        factory_seed : int
        archetype : str = "any"
            One of: dim / bright / any. Maps to upstream watt_power_range.
        coarse : bool = False
    """

    def __init__(
        self,
        factory_seed: int,
        archetype: str = "any",
        coarse: bool = False,
        **kwargs,
    ):
        if archetype not in _GLOW_ARCHETYPES:
            raise ValueError(
                f"archetype={archetype!r} not in {_GLOW_ARCHETYPES}"
            )
        watt = _ARCHETYPE_TO_WATT[archetype]
        super().__init__(
            factory_seed,
            coarse=coarse,
            watt_power_range=watt,
            **kwargs,
        )

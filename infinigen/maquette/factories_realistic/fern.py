"""RealisticFernFactory — realistic fern, wraps upstream Infinigen.

Delegates to `infinigen.assets.objects.small_plants.fern.FernFactory`.
Upstream procedurally generates leaflet-bearing fronds with curvature
sampled per seed.
"""

from __future__ import annotations

from infinigen.assets.objects.small_plants.fern import FernFactory


_FERN_ARCHETYPES = ("frond", "shuttlecock", "any")


class RealisticFernFactory(FernFactory):
    """Realistic fern factory.

    Constructor knobs:

        factory_seed : int
        archetype : str = "any"
            Label only — frond / shuttlecock / any.
        coarse : bool = False
    """

    def __init__(
        self,
        factory_seed: int,
        archetype: str = "any",
        coarse: bool = False,
        **kwargs,
    ):
        if archetype not in _FERN_ARCHETYPES:
            raise ValueError(
                f"archetype={archetype!r} not in {_FERN_ARCHETYPES}"
            )
        salt = sum(ord(c) for c in archetype) * 5417
        super().__init__(factory_seed + salt, coarse=coarse, **kwargs)

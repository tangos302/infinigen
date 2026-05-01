"""RealisticBlenderRockFactory — small rock variants, wraps upstream.

Distinct from BoulderFactory: this is a lightweight rock used as
ground-strewn pebbles / small accent rocks. BoulderFactory is the
hero-scale variant.
"""

from __future__ import annotations

from infinigen.assets.objects.rocks.blender_rock import BlenderRockFactory


_ROCK_ARCHETYPES = ("pebble", "fragment", "any")


class RealisticBlenderRockFactory(BlenderRockFactory):
    """Realistic small-rock factory.

    Constructor knobs:

        factory_seed : int
        archetype : str = "any"
            Label only — pebble / fragment / any.
        detail : int = 1
            Subdivision detail level. Higher = smoother silhouette.
    """

    def __init__(
        self,
        factory_seed: int,
        archetype: str = "any",
        detail: int = 1,
        **kwargs,
    ):
        if archetype not in _ROCK_ARCHETYPES:
            raise ValueError(
                f"archetype={archetype!r} not in {_ROCK_ARCHETYPES}"
            )
        salt = sum(ord(c) for c in archetype) * 6367
        super().__init__(factory_seed + salt, detail=detail, **kwargs)

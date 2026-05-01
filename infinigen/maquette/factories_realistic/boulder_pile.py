"""RealisticBoulderPileFactory — clustered rock pile, DISABLED.

Upstream BoulderPileFactory has cascading bugs we partially patched
(positional-arg mix-up routing ``coarse`` into ``meshing_cameras``;
missing ``i`` arg in create_asset; wrapper-Empty assumptions about
placeholder children; silent post-join exit after the physics
simulation runs). We patched the first three in
``infinigen/assets/objects/rocks/pile.py`` but the fourth is buried in
``join_objects`` and post-physics cleanup.

For v1 this factory raises NotImplementedError to send callers to the
simpler workaround: spawn ``RealisticBoulderFactory`` N times at
clustered positions yourself. Same visual result, no upstream bug
exposure.

Re-enable once upstream pile.py gets a maintenance pass.
"""

from __future__ import annotations

from infinigen.assets.objects.rocks.pile import BoulderPileFactory


_PILE_ARCHETYPES = ("scree", "cluster", "any")


class RealisticBoulderPileFactory(BoulderPileFactory):
    """Realistic boulder-pile factory.

    NOT FUNCTIONAL — see module docstring. Constructor accepts kwargs
    for catalog parity but spawn_asset raises NotImplementedError.

    Use ``RealisticBoulderFactory`` × N at clustered positions instead.
    """

    def __init__(
        self,
        factory_seed: int,
        archetype: str = "any",
        coarse: bool = False,
        **kwargs,
    ):
        if archetype not in _PILE_ARCHETYPES:
            raise ValueError(
                f"archetype={archetype!r} not in {_PILE_ARCHETYPES}"
            )
        salt = sum(ord(c) for c in archetype) * 7253
        super().__init__(factory_seed + salt, coarse=coarse, **kwargs)

    def spawn_asset(self, *args, **kwargs):
        raise NotImplementedError(
            "RealisticBoulderPileFactory is disabled in v1 due to upstream "
            "bugs in infinigen.assets.objects.rocks.pile. Spawn 3-6 "
            "RealisticBoulderFactory instances at clustered positions for "
            "the same visual effect."
        )

"""Cluster-placement helper for visually-spiky props (cacti, hero trees).

Why this exists: Sonnet's reflex when asked for desert flora is a
``for i in range(N): rng.uniform(-65, 65)`` scatter loop. Saguaro cacti
are 4 m tall thin columns with arms; 18-22 random scatters across a
160 BU map produces a forest of disconnected vertical pickets that
read as spike noise instead of designed flora.

The brief's prose rule "place in 2-4 deliberate clusters" was ignored
by the model in two consecutive runs, so we move the rule from prose
to a callable helper. The brief now FORBIDS Python-loop cactus scatter
and directs Sonnet to ``place_grove`` instead.

Usage::

    from infinigen.maquette.runtime.grove import place_grove
    from infinigen.maquette.factories.native.cactus import LowPolyCactusFactory

    place_grove(
        factory_class=LowPolyCactusFactory,
        centers=[(20, -15), (-30, 25), (45, 5)],   # 2-4 designed locations
        per_cluster=4,                              # 3-5 props each
        radius=4.0,                                 # cluster spread in BU
        terrain=terrain,
        scale_range=(0.85, 1.15),                   # min floor 0.85
        archetypes=("saguaro", "barrel"),
        seed=42,
    )

The helper enforces:
  * Each cluster has exactly ``per_cluster`` props.
  * Props sit on the carved terrain via ``terrain.height_at``.
  * Cluster offsets follow a Halton 2D quasi-random sequence so
    points spread evenly within ``radius`` instead of clumping.
  * Total prop count is bounded — clusters × per_cluster.

Extensible to other tall-thin factories (palm trees on dunes, dead
trees) by passing a different ``factory_class``. Default tuning is
calibrated for cacti.
"""

from __future__ import annotations

import math
import random
from typing import Any, Optional, Sequence


def place_grove(
    *,
    factory_class: Any,
    centers: Sequence[tuple[float, float]],
    per_cluster: int = 4,
    radius: float = 4.0,
    terrain: Any,
    scale_range: tuple[float, float] = (0.85, 1.15),
    archetypes: Optional[Sequence[str]] = None,
    archetype_kwarg: str = "cactus_archetype",
    seed: int = 0,
) -> int:
    """Spawn ``per_cluster`` props per ``centers`` location.

    Parameters
    ----------
    factory_class : type
        e.g. ``LowPolyCactusFactory``. Must accept ``factory_seed`` and
        the named ``archetype_kwarg``, and expose ``create_asset()``.
    centers : Sequence[(x, y)]
        2-4 designed cluster centers. Caller picks these to fit the
        composition (path bend, ruin edge, between heroes).
    per_cluster : int
        Props per cluster. Clamped to [1, 8].
    radius : float
        Halton offset radius from each center. Props sit within this
        circle of the cluster center.
    terrain : terrain handle
        Required. Props are placed at ``terrain.height_at(x, y)``.
    scale_range : (lo, hi)
        Per-prop scale uniform sample range.
    archetypes : Sequence[str] | None
        If given, archetype is sampled per prop; falls back to factory
        default when None.
    archetype_kwarg : str
        Name of the factory's archetype kwarg (``cactus_archetype``,
        ``palm_archetype``, ...). Only used when ``archetypes`` is given.
    seed : int
        Determinism handle.

    Returns
    -------
    int
        Total props spawned.
    """
    if terrain is None or not hasattr(terrain, "height_at"):
        raise ValueError("place_grove requires a terrain handle with .height_at()")

    n = max(1, min(8, int(per_cluster)))
    rng = random.Random(seed)
    total = 0

    for ci, (cx, cy) in enumerate(centers):
        cx_f, cy_f = float(cx), float(cy)
        for i in range(n):
            # Halton 2D — deterministic well-spread offsets.
            ox, oy = _halton_2d(ci * 100 + i + 1)
            # Map [0,1)² into a disc of given radius, centered at cluster.
            theta = ox * 2.0 * math.pi
            r = math.sqrt(oy) * float(radius)
            x = cx_f + math.cos(theta) * r
            y = cy_f + math.sin(theta) * r
            try:
                z = float(terrain.height_at(x, y))
            except Exception:
                z = 0.0
            kw: dict = {}
            if archetypes:
                kw[archetype_kwarg] = rng.choice(list(archetypes))
            obj = factory_class(
                factory_seed=int(seed + ci * 7919 + i * 137) & 0xFFFF,
                **kw,
            ).create_asset(placeholder=None)
            s = rng.uniform(float(scale_range[0]), float(scale_range[1]))
            obj.scale = (s, s, s)
            obj.location = (x, y, z)
            obj.rotation_euler.z = rng.uniform(0.0, 2.0 * math.pi)
            total += 1
    return total


def _halton_2d(i: int) -> tuple[float, float]:
    """Two-dimensional Halton sequence sample (bases 2 and 3). Returns
    coordinates in [0, 1)². The sequence is well-spread but
    deterministic, so ``radius=4`` produces the same 4 offsets every
    time for a given cluster index.
    """
    return _van_der_corput(i, 2), _van_der_corput(i, 3)


def _van_der_corput(i: int, base: int) -> float:
    """Reverse-radix fraction in base ``base`` — the building block of
    a Halton sequence. ``i=1, base=2 → 0.5; i=2 → 0.25; i=3 → 0.75``."""
    x = 0.0
    f = 1.0 / base
    while i > 0:
        x += f * (i % base)
        i //= base
        f /= base
    return x

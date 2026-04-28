"""Scene composition primitives for Maquette.

The boulder and tree factory wrappers individually emit one
faceted-low-poly asset per spawn. Scenes compose those — a
flat-ish ground patch with N boulders and M trees scattered with
sane spacing. This is the v0 scene primitive; it isn't trying to
replace Infinigen's full nature/terrain pipeline, just give us a
reliable harness for "do my factories COMPOSE into something
recognizable as a Firewatch landscape".

Design choices:
  - Random placement with a minimum-distance reject filter
    (Poisson-disk-lite). Cheap, deterministic given a seed,
    fine for the 10–100-asset scenes Maquette targets.
  - Ground is a flat subdivided plane; per-object ground
    deformation is out of v0 scope.
  - Each spec is `(factory_cls, count, kwargs)`. The factory's
    own `factory_seed` is offset per instance so each gets a
    distinct shape but the *scene* remains deterministic from
    `scene_seed`.
  - Returned dict carries object lists per spec so callers can
    apply class-based palette colors after the fact (or just
    pass `palette_color` in factory kwargs).
"""

from __future__ import annotations

import math
import random
from typing import Iterable

import bpy
from mathutils import Vector

from .palette import MAQUETTE_PALETTE


def _make_ground(name: str, size: float, palette_color: str | None) -> bpy.types.Object:
    bpy.ops.mesh.primitive_plane_add(size=size, location=(0, 0, 0))
    g = bpy.context.active_object
    g.name = name
    if palette_color is not None:
        # Local import so this module doesn't pull `materials` unless used.
        from .materials import apply_palette
        apply_palette(g, palette_color)
    return g


def _poisson_lite(
    rng: random.Random,
    n: int,
    radius: float,
    min_spacing: float,
    max_attempts: int = 64,
) -> list[tuple[float, float]]:
    """Return up to `n` (x, y) positions inside a disk of `radius`, with
    pairwise distance >= `min_spacing`. Reject-on-collision; not
    Bridson's algorithm — this is a tiny scatter, the dumb version is
    fine and produces good visual distribution for n ≲ 200."""
    placed: list[tuple[float, float]] = []
    for _ in range(n * max_attempts):
        if len(placed) >= n:
            break
        # Sample uniformly in disk
        ang = rng.uniform(0, math.tau)
        r = math.sqrt(rng.random()) * radius
        x = r * math.cos(ang)
        y = r * math.sin(ang)
        if all((x - px) ** 2 + (y - py) ** 2 >= min_spacing ** 2 for px, py in placed):
            placed.append((x, y))
    return placed


def scatter_demo(
    factories: Iterable[tuple[type, int, dict | None]],
    ground_size: float = 30.0,
    scene_seed: int = 0,
    min_spacing: float = 1.5,
    ground_palette_color: str | None = "ground_grass",
) -> dict:
    """Build a flat-ground scene with each factory class scattered on it.

    `factories` is an iterable of `(factory_cls, count, kwargs)` triples.
    Per spec, `count` instances are spawned with consecutive
    `factory_seed` values starting from `scene_seed * 1000 + spec_idx * 100`
    so each scene_seed is reproducible.

    Caller is responsible for camera + lighting + render. Returns a dict
    {spec_index: {factory_cls: <cls>, objects: [...], positions: [...]}}.
    """
    rng = random.Random(scene_seed)

    # Wipe existing geometry so the ground sits at z=0 cleanly. (We don't
    # touch lights/cameras — that's the caller's setup.)
    for o in list(bpy.data.objects):
        if o.type in {"MESH"}:
            bpy.data.objects.remove(o, do_unlink=True)

    ground = _make_ground("Maquette_Ground", ground_size, ground_palette_color)

    spawned: dict = {"ground": ground, "specs": []}
    radius = ground_size * 0.45  # leave a margin from the plane edge

    for spec_idx, (factory_cls, count, kwargs) in enumerate(factories):
        kwargs = kwargs or {}
        positions = _poisson_lite(rng, count, radius, min_spacing)
        objects = []
        for inst, (x, y) in enumerate(positions):
            seed = scene_seed * 1000 + spec_idx * 100 + inst
            factory = factory_cls(factory_seed=seed, **kwargs)
            obj = factory.spawn_asset(0)
            obj.location = Vector((x, y, 0))
            obj.rotation_euler = (0, 0, rng.uniform(0, math.tau))
            objects.append(obj)
        spawned["specs"].append(
            {"factory_cls": factory_cls, "objects": objects, "positions": positions}
        )

    return spawned

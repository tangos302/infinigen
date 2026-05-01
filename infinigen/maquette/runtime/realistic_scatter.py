"""Realistic-mode scatter helper — sidesteps the >5-tree spawn limit.

Realistic-mode build scripts that need a forest hit a hard upstream
limit at ~5 RealisticTreeFactory spawns (each tree's twig-collection
generation accumulates state Blender 4.2 silently chokes on after a
threshold). The fix that scales: spawn ONE template, scatter it as
instanced geometry on the terrain.

Two scatter strategies live here:

* ``scatter_template`` — wraps the GN-based ``scatter_on_terrain``.
  Cheapest because instances share mesh data via geometry nodes;
  good for dense ground cover (grass, flowers).
* ``scatter_template_with_keepout`` — Python-side Poisson sampling
  with keep-out radii around landmark positions. Use this when the
  scatter must NOT collide with hand-placed assets (cottages,
  wells, walls). Slightly heavier (real instance copies, not GN
  evaluation) but precise.

Densities (instances per BU² of eligible surface area):

    trees on grass     : 0.002 - 0.008  (PS3-era — reads as forest)
    boulders on alpine : 0.005 - 0.020
    grass tufts        : 0.05  - 0.20   (ground cover)
    flowers            : 0.02  - 0.10
"""

from __future__ import annotations

import bpy

from .scatter import scatter_on_terrain


def scatter_template(
    *,
    terrain,
    template: bpy.types.Object,
    density: float,
    biome_filter: str = "any",
    seed: int = 0,
    scale_jitter: tuple[float, float] = (0.85, 1.20),
    name: str | None = None,
) -> bpy.types.Object:
    """Scatter ``template`` across ``terrain`` as a Geometry-Nodes
    instancer. Returns the scatter object whose evaluated mesh holds
    the realised instances.

    The underlying ``scatter_on_terrain`` already hides the template
    from camera by default (``hide_instance_template=True``) so the
    source doesn't double-render alongside the scatter.

    Accepts ``terrain`` as either the ``Terrain`` dataclass returned by
    ``make_terrain`` (with ``.obj``) or a raw mesh object.
    """
    return scatter_on_terrain(
        terrain_obj=terrain.obj if hasattr(terrain, "obj") else terrain,
        instance_obj=template,
        density=density,
        biome_filter=biome_filter,
        seed=seed,
        scale_jitter=scale_jitter,
        name=name,
    )


def scatter_template_with_keepout(
    *,
    terrain,
    template: bpy.types.Object,
    density: float,
    keep_out: list[tuple[float, float, float]] | None = None,
    seed: int = 0,
    scale_jitter: tuple[float, float] = (0.85, 1.20),
    rotation_jitter_z: bool = True,
    align_to_normal: bool = False,
    name: str | None = None,
) -> list[bpy.types.Object]:
    """Scatter copies of ``template`` across ``terrain`` as REAL object
    instances (mesh-shared with the template via linked-data), filtered
    by keep-out radii so they don't collide with hand-placed landmarks.

    Each instance is a fresh ``bpy.types.Object`` whose ``data`` is the
    same mesh as the template — the disk and GPU pay for the mesh once,
    transformations are per-object. Heavier than the GN scatter (one
    obj per instance) but precise: we can filter by arbitrary
    Python-side rules.

    ``keep_out``: list of ``(x, y, radius)`` tuples. Any candidate point
    within the disc is rejected. Pass the locations + bounding radii of
    your cottages, wells, walls, etc. — the scatter walks around them.

    ``density``: same units as ``scatter_template`` — instances per BU²
    of terrain area before keep-out filtering. After filtering, the
    realised count is lower in proportion to the keep-out coverage.
    """
    import random

    import numpy as np

    if not hasattr(terrain, "height_at"):
        raise TypeError("scatter_template_with_keepout needs a Terrain dataclass")

    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)

    terrain_obj = terrain.obj
    # Estimate terrain area from its bounding box so we can hit ~density
    # instances per BU² without enumerating mesh faces.
    bbox_corners = [terrain_obj.matrix_world @ v.co for v in terrain_obj.data.vertices]
    if not bbox_corners:
        return []
    xs = [c.x for c in bbox_corners]
    ys = [c.y for c in bbox_corners]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    area = (x_max - x_min) * (y_max - y_min)
    n_target = max(1, int(area * density))

    # Poisson-disk minimum spacing — ensures even-but-not-grid spread.
    # 2-D Poisson density d implies minimum-spacing ~ 1 / sqrt(pi * d * 2).
    min_dist = 1.0 / (3.14159 * density * 2.0) ** 0.5

    keep_out = list(keep_out or [])
    placed: list[tuple[float, float]] = []
    instances: list[bpy.types.Object] = []

    # 4 attempts per slot per failed pass; cap total attempts so an
    # over-constrained terrain doesn't loop forever.
    attempts_budget = 8 * n_target
    while len(instances) < n_target and attempts_budget > 0:
        attempts_budget -= 1
        x = float(np_rng.uniform(x_min, x_max))
        y = float(np_rng.uniform(y_min, y_max))

        # Reject if too close to a previously-placed instance.
        too_close = any(
            (x - px) ** 2 + (y - py) ** 2 < min_dist * min_dist
            for px, py in placed
        )
        if too_close:
            continue

        # Reject if inside any keep-out disc.
        in_keepout = any(
            (x - kx) ** 2 + (y - ky) ** 2 < kr * kr
            for kx, ky, kr in keep_out
        )
        if in_keepout:
            continue

        z = terrain.height_at(x, y)
        inst = bpy.data.objects.new(
            f"{name or template.name}.scatter.{len(instances)}",
            template.data,
        )
        inst.location = (x, y, z)
        if rotation_jitter_z:
            inst.rotation_euler.z = rng.uniform(0, 6.283185)
        s = rng.uniform(scale_jitter[0], scale_jitter[1])
        inst.scale = (s, s, s)
        bpy.context.collection.objects.link(inst)
        instances.append(inst)
        placed.append((x, y))

    # Hide the source template from the camera so it doesn't double-
    # render at the origin alongside the placed instances.
    template.hide_render = True
    template.hide_viewport = True

    return instances

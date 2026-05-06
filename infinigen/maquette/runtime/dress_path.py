"""Prop-dressing helper for ``Pathway`` corridors.

Spawns native factory objects along the centerline of every ``Pathway``
in a ``Composition``. The path itself only carves a saddle into the
heightmap and tints a vertex-colour band; this helper adds the actual
3D props (lanterns, curb stones, post fences) that make a path read as
"a place humans walk" instead of "a discoloured strip of dirt".

Why a runtime helper and not in-brief loops? Three reasons:

  1. The math (Catmull-Rom resample → arc-length walk → terrain.height_at)
     is identical to what ``apply_composition`` already runs, so we want
     ONE implementation, not the LLM re-deriving spacing every prompt.
  2. Sonnet routinely picks bad spacings (lantern every 1 BU, fence
     every 30 BU) when left to author the loop itself.
  3. Adding new path archetypes later (rope-and-post, milestone cairns)
     means editing one Python file — no brief sprawl.

Sonnet calls this from the build script AFTER ``apply_composition``,
once the terrain is final and ``terrain.height_at(x, y)`` will return
the carved saddle elevation.

Available archetypes:

  * ``lantern_posts`` — alternating lanterns left/right of corridor
    edge. Cadence default 6 BU. Reads as formal village/garden lighting.
  * ``curb_stones`` — small boulders peppering both edges. Cadence 2 BU.
    Reads as rustic dirt-track shoulder.
  * ``fence_posts`` — short post-and-rail segments along ONE side
    (the side facing away from the dominant hero, if any). Cadence
    is per-segment-length; each segment is ~length= cadence BU long.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence


@dataclass
class _Pose:
    """One emit slot along the resampled centerline."""
    x: float
    y: float
    tangent_x: float
    tangent_y: float
    arc_s: float  # cumulative arc length from path start
    side: int     # +1 (left of travel direction) or -1 (right)


def dress_path(
    composition: Any,
    *,
    archetype: str = "lantern_posts",
    terrain: Any,
    spacing: float | None = None,
    offset: float = 0.6,
    seed: int = 0,
    path_index: Optional[int] = None,
    sun_side: str = "south",
) -> int:
    """Dress every Pathway in ``composition`` with props of ``archetype``.

    Parameters
    ----------
    composition : Composition
        The composition whose ``paths`` will be dressed. Returns 0 if
        no paths.
    archetype : str
        ``"lantern_posts"``, ``"curb_stones"``, or ``"fence_posts"``.
    terrain : terrain handle
        Returned by ``make_eroded_terrain`` (must expose
        ``height_at(x, y)``). Required so props sit on the carved
        saddle, not at z=0.
    spacing : float | None
        BU between consecutive emits along the centerline. Defaults to
        archetype's natural cadence (6 BU lanterns, 2 BU curbs,
        4 BU fence posts). Pass a custom value to densify / thin out.
    offset : float
        Extra BU pushed perpendicular to path direction past the
        corridor edge. ``path.width / 2 + offset`` is the actual
        centerline-to-prop distance. 0.6 BU keeps the prop just
        clear of the path.
    seed : int
        Determinism handle. Different paths in the same composition
        get ``seed + path_index * 101`` to avoid identical jitter.
    path_index : int | None
        Dress only one path index (0-based). ``None`` (default) dresses
        all paths.
    sun_side : str
        ``"south" | "north" | "east" | "west"`` — for ``fence_posts``,
        the fence emits on the OPPOSITE side from the sun so it doesn't
        cast across the walking surface. Ignored by other archetypes.

    Returns
    -------
    int
        Number of props spawned.
    """
    paths = list(getattr(composition, "paths", None) or [])
    if not paths:
        return 0
    if archetype not in _DISPATCH:
        raise ValueError(
            f"dress_path: unknown archetype {archetype!r}; "
            f"valid: {sorted(_DISPATCH)}"
        )
    if terrain is None or not hasattr(terrain, "height_at"):
        raise ValueError("dress_path requires a terrain handle with .height_at()")

    spawn_fn = _DISPATCH[archetype]
    default_spacing = _DEFAULT_SPACING[archetype]
    step = float(spacing) if spacing is not None else default_spacing

    total = 0
    for idx, path in enumerate(paths):
        if path_index is not None and idx != path_index:
            continue
        poses = _walk_centerline(
            path,
            step=step,
            offset=offset,
            seed=seed + idx * 101,
            sun_side=sun_side,
            dress_archetype=archetype,
        )
        for pose in poses:
            try:
                z = float(terrain.height_at(pose.x, pose.y))
            except Exception:
                z = 0.0
            spawn_fn(pose, z, seed=seed + idx * 101 + total)
            total += 1
    return total


# ───────────────────────── archetype dispatch ─────────────────────────


def _spawn_lantern(pose: _Pose, z: float, *, seed: int) -> None:
    import bpy  # noqa: F401
    from infinigen.maquette.factories.native.lantern_post import (
        LowPolyLanternPostFactory,
    )

    f = LowPolyLanternPostFactory(
        factory_seed=int(seed) & 0xFFFF, lantern_archetype="iron_post"
    )
    obj = f.create_asset(placeholder=None)
    obj.location = (pose.x, pose.y, z)
    # Lanterns face toward the path — rotate so post faces the
    # centerline; visual "lamp" sits over the walking surface.
    import math as _m

    obj.rotation_euler.z = _m.atan2(pose.tangent_y, pose.tangent_x)


def _spawn_curb_stone(pose: _Pose, z: float, *, seed: int) -> None:
    import random
    from infinigen.maquette.factories.boulder import LowPolyBoulderFactory

    rng = random.Random(seed)
    f = LowPolyBoulderFactory(factory_seed=int(seed) & 0xFFFF)
    obj = f.spawn_asset(i=int(seed) & 0xFFFF, loc=(pose.x, pose.y, z))
    s = rng.uniform(0.18, 0.32)
    obj.scale = (s, s, s)


def _spawn_fence_post(pose: _Pose, z: float, *, seed: int) -> None:
    import math as _m
    from infinigen.maquette.factories.native.fence import LowPolyFenceFactory

    f = LowPolyFenceFactory(
        factory_seed=int(seed) & 0xFFFF,
        fence_archetype="post_and_rail",
        length=3.4,
    )
    obj = f.create_asset(placeholder=None)
    obj.location = (pose.x, pose.y, z)
    # Fence segment runs along the path tangent.
    obj.rotation_euler.z = _m.atan2(pose.tangent_y, pose.tangent_x)


_DISPATCH = {
    "lantern_posts": _spawn_lantern,
    "curb_stones": _spawn_curb_stone,
    "fence_posts": _spawn_fence_post,
}

_DEFAULT_SPACING = {
    "lantern_posts": 6.0,
    "curb_stones": 2.0,
    "fence_posts": 4.0,
}


# ───────────────────────── arc-length walker ─────────────────────────


def _walk_centerline(
    path: Any,
    *,
    step: float,
    offset: float,
    seed: int,
    sun_side: str,
    dress_archetype: str = "lantern_posts",
) -> list[_Pose]:
    """Sample the resampled centerline of ``path`` every ``step`` BU
    and emit a ``_Pose`` on each edge (alternating sides for lanterns/
    curb stones; sun-opposite side for fence posts).
    """
    # Local import keeps influence import lazy.
    from infinigen.maquette.runtime.influence import _resample_catmull

    # Match the resample done inside apply_path_tint so props track
    # the carved curve rather than the raw user polyline.
    jitter = 0.0 if getattr(path, "archetype", "dirt") == "stone" else 0.45
    smoothed = _resample_catmull(
        list(path.waypoints),
        samples_per_segment=12,
        jitter=jitter,
        seed=seed,
    )
    if len(smoothed) < 2:
        return []

    # Cumulative arc length so we can walk by arc-length.
    arc: list[float] = [0.0]
    for i in range(1, len(smoothed)):
        ax, ay = smoothed[i - 1]
        bx, by = smoothed[i]
        arc.append(arc[-1] + ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5)
    total_len = arc[-1]
    if total_len < step * 1.5:
        return []  # path too short to dress meaningfully

    half = float(getattr(path, "width", 2.5)) * 0.5
    edge_dist = half + float(offset)

    # Decide side policy. Fence segments must run on a single side
    # (chained alternating fence pieces look broken); pick the side
    # opposite the sun so they don't shade the walking surface.
    if dress_archetype == "fence_posts":
        side_fn = _side_from_sun(sun_side)
    else:
        side_fn = _SIDE_POLICIES["alternating"]

    poses: list[_Pose] = []
    s = step  # start one step in so we don't crowd the start waypoint
    j = 1
    while s < total_len - step * 0.5:
        # Find segment index containing arc s.
        while j < len(arc) and arc[j] < s:
            j += 1
        i0 = max(0, j - 1)
        i1 = min(len(smoothed) - 1, j)
        seg_len = max(arc[i1] - arc[i0], 1e-6)
        t = (s - arc[i0]) / seg_len
        ax, ay = smoothed[i0]
        bx, by = smoothed[i1]
        cx = ax + (bx - ax) * t
        cy = ay + (by - ay) * t
        tx = bx - ax
        ty = by - ay
        ll = (tx * tx + ty * ty) ** 0.5 + 1e-9
        tx /= ll
        ty /= ll
        # Binormal (perpendicular CCW).
        nx = -ty
        ny = tx
        side = side_fn(len(poses))
        px = cx + nx * edge_dist * side
        py = cy + ny * edge_dist * side
        poses.append(
            _Pose(x=px, y=py, tangent_x=tx, tangent_y=ty, arc_s=s, side=side)
        )
        s += step
    return poses


def _alternating(i: int) -> int:
    return 1 if (i % 2 == 0) else -1


def _always_left(_: int) -> int:
    return 1


def _always_right(_: int) -> int:
    return -1


_SIDE_POLICIES = {
    "alternating": _alternating,
    "left": _always_left,
    "right": _always_right,
}


def _side_from_sun(sun_side: str):
    """Return a side policy that puts props OPPOSITE the sun. Sun in
    the south → fence emits on the north side (+Y) so it doesn't shade
    the path. Crude but sufficient for painterly framing."""
    s = (sun_side or "south").lower()
    # Rough convention: Y is "north" axis. South sun → north fence.
    if s in ("south", "se", "sw"):
        return _always_left
    if s in ("north", "ne", "nw"):
        return _always_right
    return _alternating

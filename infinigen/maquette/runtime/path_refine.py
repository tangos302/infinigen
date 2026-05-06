"""A* path refinement for LLM-emitted waypoints.

The LLM emits high-level path waypoints (anchor → milestone → terminus).
When a straight-line segment between two anchors would cross terrain
exceeding ``max_slope_deg``, this module replaces it with an A*-routed
path on a downsampled heightmap so the corridor detours around cliffs
instead of climbing them at impossible grades.

Use case: the brief asks for "winding path from oasis to peak base" but
the straight line crosses a 50 BU cliff face. A* finds the saddle and
routes the path around the cliff.

Algorithm:
- Downsample the (res, res) heightmap by ``grid_step`` (default 4) so
  256² → 64² nodes — fast enough to A* per segment in <50 ms.
- Per consecutive waypoint pair: a Bresenham line check first. If the
  direct ray's max neighbour-step rise stays under the slope budget,
  skip A* (most segments).
- Otherwise A* with 8-connected neighbours, distance heuristic, edge
  cost = step × (1 + 2·slope²).
- Decimate the A* output (every 3rd point) so downstream Catmull-Rom
  doesn't over-articulate.

If A* finds no path (cliff fully encircles the goal), keep the LLM
segment unchanged — the caller may want to spawn a ``Bridge`` later.
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Sequence

import numpy as np


def _world_to_grid(x: float, y: float, size: float, res: int) -> tuple[int, int]:
    span = 2.0 * size
    gx = int(round((x + size) / span * (res - 1)))
    gy = int(round((y + size) / span * (res - 1)))
    return max(0, min(res - 1, gx)), max(0, min(res - 1, gy))


def _grid_to_world(gx: int, gy: int, size: float, res: int) -> tuple[float, float]:
    span = 2.0 * size
    x = gx / (res - 1) * span - size
    y = gy / (res - 1) * span - size
    return float(x), float(y)


def _direct_passable(
    H: np.ndarray, sx: int, sy: int, gx: int, gy: int, max_rise: float
) -> bool:
    """Walk the Bresenham line from (sx, sy) to (gx, gy); fail if any
    one-cell step exceeds ``max_rise`` (1.4× tolerance for diagonals).
    """
    dx = abs(gx - sx)
    dy = -abs(gy - sy)
    sxd = 1 if sx < gx else -1
    syd = 1 if sy < gy else -1
    err = dx + dy
    x, y = sx, sy
    last_z = float(H[y, x])
    while True:
        if x == gx and y == gy:
            return True
        e2 = 2 * err
        moved_diag = False
        if e2 >= dy:
            err += dy
            x += sxd
            moved_diag = True
        if e2 <= dx:
            err += dx
            y += syd
            if moved_diag:
                pass  # diagonal step
        z = float(H[y, x])
        if abs(z - last_z) > max_rise * 1.4:
            return False
        last_z = z


def _astar(
    H: np.ndarray,
    sx: int,
    sy: int,
    gx: int,
    gy: int,
    cell_size_world: float,
    max_rise: float,
) -> list[tuple[int, int]] | None:
    res = H.shape[0]
    if (sx, sy) == (gx, gy):
        return [(sx, sy)]
    diag_8 = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))
    open_q: list[tuple[float, int, int, int]] = [(0.0, 0, sx, sy)]
    came: dict[tuple[int, int], tuple[int, int]] = {}
    g_score: dict[tuple[int, int], float] = {(sx, sy): 0.0}
    counter = 0

    while open_q:
        _, _, x, y = heapq.heappop(open_q)
        if (x, y) == (gx, gy):
            path = [(x, y)]
            while (x, y) in came:
                x, y = came[(x, y)]
                path.append((x, y))
            return list(reversed(path))
        for dx, dy in diag_8:
            nx, ny = x + dx, y + dy
            if not (0 <= nx < res and 0 <= ny < res):
                continue
            rise = abs(float(H[ny, nx]) - float(H[y, x]))
            if rise > max_rise:
                continue  # too steep, neighbour impassable
            step = math.hypot(dx, dy) * cell_size_world
            slope_pen = (rise / max_rise) ** 2
            cost = step * (1.0 + 2.0 * slope_pen)
            tentative_g = g_score[(x, y)] + cost
            if tentative_g < g_score.get((nx, ny), float("inf")):
                came[(nx, ny)] = (x, y)
                g_score[(nx, ny)] = tentative_g
                h_dist = math.hypot(nx - gx, ny - gy) * cell_size_world
                counter += 1
                heapq.heappush(open_q, (tentative_g + h_dist, counter, nx, ny))
    return None


def refine_waypoints(
    waypoints: Sequence[tuple[float, float]],
    H: np.ndarray,
    *,
    size: float,
    max_slope_deg: float = 22.0,
    grid_step: int = 4,
    decimate: int = 3,
) -> list[tuple[float, float]]:
    """Refine LLM waypoints by A*-routing each segment on a downsampled
    heightmap. Segments whose direct line stays within the slope budget
    pass through unchanged; segments that don't are replaced with an
    A* path that respects ``max_slope_deg``.

    Parameters
    ----------
    waypoints : list[(x, y)]
        Anchor points the LLM emitted (world coords).
    H : (res, res) ndarray
        Heightmap to plan against (use post-ridge / post-hero H so paths
        thread plateaus correctly).
    size : float
        Half-extent of the heightmap in BU; the heightmap covers
        [-size, +size] on both axes.
    max_slope_deg : float
        Cells whose neighbour rise exceeds tan(max_slope_deg) × cell_size
        are impassable. 22° is "comfortable hiking trail"; 30° is "steep
        but walkable"; 45°+ is cliffs.
    grid_step : int
        Downsample factor for path planning (256 / 4 = 64² nodes).
    decimate : int
        Keep every Nth A*-emitted point. 3 keeps ~33 % of the dense grid
        path; downstream Catmull-Rom smooths the result. 1 = no decimation.

    Returns
    -------
    list[(x, y)]
        Refined waypoints. First and last entries always equal the
        original anchors so the path begins / ends where the LLM asked.
    """
    pts = [tuple(map(float, p)) for p in waypoints]
    if len(pts) < 2:
        return pts

    H_d = np.ascontiguousarray(H[::grid_step, ::grid_step])
    res_d = H_d.shape[0]
    span = 2.0 * float(size)
    cell_size_world = span / max(res_d - 1, 1)
    max_rise = math.tan(math.radians(float(max_slope_deg))) * cell_size_world

    refined: list[tuple[float, float]] = [pts[0]]
    for i in range(len(pts) - 1):
        sx, sy = _world_to_grid(pts[i][0], pts[i][1], float(size), res_d)
        gx, gy = _world_to_grid(pts[i + 1][0], pts[i + 1][1], float(size), res_d)
        if _direct_passable(H_d, sx, sy, gx, gy, max_rise):
            refined.append(pts[i + 1])
            continue
        path = _astar(H_d, sx, sy, gx, gy, cell_size_world, max_rise)
        if path is None:
            # Fully blocked — keep the LLM segment, callers can layer a
            # Bridge later. Refinement is best-effort.
            refined.append(pts[i + 1])
            continue
        for k, (gx_, gy_) in enumerate(path[1:-1], start=1):
            if decimate <= 1 or k % decimate == 0:
                refined.append(_grid_to_world(gx_, gy_, float(size), res_d))
        refined.append(pts[i + 1])
    return refined

"""Townscaper-style tile WFC layer for Strata-backed settlements.

This module intentionally stays independent from Blender and from the final
asset factories. It consumes the coarser road-aware village WFC layout and
turns it into higher-order tile groups: house rows, courtyard blocks, market
clusters, wall runs, and gardens. The bridge then maps those semantic slots to
the existing Songe/Maquette factory bank.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable

from infinigen.maquette.runtime.village_wfc import VillageTile, VillageWFCLayout


HeightAt = Callable[[float, float], float]
SampleRole = Callable[[float, float], str]
DryCheck = Callable[[float, float], bool]
SlopeAt = Callable[[float, float], float]


class TileWFCKind(StrEnum):
    blocked = "blocked"
    empty = "empty"
    road = "road"
    plaza_core = "plaza_core"
    plaza_edge = "plaza_edge"
    alley = "alley"
    house_front = "house_front"
    house_corner = "house_corner"
    house_row = "house_row"
    courtyard = "courtyard"
    yard_wall = "yard_wall"
    fence_run = "fence_run"
    market_stall = "market_stall"
    garden = "garden"
    prop_cluster = "prop_cluster"


@dataclass(frozen=True, slots=True)
class TilePlacement:
    """One asset slot emitted by the tile WFC layer."""

    kind: str
    x: float
    y: float
    rot_z: float
    zone: str
    tile: str
    scale_range: tuple[float, float]
    footprint_scale: float = 1.0
    z_offset: float = 0.0
    alternatives: tuple[str, ...] = ()
    priority: float = 1.0
    metatile_id: str = ""

    def as_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "alternatives": list(self.alternatives),
            "x": round(float(self.x), 4),
            "y": round(float(self.y), 4),
            "rot_z": round(float(self.rot_z), 4),
            "zone": self.zone,
            "tile": self.tile,
            "scale_range": [
                round(float(self.scale_range[0]), 4),
                round(float(self.scale_range[1]), 4),
            ],
            "footprint_scale": round(float(self.footprint_scale), 4),
            "z_offset": round(float(self.z_offset), 4),
            "priority": round(float(self.priority), 4),
            "metatile_id": self.metatile_id,
        }


@dataclass(frozen=True, slots=True)
class DeformedCell:
    i: int
    j: int
    center: tuple[float, float]
    corners: tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]]

    def as_payload(self) -> dict[str, Any]:
        return {
            "i": int(self.i),
            "j": int(self.j),
            "center": [round(float(self.center[0]), 4), round(float(self.center[1]), 4)],
            "corners": [
                [round(float(x), 4), round(float(y), 4)]
                for x, y in self.corners
            ],
        }


@dataclass(frozen=True, slots=True)
class TileWFCCell:
    i: int
    j: int
    x: float
    y: float
    tile: TileWFCKind
    macro_tile: str
    fixed: bool = False
    rot_z: float = 0.0
    metatile_id: str = ""
    corners: tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]] = (
        (0.0, 0.0),
        (0.0, 0.0),
        (0.0, 0.0),
        (0.0, 0.0),
    )

    def as_payload(self) -> dict[str, Any]:
        return {
            "i": int(self.i),
            "j": int(self.j),
            "x": round(float(self.x), 4),
            "y": round(float(self.y), 4),
            "tile": self.tile.value,
            "macro_tile": self.macro_tile,
            "fixed": bool(self.fixed),
            "rot_z": round(float(self.rot_z), 4),
            "metatile_id": self.metatile_id,
            "corners": [
                [round(float(x), 4), round(float(y), 4)]
                for x, y in self.corners
            ],
        }


@dataclass(frozen=True, slots=True)
class MetaTile:
    metatile_id: str
    archetype: str
    cells: tuple[tuple[int, int], ...]
    x: float
    y: float
    rot_z: float
    span: tuple[int, int] = (1, 1)

    def as_payload(self) -> dict[str, Any]:
        return {
            "id": self.metatile_id,
            "archetype": self.archetype,
            "cells": [[int(i), int(j)] for i, j in self.cells],
            "x": round(float(self.x), 4),
            "y": round(float(self.y), 4),
            "rot_z": round(float(self.rot_z), 4),
            "span": [int(self.span[0]), int(self.span[1])],
        }


@dataclass(slots=True)
class TileWFCLayout:
    seed: int
    grid_size: int
    cell_size: float
    cells: list[TileWFCCell]
    metatiles: list[MetaTile]
    placements: list[TilePlacement]
    counters: dict[str, int] = field(default_factory=dict)

    def as_payload(self) -> dict[str, Any]:
        deformed_grid = [
            {
                "i": int(cell.i),
                "j": int(cell.j),
                "center": [round(float(cell.x), 4), round(float(cell.y), 4)],
                "corners": [
                    [round(float(x), 4), round(float(y), 4)]
                    for x, y in cell.corners
                ],
            }
            for cell in self.cells
        ]
        return {
            "seed": int(self.seed),
            "grid_size": int(self.grid_size),
            "cell_size": round(float(self.cell_size), 4),
            "counters": dict(self.counters),
            "deformed_grid": deformed_grid,
            "metatiles": [item.as_payload() for item in self.metatiles],
            "placements": [item.as_payload() for item in self.placements],
            "cells": [cell.as_payload() for cell in self.cells],
        }


_ADJ: dict[TileWFCKind, frozenset[TileWFCKind]] = {
    TileWFCKind.blocked: frozenset({TileWFCKind.blocked, TileWFCKind.empty}),
    TileWFCKind.empty: frozenset(TileWFCKind),
    TileWFCKind.road: frozenset({
        TileWFCKind.road,
        TileWFCKind.plaza_core,
        TileWFCKind.plaza_edge,
        TileWFCKind.alley,
        TileWFCKind.house_front,
        TileWFCKind.house_corner,
        TileWFCKind.fence_run,
        TileWFCKind.market_stall,
        TileWFCKind.prop_cluster,
        TileWFCKind.empty,
    }),
    TileWFCKind.plaza_core: frozenset({
        TileWFCKind.road,
        TileWFCKind.plaza_core,
        TileWFCKind.plaza_edge,
        TileWFCKind.market_stall,
        TileWFCKind.prop_cluster,
        TileWFCKind.house_front,
        TileWFCKind.empty,
    }),
    TileWFCKind.plaza_edge: frozenset({
        TileWFCKind.road,
        TileWFCKind.plaza_core,
        TileWFCKind.plaza_edge,
        TileWFCKind.market_stall,
        TileWFCKind.prop_cluster,
        TileWFCKind.house_front,
        TileWFCKind.fence_run,
        TileWFCKind.empty,
    }),
    TileWFCKind.alley: frozenset({
        TileWFCKind.road,
        TileWFCKind.alley,
        TileWFCKind.house_front,
        TileWFCKind.house_corner,
        TileWFCKind.fence_run,
        TileWFCKind.empty,
    }),
    TileWFCKind.house_front: frozenset({
        TileWFCKind.road,
        TileWFCKind.alley,
        TileWFCKind.plaza_edge,
        TileWFCKind.house_front,
        TileWFCKind.house_corner,
        TileWFCKind.house_row,
        TileWFCKind.courtyard,
        TileWFCKind.yard_wall,
        TileWFCKind.fence_run,
        TileWFCKind.prop_cluster,
        TileWFCKind.empty,
    }),
    TileWFCKind.house_corner: frozenset({
        TileWFCKind.road,
        TileWFCKind.alley,
        TileWFCKind.house_front,
        TileWFCKind.house_corner,
        TileWFCKind.house_row,
        TileWFCKind.courtyard,
        TileWFCKind.yard_wall,
        TileWFCKind.fence_run,
        TileWFCKind.empty,
    }),
    TileWFCKind.house_row: frozenset({
        TileWFCKind.house_front,
        TileWFCKind.house_corner,
        TileWFCKind.house_row,
        TileWFCKind.courtyard,
        TileWFCKind.yard_wall,
        TileWFCKind.road,
        TileWFCKind.alley,
        TileWFCKind.empty,
    }),
    TileWFCKind.courtyard: frozenset({
        TileWFCKind.house_front,
        TileWFCKind.house_corner,
        TileWFCKind.house_row,
        TileWFCKind.courtyard,
        TileWFCKind.yard_wall,
        TileWFCKind.garden,
        TileWFCKind.empty,
    }),
    TileWFCKind.yard_wall: frozenset({
        TileWFCKind.house_front,
        TileWFCKind.house_corner,
        TileWFCKind.house_row,
        TileWFCKind.courtyard,
        TileWFCKind.yard_wall,
        TileWFCKind.fence_run,
        TileWFCKind.garden,
        TileWFCKind.empty,
    }),
    TileWFCKind.fence_run: frozenset({
        TileWFCKind.road,
        TileWFCKind.plaza_edge,
        TileWFCKind.house_front,
        TileWFCKind.house_corner,
        TileWFCKind.yard_wall,
        TileWFCKind.fence_run,
        TileWFCKind.garden,
        TileWFCKind.empty,
    }),
    TileWFCKind.market_stall: frozenset({
        TileWFCKind.road,
        TileWFCKind.plaza_core,
        TileWFCKind.plaza_edge,
        TileWFCKind.market_stall,
        TileWFCKind.prop_cluster,
        TileWFCKind.empty,
    }),
    TileWFCKind.garden: frozenset({
        TileWFCKind.courtyard,
        TileWFCKind.yard_wall,
        TileWFCKind.fence_run,
        TileWFCKind.garden,
        TileWFCKind.empty,
    }),
    TileWFCKind.prop_cluster: frozenset({
        TileWFCKind.road,
        TileWFCKind.plaza_core,
        TileWFCKind.plaza_edge,
        TileWFCKind.market_stall,
        TileWFCKind.prop_cluster,
        TileWFCKind.house_front,
        TileWFCKind.fence_run,
        TileWFCKind.empty,
    }),
}

_WEIGHTS: dict[TileWFCKind, float] = {
    TileWFCKind.empty: 0.58,
    TileWFCKind.alley: 0.82,
    TileWFCKind.house_front: 2.25,
    TileWFCKind.house_corner: 1.05,
    TileWFCKind.house_row: 2.75,
    TileWFCKind.courtyard: 1.25,
    TileWFCKind.yard_wall: 0.72,
    TileWFCKind.fence_run: 0.48,
    TileWFCKind.market_stall: 2.35,
    TileWFCKind.garden: 0.75,
    TileWFCKind.prop_cluster: 0.90,
    TileWFCKind.plaza_edge: 1.28,
}


def build_village_tile_wfc_layout(
    *,
    seed: int,
    macro_layout: VillageWFCLayout,
    size: float,
    road_width: float,
    height_at: HeightAt,
    sample_role: SampleRole,
    is_dry: DryCheck,
    local_slope: SlopeAt,
    out_dir: str | Path | None = None,
) -> TileWFCLayout:
    """Build local metatiles and asset slots from a coarse village layout."""

    actual_seed = int(seed)
    rng = random.Random(actual_seed)
    macro = _macro_grid(macro_layout)
    contexts = _contexts_from_macro(
        macro_layout=macro_layout,
        macro=macro,
        size=float(size),
        road_width=float(road_width),
        seed=actual_seed,
        sample_role=sample_role,
        is_dry=is_dry,
        local_slope=local_slope,
    )
    domains = _initial_domains(contexts, road_width=float(road_width))
    tiles = _collapse(domains, contexts, rng)
    if tiles is None:
        tiles = _fallback_tiles(contexts)
    tiles = _postprocess_tiles(tiles, contexts=contexts, rng=rng, road_width=float(road_width))
    cells, metatiles, placements = _build_metatiles_and_slots(
        tiles,
        contexts=contexts,
        rng=rng,
        height_at=height_at,
    )
    counters: dict[str, int] = {}
    for cell in cells:
        counters[cell.tile.value] = int(counters.get(cell.tile.value, 0)) + 1
    for metatile in metatiles:
        counters[f"meta_{metatile.archetype}"] = int(counters.get(f"meta_{metatile.archetype}", 0)) + 1
    for placement in placements:
        counters[f"place_{placement.kind}"] = int(counters.get(f"place_{placement.kind}", 0)) + 1

    layout = TileWFCLayout(
        seed=actual_seed,
        grid_size=int(macro_layout.grid_size),
        cell_size=float(macro_layout.cell_size),
        cells=cells,
        metatiles=metatiles,
        placements=placements,
        counters=counters,
    )
    _write_debug_outputs(layout, out_dir)
    return layout


def _macro_grid(layout: VillageWFCLayout) -> dict[tuple[int, int], Any]:
    return {(int(cell.i), int(cell.j)): cell for cell in layout.cells}


def _contexts_from_macro(
    *,
    macro_layout: VillageWFCLayout,
    macro: dict[tuple[int, int], Any],
    size: float,
    road_width: float,
    seed: int,
    sample_role: SampleRole,
    is_dry: DryCheck,
    local_slope: SlopeAt,
) -> list[list[dict[str, Any]]]:
    n = int(macro_layout.grid_size)
    contexts: list[list[dict[str, Any]]] = []
    margin = max(4.0, float(size) * 0.025)
    cell_size = float(macro_layout.cell_size)
    base_x = float(macro_layout.market.get("x", 0.0)) - (n // 2) * cell_size - cell_size * 0.5
    base_y = float(macro_layout.market.get("y", 0.0)) - (n // 2) * cell_size - cell_size * 0.5
    corner_grid: list[list[tuple[float, float]]] = []
    for cj in range(n + 1):
        corner_row: list[tuple[float, float]] = []
        for ci in range(n + 1):
            x = base_x + ci * cell_size
            y = base_y + cj * cell_size
            wx, wy = _grid_vertex_warp(ci, cj, seed=seed, cell_size=cell_size)
            corner_row.append((
                max(-size + margin, min(size - margin, x + wx)),
                max(-size + margin, min(size - margin, y + wy)),
            ))
        corner_grid.append(corner_row)
    for j in range(n):
        row: list[dict[str, Any]] = []
        for i in range(n):
            cell = macro[(i, j)]
            corners = _cell_corners(corner_grid, i, j)
            deformed_center = _quad_center(corners)
            original_x = max(-size + margin, min(size - margin, float(cell.x)))
            original_y = max(-size + margin, min(size - margin, float(cell.y)))
            x = deformed_center[0]
            y = deformed_center[1]
            macro_tile = VillageTile(str(cell.tile))
            sample_x, sample_y = (
                (original_x, original_y)
                if macro_tile in {VillageTile.road, VillageTile.plaza}
                else (x, y)
            )
            role = str(sample_role(sample_x, sample_y) or "").lower()
            slope = float(local_slope(sample_x, sample_y))
            blocked = (
                macro_tile == VillageTile.blocked
                or not is_dry(sample_x, sample_y)
                or any(token in role for token in ("water", "basin_floor", "shore"))
                or slope > 0.255
            )
            # Keep road/plaza anchors stable so path connectivity stays
            # predictable, but keep the warped quad boundary for future mesh
            # tile deformation and debug output.
            if macro_tile in {VillageTile.road, VillageTile.plaza}:
                x, y = original_x, original_y
            row.append({
                "i": i,
                "j": j,
                "x": x,
                "y": y,
                "corners": corners,
                "macro_tile": macro_tile,
                "role": role,
                "slope": slope,
                "blocked": blocked,
                "fixed": blocked or macro_tile in {VillageTile.road, VillageTile.plaza},
                "dist_to_road": float(getattr(cell, "dist_to_road", 10**9)),
                "road_angle": float(getattr(cell, "road_angle", 0.0)),
                "market_pad": bool(getattr(cell, "in_market_pad", False)),
                "house_pad": bool(getattr(cell, "in_house_pad", False)),
                "road_width": road_width,
            })
        contexts.append(row)
    return contexts


def _grid_vertex_warp(i: int, j: int, *, seed: int, cell_size: float) -> tuple[float, float]:
    phase = float(seed % 10007) * 0.017
    amp = max(0.0, min(float(cell_size) * 0.19, 1.45))
    wx = (
        math.sin(i * 1.713 + j * 0.731 + phase)
        + 0.42 * math.sin(i * 0.431 - j * 1.271 + phase * 1.7)
    ) * amp * 0.62
    wy = (
        math.sin(i * 0.617 - j * 1.397 + phase * 0.83)
        + 0.38 * math.sin(i * 1.179 + j * 0.503 - phase * 1.3)
    ) * amp * 0.62
    return wx, wy


def _cell_corners(
    corner_grid: list[list[tuple[float, float]]],
    i: int,
    j: int,
) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]]:
    return (
        corner_grid[j][i],
        corner_grid[j][i + 1],
        corner_grid[j + 1][i + 1],
        corner_grid[j + 1][i],
    )


def _quad_center(
    corners: tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]],
) -> tuple[float, float]:
    return (
        sum(float(x) for x, _y in corners) * 0.25,
        sum(float(y) for _x, y in corners) * 0.25,
    )


def _quad_sample(
    corners: tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]],
    u: float,
    v: float,
) -> tuple[float, float]:
    u = max(0.0, min(1.0, float(u)))
    v = max(0.0, min(1.0, float(v)))
    x00, y00 = corners[0]
    x10, y10 = corners[1]
    x11, y11 = corners[2]
    x01, y01 = corners[3]
    x = (1.0 - u) * (1.0 - v) * x00 + u * (1.0 - v) * x10 + u * v * x11 + (1.0 - u) * v * x01
    y = (1.0 - u) * (1.0 - v) * y00 + u * (1.0 - v) * y10 + u * v * y11 + (1.0 - u) * v * y01
    return x, y


def _initial_domains(
    contexts: list[list[dict[str, Any]]],
    *,
    road_width: float,
) -> list[list[set[TileWFCKind]]]:
    domains: list[list[set[TileWFCKind]]] = []
    for row in contexts:
        domain_row: list[set[TileWFCKind]] = []
        for context in row:
            macro = context["macro_tile"]
            d_road = float(context["dist_to_road"])
            if context["blocked"]:
                domain = {TileWFCKind.blocked}
            elif macro == VillageTile.road:
                domain = {TileWFCKind.road}
            elif macro == VillageTile.plaza:
                if context["market_pad"]:
                    # Keep plaza domain pure so the 3x3/2x2 metatile detector
                    # can reliably consume contiguous plaza cells into a
                    # single coherent market plaza.
                    domain = {TileWFCKind.plaza_core, TileWFCKind.plaza_edge, TileWFCKind.market_stall}
                else:
                    domain = {TileWFCKind.plaza_edge, TileWFCKind.prop_cluster, TileWFCKind.empty}
            elif macro == VillageTile.house_front:
                domain = {
                    TileWFCKind.house_front,
                    TileWFCKind.house_corner,
                    TileWFCKind.house_row,
                    TileWFCKind.courtyard,
                    TileWFCKind.yard_wall,
                }
                if d_road <= road_width * 2.9:
                    domain.add(TileWFCKind.fence_run)
            elif macro == VillageTile.yard:
                domain = {TileWFCKind.courtyard, TileWFCKind.yard_wall, TileWFCKind.garden, TileWFCKind.empty}
            elif macro == VillageTile.fence:
                domain = {TileWFCKind.yard_wall, TileWFCKind.prop_cluster, TileWFCKind.empty}
                if d_road <= road_width * 2.6:
                    domain.add(TileWFCKind.fence_run)
            elif macro == VillageTile.prop:
                # Market stalls belong exclusively to the plaza metatile;
                # allowing them in any prop cells used to scatter stalls
                # 70+ BU from the market. Market-pad-adjacent props become
                # prop_cluster instead, which the plaza emitter naturally
                # complements with crates/lanterns.
                domain = {TileWFCKind.prop_cluster, TileWFCKind.plaza_edge, TileWFCKind.empty}
            elif macro == VillageTile.tree_pocket:
                domain = {TileWFCKind.garden, TileWFCKind.yard_wall, TileWFCKind.empty}
            else:
                domain = {TileWFCKind.empty}
                if d_road <= road_width * 2.8:
                    domain.add(TileWFCKind.alley)
                    domain.add(TileWFCKind.fence_run)
            domain_row.append(domain)
        domains.append(domain_row)
    return domains


def _collapse(
    domains: list[list[set[TileWFCKind]]],
    contexts: list[list[dict[str, Any]]],
    rng: random.Random,
) -> list[list[TileWFCKind]] | None:
    work = [[set(cell) for cell in row] for row in domains]
    if not _propagate(work):
        return None
    while True:
        target = _pick_lowest_entropy(work, rng)
        if target is None:
            return [[next(iter(cell)) for cell in row] for row in work]
        j, i = target
        work[j][i] = {_weighted_choice(work[j][i], contexts[j][i], rng)}
        if not _propagate(work):
            return None


def _propagate(domains: list[list[set[TileWFCKind]]]) -> bool:
    n = len(domains)
    queue = [(j, i) for j in range(n) for i in range(n)]
    while queue:
        j, i = queue.pop()
        domain = domains[j][i]
        if not domain:
            return False
        for nj, ni in _neighbors(j, i, n):
            other = domains[nj][ni]
            kept = {tile for tile in other if any(_compatible(tile, candidate) for candidate in domain)}
            if not kept:
                return False
            if kept != other:
                domains[nj][ni] = kept
                queue.append((nj, ni))
    return True


def _neighbors(j: int, i: int, n: int) -> tuple[tuple[int, int], ...]:
    out: list[tuple[int, int]] = []
    for dj, di in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        nj = j + dj
        ni = i + di
        if 0 <= nj < n and 0 <= ni < n:
            out.append((nj, ni))
    return tuple(out)


def _compatible(a: TileWFCKind, b: TileWFCKind) -> bool:
    if a == TileWFCKind.blocked or b == TileWFCKind.blocked:
        return True
    return b in _ADJ[a] and a in _ADJ[b]


def _pick_lowest_entropy(
    domains: list[list[set[TileWFCKind]]],
    rng: random.Random,
) -> tuple[int, int] | None:
    best: list[tuple[int, int]] = []
    best_size = 10**9
    for j, row in enumerate(domains):
        for i, domain in enumerate(row):
            if len(domain) <= 1:
                continue
            if len(domain) < best_size:
                best_size = len(domain)
                best = [(j, i)]
            elif len(domain) == best_size:
                best.append((j, i))
    return rng.choice(best) if best else None


def _weighted_choice(
    domain: set[TileWFCKind],
    context: dict[str, Any],
    rng: random.Random,
) -> TileWFCKind:
    items = list(domain)
    weights: list[float] = []
    d_road = float(context["dist_to_road"])
    road_width = float(context["road_width"])
    for tile in items:
        weight = max(0.03, float(_WEIGHTS.get(tile, 0.2)))
        if tile in {TileWFCKind.house_front, TileWFCKind.house_row, TileWFCKind.house_corner}:
            ideal = road_width * 1.85
            weight *= max(0.18, 1.45 - abs(d_road - ideal) / max(road_width * 2.6, 0.1))
            if context["house_pad"]:
                weight *= 1.35
        elif tile in {TileWFCKind.market_stall, TileWFCKind.prop_cluster}:
            weight *= 1.45 if context["market_pad"] else 0.85
        elif tile == TileWFCKind.garden:
            weight *= 1.2 if context["house_pad"] else 0.65
        elif tile == TileWFCKind.alley:
            weight *= 1.1 if d_road < road_width * 2.4 else 0.65
        weights.append(weight)
    return rng.choices(items, weights=weights, k=1)[0]


def _fallback_tiles(contexts: list[list[dict[str, Any]]]) -> list[list[TileWFCKind]]:
    out: list[list[TileWFCKind]] = []
    for row in contexts:
        tile_row: list[TileWFCKind] = []
        for context in row:
            macro = context["macro_tile"]
            if context["blocked"]:
                tile = TileWFCKind.blocked
            elif macro == VillageTile.road:
                tile = TileWFCKind.road
            elif macro == VillageTile.plaza:
                tile = TileWFCKind.plaza_core
            elif macro == VillageTile.house_front:
                tile = TileWFCKind.house_front
            elif macro == VillageTile.fence:
                tile = TileWFCKind.fence_run
            elif macro == VillageTile.prop:
                tile = TileWFCKind.prop_cluster
            elif macro == VillageTile.yard:
                tile = TileWFCKind.courtyard
            elif macro == VillageTile.tree_pocket:
                tile = TileWFCKind.garden
            else:
                tile = TileWFCKind.empty
            tile_row.append(tile)
        out.append(tile_row)
    return out


def _postprocess_tiles(
    tiles: list[list[TileWFCKind]],
    *,
    contexts: list[list[dict[str, Any]]],
    rng: random.Random,
    road_width: float,
) -> list[list[TileWFCKind]]:
    n = len(tiles)

    def has_neighbor(j: int, i: int, wanted: set[TileWFCKind], radius: int = 1) -> bool:
        for nj in range(max(0, j - radius), min(n, j + radius + 1)):
            for ni in range(max(0, i - radius), min(n, i + radius + 1)):
                if (nj, ni) == (j, i):
                    continue
                if tiles[nj][ni] in wanted:
                    return True
        return False

    house_like = {TileWFCKind.house_front, TileWFCKind.house_corner, TileWFCKind.house_row}
    for j in range(n):
        for i in range(n):
            tile = tiles[j][i]
            context = contexts[j][i]
            d_road = float(context["dist_to_road"])
            if tile in house_like:
                if (
                    d_road < road_width * 0.72
                    or d_road > road_width * 3.75
                    or not has_neighbor(j, i, {TileWFCKind.road, TileWFCKind.plaza_core, TileWFCKind.plaza_edge}, radius=1)
                ):
                    tiles[j][i] = TileWFCKind.courtyard if context["house_pad"] and rng.random() < 0.42 else TileWFCKind.empty
            elif tile == TileWFCKind.courtyard:
                if not has_neighbor(j, i, house_like | {TileWFCKind.yard_wall}, radius=1):
                    tiles[j][i] = TileWFCKind.garden if rng.random() < 0.4 else TileWFCKind.empty
            elif tile == TileWFCKind.fence_run:
                if not has_neighbor(j, i, house_like | {TileWFCKind.courtyard, TileWFCKind.yard_wall, TileWFCKind.plaza_edge}, radius=1):
                    tiles[j][i] = TileWFCKind.prop_cluster if context["market_pad"] and rng.random() < 0.30 else TileWFCKind.empty
            elif tile == TileWFCKind.market_stall:
                if d_road > road_width * 3.2 and not context["market_pad"]:
                    tiles[j][i] = TileWFCKind.prop_cluster if rng.random() < 0.35 else TileWFCKind.empty
            elif tile == TileWFCKind.garden:
                if has_neighbor(j, i, {TileWFCKind.road, TileWFCKind.plaza_core}, radius=1):
                    tiles[j][i] = TileWFCKind.yard_wall if rng.random() < 0.38 else TileWFCKind.empty
    # Earlier versions force-promoted the 3 cells closest to a road to
    # market_stall + 3 more to plaza_edge. That overrode the plaza-core block
    # the WFC was producing and scattered stalls outside the central plaza.
    # The widened plaza_force_radius in village_wfc + the new 3x3/2x2
    # metatile detection handle this cleanly, so the legacy override is gone.
    return tiles


def _build_metatiles_and_slots(
    tiles: list[list[TileWFCKind]],
    *,
    contexts: list[list[dict[str, Any]]],
    rng: random.Random,
    height_at: HeightAt,
) -> tuple[list[TileWFCCell], list[MetaTile], list[TilePlacement]]:
    n = len(tiles)
    consumed: set[tuple[int, int]] = set()
    cell_metatile: dict[tuple[int, int], str] = {}
    metatiles: list[MetaTile] = []
    placements: list[TilePlacement] = []
    meta_index = 0

    def new_id(prefix: str) -> str:
        nonlocal meta_index
        meta_index += 1
        return f"{prefix}_{meta_index:03d}"

    def center_of(cells: tuple[tuple[int, int], ...]) -> tuple[float, float]:
        xs = [float(contexts[j][i]["x"]) for i, j in cells]
        ys = [float(contexts[j][i]["y"]) for i, j in cells]
        return sum(xs) / len(xs), sum(ys) / len(ys)

    def add_meta(archetype: str, cells: tuple[tuple[int, int], ...], rot_z: float, span: tuple[int, int]) -> str:
        metatile_id = new_id(archetype)
        x, y = center_of(cells)
        metatiles.append(MetaTile(
            metatile_id=metatile_id,
            archetype=archetype,
            cells=cells,
            x=x,
            y=y,
            rot_z=rot_z,
            span=span,
        ))
        for cell in cells:
            consumed.add(cell)
            cell_metatile[cell] = metatile_id
        return metatile_id

    house_like = {TileWFCKind.house_front, TileWFCKind.house_corner, TileWFCKind.house_row}

    # Long runs are the important Townscaper-like step: turn several cells
    # into one coherent row instead of placing isolated houses.
    for j in range(n):
        i = 0
        while i < n:
            if (i, j) in consumed or tiles[j][i] not in house_like:
                i += 1
                continue
            run = [(i, j)]
            k = i + 1
            while k < n and (k, j) not in consumed and tiles[j][k] in house_like:
                if abs(float(contexts[j][k]["road_angle"]) - float(contexts[j][i]["road_angle"])) > 0.9:
                    break
                run.append((k, j))
                k += 1
            if len(run) >= 2:
                chosen = tuple(run[: min(3, len(run))])
                rot = _mean_angle([float(contexts[cj][ci]["road_angle"]) for ci, cj in chosen]) - math.pi * 0.5
                metatile_id = add_meta("house_row", chosen, rot, (len(chosen), 1))
                placements.extend(_house_row_slots(metatile_id, chosen, contexts=contexts, rng=rng, rot_z=rot))
                i += len(chosen)
            else:
                i += 1

    for i in range(n):
        j = 0
        while j < n:
            if (i, j) in consumed or tiles[j][i] not in house_like:
                j += 1
                continue
            run = [(i, j)]
            k = j + 1
            while k < n and (i, k) not in consumed and tiles[k][i] in house_like:
                if abs(float(contexts[k][i]["road_angle"]) - float(contexts[j][i]["road_angle"])) > 0.9:
                    break
                run.append((i, k))
                k += 1
            if len(run) >= 2:
                chosen = tuple(run[: min(3, len(run))])
                rot = _mean_angle([float(contexts[cj][ci]["road_angle"]) for ci, cj in chosen]) - math.pi * 0.5
                metatile_id = add_meta("house_row", chosen, rot, (1, len(chosen)))
                placements.extend(_house_row_slots(metatile_id, chosen, contexts=contexts, rng=rng, rot_z=rot))
                j += len(chosen)
            else:
                j += 1

    # 3x3 plaza blocks are the strongest compositional unit: an open core with
    # stalls on its perimeter. Detect them first so they consume cells before
    # 2x2 fallback or single market_frontage detection runs.
    plaza_kinds = {
        TileWFCKind.plaza_core,
        TileWFCKind.plaza_edge,
        TileWFCKind.market_stall,
        TileWFCKind.prop_cluster,
        TileWFCKind.empty,
    }
    for j in range(n - 2):
        for i in range(n - 2):
            block_3x3 = tuple(
                (i + di, j + dj)
                for dj in range(3)
                for di in range(3)
            )
            if any(cell in consumed for cell in block_3x3):
                continue
            block_tiles = {tiles[cj][ci] for ci, cj in block_3x3}
            if not block_tiles <= plaza_kinds:
                continue
            market_pad_count = sum(
                1 for ci, cj in block_3x3 if contexts[cj][ci]["market_pad"]
            )
            if market_pad_count < 4:
                continue
            rot = _mean_angle([float(contexts[cj][ci]["road_angle"]) for ci, cj in block_3x3])
            metatile_id = add_meta("market_plaza", block_3x3, rot, (3, 3))
            placements.extend(_market_plaza_slots(
                metatile_id,
                block_3x3,
                contexts=contexts,
                rng=rng,
                rot_z=rot,
            ))

    # 2x2 plaza blocks are the compact fallback when the macro plaza didn't
    # produce 9 contiguous plaza-allowed cells.
    for j in range(n - 1):
        for i in range(n - 1):
            block = ((i, j), (i + 1, j), (i, j + 1), (i + 1, j + 1))
            if any(cell in consumed for cell in block):
                continue
            block_tiles = {tiles[cj][ci] for ci, cj in block}
            if block_tiles <= {TileWFCKind.plaza_core, TileWFCKind.plaza_edge, TileWFCKind.market_stall, TileWFCKind.prop_cluster}:
                if sum(1 for ci, cj in block if contexts[cj][ci]["market_pad"]) < 2:
                    continue
                rot = _mean_angle([float(contexts[cj][ci]["road_angle"]) for ci, cj in block])
                metatile_id = add_meta("market_block", block, rot, (2, 2))
                placements.extend(_market_block_slots(metatile_id, block, contexts=contexts, rng=rng, rot_z=rot))

    for j in range(n):
        for i in range(n):
            if (i, j) in consumed:
                continue
            tile = tiles[j][i]
            context = contexts[j][i]
            rot = float(context["road_angle"])
            if tile in house_like:
                metatile_id = add_meta("house_single", ((i, j),), rot - math.pi * 0.5, (1, 1))
                placements.append(_slot(
                    metatile_id=metatile_id,
                    kind="house",
                    alternatives=("fence",),
                    context=context,
                    tile=tile,
                    rot_z=rot - math.pi * 0.5 + rng.uniform(-0.10, 0.10),
                    zone="tile_wfc_house",
                    scale_range=(0.80, 1.14),
                    footprint_scale=0.88,
                    priority=2.75,
                ))
            elif tile in {TileWFCKind.yard_wall, TileWFCKind.fence_run} and rng.random() < 0.42:
                metatile_id = add_meta("wall_segment", ((i, j),), rot, (1, 1))
                placements.append(_slot(
                    metatile_id=metatile_id,
                    kind="fence",
                    alternatives=("crate", "barrel"),
                    context=context,
                    tile=tile,
                    rot_z=rot + rng.uniform(-0.16, 0.16),
                    zone="tile_wfc_wall",
                    scale_range=(0.58, 0.88),
                    footprint_scale=0.66,
                    priority=1.6,
                ))
            elif tile == TileWFCKind.market_stall and rng.random() < 0.94:
                metatile_id = add_meta("market_frontage", ((i, j),), rot, (1, 1))
                placements.append(_market_stall_slot(metatile_id, context=context, tile=tile, rng=rng, priority=2.25))
                if rng.random() < 0.44:
                    placements.append(_prop_slot(metatile_id, context=context, tile=tile, rng=rng, priority=1.55))
            elif tile == TileWFCKind.prop_cluster and rng.random() < 0.64:
                metatile_id = add_meta("prop_cluster", ((i, j),), rot, (1, 1))
                placements.append(_prop_slot(metatile_id, context=context, tile=tile, rng=rng, priority=1.7))
            elif tile in {TileWFCKind.courtyard, TileWFCKind.garden} and rng.random() < 0.42:
                metatile_id = add_meta("garden_courtyard", ((i, j),), rot, (1, 1))
                kind = "haystack" if rng.random() < 0.35 else "tree"
                placements.append(_slot(
                    metatile_id=metatile_id,
                    kind=kind,
                    alternatives=("fence", "boulder", "cactus"),
                    context=context,
                    tile=tile,
                    rot_z=rng.uniform(0.0, math.tau),
                    zone="tile_wfc_garden",
                    scale_range=(0.50, 0.88) if kind == "haystack" else (0.62, 1.02),
                    footprint_scale=0.80,
                    priority=1.1,
                ))

    cells: list[TileWFCCell] = []
    for j in range(n):
        for i in range(n):
            context = contexts[j][i]
            _ = height_at(float(context["x"]), float(context["y"]))
            cells.append(TileWFCCell(
                i=i,
                j=j,
                x=float(context["x"]),
                y=float(context["y"]),
                tile=tiles[j][i],
                macro_tile=str(context["macro_tile"].value),
                fixed=bool(context["fixed"]),
                rot_z=float(context["road_angle"]),
                metatile_id=cell_metatile.get((i, j), ""),
                corners=context["corners"],
            ))

    placements.sort(key=lambda item: (-item.priority, item.metatile_id, item.kind, item.x, item.y))
    return cells, metatiles, placements


def _slot(
    *,
    metatile_id: str,
    kind: str,
    alternatives: tuple[str, ...],
    context: dict[str, Any],
    tile: TileWFCKind,
    rot_z: float,
    zone: str,
    scale_range: tuple[float, float],
    footprint_scale: float,
    priority: float,
    x_offset: float = 0.0,
    y_offset: float = 0.0,
    z_offset: float = 0.0,
) -> TilePlacement:
    return TilePlacement(
        kind=kind,
        alternatives=alternatives,
        x=float(context["x"]) + float(x_offset),
        y=float(context["y"]) + float(y_offset),
        rot_z=float(rot_z),
        zone=zone,
        tile=tile.value,
        scale_range=scale_range,
        footprint_scale=footprint_scale,
        z_offset=z_offset,
        priority=priority,
        metatile_id=metatile_id,
    )


def _house_row_slots(
    metatile_id: str,
    cells: tuple[tuple[int, int], ...],
    *,
    contexts: list[list[dict[str, Any]]],
    rng: random.Random,
    rot_z: float,
) -> list[TilePlacement]:
    slots: list[TilePlacement] = []
    for index, (i, j) in enumerate(cells):
        context = contexts[j][i]
        slots.append(_slot(
            metatile_id=metatile_id,
            kind="house",
            alternatives=("fence",),
            context=context,
            tile=TileWFCKind.house_row,
            rot_z=rot_z + rng.uniform(-0.06, 0.06),
            zone="tile_wfc_house_row",
            scale_range=(0.82, 1.16),
            footprint_scale=0.84,
            priority=3.35,
        ))
        if index < len(cells) - 1 and rng.random() < 0.28:
            next_context = contexts[cells[index + 1][1]][cells[index + 1][0]]
            x = (float(context["x"]) + float(next_context["x"])) * 0.5
            y = (float(context["y"]) + float(next_context["y"])) * 0.5
            bridge_context = dict(context)
            bridge_context["x"] = x
            bridge_context["y"] = y
            slots.append(_slot(
                metatile_id=metatile_id,
                kind="fence",
                alternatives=("crate", "barrel"),
                context=bridge_context,
                tile=TileWFCKind.yard_wall,
                rot_z=rot_z + math.pi * 0.5 + rng.uniform(-0.08, 0.08),
                zone="tile_wfc_wall",
                scale_range=(0.48, 0.78),
                footprint_scale=0.52,
                priority=1.7,
            ))
    if cells and rng.random() < 0.88:
        i, j = rng.choice(cells)
        context = contexts[j][i]
        slots.append(_prop_slot(metatile_id, context=context, tile=TileWFCKind.prop_cluster, rng=rng, priority=1.55))
    return slots


def _market_plaza_slots(
    metatile_id: str,
    cells: tuple[tuple[int, int], ...],
    *,
    contexts: list[list[dict[str, Any]]],
    rng: random.Random,
    rot_z: float,
) -> list[TilePlacement]:
    """Emit slots for a 3x3 market plaza metatile.

    Cells are passed row-major (top-left → bottom-right). The center cell gets
    a focal lantern; the four cardinal edges get stalls; the four corners get
    crates/barrels/signage. This produces a readable plaza silhouette instead
    of scattered single-cell market frontages.
    """
    if len(cells) != 9:
        return _market_block_slots(metatile_id, cells, contexts=contexts, rng=rng, rot_z=rot_z)
    slots: list[TilePlacement] = []
    # cells are already row-major from caller, but normalize defensively.
    sorted_cells = sorted(cells, key=lambda c: (c[1], c[0]))
    layout = {
        0: ("corner", ("crate", "barrel", "signage")),
        1: ("stall", ("crate", "barrel", "lantern")),
        2: ("corner", ("crate", "barrel", "signage")),
        3: ("stall", ("crate", "barrel", "lantern")),
        4: ("center", ("lantern", "signage", "barrel", "crate")),
        5: ("stall", ("crate", "barrel", "lantern")),
        6: ("corner", ("crate", "barrel", "signage")),
        7: ("stall", ("crate", "barrel", "lantern")),
        8: ("corner", ("crate", "barrel", "signage")),
    }
    for idx, (i, j) in enumerate(sorted_cells):
        context = contexts[j][i]
        role, alternatives = layout[idx]
        if role == "stall":
            kind = "stall"
            scale_range = (0.78, 1.10)
            footprint_scale = 0.88
            priority = 2.55
            tile = TileWFCKind.market_stall
        elif role == "center":
            kind = "lantern" if rng.random() < 0.65 else "signage"
            scale_range = (0.58, 0.92)
            footprint_scale = 0.64
            priority = 1.95
            tile = TileWFCKind.plaza_core
        else:  # corner
            kind = "crate" if rng.random() < 0.55 else "barrel"
            scale_range = (0.52, 0.88)
            footprint_scale = 0.58
            priority = 1.75
            tile = TileWFCKind.plaza_edge
        # Light random radial offset toward the plaza center to avoid the
        # stalls reading as a perfectly square grid of objects.
        offset = rng.uniform(-0.35, 0.35)
        slots.append(_slot(
            metatile_id=metatile_id,
            kind=kind,
            alternatives=alternatives,
            context=context,
            tile=tile,
            rot_z=rot_z + (math.pi * 0.5 if role == "stall" and idx in {1, 7} else 0.0) + rng.uniform(-0.25, 0.25),
            zone="tile_wfc_market",
            scale_range=scale_range,
            footprint_scale=footprint_scale,
            priority=priority,
            x_offset=math.cos(rot_z + math.pi * 0.5) * offset,
            y_offset=math.sin(rot_z + math.pi * 0.5) * offset,
        ))
    return slots


def _market_block_slots(
    metatile_id: str,
    cells: tuple[tuple[int, int], ...],
    *,
    contexts: list[list[dict[str, Any]]],
    rng: random.Random,
    rot_z: float,
) -> list[TilePlacement]:
    slots: list[TilePlacement] = []
    sorted_cells = sorted(cells)
    for idx, (i, j) in enumerate(sorted_cells):
        context = contexts[j][i]
        if idx == 0:
            kind = "stall"
            alternatives = ("crate", "barrel", "lantern")
        elif idx == 1:
            kind = "stall"
            alternatives = ("crate", "barrel", "signage")
        elif idx == 2:
            kind = "lantern"
            alternatives = ("signage", "barrel", "crate")
        else:
            kind = "crate" if rng.random() < 0.55 else "barrel"
            alternatives = ("barrel", "crate", "lantern")
        offset = rng.uniform(-0.55, 0.55)
        slots.append(_slot(
            metatile_id=metatile_id,
            kind=kind,
            alternatives=alternatives,
            context=context,
            tile=TileWFCKind.market_stall,
            rot_z=rot_z + rng.uniform(-0.35, 0.35),
            zone="tile_wfc_market",
            scale_range=(0.76, 1.08) if kind == "stall" else (0.54, 0.92),
            footprint_scale=0.86 if kind == "stall" else 0.62,
            priority=2.45 if kind == "stall" else 1.95,
            x_offset=math.cos(rot_z + math.pi * 0.5) * offset,
            y_offset=math.sin(rot_z + math.pi * 0.5) * offset,
        ))
    return slots


def _market_stall_slot(
    metatile_id: str,
    *,
    context: dict[str, Any],
    tile: TileWFCKind,
    rng: random.Random,
    priority: float,
) -> TilePlacement:
    return _slot(
        metatile_id=metatile_id,
        kind="stall",
        alternatives=("crate", "barrel", "lantern"),
        context=context,
        tile=tile,
        rot_z=float(context["road_angle"]) - math.pi * 0.5 + rng.uniform(-0.22, 0.22),
        zone="tile_wfc_market",
        scale_range=(0.72, 1.06),
        footprint_scale=0.84,
        priority=priority,
        x_offset=rng.uniform(-0.45, 0.45),
        y_offset=rng.uniform(-0.45, 0.45),
    )


def _prop_slot(
    metatile_id: str,
    *,
    context: dict[str, Any],
    tile: TileWFCKind,
    rng: random.Random,
    priority: float,
) -> TilePlacement:
    kind = rng.choice(("crate", "barrel", "lantern", "signage"))
    return _slot(
        metatile_id=metatile_id,
        kind=kind,
        alternatives=tuple(item for item in ("crate", "barrel", "lantern", "signage") if item != kind),
        context=context,
        tile=tile,
        rot_z=float(context["road_angle"]) + rng.uniform(-0.45, 0.45),
        zone="tile_wfc_prop",
        scale_range=(0.50, 0.88),
        footprint_scale=0.62,
        priority=priority,
        x_offset=rng.uniform(-0.65, 0.65),
        y_offset=rng.uniform(-0.65, 0.65),
    )


def _mean_angle(values: list[float]) -> float:
    if not values:
        return 0.0
    sx = sum(math.cos(value) for value in values)
    sy = sum(math.sin(value) for value in values)
    return math.atan2(sy, sx)


def _write_debug_outputs(layout: TileWFCLayout, out_dir: str | Path | None) -> None:
    if not out_dir:
        return
    target = Path(out_dir)
    try:
        target.mkdir(parents=True, exist_ok=True)
        payload = layout.as_payload()
        (target / "strata_tile_wfc_layout.json").write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )
        (target / "strata_tile_wfc_slots.json").write_text(
            json.dumps({"placements": payload["placements"], "metatiles": payload["metatiles"]}, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass
    try:
        from PIL import Image, ImageDraw

        n = int(layout.grid_size)
        scale = 11
        padding = 10
        img = Image.new("RGB", (n * scale + padding * 2, n * scale + padding * 2), (38, 40, 36))
        draw = ImageDraw.Draw(img)
        all_x = [x for cell in layout.cells for x, _y in cell.corners]
        all_y = [y for cell in layout.cells for _x, y in cell.corners]
        min_x = min(all_x) if all_x else 0.0
        max_x = max(all_x) if all_x else 1.0
        min_y = min(all_y) if all_y else 0.0
        max_y = max(all_y) if all_y else 1.0
        width = max(max_x - min_x, 1e-4)
        height = max(max_y - min_y, 1e-4)

        def project(x: float, y: float) -> tuple[int, int]:
            px = padding + int(round((float(x) - min_x) / width * (n * scale - 1)))
            py = padding + int(round((float(y) - min_y) / height * (n * scale - 1)))
            return px, py

        colors = {
            TileWFCKind.blocked.value: (42, 42, 42),
            TileWFCKind.empty.value: (72, 80, 56),
            TileWFCKind.road.value: (151, 116, 72),
            TileWFCKind.plaza_core.value: (184, 148, 94),
            TileWFCKind.plaza_edge.value: (167, 134, 86),
            TileWFCKind.alley.value: (128, 103, 70),
            TileWFCKind.house_front.value: (171, 79, 59),
            TileWFCKind.house_corner.value: (195, 92, 64),
            TileWFCKind.house_row.value: (216, 94, 67),
            TileWFCKind.courtyard.value: (126, 112, 73),
            TileWFCKind.yard_wall.value: (111, 78, 50),
            TileWFCKind.fence_run.value: (100, 70, 47),
            TileWFCKind.market_stall.value: (222, 152, 73),
            TileWFCKind.garden.value: (61, 113, 60),
            TileWFCKind.prop_cluster.value: (202, 132, 70),
        }
        for cell in layout.cells:
            polygon = [project(x, y) for x, y in cell.corners]
            draw.polygon(polygon, fill=colors.get(cell.tile.value, (84, 94, 66)))
            draw.line([*polygon, polygon[0]], fill=(29, 32, 28), width=1)
            if cell.metatile_id:
                inset = [
                    (
                        int(round(px * 0.80 + project(cell.x, cell.y)[0] * 0.20)),
                        int(round(py * 0.80 + project(cell.x, cell.y)[1] * 0.20)),
                    )
                    for px, py in polygon
                ]
                draw.line([*inset, inset[0]], fill=(255, 245, 210), width=1)
        for placement in layout.placements:
            matched = min(
                layout.cells,
                key=lambda cell: (placement.x - cell.x) ** 2 + (placement.y - cell.y) ** 2,
            )
            cx, cy = project(matched.x, matched.y)
            draw.ellipse((cx - 2, cy - 2, cx + 2, cy + 2), fill=(255, 255, 225))
        img.save(target / "strata_tile_wfc_layout.png")
    except Exception:
        pass

"""Road-aware WFC layout factory for small villages.

The solver is intentionally mesh-free. It generates a semantic placement
plan around an existing road/plaza skeleton, then Maquette factories build
the actual visible objects. This keeps object quality in the factory bank
and uses WFC only for local coherence.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable


class VillageTile(StrEnum):
    blocked = "blocked"
    empty = "empty"
    road = "road"
    plaza = "plaza"
    house_front = "house_front"
    yard = "yard"
    fence = "fence"
    prop = "prop"
    tree_pocket = "tree_pocket"


@dataclass(frozen=True, slots=True)
class VillagePlacement:
    """One semantic object placement emitted by the village WFC pass."""

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
        }


@dataclass(slots=True)
class VillageCell:
    i: int
    j: int
    x: float
    y: float
    tile: VillageTile
    fixed: bool = False
    dist_to_road: float = 10**9
    road_angle: float = 0.0
    in_market_pad: bool = False
    in_house_pad: bool = False

    def as_payload(self) -> dict[str, Any]:
        return {
            "i": self.i,
            "j": self.j,
            "x": round(float(self.x), 4),
            "y": round(float(self.y), 4),
            "tile": self.tile.value,
            "fixed": bool(self.fixed),
            "dist_to_road": round(float(self.dist_to_road), 4),
        }


@dataclass(slots=True)
class VillageWFCLayout:
    seed: int
    kind: str
    grid_size: int
    cell_size: float
    market: dict[str, float]
    cells: list[VillageCell]
    placements: list[VillagePlacement]
    counters: dict[str, int] = field(default_factory=dict)
    retries: int = 0

    def as_payload(self) -> dict[str, Any]:
        return {
            "seed": int(self.seed),
            "kind": self.kind,
            "grid_size": int(self.grid_size),
            "cell_size": round(float(self.cell_size), 4),
            "market": {
                "x": round(float(self.market.get("x", 0.0)), 4),
                "y": round(float(self.market.get("y", 0.0)), 4),
            },
            "retries": int(self.retries),
            "counters": dict(self.counters),
            "placements": [p.as_payload() for p in self.placements],
            "cells": [cell.as_payload() for cell in self.cells],
        }


HeightAt = Callable[[float, float], float]
SampleRole = Callable[[float, float], str]
DryCheck = Callable[[float, float], bool]
SlopeAt = Callable[[float, float], float]


_COMPAT: dict[VillageTile, frozenset[VillageTile]] = {
    VillageTile.blocked: frozenset({VillageTile.blocked, VillageTile.empty}),
    VillageTile.empty: frozenset(VillageTile),
    VillageTile.road: frozenset({
        VillageTile.road,
        VillageTile.plaza,
        VillageTile.house_front,
        VillageTile.fence,
        VillageTile.prop,
        VillageTile.empty,
    }),
    VillageTile.plaza: frozenset({
        VillageTile.road,
        VillageTile.plaza,
        VillageTile.house_front,
        VillageTile.fence,
        VillageTile.prop,
        VillageTile.empty,
    }),
    VillageTile.house_front: frozenset({
        VillageTile.road,
        VillageTile.plaza,
        VillageTile.house_front,
        VillageTile.yard,
        VillageTile.fence,
        VillageTile.prop,
        VillageTile.empty,
    }),
    VillageTile.yard: frozenset({
        VillageTile.house_front,
        VillageTile.yard,
        VillageTile.fence,
        VillageTile.tree_pocket,
        VillageTile.empty,
    }),
    VillageTile.fence: frozenset({
        VillageTile.road,
        VillageTile.plaza,
        VillageTile.house_front,
        VillageTile.yard,
        VillageTile.fence,
        VillageTile.prop,
        VillageTile.tree_pocket,
        VillageTile.empty,
    }),
    VillageTile.prop: frozenset({
        VillageTile.road,
        VillageTile.plaza,
        VillageTile.house_front,
        VillageTile.fence,
        VillageTile.prop,
        VillageTile.empty,
    }),
    VillageTile.tree_pocket: frozenset({
        VillageTile.yard,
        VillageTile.fence,
        VillageTile.tree_pocket,
        VillageTile.empty,
    }),
}


_STYLE_WEIGHTS: dict[str, dict[VillageTile, float]] = {
    "market_town": {
        VillageTile.empty: 0.48,
        VillageTile.house_front: 3.15,
        VillageTile.yard: 1.05,
        VillageTile.fence: 0.58,
        VillageTile.prop: 0.95,
        VillageTile.tree_pocket: 0.38,
        VillageTile.plaza: 1.18,
    },
    "hamlet": {
        VillageTile.empty: 1.15,
        VillageTile.house_front: 1.65,
        VillageTile.yard: 1.5,
        VillageTile.fence: 1.15,
        VillageTile.prop: 0.65,
        VillageTile.tree_pocket: 1.25,
        VillageTile.plaza: 0.35,
    },
    "village": {
        VillageTile.empty: 0.72,
        VillageTile.house_front: 2.55,
        VillageTile.yard: 1.35,
        VillageTile.fence: 0.72,
        VillageTile.prop: 0.72,
        VillageTile.tree_pocket: 0.85,
        VillageTile.plaza: 0.45,
    },
}


def build_village_wfc_layout(
    *,
    seed: int,
    kind: str,
    size: float,
    market: Any,
    road_paths: list[Any],
    hero_pads: list[Any],
    road_width: float,
    height_at: HeightAt,
    sample_role: SampleRole,
    is_dry: DryCheck,
    local_slope: SlopeAt,
    districts: list[Any] | None = None,
    out_dir: str | Path | None = None,
) -> VillageWFCLayout:
    """Build a reusable WFC village placement plan.

    Inputs are duck-typed so the module stays independent from
    ``strata_bridge`` dataclasses and is easy to unit-test.

    ``districts`` is optional; when provided, each entry is expected to expose
    ``x``, ``y``, ``radius`` and ``role`` (or be a tuple-like). The WFC biases
    house/plaza/yard weights toward district centers so multi-district
    settlements read as distinct clusters instead of one blob.
    """
    actual_seed = int(seed)
    rng = random.Random(actual_seed)
    style = _style_key(kind)
    grid_size = 33 if float(size) >= 220.0 else 29 if float(size) >= 160.0 else 25
    # Houses/trees are instantiated from real Maquette factories, not tiny
    # symbolic tokens. The previous 5.6 BU floor packed adjacent cells tightly
    # enough that rows read as overlapping clusters in the render. Use a wider
    # town grid and let metatiles provide cohesion instead of raw proximity.
    cell_size = max(7.0, min(float(size) * 0.048, 10.4))
    market_x = float(getattr(market, "x", 0.0))
    market_y = float(getattr(market, "y", 0.0))
    roads: list[tuple[list[Any], float]] = []
    for path in road_paths or []:
        road = _road_points(path)
        if len(road[0]) >= 2:
            roads.append(road)
    pads = list(hero_pads or [])
    district_specs = _normalize_districts(districts)

    fixed_domains, contexts = _initial_domains(
        rng=rng,
        grid_size=grid_size,
        cell_size=cell_size,
        size=float(size),
        market_x=market_x,
        market_y=market_y,
        road_paths=roads,
        pads=pads,
        districts=district_specs,
        road_width=float(road_width),
        sample_role=sample_role,
        is_dry=is_dry,
        local_slope=local_slope,
        style=style,
    )

    retries = 0
    tiles: list[list[VillageTile]] | None = None
    for attempt in range(5):
        retry_rng = random.Random(actual_seed + attempt * 104729)
        collapsed = _collapse_domains(
            domains=[row[:] for row in fixed_domains],
            contexts=contexts,
            rng=retry_rng,
            style=style,
            road_width=float(road_width),
        )
        if collapsed is not None:
            retries = attempt
            tiles = collapsed
            break
    if tiles is None:
        retries = 5
        tiles = [
            [
                _fallback_tile(contexts[j][i])
                for i in range(grid_size)
            ]
            for j in range(grid_size)
        ]

    tiles = _postprocess_tiles(
        tiles,
        contexts=contexts,
        rng=rng,
        road_width=float(road_width),
        style=style,
    )
    cells, placements = _tiles_to_placements(
        tiles,
        contexts=contexts,
        rng=rng,
        style=style,
        height_at=height_at,
    )
    counters: dict[str, int] = {}
    for cell in cells:
        counters[cell.tile.value] = int(counters.get(cell.tile.value, 0)) + 1
    for placement in placements:
        counters[f"place_{placement.kind}"] = int(counters.get(f"place_{placement.kind}", 0)) + 1

    layout = VillageWFCLayout(
        seed=actual_seed,
        kind=style,
        grid_size=grid_size,
        cell_size=cell_size,
        market={"x": market_x, "y": market_y},
        cells=cells,
        placements=placements,
        counters=counters,
        retries=retries,
    )
    _write_debug_outputs(layout, out_dir)
    return layout


def _style_key(kind: str) -> str:
    lower = str(kind or "").lower()
    if "hamlet" in lower or "farm" in lower:
        return "hamlet"
    if "village" in lower:
        return "village"
    return "market_town"


def _normalize_districts(districts: list[Any] | None) -> list[dict[str, float | str]]:
    """Coerce duck-typed district anchors to plain dicts the WFC can consume.

    Accepts strata_bridge.DistrictAnchor objects, mappings, or anything with
    ``x``/``y``/``radius``/``role`` attributes. Returns a list of dicts so the
    module stays independent from upstream dataclasses.
    """
    out: list[dict[str, float | str]] = []
    for entry in districts or []:
        if entry is None:
            continue
        if isinstance(entry, dict):
            x = float(entry.get("x", 0.0))
            y = float(entry.get("y", 0.0))
            radius = float(entry.get("radius", 12.0))
            role = str(entry.get("role", ""))
            name = str(entry.get("name", ""))
        else:
            x = float(getattr(entry, "x", 0.0))
            y = float(getattr(entry, "y", 0.0))
            radius = float(getattr(entry, "radius", 12.0))
            role = str(getattr(entry, "role", ""))
            name = str(getattr(entry, "name", ""))
        out.append({
            "x": x,
            "y": y,
            "radius": max(float(radius), 1e-4),
            "role": role,
            "name": name,
        })
    return out


def _nearest_district(
    x: float,
    y: float,
    districts: list[dict[str, float | str]],
) -> tuple[float, dict[str, float | str] | None]:
    """Return (affinity_in_[0,1], district) for the strongest nearby district.

    Affinity is 1.0 at the district center and decays linearly to 0 at the
    district radius. Returns (0.0, None) when there are no districts.
    """
    if not districts:
        return 0.0, None
    best_affinity = 0.0
    best_district: dict[str, float | str] | None = None
    for district in districts:
        d = math.hypot(float(x) - float(district["x"]), float(y) - float(district["y"]))
        radius = float(district["radius"]) or 1e-4
        affinity = max(0.0, 1.0 - d / radius)
        if affinity > best_affinity:
            best_affinity = affinity
            best_district = district
    return best_affinity, best_district


def _road_points(path: Any) -> tuple[list[Any], float]:
    points = list(getattr(path, "points", []) or [])
    width = float(getattr(path, "width", 5.0) or 5.0)
    return points, width


def _initial_domains(
    *,
    rng: random.Random,
    grid_size: int,
    cell_size: float,
    size: float,
    market_x: float,
    market_y: float,
    road_paths: list[tuple[list[Any], float]],
    pads: list[Any],
    districts: list[dict[str, float | str]],
    road_width: float,
    sample_role: SampleRole,
    is_dry: DryCheck,
    local_slope: SlopeAt,
    style: str,
) -> tuple[list[list[set[VillageTile]]], list[list[dict[str, Any]]]]:
    half = grid_size // 2
    margin = max(5.0, size * 0.035)
    domains: list[list[set[VillageTile]]] = []
    contexts: list[list[dict[str, Any]]] = []
    districts_active = bool(districts)
    # Plaza forcing covers a 3x3 worth of cells around the market center so
    # the tile WFC can form a single coherent plaza metatile. A wider radius
    # spills plaza cells outside the 3x3 footprint and leaks single-cell
    # market_frontage stalls on the periphery, which is exactly the failure
    # mode the metatile is replacing. cell_size * 1.6 picks up the four
    # diagonal cells at cell_size * sqrt(2) ≈ cell_size * 1.41.
    plaza_force_radius = max(road_width * 2.0, cell_size * 1.6)
    for j in range(grid_size):
        domain_row: list[set[VillageTile]] = []
        context_row: list[dict[str, Any]] = []
        for i in range(grid_size):
            x = max(-size + margin, min(size - margin, market_x + (i - half) * cell_size))
            y = max(-size + margin, min(size - margin, market_y + (j - half) * cell_size))
            role = str(sample_role(float(x), float(y)) or "").lower()
            d_road, _rx, _ry, road_angle = _nearest_road_info(x, y, road_paths)
            market_pad = _pad_contains(pads, x, y, role_tokens=("market", "plaza"), margin=1.12)
            house_pad = _pad_contains(pads, x, y, role_tokens=("house", "cluster"), margin=1.14)
            tower_pad = _pad_contains(pads, x, y, role_tokens=("tower",), margin=1.08)
            d_market = math.hypot(x - market_x, y - market_y)
            slope = float(local_slope(float(x), float(y)))
            district_affinity, nearest = _nearest_district(x, y, districts)
            district_role = str(nearest["role"]) if nearest is not None else ""
            blocked = (
                not is_dry(float(x), float(y))
                or any(token in role for token in ("water", "basin_floor", "shore"))
                or slope > 0.245
            )
            context = {
                "x": x,
                "y": y,
                "role": role,
                "dist_to_road": d_road,
                "road_angle": road_angle,
                "market_pad": market_pad,
                "house_pad": house_pad,
                "tower_pad": tower_pad,
                "dist_to_market": d_market,
                "slope": slope,
                "fixed": False,
                "district_affinity": float(district_affinity),
                "district_role": district_role,
                "districts_active": districts_active,
            }
            if blocked:
                domain = {VillageTile.blocked}
                context["fixed"] = True
            elif market_pad and d_market <= plaza_force_radius:
                # Plaza takes precedence over road inside the market core,
                # otherwise converging spokes consume the entire plaza-force
                # area as road tiles and the 3x3 plaza metatile cannot form.
                domain = {VillageTile.plaza}
                context["fixed"] = True
            elif d_road <= road_width * 0.74:
                domain = {VillageTile.road}
                context["fixed"] = True
            else:
                domain = _context_domain(
                    context,
                    rng=rng,
                    road_width=road_width,
                    style=style,
                )
            domain_row.append(domain)
            context_row.append(context)
        domains.append(domain_row)
        contexts.append(context_row)
    return domains, contexts


def _context_domain(
    context: dict[str, Any],
    *,
    rng: random.Random,
    road_width: float,
    style: str,
) -> set[VillageTile]:
    d_road = float(context["dist_to_road"])
    d_market = float(context["dist_to_market"])
    in_market = bool(context["market_pad"])
    in_house = bool(context["house_pad"])
    in_tower = bool(context["tower_pad"])
    domain: set[VillageTile] = {VillageTile.empty}
    road_ring = road_width * 1.05 <= d_road <= road_width * 3.25
    near_road = d_road <= road_width * 3.8
    if in_market:
        # Plaza cells are exclusively the fixed inner core (handled by the
        # plaza_force branch upstream). Soft market_pad cells around that
        # core produce props, not scattered standalone plazas that would
        # break the 3x3 plaza metatile.
        domain.update({VillageTile.prop})
        if road_ring and d_market > road_width * 2.0:
            domain.add(VillageTile.house_front)
    if in_house:
        domain.update({VillageTile.yard, VillageTile.tree_pocket})
        if road_ring:
            domain.add(VillageTile.house_front)
    if in_tower:
        domain.update({VillageTile.fence, VillageTile.prop})
    if road_ring:
        domain.update({VillageTile.house_front, VillageTile.prop})
        if in_house or in_tower or rng.random() < 0.42:
            domain.add(VillageTile.fence)
    elif near_road:
        domain.update({VillageTile.prop})
        if rng.random() < 0.34:
            domain.add(VillageTile.fence)
    elif in_house:
        domain.update({VillageTile.yard, VillageTile.tree_pocket})
    district_affinity = float(context.get("district_affinity", 0.0))
    districts_active = bool(context.get("districts_active"))
    inside_district = district_affinity > 0.08
    if not (in_market or in_house or in_tower or d_road <= road_width * 4.8 or inside_district):
        # Outskirts cells are allowed to stay quiet; otherwise WFC becomes
        # broad random scatter, which was the previous failure mode.
        domain = {VillageTile.empty}
    # When districts are explicitly provided, gate houses on district
    # membership. This prevents long roads from drawing a thin line of houses
    # across the whole map between districts.
    if (
        districts_active
        and not inside_district
        and not (in_market or in_house or in_tower)
    ):
        domain.discard(VillageTile.house_front)
    if style == "hamlet" and VillageTile.prop in domain and rng.random() < 0.35:
        domain.discard(VillageTile.prop)
    return domain


def _collapse_domains(
    *,
    domains: list[list[set[VillageTile]]],
    contexts: list[list[dict[str, Any]]],
    rng: random.Random,
    style: str,
    road_width: float,
) -> list[list[VillageTile]] | None:
    if not _propagate(domains):
        return None
    while True:
        target = _pick_lowest_entropy(domains, rng)
        if target is None:
            break
        j, i = target
        choice = _weighted_choice(domains[j][i], contexts[j][i], rng, style=style, road_width=road_width)
        domains[j][i] = {choice}
        if not _propagate(domains):
            return None
    return [[next(iter(cell)) for cell in row] for row in domains]


def _propagate(domains: list[list[set[VillageTile]]]) -> bool:
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


def _neighbors(j: int, i: int, n: int) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for dj, di in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        nj = j + dj
        ni = i + di
        if 0 <= nj < n and 0 <= ni < n:
            out.append((nj, ni))
    return out


def _compatible(a: VillageTile, b: VillageTile) -> bool:
    if a == VillageTile.blocked or b == VillageTile.blocked:
        return True
    return b in _COMPAT[a] and a in _COMPAT[b]


def _pick_lowest_entropy(domains: list[list[set[VillageTile]]], rng: random.Random) -> tuple[int, int] | None:
    best: list[tuple[int, int]] = []
    best_size = 10**9
    for j, row in enumerate(domains):
        for i, domain in enumerate(row):
            size = len(domain)
            if size <= 1:
                continue
            if size < best_size:
                best_size = size
                best = [(j, i)]
            elif size == best_size:
                best.append((j, i))
    return rng.choice(best) if best else None


def _weighted_choice(
    domain: set[VillageTile],
    context: dict[str, Any],
    rng: random.Random,
    *,
    style: str,
    road_width: float,
) -> VillageTile:
    weights = _STYLE_WEIGHTS.get(style, _STYLE_WEIGHTS["market_town"])
    d_road = float(context["dist_to_road"])
    affinity = float(context.get("district_affinity", 0.0))
    district_role = str(context.get("district_role", ""))
    has_district = bool(context.get("districts_active"))
    inside_district = affinity > 0.05
    out: list[VillageTile] = list(domain)
    weighted: list[float] = []
    for tile in out:
        weight = max(0.02, float(weights.get(tile, 0.12)))
        if tile == VillageTile.house_front:
            ideal = road_width * 2.05
            weight *= max(0.18, 1.35 - abs(d_road - ideal) / max(road_width * 2.4, 0.1))
            if context["house_pad"]:
                weight *= 1.45
            # Pull houses toward district cores and away from inter-district gaps.
            weight *= 1.0 + affinity * 0.65
            if has_district and not inside_district and not context["market_pad"] and not context["house_pad"]:
                weight *= 0.50
        elif tile == VillageTile.yard:
            weight *= 1.35 if context["house_pad"] else 0.55
            weight *= 1.0 + affinity * 0.35
        elif tile == VillageTile.prop:
            weight *= 1.45 if context["market_pad"] else 0.85
            weight *= 1.0 + affinity * 0.30
        elif tile == VillageTile.tree_pocket:
            weight *= 0.40 if d_road < road_width * 2.4 else 1.15
        elif tile == VillageTile.plaza:
            if context["market_pad"] or district_role == "market":
                weight *= 1.55 + affinity * 0.45
            else:
                weight *= 0.40
        weighted.append(weight)
    return rng.choices(out, weights=weighted, k=1)[0]


def _postprocess_tiles(
    tiles: list[list[VillageTile]],
    *,
    contexts: list[list[dict[str, Any]]],
    rng: random.Random,
    road_width: float,
    style: str,
) -> list[list[VillageTile]]:
    n = len(tiles)

    def has_neighbor(j: int, i: int, wanted: set[VillageTile], radius: int = 1) -> bool:
        for nj in range(max(0, j - radius), min(n, j + radius + 1)):
            for ni in range(max(0, i - radius), min(n, i + radius + 1)):
                if (nj, ni) == (j, i):
                    continue
                if tiles[nj][ni] in wanted:
                    return True
        return False

    house_limit = 30 if style == "market_town" else 22 if style == "village" else 12
    house_count = 0
    fence_count = 0
    for j in range(n):
        for i in range(n):
            tile = tiles[j][i]
            context = contexts[j][i]
            if tile == VillageTile.house_front:
                if (
                    house_count >= house_limit
                    or context["dist_to_road"] > road_width * 3.55
                    or context["dist_to_road"] < road_width * 0.88
                    or not has_neighbor(j, i, {VillageTile.road, VillageTile.plaza}, radius=1)
                ):
                    tiles[j][i] = VillageTile.yard if context["house_pad"] and rng.random() < 0.50 else VillageTile.empty
                    continue
                house_count += 1
            elif tile == VillageTile.fence:
                if (
                    fence_count >= max(10, house_limit // 2)
                    or not has_neighbor(j, i, {VillageTile.house_front, VillageTile.yard, VillageTile.plaza}, radius=1)
                ):
                    tiles[j][i] = VillageTile.prop if context["market_pad"] and rng.random() < 0.35 else VillageTile.empty
                    continue
                fence_count += 1
            elif tile == VillageTile.yard:
                if not has_neighbor(j, i, {VillageTile.house_front, VillageTile.fence}, radius=1):
                    tiles[j][i] = VillageTile.tree_pocket if rng.random() < 0.38 else VillageTile.empty
            elif tile == VillageTile.tree_pocket:
                if has_neighbor(j, i, {VillageTile.road, VillageTile.plaza}, radius=1):
                    tiles[j][i] = VillageTile.empty
            elif tile == VillageTile.prop:
                if context["dist_to_road"] > road_width * 3.0 and not context["market_pad"]:
                    tiles[j][i] = VillageTile.empty
    return tiles


def _fallback_tile(context: dict[str, Any]) -> VillageTile:
    if context.get("fixed"):
        if context.get("dist_to_road", 10**9) < 10**8:
            return VillageTile.road
        return VillageTile.blocked
    if context.get("market_pad"):
        return VillageTile.plaza
    if context.get("house_pad") and context.get("dist_to_road", 10**9) < 20.0:
        return VillageTile.house_front
    return VillageTile.empty


def _tiles_to_placements(
    tiles: list[list[VillageTile]],
    *,
    contexts: list[list[dict[str, Any]]],
    rng: random.Random,
    style: str,
    height_at: HeightAt,
) -> tuple[list[VillageCell], list[VillagePlacement]]:
    cells: list[VillageCell] = []
    placements: list[VillagePlacement] = []
    n = len(tiles)
    for j in range(n):
        for i in range(n):
            tile = tiles[j][i]
            context = contexts[j][i]
            x = float(context["x"])
            y = float(context["y"])
            road_angle = float(context["road_angle"])
            cells.append(VillageCell(
                i=i,
                j=j,
                x=x,
                y=y,
                tile=tile,
                fixed=bool(context.get("fixed", False)),
                dist_to_road=float(context.get("dist_to_road", 10**9)),
                road_angle=road_angle,
                in_market_pad=bool(context.get("market_pad")),
                in_house_pad=bool(context.get("house_pad")),
            ))
            priority = 1.0
            _ = height_at(x, y)  # validate callback while keeping this module z-agnostic.
            if tile == VillageTile.house_front:
                # Maquette low-poly houses generally face local -Y.
                rot = road_angle - math.pi * 0.5 + rng.uniform(-0.12, 0.12)
                placements.append(VillagePlacement(
                    kind="house",
                    alternatives=("fence",),
                    x=x,
                    y=y,
                    rot_z=rot,
                    zone="wfc_house_front",
                    tile=tile.value,
                    scale_range=(0.72, 1.05),
                    footprint_scale=0.92,
                    priority=priority + 0.7,
                ))
            elif tile == VillageTile.fence and rng.random() < 0.36:
                placements.append(VillagePlacement(
                    kind="fence",
                    alternatives=("crate", "barrel"),
                    x=x,
                    y=y,
                    rot_z=road_angle + rng.uniform(-0.18, 0.18),
                    zone="wfc_fence",
                    tile=tile.value,
                    scale_range=(0.60, 0.92),
                    footprint_scale=0.70,
                    priority=priority + 0.25,
                ))
            elif tile == VillageTile.prop and rng.random() < 0.68:
                prop_choices = ("crate", "barrel", "lantern", "signage")
                kind = rng.choice(prop_choices)
                placements.append(VillagePlacement(
                    kind=kind,
                    alternatives=tuple(k for k in prop_choices if k != kind),
                    x=x + rng.uniform(-0.9, 0.9),
                    y=y + rng.uniform(-0.9, 0.9),
                    rot_z=road_angle + rng.uniform(-0.5, 0.5),
                    zone="wfc_prop_pocket",
                    tile=tile.value,
                    scale_range=(0.54, 0.92),
                    footprint_scale=0.68,
                    priority=priority + 0.35,
                ))
            elif tile == VillageTile.yard and rng.random() < 0.62:
                kind = "haystack" if rng.random() < 0.52 else "fence"
                placements.append(VillagePlacement(
                    kind=kind,
                    alternatives=("fence", "crate", "barrel"),
                    x=x,
                    y=y,
                    rot_z=road_angle + math.pi * 0.5 + rng.uniform(-0.35, 0.35),
                    zone="wfc_yard",
                    tile=tile.value,
                    scale_range=(0.44, 0.82) if kind == "haystack" else (0.50, 0.86),
                    footprint_scale=0.78,
                    z_offset=-0.02 if kind == "haystack" else 0.0,
                    priority=priority,
                ))
            elif tile == VillageTile.tree_pocket and rng.random() < 0.54:
                placements.append(VillagePlacement(
                    kind="tree",
                    alternatives=("palm", "cactus", "boulder"),
                    x=x + rng.uniform(-0.7, 0.7),
                    y=y + rng.uniform(-0.7, 0.7),
                    rot_z=rng.uniform(0.0, math.tau),
                    zone="wfc_tree_pocket",
                    tile=tile.value,
                    scale_range=(0.64, 1.10),
                    footprint_scale=0.86,
                    priority=priority - 0.05,
                ))
            elif tile == VillageTile.plaza and rng.random() < (0.18 if style == "market_town" else 0.08):
                kind = rng.choice(("lantern", "signage", "barrel"))
                placements.append(VillagePlacement(
                    kind=kind,
                    alternatives=("crate", "barrel", "fence"),
                    x=x + rng.uniform(-1.1, 1.1),
                    y=y + rng.uniform(-1.1, 1.1),
                    rot_z=rng.uniform(0.0, math.tau),
                    zone="wfc_prop_pocket",
                    tile=tile.value,
                    scale_range=(0.52, 0.86),
                    footprint_scale=0.66,
                    priority=priority + 0.15,
                ))
    placements.sort(key=lambda p: (-p.priority, p.tile, p.x, p.y))
    return cells, placements


def _nearest_road_info(
    x: float,
    y: float,
    road_paths: list[tuple[list[Any], float]],
) -> tuple[float, float, float, float]:
    best = (10**9, float(x), float(y), 0.0)
    for points, _width in road_paths:
        for start, end in zip(points, points[1:], strict=False):
            ax, ay = float(getattr(start, "x", 0.0)), float(getattr(start, "y", 0.0))
            bx, by = float(getattr(end, "x", 0.0)), float(getattr(end, "y", 0.0))
            abx = bx - ax
            aby = by - ay
            denom = max(abx * abx + aby * aby, 1e-6)
            t = max(0.0, min(1.0, ((float(x) - ax) * abx + (float(y) - ay) * aby) / denom))
            cx = ax + abx * t
            cy = ay + aby * t
            dist = math.hypot(float(x) - cx, float(y) - cy)
            if dist < best[0]:
                best = (dist, cx, cy, math.atan2(aby, abx))
    return best


def _pad_contains(
    pads: list[Any],
    x: float,
    y: float,
    *,
    role_tokens: tuple[str, ...],
    margin: float,
) -> bool:
    for pad in pads:
        role = str(getattr(pad, "role", "") or "").lower()
        if role_tokens and not any(token in role for token in role_tokens):
            continue
        contains = getattr(pad, "contains", None)
        if callable(contains):
            try:
                if bool(contains(float(x), float(y), margin=margin)):
                    return True
            except TypeError:
                if bool(contains(float(x), float(y))):
                    return True
        else:
            px = float(getattr(pad, "x", 0.0))
            py = float(getattr(pad, "y", 0.0))
            rx = float(getattr(pad, "radius_x", 8.0)) * margin
            ry = float(getattr(pad, "radius_y", 8.0)) * margin
            if ((float(x) - px) / max(rx, 1e-4)) ** 2 + ((float(y) - py) / max(ry, 1e-4)) ** 2 <= 1.0:
                return True
    return False


def _write_debug_outputs(layout: VillageWFCLayout, out_dir: str | Path | None) -> None:
    if not out_dir:
        return
    target = Path(out_dir)
    try:
        target.mkdir(parents=True, exist_ok=True)
        payload = layout.as_payload()
        (target / "strata_wfc_village_layout.json").write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )
        # Backward-compatible name used by previous comparison tooling.
        (target / "strata_wfc_settlement_experiment.json").write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass
    try:
        from PIL import Image, ImageDraw

        scale = 12
        n = layout.grid_size
        img = Image.new("RGB", (n * scale, n * scale), (36, 40, 34))
        draw = ImageDraw.Draw(img)
        colors = {
            VillageTile.blocked.value: (42, 42, 42),
            VillageTile.empty.value: (74, 82, 58),
            VillageTile.road.value: (158, 125, 78),
            VillageTile.plaza.value: (176, 145, 94),
            VillageTile.house_front.value: (182, 80, 61),
            VillageTile.yard.value: (133, 121, 73),
            VillageTile.fence.value: (107, 74, 49),
            VillageTile.prop.value: (212, 143, 72),
            VillageTile.tree_pocket.value: (55, 112, 57),
        }
        for cell in layout.cells:
            color = colors.get(cell.tile.value, (96, 110, 68))
            draw.rectangle(
                (
                    cell.i * scale,
                    cell.j * scale,
                    (cell.i + 1) * scale - 1,
                    (cell.j + 1) * scale - 1,
                ),
                fill=color,
            )
        for placement in layout.placements:
            gx = int(round((placement.x - layout.market["x"]) / layout.cell_size + layout.grid_size // 2))
            gy = int(round((placement.y - layout.market["y"]) / layout.cell_size + layout.grid_size // 2))
            if 0 <= gx < n and 0 <= gy < n:
                cx = gx * scale + scale // 2
                cy = gy * scale + scale // 2
                draw.ellipse((cx - 3, cy - 3, cx + 3, cy + 3), outline=(255, 245, 210), width=1)
        img.save(target / "strata_wfc_village_layout.png")
        img.save(target / "strata_wfc_settlement_experiment.png")
    except Exception:
        pass

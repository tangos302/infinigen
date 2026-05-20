"""Maquette terrain bridge for Strata heightfields.

This module is intentionally Maquette-side. It consumes Strata's geometry
package, but all visible terrain color/material work is Maquette's existing
vertex-color terrain pipeline. Strata style artifacts are ignored.
"""

from __future__ import annotations

import json
import os
import math
import random
import heapq
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class TerrainPoint:
    x: float
    y: float
    z: float
    role: str = ""
    name: str = ""

    def __iter__(self):
        # Maquette scripts commonly unpack placement samples as
        # ``for x, y in terrain.find_placeable_points(...)`` and then use
        # ``terrain.height_at(x, y)`` through their local place() helper.
        # Keep z available as ``point.z`` for scripts that want it.
        yield self.x
        yield self.y

    def __getitem__(self, index):
        # Integer indexing maps 0/1/2 → x/y/z. Slicing returns a tuple so
        # LLM-authored build.py can do ``pt[:2]`` to grab (x, y). We
        # observed real LLM output that wrote ``pts[i][:2]``; without
        # slice support that crashes with IndexError("slice(None, 2, None)").
        if isinstance(index, slice):
            return (self.x, self.y, self.z)[index]
        if index == 0:
            return self.x
        if index == 1:
            return self.y
        if index == 2:
            return self.z
        raise IndexError(index)

    @property
    def location(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.z)

    @property
    def radius(self) -> float:
        """Compatibility radius for LLM-authored zone code.

        `SettlementLayout.tree_zones` and `outer_zones` are lightweight
        TerrainPoints. Real build scripts sometimes treat those zone anchors
        like RegionAnchor/DistrictAnchor and read `.radius`. Returning a
        conservative default keeps those scripts recoverable without turning
        every zone into a heavier object.
        """
        role = str(self.role or "").lower()
        name = str(self.name or "").lower()
        if "outer" in role or "outer" in name:
            return 18.0
        if "tree" in role or "tree" in name or "grove" in role or "grove" in name:
            return 14.0
        if "market" in role or "pad" in role:
            return 12.0
        return 10.0


@dataclass
class WaterAnchor:
    x: float
    y: float
    z: float
    radius: float
    shore_points: list[TerrainPoint]

    @property
    def cx(self) -> float:
        return self.x

    @property
    def cy(self) -> float:
        return self.y

    @property
    def target_z(self) -> float:
        return self.z

    @property
    def center(self) -> tuple[float, float]:
        return (self.x, self.y)

    @property
    def location(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.z)


@dataclass
class RegionAnchor:
    name: str
    role: str
    x: float
    y: float
    z: float
    radius: float
    points: list[TerrainPoint]

    @property
    def center(self) -> tuple[float, float]:
        return (self.x, self.y)

    @property
    def location(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.z)


@dataclass
class CameraHeroAnchor:
    cx: float
    cy: float
    radius: float
    target_z: float = 0.0
    lift: float = 0.0


@dataclass
class CameraComposition:
    heroes: list[CameraHeroAnchor]
    water: WaterAnchor | None = None
    ridges: list[Any] | None = None
    camera_profile: str = "default"

    def __post_init__(self) -> None:
        if self.ridges is None:
            self.ridges = []


@dataclass
class RoadPath:
    name: str
    role: str
    points: list[TerrainPoint]
    width: float = 5.0

    def __iter__(self):
        return iter(self.points)

    def __len__(self) -> int:
        return len(self.points)

    def __getitem__(self, index: int) -> TerrainPoint:
        return self.points[index]

    @property
    def start(self) -> TerrainPoint:
        return self.points[0]

    @property
    def end(self) -> TerrainPoint:
        return self.points[-1]


@dataclass
class HeroGroundPad:
    name: str
    role: str
    x: float
    y: float
    radius_x: float
    radius_y: float
    angle: float
    irregularity: float = 0.14

    @property
    def center(self) -> tuple[float, float]:
        return (self.x, self.y)

    def contains(self, x: float, y: float, *, margin: float = 1.0) -> bool:
        dx = float(x) - self.x
        dy = float(y) - self.y
        c = math.cos(-self.angle)
        s = math.sin(-self.angle)
        lx = dx * c - dy * s
        ly = dx * s + dy * c
        value = math.hypot(
            lx / max(self.radius_x * float(margin), 1e-4),
            ly / max(self.radius_y * float(margin), 1e-4),
        )
        return value <= 1.0


_CASTLE_OUTPOST_KEYWORDS: tuple[str, ...] = (
    "castle_outpost",
    "castle outpost",
    "castle",
    "fortress",
    "keep",
    "citadel",
    "outpost",
    "stronghold",
)


_HERO_TOWER_PROMPT_CUES: tuple[str, ...] = (
    "watchtower",
    "watch tower",
    "stone keep",
    "tall keep",
    "main keep",
    "lone watchtower",
    "lone tower",
    "lone keep",
    "lighthouse",
    "main tower",
    "great tower",
    "central tower",
    "hilltop tower",
    "tower of",
)


def _prompt_lists_tower_as_hero(prompt: str | None) -> bool:
    """True when the user prompt explicitly names a tower/keep as a focal.

    The detector is intentionally narrow: 'a small fence and a tower in the
    distance' is not enough — we want phrases that imply the tower IS the
    visible landmark. Castle prompts always trigger the hero promotion via
    the castle_outpost kind path; this helper covers non-castle scenes.
    """
    if not prompt:
        return False
    text = " ".join(prompt.lower().split())
    return any(cue in text for cue in _HERO_TOWER_PROMPT_CUES)


def is_castle_outpost_kind(kind: str | None) -> bool:
    """True when the settlement kind reads as a castle/outpost.

    v2-4: routes to the castle archetype (keep on high ground, gatehouse,
    garrison, no market plaza). The substring check stays generic — any
    kind containing castle/fortress/keep/citadel/outpost/stronghold opts in.
    """
    if not kind:
        return False
    style = str(kind).lower()
    return any(token in style for token in _CASTLE_OUTPOST_KEYWORDS)


def _settlement_archetype_for_kind(kind: str | None, *, prompt: str | None = None) -> str:
    """Coarse scene grammar bucket used by reports and quality gates.

    The settlement ``kind`` is often generic ("village") even when the prompt
    names a coastal fishing village or oasis bazaar. Use both signals so
    downstream metrics do not judge every settlement as a market town.
    """
    text = f"{kind or ''} {prompt or ''}".lower()
    if is_castle_outpost_kind(text):
        return "castle_outpost"
    if any(token in text for token in ("coastal", "fishing", "dock", "pier", "jetty", "shoreline", "seaside")):
        return "coastal_village"
    if any(token in text for token in ("oasis", "bazaar", "caravan", "palm grove", "desert settlement")):
        return "oasis_bazaar"
    if "hamlet" in text or "farm" in text:
        return "hamlet"
    if "village" in text:
        return "village"
    return "market_town"


def _settlement_district_count(kind: str, size: float) -> int:
    """Target district count for a settlement kind on a given map size.

    v8 ships a *generous* default for market_town / town / city. The fresh-
    LLM run in v7 called settlement_layout(...) without passing
    house_clusters and got the v7 default of 2 → that produced a hamlet,
    not a market town. The v8 default for a 280 BU full-side map
    (size=140 half-side) is 5 clusters: one market core + 2 residential
    + 1 craft + 1 outskirt/farm. Smaller settlement kinds keep the
    smaller defaults so we don't over-cluster a hamlet.

    v2-4: castle_outpost gets a smaller table — a keep + gatehouse + small
    garrison reads cleanly with 3-4 districts; more clusters dilute the
    "outpost" composition into a town.
    """
    style = str(kind or "").lower()
    if "hamlet" in style or "oasis" in style or "farm" in style:
        return 1
    if is_castle_outpost_kind(style):
        # Keep (focal) + gatehouse + 1-2 garrison/outer huts. Large maps
        # may add a second outer cluster, but we cap at 4 — a castle outpost
        # isn't a market town with extra walls.
        if float(size) >= 200.0:
            return 4
        if float(size) >= 130.0:
            return 3
        return 2
    if "village" in style:
        if float(size) >= 180.0:
            return 3
        if float(size) >= 120.0:
            return 2
        return 1
    # market_town / town / city
    if float(size) >= 230.0:
        return 6
    if float(size) >= 170.0:
        return 5
    if float(size) >= 130.0:
        return 4
    if float(size) >= 90.0:
        return 3
    return 2


def _district_role_for_index_castle_outpost(index: int) -> str:
    """Castle outpost district roles: keep focal (the 'market' slot in the
    layout dataclass is reused for the keep), gatehouse near approach,
    garrison huts in the lower yard, outer scout/lookout when an extra
    cluster is allowed."""
    if index <= 0:
        return "keep_approach"
    if index == 1:
        return "gatehouse"
    if index == 2:
        return "garrison_hut"
    return "outer_hut"


def _district_role_for_index_v8(index: int, total_clusters: int) -> str:
    """v8 district role labels biased toward market_town flavours.

    Order: residential (close-in) → craft → gate (outermost) → farmstead.
    Used by settlement_layout to tag clusters in the sidecar so downstream
    debugging can attribute placements to district types.
    """
    if index <= 0:
        return "residential"
    if index == 1:
        return "craft"
    if index == 2:
        return "residential"
    if index == 3:
        return "gate"
    return "farmstead"


def _district_role_for_index(index: int) -> str:
    """Generic district role labels in placement order (non-market only)."""
    if index <= 0:
        return "residential"
    if index == 1:
        return "craft"
    return "gate"


@dataclass
class HeroLandmark:
    """v2-5: a recommendation for the build script's focal landmark.

    The bridge picks the position (high pad for castle/keep; the existing
    tower pad otherwise) and the scale (boosted when the prompt or kind
    implies a hero landmark). Build scripts consult ``layout.hero_landmark``
    when authoring towers/keeps, so the bridge can downstream verify whether
    the recommendation was honoured (footprint reserved near (x, y) with
    radius near the recommended scale).

    ``prominence_ok`` is True when the chosen position sits above the median
    height of the flat pads — i.e. the landmark would be visible from a
    default camera framing.
    """

    kind: str                     # "keep", "watchtower", or "tower"
    x: float
    y: float
    z: float
    recommended_scale: float       # multiplier to apply to the factory's base size
    prominence_ok: bool
    reason: str                    # short explanation: "castle_archetype" / "highest_pad" / "tower_pad"


@dataclass
class DistrictAnchor:
    """A coarse district nucleus used by WFC to spread settlements out.

    Each district is a bias center for house placement. Districts are kept
    minimal on purpose: x/y/radius/role is enough for WFC to bias weights and
    for spatial metrics to attribute placements.
    """

    name: str
    role: str
    x: float
    y: float
    radius: float

    @property
    def center(self) -> tuple[float, float]:
        return (self.x, self.y)

    def affinity(self, x: float, y: float) -> float:
        d = math.hypot(float(x) - self.x, float(y) - self.y)
        return max(0.0, 1.0 - d / max(self.radius, 1e-4))


@dataclass(frozen=True)
class CastleWallSegment:
    start_x: float
    start_y: float
    end_x: float
    end_y: float
    mid_x: float
    mid_y: float
    length: float
    rot_z: float


@dataclass(frozen=True)
class CastleCompoundPlan:
    center_x: float
    center_y: float
    gate_x: float
    gate_y: float
    gate_rot_z: float
    wall_radius_x: float
    wall_radius_y: float
    wall_segments: list[CastleWallSegment]


def _plan_castle_compound(
    keep: TerrainPoint,
    gate_hint: TerrainPoint | DistrictAnchor | None,
    *,
    size: float,
    pad_radius: float | None = None,
) -> CastleCompoundPlan:
    """Plan a compact castle yard around the keep.

    The factory layer builds the meshes later; this pure geometry helper keeps
    the visible castle grammar testable without Blender. Local +X points from
    the keep toward the gatehouse, and the gate side has an intentional gap.
    """
    cx = float(keep.x)
    cy = float(keep.y)
    if gate_hint is not None:
        dx = float(gate_hint.x) - cx
        dy = float(gate_hint.y) - cy
    else:
        dx, dy = 1.0, 0.0
    if math.hypot(dx, dy) < 1e-3:
        dx, dy = 1.0, 0.0
    gate_angle = math.atan2(dy, dx)
    ux, uy = math.cos(gate_angle), math.sin(gate_angle)
    vx, vy = -uy, ux

    radius_hint = float(pad_radius or 16.0)
    rx = max(15.0, min(max(radius_hint * 1.18, 18.0), float(size) * 0.18, 30.0))
    ry = max(11.0, min(rx * 0.76, float(size) * 0.145, 23.0))
    gate_gap = max(5.5, min(ry * 0.52, 8.5))

    def world(local_x: float, local_y: float) -> tuple[float, float]:
        return (
            cx + ux * local_x + vx * local_y,
            cy + uy * local_x + vy * local_y,
        )

    def segment(a: tuple[float, float], b: tuple[float, float]) -> CastleWallSegment | None:
        sx, sy = world(a[0], a[1])
        ex, ey = world(b[0], b[1])
        length = math.hypot(ex - sx, ey - sy)
        if length < 4.0:
            return None
        return CastleWallSegment(
            start_x=sx,
            start_y=sy,
            end_x=ex,
            end_y=ey,
            mid_x=(sx + ex) * 0.5,
            mid_y=(sy + ey) * 0.5,
            length=length,
            rot_z=math.atan2(ey - sy, ex - sx),
        )

    raw_segments = [
        segment((-rx, -ry), (-rx, ry)),
        segment((-rx, -ry), (rx, -ry)),
        segment((-rx, ry), (rx, ry)),
        segment((rx, -ry), (rx, -gate_gap)),
        segment((rx, gate_gap), (rx, ry)),
    ]
    gate_x, gate_y = world(rx + 1.8, 0.0)
    return CastleCompoundPlan(
        center_x=cx,
        center_y=cy,
        gate_x=gate_x,
        gate_y=gate_y,
        gate_rot_z=gate_angle - math.pi * 0.5,
        wall_radius_x=rx,
        wall_radius_y=ry,
        wall_segments=[s for s in raw_segments if s is not None],
    )


@dataclass
class ScenePathGraph:
    kind: str
    nodes: list[TerrainPoint]
    paths: list[RoadPath]
    edge_paths: list[RoadPath]


@dataclass
class SettlementLayout:
    kind: str
    market: TerrainPoint
    tower: TerrainPoint | None
    house_clusters: list[TerrainPoint]
    support_points: list[TerrainPoint]
    road_pairs: list[tuple[TerrainPoint, TerrainPoint]]
    pads: list[RegionAnchor]
    tree_zones: list[TerrainPoint] | None = None
    outer_zones: list[TerrainPoint] | None = None
    path_graph: ScenePathGraph | None = None
    road_paths: list[RoadPath] | None = None
    hero_pads: list[HeroGroundPad] | None = None
    districts: list[DistrictAnchor] | None = None
    hero_landmark: HeroLandmark | None = None

    def __post_init__(self) -> None:
        if self.tree_zones is None:
            self.tree_zones = []
        if self.outer_zones is None:
            self.outer_zones = []
        if self.road_paths is None:
            self.road_paths = [
                RoadPath(
                    name=f"{start.name}_to_{end.name}",
                    role="settlement_road",
                    points=[start, end],
                    width=5.0,
                )
                for start, end in self.road_pairs
            ]
        if self.hero_pads is None:
            self.hero_pads = []
        if self.districts is None:
            self.districts = []

    @property
    def camera_anchors(self) -> list[tuple[float, float, float]]:
        anchors: list[tuple[float, float, float]] = [
            (self.market.x, self.market.y, 18.0),
        ]
        if self.tower is not None:
            anchors.append((self.tower.x, self.tower.y, 16.0))
        anchors.extend((p.x, p.y, 10.0) for p in self.house_clusters[:4])
        return anchors

    @property
    def all_anchors(self) -> list[TerrainPoint]:
        out = [self.market]
        if self.tower is not None:
            out.append(self.tower)
        out.extend(self.house_clusters)
        return out

    @property
    def road_edge_anchors(self) -> list[TerrainPoint]:
        anchors: list[TerrainPoint] = []
        for start, end in self.road_pairs:
            mx = (start.x + end.x) * 0.5
            my = (start.y + end.y) * 0.5
            anchors.append(TerrainPoint(
                x=mx,
                y=my,
                z=(start.z + end.z) * 0.5,
                role="road_edge",
                name=f"{start.name}_to_{end.name}",
            ))
        return anchors

    def road_distance(self, x: float, y: float) -> float:
        if self.road_paths:
            return min(
                _point_polyline_distance(float(x), float(y), path.points)
                for path in self.road_paths
                if len(path.points) >= 2
            )
        if not self.road_pairs:
            return 10**9
        return min(
            _point_segment_distance(float(x), float(y), start.x, start.y, end.x, end.y)
            for start, end in self.road_pairs
        )

    def anchor_distance(self, x: float, y: float) -> float:
        anchors = self.all_anchors
        if not anchors:
            return 10**9
        return min(math.hypot(float(x) - p.x, float(y) - p.y) for p in anchors)


class TerrainRegions:
    def __init__(self, regions: list[RegionAnchor]):
        self._regions = list(regions)

    def all(self) -> list[RegionAnchor]:
        return list(self._regions)

    def by_role(self, role: str) -> list[RegionAnchor]:
        wanted = str(role).strip().lower()
        wanted_roles = _resolve_region_role_query(wanted)
        return [
            region for region in self._regions
            if region.role.lower() in wanted_roles
        ]

    def first(self, role: str) -> RegionAnchor | None:
        matches = self.by_role(role)
        return matches[0] if matches else None

    def points(self, role: str, count: int = 8) -> list[TerrainPoint]:
        out: list[TerrainPoint] = []
        for region in self.by_role(role):
            out.extend(region.points)
        return _evenly_limit_points(out, int(count))


def _resolve_region_role_query(role: str) -> set[str]:
    wanted = str(role).strip().lower()
    aliases = {
        "ruin_pad": {"flat_feature_pad"},
        "pad": {"flat_feature_pad"},
        "landmark": {"flat_feature_pad"},
        "landmark_pad": {"flat_feature_pad"},
        "beach": {"shore_shelf"},
        "shoreline": {"shore_shelf"},
        "water_edge": {"shore_shelf"},
        "rim": {"ridge_field"},
        "ridge": {"ridge_field", "backdrop"},
        "dry": {"base", "ridge_field", "backdrop", "flat_feature_pad"},
        "desert": {"base", "ridge_field", "backdrop", "shore_shelf"},
        "natural": {"base", "ridge_field", "backdrop", "shore_shelf"},
        "scatter": {"base", "ridge_field", "backdrop", "shore_shelf"},
        "any": {"base", "ridge_field", "backdrop", "shore_shelf", "flat_feature_pad"},
    }
    return aliases.get(wanted, {wanted})


def _load_heightfield(strata_dir: Path):
    import numpy as np

    height_path = strata_dir / "strata_heights.npy"
    terrain_path = strata_dir / "terrain.json"
    if height_path.is_file():
        heights = np.load(height_path).astype("float32")
    elif terrain_path.is_file():
        payload = json.loads(terrain_path.read_text(encoding="utf-8"))
        res = int(payload["resolution"])
        heights = np.asarray(payload["heights"], dtype="float32").reshape(res, res)
    else:
        raise FileNotFoundError(
            f"Strata terrain package missing strata_heights.npy/terrain.json in {strata_dir}"
        )
    if heights.ndim != 2 or min(heights.shape) < 2:
        raise ValueError(f"Invalid Strata heightfield shape: {heights.shape!r}")
    if not np.isfinite(heights).all():
        finite = heights[np.isfinite(heights)]
        fill = float(np.nanmedian(finite)) if finite.size else 0.0
        heights = np.nan_to_num(heights, nan=fill, posinf=fill, neginf=fill).astype("float32")

    if terrain_path.is_file():
        payload = json.loads(terrain_path.read_text(encoding="utf-8"))
        world_size = float(payload.get("world_size") or max(heights.shape))
        biome_hint = str(payload.get("biome_hint") or "")
        seed = int(payload.get("seed") or 0)
    else:
        world_size = float(max(heights.shape))
        biome_hint = ""
        seed = 0
    return heights, world_size, biome_hint, seed


def _finite_median(values: Any) -> float | None:
    import numpy as np

    arr = np.asarray(values, dtype="float32")
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return None
    value = float(np.median(finite))
    return value if math.isfinite(value) else None


def _grid_to_world(j: Any, i: Any, *, size: float, shape: tuple[int, int]):
    res_y, res_x = shape
    x = -float(size) + (i / max(res_x - 1, 1)) * (2.0 * float(size))
    y = -float(size) + (j / max(res_y - 1, 1)) * (2.0 * float(size))
    return x, y


def _world_to_grid(x: float, y: float, *, size: float, shape: tuple[int, int]) -> tuple[int, int]:
    res_y, res_x = shape
    u = (float(x) + float(size)) / (2.0 * float(size)) * (res_x - 1)
    v = (float(y) + float(size)) / (2.0 * float(size)) * (res_y - 1)
    i = int(max(0, min(res_x - 1, round(u))))
    j = int(max(0, min(res_y - 1, round(v))))
    return j, i


def _dilate_mask(mask, *, iterations: int = 1):
    import numpy as np

    out = mask.astype(bool)
    for _ in range(max(int(iterations), 1)):
        padded = np.pad(out, 1, mode="constant", constant_values=False)
        grown = np.zeros_like(out, dtype=bool)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                grown |= padded[1 + dy:1 + dy + out.shape[0],
                                1 + dx:1 + dx + out.shape[1]]
        out = grown
    return out


def _smooth_heightfield(heights, *, iterations: int = 1, strength: float = 0.38):
    import numpy as np

    out = heights.astype("float32", copy=True)
    strength = float(max(0.0, min(1.0, strength)))
    for _ in range(max(int(iterations), 0)):
        padded = np.pad(out, 1, mode="edge")
        avg = (
            padded[:-2, :-2] + padded[:-2, 1:-1] + padded[:-2, 2:]
            + padded[1:-1, :-2] + padded[1:-1, 1:-1] * 4.0 + padded[1:-1, 2:]
            + padded[2:, :-2] + padded[2:, 1:-1] + padded[2:, 2:]
        ) / 12.0
        out = out * (1.0 - strength) + avg * strength
    return out.astype("float32", copy=False)


def _smoothstep(edge0: float, edge1: float, value):
    import numpy as np

    if abs(float(edge1) - float(edge0)) < 1e-6:
        return np.where(value >= edge1, 1.0, 0.0)
    t = np.clip((value - float(edge0)) / (float(edge1) - float(edge0)), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _soften_flat_feature_pads(heights, strata_dir: Path, *, size: float):
    """Round Strata's artificial pads before building the render mesh.

    Phase-1 regions can arrive as cell/polygon footprints. If we render those
    footprints directly, settlement pads read as hexagonal/board-game pieces.
    This pass converts each flat-feature region into a soft circular SDF-like
    blend: flat enough for buildings, but with a rounded skirt into the
    surrounding terrain.
    """
    import numpy as np

    index_path = strata_dir / "strata_region_index.npy"
    table_path = strata_dir / "strata_region_table.json"
    if not (index_path.is_file() and table_path.is_file()):
        return heights
    try:
        region_index = np.load(index_path)
        table = json.loads(table_path.read_text(encoding="utf-8"))
    except Exception:
        return heights
    if tuple(region_index.shape) != tuple(heights.shape):
        return heights

    out = heights.astype("float32", copy=True)
    yy, xx = np.indices(out.shape, dtype=np.float32)
    pad_rows: list[tuple[int, str]] = []
    for row in table:
        role = str(row.get("role") or "").lower()
        if role != "flat_feature_pad":
            continue
        try:
            pad_rows.append((int(row.get("index")), str(row.get("name") or "")))
        except Exception:
            continue

    for idx, name in pad_rows:
        mask = region_index == idx
        area = int(mask.sum())
        if area < 8:
            continue
        jj, ii = np.nonzero(mask)
        cx = float(np.mean(ii))
        cy = float(np.mean(jj))
        radius = math.sqrt(float(area) / math.pi)
        if not math.isfinite(radius) or radius < 1.5:
            continue

        # Use an axis-aligned ellipse rather than the raw polygon mask. The
        # Strata LLM often emits hex-ish pads for towns/landmarks; using the
        # mask directly keeps those facets visible in the terrain.
        sx = max(2.5, radius * 0.95, float(np.std(ii)) * 2.15)
        sy = max(2.5, radius * 0.95, float(np.std(jj)) * 2.15)
        edist = np.hypot((xx - cx) / sx, (yy - cy) / sy)
        inner = 0.72
        outer = 2.15
        affected = edist <= outer
        if not np.any(affected):
            continue

        target = float(np.median(out[mask]))
        if not math.isfinite(target):
            continue

        ring = (edist > 1.12) & (edist <= outer)
        ring_values = out[ring]
        if ring_values.size == 0:
            ring_values = out[affected]
        ring_median = float(np.median(ring_values))
        if not math.isfinite(ring_median):
            ring_median = target

        lower_name = name.lower()
        can_stand_proud = any(cue in lower_name for cue in ("tower", "watch", "keep", "citadel", "peak"))
        allowed_lift = 1.8 if can_stand_proud else 0.55
        target = min(target, ring_median + allowed_lift)

        blend = (1.0 - _smoothstep(inner, outer, edist)).astype("float32")
        radial_level = (
            target
            + (ring_median - target) * _smoothstep(inner * 0.92, outer, edist)
        ).astype("float32")
        center_strength = 0.88 if can_stand_proud else 0.82
        strength = np.where(edist <= inner, center_strength, 0.74).astype("float32")
        w = blend * strength
        out[affected] = out[affected] * (1.0 - w[affected]) + radial_level[affected] * w[affected]

        skirt = affected & (edist >= inner * 0.72)
        if np.any(skirt):
            smoothed = _smooth_heightfield(out, iterations=2, strength=0.42)
            out[skirt] = out[skirt] * 0.30 + smoothed[skirt] * 0.70

    return out.astype("float32", copy=False)


def _point_segment_distance(
    px: float,
    py: float,
    ax: float,
    ay: float,
    bx: float,
    by: float,
) -> float:
    abx = float(bx) - float(ax)
    aby = float(by) - float(ay)
    denom = abx * abx + aby * aby
    if denom <= 1e-9:
        return math.hypot(float(px) - float(ax), float(py) - float(ay))
    t = ((float(px) - float(ax)) * abx + (float(py) - float(ay)) * aby) / denom
    t = max(0.0, min(1.0, t))
    qx = float(ax) + abx * t
    qy = float(ay) + aby * t
    return math.hypot(float(px) - qx, float(py) - qy)


def _point_polyline_distance(px: float, py: float, points: list[TerrainPoint]) -> float:
    if len(points) < 2:
        if points:
            return math.hypot(float(px) - points[0].x, float(py) - points[0].y)
        return 10**9
    return min(
        _point_segment_distance(float(px), float(py), a.x, a.y, b.x, b.y)
        for a, b in zip(points, points[1:], strict=False)
    )


def _evenly_limit_points(points: list[TerrainPoint], count: int) -> list[TerrainPoint]:
    if count <= 0:
        return []
    if len(points) <= count:
        return list(points)
    if count == 1:
        return [points[0]]
    step = (len(points) - 1) / float(count - 1)
    return [points[int(round(i * step))] for i in range(count)]


def _sample_mask_points(
    mask,
    *,
    size: float,
    count: int,
    height_at,
    role: str,
    name: str,
    center_xy: tuple[float, float] | None = None,
) -> list[TerrainPoint]:
    import numpy as np

    jj, ii = np.nonzero(mask)
    if len(jj) == 0:
        return []
    xs, ys = _grid_to_world(jj.astype("float32"), ii.astype("float32"),
                            size=size, shape=mask.shape)
    if center_xy is None:
        cx = float(np.mean(xs))
        cy = float(np.mean(ys))
    else:
        cx, cy = center_xy
    angles = np.arctan2(ys - cy, xs - cx)
    radii = np.hypot(xs - cx, ys - cy)
    order = np.lexsort((-radii, angles))
    xs = xs[order]
    ys = ys[order]
    raw = [
        TerrainPoint(
            x=float(x),
            y=float(y),
            z=float(height_at(float(x), float(y))),
            role=role,
            name=name,
        )
        for x, y in zip(xs, ys, strict=False)
    ]
    return _evenly_limit_points(raw, int(count))


def _build_region_anchors(
    strata_dir: Path,
    *,
    heights,
    size: float,
    height_at,
) -> TerrainRegions:
    import numpy as np

    index_path = strata_dir / "strata_region_index.npy"
    table_path = strata_dir / "strata_region_table.json"
    if not (index_path.is_file() and table_path.is_file()):
        return TerrainRegions([])
    region_index = np.load(index_path)
    table = json.loads(table_path.read_text(encoding="utf-8"))
    cell = (2.0 * float(size)) / max(region_index.shape[0] - 1, 1)
    regions: list[RegionAnchor] = []
    for row in table:
        try:
            idx = int(row.get("index"))
        except Exception:
            continue
        mask = region_index == idx
        if int(mask.sum()) < 4:
            continue
        jj, ii = np.nonzero(mask)
        xw, yw = _grid_to_world(jj.astype("float32"), ii.astype("float32"),
                                size=size, shape=region_index.shape)
        cx = float(np.mean(xw))
        cy = float(np.mean(yw))
        role = str(row.get("role") or "")
        name = str(row.get("name") or role or f"region_{idx}")
        area = float(mask.sum()) * cell * cell
        radius = math.sqrt(max(area, 0.0) / math.pi)
        points = _sample_mask_points(
            mask,
            size=size,
            count=96,
            height_at=height_at,
            role=role,
            name=name,
            center_xy=(cx, cy),
        )
        regions.append(RegionAnchor(
            name=name,
            role=role,
            x=cx,
            y=cy,
            z=float(height_at(cx, cy)),
            radius=radius,
            points=points,
        ))
    return TerrainRegions(regions)


def _build_primary_water_anchor(
    strata_dir: Path,
    *,
    size: float,
    height_at,
) -> WaterAnchor | None:
    import numpy as np

    water_path = strata_dir / "strata_water_surface.npy"
    if not water_path.is_file():
        return None
    water = np.load(water_path).astype("float32")
    finite = np.isfinite(water)
    if int(finite.sum()) < 4:
        return None
    jj, ii = np.nonzero(finite)
    xw, yw = _grid_to_world(jj.astype("float32"), ii.astype("float32"),
                            size=size, shape=water.shape)
    cx = float(np.mean(xw))
    cy = float(np.mean(yw))
    cell = (2.0 * float(size)) / max(water.shape[0] - 1, 1)
    area = float(finite.sum()) * cell * cell
    radius = math.sqrt(max(area, 0.0) / math.pi)
    shore_mask = _dilate_mask(finite, iterations=3) & ~finite
    shore_points = _sample_mask_points(
        shore_mask,
        size=size,
        count=192,
        height_at=height_at,
        role="shore",
        name="primary_water_shore",
        center_xy=(cx, cy),
    )
    return WaterAnchor(
        x=cx,
        y=cy,
        z=float(np.nanmedian(water[finite])),
        radius=radius,
        shore_points=shore_points,
    )


def _terrain_palette_name(palette_preset: str | None, biome_hint: str) -> str:
    value = (palette_preset or biome_hint or "alpine").strip().lower()
    aliases = {
        "arid": "desert",
        "oasis": "desert",
        "snow": "tundra",
        "frozen": "tundra",
        "jungle": "tropical",
        "forest": "wetland",
        "coastal": "tropical",
        "lava": "volcanic",
        "medieval": "temperate",
        "town": "temperate",
        "village": "temperate",
        "market": "temperate",
        "grassland": "temperate",
        "meadow": "temperate",
    }
    return aliases.get(value, value)


def _write_vertex_color_material(mesh: Any) -> None:
    import bpy

    mat = bpy.data.materials.new("strata_maquette_terrain_mat")
    mat.use_nodes = True
    nt = mat.node_tree
    for node in list(nt.nodes):
        if node.type != "OUTPUT_MATERIAL":
            nt.nodes.remove(node)
    out_node = nt.nodes["Material Output"]
    attr = nt.nodes.new("ShaderNodeVertexColor")
    attr.layer_name = "Col"
    diffuse = nt.nodes.new("ShaderNodeBsdfDiffuse")
    diffuse.inputs["Roughness"].default_value = 1.0
    nt.links.new(attr.outputs["Color"], diffuse.inputs["Color"])
    nt.links.new(diffuse.outputs["BSDF"], out_node.inputs["Surface"])
    mesh.materials.append(mat)


def _set_node_input(node: Any, names: tuple[str, ...], value: Any) -> bool:
    for name in names:
        if name in node.inputs:
            node.inputs[name].default_value = value
            return True
    return False


def _get_or_create_strata_water_material() -> Any:
    import bpy

    mat = bpy.data.materials.get("strata_clear_water_mat")
    if mat is None:
        mat = bpy.data.materials.new("strata_clear_water_mat")
    mat.use_nodes = True
    mat.blend_method = "BLEND"
    mat.show_transparent_back = True
    if hasattr(mat, "use_screen_refraction"):
        mat.use_screen_refraction = True
    if hasattr(mat, "surface_render_method"):
        # Blender 4.x Eevee Next uses surface_render_method instead of
        # the older hashed/blend-only material flags.
        try:
            mat.surface_render_method = "BLENDED"
        except TypeError:
            pass
    if hasattr(mat, "use_raytrace_refraction"):
        mat.use_raytrace_refraction = True

    nt = mat.node_tree
    for node in list(nt.nodes):
        if node.type != "OUTPUT_MATERIAL":
            nt.nodes.remove(node)
    out_node = nt.nodes.get("Material Output")
    if out_node is None:
        out_node = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (-80, 0)
    _set_node_input(bsdf, ("Base Color",), (0.035, 0.42, 0.66, 0.78))
    _set_node_input(bsdf, ("Alpha",), 0.74)
    _set_node_input(bsdf, ("Roughness",), 0.055)
    _set_node_input(bsdf, ("Metallic",), 0.0)
    _set_node_input(bsdf, ("IOR",), 1.333)
    _set_node_input(bsdf, ("Transmission Weight", "Transmission"), 0.22)
    _set_node_input(bsdf, ("Specular IOR Level", "Specular"), 0.82)

    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.location = (-620, -170)
    _set_node_input(noise, ("Scale",), 38.0)
    _set_node_input(noise, ("Detail",), 9.0)
    _set_node_input(noise, ("Roughness",), 0.46)

    bump = nt.nodes.new("ShaderNodeBump")
    bump.location = (-330, -115)
    _set_node_input(bump, ("Strength",), 0.028)
    _set_node_input(bump, ("Distance",), 0.16)
    try:
        nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
        nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    except Exception:
        pass
    nt.links.new(bsdf.outputs["BSDF"], out_node.inputs["Surface"])
    return mat


def _build_flat_water_surface(name: str, mask, *, size: float, water_level: float):
    import bpy
    import numpy as np

    res_y, res_x = mask.shape
    span = 2.0 * float(size)
    cell_x = span / max(res_x - 1, 1)
    cell_y = span / max(res_y - 1, 1)
    z_top = float(water_level)

    # Convert the raster water mask into a slightly expanded radial polygon.
    # The old one-quad-per-mask-cell surface left tiny square gaps around
    # basin edges and made the shoreline look pixelated. The terrain basin is
    # already carved at the correct altitude; this mesh only needs to cover it.
    mask = _dilate_mask(mask.astype(bool), iterations=1)
    padded = np.pad(mask, 1, mode="constant", constant_values=False)
    inner = np.ones_like(mask, dtype=bool)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            inner &= padded[1 + dy:1 + dy + res_y, 1 + dx:1 + dx + res_x]
    boundary = mask & ~inner
    jj, ii = np.nonzero(boundary if int(boundary.sum()) >= 8 else mask)
    if len(jj) < 4:
        me = bpy.data.meshes.new(name)
        obj = bpy.data.objects.new(name, me)
        bpy.context.collection.objects.link(obj)
        return obj

    xs = -float(size) + ii.astype("float32") * cell_x
    ys = -float(size) + jj.astype("float32") * cell_y
    all_j, all_i = np.nonzero(mask)
    cx = float(np.mean(-float(size) + all_i.astype("float32") * cell_x))
    cy = float(np.mean(-float(size) + all_j.astype("float32") * cell_y))
    angles = np.arctan2(ys - cy, xs - cx)
    radii = np.hypot(xs - cx, ys - cy)
    n_segments = int(max(64, min(220, len(jj))))
    ring_r = np.zeros(n_segments, dtype=np.float32)
    for k in range(n_segments):
        a0 = -np.pi + (2.0 * np.pi) * (k / n_segments)
        a1 = -np.pi + (2.0 * np.pi) * ((k + 1) / n_segments)
        if k == n_segments - 1:
            sel = (angles >= a0) | (angles < -np.pi + 1e-6)
        else:
            sel = (angles >= a0) & (angles < a1)
        if np.any(sel):
            ring_r[k] = float(np.max(radii[sel]))
        else:
            mid = (a0 + a1) * 0.5
            delta = np.abs(np.angle(np.exp(1j * (angles - mid))))
            ring_r[k] = float(radii[int(np.argmin(delta))])
    for _ in range(2):
        ring_r = (
            np.roll(ring_r, 2) + np.roll(ring_r, 1) * 2.0
            + ring_r * 3.0
            + np.roll(ring_r, -1) * 2.0 + np.roll(ring_r, -2)
        ) / 9.0
    expand = max(cell_x, cell_y) * 2.2
    ring_r = ring_r + expand

    verts = [(cx, cy, z_top)]
    for k in range(n_segments):
        a = -math.pi + (2.0 * math.pi) * (k / n_segments)
        x = max(-float(size), min(float(size), cx + math.cos(a) * float(ring_r[k])))
        y = max(-float(size), min(float(size), cy + math.sin(a) * float(ring_r[k])))
        verts.append((x, y, z_top))
    faces = [(0, k, 1 + (k % n_segments)) for k in range(1, n_segments + 1)]
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    obj = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(obj)
    return obj


def _write_col_attribute(mesh: Any, colors, *, size: float) -> None:
    import numpy as np

    from infinigen.maquette.runtime.eroded_terrain import (
        _apply_stylised_passes,
        _biome_colors,
        _palette_linear,
        _resolve_palette,
    )

    heights = np.asarray(colors["heights"], dtype="float32")
    if not np.isfinite(heights).all():
        finite = heights[np.isfinite(heights)]
        fill = float(np.median(finite)) if finite.size else 0.0
        heights = np.nan_to_num(heights, nan=fill, posinf=fill, neginf=fill).astype("float32")
    palette_name = colors["palette_name"]
    seed = int(colors["seed"])
    sea_level = float(colors["sea_level"])
    if not math.isfinite(sea_level):
        sea_level = float(np.quantile(heights, 0.18))
    palette = _resolve_palette(None, palette_name)
    gy, gx = np.gradient(heights.astype("float32"))
    slope = np.hypot(gx, gy)
    alpine = (heights > np.quantile(heights, 0.72)) | (slope > np.quantile(slope, 0.78))
    col = _biome_colors(
        heights,
        alpine,
        sea_level,
        palette,
        dunes=palette_name == "desert",
    )
    col = _apply_stylised_passes(
        heights,
        col,
        palette,
        seed=seed,
        dunes=palette_name == "desert",
        palette_preset=palette_name,
    )
    if palette_name == "desert":
        # Strata oasis/dune maps have much taller continuous dune masses
        # than Maquette's native desert terrain. Letting the standard
        # painterly passes and Cycles shadows push them down produces huge
        # muddy brown regions. Replace the macro-painted desert with a
        # smoother sand/slope blend; water/lakebed still gets its darker
        # color from the water mesh.
        sand = np.array(_palette_linear("shore", palette), dtype=np.float32)
        warm_rock = np.array(_palette_linear("stone", palette), dtype=np.float32)
        pale_rock = np.array(_palette_linear("snow", palette), dtype=np.float32)
        z_lo, z_hi = float(heights.min()), float(heights.max())
        if z_hi - z_lo > 1e-3:
            z_norm = ((heights - z_lo) / (z_hi - z_lo)).astype(np.float32)
        else:
            z_norm = np.zeros_like(heights, dtype=np.float32)
        slope_q = float(np.quantile(slope, 0.88))
        slope_hi = float(np.quantile(slope, 0.985))
        slope_norm = np.clip((slope - slope_q) / max(slope_hi - slope_q, 1e-4), 0.0, 1.0)
        yy, xx = np.indices(heights.shape, dtype=np.float32)
        phase = (seed % 997) * 0.013
        broad = (
            np.sin(xx * 0.045 + phase)
            + np.sin(yy * 0.037 - phase * 1.7)
            + 0.55 * np.sin((xx + yy) * 0.024 + phase * 0.6)
        ) / 2.55
        broad = broad.astype(np.float32)
        shade = 0.96 + 0.055 * broad + 0.075 * z_norm + 0.045 * slope_norm
        calm_sand = sand[None, None, :] * shade[..., None]
        rock_tint = (warm_rock * 0.72 + pale_rock * 0.28)[None, None, :]
        steep_mix = (slope_norm ** 1.35)[..., None] * 0.36
        col = calm_sand * (1.0 - steep_mix) + rock_tint * steep_mix
        col = np.maximum(col, (sand * 0.76)[None, None, :])
        col = np.clip(col, 0.0, 1.0)
    elif palette_name == "temperate":
        # Settlement Strata maps should read as pasture + authored dirt
        # roads. Maquette's generic stylised pass adds broad rocky/dirt
        # territories, which look like accidental paths when buildings and
        # trees sit on top. Keep the base terrain mostly meadow/hedgerow;
        # settlement_layout() paints actual road corridors later.
        meadow = np.array(_palette_linear("meadow", palette), dtype=np.float32)
        forest = np.array(_palette_linear("forest", palette), dtype=np.float32)
        stone = np.array(_palette_linear("stone", palette), dtype=np.float32)
        z_lo, z_hi = float(heights.min()), float(heights.max())
        if z_hi - z_lo > 1e-3:
            z_norm = ((heights - z_lo) / (z_hi - z_lo)).astype(np.float32)
        else:
            z_norm = np.zeros_like(heights, dtype=np.float32)
        slope_q = float(np.quantile(slope, 0.88))
        slope_hi = float(np.quantile(slope, 0.985))
        slope_norm = np.clip((slope - slope_q) / max(slope_hi - slope_q, 1e-4), 0.0, 1.0)
        yy, xx = np.indices(heights.shape, dtype=np.float32)
        phase = (seed % 1069) * 0.011
        broad = (
            np.sin(xx * 0.030 + phase)
            + np.sin(yy * 0.026 - phase * 1.4)
            + 0.45 * np.sin((xx - yy) * 0.020 + phase * 0.7)
        ) / 2.45
        shade = 0.99 + 0.035 * broad + 0.055 * z_norm
        col = meadow[None, None, :] * shade[..., None]
        forest_mix = (
            np.clip((z_norm - 0.58) / 0.30, 0.0, 1.0)
            * np.clip(1.0 - slope_norm * 1.25, 0.0, 1.0)
            * 0.16
        )[..., None]
        col = col * (1.0 - forest_mix) + forest[None, None, :] * forest_mix
        rock_mix = (slope_norm ** 1.35 * 0.36)[..., None]
        col = col * (1.0 - rock_mix) + stone[None, None, :] * rock_mix
        col = col * np.array([1.12, 1.16, 1.07], dtype=np.float32)[None, None, :]
        col = np.clip(col, 0.0, 1.0)
    col = np.nan_to_num(col, nan=0.5, posinf=1.0, neginf=0.0).astype("float32")

    # Strata already carries a lot of topographic detail. Using Maquette's
    # per-face export path here split every edge and made the terrain read
    # laminated/Minecraft-ish. Keep shared vertices and write smooth
    # point-domain colors instead.
    obj = mesh["object"]
    data = obj.data
    rgba = np.empty((len(data.vertices), 4), dtype=np.float32)
    rgba[:, 3] = 1.0
    if len(data.vertices) == col.shape[0] * col.shape[1]:
        rgba[:, :3] = col.reshape(-1, 3).astype("float32")
    else:
        half = float(size)
        verts_flat = np.empty(len(data.vertices) * 3, dtype=np.float32)
        data.vertices.foreach_get("co", verts_flat)
        verts_xy = verts_flat.reshape(len(data.vertices), 3)[:, :2]
        sx = np.clip((verts_xy[:, 0] + half) / (2.0 * half) * (col.shape[1] - 1), 0, col.shape[1] - 1)
        sy = np.clip((verts_xy[:, 1] + half) / (2.0 * half) * (col.shape[0] - 1), 0, col.shape[0] - 1)
        rgba[:, :3] = col[np.round(sy).astype(np.int32), np.round(sx).astype(np.int32)]
    color_attr = data.color_attributes.get("Col")
    if color_attr is None:
        color_attr = data.color_attributes.new(name="Col", type="FLOAT_COLOR", domain="POINT")
    color_attr.data.foreach_set("color", rgba.flatten())
    if color_attr is not None:
        data.color_attributes.active_color = color_attr


def _paint_vertex_path_tint(
    obj: Any,
    road_pairs: list[Any],
    *,
    palette_name: str,
    size: float,
    width: float,
    hero_pads: list[HeroGroundPad] | None = None,
) -> None:
    if not road_pairs and not hero_pads:
        return
    import numpy as np

    from infinigen.maquette.runtime.eroded_terrain import (
        _palette_linear,
        _resolve_palette,
    )

    data = getattr(obj, "data", None)
    if data is None:
        return
    col_attr = data.color_attributes.get("Col")
    if col_attr is None or len(data.vertices) == 0:
        return

    verts = np.empty(len(data.vertices) * 3, dtype=np.float32)
    data.vertices.foreach_get("co", verts)
    xyz = verts.reshape(len(data.vertices), 3)
    xy = xyz[:, :2]
    px = xy[:, 0]
    py = xy[:, 1]
    weight = np.zeros(len(data.vertices), dtype=np.float32)
    normals = np.empty(len(data.vertices) * 3, dtype=np.float32)
    try:
        data.vertices.foreach_get("normal", normals)
        normals = normals.reshape(len(data.vertices), 3)
        normal_z = np.maximum(np.abs(normals[:, 2]), 0.08)
        slope_estimate = np.hypot(normals[:, 0], normals[:, 1]) / normal_z
    except Exception:
        slope_estimate = np.zeros(len(data.vertices), dtype=np.float32)
    prompt_lower = (os.environ.get("SONGE_MAQUETTE_USER_PROMPT", "") or "").lower()
    mountain_cautious_paths = any(
        token in prompt_lower
        for token in ("alpine", "mountain", "caldera", "volcanic", "crater", "cliff", "canyon")
    )

    def road_points(item: Any) -> tuple[str, str, list[Any], float]:
        if isinstance(item, RoadPath):
            return item.name, item.role, list(item.points), max(float(item.width), 0.5)
        if hasattr(item, "points") and hasattr(item, "width"):
            return (
                str(getattr(item, "name", "road")),
                str(getattr(item, "role", "road")),
                list(item.points),
                max(float(item.width), 0.5),
            )
        try:
            start, end = item
            return (
                f"{getattr(start, 'name', 'road')}_to_{getattr(end, 'name', 'road')}",
                "road",
                [start, end],
                float(width),
            )
        except Exception:
            return "road", "road", [], float(width)

    for path_index, item in enumerate(road_pairs or []):
        _name, role, points, path_width = road_points(item)
        if len(points) < 2:
            continue
        role_lower = str(role or "").lower()
        visual_strength = 0.46 if "edge_path" in role_lower else 1.0
        if "steep_suppressed" in role_lower:
            visual_strength *= 0.22
            path_width *= 0.42
        elif "mountain_cautious" in role_lower:
            visual_strength *= 0.64
            path_width *= 0.72
        if "edge_path" in role_lower:
            path_width *= 0.62
            fade_lo, fade_hi = (0.055, 0.145) if mountain_cautious_paths else (0.085, 0.20)
        elif mountain_cautious_paths:
            fade_lo, fade_hi = (0.080, 0.195)
        else:
            fade_lo, fade_hi = (0.135, 0.300)
        # Roads/paths are dirt/stone tints, not excavated mesh. Do not paint
        # them across cliff and mountain faces; keep them strongest on flat
        # passes and fade them out as the terrain becomes too steep.
        role_slope_fade = (1.0 - _smoothstep(fade_lo, fade_hi, slope_estimate)).astype(np.float32)
        if mountain_cautious_paths:
            z = xyz[:, 2]
            z_lo = float(np.quantile(z, 0.62))
            z_hi = float(np.quantile(z, 0.90))
            # On mountain/caldera/canyon scenes, dirt tracks should not
            # paint across the high faces. Plateaus still keep faint paths
            # if they are flat; high+steep vertices disappear almost fully.
            high_fade = (1.0 - _smoothstep(z_lo, z_hi, z)).astype(np.float32)
            role_slope_fade *= np.clip(0.38 + high_fade * 0.62, 0.0, 1.0)
        path_weight = np.zeros(len(data.vertices), dtype=np.float32)
        for start, end in zip(points, points[1:], strict=False):
            ax, ay = float(start.x), float(start.y)
            bx, by = float(end.x), float(end.y)
            abx = bx - ax
            aby = by - ay
            denom = max(abx * abx + aby * aby, 1e-6)
            t = np.clip(((px - ax) * abx + (py - ay) * aby) / denom, 0.0, 1.0)
            cx = ax + abx * t
            cy = ay + aby * t
            dist = np.hypot(px - cx, py - cy)
            wavering_width = path_width * (
                1.0
                + 0.11 * np.sin(px * 0.052 + py * 0.019 + path_index * 1.73)
                + 0.07 * np.sin(px * 0.017 - py * 0.061 + path_index * 2.41)
            )
            wavering_width = np.clip(wavering_width, path_width * 0.74, path_width * 1.32)
            t = np.clip((dist - wavering_width) / np.maximum(wavering_width * 0.55, 1e-4), 0.0, 1.0)
            w = (1.0 - (t * t * (3.0 - 2.0 * t))).astype(np.float32)
            path_weight = np.maximum(path_weight, w)
        path_weight *= role_slope_fade
        weight = np.maximum(weight, path_weight * visual_strength)

    # Split pads into "plaza" (market square — gets a distinct flagstone
    # tint) and "other" (house clusters, tower pads — share the path
    # color). This is the v5 fix for "plaza is indistinguishable from
    # random dirt".
    plaza_weight = np.zeros(len(data.vertices), dtype=np.float32)
    for pad_index, pad in enumerate(hero_pads or []):
        dx = px - float(pad.x)
        dy = py - float(pad.y)
        c = math.cos(-float(pad.angle))
        s = math.sin(-float(pad.angle))
        lx = dx * c - dy * s
        ly = dx * s + dy * c
        radius_x = max(float(pad.radius_x), 0.5)
        radius_y = max(float(pad.radius_y), 0.5)
        nd = np.hypot(lx / radius_x, ly / radius_y)
        angle = np.arctan2(ly / radius_y, lx / radius_x)
        edge = 1.0 + float(pad.irregularity) * (
            0.55 * np.sin(angle * 3.0 + pad_index * 1.7)
            + 0.35 * np.sin(angle * 5.0 - pad_index * 0.9)
            + 0.25 * np.sin((px + py) * 0.025 + pad_index * 2.3)
        )
        edge = np.clip(edge, 0.76, 1.28)
        pad_dist = nd / edge
        pad_weight = (1.0 - _smoothstep(0.72, 1.14, pad_dist)).astype(np.float32)
        pad_weight = np.clip(pad_weight, 0.0, 1.0)
        if pad.role in {"market_pad", "plaza_pad"}:
            # Market pad fills the plaza_weight buffer; we'll paint it
            # with a flagstone-leaning color AFTER the road tint, so the
            # plaza reads as its own ground type.
            plaza_weight = np.maximum(plaza_weight, pad_weight * 1.08)
        else:
            pad_slope_fade = (1.0 - _smoothstep(0.13, 0.31, slope_estimate)).astype(np.float32)
            pad_weight *= pad_slope_fade
            weight = np.maximum(weight, pad_weight)

    if float(np.max(weight)) <= 1e-4 and float(np.max(plaza_weight)) <= 1e-4:
        return

    palette = _resolve_palette(None, palette_name)
    shore = np.array(_palette_linear("shore", palette), dtype=np.float32)
    meadow = np.array(_palette_linear("meadow", palette), dtype=np.float32)
    stone = np.array(_palette_linear("stone", palette), dtype=np.float32)
    if palette_name == "temperate":
        path_rgb = shore * 0.78 + stone * 0.14 + meadow * 0.08
    else:
        path_rgb = shore * 0.86 + stone * 0.14
    # Plaza is a stonier, slightly cooler tone than the warm dirt path —
    # readable as a flagstone-style market square.
    plaza_rgb = np.clip(stone * 0.62 + shore * 0.22 + np.array([0.05, 0.04, 0.02], dtype=np.float32)[:stone.shape[0]], 0.0, 1.0)

    rgba = np.empty(len(col_attr.data) * 4, dtype=np.float32)
    col_attr.data.foreach_get("color", rgba)
    rgba = rgba.reshape(len(col_attr.data), 4)
    if len(rgba) != len(weight):
        return
    # First the road/path tint.
    if float(np.max(weight)) > 1e-4:
        blend = (weight * 0.74)[..., None]
        rgba[:, :3] = np.clip(rgba[:, :3] * (1.0 - blend) + path_rgb[None, :3] * blend, 0.0, 1.0)
    # Then the plaza on top so the market square has its own ground.
    if float(np.max(plaza_weight)) > 1e-4:
        plaza_blend = (plaza_weight * 0.82)[..., None]
        rgba[:, :3] = np.clip(rgba[:, :3] * (1.0 - plaza_blend) + plaza_rgb[None, :3] * plaza_blend, 0.0, 1.0)
    col_attr.data.foreach_set("color", rgba.flatten())
    data.color_attributes.active_color = col_attr


def _paint_enrichment_ground_patches(
    obj: Any,
    patches: list[dict[str, Any]],
    *,
    palette_name: str,
) -> int:
    """Tint terrain vertices for enrichment ground patches (paddocks, dirt
    tracks, orchard grass) using the existing vertex-color attribute.

    ``patches`` is a list of dicts with ``cx``, ``cy``, ``radius_x``,
    ``radius_y``, ``angle``, ``irregularity``, ``style``. Style controls the
    palette mix:

    - ``field``: meadow + amber wheat tint (cultivated paddock)
    - ``track``: shore + stone (dirt road, slightly warmer than the road tint)
    - ``orchard``: meadow shifted toward darker grass
    - ``snow``: cool pale + stone (mountain snow patches)

    Returns the number of patches that actually contributed any tint
    (patches whose vertices all lie outside the mesh are silently dropped
    so they're visible in the runtime report as "no_vertex_coverage").
    """
    if not patches:
        return 0
    import numpy as np

    from infinigen.maquette.runtime.eroded_terrain import (
        _palette_linear,
        _resolve_palette,
    )

    data = getattr(obj, "data", None)
    if data is None:
        return 0
    col_attr = data.color_attributes.get("Col")
    if col_attr is None or len(data.vertices) == 0:
        return 0

    verts = np.empty(len(data.vertices) * 3, dtype=np.float32)
    data.vertices.foreach_get("co", verts)
    xy = verts.reshape(len(data.vertices), 3)[:, :2]
    px = xy[:, 0]
    py = xy[:, 1]

    rgba = np.empty(len(col_attr.data) * 4, dtype=np.float32)
    col_attr.data.foreach_get("color", rgba)
    rgba = rgba.reshape(len(col_attr.data), 4)
    if len(rgba) != len(px):
        return 0

    palette = _resolve_palette(None, palette_name)
    # _palette_linear returns either 3 or 4 floats depending on palette
    # source; coerce to 3 components for the tint math.
    def _rgb3(name: str) -> "np.ndarray":
        arr = np.asarray(_palette_linear(name, palette), dtype=np.float32)
        return arr[:3] if arr.size >= 3 else np.zeros(3, dtype=np.float32)

    shore = _rgb3("shore")
    meadow = _rgb3("meadow")
    stone = _rgb3("stone")

    # Visually-tuned tints. The colors need to read as "this is a cultivated
    # patch / dirt track / orchard / snow" against the surrounding biome,
    # not as a barely-perceptible gradient. Field patches lean toward a warm
    # wheat/amber; tracks are clearly dirt; orchard is a darker richer
    # green; snow is pale.
    style_color: dict[str, np.ndarray] = {
        "field": np.clip(
            meadow * 0.45 + shore * 0.20 + np.array([0.30, 0.24, 0.05], dtype=np.float32),
            0.0, 1.0,
        ),
        "track": np.clip(
            shore * 0.55 + stone * 0.20 + np.array([0.22, 0.16, 0.08], dtype=np.float32),
            0.0, 1.0,
        ),
        "orchard": np.clip(
            meadow * 0.60 + stone * 0.10 + np.array([-0.05, 0.10, -0.05], dtype=np.float32),
            0.0, 1.0,
        ),
        "snow": np.clip(stone * 0.20 + np.array([0.62, 0.66, 0.72], dtype=np.float32), 0.0, 1.0),
    }

    applied = 0
    for index, patch in enumerate(patches):
        cx = float(patch.get("cx", 0.0))
        cy = float(patch.get("cy", 0.0))
        radius_x = max(float(patch.get("radius_x", 1.0)), 0.5)
        radius_y = max(float(patch.get("radius_y", 1.0)), 0.5)
        angle = float(patch.get("angle", 0.0))
        irregularity = float(patch.get("irregularity", 0.2))
        style = str(patch.get("style", "field"))
        shape = str(patch.get("shape", "ellipse"))
        color = style_color.get(style, style_color["field"])

        dx = px - cx
        dy = py - cy
        c = math.cos(-angle)
        s = math.sin(-angle)
        lx = dx * c - dy * s
        ly = dx * s + dy * c
        # Distance metric: ellipse uses Euclidean in normalized coords,
        # rect uses Chebyshev (max of normalized |x|, |y|) so the edge is
        # a rectangle in the local frame.
        if shape == "rect":
            nd = np.maximum(np.abs(lx) / radius_x, np.abs(ly) / radius_y)
        else:
            nd = np.hypot(lx / radius_x, ly / radius_y)
        ang = np.arctan2(ly / radius_y, lx / radius_x)
        edge = 1.0 + irregularity * (
            0.55 * np.sin(ang * 3.0 + index * 1.7)
            + 0.32 * np.sin(ang * 5.0 - index * 0.9)
            + 0.22 * np.sin((px + py) * 0.025 + index * 2.3)
        )
        # Rects keep a tighter edge envelope so they don't bulge into
        # rounded blobs again. Ellipses keep more give for organic shapes.
        if shape == "rect":
            edge = np.clip(edge, 0.92, 1.08)
        else:
            edge = np.clip(edge, 0.78, 1.26)
        patch_distance = nd / edge
        # Rects use a tighter smoothstep so the fall-off looks like a
        # ploughed field edge rather than an airbrush.
        if shape == "rect":
            patch_weight = (1.0 - _smoothstep(0.88, 1.04, patch_distance)).astype(np.float32)
        else:
            patch_weight = (1.0 - _smoothstep(0.78, 1.10, patch_distance)).astype(np.float32)
        max_weight = float(np.max(patch_weight))
        if max_weight <= 1e-4:
            continue
        # Read-tuned blend: paddocks need to show clearly from a
        # 3/4-perspective camera, so we lean toward the tint while keeping
        # enough of the underlying biome for terrain detail to survive.
        style_blend = {"field": 0.78, "track": 0.85, "orchard": 0.70, "snow": 0.82}
        blend_strength = style_blend.get(style, 0.74)
        blend = (patch_weight * blend_strength)[..., None]
        rgba[:, :3] = np.clip(rgba[:, :3] * (1.0 - blend) + color[None, :] * blend, 0.0, 1.0)
        applied += 1

    col_attr.data.foreach_set("color", rgba.flatten())
    data.color_attributes.active_color = col_attr
    return applied


def _build_water_from_strata(strata_dir: Path, *, size: float, thickness: float = 0.4) -> list[Any]:
    import numpy as np

    water_path = strata_dir / "strata_water_surface.npy"
    if not water_path.is_file():
        return []
    water = np.load(water_path).astype("float32")
    finite = np.isfinite(water)
    if int(finite.sum()) < 4:
        return []

    components: list[tuple[int, Any]] = []
    try:
        from scipy.ndimage import label

        labels, count = label(finite.astype("int32"))
        for idx in range(1, int(count) + 1):
            comp = labels == idx
            if int(comp.sum()) >= 4:
                components.append((idx, comp))
    except Exception:  # noqa: BLE001
        components.append((1, finite))

    out = []
    water_mat = _get_or_create_strata_water_material()
    for idx, mask in components:
        z = float(np.nanmedian(water[mask])) + 0.04
        obj = _build_flat_water_surface(
            f"StrataWater_{idx:02d}",
            mask,
            size=float(size),
            water_level=z,
        )
        for poly in obj.data.polygons:
            poly.use_smooth = True
        obj.data.materials.append(water_mat)
        out.append(obj)
    return out


def _object_budget_for_size(size: float, *, palette_name: str = "") -> dict[str, int | float | str]:
    full_side = float(size) * 2.0
    if full_side <= 170.0:
        map_size = "small"
        minimum_objects = 160
        target_objects = 240
        max_objects = 450
    elif full_side <= 240.0:
        map_size = "medium"
        minimum_objects = 320
        target_objects = 480
        max_objects = 800
    elif full_side <= 320.0:
        map_size = "large"
        minimum_objects = 560
        target_objects = 800
        max_objects = 1300
    else:
        map_size = "xl"
        minimum_objects = 900
        target_objects = 1250
        max_objects = 2000

    density_style = "balanced"
    if palette_name in {"desert", "volcanic", "tundra"}:
        # Sparse biomes should read through silhouettes and clustered
        # landmarks, not uniform confetti over the whole heightfield.
        density_style = "sparse_clustered"
        sparse_targets = {
            "small": (70, 120, 260),
            "medium": (120, 210, 420),
            "large": (180, 320, 650),
            "xl": (240, 420, 850),
        }
        minimum_objects, target_objects, max_objects = sparse_targets[map_size]
    return {
        "map_size": map_size,
        "terrain_full_side_bu": round(full_side, 3),
        "minimum_objects": minimum_objects,
        "minimum_visible_objects": minimum_objects,
        "target_objects": target_objects,
        "max_objects": max_objects,
        "density_style": density_style,
        "density_contract": "tiny/pebble/small-rock details do not satisfy the minimum by themselves",
    }


def _make_object_budget_writer(budget: dict[str, Any]):
    def write_object_budget_report(
        *,
        planned: dict[str, int] | list[dict[str, Any]] | None = None,
        spawned: dict[str, int] | list[dict[str, Any]] | None = None,
        omitted_due_to_limit: list[dict[str, Any]] | None = None,
        notes: list[str] | None = None,
    ) -> Path | None:
        out_dir = os.environ.get("MAQUETTE_OUT_DIR")
        if not out_dir:
            return None
        payload = {
            "budget": budget,
            "planned": planned or {},
            "spawned": spawned or {},
            "omitted_due_to_limit": omitted_due_to_limit or [],
            "notes": notes or [],
        }
        path = Path(out_dir) / "strata_object_budget.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    return write_object_budget_report


_DETAIL_KIND_HINTS = (
    "small",
    "tiny",
    "micro",
    "pebble",
    "chip",
    "grain",
)


def _visible_count(spawned_counts: dict[str, int] | None) -> int:
    if not isinstance(spawned_counts, dict):
        return 0
    total = 0
    for key, value in spawned_counts.items():
        kind = str(key).lower()
        try:
            count = int(value)
        except Exception:
            continue
        if any(hint in kind for hint in _DETAIL_KIND_HINTS):
            continue
        total += max(count, 0)
    return total


def _total_count(spawned_counts: dict[str, int] | None) -> int:
    if not isinstance(spawned_counts, dict):
        return 0
    total = 0
    for value in spawned_counts.values():
        try:
            total += max(int(value), 0)
        except Exception:
            pass
    return total


def _bump_count(counts: dict[str, int] | None, key: str, amount: int = 1) -> None:
    if not isinstance(counts, dict):
        return
    counts[key] = int(counts.get(key, 0)) + int(amount)


_SETTLEMENT_CUES = (
    "house",
    "village",
    "town",
    "market",
    "stall",
    "watchtower",
    "tower",
    "castle",
    "cart",
    "wagon",
    "barrel",
    "crate",
    "fence",
    "well",
    "lantern",
    "sign",
    "building",
    "farm",
)


_RUIN_CUES = (
    "ruin",
    "collapsed",
    "broken",
    "ancient",
    "temple",
    "archaeolog",
    "tomb",
)


def _count_keys(*counts: dict[str, int] | None) -> set[str]:
    return {
        str(key).lower()
        for mapping in counts
        if isinstance(mapping, dict)
        for key in mapping
    }


def _has_any_cue(keys: set[str], cues: tuple[str, ...]) -> bool:
    return any(cue in key for key in keys for cue in cues)


def _hide_template_object(obj: Any) -> None:
    """Keep prototype objects out of rendered scenes.

    Some factory assets are created once and then linked-copied many times.
    If the template remains at its construction location, it can show up as
    an unexplained stack of props around world origin. Hide it and move it
    well below the terrain as a second line of defense.
    """
    stack = [obj]
    seen: set[int] = set()
    while stack:
        current = stack.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        try:
            current.hide_render = True
            current.hide_viewport = True
            current.hide_set(True)
            current.location = (0.0, 0.0, -10000.0)
        except Exception:
            pass
        try:
            for collection in list(current.users_collection):
                collection.objects.unlink(current)
        except Exception:
            pass
        try:
            stack.extend(list(current.children))
        except Exception:
            pass


def _copy_template_object(proto: Any, *, name: str, x: float, y: float, z: float,
                          scale: tuple[float, float, float], rot_z: float):
    import bpy

    obj = proto.copy()
    obj.data = proto.data
    obj.animation_data_clear()
    obj.name = name
    obj.location = (float(x), float(y), float(z))
    obj.rotation_euler = (
        random.uniform(-0.04, 0.04),
        random.uniform(-0.04, 0.04),
        float(rot_z),
    )
    obj.scale = scale
    obj.hide_render = False
    obj.hide_viewport = False
    bpy.context.collection.objects.link(obj)
    for child in list(getattr(proto, "children", []) or []):
        try:
            child_copy = child.copy()
            if getattr(child, "data", None) is not None:
                child_copy.data = child.data.copy()
            child_copy.name = f"{name}_{child.name}"
            child_copy.parent = obj
            child_copy.location = child.location
            child_copy.rotation_euler = child.rotation_euler
            child_copy.scale = child.scale
            child_copy.hide_render = False
            child_copy.hide_viewport = False
            bpy.context.collection.objects.link(child_copy)
        except Exception:
            continue
    return obj


_CASTLE_WFC_API_CACHE: dict[str, Any] | None = None
_CASTLE_WFC_MESH_CACHE: Any | None = None


def _load_castle_wfc_api() -> dict[str, Any]:
    """Load the pure Songe castle WFC solver if available in Blender Python."""

    global _CASTLE_WFC_API_CACHE
    if _CASTLE_WFC_API_CACHE is not None:
        return _CASTLE_WFC_API_CACHE
    try:
        from app.pipeline.strata.castle_wfc import build_castle_wfc_layout
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"castle_wfc_api_unavailable:{exc}") from exc
    _CASTLE_WFC_API_CACHE = {
        "build_castle_wfc_layout": build_castle_wfc_layout,
    }
    return _CASTLE_WFC_API_CACHE


def _load_castle_wfc_meshes() -> Any:
    """Load the archived v4 authored castle mesh kit.

    The v4 kit lives in songe-core/experiments because it is the original
    standalone Blender prototype. We load it dynamically so Maquette can reuse
    the authored tower/wall/keep meshes without importing a package named
    "experiments" into production code.
    """

    global _CASTLE_WFC_MESH_CACHE
    if _CASTLE_WFC_MESH_CACHE is not None:
        return _CASTLE_WFC_MESH_CACHE
    try:
        import importlib.util
        import sys

        import app

        songe_core_root = Path(app.__file__).resolve().parents[1]
        mesh_path = songe_core_root / "experiments" / "wfc_castle_demo" / "build_castles_v4.py"
        if not mesh_path.is_file():
            raise FileNotFoundError(mesh_path)
        spec = importlib.util.spec_from_file_location("songe_castle_wfc_v4_meshes_runtime", mesh_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot create import spec for {mesh_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"castle_wfc_meshes_unavailable:{exc}") from exc
    _CASTLE_WFC_MESH_CACHE = module
    return module


def _get_or_create_ruin_materials() -> list[Any]:
    import bpy

    specs = [
        ("strata_ruin_sandstone", (0.63, 0.49, 0.31, 1.0)),
        ("strata_ruin_sandstone_pale", (0.76, 0.65, 0.46, 1.0)),
        ("strata_ruin_shadow", (0.36, 0.29, 0.22, 1.0)),
    ]
    out = []
    for name, color in specs:
        mat = bpy.data.materials.get(name)
        if mat is None:
            mat = bpy.data.materials.new(name)
        mat.diffuse_color = color
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf is not None:
            _set_node_input(bsdf, ("Base Color",), color)
            _set_node_input(bsdf, ("Roughness",), 0.82)
        out.append(mat)
    return out


def _add_oriented_box(
    verts: list[tuple[float, float, float]],
    faces: list[tuple[int, int, int, int]],
    material_indices: list[int],
    *,
    center: tuple[float, float, float],
    size_xyz: tuple[float, float, float],
    rot_z: float,
    slot: int = 0,
) -> None:
    cx, cy, cz = center
    sx, sy, sz = size_xyz
    hx, hy, hz = sx * 0.5, sy * 0.5, sz * 0.5
    ca, sa = math.cos(rot_z), math.sin(rot_z)
    local = [
        (-hx, -hy, -hz), (hx, -hy, -hz), (hx, hy, -hz), (-hx, hy, -hz),
        (-hx, -hy, hz), (hx, -hy, hz), (hx, hy, hz), (-hx, hy, hz),
    ]
    base = len(verts)
    for lx, ly, lz in local:
        x = cx + lx * ca - ly * sa
        y = cy + lx * sa + ly * ca
        verts.append((x, y, cz + lz))
    faces.extend([
        (base + 0, base + 1, base + 5, base + 4),
        (base + 1, base + 2, base + 6, base + 5),
        (base + 2, base + 3, base + 7, base + 6),
        (base + 3, base + 0, base + 4, base + 7),
        (base + 4, base + 5, base + 6, base + 7),
        (base + 0, base + 3, base + 2, base + 1),
    ])
    material_indices.extend([slot] * 6)


def _make_ruin_fragment_template(kind: str, *, seed: int) -> Any:
    import bpy

    rng = random.Random(int(seed))
    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    mat_indices: list[int] = []
    if kind == "ruin_wall":
        length = rng.uniform(2.8, 5.2)
        blocks = max(3, int(length / 0.8))
        for idx in range(blocks):
            if rng.random() < 0.18:
                continue
            bx = -length * 0.5 + (idx + 0.5) * (length / blocks)
            h = rng.uniform(0.45, 1.25)
            _add_oriented_box(
                verts, faces, mat_indices,
                center=(bx, rng.uniform(-0.06, 0.06), h * 0.5),
                size_xyz=(length / blocks * rng.uniform(0.82, 1.05), rng.uniform(0.42, 0.70), h),
                rot_z=rng.uniform(-0.05, 0.05),
                slot=rng.choice([0, 0, 1, 2]),
            )
    else:
        if rng.random() < 0.55:
            _add_oriented_box(
                verts, faces, mat_indices,
                center=(0.0, 0.0, rng.uniform(0.16, 0.32)),
                size_xyz=(rng.uniform(1.3, 2.8), rng.uniform(0.38, 0.75), rng.uniform(0.25, 0.55)),
                rot_z=rng.uniform(-0.25, 0.25),
                slot=rng.choice([0, 1, 2]),
            )
        else:
            height = rng.uniform(1.1, 2.2)
            for layer in range(rng.randint(2, 4)):
                z = (layer + 0.5) * height / 4.0
                scale = 1.0 - layer * rng.uniform(0.08, 0.14)
                _add_oriented_box(
                    verts, faces, mat_indices,
                    center=(rng.uniform(-0.04, 0.04), rng.uniform(-0.04, 0.04), z),
                    size_xyz=(rng.uniform(0.36, 0.62) * scale, rng.uniform(0.36, 0.62) * scale, height / 4.0),
                    rot_z=rng.uniform(-0.12, 0.12),
                    slot=rng.choice([0, 0, 1, 2]),
                )

    mesh = bpy.data.meshes.new(f"StrataRuinFragment_{kind}_{seed}_Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(f"StrataRuinFragment_{kind}_{seed}", mesh)
    for mat in _get_or_create_ruin_materials():
        obj.data.materials.append(mat)
    for poly, slot in zip(obj.data.polygons, mat_indices, strict=False):
        poly.material_index = slot
        poly.use_smooth = False
    bpy.context.collection.objects.link(obj)
    return obj


def _build_ruin_cluster(
    *,
    height_at,
    x: float,
    y: float,
    radius: float,
    pieces: int,
    seed: int,
    name: str = "StrataRuinCluster",
) -> tuple[Any, int]:
    import bpy

    rng = random.Random(int(seed))
    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    mat_indices: list[int] = []
    count = 0
    base_rot = rng.uniform(0.0, math.tau)
    footprint_r = max(float(radius) * 1.28, 6.4)
    length = footprint_r * rng.uniform(1.65, 2.15)
    width = footprint_r * rng.uniform(1.05, 1.45)
    wall_thick = rng.uniform(0.42, 0.68)

    def world(lx: float, ly: float) -> tuple[float, float]:
        ca, sa = math.cos(base_rot), math.sin(base_rot)
        return (
            float(x) + lx * ca - ly * sa,
            float(y) + lx * sa + ly * ca,
        )

    def box(
        lx: float,
        ly: float,
        *,
        sx: float,
        sy: float,
        sz: float,
        rz: float = 0.0,
        z_lift: float = 0.0,
        bury: float = 0.0,
        slot: int = 0,
    ) -> None:
        nonlocal count
        wx, wy = world(lx, ly)
        ground = float(height_at(wx, wy))
        _add_oriented_box(
            verts, faces, mat_indices,
            center=(wx, wy, ground + sz * 0.5 + z_lift - bury),
            size_xyz=(sx, sy, sz),
            rot_z=base_rot + rz,
            slot=slot,
        )
        count += 1

    # A partially sand-buried architectural footprint makes the ruin read as
    # human-made from a distance. Keep it low so it does not become a house.
    box(
        0.0, 0.0,
        sx=length * rng.uniform(0.78, 0.92),
        sy=width * rng.uniform(0.72, 0.88),
        sz=rng.uniform(0.16, 0.28),
        bury=rng.uniform(0.10, 0.22),
        slot=1,
    )

    # Broken perimeter walls: long enough to describe a footprint, but with
    # deliberate gaps and varied heights so it reads weathered.
    sides = [
        ("north", 0.0, width * 0.5, 0.0, length),
        ("south", 0.0, -width * 0.5, 0.0, length),
        ("east", length * 0.5, 0.0, math.pi * 0.5, width),
        ("west", -length * 0.5, 0.0, math.pi * 0.5, width),
    ]
    rng.shuffle(sides)
    for side_index, (_, cx_l, cy_l, rz, side_len) in enumerate(sides):
        n_seg = 2 if side_len < 10.0 else 3
        for seg in range(n_seg):
            if side_index > 1 and seg == n_seg - 1 and rng.random() < 0.55:
                continue
            offset = (-0.34 + 0.68 * (seg / max(n_seg - 1, 1))) * side_len
            gap_jitter = rng.uniform(-0.08, 0.08) * side_len
            lx = cx_l + (math.cos(rz) * (offset + gap_jitter))
            ly = cy_l + (math.sin(rz) * (offset + gap_jitter))
            seg_len = side_len / n_seg * rng.uniform(0.58, 0.86)
            wall_h = rng.uniform(0.75, 1.75)
            if rng.random() < 0.18:
                wall_h *= rng.uniform(1.15, 1.45)
            box(
                lx, ly,
                sx=seg_len,
                sy=wall_thick,
                sz=wall_h,
                rz=rz + rng.uniform(-0.08, 0.08),
                bury=rng.uniform(0.14, 0.42),
                slot=rng.choice([0, 0, 1, 2]),
            )

    # Column stubs placed near corners/interior axes. These give the ruin a
    # stronger silhouette than random tombstone-shaped markers.
    column_spots = [
        (-length * 0.28, -width * 0.22),
        (-length * 0.28, width * 0.22),
        (length * 0.20, -width * 0.18),
        (length * 0.22, width * 0.18),
        (0.0, width * 0.04),
    ]
    rng.shuffle(column_spots)
    for idx, (lx, ly) in enumerate(column_spots[:max(3, min(5, pieces // 7))]):
        levels = rng.randint(2, 4 if idx < 2 else 3)
        block_h = rng.uniform(0.44, 0.68)
        base_s = rng.uniform(0.55, 0.82)
        lean_x = rng.uniform(-0.07, 0.07)
        lean_y = rng.uniform(-0.07, 0.07)
        for level in range(levels):
            scale = 1.0 - level * rng.uniform(0.04, 0.09)
            box(
                lx + lean_x * level,
                ly + lean_y * level,
                sx=base_s * scale,
                sy=base_s * rng.uniform(0.82, 1.06) * scale,
                sz=block_h,
                rz=rng.uniform(-0.12, 0.12),
                z_lift=block_h * level,
                bury=0.10 if level == 0 else 0.0,
                slot=rng.choice([0, 0, 1, 2]),
            )

    # A few toppled slabs and lintels inside the footprint. Keep them aligned
    # with the ruin grammar instead of radial/random scatter.
    for _ in range(max(3, min(6, pieces // 6))):
        lx = rng.uniform(-length * 0.34, length * 0.34)
        ly = rng.uniform(-width * 0.28, width * 0.28)
        box(
            lx, ly,
            sx=rng.uniform(1.6, 3.4),
            sy=rng.uniform(0.36, 0.72),
            sz=rng.uniform(0.18, 0.34),
            rz=rng.choice([0.0, math.pi * 0.5]) + rng.uniform(-0.32, 0.32),
            bury=rng.uniform(0.00, 0.10),
            slot=rng.choice([0, 1, 2]),
        )

    # Controlled rubble, biased around the wall edges. This provides decay
    # without reverting the whole cluster to visual noise.
    rubble_count = max(5, min(12, int(pieces * 0.30)))
    for _ in range(rubble_count):
        side = rng.choice(sides)
        _, cx_l, cy_l, rz, side_len = side
        lx = cx_l + math.cos(rz) * rng.uniform(-side_len * 0.45, side_len * 0.45)
        ly = cy_l + math.sin(rz) * rng.uniform(-side_len * 0.45, side_len * 0.45)
        lx += rng.uniform(-0.8, 0.8)
        ly += rng.uniform(-0.8, 0.8)
        s = rng.uniform(0.22, 0.58)
        box(
            lx, ly,
            sx=s * rng.uniform(1.1, 2.0),
            sy=s * rng.uniform(0.75, 1.45),
            sz=s * rng.uniform(0.45, 0.95),
            rz=rng.uniform(0.0, math.tau),
            bury=rng.uniform(0.05, 0.18),
            slot=rng.choice([0, 0, 1, 2]),
        )

    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    for mat in _get_or_create_ruin_materials():
        obj.data.materials.append(mat)
    for poly, slot in zip(obj.data.polygons, mat_indices, strict=False):
        poly.material_index = slot
        poly.use_smooth = False
    bpy.context.collection.objects.link(obj)
    return obj, count


def _make_visual_density_filler(
    *,
    height_at,
    sample_role,
    find_placeable_points,
    primary_water: WaterAnchor | None,
    size: float,
    seed: int,
    palette_name: str,
    budget: dict[str, Any],
    regions: TerrainRegions,
    reserved_footprints: list[tuple[float, float, float, str]] | None = None,
    settlement_layout_factory=None,
):
    def fill_visual_density(
        *,
        spawned_counts: dict[str, int] | None = None,
        planned_counts: dict[str, int] | None = None,
        omitted_due_to_limit: list[dict[str, Any]] | None = None,
        minimum_visible: int | None = None,
        target_visible: int | None = None,
        max_objects: int | None = None,
        intent: str = "fill",
    ) -> dict[str, Any]:
        """Top up broad scene density with readable linked low-poly props.

        The LLM still owns hero composition. This helper only fills the
        generic scatter layer using Maquette's native factories, so a scene
        cannot satisfy "dense" with hundreds of invisible pebble-sized rocks.

        When ``intent="minimal"`` the helper becomes a no-op so strict
        prompts (e.g. "only what I asked for") can satisfy the build-script
        linter without adding unwanted filler. The returned report still
        records the explicit opt-out so the runner can audit it.
        """
        if intent == "minimal":
            return {
                "intent": "minimal",
                "spawned": {},
                "minimum_visible": 0,
                "target_visible": 0,
                "skipped_reason": "strict_prompt_minimal_intent",
            }
        from infinigen.maquette.factories.boulder import LowPolyBoulderFactory
        from infinigen.maquette.factories.native.barrel import LowPolyBarrelFactory
        from infinigen.maquette.factories.native.building import LowPolyHouseFactory
        from infinigen.maquette.factories.native.cactus import LowPolyCactusFactory
        from infinigen.maquette.factories.native.crate import LowPolyCrateFactory
        from infinigen.maquette.factories.native.fence import LowPolyFenceFactory
        from infinigen.maquette.factories.native.haystack import LowPolyHaystackFactory
        from infinigen.maquette.factories.native.lantern_post import LowPolyLanternPostFactory
        from infinigen.maquette.factories.native.palm_tree import LowPolyPalmTreeFactory
        from infinigen.maquette.factories.native.signage import LowPolySignageFactory
        from infinigen.maquette.factories.native.tree import NativeLowPolyTreeFactory
        from infinigen.maquette.factories.native.tumbleweed import LowPolyTumbleweedFactory

        rng = random.Random(int(seed) + 73129)
        artificial_keys = _count_keys(planned_counts, spawned_counts)
        prompt_text = os.environ.get("SONGE_MAQUETTE_USER_PROMPT", "").lower()
        if prompt_text:
            prompt_keys = {
                cue
                for cue in (*_SETTLEMENT_CUES, *_RUIN_CUES)
                if cue in prompt_text
            }
            artificial_keys.update(prompt_keys)
        primary_wfc_already_used = any(
            str(key).startswith("wfc_primary")
            for key in artificial_keys
        )
        settlement_scene = _has_any_cue(artificial_keys, _SETTLEMENT_CUES)
        ruin_scene = _has_any_cue(artificial_keys, _RUIN_CUES)
        min_visible = int(
            minimum_visible
            if minimum_visible is not None
            else budget.get("minimum_visible_objects", budget.get("minimum_objects", 0))
        )
        target = int(
            target_visible
            if target_visible is not None
            else max(min_visible, int(budget.get("target_objects", min_visible)))
        )
        cap = int(max_objects if max_objects is not None else budget.get("max_objects", target))
        existing_visible = _visible_count(spawned_counts)
        existing_total = _total_count(spawned_counts)
        if settlement_scene and not ruin_scene:
            # Settlement quality is hurt by blindly satisfying the XL terrain
            # floor with generic filler. A town reads better with semantic
            # clusters + open meadow than with 900+ tiny props.
            settlement_floor = 660 if budget.get("map_size") == "xl" else 440
            min_visible = min(min_visible, settlement_floor)
            budget["minimum_visible_objects"] = int(min_visible)
            budget["minimum_objects"] = min(int(budget.get("minimum_objects", min_visible)), int(min_visible))
            # A normal settlement should be completed by authored buildings
            # and local props, not by hundreds of generic trees/boulders. If
            # the generated script under-authored the settlement, this helper
            # upgrades itself from "support scatter" to a settlement backstop
            # and still honours the terrain-scaled minimum.
            settlement_target = max(existing_visible + 300, min_visible)
            if budget.get("map_size") == "xl":
                settlement_target = max(existing_visible + 430, min_visible)
            target = min(target, settlement_target)
        desired = max(min_visible, min(target, cap))
        needed = max(0, min(desired - existing_visible, cap - existing_total))
        report = {
            "requested_visible": int(desired),
            "existing_visible": int(existing_visible),
            "spawned": {},
            "skipped": [],
            "scatter_zones": {},
            "placements": [],
            "density_mode": (
                "settlement_support" if settlement_scene and not ruin_scene
                else "ruin_support" if ruin_scene
                else "natural_support"
            ),
            "primary_wfc_already_used": bool(primary_wfc_already_used),
            "density_suppressed_by_enrichment": 0,
            "random_haystack_outside_farmland_count": 0,
            "tree_on_field_or_road_rejects": 0,
            # v5: friendlier aliases the user-facing report uses.
            "density_suppressed_by_zone": 0,
            "haystack_outside_farmland_count": 0,
            "tree_on_road_or_field_rejects": 0,
            "boulder_in_town_rejects": 0,
        }

        # Load enrichment ground patches and feature anchors so we can
        # avoid scattering noise on top of paddocks, tracks, orchards or
        # other authored zones.
        enrichment_zones: list[dict[str, float | str]] = []
        farmland_zones: list[tuple[float, float, float]] = []  # (cx, cy, radius) for haystack steering
        try:
            out_dir_env = os.environ.get("MAQUETTE_OUT_DIR")
            if out_dir_env:
                report_path = Path(out_dir_env) / "strata_enrichment_runtime_report.json"
                if report_path.is_file():
                    er_payload = json.loads(report_path.read_text(encoding="utf-8"))
                    # The runtime report tracks features and patches but
                    # the patches themselves live alongside in the
                    # enrichment plan + the per-feature placement. Load
                    # whatever we can attribute from the runtime side.
                    # Anchors:
                    for feat in er_payload.get("features", []) or []:
                        anchor = feat.get("anchor")
                        if not anchor:
                            continue
                        kind = str(feat.get("kind") or "")
                        radius = max(8.0, math.sqrt(max(float(feat.get("footprint_area") or 0.0), 1.0) / math.pi))
                        if kind == "farmland_belt":
                            farmland_zones.append((float(anchor[0]), float(anchor[1]), float(radius) * 1.4))
                        enrichment_zones.append({
                            "kind": kind,
                            "cx": float(anchor[0]),
                            "cy": float(anchor[1]),
                            "radius": float(radius),
                        })
        except Exception:  # noqa: BLE001
            pass

        def _inside_enrichment_zone(x: float, y: float) -> str | None:
            """Return the enrichment kind whose anchor radius contains (x, y)."""
            for zone in enrichment_zones:
                d = math.hypot(float(x) - zone["cx"], float(y) - zone["cy"])
                if d <= float(zone["radius"]):
                    return str(zone["kind"])
            return None

        def _inside_farmland(x: float, y: float) -> bool:
            for cx, cy, r in farmland_zones:
                if math.hypot(float(x) - cx, float(y) - cy) <= r:
                    return True
            return False

        # v5: settlement-core circle used by density rules. Boulders and
        # other wilderness props should never land inside the settlement
        # footprint — they break the town read.
        settlement_core: tuple[float, float, float] | None = None
        # Filled in once ``layout`` is built below.
        if needed <= 0:
            return report

        wfc_env = os.environ.get("SONGE_STRATA_WFC_VILLAGE", "").strip().lower()
        legacy_wfc_env = os.environ.get("SONGE_STRATA_WFC_SETTLEMENT_EXPERIMENT", "").strip().lower()
        village_wfc_enabled = (
            not primary_wfc_already_used
            and (
                wfc_env in {"1", "true", "yes", "on"}
                or legacy_wfc_env in {"1", "true", "yes", "on"}
            )
        )
        tile_wfc_env = os.environ.get("SONGE_STRATA_TILE_WFC", "").strip().lower()
        tile_wfc_enabled = village_wfc_enabled and tile_wfc_env in {"1", "true", "yes", "on"}
        layout: SettlementLayout | None = None
        road_pairs: list[tuple[TerrainPoint, TerrainPoint]] = []
        road_paths: list[RoadPath] = []
        hero_pads: list[HeroGroundPad] = []
        if settlement_scene and not ruin_scene and settlement_layout_factory is not None:
            try:
                # v4: don't override cluster_goal here — the
                # _settlement_district_count helper picks an
                # appropriately-spread number of districts based on the
                # actual map size. The legacy hardcoded 5/7 over-
                # populated mid-size maps and (worse) clobbered the
                # settlement layout the build.py already authored.
                layout = settlement_layout_factory(
                    kind="market_town",
                    support_points=36 if budget.get("map_size") == "xl" else 24,
                )
                road_pairs = list(layout.road_pairs)
                road_paths = list(layout.road_paths or [])
                hero_pads = list(layout.hero_pads or [])
                report["layout"] = {
                    "house_clusters": len(layout.house_clusters),
                    "roads": len(road_pairs),
                    "road_paths": len(road_paths),
                    "hero_pads": len(hero_pads),
                    "tree_zones": len(layout.tree_zones or []),
                    "outer_zones": len(layout.outer_zones or []),
                }
            except Exception as exc:  # noqa: BLE001
                report["skipped"].append({
                    "kind": "settlement_layout",
                    "reason": f"layout_failed:{exc}",
                })

        occupied: list[tuple[float, float, float, str]] = list(reserved_footprints or [])
        road_width = 6.0 if settlement_scene and not ruin_scene else 3.0

        def reserve(x: float, y: float, radius: float, label: str) -> None:
            occupied.append((float(x), float(y), max(0.05, float(radius)), str(label)))

        if layout is not None:
            reserve(layout.market.x, layout.market.y, 10.0, "market_keepout")
            if layout.tower is not None:
                reserve(layout.tower.x, layout.tower.y, 8.0, "tower_keepout")
            for cluster in layout.house_clusters:
                reserve(cluster.x, cluster.y, 4.5, "house_cluster_core")
            # Settlement core: bbox of market + all clusters, with a small
            # outward margin. Boulders/wilderness scatter that lands here
            # gets rejected as "boulder_in_town".
            xs = [layout.market.x] + [c.x for c in layout.house_clusters]
            ys = [layout.market.y] + [c.y for c in layout.house_clusters]
            cx = sum(xs) / max(len(xs), 1)
            cy = sum(ys) / max(len(ys), 1)
            radius = max(
                25.0,
                max(math.hypot(x - cx, y - cy) for x, y in zip(xs, ys)) + 8.0,
            )
            settlement_core = (cx, cy, radius)

        def distance_to_roads(x: float, y: float) -> float:
            if road_paths:
                return min(
                    _point_polyline_distance(float(x), float(y), path.points)
                    for path in road_paths
                    if len(path.points) >= 2
                )
            if not road_pairs:
                return 10**9
            return min(
                _point_segment_distance(
                    float(x), float(y),
                    start.x, start.y,
                    end.x, end.y,
                )
                for start, end in road_pairs
            )

        def near_road_center(kind: str, x: float, y: float) -> bool:
            dist = distance_to_roads(float(x), float(y))
            if dist >= 10**8:
                return False
            if kind in {"tree", "palm", "cactus", "boulder", "house", "haystack"}:
                return dist < road_width
            if kind in {"barrel", "crate", "fence", "signage", "lantern", "tumbleweed"}:
                return dist < road_width * 0.35
            return dist < road_width * 0.5

        footprint_radius = {
            "house": 4.1,
            "tree": 2.8,
            "palm": 2.8,
            "cactus": 2.0,
            "boulder": 2.3,
            "tumbleweed": 1.2,
            "barrel": 1.0,
            "crate": 1.1,
            "fence": 2.2,
            "signage": 1.4,
            "lantern": 1.0,
            "haystack": 2.8,
            "ruin_slab": 2.3,
            "ruin_wall": 2.8,
        }
        density_caps = (
            {
                "barrel": 16 if primary_wfc_already_used else 24,
                "crate": 18 if primary_wfc_already_used else 30,
                "fence": 8 if primary_wfc_already_used else 46,
                "signage": 8 if primary_wfc_already_used else 16,
                "lantern": 10 if primary_wfc_already_used else 18,
                "haystack": 16 if primary_wfc_already_used else 20,
                "boulder": 60 if primary_wfc_already_used else 68,
                "tree": 130 if primary_wfc_already_used else 180,
                "house": (
                    6 if primary_wfc_already_used
                    else 28 if tile_wfc_enabled and budget.get("map_size") == "xl"
                    else 22 if tile_wfc_enabled
                    else 18 if village_wfc_enabled
                    else 8
                ),
            }
            if settlement_scene and not ruin_scene
            else {}
        )
        zone_caps = (
            {
                "settlement_district": 44,
                "hero_support": 82,
                "road_edges": 18 if primary_wfc_already_used else 32,
                "road_edge_relaxed": 8 if primary_wfc_already_used else 18,
                "woodlots": 135,
                "woodlot_relaxed": 60,
                "meadow_trees": 120 if primary_wfc_already_used else 250,
                "meadow_tree_relaxed": 55 if primary_wfc_already_used else 120,
                "outer_clusters": 52,
                "outer_relaxed": 26,
                "wfc_house_front": 16,
                "wfc_fence": 24,
                "wfc_prop_pocket": 28,
                "wfc_yard": 22,
                "wfc_tree_pocket": 34,
                "tile_wfc_house_row": 28,
                "tile_wfc_house": 14,
                "tile_wfc_market": 42,
                "tile_wfc_wall": 44,
                "tile_wfc_prop": 36,
                "tile_wfc_garden": 28,
            }
            if settlement_scene and not ruin_scene
            else {}
        )
        if zone_caps:
            report["zone_caps"] = dict(zone_caps)

        def local_slope(x: float, y: float) -> float:
            delta = max(2.0, float(size) * 0.010)
            x0, y0 = clamp_to_world(float(x) - delta, float(y))
            x1, y1 = clamp_to_world(float(x) + delta, float(y))
            x2, y2 = clamp_to_world(float(x), float(y) - delta)
            x3, y3 = clamp_to_world(float(x), float(y) + delta)
            sx = abs(float(height_at(x1, y1)) - float(height_at(x0, y0))) / max(delta * 2.0, 1e-3)
            sy = abs(float(height_at(x3, y3)) - float(height_at(x2, y2))) / max(delta * 2.0, 1e-3)
            return math.hypot(sx, sy)

        def settlement_anchor_distance(x: float, y: float) -> float:
            if layout is None:
                return 10**9
            return layout.anchor_distance(float(x), float(y))

        def meadow_tree_score(x: float, y: float) -> float:
            phase = (int(seed) % 997) * 0.019
            return (
                math.sin(float(x) * 0.030 + phase)
                + math.sin(float(y) * 0.026 - phase * 1.31)
                + 0.65 * math.sin((float(x) + float(y)) * 0.018 + phase * 0.47)
            ) / 2.65

        def is_green_tree_ground(
            x: float,
            y: float,
            *,
            far_from_market: bool = False,
            require_cluster: bool = False,
        ) -> bool:
            if not is_dry(float(x), float(y), water_buffer=3.0):
                return False
            role = str(sample_role(float(x), float(y)) or "").lower()
            if any(cue in role for cue in ("water", "basin_floor", "shore", "flat_feature_pad", "road", "path")):
                return False
            if distance_to_roads(float(x), float(y)) < road_width * 3.0:
                return False
            if layout is not None:
                if far_from_market and math.hypot(float(x) - layout.market.x, float(y) - layout.market.y) < size * 0.22:
                    return False
                if settlement_anchor_distance(float(x), float(y)) < 13.0:
                    return False
            if local_slope(float(x), float(y)) >= 0.18:
                return False
            return (not require_cluster) or meadow_tree_score(float(x), float(y)) > -0.08

        def vegetation_allowed(kind: str, x: float, y: float, zone: str) -> bool:
            if kind not in {"tree", "palm"}:
                return True
            role = str(sample_role(float(x), float(y)) or "").lower()
            if "water" in role or "basin_floor" in role or "flat_feature_pad" in role:
                return False
            if settlement_scene and not ruin_scene:
                if kind == "palm":
                    return zone == "shore_band"
                if zone not in {"woodlots", "woodlot_relaxed", "meadow_trees", "meadow_tree_relaxed"}:
                    return False
                if any(cue in role for cue in ("detail", "shore", "road", "path")):
                    return False
                if distance_to_roads(float(x), float(y)) < road_width * 2.4:
                    return False
                if zone in {"meadow_trees", "meadow_tree_relaxed"} and not is_green_tree_ground(
                    float(x),
                    float(y),
                    far_from_market=zone == "meadow_tree_relaxed",
                    require_cluster=True,
                ):
                    return False
            return True

        def _bump_tree_reject() -> None:
            report["tree_on_field_or_road_rejects"] = int(report.get("tree_on_field_or_road_rejects", 0)) + 1
            report["tree_on_road_or_field_rejects"] = int(report.get("tree_on_road_or_field_rejects", 0)) + 1

        def _bump_zone_suppress() -> None:
            report["density_suppressed_by_enrichment"] = int(report.get("density_suppressed_by_enrichment", 0)) + 1
            report["density_suppressed_by_zone"] = int(report.get("density_suppressed_by_zone", 0)) + 1

        def can_place(kind: str, x: float, y: float, radius: float, *, zone: str = "fill") -> bool:
            if not vegetation_allowed(kind, x, y, zone):
                return False
            if near_road_center(kind, x, y):
                if kind == "tree":
                    _bump_tree_reject()
                return False
            # v5: boulders/wilderness rocks reject inside settlement core.
            if (
                kind in {"boulder"}
                and settlement_core is not None
                and math.hypot(float(x) - settlement_core[0], float(y) - settlement_core[1]) <= settlement_core[2]
            ):
                report["boulder_in_town_rejects"] = int(report.get("boulder_in_town_rejects", 0)) + 1
                _bump_zone_suppress()
                return False
            # Enrichment zone awareness — reject scatter that lands inside
            # an authored zone (orchard / track / paddock). The enrichment
            # objects already own those zones; piling random scatter on top
            # turns the composition back into noise.
            zone_kind = _inside_enrichment_zone(float(x), float(y))
            if zone_kind is not None:
                if zone_kind == "orchard":
                    # No scatter at all inside an orchard — let the tree
                    # grid dominate.
                    _bump_zone_suppress()
                    if kind == "tree":
                        _bump_tree_reject()
                    return False
                if zone_kind == "farmland_belt":
                    # Trees / boulders / cactus break the cultivated read;
                    # haystacks are OK because they're a natural fit.
                    if kind in {"tree", "palm", "cactus", "boulder"}:
                        _bump_zone_suppress()
                        if kind == "tree":
                            _bump_tree_reject()
                        return False
            # Outside-farmland haystack telemetry: we don't reject it, but
            # we count it so we can see how much random rural prop ends up
            # in wilderness vs farmland.
            if kind == "haystack" and farmland_zones and not _inside_farmland(float(x), float(y)):
                report["random_haystack_outside_farmland_count"] = int(
                    report.get("random_haystack_outside_farmland_count", 0)
                ) + 1
                report["haystack_outside_farmland_count"] = int(
                    report.get("haystack_outside_farmland_count", 0)
                ) + 1
            for ox, oy, oradius, _label in occupied[-1200:]:
                if (float(x) - ox) ** 2 + (float(y) - oy) ** 2 < (float(radius) + oradius) ** 2:
                    return False
            return True

        def note_zone(zone: str) -> None:
            zones = report.setdefault("scatter_zones", {})
            zones[zone] = int(zones.get(zone, 0)) + 1

        def zone_has_capacity(zone: str) -> bool:
            if not zone_caps or zone not in zone_caps:
                return True
            return int(report.setdefault("scatter_zones", {}).get(zone, 0)) < int(zone_caps[zone])

        def available_kinds(kind_pool: list[str]) -> list[str]:
            out: list[str] = []
            for kind in kind_pool:
                if kind not in prototypes:
                    continue
                if density_caps and kind in density_caps:
                    key = f"density_{kind}"
                    if int(report["spawned"].get(key, 0)) >= int(density_caps[kind]):
                        continue
                out.append(kind)
            return out

        def make_proto(kind: str, idx: int):
            if kind == "palm":
                return LowPolyPalmTreeFactory(
                    factory_seed=seed + 20000 + idx,
                    palm_archetype=rng.choice(["coconut", "date", "fan_palm"]),
                    coarse=True,
                ).create_asset(placeholder=None)
            if kind == "cactus":
                return LowPolyCactusFactory(
                    factory_seed=seed + 21000 + idx,
                    cactus_archetype=rng.choice(["saguaro", "barrel"]),
                    coarse=True,
                ).create_asset(placeholder=None)
            if kind == "tumbleweed":
                return LowPolyTumbleweedFactory(
                    factory_seed=seed + 22000 + idx,
                    tumbleweed_archetype=rng.choice(["dry", "sparse", "dense"]),
                    coarse=True,
                ).create_asset(placeholder=None)
            if kind == "tree":
                return NativeLowPolyTreeFactory(
                    factory_seed=seed + 23000 + idx,
                    trunk_height=rng.uniform(4.5, 7.0),
                    foliage_radius=rng.uniform(1.2, 1.9),
                    coarse=True,
                ).create_asset(placeholder=None)
            if kind == "house":
                return LowPolyHouseFactory(
                    factory_seed=seed + 23100 + idx,
                    building_archetype=rng.choice([
                        "cottage", "cabin", "longhouse", "barn",
                        "townhouse", "workshop", "tavern", "stable",
                    ]),
                    roof_archetype=rng.choice(["gabled", "hipped"]),
                    wall_color=rng.choice(["rock_pale", "stucco", "wood"]),
                    roof_color=rng.choice(["rock_shadow", "accent_red", "rust_metal"]),
                    accent_color="wood",
                    window_glow=True,
                    window_glow_color=rng.choice(["sky_warm", "foliage_lemon", "foliage_amber"]),
                    window_emission_strength=rng.uniform(0.95, 1.35),
                    coarse=True,
                ).create_asset(placeholder=None)
            if kind == "barrel":
                return LowPolyBarrelFactory(
                    factory_seed=seed + 23200 + idx,
                    barrel_archetype=rng.choice(["wooden", "metal_drum"]),
                    coarse=True,
                ).create_asset(placeholder=None)
            if kind == "crate":
                return LowPolyCrateFactory(
                    factory_seed=seed + 23300 + idx,
                    crate_archetype=rng.choice(["wooden", "fragile"]),
                    coarse=True,
                ).create_asset(placeholder=None)
            if kind == "fence":
                return LowPolyFenceFactory(
                    factory_seed=seed + 23400 + idx,
                    fence_archetype=rng.choice(["picket", "post_and_rail", "wooden_plank"]),
                    length=rng.uniform(2.5, 4.5),
                    coarse=True,
                ).create_asset(placeholder=None)
            if kind == "signage":
                return LowPolySignageFactory(
                    factory_seed=seed + 23600 + idx,
                    signage_archetype=rng.choice(["free_standing", "wall_plank"]),
                    coarse=True,
                ).create_asset(placeholder=None)
            if kind == "lantern":
                return LowPolyLanternPostFactory(
                    factory_seed=seed + 23700 + idx,
                    lantern_archetype=rng.choice(["wooden_post", "iron_post", "stone_brazier"]),
                    coarse=True,
                ).create_asset(placeholder=None)
            if kind == "haystack":
                return LowPolyHaystackFactory(
                    factory_seed=seed + 23900 + idx,
                    haystack_archetype=rng.choice(["cone", "rounded_mound", "stacked_disks"]),
                    coarse=True,
                ).create_asset(placeholder=None)
            if kind == "ruin_slab":
                return _make_ruin_fragment_template(kind, seed=seed + 23500 + idx)
            if kind == "ruin_wall":
                return _make_ruin_fragment_template(kind, seed=seed + 23800 + idx)
            return LowPolyBoulderFactory(
                factory_seed=seed + 24000 + idx,
                palette_color=rng.choice(["rock_warm", "rock_pale", "rock_shadow"]),
                decimate_ratio=0.55,
            ).spawn_asset(i=seed + 24000 + idx, loc=(0.0, 0.0, 0.0))

        prototype_kinds = ["boulder", "tumbleweed"]
        if palette_name in {"desert", "savanna", "volcanic"}:
            prototype_kinds.extend(["cactus", "palm"])
        else:
            prototype_kinds.extend(["tree"])
        has_artificial_hero = _has_any_cue(
            artificial_keys,
            _RUIN_CUES + _SETTLEMENT_CUES + ("platform", "landmark"),
        )
        if settlement_scene and not ruin_scene:
            prototype_kinds.extend([
                "house", "barrel", "crate", "fence",
                "signage", "lantern", "haystack",
            ])
        if ruin_scene:
            prototype_kinds.extend(["ruin_slab", "ruin_wall"])
        prototypes: dict[str, list[Any]] = {}
        for kind in prototype_kinds:
            prototypes[kind] = []
            for idx in range(4 if kind == "house" else 3 if kind in {"boulder", "tree"} else 2):
                try:
                    proto = make_proto(kind, idx)
                    _hide_template_object(proto)
                    prototypes[kind].append(proto)
                except Exception as exc:  # noqa: BLE001
                    report["skipped"].append({"kind": kind, "reason": f"prototype_failed:{exc}"})

        spawned = 0

        def place(kind: str, x: float, y: float, *,
                  scale_range: tuple[float, float],
                  z_offset: float = 0.0,
                  zone: str = "fill",
                  footprint_scale: float = 1.0,
                  rot_z: float | None = None) -> bool:
            nonlocal spawned
            proto_list = prototypes.get(kind) or []
            if not proto_list:
                return False
            key = f"density_{kind}"
            if density_caps and kind in density_caps:
                if int(report["spawned"].get(key, 0)) >= int(density_caps[kind]):
                    return False
            if not zone_has_capacity(zone):
                return False
            radius = float(footprint_radius.get(kind, 1.8)) * max(0.35, float(footprint_scale))
            if not can_place(kind, float(x), float(y), radius, zone=zone):
                return False
            z = float(height_at(float(x), float(y))) + float(z_offset)
            s = rng.uniform(*scale_range)
            if kind == "boulder":
                scale = (s * rng.uniform(0.8, 1.35), s * rng.uniform(0.75, 1.25), s * rng.uniform(0.55, 0.9))
            elif kind == "ruin_wall":
                scale = (s * rng.uniform(0.9, 1.3), s * rng.uniform(0.8, 1.1), s * rng.uniform(0.45, 0.75))
            elif kind == "ruin_slab":
                scale = (s * rng.uniform(0.75, 1.15), s * rng.uniform(0.75, 1.15), s * rng.uniform(0.65, 1.0))
            elif kind == "house":
                scale = (s * rng.uniform(0.88, 1.12), s * rng.uniform(0.88, 1.12), s * rng.uniform(0.86, 1.18))
            else:
                scale = (s, s, s)
            _copy_template_object(
                rng.choice(proto_list),
                name=f"StrataDensity_{kind}_{spawned:04d}",
                x=float(x),
                y=float(y),
                z=z,
                scale=scale,
                rot_z=rng.uniform(0.0, math.tau) if rot_z is None else float(rot_z),
            )
            report["spawned"][key] = int(report["spawned"].get(key, 0)) + 1
            _bump_count(spawned_counts, key, 1)
            _bump_count(planned_counts, key, 1)
            reserve(float(x), float(y), radius * max(0.85, s), key)
            note_zone(zone)
            try:
                report["placements"].append({
                    "kind": kind,
                    "zone": zone,
                    "x": round(float(x), 4),
                    "y": round(float(y), 4),
                    "z": round(float(z), 4),
                })
            except Exception:
                pass
            spawned += 1
            return True

        def clamp_to_world(x: float, y: float) -> tuple[float, float]:
            margin = max(4.0, float(size) * 0.025)
            return (
                max(-float(size) + margin, min(float(size) - margin, float(x))),
                max(-float(size) + margin, min(float(size) - margin, float(y))),
            )

        def is_dry(x: float, y: float, *, water_buffer: float = 1.0) -> bool:
            role = str(sample_role(float(x), float(y)) or "").lower()
            if "water" in role:
                return False
            if primary_water is not None:
                d = math.hypot(float(x) - primary_water.x, float(y) - primary_water.y)
                if d < primary_water.radius + water_buffer:
                    return False
            return True

        def shore_band_candidate(point: TerrainPoint) -> tuple[float, float]:
            if primary_water is None:
                return point.x, point.y
            dx = float(point.x) - primary_water.x
            dy = float(point.y) - primary_water.y
            length = math.hypot(dx, dy)
            if length < 0.001:
                angle = rng.uniform(0.0, math.tau)
                nx, ny = math.cos(angle), math.sin(angle)
            else:
                nx, ny = dx / length, dy / length
            tx, ty = -ny, nx
            outward = rng.uniform(1.5, 13.0 if palette_name == "desert" else 8.0)
            tangent = rng.uniform(-8.0, 8.0)
            if rng.random() < 0.22:
                outward *= rng.uniform(1.25, 1.9)
            x = point.x + nx * outward + tx * tangent
            y = point.y + ny * outward + ty * tangent
            return clamp_to_world(x, y)

        # Shore band first: these are the most visible objects in oasis,
        # lake, wetland, and coastal prompts. Use loose groves around the
        # shore, not the raw single-pixel shoreline samples.
        shore_goal = 0
        if primary_water is not None:
            if palette_name == "desert":
                shore_goal = min(max(36, int(needed * 0.34)), 95)
            else:
                shore_goal = min(max(30, int(needed * 0.22)), 150)
        shore_points = (
            list(primary_water.shore_points)
            if primary_water is not None
            else list(find_placeable_points(role="shore", count=max(24, shore_goal * 2)))
        )
        rng.shuffle(shore_points)
        shore_failures = 0
        while (
            spawned < needed
            and report["spawned"].get("density_palm", 0) < shore_goal
            and shore_points
            and shore_failures < shore_goal * 12
        ):
            shore_failures += 1
            point = rng.choice(shore_points)
            if spawned >= needed or report["spawned"].get("density_palm", 0) >= shore_goal:
                break
            kind = "palm" if "palm" in prototypes else ("tree" if "tree" in prototypes else "boulder")
            x, y = shore_band_candidate(point)
            if not is_dry(x, y, water_buffer=0.15):
                continue
            if place(kind, x, y, scale_range=(0.70, 1.25), z_offset=0.0, zone="shore_band"):
                continue

        # Artificial heroes need dense local support. For settlements, this
        # means crates/barrels/fences and a few trees around authored pads.
        # For actual ruin prompts, use rubble/slabs/walls. Do not turn every
        # house/town prompt into archaeological debris.
        if has_artificial_hero and spawned < needed:
            pad_regions = regions.by_role("flat_feature_pad")
            if settlement_scene and not ruin_scene and len(pad_regions) < 3:
                dry_regions = [
                    region for region in regions.by_role("dry")
                    if region.role != "flat_feature_pad"
                ]
                pad_regions = list(pad_regions) + dry_regions[: max(0, 3 - len(pad_regions))]
            rng.shuffle(pad_regions)
            if settlement_scene and not ruin_scene:
                hero_goal = min(max(34, int(needed * 0.24)), 95)
            else:
                hero_goal = min(max(24, int(needed * 0.34)), 130)

            if settlement_scene and not ruin_scene and "house" in prototypes and pad_regions:
                existing_houses = sum(
                    int(value)
                    for key, value in (spawned_counts or {}).items()
                    if any(cue in str(key).lower() for cue in ("house", "building", "cottage", "density_house"))
                )
                desired_houses = 26 if budget.get("map_size") == "xl" else 16
                house_goal = max(0, min(desired_houses - existing_houses, needed - spawned, 36))
                house_attempts = 0
                placed_houses = 0
                while placed_houses < house_goal and spawned < needed and house_attempts < house_goal * 28:
                    house_attempts += 1
                    region = rng.choice(pad_regions)
                    radius = max(5.0, min(float(region.radius) * 0.55, 34.0))
                    min_dist = min(3.5, radius * 0.35)
                    angle = rng.uniform(0.0, math.tau)
                    dist = rng.uniform(min_dist, radius)
                    x, y = clamp_to_world(
                        region.x + math.cos(angle) * dist,
                        region.y + math.sin(angle) * dist,
                    )
                    if not is_dry(x, y, water_buffer=4.0):
                        continue
                    if place("house", x, y, scale_range=(0.72, 1.08), zone="settlement_district"):
                        placed_houses += 1

            hero_spawned = 0
            hero_attempts = 0
            while pad_regions and spawned < needed and hero_spawned < hero_goal and hero_attempts < hero_goal * 12:
                hero_attempts += 1
                region = rng.choice(pad_regions)
                radius = max(3.0, min(float(region.radius) * 0.8, 12.0))
                angle = rng.uniform(0.0, math.tau)
                dist = radius * math.sqrt(rng.uniform(0.0, 1.0))
                x, y = clamp_to_world(region.x + math.cos(angle) * dist, region.y + math.sin(angle) * dist)
                if not is_dry(x, y, water_buffer=4.0):
                    continue
                if settlement_scene and not ruin_scene:
                    roll = rng.random()
                    if "barrel" in prototypes and roll < 0.22:
                        kind = "barrel"
                        scale_range = (0.72, 1.05)
                        z_offset = 0.0
                    elif "crate" in prototypes and roll < 0.42:
                        kind = "crate"
                        scale_range = (0.72, 1.10)
                        z_offset = 0.0
                    elif "fence" in prototypes and roll < 0.62:
                        kind = "fence"
                        scale_range = (0.70, 1.05)
                        z_offset = 0.0
                    elif "signage" in prototypes and roll < 0.72:
                        kind = "signage"
                        scale_range = (0.72, 1.05)
                        z_offset = 0.0
                    elif "lantern" in prototypes and roll < 0.82:
                        kind = "lantern"
                        scale_range = (0.78, 1.12)
                        z_offset = 0.0
                    elif "haystack" in prototypes and roll < 0.90:
                        kind = "haystack"
                        scale_range = (0.55, 0.92)
                        z_offset = -0.02
                    else:
                        kind = "boulder"
                        scale_range = (0.32, 0.82)
                        z_offset = -rng.uniform(0.05, 0.18)
                else:
                    roll = rng.random()
                    if "ruin_slab" in prototypes and roll < 0.42:
                        kind = "ruin_slab"
                        scale_range = (0.55, 1.05)
                        z_offset = -rng.uniform(0.03, 0.18)
                    elif "ruin_wall" in prototypes and roll < 0.58:
                        kind = "ruin_wall"
                        scale_range = (0.55, 0.95)
                        z_offset = -rng.uniform(0.02, 0.10)
                    else:
                        kind = "boulder"
                        scale_range = (0.40, 1.05)
                        z_offset = -rng.uniform(0.08, 0.28)
                if place(kind, x, y, scale_range=scale_range, z_offset=z_offset, zone="hero_support"):
                    hero_spawned += 1

        # Broad map coverage. Use zones rather than uniform dry scatter:
        # settlement maps get road-edge props, woodlots, and outskirts
        # clusters; open/natural maps keep the old broader distribution.
        dry_kinds = (
            ["boulder", "tumbleweed", "cactus", "boulder"]
            if palette_name in {"desert", "savanna", "volcanic"}
            else ["tree", "boulder", "tree", "boulder", "tree"]
        )
        margin = max(4.0, float(size) * 0.025)
        woodlot_centers: list[TerrainPoint] = list(layout.tree_zones or []) if layout is not None else []
        outer_centers: list[TerrainPoint] = list(layout.outer_zones or []) if layout is not None else []
        if layout is not None and len(woodlot_centers) < 4:
            for region in regions.by_role("dry"):
                if region.role == "flat_feature_pad":
                    continue
                if math.hypot(region.x - layout.market.x, region.y - layout.market.y) < size * 0.20:
                    continue
                if distance_to_roads(region.x, region.y) < road_width * 2.5:
                    continue
                woodlot_centers.append(TerrainPoint(
                    x=region.x,
                    y=region.y,
                    z=region.z,
                    role="tree_zone",
                    name=f"{region.name}_woodlot",
                ))
                if len(woodlot_centers) >= 6:
                    break

        def random_dry_point(*, far_from_market: bool = False) -> tuple[float, float] | None:
            for _ in range(80):
                x = rng.uniform(-float(size) + margin, float(size) - margin)
                y = rng.uniform(-float(size) + margin, float(size) - margin)
                if not is_dry(x, y, water_buffer=2.0):
                    continue
                if "basin_floor" in str(sample_role(x, y) or "").lower():
                    continue
                if far_from_market and layout is not None:
                    if math.hypot(x - layout.market.x, y - layout.market.y) < size * 0.24:
                        continue
                return x, y
            return None

        if layout is not None and len(outer_centers) < 4:
            for _ in range(16):
                point = random_dry_point(far_from_market=True)
                if point is None:
                    continue
                x, y = point
                if distance_to_roads(x, y) < road_width * 2.0:
                    continue
                outer_centers.append(TerrainPoint(
                    x=x,
                    y=y,
                    z=float(height_at(x, y)),
                    role="outer_scatter_zone",
                    name=f"outer_zone_{len(outer_centers):02d}",
                ))
                if len(outer_centers) >= 6:
                    break

        def road_edge_candidate() -> tuple[float, float] | None:
            if road_paths:
                path = rng.choice(road_paths)
                if len(path.points) < 2:
                    return None
                segment_index = rng.randrange(0, len(path.points) - 1)
                start = path.points[segment_index]
                end = path.points[segment_index + 1]
            elif road_pairs:
                start, end = rng.choice(road_pairs)
                path = None
            else:
                return None
            dx = end.x - start.x
            dy = end.y - start.y
            length = math.hypot(dx, dy)
            if length < 1e-3:
                return None
            t = rng.uniform(0.12, 0.88)
            nx, ny = -dy / length, dx / length
            side = -1.0 if rng.random() < 0.5 else 1.0
            local_width = max(road_width, float(path.width) if path is not None else road_width)
            offset = side * rng.uniform(local_width + 1.6, local_width + 8.5)
            x, y = clamp_to_world(start.x + dx * t + nx * offset, start.y + dy * t + ny * offset)
            return (x, y)

        def clustered_candidate(centers: list[TerrainPoint], *, radius: float) -> tuple[float, float] | None:
            if not centers:
                return None
            center = rng.choice(centers)
            angle = rng.uniform(0.0, math.tau)
            dist = radius * math.sqrt(rng.uniform(0.0, 1.0))
            return clamp_to_world(center.x + math.cos(angle) * dist, center.y + math.sin(angle) * dist)

        def nearest_road_info(x: float, y: float) -> tuple[float, float, float, float]:
            if road_paths:
                segments = [
                    (a, b)
                    for path in road_paths
                    for a, b in zip(path.points, path.points[1:], strict=False)
                ]
            else:
                segments = list(road_pairs)
            if not segments:
                return 10**9, float(x), float(y), 0.0
            best = (10**9, float(x), float(y), 0.0)
            for start, end in segments:
                ax, ay = start.x, start.y
                bx, by = end.x, end.y
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

        def run_settlement_wfc_experiment() -> dict[str, Any]:
            if not (village_wfc_enabled and settlement_scene and not ruin_scene and layout is not None):
                return {}
            if "house" not in prototypes:
                return {"enabled": True, "skipped": "missing_house_prototype"}

            try:
                from infinigen.maquette.runtime.village_wfc import build_village_wfc_layout

                village_layout = build_village_wfc_layout(
                    seed=int(seed) + 170031,
                    kind=str(layout.kind or "market_town"),
                    size=float(size),
                    market=layout.market,
                    road_paths=road_paths,
                    hero_pads=hero_pads,
                    road_width=float(road_width),
                    height_at=height_at,
                    sample_role=sample_role,
                    is_dry=lambda x, y: is_dry(float(x), float(y), water_buffer=3.0),
                    local_slope=local_slope,
                    out_dir=os.environ.get("MAQUETTE_OUT_DIR"),
                )
            except Exception as exc:  # noqa: BLE001
                return {"enabled": True, "skipped": f"village_wfc_failed:{exc}"}

            tile_layout = None
            tile_error = None
            if tile_wfc_enabled:
                try:
                    from infinigen.maquette.runtime.village_tile_wfc import build_village_tile_wfc_layout

                    tile_layout = build_village_tile_wfc_layout(
                        seed=int(seed) + 270047,
                        macro_layout=village_layout,
                        size=float(size),
                        road_width=float(road_width),
                        height_at=height_at,
                        sample_role=sample_role,
                        is_dry=lambda x, y: is_dry(float(x), float(y), water_buffer=3.0),
                        local_slope=local_slope,
                        out_dir=os.environ.get("MAQUETTE_OUT_DIR"),
                    )
                except Exception as exc:  # noqa: BLE001
                    tile_error = f"tile_wfc_failed:{exc}"

            tile_placements = list(getattr(tile_layout, "placements", []) or [])
            tile_cells = [
                (float(item.x), float(item.y), max(1.5, float(item.footprint_scale) * 4.4))
                for item in tile_placements
            ]
            macro_placements = []
            for placement in village_layout.placements:
                px = float(placement.x)
                py = float(placement.y)
                if any((px - tx) ** 2 + (py - ty) ** 2 < tr**2 for tx, ty, tr in tile_cells):
                    continue
                macro_placements.append(placement)
            placement_plan = tile_placements + macro_placements

            counters = {
                "requested": len(placement_plan),
                "macro_requested": len(village_layout.placements),
                "tile_requested": len(tile_placements),
                "placed": 0,
                "failed": 0,
                "by_kind": {},
                "tile_wfc_enabled": bool(tile_wfc_enabled),
            }
            if tile_error:
                counters["tile_error"] = tile_error

            def resolve_kind(primary: str, alternatives: tuple[str, ...]) -> str | None:
                for candidate in (primary, *alternatives):
                    if candidate == "tree" and candidate not in prototypes:
                        if "cactus" in prototypes:
                            return "cactus"
                        if "boulder" in prototypes:
                            return "boulder"
                        if "palm" in prototypes:
                            return "palm"
                    if candidate in prototypes:
                        return candidate
                return None

            for placement in placement_plan:
                if spawned >= needed:
                    break
                kind = resolve_kind(placement.kind, tuple(placement.alternatives))
                if kind is None:
                    counters["failed"] += 1
                    continue
                scale_range = tuple(placement.scale_range)
                ok = place(
                    kind,
                    placement.x,
                    placement.y,
                    scale_range=(float(scale_range[0]), float(scale_range[1])),
                    z_offset=float(placement.z_offset),
                    zone=str(placement.zone),
                    footprint_scale=float(placement.footprint_scale),
                    rot_z=float(placement.rot_z),
                )
                if ok:
                    counters["placed"] += 1
                    by_kind = counters["by_kind"]
                    by_kind[kind] = int(by_kind.get(kind, 0)) + 1
                else:
                    counters["failed"] += 1

            payload = village_layout.as_payload()
            payload["enabled"] = True
            payload["placement_result"] = counters
            if tile_layout is not None:
                payload["tile_wfc"] = tile_layout.as_payload()
            elif tile_error:
                payload["tile_wfc"] = {"enabled": True, "skipped": tile_error}
            return payload

            def containing_pad(x: float, y: float, *, margin: float = 1.0) -> HeroGroundPad | None:
                for pad in hero_pads:
                    if pad.contains(float(x), float(y), margin=margin):
                        return pad
                return None

            cell = max(7.0, min(float(size) * 0.044, 10.5))
            grid = 23 if float(size) >= 180.0 else 19
            half = grid // 2
            road_cells: set[tuple[int, int]] = set()
            placed_cells: dict[tuple[int, int], str] = {}
            debug_cells: list[dict[str, Any]] = []
            candidates: list[tuple[float, str, int, int, float, float]] = []
            for gy_i in range(grid):
                for gx_i in range(grid):
                    wx, wy = clamp_to_world(
                        layout.market.x + (gx_i - half) * cell,
                        layout.market.y + (gy_i - half) * cell,
                    )
                    role = str(sample_role(wx, wy) or "").lower()
                    if any(cue in role for cue in ("water", "basin_floor", "shore")):
                        debug_cells.append({"i": gx_i, "j": gy_i, "tile": "blocked", "x": wx, "y": wy})
                        continue
                    d_road = distance_to_roads(wx, wy)
                    d_anchor = settlement_anchor_distance(wx, wy)
                    slope = local_slope(wx, wy)
                    pad = containing_pad(wx, wy, margin=1.18)
                    if d_road < road_width * 1.05:
                        road_cells.add((gx_i, gy_i))
                        placed_cells[(gx_i, gy_i)] = "road"
                        debug_cells.append({"i": gx_i, "j": gy_i, "tile": "road", "x": wx, "y": wy})
                        continue
                    if d_anchor < 7.5:
                        placed_cells[(gx_i, gy_i)] = "courtyard"
                        debug_cells.append({"i": gx_i, "j": gy_i, "tile": "courtyard", "x": wx, "y": wy})
                        continue
                    if slope > 0.20 or not is_dry(wx, wy, water_buffer=3.0):
                        debug_cells.append({"i": gx_i, "j": gy_i, "tile": "blocked", "x": wx, "y": wy})
                        continue
                    if pad is None and d_road > road_width * 2.4:
                        continue
                    pad_role = str(pad.role if pad is not None else "").lower()
                    if "market" in pad_role and d_road <= road_width * 3.2:
                        score = 3.2 - abs(d_road - road_width * 1.9) * 0.16
                        candidates.append((score + rng.random() * 0.45, "prop_pocket", gx_i, gy_i, wx, wy))
                    elif "house_cluster" in pad_role and road_width * 1.18 <= d_road <= road_width * 3.4:
                        score = 3.4 - abs(d_road - road_width * 2.05) * 0.20
                        score += 0.7 if d_anchor < 34.0 else 0.0
                        candidates.append((score + rng.random() * 0.35, "house_front", gx_i, gy_i, wx, wy))
                    elif pad is not None and d_road > road_width * 2.6:
                        score = meadow_tree_score(wx, wy)
                        tile = "tree_pocket" if score > 0.22 and "tree" in prototypes else "yard"
                        candidates.append((score + rng.random() * 0.35, tile, gx_i, gy_i, wx, wy))
                    elif pad is not None and road_width * 1.10 <= d_road <= road_width * 2.7:
                        candidates.append((1.2 + rng.random() * 0.30, "fence", gx_i, gy_i, wx, wy))

            # WFC-ish collapse: process highest-constraint cells first, with
            # adjacency rules that need roads near houses and keep groves
            # away from road cells. This is intentionally local/experimental;
            # terrain, roads, and authored landmarks remain untouched.
            candidates.sort(reverse=True, key=lambda row: row[0])
            counters = {
                "house_front": 0,
                "fence": 0,
                "prop_pocket": 0,
                "yard": 0,
                "tree_pocket": 0,
                "empty": 0,
            }

            def has_neighbor_tile(i: int, j: int, tile: str) -> bool:
                for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    if placed_cells.get((i + di, j + dj)) == tile:
                        return True
                return False

            for _score, tile, i, j, x, y in candidates:
                if spawned >= needed:
                    break
                if (i, j) in placed_cells:
                    continue
                d_road, rx, ry, road_angle = nearest_road_info(x, y)
                if tile == "house_front":
                    if counters["house_front"] >= (14 if budget.get("map_size") == "xl" else 8):
                        tile = "fence"
                    elif d_road > road_width * 3.4 or not any(
                        (i + di, j + dj) in road_cells
                        for di in (-1, 0, 1)
                        for dj in (-1, 0, 1)
                    ):
                        continue
                if tile == "fence" and counters["fence"] >= (24 if budget.get("map_size") == "xl" else 14):
                    continue
                if tile == "yard" and has_neighbor_tile(i, j, "yard") and rng.random() < 0.58:
                    continue

                if tile == "house_front":
                    # Most Songe house fronts face local -Y, so rotate the
                    # facade toward the nearest road centerline.
                    rot = math.atan2(ry - y, rx - x) - math.pi * 0.5
                    if place("house", x, y, scale_range=(0.72, 1.04), zone="wfc_house_front", rot_z=rot):
                        placed_cells[(i, j)] = tile
                        counters["house_front"] += 1
                elif tile == "fence":
                    if place("fence", x, y, scale_range=(0.68, 1.02), zone="wfc_fence", rot_z=road_angle):
                        placed_cells[(i, j)] = tile
                        counters["fence"] += 1
                elif tile == "prop_pocket":
                    roll = rng.random()
                    if "crate" in prototypes and roll < 0.30:
                        kind = "crate"
                    elif "barrel" in prototypes and roll < 0.55:
                        kind = "barrel"
                    elif "lantern" in prototypes and roll < 0.78:
                        kind = "lantern"
                    else:
                        kind = "signage"
                    if place(
                        kind,
                        x,
                        y,
                        scale_range=(0.58, 0.96),
                        zone="wfc_prop_pocket",
                        footprint_scale=0.72,
                    ):
                        placed_cells[(i, j)] = tile
                        counters["prop_pocket"] += 1
                elif tile == "tree_pocket":
                    if "tree" in prototypes and place(
                        "tree",
                        x,
                        y,
                        scale_range=(0.72, 1.18),
                        zone="wfc_tree_pocket",
                        footprint_scale=0.92,
                    ):
                        placed_cells[(i, j)] = tile
                        counters["tree_pocket"] += 1
                elif tile == "yard":
                    if rng.random() > 0.32:
                        placed_cells[(i, j)] = "empty"
                        counters["empty"] += 1
                        continue
                    kind = "haystack" if "haystack" in prototypes and rng.random() < 0.55 else "fence"
                    if place(
                        kind,
                        x,
                        y,
                        scale_range=(0.46, 0.82) if kind == "haystack" else (0.52, 0.88),
                        z_offset=-0.02 if kind == "haystack" else 0.0,
                        zone="wfc_yard",
                        footprint_scale=0.82,
                    ):
                        placed_cells[(i, j)] = tile
                        counters["yard"] += 1

            for (i, j), tile in placed_cells.items():
                if tile in {"road", "courtyard"}:
                    continue
                x = layout.market.x + (i - half) * cell
                y = layout.market.y + (j - half) * cell
                debug_cells.append({"i": i, "j": j, "tile": tile, "x": x, "y": y})
            payload = {
                "enabled": True,
                "grid": grid,
                "cell_size": cell,
                "market": {"x": layout.market.x, "y": layout.market.y},
                "counters": counters,
                "road_cells": len(road_cells),
                "cells": debug_cells,
            }
            out_dir = os.environ.get("MAQUETTE_OUT_DIR")
            if out_dir:
                try:
                    debug_path = Path(out_dir) / "strata_wfc_settlement_experiment.json"
                    debug_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                except Exception:
                    pass
                try:
                    from PIL import Image, ImageDraw
                    scale = 10
                    img = Image.new("RGB", (grid * scale, grid * scale), (38, 44, 35))
                    draw = ImageDraw.Draw(img)
                    colors = {
                        "blocked": (45, 45, 45),
                        "road": (154, 123, 81),
                        "courtyard": (124, 104, 70),
                        "house_front": (158, 76, 58),
                        "fence": (108, 74, 48),
                        "prop_pocket": (191, 137, 73),
                        "yard": (130, 116, 69),
                        "tree_pocket": (56, 106, 45),
                        "empty": (77, 84, 55),
                    }
                    for cell_payload in debug_cells:
                        i = int(cell_payload["i"])
                        j = int(cell_payload["j"])
                        tile = str(cell_payload["tile"])
                        draw.rectangle(
                            (i * scale, j * scale, (i + 1) * scale - 1, (j + 1) * scale - 1),
                            fill=colors.get(tile, (83, 112, 50)),
                        )
                    img.save(Path(out_dir) / "strata_wfc_settlement_experiment.png")
                except Exception:
                    pass
            return payload

        def meadow_tree_candidate(*, far_from_market: bool = False) -> tuple[float, float] | None:
            for _ in range(140):
                x = rng.uniform(-float(size) + margin, float(size) - margin)
                y = rng.uniform(-float(size) + margin, float(size) - margin)
                if is_green_tree_ground(x, y, far_from_market=far_from_market, require_cluster=True):
                    return x, y
            return None

        wfc_report = run_settlement_wfc_experiment()
        if wfc_report:
            report["wfc_village"] = wfc_report
            report["wfc_experiment"] = wfc_report

        attempts = 0
        max_attempts = max(needed * 18, 400)
        broad_points: list[tuple[float, float]] = []
        broad_min_spacing = max(
            5.0,
            float(size) * (
                0.050 if settlement_scene and not ruin_scene
                else 0.045 if palette_name == "desert"
                else 0.025
            ),
        )
        while spawned < needed and attempts < max_attempts:
            attempts += 1
            zone = "broad_scatter"
            if settlement_scene and not ruin_scene and layout is not None:
                roll = rng.random()
                if roll < 0.10:
                    candidate = road_edge_candidate()
                    zone = "road_edges"
                    kind_pool = ["fence", "barrel", "crate", "signage", "lantern"]
                elif roll < 0.52:
                    candidate = clustered_candidate(
                        woodlot_centers,
                        radius=max(11.0, min(size * 0.12, 26.0)),
                    )
                    zone = "woodlots"
                    kind_pool = ["tree", "tree", "tree", "tree", "boulder"]
                elif roll < 0.84:
                    candidate = meadow_tree_candidate(far_from_market=True)
                    zone = "meadow_trees"
                    kind_pool = ["tree", "tree", "tree", "boulder"]
                else:
                    candidate = clustered_candidate(
                        outer_centers,
                        radius=max(12.0, min(size * 0.13, 30.0)),
                    ) or random_dry_point(far_from_market=True)
                    zone = "outer_clusters"
                    kind_pool = ["boulder", "haystack"]
                if candidate is None:
                    candidate = meadow_tree_candidate(far_from_market=False) or random_dry_point(far_from_market=False)
                    kind_pool = (
                        ["tree", "tree", "boulder", "haystack"]
                        if settlement_scene and not ruin_scene
                        else dry_kinds
                    )
                    zone = "meadow_trees" if settlement_scene and not ruin_scene else "broad_scatter"
                if candidate is None:
                    continue
                x, y = candidate
            else:
                x = rng.uniform(-float(size) + margin, float(size) - margin)
                y = rng.uniform(-float(size) + margin, float(size) - margin)
                kind_pool = dry_kinds
            if not is_dry(x, y, water_buffer=2.0):
                continue
            role = str(sample_role(x, y) or "").lower()
            if "basin_floor" in role:
                continue
            if any((x - px) ** 2 + (y - py) ** 2 < broad_min_spacing ** 2 for px, py in broad_points[-220:]):
                continue
            kind = rng.choice(available_kinds(kind_pool) or available_kinds(dry_kinds) or ["boulder"])
            if kind == "cactus" and primary_water is not None:
                if math.hypot(x - primary_water.x, y - primary_water.y) < primary_water.radius + 10.0:
                    kind = "tumbleweed"
            if kind == "tree":
                ok = place(kind, x, y, scale_range=(0.70, 1.25), zone=zone)
            elif kind == "cactus":
                ok = place(kind, x, y, scale_range=(0.55, 1.20), zone=zone)
            elif kind == "tumbleweed":
                ok = place(kind, x, y, scale_range=(0.55, 1.05), z_offset=-0.03, zone=zone)
            elif kind in {"barrel", "crate", "fence", "signage", "lantern"}:
                ok = place(kind, x, y, scale_range=(0.62, 1.06), zone=zone)
            elif kind == "haystack":
                ok = place(kind, x, y, scale_range=(0.50, 0.92), z_offset=-0.02, zone=zone)
            else:
                ok = place(kind, x, y, scale_range=(0.55, 1.35), z_offset=-0.08, zone=zone)
            if not ok:
                continue
            broad_points.append((x, y))

        # Last-mile fill: keep road/water rules, but relax footprint spacing
        # for low-priority outskirts details so quality gates do not push the
        # LLM back into retries just because the stricter first pass protected
        # too much space.
        relaxed_attempts = 0
        while spawned < needed and relaxed_attempts < max((needed - spawned) * 80, 1200):
            relaxed_attempts += 1
            zone = "outer_relaxed"
            if settlement_scene and not ruin_scene and layout is not None:
                roll = rng.random()
                if roll < 0.18:
                    candidate = clustered_candidate(
                        outer_centers or woodlot_centers,
                        radius=max(15.0, min(size * 0.16, 38.0)),
                    ) or random_dry_point(far_from_market=True)
                    kind_pool = ["boulder", "haystack"]
                elif roll < 0.62:
                    candidate = clustered_candidate(
                        woodlot_centers or outer_centers,
                        radius=max(12.0, min(size * 0.14, 32.0)),
                    ) or random_dry_point(far_from_market=True)
                    kind_pool = ["tree", "tree", "tree", "boulder"]
                    zone = "woodlot_relaxed"
                elif roll < 0.88:
                    candidate = meadow_tree_candidate(far_from_market=True)
                    kind_pool = ["tree", "tree", "tree", "boulder"]
                    zone = "meadow_tree_relaxed"
                else:
                    candidate = road_edge_candidate() or random_dry_point(far_from_market=False)
                    kind_pool = ["barrel", "crate", "fence", "signage", "lantern"]
                    zone = "road_edge_relaxed"
                footprint_scale = 0.58
            else:
                candidate = random_dry_point(far_from_market=False)
                kind_pool = dry_kinds
                footprint_scale = 0.70
            if candidate is None:
                continue
            x, y = candidate
            if not is_dry(x, y, water_buffer=1.5):
                continue
            role = str(sample_role(x, y) or "").lower()
            if "basin_floor" in role:
                continue
            kind = rng.choice(available_kinds(kind_pool) or available_kinds(dry_kinds) or ["boulder"])
            if kind == "tree":
                ok = place(kind, x, y, scale_range=(0.58, 1.08), zone=zone, footprint_scale=footprint_scale)
            elif kind == "cactus":
                ok = place(kind, x, y, scale_range=(0.48, 1.05), zone=zone, footprint_scale=footprint_scale)
            elif kind == "tumbleweed":
                ok = place(kind, x, y, scale_range=(0.48, 0.95), z_offset=-0.03, zone=zone, footprint_scale=footprint_scale)
            elif kind in {"barrel", "crate", "fence", "signage", "lantern"}:
                ok = place(kind, x, y, scale_range=(0.54, 0.95), zone=zone, footprint_scale=footprint_scale)
            elif kind == "haystack":
                ok = place(kind, x, y, scale_range=(0.42, 0.78), z_offset=-0.02, zone=zone, footprint_scale=footprint_scale)
            else:
                ok = place(kind, x, y, scale_range=(0.45, 1.08), z_offset=-0.08, zone=zone, footprint_scale=footprint_scale)
            if ok:
                broad_points.append((x, y))

        if spawned < needed and omitted_due_to_limit is not None:
            omitted_due_to_limit.append({
                "kind": "density_fill",
                "requested": int(needed),
                "spawned": int(spawned),
                "reason": "insufficient_dry_points_or_missing_prototypes",
            })
        report["spawned_total"] = int(spawned)
        report["final_visible_estimate"] = int(_visible_count(spawned_counts))
        out_dir = os.environ.get("MAQUETTE_OUT_DIR")
        if out_dir:
            try:
                zone_payload = {
                    "requested_visible": report.get("requested_visible"),
                    "existing_visible": report.get("existing_visible"),
                    "spawned_total": report.get("spawned_total"),
                    "density_mode": report.get("density_mode"),
                    "zone_caps": report.get("zone_caps", {}),
                    "spawned_by_zone": report.get("scatter_zones", {}),
                    "spawned_by_kind": report.get("spawned", {}),
                    "placements": report.get("placements", []),
                }
                Path(out_dir, "strata_zone_budget.json").write_text(
                    json.dumps(zone_payload, indent=2),
                    encoding="utf-8",
                )
            except Exception:
                pass
            try:
                from PIL import Image, ImageDraw

                canvas = 720
                margin = 28

                def sx(x: float) -> int:
                    return int(round(margin + ((float(x) + size) / (2.0 * size)) * (canvas - margin * 2)))

                def sy(y: float) -> int:
                    return int(round(canvas - margin - ((float(y) + size) / (2.0 * size)) * (canvas - margin * 2)))

                colors = {
                    "hero_support": (223, 166, 76, 220),
                    "settlement_district": (204, 94, 71, 230),
                    "road_edges": (190, 146, 88, 230),
                    "road_edge_relaxed": (168, 125, 82, 210),
                    "woodlots": (70, 137, 69, 225),
                    "woodlot_relaxed": (70, 125, 72, 190),
                    "meadow_trees": (92, 155, 76, 205),
                    "meadow_tree_relaxed": (92, 140, 80, 175),
                    "outer_clusters": (152, 116, 71, 190),
                    "outer_relaxed": (132, 107, 73, 170),
                    "wfc_house_front": (220, 82, 64, 235),
                    "wfc_fence": (120, 83, 52, 220),
                    "wfc_prop_pocket": (225, 151, 76, 230),
                    "wfc_yard": (158, 139, 79, 210),
                    "wfc_tree_pocket": (58, 125, 61, 220),
                }
                img = Image.new("RGB", (canvas, canvas), (36, 40, 34))
                draw = ImageDraw.Draw(img, "RGBA")
                draw.rectangle((margin, margin, canvas - margin, canvas - margin), outline=(92, 98, 84, 255), width=2)
                for placement in report.get("placements", []):
                    zone = str(placement.get("zone", ""))
                    color = colors.get(zone, (180, 180, 145, 180))
                    x = sx(float(placement.get("x", 0.0)))
                    y = sy(float(placement.get("y", 0.0)))
                    r = 3 if str(placement.get("kind")) in {"tree", "house"} else 2
                    draw.ellipse((x - r, y - r, x + r, y + r), fill=color)
                img.save(Path(out_dir) / "strata_zone_scatter.png")
            except Exception:
                pass
        report["placements_count"] = len(report.get("placements", []))
        report.pop("placements", None)
        return report

    return fill_visual_density


def _write_terrain_sidecar(heights, *, size: float, seed: int, biome_hint: str) -> None:
    import numpy as np

    out_dir = os.environ.get("MAQUETTE_OUT_DIR")
    if not out_dir:
        return
    target_res = 64
    stride = max(1, int(heights.shape[0]) // target_res)
    down = heights[::stride, ::stride].astype("float32")
    payload = {
        "resolution": int(down.shape[0]),
        "world_size": float(2.0 * size),
        "heights": [float(v) for v in down.flatten().tolist()],
        "seed": int(seed),
        "biome_hint": biome_hint,
        "amplitude": float(np.max(down) - np.min(down)),
    }
    Path(out_dir).joinpath("terrain.json").write_text(json.dumps(payload), encoding="utf-8")


def make_strata_terrain(
    *,
    strata_dir: str | os.PathLike[str] | None = None,
    palette_preset: str | None = None,
    water: bool = True,
    seed: int = 0,
    smooth_shading: bool = True,
):
    """Build a Maquette terrain object from a Strata heightfield package.

    Returns the same Terrain shape as make_eroded_terrain, so all Maquette
    object factories can continue placing assets with terrain.height_at(x,y).
    """
    import bpy
    import numpy as np

    from infinigen.maquette.runtime.eroded_terrain import (
        Terrain,
        _apply_painterly_hsv_macro,
        _bake_ao_to_col,
    )

    root_value = strata_dir or os.environ.get("SONGE_STRATA_TERRAIN_DIR", "")
    if not root_value:
        raise ValueError("make_strata_terrain requires strata_dir or SONGE_STRATA_TERRAIN_DIR")
    root = Path(root_value)
    raw_heights, world_size, biome_hint, source_seed = _load_heightfield(root)
    seed = int(seed if seed is not None else source_seed)
    size = float(world_size) * 0.5
    forced_palette = os.environ.get("SONGE_STRATA_PALETTE")
    palette_name = _terrain_palette_name(forced_palette or palette_preset, biome_hint)
    heights = _smooth_heightfield(
        raw_heights,
        iterations=2 if palette_name == "desert" else 1,
        strength=0.34 if palette_name == "desert" else 0.24,
    )
    heights = _soften_flat_feature_pads(heights, root, size=size)

    res_y, res_x = heights.shape
    xs = np.linspace(-size, size, res_x, dtype="float32")
    ys = np.linspace(-size, size, res_y, dtype="float32")
    xg, yg = np.meshgrid(xs, ys)
    verts = np.stack([xg, yg, heights], axis=-1).reshape(-1, 3).astype("float32")
    faces = []
    for j in range(res_y - 1):
        base = j * res_x
        nxt = (j + 1) * res_x
        for i in range(res_x - 1):
            faces.append((base + i, base + i + 1, nxt + i + 1, nxt + i))

    mesh = bpy.data.meshes.new("strata_maquette_terrain_mesh")
    mesh.from_pydata(verts.tolist(), [], faces)
    mesh.update()
    obj = bpy.data.objects.new("Terrain", mesh)
    bpy.context.collection.objects.link(obj)
    if hasattr(obj, "visible_shadow"):
        obj.visible_shadow = False
    if hasattr(obj, "cycles_visibility"):
        try:
            obj.cycles_visibility.shadow = False
        except Exception:
            pass

    for poly in mesh.polygons:
        poly.use_smooth = bool(smooth_shading)

    water_surface = None
    water_path = root / "strata_water_surface.npy"
    if water_path.is_file():
        try:
            w = np.load(water_path).astype("float32")
            water_surface = _finite_median(w)
        except Exception:  # noqa: BLE001
            water_surface = None
    sea_level = (
        water_surface if water_surface is not None and math.isfinite(water_surface)
        else float(np.quantile(heights, 0.18))
    )
    _write_col_attribute(
        {"object": obj},
        {
            "heights": heights,
            "palette_name": palette_name,
            "seed": seed,
            "sea_level": sea_level,
        },
        size=size,
    )
    _write_vertex_color_material(obj.data)

    try:
        ao = _bake_ao_to_col(obj, obj.data, samples=5, distance=3.0)
        if ao is not None and palette_name != "desert":
            col_attr = obj.data.color_attributes.get("Col")
            if col_attr is not None and len(col_attr.data) == len(ao):
                rgba = np.empty(len(ao) * 4, dtype="float32")
                col_attr.data.foreach_get("color", rgba)
                rgba = rgba.reshape(len(ao), 4)
                factor = 0.80 + 0.20 * np.clip(ao, 0.0, 1.0)
                rgba[:, :3] = np.clip(rgba[:, :3] * factor[:, None], 0.0, 1.0)
                col_attr.data.foreach_set("color", rgba.flatten())
    except Exception as exc:  # noqa: BLE001
        print(f"[strata_bridge] AO skipped: {exc}")

    if palette_name != "desert":
        try:
            _apply_painterly_hsv_macro(obj.data, seed=seed)
        except Exception as exc:  # noqa: BLE001
            print(f"[strata_bridge] painterly macro skipped: {exc}")

    water_objs = []
    if water:
        try:
            water_objs = _build_water_from_strata(root, size=size)
            print(f"[strata_bridge] placed {len(water_objs)} Strata water object(s)")
        except Exception as exc:  # noqa: BLE001
            print(f"[strata_bridge] water skipped: {exc}")

    res_minus_x = res_x - 1
    res_minus_y = res_y - 1
    span = 2.0 * size

    def height_at(x: float, y: float) -> float:
        u = (float(x) + size) / span * res_minus_x
        v = (float(y) + size) / span * res_minus_y
        u = max(0.0, min(float(res_minus_x) - 0.001, u))
        v = max(0.0, min(float(res_minus_y) - 0.001, v))
        i = int(u)
        j = int(v)
        fu = u - i
        fv = v - j
        h00 = float(heights[j, i])
        h10 = float(heights[j, i + 1])
        h01 = float(heights[j + 1, i])
        h11 = float(heights[j + 1, i + 1])
        a = h00 * (1.0 - fu) + h10 * fu
        b = h01 * (1.0 - fu) + h11 * fu
        return float(a * (1.0 - fv) + b * fv)

    regions = _build_region_anchors(root, heights=heights, size=size, height_at=height_at)
    primary_water = _build_primary_water_anchor(root, size=size, height_at=height_at)
    reserved_footprints: list[tuple[float, float, float, str]] = []

    region_roles: dict[int, str] = {}
    region_index = None
    try:
        region_index = np.load(root / "strata_region_index.npy")
        table = json.loads((root / "strata_region_table.json").read_text(encoding="utf-8"))
        region_roles = {
            int(row.get("index")): str(row.get("role") or "")
            for row in table
            if row.get("index") is not None
        }
    except Exception:
        region_index = None
        region_roles = {}

    def sample_role(x: float, y: float) -> str:
        if region_index is None:
            return ""
        j, i = _world_to_grid(float(x), float(y), size=size, shape=region_index.shape)
        return region_roles.get(int(region_index[j, i]), "")

    settlement_roads_painted = False

    def _point_payload(point: TerrainPoint) -> dict[str, Any]:
        return {
            "x": round(float(point.x), 4),
            "y": round(float(point.y), 4),
            "z": round(float(point.z), 4),
            "role": point.role,
            "name": point.name,
        }

    def _pad_payload(pad: HeroGroundPad) -> dict[str, Any]:
        return {
            "name": pad.name,
            "role": pad.role,
            "x": round(float(pad.x), 4),
            "y": round(float(pad.y), 4),
            "radius_x": round(float(pad.radius_x), 4),
            "radius_y": round(float(pad.radius_y), 4),
            "angle": round(float(pad.angle), 4),
            "irregularity": round(float(pad.irregularity), 4),
        }

    def _path_payload(path: RoadPath) -> dict[str, Any]:
        payload = {
            "name": path.name,
            "role": path.role,
            "base_role": getattr(path, "base_role", path.role),
            "width": round(float(path.width), 4),
            "points": [_point_payload(point) for point in path.points],
        }
        quality = getattr(path, "path_quality", None)
        if isinstance(quality, dict):
            payload["quality"] = quality
        return payload

    def _write_settlement_layout_debug(
        layout: SettlementLayout,
        *,
        resolution: dict[str, Any] | None = None,
    ) -> None:
        out_dir = os.environ.get("MAQUETTE_OUT_DIR")
        if not out_dir:
            return
        out = Path(out_dir)
        payload = {
            "kind": layout.kind,
            "market": _point_payload(layout.market),
            "tower": _point_payload(layout.tower) if layout.tower is not None else None,
            "house_clusters": [_point_payload(point) for point in layout.house_clusters],
            "tree_zones": [_point_payload(point) for point in layout.tree_zones or []],
            "outer_zones": [_point_payload(point) for point in layout.outer_zones or []],
            "hero_pads": [_pad_payload(pad) for pad in layout.hero_pads or []],
            "resolution": dict(resolution or {}),
            "districts": [
                {
                    "name": district.name,
                    "role": district.role,
                    "x": round(float(district.x), 4),
                    "y": round(float(district.y), 4),
                    "radius": round(float(district.radius), 4),
                }
                for district in (layout.districts or [])
            ],
            "path_graph": {
                "kind": layout.path_graph.kind if layout.path_graph is not None else layout.kind,
                "nodes": [
                    _point_payload(point)
                    for point in (layout.path_graph.nodes if layout.path_graph is not None else layout.all_anchors)
                ],
                "paths": [
                    _path_payload(path)
                    for path in (layout.path_graph.paths if layout.path_graph is not None else layout.road_paths or [])
                ],
                "edge_paths": [
                    _path_payload(path)
                    for path in (layout.path_graph.edge_paths if layout.path_graph is not None else [])
                ],
            },
        }
        try:
            (out / "strata_path_graph.json").write_text(
                json.dumps(payload["path_graph"], indent=2),
                encoding="utf-8",
            )
            (out / "strata_hero_pads.json").write_text(
                json.dumps({"hero_pads": payload["hero_pads"]}, indent=2),
                encoding="utf-8",
            )
            (out / "strata_settlement_layout.json").write_text(
                json.dumps(payload, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass
        try:
            from PIL import Image, ImageDraw

            canvas = 720
            margin = 28

            def sx(x: float) -> int:
                return int(round(margin + ((float(x) + size) / (2.0 * size)) * (canvas - margin * 2)))

            def sy(y: float) -> int:
                return int(round(canvas - margin - ((float(y) + size) / (2.0 * size)) * (canvas - margin * 2)))

            img = Image.new("RGB", (canvas, canvas), (36, 40, 34))
            draw = ImageDraw.Draw(img, "RGBA")
            draw.rectangle((margin, margin, canvas - margin, canvas - margin), outline=(92, 98, 84, 255), width=2)
            for pad in layout.hero_pads or []:
                rx = max(2, int(round((pad.radius_x / (2.0 * size)) * (canvas - margin * 2))))
                ry = max(2, int(round((pad.radius_y / (2.0 * size)) * (canvas - margin * 2))))
                color = (172, 139, 82, 115) if "market" in pad.role else (142, 115, 76, 90)
                draw.ellipse((sx(pad.x) - rx, sy(pad.y) - ry, sx(pad.x) + rx, sy(pad.y) + ry), fill=color, outline=(220, 177, 104, 180))
            for path in layout.road_paths or []:
                pts = [(sx(point.x), sy(point.y)) for point in path.points]
                if len(pts) >= 2:
                    role_lower = str(path.role or "").lower()
                    if "steep_suppressed" in role_lower:
                        color = (132, 118, 96, 120)
                    elif "edge_path" in role_lower:
                        color = (180, 145, 89, 185)
                    else:
                        color = (202, 165, 95, 230)
                    draw.line(pts, fill=color, width=max(2, int(round(path.width * 1.2))), joint="curve")
            for point in layout.house_clusters:
                draw.ellipse((sx(point.x) - 5, sy(point.y) - 5, sx(point.x) + 5, sy(point.y) + 5), fill=(188, 80, 64, 240))
            draw.ellipse((sx(layout.market.x) - 7, sy(layout.market.y) - 7, sx(layout.market.x) + 7, sy(layout.market.y) + 7), fill=(235, 205, 95, 255))
            if layout.tower is not None:
                draw.rectangle((sx(layout.tower.x) - 6, sy(layout.tower.y) - 6, sx(layout.tower.x) + 6, sy(layout.tower.y) + 6), fill=(102, 145, 210, 255))
            img.save(out / "strata_path_graph.png")
        except Exception:
            pass

    def paint_settlement_roads_once(
        roads: list[Any],
        *,
        hero_pads: list[HeroGroundPad] | None = None,
    ) -> None:
        nonlocal settlement_roads_painted
        if settlement_roads_painted:
            return
        settlement_roads_painted = True
        try:
            _paint_vertex_path_tint(
                obj,
                roads,
                palette_name=palette_name,
                size=size,
                width=max(2.7, min(float(size) * 0.018, 5.4)),
                hero_pads=hero_pads,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[strata_bridge] road tint skipped: {exc}")

    def shore_band_points(count: int) -> list[TerrainPoint]:
        if primary_water is None:
            return []
        raw = list(primary_water.shore_points)
        if not raw:
            return []
        rng = random.Random(int(seed) + int(count) * 97 + 44831)
        anchors = list(raw)
        rng.shuffle(anchors)
        out: list[TerrainPoint] = []
        attempts = 0
        margin = max(4.0, float(size) * 0.025)
        while len(out) < int(count) and attempts < max(int(count) * 24, 120):
            attempts += 1
            point = anchors[attempts % len(anchors)]
            dx = point.x - primary_water.x
            dy = point.y - primary_water.y
            length = math.hypot(dx, dy)
            if length < 0.001:
                angle = rng.uniform(0.0, math.tau)
                nx, ny = math.cos(angle), math.sin(angle)
            else:
                nx, ny = dx / length, dy / length
            tx, ty = -ny, nx
            outward = rng.uniform(1.0, 11.0 if palette_name == "desert" else 7.0)
            tangent = rng.uniform(-7.0, 7.0)
            if rng.random() < 0.18:
                outward *= rng.uniform(1.35, 2.1)
            x = point.x + nx * outward + tx * tangent
            y = point.y + ny * outward + ty * tangent
            x = max(-float(size) + margin, min(float(size) - margin, x))
            y = max(-float(size) + margin, min(float(size) - margin, y))
            if (x - primary_water.x) ** 2 + (y - primary_water.y) ** 2 <= (primary_water.radius + 0.25) ** 2:
                continue
            if "water" in str(sample_role(x, y) or "").lower():
                continue
            out.append(TerrainPoint(
                x=float(x),
                y=float(y),
                z=float(height_at(float(x), float(y))),
                role="shore",
                name="primary_water_shore_band",
            ))
        if len(out) < int(count):
            out.extend(raw[:max(0, int(count) - len(out))])
        return _evenly_limit_points(out, int(count))

    def find_placeable_points(
        role: str = "shore",
        count: int = 8,
        *,
        avoid_water: bool = True,
    ) -> list[TerrainPoint]:
        wanted = str(role).strip().lower()
        if wanted in {"primary_water_shore", "raw_shore"}:
            return _evenly_limit_points(
                list(primary_water.shore_points) if primary_water is not None else [],
                int(count),
            )
        if wanted in {"shore", "shoreline", "water_edge"}:
            return shore_band_points(int(count))
        points = regions.points(wanted, count=max(int(count) * 2, int(count)))
        if avoid_water and primary_water is not None and wanted not in {"basin_floor", "water"}:
            filtered = [
                point for point in points
                if (point.x - primary_water.x) ** 2 + (point.y - primary_water.y) ** 2
                > (primary_water.radius * 0.85) ** 2
            ]
            if filtered:
                points = filtered
        return _evenly_limit_points(points, int(count))

    def reserve_footprint(
        x: float,
        y: float,
        radius: float,
        *,
        name: str = "authored_object",
    ) -> TerrainPoint:
        label = str(name or "authored_object").lower()
        spacing_factor = 1.0
        if any(token in label for token in ("cluster", "district", "grove", "woodlot")):
            spacing_factor = 1.28
        elif any(token in label for token in ("house", "building", "tree", "palm")):
            spacing_factor = 1.18
        elif any(token in label for token in ("stall", "cart", "wagon", "fence")):
            spacing_factor = 1.10
        point = TerrainPoint(
            x=float(x),
            y=float(y),
            z=float(height_at(float(x), float(y))),
            role="reserved_footprint",
            name=str(name or "authored_object"),
        )
        reserved_footprints.append((
            point.x,
            point.y,
            max(0.05, float(radius) * spacing_factor),
            point.name,
        ))
        return point

    def place_ruin_cluster(
        x: float,
        y: float,
        *,
        radius: float = 6.0,
        pieces: int = 28,
        seed_offset: int = 0,
        name: str | None = None,
    ) -> dict[str, Any]:
        obj, piece_count = _build_ruin_cluster(
            height_at=height_at,
            x=float(x),
            y=float(y),
            radius=float(radius),
            pieces=int(pieces),
            seed=int(seed) + int(seed_offset) + 81017,
            name=name or f"StrataRuinCluster_{int(seed_offset):03d}",
        )
        return {
            "object": obj,
            "pieces": int(piece_count),
            "x": float(x),
            "y": float(y),
        }

    def settlement_layout(
        kind: str = "market_town",
        *,
        house_clusters: int | None = None,
        support_points: int = 24,
    ) -> SettlementLayout:
        """Return semantic anchors for settlement-style Maquette scenes.

        Strata often has only one or two explicit flat pads. This helper
        promotes the largest dry pad to the settlement ground and synthesizes
        additional house-cluster anchors on dry terrain around the market.
        """
        rng = random.Random(int(seed) + 53017)
        kind_str = str(kind or "")
        # v2-4 defensive: if the caller passed a generic kind (market_town,
        # town, etc.) but the user prompt clearly describes a castle/fortress/
        # keep/outpost, route to the castle archetype anyway. This protects
        # against the v1 failure mode where the LLM passed kind="market_town"
        # for a castle prompt and got a stall ring under the keep.
        env_prompt_lower = (os.environ.get("SONGE_MAQUETTE_USER_PROMPT", "") or "").lower()
        prompt_indicates_castle = any(
            token in env_prompt_lower
            for token in ("castle", "fortress", "keep ", "citadel", "stronghold", "outpost")
        )
        path_height_guard_enabled = any(
            token in env_prompt_lower
            for token in (
                "alpine",
                "mountain",
                "mountains",
                "ridge",
                "ridges",
                "peak",
                "peaks",
                "cliff",
                "cliffs",
                "canyon",
                "caldera",
                "volcanic",
                "crater",
            )
        )
        castle_archetype = is_castle_outpost_kind(kind_str) or (
            prompt_indicates_castle
            and not any(
                # If the prompt is BOTH market+castle (e.g. "castle town"),
                # the more visible composition is the market town — keep
                # the existing behaviour.
                tok in kind_str.lower() for tok in ("village", "town", "market", "hamlet")
            )
        )
        if castle_archetype and not is_castle_outpost_kind(kind_str):
            # Promote the kind so downstream report fields and plaza gates
            # observe the castle archetype consistently.
            kind_str = "castle_outpost"
        district_count = _settlement_district_count(kind_str, float(size))
        # Each district anchors a built nucleus; the market is one of them, so
        # remaining clusters fill in the other districts. Caller can still
        # override with house_clusters for legacy scripts/tests.
        non_market_districts = max(0, district_count - 1)
        # v8: settlement_resolution telemetry — the LLM-authored build.py in
        # v7 often omitted house_clusters and got a hamlet. The new default
        # for market_town size>=130 is 4-6 clusters; resolved_by_default
        # records whether the caller supplied an explicit value or whether
        # the runtime picked it.
        requested_house_clusters = (
            int(house_clusters) if house_clusters is not None else None
        )
        resolved_by_default = house_clusters is None
        cluster_goal = int(
            house_clusters
            if house_clusters is not None
            else non_market_districts
        )

        def terrain_point(x: float, y: float, *, role: str, name: str) -> TerrainPoint:
            return TerrainPoint(
                x=float(x),
                y=float(y),
                z=float(height_at(float(x), float(y))),
                role=role,
                name=name,
            )

        def is_dry(x: float, y: float, *, water_buffer: float = 3.0) -> bool:
            role = str(sample_role(float(x), float(y)) or "").lower()
            if "water" in role or "basin_floor" in role or "shore" in role:
                return False
            if primary_water is not None:
                d = math.hypot(float(x) - primary_water.x, float(y) - primary_water.y)
                if d < primary_water.radius + water_buffer:
                    return False
            return True

        def clamp(x: float, y: float) -> tuple[float, float]:
            margin = max(5.0, float(size) * 0.035)
            return (
                max(-float(size) + margin, min(float(size) - margin, float(x))),
                max(-float(size) + margin, min(float(size) - margin, float(y))),
            )

        def local_path_slope(x: float, y: float) -> float:
            delta = max(2.0, float(size) * 0.010)
            x0 = max(-float(size), min(float(size), float(x) - delta))
            x1 = max(-float(size), min(float(size), float(x) + delta))
            y0 = max(-float(size), min(float(size), float(y) - delta))
            y1 = max(-float(size), min(float(size), float(y) + delta))
            sx = abs(float(height_at(x1, y)) - float(height_at(x0, y))) / max(delta * 2.0, 1e-3)
            sy = abs(float(height_at(x, y1)) - float(height_at(x, y0))) / max(delta * 2.0, 1e-3)
            return math.hypot(sx, sy)

        try:
            import numpy as _np

            finite_heights = _np.asarray(heights, dtype="float32")
            finite_heights = finite_heights[_np.isfinite(finite_heights)]
            path_z_mid = float(_np.quantile(finite_heights, 0.62)) if finite_heights.size else 0.0
            path_z_high = float(_np.quantile(finite_heights, 0.78)) if finite_heights.size else 0.0
            path_z_extreme = float(_np.quantile(finite_heights, 0.90)) if finite_heights.size else path_z_high
        except Exception:
            path_z_mid = 0.0
            path_z_high = 0.0
            path_z_extreme = 0.0
        path_z_span = max(abs(path_z_extreme - path_z_mid), 1.0)

        def road_height_penalty(x: float, y: float, *, role: str = "") -> float:
            """Positive when a route sample sits on high ground.

            Slope alone is not enough: a broad mountain shoulder can be
            locally flat while still reading as "road painted on a mountain".
            Penalize high terrain only for mountain-like prompts; ordinary
            rolling terrain can have valid roads on high-but-flat shoulders.
            Keep a little tolerance for castle hero paths whose endpoint
            legitimately sits on a defensible pad.
            """
            role_lower = str(role or "").lower()
            z = float(height_at(float(x), float(y)))
            if not path_height_guard_enabled:
                threshold = path_z_extreme
                scale = 0.18
                if "edge_path" in role_lower:
                    threshold = path_z_high
                    scale = 0.34
                return float(
                    min(
                        0.45,
                        max(0.0, z - threshold) / path_z_span * scale,
                    )
                )
            threshold = path_z_high
            if "edge_path" in role_lower:
                threshold = path_z_mid
            elif castle_archetype and "hero_path" in role_lower:
                threshold = path_z_extreme
            penalty = max(0.0, z - threshold) / path_z_span
            if "edge_path" in role_lower:
                penalty *= 1.45
            return float(penalty)

        def road_segment_stats(points: list[TerrainPoint], *, role: str) -> dict[str, Any]:
            samples = 0
            steep = 0
            high = 0
            max_slope = 0.0
            max_grade = 0.0
            max_height_penalty = 0.0
            role_lower = str(role or "").lower()
            slope_limit = 0.30 if castle_archetype and "hero_path" in role_lower else 0.24
            if "edge_path" in role_lower:
                slope_limit = 0.18
            for a, b in zip(points, points[1:], strict=False):
                ax, ay = float(a.x), float(a.y)
                bx, by = float(b.x), float(b.y)
                seg_len = max(math.hypot(bx - ax, by - ay), 1e-4)
                steps = max(2, min(18, int(math.ceil(seg_len / max(4.0, float(size) * 0.018)))))
                last_z = float(height_at(ax, ay))
                for step_index in range(steps + 1):
                    t = step_index / float(steps)
                    x = ax + (bx - ax) * t
                    y = ay + (by - ay) * t
                    z = float(height_at(x, y))
                    slope = float(local_path_slope(x, y))
                    height_penalty = road_height_penalty(x, y, role=role)
                    max_slope = max(max_slope, slope)
                    max_height_penalty = max(max_height_penalty, height_penalty)
                    if step_index > 0:
                        grade = abs(z - last_z) / max(seg_len / float(steps), 1e-4)
                        max_grade = max(max_grade, grade)
                    last_z = z
                    samples += 1
                    if slope > slope_limit or max(slope, max_grade) > slope_limit + 0.08:
                        steep += 1
                    if height_penalty > 0.55:
                        high += 1
            return {
                "samples": int(samples),
                "steep_samples": int(steep),
                "high_samples": int(high),
                "steep_fraction": round(steep / max(samples, 1), 4),
                "high_fraction": round(high / max(samples, 1), 4),
                "max_slope": round(max_slope, 4),
                "max_grade": round(max_grade, 4),
                "max_height_penalty": round(max_height_penalty, 4),
            }

        def classify_path_role(role: str, stats: dict[str, Any]) -> str:
            role_lower = str(role or "").lower()
            steep_fraction = float(stats.get("steep_fraction") or 0.0)
            high_fraction = float(stats.get("high_fraction") or 0.0)
            max_slope = float(stats.get("max_slope") or 0.0)
            max_grade = float(stats.get("max_grade") or 0.0)
            high_suppressed = (
                path_height_guard_enabled
                and high_fraction > (0.22 if "edge_path" in role_lower else 0.34)
            )
            high_cautious = path_height_guard_enabled and high_fraction > 0.12
            if (
                steep_fraction > (0.16 if "edge_path" in role_lower else 0.24)
                or high_suppressed
                or max(max_slope, max_grade) > (0.46 if castle_archetype else 0.38)
            ):
                return f"{role}_steep_suppressed"
            if steep_fraction > 0.08 or high_cautious:
                return f"{role}_mountain_cautious"
            return role

        flat_pads = list(regions.by_role("flat_feature_pad"))
        dry_regions = [
            region for region in regions.by_role("dry")
            if region.role != "flat_feature_pad"
        ]
        all_dry_regions = flat_pads + dry_regions

        def centrality(region: RegionAnchor) -> float:
            return math.hypot(region.x, region.y)

        market_region: RegionAnchor | None = None
        market_candidates = list(flat_pads)
        if not market_candidates:
            market_candidates = list(all_dry_regions)
        if market_candidates:
            if castle_archetype:
                # Castle outpost: hero is a keep on HIGH ground. Pick the
                # highest dry pad; the 'market' field in SettlementLayout is
                # reused to carry the keep focal so downstream consumers
                # (camera, plaza gate, road graph) keep working unchanged.
                # Bias toward elevation and away from a tiny pad — a keep
                # needs enough flat ground to sit on.
                market_region = max(
                    market_candidates,
                    key=lambda r: (
                        max(0.0, r.z) * 1.8
                        + min(r.radius, 30.0) * 1.1
                        - centrality(r) * 0.012
                    ),
                )
            else:
                market_region = max(
                    market_candidates,
                    key=lambda r: (
                        min(r.radius, 46.0) * 1.9
                        - centrality(r) * 0.025
                        - max(0.0, r.z - 8.0) * 1.2
                    ),
                )

        focal_role = "keep_focal" if castle_archetype else "market_square"
        focal_label_suffix = "keep" if castle_archetype else "market"
        if market_region is not None:
            market = terrain_point(
                market_region.x,
                market_region.y,
                role=focal_role,
                name=f"{market_region.name}_{focal_label_suffix}",
            )
        else:
            natural = find_placeable_points(role="dry", count=12)
            center = min(natural, key=lambda p: p.x * p.x + p.y * p.y) if natural else None
            market = terrain_point(
                center.x if center else 0.0,
                center.y if center else 0.0,
                role=focal_role,
                name=f"synthetic_{focal_label_suffix}",
            )

        tower_region: RegionAnchor | None = None
        tower_candidates = [
            region for region in (flat_pads if flat_pads else all_dry_regions)
            if market_region is None or region.name != market_region.name
        ]
        if tower_candidates:
            tower_region = max(
                tower_candidates,
                key=lambda r: (
                    r.z * 1.25
                    + min(r.radius, 20.0) * 0.06
                    + math.hypot(r.x - market.x, r.y - market.y) * 0.045
                    - centrality(r) * 0.004
                ),
            )

        tower: TerrainPoint | None = None
        if tower_region is not None:
            tower = terrain_point(
                tower_region.x,
                tower_region.y,
                role="tower_pad",
                name=f"{tower_region.name}_tower",
            )
        elif all_dry_regions:
            region = max(
                all_dry_regions,
                key=lambda r: r.z + math.hypot(r.x - market.x, r.y - market.y) * 0.035,
            )
            tower = terrain_point(region.x, region.y, role="tower_pad", name=f"{region.name}_tower")

        clusters: list[TerrainPoint] = []

        # Use remaining explicit pads first, but avoid reusing market/tower.
        used_names = {
            name for name in (
                market_region.name if market_region is not None else None,
                tower_region.name if tower_region is not None else None,
            ) if name
        }
        for region in flat_pads:
            if region.name in used_names:
                continue
            if not is_dry(region.x, region.y, water_buffer=4.0):
                continue
            if local_path_slope(region.x, region.y) > (0.32 if castle_archetype else 0.24):
                continue
            clusters.append(terrain_point(
                region.x,
                region.y,
                role="house_cluster",
                name=f"{region.name}_houses",
            ))
            if len(clusters) >= cluster_goal:
                break

        # Then synthesize districts around the settlement ground. v6 tuned
        # to 36-58 BU for size=140: enough spread to push bbox_fraction
        # past 0.14 with 3 clusters, but tight enough that the road graph
        # still reaches every district and the WFC produces ≥1 component
        # that road-connects via the settlement_outer_radius gate.
        base_radius = max(20.0, min((market_region.radius if market_region else size * 0.22), size * 0.38))
        district_min_sep = max(36.0, float(size) * 0.22) if cluster_goal else 0.0
        district_max_sep = (
            max(district_min_sep + 22.0, min(float(size) * 0.46, base_radius * 1.85))
            if cluster_goal else 0.0
        )
        # Inter-district clearance keeps two districts from merging visually.
        inter_district_clearance = max(28.0, float(size) * 0.16)
        attempts = 0
        while len(clusters) < cluster_goal and attempts < cluster_goal * 80:
            attempts += 1
            angle = rng.uniform(0.0, math.tau)
            dist = rng.uniform(district_min_sep, district_max_sep)
            if attempts <= cluster_goal * 3:
                angle = (len(clusters) / max(cluster_goal, 1)) * math.tau + rng.uniform(-0.18, 0.18)
            x, y = clamp(market.x + math.cos(angle) * dist, market.y + math.sin(angle) * dist)
            if not is_dry(x, y, water_buffer=5.0):
                continue
            if local_path_slope(x, y) > (0.30 if castle_archetype else 0.22):
                continue
            if tower is not None and math.hypot(x - tower.x, y - tower.y) < 20.0:
                continue
            if math.hypot(x - market.x, y - market.y) < district_min_sep * 0.85:
                continue
            if any(math.hypot(x - p.x, y - p.y) < inter_district_clearance for p in clusters):
                continue
            clusters.append(terrain_point(
                x,
                y,
                role="house_cluster",
                name=f"synthetic_house_cluster_{len(clusters):02d}",
            ))

        # Fallback: draw from broad dry sample points if radial synthesis was
        # constrained by water or narrow terrain. Still respect inter-district
        # clearance so the fallback doesn't collapse them into one blob.
        if len(clusters) < cluster_goal:
            fallback_min_market = max(20.0, district_min_sep * 0.75) if cluster_goal else 13.0
            for point in find_placeable_points(role="dry", count=cluster_goal * 8):
                if len(clusters) >= cluster_goal:
                    break
                if not is_dry(point.x, point.y, water_buffer=4.0):
                    continue
                if local_path_slope(point.x, point.y) > (0.34 if castle_archetype else 0.25):
                    continue
                if math.hypot(point.x - market.x, point.y - market.y) < fallback_min_market:
                    continue
                if any(math.hypot(point.x - p.x, point.y - p.y) < inter_district_clearance for p in clusters):
                    continue
                clusters.append(terrain_point(
                    point.x,
                    point.y,
                    role="house_cluster",
                    name=f"dry_house_cluster_{len(clusters):02d}",
                ))

        support: list[TerrainPoint] = []
        support_goal = max(0, int(support_points))
        support_attempts = 0
        support_anchors = [market] + clusters
        while len(support) < support_goal and support_attempts < support_goal * 40:
            support_attempts += 1
            anchor = rng.choice(support_anchors)
            angle = rng.uniform(0.0, math.tau)
            dist = rng.uniform(3.0, 12.0)
            x, y = clamp(anchor.x + math.cos(angle) * dist, anchor.y + math.sin(angle) * dist)
            if not is_dry(x, y, water_buffer=3.0):
                continue
            if local_path_slope(x, y) > 0.32:
                continue
            support.append(terrain_point(
                x,
                y,
                role="settlement_support",
                name=f"support_{len(support):02d}",
            ))

        hero_pads: list[HeroGroundPad] = []

        def add_pad(point: TerrainPoint, *, role: str, radius: float, stretch: float = 1.0) -> None:
            rx = max(5.0, float(radius) * rng.uniform(0.86, 1.22) * max(float(stretch), 0.4))
            ry = max(5.0, float(radius) * rng.uniform(0.78, 1.12) / max(float(stretch), 0.4) ** 0.35)
            hero_pads.append(HeroGroundPad(
                name=f"{point.name}_{role}",
                role=role,
                x=point.x,
                y=point.y,
                radius_x=min(rx, size * 0.18),
                radius_y=min(ry, size * 0.18),
                angle=rng.uniform(-math.pi, math.pi),
                irregularity=rng.uniform(0.13, 0.22),
            ))

        def road_candidate_score(
            x: float,
            y: float,
            *,
            desired_x: float,
            desired_y: float,
            allow_steep_endpoint: bool = False,
            role: str = "",
        ) -> float:
            path_role = str(role or "")
            terrain_role = str(sample_role(float(x), float(y)) or "").lower()
            slope = local_path_slope(float(x), float(y))
            height_penalty = road_height_penalty(float(x), float(y), role=path_role)
            score = math.hypot(float(x) - desired_x, float(y) - desired_y) * 0.11
            score += slope * 58.0
            score += height_penalty * 92.0
            if not is_dry(float(x), float(y), water_buffer=2.0):
                score += 1000.0
            if any(cue in terrain_role for cue in ("cliff", "ridge", "peak", "mountain_wall", "steep")):
                score += 42.0
            if "shore" in terrain_role or "basin_floor" in terrain_role:
                score += 32.0
            if not allow_steep_endpoint and slope > 0.34:
                score += (slope - 0.34) * 120.0
            if not allow_steep_endpoint and height_penalty > 0.75:
                score += (height_penalty - 0.75) * 130.0
            return score

        def low_slope_route(
            start: TerrainPoint,
            end: TerrainPoint,
            *,
            name: str,
            role: str,
        ) -> list[TerrainPoint] | None:
            """Route roads through plausible passes instead of straight over relief.

            This is a compact A* over a local heightfield window. It is not a
            civil-engineering road solver; it simply makes slope, water, shore,
            and cliff-like region labels expensive enough that entry/exit paths
            prefer valleys and saddles when the Strata terrain offers them.
            """
            dx = float(end.x) - float(start.x)
            dy = float(end.y) - float(start.y)
            direct_len = math.hypot(dx, dy)
            if direct_len < max(12.0, float(size) * 0.055):
                return None
            margin = max(6.0, float(size) * 0.04)
            step = max(4.8, min(float(size) * 0.040, 7.5))
            route_pad = max(22.0, min(float(size) * 0.46, direct_len * 0.42))
            min_x = max(-float(size) + margin, min(float(start.x), float(end.x)) - route_pad)
            max_x = min(float(size) - margin, max(float(start.x), float(end.x)) + route_pad)
            min_y = max(-float(size) + margin, min(float(start.y), float(end.y)) - route_pad)
            max_y = min(float(size) - margin, max(float(start.y), float(end.y)) + route_pad)
            cols = max(3, int(math.ceil((max_x - min_x) / step)) + 1)
            rows = max(3, int(math.ceil((max_y - min_y) / step)) + 1)
            if cols * rows > 12000:
                return None

            def xy_for(ix: int, iy: int) -> tuple[float, float]:
                return (
                    min(max_x, min_x + ix * step),
                    min(max_y, min_y + iy * step),
                )

            def idx_for(x: float, y: float) -> tuple[int, int]:
                ix = int(round((float(x) - min_x) / max(step, 1e-4)))
                iy = int(round((float(y) - min_y) / max(step, 1e-4)))
                return (max(0, min(cols - 1, ix)), max(0, min(rows - 1, iy)))

            start_idx = idx_for(start.x, start.y)
            end_idx = idx_for(end.x, end.y)
            cell_cost_cache: dict[tuple[int, int], float] = {}

            def cell_cost(ix: int, iy: int) -> float:
                key = (ix, iy)
                cached = cell_cost_cache.get(key)
                if cached is not None:
                    return cached
                x, y = xy_for(ix, iy)
                slope = local_path_slope(x, y)
                height_penalty = road_height_penalty(x, y, role=role)
                region_role = str(sample_role(x, y) or "").lower()
                cost = 1.0
                cost += slope * 24.0
                cost += max(0.0, slope - 0.14) * 90.0
                cost += max(0.0, slope - 0.26) * 230.0
                cost += height_penalty * (95.0 if "edge_path" in str(role).lower() else 58.0)
                cost += max(0.0, height_penalty - 0.72) * 190.0
                if not is_dry(x, y, water_buffer=2.0):
                    cost += 1800.0
                if any(cue in region_role for cue in ("cliff", "ridge", "peak", "mountain_wall", "steep")):
                    cost += 95.0
                if "shore" in region_role or "basin_floor" in region_role:
                    cost += 65.0
                # Avoid huge detours for the first/last few cells where the
                # authored endpoint itself may sit on a hilltop or pad.
                if key == start_idx or key == end_idx:
                    cost *= 0.25
                cell_cost_cache[key] = cost
                return cost

            def heuristic(ix: int, iy: int) -> float:
                x, y = xy_for(ix, iy)
                return math.hypot(x - float(end.x), y - float(end.y)) * 1.08

            frontier: list[tuple[float, int, tuple[int, int]]] = []
            heapq.heappush(frontier, (heuristic(*start_idx), 0, start_idx))
            came_from: dict[tuple[int, int], tuple[int, int] | None] = {start_idx: None}
            best_cost: dict[tuple[int, int], float] = {start_idx: 0.0}
            counter = 0
            max_expansions = min(cols * rows, 7200)
            expanded = 0
            neighbors = (
                (-1, 0), (1, 0), (0, -1), (0, 1),
                (-1, -1), (-1, 1), (1, -1), (1, 1),
            )
            while frontier and expanded < max_expansions:
                _priority, _counter, current = heapq.heappop(frontier)
                expanded += 1
                if current == end_idx:
                    break
                cix, ciy = current
                cx, cy = xy_for(cix, ciy)
                current_cost = best_cost[current]
                for ox, oy in neighbors:
                    nix, niy = cix + ox, ciy + oy
                    if nix < 0 or niy < 0 or nix >= cols or niy >= rows:
                        continue
                    nx, ny = xy_for(nix, niy)
                    step_dist = math.hypot(nx - cx, ny - cy)
                    movement = step_dist * (0.55 + 0.5 * (cell_cost(cix, ciy) + cell_cost(nix, niy)))
                    # Penalize grid-zigzags mildly so the route prefers
                    # broader curves over staircase noise when costs tie.
                    if ox != 0 and oy != 0:
                        movement *= 1.04
                    new_cost = current_cost + movement
                    nkey = (nix, niy)
                    if new_cost < best_cost.get(nkey, float("inf")):
                        best_cost[nkey] = new_cost
                        came_from[nkey] = current
                        counter += 1
                        heapq.heappush(frontier, (new_cost + heuristic(nix, niy), counter, nkey))

            if end_idx not in came_from:
                return None
            raw: list[tuple[int, int]] = []
            cursor: tuple[int, int] | None = end_idx
            while cursor is not None:
                raw.append(cursor)
                cursor = came_from.get(cursor)
            raw.reverse()
            if len(raw) < 3:
                return None

            simplified: list[tuple[int, int]] = [raw[0]]
            prev_dir: tuple[int, int] | None = None
            for a, b in zip(raw, raw[1:], strict=False):
                direction = (b[0] - a[0], b[1] - a[1])
                if prev_dir is None:
                    prev_dir = direction
                    continue
                if direction != prev_dir:
                    simplified.append(a)
                    prev_dir = direction
            simplified.append(raw[-1])
            # Keep enough intermediate points that the painted polyline does
            # not cut back across a slope the A* route avoided. Preserve
            # original route order; the simplified turn nodes are mandatory,
            # and long straight sections get additional support points.
            max_gap = max(2, int(round(18.0 / max(step, 1e-3))))
            turn_nodes = set(simplified)
            densified: list[tuple[int, int]] = []
            last_added = -10**6
            for index, node in enumerate(raw):
                mandatory = index == 0 or index == len(raw) - 1 or node in turn_nodes
                if mandatory or index - last_added >= max_gap:
                    densified.append(node)
                    last_added = index

            points: list[TerrainPoint] = [start]
            for index, (ix, iy) in enumerate(densified[1:-1], start=1):
                x, y = xy_for(ix, iy)
                points.append(terrain_point(
                    x,
                    y,
                    role=f"{role}_route",
                    name=f"{name}_route_{index:02d}",
                ))
            points.append(end)
            direct_score = road_candidate_score(
                (float(start.x) + float(end.x)) * 0.5,
                (float(start.y) + float(end.y)) * 0.5,
                desired_x=(float(start.x) + float(end.x)) * 0.5,
                desired_y=(float(start.y) + float(end.y)) * 0.5,
                allow_steep_endpoint=True,
                role=role,
            )
            route_score = sum(
                road_candidate_score(
                    float(point.x),
                    float(point.y),
                    desired_x=float(point.x),
                    desired_y=float(point.y),
                    allow_steep_endpoint=True,
                    role=role,
                )
                for point in points[1:-1]
            ) / max(len(points) - 2, 1)
            if route_score > direct_score + 55.0 and direct_len < float(size) * 0.34:
                return None
            return points

        market_radius = max(
            15.0,
            min((market_region.radius if market_region is not None else base_radius * 0.55), size * 0.16, 34.0),
        )
        add_pad(market, role="market_pad", radius=market_radius, stretch=1.10)
        if tower is not None:
            tower_radius = max(10.0, min(size * 0.075, 18.0))
            if tower_region is not None:
                tower_radius = max(10.0, min(tower_region.radius * 0.75, 18.0))
            add_pad(tower, role="tower_pad", radius=tower_radius, stretch=0.92)
        # Fewer-but-larger district pads spread the WFC built footprint out
        # without collapsing into one blob. v4 grows the cluster pad so each
        # district receives more WFC house tiles per square BU.
        cluster_radius_base = max(15.0, min(float(size) * 0.10, 26.0))
        for index, cluster in enumerate(clusters):
            add_pad(
                cluster,
                role="house_cluster_pad",
                radius=cluster_radius_base * rng.uniform(0.9, 1.18),
                stretch=1.20 if index % 2 == 0 else 0.88,
            )

        def make_path(
            start: TerrainPoint,
            end: TerrainPoint,
            *,
            name: str,
            role: str,
            width_value: float,
            bend_scale: float = 1.0,
        ) -> RoadPath:
            def finalize_path(points: list[TerrainPoint], *, base_width: float) -> RoadPath:
                stats = road_segment_stats(points, role=role)
                final_role = classify_path_role(role, stats)
                width_multiplier = 1.0
                if "steep_suppressed" in final_role:
                    width_multiplier = 0.44
                elif "mountain_cautious" in final_role:
                    width_multiplier = 0.72
                path = RoadPath(
                    name=name,
                    role=final_role,
                    points=points,
                    width=float(base_width) * width_multiplier,
                )
                setattr(path, "path_quality", stats)
                setattr(path, "base_role", role)
                return path

            dx = end.x - start.x
            dy = end.y - start.y
            length = max(math.hypot(dx, dy), 1e-4)
            route_points = low_slope_route(start, end, name=name, role=role)
            if route_points is not None and len(route_points) >= 3:
                return finalize_path(
                    route_points,
                    base_width=float(width_value) * rng.uniform(0.88, 1.08),
                )
            nx = -dy / length
            ny = dx / length
            count = 3 if length > size * 0.28 else 2
            points = [start]
            bend = min(max(3.5, length * 0.16), size * 0.075) * float(bend_scale)
            phase = rng.uniform(-math.pi, math.pi)
            for step_index in range(1, count + 1):
                t = step_index / float(count + 1)
                easing = math.sin(t * math.pi)
                side = math.sin(t * math.pi * 1.35 + phase) * bend * easing
                side += rng.uniform(-bend * 0.20, bend * 0.20)
                along = rng.uniform(-length * 0.035, length * 0.035)
                desired_x = start.x + dx * t + nx * side + (dx / length) * along
                desired_y = start.y + dy * t + ny * side + (dy / length) * along
                best_xy: tuple[float, float] | None = None
                best_score = float("inf")
                side_radius = max(4.0, bend * (0.55 + 0.28 * easing))
                along_radius = max(3.0, length * 0.055)
                for side_mul in (-1.0, -0.55, 0.0, 0.55, 1.0):
                    for along_mul in (-0.65, 0.0, 0.65):
                        cx = desired_x + nx * side_radius * side_mul + (dx / length) * along_radius * along_mul
                        cy = desired_y + ny * side_radius * side_mul + (dy / length) * along_radius * along_mul
                        cx, cy = clamp(cx, cy)
                        score = road_candidate_score(cx, cy, desired_x=desired_x, desired_y=desired_y, role=role)
                        if score < best_score:
                            best_score = score
                            best_xy = (cx, cy)
                if best_xy is not None and best_score < 1000.0:
                    x, y = best_xy
                else:
                    x, y = clamp(start.x + dx * t, start.y + dy * t)
                points.append(terrain_point(
                    x,
                    y,
                    role=f"{role}_control",
                    name=f"{name}_control_{step_index:02d}",
                ))
            points.append(end)
            return finalize_path(
                points,
                base_width=float(width_value) * rng.uniform(0.92, 1.14),
            )

        def edge_anchor(angle: float, *, name: str, role: str) -> TerrainPoint:
            margin = max(7.0, size * 0.035)
            ca = math.cos(angle)
            sa = math.sin(angle)
            tx = (size - margin - market.x) / ca if ca > 1e-4 else (-size + margin - market.x) / ca if ca < -1e-4 else 10**9
            ty = (size - margin - market.y) / sa if sa > 1e-4 else (-size + margin - market.y) / sa if sa < -1e-4 else 10**9
            t = min(value for value in (tx, ty) if value > 0.0)
            x, y = clamp(market.x + ca * t, market.y + sa * t)
            direct_x, direct_y = x, y
            best_xy = (x, y)
            best_score = road_candidate_score(
                x,
                y,
                desired_x=direct_x,
                desired_y=direct_y,
                allow_steep_endpoint=True,
                role=role,
            )
            # Slide the ingress along the same boundary if the direct edge
            # point lands on a mountain face. Entry roads should choose a
            # plausible pass into the map, not cut straight over high relief.
            span = max(18.0, float(size) * 0.18)
            on_x_edge = abs(abs(x) - (float(size) - margin)) < abs(abs(y) - (float(size) - margin))
            for offset in (-span, -span * 0.55, -span * 0.25, span * 0.25, span * 0.55, span):
                if on_x_edge:
                    cx, cy = clamp(x, y + offset)
                    cx = x
                else:
                    cx, cy = clamp(x + offset, y)
                    cy = y
                score = road_candidate_score(
                    cx,
                    cy,
                    desired_x=direct_x,
                    desired_y=direct_y,
                    allow_steep_endpoint=True,
                    role=role,
                )
                if score < best_score:
                    best_score = score
                    best_xy = (cx, cy)
            x, y = best_xy
            return terrain_point(x, y, role=role, name=name)

        roads: list[tuple[TerrainPoint, TerrainPoint]] = []
        road_paths: list[RoadPath] = []
        if tower is not None:
            roads.append((market, tower))
            road_paths.append(make_path(
                market,
                tower,
                name=f"{market.name}_to_{tower.name}",
                role="hero_path",
                width_value=max(4.2, min(size * 0.024, 6.4)),
                bend_scale=0.72,
            ))
        for cluster in clusters:
            roads.append((market, cluster))
            road_paths.append(make_path(
                market,
                cluster,
                name=f"{market.name}_to_{cluster.name}",
                role="settlement_road",
                width_value=max(4.0, min(size * 0.023, 6.1)),
                bend_scale=0.92,
            ))

        # Directional travel line: not every genre needs a road across the
        # full scene, but settlements benefit from an entry/exit path that
        # gives the terrain a readable direction.
        direction = None
        if tower is not None:
            direction = math.atan2(tower.y - market.y, tower.x - market.x)
        elif clusters:
            far = max(clusters, key=lambda p: math.hypot(p.x - market.x, p.y - market.y))
            direction = math.atan2(far.y - market.y, far.x - market.x)
        if direction is None:
            direction = rng.uniform(0.0, math.tau)
        direction += rng.uniform(-0.42, 0.42)
        entry = edge_anchor(direction + math.pi, name="settlement_entry_edge", role="entry_edge")
        exitp = edge_anchor(direction, name="settlement_exit_edge", role="exit_edge")
        roads.append((entry, market))
        roads.append((market, exitp))
        edge_paths = [
            make_path(
                entry,
                market,
                name="settlement_entry_path",
                role="edge_path",
                width_value=max(3.4, min(size * 0.018, 5.0)),
                bend_scale=1.15,
            ),
            make_path(
                market,
                exitp,
                name="settlement_exit_path",
                role="edge_path",
                width_value=max(3.4, min(size * 0.018, 5.0)),
                bend_scale=1.15,
            ),
        ]
        road_paths.extend(edge_paths)
        path_graph = ScenePathGraph(
            kind=str(kind or "market_town"),
            nodes=[entry, market, exitp] + ([tower] if tower is not None else []) + clusters,
            paths=road_paths,
            edge_paths=edge_paths,
        )
        paint_settlement_roads_once(road_paths, hero_pads=hero_pads)

        def distance_to_roads(x: float, y: float) -> float:
            if not road_paths:
                return 10**9
            return min(
                _point_polyline_distance(x, y, path.points)
                for path in road_paths
            )

        tree_zones: list[TerrainPoint] = []
        outer_zones: list[TerrainPoint] = []
        for region in sorted(
            all_dry_regions,
            key=lambda r: math.hypot(r.x - market.x, r.y - market.y),
            reverse=True,
        ):
            if region.role == "flat_feature_pad":
                continue
            if math.hypot(region.x - market.x, region.y - market.y) < size * 0.18:
                continue
            if distance_to_roads(region.x, region.y) < 14.0:
                continue
            point = terrain_point(region.x, region.y, role="tree_zone", name=f"{region.name}_tree_zone")
            tree_zones.append(point)
            if len(tree_zones) >= 5:
                break
        zone_attempts = 0
        while len(outer_zones) < 5 and zone_attempts < 120:
            zone_attempts += 1
            angle = rng.uniform(0.0, math.tau)
            dist = rng.uniform(size * 0.28, size * 0.72)
            x, y = clamp(market.x + math.cos(angle) * dist, market.y + math.sin(angle) * dist)
            if not is_dry(x, y, water_buffer=4.0):
                continue
            if distance_to_roads(x, y) < 12.0:
                continue
            if any(math.hypot(x - p.x, y - p.y) < 22.0 for p in outer_zones):
                continue
            outer_zones.append(terrain_point(
                x,
                y,
                role="outer_scatter_zone",
                name=f"outer_zone_{len(outer_zones):02d}",
            ))

        # Build the explicit districts list. The market is always district[0];
        # remaining clusters get generic roles (residential/craft/gate) so
        # downstream code stays prompt-agnostic. v8 uses the kind-aware
        # role table so 4-6 cluster towns get mixed residential/craft/gate
        # /farmstead labels instead of all "gate" for indices ≥ 2.
        # v2-4: castle archetype uses its own role table (keep/gatehouse/
        # garrison/outer_hut) so the report distinguishes a castle outpost
        # from a market town.
        market_district_radius = market_radius * 1.05
        focal_district_role = "keep_focal" if castle_archetype else "market"
        districts: list[DistrictAnchor] = [DistrictAnchor(
            name=market.name,
            role=focal_district_role,
            x=market.x,
            y=market.y,
            radius=float(market_district_radius),
        )]
        district_radius_other = max(16.0, min(float(size) * 0.092, 26.0))
        total_clusters = len(clusters)
        for index, cluster in enumerate(clusters):
            if castle_archetype:
                cluster_role = _district_role_for_index_castle_outpost(index)
            else:
                cluster_role = _district_role_for_index_v8(index, total_clusters)
            districts.append(DistrictAnchor(
                name=cluster.name,
                role=cluster_role,
                x=cluster.x,
                y=cluster.y,
                radius=float(district_radius_other),
            ))

        # Stash the v8 resolution telemetry on the layout object so the
        # debug writer can fold it into strata_settlement_layout.json.
        # SettlementLayout is a dataclass — using a private attr keeps the
        # schema unchanged while still letting downstream code peek.
        # v2-4: declare which archetype fired. Downstream debug and the
        # primary WFC report read `settlement_archetype` so the comparison
        # board can show "castle_outpost" vs "market_town" per row.
        settlement_archetype = _settlement_archetype_for_kind(
            kind_str,
            prompt=os.environ.get("SONGE_MAQUETTE_USER_PROMPT", ""),
        )

        # v2-5: hero landmark promotion. Castle outposts always get a hero
        # keep on the focal cell. Other kinds get a hero promotion only when
        # the user prompt explicitly names a tower/keep as a focal element
        # (see _prompt_lists_tower_as_hero). When neither condition holds,
        # the recommended scale stays at 1.0 and the build script uses the
        # factory's defaults for the secondary tower at `layout.tower`.
        env_prompt = os.environ.get("SONGE_MAQUETTE_USER_PROMPT", "") or ""
        prompt_hero = _prompt_lists_tower_as_hero(env_prompt)
        # Heights of all flat pads — used to test prominence.
        pad_heights = [float(region.z) for region in flat_pads] if flat_pads else []
        median_pad_height = (
            sorted(pad_heights)[len(pad_heights) // 2] if pad_heights else 0.0
        )

        hero_landmark: HeroLandmark | None = None
        if castle_archetype:
            # The keep sits on the same cell as the focal (the bridge picked
            # the highest pad above; reuse it). Scale boosted to ~1.6x so
            # the keep reads from the default 35mm camera.
            keep_z = float(market.z)
            hero_landmark = HeroLandmark(
                kind="keep",
                x=float(market.x),
                y=float(market.y),
                z=keep_z,
                recommended_scale=1.6,
                prominence_ok=bool(keep_z >= median_pad_height - 0.25),
                reason="castle_archetype",
            )
        elif prompt_hero and tower is not None:
            # Non-castle scene where the user explicitly named the tower as
            # a hero. Promote the secondary tower cell to hero status and
            # boost scale to 1.4x. Prominence is still required.
            t_z = float(tower.z)
            hero_landmark = HeroLandmark(
                kind="watchtower",
                x=float(tower.x),
                y=float(tower.y),
                z=t_z,
                recommended_scale=1.4,
                prominence_ok=bool(t_z >= median_pad_height - 0.25),
                reason="prompt_listed_tower_as_hero",
            )

        layout_resolution = {
            "requested_house_clusters": requested_house_clusters,
            "resolved_house_clusters": int(cluster_goal),
            "resolved_by_default": bool(resolved_by_default),
            "district_count_default_for_size": int(district_count),
            "cluster_roles": [d.role for d in districts],
            "cluster_centers": [(round(d.x, 4), round(d.y, 4)) for d in districts],
            "settlement_archetype": settlement_archetype,
            "focal_role": focal_district_role,
            "hero_landmark": (
                {
                    "kind": hero_landmark.kind,
                    "x": round(hero_landmark.x, 4),
                    "y": round(hero_landmark.y, 4),
                    "z": round(hero_landmark.z, 4),
                    "recommended_scale": round(hero_landmark.recommended_scale, 3),
                    "prominence_ok": hero_landmark.prominence_ok,
                    "reason": hero_landmark.reason,
                }
                if hero_landmark is not None else None
            ),
        }

        # Use the promoted kind_str so a defensive market_town→castle_outpost
        # routing is reflected in layout.kind (and therefore the WFC plaza
        # gate later in the pipeline).
        layout = SettlementLayout(
            kind=str(kind_str or "market_town"),
            market=market,
            tower=tower,
            house_clusters=clusters,
            support_points=support,
            road_pairs=roads,
            pads=flat_pads,
            tree_zones=tree_zones,
            outer_zones=outer_zones,
            path_graph=path_graph,
            road_paths=road_paths,
            hero_pads=hero_pads,
            districts=districts,
            hero_landmark=hero_landmark,
        )
        _write_settlement_layout_debug(layout, resolution=layout_resolution)
        return layout

    def _settlement_wfc_local_slope(x: float, y: float) -> float:
        delta = max(2.0, float(size) * 0.010)
        x0 = max(-float(size), min(float(size), float(x) - delta))
        x1 = max(-float(size), min(float(size), float(x) + delta))
        y0 = max(-float(size), min(float(size), float(y) - delta))
        y1 = max(-float(size), min(float(size), float(y) + delta))
        sx = abs(float(height_at(x1, y)) - float(height_at(x0, y))) / max(delta * 2.0, 1e-3)
        sy = abs(float(height_at(x, y1)) - float(height_at(x, y0))) / max(delta * 2.0, 1e-3)
        return math.hypot(sx, sy)

    def _settlement_wfc_is_dry(x: float, y: float, *, water_buffer: float = 3.0) -> bool:
        role = str(sample_role(float(x), float(y)) or "").lower()
        if "water" in role or "basin_floor" in role or "shore" in role:
            return False
        if primary_water is not None:
            d = math.hypot(float(x) - primary_water.x, float(y) - primary_water.y)
            if d < primary_water.radius + float(water_buffer):
                return False
        return True

    def wfc_settlement_plan(
        kind: str = "market_town",
        *,
        layout: SettlementLayout | None = None,
        house_clusters: int | None = None,
        support_points: int = 36,
        tile_wfc: bool | None = None,
    ) -> dict[str, Any]:
        """Build the primary WFC settlement plan for Maquette scripts.

        The return value deliberately contains semantic slots, not meshes.
        Maquette factories remain responsible for the visible assets; WFC only
        decides where coherent rows, courtyards, market edges, fences, and
        local props belong.
        """

        use_tile_wfc = (
            os.environ.get("SONGE_STRATA_TILE_WFC", "").strip().lower()
            in {"1", "true", "yes", "on"}
            if tile_wfc is None else bool(tile_wfc)
        )
        settlement = layout or settlement_layout(
            kind=kind,
            house_clusters=house_clusters,
            support_points=support_points,
        )
        road_width = max(4.8, min(float(size) * 0.034, 7.2))
        out_dir = os.environ.get("MAQUETTE_OUT_DIR")
        try:
            from infinigen.maquette.runtime.village_wfc import build_village_wfc_layout

            village_layout = build_village_wfc_layout(
                seed=int(seed) + 170031,
                kind=str(settlement.kind or kind or "market_town"),
                size=float(size),
                market=settlement.market,
                road_paths=list(settlement.road_paths or []),
                hero_pads=list(settlement.hero_pads or []),
                districts=list(settlement.districts or []),
                road_width=float(road_width),
                height_at=height_at,
                sample_role=sample_role,
                is_dry=lambda x, y: _settlement_wfc_is_dry(float(x), float(y), water_buffer=3.0),
                local_slope=_settlement_wfc_local_slope,
                out_dir=out_dir,
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "enabled": True,
                "layout": settlement,
                "placements": [],
                "skipped": f"village_wfc_failed:{exc}",
            }

        tile_layout = None
        tile_error: str | None = None
        if use_tile_wfc:
            try:
                from infinigen.maquette.runtime.village_tile_wfc import build_village_tile_wfc_layout

                tile_layout = build_village_tile_wfc_layout(
                    seed=int(seed) + 270047,
                    macro_layout=village_layout,
                    size=float(size),
                    road_width=float(road_width),
                    height_at=height_at,
                    sample_role=sample_role,
                    is_dry=lambda x, y: _settlement_wfc_is_dry(float(x), float(y), water_buffer=3.0),
                    local_slope=_settlement_wfc_local_slope,
                    out_dir=out_dir,
                )
            except Exception as exc:  # noqa: BLE001
                tile_error = f"tile_wfc_failed:{exc}"

        tile_placements = list(getattr(tile_layout, "placements", []) or [])
        tile_cells = [
            (float(item.x), float(item.y), max(2.5, float(item.footprint_scale) * 5.2))
            for item in tile_placements
        ]
        # When tile WFC produced authoritative metatile placements, we drop the
        # legacy macro fallback entirely — adding it back on top reintroduces
        # the wfc_prop_pocket / wfc_yard / wfc_fence loose clutter that the
        # metatile layer was supposed to replace.
        tile_succeeded = bool(use_tile_wfc and tile_error is None and tile_placements)
        if tile_succeeded:
            macro_placements: list[Any] = []
            legacy_dropped_count = len(list(getattr(village_layout, "placements", []) or []))
        else:
            macro_placements = []
            for placement in list(getattr(village_layout, "placements", []) or []):
                px = float(placement.x)
                py = float(placement.y)
                if any((px - tx) ** 2 + (py - ty) ** 2 < tr**2 for tx, ty, tr in tile_cells):
                    continue
                macro_placements.append(placement)
            legacy_dropped_count = 0
        placements = tile_placements + macro_placements
        placements.sort(
            key=lambda item: (
                -float(getattr(item, "priority", 1.0)),
                str(getattr(item, "zone", "")),
                str(getattr(item, "kind", "")),
                float(getattr(item, "x", 0.0)),
                float(getattr(item, "y", 0.0)),
            )
        )
        placement_kind_counts: dict[str, int] = {}
        placement_zone_counts: dict[str, int] = {}
        for item in placements:
            kind_name = str(getattr(item, "kind", ""))
            zone_name = str(getattr(item, "zone", ""))
            placement_kind_counts[kind_name] = int(placement_kind_counts.get(kind_name, 0)) + 1
            placement_zone_counts[zone_name] = int(placement_zone_counts.get(zone_name, 0)) + 1

        payload = {
            "enabled": True,
            "layout": settlement,
            "village_layout": village_layout,
            "tile_layout": tile_layout,
            "placements": placements,
            "road_width": float(road_width),
            "tile_wfc_enabled": bool(use_tile_wfc),
            "tile_error": tile_error,
            "market": settlement.market,
            "tower": settlement.tower,
            "house_clusters": list(settlement.house_clusters),
            "road_paths": list(settlement.road_paths or []),
            "hero_pads": list(settlement.hero_pads or []),
            "counts": {
                "village_slots": len(list(getattr(village_layout, "placements", []) or [])),
                "tile_slots": len(tile_placements),
                "final_slots": len(placements),
                "legacy_dropped": int(legacy_dropped_count),
                "by_kind": dict(placement_kind_counts),
                "by_zone": dict(placement_zone_counts),
            },
        }
        if out_dir:
            try:
                debug_payload = {
                    "enabled": True,
                    "tile_wfc_enabled": bool(use_tile_wfc),
                    "tile_error": tile_error,
                    "counts": payload["counts"],
                    "placements": [
                        item.as_payload() if hasattr(item, "as_payload") else {
                            "kind": str(getattr(item, "kind", "")),
                            "x": float(getattr(item, "x", 0.0)),
                            "y": float(getattr(item, "y", 0.0)),
                        }
                        for item in placements
                    ],
                }
                Path(out_dir, "strata_wfc_primary_plan.json").write_text(
                    json.dumps(debug_payload, indent=2),
                    encoding="utf-8",
                )
            except Exception:
                pass
        return payload

    def place_wfc_settlement_slots(
        plan: dict[str, Any] | None,
        *,
        spawned_counts: dict[str, int] | None = None,
        planned_counts: dict[str, int] | None = None,
        omitted_due_to_limit: list[dict[str, Any]] | None = None,
        max_slots: int | None = None,
        label_prefix: str = "wfc_primary",
    ) -> dict[str, Any]:
        """Instantiate WFC settlement slots through the normal Maquette bank."""

        placement_plan = list((plan or {}).get("placements") or [])
        report: dict[str, Any] = {
            "enabled": True,
            "requested": len(placement_plan),
            "placed": 0,
            "failed": 0,
            "by_kind": {},
            "by_zone": {},
            "skipped": [],
        }
        def write_report() -> None:
            out_dir = os.environ.get("MAQUETTE_OUT_DIR")
            if not out_dir:
                return
            try:
                Path(out_dir, "strata_wfc_primary_report.json").write_text(
                    json.dumps(report, indent=2),
                    encoding="utf-8",
                )
            except Exception:
                pass

        def slot_get(slot: Any, key: str, default: Any = None) -> Any:
            if isinstance(slot, dict):
                return slot.get(key, default)
            return getattr(slot, key, default)

        if not placement_plan:
            report["skipped"].append({"reason": "empty_wfc_plan"})
            write_report()
            return report

        try:
            from infinigen.maquette.factories.boulder import LowPolyBoulderFactory
            from infinigen.maquette.factories.native.barrel import LowPolyBarrelFactory
            from infinigen.maquette.factories.native.cactus import LowPolyCactusFactory
            from infinigen.maquette.factories.native.crate import LowPolyCrateFactory
            from infinigen.maquette.factories.native.fence import LowPolyFenceFactory
            from infinigen.maquette.factories.native.haystack import LowPolyHaystackFactory
            from infinigen.maquette.factories.native.lantern_post import LowPolyLanternPostFactory
            from infinigen.maquette.factories.native.palm_tree import LowPolyPalmTreeFactory
            from infinigen.maquette.factories.native.signage import LowPolySignageFactory
            from infinigen.maquette.factories.native.stall import LowPolyStallFactory
            from infinigen.maquette.factories.native.shopfront import LowPolyShopfrontFactory
            from infinigen.maquette.factories.native.stable_yard import LowPolyStableYardFactory
            from infinigen.maquette.factories.native.tavern import LowPolyTavernFactory
            from infinigen.maquette.factories.native.town_block import LowPolyTownBlockFactory
            from infinigen.maquette.factories.native.tree import NativeLowPolyTreeFactory
            from infinigen.maquette.factories.native.watchtower import LowPolyWatchtowerFactory
            from infinigen.maquette.factories.native.building import LowPolyHouseFactory
        except Exception as exc:  # noqa: BLE001
            report["skipped"].append({"reason": f"factory_import_failed:{exc}"})
            write_report()
            return report

        rng = random.Random(int(seed) + 88113)
        footprint_radius = {
            "house": 4.2,
            "tree": 3.1,
            "palm": 3.1,
            "cactus": 2.2,
            "boulder": 2.6,
            "barrel": 1.15,
            "crate": 1.2,
            "fence": 2.45,
            "signage": 1.55,
            "stall": 2.85,
            "lantern": 1.15,
            "haystack": 2.9,
        }
        occupied: list[tuple[float, float, float, str]] = list(reserved_footprints)
        layout = (plan or {}).get("layout")
        road_paths = list(getattr(layout, "road_paths", []) or [])
        road_width = float((plan or {}).get("road_width") or max(4.8, min(float(size) * 0.034, 7.2)))
        hard_cap = int(max_slots if max_slots is not None else (150 if float(size) >= 180.0 else 115))
        remaining_cap = max(0, int(terrain.object_budget.get("max_objects", hard_cap)) - _total_count(spawned_counts))
        hard_cap = min(hard_cap, remaining_cap)

        def distance_to_roads(x: float, y: float) -> float:
            if not road_paths:
                return 10**9
            return min(
                _point_polyline_distance(float(x), float(y), path.points)
                for path in road_paths
                if len(path.points) >= 2
            )

        def zone_capacity(zone: str) -> int:
            if zone in {"tile_wfc_house_row", "tile_wfc_house"}:
                return 58 if float(size) >= 180.0 else 38
            if zone == "tile_wfc_market":
                return 46
            if zone == "tile_wfc_wall":
                return 18
            if zone == "tile_wfc_prop":
                return 24
            if zone == "tile_wfc_garden":
                return 24
            if zone == "wfc_house_front":
                return 26
            if zone == "wfc_fence":
                return 12
            if zone == "wfc_prop_pocket":
                return 24
            return 999

        def can_place(kind: str, x: float, y: float, radius: float, *, zone: str) -> bool:
            role = str(sample_role(float(x), float(y)) or "").lower()
            if "water" in role or "basin_floor" in role:
                return False
            if kind in {"house", "tree", "palm", "cactus", "boulder", "haystack"}:
                if distance_to_roads(float(x), float(y)) < road_width * 0.78:
                    return False
            elif distance_to_roads(float(x), float(y)) < road_width * 0.24:
                return False
            for ox, oy, oradius, _label in occupied[-1600:]:
                if (float(x) - ox) ** 2 + (float(y) - oy) ** 2 < (float(radius) + oradius) ** 2:
                    return False
            return True

        def make_proto(kind: str, idx: int):
            if kind == "tree":
                return NativeLowPolyTreeFactory(
                    factory_seed=seed + 41000 + idx,
                    trunk_height=rng.uniform(4.7, 7.3),
                    foliage_radius=rng.uniform(1.25, 2.0),
                    coarse=True,
                ).create_asset(placeholder=None)
            if kind == "palm":
                return LowPolyPalmTreeFactory(
                    factory_seed=seed + 41100 + idx,
                    palm_archetype=rng.choice(["coconut", "date", "fan_palm"]),
                    coarse=True,
                ).create_asset(placeholder=None)
            if kind == "cactus":
                return LowPolyCactusFactory(
                    factory_seed=seed + 41200 + idx,
                    cactus_archetype=rng.choice(["saguaro", "barrel"]),
                    coarse=True,
                ).create_asset(placeholder=None)
            if kind == "house":
                public_building_ok = (
                    "market" in settlement_archetype_runtime
                    or "town" in settlement_archetype_runtime
                    or "village" in settlement_archetype_runtime
                    or "coastal" in settlement_archetype_runtime
                )
                service_yard_ok = (
                    public_building_ok
                    or "castle" in settlement_archetype_runtime
                    or "farm" in settlement_archetype_runtime
                )
                if idx == 6 and public_building_ok:
                    return LowPolyTavernFactory(
                        factory_seed=seed + 41300 + idx,
                        tavern_archetype=rng.choice(["roadside_inn", "guildhall", "riverside_pub"]),
                        wall_color=rng.choice(["stucco", "rock_pale", "wood"]),
                        roof_color=rng.choice(["rock_shadow", "accent_red", "rust_metal"]),
                        wood_color="wood",
                        coarse=True,
                    ).create_asset(placeholder=None)
                if idx in {7, 8} and public_building_ok:
                    return LowPolyShopfrontFactory(
                        factory_seed=seed + 41300 + idx,
                        shopfront_archetype=rng.choice(["awning_shop", "bakery_front", "apothecary_front", "closed_shutters"]),
                        wall_color=rng.choice(["stucco", "rock_pale"]),
                        cloth_color=rng.choice(["accent_red", "foliage_amber", "sky_cool", "ground_sand"]),
                        wood_color="wood",
                        coarse=True,
                    ).create_asset(placeholder=None)
                if idx == 9 and service_yard_ok:
                    return LowPolyStableYardFactory(
                        factory_seed=seed + 41300 + idx,
                        stable_yard_archetype=rng.choice(["open_stable", "paddock_yard", "cart_shelter"]),
                        roof_color=rng.choice(["rock_warm", "rock_shadow", "rust_metal"]),
                        wood_color="wood",
                        coarse=True,
                    ).create_asset(placeholder=None)
                if idx == 10 and public_building_ok:
                    town_block_choices = ["market_row", "stacked_tenement", "workshop_courtyard"]
                    if palette_name in {"desert", "savanna"} or "oasis" in settlement_archetype_runtime:
                        town_block_choices = ["mudbrick_bazaar", "market_row", "workshop_courtyard"]
                    elif "coastal" in settlement_archetype_runtime or palette_name == "coastal":
                        town_block_choices = ["coastal_row", "market_row", "workshop_courtyard"]
                    elif palette_name in {"snow", "alpine", "mountain"}:
                        town_block_choices = ["alpine_chalet_row", "stacked_tenement", "workshop_courtyard"]
                    return LowPolyTownBlockFactory(
                        factory_seed=seed + 41300 + idx,
                        town_block_archetype=rng.choice(town_block_choices),
                        wall_color=rng.choice(["stucco", "rock_pale", "wood"]),
                        roof_color=rng.choice(["rock_shadow", "accent_red", "rust_metal"]),
                        wood_color="wood",
                        window_glow=True,
                        window_glow_color=rng.choice(["sky_warm", "foliage_lemon", "foliage_amber"]),
                        window_emission_strength=rng.uniform(0.85, 1.15),
                        coarse=True,
                    ).create_asset(placeholder=None)
                return LowPolyHouseFactory(
                    factory_seed=seed + 41300 + idx,
                    building_archetype=rng.choice([
                        "cottage", "cabin", "longhouse", "barn",
                        "townhouse", "workshop", "tavern", "stable",
                    ]),
                    roof_archetype=rng.choice(["gabled", "hipped"]),
                    wall_color=rng.choice(["rock_pale", "stucco", "wood"]),
                    roof_color=rng.choice(["rock_shadow", "accent_red", "rust_metal"]),
                    accent_color="wood",
                    window_glow=True,
                    window_glow_color=rng.choice(["sky_warm", "foliage_lemon", "foliage_amber"]),
                    window_emission_strength=rng.uniform(0.95, 1.35),
                    coarse=True,
                ).create_asset(placeholder=None)
            if kind == "barrel":
                return LowPolyBarrelFactory(
                    factory_seed=seed + 41400 + idx,
                    barrel_archetype=rng.choice(["wooden", "metal_drum"]),
                    coarse=True,
                ).create_asset(placeholder=None)
            if kind == "crate":
                return LowPolyCrateFactory(
                    factory_seed=seed + 41500 + idx,
                    crate_archetype=rng.choice(["wooden", "fragile"]),
                    coarse=True,
                ).create_asset(placeholder=None)
            if kind == "fence":
                return LowPolyFenceFactory(
                    factory_seed=seed + 41600 + idx,
                    fence_archetype=rng.choice(["picket", "post_and_rail", "wooden_plank"]),
                    length=rng.uniform(2.8, 4.8),
                    coarse=True,
                ).create_asset(placeholder=None)
            if kind == "signage":
                return LowPolySignageFactory(
                    factory_seed=seed + 41700 + idx,
                    signage_archetype=rng.choice(["free_standing", "wall_plank"]),
                    coarse=True,
                ).create_asset(placeholder=None)
            if kind == "stall":
                return LowPolyStallFactory(
                    factory_seed=seed + 41750 + idx,
                    stall_archetype=rng.choice(["open", "closed_back", "double"]),
                    awning_color=rng.choice(["accent_red", "foliage_amber", "foliage_lemon", "sky_cool"]),
                    coarse=True,
                ).create_asset(placeholder=None)
            if kind == "lantern":
                return LowPolyLanternPostFactory(
                    factory_seed=seed + 41800 + idx,
                    lantern_archetype=rng.choice(["wooden_post", "iron_post", "stone_brazier"]),
                    coarse=True,
                ).create_asset(placeholder=None)
            if kind == "haystack":
                return LowPolyHaystackFactory(
                    factory_seed=seed + 41900 + idx,
                    haystack_archetype=rng.choice(["cone", "rounded_mound", "stacked_disks"]),
                    coarse=True,
                ).create_asset(placeholder=None)
            return LowPolyBoulderFactory(
                factory_seed=seed + 42000 + idx,
                palette_color=rng.choice(["rock_warm", "rock_pale", "rock_shadow"]),
                decimate_ratio=0.55,
            ).spawn_asset(i=seed + 42000 + idx, loc=(0.0, 0.0, 0.0))

        prototype_kinds = [
            "house", "barrel", "crate", "fence", "signage", "lantern",
            "stall", "haystack", "boulder",
        ]
        if palette_name in {"desert", "savanna", "volcanic"}:
            prototype_kinds.extend(["cactus", "palm"])
        else:
            prototype_kinds.append("tree")
        prototypes: dict[str, list[Any]] = {}
        for kind in prototype_kinds:
            prototypes[kind] = []
            for idx in range(11 if kind == "house" else 4 if kind == "stall" else 3):
                try:
                    proto = make_proto(kind, idx)
                    _hide_template_object(proto)
                    prototypes[kind].append(proto)
                except Exception as exc:  # noqa: BLE001
                    report["skipped"].append({"kind": kind, "reason": f"prototype_failed:{exc}"})

        def resolve_kind(primary: str, alternatives: tuple[str, ...]) -> str | None:
            for candidate in (primary, *alternatives):
                if candidate == "tree" and candidate not in prototypes:
                    if "cactus" in prototypes:
                        return "cactus"
                    if "palm" in prototypes:
                        return "palm"
                    if "boulder" in prototypes:
                        return "boulder"
                if prototypes.get(candidate):
                    return candidate
            return None

        reject_metrics: dict[str, int] = {
            "road_rejects": 0,
            "overlap_rejects": 0,
            "role_rejects": 0,
            "zone_cap_rejects": 0,
            "missing_factory_rejects": 0,
        }
        placed_positions: list[tuple[str, str, float, float]] = []

        layout_for_plaza = (plan or {}).get("layout")
        settlement_kind_str = str(
            getattr(layout_for_plaza, "kind", "market_town") or "market_town"
        ).lower()
        settlement_archetype_runtime = str(
            (getattr(layout_for_plaza, "_strata_resolution", {}) or {}).get("settlement_archetype")
            or _settlement_archetype_for_kind(
                settlement_kind_str,
                prompt=os.environ.get("SONGE_MAQUETTE_USER_PROMPT", ""),
            )
        ).lower()

        # ---- Batch 2: authoritative castle compound -------------------
        # Castle outposts need a recognisable silhouette, not just generic
        # houses around a high keep. Author a compact crenellated wall ring
        # and a two-tower gatehouse before WFC placements so later houses
        # naturally avoid the compound footprint.
        castle_compound_used = False
        castle_gatehouse_tower_count = 0
        castle_wall_segments_placed = 0
        castle_wall_segments_attempted = 0
        castle_gatehouse_present = False
        castle_wfc_used = False
        castle_wfc_piece_count = 0
        castle_wfc_mesh_object_count = 0
        castle_wfc_archetype = None
        castle_wfc_theme = None
        castle_wfc_error = None
        if (
            settlement_archetype_runtime == "castle_outpost"
            and layout_for_plaza is not None
        ):
            keep_point = getattr(layout_for_plaza, "market", None)
            gate_hint = None
            for district in (getattr(layout_for_plaza, "districts", None) or []):
                if str(getattr(district, "role", "")).lower() == "gatehouse":
                    gate_hint = district
                    break
            if gate_hint is None:
                gate_hint = getattr(layout_for_plaza, "tower", None)
            if gate_hint is None:
                clusters = list(getattr(layout_for_plaza, "house_clusters", []) or [])
                gate_hint = clusters[0] if clusters else None

            keep_pad_radius = None
            for pad in (getattr(layout_for_plaza, "hero_pads", None) or []):
                if str(getattr(pad, "role", "")).lower() in {"market_pad", "keep_pad", "plaza_pad"}:
                    keep_pad_radius = max(float(pad.radius_x), float(pad.radius_y))
                    break
            if keep_point is not None:
                try:
                    import bpy

                    castle_api = _load_castle_wfc_api()
                    castle_meshes = _load_castle_wfc_meshes()
                    build_castle_wfc_layout = castle_api["build_castle_wfc_layout"]
                    wfc_rng = random.Random(int(seed) + 926771)
                    archetype_options = (
                        "motte_bailey",
                        "irregular",
                        "multi_keep",
                        "L",
                        "ring",
                        "rect",
                    )
                    theme_options = ("pristine", "mixed", "ruined")
                    castle_wfc_archetype = wfc_rng.choice(archetype_options)
                    castle_wfc_theme = wfc_rng.choice(theme_options)
                    castle_layout = build_castle_wfc_layout(
                        seed=int(seed) + 926771,
                        archetype=castle_wfc_archetype,
                        theme=castle_wfc_theme,
                        grid_size=9,
                        tile_size=2.0,
                    )
                    local_width = max(
                        max((cell.x for cell in castle_layout.cells), default=0.0)
                        - min((cell.x for cell in castle_layout.cells), default=0.0),
                        max((cell.y for cell in castle_layout.cells), default=0.0)
                        - min((cell.y for cell in castle_layout.cells), default=0.0),
                        2.0,
                    ) + 2.0
                    target_diameter = max(
                        22.0,
                        min(float(size) * 0.24, 42.0, float(keep_pad_radius or 18.0) * 2.15),
                    )
                    visual_scale = max(1.25, min(3.1, target_diameter / local_width))
                    if gate_hint is not None:
                        global_rot = math.atan2(float(gate_hint.y) - float(keep_point.y), float(gate_hint.x) - float(keep_point.x))
                    else:
                        global_rot = 0.0
                    cos_r = math.cos(global_rot)
                    sin_r = math.sin(global_rot)
                    piece_index = {piece.name: idx for idx, piece in enumerate(castle_meshes.PIECES)}
                    mats = castle_meshes.make_castle_materials(0, int(seed) + 926771)

                    boundary_cells = 0
                    gate_cells = 0
                    keep_cells = 0
                    built_metric_cells = 0
                    all_cell_positions: list[tuple[float, float]] = []
                    for cell_index, cell in enumerate(castle_layout.cells):
                        piece_idx = piece_index.get(cell.piece_id)
                        if piece_idx is None:
                            continue
                        world_x = float(keep_point.x) + (cell.x * cos_r - cell.y * sin_r) * visual_scale
                        world_y = float(keep_point.y) + (cell.x * sin_r + cell.y * cos_r) * visual_scale
                        role_name = str(sample_role(world_x, world_y) or "").lower()
                        if "water" in role_name or "basin_floor" in role_name:
                            continue
                        base_z = float(height_at(world_x, world_y))
                        before = set(bpy.data.objects)
                        ctx = castle_meshes.Ctx(
                            cx=world_x,
                            cy=world_y,
                            theta=float(global_rot - cell.rotation * math.pi * 0.5),
                            rng=random.Random(int(seed) * 1000 + cell.row * 31 + cell.col),
                            mats=mats,
                        )
                        castle_meshes.PIECES[piece_idx].mesh_fn(ctx)
                        new_objects = [obj for obj in bpy.data.objects if obj not in before]
                        for obj_new in new_objects:
                            obj_new.name = f"StrataCastleWFC_{cell_index:03d}_{cell.piece_id}_{obj_new.name}"
                            obj_new.location.x = world_x + (float(obj_new.location.x) - world_x) * visual_scale
                            obj_new.location.y = world_y + (float(obj_new.location.y) - world_y) * visual_scale
                            obj_new.location.z = base_z + float(obj_new.location.z) * visual_scale
                            obj_new.scale = (
                                float(obj_new.scale.x) * visual_scale,
                                float(obj_new.scale.y) * visual_scale,
                                float(obj_new.scale.z) * visual_scale,
                            )
                            try:
                                obj_new.hide_render = False
                                obj_new.hide_viewport = False
                            except Exception:
                                pass
                        castle_wfc_mesh_object_count += len(new_objects)
                        castle_wfc_piece_count += 1
                        all_cell_positions.append((world_x, world_y))
                        radius = max(2.2, 1.35 * visual_scale)
                        reserved_footprints.append((world_x, world_y, radius, f"castle_wfc_{cell.piece_id}_{cell_index}"))
                        occupied.append((world_x, world_y, radius, f"castle_wfc_{cell.piece_id}_{cell_index}"))
                        if cell.piece_kind in {"wall", "corner", "passage", "end_cap", "isolated"}:
                            boundary_cells += 1
                        if cell.piece_id.startswith("gate_"):
                            gate_cells += 1
                        if cell.piece_kind == "keep":
                            keep_cells += 1
                        if cell.piece_kind in {"keep", "inner", "stairs"}:
                            built_metric_cells += 1
                            placed_positions.append(("castle_wfc", "castle_wfc", world_x, world_y))

                    if castle_wfc_piece_count > 0:
                        castle_wfc_used = True
                        castle_wall_segments_attempted = int(boundary_cells)
                        castle_wall_segments_placed = int(boundary_cells)
                        castle_gatehouse_tower_count = int(gate_cells)
                        castle_gatehouse_present = gate_cells > 0
                        castle_compound_used = True
                        report["placed"] += int(castle_wfc_piece_count)
                        report["by_kind"]["castle_wfc_piece"] = int(report["by_kind"].get("castle_wfc_piece", 0)) + int(castle_wfc_piece_count)
                        report["by_kind"]["castle_wfc_boundary"] = int(report["by_kind"].get("castle_wfc_boundary", 0)) + int(boundary_cells)
                        report["by_kind"]["castle_wfc_keep"] = int(report["by_kind"].get("castle_wfc_keep", 0)) + int(keep_cells)
                        report["by_zone"]["castle_wfc"] = int(report["by_zone"].get("castle_wfc", 0)) + int(castle_wfc_piece_count)
                        _bump_count(spawned_counts, "wfc_primary_castle_wfc_piece", int(castle_wfc_piece_count))
                        _bump_count(planned_counts, "wfc_primary_castle_wfc_piece", int(castle_wfc_piece_count))
                        if all_cell_positions:
                            xs = [p[0] for p in all_cell_positions]
                            ys = [p[1] for p in all_cell_positions]
                            report["castle_wfc_bounds"] = {
                                "min_x": round(min(xs), 3),
                                "max_x": round(max(xs), 3),
                                "min_y": round(min(ys), 3),
                                "max_y": round(max(ys), 3),
                            }
                    else:
                        castle_wfc_error = "no_cells_rendered"
                except Exception as exc:  # noqa: BLE001
                    castle_wfc_error = str(exc)
                    report["skipped"].append({
                        "kind": "castle_wfc",
                        "reason": f"castle_wfc_failed:{exc}",
                    })

            if keep_point is not None and not castle_wfc_used:
                castle_plan = _plan_castle_compound(
                    keep_point,
                    gate_hint,
                    size=float(size),
                    pad_radius=keep_pad_radius,
                )
                compound_rng = random.Random(int(seed) + 926771)

                def reserve_wall_segment(segment: CastleWallSegment, label: str) -> None:
                    samples = max(2, int(math.ceil(segment.length / 7.0)))
                    for sample_i in range(samples):
                        t = (sample_i + 0.5) / samples
                        px = segment.start_x + (segment.end_x - segment.start_x) * t
                        py = segment.start_y + (segment.end_y - segment.start_y) * t
                        reserved_footprints.append((px, py, 2.2, label))
                        occupied.append((px, py, 2.2, label))

                for wall_index, segment in enumerate(castle_plan.wall_segments):
                    castle_wall_segments_attempted += 1
                    role_name = str(sample_role(segment.mid_x, segment.mid_y) or "").lower()
                    if "water" in role_name or "basin_floor" in role_name:
                        report["skipped"].append({
                            "kind": "castle_wall_segment",
                            "reason": "water_role",
                            "index": wall_index,
                        })
                        continue
                    try:
                        wall_obj = LowPolyFenceFactory(
                            factory_seed=seed + 73100 + wall_index,
                            fence_archetype="stone_wall",
                            length=max(4.0, float(segment.length)),
                            height=compound_rng.uniform(1.85, 2.25),
                            post_radius=compound_rng.uniform(0.34, 0.46),
                            crenellated_top=True,
                            merlon_height=compound_rng.uniform(0.38, 0.56),
                            merlon_width=compound_rng.uniform(0.45, 0.62),
                            merlon_gap=compound_rng.uniform(0.36, 0.52),
                            wall_color="rock_cool",
                            accent_color="rock_pale",
                            coarse=True,
                        ).create_asset(placeholder=None)
                        wall_obj.name = f"StrataCastleWall_segment_{wall_index:02d}"
                        wall_obj.location = (
                            float(segment.start_x),
                            float(segment.start_y),
                            float(height_at(segment.mid_x, segment.mid_y)),
                        )
                        wall_obj.rotation_euler = (
                            compound_rng.uniform(-0.015, 0.015),
                            compound_rng.uniform(-0.015, 0.015),
                            float(segment.rot_z),
                        )
                        reserve_wall_segment(segment, f"castle_wall_segment_{wall_index}")
                        _bump_count(spawned_counts, "wfc_primary_castle_wall_segment", 1)
                        _bump_count(planned_counts, "wfc_primary_castle_wall_segment", 1)
                        report["placed"] += 1
                        report["by_kind"]["castle_wall_segment"] = int(
                            report["by_kind"].get("castle_wall_segment", 0)
                        ) + 1
                        report["by_zone"]["castle_compound"] = int(
                            report["by_zone"].get("castle_compound", 0)
                        ) + 1
                        placed_positions.append((
                            "castle_wall",
                            "castle_compound",
                            segment.mid_x,
                            segment.mid_y,
                        ))
                        castle_wall_segments_placed += 1
                    except Exception as exc:  # noqa: BLE001
                        report["skipped"].append({
                            "kind": "castle_wall_segment",
                            "reason": f"factory_failed:{exc}",
                            "index": wall_index,
                        })

                # Two squat square towers flanking the wall gap read more
                # clearly as a gatehouse than one generic tower.
                gate_side = (
                    -math.sin(castle_plan.gate_rot_z + math.pi * 0.5),
                    math.cos(castle_plan.gate_rot_z + math.pi * 0.5),
                )
                for tower_index, side in enumerate((-1.0, 1.0)):
                    gx = castle_plan.gate_x + gate_side[0] * side * 2.7
                    gy = castle_plan.gate_y + gate_side[1] * side * 2.7
                    role_name = str(sample_role(gx, gy) or "").lower()
                    if "water" in role_name or "basin_floor" in role_name:
                        continue
                    blocked_gate = False
                    for rx, ry, rr, label in reserved_footprints:
                        label_lower = str(label).lower()
                        if "castle_gatehouse_tower" in label_lower:
                            threshold = 2.0 + rr * 0.35
                        elif "castle_wall_segment" in label_lower:
                            threshold = 2.1 + rr * 0.45
                        else:
                            threshold = 3.1 + rr
                        if (gx - rx) ** 2 + (gy - ry) ** 2 < threshold ** 2:
                            blocked_gate = True
                            break
                    if blocked_gate:
                        continue
                    try:
                        gate_obj = LowPolyWatchtowerFactory(
                            factory_seed=seed + 73200 + tower_index,
                            watchtower_archetype="square_keep",
                            shaft_radius=1.28,
                            shaft_height=3.85,
                            n_sides=4,
                            crenel_height=0.44,
                            crenel_count=8,
                            stone_color="rock_cool",
                            wood_color="wood",
                            roof_color="rock_shadow",
                            coarse=True,
                        ).create_asset(placeholder=None)
                        gate_obj.name = f"StrataCastleGatehouse_tower_{tower_index:02d}"
                        gate_obj.location = (
                            float(gx),
                            float(gy),
                            float(height_at(gx, gy)),
                        )
                        gate_obj.rotation_euler = (0.0, 0.0, float(castle_plan.gate_rot_z))
                        gate_obj.scale = (1.08, 0.92, 0.92)
                        reserved_footprints.append((gx, gy, 3.1, f"castle_gatehouse_tower_{tower_index}"))
                        occupied.append((gx, gy, 3.1, f"castle_gatehouse_tower_{tower_index}"))
                        _bump_count(spawned_counts, "wfc_primary_castle_gatehouse_tower", 1)
                        _bump_count(planned_counts, "wfc_primary_castle_gatehouse_tower", 1)
                        report["placed"] += 1
                        report["by_kind"]["castle_gatehouse"] = int(
                            report["by_kind"].get("castle_gatehouse", 0)
                        ) + 1
                        report["by_zone"]["castle_compound"] = int(
                            report["by_zone"].get("castle_compound", 0)
                        ) + 1
                        placed_positions.append(("gatehouse", "castle_compound", gx, gy))
                        castle_gatehouse_tower_count += 1
                    except Exception as exc:  # noqa: BLE001
                        report["skipped"].append({
                            "kind": "castle_gatehouse",
                            "reason": f"factory_failed:{exc}",
                            "index": tower_index,
                        })
                castle_gatehouse_present = castle_gatehouse_tower_count >= 1
                castle_compound_used = castle_wall_segments_placed >= 4 or castle_gatehouse_present

        # ---- v8: AUTHORITATIVE plaza ring (before WFC) ------------------
        # The bridge unconditionally authors a 6-stall ring + lantern accent
        # for market_town-like kinds BEFORE the WFC main loop, so the ring
        # is the first thing reserved. WFC houses route around it instead
        # of consuming the band. Plaza overlap rejection is fixed because
        # nothing is at the ring positions when we author them.
        market_pad_obj = None
        if layout_for_plaza is not None:
            for pad in (getattr(layout_for_plaza, "hero_pads", None) or []):
                if str(getattr(pad, "role", "")).lower() in {"market_pad", "plaza_pad"}:
                    market_pad_obj = pad
                    break
        kind_allows_plaza = (
            "market" in settlement_kind_str
            or "town" in settlement_kind_str
            or "village" in settlement_kind_str
        )
        authored_plaza_used = False
        authored_plaza_stalls: list[tuple[float, float]] = []
        plaza_slots_attempted = 0
        plaza_slots_placed = 0
        plaza_slots_rejected = 0
        plaza_rejection_reasons: list[str] = []
        plaza_inner_clear_radius = 0.0
        plaza_ring_radius = 0.0
        if market_pad_obj is not None and kind_allows_plaza and prototypes.get("stall"):
            mx = float(market_pad_obj.x)
            my = float(market_pad_obj.y)
            pad_min_radius = float(min(float(market_pad_obj.radius_x), float(market_pad_obj.radius_y)))
            plaza_ring_radius = max(7.0, min(pad_min_radius * 0.55, 12.0))
            plaza_inner_clear_radius = plaza_ring_radius * 0.45
            fallback_rng = random.Random(int(seed) + 919193)
            base_angle = fallback_rng.uniform(0.0, math.tau)
            ring_count = 6
            plaza_slots_attempted = ring_count
            for ring_idx in range(ring_count):
                angle = base_angle + ring_idx * (math.tau / ring_count)
                sx = mx + math.cos(angle) * plaza_ring_radius
                sy = my + math.sin(angle) * plaza_ring_radius
                role_name = str(sample_role(sx, sy) or "").lower()
                if "water" in role_name or "basin_floor" in role_name:
                    plaza_slots_rejected += 1
                    plaza_rejection_reasons.append("water_role")
                    continue
                # v8 kind-aware overlap: a freshly authored stall is OK
                # next to other authored stalls (the ring is supposed to
                # be tight), but hard-rejects houses/large objects.
                blocked = False
                for ox, oy, oradius, olabel in occupied[-1200:]:
                    dist_sq = (sx - ox) ** 2 + (sy - oy) ** 2
                    olabel_lower = str(olabel).lower()
                    if "house" in olabel_lower or "watchtower" in olabel_lower or "wall" in olabel_lower:
                        # Hard reject — would clip a large structure.
                        if dist_sq < (2.6 + oradius) ** 2:
                            blocked = True
                            plaza_rejection_reasons.append(f"house_overlap:{olabel}")
                            break
                    elif "stall" in olabel_lower:
                        # Tighter for stall-vs-stall — only reject if
                        # literally overlapping.
                        if dist_sq < (1.4 + oradius * 0.6) ** 2:
                            blocked = True
                            plaza_rejection_reasons.append(f"stall_overlap:{olabel}")
                            break
                    else:
                        # Other props (plaza_edge, prop_cluster) — moderate.
                        if dist_sq < (1.8 + oradius * 0.8) ** 2:
                            blocked = True
                            plaza_rejection_reasons.append(f"prop_overlap:{olabel}")
                            break
                if blocked:
                    plaza_slots_rejected += 1
                    continue
                stall_proto = fallback_rng.choice(prototypes["stall"])
                z = float(height_at(sx, sy))
                stall_scale = fallback_rng.uniform(0.88, 1.06)
                rot_z = angle + math.pi  # face inward toward plaza
                _copy_template_object(
                    stall_proto,
                    name=f"StrataAuthoredPlaza_stall_{ring_idx:02d}",
                    x=sx,
                    y=sy,
                    z=z,
                    scale=(stall_scale, stall_scale, stall_scale),
                    rot_z=rot_z,
                )
                reserved_footprints.append((sx, sy, 2.4, f"authored_plaza_stall_{ring_idx}"))
                occupied.append((sx, sy, 2.4, f"authored_plaza_stall_{ring_idx}"))
                _bump_count(spawned_counts, "wfc_primary_authored_stall", 1)
                report["placed"] += 1
                report["by_kind"]["stall"] = int(report["by_kind"].get("stall", 0)) + 1
                report["by_zone"]["authored_plaza"] = int(report["by_zone"].get("authored_plaza", 0)) + 1
                placed_positions.append(("stall", "authored_plaza", sx, sy))
                authored_plaza_stalls.append((sx, sy))
                plaza_slots_placed += 1
            # Lantern accent: place off-center but inside the ring so the
            # open center stays clear of large props.
            if prototypes.get("lantern") and authored_plaza_stalls:
                lantern_angle = base_angle + math.pi * 0.5
                lx = mx + math.cos(lantern_angle) * plaza_ring_radius * 0.45
                ly = my + math.sin(lantern_angle) * plaza_ring_radius * 0.45
                if not any(
                    (lx - rx) ** 2 + (ly - ry) ** 2 < (1.2 + rr) ** 2
                    for rx, ry, rr, _ in reserved_footprints
                ):
                    proto = fallback_rng.choice(prototypes["lantern"])
                    z = float(height_at(lx, ly))
                    _copy_template_object(
                        proto,
                        name="StrataAuthoredPlaza_lantern_00",
                        x=lx, y=ly, z=z,
                        scale=(1.0, 1.0, 1.0),
                        rot_z=lantern_angle,
                    )
                    reserved_footprints.append((lx, ly, 1.2, "authored_plaza_lantern"))
                    occupied.append((lx, ly, 1.2, "authored_plaza_lantern"))
                    _bump_count(spawned_counts, "wfc_primary_authored_lantern", 1)
                    report["placed"] += 1
                    report["by_kind"]["lantern"] = int(report["by_kind"].get("lantern", 0)) + 1
                    placed_positions.append(("lantern", "authored_plaza", lx, ly))
            authored_plaza_used = bool(authored_plaza_stalls)

        for slot in placement_plan:
            if report["placed"] >= hard_cap:
                report["skipped"].append({"reason": "wfc_primary_slot_cap", "remaining": len(placement_plan) - report["placed"]})
                break
            zone = str(slot_get(slot, "zone", "wfc_primary"))
            if int(report["by_zone"].get(zone, 0)) >= zone_capacity(zone):
                reject_metrics["zone_cap_rejects"] += 1
                report["failed"] += 1
                continue
            alternatives = tuple(slot_get(slot, "alternatives", ()) or ())
            kind = resolve_kind(str(slot_get(slot, "kind", "")), alternatives)
            if kind is None:
                reject_metrics["missing_factory_rejects"] += 1
                report["failed"] += 1
                continue
            key = f"{label_prefix}_{kind}"
            _bump_count(planned_counts, key, 1)
            scale_range = tuple(slot_get(slot, "scale_range", (0.7, 1.0)))
            footprint_scale = max(0.35, float(slot_get(slot, "footprint_scale", 1.0)))
            radius = float(footprint_radius.get(kind, 1.8)) * footprint_scale
            if zone in {"tile_wfc_house_row", "tile_wfc_house", "wfc_house_front"}:
                radius *= 0.92
            elif kind in {"tree", "palm"}:
                radius *= 1.08
            x = float(slot_get(slot, "x", 0.0))
            y = float(slot_get(slot, "y", 0.0))
            role = str(sample_role(float(x), float(y)) or "").lower()
            if "water" in role or "basin_floor" in role:
                reject_metrics["role_rejects"] += 1
                report["failed"] += 1
                continue
            road_distance = distance_to_roads(float(x), float(y))
            if (
                kind in {"house", "tree", "palm", "cactus", "boulder", "haystack"}
                and road_distance < road_width * 0.78
            ) or (
                kind not in {"house", "tree", "palm", "cactus", "boulder", "haystack"}
                and road_distance < road_width * 0.24
            ):
                reject_metrics["road_rejects"] += 1
                report["failed"] += 1
                continue
            if any((float(x) - ox) ** 2 + (float(y) - oy) ** 2 < (float(radius) + oradius) ** 2 for ox, oy, oradius, _label in occupied[-1600:]):
                reject_metrics["overlap_rejects"] += 1
                report["failed"] += 1
                continue
            if not can_place(kind, x, y, radius, zone=zone):
                report["failed"] += 1
                continue
            z = float(height_at(x, y)) + float(slot_get(slot, "z_offset", 0.0))
            s = rng.uniform(float(scale_range[0]), float(scale_range[1]))
            if kind == "house":
                scale = (s * rng.uniform(0.94, 1.18), s * rng.uniform(0.94, 1.18), s * rng.uniform(0.94, 1.22))
            elif kind == "stall":
                scale = (s * rng.uniform(0.92, 1.12), s * rng.uniform(0.90, 1.10), s * rng.uniform(0.92, 1.10))
            elif kind == "boulder":
                scale = (s * rng.uniform(0.8, 1.35), s * rng.uniform(0.75, 1.25), s * rng.uniform(0.55, 0.9))
            else:
                scale = (s, s, s)
            _copy_template_object(
                rng.choice(prototypes[kind]),
                name=f"StrataWFCPrimary_{kind}_{report['placed']:04d}",
                x=x,
                y=y,
                z=z,
                scale=scale,
                rot_z=float(slot_get(slot, "rot_z", rng.uniform(0.0, math.tau))),
            )
            occupied.append((x, y, radius * max(0.9, s), key))
            reserved_footprints.append((x, y, radius * max(0.9, s), key))
            _bump_count(spawned_counts, key, 1)
            report["placed"] += 1
            report["by_kind"][kind] = int(report["by_kind"].get(kind, 0)) + 1
            report["by_zone"][zone] = int(report["by_zone"].get(zone, 0)) + 1
            placed_positions.append((kind, zone, x, y))

        # v8: post-WFC variables that the outskirt block and metrics
        # block read. The plaza ring already fired BEFORE the WFC loop;
        # these names are kept stable for compatibility with the report.
        layout_for_fallback = layout_for_plaza
        # ---- v7: semantic outskirt district ----------------------------
        # If the WFC's settlement footprint comes in below the kind-aware
        # threshold AND there's an entry/exit road, author a small row of
        # houses + a single farmstead support prop along that road. The
        # outskirts MUST be road-adjacent and path-connected to the plaza,
        # otherwise we don't author them at all (per "no metric gaming").
        outskirt_houses: list[tuple[float, float]] = []
        outskirt_support: list[str] = []
        outskirt_road_label: str | None = None
        footprint_before_outskirts: float | None = None
        outskirt_connected_to_plaza = False

        def _quick_bbox_fraction(positions_xy: list[tuple[float, float]]) -> float:
            if not positions_xy:
                return 0.0
            xs = [p[0] for p in positions_xy]
            ys = [p[1] for p in positions_xy]
            bbox_area = max(max(xs) - min(xs), 1.0) * max(max(ys) - min(ys), 1.0)
            return bbox_area / max((2.0 * float(size)) ** 2, 1.0)

        # Same kind-aware thresholds the metrics block will use.
        if "hamlet" in settlement_kind_str or "oasis" in settlement_kind_str:
            outskirt_threshold = 0.04
        elif "village" in settlement_kind_str:
            outskirt_threshold = 0.08
        else:
            outskirt_threshold = 0.14

        current_built_xy = [
            (px, py)
            for k, _z, px, py in placed_positions
            if k in {"house", "stall"}
        ]
        footprint_before_outskirts = float(_quick_bbox_fraction(current_built_xy))

        if (
            footprint_before_outskirts < outskirt_threshold
            and layout_for_fallback is not None
            and kind_allows_plaza
            and prototypes.get("house")
        ):
            # Pick the longest road path that touches the map edge (entry
            # or exit). Outskirts ride this road.
            entry_road = None
            longest_len = 0.0
            for path in (getattr(layout_for_fallback, "road_paths", None) or []):
                pts = list(getattr(path, "points", []) or [])
                if len(pts) < 2:
                    continue
                length = sum(
                    math.hypot(b.x - a.x, b.y - a.y)
                    for a, b in zip(pts, pts[1:])
                )
                edge_touch = any(
                    abs(float(p.x)) >= float(size) * 0.90
                    or abs(float(p.y)) >= float(size) * 0.90
                    for p in pts
                )
                if edge_touch and length > longest_len:
                    longest_len = length
                    entry_road = path
            if entry_road is not None:
                pts = list(entry_road.points)
                market_x = float(getattr(layout_for_fallback.market, "x", 0.0))
                market_y = float(getattr(layout_for_fallback.market, "y", 0.0))
                # v8: anchor MUST sit beyond the current settlement bbox
                # so the outskirt actually extends the footprint rather
                # than landing inside it. Compute the existing settlement
                # outer radius from current_built_xy and target ~20 BU
                # past it.
                if current_built_xy:
                    existing_outer = max(
                        math.hypot(px - market_x, py - market_y)
                        for px, py in current_built_xy
                    )
                else:
                    existing_outer = 30.0
                target_d = max(
                    existing_outer + 22.0,
                    float(size) * 0.55,
                    78.0,
                )
                # Cap so we don't push past the map edge band.
                target_d = min(target_d, float(size) * 0.85)
                anchor_xy: tuple[float, float, float] | None = None
                best_dist_err = float("inf")
                for a, b in zip(pts, pts[1:]):
                    seg_len = math.hypot(b.x - a.x, b.y - a.y)
                    if seg_len < 1e-3:
                        continue
                    for k_step in range(0, 11):
                        t = k_step / 10.0
                        px = a.x + (b.x - a.x) * t
                        py = a.y + (b.y - a.y) * t
                        d_market = math.hypot(px - market_x, py - market_y)
                        if d_market < target_d - 6.0:
                            continue
                        # Prefer the road point closest to target_d.
                        err = abs(d_market - target_d)
                        if err < best_dist_err:
                            best_dist_err = err
                            seg_angle = math.atan2(b.y - a.y, b.x - a.x)
                            anchor_xy = (px, py, seg_angle)
                if anchor_xy is not None:
                    ax, ay, road_angle = anchor_xy
                    outskirt_road_label = entry_road.name or "outskirt_road"
                    outskirt_count = 5
                    spacing = 6.5
                    side_offset = max(road_width * 1.8, 7.0)
                    fallback_rng2 = random.Random(int(seed) + 707071)
                    for oi in range(outskirt_count):
                        # Alternate sides; offset along road.
                        side = 1.0 if (oi % 2 == 0) else -1.0
                        along = (oi - (outskirt_count - 1) / 2.0) * spacing
                        # Perpendicular vector to road tangent.
                        perp = (-math.sin(road_angle), math.cos(road_angle))
                        hx = ax + math.cos(road_angle) * along + perp[0] * side_offset * side
                        hy = ay + math.sin(road_angle) * along + perp[1] * side_offset * side
                        if (
                            abs(hx) >= float(size) * 0.95
                            or abs(hy) >= float(size) * 0.95
                        ):
                            continue
                        role_name = str(sample_role(hx, hy) or "").lower()
                        if "water" in role_name or "basin_floor" in role_name:
                            continue
                        if any(
                            (hx - rx) ** 2 + (hy - ry) ** 2 < (3.6 + rr) ** 2
                            for rx, ry, rr, _ in reserved_footprints
                        ):
                            continue
                        house_proto = fallback_rng2.choice(prototypes["house"])
                        hz = float(height_at(hx, hy))
                        house_scale = fallback_rng2.uniform(0.92, 1.10)
                        rot_z = road_angle + (math.pi if side > 0 else 0.0) + fallback_rng2.uniform(-0.10, 0.10)
                        _copy_template_object(
                            house_proto,
                            name=f"StrataWFCOutskirt_house_{oi:02d}",
                            x=hx, y=hy, z=hz,
                            scale=(house_scale, house_scale, house_scale),
                            rot_z=rot_z,
                        )
                        reserved_footprints.append((hx, hy, 3.6, f"outskirt_house_{oi}"))
                        occupied.append((hx, hy, 3.6, f"outskirt_house_{oi}"))
                        _bump_count(spawned_counts, "wfc_primary_outskirt_house", 1)
                        report["placed"] += 1
                        report["by_kind"]["house"] = int(report["by_kind"].get("house", 0)) + 1
                        report["by_zone"]["roadside_outskirt"] = int(report["by_zone"].get("roadside_outskirt", 0)) + 1
                        placed_positions.append(("house", "roadside_outskirt", hx, hy))
                        outskirt_houses.append((hx, hy))
                    # One farmstead support prop: a haystack + a fence so
                    # the outskirt reads intentional, not just a row of
                    # houses.
                    for support_kind, fr_radius in (("haystack", 2.4), ("fence", 1.6)):
                        proto_list = prototypes.get(support_kind)
                        if not proto_list:
                            continue
                        offset_idx = 0 if support_kind == "haystack" else outskirt_count - 1
                        ax2 = ax + math.cos(road_angle) * (offset_idx - (outskirt_count - 1) / 2.0) * spacing + (-math.sin(road_angle)) * side_offset * 1.5
                        ay2 = ay + math.sin(road_angle) * (offset_idx - (outskirt_count - 1) / 2.0) * spacing + math.cos(road_angle) * side_offset * 1.5
                        if any(
                            (ax2 - rx) ** 2 + (ay2 - ry) ** 2 < (fr_radius + rr) ** 2
                            for rx, ry, rr, _ in reserved_footprints
                        ):
                            continue
                        proto = fallback_rng2.choice(proto_list)
                        z = float(height_at(ax2, ay2))
                        _copy_template_object(
                            proto,
                            name=f"StrataWFCOutskirt_{support_kind}_00",
                            x=ax2, y=ay2, z=z,
                            scale=(1.0, 1.0, 1.0),
                            rot_z=road_angle + math.pi * 0.5,
                        )
                        reserved_footprints.append((ax2, ay2, fr_radius, f"outskirt_{support_kind}"))
                        occupied.append((ax2, ay2, fr_radius, f"outskirt_{support_kind}"))
                        _bump_count(spawned_counts, f"wfc_primary_outskirt_{support_kind}", 1)
                        report["placed"] += 1
                        report["by_kind"][support_kind] = int(report["by_kind"].get(support_kind, 0)) + 1
                        placed_positions.append((support_kind, "roadside_outskirt", ax2, ay2))
                        outskirt_support.append(support_kind)
                    # Outskirts are placed on a road that touches the map
                    # edge AND originates from the market — so they're
                    # path-connected to the plaza by construction.
                    outskirt_connected_to_plaza = bool(outskirt_houses)

        # ---- v9: second outskirt anchor for footprint push -------------
        # If after the first outskirt the bbox is still below the v9
        # target (0.14 for market_town), try a SECOND outskirt anchor on
        # a road whose tangent differs by ≥ 60° from the first. Keep all
        # the same semantic constraints (road-adjacent, path-connected,
        # bbox-expanding).
        second_outskirt_used = False
        second_outskirt_houses: list[tuple[float, float]] = []
        first_outskirt_road_angle = None
        if outskirt_houses and 'entry_road' in dir():
            try:
                first_pts = list(entry_road.points)
                if len(first_pts) >= 2:
                    a0, b0 = first_pts[0], first_pts[1]
                    first_outskirt_road_angle = math.atan2(b0.y - a0.y, b0.x - a0.x)
            except Exception:  # noqa: BLE001
                first_outskirt_road_angle = None
        v9_density_threshold = 0.14
        post_first_built_xy = [
            (px, py)
            for k, _z, px, py in placed_positions
            if k in {"house", "stall"}
        ]
        post_first_footprint = float(_quick_bbox_fraction(post_first_built_xy))
        if (
            outskirt_houses
            and layout_for_fallback is not None
            and kind_allows_plaza
            and prototypes.get("house")
            and post_first_footprint < v9_density_threshold
            and first_outskirt_road_angle is not None
        ):
            second_road = None
            second_longest = 0.0
            for path in (getattr(layout_for_fallback, "road_paths", None) or []):
                pts = list(getattr(path, "points", []) or [])
                if len(pts) < 2:
                    continue
                edge_touch = any(
                    abs(float(p.x)) >= float(size) * 0.90
                    or abs(float(p.y)) >= float(size) * 0.90
                    for p in pts
                )
                if not edge_touch:
                    continue
                a, b = pts[0], pts[1]
                angle = math.atan2(b.y - a.y, b.x - a.x)
                angular_diff = abs(((angle - first_outskirt_road_angle) + math.pi) % math.tau - math.pi)
                if angular_diff < math.radians(60.0):
                    continue
                length = sum(
                    math.hypot(b.x - a.x, b.y - a.y)
                    for a, b in zip(pts, pts[1:])
                )
                if length > second_longest:
                    second_longest = length
                    second_road = path
            if second_road is not None:
                pts2 = list(second_road.points)
                market_x = float(getattr(layout_for_fallback.market, "x", 0.0))
                market_y = float(getattr(layout_for_fallback.market, "y", 0.0))
                existing_outer2 = max(
                    math.hypot(px - market_x, py - market_y)
                    for px, py in post_first_built_xy
                )
                target_d2 = max(existing_outer2 + 18.0, float(size) * 0.55, 80.0)
                target_d2 = min(target_d2, float(size) * 0.85)
                anchor_xy2 = None
                best_err = float("inf")
                for a, b in zip(pts2, pts2[1:]):
                    seg_len = math.hypot(b.x - a.x, b.y - a.y)
                    if seg_len < 1e-3:
                        continue
                    for k_step in range(11):
                        t = k_step / 10.0
                        px = a.x + (b.x - a.x) * t
                        py = a.y + (b.y - a.y) * t
                        d_market = math.hypot(px - market_x, py - market_y)
                        if d_market < target_d2 - 6.0:
                            continue
                        err = abs(d_market - target_d2)
                        if err < best_err:
                            best_err = err
                            seg_angle = math.atan2(b.y - a.y, b.x - a.x)
                            anchor_xy2 = (px, py, seg_angle)
                if anchor_xy2 is not None:
                    ax3, ay3, road_angle2 = anchor_xy2
                    outskirt_count2 = 4
                    spacing2 = 6.5
                    side_offset2 = max(road_width * 1.8, 7.0)
                    fallback_rng3 = random.Random(int(seed) + 909091)
                    for oi in range(outskirt_count2):
                        side = 1.0 if (oi % 2 == 0) else -1.0
                        along = (oi - (outskirt_count2 - 1) / 2.0) * spacing2
                        perp = (-math.sin(road_angle2), math.cos(road_angle2))
                        hx = ax3 + math.cos(road_angle2) * along + perp[0] * side_offset2 * side
                        hy = ay3 + math.sin(road_angle2) * along + perp[1] * side_offset2 * side
                        if abs(hx) >= float(size) * 0.95 or abs(hy) >= float(size) * 0.95:
                            continue
                        role_name = str(sample_role(hx, hy) or "").lower()
                        if "water" in role_name or "basin_floor" in role_name:
                            continue
                        if any(
                            (hx - rx) ** 2 + (hy - ry) ** 2 < (3.6 + rr) ** 2
                            for rx, ry, rr, _ in reserved_footprints
                        ):
                            continue
                        house_proto = fallback_rng3.choice(prototypes["house"])
                        hz = float(height_at(hx, hy))
                        house_scale = fallback_rng3.uniform(0.92, 1.10)
                        rot_z = road_angle2 + (math.pi if side > 0 else 0.0) + fallback_rng3.uniform(-0.10, 0.10)
                        _copy_template_object(
                            house_proto,
                            name=f"StrataWFCOutskirt2_house_{oi:02d}",
                            x=hx, y=hy, z=hz,
                            scale=(house_scale, house_scale, house_scale),
                            rot_z=rot_z,
                        )
                        reserved_footprints.append((hx, hy, 3.6, f"outskirt2_house_{oi}"))
                        occupied.append((hx, hy, 3.6, f"outskirt2_house_{oi}"))
                        _bump_count(spawned_counts, "wfc_primary_outskirt_house", 1)
                        report["placed"] += 1
                        report["by_kind"]["house"] = int(report["by_kind"].get("house", 0)) + 1
                        report["by_zone"]["roadside_outskirt"] = int(report["by_zone"].get("roadside_outskirt", 0)) + 1
                        placed_positions.append(("house", "roadside_outskirt", hx, hy))
                        second_outskirt_houses.append((hx, hy))
                    second_outskirt_used = bool(second_outskirt_houses)

        def nearest_distance(values: list[tuple[str, str, float, float]], *, kind_filter: set[str] | None = None) -> float | None:
            pts = [(x, y) for kind, _zone, x, y in values if kind_filter is None or kind in kind_filter]
            if len(pts) < 2:
                return None
            total = 0.0
            for idx, (x, y) in enumerate(pts):
                best = min(
                    math.hypot(x - ox, y - oy)
                    for other_idx, (ox, oy) in enumerate(pts)
                    if other_idx != idx
                )
                total += best
            return total / len(pts)

        house_count = int(report["by_kind"].get("house", 0))
        market_count = int(report["by_kind"].get("stall", 0)) + int(report["by_zone"].get("tile_wfc_market", 0))
        fence_count = int(report["by_kind"].get("fence", 0))
        prop_count = sum(int(report["by_kind"].get(kind, 0)) for kind in ("barrel", "crate", "signage", "lantern", "haystack"))
        castle_visual_piece_count = (
            int(report["by_kind"].get("castle_wfc_piece", 0))
            + int(report["by_kind"].get("castle_wall_segment", 0))
            + int(report["by_kind"].get("castle_gatehouse", 0))
        )

        # ---- Spatial coherence metrics ----
        # Built positions = houses + stalls. Bbox-only metrics can lie when an
        # outlier sits far from the rest, so we compute both the global bbox
        # fraction and a sum-of-component-bboxes fraction; both must be
        # reasonable for the settlement to read as coherent.
        built_positions = [
            (px, py)
            for k, _z, px, py in placed_positions
            if k in {"house", "stall", "castle_wfc", "gatehouse", "castle_wall"}
        ]
        stall_positions = [
            (px, py)
            for k, _z, px, py in placed_positions
            if k == "stall"
        ]
        component_eps = max(20.0, road_width * 4.5)

        def _components(positions: list[tuple[float, float]], eps: float) -> list[list[int]]:
            count = len(positions)
            visited = [False] * count
            comps: list[list[int]] = []
            eps_sq = float(eps) * float(eps)
            for start in range(count):
                if visited[start]:
                    continue
                stack = [start]
                comp: list[int] = []
                while stack:
                    node = stack.pop()
                    if visited[node]:
                        continue
                    visited[node] = True
                    comp.append(node)
                    nx, ny = positions[node]
                    for j in range(count):
                        if not visited[j]:
                            jx, jy = positions[j]
                            if (nx - jx) * (nx - jx) + (ny - jy) * (ny - jy) <= eps_sq:
                                stack.append(j)
                comps.append(comp)
            return comps

        comps = _components(built_positions, component_eps)
        n_built_components = len(comps) if built_positions else 0

        if stall_positions and len(stall_positions) >= 2:
            market_compactness = max(
                math.hypot(a[0] - b[0], a[1] - b[1])
                for a_idx, a in enumerate(stall_positions)
                for b in stall_positions[a_idx + 1:]
            )
        else:
            market_compactness = 0.0 if stall_positions else None

        layout_road_paths = list(getattr(layout, "road_paths", []) or [])

        def _path_distance(px: float, py: float) -> float:
            if not layout_road_paths:
                return 10**9
            return min(
                _point_polyline_distance(float(px), float(py), path.points)
                for path in layout_road_paths
                if len(path.points) >= 2
            )

        if built_positions:
            road_adj_threshold = max(road_width * 2.6, 12.0)
            near_count = sum(
                1 for px, py in built_positions
                if _path_distance(px, py) <= road_adj_threshold
            )
            road_adjacency_rate = round(near_count / len(built_positions), 3)
        else:
            road_adjacency_rate = None

        # ---- v9: road-graph-based district metric ----------------------
        # The DBSCAN-based count collapses to 1 when the LLM authors a
        # tight settlement (one big component). v9 derives district
        # connectivity from the *planned* layout.districts and road graph,
        # and reports occupancy as a separate signal. Semantic gate
        # downstream uses the road-graph metric, not the DBSCAN one.
        planned_district_count = 0
        road_graph_connected_district_count = 0
        disconnected_planned_district_count = 0
        occupied_district_count = 0
        district_occupancy_by_role: dict[str, int] = {}
        if layout is not None:
            planned_districts = list(getattr(layout, "districts", None) or [])
            planned_district_count = len(planned_districts)
            for district in planned_districts:
                d_road = float("inf")
                for path in layout_road_paths:
                    pts = list(getattr(path, "points", []) or [])
                    if len(pts) < 2:
                        continue
                    for a, b in zip(pts, pts[1:]):
                        d_road = min(d_road, _point_segment_distance(
                            float(district.x), float(district.y),
                            float(a.x), float(a.y), float(b.x), float(b.y),
                        ))
                if d_road <= road_adj_threshold + 14.0:
                    road_graph_connected_district_count += 1
                else:
                    disconnected_planned_district_count += 1
                inside_count = sum(
                    1 for px, py in built_positions
                    if math.hypot(px - float(district.x), py - float(district.y))
                    <= float(getattr(district, "radius", 16.0)) * 1.20
                )
                if inside_count > 0:
                    occupied_district_count += 1
                    role = str(getattr(district, "role", "unknown") or "unknown")
                    district_occupancy_by_role[role] = (
                        int(district_occupancy_by_role.get(role, 0)) + inside_count
                    )

        # DBSCAN-based diagnostic — kept so "isolated_building_count" can
        # still flag pathological scatter cases. NOT used by the v9
        # semantic gate.
        road_connected_district_count = 0
        isolated_building_count = 0
        district_centroids: list[tuple[float, float]] = []
        if built_positions and comps:
            market_xy = (float(getattr(layout.market, "x", 0.0)), float(getattr(layout.market, "y", 0.0)))
            district_thresh = road_adj_threshold + 8.0
            # v6: widened from 0.55 → 0.85 of half-size. Component centroids
            # at 60-90 BU from market need to count as connected, not
            # isolated. The road graph reaches every cluster anyway, so
            # the gate is really about "is this component near the
            # settlement nucleus?".
            settlement_outer_radius = max(110.0, float(size) * 0.85)
            for comp in comps:
                if not comp:
                    continue
                cxs = [built_positions[i][0] for i in comp]
                cys = [built_positions[i][1] for i in comp]
                cx = sum(cxs) / len(cxs)
                cy = sum(cys) / len(cys)
                d_road = _path_distance(cx, cy)
                d_market = math.hypot(cx - market_xy[0], cy - market_xy[1])
                if d_road <= district_thresh and d_market <= settlement_outer_radius:
                    road_connected_district_count += 1
                    district_centroids.append((cx, cy))
                else:
                    isolated_building_count += len(comp)

        # Market square readability — derived from stall compactness and
        # count. v5 cares whether a reader sees a plaza, not just whether
        # stalls happen to be near each other.
        stall_count = len(stall_positions)
        if stall_count >= 6 and market_compactness is not None and market_compactness <= 18.0:
            market_square_readability = "strong"
        elif stall_count >= 4 and market_compactness is not None and market_compactness <= 26.0:
            market_square_readability = "medium"
        elif stall_count >= 3 and market_compactness is not None and market_compactness <= 36.0:
            market_square_readability = "medium"
        else:
            market_square_readability = "weak"

        # v6 plaza-readability debug fields. plaza_radius comes from the
        # market hero pad (the same pad that gets the plaza tint).
        plaza_center: tuple[float, float] = (
            float(getattr(layout.market, "x", 0.0)),
            float(getattr(layout.market, "y", 0.0)),
        )
        market_pads = [
            p for p in (getattr(layout, "hero_pads", None) or [])
            if str(getattr(p, "role", "")).lower() in {"market_pad", "plaza_pad"}
        ]
        if market_pads:
            mp = market_pads[0]
            plaza_radius = float(max(float(mp.radius_x), float(mp.radius_y)))
        else:
            plaza_radius = 14.0
        plaza_area = math.pi * plaza_radius * plaza_radius

        def _within(point: tuple[float, float], radius: float) -> bool:
            return math.hypot(point[0] - plaza_center[0], point[1] - plaza_center[1]) <= radius

        stalls_adjacent_to_plaza_count = sum(
            1 for px, py in stall_positions if _within((px, py), plaza_radius * 1.3)
        )
        # Count road paths whose nearest endpoint or midpoint lies inside
        # the plaza outer ring. We only need 2 to call it "connected".
        roads_connected_to_plaza_count = 0
        for path in layout_road_paths:
            pts = list(getattr(path, "points", []) or [])
            if not pts:
                continue
            samples = [(float(p.x), float(p.y)) for p in pts]
            # Midpoint of the path is a useful sample — settlement spokes
            # have their midpoint between market and a district anchor.
            mid = samples[len(samples) // 2]
            if _within(samples[0], plaza_radius * 1.4) or _within(samples[-1], plaza_radius * 1.4) or _within(mid, plaza_radius * 1.4):
                roads_connected_to_plaza_count += 1
        house_positions = [
            (px, py)
            for k, _z, px, py in placed_positions
            if k == "house"
        ]
        houses_facing_plaza_count = sum(
            1 for px, py in house_positions if _within((px, py), plaza_radius * 1.8)
        )
        # Plaza "open center" means no large props inside the inner 40% of
        # the plaza other than the well. Sample placed_positions inside
        # that inner radius.
        inner_radius = plaza_radius * 0.4
        objects_inside_open_center = [
            (k, px, py)
            for k, _z, px, py in placed_positions
            if k in {"stall", "house", "fence", "cart", "haystack", "boulder"}
            and math.hypot(px - plaza_center[0], py - plaza_center[1]) <= inner_radius
        ]
        plaza_open_center_clear = len(objects_inside_open_center) <= 1

        map_area = max((2.0 * float(size)) ** 2, 1.0)
        if built_positions:
            xs = [p[0] for p in built_positions]
            ys = [p[1] for p in built_positions]
            bbox_area = max(max(xs) - min(xs), 1.0) * max(max(ys) - min(ys), 1.0)
            bbox_footprint_fraction = round(bbox_area / map_area, 4)
            occupied = 0.0
            for comp in comps:
                if not comp:
                    continue
                cxs = [built_positions[i][0] for i in comp]
                cys = [built_positions[i][1] for i in comp]
                occupied += max(max(cxs) - min(cxs), 1.0) * max(max(cys) - min(cys), 1.0)
            occupied_cluster_fraction = round(occupied / map_area, 4)
        else:
            bbox_footprint_fraction = None
            occupied_cluster_fraction = None

        # Kind-aware thresholds: hamlets should not be punished for being
        # small. The semantic_read string now reflects spatial coherence rather
        # than just object volume.
        settlement_kind_str = str(getattr(layout, "kind", "market_town") or "market_town").lower()
        resolution_payload = getattr(layout, "_strata_resolution", {}) or {}
        settlement_archetype = str(
            resolution_payload.get("settlement_archetype")
            or _settlement_archetype_for_kind(
                settlement_kind_str,
                prompt=os.environ.get("SONGE_MAQUETTE_USER_PROMPT", ""),
            )
        ).lower()
        is_castle_archetype = settlement_archetype == "castle_outpost"
        is_oasis_archetype = settlement_archetype == "oasis_bazaar"
        is_coastal_archetype = settlement_archetype == "coastal_village"
        is_small_archetype = (
            "hamlet" in settlement_kind_str
            or "farm" in settlement_kind_str
            or is_oasis_archetype
        )
        if is_castle_archetype:
            thresh_footprint = 0.005
            thresh_components_max = 3
            thresh_market_compact = 999.0
            min_houses_strong = 3
        elif is_small_archetype:
            thresh_footprint = 0.04
            thresh_components_max = 1
            thresh_market_compact = 28.0
            min_houses_strong = 6
        elif is_coastal_archetype:
            thresh_footprint = 0.07
            thresh_components_max = 2
            thresh_market_compact = 34.0
            min_houses_strong = 8
        elif "village" in settlement_kind_str:
            thresh_footprint = 0.08
            thresh_components_max = 2
            thresh_market_compact = 32.0
            min_houses_strong = 12
        else:
            thresh_footprint = 0.12
            thresh_components_max = 3
            thresh_market_compact = 36.0
            min_houses_strong = 18
        thresh_road_adj = 0.65

        # v5: road-connected districts replace the raw component count.
        # market_town wants 2-3 such districts; smaller kinds allow 1.
        if is_small_archetype:
            thresh_road_districts_lo, thresh_road_districts_hi = 1, 2
        elif is_castle_archetype:
            thresh_road_districts_lo, thresh_road_districts_hi = 2, 4
        elif is_coastal_archetype or "village" in settlement_kind_str:
            thresh_road_districts_lo, thresh_road_districts_hi = 1, 3
        else:
            thresh_road_districts_lo, thresh_road_districts_hi = 2, 3
        thresh_isolated_max = 2

        hero_landmark_obj = (
            getattr(layout_for_plaza, "hero_landmark", None)
            if layout_for_plaza is not None else None
        )
        hero_landmark_honoured = bool(
            hero_landmark_obj is not None
            and any(
                (rx - float(getattr(hero_landmark_obj, "x", 0.0))) ** 2
                + (ry - float(getattr(hero_landmark_obj, "y", 0.0))) ** 2
                < 4.0 ** 2
                for rx, ry, _rr, _label in reserved_footprints
            )
        )
        castle_keep_on_high_ground_ok = (
            not is_castle_archetype
            or (
                hero_landmark_obj is not None
                and str(getattr(hero_landmark_obj, "kind", "")).lower() in {"keep", "watchtower", "tower"}
                and bool(getattr(hero_landmark_obj, "prominence_ok", False))
            )
        )
        castle_gatehouse_present_ok = (
            not is_castle_archetype
            or bool(castle_gatehouse_present)
            or int(district_occupancy_by_role.get("gatehouse", 0)) > 0
            or any(
                str(getattr(district, "role", "")).lower() == "gatehouse"
                for district in (getattr(layout, "districts", None) or [])
            )
        )
        castle_wall_segments_present_ok = (
            not is_castle_archetype
            or castle_wall_segments_placed >= 4
        )
        castle_district_spread_ok = (
            not is_castle_archetype
            or occupied_district_count >= 2
            or road_graph_connected_district_count >= 2
        )
        requires_market_square = (
            settlement_archetype == "market_town"
            or (kind_allows_plaza and not is_castle_archetype and not is_coastal_archetype)
        )
        required_planned_districts = (
            max(thresh_road_districts_lo, 2)
            if (settlement_archetype == "market_town" or is_castle_archetype)
            else thresh_road_districts_lo
        )

        checks = {
            "footprint_ok": (
                bbox_footprint_fraction is not None
                and bbox_footprint_fraction >= thresh_footprint
            ),
            "components_ok": (
                bool(built_positions)
                and 1 <= n_built_components <= thresh_components_max
            ),
            "market_compact_ok": (
                market_compactness is None
                or market_compactness <= thresh_market_compact
            ),
            "road_adjacency_ok": (
                road_adjacency_rate is None
                or road_adjacency_rate >= thresh_road_adj
            ),
            "volume_ok": house_count >= min_houses_strong,
            "castle_volume_ok": (
                not is_castle_archetype
                or castle_visual_piece_count >= 8
                or house_count >= min_houses_strong
            ),
            "road_connected_districts_ok": (
                # v9: gate on the road-graph metric (planned districts +
                # occupied) rather than the DBSCAN component count.
                # market_town and castle_outpost need ≥2 planned districts;
                # hamlet/oasis/fishing-village can be coherent with one.
                planned_district_count >= required_planned_districts
                and disconnected_planned_district_count == 0
                and occupied_district_count >= required_planned_districts
            ),
            "isolated_buildings_ok": isolated_building_count <= thresh_isolated_max,
            "market_square_readable_ok": (
                not requires_market_square
                or market_square_readability in {"medium", "strong"}
            ),
            "castle_keep_on_high_ground_ok": bool(castle_keep_on_high_ground_ok),
            "castle_gatehouse_present_ok": bool(castle_gatehouse_present_ok),
            "castle_wall_segments_present_ok": bool(castle_wall_segments_present_ok),
            "castle_district_spread_ok": bool(castle_district_spread_ok),
        }
        passes = sum(1 for value in checks.values() if value)
        # v5: strong requires ALL the new spatial checks to pass on top of
        # the volume + footprint checks. Medium remains a "most checks pass"
        # bucket; weak is reserved for scenes that need rework.
        if is_castle_archetype and (
            checks["footprint_ok"]
            and checks["road_connected_districts_ok"]
            and checks["isolated_buildings_ok"]
            and checks["castle_keep_on_high_ground_ok"]
            and checks["castle_gatehouse_present_ok"]
            and checks["castle_wall_segments_present_ok"]
            and checks["castle_district_spread_ok"]
            and checks["castle_volume_ok"]
        ):
            semantic_read = "strong"
        elif (
            passes >= 8
            and checks["footprint_ok"]
            and checks["market_compact_ok"]
            and checks["road_adjacency_ok"]
            and checks["road_connected_districts_ok"]
            and checks["isolated_buildings_ok"]
            and checks["market_square_readable_ok"]
        ):
            semantic_read = "strong"
        elif passes >= 5:
            semantic_read = "medium"
        else:
            semantic_read = "weak"

        report["metrics"] = {
            **reject_metrics,
            "house_count": house_count,
            "market_core_count": market_count,
            "fence_count": fence_count,
            "prop_count": prop_count,
            "castle_visual_piece_count": int(castle_visual_piece_count),
            "house_to_fence_ratio": round(house_count / max(fence_count, 1), 3),
            "house_nearest_avg": (
                round(value, 3) if (value := nearest_distance(placed_positions, kind_filter={"house"})) is not None else None
            ),
            "all_nearest_avg": (
                round(value, 3) if (value := nearest_distance(placed_positions)) is not None else None
            ),
            "n_built_components": int(n_built_components),
            "market_compactness": (round(float(market_compactness), 3) if market_compactness is not None else None),
            "road_adjacency_rate": road_adjacency_rate,
            "bbox_footprint_fraction": bbox_footprint_fraction,
            "occupied_cluster_fraction": occupied_cluster_fraction,
            "road_connected_district_count": int(road_connected_district_count),
            "planned_district_count": int(planned_district_count),
            "road_graph_connected_district_count": int(road_graph_connected_district_count),
            "disconnected_planned_district_count": int(disconnected_planned_district_count),
            "occupied_district_count": int(occupied_district_count),
            "district_occupancy_by_role": dict(district_occupancy_by_role),
            "isolated_building_count": int(isolated_building_count),
            "market_square_readability": str(market_square_readability),
            # v8 reordering: the plaza ring is authored BEFORE the WFC
            # main loop, so "wfc_stalls" is the count placed by the WFC
            # pass alone (zone != "authored_plaza"). The total is the sum.
            "wfc_stalls": int(sum(
                1 for k, z, _x, _y in placed_positions
                if k == "stall" and z != "authored_plaza"
            )),
            # v9: WFC's role. For market_town we author the plaza BEFORE
            # the WFC loop and rely on density_fill + outskirt fallbacks
            # for footprint, so the WFC is "variation" — it adds local
            # detail but doesn't determine whether the town reads. For
            # non-market-town kinds the WFC stays load-bearing.
            "wfc_role": (
                "variation" if (
                    authored_plaza_used and kind_allows_plaza
                ) else "load_bearing"
            ),
            "authored_market_plaza_used": bool(authored_plaza_used),
            "authored_plaza_fallback_used": bool(authored_plaza_used),
            "authored_plaza_stall_count": int(len(authored_plaza_stalls)),
            # v2-4: which settlement archetype actually fired. Reads
            # "market_town" by default; "castle_outpost" routes the layout
            # to keep-on-high-ground + gatehouse + garrison and skips the
            # plaza ring.
            "settlement_archetype": settlement_archetype,
            "kind_allows_plaza": bool(kind_allows_plaza),
            "castle_compound_used": bool(castle_compound_used),
            "castle_wfc_used": bool(castle_wfc_used),
            "castle_wfc_piece_count": int(castle_wfc_piece_count),
            "castle_wfc_mesh_object_count": int(castle_wfc_mesh_object_count),
            "castle_wfc_archetype": castle_wfc_archetype,
            "castle_wfc_theme": castle_wfc_theme,
            "castle_wfc_error": castle_wfc_error,
            "castle_wall_segments_attempted": int(castle_wall_segments_attempted),
            "castle_wall_segments_placed": int(castle_wall_segments_placed),
            "castle_gatehouse_tower_count": int(castle_gatehouse_tower_count),
            "castle_gatehouse_present": bool(castle_gatehouse_present),
            # v2-5: hero landmark recommendation + whether the build script
            # actually reserved a footprint near it. Build scripts are
            # expected to consult layout.hero_landmark and reserve_footprint
            # at that position with radius near recommended_scale * 3 BU.
            "hero_landmark": (
                {
                    "kind": hero_landmark_obj.kind,
                    "x": round(float(hero_landmark_obj.x), 3),
                    "y": round(float(hero_landmark_obj.y), 3),
                    "z": round(float(hero_landmark_obj.z), 3),
                    "recommended_scale": round(
                        float(hero_landmark_obj.recommended_scale), 3
                    ),
                    "prominence_ok": bool(
                        hero_landmark_obj.prominence_ok
                    ),
                    "reason": hero_landmark_obj.reason,
                    "honoured": hero_landmark_honoured,
                }
                if hero_landmark_obj is not None
                else None
            ),
            "plaza_slots_attempted": int(plaza_slots_attempted),
            "plaza_slots_placed": int(plaza_slots_placed),
            "plaza_slots_rejected": int(plaza_slots_rejected),
            "plaza_rejection_reasons": list(plaza_rejection_reasons[:20]),
            "total_stalls_after_fallback": int(stall_count),
            "market_square_readability_after_fallback": str(market_square_readability),
            "outskirt_district_used": bool(outskirt_houses),
            "outskirt_building_count": int(len(outskirt_houses)),
            "outskirt_connected_to_plaza": bool(outskirt_connected_to_plaza),
            "outskirt_support_kinds": list(outskirt_support),
            "outskirt_road_label": outskirt_road_label,
            "footprint_before_outskirts": round(float(footprint_before_outskirts or 0.0), 4),
            "footprint_after_outskirts": round(float(bbox_footprint_fraction or 0.0), 4) if bbox_footprint_fraction is not None else None,
            "outskirt_expanded_bbox": bool(
                bbox_footprint_fraction is not None
                and footprint_before_outskirts is not None
                and (bbox_footprint_fraction - float(footprint_before_outskirts)) >= 0.01
            ),
            "footprint_before_density_expansion": round(float(post_first_footprint or 0.0), 4) if 'post_first_footprint' in dir() else None,
            "footprint_after_density_expansion": round(float(bbox_footprint_fraction or 0.0), 4) if bbox_footprint_fraction is not None else None,
            "density_expansion_used": bool(second_outskirt_used) if 'second_outskirt_used' in dir() else False,
            "density_expansion_kind": "second_outskirt_anchor" if ('second_outskirt_used' in dir() and second_outskirt_used) else None,
            "density_expansion_connected_to_plaza": bool(second_outskirt_used) if 'second_outskirt_used' in dir() else False,
            "extra_buildings_added": int(len(second_outskirt_houses)) if 'second_outskirt_houses' in dir() else 0,
            "plaza_center": [round(plaza_center[0], 3), round(plaza_center[1], 3)],
            "plaza_radius": round(float(plaza_radius), 3),
            "plaza_area": round(float(plaza_area), 3),
            "stalls_adjacent_to_plaza_count": int(stalls_adjacent_to_plaza_count),
            "roads_connected_to_plaza_count": int(roads_connected_to_plaza_count),
            "houses_facing_plaza_count": int(houses_facing_plaza_count),
            "plaza_open_center_clear": bool(plaza_open_center_clear),
            "semantic_checks": {key: bool(value) for key, value in checks.items()},
            "semantic_read": semantic_read,
        }
        write_report()
        if report["requested"] and report["placed"] < max(6, min(18, report["requested"] // 4)):
            if omitted_due_to_limit is not None:
                omitted_due_to_limit.append({
                    "kind": "wfc_primary_settlement",
                    "requested": report["requested"],
                    "spawned": report["placed"],
                    "reason": "wfc_spacing_or_factory_limit",
                })
        return report

    def place_enrichment_features(
        layout: SettlementLayout | None = None,
        *,
        spawned_counts: dict[str, int] | None = None,
        planned_counts: dict[str, int] | None = None,
        omitted_due_to_limit: list[dict[str, Any]] | None = None,
        max_objects: int | None = None,
    ) -> dict[str, Any]:
        """Instantiate enrichment secondary features after primary placement.

        Loads ``strata_scene_enrichment.json`` from the run root (the parent
        of ``MAQUETTE_OUT_DIR``) and dispatches each active feature to a
        pure planner in ``app.pipeline.enrichment.placers``. Each planned
        object is instantiated via the existing Songe Forge factory bank
        and the footprint is reserved so later density fill steps stay
        clear. Writes ``strata_enrichment_runtime_report.json`` next to
        the sidecar with per-feature attempt/placed/skipped counts.

        Returns the same payload that's written to the report sidecar.
        """

        out_dir_env = os.environ.get("MAQUETTE_OUT_DIR")
        # The sidecar is one level above MAQUETTE_OUT_DIR (it lives at
        # run root). Fall back to MAQUETTE_OUT_DIR itself for older runs.
        sidecar_payload: dict[str, Any] | None = None
        sidecar_candidates: list[Path] = []
        if out_dir_env:
            sidecar_candidates.append(Path(out_dir_env).parent / "strata_scene_enrichment.json")
            sidecar_candidates.append(Path(out_dir_env) / "strata_scene_enrichment.json")
        for path in sidecar_candidates:
            try:
                if path.is_file():
                    sidecar_payload = json.loads(path.read_text(encoding="utf-8"))
                    break
            except Exception:  # noqa: BLE001
                continue

        report: dict[str, Any] = {
            "enabled": True,
            "mode": "faithful",
            "biome": "",
            "primary_theme": "",
            "features": [],
            "ground_patches_painted": 0,
            "camera_anchors": [],
            "prompt_requested_water": False,
            "incidental_water_present": bool(primary_water is not None),
            "water_used_as_camera_anchor": False,
            "ignored_incidental_water": False,
            "unsupported_aliases": [],
            "overlap_rejects": 0,
            "budget_rejects": 0,
            "notes": [],
        }

        def _write_runtime_report() -> None:
            if not out_dir_env:
                return
            try:
                Path(out_dir_env, "strata_enrichment_runtime_report.json").write_text(
                    json.dumps(report, indent=2),
                    encoding="utf-8",
                )
            except Exception:  # noqa: BLE001
                pass

        if sidecar_payload is None:
            report["enabled"] = False
            report["notes"].append("no_enrichment_sidecar")
            _write_runtime_report()
            return report

        report["mode"] = str(sidecar_payload.get("mode", "faithful"))
        report["biome"] = str(sidecar_payload.get("biome", ""))
        report["primary_theme"] = str(sidecar_payload.get("primary_theme", ""))
        report["prompt_requested_water"] = bool(sidecar_payload.get("prompt_requested_water"))
        report["water_used_as_camera_anchor"] = bool(report["prompt_requested_water"])
        report["ignored_incidental_water"] = bool(
            report["incidental_water_present"] and not report["prompt_requested_water"]
        )
        # ``visible_in_camera`` is recorded BEFORE we hide the water so the
        # report reflects "we needed to suppress" not "no water existed".
        report["incidental_water_visible_in_camera"] = bool(report["ignored_incidental_water"])
        report["incidental_water_suppressed_or_hidden"] = False
        # v5: physically hide incidental water meshes so they don't show
        # up in the final render when the prompt didn't ask for water.
        # The camera_composition step already drops water as a camera
        # anchor, but the mesh remains in the scene and can still be
        # visible from oblique angles.
        if report["ignored_incidental_water"]:
            hidden = 0
            for water_obj in water_objs:
                try:
                    if water_obj is None:
                        continue
                    if not water_obj.hide_render:
                        water_obj.hide_render = True
                        hidden += 1
                    # Move below terrain as a second line of defense in
                    # case some downstream pass clears the hide flag.
                    water_obj.location.z = float(water_obj.location.z) - 1000.0
                except Exception:  # noqa: BLE001
                    continue
            if hidden:
                report["incidental_water_suppressed_or_hidden"] = True
                report["notes"].append(f"hid_incidental_water:{hidden}")

        secondary = list(sidecar_payload.get("secondary_features") or [])
        if not secondary or report["mode"] == "faithful":
            report["notes"].append("no_active_features")
            _write_runtime_report()
            return report

        try:
            from app.pipeline.enrichment import (
                PLACERS,
                PlacementContext,
                SimplePoint,
                SimpleRoad,
                resolve_factory,
                UNSUPPORTED,
            )
        except ImportError:
            # Fallback: songe-core sits two levels above _artifacts/, which
            # is parents[5] from runtime/strata_bridge.py. We also probe a
            # couple of nearby candidates so the helper survives a small
            # repo-layout shift without losing enrichment.
            import sys
            here = Path(__file__).resolve()
            candidates: list[Path] = []
            for depth in (5, 6, 4, 7):
                try:
                    candidates.append(here.parents[depth] / "songe-core")
                except IndexError:
                    continue
            for candidate in candidates:
                if (candidate / "app" / "pipeline" / "enrichment").is_dir():
                    sys.path.insert(0, str(candidate))
                    break
            try:
                from app.pipeline.enrichment import (
                    PLACERS,
                    PlacementContext,
                    SimplePoint,
                    SimpleRoad,
                    resolve_factory,
                    UNSUPPORTED,
                )
            except Exception as exc:  # noqa: BLE001
                report["notes"].append(f"enrichment_module_unavailable:{exc}")
                _write_runtime_report()
                return report
        except Exception as exc:  # noqa: BLE001
            report["notes"].append(f"enrichment_module_unavailable:{exc}")
            _write_runtime_report()
            return report

        active_layout = layout if layout is not None else settlement_layout(
            kind=str(sidecar_payload.get("primary_theme") or "market_town"),
        )

        ctx = PlacementContext(
            seed=int(seed),
            map_size=float(size),
            market=SimplePoint(
                x=float(active_layout.market.x),
                y=float(active_layout.market.y),
                role="market",
                name=str(active_layout.market.name),
            ),
            house_clusters=tuple(
                SimplePoint(x=float(c.x), y=float(c.y), role="house_cluster", name=str(c.name))
                for c in active_layout.house_clusters
            ),
            road_paths=tuple(
                SimpleRoad(
                    points=tuple(
                        SimplePoint(x=float(p.x), y=float(p.y))
                        for p in path.points
                    ),
                    width=float(path.width),
                )
                for path in (active_layout.road_paths or [])
                if len(path.points) >= 2
            ),
            has_primary_water=bool(primary_water is not None),
            primary_water_center=(
                (float(primary_water.x), float(primary_water.y))
                if primary_water is not None else None
            ),
            primary_water_radius=(
                float(primary_water.radius) if primary_water is not None else 0.0
            ),
            occupied=tuple(
                (float(ox), float(oy), float(orad))
                for ox, oy, orad, _label in reserved_footprints
            ),
            is_dry=lambda x, y: _settlement_wfc_is_dry(float(x), float(y), water_buffer=2.0),
        )

        # Per-feature budget so a single planner can't eat the scene.
        per_feature_cap = 24
        remaining_cap = max(0, int(terrain.object_budget.get("max_objects", 1300)) - _total_count(spawned_counts))
        global_cap = max_objects if max_objects is not None else min(remaining_cap, 80)
        placed_total = 0
        rng = random.Random(int(seed) + 71117)

        # Prototype prep — shared bank for the cheap kinds used by placers.
        try:
            from infinigen.maquette.factories.boulder import LowPolyBoulderFactory
        except Exception:
            LowPolyBoulderFactory = None  # type: ignore[assignment]

        prototype_cache: dict[str, list[Any]] = {}

        def _make_prototype(label: str, idx: int) -> Any | None:
            module_class = resolve_factory(label)
            if not module_class or module_class.startswith(UNSUPPORTED):
                return None
            module_name, _, class_name = module_class.partition(":")
            try:
                import importlib

                module = importlib.import_module(module_name)
                cls = getattr(module, class_name)
                if label == "boulder":
                    return cls(
                        factory_seed=seed + 43000 + idx,
                        palette_color=rng.choice(["rock_warm", "rock_pale", "rock_shadow"]),
                        decimate_ratio=0.55,
                    ).spawn_asset(i=seed + 43000 + idx, loc=(0.0, 0.0, 0.0))
                # Most native factories share a common interface
                kwargs: dict[str, Any] = {"factory_seed": seed + 43000 + idx}
                if label == "wagon" or label == "cart":
                    kwargs["wagon_archetype"] = rng.choice(["covered", "buckboard", "handcart"])
                elif label == "haystack":
                    kwargs["haystack_archetype"] = rng.choice(["cone", "rounded_mound", "stacked_disks"])
                elif label == "fence":
                    kwargs["fence_archetype"] = rng.choice(["picket", "post_and_rail", "wooden_plank"])
                    kwargs["length"] = rng.uniform(2.4, 4.0)
                elif label == "crate":
                    kwargs["crate_archetype"] = rng.choice(["wooden", "fragile"])
                elif label == "barrel":
                    kwargs["barrel_archetype"] = rng.choice(["wooden", "metal_drum"])
                elif label == "lantern":
                    kwargs["lantern_archetype"] = rng.choice(["wooden_post", "iron_post", "stone_brazier"])
                elif label == "campfire":
                    kwargs["campfire_archetype"] = rng.choice(["stone_ring", "log_pile", "ember_bed"])
                elif label == "torch":
                    kwargs["torch_archetype"] = rng.choice(["pole", "wall_sconce", "tripod"])
                elif label == "candle_cluster":
                    kwargs["candle_archetype"] = rng.choice(["three_candles", "altar_row", "melted_cluster"])
                elif label == "string_lights":
                    kwargs["lights_archetype"] = rng.choice(["market_span", "festival_arc", "camp_line"])
                elif label == "signage":
                    kwargs["signage_archetype"] = rng.choice(["free_standing", "wall_plank"])
                elif label == "peasant":
                    kwargs["peasant_archetype"] = rng.choice(["farmer", "merchant", "guard", "child"])
                elif label == "farm_animal":
                    kwargs["animal_archetype"] = rng.choice(["sheep", "goat", "cow", "chicken"])
                elif label == "dock":
                    kwargs["dock_archetype"] = rng.choice(["straight_pier", "l_wharf", "fishing_wharf", "ruined_jetty"])
                elif label == "boat":
                    kwargs["boat_archetype"] = rng.choice(["rowboat", "dinghy"])
                elif label == "fish_rack":
                    kwargs["fish_rack_archetype"] = rng.choice(["single_rail", "triple_tier", "wide_double"])
                elif label == "town_gate":
                    kwargs["town_gate_archetype"] = rng.choice(["timber_palisade", "stone_arch", "watch_gate", "ruined_gate"])
                elif label == "stone_bridge":
                    kwargs["stone_bridge_archetype"] = rng.choice(["single_arch", "double_arch", "ruined_arch"])
                elif label == "chapel":
                    kwargs["chapel_archetype"] = rng.choice(["village_chapel", "alpine_chapel", "ruined_chapel"])
                elif label == "watermill":
                    kwargs["watermill_archetype"] = rng.choice(["timber_river", "stone_river", "half_timber_mill"])
                elif label == "ruin":
                    kwargs["ruin_archetype"] = rng.choice(["broken_walls", "column_scatter", "archway", "obelisk_fragment"])
                elif label == "tree":
                    kwargs["trunk_height"] = rng.uniform(4.7, 6.4)
                    kwargs["foliage_radius"] = rng.uniform(1.2, 1.9)
                    kwargs["coarse"] = True
                elif label == "wooden_bridge":
                    # Deck factory: simple low-poly deck
                    pass
                else:
                    kwargs["coarse"] = True
                return cls(**kwargs).create_asset(placeholder=None)
            except Exception as exc:  # noqa: BLE001
                return f"__factory_error__:{type(exc).__name__}:{exc}"

        def _get_prototype(label: str) -> Any | None:
            cache_entries = prototype_cache.get(label)
            if cache_entries is None:
                cache_entries = []
                for idx in range(3):
                    proto = _make_prototype(label, idx)
                    if isinstance(proto, str) and proto.startswith("__factory_error__"):
                        report["notes"].append(f"factory_error:{label}:{proto[18:]}")
                        break
                    if proto is None:
                        if label not in report["unsupported_aliases"]:
                            report["unsupported_aliases"].append(label)
                        break
                    _hide_template_object(proto)
                    cache_entries.append(proto)
                prototype_cache[label] = cache_entries
            return rng.choice(cache_entries) if cache_entries else None

        # Build a feature-kind → catalog metadata table so we can look up
        # min_visual_objects, target_footprint_area, fallback_kind without
        # round-tripping through the catalog module again.
        try:
            from app.pipeline.enrichment.catalog import CATALOG as _CATALOG
            biome_meta = {f.kind: f for f in _CATALOG.get(report["biome"], ())}
        except Exception:  # noqa: BLE001
            biome_meta = {}

        # Track which kinds we've already tried so a fallback can't recurse
        # back onto the same feature.
        attempted_kinds: set[str] = set()
        # Stash all ground patches across features; we paint them once at
        # the end so the tint pass runs over all enrichment in one go.
        all_patches: list[dict[str, Any]] = []
        camera_anchors: list[tuple[float, float, float]] = []
        market_pos = (float(active_layout.market.x), float(active_layout.market.y))

        def _process_feature(
            kind: str,
            origin: str,
            depth: int,
        ) -> dict[str, Any]:
            """Run one placer (with bounded fallback if it skips)."""
            nonlocal placed_total
            placer = PLACERS.get(kind)
            feature_report: dict[str, Any] = {
                "kind": kind,
                "origin": origin,
                "attempted": False,
                "placed_count": 0,
                "placed_kinds": [],
                "skipped_reason": None,
                "anchor": None,
                "reserved_footprint_count": 0,
                "ground_patch_count": 0,
                "footprint_area": 0.0,
                "distance_to_market": None,
                "in_camera_frame": False,
                "visual_read": "weak",
                "affects_camera": False,
                "notes": [],
            }
            if placer is None:
                feature_report["skipped_reason"] = "no_placer_for_kind"
                # v2-3: route to fallback even when the primary placer is
                # missing. The catalog declares `fallback_kind` per feature
                # and the test test_every_catalog_kind_terminates_in_real_placer
                # enforces that the chain reaches a real placer.
                fallback_kind = (
                    biome_meta[kind].fallback_kind if kind in biome_meta else None
                )
                if depth < 1 and fallback_kind and fallback_kind not in attempted_kinds:
                    feature_report["notes"].append(f"fallback_to:{fallback_kind}")
                return feature_report
            if kind in attempted_kinds:
                feature_report["skipped_reason"] = "already_attempted"
                return feature_report
            attempted_kinds.add(kind)
            if placed_total >= global_cap:
                feature_report["skipped_reason"] = "enrichment_budget_exhausted"
                return feature_report
            # Refresh ctx.occupied so the placer sees the current footprints.
            ctx_local = PlacementContext(
                seed=ctx.seed,
                map_size=ctx.map_size,
                market=ctx.market,
                house_clusters=ctx.house_clusters,
                road_paths=ctx.road_paths,
                has_primary_water=ctx.has_primary_water,
                primary_water_center=ctx.primary_water_center,
                primary_water_radius=ctx.primary_water_radius,
                occupied=tuple(
                    (float(ox), float(oy), float(orad))
                    for ox, oy, orad, _label in reserved_footprints
                ),
                is_dry=ctx.is_dry,
            )
            try:
                planned = placer(ctx_local)
            except Exception as exc:  # noqa: BLE001
                feature_report["attempted"] = True
                feature_report["skipped_reason"] = f"placer_error:{type(exc).__name__}:{exc}"
                return feature_report
            feature_report["attempted"] = bool(planned.attempted)
            feature_report["affects_camera"] = bool(planned.affects_camera)
            if planned.anchor is not None:
                feature_report["anchor"] = [float(planned.anchor[0]), float(planned.anchor[1])]
                feature_report["distance_to_market"] = round(
                    math.hypot(planned.anchor[0] - market_pos[0], planned.anchor[1] - market_pos[1]),
                    3,
                )
            if planned.skipped_reason:
                feature_report["skipped_reason"] = str(planned.skipped_reason)
                # Fallback dispatch (bounded depth).
                fallback_kind = (
                    biome_meta[kind].fallback_kind
                    if kind in biome_meta else planned.fallback_kind
                )
                if depth < 1 and fallback_kind and fallback_kind not in attempted_kinds:
                    feature_report["notes"].append(f"fallback_to:{fallback_kind}")
                    return feature_report  # outer loop will spawn fallback
                return feature_report

            placed_this_feature = 0
            kinds_used: list[str] = []
            for obj in planned.placed_objects:
                if placed_this_feature >= per_feature_cap or placed_total >= global_cap:
                    feature_report["notes"].append("feature_budget_exhausted")
                    report["budget_rejects"] += 1
                    break
                proto = _get_prototype(obj.kind)
                if proto is None:
                    feature_report["notes"].append(f"unsupported_alias:{obj.kind}")
                    continue
                if any(
                    (obj.x - rx) ** 2 + (obj.y - ry) ** 2 < (obj.footprint_radius + rr) ** 2
                    for rx, ry, rr, _ in reserved_footprints
                ):
                    report["overlap_rejects"] += 1
                    continue
                z = float(height_at(obj.x, obj.y))
                scale = obj.scale_hint
                _copy_template_object(
                    proto,
                    name=f"StrataEnrichment_{kind}_{obj.kind}_{placed_total:04d}",
                    x=obj.x,
                    y=obj.y,
                    z=z,
                    scale=(scale, scale, scale),
                    rot_z=float(obj.rot_z),
                )
                reserved_footprints.append(
                    (obj.x, obj.y, obj.footprint_radius, f"enrichment_{kind}")
                )
                kinds_used.append(obj.kind)
                _bump_count(spawned_counts, f"enrichment_{obj.kind}", 1)
                if planned_counts is not None:
                    _bump_count(planned_counts, f"enrichment_{obj.kind}", 1)
                placed_this_feature += 1
                placed_total += 1

            for patch in planned.ground_patches:
                all_patches.append(patch.as_payload())
            feature_report["ground_patch_count"] = len(planned.ground_patches)
            feature_report["placed_count"] = placed_this_feature
            feature_report["placed_kinds"] = sorted(set(kinds_used))
            feature_report["reserved_footprint_count"] = placed_this_feature
            feature_report["footprint_area"] = round(float(planned.footprint_area), 3)
            feature_report["visual_read"] = planned.visual_read()
            if placed_this_feature == 0 and not planned.ground_patches and not feature_report["skipped_reason"]:
                feature_report["skipped_reason"] = "all_planned_slots_blocked"
                # Trigger fallback when nothing landed.
                fallback_kind = (
                    biome_meta[kind].fallback_kind
                    if kind in biome_meta else planned.fallback_kind
                )
                if depth < 1 and fallback_kind and fallback_kind not in attempted_kinds:
                    feature_report["notes"].append(f"fallback_to:{fallback_kind}")
            # Camera anchor: include strong/medium features that say so.
            if planned.affects_camera and planned.anchor is not None:
                radius_estimate = max(
                    6.0,
                    math.sqrt(float(planned.footprint_area) / math.pi) if planned.footprint_area else 6.0,
                )
                camera_anchors.append(
                    (float(planned.anchor[0]), float(planned.anchor[1]), float(radius_estimate))
                )
            return feature_report

        # v4 processing order: smaller-footprint authored clusters before
        # bigger belt features so their objects aren't blocked by the
        # belt's fence/track reservations.
        process_priority = {
            "orchard": 0,
            "shrine_or_marker": 1,
            "chapel_landmark": 1,
            "cart_camp": 2,
            "boulder_outcrop": 3,
            "small_ruin": 3,
            "buried_ruins": 3,
            "ravine_bridge": 4,
            "stream_crossing": 4,
            "watermill": 4,
            "pond": 4,
            "farmland_belt": 9,
            "palm_grove_extension": 9,
        }

        def _order_key(payload: dict[str, Any]) -> int:
            return process_priority.get(str(payload.get("kind") or ""), 5)

        ordered_secondary = sorted(secondary, key=_order_key)

        for feature_payload in ordered_secondary:
            kind = str(feature_payload.get("kind") or "")
            primary_report = _process_feature(kind, origin="planned", depth=0)
            # Soft-skip rule: an enriched feature that landed only weak
            # should fall through to its fallback so the user doesn't
            # have an authored slot that the camera can't see.
            soft_skip = (
                primary_report.get("skipped_reason") is None
                and primary_report.get("visual_read") == "weak"
                and report["mode"] != "faithful"
            )
            if soft_skip:
                primary_report["notes"].append("weak_visual_read_triggers_fallback")
            report["features"].append(primary_report)
            # Trigger fallback if a fallback_to note was emitted OR if the
            # primary placement remained weak.
            fallback_note = next(
                (n for n in primary_report.get("notes", []) if n.startswith("fallback_to:")),
                None,
            )
            fallback_kind = None
            if fallback_note:
                fallback_kind = fallback_note.split(":", 1)[1]
            elif soft_skip:
                fallback_kind = (
                    biome_meta[kind].fallback_kind
                    if kind in biome_meta else None
                )
            if fallback_kind:
                fb_report = _process_feature(
                    fallback_kind, origin=f"fallback_of:{kind}", depth=1
                )
                report["features"].append(fb_report)

        # Single ground-patch tint pass after every feature has emitted its
        # patches. Painting once avoids stacking blend coefficients.
        if all_patches:
            try:
                painted = _paint_enrichment_ground_patches(
                    obj,
                    all_patches,
                    palette_name=palette_name,
                )
                report["ground_patches_painted"] = int(painted)
            except Exception as exc:  # noqa: BLE001
                report["notes"].append(f"ground_patch_paint_failed:{exc}")

        # Decide whether camera anchors landed inside the default frame
        # (within ~1.6 × settlement_radius from market center).
        settlement_radius = max(
            (
                math.hypot(c.x - active_layout.market.x, c.y - active_layout.market.y)
                for c in active_layout.house_clusters
            ),
            default=max(20.0, float(size) * 0.18),
        )
        frame_radius = settlement_radius * 1.6
        for feature_report in report["features"]:
            anchor = feature_report.get("anchor")
            if anchor is None:
                continue
            d = math.hypot(anchor[0] - market_pos[0], anchor[1] - market_pos[1])
            feature_report["in_camera_frame"] = bool(d <= frame_radius)

        for anchor in camera_anchors:
            report["camera_anchors"].append(
                {"x": round(anchor[0], 4), "y": round(anchor[1], 4), "radius": round(anchor[2], 4)}
            )

        _write_runtime_report()
        return report

    def _load_enrichment_water_flag() -> tuple[bool, bool]:
        """Return ``(prompt_requested_water, sidecar_found)``.

        Reads the enrichment sidecar (if any) so other helpers can default
        ``include_water`` correctly without relying on the LLM to remember.
        """
        out_dir_env = os.environ.get("MAQUETTE_OUT_DIR")
        if not out_dir_env:
            return False, False
        for path in (
            Path(out_dir_env).parent / "strata_scene_enrichment.json",
            Path(out_dir_env) / "strata_scene_enrichment.json",
        ):
            try:
                if path.is_file():
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    return bool(payload.get("prompt_requested_water")), True
            except Exception:  # noqa: BLE001
                continue
        return False, False

    def camera_composition(
        heroes: list[Any] | tuple[Any, ...] | None = None,
        *,
        include_water: bool | None = None,
    ) -> CameraComposition:
        """Build the lightweight Composition shape expected by camera.py.

        Accepts RegionAnchor, TerrainPoint, dicts with x/y/radius, or
        tuples like ``(x, y)`` / ``(x, y, radius)``. This keeps Strata-backed
        build scripts from passing ``None`` to place_scene_camera, which
        otherwise falls back to generic center framing and can miss the
        authored town/landmark.

        ``include_water`` defaults to the enrichment sidecar's
        ``prompt_requested_water`` flag when None. This stops incidental
        Strata water from dominating the foreground on prompts that didn't
        ask for water. Pass True/False explicitly to override.
        """
        prompt_requested_water, sidecar_present = _load_enrichment_water_flag()
        if include_water is None:
            # Default policy: include water only when the prompt invited it.
            # If there's no sidecar at all (legacy run), keep the old
            # behaviour of including water — those builds were authored
            # before enrichment existed and may rely on it.
            include_water_resolved = (
                prompt_requested_water if sidecar_present else True
            )
        else:
            include_water_resolved = bool(include_water)

        camera_decision_log: dict[str, Any] = {
            "prompt_requested_water": bool(prompt_requested_water),
            "sidecar_present": bool(sidecar_present),
            "include_water_resolved": bool(include_water_resolved),
            "include_water_arg": include_water,
            "rejected_water_anchors": 0,
            "included_anchors": [],
            "rejected_anchors": [],
            "camera_reason": (
                "prompt_invited_water"
                if include_water_resolved and prompt_requested_water else
                "default_no_water" if not include_water_resolved else
                "caller_forced"
            ),
        }
        prompt_text = os.environ.get("SONGE_MAQUETTE_USER_PROMPT", "") or ""
        profile_text = prompt_text.lower()
        out_dir_for_profile = os.environ.get("MAQUETTE_OUT_DIR")
        profile_sidecars = (
            (
                Path(out_dir_for_profile).parent / "strata_scene_enrichment.json",
                Path(out_dir_for_profile) / "strata_scene_enrichment.json",
            )
            if out_dir_for_profile else ()
        )
        for sidecar_path in profile_sidecars:
            try:
                if sidecar_path.exists():
                    sidecar_payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
                    profile_text += " " + str(sidecar_payload.get("primary_theme") or "")
                    profile_text += " " + str(sidecar_payload.get("biome") or "")
                    break
            except Exception:  # noqa: BLE001
                continue
        if any(token in profile_text for token in ("coastal", "fishing", "dock", "pier", "jetty", "beach", "shoreline")):
            camera_profile = "coastal_land_bias"
        elif any(token in profile_text for token in ("caldera", "volcanic", "volcano", "crater")):
            camera_profile = "caldera_wide"
        elif any(token in profile_text for token in ("alpine", "basin", "frozen lake", "mountain village")):
            camera_profile = "basin_wide"
        elif any(token in profile_text for token in ("castle", "fortress", "keep", "stronghold", "outpost")):
            camera_profile = "castle_compound"
        else:
            camera_profile = "default"
        camera_decision_log["camera_profile"] = camera_profile
        out: list[CameraHeroAnchor] = []
        rejected_anchors: list[dict[str, Any]] = []
        water_radius = (
            float(primary_water.radius) if primary_water is not None else 0.0
        )
        water_xy = (
            (float(primary_water.x), float(primary_water.y))
            if primary_water is not None else None
        )

        def _looks_like_water_anchor(x: float, y: float, radius: float) -> bool:
            if water_xy is None or water_radius <= 0.0:
                return False
            d = math.hypot(x - water_xy[0], y - water_xy[1])
            # Within or slightly outside the water rim → water anchor.
            return d <= max(water_radius * 0.95, radius + 2.0)

        # Composition quality gate: by convention the primary hero is the
        # first anchor passed in. Any subsequent anchor that lives much
        # further than 2.4 × the primary radius is rejected, because
        # including it would force the camera to pull back so far that
        # the primary settlement becomes a postage stamp.
        primary_xy: tuple[float, float] | None = None
        primary_radius_local: float = 0.0
        for idx, item in enumerate(list(heroes or [])):
            try:
                if isinstance(item, RegionAnchor):
                    x, y = item.x, item.y
                    radius = max(6.0, float(item.radius))
                elif isinstance(item, TerrainPoint):
                    x, y = item.x, item.y
                    radius = 8.0
                elif isinstance(item, dict):
                    x = float(item.get("x", item.get("cx")))
                    y = float(item.get("y", item.get("cy")))
                    radius = float(item.get("radius", 10.0))
                else:
                    seq = list(item)
                    x = float(seq[0])
                    y = float(seq[1])
                    radius = float(seq[2]) if len(seq) >= 3 else 10.0
                # Gate water-anchors when the prompt didn't ask for water.
                if (
                    not include_water_resolved
                    and _looks_like_water_anchor(float(x), float(y), float(radius))
                ):
                    rejected_anchors.append({
                        "x": round(float(x), 4),
                        "y": round(float(y), 4),
                        "radius": round(float(radius), 4),
                        "reason": "water_anchor_not_requested",
                    })
                    continue
                if primary_xy is None:
                    primary_xy = (float(x), float(y))
                    primary_radius_local = float(radius)
                else:
                    # Primary-dominance check: anchors past 2.4× the
                    # primary's authored radius are too far to include
                    # without shrinking the primary on screen.
                    d_to_primary = math.hypot(float(x) - primary_xy[0], float(y) - primary_xy[1])
                    far_limit = max(primary_radius_local * 2.4, primary_radius_local + 50.0)
                    if d_to_primary > far_limit:
                        rejected_anchors.append({
                            "x": round(float(x), 4),
                            "y": round(float(y), 4),
                            "radius": round(float(radius), 4),
                            "reason": f"anchor_too_far_from_primary:{d_to_primary:.1f}>{far_limit:.1f}",
                        })
                        continue
                out.append(CameraHeroAnchor(
                    cx=float(x),
                    cy=float(y),
                    radius=max(4.0, float(radius)),
                    target_z=float(height_at(float(x), float(y))),
                    lift=0.0,
                ))
            except Exception:
                continue
        if not out:
            for region in regions.by_role("flat_feature_pad")[:3]:
                out.append(CameraHeroAnchor(
                    cx=region.x,
                    cy=region.y,
                    radius=max(6.0, region.radius),
                    target_z=region.z,
                    lift=0.0,
                ))
        camera_decision_log["included_anchors"] = [
            {
                "x": round(float(h.cx), 4),
                "y": round(float(h.cy), 4),
                "radius": round(float(h.radius), 4),
            }
            for h in out
        ]
        camera_decision_log["rejected_anchors"] = rejected_anchors
        camera_decision_log["rejected_water_anchors"] = sum(
            1 for r in rejected_anchors if r.get("reason") == "water_anchor_not_requested"
        )
        # Estimated primary screen fraction: ratio of primary anchor area
        # over the bbox of all included anchors. This is a rough proxy —
        # the real camera framing depends on lens/altitude — but it tracks
        # the regression we care about (primary shrinking under enrichment).
        if out and primary_radius_local > 0.0:
            xs = [float(h.cx) for h in out]
            ys = [float(h.cy) for h in out]
            bbox_w = max(max(xs) - min(xs), primary_radius_local * 2.0)
            bbox_h = max(max(ys) - min(ys), primary_radius_local * 2.0)
            bbox_area = bbox_w * bbox_h
            primary_area = math.pi * primary_radius_local * primary_radius_local
            camera_decision_log["estimated_primary_screen_fraction"] = round(
                min(1.0, primary_area / max(bbox_area, 1e-3)),
                4,
            )
        else:
            camera_decision_log["estimated_primary_screen_fraction"] = None
        # Persist the decision as a sidecar so the enrichment runtime
        # report and any post-build tooling can cross-reference it.
        out_dir_env = os.environ.get("MAQUETTE_OUT_DIR")
        if out_dir_env:
            try:
                Path(out_dir_env, "strata_camera_decision.json").write_text(
                    json.dumps(camera_decision_log, indent=2),
                    encoding="utf-8",
                )
            except Exception:  # noqa: BLE001
                pass
        return CameraComposition(
            heroes=out,
            water=primary_water if include_water_resolved else None,
            ridges=[],
            camera_profile=camera_profile,
        )

    _write_terrain_sidecar(heights, size=size, seed=seed, biome_hint=palette_name)
    print(
        f"[strata_bridge] terrain loaded from {root} "
        f"(res={res_x}x{res_y}, size={size:.1f}, palette={palette_name})"
    )
    terrain = Terrain(height_at=height_at, obj=obj, heightmap=heights, size=size)
    terrain.primary_water = primary_water
    terrain.water_anchors = [primary_water] if primary_water is not None else []
    terrain.water_objects = water_objs
    terrain.regions = regions
    terrain.find_placeable_points = find_placeable_points
    terrain.reserve_footprint = reserve_footprint
    terrain.place_ruin_cluster = place_ruin_cluster
    terrain.settlement_layout = settlement_layout
    terrain.wfc_settlement_plan = wfc_settlement_plan
    terrain.place_wfc_settlement_slots = place_wfc_settlement_slots
    terrain.place_enrichment_features = place_enrichment_features
    terrain.camera_composition = camera_composition
    terrain.sample_role = sample_role
    terrain.sample_region_role = sample_role
    terrain.object_budget = _object_budget_for_size(size, palette_name=palette_name)
    terrain.palette_name = palette_name
    terrain.minimum_objects = int(terrain.object_budget.get("minimum_objects", 0))
    terrain.minimum_visible_objects = int(
        terrain.object_budget.get("minimum_visible_objects", terrain.minimum_objects)
    )
    terrain.fill_visual_density = _make_visual_density_filler(
        height_at=height_at,
        sample_role=sample_role,
        find_placeable_points=find_placeable_points,
        primary_water=primary_water,
        size=size,
        seed=seed,
        palette_name=palette_name,
        budget=terrain.object_budget,
        regions=regions,
        reserved_footprints=reserved_footprints,
        settlement_layout_factory=settlement_layout,
    )
    terrain.write_object_budget_report = _make_object_budget_writer(terrain.object_budget)
    terrain.strata_dir = str(root)
    return terrain

"""LowPolyWaterSurfaceFactory — flat water plane for streams / lakes / puddles.

Tier-1 factory by narrative weight (2/6 prompts: medieval, fishing) —
without it, "village by a stream" just looks like "village in a forest".

Strictly a STATIC plane in v0. Ripples + reflection + caustic shading
are out of scope; that's shader work and Maquette's whole point is to
keep materials trivial. The water-feel comes from the muted `water`
palette color + the flat plane sitting flush with the ground.

Archetypes:
  still_lake  — rectangular plane (extent w×h), gently jittered edge
                vertices for an organic shoreline at low poly
  stream      — long narrow plane along +X axis with subdivision
                so caller can rotate / bend it through the scene
  puddle      — small irregular polygon (~8 sides), subtle vertical
                jitter for "this is liquid" reading

Material slots: 1 (water).

Layout convention: the plane lies in the XY plane at z=0 — the
caller is expected to translate it to the desired water level.
Edge_lift parameter raises the outer ring above the center, which
reads as "this water is contained in a basin" and is useful for
fountain ponds.
"""

from __future__ import annotations

import math
import random

import bmesh
import bpy
from mathutils import Vector

from infinigen.core.placement.factory import AssetFactory

from ...density import n_along_axis, target_edge_for_bbox
from ...materials import apply_palette_slots


_WATER_ARCHETYPES = ("still_lake", "stream", "puddle")


# n_segments is bbox-derived. Defaults below carry shape only.
_ARCHETYPE_DEFAULTS = {
    "still_lake": dict(
        extent=(8.0, 6.0),
        length=None, width=None,
        edge_lift=0.0, edge_jitter=0.25,
        water_color="water",
    ),
    "stream": dict(
        extent=None,
        length=12.0, width=1.6,
        edge_lift=0.0, edge_jitter=0.10,
        water_color="water",
    ),
    "puddle": dict(
        extent=(1.5, 1.0),
        length=None, width=None,
        edge_lift=0.0, edge_jitter=0.18,
        water_color="water",
    ),
}


def _bm_face_count(bm) -> int:
    return len(bm.faces)


def _build_subdivided_rect(
    bm,
    sx: float, sy: float,
    n_seg_x: int, n_seg_y: int,
    edge_jitter: float,
    edge_lift: float,
    rng: random.Random,
) -> int:
    """A subdivided rectangle in the XY plane at z=0, centered. Edge
    vertices get a small XY jitter for organic shoreline + optional
    Z lift for basin look. Inner vertices stay flat. Returns face count."""
    n_before = _bm_face_count(bm)
    nx = max(2, n_seg_x + 1)
    ny = max(2, n_seg_y + 1)
    grid = [[None] * ny for _ in range(nx)]
    for i in range(nx):
        for j in range(ny):
            u = i / (nx - 1)
            v = j / (ny - 1)
            x = (u - 0.5) * sx
            y = (v - 0.5) * sy
            z = 0.0
            on_edge = (i in (0, nx - 1)) or (j in (0, ny - 1))
            if on_edge:
                # Pull edge vertices slightly inward / outward for
                # organic-ish shoreline. Direction is the outward normal.
                normal_x = (1.0 if i == nx - 1 else (-1.0 if i == 0 else 0.0))
                normal_y = (1.0 if j == ny - 1 else (-1.0 if j == 0 else 0.0))
                jitter = rng.uniform(-edge_jitter, edge_jitter)
                x += normal_x * jitter
                y += normal_y * jitter
                z += edge_lift
            grid[i][j] = bm.verts.new((x, y, z))
    bm.verts.ensure_lookup_table()
    for i in range(nx - 1):
        for j in range(ny - 1):
            bm.faces.new((
                grid[i][j],
                grid[i + 1][j],
                grid[i + 1][j + 1],
                grid[i][j + 1],
            ))
    return _bm_face_count(bm) - n_before


def _build_puddle(
    bm,
    sx: float, sy: float,
    edge_jitter: float,
    rng: random.Random,
) -> int:
    """Irregular ~8-sided polygon, fan-triangulated from a center vertex.
    Reads as a small puddle even at low poly thanks to the asymmetric
    silhouette."""
    n_before = _bm_face_count(bm)
    n_sides = 8
    center = bm.verts.new((0, 0, 0))
    ring = []
    for s in range(n_sides):
        a = 2 * math.pi * s / n_sides
        rx = (sx / 2) * (1 + rng.uniform(-edge_jitter, edge_jitter))
        ry = (sy / 2) * (1 + rng.uniform(-edge_jitter, edge_jitter))
        x = math.cos(a) * rx
        y = math.sin(a) * ry
        ring.append(bm.verts.new((x, y, 0)))
    bm.verts.ensure_lookup_table()
    for s in range(n_sides):
        ns = (s + 1) % n_sides
        bm.faces.new((center, ring[s], ring[ns]))
    return _bm_face_count(bm) - n_before


class LowPolyWaterSurfaceFactory(AssetFactory):
    """A flat water surface — lake, stream, or puddle. Static plane;
    ripples are out of v0 scope.

    Constructor knobs:

        factory_seed
        water_archetype : str = "still_lake"
                          "still_lake" | "stream" | "puddle"
        extent          : (sx, sy)        for lakes / puddles
        length, width   : floats          for streams (length is +X axis)
        edge_lift       : float           lift outer ring (basin look)
        edge_jitter     : float           organic-ish edge offsets
        n_segments      : int             subdivision count (rect)
        water_color     : str             slot 0
    """

    def __init__(
        self,
        factory_seed,
        water_archetype: str = "still_lake",
        extent: tuple[float, float] | None = None,
        length: float | None = None,
        width: float | None = None,
        edge_lift: float | None = None,
        edge_jitter: float | None = None,
        polygon_multiplier: float = 1.0,
        target_edge: float | None = None,
        n_segments: int | None = None,
        water_color: str | None = None,
        coarse: bool = False,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if water_archetype not in _WATER_ARCHETYPES:
            # Lenient fallback rather than crash. Sonnet has been
            # observed to hallucinate plausible-sounding archetype
            # names despite the factories_guide brief listing the
            # valid set; killing a 6-minute build over a one-line
            # archetype typo wastes a generation. Substitute the
            # canonical default and warn to stderr.
            import sys
            print(
                f"[water_archetype] WARN: unknown water_archetype "
                f"{water_archetype!r}; falling back to {_WATER_ARCHETYPES[0]!r}. "
                f"Valid: {_WATER_ARCHETYPES}",
                file=sys.stderr,
            )
            water_archetype = _WATER_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[water_archetype]
        self.water_archetype = water_archetype
        # Resolve extent vs length/width depending on archetype.
        if water_archetype == "stream":
            self.length = float(length if length is not None else d["length"])
            self.width = float(width if width is not None else d["width"])
            self.extent = (self.length, self.width)
        else:
            ext = extent if extent is not None else d["extent"]
            self.extent = (float(ext[0]), float(ext[1]))
            self.length = self.extent[0]
            self.width = self.extent[1]
        self.edge_lift = float(edge_lift if edge_lift is not None else d["edge_lift"])
        self.edge_jitter = float(
            edge_jitter if edge_jitter is not None else d["edge_jitter"]
        )
        # Bbox-derived segment count using the smaller axis as scale anchor;
        # _build later still oversamples streams along the long axis.
        sx, sy = self.extent
        edge = (
            float(target_edge) if target_edge is not None
            else target_edge_for_bbox(
                (sx, sy, max(sx, sy) * 0.1),
                polygon_multiplier=polygon_multiplier,
            )
        )
        self.n_segments = int(
            n_segments if n_segments is not None
            else n_along_axis(min(sx, sy), edge, min_n=2)
        )
        self.water_color = water_color or d["water_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyWaterSurface({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        rng = random.Random(self.factory_seed)
        bm = bmesh.new()

        sx, sy = self.extent
        if self.water_archetype == "puddle":
            _build_puddle(bm, sx, sy, self.edge_jitter, rng)
        else:
            # Stream gets more subdivision along its length axis
            if self.water_archetype == "stream":
                n_seg_x = max(self.n_segments, int(self.length / 1.5))
                n_seg_y = max(2, self.n_segments // 2)
            else:
                n_seg_x = self.n_segments
                n_seg_y = self.n_segments
            _build_subdivided_rect(
                bm, sx, sy, n_seg_x, n_seg_y,
                self.edge_jitter, self.edge_lift, rng,
            )

        me = bpy.data.meshes.new(f"LowPolyWaterSurface({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(
            f"LowPolyWaterSurface({self.factory_seed})", me
        )
        bpy.context.scene.collection.objects.link(obj)

        while len(obj.data.materials) < 1:
            obj.data.materials.append(None)

        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(obj, [self.water_color])
        return obj

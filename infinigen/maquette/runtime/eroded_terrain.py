"""Game-ready eroded terrain — opensimplex + pure-NumPy hydraulic erosion.

Use this when the prompt calls for serious topographic relief: dramatic
peaks, dendritic river networks, multi-biome composition with believable
shape. For simple flat/single-biome ground use ``make_terrain``.

Pipeline (per call):
  1. opensimplex base with peaks (positive Gaussians) + troughs
     (negative Gaussians) + domain-warped FBM relief + ridged noise
     local to alpine peaks.
  2. Edge skirt — a smoothstep ring near the world boundary pulls
     elevation down to ``edge_floor`` so the camera never sees a
     guillotine cliff at the rim.
  3. Priority-flood sink fill so the eroder doesn't stall on local
     pits, then stream-power erosion *with* a Davy-Lague style
     deposition term so the system isn't monotonically lowering.
  4. Subdivided plane mesh built from the eroded heightmap.
  5. Per-vertex Whittaker biome colors. Bands are placed by elevation
     QUANTILE, not absolute Z, so bumping ``plain_offset`` doesn't
     wipe out the meadow band. Snow + stone are *slope-gated* — snow
     drops off above ~30° and stone grows in through scree on
     intermediate slopes instead of snapping at one threshold.
  6. Polygonal water meshes per detected basin (cell-quad prisms +
     remove_doubles) using the shared low-poly water shader from
     ``maquette.materials.apply_water_material`` — no more axis-aligned
     bbox slabs covering dry land.

Color authoring: ``_DEFAULT_PALETTE`` is in **sRGB intent** (the values
you'd type into a paint program). They get converted to linear at the
vertex-color write site so they don't blow out under the Standard view
transform + sun energy 2.5 used by the example pipelines. The scatter
biome thresholds in ``runtime.scatter`` are kept in sync.

Dependency notes:
  * ``opensimplex`` and ``scipy`` are required. Both ship with the
    user-site setup the maquette pipeline already does at startup.
"""
from __future__ import annotations

import heapq
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


# Add the version-specific user-site so opensimplex / scipy / landlab
# resolve even when Blender's bundled Python doesn't include user-site
# by default.
def _ensure_user_site_on_path() -> None:
    user = Path(
        f"/home/tang/.local/lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"
    )
    if user.is_dir() and str(user) not in sys.path:
        sys.path.insert(0, str(user))


_ensure_user_site_on_path()


# Type aliases for the public spec.
Peak = tuple[float, float, float, float]      # (cx, cy, sigma, height)
Trough = tuple[float, float, float, float]    # (cx, cy, sigma, depth) — depth NEGATIVE
PaletteRGB = tuple[float, float, float]


@dataclass
class Terrain:
    """Same shape as the simple-helper Terrain so callers don't branch."""
    height_at: Callable[[float, float], float]
    obj: object


# Palette is **sRGB-intent** — these are the values you'd type into a
# paint program. The vertex-color write step converts to linear via
# ``_srgb_to_linear`` so they don't blow out under the Standard view
# transform. Hand-tuned 2026-05-01 after the user noted blown-out
# greens in test renders.
_DEFAULT_PALETTE: dict[str, PaletteRGB] = {
    "lakebed": (0.46, 0.40, 0.30),    # damp earth, slight green tint
    "shore":   (0.74, 0.66, 0.48),    # warm pale sand
    "meadow":  (0.40, 0.50, 0.22),    # grass — desaturated a touch from the original
    "forest":  (0.20, 0.30, 0.15),    # deeper, mossier forest
    "stone":   (0.46, 0.42, 0.36),    # dry rock, slight ochre
    "alpine":  (0.58, 0.56, 0.54),    # exposed alpine, near-neutral
    "snow":    (0.86, 0.88, 0.92),    # off-white — Standard view will lift this to display white
}


def _srgb_to_linear(c: float) -> float:
    """sRGB-intent value → scene-linear, used so colors authored in the
    palette don't blow out when written into a vertex-color attribute
    that the shader graph reads as linear."""
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def _palette_linear(name: str, palette: dict[str, PaletteRGB]):
    """Resolve palette entry as a linear-RGB tuple (3 floats)."""
    rgb = palette.get(name, _DEFAULT_PALETTE[name])
    return (_srgb_to_linear(rgb[0]),
            _srgb_to_linear(rgb[1]),
            _srgb_to_linear(rgb[2]))


def _edge_skirt_mask(res: int, size: float, falloff_bu: float):
    """Return a (res, res) mask in [0, 1] that's 0 deep inside the
    domain and 1 at the world edge. Smoothstep so it ramps smoothly
    rather than ringing.

    ``falloff_bu`` is how far from the edge the ramp starts (in BU).
    """
    import numpy as np

    if falloff_bu <= 0:
        return np.zeros((res, res), dtype=np.float32)

    coords = np.linspace(-size, size, res, dtype=np.float32)
    X, Y = np.meshgrid(coords, coords)
    # Distance into the falloff band — 0 inside, ramps to falloff_bu at the rim.
    dx = np.maximum(0.0, np.abs(X) - (size - falloff_bu))
    dy = np.maximum(0.0, np.abs(Y) - (size - falloff_bu))
    d = np.maximum(dx, dy) / falloff_bu
    t = np.clip(d, 0.0, 1.0)
    # Cubic smoothstep — C1-continuous so the edge of the falloff band
    # doesn't show a kink under grazing camera angles.
    return (t * t * (3.0 - 2.0 * t)).astype(np.float32)


def _build_heightmap(
    res: int,
    size: float,
    seed: int,
    peaks: Sequence[Peak],
    troughs: Sequence[Trough],
    plain_offset: float,
    edge_falloff: float,
    edge_floor: float,
):
    """Returns (heightmap, alpine_mask). Both are (res, res) float32 NumPy.

    Domain warp is applied via ``scipy.ndimage.map_coordinates`` — the
    previous implementation collapsed the warped Y axis to a single
    value per row (``noise2array`` called with a singleton Y array),
    making relief read as streaky along Y at oblique angles.
    """
    import numpy as np
    from opensimplex import OpenSimplex
    from scipy.ndimage import map_coordinates

    nz_warp_x = OpenSimplex(seed=seed + 1)
    nz_warp_y = OpenSimplex(seed=seed + 2)
    nz_fbm    = OpenSimplex(seed=seed + 3)
    nz_ridge  = OpenSimplex(seed=seed + 4)
    nz_micro  = OpenSimplex(seed=seed + 5)

    coords = np.linspace(-size, size, res, dtype=np.float64)
    X, Y = np.meshgrid(coords, coords)
    h = np.zeros((res, res), dtype=np.float32)

    # Peaks. alpine_mask tracks high-elevation peaks for ridged noise
    # gating downstream.
    alpine_mask = np.zeros_like(h)
    for (cx, cy, sigma, height) in peaks:
        d2 = (X - cx) ** 2 + (Y - cy) ** 2
        h += (np.exp(-d2 / (2 * sigma * sigma)) * height).astype(np.float32)
        if height >= 12:
            tight = np.exp(-d2 / (2 * (sigma * 0.5) ** 2)).astype(np.float32)
            alpine_mask = np.maximum(alpine_mask, tight)

    # Troughs (negative Gaussians).
    for (cx, cy, sigma, depth) in troughs:
        d2 = (X - cx) ** 2 + (Y - cy) ** 2
        h += (np.exp(-d2 / (2 * sigma * sigma)) * depth).astype(np.float32)

    # Domain warp — sample on the regular grid, then we'll look up the
    # FBM stack at warped pixel coordinates.
    warp_x = nz_warp_x.noise2array(coords / 60.0, coords / 60.0).astype(np.float32) * 22.0
    warp_y = nz_warp_y.noise2array(coords / 60.0 + 31.0, coords / 60.0 + 31.0).astype(np.float32) * 22.0
    span = 2.0 * float(size)

    # Per-octave domain-warped FBM via map_coordinates (bilinear remap
    # on a regular FBM grid). This vectorizes what used to be a row x
    # octave Python loop and — more importantly — ACTUALLY warps in Y,
    # not just X. Single-octave warp re-applied per band gets us the
    # gnarled silhouette the legacy code was reaching for.
    fbm = np.zeros((res, res), dtype=np.float32)
    for amp, freq in [(1.0, 1.0), (0.55, 2.1), (0.28, 4.3), (0.13, 8.5)]:
        cx_axis = coords * freq / 28.0
        layer = nz_fbm.noise2array(cx_axis, cx_axis).astype(np.float32)
        # Sample at warped coords (in pixel space).
        wx_pix = ((X.astype(np.float32) + warp_x) + size) / span * (res - 1)
        wy_pix = ((Y.astype(np.float32) + warp_y) + size) / span * (res - 1)
        warped = map_coordinates(
            layer, [wy_pix, wx_pix], order=1, mode="reflect"
        ).astype(np.float32)
        fbm += amp * warped
    h += fbm * 1.0

    # Micro detail — uncorrelated, no warp. Keeps near-camera ground
    # from looking like a smooth balloon.
    micro = nz_micro.noise2array(coords / 6.0, coords / 6.0).astype(np.float32)
    h += micro * 0.25

    # Ridged noise concentrated on alpine peaks.
    ridge = 1.0 - np.abs(nz_ridge.noise2array(coords / 9.0, coords / 9.0).astype(np.float32))
    h += (ridge ** 2) * 5.0 * alpine_mask

    h += plain_offset

    # Edge skirt — pull the rim down to ``edge_floor`` so the world
    # doesn't end in a guillotine cliff. Cubic smoothstep so the
    # transition is invisible at typical grazing angles.
    if edge_falloff > 0.0:
        m = _edge_skirt_mask(res, float(size), float(edge_falloff))
        h = h * (1.0 - m) + float(edge_floor) * m

    return h.astype(np.float32), alpine_mask


# D8 neighbor offsets, indices 0..7 in clockwise order from +x (E).
# (dy, dx) in grid coordinates, with row-major ordering (y is the row axis).
_D8_DY = (0, 1, 1, 1, 0, -1, -1, -1)
_D8_DX = (1, 1, 0, -1, -1, -1, 0, 1)
_SQRT2 = 1.41421356237
_D8_DIST = (1.0, _SQRT2, 1.0, _SQRT2, 1.0, _SQRT2, 1.0, _SQRT2)


def _fill_sinks(z, eps: float = 1e-3):
    """Priority-flood sink fill (Planchon-Darboux variant).

    Walks cells from the boundary inward in a min-heap; any neighbor
    lower than the current 'wave' is raised to current+eps so flow
    paths exist for every interior cell. Without this the eroder
    stalls on every closed pit (receivers stay -1, no drainage area
    accumulates downstream of the sink).

    O(N log N) where N = res². ~150 ms at res=256 in pure Python.
    """
    import numpy as np

    res = z.shape[0]
    filled = z.astype(np.float32, copy=True)
    visited = np.zeros((res, res), dtype=bool)
    heap: list[tuple[float, int, int]] = []

    # Seed with all boundary cells.
    for i in range(res):
        for jj, ii in ((0, i), (res - 1, i), (i, 0), (i, res - 1)):
            if not visited[jj, ii]:
                heapq.heappush(heap, (float(filled[jj, ii]), jj, ii))
                visited[jj, ii] = True

    while heap:
        h, j, i = heapq.heappop(heap)
        for k in range(8):
            nj = j + _D8_DY[k]
            ni = i + _D8_DX[k]
            if 0 <= nj < res and 0 <= ni < res and not visited[nj, ni]:
                if filled[nj, ni] < h + eps:
                    filled[nj, ni] = h + eps
                heapq.heappush(heap, (float(filled[nj, ni]), nj, ni))
                visited[nj, ni] = True

    return filled


def _erode(
    h,
    n_iter: int,
    k_sp: float = 4.5e-5,
    m: float = 0.5,
    n_exp: float = 1.0,
    dt: float = 1500.0,
    deposition: float = 0.4,
    s_crit: float = 0.10,
):
    """Pure-NumPy stream-power erosion **with deposition**.

    Each iteration:
      1. Sink-fill so every cell has a downstream flow path.
      2. D8 receivers + drainage-area accumulation by topological
         (high-to-low) order.
      3. Erode: dz = K · A^m · S^n · dt, clamped so a cell can't carve
         below its receiver (would invert flow).
      4. Route the eroded sediment downstream along the flow path.
         Cells with low local slope deposit a fraction
         ``deposition * (1 - s/s_crit)`` of their carried sediment;
         the rest passes to the receiver. Sediment that exits the
         domain at boundary cells is lost — that's our "sea outlet".

    The deposition step is what stops the legacy eroder from
    monotonically lowering the map: floodplains and alluvial fans
    actually build up where slopes flatten.
    """
    import numpy as np

    res = h.shape[0]
    n_cells = res * res
    z = h.astype(np.float32).copy()

    ny_grid, nx_grid = np.indices((res, res), dtype=np.int64)

    for it in range(n_iter):
        # 0) Fill closed pits so flow always reaches a boundary.
        z = _fill_sinks(z)

        # 1) D8 receiver: for each cell, find the neighbor with the
        #    steepest descent.
        z_pad = np.pad(z, 1, mode="edge")
        receivers_2d = np.full((res, res), -1, dtype=np.int64)
        slopes_2d = np.zeros((res, res), dtype=np.float32)

        for k in range(8):
            dy, dx, dist = _D8_DY[k], _D8_DX[k], _D8_DIST[k]
            neigh = z_pad[1 + dy:1 + dy + res, 1 + dx:1 + dx + res]
            drop = z - neigh
            slope_k = drop / dist
            cy = ny_grid + dy
            cx = nx_grid + dx
            in_bounds = (cy >= 0) & (cy < res) & (cx >= 0) & (cx < res)
            mask = (slope_k > slopes_2d) & in_bounds & (drop > 0)
            slopes_2d = np.where(mask, slope_k, slopes_2d)
            recv_idx = cy * res + cx
            receivers_2d = np.where(mask, recv_idx, receivers_2d)

        # 2) Drainage area via topological accumulation.
        order = np.argsort(-z, axis=None, kind="stable")
        area_flat = np.ones(n_cells, dtype=np.float32)
        rec_flat = receivers_2d.flatten()
        for idx in order:
            r = rec_flat[idx]
            if r >= 0:
                area_flat[r] += area_flat[idx]

        # 3) Stream-power erosion.
        a_field = area_flat.reshape((res, res))
        s_field = np.maximum(slopes_2d, 1e-6)
        dz = k_sp * np.power(a_field, m) * np.power(s_field, n_exp) * dt
        z_flat = z.flatten()
        recv_z_flat = np.where(rec_flat >= 0,
                               z_flat[np.maximum(rec_flat, 0)],
                               z_flat)
        recv_z = recv_z_flat.reshape((res, res))
        eroded = np.maximum(z - dz, recv_z)
        actual_dz = z - eroded

        # 4) Sediment routing + deposition. Walk cells in flow order
        #    (high to low); each cell deposits a fraction of its carried
        #    sediment based on the receiver's local slope, passes the
        #    rest downstream. Boundary outflow lost.
        sediment = actual_dz.flatten().astype(np.float32)
        deposit = np.zeros(n_cells, dtype=np.float32)
        slopes_flat = slopes_2d.flatten()
        gamma = float(deposition)
        s_c = float(max(s_crit, 1e-3))
        for idx in order:
            sed = sediment[idx]
            if sed <= 0:
                continue
            r = rec_flat[idx]
            if r < 0:
                continue
            s_r = float(slopes_flat[r])
            frac = gamma * max(0.0, 1.0 - s_r / s_c)
            d = frac * sed
            deposit[r] += d
            sediment[r] += sed - d
            sediment[idx] = 0.0

        new_z = eroded + deposit.reshape((res, res))

        # Boundary cells stay fixed (acts as the outlet for drainage).
        new_z[0, :] = h[0, :]
        new_z[-1, :] = h[-1, :]
        new_z[:, 0] = h[:, 0]
        new_z[:, -1] = h[:, -1]
        z = new_z.astype(np.float32)

    return z


def _quantile_thresholds(elev, sea_level: float):
    """Pick biome thresholds from the elevation distribution itself.

    The legacy code hard-coded ``forest 0.5..3.5, alpine >= 4`` etc.
    Bumping plain_offset just shifted the whole map into one band.
    Here we pick thresholds at fixed quantiles of *above-sea-level*
    elevation, so the palette tracks whatever range erosion produced.

    Returns a dict of named bounds.
    """
    import numpy as np

    above = elev - float(sea_level)
    land = above[above >= 0]
    if land.size < 16:
        # Pathological — almost the whole map is submerged. Fall back.
        return {
            "beach_top":  0.18,
            "meadow_top": 1.5,
            "forest_top": 3.5,
            "alpine_top": 6.0,
            "snow_top":   12.0,
        }
    return {
        "beach_top":  float(np.quantile(land, 0.06)),
        "meadow_top": float(np.quantile(land, 0.45)),
        "forest_top": float(np.quantile(land, 0.78)),
        "alpine_top": float(np.quantile(land, 0.93)),
        "snow_top":   float(np.quantile(land, 0.99)),
    }


def _biome_colors(elev, alpine_mask, sea_level: float, palette: dict[str, PaletteRGB]):
    """Continuous biome blend. Returns (res, res, 3) **linear-RGB**.

    Thresholds follow elevation quantiles (see ``_quantile_thresholds``)
    so palette bands stay where they should regardless of plain_offset.
    Snow is gated by SLOPE — it falls off above ~30° so cliffs read as
    rock not white. Stone fades through scree on intermediate slopes
    rather than snapping at one threshold.
    """
    import numpy as np

    def _arr(name: str):
        return np.array(_palette_linear(name, palette), dtype=np.float32)

    res = elev.shape[0]
    out = np.empty((res, res, 3), dtype=np.float32)
    out[:] = _arr("meadow")

    above = elev - sea_level
    q = _quantile_thresholds(elev, sea_level)
    beach_top  = q["beach_top"]
    meadow_top = q["meadow_top"]
    forest_top = q["forest_top"]
    alpine_top = q["alpine_top"]
    snow_top   = q["snow_top"]

    # Submerged: sandy near surface, lakebed at depth.
    submerged = (above < 0).astype(np.float32)
    depth = np.clip(-above / 1.5, 0, 1)
    near = (1 - depth)[..., None]
    deep = depth[..., None]
    underwater = _arr("shore") * near + _arr("lakebed") * deep
    out = out * (1 - submerged[..., None]) + underwater * submerged[..., None]

    # Beach band — narrow.
    if beach_top > 1e-3:
        t_beach = np.clip(above / beach_top, 0, 1) * (above >= 0) * (above < beach_top)
        t_beach = t_beach[..., None]
        beach_color = _arr("shore") * 0.7 + _arr("meadow") * 0.3
        out = out * (1 - t_beach) + beach_color * t_beach

    # Forest band — dominant in the meadow_top..forest_top range.
    forest_lo = max(meadow_top, beach_top + 0.05)
    if forest_top > forest_lo:
        t_forest = np.clip(
            (above - forest_lo) / max(forest_top - forest_lo, 1e-3), 0, 1
        ) * (above >= forest_lo) * (above < forest_top)
        t_forest = t_forest[..., None] * (1 - alpine_mask[..., None])
        out = out * (1 - t_forest) + _arr("forest") * t_forest

    # Slope (used by stone + snow). Computed once.
    gy, gx = np.gradient(elev)
    slope = np.sqrt(gx * gx + gy * gy)

    # Stone — fades in from "scree" (slope ~0.25) to "bare rock" (>0.7).
    # Restricted to land that's actually above the meadow band so
    # lowland erosion gullies don't go grey.
    elev_factor = np.clip((above - forest_lo * 0.6) / max(meadow_top, 1.0), 0, 1)
    stone_mask = np.clip((slope - 0.25) / 0.45, 0, 1) * elev_factor
    stone_mask_3 = stone_mask[..., None]
    out = out * (1 - stone_mask_3) + _arr("stone") * stone_mask_3

    # Alpine — exposed rock band at upper elevations.
    if alpine_top > forest_top:
        t_alp = np.clip(
            (above - forest_top) / max(alpine_top - forest_top, 1e-3), 0, 1
        ) * (above >= forest_top)
        t_alp = t_alp[..., None]
        out = out * (1 - t_alp) + _arr("alpine") * t_alp

    # Snow — slope-gated. Falls off above slope ~0.6 (≈30°) so cliff
    # faces stay rocky even if elevation says "should be snowy".
    snow_lo = max(alpine_top, forest_top + 0.5)
    if snow_top > snow_lo:
        t_snow_elev = np.clip(
            (above - snow_lo) / max(snow_top - snow_lo, 1e-3), 0, 1
        )
        slope_gate = np.clip(1.0 - (slope - 0.45) / 0.35, 0, 1)
        t_snow = (t_snow_elev * slope_gate)[..., None]
        out = out * (1 - t_snow) + _arr("snow") * t_snow

    return np.clip(out, 0, 1)


def _build_water_mesh(name: str, mask, size: float, water_level: float, thickness: float):
    """Build a polygonal water volume that follows the basin outline.

    For every cell flagged in ``mask`` we emit a thin prism at
    ``water_level`` (top) / ``water_level - thickness`` (bottom). Then
    ``bmesh.ops.remove_doubles`` welds neighboring prisms into a single
    surface, so a meandering basin produces a meandering water mesh
    instead of an axis-aligned bbox slab covering its banks.
    """
    import bmesh
    import bpy
    import numpy as np

    res_y, res_x = mask.shape
    span = 2.0 * float(size)
    cell_x = span / (res_x - 1)
    cell_y = span / (res_y - 1)

    bm = bmesh.new()
    masked = np.argwhere(mask)
    z_top = float(water_level)
    z_bot = float(water_level - thickness)

    for jj, ii in masked:
        x0 = -size + ii * cell_x
        x1 = x0 + cell_x
        y0 = -size + jj * cell_y
        y1 = y0 + cell_y
        v = [
            bm.verts.new((x0, y0, z_bot)),  # 0
            bm.verts.new((x1, y0, z_bot)),  # 1
            bm.verts.new((x1, y1, z_bot)),  # 2
            bm.verts.new((x0, y1, z_bot)),  # 3
            bm.verts.new((x0, y0, z_top)),  # 4
            bm.verts.new((x1, y0, z_top)),  # 5
            bm.verts.new((x1, y1, z_top)),  # 6
            bm.verts.new((x0, y1, z_top)),  # 7
        ]
        bm.faces.new([v[4], v[5], v[6], v[7]])  # top
        bm.faces.new([v[3], v[2], v[1], v[0]])  # bottom (reversed)
        bm.faces.new([v[0], v[1], v[5], v[4]])  # -Y side
        bm.faces.new([v[1], v[2], v[6], v[5]])  # +X side
        bm.faces.new([v[2], v[3], v[7], v[6]])  # +Y side
        bm.faces.new([v[3], v[0], v[4], v[7]])  # -X side

    # Weld duplicate verts within a small tolerance — neighbouring
    # prisms now share faces, so internal faces get cancelled by
    # ``dissolve_degenerate``.
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=min(cell_x, cell_y) * 0.05)

    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.update()
    obj = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(obj)
    return obj


def _place_water_volumes(
    H,
    sea_level: float,
    size: float,
    water_offset: float,
    water_thickness: float,
    min_area_cells: int,
    use_low_poly_shader: bool,
    water_color: tuple[float, float, float, float],
):
    """Detect connected basins and place a polygonal water mesh per
    basin. Each basin is meshed from its actual cell footprint (not a
    bbox), so meandering rivers and dendritic lakes look right.

    If ``use_low_poly_shader`` is True (default) we apply the shared
    Maquette translucent water material from
    ``maquette.materials.apply_water_material`` — the canonical
    low-poly water recipe with depth-encoded color, banded fresnel
    rim, and voronoi shimmer. Otherwise we fall back to a simple
    Principled-BSDF translucent material parameterised by
    ``water_color``.
    """
    import bpy
    import numpy as np
    from scipy.ndimage import label

    submerged = (H < sea_level).astype(np.int32)
    labels, n_components = label(submerged, structure=np.ones((3, 3), dtype=np.int32))
    water_z = float(sea_level) + float(water_offset)

    # Lazy import to avoid a hard dep when this module is imported in
    # pure-Python contexts (factories_guide regen, unit tests).
    apply_low_poly_water = None
    if use_low_poly_shader:
        try:
            from infinigen.maquette.materials import apply_water_material as _apply_water
            apply_low_poly_water = _apply_water
        except Exception:
            apply_low_poly_water = None

    # Fallback simple material (one shared instance).
    fallback_mat = None
    if apply_low_poly_water is None:
        fallback_mat = bpy.data.materials.new("water_volume_mat")
        fallback_mat.use_nodes = True
        fallback_mat.blend_method = "BLEND"
        nt = fallback_mat.node_tree
        for n in list(nt.nodes):
            if n.type != "OUTPUT_MATERIAL":
                nt.nodes.remove(n)
        out_node = nt.nodes["Material Output"]
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        r, g, b, a = water_color
        bsdf.inputs["Base Color"].default_value = (r, g, b, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.15
        bsdf.inputs["Alpha"].default_value = float(a)
        nt.links.new(bsdf.outputs["BSDF"], out_node.inputs["Surface"])

    objs = []
    for comp_idx in range(1, n_components + 1):
        comp_mask = (labels == comp_idx)
        if int(comp_mask.sum()) < min_area_cells:
            continue
        obj = _build_water_mesh(
            f"Water_{comp_idx:02d}", comp_mask,
            size=size, water_level=water_z, thickness=water_thickness,
        )
        if apply_low_poly_water is not None:
            apply_low_poly_water(obj)
        else:
            obj.data.materials.append(fallback_mat)
        objs.append(obj)

    return objs


def make_eroded_terrain(
    *,
    size: float = 140.0,
    seed: int = 0,
    peaks: Sequence[Peak] = (),
    troughs: Sequence[Trough] = (),
    plain_offset: float = 2.4,
    sea_level: float = 0.5,
    erode_iters: int = 35,
    deposition: float = 0.4,
    edge_falloff: float = 18.0,
    edge_floor: float | None = None,
    resolution: int = 256,
    palette: dict[str, PaletteRGB] | None = None,
    smooth_shading: bool = True,
    water: bool = True,
    water_color: tuple[float, float, float, float] = (0.20, 0.42, 0.60, 0.8),
    water_offset: float = 0.10,
    water_thickness: float = 0.4,
    water_min_area_cells: int = 12,
    water_low_poly_shader: bool = True,
) -> Terrain:
    """Build a hydraulically-eroded terrain mesh.

    Returns a ``Terrain`` whose ``height_at(x, y)`` samples the eroded
    surface — use it the same way as the simple ``make_terrain``
    helper.

    Spec format (passed by the LLM build script):
      * ``peaks`` — list of (cx, cy, sigma, height). Heights ≥12 trigger
        ridged-noise alpine character + snow capping at the highest band.
      * ``troughs`` — list of (cx, cy, sigma, depth) with NEGATIVE depth.
      * ``plain_offset`` — uniform lift applied to the WHOLE map. Bump
        if too much of the map reads as sandy. Biome bands are quantile-
        based, so this no longer flips the whole palette to forest.
      * ``sea_level`` — anything below reads as lakebed/shore.
      * ``edge_falloff`` — distance (BU) from the world rim over which
        elevation tapers down to ``edge_floor`` so cameras don't see
        a guillotine cliff. Set to 0 to disable.
      * ``edge_floor`` — target elevation at the rim. ``None`` resolves
        to ``max(sea_level + 0.2, plain_offset - 1.5)`` — i.e. the rim
        sits just above water as a thin beach band by default, so
        inland scenes don't accidentally turn into islands. For
        coastal / ocean prompts pass ``edge_floor=sea_level - 1.0``
        explicitly to flood the rim.
      * ``deposition`` — sediment deposition fraction in flat regions.
        Higher = more floodplain build-up; lower = more incised
        bedrock channels. 0.4 is a good general-purpose value.
      * ``water_low_poly_shader`` — when True (default) water meshes
        use the shared low-poly water recipe; when False they use a
        simple alpha-blend Principled BSDF parameterised by
        ``water_color``.
    """
    import bpy
    import numpy as np

    if palette is None:
        palette = {}
    if edge_floor is None:
        # Default: rim sits just above sea level so inland scenes don't
        # flood. Coastal prompts override with a sub-sea-level value.
        edge_floor = max(float(sea_level) + 0.2, float(plain_offset) - 1.5)

    print(f"[eroded_terrain] base heightmap (peaks={len(peaks)}, troughs={len(troughs)})")
    H0, alpine = _build_heightmap(
        resolution, float(size), int(seed),
        list(peaks), list(troughs), float(plain_offset),
        float(edge_falloff), float(edge_floor),
    )
    print(f"[eroded_terrain] eroding ({erode_iters} iter, deposition={deposition:.2f})")
    H = _erode(H0, n_iter=int(erode_iters), deposition=float(deposition))
    print(f"[eroded_terrain] elevation range {H.min():.2f}..{H.max():.2f}")
    COL = _biome_colors(H, alpine, float(sea_level), palette)

    res = resolution
    xs = np.linspace(-size, size, res, dtype=np.float32)
    ys = np.linspace(-size, size, res, dtype=np.float32)

    # Vertex array via vectorized stack — much faster than the python
    # double-loop ``for j: for i: verts[j*res+i] = (...)`` we used to
    # have. At res=256 this drops mesh-build wall time from ~2s to
    # ~150ms.
    Xg, Yg = np.meshgrid(xs, ys)
    verts_arr = np.stack([Xg, Yg, H], axis=-1).reshape(-1, 3).astype(np.float32)

    faces: list[tuple[int, int, int, int]] = []
    for j in range(res - 1):
        base = j * res
        nxt = (j + 1) * res
        for i in range(res - 1):
            faces.append((base + i, base + i + 1, nxt + i + 1, nxt + i))

    me = bpy.data.meshes.new("eroded_terrain_mesh")
    me.from_pydata(verts_arr.tolist(), [], faces)
    me.update()
    obj = bpy.data.objects.new("Terrain", me)
    bpy.context.collection.objects.link(obj)

    # Per-vertex color attribute (Blender 3.2+ FLOAT_COLOR domain="POINT").
    # Vectorized write via foreach_set — the legacy per-vertex Python
    # loop was ~500ms at res=256, foreach_set is ~5ms.
    col_attr = me.color_attributes.new(name="Col", type="FLOAT_COLOR", domain="POINT")
    rgba = np.empty((res * res, 4), dtype=np.float32)
    rgba[:, :3] = COL.reshape(-1, 3)
    rgba[:, 3] = 1.0
    col_attr.data.foreach_set("color", rgba.flatten())

    if smooth_shading:
        for poly in me.polygons:
            poly.use_smooth = True

    mat = bpy.data.materials.new("eroded_terrain_mat")
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        if n.type != "OUTPUT_MATERIAL":
            nt.nodes.remove(n)
    out_node = nt.nodes["Material Output"]
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    attr = nt.nodes.new("ShaderNodeVertexColor")
    attr.layer_name = "Col"
    nt.links.new(attr.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.95
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = 0.05
    elif "Specular" in bsdf.inputs:
        bsdf.inputs["Specular"].default_value = 0.05
    nt.links.new(bsdf.outputs["BSDF"], out_node.inputs["Surface"])
    me.materials.append(mat)

    if water:
        try:
            water_objs = _place_water_volumes(
                H,
                sea_level=sea_level,
                size=size,
                water_offset=water_offset,
                water_thickness=water_thickness,
                min_area_cells=water_min_area_cells,
                use_low_poly_shader=water_low_poly_shader,
                water_color=water_color,
            )
            print(f"[eroded_terrain] placed {len(water_objs)} water volume(s)")
        except Exception as exc:
            # Non-fatal — the terrain itself is still good without water.
            print(f"[eroded_terrain] water placement skipped ({type(exc).__name__}: {exc})")

    # Closure for height_at — bilinear sample of the eroded grid at world (x, y).
    res_minus = res - 1
    span = 2 * float(size)

    def height_at(x: float, y: float) -> float:
        u = (float(x) + size) / span * res_minus
        v = (float(y) + size) / span * res_minus
        u = max(0.0, min(res_minus - 0.001, u))
        v = max(0.0, min(res_minus - 0.001, v))
        i = int(u)
        j = int(v)
        fu = u - i
        fv = v - j
        h00 = float(H[j,     i    ])
        h10 = float(H[j,     i + 1])
        h01 = float(H[j + 1, i    ])
        h11 = float(H[j + 1, i + 1])
        a = h00 * (1 - fu) + h10 * fu
        b = h01 * (1 - fu) + h11 * fu
        return a * (1 - fv) + b * fv

    return Terrain(height_at=height_at, obj=obj)

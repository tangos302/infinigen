"""Game-ready eroded terrain — opensimplex + pure-NumPy hydraulic erosion.

Use this when the prompt calls for serious topographic relief: dramatic
peaks, dendritic river networks, multi-biome composition with believable
shape. For simple flat/single-biome ground use ``make_terrain``.

Pipeline (per call):
  1. opensimplex base with peaks (positive Gaussians) + troughs
     (negative Gaussians) + domain-warped FBM relief + ridged noise
     local to alpine peaks.
  2. Stream-power erosion in pure NumPy — D8 flow direction, drainage
     area via topological-sort accumulation, dz = -K · A^m · S^n · dt.
     Same algorithm landlab's FastscapeEroder runs, but no C extension
     so we stay on Blender 4.2 / Python 3.11 with no ABI grief.
     ~3-6 seconds at 256×256 on CPU.
  3. Subdivided plane mesh built from the eroded heightmap.
  4. Per-vertex Whittaker biome colors blended in linear RGB.

Usage::

    from infinigen.maquette.runtime.eroded_terrain import make_eroded_terrain

    terrain = make_eroded_terrain(
        size=140,
        seed=808080,
        peaks=[
            # (cx, cy, sigma, height) — Gaussian mountain masses
            (115, 50, 25, 18.0),     # hero alpine, far NE
            (-110, 70, 18, 4.5),     # small western range
        ],
        troughs=[
            # (cx, cy, sigma, depth) — negative Gaussians for river/lake basins
            (-40, -10, 14, -3.6),
            (5,    5,  12, -3.4),
        ],
        plain_offset=2.4,    # lift plains above sea level so meadow dominates
        sea_level=0.5,       # below this reads as sandy lakebed
        erode_iters=35,      # 25 = soft, 35 default, 60 = aggressive carving
        resolution=256,      # heightmap pixels per axis
    )

    # height_at works the same as make_terrain for asset placement:
    obj.location = (x, y, terrain.height_at(x, y))

Dependency notes:
  * Only ``opensimplex`` is required (the eroder is pure NumPy + Blender's
    bundled NumPy). Install once with::

      blender --background --python-expr \\
        "import sys, subprocess; subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--user', 'opensimplex==0.4.5'])"

  * Pipeline scripts that call this should ensure
    ``~/.local/lib/python<X>.<Y>/site-packages`` is on ``sys.path``
    when running headless from Blender — handled automatically by the
    ``_ensure_user_site_on_path`` helper at module import.
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


# Add the version-specific user-site so opensimplex / landlab resolve
# even when Blender's bundled Python doesn't include user-site by default.
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


# Linear-RGB palette tuned for the Whittaker biome bands. Override via
# ``palette=`` kwarg; missing keys fall back to these.
_DEFAULT_PALETTE: dict[str, PaletteRGB] = {
    "lakebed": (0.55, 0.50, 0.36),    # damp earth + light gravel
    "shore":   (0.78, 0.72, 0.55),    # pale sand
    "meadow":  (0.40, 0.52, 0.24),    # grass
    "forest":  (0.22, 0.34, 0.18),    # darker forest
    "stone":   (0.50, 0.46, 0.40),    # rocky outcrop
    "alpine":  (0.60, 0.58, 0.55),    # exposed alpine rock
    "snow":    (0.94, 0.95, 0.96),
}


def _build_heightmap(
    res: int,
    size: float,
    seed: int,
    peaks: Sequence[Peak],
    troughs: Sequence[Trough],
    plain_offset: float,
):
    """Returns (heightmap, alpine_mask). Both are (res, res) float32 NumPy."""
    import numpy as np
    from opensimplex import OpenSimplex

    nz_warp_x = OpenSimplex(seed=seed + 1)
    nz_warp_y = OpenSimplex(seed=seed + 2)
    nz_fbm    = OpenSimplex(seed=seed + 3)
    nz_ridge  = OpenSimplex(seed=seed + 4)
    nz_micro  = OpenSimplex(seed=seed + 5)

    coords = np.linspace(-size, size, res, dtype=np.float64)
    X, Y = np.meshgrid(coords, coords)
    h = np.zeros((res, res), dtype=np.float32)

    # Peaks. alpine_mask tracks high-elevation peaks for ridged noise.
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

    # Domain-warped FBM. Single-row noise2array sweep is ~300× faster
    # than per-pixel loop while preserving warped lookup coords.
    warp_x = nz_warp_x.noise2array(coords / 60.0, coords / 60.0).astype(np.float32) * 22.0
    warp_y = nz_warp_y.noise2array(coords / 60.0 + 31.0, coords / 60.0 + 31.0).astype(np.float32) * 22.0
    sx = X.astype(np.float32) + warp_x
    sy = Y.astype(np.float32) + warp_y

    fbm = np.zeros((res, res), dtype=np.float32)
    for amp, freq in [(1.0, 1.0), (0.55, 2.1), (0.28, 4.3), (0.13, 8.5)]:
        layer = np.zeros((res, res), dtype=np.float32)
        for j in range(res):
            row_x = sx[j] * freq / 28.0
            row_y = sy[j] * freq / 28.0
            arr = nz_fbm.noise2array(row_x, np.array([row_y[0]]))
            layer[j] = arr[0]
        fbm += amp * layer
    h += fbm * 1.0

    micro = nz_micro.noise2array(coords / 6.0, coords / 6.0).astype(np.float32)
    h += micro * 0.25

    ridge = 1.0 - np.abs(nz_ridge.noise2array(coords / 9.0, coords / 9.0).astype(np.float32))
    h += (ridge ** 2) * 5.0 * alpine_mask

    h += plain_offset
    return h.astype(np.float32), alpine_mask


# D8 neighbor offsets, indices 0..7 in clockwise order from +x (E).
# (dy, dx) in grid coordinates, with row-major ordering (y is the row axis).
_D8_DY = (0, 1, 1, 1, 0, -1, -1, -1)
_D8_DX = (1, 1, 0, -1, -1, -1, 0, 1)
_SQRT2 = 1.41421356237
_D8_DIST = (1.0, _SQRT2, 1.0, _SQRT2, 1.0, _SQRT2, 1.0, _SQRT2)


def _erode(h, n_iter: int, k_sp: float = 4.5e-5, m: float = 0.5,
           n_exp: float = 1.0, dt: float = 1500.0):
    """Pure-NumPy stream-power erosion. Same algorithm as
    ``landlab.components.FastscapeEroder``: D8 flow routing + drainage
    area via topological-sort accumulation + dz = -K·A^m·S^n·dt
    applied implicitly along the flow path.

    Boundary cells are kept at fixed elevation (sinks). Inner cells
    that have no descending neighbor become local pits — they get a
    tiny perturbation + flow forward, preventing zero-drainage stalls.
    """
    import numpy as np

    res = h.shape[0]
    n_cells = res * res
    z = h.astype(np.float32).copy()

    ny_grid, nx_grid = np.indices((res, res), dtype=np.int64)

    for _ in range(n_iter):
        # 1) D8 receiver: for each cell, find the neighbor with the
        #    steepest descent. We work in 2D arrays throughout.
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

        # 2) Drainage area via topological accumulation: sort cells
        #    from high to low elevation, then each cell pushes its
        #    accumulated area to its receiver in that order.
        order = np.argsort(-z, axis=None, kind="stable")
        area_flat = np.ones(n_cells, dtype=np.float32)
        rec_flat = receivers_2d.flatten()
        for idx in order:
            r = rec_flat[idx]
            if r >= 0:
                area_flat[r] += area_flat[idx]

        # 3) Stream-power erosion. dz = K·A^m·S^n·dt; clamp so a cell
        #    can't carve below its receiver (would invert flow).
        a_field = area_flat.reshape((res, res))
        s_field = np.maximum(slopes_2d, 1e-6)
        dz = k_sp * np.power(a_field, m) * np.power(s_field, n_exp) * dt
        z_flat = z.flatten()
        recv_z_flat = np.where(rec_flat >= 0,
                               z_flat[np.maximum(rec_flat, 0)],
                               z_flat)
        recv_z = recv_z_flat.reshape((res, res))
        new_z = np.maximum(z - dz, recv_z)
        # Boundary cells stay fixed (acts as the outlet for drainage).
        new_z[0, :] = z[0, :]
        new_z[-1, :] = z[-1, :]
        new_z[:, 0] = z[:, 0]
        new_z[:, -1] = z[:, -1]
        z = new_z

    return z


def _biome_colors(elev, alpine_mask, sea_level: float, palette: dict[str, PaletteRGB]):
    """Continuous biome blend. Returns (res, res, 3) linear RGB."""
    import numpy as np

    def _arr(name: str):
        return np.array(palette.get(name, _DEFAULT_PALETTE[name]), dtype=np.float32)

    res = elev.shape[0]
    out = np.empty((res, res, 3), dtype=np.float32)
    out[:] = _arr("meadow")

    above = elev - sea_level

    # Submerged: sandy near surface, lakebed at depth.
    submerged = (above < 0).astype(np.float32)
    depth = np.clip(-above / 1.5, 0, 1)
    near = (1 - depth)[..., None]
    deep = depth[..., None]
    underwater = _arr("shore") * near + _arr("lakebed") * deep
    out = out * (1 - submerged[..., None]) + underwater * submerged[..., None]

    # Beach band — narrow so plains don't read as desert.
    t_beach = np.clip(above / 0.18, 0, 1) * (above >= 0) * (above < 0.18)
    t_beach = t_beach[..., None]
    out = out * (1 - t_beach) + (_arr("shore") * 0.7 + _arr("meadow") * 0.3) * t_beach

    # Forest where elevation 0.5..3.5 and not on alpine mask.
    t_forest = np.clip((above - 0.5) / 2.5, 0, 1) * (above >= 0.5) * (above < 3.5)
    t_forest = t_forest[..., None] * (1 - alpine_mask[..., None])
    out = out * (1 - t_forest) + _arr("forest") * t_forest

    # Stone where slope is high AND well above the plain. Restricting
    # by elevation keeps lowland erosion gullies green.
    gy, gx = np.gradient(elev)
    slope = np.sqrt(gx * gx + gy * gy)
    elev_factor = np.clip((above - 1.5) / 2.0, 0, 1)
    stone_mask = np.clip((slope - 0.6) / 0.4, 0, 1) * elev_factor
    stone_mask = stone_mask[..., None]
    out = out * (1 - stone_mask) + _arr("stone") * stone_mask

    t_alp = np.clip((above - 4.0) / 5.0, 0, 1) * (above >= 4.0)
    t_alp = t_alp[..., None]
    out = out * (1 - t_alp) + _arr("alpine") * t_alp

    t_snow = np.clip((above - 9.0) / 4.0, 0, 1)
    t_snow = t_snow[..., None]
    out = out * (1 - t_snow) + _arr("snow") * t_snow

    return np.clip(out, 0, 1)


def make_eroded_terrain(
    *,
    size: float = 140.0,
    seed: int = 0,
    peaks: Sequence[Peak] = (),
    troughs: Sequence[Trough] = (),
    plain_offset: float = 2.4,
    sea_level: float = 0.5,
    erode_iters: int = 35,
    resolution: int = 256,
    palette: dict[str, PaletteRGB] | None = None,
    smooth_shading: bool = True,
) -> Terrain:
    """Build a hydraulically-eroded terrain mesh.

    Returns a ``Terrain`` whose ``height_at(x, y)`` samples the eroded
    surface at any world XY point — use it the same way as the simple
    ``make_terrain`` helper.

    Spec format (passed by the LLM build script):
      * ``peaks``  — list of (cx, cy, sigma, height). Heights ≥12 trigger
        ridged-noise alpine character + snow capping at the highest band.
      * ``troughs`` — list of (cx, cy, sigma, depth) with NEGATIVE depth.
        Use these to thread a river/lake basin through the terrain;
        the FastscapeEroder then carves natural drainage networks
        following the resulting slope field.
      * ``plain_offset`` — uniform lift applied to the WHOLE map so
        meadow dominates instead of beach. Bump this if too much of
        the map reads as sandy.
      * ``sea_level`` — anything below reads as lakebed/shore. Keep
        well below ``plain_offset`` so plains don't accidentally
        dip into the shore band.

    The heavy work is the heightmap composition + erosion (~3-8s at
    resolution=256). Mesh building scales with resolution² — keep at
    256 unless you really need crisp shorelines.
    """
    import bpy
    import numpy as np

    if palette is None:
        palette = {}

    print(f"[eroded_terrain] base heightmap (peaks={len(peaks)}, troughs={len(troughs)})")
    H0, alpine = _build_heightmap(
        resolution, float(size), int(seed),
        list(peaks), list(troughs), float(plain_offset),
    )
    print(f"[eroded_terrain] eroding ({erode_iters} iter)")
    H = _erode(H0, n_iter=int(erode_iters))
    print(f"[eroded_terrain] elevation range {H.min():.2f}..{H.max():.2f}")
    COL = _biome_colors(H, alpine, float(sea_level), palette)

    res = resolution
    xs = np.linspace(-size, size, res, dtype=np.float32)
    ys = np.linspace(-size, size, res, dtype=np.float32)
    verts = np.zeros((res * res, 3), dtype=np.float32)
    for j in range(res):
        for i in range(res):
            verts[j * res + i] = (xs[i], ys[j], H[j, i])

    faces: list[tuple[int, int, int, int]] = []
    for j in range(res - 1):
        base = j * res
        nxt = (j + 1) * res
        for i in range(res - 1):
            faces.append((base + i, base + i + 1, nxt + i + 1, nxt + i))

    me = bpy.data.meshes.new("eroded_terrain_mesh")
    me.from_pydata(verts.tolist(), [], faces)
    me.update()
    obj = bpy.data.objects.new("Terrain", me)
    bpy.context.collection.objects.link(obj)

    # Per-vertex color attribute (Blender 3.2+ FLOAT_COLOR domain="POINT").
    col_attr = me.color_attributes.new(name="Col", type="FLOAT_COLOR", domain="POINT")
    for j in range(res):
        for i in range(res):
            idx = j * res + i
            r, g, b = COL[j, i]
            col_attr.data[idx].color = (float(r), float(g), float(b), 1.0)

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
    nt.links.new(bsdf.outputs["BSDF"], out_node.inputs["Surface"])
    me.materials.append(mat)

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

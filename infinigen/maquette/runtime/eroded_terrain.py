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
    """Same shape as the simple-helper Terrain so callers don't branch.

    ``heightmap`` and ``size`` are exposed so post-build helpers (e.g.
    ``carve_path``) can mutate the underlying field in place — the
    ``height_at`` closure samples ``heightmap`` directly, so any
    in-place edit is picked up by subsequent placements.
    """
    height_at: Callable[[float, float], float]
    obj: object
    heightmap: object = None  # numpy.ndarray (res, res) when available
    size: float = 0.0


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

# Named biome presets — the LLM picks one with ``palette_preset="..."``
# instead of authoring a 7-color dict by hand. Names track scene mood,
# not strict ecology, so an "oasis" prompt → ``palette_preset="desert"``.
# Slot semantics are unchanged across presets: lakebed (lowest, wet) →
# shore → meadow (low land) → forest (mid land) → stone (mid-high) →
# alpine (rocky high) → snow (peak). Picking the wrong preset is safe;
# the colors just won't match the prompt.
_PALETTE_PRESETS: dict[str, dict[str, PaletteRGB]] = {
    "alpine": _DEFAULT_PALETTE,        # explicit alias for clarity
    "desert": {
        "lakebed": (0.45, 0.36, 0.22),  # oasis pool floor, dark damp sand
        "shore":   (0.86, 0.74, 0.50),  # bright dune sand
        "meadow":  (0.78, 0.68, 0.44),  # dry pale sand grass
        "forest":  (0.55, 0.46, 0.28),  # scrub thicket, brown-ochre
        "stone":   (0.65, 0.48, 0.32),  # warm sandstone
        "alpine":  (0.74, 0.60, 0.40),  # weathered rock, lighter than stone
        "snow":    (0.92, 0.84, 0.62),  # bleached crest sand, no white
    },
    "wetland": {
        "lakebed": (0.30, 0.34, 0.24),  # peat / muck
        "shore":   (0.55, 0.55, 0.38),  # reedy bank
        "meadow":  (0.32, 0.45, 0.20),  # grass marsh
        "forest":  (0.18, 0.28, 0.16),  # bog forest
        "stone":   (0.40, 0.42, 0.34),  # damp slate
        "alpine":  (0.50, 0.52, 0.48),  # cool rock
        "snow":    (0.82, 0.86, 0.88),
    },
    "volcanic": {
        "lakebed": (0.18, 0.16, 0.16),  # dark obsidian basin
        "shore":   (0.30, 0.26, 0.24),  # cooled lava sand
        "meadow":  (0.26, 0.22, 0.20),  # ash plain
        "forest":  (0.16, 0.18, 0.16),  # sparse charred scrub
        "stone":   (0.34, 0.28, 0.24),  # basalt
        "alpine":  (0.38, 0.30, 0.26),  # weathered rock
        "snow":    (0.62, 0.58, 0.55),  # ash dust, not white
    },
    "savanna": {
        "lakebed": (0.42, 0.34, 0.22),  # dry watering hole
        "shore":   (0.78, 0.68, 0.40),  # dusty pale earth
        "meadow":  (0.62, 0.58, 0.30),  # tall yellow-green grass
        "forest":  (0.36, 0.44, 0.20),  # acacia scrub
        "stone":   (0.55, 0.46, 0.34),
        "alpine":  (0.62, 0.54, 0.42),
        "snow":    (0.88, 0.80, 0.62),  # bleached crest, never white
    },
    "tundra": {
        "lakebed": (0.40, 0.42, 0.42),  # cold meltwater pool
        "shore":   (0.58, 0.60, 0.58),  # frostbitten earth
        "meadow":  (0.42, 0.46, 0.36),  # moss + low grass
        "forest":  (0.24, 0.30, 0.22),  # taiga
        "stone":   (0.48, 0.48, 0.48),
        "alpine":  (0.62, 0.64, 0.66),  # cold rock
        "snow":    (0.92, 0.94, 0.96),
    },
    "tropical": {
        "lakebed": (0.20, 0.36, 0.30),  # turquoise lagoon floor
        "shore":   (0.92, 0.88, 0.72),  # white coral sand
        "meadow":  (0.30, 0.52, 0.22),  # lush jungle floor
        "forest":  (0.16, 0.36, 0.16),  # deep canopy
        "stone":   (0.50, 0.44, 0.34),  # warm volcanic-tropical rock
        "alpine":  (0.62, 0.58, 0.52),
        "snow":    (0.82, 0.86, 0.84),
    },
}


def _resolve_palette(palette: dict[str, PaletteRGB] | None,
                     preset: str | None) -> dict[str, PaletteRGB]:
    """Layer order: explicit ``palette`` overrides win, then the named
    ``preset`` fills in missing slots, then ``_DEFAULT_PALETTE`` (alpine)
    fills any remaining gaps. Unknown preset names fall through silently
    to alpine — typo shouldn't crash the build."""
    base = _PALETTE_PRESETS.get((preset or "").lower(), _DEFAULT_PALETTE)
    if not palette:
        return base
    out = dict(base)
    out.update(palette)
    return out


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
    aniso_theta_rad: float | None = None,
    dunes: bool = False,
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

    # Two-pass domain warp (Inigo Quilez `warp(warp(...))` recipe) —
    # produces non-self-similar gnarled silhouettes that read as
    # designed rather than function-on-a-grid. Pass 1 generates a
    # standard warp noise grid; Pass 2 looks up that grid at coords
    # already displaced by Pass 1, via bilinear ``map_coordinates``.
    # https://iquilezles.org/articles/warp/
    span = 2.0 * float(size)
    q_x = nz_warp_x.noise2array(coords / 60.0, coords / 60.0).astype(np.float32)
    q_y = nz_warp_y.noise2array(coords / 60.0 + 31.0, coords / 60.0 + 31.0).astype(np.float32)
    # Pass-2 lookup: sample (q_x, q_y) at pixel coords displaced by
    # the pass-1 noise. Pass-1 amplitude in pixels = noise_unit * px/BU.
    p1_amp_px = 35.0 / span * (res - 1)  # 35 BU pass-1 displacement
    grid_xx, grid_yy = np.meshgrid(np.arange(res, dtype=np.float32),
                                   np.arange(res, dtype=np.float32))
    warp_pix_x = grid_xx + q_x * p1_amp_px
    warp_pix_y = grid_yy + q_y * p1_amp_px
    r_x = map_coordinates(q_x, [warp_pix_y, warp_pix_x],
                          order=1, mode="reflect").astype(np.float32)
    r_y = map_coordinates(q_y, [warp_pix_y, warp_pix_x],
                          order=1, mode="reflect").astype(np.float32)
    # Final warp amplitude in BU — combines pass 1 (foundation curve)
    # and pass 2 (gnarled detail).
    warp_x = (q_x * 18.0 + r_x * 32.0).astype(np.float32)
    warp_y = (q_y * 18.0 + r_y * 32.0).astype(np.float32)

    # Per-octave domain-warped FBM with **anisotropic stretch** along a
    # seed-derived flow axis. Sky CotL terrain has visible direction —
    # ridges run along the wind / valley axis — so stretching the noise
    # 2.2× along one axis produces sweeping forms instead of equal-
    # frequency-in-all-directions noise. Rotation theta varies with
    # seed so different prompts get different ridge orientations.
    #
    # Reduced from 4 octaves to 2 (1.0 + 0.40); the upper octaves were
    # producing the noisy "function on a grid" read.
    # Aniso theta: when caller passes a ridge-derived angle, align the
    # noise stretch with the ridge axis so terrain features run WITH
    # the ridge, not cross-grain. Falls back to a seed-derived angle
    # when no ridge is present.
    if aniso_theta_rad is not None:
        theta = float(aniso_theta_rad)
    else:
        theta = float(seed % 360) * (np.pi / 180.0)
    cos_t, sin_t = np.cos(theta), np.sin(theta)
    along_stretch = 0.62  # 1.6× longer wavelength along ridge axis

    fbm = np.zeros((res, res), dtype=np.float32)
    Xw_world = X.astype(np.float32) + warp_x
    Yw_world = Y.astype(np.float32) + warp_y
    # Aniso coords (broad octave only): rotate into ridge-aligned frame,
    # stretch the along-axis. Higher-frequency octaves use isotropic
    # world-XY so fine detail stays uncombed.
    along = (cos_t * Xw_world + sin_t * Yw_world) * along_stretch
    cross = -sin_t * Xw_world + cos_t * Yw_world
    # Multi-scale octaves — broad / medium / small features mixed so
    # the terrain has identifiable scale variation (not "every swell
    # the same size"). Wavelengths roughly 60 / 28 / 13 BU on the
    # 160 BU plane — the broad octave defines the rolling silhouette,
    # medium adds character, small adds painterly grain.
    for octave_i, (amp, freq) in enumerate([(0.90, 0.45), (0.70, 1.0), (0.30, 2.1)]):
        cx_axis = coords * freq / 28.0
        layer = nz_fbm.noise2array(cx_axis, cx_axis).astype(np.float32)
        # Per-octave anisotropy: only the BROAD octave (i=0) stretches
        # along the ridge axis. Medium and high octaves stay isotropic
        # — stretching all of them was producing the "combed" surface.
        if octave_i == 0:
            ax_pix = (along + size) / span * (res - 1)
            ay_pix = (cross + size) / span * (res - 1)
        else:
            ax_pix = (Xw_world + size) / span * (res - 1)
            ay_pix = (Yw_world + size) / span * (res - 1)
        warped = map_coordinates(
            layer, [ay_pix, ax_pix], order=1, mode="reflect"
        ).astype(np.float32)
        fbm += amp * warped
    # Post-mul 1.6 brings max FBM contribution to ~3 BU on a 16 BU
    # max-elevation scene — gentle mixed-scale terrain, not pancake.
    h += fbm * 1.6

    # Micro detail — heavily reduced (was 0.25 amplitude). Painterly
    # mode wants near-zero ground noise; Sky's foreground is glassy
    # smooth. Keep a sliver so the meadow doesn't read as a balloon.
    micro = nz_micro.noise2array(coords / 6.0, coords / 6.0).astype(np.float32)
    h += micro * 0.06

    # Optional: dunes layer (palette_preset='desert' triggers it).
    # Two crossing sinusoids at 45 / 80 BU wavelengths produce the
    # rolling-and-crossing dune field characteristic of *Sky CotL*'s
    # Golden Wasteland — long-period waves, not noise.
    if dunes:
        dune_dir = np.array([0.94, 0.34], dtype=np.float32)   # ~20° tilt
        dune_dir2 = np.array([-0.34, 0.94], dtype=np.float32)
        h += (1.4 * np.sin(2 * np.pi * (dune_dir[0] * X + dune_dir[1] * Y) / 45.0 + 0.3)).astype(np.float32)
        h += (0.6 * np.sin(2 * np.pi * (dune_dir2[0] * X + dune_dir2[1] * Y) / 80.0)).astype(np.float32)

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
    # Biased toward "single dominant biome" — Sky CotL scenes are
    # mono-toned per vista (90% Daylight Prairie grass, 90% Wasteland
    # sand). Quantiles compressed: meadow now covers 0.06..0.72 (66%
    # of land, up from 39%), forest 0.72..0.86, alpine 0.86..0.96,
    # snow >0.96. Was producing the "heatmap" stripe read.
    return {
        "beach_top":  float(np.quantile(land, 0.06)),
        "meadow_top": float(np.quantile(land, 0.72)),
        "forest_top": float(np.quantile(land, 0.86)),
        "alpine_top": float(np.quantile(land, 0.96)),
        "snow_top":   float(np.quantile(land, 0.995)),
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


def _apply_stylised_passes(elev, col, palette, *, seed: int = 0):
    """Lift the flat biome-band colour into a stylised low-poly read.

    Two multiplicative-style passes, both pure numpy on the (res, res, 3)
    colour grid:

      1. **Slope tint** — cliffs (high gradient magnitude) lerp toward a
         deep dark stone colour, so steep faces read as rock-shadow
         notches not green sausages. Widened from [0.35, 0.75] to
         [0.20, 0.60] so more of the rolling terrain catches the rock
         tint, and rock target pushed from 0.6× → 0.3× so cliffs read
         as near-black silhouette breaks (Bad North style).
      2. **HSV value jitter** — sample 2-octave value-noise at the grid
         coords, quantise to 5 buckets ×3 % each (±12 % total range)
         and shift the colour's brightness. Was ±4 %/3-bucket which was
         visually invisible; ±12 %/5-bucket is in the Polygon-Runway
         "macro patch" range.

    AO is baked later (after the Blender mesh exists) and multiplied
    into the same vertex-colour attribute. See ``_bake_ao_to_col``.
    """
    import numpy as np

    out = np.array(col, dtype=np.float32, copy=True)

    # 1. Slope tint — gentle. Painterly mode wants the rock band to read
    # as a *suggestion* of rock under the cel-toon shading, not a high-
    # contrast notch. Toon BSDF amplifies everything, so the amplitude
    # is half what the chunky-poly pipeline used.
    gy, gx = np.gradient(elev)
    slope = np.sqrt(gx * gx + gy * gy)
    s = np.clip((slope - 0.30) / 0.50, 0, 1)
    s = s * s * (3.0 - 2.0 * s)
    rock_rgb = np.array(_palette_linear("stone", palette), dtype=np.float32) * 0.50
    out = out * (1 - s[..., None]) + rock_rgb * s[..., None]

    # 2. Smooth low-frequency macro variation — broad pasture tones, not
    # high-contrast splotches. ±5 % brightness off a smooth FBM (no
    # quantisation: continuous variation reads painterly).
    res = elev.shape[0]
    coords = np.indices((res, res), dtype=np.float32) / float(res)
    seed_phase = float(seed) * 0.137
    n1 = np.cos(coords[0] * 6.0 + seed_phase) * np.sin(coords[1] * 7.0 + seed_phase * 1.3)
    n2 = np.cos(coords[0] * 17.0 + seed_phase * 2.1) * np.sin(coords[1] * 19.0 + seed_phase * 1.7)
    fbm = 0.7 * n1 + 0.3 * n2  # roughly in [-1, +1]
    tint = (fbm * 0.05)[..., None]  # ±5 % continuous brightness.
    out = np.clip(out * (1.0 + tint), 0, 1)

    # 3. Vertical brightness gradient — Sky's biggest tonal lever. Bake
    # a +18 % brightness on highs / -8 % on lows so the silhouette
    # reads with sun-touched ridges and shadowed valleys before any
    # actual lighting is applied.
    z_lo, z_hi = float(elev.min()), float(elev.max())
    if z_hi - z_lo > 1e-3:
        z_norm = ((elev - z_lo) / (z_hi - z_lo)).astype(np.float32)
        vert_grad = (0.92 + 0.26 * z_norm)[..., None]
        out = np.clip(out * vert_grad, 0, 1)

    # 4. Crest highlight strip — second derivative of elev highlights
    # ridge tops; soft positive Gaussian Laplacian → multiply by
    # (1 + 0.10) on those cells. Looks like sun-touched snow rims.
    try:
        from scipy.ndimage import gaussian_laplace
        crest = (-gaussian_laplace(elev.astype(np.float32), sigma=2.0)).astype(np.float32)
        # Normalize to [0, 1] using positive max (negative = valleys).
        max_pos = max(float(crest.max()), 1e-3)
        crest = np.clip(crest / max_pos, 0, 1)
        crest = crest * crest  # square so only sharpest ridges hit
        out = np.clip(out * (1.0 + 0.10 * crest[..., None]), 0, 1)
    except Exception:
        pass

    # 5. Surface character — occasional rocky / dirt patches. Sample a
    # coarse Voronoi via low-frequency noise; cells with the lowest
    # ~12 % values get tinted toward a darker desaturated rock colour.
    # Reads as "scattered rocky outcrops" without breaking the calm
    # meadow read. Sky CotL has occasional dirt-patch breakup like this.
    try:
        from opensimplex import OpenSimplex
        nz_patch = OpenSimplex(seed=int(seed) + 41)
        # Per-cell sample; one octave at ~22 BU wavelength.
        coords1d = np.linspace(-1.0, 1.0, res, dtype=np.float64) * (res / 22.0)
        patch_field = nz_patch.noise2array(coords1d, coords1d).astype(np.float32)
        # Threshold to bottom ~12 % of cells (organic patches, sparse).
        patch_mask = np.clip((-patch_field - 0.55) / 0.30, 0, 1)
        patch_mask = patch_mask * patch_mask  # square for sharper edges
        rock_patch_rgb = np.array(
            _palette_linear("stone", palette), dtype=np.float32) * 0.55
        m = patch_mask[..., None]
        out = np.clip(out * (1.0 - 0.45 * m) + rock_patch_rgb * 0.45 * m, 0, 1)
    except Exception:
        pass

    return out


def _split_all_face_edges(obj):
    """Edge-split every edge of a mesh so that each face owns its own
    set of vertices (no sharing across faces). After this, POINT-domain
    colour attributes behave as per-face flat colours: writing the same
    RGB to all of a face's verts produces a perfectly flat patch with
    no interpolation against neighbours, which is the load-bearing
    rasterisation step for the indie low-poly look.

    Vertex count roughly triples (each shared corner becomes N copies),
    but the total stays bounded — at 5k pre-split verts → ~15k post-split,
    well within OBJ/Three.js budgets.
    """
    import bmesh
    me = obj.data
    bm = bmesh.new()
    bm.from_mesh(me)
    # ``bmesh.ops.split_edges`` with all edges = make every edge a seam.
    bmesh.ops.split_edges(bm, edges=bm.edges[:])
    bm.to_mesh(me)
    bm.free()
    me.update()


def _write_per_face_col(mesh, col_grid, size):
    """Sample ``col_grid`` (res, res, 3 linear RGB) at each face centroid
    using nearest-neighbour, then write the per-face RGB to every
    vertex of that face. Assumes ``_split_all_face_edges`` was called
    so each vertex belongs to exactly one face.

    Nearest-neighbour (not bilinear) sampling is intentional — it's what
    produces sharp biome boundaries between adjacent faces. Bilinear
    would re-introduce the soft gradient the whole exercise is trying
    to eliminate.

    Returns the per-face RGB array (shape ``(n_polys, 3)``) for downstream
    passes (Voronoi macro, etc.) that want the same per-face look.
    """
    import numpy as np

    n_polys = len(mesh.polygons)
    n_verts = len(mesh.vertices)
    res = col_grid.shape[0]
    half = float(size)

    verts_flat = np.empty(n_verts * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", verts_flat)
    verts_xy = verts_flat.reshape(n_verts, 3)[:, :2]

    centroids = np.zeros((n_polys, 2), dtype=np.float32)
    for i, poly in enumerate(mesh.polygons):
        s = np.zeros(2, dtype=np.float32)
        for vi in poly.vertices:
            s += verts_xy[vi]
        centroids[i] = s / max(len(poly.vertices), 1)

    sx = np.clip((centroids[:, 0] + half) / (2.0 * half) * (res - 1), 0, res - 1)
    sy = np.clip((centroids[:, 1] + half) / (2.0 * half) * (res - 1), 0, res - 1)
    ix = np.round(sx).astype(np.int32)
    iy = np.round(sy).astype(np.int32)
    face_rgb = col_grid[iy, ix]  # (n_polys, 3)

    rgba = np.empty((n_verts, 4), dtype=np.float32)
    rgba[:, 3] = 1.0
    for poly_i, poly in enumerate(mesh.polygons):
        c = face_rgb[poly_i]
        for vi in poly.vertices:
            rgba[vi, :3] = c

    col_attr = mesh.color_attributes.get("Col")
    if col_attr is None:
        col_attr = mesh.color_attributes.new(name="Col", type="FLOAT_COLOR", domain="POINT")
    col_attr.data.foreach_set("color", rgba.flatten())
    return face_rgb


def _apply_painterly_hsv_macro(mesh, *, seed: int = 0):
    """Continuous low-frequency FBM in HSV space — painterly hue+sat+val
    drift across the terrain instead of cell-bucketed value splotches.

    Three independent OpenSimplex generators feed three HSV channels:
      - Hue: ±0.015 (subtle warm/cool drift)
      - Sat: ±10 % multiplicative
      - Val: ±5 % multiplicative

    Wavelengths chosen so the drift reads as broad pasture variation
    (~30 BU half-wave), not high-frequency noise. Sky's grass shows
    exactly this kind of continuous painterly wash — neighbouring
    patches are different, but never quantised.

    Replaces the old ``_apply_voronoi_macro`` cell-hash splotches.
    """
    import numpy as np
    from opensimplex import OpenSimplex

    n_polys = len(mesh.polygons)
    n_verts = len(mesh.vertices)
    if n_polys == 0:
        return

    verts_flat = np.empty(n_verts * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", verts_flat)
    verts_xy = verts_flat.reshape(n_verts, 3)[:, :2]

    centroids = np.zeros((n_polys, 2), dtype=np.float32)
    for i, poly in enumerate(mesh.polygons):
        s = np.zeros(2, dtype=np.float32)
        for vi in poly.vertices:
            s += verts_xy[vi]
        centroids[i] = s / max(len(poly.vertices), 1)

    nz_h = OpenSimplex(seed=int(seed) + 11)
    nz_s = OpenSimplex(seed=int(seed) + 12)
    nz_v = OpenSimplex(seed=int(seed) + 13)

    # Sample noise per face centroid (one-by-one — vectorisation would
    # need a regular grid; n_polys ≤ ~40 k so the loop is fine, ~50 ms).
    fh = np.empty(n_polys, dtype=np.float32)
    fs = np.empty(n_polys, dtype=np.float32)
    fv = np.empty(n_polys, dtype=np.float32)
    for i in range(n_polys):
        fh[i] = nz_h.noise2(centroids[i, 0] / 22.0, centroids[i, 1] / 22.0)
        fs[i] = nz_s.noise2(centroids[i, 0] / 30.0, centroids[i, 1] / 30.0)
        fv[i] = nz_v.noise2(centroids[i, 0] / 18.0, centroids[i, 1] / 18.0)

    col_attr = mesh.color_attributes.get("Col")
    if col_attr is None:
        return
    rgba = np.empty(n_verts * 4, dtype=np.float32)
    col_attr.data.foreach_get("color", rgba)
    rgba = rgba.reshape(n_verts, 4)

    # Per-face RGB → HSV → shift → RGB. Vectorise via matplotlib helper.
    from matplotlib.colors import rgb_to_hsv, hsv_to_rgb
    face_rgb = np.empty((n_polys, 3), dtype=np.float32)
    for poly_i, poly in enumerate(mesh.polygons):
        face_rgb[poly_i] = rgba[poly.vertices[0], :3]
    hsv = rgb_to_hsv(np.clip(face_rgb, 0, 1).reshape(-1, 1, 3)).reshape(-1, 3)
    hsv[:, 0] = (hsv[:, 0] + fh * 0.015) % 1.0
    hsv[:, 1] = np.clip(hsv[:, 1] * (1.0 + fs * 0.10), 0, 1)
    hsv[:, 2] = np.clip(hsv[:, 2] * (1.0 + fv * 0.05), 0, 1)
    new_rgb = hsv_to_rgb(hsv.reshape(-1, 1, 3)).reshape(-1, 3)

    for poly_i, poly in enumerate(mesh.polygons):
        c = new_rgb[poly_i]
        for vi in poly.vertices:
            rgba[vi, :3] = c
    col_attr.data.foreach_set("color", rgba.flatten())


# Legacy alias — call sites use ``_apply_voronoi_macro``; keep working.
_apply_voronoi_macro = _apply_painterly_hsv_macro


def _bake_ao_to_col(obj, mesh, *, samples: int = 8, distance: float = 4.0):
    """Cycles-bake AO into the active vertex colour attribute, then read
    the values back and return as a (N,) numpy array. The attribute itself
    is RESTORED to whatever was there before the bake — we use a temporary
    side attribute as the bake target so the build-script-authored ``Col``
    isn't clobbered. Returns None on bake failure (caller falls back to
    leaving colours un-shadowed).

    Cost: ~1-3s on a 32k-vert decimated terrain at 8 samples; acceptable
    for the maquette pipeline. Cycles must be the active engine; we
    save/restore the previous engine + bake target settings.
    """
    import bpy
    import numpy as np

    scene = bpy.context.scene
    if scene is None:
        return None

    ao_name = "_AO_TEMP"
    # Drop any leftover from a previous failed bake.
    if ao_name in mesh.color_attributes:
        mesh.color_attributes.remove(mesh.color_attributes[ao_name])
    ao_attr = mesh.color_attributes.new(name=ao_name, type="FLOAT_COLOR", domain="POINT")
    # Active color attribute = bake target.
    prev_active = mesh.color_attributes.active_color
    mesh.color_attributes.active_color = ao_attr

    prev_engine = scene.render.engine
    prev_target = scene.render.bake.target
    prev_samples = scene.cycles.samples if hasattr(scene, "cycles") else None
    prev_use_normalize = getattr(scene.render.bake, "use_pass_indirect", None)

    scene.render.engine = "CYCLES"
    scene.render.bake.target = "VERTEX_COLORS"
    if hasattr(scene, "cycles"):
        scene.cycles.samples = max(int(samples), 1)
    bake_settings = scene.render.bake
    if hasattr(bake_settings, "use_pass_direct"):
        bake_settings.use_pass_direct = False
    if hasattr(bake_settings, "use_pass_indirect"):
        bake_settings.use_pass_indirect = False
    if hasattr(bake_settings, "cage_extrusion"):
        bake_settings.cage_extrusion = 0.0

    # Cycles AO bake samples a hemisphere; ``distance`` controls how far
    # the rays travel before hitting nothing. Larger = softer shadows
    # (shoulders darken more), smaller = crisp local cavity. 4 BU is a
    # good default for our 160 BU plane.
    if hasattr(scene.world, "light_settings"):
        scene.world.light_settings.distance = float(distance)

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    ao_array = None
    try:
        bpy.ops.object.bake(type="AO")
        n = len(ao_attr.data)
        flat = np.empty(n * 4, dtype=np.float32)
        ao_attr.data.foreach_get("color", flat)
        ao_array = flat.reshape(n, 4)[:, 0]
    except Exception as exc:  # noqa: BLE001
        print(f"[eroded_terrain] AO bake failed ({exc}); skipping AO pass")
    finally:
        # Restore engine + bake settings + clean up temp attribute.
        scene.render.engine = prev_engine
        scene.render.bake.target = prev_target
        if prev_samples is not None and hasattr(scene, "cycles"):
            scene.cycles.samples = prev_samples
        if ao_name in mesh.color_attributes:
            mesh.color_attributes.remove(mesh.color_attributes[ao_name])
        if prev_active is not None:
            try:
                mesh.color_attributes.active_color = prev_active
            except Exception:
                pass
    return ao_array


def _decimate_terrain(obj, target_verts: int) -> None:
    """PLANAR-decimate the terrain mesh, preserving silhouette ridges.

    Was COLLAPSE/ratio-based; PLANAR with a tight angle limit keeps
    crisp ridge edges while dissolving co-planar faces. This pairs
    better with the painterly Sky-CotL look: long sweeping ridges
    survive instead of getting smeared by an unbiased collapse.

    Falls back to COLLAPSE if PLANAR doesn't reach the vertex target
    in one pass (rare on heightmaps but possible on near-flat plains
    where everything is co-planar and the angle gate blocks reduction).

    Vertex colours (Col FLOAT_COLOR domain="POINT") propagate through
    both decimator paths.
    """
    import bpy
    import math

    me = obj.data
    n = len(me.vertices)
    if n <= int(target_verts):
        return

    prev_active = bpy.context.view_layer.objects.active
    prev_selected = list(bpy.context.selected_objects)
    try:
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

        # Save a snapshot of the original mesh data via bmesh, in case
        # DISSOLVE over-collapses (Sky-flat terrain has very few non-
        # coplanar regions; the angle-limited dissolve would crush
        # everything to <5k verts and the meadow would read as a low-
        # poly plane). We restore from snapshot and use COLLAPSE on the
        # original if DISSOLVE drops below the floor.
        import bmesh as _bmesh
        snapshot_bm = _bmesh.new()
        snapshot_bm.from_mesh(me)

        # Try DISSOLVE (planar / angle-limited) first — preserves
        # silhouette ridges by collapsing co-planar faces only. Blender's
        # Decimate enum spells this ``DISSOLVE``; UI labels it "Planar".
        mod_name = "TerrainLOD"
        mod = obj.modifiers.new(mod_name, "DECIMATE")
        mod.decimate_type = "DISSOLVE"
        mod.angle_limit = math.radians(1.5)
        mod.use_dissolve_boundaries = True
        try:
            bpy.ops.object.modifier_apply(modifier=mod_name)
        except RuntimeError as exc:
            print(f"[eroded_terrain] PLANAR decimate failed ({exc}); falling back to COLLAPSE")
            if mod_name in obj.modifiers:
                obj.modifiers.remove(obj.modifiers[mod_name])

        # Vert floor — if DISSOLVE over-collapsed (mostly-flat terrain),
        # restore from snapshot and use COLLAPSE to ratio-target instead.
        # Floor of 12k preserves enough detail for smooth shading on a
        # 160 BU plane without giving up too much LOD savings.
        n_after_planar = len(me.vertices)
        floor = max(int(target_verts) // 3, 12000)
        if n_after_planar < floor:
            print(f"[eroded_terrain] DISSOLVE under-shot ({n_after_planar} < "
                  f"{floor}); restoring snapshot + COLLAPSE")
            # Wipe current mesh + restore from snapshot.
            me.clear_geometry()
            snapshot_bm.to_mesh(me)
            me.update()
            n_restored = len(me.vertices)
            ratio = max(0.02, min(1.0, float(target_verts) / float(n_restored)))
            mod_r = obj.modifiers.new("TerrainLOD_R", "DECIMATE")
            mod_r.decimate_type = "COLLAPSE"
            mod_r.ratio = ratio
            try:
                bpy.ops.object.modifier_apply(modifier="TerrainLOD_R")
            except RuntimeError as exc:
                print(f"[eroded_terrain] COLLAPSE restore failed ({exc})")
                if "TerrainLOD_R" in obj.modifiers:
                    obj.modifiers.remove(obj.modifiers["TerrainLOD_R"])
        else:
            # Optional COLLAPSE follow-up if DISSOLVE OVER-shot — only
            # triggers when vert count is way above target (>1.3×), e.g.
            # rugged terrain with lots of non-coplanar faces.
            if n_after_planar > int(target_verts) * 1.3:
                ratio = max(0.02, min(1.0, float(target_verts) / float(n_after_planar)))
                mod2 = obj.modifiers.new("TerrainLOD2", "DECIMATE")
                mod2.decimate_type = "COLLAPSE"
                mod2.ratio = ratio
                try:
                    bpy.ops.object.modifier_apply(modifier="TerrainLOD2")
                except RuntimeError as exc:
                    print(f"[eroded_terrain] COLLAPSE follow-up failed ({exc})")
                    if "TerrainLOD2" in obj.modifiers:
                        obj.modifiers.remove(obj.modifiers["TerrainLOD2"])
        snapshot_bm.free()
    finally:
        bpy.ops.object.select_all(action="DESELECT")
        for o in prev_selected:
            try:
                o.select_set(True)
            except (ReferenceError, RuntimeError):
                pass
        bpy.context.view_layer.objects.active = prev_active

    print(f"[eroded_terrain] decimated {n} -> {len(me.vertices)} verts (target {target_verts})")


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
    max_peak_height: float | None = 12.0,
    plain_offset: float = 2.4,
    sea_level: float = 0.5,
    erode_iters: int = 4,
    deposition: float = 0.4,
    edge_falloff: float = 18.0,
    edge_floor: float | None = None,
    resolution: int = 256,
    palette: dict[str, PaletteRGB] | None = None,
    palette_preset: str | None = None,
    smooth_shading: bool = True,
    water: bool = True,
    water_color: tuple[float, float, float, float] = (0.20, 0.42, 0.60, 0.8),
    water_offset: float = 0.10,
    water_thickness: float = 0.4,
    water_min_area_cells: int = 12,
    water_low_poly_shader: bool = True,
    target_verts: int | None = 30000,
    composition=None,
    realistic_textures: bool | None = None,
    bake_for_export: bool | None = None,
    bake_resolution: int = 1024,
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
      * ``target_verts`` — post-build DECIMATE target. Default 32000.
        Sourced from a 256² (65k-vert) grid, so 32k keeps roughly
        half the topology — enough density that hill silhouettes
        read as smooth rather than faceted at typical camera
        distances, while staying small enough that GLB downloads
        for the browser viewer remain ~3-5 MB after Draco compress.
        Pass ``None`` to skip decimation entirely (max detail; only
        do this for hero renders that don't ship to the viewer).
        Was 12000 pre-2026-05; bumped after users called out
        terrain reading as "too few polygons" on wide vistas.
        Vertex colors are preserved through the COLLAPSE decimator
        so biome-driven scatter still works on the decimated mesh.
      * ``realistic_textures`` — when True, replace the flat
        vertex-color material with a PBR shader that blends 5
        Polyhaven CC0 texture sets (grass / forest / rock / snow /
        sand) by a per-vertex Splat mask, with box projection +
        Voronoi macro overlay. Requires the textures present in
        ``runtime/textures/`` (see that dir's README for sources);
        falls back to vertex-color silently if any are missing.
        ``None`` (default) reads ``MAQUETTE_REALISTIC_TERRAIN`` from
        the environment so the maquette runner can force this on for
        realistic-mode pipelines without LLM cooperation.
      * ``bake_for_export`` — only meaningful when ``realistic_textures``
        is True. Bakes the procedural shader (Voronoi macro + per-pixel
        Splat blend) to flat 2D textures so glTF export captures the
        actual look (otherwise the browser sees a fallback grey
        because procedural nodes don't survive the exporter). Slow
        (~10-30s for a 2k bake); only set when you're going to render +
        export the GLB. Cycles render quality of the .blend itself is
        not improved by this flag.
        ``None`` (default) reads ``MAQUETTE_BAKE_FOR_EXPORT`` from
        the environment for the same reason as ``realistic_textures``.
      * ``bake_resolution`` — texture size for the bake target. 1024
        is the browser-friendly default (~5 MB GLB after Draco). Bump
        to 2048 for hero/marketing renders; beyond that the procedural
        shader's effective resolution is the limiting factor.
    """
    import bpy
    import numpy as np

    palette = _resolve_palette(palette, palette_preset)
    if edge_floor is None:
        # Default: rim sits just above sea level so inland scenes don't
        # flood. Coastal prompts override with a sub-sea-level value.
        edge_floor = max(float(sea_level) + 0.2, float(plain_offset) - 1.5)

    # Env-var defaults — let the maquette runner force realistic-mode
    # behavior without depending on the LLM remembering to pass the
    # kwargs. Explicit ``True``/``False`` always wins over the env.
    import os as _os
    if realistic_textures is None:
        realistic_textures = _os.environ.get("MAQUETTE_REALISTIC_TERRAIN", "0") == "1"
    if bake_for_export is None:
        bake_for_export = _os.environ.get("MAQUETTE_BAKE_FOR_EXPORT", "0") == "1"

    # Soft-deprecate ``peaks=`` for painterly mode — when the build
    # script doesn't supply a Ridge but does supply peaks, warn the
    # operator (and any LLM trace reader) that Ridge is the preferred
    # silhouette primitive. Doesn't disable peaks; just nudges.
    if peaks and (composition is None
                   or not getattr(composition, "ridges", None)):
        print(f"[eroded_terrain] WARNING: {len(peaks)} peak(s) used "
              f"without a Ridge — peaks=[] is gradually deprecating in "
              f"favour of Composition(ridges=[Ridge(...)]). Heroes can "
              f"sit on a sweeping Ridge silhouette for the Sky CotL "
              f"painterly read.")

    # Painterly mode peak handling — when the composition includes any
    # Ridge primitive, the Ridge owns the silhouette. Don't drop peaks
    # entirely (that left scenes pancake-flat); instead cap them HARD
    # to 4-8 BU so they read as gentle hill variation around the ridge,
    # not competing splats. Empty-ridges scenes still respect peaks at
    # full height for explicit isolated-peak prompts.
    if composition is not None and getattr(composition, "ridges", None) and peaks:
        peaks_capped = []
        for cx, cy, sigma, h_p in peaks:
            new_h = min(float(h_p), 6.0)  # tight cap when ridges present
            peaks_capped.append((cx, cy, sigma, new_h))
        print(f"[eroded_terrain] painterly mode: clamping {len(peaks)} "
              f"peaks to ≤6 BU (Ridge owns silhouette)")
        peaks = peaks_capped

    # Clamp incoming peak heights — Sky CotL terrain reads as serene/
    # horizontal, not Skyrim/vertical. The LLM brief asks for 8-12 BU
    # peaks but the model often pushes higher; this is a hard ceiling
    # so any peak above ``max_peak_height`` is capped at that value.
    # Pass ``max_peak_height=None`` (or ``=30``) when an explicit
    # "tall mountain" prompt asks for it.
    clamped_peaks = list(peaks)
    if max_peak_height is not None:
        cap = float(max_peak_height)
        clamped_peaks = [
            (cx, cy, sigma, min(float(h), cap))
            for (cx, cy, sigma, h) in clamped_peaks
        ]
        n_clamped = sum(
            1 for orig, c in zip(peaks, clamped_peaks)
            if abs(orig[3] - c[3]) > 1e-3
        )
        if n_clamped:
            print(f"[eroded_terrain] clamped {n_clamped}/{len(peaks)} peaks "
                  f"to max_peak_height={cap:.1f}")
    # Derive aniso theta from the first ridge's overall direction so
    # the broad-octave noise stretches WITH the ridge, not against it.
    # Falls back to seed-derived angle when no ridge is present.
    aniso_theta_rad: float | None = None
    if (composition is not None and getattr(composition, "ridges", None)
            and len(composition.ridges) > 0):
        first = composition.ridges[0]
        wp = list(first.waypoints)
        if len(wp) >= 2:
            dx = float(wp[-1][0]) - float(wp[0][0])
            dy = float(wp[-1][1]) - float(wp[0][1])
            if (dx * dx + dy * dy) > 1e-3:
                import math as _math
                aniso_theta_rad = _math.atan2(dy, dx)
                print(f"[eroded_terrain] aniso aligned to ridge axis "
                      f"({_math.degrees(aniso_theta_rad):.0f}°)")

    print(f"[eroded_terrain] base heightmap (peaks={len(clamped_peaks)}, "
          f"troughs={len(troughs)})")
    # Desert palette → enable dunes sinusoid layer in the heightmap.
    dunes_active = (palette_preset or "").lower() == "desert"
    if dunes_active:
        print("[eroded_terrain] dunes layer enabled (palette_preset='desert')")
    H0, alpine = _build_heightmap(
        resolution, float(size), int(seed),
        clamped_peaks, list(troughs), float(plain_offset),
        float(edge_falloff), float(edge_floor),
        aniso_theta_rad=aniso_theta_rad,
        dunes=dunes_active,
    )
    print(f"[eroded_terrain] eroding ({erode_iters} iter, deposition={deposition:.2f})")
    H = _erode(H0, n_iter=int(erode_iters), deposition=float(deposition))
    # Composition pass — bend the post-erosion heightmap to fit the
    # known scene composition (hero plateaus, path saddles, water basin).
    # See runtime/influence.py for the operators. Applied AFTER erosion
    # so plateaus and saddles aren't washed back into noise; the LLM
    # passes a Composition built from the same hero/path/water positions
    # it'll use for `place(...)` calls downstream so the terrain shape
    # matches the placement.
    if composition is not None:
        from infinigen.maquette.runtime import influence as _infl
        coords = np.linspace(-float(size), float(size), int(resolution),
                             dtype=np.float32)
        Xg, Yg = np.meshgrid(coords, coords)
        # Sample the eroded surface for hero target_z fallbacks: nearest-
        # neighbour read of H against world XY → grid index.
        def _eroded_sample(x: float, y: float) -> float:
            res = H.shape[0]
            fi = (x + float(size)) / (2.0 * float(size)) * (res - 1)
            fj = (y + float(size)) / (2.0 * float(size)) * (res - 1)
            i = int(np.clip(round(fi), 0, res - 1))
            j = int(np.clip(round(fj), 0, res - 1))
            return float(H[j, i])
        H = _infl.apply_composition(H, Xg, Yg, composition, _eroded_sample)
        print(f"[eroded_terrain] composition applied "
              f"(heroes={len(composition.heroes)}, paths={len(composition.paths)}, "
              f"water={'yes' if composition.water else 'no'})")
    print(f"[eroded_terrain] elevation range {H.min():.2f}..{H.max():.2f}")
    COL = _biome_colors(H, alpine, float(sea_level), palette)
    # Stylised passes — slope tint + quantised palette jitter. Lifts
    # the flat biome bands into a stylised low-poly read. Skip when
    # realistic textures are on, since the PBR shader does its own
    # painting from these colours and a slope-darken would double up.
    if not realistic_textures:
        COL = _apply_stylised_passes(H, COL, palette, seed=int(seed))
        # Watercolour-paper screen-blend overlay — adds the painterly
        # "paper grain" wash Sky CotL surfaces have. Tile the 512²
        # grayscale texture across world XY at ~12 BU/tile, screen-
        # blend at 18 % strength. Screen blend (1 - (1-a)(1-b)) lifts
        # values without darkening — preserves biome colour intent.
        try:
            from PIL import Image as _Image
            _tex_path = (Path(__file__).parent / "textures" /
                         "watercolour_512.png")
            if _tex_path.is_file():
                tex = (np.asarray(_Image.open(_tex_path).convert("L"),
                                  dtype=np.float32) / 255.0)
                _coords_t = np.linspace(-float(size), float(size),
                                        int(resolution), dtype=np.float32)
                _Xt, _Yt = np.meshgrid(_coords_t, _coords_t)
                # Rotate tex coords 31° so seams don't align with world axes.
                _ct, _st = np.cos(0.541), np.sin(0.541)
                _ux = _ct * _Xt + _st * _Yt
                _uy = -_st * _Xt + _ct * _Yt
                tile_bu = 12.0
                tx = (_ux / tile_bu) % 1.0
                ty = (_uy / tile_bu) % 1.0
                ti = (tx * tex.shape[1]).astype(np.int32) % tex.shape[1]
                tj = (ty * tex.shape[0]).astype(np.int32) % tex.shape[0]
                wash = tex[tj, ti][..., None]  # (res, res, 1)
                strength = 0.18
                COL = 1.0 - (1.0 - COL) * (1.0 - wash * strength)
                COL = np.clip(COL, 0, 1).astype(np.float32)
        except Exception as _exc:  # noqa: BLE001
            print(f"[eroded_terrain] watercolour overlay skipped: {_exc}")

        # Composition-driven colour passes — path corridors + hero
        # plateau edge rings. Both run on the (res, res, 3) COL grid;
        # build the world-XY mesh grid once and share.
        if composition is not None:
            from infinigen.maquette.runtime import influence as _infl
            _coords = np.linspace(-float(size), float(size), int(resolution),
                                  dtype=np.float32)
            _Xg, _Yg = np.meshgrid(_coords, _coords)
            if composition.paths:
                # Path tint — paint Pathway corridors with their archetype
                # colour (dirt/stone/wood/sand). The carve in
                # apply_composition only changed terrain HEIGHT; without
                # this pass the carved path keeps its biome colour and
                # reads as a depression in meadow rather than a road.
                COL = _infl.apply_path_tint(COL, _Xg, _Yg, composition)
            if composition.heroes:
                # Dark plateau-edge ring — only for MESA heroes (sharp
                # hardness >= 1.8). Painterly Gaussian-dome heroes
                # (hardness ~1.0-1.4) don't need a ring; in fact the
                # ring made the donut shape MORE visible. Filter and
                # apply to a sub-composition.
                from dataclasses import replace as _dc_replace
                mesa_heroes = [h for h in composition.heroes
                               if h.hardness >= 1.8]
                if mesa_heroes:
                    sub_comp = _dc_replace(composition, heroes=mesa_heroes)
                    COL = _infl.apply_plateau_edge_ring(COL, _Xg, _Yg, sub_comp)

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

    # Painterly stylised mode wants SMOOTH shading. The per-vertex Col
    # gradient + Toon BSDF cel bands produce the soft rolling read that
    # Sky CotL uses; flat shading would re-introduce the chunky low-
    # poly look the user explicitly rejected. Realistic mode also uses
    # smooth shading.
    for poly in me.polygons:
        poly.use_smooth = bool(smooth_shading)

    # Painterly Sky-CotL terrain material — pure Lambert / Diffuse BSDF
    # fed by the per-vertex Col attribute. Sky's terrain shading is
    # CONTINUOUS gradient (Lambert + IBL), NOT cel-banded. The earlier
    # Toon BSDF made the terrain read as "flat indie cel-shaded" —
    # different look than what we want. Plain Diffuse + a slight
    # ambient-occlusion-already-in-Col gives the soft pastoral surface
    # Sky uses on Daylight Prairie / Eden meadow.
    mat = bpy.data.materials.new("eroded_terrain_mat")
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        if n.type != "OUTPUT_MATERIAL":
            nt.nodes.remove(n)
    out_node = nt.nodes["Material Output"]

    attr = nt.nodes.new("ShaderNodeVertexColor")
    attr.layer_name = "Col"

    diffuse = nt.nodes.new("ShaderNodeBsdfDiffuse")
    diffuse.inputs["Roughness"].default_value = 1.0
    nt.links.new(attr.outputs["Color"], diffuse.inputs["Color"])
    nt.links.new(diffuse.outputs["BSDF"], out_node.inputs["Surface"])
    me.materials.append(mat)

    # Splat vertex attributes — five biome weights (grass/forest/rock/
    # snow/sand) packed into Splat (RGBA) + Splat2.R. These drive the
    # realistic-textures shader; written here even when realistic mode
    # is off so the attribute is always available for downstream
    # consumers (export, scatter overrides).
    splat = None
    if realistic_textures:
        try:
            from infinigen.maquette.runtime import terrain_textures as _tt
            splat = _tt.compute_splat_weights(H, alpine, float(sea_level))
            _tt.write_splat_attributes(me, splat)
        except Exception as exc:
            print(f"[eroded_terrain] splat write skipped ({type(exc).__name__}: {exc})")
            splat = None

    # LOD: decimate the ground for browser-friendly GLB export. Keep
    # the heightmap H around for height_at — placement accuracy is
    # bilinear on the source grid, not the decimated mesh, so this
    # only affects render geometry.
    if target_verts is not None and len(me.vertices) > int(target_verts):
        # If splat was written pre-decimate it gets interpolated by
        # COLLAPSE — fine, but we get crisper masks by re-sampling at
        # decimated vert positions. Re-sample after decimation.
        had_splat = realistic_textures and splat is not None
        if had_splat:
            # Strip pre-decimate splat attrs so we don't end up with
            # duplicated names after the post-decimate write.
            for an in ("Splat", "Splat2"):
                if an in me.color_attributes:
                    me.color_attributes.remove(me.color_attributes[an])
        _decimate_terrain(obj, int(target_verts))
        if had_splat:
            try:
                from infinigen.maquette.runtime import terrain_textures as _tt
                _tt.write_splat_post_decimate(me, splat, float(size))
            except Exception as exc:
                print(f"[eroded_terrain] post-decimate splat skipped ({type(exc).__name__}: {exc})")

    # ── Painterly Sky-CotL pipeline ─────────────────────────────────────
    # Pivoted from chunky-poly to soft painterly per the Sky: Children
    # of the Light reference. Smooth shading + per-vertex Col + Toon
    # BSDF in the material graph + warm world volume = the look.
    #
    #   1. Soft AO bake (gentle multiplier — concavities read as cool
    #      shadow not crack-black)
    #   2. Broad macro variation at scale 4 BU, ±3 % brightness only
    #      (subtle pasture tone shifts, not splotchy patches)
    # Skipped in realistic mode (PBR shader paints its own variation).
    if not realistic_textures:
        ao = _bake_ao_to_col(obj, me, samples=6, distance=3.0)
        if ao is not None:
            n_verts = len(me.vertices)
            rgba_existing = np.empty(n_verts * 4, dtype=np.float32)
            col_attr_post = me.color_attributes.get("Col")
            if col_attr_post is not None and len(ao) == n_verts:
                col_attr_post.data.foreach_get("color", rgba_existing)
                rgba_existing = rgba_existing.reshape(n_verts, 4)
                # Gentle AO floor — painterly mode wants softness, NOT
                # crack notches. Range 0.78..1.00 (was 0.45..1.00).
                ao_factor = 0.78 + 0.22 * np.clip(ao, 0, 1)
                rgba_existing[:, :3] *= ao_factor[:, None]
                rgba_existing = np.clip(rgba_existing, 0, 1)
                col_attr_post.data.foreach_set("color", rgba_existing.flatten())
                print(f"[eroded_terrain] AO baked into Col ({n_verts} verts, "
                      f"min={ao.min():.2f} max={ao.max():.2f})")
        # Subtle macro variation — broad tone shifts, not splotches.
        _apply_painterly_hsv_macro(me, seed=int(seed))

        # Distance-baked aerial perspective — lerp distant verts toward
        # a warm sky tint, baked into Col so it survives OBJ → Three.js
        # (Cycles Mist Pass is compositor-only and wouldn't reach the
        # browser viewer). Distance is measured from a "viewer anchor"
        # — the scene camera if it's already placed, else (0, -size, 0)
        # which approximates the LLM's typical south-of-origin cam.
        try:
            cam = bpy.context.scene.camera
            if cam is not None:
                anchor = np.array(cam.location[:3], dtype=np.float32)
            else:
                # Stand-in anchor: south-of-origin, slightly elevated.
                anchor = np.array([0.0, -float(size) * 0.85, float(size) * 0.35],
                                  dtype=np.float32)
            n_v = len(me.vertices)
            vflat = np.empty(n_v * 3, dtype=np.float32)
            me.vertices.foreach_get("co", vflat)
            vxyz = vflat.reshape(n_v, 3)
            dist = np.linalg.norm(vxyz - anchor, axis=1)
            # Fade ramp tuned to scene size — starts at 0.7×size, sat-
            # urates at 1.6×size, max blend 0.30 (pulled back from 0.4
            # / 1.2 / 0.45 — earlier ramp washed the mid-ground ridge
            # silhouette into the sky before it could read).
            fade_lo = float(size) * 0.7
            fade_hi = float(size) * 1.6
            fog_t = np.clip((dist - fade_lo) / max(fade_hi - fade_lo, 1.0),
                            0.0, 1.0)
            sky_lin = np.array([0.78, 0.72, 0.65], dtype=np.float32)
            ca = me.color_attributes.get("Col")
            if ca is not None and len(ca.data) == n_v:
                rgba_d = np.empty(n_v * 4, dtype=np.float32)
                ca.data.foreach_get("color", rgba_d)
                rgba_d = rgba_d.reshape(n_v, 4)
                blend = (fog_t * 0.30)[:, None]
                rgba_d[:, :3] = rgba_d[:, :3] * (1 - blend) + sky_lin * blend
                ca.data.foreach_set("color", rgba_d.flatten())
                print(f"[eroded_terrain] aerial perspective baked "
                      f"(fade {fog_t.min():.2f}..{fog_t.max():.2f})")
        except Exception as exc:  # noqa: BLE001
            print(f"[eroded_terrain] aerial perspective bake skipped: {exc}")

        print(f"[eroded_terrain] painterly pipeline applied "
              f"(faces={len(me.polygons)}, verts={len(me.vertices)})")

    # Replace the vertex-color material with the realistic PBR shader
    # when textures + splat are available.
    realistic_applied = False
    if realistic_textures and splat is not None:
        try:
            from infinigen.maquette.runtime import terrain_textures as _tt
            if _tt.textures_available():
                me.materials.clear()
                me.materials.append(_tt.build_realistic_terrain_material(seed=int(seed)))
                print("[eroded_terrain] realistic PBR material applied")
                realistic_applied = True
            else:
                print("[eroded_terrain] realistic_textures requested but textures missing — kept vertex-color material")
        except Exception as exc:
            print(f"[eroded_terrain] realistic material skipped ({type(exc).__name__}: {exc})")

    # Pin ``Col`` as the active color attribute — Blender's
    # ``wm.obj_export(export_colors=True)`` writes ONLY the active
    # color attribute as ``v X Y Z R G B``. Decimation, AO bake, and
    # realistic-textures material setup all touch ``active_color`` and
    # can leave it pointing somewhere else (or at a now-deleted attr).
    # Without this pin the OBJ exports with bare ``v X Y Z`` and the
    # browser viewer reads every terrain vertex as the unset 0.8 grey.
    col_for_export = me.color_attributes.get("Col")
    if col_for_export is not None:
        try:
            me.color_attributes.active_color = col_for_export
        except Exception as exc:
            print(f"[eroded_terrain] could not pin Col active ({exc})")

    # Bake the realistic shader for glTF export. Procedural Voronoi +
    # Splat-driven mixes don't make it through ``export_scene.gltf``;
    # this collapses them to flat 2D textures + a Principled BSDF.
    if bake_for_export and realistic_applied:
        try:
            from infinigen.maquette.runtime import terrain_textures as _tt
            ok = _tt.bake_realistic_for_export(obj, float(size), int(bake_resolution))
            if ok:
                print(f"[eroded_terrain] baked realistic shader to {bake_resolution}² textures")
            else:
                print("[eroded_terrain] bake_for_export requested but bake failed — kept procedural shader")
        except Exception as exc:
            print(f"[eroded_terrain] bake skipped ({type(exc).__name__}: {exc})")

    # SDF landmarks (Hoodoo / Arch / Pillar) — full 3D shapes built via
    # marching cubes, added as separate Blender objects. Painterly
    # material is shared with the terrain so they shade consistently.
    if (composition is not None and
            getattr(composition, "landmarks", None)):
        try:
            from infinigen.maquette.runtime import landmarks as _landmarks_mod

            def _h_at(x: float, y: float) -> float:
                # Closure over the local height_at function (defined below
                # — but reused here via the bilinear sampler structure).
                res_l = H.shape[0]
                fi = (x + float(size)) / (2.0 * float(size)) * (res_l - 1)
                fj = (y + float(size)) / (2.0 * float(size)) * (res_l - 1)
                i = int(np.clip(round(fi), 0, res_l - 1))
                j = int(np.clip(round(fj), 0, res_l - 1))
                return float(H[j, i])

            _landmarks_mod.build_landmark_meshes(
                composition.landmarks,
                height_at=_h_at,
                voxel_size=0.4,
                material=mat,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[eroded_terrain] landmarks skipped: {exc}")

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

    return Terrain(height_at=height_at, obj=obj, heightmap=H, size=float(size))


def carve_path(
    terrain: Terrain,
    waypoints: Sequence[tuple[float, float]],
    *,
    width: float = 2.5,
    blend: float = 1.5,
    depth: float = 0.0,
) -> None:
    """Flatten a corridor through the eroded terrain along a polyline.

    The corridor sits at the linearly-interpolated height of the waypoints
    (sampled from the terrain at each waypoint's XY), shifted by
    ``depth``. Within ``width / 2`` of the centerline the cells are
    fully flattened; over the next ``blend`` BU the corridor smoothsteps
    back to the original surface.

    Mutates ``terrain.heightmap`` in place + rewrites the mesh's vertex
    Z values, so a build script can call ``terrain.height_at(x, y)``
    afterward and get the carved heights for object placement on the
    path.

    Parameters
    ----------
    terrain     : the Terrain returned by ``make_eroded_terrain``.
    waypoints   : iterable of (x, y) world-space points defining the
                  path centerline. Three or more points produce a
                  natural curve; two are a straight segment.
    width       : full corridor width in BU (a 2.5 BU path is wide
                  enough for two villagers to pass).
    blend       : feather distance over which the carved height eases
                  back to the natural surface. Smaller = harder edge.
    depth       : Z offset of the carved path below the interpolated
                  waypoint height. 0 leaves the path level with the
                  surface; -0.05 to -0.10 reads as a worn cobble track.

    Notes
    -----
    The carving is purely an XY mask — it doesn't bevel or terrace.
    For a stone trail set ``depth=-0.05`` and lay a thin path mesh
    on top via the build script (terrain.height_at + 0.02).
    For a flat plaza, pass three or four waypoints describing its
    perimeter and a ``width`` larger than the plaza extent.
    """
    import numpy as np

    # Soft-fail when called against the simple make_terrain (which has no
    # heightmap to mutate). Crashing here would lose the entire build —
    # all object placement, scatter, camera setup — even though the path
    # carving is the only thing that doesn't apply. Warn and return so
    # the LLM's script still ships a viable scene; the user can rerun
    # with a make_eroded_terrain backbone if they want the real groove.
    if not hasattr(terrain, "heightmap") or terrain.heightmap is None:
        print("[carve_path] terrain has no heightmap (use make_eroded_terrain "
              "or make_multi_biome_terrain for an actual carved path); "
              "skipping carve, scene continues.")
        return
    pts = list(waypoints)
    if len(pts) < 2:
        raise ValueError("carve_path needs at least 2 waypoints")

    H = terrain.heightmap
    res = H.shape[0]
    size = float(terrain.size)
    span = 2.0 * size

    # Build per-pixel world coordinates.
    coords = np.linspace(-size, size, res, dtype=np.float32)
    GX, GY = np.meshgrid(coords, coords)

    # Per-segment: distance from each grid point to the segment + the
    # height that segment contributes (linear lerp of waypoint heights).
    waypoint_z = np.array(
        [terrain.height_at(float(px), float(py)) for px, py in pts],
        dtype=np.float32,
    )

    min_dist = np.full((res, res), np.inf, dtype=np.float32)
    seg_z = np.zeros((res, res), dtype=np.float32)

    half_w = float(width) * 0.5
    blend_w = float(blend)

    for k in range(len(pts) - 1):
        x0, y0 = float(pts[k][0]), float(pts[k][1])
        x1, y1 = float(pts[k + 1][0]), float(pts[k + 1][1])
        z0 = float(waypoint_z[k])
        z1 = float(waypoint_z[k + 1])

        dx = x1 - x0
        dy = y1 - y0
        seg_len_sq = dx * dx + dy * dy
        if seg_len_sq < 1e-9:
            continue

        # Project each grid point onto the segment, clamped to [0, 1].
        t = ((GX - x0) * dx + (GY - y0) * dy) / seg_len_sq
        t = np.clip(t, 0.0, 1.0)
        px = x0 + t * dx
        py = y0 + t * dy
        d = np.sqrt((GX - px) ** 2 + (GY - py) ** 2)
        seg_height = z0 + t * (z1 - z0)

        # Where this segment is the closest one, take its height + distance.
        closer = d < min_dist
        min_dist = np.where(closer, d, min_dist)
        seg_z = np.where(closer, seg_height, seg_z)

    target_z = seg_z + float(depth)

    # Mask: 1.0 inside the corridor, 0.0 outside, smoothstep in between.
    inner = np.clip((half_w + blend_w - min_dist) / max(blend_w, 1e-3), 0.0, 1.0)
    inner = np.where(min_dist <= half_w, 1.0, inner)
    # Smoothstep on the feather band.
    fade = inner * inner * (3.0 - 2.0 * inner)

    new_H = H * (1.0 - fade) + target_z * fade
    H[...] = new_H.astype(np.float32)

    # Rewrite the mesh's vertex Z from the new heightmap (bilinear
    # sample at each vert's XY — matches the existing height_at logic).
    obj = terrain.obj
    if obj is None or not hasattr(obj, "data"):
        return
    me = obj.data
    n_verts = len(me.vertices)
    flat = np.zeros(n_verts * 3, dtype=np.float32)
    me.vertices.foreach_get("co", flat)
    flat = flat.reshape(n_verts, 3)
    u = (flat[:, 0] + size) / span * (res - 1)
    v = (flat[:, 1] + size) / span * (res - 1)
    u = np.clip(u, 0.0, res - 1.001)
    v = np.clip(v, 0.0, res - 1.001)
    i = u.astype(np.int32)
    j = v.astype(np.int32)
    fu = u - i
    fv = v - j
    h00 = H[j,     i    ]
    h10 = H[j,     i + 1]
    h01 = H[j + 1, i    ]
    h11 = H[j + 1, i + 1]
    a = h00 * (1 - fu) + h10 * fu
    b = h01 * (1 - fu) + h11 * fu
    flat[:, 2] = a * (1 - fv) + b * fv
    me.vertices.foreach_set("co", flat.reshape(-1))
    me.update()

"""Tiny signed-distance-function library.

A compact, dependency-free SDF library — enough primitives to express
ground + mesas + ravines + caves + tunnels by composition. We could have
pulled fogleman/sdf, but a 200-line homegrown library lets us control
semantics (consistent Vec3 conventions, vectorized over numpy arrays of
sample points, no surprise allocations) and avoids an external GitHub
dependency.

Convention:
  - All primitives are functions that return a callable
    `f(p: np.ndarray[N, 3]) -> np.ndarray[N]` returning the signed
    distance to the surface, negative inside.
  - `f(p)` is broadcast-friendly: pass any (..., 3) array and get the
    matching scalar shape back.
  - Composition operators (union, subtract, etc.) take SDFs and return
    a new SDF. Smooth variants take a `k` blend radius (m).

Reference: Inigo Quilez's SDF compendium
(https://iquilezles.org/articles/distfunctions/) — the math is standard.
"""

from __future__ import annotations

from typing import Callable, Sequence

import numpy as np


SDF = Callable[[np.ndarray], np.ndarray]
Vec3 = tuple[float, float, float]


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


def sphere(radius: float, center: Vec3 = (0.0, 0.0, 0.0)) -> SDF:
    """A sphere of given radius centered at `center`."""
    c = np.asarray(center, dtype=np.float32)

    def f(p: np.ndarray) -> np.ndarray:
        return np.linalg.norm(p - c, axis=-1) - radius

    return f


def box(size: Vec3, center: Vec3 = (0.0, 0.0, 0.0)) -> SDF:
    """An axis-aligned box of full extents `size` centered at `center`.

    Slightly rounded — uses iq's standard `length(max(q,0)) + min(max(q),0)`
    so corners are technically a touch sharp but distance remains
    Lipschitz, which marching cubes prefers.
    """
    half = np.asarray(size, dtype=np.float32) * 0.5
    c = np.asarray(center, dtype=np.float32)

    def f(p: np.ndarray) -> np.ndarray:
        q = np.abs(p - c) - half
        outside = np.linalg.norm(np.maximum(q, 0.0), axis=-1)
        inside = np.minimum(np.max(q, axis=-1), 0.0)
        return outside + inside

    return f


def cylinder(radius: float, height: float, center: Vec3 = (0.0, 0.0, 0.0)) -> SDF:
    """A z-axis-aligned cylinder."""
    c = np.asarray(center, dtype=np.float32)
    half_h = height * 0.5

    def f(p: np.ndarray) -> np.ndarray:
        d = p - c
        radial = np.linalg.norm(d[..., :2], axis=-1) - radius
        vertical = np.abs(d[..., 2]) - half_h
        outside = np.linalg.norm(
            np.stack([np.maximum(radial, 0.0), np.maximum(vertical, 0.0)], axis=-1),
            axis=-1,
        )
        inside = np.minimum(np.maximum(radial, vertical), 0.0)
        return outside + inside

    return f


def cylinder_weathered(
    radius: float,
    height: float,
    *,
    center: Vec3 = (0.0, 0.0, 0.0),
    horizontal_components: Sequence[tuple[int, float, float]] = (),
    radial_shift: tuple[float, float] = (0.0, 0.0),
    base_flare: float = 0.08,
    flare_height_frac: float = 0.30,
    fluting_components: Sequence[tuple[int, float, float, float, float]] = (),
    top_taper: float = 0.0,
    column_tilt_amount: float = 0.0,
    column_tilt_direction: float = 0.0,
    top_slope_amount: float = 0.0,
    top_slope_direction: float = 0.0,
    top_relief_components: Sequence[tuple[int, float, float]] = (),
) -> SDF:
    """A weathered mesa cylinder with several classes of irregularity:

      1. **Talus skirt** — `base_flare` (fraction of radius) widens the
         cylinder at z=0 (the ground) tapering to 0 over
         `flare_height_frac` of the total height. Reads as the cone of
         broken rock at the base of every real mesa.

      2. **Vertical fluting / scratches** — water-erosion channels.
         Each `fluting_components` entry is `(n_theta, n_z, amp,
         phase_theta, phase_z)`; the radius is perturbed by `amp ·
         cos(n_theta · θ + phase_θ) · cos(n_z · z_norm · 2π + phase_z)`.
         Multiple components at different (n_theta, n_z) sum into
         irregular vertical streaks.

      3. **Horizontal asymmetry** — `horizontal_components` is a list
         of `(n_theta, amp, phase)` cosine harmonics summed onto the
         radius; `radial_shift` offsets the cylinder's XY axis so the
         silhouette isn't a perfect circle from above.

      4. **Top taper** — `top_taper` (fraction of radius) narrows the
         top so it's not razor-edged. Keep small (~0.05) for subtle
         caprock weathering.

      5. **Column tilt** — `column_tilt_amount` is the *fraction of
         height* the top is displaced laterally; `column_tilt_direction`
         is the tilt direction in radians (XY plane, 0 = +X). At
         `tilt_amount=0.10` the top shifts by 10% of the cylinder
         height in the chosen direction → about a 6° lean. Real mesas
         can lean a few degrees from differential erosion.

      6. **Top slope** — `top_slope_amount` is z-displacement (in
         meters, NOT a fraction) of the top surface across one radius
         in the `top_slope_direction`. Positive amount tilts the top
         so it's higher in the slope_direction side, lower on the
         opposite side. ~0.5-1.5m gives a visibly-oblique mesa top
         without breaking the mesa silhouette.

      7. **Top relief** — `top_relief_components` is a list of
         `(n_theta, amp, phase)` triples that add cosine bumps to the
         top z-coordinate (in meters). 1-3 components with `amp` ~0.3-
         0.8 m gives subtle top variation — not perfectly flat,
         not lumpy.

    All "slight" knobs default to 0 so a no-arg call gives a perfect
    cylinder; turn them on selectively for the natural-mesa look.
    """
    c = np.asarray(center, dtype=np.float32)
    half_h = height * 0.5
    sx, sy = float(radial_shift[0]), float(radial_shift[1])
    horiz = list(horizontal_components)
    fluting = list(fluting_components)
    top_relief = list(top_relief_components)
    flare_h_world = max(flare_height_frac * height, 1e-3)
    base_flare_world = base_flare * radius
    # Tilt as world-meter displacement of the TOP relative to the bottom.
    tilt_dx = column_tilt_amount * height * float(np.cos(column_tilt_direction))
    tilt_dy = column_tilt_amount * height * float(np.sin(column_tilt_direction))
    slope_cos_dir = float(np.cos(top_slope_direction))
    slope_sin_dir = float(np.sin(top_slope_direction))

    def f(p: np.ndarray) -> np.ndarray:
        d = p - c
        # Apply column tilt by SHEARING — at z=-half_h (bottom), no shift;
        # at z=+half_h (top), shift by (tilt_dx, tilt_dy). Linear in z.
        if column_tilt_amount != 0.0:
            z_norm_full = (d[..., 2] + half_h) / max(height, 1e-3)
            x = d[..., 0] - sx - tilt_dx * z_norm_full
            y = d[..., 1] - sy - tilt_dy * z_norm_full
        else:
            x = d[..., 0] - sx
            y = d[..., 1] - sy
        z = d[..., 2]
        angle = np.arctan2(y, x)
        r_local = np.sqrt(x * x + y * y)
        r_target = np.full_like(r_local, radius)

        # 1. Horizontal harmonics → asymmetric outline.
        for n, amp, phase in horiz:
            r_target = r_target + amp * np.cos(n * angle + phase)

        # 2. Vertical fluting — perturbation in (theta, z).
        if fluting:
            z_norm = (z + half_h) / max(height, 1e-3)
            for n_t, n_z, amp, phase_t, phase_z in fluting:
                r_target = r_target + amp * (
                    np.cos(n_t * angle + phase_t)
                    * np.cos(n_z * z_norm * 2.0 * np.pi + phase_z)
                )

        # 3. Talus skirt — base flare.
        if base_flare_world > 0:
            h_above = z + half_h
            flare_t = np.clip(1.0 - h_above / flare_h_world, 0.0, 1.0)
            flare_t = flare_t * flare_t * (3.0 - 2.0 * flare_t)
            r_target = r_target + base_flare_world * flare_t

        # 4. Top taper.
        if top_taper > 0:
            h_above = z + half_h
            taper_t = np.clip(h_above / max(height, 1e-3), 0.0, 1.0)
            taper_t = taper_t * taper_t * (3.0 - 2.0 * taper_t)
            r_target = r_target - top_taper * radius * taper_t

        # Compute the per-(x,y) top z based on top_slope + top_relief.
        # `top_z` is the z-coordinate where the cylinder ends.
        top_z = np.full_like(z, half_h)
        if top_slope_amount != 0.0:
            # Linear plane tilt across the radius — `top_slope_amount` is
            # the meters of z-rise per `radius` of horizontal displacement
            # in `top_slope_direction`. (x*cos+y*sin)/radius gives the
            # signed normalized projection onto the slope direction.
            top_z = top_z + top_slope_amount * (
                (x * slope_cos_dir + y * slope_sin_dir) / max(radius, 1e-3)
            )
        if top_relief:
            for n, amp, phase in top_relief:
                top_z = top_z + amp * np.cos(n * angle + phase)

        radial = r_local - r_target
        # Vertical outside-distance: above top_z, or below -half_h.
        above = z - top_z
        below = -half_h - z
        vertical = np.maximum(above, below)
        outside = np.linalg.norm(
            np.stack([np.maximum(radial, 0.0), np.maximum(vertical, 0.0)], axis=-1),
            axis=-1,
        )
        inside = np.minimum(np.maximum(radial, vertical), 0.0)
        return outside + inside

    return f


def cylinder_organic(
    radius: float,
    height: float,
    *,
    center: Vec3 = (0.0, 0.0, 0.0),
    components: Sequence[tuple[int, float, float]] = (),
    radial_shift: tuple[float, float] = (0.0, 0.0),
) -> SDF:
    """A z-axis-aligned cylinder whose radius varies with angle as the
    SUM of several cosine harmonics with random phases:

        r(θ) = radius + Σ_i amp_i · cos(n_i · θ + phase_i)

    With 2–4 components at different `n` and random phases, the result
    is a smooth, ASYMMETRIC outline — much more natural than a single
    cosine (which gives regular flower-petal lobes). Used by MesaCluster
    to give every mesa a unique organic profile.

    `radial_shift` translates the radius origin, giving an overall
    lean/offset to the mesa silhouette (one side wider than the other).

    `components` is a list of `(n_lobes, amplitude, phase)` triples;
    typically generated per-mesa from the seeded RNG. Empty list →
    perfect cylinder.
    """
    c = np.asarray(center, dtype=np.float32)
    half_h = height * 0.5
    sx, sy = float(radial_shift[0]), float(radial_shift[1])

    def f(p: np.ndarray) -> np.ndarray:
        d = p - c
        # Apply radial origin shift in XY only.
        x = d[..., 0] - sx
        y = d[..., 1] - sy
        angle = np.arctan2(y, x)
        r_local = np.sqrt(x * x + y * y)
        r_target = np.full_like(r_local, radius)
        for n, amp, phase in components:
            r_target = r_target + amp * np.cos(n * angle + phase)
        radial = r_local - r_target
        vertical = np.abs(d[..., 2]) - half_h
        outside = np.linalg.norm(
            np.stack([np.maximum(radial, 0.0), np.maximum(vertical, 0.0)], axis=-1),
            axis=-1,
        )
        inside = np.minimum(np.maximum(radial, vertical), 0.0)
        return outside + inside

    return f


def island_dome(
    radius: float,
    height: float,
    *,
    center: Vec3 = (0.0, 0.0, 0.0),
    horizontal_components: Sequence[tuple[int, float, float]] = (),
    radial_shift: tuple[float, float] = (0.0, 0.0),
    surface_relief: Sequence[tuple[int, int, float, float, float]] = (),
) -> SDF:
    """An asymmetric dome — a sphere-cap whose XY footprint is a potato
    silhouette (n=1 + n=2 harmonics) rather than a circle.

    `radius` is the at-water-level (z=cz) horizontal radius, `height` is
    the peak height above center z. Internally fits a sphere of radius
    `R = (r²+h²)/(2h)` whose cap chord intersects z=cz at radius
    `radius`. Then the XY distance is scaled by 1/(1+perturb(θ)) so the
    apparent radius varies with angle — gives the potato outline without
    breaking the sphere SDF's distance-field property too badly.

    `surface_relief` is a list of `(n_theta, n_z, amp, phase_t, phase_z)`
    that adds high-frequency dimples/bumps to the outer surface — helps
    the dome read as rocky/sandy rather than glass-smooth. `n_z` here is
    interpreted relative to z normalised by `height`.
    """
    cx, cy, cz = center
    h = max(height, 0.01)
    R = (radius * radius + h * h) / (2.0 * h)
    sphere_cz = cz + h - R
    h_comp = list(horizontal_components)
    s_comp = list(surface_relief)
    sx, sy = float(radial_shift[0]), float(radial_shift[1])
    inv_radius = 1.0 / max(radius, 0.01)

    def f(p: np.ndarray) -> np.ndarray:
        dx = p[..., 0] - cx - sx
        dy = p[..., 1] - cy - sy
        dz = p[..., 2] - sphere_cz
        r_xy = np.sqrt(dx * dx + dy * dy + 1e-8)
        theta = np.arctan2(dy, dx)
        perturb = np.zeros_like(theta, dtype=np.float32)
        for n, amp, phase in h_comp:
            perturb = perturb + np.float32(amp * inv_radius) * np.cos(n * theta + phase).astype(np.float32)
        # Clamp so we never invert the silhouette (1+perturb >= 0.2).
        scale = 1.0 / np.maximum(1.0 + perturb, np.float32(0.2))
        scaled_xy = r_xy * scale
        d = np.sqrt(scaled_xy * scaled_xy + dz * dz) - R
        if s_comp:
            z_norm = (p[..., 2] - cz) / h  # 0 at water, 1 at peak
            relief = np.zeros_like(theta, dtype=np.float32)
            for n_t, n_z, amp, p_t, p_z in s_comp:
                relief = relief + np.float32(amp) * np.cos(
                    n_t * theta + p_t
                ).astype(np.float32) * np.cos(
                    n_z * z_norm * 2.0 * np.pi + p_z
                ).astype(np.float32)
            d = d - relief
        return d.astype(np.float32)

    return f


def island_plateau(
    radius: float,
    height: float,
    *,
    center: Vec3 = (0.0, 0.0, 0.0),
    plateau_frac: float = 0.65,
    transition_softness: float = 1.0,
    horizontal_components: Sequence[tuple[int, float, float]] = (),
    radial_shift: tuple[float, float] = (0.0, 0.0),
) -> SDF:
    """A flat-topped island modelled as a height field — most of the
    surface area is at full height `height`, with a soft beach-slope
    transition near the rim, and outside the rim the surface
    "disappears" (treated as far below z=0 so no iso-surface is drawn
    there).

    `plateau_frac` controls how much of the radius is the flat top
    (0.65 = inner 65% at full height, outer 35% smoothsteps down).
    `transition_softness` ≥ 1 stretches the slope band wider.

    Pair with `EmptyBase` and a translucent water box for ocean
    scenes. The SDF is a vertical signed distance (z - surface_z) —
    well-behaved under domain warp because the gradient stays
    bounded everywhere except the rim discontinuity, which marching
    cubes handles cleanly.
    """
    cx, cy, cz = center
    h = max(float(height), 0.01)
    h_comp = list(horizontal_components)
    sx, sy = float(radial_shift[0]), float(radial_shift[1])
    plateau_r = max(0.0, min(0.95, float(plateau_frac))) * radius
    transition = max(radius - plateau_r, 0.5) * max(float(transition_softness), 0.1)
    # Drop band: smooth descent past the rim into "no surface here"
    # territory. Smoothing this avoids a hard SDF discontinuity at the
    # rim, which would otherwise produce marching-cubes hair under
    # domain warp.
    drop_band = max(transition, 1.5)
    drop_depth = 80.0  # how far the surface drops past the rim — enough
                      # that the iso-surface is well below the sample range.

    def f(p: np.ndarray) -> np.ndarray:
        dx = (p[..., 0] - cx - sx).astype(np.float32)
        dy = (p[..., 1] - cy - sy).astype(np.float32)
        r_xy = np.sqrt(dx * dx + dy * dy + 1e-8).astype(np.float32)
        theta = np.arctan2(dy, dx).astype(np.float32)
        r_eff = np.full_like(theta, float(radius), dtype=np.float32)
        for n, amp, phase in h_comp:
            r_eff = r_eff + np.float32(amp) * np.cos(n * theta + phase).astype(np.float32)
        # Plateau rise: 0 at rim, 1 deep inside the plateau.
        plateau_t = np.clip((r_eff - r_xy) / np.maximum(transition, 0.5), 0.0, 1.0).astype(np.float32)
        plateau_t = (plateau_t * plateau_t * (3.0 - 2.0 * plateau_t)).astype(np.float32)
        # Drop past the rim: 0 at rim, 1 once we're a `drop_band` past.
        drop_t = np.clip((r_xy - r_eff) / np.float32(drop_band), 0.0, 1.0).astype(np.float32)
        drop_t = (drop_t * drop_t * (3.0 - 2.0 * drop_t)).astype(np.float32)
        # Surface z: plateau rise inside, smooth fall past the rim. The
        # crossover at the rim itself is z = cz, so the iso-surface
        # there meets the waterline cleanly.
        surface_z = (cz + h * plateau_t - drop_depth * drop_t).astype(np.float32)
        return (p[..., 2] - surface_z).astype(np.float32)

    return f


def warp_xy(
    base_sdf: SDF,
    *,
    noise_x: Callable[[np.ndarray, np.ndarray], np.ndarray],
    noise_y: Callable[[np.ndarray, np.ndarray], np.ndarray],
    amplitude: float,
) -> SDF:
    """Domain-warp wrapper. Before evaluating `base_sdf(p)`, perturb
    the XY coordinates by `(amp · noise_x(x,y), amp · noise_y(x,y))`.

    With low-frequency 2D noise + amplitude ~30-50% of the underlying
    feature radius, this turns smooth circular outlines into fractal,
    fjord-carved coastlines without changing the primitive. Two
    independent noise functions (different seeds) → uncorrelated x/y
    perturbations.

    Useful applied per-island for varied silhouettes, or applied at the
    cluster level for a coherent "current" / "wind direction" warp
    across the whole map.

    Reference: iquilezles.org/articles/warp/
    """
    a = float(amplitude)

    def f(p: np.ndarray) -> np.ndarray:
        x = p[..., 0]
        y = p[..., 1]
        wx = (noise_x(x, y) * a).astype(np.float32)
        wy = (noise_y(x, y) * a).astype(np.float32)
        # Build a warped point array. Use a copy so we don't mutate p.
        p_warped = p.copy()
        p_warped[..., 0] = (x + wx).astype(np.float32)
        p_warped[..., 1] = (y + wy).astype(np.float32)
        return base_sdf(p_warped)

    return f


def box_rotated(
    size: Vec3,
    *,
    center: Vec3 = (0.0, 0.0, 0.0),
    angle: float = 0.0,
) -> SDF:
    """An axis-aligned box rotated by `angle` (radians) around the Z axis
    about its `center`. Used for square-footprint mesa columns whose
    corners read as square but vary in orientation.
    """
    cx, cy, cz = center
    cos_a = float(np.cos(angle))
    sin_a = float(np.sin(angle))
    half = (size[0] / 2, size[1] / 2, size[2] / 2)
    half_arr = np.asarray(half, dtype=np.float32)

    def f(p: np.ndarray) -> np.ndarray:
        # Translate p so center is at origin, then rotate by -angle.
        x_local = (p[..., 0] - cx) * cos_a + (p[..., 1] - cy) * sin_a
        y_local = -(p[..., 0] - cx) * sin_a + (p[..., 1] - cy) * cos_a
        z_local = p[..., 2] - cz
        local = np.stack([x_local, y_local, z_local], axis=-1)
        q = np.abs(local) - half_arr
        outside = np.linalg.norm(np.maximum(q, 0.0), axis=-1)
        inside = np.minimum(np.max(q, axis=-1), 0.0)
        return outside + inside

    return f


def plane(normal: Vec3 = (0.0, 0.0, 1.0), offset: float = 0.0) -> SDF:
    """An infinite plane. `normal` should be unit length; `offset` is the
    signed distance from origin along the normal. Default = ground at z=0."""
    n = np.asarray(normal, dtype=np.float32)
    n = n / np.linalg.norm(n)

    def f(p: np.ndarray) -> np.ndarray:
        return np.einsum("...i,i->...", p, n) - offset

    return f


def capsule(a: Vec3, b: Vec3, radius: float) -> SDF:
    """A capsule from segment `a`→`b` with given radius."""
    a_ = np.asarray(a, dtype=np.float32)
    b_ = np.asarray(b, dtype=np.float32)
    ab = b_ - a_
    ab_len2 = float(np.dot(ab, ab))

    def f(p: np.ndarray) -> np.ndarray:
        ap = p - a_
        # Project ap onto ab, clamp to [0, 1] = parameter along segment
        t = np.einsum("...i,i->...", ap, ab) / max(ab_len2, 1e-9)
        t = np.clip(t, 0.0, 1.0)
        closest = a_ + t[..., None] * ab
        return np.linalg.norm(p - closest, axis=-1) - radius

    return f


def line_xy(
    points_xy: Sequence[Vec3],
    radius: float,
    z: float = 0.0,
    z_extent: float = 1e3,
) -> SDF:
    """A polyline-in-XY swept as a vertical capsule wall — useful for carving
    ravines. `points_xy` is a list of (x, y) (or (x, y, _) — z ignored).
    Distance is measured in XY only and the SDF is constant along Z (so
    the carved trench has vertical walls that go from -z_extent to
    +z_extent), matching how a ravine reads.

    `radius` = half-width of the trench. `z` shifts the SDF up/down for
    height-banded use cases; default 0 = the full vertical column.
    """
    pts = np.asarray([(p[0], p[1]) for p in points_xy], dtype=np.float32)
    if len(pts) < 2:
        raise ValueError("line_xy needs at least 2 points")

    def f(p: np.ndarray) -> np.ndarray:
        xy = p[..., :2]
        # Distance from each query point to each segment, take minimum.
        # Vectorized: compute distance from xy to every (a,b) segment.
        out = np.full(xy.shape[:-1], np.inf, dtype=np.float32)
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            ab = b - a
            ab_len2 = float(np.dot(ab, ab)) + 1e-9
            ap = xy - a
            t = np.einsum("...i,i->...", ap, ab) / ab_len2
            t = np.clip(t, 0.0, 1.0)
            closest = a + t[..., None] * ab
            d = np.linalg.norm(xy - closest, axis=-1)
            out = np.minimum(out, d)
        # Convert XY distance to a 3D capsule-along-Z: distance to the
        # vertical wall at radius `radius`. Z coordinate is mostly irrelevant
        # over [-z_extent, +z_extent], so we use a thin 2D-ish field.
        if z_extent < 1e3:
            z_dist = np.maximum(np.abs(p[..., 2] - z) - z_extent, 0.0)
            return np.sqrt((np.maximum(out - radius, 0.0)) ** 2 + z_dist ** 2) + np.minimum(
                np.maximum(out - radius, np.abs(p[..., 2] - z) - z_extent), 0.0
            )
        return out - radius

    return f


# ---------------------------------------------------------------------------
# Procedural noise — used to displace ground heights
# ---------------------------------------------------------------------------


def low_freq_noise_2d(
    seed: int = 0,
    feature_scale: float = 30.0,
    amplitude: float = 1.0,
    grid_size: int = 8,
) -> Callable[[np.ndarray, np.ndarray], np.ndarray]:
    """A genuinely-low-frequency 2D smooth-noise sampler.

    Samples random values on an `grid_size` × `grid_size` lattice that
    covers a `feature_scale × feature_scale` tile. Bilinear-interpolates
    with quintic smoothstep between cells. Tiles repeat outside the
    initial extent.

    Distinct from `perlin_2d`, which samples a 64×64 grid regardless of
    period — perlin_2d has high-frequency content even with large
    periods, which produces spiky/jagged threshold contours when used
    for mesa-zone selection. This function ties feature size directly
    to lattice spacing (feature_scale / grid_size), so the output is
    smooth at the requested scale and nothing finer.

    Use for: large-feature zone masks (mesa locations, biome
    boundaries). Use perlin_2d for: per-vertex texture noise.
    """
    rng = np.random.default_rng(seed)
    grid = rng.random((grid_size, grid_size), dtype=np.float32) * 2.0 - 1.0

    def h(x: np.ndarray, y: np.ndarray) -> np.ndarray:
        u = (x / feature_scale) % 1.0 * (grid_size - 1)
        v = (y / feature_scale) % 1.0 * (grid_size - 1)
        i = u.astype(np.int32)
        j = v.astype(np.int32)
        i1 = (i + 1) % grid_size
        j1 = (j + 1) % grid_size
        fu = u - i
        fv = v - j
        sfu = fu * fu * fu * (fu * (fu * 6 - 15) + 10)
        sfv = fv * fv * fv * (fv * (fv * 6 - 15) + 10)
        v00 = grid[j, i]
        v10 = grid[j, i1]
        v01 = grid[j1, i]
        v11 = grid[j1, i1]
        a = v00 * (1 - sfu) + v10 * sfu
        b = v01 * (1 - sfu) + v11 * sfu
        return amplitude * (a * (1 - sfv) + b * sfv)

    return h


def perlin_2d(
    seed: int = 0,
    period: float = 40.0,
    amplitude: float = 1.0,
    octaves: int = 2,
    persistence: float = 0.5,
) -> Callable[[np.ndarray, np.ndarray], np.ndarray]:
    """Smooth fractal-Brownian-motion noise on the XY plane.

    Per-cell value noise interpolated with a quintic smoothstep
    (Perlin's `6t⁵−15t⁴+10t³`) — first and second derivatives go to
    zero at cell boundaries, eliminating the ridge artifacts that
    plain bilinear interpolation produces. That's what gave the
    initial PoC its "spiky" desert-floor look.

    Defaults are tuned for a *dune-ish* desert look: long period (40m),
    only 2 octaves so high-frequency chatter is gone. Caller can pass
    octaves=1 for pure rolling dunes, or octaves=3+ for grittier terrain.
    """
    rng_master = np.random.default_rng(seed)
    octave_grids = []
    for o in range(octaves):
        side = max(8, int(64 / (2 ** o)))
        grid = rng_master.random((side, side), dtype=np.float32) * 2.0 - 1.0
        octave_grids.append(grid)

    def h(x: np.ndarray, y: np.ndarray) -> np.ndarray:
        total = np.zeros_like(x, dtype=np.float32)
        amp = amplitude
        per = period
        for grid in octave_grids:
            side = grid.shape[0]
            u = (x / per) % 1.0 * (side - 1)
            v = (y / per) % 1.0 * (side - 1)
            i = u.astype(np.int32)
            j = v.astype(np.int32)
            i1 = (i + 1) % side
            j1 = (j + 1) % side
            fu = u - i
            fv = v - j
            # Quintic smoothstep: derivatives vanish at the cell corners,
            # so adjacent cells join without visible seams.
            sfu = fu * fu * fu * (fu * (fu * 6 - 15) + 10)
            sfv = fv * fv * fv * (fv * (fv * 6 - 15) + 10)
            v00 = grid[j, i]
            v10 = grid[j, i1]
            v01 = grid[j1, i]
            v11 = grid[j1, i1]
            a = v00 * (1 - sfu) + v10 * sfu
            b = v01 * (1 - sfu) + v11 * sfu
            total += amp * (a * (1 - sfv) + b * sfv)
            amp *= persistence
            per *= 0.5
        return total

    return h


def height_field(
    height_fn: Callable[[np.ndarray, np.ndarray], np.ndarray],
) -> SDF:
    """Wrap an XY→Z function as a 3D SDF. The result is `f(p) = p.z - h(p.x, p.y)`,
    which is signed-distance-ish along the vertical axis (not a true Lipschitz
    distance, but marching cubes works correctly because the sign change is
    exactly at z = h(x, y))."""

    def f(p: np.ndarray) -> np.ndarray:
        return p[..., 2] - height_fn(p[..., 0], p[..., 1])

    return f


# ---------------------------------------------------------------------------
# Operators — set algebra on SDFs
# ---------------------------------------------------------------------------


def union(*sdfs: SDF) -> SDF:
    """`min` across all distances — set union, sharp seams."""
    if not sdfs:
        raise ValueError("union needs ≥1 sdf")

    def f(p: np.ndarray) -> np.ndarray:
        d = sdfs[0](p)
        for s in sdfs[1:]:
            d = np.minimum(d, s(p))
        return d

    return f


def subtract(a: SDF, b: SDF) -> SDF:
    """A minus B (carve B out of A). `max(a, -b)`."""

    def f(p: np.ndarray) -> np.ndarray:
        return np.maximum(a(p), -b(p))

    return f


def intersect(a: SDF, b: SDF) -> SDF:
    """A intersected with B."""

    def f(p: np.ndarray) -> np.ndarray:
        return np.maximum(a(p), b(p))

    return f


def smooth_union(k: float, *sdfs: SDF) -> SDF:
    """Smooth-min union — `k` is the blend radius in world meters. Soft
    seams between mesas + ground, etc."""
    if k <= 0:
        return union(*sdfs)
    if not sdfs:
        raise ValueError("smooth_union needs ≥1 sdf")

    def f(p: np.ndarray) -> np.ndarray:
        d = sdfs[0](p)
        for s in sdfs[1:]:
            db = s(p)
            h = np.clip(0.5 + 0.5 * (db - d) / k, 0.0, 1.0)
            d = (db * (1 - h) + d * h) - k * h * (1 - h)
        return d

    return f


def smooth_subtract(k: float, a: SDF, b: SDF) -> SDF:
    """Smooth A minus B — soft-edged ravine carve."""
    if k <= 0:
        return subtract(a, b)

    def f(p: np.ndarray) -> np.ndarray:
        da = a(p)
        db = b(p)
        h = np.clip(0.5 - 0.5 * (db + da) / k, 0.0, 1.0)
        return (da * (1 - h) + (-db) * h) + k * h * (1 - h)

    return f


def translate(sdf: SDF, offset: Vec3) -> SDF:
    """Translate the field by `offset`."""
    o = np.asarray(offset, dtype=np.float32)

    def f(p: np.ndarray) -> np.ndarray:
        return sdf(p - o)

    return f


def rotate_z(sdf: SDF, angle: float) -> SDF:
    """Rotate around the Z axis (most common case for terrain features)."""
    cos_a = float(np.cos(angle))
    sin_a = float(np.sin(angle))

    def f(p: np.ndarray) -> np.ndarray:
        x = p[..., 0] * cos_a + p[..., 1] * sin_a
        y = -p[..., 0] * sin_a + p[..., 1] * cos_a
        q = np.stack([x, y, p[..., 2]], axis=-1)
        return sdf(q)

    return f

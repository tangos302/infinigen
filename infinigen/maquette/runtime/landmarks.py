"""SDF-based terrain landmarks (arches, hoodoos, sea stacks).

The heightmap pipeline can't represent overhangs (it's a 2.5D field).
Distinctive landmark forms — Sky CotL's Vault arch, Wasteland hoodoos,
sea-stack pillars in the archipelago — need full 3D SDF + marching
cubes. This module provides:

- ``Arch`` / ``Hoodoo`` / ``Pillar`` dataclasses (describe LLM-side)
- ``build_landmark_meshes(scene, composition, terrain)`` (drives marching
  cubes per landmark, adds Blender objects to scene with the same
  painterly material as the terrain)

Landmarks are placed at composition-supplied (cx, cy) and pinned to the
terrain surface (sampled via ``terrain.height_at``). They're separate
mesh objects, not part of the terrain mesh — so they survive OBJ export
as their own ``o`` blocks and the Three.js viewer can render them.

Cost: ~0.5–2 s per landmark for marching cubes at 0.5 BU voxel size on a
~12×12×10 BU bounding box. For a typical scene with 1–2 landmarks, the
addition is small relative to render time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np


@dataclass
class Hoodoo:
    """A weathered rock spire — Sky Wasteland-style.

    Tall asymmetric cylinder with cosine-harmonic radial variation so
    the silhouette reads as eroded sandstone, not a smooth pipe.
    Optional ``cap_radius_factor`` > 1 gives a mushroom top (top wider
    than base) for canonical hoodoo shapes; < 1 gives a tapering spire.
    """
    cx: float
    cy: float
    height: float = 8.0
    base_radius: float = 1.4
    cap_radius_factor: float = 1.3  # cap_radius = base * factor
    bz: float | None = None  # auto-snap to terrain when None
    seed: int = 0


@dataclass
class Arch:
    """A natural rock arch — two pillars joined by an overhead span.

    Implemented as the union of a thick capped 'gate' shape minus the
    archway opening (a horizontal capsule subtracted from a tall box).
    ``span`` is the inner opening width; ``height`` the peak above base.
    """
    cx: float
    cy: float
    span: float = 8.0
    height: float = 7.0
    thickness: float = 2.0
    orientation_deg: float = 0.0  # rotation in XY plane
    bz: float | None = None
    seed: int = 0


@dataclass
class Pillar:
    """A simple sea-stack / monolith pillar — vertical cylinder with
    organic asymmetry. Less weathered than ``Hoodoo``; more uniform."""
    cx: float
    cy: float
    height: float = 12.0
    radius: float = 2.0
    bz: float | None = None
    seed: int = 0


# Type alias for any landmark.
Landmark = Hoodoo | Arch | Pillar


def _hoodoo_sdf(h: Hoodoo, base_z: float):
    """Build a cylinder-organic SDF for a hoodoo. Optionally widens the
    cap by the ``cap_radius_factor`` via z-dependent radius shift.
    """
    rng = np.random.default_rng(int(h.seed) + 71)
    components = []
    for _ in range(3):
        n_lobes = int(rng.integers(2, 6))
        amp = float(rng.uniform(0.05, 0.18) * h.base_radius)
        phase = float(rng.uniform(0.0, 2.0 * np.pi))
        components.append((n_lobes, amp, phase))
    cap_factor = float(h.cap_radius_factor)
    base_radius = float(h.base_radius)
    height = float(h.height)
    cx, cy = float(h.cx), float(h.cy)
    z_center = base_z + height * 0.5

    def f(p: np.ndarray) -> np.ndarray:
        x = p[..., 0] - cx
        y = p[..., 1] - cy
        z = p[..., 2] - z_center
        # Radial profile: linear interp between base radius (z=-h/2)
        # and cap radius (z=+h/2). cap_factor > 1 → mushroom top.
        z_t = (z + height * 0.5) / max(height, 1e-3)
        z_t = np.clip(z_t, 0.0, 1.0)
        radius_at_z = base_radius * (1.0 + (cap_factor - 1.0) * (z_t ** 2.0))
        angle = np.arctan2(y, x)
        r_local = np.sqrt(x * x + y * y)
        r_target = radius_at_z.copy()
        for n_l, amp, phase in components:
            r_target = r_target + amp * np.cos(n_l * angle + phase)
        radial = r_local - r_target
        vertical = np.abs(z) - height * 0.5
        outside = np.sqrt(
            np.maximum(radial, 0.0) ** 2 + np.maximum(vertical, 0.0) ** 2
        )
        inside = np.minimum(np.maximum(radial, vertical), 0.0)
        return outside + inside

    return f


def _pillar_sdf(p: Pillar, base_z: float):
    """Sea-stack: same idea as hoodoo but more uniform (light radial
    variation, no mushroom cap)."""
    rng = np.random.default_rng(int(p.seed) + 31)
    components = [
        (int(rng.integers(2, 5)),
         float(rng.uniform(0.04, 0.12) * p.radius),
         float(rng.uniform(0.0, 2.0 * np.pi)))
        for _ in range(2)
    ]
    radius = float(p.radius)
    height = float(p.height)
    cx, cy = float(p.cx), float(p.cy)
    z_center = base_z + height * 0.5

    def f(pt: np.ndarray) -> np.ndarray:
        x = pt[..., 0] - cx
        y = pt[..., 1] - cy
        z = pt[..., 2] - z_center
        angle = np.arctan2(y, x)
        r_local = np.sqrt(x * x + y * y)
        r_target = np.full_like(r_local, radius)
        for n_l, amp, phase in components:
            r_target = r_target + amp * np.cos(n_l * angle + phase)
        radial = r_local - r_target
        vertical = np.abs(z) - height * 0.5
        outside = np.sqrt(
            np.maximum(radial, 0.0) ** 2 + np.maximum(vertical, 0.0) ** 2
        )
        inside = np.minimum(np.maximum(radial, vertical), 0.0)
        return outside + inside

    return f


def _arch_sdf(a: Arch, base_z: float):
    """Natural rock arch: thick rotated box minus a horizontal capsule
    that punches the gateway opening. Result: two pillars connected by
    an overhead span.
    """
    span = float(a.span)
    height = float(a.height)
    thickness = float(a.thickness)
    cx, cy = float(a.cx), float(a.cy)
    z_center = base_z + height * 0.5
    theta = float(a.orientation_deg) * np.pi / 180.0
    cos_t, sin_t = np.cos(theta), np.sin(theta)

    # Outer "gate" half-extents in local coords (along, cross, vertical).
    along_half = span * 0.5 + thickness  # extends past pillar bases
    cross_half = thickness * 0.5
    vert_half = height * 0.5

    # Inner archway opening: capsule of radius ``span * 0.4`` centered
    # at z = base_z + height * 0.55 (slightly below top).
    arch_radius = span * 0.40
    arch_z = base_z + height * 0.55

    def f(p: np.ndarray) -> np.ndarray:
        # Translate to landmark origin.
        dx = p[..., 0] - cx
        dy = p[..., 1] - cy
        # Rotate into landmark-local frame (along the arch span).
        u = cos_t * dx + sin_t * dy
        v = -sin_t * dx + cos_t * dy
        z = p[..., 2] - z_center

        # Outer gate as an axis-aligned box in (u, v, z).
        bu = np.abs(u) - along_half
        bv = np.abs(v) - cross_half
        bz = np.abs(z) - vert_half
        outer_outside = np.sqrt(
            np.maximum(bu, 0.0) ** 2
            + np.maximum(bv, 0.0) ** 2
            + np.maximum(bz, 0.0) ** 2
        )
        outer_inside = np.minimum(np.maximum(bu, np.maximum(bv, bz)), 0.0)
        outer = outer_outside + outer_inside

        # Inner opening: capsule along u-axis from u=-span/2 to +span/2,
        # at world z = arch_z. Subtract by max(outer, -inner).
        u_clamped = np.clip(u, -span * 0.5, span * 0.5)
        # Distance from p to nearest segment point (u_clamped, 0, arch_z-z_center).
        dz_arch = (p[..., 2] - arch_z)
        inner_dist = np.sqrt((u - u_clamped) ** 2 + v ** 2 + dz_arch ** 2) - arch_radius

        return np.maximum(outer, -inner_dist)

    return f


def _build_sdf(landmark: Landmark, base_z: float):
    if isinstance(landmark, Hoodoo):
        return _hoodoo_sdf(landmark, base_z)
    if isinstance(landmark, Pillar):
        return _pillar_sdf(landmark, base_z)
    if isinstance(landmark, Arch):
        return _arch_sdf(landmark, base_z)
    raise TypeError(f"Unknown landmark type: {type(landmark).__name__}")


def _bounding_box(landmark: Landmark, base_z: float):
    """Return (xmin, xmax), (ymin, ymax), (zmin, zmax) for marching cubes."""
    if isinstance(landmark, Hoodoo):
        cap_r = landmark.base_radius * max(landmark.cap_radius_factor, 1.0)
        rmax = max(cap_r, landmark.base_radius) * 1.4
        return (
            (landmark.cx - rmax, landmark.cx + rmax),
            (landmark.cy - rmax, landmark.cy + rmax),
            (base_z - 0.5, base_z + landmark.height + 0.5),
        )
    if isinstance(landmark, Pillar):
        rmax = landmark.radius * 1.4
        return (
            (landmark.cx - rmax, landmark.cx + rmax),
            (landmark.cy - rmax, landmark.cy + rmax),
            (base_z - 0.5, base_z + landmark.height + 0.5),
        )
    if isinstance(landmark, Arch):
        # Diagonal worst-case; orient-aware would be tighter.
        half = max(landmark.span * 0.5 + landmark.thickness * 1.5,
                   landmark.thickness * 1.5)
        return (
            (landmark.cx - half, landmark.cx + half),
            (landmark.cy - half, landmark.cy + half),
            (base_z - 0.5, base_z + landmark.height + 0.5),
        )
    raise TypeError(f"Unknown landmark type: {type(landmark).__name__}")


def build_landmark_meshes(
    landmarks: Sequence[Landmark],
    *,
    height_at,
    voxel_size: float = 0.4,
    material=None,
    color_rgb: tuple[float, float, float] = (0.55, 0.50, 0.42),
) -> list[Any]:
    """Build a Blender mesh per landmark via marching cubes.

    Returns the list of created Blender objects. The painterly material
    (passed via ``material``) is appended to each so they shade
    consistently with the terrain. ``color_rgb`` (linear) is written as
    a uniform vertex colour on each landmark mesh — no per-vertex biome
    bands, just the warm sandstone/grey rock tone.
    """
    if not landmarks:
        return []
    import bpy
    from infinigen.maquette.terrain.marching import build_mesh, mesh_to_blender

    out = []
    for i, landmark in enumerate(landmarks):
        bz = landmark.bz
        if bz is None:
            try:
                bz = float(height_at(landmark.cx, landmark.cy))
            except Exception:
                bz = 0.0
            # Anchor the landmark slightly below the surface so the
            # base appears to emerge naturally rather than float.
            bz -= 0.4

        sdf = _build_sdf(landmark, bz)
        extent = _bounding_box(landmark, bz)
        try:
            verts, faces = build_mesh(
                sdf, extent=extent, voxel_size=voxel_size, chunk=48,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[landmarks] {type(landmark).__name__} #{i} marching "
                  f"failed: {exc}; skipping")
            continue
        if verts.shape[0] == 0:
            print(f"[landmarks] {type(landmark).__name__} #{i} produced "
                  f"empty mesh; skipping")
            continue

        name = f"{type(landmark).__name__}_{i}"
        obj = mesh_to_blender(verts, faces, name=name)

        # Force flat shading for a low-poly read on top of the smooth
        # terrain — landmarks read as solid forms not bumpy surfaces.
        for poly in obj.data.polygons:
            poly.use_smooth = False

        # Per-landmark uniform vertex-colour Col so it inherits the
        # painterly material's vertex-colour shader path.
        n_v = len(obj.data.vertices)
        col_attr = obj.data.color_attributes.new(
            name="Col", type="FLOAT_COLOR", domain="POINT")
        rgba = np.empty(n_v * 4, dtype=np.float32)
        rgba.reshape(n_v, 4)[:, :3] = color_rgb
        rgba.reshape(n_v, 4)[:, 3] = 1.0
        col_attr.data.foreach_set("color", rgba)

        if material is not None:
            obj.data.materials.append(material)
        out.append(obj)
        print(f"[landmarks] {type(landmark).__name__} #{i} at "
              f"({landmark.cx:.1f}, {landmark.cy:.1f}) → "
              f"{verts.shape[0]} verts, {faces.shape[0]} faces")
    return out

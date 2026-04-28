"""SDF → mesh via marching cubes, plus Blender import + surface query.

The pipeline:
  1. Sample an SDF over a uniform 3D grid (`build_mesh`).
  2. Run scikit-image's marching-cubes to extract an iso-zero mesh.
  3. Import the mesh into Blender (`mesh_to_blender`).
  4. (Optional) cache a 2D height grid + provide `surface_height_at(x, y)`
     so factories can drop assets onto the terrain surface.

scikit-image's `marching_cubes` is a well-trusted implementation of the
Lewiner variant, runs on CPU, no GPU dependency. For our typical terrain
extents (40–100 m wide, voxel size ~0.5 m) the grid is ~10⁵ voxels and
meshing takes <1s.
"""

from __future__ import annotations

from typing import Callable

import numpy as np


# scikit-image is a heavyweight import (~1s, transitively pulls scipy);
# we lazy-import so the module loads cheaply for callers that only need
# the SDF library.
def _marching_cubes(volume: np.ndarray, *, level: float = 0.0, spacing: tuple[float, float, float]):
    from skimage.measure import marching_cubes

    return marching_cubes(volume, level=level, spacing=spacing)


def build_mesh(
    sdf: Callable[[np.ndarray], np.ndarray],
    *,
    extent: tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
    voxel_size: float = 0.5,
    chunk: int = 64,
) -> tuple[np.ndarray, np.ndarray]:
    """Sample `sdf` over an axis-aligned voxel grid and march-cubes it.

    `extent` = ((xmin, xmax), (ymin, ymax), (zmin, zmax)).
    `voxel_size` = grid spacing in world meters. Smaller = more polys.
    `chunk` = how many slices to sample per batch (avoids 2 GB allocations
              on the 256³ grid).

    Returns `(verts, faces)` as numpy arrays in world coordinates. Verts
    are float32 (N, 3); faces are int32 (M, 3) referencing verts. Marching
    cubes always produces triangles — caller can leave them or merge later.
    """
    (x0, x1), (y0, y1), (z0, z1) = extent
    nx = max(2, int(np.ceil((x1 - x0) / voxel_size)) + 1)
    ny = max(2, int(np.ceil((y1 - y0) / voxel_size)) + 1)
    nz = max(2, int(np.ceil((z1 - z0) / voxel_size)) + 1)
    xs = np.linspace(x0, x1, nx, dtype=np.float32)
    ys = np.linspace(y0, y1, ny, dtype=np.float32)
    zs = np.linspace(z0, z1, nz, dtype=np.float32)

    # Sample in z-chunks to keep memory bounded — full grid for a 100m
    # extent at 0.5m voxels is ~200³ ≈ 8M voxels × 4 bytes = 32 MB,
    # totally fine but the *intermediate* per-call SDF temps balloon
    # without chunking.
    volume = np.empty((nx, ny, nz), dtype=np.float32)
    Y, X = np.meshgrid(ys, xs)  # shape (nx, ny)
    flat_xy = np.stack([X.ravel(), Y.ravel()], axis=-1)  # (nx*ny, 2)
    for zi in range(0, nz, chunk):
        z_slice = zs[zi : zi + chunk]
        # Build (nx*ny*z_slice, 3) sample points
        z_col = np.broadcast_to(
            z_slice[None, :], (flat_xy.shape[0], len(z_slice))
        ).reshape(-1)
        xy_rep = np.repeat(flat_xy, len(z_slice), axis=0)
        pts = np.concatenate([xy_rep, z_col[:, None]], axis=1).astype(np.float32)
        vals = sdf(pts).astype(np.float32)
        volume[:, :, zi : zi + chunk] = vals.reshape(nx, ny, len(z_slice))

    # Marching cubes — note skimage's `spacing` is (dx, dy, dz). Returned
    # vertex coords are in [0, (n-1)*spacing], we add the world origin.
    spacing = (
        (x1 - x0) / max(nx - 1, 1),
        (y1 - y0) / max(ny - 1, 1),
        (z1 - z0) / max(nz - 1, 1),
    )
    try:
        verts, faces, _normals, _vals = _marching_cubes(
            volume, level=0.0, spacing=spacing,
        )
    except (ValueError, RuntimeError) as e:
        # skimage raises if the iso-surface doesn't intersect the volume
        # (entirely positive or entirely negative). Return an empty mesh.
        if "must be" in str(e) or "level" in str(e) or "Surface" in str(e):
            return (
                np.zeros((0, 3), dtype=np.float32),
                np.zeros((0, 3), dtype=np.int32),
            )
        raise

    verts = verts.astype(np.float32) + np.array([x0, y0, z0], dtype=np.float32)
    faces = faces.astype(np.int32)
    return verts, faces


def mesh_to_blender(
    verts: np.ndarray,
    faces: np.ndarray,
    *,
    name: str = "Terrain",
    flat_shaded: bool = True,
    planar_decimate_deg: float | None = 7.99,
):
    """Import a (verts, faces) pair into Blender as a mesh object. Returns
    the created `bpy.types.Object`. Caller adds it to the scene.

    `flat_shaded` keeps the per-face hard-edge look that matches the rest
    of Maquette. Pass False for smooth-shaded terrain (rare for the
    low-poly target style).

    `planar_decimate_deg` runs a Decimate (PLANAR) modifier with the
    given angle threshold. Marching cubes emits a uniform voxel grid of
    tris even on dead-flat surfaces — without this step the terrain
    *looks* textured/spiky from voxel stepping artifacts. ~8° collapses
    co-planar tris (flat floors, mesa tops) while preserving cliff /
    gorge detail. Pass None to skip; bump it past 15° to aggressively
    blockify mesas into stylized columns.
    """
    import bpy  # local import — module must work outside Blender too

    me = bpy.data.meshes.new(name + "_Mesh")
    if len(verts) and len(faces):
        me.from_pydata(verts.tolist(), [], faces.tolist())
        me.update()
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    if flat_shaded:
        for p in me.polygons:
            p.use_smooth = False
    if planar_decimate_deg is not None and len(faces):
        mod = obj.modifiers.new(name="PlanarDecimate", type="DECIMATE")
        mod.decimate_type = "DISSOLVE"
        mod.angle_limit = float(planar_decimate_deg) * (3.14159265 / 180.0)
        mod.use_dissolve_boundaries = False
        # Apply now so the saved mesh is final — terrain never
        # re-spawns, no point keeping a live modifier.
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.modifier_apply(modifier=mod.name)
    return obj


def surface_height_at(
    height_fn: Callable[[np.ndarray, np.ndarray], np.ndarray],
    x: float | np.ndarray,
    y: float | np.ndarray,
) -> float | np.ndarray:
    """Evaluate the heightmap function at one or many (x, y) points.

    Useful when factories scatter assets — they ask the terrain "what's the
    z at this place?" and place the asset's base there. This works for
    height-field-based archetypes (mesas, hills, gentle valleys); for
    fully-3D terrain (caves, overhangs) the caller would need a vertical
    raycast against the meshed surface instead.
    """
    x_arr = np.atleast_1d(np.asarray(x, dtype=np.float32))
    y_arr = np.atleast_1d(np.asarray(y, dtype=np.float32))
    z = height_fn(x_arr, y_arr)
    if z.shape == (1,):
        return float(z[0])
    return z

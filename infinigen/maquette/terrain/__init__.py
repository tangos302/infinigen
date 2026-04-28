"""Maquette terrain — SDF-driven procedural ground meshes.

Why a separate `terrain` subpackage instead of folding into `factories/`:
the asset factories are small bmesh constructions (10–1000 faces); terrain
is a single large mesh (10k–500k faces) built by sampling a 3D signed
distance field and marching cubes. Different sampling strategy,
different polycount budget, and the terrain has to land BEFORE asset
placement so factories can scatter on top of the actual surface.

Public surface:

    from infinigen.maquette.terrain import sdf, build, LowPolyTerrainFactory

`sdf` — composable signed-distance primitives + ops (box, sphere, plane,
        capsule, union, subtract, translate, smooth_union, …).
`build` — sample an SDF over a 3D grid and run marching-cubes; returns
          (verts, faces) numpy arrays.
`LowPolyTerrainFactory` — AssetFactory subclass that drops a terrain
                          mesh into the scene at instantiation time.
"""

from .factory import LowPolyTerrainFactory
from .marching import build_mesh, mesh_to_blender, surface_height_at
from .sdf import (
    SDF,
    Vec3,
    box,
    capsule,
    cylinder,
    height_field,
    line_xy,
    perlin_2d,
    plane,
    sphere,
    smooth_subtract,
    smooth_union,
)

__all__ = [
    "LowPolyTerrainFactory",
    "SDF",
    "Vec3",
    "box",
    "build_mesh",
    "capsule",
    "cylinder",
    "height_field",
    "line_xy",
    "mesh_to_blender",
    "perlin_2d",
    "plane",
    "smooth_subtract",
    "smooth_union",
    "sphere",
    "surface_height_at",
]

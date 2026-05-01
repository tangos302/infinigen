"""RealisticFunctionSurfaceFactory — math-art surface, derived from addon.

The `add_mesh_3d_function_surface` addon's Z-function surface logic is
buried in an Operator's execute() method. We re-implement the small
generation step here to skip the operator and avoid `safe_dict`
expression evaluation (we use real lambdas instead — safer).

Use for monuments / sculpture / sci-fi terrain accents — anywhere a
parametric mathematical surface fits the scene.

Archetype mapping → z(x, y) lambda:

    "dome"        : z = 1 - (x**2 + y**2)/4   — paraboloid dome
    "saddle"      : z = (x*x - y*y) / 4        — saddle surface
    "ripple"      : z = sin(sqrt(x*x + y*y))   — water-ripple-like
    "hill"        : z = exp(-(x*x + y*y))      — gaussian peak
    "any"         : random pick

License: derived from the GPL-2.0 ZFunctionSurface operator.
"""

from __future__ import annotations

import math
from typing import Callable

import bpy
import numpy as np

from infinigen.core.placement.factory import AssetFactory
from infinigen.core.util.math import FixedSeed


_FN_ARCHETYPES = ("dome", "saddle", "ripple", "hill", "any")

_ARCHETYPE_TO_FN: dict[str, Callable[[float, float], float]] = {
    "dome":   lambda x, y: 1.0 - (x * x + y * y) / 4.0,
    "saddle": lambda x, y: (x * x - y * y) / 4.0,
    "ripple": lambda x, y: math.sin(math.sqrt(x * x + y * y) * 1.5) * 0.6,
    "hill":   lambda x, y: math.exp(-(x * x + y * y) * 0.4),
}


def _zsurface(z_fn, size_x: float, size_y: float, div_x: int, div_y: int):
    """Sample z=f(x,y) on a grid, returning (verts, faces) for a triangle
    surface. Same math as upstream's AddZFunctionSurface.execute()."""
    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []

    delta_x = size_x / (div_x - 1)
    delta_y = size_y / (div_y - 1)
    start_x = -size_x / 2.0
    start_y = -size_y / 2.0

    edgeloop_prev: list[int] = []
    for row_x in range(div_x):
        edgeloop_cur: list[int] = []
        x = start_x + row_x * delta_x
        for row_y in range(div_y):
            y = start_y + row_y * delta_y
            z = float(z_fn(x, y))
            edgeloop_cur.append(len(verts))
            verts.append((x, y, z))

        if edgeloop_prev:
            for j in range(len(edgeloop_prev) - 1):
                faces.append((
                    edgeloop_prev[j], edgeloop_prev[j + 1],
                    edgeloop_cur[j + 1], edgeloop_cur[j],
                ))
        edgeloop_prev = edgeloop_cur

    return verts, faces


class RealisticFunctionSurfaceFactory(AssetFactory):
    """Realistic parametric Z-function surface factory.

    Constructor knobs:

        factory_seed : int
        archetype : str = "dome"
            One of: dome / saddle / ripple / hill / any.
        size : float = 2.0  (X and Y extent, meters)
        subdivisions : int = 24  (grid density per axis)
    """

    def __init__(
        self,
        factory_seed: int,
        archetype: str = "dome",
        size: float = 2.0,
        subdivisions: int = 24,
        coarse: bool = False,
    ):
        if archetype not in _FN_ARCHETYPES:
            raise ValueError(
                f"archetype={archetype!r} not in {_FN_ARCHETYPES}"
            )
        super().__init__(factory_seed, coarse=coarse)
        if archetype == "any":
            with FixedSeed(factory_seed):
                non_any = list(_ARCHETYPE_TO_FN.keys())
                archetype = str(np.random.choice(non_any))
        self.archetype = archetype
        self.size = size
        self.subdivisions = max(3, int(subdivisions))

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        empty = bpy.data.objects.new("FunctionSurfacePlaceholder", None)
        bpy.context.collection.objects.link(empty)
        return empty

    def create_asset(self, i: int = 0, placeholder=None, **params) -> bpy.types.Object:
        z_fn = _ARCHETYPE_TO_FN[self.archetype]
        verts, faces = _zsurface(
            z_fn, self.size, self.size, self.subdivisions, self.subdivisions,
        )
        mesh = bpy.data.meshes.new(f"FunctionSurface.{self.archetype}.{i}")
        mesh.from_pydata(verts, [], faces)
        mesh.update()
        obj = bpy.data.objects.new(mesh.name, mesh)
        bpy.context.collection.objects.link(obj)
        return obj

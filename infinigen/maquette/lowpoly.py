"""Geometry helpers for converting an Infinigen mesh to a low-poly,
Firewatch-style read.

The functions here are intentionally small and one-purpose so that a
factory wrapper composes them: `flat_shade`, `strip_voronoi_displace`,
`decimate`. None of them touch shading nodes — materials are out of v0
scope.

All helpers operate on a single `bpy.types.Object` (mesh type) and
return it for chaining. They assume the object is already in the scene.
"""

from __future__ import annotations

import bpy

from infinigen.core.util import blender as butil


def flat_shade(obj: bpy.types.Object) -> bpy.types.Object:
    """Set every polygon's `use_smooth` to False.

    Faceted shading is the foundational ingredient of the Firewatch /
    low-poly look — without it, even a low-poly mesh reads as a smooth
    blob because Blender's default smooth-shading interpolates normals
    across faces. Doing this once after final mesh resolution is
    cheaper and clearer than fighting the shader graph for the same
    look.
    """
    if obj.type != "MESH":
        return obj
    for poly in obj.data.polygons:
        poly.use_smooth = False
    return obj


def strip_voronoi_displace(obj: bpy.types.Object) -> bpy.types.Object:
    """Remove `DISPLACE` modifiers whose texture is `VORONOI`.

    Upstream `BoulderFactory.create_placeholder` adds two such
    modifiers to bake high-frequency surface noise into the final
    mesh. Under low-poly + flat shading that detail (a) does not read
    visually and (b) bloats vertex counts when applied because each
    vertex is shifted independently. Removing the modifiers before
    `create_asset` runs avoids both costs.
    """
    if obj.type != "MESH":
        return obj
    for mod in list(obj.modifiers):
        if mod.type != "DISPLACE":
            continue
        tex = getattr(mod, "texture", None)
        if tex is not None and tex.type == "VORONOI":
            obj.modifiers.remove(mod)
    return obj


def decimate(obj: bpy.types.Object, ratio: float) -> bpy.types.Object:
    """Apply a `COLLAPSE` decimate at the given `ratio` (0..1).

    Used as a polycount cap after the upstream factory's adaptive
    remesh, when the chosen `face_size` still leaves more triangles
    than we want for a given asset class. `ratio=1.0` is a no-op;
    `ratio=0.05` means "keep 5% of the polys".

    Preserves UVs and shape keys the way Blender's decimate normally
    does. Triangulates as a side effect — that's fine for
    flat-shaded low-poly.
    """
    if obj.type != "MESH" or ratio is None or ratio >= 1.0:
        return obj
    if ratio <= 0:
        raise ValueError(f"decimate ratio must be > 0, got {ratio}")

    butil.modify_mesh(
        obj,
        "DECIMATE",
        decimate_type="COLLAPSE",
        ratio=ratio,
        apply=True,
    )
    return obj

"""Maquette material helpers.

Strips upstream Infinigen's complex shader-graph materials off a
mesh and replaces them with a single matte Principled BSDF tinted to
a Maquette palette color. That's the entire material story for v0:
one solid color per object, picked by the caller (or a future
class-based mapping).

Why single-color, not even per-face variation:
  - It's the foundational ingredient of the Firewatch look. Per-face
    color drift fights the silhouette.
  - Materials authoring is out of v0 scope; we want predictable
    output that's easy to A/B against geometry-only renders.
  - If a future asset class wants two-tone (e.g. trunk/leaves),
    that's a decision on the FACTORY side — call this helper twice
    on the two child meshes — not a complication of this primitive.

The created materials are named `Maquette_<palette_key>` and reused
across calls — every boulder asking for `rock_warm` shares the same
material data block, which keeps the .blend file size sane when
scattering hundreds.
"""

from __future__ import annotations

import bpy

from .palette import MAQUETTE_PALETTE, hex_to_rgba


_MATERIAL_PREFIX = "Maquette_"


def _get_or_create_palette_material(palette_key: str) -> bpy.types.Material:
    """Return the named Maquette material, creating it (with the palette
    color baked in) on first use. Reused across all callers."""
    if palette_key not in MAQUETTE_PALETTE:
        raise KeyError(f"unknown palette key {palette_key!r}; valid: {list(MAQUETTE_PALETTE)}")
    name = f"{_MATERIAL_PREFIX}{palette_key}"
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    bsdf.inputs["Base Color"].default_value = hex_to_rgba(MAQUETTE_PALETTE[palette_key])
    bsdf.inputs["Roughness"].default_value = 0.85   # matte for flat-shaded read
    bsdf.inputs["Metallic"].default_value = 0.0
    bsdf.inputs["IOR"].default_value = 1.45
    return mat


def apply_palette(obj: bpy.types.Object, palette_key: str) -> bpy.types.Object:
    """Replace all materials on `obj` with the Maquette palette material
    named `palette_key`. Idempotent — calling repeatedly with the same key
    does not duplicate material slots.

    Mirrors the Firewatch-style "one color per object" decision. If an
    asset has child meshes that need different colors (e.g. trunk vs
    leaves on a tree), call apply_palette on each child individually.
    """
    if obj.type != "MESH":
        return obj
    mat = _get_or_create_palette_material(palette_key)
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    return obj


def apply_palette_slots(
    obj: bpy.types.Object, slot_colors: list[str]
) -> bpy.types.Object:
    """Set up multiple material slots on `obj`, one per palette key in
    `slot_colors`. Polygons' material_index values are preserved — caller is
    responsible for having set those before/during geometry construction.

    Used by factories that want per-region color (e.g. NativeLowPolyTreeFactory
    splitting trunk from foliage). For a single-color asset, prefer
    apply_palette() — same end result with less ceremony.
    """
    if obj.type != "MESH":
        return obj
    obj.data.materials.clear()
    for key in slot_colors:
        obj.data.materials.append(_get_or_create_palette_material(key))
    return obj

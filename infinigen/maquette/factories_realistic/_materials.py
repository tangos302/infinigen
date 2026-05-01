"""Default PBR materials for structural / abstract factories.

Most upstream Infinigen factories ship full procedural shaders (bark,
foliage, rock surface, coral). The structural factories we wrap from
``extra_mesh_objects`` and our native ones (Wall, Beam, Pyramid, Pipe,
Solid, Supertoroid, Honeycomb, Menger, FunctionSurface, Gear, WormGear,
Gemstone) come out with no material — Cycles renders them as a flat
neutral grey, which clashes with the procedural-shader-rich realistic
mode aesthetic.

This module attaches a sensible default Principled-BSDF material per
factory at wrap time, keyed on the factory class name. The material is
deliberately monochrome — sophisticated multi-material setups would
need per-face vertex groups, which most of these factories don't emit.

For factories with archetype-keyed colour variation (like the building
factory), do the material work inside the factory itself; this helper
is for the simpler one-colour-per-asset case.
"""

from __future__ import annotations

from typing import Any

import bpy


# Class-name → (base_color RGB tuple, roughness, metallic).
# Lookups are by repr / qualname suffix so the with_default_material
# wrapper can find them after with_polycap subclassing.
_PALETTE: dict[str, tuple[tuple[float, float, float], float, float]] = {
    # Masonry & stone
    "RealisticWallFactory":          ((0.55, 0.50, 0.42), 0.85, 0.0),  # weathered stone
    "RealisticStepPyramidFactory":   ((0.78, 0.68, 0.50), 0.88, 0.0),  # sandstone
    # Mechanical / steel
    "RealisticBeamFactory":          ((0.42, 0.42, 0.45), 0.55, 0.85), # painted steel
    "RealisticPipeJointFactory":     ((0.45, 0.32, 0.22), 0.60, 0.40), # copper-bronze
    "RealisticGearFactory":          ((0.48, 0.42, 0.32), 0.45, 0.70), # bronze gear
    "RealisticWormGearFactory":      ((0.48, 0.42, 0.32), 0.45, 0.70), # bronze worm
    # Decorative / abstract
    "RealisticGemstoneFactory":      ((0.30, 0.55, 0.85), 0.05, 0.0),  # blue gem (high glossy via low roughness)
    "RealisticSolidFactory":         ((0.62, 0.58, 0.55), 0.45, 0.30), # pewter
    "RealisticSupertoroidFactory":   ((0.55, 0.42, 0.32), 0.55, 0.20), # bronze ring
    "RealisticHoneycombFactory":     ((0.85, 0.65, 0.20), 0.55, 0.0),  # honey-yellow
    "RealisticMengerSpongeFactory":  ((0.42, 0.45, 0.55), 0.40, 0.40), # cool-grey sci-fi
    "RealisticFunctionSurfaceFactory": ((0.65, 0.62, 0.58), 0.60, 0.20),  # dusty stone
}


def _make_pbr(name: str, base_color, roughness: float, metallic: float) -> bpy.types.Material:
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (*base_color, 1.0)
        bsdf.inputs["Roughness"].default_value = roughness
        bsdf.inputs["Metallic"].default_value = metallic
    return mat


def apply_default_material(obj: bpy.types.Object, factory_name: str) -> None:
    """Attach a single Principled-BSDF material to obj, keyed by
    factory class name. No-op if obj has no mesh data or no palette
    entry exists for the factory. Idempotent: skips if a material is
    already assigned (so factory-internal material work isn't
    overwritten).
    """
    if obj is None or obj.data is None or not hasattr(obj.data, "materials"):
        return
    if len(obj.data.materials) > 0:
        return  # respect any factory-internal material work
    palette = _PALETTE.get(factory_name)
    if palette is None:
        return
    base_color, roughness, metallic = palette
    obj.data.materials.append(
        _make_pbr(f"Default.{factory_name}", base_color, roughness, metallic)
    )


def with_default_material(cls: type) -> type:
    """Wrap ``cls.spawn_asset`` to apply a default PBR material on the
    way out. Pairs with ``with_polycap`` — apply this AFTER polycap so
    the material lands on the post-decimate mesh.
    """
    factory_name = cls.__name__
    if factory_name not in _PALETTE:
        return cls

    base_spawn = cls.spawn_asset

    def spawn_asset(self, *args, **kwargs):
        result = base_spawn(self, *args, **kwargs)
        if isinstance(result, tuple) and result and hasattr(result[0], "data"):
            apply_default_material(result[0], factory_name)
        elif result is not None and hasattr(result, "data"):
            apply_default_material(result, factory_name)
        return result

    out = type(
        cls.__name__,
        (cls,),
        {
            "spawn_asset": spawn_asset,
            "__module__": cls.__module__,
            "__qualname__": cls.__qualname__,
            "__doc__": cls.__doc__,
        },
    )
    out.__call__ = spawn_asset
    return out

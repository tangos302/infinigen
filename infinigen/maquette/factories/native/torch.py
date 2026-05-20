"""LowPolyTorchFactory — wall, pole, and tripod torches.

Torch meshes are small but scene-critical: they make castle walls,
ruin entrances, cave mouths, village roads, and night prompts read as
inhabited instead of just decorated. Each archetype includes a simple
emissive flame and optional parented point light.
"""

from __future__ import annotations

import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector

from infinigen.core.placement.factory import AssetFactory

from ...materials import (
    add_palette_point_light,
    apply_emission_palette_slot,
    apply_palette_slots,
)


_TORCH_ARCHETYPES = ("pole", "wall_sconce", "tripod")


_DEFAULTS = {
    "pole": dict(height=2.15, radius=0.055, flame_height=0.46, flame_radius=0.16, light_energy=70.0),
    "wall_sconce": dict(height=0.95, radius=0.05, flame_height=0.38, flame_radius=0.14, light_energy=58.0),
    "tripod": dict(height=1.45, radius=0.05, flame_height=0.42, flame_radius=0.18, light_energy=82.0),
}


def _face_count(bm: bmesh.types.BMesh) -> int:
    return len(bm.faces)


def _add_cylinder_between(
    bm: bmesh.types.BMesh,
    start: Vector,
    end: Vector,
    radius: float,
    n_sides: int,
    slot_ranges: list[tuple[int, int, int]],
    slot: int,
) -> None:
    face_start = _face_count(bm)
    axis = end - start
    length = axis.length
    if length <= 0:
        return
    z_axis = Vector((0.0, 0.0, 1.0))
    quat = z_axis.rotation_difference(axis.normalized())
    ring_a = []
    ring_b = []
    for i in range(n_sides):
        a = 2.0 * math.pi * i / n_sides
        local = Vector((radius * math.cos(a), radius * math.sin(a), 0.0))
        ring_a.append(bm.verts.new(start + quat @ local))
        ring_b.append(bm.verts.new(end + quat @ local))
    bm.verts.ensure_lookup_table()
    for i in range(n_sides):
        ni = (i + 1) % n_sides
        bm.faces.new((ring_a[i], ring_a[ni], ring_b[ni], ring_b[i]))
    bm.faces.new(list(reversed(ring_a)))
    bm.faces.new(ring_b)
    slot_ranges.append((face_start, _face_count(bm), slot))


def _add_flame(
    bm: bmesh.types.BMesh,
    center: Vector,
    radius: float,
    height: float,
    slot_ranges: list[tuple[int, int, int]],
    rng: random.Random,
) -> None:
    face_start = _face_count(bm)
    ring = []
    for i in range(6):
        a = 2.0 * math.pi * i / 6.0
        r = radius * rng.uniform(0.80, 1.18)
        ring.append(bm.verts.new((center.x + r * math.cos(a), center.y + r * math.sin(a), center.z)))
    apex = bm.verts.new((
        center.x + rng.uniform(-0.035, 0.035),
        center.y + rng.uniform(-0.035, 0.035),
        center.z + height,
    ))
    bm.verts.ensure_lookup_table()
    for i in range(6):
        ni = (i + 1) % 6
        bm.faces.new((ring[i], ring[ni], apex))
    slot_ranges.append((face_start, _face_count(bm), 2))


class LowPolyTorchFactory(AssetFactory):
    """A compact torch with real light.

    Constructor knobs:
        factory_seed
        torch_archetype : "pole" | "wall_sconce" | "tripod"
        height, radius, flame_height, flame_radius
        wood_color, metal_color, flame_color
        emit_light, light_energy, light_radius, emission_strength
    """

    def __init__(
        self,
        factory_seed,
        torch_archetype: str = "pole",
        height: float | None = None,
        radius: float | None = None,
        flame_height: float | None = None,
        flame_radius: float | None = None,
        wood_color: str = "wood",
        metal_color: str = "rust_metal",
        flame_color: str = "foliage_amber",
        emit_light: bool = True,
        light_energy: float | None = None,
        light_radius: float = 1.25,
        emission_strength: float = 4.2,
        coarse: bool = False,
        **_unused_kwargs,
    ) -> None:
        super().__init__(factory_seed, coarse=coarse)
        if _unused_kwargs:
            from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
            accept_unused_kwargs("LowPolyTorchFactory", _unused_kwargs)
        if torch_archetype not in _TORCH_ARCHETYPES:
            import sys
            print(
                f"[torch_archetype] WARN: unknown {torch_archetype!r}; "
                f"falling back to {_TORCH_ARCHETYPES[0]!r}. Valid: {_TORCH_ARCHETYPES}",
                file=sys.stderr,
            )
            torch_archetype = _TORCH_ARCHETYPES[0]
        d = _DEFAULTS[torch_archetype]
        self.torch_archetype = torch_archetype
        self.height = float(height if height is not None else d["height"])
        self.radius = float(radius if radius is not None else d["radius"])
        self.flame_height = float(flame_height if flame_height is not None else d["flame_height"])
        self.flame_radius = float(flame_radius if flame_radius is not None else d["flame_radius"])
        self.wood_color = wood_color
        self.metal_color = metal_color
        self.flame_color = flame_color
        self.emit_light = bool(emit_light)
        self.light_energy = float(light_energy if light_energy is not None else d["light_energy"])
        self.light_radius = float(light_radius)
        self.emission_strength = float(emission_strength)

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(f"LowPolyTorch({self.factory_seed})_placeholder", None)
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        rng = random.Random(int(self.factory_seed) + 39191)
        bm = bmesh.new()
        slots: list[tuple[int, int, int]] = []

        flame_center = Vector((0.0, 0.0, self.height))
        if self.torch_archetype == "pole":
            _add_cylinder_between(bm, Vector((0, 0, 0)), Vector((0, 0, self.height)), self.radius, 6, slots, 0)
            _add_cylinder_between(
                bm,
                Vector((-0.18, 0, self.height * 0.82)),
                Vector((0.18, 0, self.height * 0.82)),
                self.radius * 0.55,
                5,
                slots,
                1,
            )
        elif self.torch_archetype == "wall_sconce":
            _add_cylinder_between(
                bm,
                Vector((0.0, -0.18, self.height * 0.35)),
                Vector((0.0, 0.32, self.height)),
                self.radius,
                6,
                slots,
                0,
            )
            _add_cylinder_between(
                bm,
                Vector((-0.22, -0.2, self.height * 0.32)),
                Vector((0.22, -0.2, self.height * 0.32)),
                self.radius * 0.45,
                4,
                slots,
                1,
            )
            flame_center = Vector((0.0, 0.35, self.height))
        else:
            for i in range(3):
                a = 2.0 * math.pi * i / 3.0
                foot = Vector((0.34 * math.cos(a), 0.34 * math.sin(a), 0.0))
                _add_cylinder_between(bm, foot, Vector((0, 0, self.height)), self.radius, 5, slots, 0)
            _add_cylinder_between(
                bm,
                Vector((-0.24, 0, self.height * 0.78)),
                Vector((0.24, 0, self.height * 0.78)),
                self.radius * 0.50,
                5,
                slots,
                1,
            )

        _add_flame(bm, flame_center, self.flame_radius, self.flame_height, slots, rng)

        mesh = bpy.data.meshes.new(f"LowPolyTorch({self.factory_seed})_Mesh")
        bm.to_mesh(mesh)
        bm.free()
        obj = bpy.data.objects.new(f"LowPolyTorch({self.factory_seed})", mesh)
        bpy.context.scene.collection.objects.link(obj)
        while len(obj.data.materials) < 3:
            obj.data.materials.append(None)
        for start, end, slot in slots:
            for face_idx in range(start, end):
                obj.data.polygons[face_idx].material_index = slot
        for poly in obj.data.polygons:
            poly.use_smooth = False

        apply_palette_slots(obj, [self.wood_color, self.metal_color, self.flame_color])
        apply_emission_palette_slot(obj, 2, self.flame_color, strength=self.emission_strength)
        if self.emit_light:
            add_palette_point_light(
                name=f"{obj.name}_PointLight",
                location=(flame_center.x, flame_center.y, flame_center.z + self.flame_height * 0.45),
                palette_key=self.flame_color,
                energy=self.light_energy,
                radius=self.light_radius,
                parent=obj,
            )
        return obj

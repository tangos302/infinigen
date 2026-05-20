"""LowPolyStringLightsFactory — plaza and camp light spans.

String lights are intentionally compositional props: one asset can make
a market square, tavern patio, caravan camp, or coastal pier read as
inhabited. The mesh stays low-poly and uses a single parented point
light so repeated spans do not explode the light count.
"""

from __future__ import annotations

import math
import random

import bmesh
import bpy
from mathutils import Vector

from infinigen.core.placement.factory import AssetFactory

from ...materials import (
    add_palette_point_light,
    apply_emission_palette_slot,
    apply_palette_slots,
)


_STRING_LIGHT_ARCHETYPES = ("market_span", "festival_arc", "camp_line")


_DEFAULTS = {
    "market_span": dict(span=5.6, height=2.45, post_thickness=0.10, bulb_count=6, sag=0.34, light_energy=72.0),
    "festival_arc": dict(span=7.2, height=2.80, post_thickness=0.11, bulb_count=8, sag=0.58, light_energy=92.0),
    "camp_line": dict(span=3.9, height=1.85, post_thickness=0.075, bulb_count=5, sag=0.28, light_energy=46.0),
}


def _face_count(bm: bmesh.types.BMesh) -> int:
    return len(bm.faces)


def _add_box(
    bm: bmesh.types.BMesh,
    *,
    center: tuple[float, float, float],
    size: tuple[float, float, float],
    slot_ranges: list[tuple[int, int, int]],
    slot: int,
) -> None:
    cx, cy, cz = center
    sx, sy, sz = (max(0.001, float(v)) * 0.5 for v in size)
    face_start = _face_count(bm)
    verts = [
        bm.verts.new((cx - sx, cy - sy, cz - sz)),
        bm.verts.new((cx + sx, cy - sy, cz - sz)),
        bm.verts.new((cx + sx, cy + sy, cz - sz)),
        bm.verts.new((cx - sx, cy + sy, cz - sz)),
        bm.verts.new((cx - sx, cy - sy, cz + sz)),
        bm.verts.new((cx + sx, cy - sy, cz + sz)),
        bm.verts.new((cx + sx, cy + sy, cz + sz)),
        bm.verts.new((cx - sx, cy + sy, cz + sz)),
    ]
    faces = (
        (0, 1, 2, 3),
        (4, 7, 6, 5),
        (0, 4, 5, 1),
        (1, 5, 6, 2),
        (2, 6, 7, 3),
        (3, 7, 4, 0),
    )
    for idxs in faces:
        bm.faces.new(tuple(verts[i] for i in idxs))
    slot_ranges.append((face_start, _face_count(bm), slot))


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
    if length <= 1e-4:
        return
    quat = Vector((0.0, 0.0, 1.0)).rotation_difference(axis.normalized())
    ring_a: list[bmesh.types.BMVert] = []
    ring_b: list[bmesh.types.BMVert] = []
    for i in range(max(4, int(n_sides))):
        a = 2.0 * math.pi * i / max(4, int(n_sides))
        local = Vector((radius * math.cos(a), radius * math.sin(a), 0.0))
        ring_a.append(bm.verts.new(start + quat @ local))
        ring_b.append(bm.verts.new(end + quat @ local))
    bm.verts.ensure_lookup_table()
    count = len(ring_a)
    for i in range(count):
        ni = (i + 1) % count
        bm.faces.new((ring_a[i], ring_a[ni], ring_b[ni], ring_b[i]))
    bm.faces.new(list(reversed(ring_a)))
    bm.faces.new(ring_b)
    slot_ranges.append((face_start, _face_count(bm), slot))


def _add_diamond_bulb(
    bm: bmesh.types.BMesh,
    *,
    center: Vector,
    radius: float,
    height: float,
    slot_ranges: list[tuple[int, int, int]],
    rng: random.Random,
) -> None:
    face_start = _face_count(bm)
    r = max(0.035, float(radius)) * rng.uniform(0.86, 1.12)
    h = max(0.07, float(height)) * rng.uniform(0.88, 1.10)
    top = bm.verts.new((center.x, center.y, center.z + h * 0.5))
    bottom = bm.verts.new((center.x, center.y, center.z - h * 0.5))
    ring = [
        bm.verts.new((center.x + r, center.y, center.z)),
        bm.verts.new((center.x, center.y + r, center.z)),
        bm.verts.new((center.x - r, center.y, center.z)),
        bm.verts.new((center.x, center.y - r, center.z)),
    ]
    for i in range(4):
        ni = (i + 1) % 4
        bm.faces.new((ring[i], ring[ni], top))
        bm.faces.new((ring[ni], ring[i], bottom))
    slot_ranges.append((face_start, _face_count(bm), 2))


class LowPolyStringLightsFactory(AssetFactory):
    """A reusable light span for markets, camps, taverns, and piers.

    Constructor knobs:
        factory_seed
        lights_archetype : "market_span" | "festival_arc" | "camp_line"
        span, height, post_thickness, bulb_count, sag
        wood_color, cable_color, glow_color
        emit_light, light_energy, light_radius, emission_strength
    """

    def __init__(
        self,
        factory_seed,
        lights_archetype: str = "market_span",
        span: float | None = None,
        height: float | None = None,
        post_thickness: float | None = None,
        bulb_count: int | None = None,
        sag: float | None = None,
        wood_color: str = "wood",
        cable_color: str = "rust_metal",
        glow_color: str = "foliage_lemon",
        emit_light: bool = True,
        light_energy: float | None = None,
        light_radius: float | None = None,
        emission_strength: float = 4.6,
        coarse: bool = False,
        **_unused_kwargs,
    ) -> None:
        super().__init__(factory_seed, coarse=coarse)
        if _unused_kwargs:
            from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
            accept_unused_kwargs("LowPolyStringLightsFactory", _unused_kwargs)
        if lights_archetype not in _STRING_LIGHT_ARCHETYPES:
            import sys
            print(
                f"[lights_archetype] WARN: unknown {lights_archetype!r}; "
                f"falling back to {_STRING_LIGHT_ARCHETYPES[0]!r}. Valid: {_STRING_LIGHT_ARCHETYPES}",
                file=sys.stderr,
            )
            lights_archetype = _STRING_LIGHT_ARCHETYPES[0]
        d = _DEFAULTS[lights_archetype]
        self.lights_archetype = lights_archetype
        self.span = float(span if span is not None else d["span"])
        self.height = float(height if height is not None else d["height"])
        self.post_thickness = float(post_thickness if post_thickness is not None else d["post_thickness"])
        self.bulb_count = max(2, int(bulb_count if bulb_count is not None else d["bulb_count"]))
        self.sag = float(sag if sag is not None else d["sag"])
        self.wood_color = wood_color
        self.cable_color = cable_color
        self.glow_color = glow_color
        self.emit_light = bool(emit_light)
        self.light_energy = float(light_energy if light_energy is not None else d["light_energy"])
        self.light_radius = float(light_radius if light_radius is not None else max(1.8, self.span * 0.30))
        self.emission_strength = float(emission_strength)

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(f"LowPolyStringLights({self.factory_seed})_placeholder", None)
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        rng = random.Random(int(self.factory_seed) + 59117)
        bm = bmesh.new()
        slots: list[tuple[int, int, int]] = []
        half = self.span * 0.5
        post = self.post_thickness

        for x in (-half, half):
            _add_box(
                bm,
                center=(x, 0.0, self.height * 0.5),
                size=(post, post, self.height),
                slot_ranges=slots,
                slot=0,
            )
            _add_box(
                bm,
                center=(x, 0.0, self.height + post * 0.35),
                size=(post * 1.9, post * 1.9, post * 0.42),
                slot_ranges=slots,
                slot=0,
            )

        cable_points: list[Vector] = []
        segments = max(5, self.bulb_count + 1)
        for i in range(segments + 1):
            t = i / segments
            x = -half + self.span * t
            sag_weight = 1.0 - (2.0 * t - 1.0) ** 2
            z = self.height - self.sag * sag_weight
            cable_points.append(Vector((x, 0.0, z)))
        for a, b in zip(cable_points, cable_points[1:]):
            _add_cylinder_between(bm, a, b, post * 0.13, 4, slots, 1)

        for i in range(self.bulb_count):
            t = (i + 1) / (self.bulb_count + 1)
            x = -half + self.span * t
            sag_weight = 1.0 - (2.0 * t - 1.0) ** 2
            cable_z = self.height - self.sag * sag_weight
            drop = rng.uniform(0.08, 0.18)
            _add_cylinder_between(
                bm,
                Vector((x, 0.0, cable_z)),
                Vector((x, 0.0, cable_z - drop)),
                post * 0.08,
                4,
                slots,
                1,
            )
            _add_diamond_bulb(
                bm,
                center=Vector((x, 0.0, cable_z - drop - 0.09)),
                radius=post * 0.55,
                height=post * 1.45,
                slot_ranges=slots,
                rng=rng,
            )

        mesh = bpy.data.meshes.new(f"LowPolyStringLights({self.factory_seed})_Mesh")
        bm.to_mesh(mesh)
        bm.free()
        obj = bpy.data.objects.new(f"LowPolyStringLights({self.factory_seed})", mesh)
        bpy.context.scene.collection.objects.link(obj)
        while len(obj.data.materials) < 3:
            obj.data.materials.append(None)
        for start, end, slot in slots:
            for idx in range(start, end):
                obj.data.polygons[idx].material_index = slot
        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(obj, [self.wood_color, self.cable_color, self.glow_color])
        apply_emission_palette_slot(obj, 2, self.glow_color, strength=self.emission_strength)
        if self.emit_light:
            add_palette_point_light(
                name=f"{obj.name}_glow",
                location=(0.0, 0.0, self.height - max(0.05, self.sag) * 0.55),
                palette_key=self.glow_color,
                energy=self.light_energy,
                radius=self.light_radius,
                parent=obj,
            )
        return obj


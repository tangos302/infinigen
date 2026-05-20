"""LowPolyForgeFactory — blacksmith's forge / masonry fire hearth.

The hero light source of a smithy scene: a built-up hearth where the
coal fire burns. Pairs with LowPolySmithyPropsFactory (anvil, quench
trough, grindstone, tool rack, coal pile) to dress a blacksmith yard.
Like the campfire, the fire emits both visible glow materials and a
real point light parented to the mesh.

Archetypes:
  stone_hearth      — low stone masonry block on a plinth, coals in a
                      metal firepot rim, a short stone back wall. The
                      classic open village forge.
  brick_chimney     — taller workshop forge with a full brick flue
                      rising off the back and an angled metal hood
                      funnelling the coals into it.
  open_field_forge  — a portable raised metal fire pan on stubby legs,
                      no chimney. A farrier / campaign smithy.

Material slots:
  slot 0 = masonry (plinth, stone block, back wall, brick chimney)
  slot 1 = metal (firepot rim, hood, fire pan, legs)
  slot 2 = coal bed (gently glowing embers — large area, low emission)
  slot 3 = flame tongues (small area, bright emission)
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


_FORGE_ARCHETYPES = ("stone_hearth", "brick_chimney", "open_field_forge")

_LEG_HEIGHT = 0.5


_ARCHETYPE_DEFAULTS = {
    "stone_hearth": dict(
        body_width=1.25,
        body_depth=0.95,
        body_height=0.82,
        body_taper=0.93,
        body_is_metal=False,
        has_back_wall=True,
        has_chimney=False,
        has_hood=False,
        has_legs=False,
        has_rim=True,
        coal_radius=0.35,
        coal_offset_y=-0.06,
        flame_count=3,
        flame_height=0.30,
        masonry_color="rock_cool",
        metal_color="rust_metal",
        flame_color="foliage_amber",
        light_energy=150.0,
        light_radius=2.4,
        coal_emission=1.5,
        emission_strength=4.2,
    ),
    "brick_chimney": dict(
        body_width=1.16,
        body_depth=0.96,
        body_height=0.82,
        body_taper=0.96,
        body_is_metal=False,
        has_back_wall=False,
        has_chimney=True,
        has_hood=True,
        has_legs=False,
        has_rim=False,
        coal_radius=0.36,
        coal_offset_y=-0.12,
        flame_count=3,
        flame_height=0.32,
        masonry_color="rock_warm",
        metal_color="rust_metal",
        flame_color="foliage_lemon",
        light_energy=165.0,
        light_radius=2.5,
        coal_emission=1.7,
        emission_strength=4.5,
    ),
    "open_field_forge": dict(
        body_width=0.96,
        body_depth=0.84,
        body_height=0.24,
        body_taper=1.0,
        body_is_metal=True,
        has_back_wall=False,
        has_chimney=False,
        has_hood=False,
        has_legs=True,
        has_rim=True,
        coal_radius=0.30,
        coal_offset_y=0.0,
        flame_count=2,
        flame_height=0.22,
        masonry_color="rock_cool",
        metal_color="rust_metal",
        flame_color="foliage_amber",
        light_energy=95.0,
        light_radius=1.9,
        coal_emission=1.3,
        emission_strength=3.6,
    ),
}


def _face_count(bm: bmesh.types.BMesh) -> int:
    return len(bm.faces)


def _add_box(
    bm: bmesh.types.BMesh,
    *,
    cx: float,
    cy: float,
    z0: float,
    sx: float,
    sy: float,
    sz: float,
    slot: int,
    slot_ranges: list[tuple[int, int, int]],
    top_scale_x: float = 1.0,
    top_scale_y: float = 1.0,
    top_dx: float = 0.0,
    top_dy: float = 0.0,
    rot_z: float = 0.0,
) -> None:
    """A box from z0 to z0+sz, footprint sx*sy centred on (cx, cy).

    The top face can be independently scaled (`top_scale_*`) and sheared
    (`top_d*`), so the one helper covers plain boxes, masonry batter, a
    tapered chimney flue, and the back-leaning hood.
    """
    start = _face_count(bm)
    rot = Matrix.Rotation(float(rot_z), 4, "Z")
    hx, hy = sx * 0.5, sy * 0.5
    txh, tyh = hx * top_scale_x, hy * top_scale_y
    bottom_local = ((-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy))
    top_local = ((-txh, -tyh), (txh, -tyh), (txh, tyh), (-txh, tyh))
    bottom = []
    top = []
    for lx, ly in bottom_local:
        p = rot @ Vector((lx, ly, 0.0))
        bottom.append(bm.verts.new((cx + p.x, cy + p.y, z0)))
    for lx, ly in top_local:
        p = rot @ Vector((lx + top_dx, ly + top_dy, 0.0))
        top.append(bm.verts.new((cx + p.x, cy + p.y, z0 + sz)))
    bm.verts.ensure_lookup_table()
    for i in range(4):
        ni = (i + 1) % 4
        bm.faces.new((bottom[i], bottom[ni], top[ni], top[i]))
    bm.faces.new(tuple(reversed(bottom)))
    bm.faces.new(tuple(top))
    slot_ranges.append((start, _face_count(bm), int(slot)))


def _add_prism(
    bm: bmesh.types.BMesh,
    *,
    center: tuple[float, float, float],
    radius: float,
    height: float,
    n_sides: int,
    slot: int,
    slot_ranges: list[tuple[int, int, int]],
    scale_y: float = 1.0,
    rot_z: float = 0.0,
) -> None:
    start = _face_count(bm)
    cx, cy, cz = center
    rot = Matrix.Rotation(float(rot_z), 4, "Z")
    bottom = []
    top = []
    for i in range(n_sides):
        a = 2.0 * math.pi * i / n_sides
        local = Vector((radius * math.cos(a), radius * scale_y * math.sin(a), 0.0))
        p = Vector((cx, cy, cz)) + (rot @ local)
        bottom.append(bm.verts.new((p.x, p.y, p.z)))
        top.append(bm.verts.new((p.x, p.y, p.z + height)))
    bm.verts.ensure_lookup_table()
    for i in range(n_sides):
        ni = (i + 1) % n_sides
        bm.faces.new((bottom[i], bottom[ni], top[ni], top[i]))
    bm.faces.new(tuple(reversed(bottom)))
    bm.faces.new(tuple(top))
    slot_ranges.append((start, _face_count(bm), int(slot)))


def _add_flame(
    bm: bmesh.types.BMesh,
    *,
    cx: float,
    cy: float,
    z0: float,
    radius: float,
    height: float,
    slot: int,
    slot_ranges: list[tuple[int, int, int]],
    rng: random.Random,
) -> None:
    start = _face_count(bm)
    n_sides = 6
    ring = []
    for i in range(n_sides):
        a = 2.0 * math.pi * i / n_sides
        r = radius * rng.uniform(0.72, 1.16)
        ring.append(bm.verts.new((cx + r * math.cos(a), cy + r * math.sin(a), z0)))
    apex = bm.verts.new(
        (cx + rng.uniform(-0.06, 0.06), cy + rng.uniform(-0.06, 0.06), z0 + height)
    )
    bm.verts.ensure_lookup_table()
    for i in range(n_sides):
        ni = (i + 1) % n_sides
        bm.faces.new((ring[i], ring[ni], apex))
    slot_ranges.append((start, _face_count(bm), int(slot)))


def _add_coal_bed(
    bm: bmesh.types.BMesh,
    *,
    cx: float,
    cy: float,
    z0: float,
    radius: float,
    slot: int,
    slot_ranges: list[tuple[int, int, int]],
    rng: random.Random,
) -> float:
    """A flat octagonal coal bed plus a scatter of lumps. Returns the
    approximate Z of the top of the coals (where flames start)."""
    _add_prism(
        bm,
        center=(cx, cy, z0),
        radius=radius,
        height=0.09,
        n_sides=8,
        slot=slot,
        slot_ranges=slot_ranges,
        scale_y=0.82,
        rot_z=rng.uniform(0.0, math.pi),
    )
    for _ in range(rng.randint(5, 8)):
        a = rng.uniform(0.0, 2.0 * math.pi)
        rr = radius * rng.uniform(0.0, 0.66)
        _add_prism(
            bm,
            center=(cx + rr * math.cos(a), cy + rr * math.sin(a) * 0.82, z0 + 0.06),
            radius=rng.uniform(0.05, 0.10),
            height=rng.uniform(0.05, 0.12),
            n_sides=rng.choice((5, 6)),
            slot=slot,
            slot_ranges=slot_ranges,
            scale_y=rng.uniform(0.7, 1.1),
            rot_z=rng.uniform(0.0, math.pi),
        )
    return z0 + 0.13


class LowPolyForgeFactory(AssetFactory):
    """A masonry blacksmith's forge with a glowing coal bed + point light.

    Constructor knobs:
        factory_seed
        forge_archetype : "stone_hearth" | "brick_chimney" | "open_field_forge"
        masonry_color, metal_color, flame_color
        emit_light, light_energy, light_radius, emission_strength
    """

    def __init__(
        self,
        factory_seed,
        forge_archetype: str = "stone_hearth",
        masonry_color: str | None = None,
        metal_color: str | None = None,
        flame_color: str | None = None,
        emit_light: bool = True,
        light_energy: float | None = None,
        light_radius: float | None = None,
        emission_strength: float | None = None,
        coarse: bool = False,
        **_unused_kwargs,
    ) -> None:
        super().__init__(factory_seed, coarse=coarse)
        if _unused_kwargs:
            from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
            accept_unused_kwargs("LowPolyForgeFactory", _unused_kwargs)
        if forge_archetype not in _FORGE_ARCHETYPES:
            import sys
            print(
                f"[forge_archetype] WARN: unknown {forge_archetype!r}; "
                f"falling back to {_FORGE_ARCHETYPES[0]!r}. Valid: {_FORGE_ARCHETYPES}",
                file=sys.stderr,
            )
            forge_archetype = _FORGE_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[forge_archetype]
        self.forge_archetype = forge_archetype
        # geometry — authored per archetype, not exposed as knobs
        self.body_width = float(d["body_width"])
        self.body_depth = float(d["body_depth"])
        self.body_height = float(d["body_height"])
        self.body_taper = float(d["body_taper"])
        self.body_is_metal = bool(d["body_is_metal"])
        self.has_back_wall = bool(d["has_back_wall"])
        self.has_chimney = bool(d["has_chimney"])
        self.has_hood = bool(d["has_hood"])
        self.has_legs = bool(d["has_legs"])
        self.has_rim = bool(d["has_rim"])
        self.coal_radius = float(d["coal_radius"])
        self.coal_offset_y = float(d["coal_offset_y"])
        self.flame_count = int(d["flame_count"])
        self.flame_height = float(d["flame_height"])
        self.coal_emission = float(d["coal_emission"])
        # look — overridable for presets
        self.masonry_color = masonry_color or d["masonry_color"]
        self.metal_color = metal_color or d["metal_color"]
        self.flame_color = flame_color or d["flame_color"]
        self.emit_light = bool(emit_light)
        self.light_energy = float(light_energy if light_energy is not None else d["light_energy"])
        self.light_radius = float(light_radius if light_radius is not None else d["light_radius"])
        self.emission_strength = float(
            emission_strength if emission_strength is not None else d["emission_strength"]
        )

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(f"LowPolyForge({self.factory_seed})_placeholder", None)
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        rng = random.Random(int(self.factory_seed) + 51807)
        bm = bmesh.new()
        slot_ranges: list[tuple[int, int, int]] = []

        # Raised metal fire pan sits on stubby legs (open_field_forge);
        # the masonry forges stand on a slightly oversized stone plinth.
        body_z0 = 0.0
        if self.has_legs:
            inset = 0.15
            for sx_sign in (-1.0, 1.0):
                for sy_sign in (-1.0, 1.0):
                    _add_box(
                        bm,
                        cx=sx_sign * (self.body_width * 0.5 - inset),
                        cy=sy_sign * (self.body_depth * 0.5 - inset),
                        z0=0.0,
                        sx=0.11,
                        sy=0.11,
                        sz=_LEG_HEIGHT,
                        slot=1,
                        slot_ranges=slot_ranges,
                    )
            body_z0 = _LEG_HEIGHT - 0.03
        else:
            plinth_height = 0.16
            _add_box(
                bm,
                cx=0.0,
                cy=0.0,
                z0=0.0,
                sx=self.body_width + 0.22,
                sy=self.body_depth + 0.18,
                sz=plinth_height,
                slot=0,
                slot_ranges=slot_ranges,
            )
            body_z0 = plinth_height - 0.03

        body_slot = 1 if self.body_is_metal else 0
        _add_box(
            bm,
            cx=0.0,
            cy=0.0,
            z0=body_z0,
            sx=self.body_width,
            sy=self.body_depth,
            sz=self.body_height,
            slot=body_slot,
            slot_ranges=slot_ranges,
            top_scale_x=self.body_taper,
            top_scale_y=self.body_taper,
        )
        body_top = body_z0 + self.body_height

        if self.has_back_wall:
            wall_depth = 0.20
            _add_box(
                bm,
                cx=0.0,
                cy=self.body_depth * 0.5 - wall_depth * 0.5,
                z0=body_top - 0.05,
                sx=self.body_width * 0.98,
                sy=wall_depth,
                sz=0.66,
                slot=0,
                slot_ranges=slot_ranges,
            )

        if self.has_chimney:
            ch_depth = 0.44
            _add_box(
                bm,
                cx=0.0,
                cy=self.body_depth * 0.5 - ch_depth * 0.5,
                z0=body_top - 0.05,
                sx=0.96,
                sy=ch_depth,
                sz=2.30,
                slot=0,
                slot_ranges=slot_ranges,
                top_scale_x=0.62,
                top_scale_y=0.80,
            )

        coal_cy = self.coal_offset_y
        coal_top = _add_coal_bed(
            bm,
            cx=0.0,
            cy=coal_cy,
            z0=body_top - 0.06,
            radius=self.coal_radius,
            slot=2,
            slot_ranges=slot_ranges,
            rng=rng,
        )

        if self.has_rim:
            # low metal firepot rim so the coals sit IN a hearth rather
            # than on a bare tabletop
            rim_h = 0.14
            rim_t = 0.08
            rim_z0 = body_top - 0.04
            reach = self.coal_radius + 0.05
            for sy_sign in (-1.0, 1.0):
                _add_box(
                    bm,
                    cx=0.0,
                    cy=coal_cy + sy_sign * reach,
                    z0=rim_z0,
                    sx=2.0 * reach + rim_t,
                    sy=rim_t,
                    sz=rim_h,
                    slot=1,
                    slot_ranges=slot_ranges,
                )
            for sx_sign in (-1.0, 1.0):
                _add_box(
                    bm,
                    cx=sx_sign * reach,
                    cy=coal_cy,
                    z0=rim_z0,
                    sx=rim_t,
                    sy=2.0 * reach - rim_t,
                    sz=rim_h,
                    slot=1,
                    slot_ranges=slot_ranges,
                )

        if self.has_hood:
            hood_cy = coal_cy + 0.02
            _add_box(
                bm,
                cx=0.0,
                cy=hood_cy,
                z0=coal_top + self.flame_height + 0.05,
                sx=self.coal_radius * 2.0 + 0.22,
                sy=self.coal_radius * 1.7,
                sz=0.46,
                slot=1,
                slot_ranges=slot_ranges,
                top_scale_x=0.5,
                top_scale_y=0.44,
                top_dy=(self.body_depth * 0.5 - 0.30) - hood_cy,
            )

        for i in range(max(1, self.flame_count)):
            a = 2.0 * math.pi * i / max(1, self.flame_count) + rng.uniform(-0.4, 0.4)
            rr = self.coal_radius * rng.uniform(0.0, 0.5)
            _add_flame(
                bm,
                cx=rr * math.cos(a),
                cy=coal_cy + rr * math.sin(a) * 0.8,
                z0=coal_top,
                radius=self.coal_radius * rng.uniform(0.26, 0.38),
                height=self.flame_height * rng.uniform(0.82, 1.20),
                slot=3,
                slot_ranges=slot_ranges,
                rng=rng,
            )

        me = bpy.data.meshes.new(f"LowPolyForge({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(f"LowPolyForge({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)
        while len(obj.data.materials) < 4:
            obj.data.materials.append(None)
        for start, end, slot in slot_ranges:
            for face_idx in range(start, end):
                obj.data.polygons[face_idx].material_index = slot
        for poly in obj.data.polygons:
            poly.use_smooth = False

        apply_palette_slots(
            obj,
            [self.masonry_color, self.metal_color, self.flame_color, self.flame_color],
        )
        # The coal bed glows gently (large surface, low strength) while the
        # flame tongues are bright (small surface). Splitting the emission
        # keeps the bed from blowing out into a single white blob.
        apply_emission_palette_slot(obj, 2, self.flame_color, strength=self.coal_emission)
        apply_emission_palette_slot(obj, 3, self.flame_color, strength=self.emission_strength)
        if self.emit_light:
            add_palette_point_light(
                name=f"{obj.name}_PointLight",
                location=(0.0, coal_cy, coal_top + self.flame_height * 0.6 + 0.16),
                palette_key=self.flame_color,
                energy=self.light_energy,
                radius=self.light_radius,
                parent=obj,
            )
        return obj

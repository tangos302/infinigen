"""LowPolySmithyPropsFactory — blacksmith yard prop kit.

The working props that dress a smithy around the LowPolyForgeFactory
hearth. Each archetype is a distinct object; the factory seed drives
dimensional variation within each.

Archetypes:
  anvil          — London-pattern anvil (horn + face + waist + foot)
                   on a wooden stump.
  quench_trough  — wooden water trough for quenching hot iron; the
                   water is a real translucent-shader child mesh.
  grindstone     — circular sharpening stone on a hand-cranked frame.
  tool_rack      — a frame of posts hung with smith tools.
  coal_pile      — a heap of coal / coke fuel.

Material slots:
  slot 0 = wood (stumps, frames, trough body, handles)
  slot 1 = metal (anvil, axle, tool heads)
  slot 2 = stone (grindstone wheel)
  slot 3 = coal (coal pile)
The quench-trough water is a separate child object carrying the
Maquette translucent-water material.
"""

from __future__ import annotations

import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots, apply_water_material


_SMITHY_PROPS_ARCHETYPES = ("anvil", "quench_trough", "grindstone", "tool_rack", "coal_pile")


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
    rot_z: float = 0.0,
) -> None:
    """A box from z0 to z0+sz, footprint sx*sy centred on (cx, cy), with
    an optionally scaled top face and Z rotation."""
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
        p = rot @ Vector((lx, ly, 0.0))
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


def _add_wheel(
    bm: bmesh.types.BMesh,
    *,
    cx: float,
    cy: float,
    cz: float,
    radius: float,
    thickness: float,
    n_sides: int,
    slot: int,
    slot_ranges: list[tuple[int, int, int]],
) -> None:
    """A disc / cylinder with its axis along X — a grindstone wheel, or
    an axle laid sideways when given a small radius."""
    start = _face_count(bm)
    half = thickness * 0.5
    rings: list[list[bmesh.types.BMVert]] = []
    for x in (cx - half, cx + half):
        ring = []
        for i in range(n_sides):
            a = 2.0 * math.pi * i / n_sides
            ring.append(
                bm.verts.new((x, cy + radius * math.cos(a), cz + radius * math.sin(a)))
            )
        rings.append(ring)
    bm.verts.ensure_lookup_table()
    a_ring, b_ring = rings
    for i in range(n_sides):
        ni = (i + 1) % n_sides
        bm.faces.new((a_ring[i], a_ring[ni], b_ring[ni], b_ring[i]))
    bm.faces.new(tuple(reversed(a_ring)))
    bm.faces.new(tuple(b_ring))
    slot_ranges.append((start, _face_count(bm), int(slot)))


def _add_horn(
    bm: bmesh.types.BMesh,
    *,
    base_x: float,
    tip_x: float,
    cy: float,
    cz: float,
    base_w: float,
    base_h: float,
    slot: int,
    slot_ranges: list[tuple[int, int, int]],
) -> None:
    """A 4-sided tapered point — the anvil's horn. The base quad is left
    open; callers inset `base_x` into the anvil body so the opening is
    hidden inside solid geometry."""
    start = _face_count(bm)
    hw, hh = base_w * 0.5, base_h * 0.5
    base = [
        bm.verts.new((base_x, cy - hw, cz - hh)),
        bm.verts.new((base_x, cy + hw, cz - hh)),
        bm.verts.new((base_x, cy + hw, cz + hh)),
        bm.verts.new((base_x, cy - hw, cz + hh)),
    ]
    tip = bm.verts.new((tip_x, cy, cz + 0.015))
    bm.verts.ensure_lookup_table()
    for i in range(4):
        ni = (i + 1) % 4
        bm.faces.new((base[i], base[ni], tip))
    slot_ranges.append((start, _face_count(bm), int(slot)))


class LowPolySmithyPropsFactory(AssetFactory):
    """A kit of blacksmith yard props selected by `prop_archetype`.

    Constructor knobs:
        factory_seed
        prop_archetype : "anvil" | "quench_trough" | "grindstone"
                         | "tool_rack" | "coal_pile"
        wood_color, metal_color, stone_color, coal_color
    """

    def __init__(
        self,
        factory_seed,
        prop_archetype: str = "anvil",
        wood_color: str | None = None,
        metal_color: str | None = None,
        stone_color: str | None = None,
        coal_color: str | None = None,
        coarse: bool = False,
        **_unused_kwargs,
    ) -> None:
        super().__init__(factory_seed, coarse=coarse)
        if _unused_kwargs:
            from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
            accept_unused_kwargs("LowPolySmithyPropsFactory", _unused_kwargs)
        if prop_archetype not in _SMITHY_PROPS_ARCHETYPES:
            import sys
            print(
                f"[prop_archetype] WARN: unknown {prop_archetype!r}; "
                f"falling back to {_SMITHY_PROPS_ARCHETYPES[0]!r}. "
                f"Valid: {_SMITHY_PROPS_ARCHETYPES}",
                file=sys.stderr,
            )
            prop_archetype = _SMITHY_PROPS_ARCHETYPES[0]
        self.prop_archetype = prop_archetype
        self.wood_color = wood_color or "wood"
        self.metal_color = metal_color or "rust_metal"
        self.stone_color = stone_color or "rock_cool"
        self.coal_color = coal_color or "rock_shadow"

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolySmithyProps({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        rng = random.Random(int(self.factory_seed) + 73219)
        builders = {
            "anvil": self._build_anvil,
            "quench_trough": self._build_quench_trough,
            "grindstone": self._build_grindstone,
            "tool_rack": self._build_tool_rack,
            "coal_pile": self._build_coal_pile,
        }
        return builders[self.prop_archetype](rng)

    def _finalize(
        self, bm: bmesh.types.BMesh, slot_ranges: list[tuple[int, int, int]]
    ) -> bpy.types.Object:
        me = bpy.data.meshes.new(f"LowPolySmithyProps({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()
        obj = bpy.data.objects.new(
            f"LowPolySmithyProps({self.factory_seed})_{self.prop_archetype}", me
        )
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
            [self.wood_color, self.metal_color, self.stone_color, self.coal_color],
        )
        return obj

    def _add_water_child(
        self,
        parent: bpy.types.Object,
        *,
        sx: float,
        sy: float,
        sz: float,
        z0: float,
    ) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        _add_box(bm, cx=0.0, cy=0.0, z0=z0, sx=sx, sy=sy, sz=sz, slot=0, slot_ranges=sr)
        me = bpy.data.meshes.new(f"LowPolySmithyProps({self.factory_seed})_WaterMesh")
        bm.to_mesh(me)
        bm.free()
        water = bpy.data.objects.new(
            f"LowPolySmithyProps({self.factory_seed})_Water", me
        )
        bpy.context.scene.collection.objects.link(water)
        water.parent = parent
        for poly in water.data.polygons:
            poly.use_smooth = False
        apply_water_material(water)
        return water

    # -- archetype builders ------------------------------------------------

    def _build_anvil(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        stump_r = 0.30 * rng.uniform(0.92, 1.10)
        stump_h = 0.44 * rng.uniform(0.90, 1.12)
        _add_prism(
            bm,
            center=(0.0, 0.0, 0.0),
            radius=stump_r,
            height=stump_h,
            n_sides=8,
            slot=0,
            slot_ranges=sr,
            scale_y=rng.uniform(0.9, 1.0),
            rot_z=rng.uniform(0.0, math.pi),
        )
        foot_z = stump_h - 0.03
        _add_box(bm, cx=0.0, cy=0.0, z0=foot_z, sx=0.50, sy=0.27, sz=0.10,
                 slot=1, slot_ranges=sr)
        waist_z = foot_z + 0.10 - 0.03
        _add_box(bm, cx=0.0, cy=0.0, z0=waist_z, sx=0.30, sy=0.20, sz=0.15,
                 slot=1, slot_ranges=sr)
        body_len = 0.62 * rng.uniform(0.95, 1.12)
        body_h = 0.16
        body_z = waist_z + 0.15 - 0.03
        _add_box(bm, cx=0.0, cy=0.0, z0=body_z, sx=body_len, sy=0.22, sz=body_h,
                 slot=1, slot_ranges=sr)
        horn_len = 0.30 * rng.uniform(0.85, 1.20)
        _add_horn(
            bm,
            base_x=body_len * 0.5 - 0.03,
            tip_x=body_len * 0.5 + horn_len,
            cy=0.0,
            cz=body_z + body_h * 0.5,
            base_w=0.16,
            base_h=0.13,
            slot=1,
            slot_ranges=sr,
        )
        return self._finalize(bm, sr)

    def _build_quench_trough(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        outer_x, outer_y = 0.92, 0.46
        wall_t = 0.09
        leg_h = 0.18 * rng.uniform(0.85, 1.15)
        for sx_sign in (-1.0, 1.0):
            for sy_sign in (-1.0, 1.0):
                _add_box(
                    bm,
                    cx=sx_sign * (outer_x * 0.5 - 0.10),
                    cy=sy_sign * (outer_y * 0.5 - 0.10),
                    z0=0.0,
                    sx=0.09,
                    sy=0.09,
                    sz=leg_h,
                    slot=0,
                    slot_ranges=sr,
                )
        floor_z = leg_h - 0.03
        _add_box(bm, cx=0.0, cy=0.0, z0=floor_z, sx=outer_x, sy=outer_y, sz=0.10,
                 slot=0, slot_ranges=sr)
        wall_z = floor_z + 0.10 - 0.05
        wall_h = 0.34
        for sy_sign in (-1.0, 1.0):
            _add_box(
                bm,
                cx=0.0,
                cy=sy_sign * (outer_y * 0.5 - wall_t * 0.5),
                z0=wall_z,
                sx=outer_x,
                sy=wall_t,
                sz=wall_h,
                slot=0,
                slot_ranges=sr,
            )
        inner_y = outer_y - 2.0 * wall_t
        for sx_sign in (-1.0, 1.0):
            _add_box(
                bm,
                cx=sx_sign * (outer_x * 0.5 - wall_t * 0.5),
                cy=0.0,
                z0=wall_z,
                sx=wall_t,
                sy=inner_y,
                sz=wall_h,
                slot=0,
                slot_ranges=sr,
            )
        trough = self._finalize(bm, sr)
        floor_top = floor_z + 0.10
        rim_z = wall_z + wall_h
        water_z0 = floor_top - 0.02
        water_sz = (rim_z - 0.10) - water_z0
        self._add_water_child(
            trough,
            sx=outer_x - 2.0 * wall_t - 0.04,
            sy=inner_y - 0.04,
            sz=water_sz,
            z0=water_z0,
        )
        return trough

    def _build_grindstone(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        _add_box(bm, cx=0.0, cy=0.0, z0=0.0, sx=0.66, sy=0.30, sz=0.12,
                 slot=0, slot_ranges=sr)
        post_z = 0.12 - 0.03
        post_h = 0.50
        for sx_sign in (-1.0, 1.0):
            _add_box(bm, cx=sx_sign * 0.25, cy=0.0, z0=post_z, sx=0.10, sy=0.13,
                     sz=post_h, slot=0, slot_ranges=sr)
        hub_z = post_z + post_h * 0.92
        wheel_r = 0.32 * rng.uniform(0.92, 1.10)
        _add_wheel(bm, cx=0.0, cy=0.0, cz=hub_z, radius=wheel_r, thickness=0.09,
                   n_sides=16, slot=2, slot_ranges=sr)
        _add_wheel(bm, cx=0.0, cy=0.0, cz=hub_z, radius=0.04, thickness=0.62,
                   n_sides=6, slot=1, slot_ranges=sr)
        # hand crank on the +X side
        _add_box(bm, cx=0.34, cy=0.0, z0=hub_z, sx=0.05, sy=0.05, sz=0.17,
                 slot=1, slot_ranges=sr)
        _add_box(bm, cx=0.34, cy=0.09, z0=hub_z + 0.14, sx=0.05, sy=0.16, sz=0.05,
                 slot=1, slot_ranges=sr)
        return self._finalize(bm, sr)

    def _build_tool_rack(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        _add_box(bm, cx=0.0, cy=0.0, z0=0.0, sx=0.78, sy=0.22, sz=0.10,
                 slot=0, slot_ranges=sr)
        post_z = 0.10 - 0.03
        post_h = 1.00
        for sx_sign in (-1.0, 1.0):
            _add_box(bm, cx=sx_sign * 0.33, cy=0.0, z0=post_z, sx=0.09, sy=0.09,
                     sz=post_h, slot=0, slot_ranges=sr)
        post_top = post_z + post_h
        crossbar_z = post_top - 0.06
        _add_box(bm, cx=0.0, cy=0.0, z0=crossbar_z, sx=0.78, sy=0.10, sz=0.10,
                 slot=0, slot_ranges=sr)
        _add_box(bm, cx=0.0, cy=0.0, z0=0.52, sx=0.74, sy=0.12, sz=0.06,
                 slot=0, slot_ranges=sr)
        # hammer — wooden handle, metal head resting over the crossbar
        _add_box(bm, cx=-0.22, cy=0.0, z0=crossbar_z - 0.40, sx=0.05, sy=0.05,
                 sz=0.44, slot=0, slot_ranges=sr)
        _add_box(bm, cx=-0.22, cy=0.0, z0=crossbar_z - 0.02, sx=0.18, sy=0.10,
                 sz=0.12, slot=1, slot_ranges=sr)
        # tongs — a closed pair of pincers hanging from the crossbar
        for off in (-0.045, 0.045):
            _add_box(bm, cx=0.02 + off, cy=0.0, z0=crossbar_z - 0.42, sx=0.04,
                     sy=0.04, sz=0.40, slot=1, slot_ranges=sr)
        _add_box(bm, cx=0.02, cy=0.0, z0=crossbar_z - 0.06, sx=0.14, sy=0.05,
                 sz=0.06, slot=1, slot_ranges=sr)
        # poker rod with a small bent handle
        _add_box(bm, cx=0.27, cy=0.0, z0=crossbar_z - 0.52, sx=0.035, sy=0.035,
                 sz=0.52, slot=1, slot_ranges=sr)
        _add_box(bm, cx=0.27, cy=0.0, z0=crossbar_z - 0.04, sx=0.10, sy=0.05,
                 sz=0.05, slot=1, slot_ranges=sr)
        return self._finalize(bm, sr)

    def _build_coal_pile(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        _add_prism(
            bm,
            center=(0.0, 0.0, 0.0),
            radius=0.50,
            height=0.13,
            n_sides=8,
            slot=3,
            slot_ranges=sr,
            scale_y=rng.uniform(0.82, 0.98),
            rot_z=rng.uniform(0.0, math.pi),
        )
        for _ in range(rng.randint(17, 25)):
            t = rng.random()
            z = 0.09 + t * 0.40
            max_r = 0.46 * (1.0 - t * 0.80)
            a = rng.uniform(0.0, 2.0 * math.pi)
            rr = max_r * math.sqrt(rng.random())
            _add_prism(
                bm,
                center=(rr * math.cos(a), rr * math.sin(a) * 0.9, z),
                radius=rng.uniform(0.06, 0.13),
                height=rng.uniform(0.06, 0.15),
                n_sides=rng.choice((5, 6)),
                slot=3,
                slot_ranges=sr,
                scale_y=rng.uniform(0.7, 1.1),
                rot_z=rng.uniform(0.0, math.pi),
            )
        for _ in range(rng.randint(3, 5)):
            a = rng.uniform(0.0, 2.0 * math.pi)
            rr = rng.uniform(0.48, 0.64)
            _add_prism(
                bm,
                center=(rr * math.cos(a), rr * math.sin(a) * 0.9, 0.02),
                radius=rng.uniform(0.05, 0.09),
                height=rng.uniform(0.05, 0.10),
                n_sides=rng.choice((5, 6)),
                slot=3,
                slot_ranges=sr,
                scale_y=rng.uniform(0.7, 1.0),
                rot_z=rng.uniform(0.0, math.pi),
            )
        return self._finalize(bm, sr)

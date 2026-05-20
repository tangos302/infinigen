"""LowPolyLavaFactory — molten lava features for the volcanic biome.

The volcanic biome (Songe terrain detects `volcanic / lava / crater /
caldera / magma ...`) had no assets at all. This is the glowing half of
the volcanic kit; LowPolyVolcanicRockFactory supplies the cooled rock.

Every archetype pairs an emissive molten surface with dark cooled
crust and a parented point light. The molten surface emits at LOW
strength — it is a large area, and a high strength blows it out to a
white blob (learned from the forge coal bed). The point light, not the
emission, carries the cast glow.

Archetypes:
  lava_pool    — a molten pool ringed by chunky cooled-crust rocks,
                 with a couple of dark crust islands adrift on it
  lava_crack   — a glowing field broken by dark rock plates; the lava
                 shows through the gaps as jagged rifts
  cooled_flow  — a low domed flow, mostly dark crust plates with thin
                 glowing seams between them
  fumarole     — a dark spatter / vent cone with a glowing throat and
                 a little glowing spatter on the rim

Material slots:
  slot 0 = cooled crust rock (dark)
  slot 1 = molten lava (emissive)
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


_LAVA_ARCHETYPES = ("lava_pool", "lava_crack", "cooled_flow", "fumarole")

_ARCHETYPE_DEFAULTS = {
    "lava_pool": dict(light_energy=175.0, light_radius=2.6, emission_strength=2.0),
    "lava_crack": dict(light_energy=150.0, light_radius=2.4, emission_strength=2.2),
    "cooled_flow": dict(light_energy=130.0, light_radius=2.2, emission_strength=2.2),
    "fumarole": dict(light_energy=110.0, light_radius=1.9, emission_strength=2.6),
}


def _face_count(bm: bmesh.types.BMesh) -> int:
    return len(bm.faces)


def _add_irregular_disc(
    bm: bmesh.types.BMesh,
    *,
    cx: float,
    cy: float,
    z0: float,
    radius: float,
    n_sides: int,
    thickness: float,
    dome_height: float,
    jitter: float,
    slot: int,
    slot_ranges: list[tuple[int, int, int]],
    rng: random.Random,
) -> None:
    """A thin irregular disc slab — flat (dome_height 0) or domed. Used for
    the molten surfaces; the thickness keeps it a body, never a flat plane."""
    start = _face_count(bm)
    rim_top = []
    rim_bot = []
    for i in range(n_sides):
        a = 2.0 * math.pi * i / n_sides
        r = radius * (1.0 + rng.uniform(-jitter, jitter))
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        rim_bot.append(bm.verts.new((x, y, z0)))
        rim_top.append(
            bm.verts.new((x, y, z0 + thickness + rng.uniform(-thickness * 0.2, thickness * 0.2)))
        )
    center = bm.verts.new(
        (cx + rng.uniform(-0.12, 0.12), cy + rng.uniform(-0.12, 0.12), z0 + thickness + dome_height)
    )
    bm.verts.ensure_lookup_table()
    for i in range(n_sides):
        ni = (i + 1) % n_sides
        bm.faces.new((rim_top[i], rim_top[ni], center))
    for i in range(n_sides):
        ni = (i + 1) % n_sides
        bm.faces.new((rim_bot[i], rim_bot[ni], rim_top[ni], rim_top[i]))
    bm.faces.new(tuple(reversed(rim_bot)))
    slot_ranges.append((start, _face_count(bm), int(slot)))


def _add_rock_chunk(
    bm: bmesh.types.BMesh,
    *,
    cx: float,
    cy: float,
    z0: float,
    radius: float,
    height: float,
    n_sides: int,
    slot: int,
    slot_ranges: list[tuple[int, int, int]],
    rng: random.Random,
    rot_z: float = 0.0,
) -> None:
    """An irregular angular rock — jittered radius and top height per vert."""
    start = _face_count(bm)
    rot = Matrix.Rotation(float(rot_z), 4, "Z")
    bot = []
    top = []
    for i in range(n_sides):
        a = 2.0 * math.pi * i / n_sides
        rb = radius * (1.0 + rng.uniform(-0.32, 0.32))
        rt = rb * rng.uniform(0.5, 0.9)
        lb = rot @ Vector((rb * math.cos(a), rb * math.sin(a), 0.0))
        lt = rot @ Vector((rt * math.cos(a), rt * math.sin(a), 0.0))
        bot.append(bm.verts.new((cx + lb.x, cy + lb.y, z0)))
        top.append(bm.verts.new((cx + lt.x, cy + lt.y, z0 + height * rng.uniform(0.62, 1.2))))
    bm.verts.ensure_lookup_table()
    for i in range(n_sides):
        ni = (i + 1) % n_sides
        bm.faces.new((bot[i], bot[ni], top[ni], top[i]))
    bm.faces.new(tuple(reversed(bot)))
    bm.faces.new(tuple(top))
    slot_ranges.append((start, _face_count(bm), int(slot)))


def _add_cone(
    bm: bmesh.types.BMesh,
    *,
    cx: float,
    cy: float,
    z0: float,
    base_radius: float,
    top_radius: float,
    height: float,
    n_sides: int,
    cap_top: bool,
    slot: int,
    slot_ranges: list[tuple[int, int, int]],
    rng: random.Random,
) -> None:
    """A rough truncated cone — the fumarole vent (left open at the top)."""
    start = _face_count(bm)
    bot = []
    top = []
    for i in range(n_sides):
        a = 2.0 * math.pi * i / n_sides
        rb = base_radius * (1.0 + rng.uniform(-0.12, 0.12))
        rt = top_radius * (1.0 + rng.uniform(-0.18, 0.18))
        bot.append(bm.verts.new((cx + rb * math.cos(a), cy + rb * math.sin(a), z0)))
        top.append(
            bm.verts.new(
                (cx + rt * math.cos(a), cy + rt * math.sin(a), z0 + height * rng.uniform(0.93, 1.07))
            )
        )
    bm.verts.ensure_lookup_table()
    for i in range(n_sides):
        ni = (i + 1) % n_sides
        bm.faces.new((bot[i], bot[ni], top[ni], top[i]))
    bm.faces.new(tuple(reversed(bot)))
    if cap_top:
        bm.faces.new(tuple(top))
    slot_ranges.append((start, _face_count(bm), int(slot)))


class LowPolyLavaFactory(AssetFactory):
    """Molten lava features — pools, rifts, flows, fumaroles.

    Constructor knobs:
        factory_seed
        lava_archetype : "lava_pool" | "lava_crack" | "cooled_flow" | "fumarole"
        crust_color, lava_color
        emit_light, light_energy, light_radius, emission_strength
    """

    def __init__(
        self,
        factory_seed,
        lava_archetype: str = "lava_pool",
        crust_color: str | None = None,
        lava_color: str | None = None,
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
            accept_unused_kwargs("LowPolyLavaFactory", _unused_kwargs)
        if lava_archetype not in _LAVA_ARCHETYPES:
            import sys
            print(
                f"[lava_archetype] WARN: unknown {lava_archetype!r}; "
                f"falling back to {_LAVA_ARCHETYPES[0]!r}. Valid: {_LAVA_ARCHETYPES}",
                file=sys.stderr,
            )
            lava_archetype = _LAVA_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[lava_archetype]
        self.lava_archetype = lava_archetype
        # Deep saturated red holds its colour; a light amber washes out to
        # pale cream once the emission is bright enough to read as hot. The
        # near-black crust gives the molten lava something to glow against.
        self.crust_color = crust_color or "rust_metal"
        self.lava_color = lava_color or "accent_red"
        self.emit_light = bool(emit_light)
        self.light_energy = float(light_energy if light_energy is not None else d["light_energy"])
        self.light_radius = float(light_radius if light_radius is not None else d["light_radius"])
        self.emission_strength = float(
            emission_strength if emission_strength is not None else d["emission_strength"]
        )

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(f"LowPolyLava({self.factory_seed})_placeholder", None)
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        rng = random.Random(int(self.factory_seed) + 88243)
        builders = {
            "lava_pool": self._build_lava_pool,
            "lava_crack": self._build_lava_crack,
            "cooled_flow": self._build_cooled_flow,
            "fumarole": self._build_fumarole,
        }
        return builders[self.lava_archetype](rng)

    def _finalize(
        self,
        bm: bmesh.types.BMesh,
        slot_ranges: list[tuple[int, int, int]],
        light_z: float,
    ) -> bpy.types.Object:
        me = bpy.data.meshes.new(f"LowPolyLava({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()
        obj = bpy.data.objects.new(
            f"LowPolyLava({self.factory_seed})_{self.lava_archetype}", me
        )
        bpy.context.scene.collection.objects.link(obj)
        while len(obj.data.materials) < 2:
            obj.data.materials.append(None)
        for start, end, slot in slot_ranges:
            for face_idx in range(start, end):
                obj.data.polygons[face_idx].material_index = slot
        for poly in obj.data.polygons:
            poly.use_smooth = False
        apply_palette_slots(obj, [self.crust_color, self.lava_color])
        apply_emission_palette_slot(obj, 1, self.lava_color, strength=self.emission_strength)
        if self.emit_light:
            add_palette_point_light(
                name=f"{obj.name}_PointLight",
                location=(0.0, 0.0, light_z),
                palette_key=self.lava_color,
                energy=self.light_energy,
                radius=self.light_radius,
                parent=obj,
            )
        return obj

    # -- archetype builders ------------------------------------------------

    def _build_lava_pool(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        radius = rng.uniform(1.6, 2.4)
        thickness = 0.16
        _add_irregular_disc(
            bm, cx=0.0, cy=0.0, z0=0.0, radius=radius, n_sides=14,
            thickness=thickness, dome_height=0.0, jitter=0.16,
            slot=1, slot_ranges=sr, rng=rng,
        )
        n_rim = rng.randint(11, 16)
        for i in range(n_rim):
            a = 2.0 * math.pi * i / n_rim + rng.uniform(-0.18, 0.18)
            rr = radius * rng.uniform(0.92, 1.07)
            _add_rock_chunk(
                bm, cx=rr * math.cos(a), cy=rr * math.sin(a), z0=-0.05,
                radius=rng.uniform(0.28, 0.50), height=rng.uniform(0.30, 0.62),
                n_sides=rng.choice((5, 6)), slot=0, slot_ranges=sr, rng=rng,
                rot_z=rng.uniform(0.0, math.pi),
            )
        # dark cooled-crust floes adrift on the molten surface — they break
        # the bright lava into glowing channels so it reads as molten rather
        # than as one flat blown-out disc
        for _ in range(rng.randint(6, 10)):
            a = rng.uniform(0.0, 2.0 * math.pi)
            rr = radius * math.sqrt(rng.uniform(0.0, 1.0)) * 0.74
            _add_rock_chunk(
                bm, cx=rr * math.cos(a), cy=rr * math.sin(a), z0=thickness * 0.5,
                radius=rng.uniform(0.34, 0.66), height=rng.uniform(0.12, 0.22),
                n_sides=rng.choice((5, 6)), slot=0, slot_ranges=sr, rng=rng,
                rot_z=rng.uniform(0.0, math.pi),
            )
        return self._finalize(bm, sr, light_z=1.05)

    def _build_lava_crack(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        radius = rng.uniform(1.9, 2.7)
        thickness = 0.14
        _add_irregular_disc(
            bm, cx=0.0, cy=0.0, z0=0.0, radius=radius, n_sides=16,
            thickness=thickness, dome_height=0.0, jitter=0.24,
            slot=1, slot_ranges=sr, rng=rng,
        )
        for _ in range(rng.randint(5, 8)):
            a = rng.uniform(0.0, 2.0 * math.pi)
            rr = radius * rng.uniform(0.0, 0.62)
            _add_rock_chunk(
                bm, cx=rr * math.cos(a), cy=rr * math.sin(a), z0=thickness * 0.6,
                radius=rng.uniform(0.55, 0.95), height=rng.uniform(0.14, 0.26),
                n_sides=rng.choice((5, 6, 7)), slot=0, slot_ranges=sr, rng=rng,
                rot_z=rng.uniform(0.0, math.pi),
            )
        return self._finalize(bm, sr, light_z=0.95)

    def _build_cooled_flow(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        radius = rng.uniform(1.5, 2.2)
        thickness = 0.16
        dome = rng.uniform(0.38, 0.62)
        _add_irregular_disc(
            bm, cx=0.0, cy=0.0, z0=0.0, radius=radius, n_sides=14,
            thickness=thickness, dome_height=dome, jitter=0.18,
            slot=1, slot_ranges=sr, rng=rng,
        )
        for _ in range(rng.randint(9, 14)):
            a = rng.uniform(0.0, 2.0 * math.pi)
            rr = radius * math.sqrt(rng.uniform(0.0, 1.0)) * 0.92
            dome_z = thickness + dome * (1.0 - (rr / radius) ** 2)
            _add_rock_chunk(
                bm, cx=rr * math.cos(a), cy=rr * math.sin(a), z0=dome_z - 0.07,
                radius=rng.uniform(0.34, 0.58), height=rng.uniform(0.10, 0.20),
                n_sides=rng.choice((5, 6)), slot=0, slot_ranges=sr, rng=rng,
                rot_z=rng.uniform(0.0, math.pi),
            )
        return self._finalize(bm, sr, light_z=thickness + dome + 0.6)

    def _build_fumarole(self, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        sr: list[tuple[int, int, int]] = []
        base_r = rng.uniform(0.95, 1.40)
        top_r = rng.uniform(0.32, 0.50)
        height = rng.uniform(1.0, 1.6)
        _add_cone(
            bm, cx=0.0, cy=0.0, z0=0.0, base_radius=base_r, top_radius=top_r,
            height=height, n_sides=9, cap_top=False, slot=0, slot_ranges=sr, rng=rng,
        )
        _add_irregular_disc(
            bm, cx=0.0, cy=0.0, z0=height * 0.74, radius=top_r * 0.82, n_sides=8,
            thickness=0.08, dome_height=0.0, jitter=0.2, slot=1, slot_ranges=sr, rng=rng,
        )
        for _ in range(rng.randint(3, 5)):
            a = rng.uniform(0.0, 2.0 * math.pi)
            rr = top_r * rng.uniform(0.95, 1.30)
            _add_rock_chunk(
                bm, cx=rr * math.cos(a), cy=rr * math.sin(a), z0=height * 0.86,
                radius=rng.uniform(0.07, 0.14), height=rng.uniform(0.06, 0.13),
                n_sides=5, slot=1, slot_ranges=sr, rng=rng, rot_z=rng.uniform(0.0, math.pi),
            )
        return self._finalize(bm, sr, light_z=height + 0.2)

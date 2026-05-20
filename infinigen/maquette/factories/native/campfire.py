"""LowPolyCampfireFactory — fire ring / travel camp light source.

Small but high-value storytelling prop for campsites, caravan stops,
ruins, forest clearings, and night scenes. Unlike the original lantern
mesh this factory emits both a visible flame material and a real point
light parented to the mesh.

Archetypes:
  stone_ring   — classic ring of stones, crossed logs, central flame
  log_pile     — fewer stones, heavier crossed logs
  ember_bed    — low glowing coals, subtle light for abandoned camps

Material slots:
  slot 0 = stones / ash
  slot 1 = logs
  slot 2 = flame / ember glow
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


_CAMPFIRE_ARCHETYPES = ("stone_ring", "log_pile", "ember_bed")


_ARCHETYPE_DEFAULTS = {
    "stone_ring": dict(
        base_archetype="campfire_stones",
        radius=0.78,
        stone_count=10,
        log_count=3,
        flame_height=0.46,
        flame_radius=0.16,
        stone_color="rock_pale",
        log_color="wood",
        flame_color="foliage_amber",
        light_energy=115.0,
        light_radius=2.15,
        emission_strength=4.4,
    ),
    "log_pile": dict(
        base_archetype="campfire_logs",
        radius=0.68,
        stone_count=6,
        log_count=4,
        flame_height=0.54,
        flame_radius=0.18,
        stone_color="rock_warm",
        log_color="wood",
        flame_color="foliage_lemon",
        light_energy=140.0,
        light_radius=2.35,
        emission_strength=4.8,
    ),
    "ember_bed": dict(
        base_archetype="campfire_bricks",
        radius=0.62,
        stone_count=8,
        log_count=2,
        flame_height=0.16,
        flame_radius=0.26,
        stone_color="rock_shadow",
        log_color="wood",
        flame_color="accent_red",
        light_energy=55.0,
        light_radius=1.45,
        emission_strength=3.2,
    ),
}


def _face_count(bm: bmesh.types.BMesh) -> int:
    return len(bm.faces)


def _add_prism(
    bm: bmesh.types.BMesh,
    *,
    center: tuple[float, float, float],
    radius: float,
    height: float,
    n_sides: int,
    slot_ranges: list[tuple[int, int, int]],
    slot: int,
    scale_y: float = 1.0,
    rot_z: float = 0.0,
) -> None:
    start = _face_count(bm)
    cx, cy, cz = center
    bottom = []
    top = []
    rot = Matrix.Rotation(float(rot_z), 4, "Z")
    for i in range(int(n_sides)):
        a = 2.0 * math.pi * i / int(n_sides)
        local = Vector((radius * math.cos(a), radius * scale_y * math.sin(a), 0.0))
        p = Vector((cx, cy, cz)) + (rot @ local)
        bottom.append(bm.verts.new((p.x, p.y, p.z)))
        top.append(bm.verts.new((p.x, p.y, p.z + height)))
    bm.verts.ensure_lookup_table()
    for i in range(int(n_sides)):
        ni = (i + 1) % int(n_sides)
        bm.faces.new((bottom[i], bottom[ni], top[ni], top[i]))
    bm.faces.new(list(reversed(bottom)))
    bm.faces.new(top)
    slot_ranges.append((start, _face_count(bm), int(slot)))


def _add_log(
    bm: bmesh.types.BMesh,
    *,
    length: float,
    radius: float,
    z: float,
    rot_z: float,
    slot_ranges: list[tuple[int, int, int]],
) -> None:
    # A log is an 8-sided prism laid sideways, then rotated around Z.
    start = _face_count(bm)
    n_sides = 8
    half = length * 0.5
    rings: list[list[bmesh.types.BMVert]] = []
    rot = Matrix.Rotation(float(rot_z), 4, "Z")
    for x in (-half, half):
        ring = []
        for i in range(n_sides):
            a = 2.0 * math.pi * i / n_sides
            local = Vector((x, radius * math.cos(a), z + radius * math.sin(a)))
            p = rot @ local
            ring.append(bm.verts.new((p.x, p.y, p.z)))
        rings.append(ring)
    bm.verts.ensure_lookup_table()
    a_ring, b_ring = rings
    for i in range(n_sides):
        ni = (i + 1) % n_sides
        bm.faces.new((a_ring[i], a_ring[ni], b_ring[ni], b_ring[i]))
    bm.faces.new(list(reversed(a_ring)))
    bm.faces.new(b_ring)
    slot_ranges.append((start, _face_count(bm), 1))


def _add_flame(
    bm: bmesh.types.BMesh,
    *,
    radius: float,
    height: float,
    slot_ranges: list[tuple[int, int, int]],
    rng: random.Random,
) -> None:
    start = _face_count(bm)
    n_sides = 6
    ring = []
    for i in range(n_sides):
        a = 2.0 * math.pi * i / n_sides
        r = radius * rng.uniform(0.78, 1.12)
        ring.append(bm.verts.new((r * math.cos(a), r * math.sin(a), 0.18)))
    apex = bm.verts.new((rng.uniform(-0.06, 0.06), rng.uniform(-0.06, 0.06), height))
    bm.verts.ensure_lookup_table()
    for i in range(n_sides):
        ni = (i + 1) % n_sides
        bm.faces.new((ring[i], ring[ni], apex))
    slot_ranges.append((start, _face_count(bm), 2))


class LowPolyCampfireFactory(AssetFactory):
    """A compact fire prop with a real point light.

    Constructor knobs:
        factory_seed
        campfire_archetype : "stone_ring" | "log_pile" | "ember_bed"
        radius, stone_count, log_count
        flame_height, flame_radius
        stone_color, log_color, flame_color
        emit_light, light_energy, light_radius, emission_strength
    """

    def __init__(
        self,
        factory_seed,
        campfire_archetype: str = "stone_ring",
        radius: float | None = None,
        stone_count: int | None = None,
        log_count: int | None = None,
        flame_height: float | None = None,
        flame_radius: float | None = None,
        stone_color: str | None = None,
        log_color: str | None = None,
        flame_color: str | None = None,
        emit_light: bool = True,
        light_energy: float | None = None,
        light_radius: float | None = None,
        emission_strength: float | None = None,
        use_loaded_base: bool = True,
        base_archetype: str | None = None,
        coarse: bool = False,
        **_unused_kwargs,
    ) -> None:
        super().__init__(factory_seed, coarse=coarse)
        if _unused_kwargs:
            from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
            accept_unused_kwargs("LowPolyCampfireFactory", _unused_kwargs)
        if campfire_archetype not in _CAMPFIRE_ARCHETYPES:
            import sys
            print(
                f"[campfire_archetype] WARN: unknown {campfire_archetype!r}; "
                f"falling back to {_CAMPFIRE_ARCHETYPES[0]!r}. "
                f"Valid: {_CAMPFIRE_ARCHETYPES}",
                file=sys.stderr,
            )
            campfire_archetype = _CAMPFIRE_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[campfire_archetype]
        self.campfire_archetype = campfire_archetype
        self.base_archetype = base_archetype or d["base_archetype"]
        self.radius = float(radius if radius is not None else d["radius"])
        self.stone_count = int(stone_count if stone_count is not None else d["stone_count"])
        self.log_count = int(log_count if log_count is not None else d["log_count"])
        self.flame_height = float(flame_height if flame_height is not None else d["flame_height"])
        self.flame_radius = float(flame_radius if flame_radius is not None else d["flame_radius"])
        self.stone_color = stone_color or d["stone_color"]
        self.log_color = log_color or d["log_color"]
        self.flame_color = flame_color or d["flame_color"]
        self.emit_light = bool(emit_light)
        self.light_energy = float(light_energy if light_energy is not None else d["light_energy"])
        self.light_radius = float(light_radius if light_radius is not None else d["light_radius"])
        self.emission_strength = float(
            emission_strength if emission_strength is not None else d["emission_strength"]
        )
        self.use_loaded_base = bool(use_loaded_base)

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyCampfire({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _make_flame_child(self, parent: bpy.types.Object, rng: random.Random) -> bpy.types.Object:
        bm = bmesh.new()
        slot_ranges: list[tuple[int, int, int]] = []
        _add_flame(
            bm,
            radius=self.flame_radius,
            height=self.flame_height,
            slot_ranges=slot_ranges,
            rng=rng,
        )
        me = bpy.data.meshes.new(f"LowPolyCampfire({self.factory_seed})_FlameMesh")
        bm.to_mesh(me)
        bm.free()
        flame = bpy.data.objects.new(f"LowPolyCampfire({self.factory_seed})_Flame", me)
        bpy.context.scene.collection.objects.link(flame)
        flame.parent = parent
        flame.location = (0.0, 0.0, 0.02)
        while len(flame.data.materials) < 1:
            flame.data.materials.append(None)
        for poly in flame.data.polygons:
            poly.material_index = 0
            poly.use_smooth = False
        apply_palette_slots(flame, [self.flame_color])
        apply_emission_palette_slot(
            flame,
            0,
            self.flame_color,
            strength=self.emission_strength,
        )
        return flame

    def _build_loaded(self, rng: random.Random) -> bpy.types.Object | None:
        try:
            from infinigen.maquette.runtime.loaded_factory import LoadedNatureFactory
            base = LoadedNatureFactory(
                archetype=self.base_archetype,
                factory_seed=int(self.factory_seed),
                scale=max(2.4, self.radius * 3.5),
                scale_jitter=0.06,
                xy_jitter=0.04,
                z_jitter=0.02,
            ).spawn_asset(i=0, loc=(0.0, 0.0, 0.0))
        except Exception:
            return None
        try:
            scale = base.scale.copy()
            base.data.transform(Matrix.Diagonal((scale.x, scale.y, scale.z, 1.0)))
            base.scale = (1.0, 1.0, 1.0)
        except Exception:
            pass
        base.name = f"LowPolyCampfire({self.factory_seed})"
        base.hide_render = False
        base.hide_viewport = False
        self._make_flame_child(base, rng)
        if self.emit_light:
            add_palette_point_light(
                name=f"{base.name}_PointLight",
                location=(0.0, 0.0, max(0.22, self.flame_height * 0.55)),
                palette_key=self.flame_color,
                energy=self.light_energy,
                radius=self.light_radius,
                parent=base,
            )
        return base

    def _build(self) -> bpy.types.Object:
        rng = random.Random(int(self.factory_seed) + 27103)
        if self.use_loaded_base:
            loaded = self._build_loaded(rng)
            if loaded is not None:
                return loaded

        bm = bmesh.new()
        slot_ranges: list[tuple[int, int, int]] = []

        for i in range(max(0, self.stone_count)):
            a = 2.0 * math.pi * i / max(1, self.stone_count)
            r = self.radius * rng.uniform(0.88, 1.08)
            _add_prism(
                bm,
                center=(r * math.cos(a), r * math.sin(a), 0.0),
                radius=rng.uniform(0.08, 0.14),
                height=rng.uniform(0.08, 0.16),
                n_sides=6,
                slot_ranges=slot_ranges,
                slot=0,
                scale_y=rng.uniform(0.65, 1.05),
                rot_z=a + rng.uniform(-0.25, 0.25),
            )

        for i in range(max(0, self.log_count)):
            _add_log(
                bm,
                length=self.radius * rng.uniform(1.05, 1.55),
                radius=rng.uniform(0.055, 0.085),
                z=rng.uniform(0.08, 0.16) + i * 0.015,
                rot_z=2.0 * math.pi * i / max(1, self.log_count) + rng.uniform(-0.18, 0.18),
                slot_ranges=slot_ranges,
            )

        _add_flame(
            bm,
            radius=self.flame_radius,
            height=self.flame_height,
            slot_ranges=slot_ranges,
            rng=rng,
        )

        me = bpy.data.meshes.new(f"LowPolyCampfire({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(f"LowPolyCampfire({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)
        while len(obj.data.materials) < 3:
            obj.data.materials.append(None)
        for start, end, slot in slot_ranges:
            for face_idx in range(start, end):
                obj.data.polygons[face_idx].material_index = slot
        for poly in obj.data.polygons:
            poly.use_smooth = False

        apply_palette_slots(obj, [self.stone_color, self.log_color, self.flame_color])
        apply_emission_palette_slot(
            obj,
            2,
            self.flame_color,
            strength=self.emission_strength,
        )
        if self.emit_light:
            add_palette_point_light(
                name=f"{obj.name}_PointLight",
                location=(0.0, 0.0, max(0.22, self.flame_height * 0.55)),
                palette_key=self.flame_color,
                energy=self.light_energy,
                radius=self.light_radius,
                parent=obj,
            )
        return obj

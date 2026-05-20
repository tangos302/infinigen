"""LowPolyFarmAnimalFactory — livestock silhouettes for villages.

Villages and farm belts look empty when they only have fences and hay.
This factory adds tiny low-poly animals with distinct silhouettes: sheep
as wool blocks, goats with horns, cows with longer bodies, and chickens
as small pecking ground props.

Archetypes:
  sheep    — wooly rectangular body, small dark legs.
  goat     — slim body, horns, raised tail.
  cow      — larger body, head, horns, tail.
  chicken  — small bird body, beak, comb.

Material slots:
  slot 0 = body / wool / hide
  slot 1 = legs / head accent
  slot 2 = horns / beak / tail
"""

from __future__ import annotations

import random

import bmesh
import bpy

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_FARM_ANIMAL_ARCHETYPES = ("sheep", "goat", "cow", "chicken")

_ARCHETYPE_DEFAULTS = {
    "sheep": dict(scale=1.0, body_color="stucco", accent_color="rock_shadow", detail_color="rock_pale"),
    "goat": dict(scale=0.9, body_color="rock_pale", accent_color="rock_shadow", detail_color="wood"),
    "cow": dict(scale=1.25, body_color="rock_warm", accent_color="rock_shadow", detail_color="stucco"),
    "chicken": dict(scale=0.55, body_color="foliage_amber", accent_color="rock_warm", detail_color="accent_red"),
}


def _face_count(bm: bmesh.types.BMesh) -> int:
    return len(bm.faces)


def _add_box(
    bm: bmesh.types.BMesh,
    ranges: list[tuple[int, int, int]],
    slot: int,
    center: tuple[float, float, float],
    size: tuple[float, float, float],
) -> None:
    start = _face_count(bm)
    res = bmesh.ops.create_cube(bm, size=1.0)
    cx, cy, cz = center
    sx, sy, sz = size
    for v in res["verts"]:
        v.co.x = v.co.x * sx + cx
        v.co.y = v.co.y * sy + cy
        v.co.z = v.co.z * sz + cz
    bm.faces.ensure_lookup_table()
    ranges.append((start, _face_count(bm), int(slot)))


class LowPolyFarmAnimalFactory(AssetFactory):
    """Low-poly livestock for farm belts and village outskirts.

    Constructor knobs:
        factory_seed
        animal_archetype : "sheep" | "goat" | "cow" | "chicken"
        scale
        body_color, accent_color, detail_color
    """

    def __init__(
        self,
        factory_seed,
        animal_archetype: str = "sheep",
        scale: float | None = None,
        body_color: str | None = None,
        accent_color: str | None = None,
        detail_color: str | None = None,
        coarse: bool = False,
        **_unused_kwargs,
    ) -> None:
        super().__init__(factory_seed, coarse=coarse)
        if _unused_kwargs:
            from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
            accept_unused_kwargs("LowPolyFarmAnimalFactory", _unused_kwargs)
        if animal_archetype not in _FARM_ANIMAL_ARCHETYPES:
            import sys
            print(
                f"[animal_archetype] WARN: unknown {animal_archetype!r}; "
                f"falling back to {_FARM_ANIMAL_ARCHETYPES[0]!r}. Valid: {_FARM_ANIMAL_ARCHETYPES}",
                file=sys.stderr,
            )
            animal_archetype = _FARM_ANIMAL_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[animal_archetype]
        self.animal_archetype = animal_archetype
        self.scale = float(scale if scale is not None else d["scale"])
        self.body_color = body_color or d["body_color"]
        self.accent_color = accent_color or d["accent_color"]
        self.detail_color = detail_color or d["detail_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(f"LowPolyFarmAnimal({self.factory_seed})_placeholder", None)
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        rng = random.Random(self.factory_seed)
        bm = bmesh.new()
        ranges: list[tuple[int, int, int]] = []
        s = self.scale * rng.uniform(0.92, 1.08)

        if self.animal_archetype == "chicken":
            _add_box(bm, ranges, 0, (0.0, 0.0, 0.32 * s), (0.55 * s, 0.36 * s, 0.40 * s))
            _add_box(bm, ranges, 1, (0.34 * s, 0.0, 0.48 * s), (0.25 * s, 0.25 * s, 0.25 * s))
            _add_box(bm, ranges, 2, (0.52 * s, 0.0, 0.49 * s), (0.16 * s, 0.10 * s, 0.08 * s))
            _add_box(bm, ranges, 2, (0.35 * s, 0.0, 0.66 * s), (0.10 * s, 0.08 * s, 0.13 * s))
            for x in (-0.08, 0.10):
                _add_box(bm, ranges, 1, (x * s, 0.08 * s, 0.12 * s), (0.035 * s, 0.035 * s, 0.24 * s))
            _add_box(bm, ranges, 2, (-0.32 * s, 0.0, 0.43 * s), (0.18 * s, 0.08 * s, 0.20 * s))
        else:
            if self.animal_archetype == "cow":
                body = (1.55 * s, 0.58 * s, 0.72 * s)
                head = (0.40 * s, 0.40 * s, 0.46 * s)
                leg_h = 0.58 * s
            elif self.animal_archetype == "goat":
                body = (1.05 * s, 0.42 * s, 0.54 * s)
                head = (0.34 * s, 0.30 * s, 0.34 * s)
                leg_h = 0.48 * s
            else:
                body = (1.12 * s, 0.58 * s, 0.62 * s)
                head = (0.34 * s, 0.34 * s, 0.34 * s)
                leg_h = 0.38 * s
            _add_box(bm, ranges, 0, (0.0, 0.0, leg_h + body[2] * 0.5), body)
            # Wool lumps for sheep.
            if self.animal_archetype == "sheep":
                for x in (-0.34, 0.0, 0.34):
                    _add_box(
                        bm,
                        ranges,
                        0,
                        (x * s, 0.0, leg_h + body[2] * 0.9),
                        (0.38 * s, 0.62 * s, 0.20 * s),
                    )
            head_x = body[0] * 0.58
            _add_box(bm, ranges, 1, (head_x, 0.0, leg_h + body[2] * 0.66), head)
            for x in (-body[0] * 0.32, body[0] * 0.32):
                for y in (-body[1] * 0.28, body[1] * 0.28):
                    _add_box(bm, ranges, 1, (x, y, leg_h * 0.5), (0.08 * s, 0.08 * s, leg_h))
            if self.animal_archetype in {"goat", "cow"}:
                horn_z = leg_h + body[2] * 0.95
                _add_box(bm, ranges, 2, (head_x + 0.05 * s, -0.18 * s, horn_z), (0.06 * s, 0.24 * s, 0.06 * s))
                _add_box(bm, ranges, 2, (head_x + 0.05 * s, 0.18 * s, horn_z), (0.06 * s, 0.24 * s, 0.06 * s))
            # Tail.
            _add_box(bm, ranges, 2, (-body[0] * 0.58, 0.0, leg_h + body[2] * 0.62), (0.30 * s, 0.06 * s, 0.06 * s))

        me = bpy.data.meshes.new(f"LowPolyFarmAnimal({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()
        obj = bpy.data.objects.new(f"LowPolyFarmAnimal({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)
        while len(obj.data.materials) < 3:
            obj.data.materials.append(None)
        for start, end, slot in ranges:
            for i in range(start, min(end, len(obj.data.polygons))):
                obj.data.polygons[i].material_index = slot
        for p in obj.data.polygons:
            p.use_smooth = False
        apply_palette_slots(obj, [self.body_color, self.accent_color, self.detail_color])
        return obj

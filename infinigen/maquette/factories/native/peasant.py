"""LowPolyPeasantFactory — tiny readable settlement people.

Settlements currently read structurally but not socially: houses, stalls,
and roads exist, yet no one appears to live there. This factory provides
very low-poly human figures that work at Maquette camera distance without
trying to be realistic characters.

Archetypes:
  farmer    — tunic, brim hat, shoulder hoe.
  merchant  — brighter tunic, apron/tablet bundle.
  guard     — helmet, dark tunic, simple spear.
  child     — smaller proportions, no tool.

Material slots:
  slot 0 = clothes
  slot 1 = skin
  slot 2 = hair / hat / tool
"""

from __future__ import annotations

import math
import random

import bmesh
import bpy

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_PEASANT_ARCHETYPES = ("farmer", "merchant", "guard", "child")

_ARCHETYPE_DEFAULTS = {
    "farmer": dict(
        height=1.55,
        body_color="ground_sand",
        skin_color="rock_pale",
        accent_color="wood",
        hat=True,
        tool="hoe",
    ),
    "merchant": dict(
        height=1.50,
        body_color="accent_red",
        skin_color="rock_pale",
        accent_color="stucco",
        hat=False,
        tool="bundle",
    ),
    "guard": dict(
        height=1.62,
        body_color="rock_shadow",
        skin_color="rock_pale",
        accent_color="rust_metal",
        hat=True,
        tool="spear",
    ),
    "child": dict(
        height=1.05,
        body_color="foliage_amber",
        skin_color="rock_pale",
        accent_color="wood",
        hat=False,
        tool="none",
    ),
}


def _face_count(bm: bmesh.types.BMesh) -> int:
    return len(bm.faces)


def _add_box(
    bm: bmesh.types.BMesh,
    slot_ranges: list[tuple[int, int, int]],
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
    slot_ranges.append((start, _face_count(bm), int(slot)))


def _add_cone(
    bm: bmesh.types.BMesh,
    slot_ranges: list[tuple[int, int, int]],
    slot: int,
    *,
    radius1: float,
    radius2: float,
    depth: float,
    location: tuple[float, float, float],
    vertices: int = 8,
) -> None:
    start = _face_count(bm)
    result = bmesh.ops.create_cone(
        bm,
        cap_ends=True,
        cap_tris=False,
        segments=vertices,
        radius1=radius1,
        radius2=radius2,
        depth=depth,
    )
    lx, ly, lz = location
    new_verts = [elem for elem in result.get("verts", ()) if isinstance(elem, bmesh.types.BMVert)]
    for v in new_verts:
        v.co.x += lx
        v.co.y += ly
        v.co.z += lz
    bm.faces.ensure_lookup_table()
    slot_ranges.append((start, _face_count(bm), int(slot)))


def _add_tool(
    bm: bmesh.types.BMesh,
    slot_ranges: list[tuple[int, int, int]],
    tool: str,
    h: float,
) -> None:
    if tool == "hoe":
        _add_box(bm, slot_ranges, 2, (0.30, -0.10, h * 0.52), (0.05, 0.05, h * 0.74))
        _add_box(bm, slot_ranges, 2, (0.30, -0.10, h * 0.84), (0.34, 0.05, 0.05))
    elif tool == "spear":
        _add_box(bm, slot_ranges, 2, (0.34, -0.08, h * 0.62), (0.045, 0.045, h * 0.98))
        _add_cone(
            bm,
            slot_ranges,
            2,
            radius1=0.10,
            radius2=0.0,
            depth=0.26,
            location=(0.34, -0.08, h * 1.15),
            vertices=5,
        )
    elif tool == "bundle":
        _add_box(bm, slot_ranges, 2, (-0.24, -0.02, h * 0.50), (0.28, 0.18, 0.24))


class LowPolyPeasantFactory(AssetFactory):
    """Tiny low-poly human figure for settlement life.

    Constructor knobs:
        factory_seed
        peasant_archetype : "farmer" | "merchant" | "guard" | "child"
        height
        body_color, skin_color, accent_color
        hat
        tool : "hoe" | "bundle" | "spear" | "none"
    """

    def __init__(
        self,
        factory_seed,
        peasant_archetype: str = "farmer",
        height: float | None = None,
        body_color: str | None = None,
        skin_color: str | None = None,
        accent_color: str | None = None,
        hat: bool | None = None,
        tool: str | None = None,
        coarse: bool = False,
        **_unused_kwargs,
    ) -> None:
        super().__init__(factory_seed, coarse=coarse)
        if _unused_kwargs:
            from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
            accept_unused_kwargs("LowPolyPeasantFactory", _unused_kwargs)
        if peasant_archetype not in _PEASANT_ARCHETYPES:
            import sys
            print(
                f"[peasant_archetype] WARN: unknown {peasant_archetype!r}; "
                f"falling back to {_PEASANT_ARCHETYPES[0]!r}. Valid: {_PEASANT_ARCHETYPES}",
                file=sys.stderr,
            )
            peasant_archetype = _PEASANT_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[peasant_archetype]
        self.peasant_archetype = peasant_archetype
        self.height = float(height if height is not None else d["height"])
        self.body_color = body_color or d["body_color"]
        self.skin_color = skin_color or d["skin_color"]
        self.accent_color = accent_color or d["accent_color"]
        self.hat = bool(hat if hat is not None else d["hat"])
        self.tool = tool or d["tool"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(f"LowPolyPeasant({self.factory_seed})_placeholder", None)
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        rng = random.Random(self.factory_seed)
        bm = bmesh.new()
        slot_ranges: list[tuple[int, int, int]] = []
        h = self.height * rng.uniform(0.94, 1.06)
        body_h = h * 0.43
        leg_h = h * 0.30
        head_r = h * 0.095

        _add_box(bm, slot_ranges, 0, (0.0, 0.0, leg_h + body_h * 0.5), (0.28, 0.18, body_h))
        # Legs.
        _add_box(bm, slot_ranges, 0, (-0.07, 0.0, leg_h * 0.5), (0.075, 0.075, leg_h))
        _add_box(bm, slot_ranges, 0, (0.07, 0.0, leg_h * 0.5), (0.075, 0.075, leg_h))
        # Arms with a slight pose asymmetry.
        arm_z = leg_h + body_h * 0.55
        _add_box(bm, slot_ranges, 1, (-0.22, 0.0, arm_z), (0.07, 0.07, body_h * 0.72))
        _add_box(bm, slot_ranges, 1, (0.22, 0.0, arm_z + rng.uniform(-0.04, 0.04)), (0.07, 0.07, body_h * 0.72))
        # Head.
        head_z = leg_h + body_h + head_r * 1.45
        _add_box(bm, slot_ranges, 1, (0.0, 0.0, head_z), (head_r * 1.8, head_r * 1.55, head_r * 1.9))
        # Hair/hat.
        if self.hat:
            _add_box(bm, slot_ranges, 2, (0.0, 0.0, head_z + head_r * 1.08), (head_r * 2.65, head_r * 2.25, 0.055))
            _add_cone(
                bm,
                slot_ranges,
                2,
                radius1=head_r * 1.18,
                radius2=head_r * 0.34,
                depth=head_r * 1.18,
                location=(0.0, 0.0, head_z + head_r * 1.66),
                vertices=7,
            )
        else:
            _add_box(bm, slot_ranges, 2, (0.0, 0.0, head_z + head_r * 0.82), (head_r * 1.9, head_r * 1.55, 0.055))

        _add_tool(bm, slot_ranges, self.tool, h)

        me = bpy.data.meshes.new(f"LowPolyPeasant({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()
        obj = bpy.data.objects.new(f"LowPolyPeasant({self.factory_seed})", me)
        bpy.context.scene.collection.objects.link(obj)
        while len(obj.data.materials) < 3:
            obj.data.materials.append(None)
        for start, end, slot in slot_ranges:
            for i in range(start, min(end, len(obj.data.polygons))):
                obj.data.polygons[i].material_index = slot
        for p in obj.data.polygons:
            p.use_smooth = False
        apply_palette_slots(obj, [self.body_color, self.skin_color, self.accent_color])
        return obj

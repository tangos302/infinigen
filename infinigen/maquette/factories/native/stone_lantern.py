"""LowPolyStoneLanternFactory — Japanese stone lantern (tōrō).

Invented 2026-05-16 to fill the zen-garden / shrine vocabulary the
existing catalog lacks (torii covers the shrine arch; this covers the
stone-path lantern that lines the approach). Plausible LLM request
for any zen-garden or temple-grounds prompt.

Archetypes:
  tachi_gata — tall pedestal lantern (~1.6m). Standard 5-section
               formal lantern: ground (kiso), shaft (sao), platform
               (chudai), light box (hibukuro), roof (kasa), finial
               (hoju). Lines the path to a shrine.
  yukimi_gata — snow-viewing low lantern (~0.8m). Three short curved
                legs replace the shaft; wider roof catches snow.
                Sits at pond edges and stepping-stone crossings.
  kasuga      — tall ornate formal lantern (~2m) on a long slim shaft
                with a taller light box and a steep peaked roof.
  oki_gata    — small movable lantern (~0.7m), no shaft — base, box,
                and roof sit low. For stepping stones and tea gardens.

Material slots:
  slot 0 = stone (rock_pale by default — light weathered granite)
  slot 1 = warm glow (stucco — for the light-box opening, reads as
                       paper/illumination from a distance)

The glow face uses an emission material and can parent a small point
light to the mesh. This makes temple/shrine/night scenes visibly lit
without requiring the build script to author a separate light object.
"""

from __future__ import annotations

import math

import bmesh
import bpy

from infinigen.core.placement.factory import AssetFactory

from ...materials import (
    add_palette_point_light,
    apply_emission_palette_slot,
    apply_palette_slots,
)


_LANTERN_ARCHETYPES = ("tachi_gata", "yukimi_gata", "kasuga", "oki_gata")


_ARCHETYPE_DEFAULTS = {
    "tachi_gata": dict(
        base_radius=0.32, base_height=0.18,
        shaft_radius=0.08, shaft_height=0.55,
        platform_radius=0.20, platform_height=0.06,
        box_radius=0.18, box_height=0.30,
        roof_radius=0.40, roof_height=0.18, roof_rise=0.10,
        finial_radius=0.08, finial_height=0.18,
        n_legs=0,
        stone_color="rock_pale", glow_color="stucco",
    ),
    "yukimi_gata": dict(
        base_radius=0.0, base_height=0.0,
        shaft_radius=0.0, shaft_height=0.0,
        platform_radius=0.22, platform_height=0.05,
        box_radius=0.20, box_height=0.20,
        roof_radius=0.55, roof_height=0.16, roof_rise=0.10,
        finial_radius=0.07, finial_height=0.12,
        n_legs=3,
        stone_color="rock_pale", glow_color="stucco",
    ),
    "kasuga": dict(
        base_radius=0.28, base_height=0.16,
        shaft_radius=0.07, shaft_height=0.80,
        platform_radius=0.18, platform_height=0.06,
        box_radius=0.17, box_height=0.34,
        roof_radius=0.38, roof_height=0.20, roof_rise=0.14,
        finial_radius=0.07, finial_height=0.20,
        n_legs=0,
        stone_color="rock_pale", glow_color="stucco",
    ),
    "oki_gata": dict(
        base_radius=0.30, base_height=0.14,
        shaft_radius=0.0, shaft_height=0.0,
        platform_radius=0.22, platform_height=0.06,
        box_radius=0.20, box_height=0.24,
        roof_radius=0.42, roof_height=0.16, roof_rise=0.09,
        finial_radius=0.07, finial_height=0.12,
        n_legs=0,
        stone_color="rock_pale", glow_color="stucco",
    ),
}


def _bm_face_count(bm) -> int:
    return len(bm.faces)


def _add_box(bm, slot_ranges, slot, cx, cy, cz, sx, sy, sz):
    start = _bm_face_count(bm)
    hx, hy, hz = sx / 2, sy / 2, sz / 2
    verts = [
        bm.verts.new((cx - hx, cy - hy, cz - hz)),
        bm.verts.new((cx + hx, cy - hy, cz - hz)),
        bm.verts.new((cx + hx, cy + hy, cz - hz)),
        bm.verts.new((cx - hx, cy + hy, cz - hz)),
        bm.verts.new((cx - hx, cy - hy, cz + hz)),
        bm.verts.new((cx + hx, cy - hy, cz + hz)),
        bm.verts.new((cx + hx, cy + hy, cz + hz)),
        bm.verts.new((cx - hx, cy + hy, cz + hz)),
    ]
    bm.verts.ensure_lookup_table()
    b00, b10, b11, b01, t00, t10, t11, t01 = verts
    bm.faces.new((b00, b10, t10, t00))
    bm.faces.new((b10, b11, t11, t10))
    bm.faces.new((b11, b01, t01, t11))
    bm.faces.new((b01, b00, t00, t01))
    bm.faces.new((t00, t10, t11, t01))
    bm.faces.new((b00, b01, b11, b10))
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))


def _add_prism(bm, slot_ranges, slot, cz, radius, height, n_sides):
    """Vertical n-sided prism centered on the Z axis, base at z=cz."""
    start = _bm_face_count(bm)
    bot = []
    top = []
    for s in range(n_sides):
        a = 2 * math.pi * s / n_sides
        x, y = radius * math.cos(a), radius * math.sin(a)
        bot.append(bm.verts.new((x, y, cz)))
        top.append(bm.verts.new((x, y, cz + height)))
    bm.verts.ensure_lookup_table()
    for s in range(n_sides):
        ns = (s + 1) % n_sides
        bm.faces.new((bot[s], bot[ns], top[ns], top[s]))
    bm.faces.new(list(reversed(bot)))
    bm.faces.new(top)
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))


def _add_pyramid_cap(bm, slot_ranges, slot, cz, base_radius, height, rise, n_sides):
    """Wide stone roof — a low truncated cone made of two stacked prisms,
    giving the "stepped pagoda cap" silhouette that reads as a tōrō
    roof. The `rise` is a small extra peak at the apex (finial pad)."""
    # Lower ring (wide).
    _add_prism(bm, slot_ranges, slot, cz, base_radius, height * 0.55, n_sides)
    # Upper ring (narrower), with a small rise on top.
    upper_r = base_radius * 0.55
    _add_prism(bm, slot_ranges, slot, cz + height * 0.55, upper_r, height * 0.45 + rise * 0.4, n_sides)


def _add_light_box(bm, slot_ranges, stone_slot, glow_slot, cz, radius, height, n_sides):
    """The hibukuro — open-faced hexagonal/square light box. Outer stone
    walls with one face replaced by a glowing-color patch on the +X side
    so it reads as 'the candle inside is visible'."""
    # First the full prism in stone.
    start = _bm_face_count(bm)
    bot = []
    top = []
    for s in range(n_sides):
        a = 2 * math.pi * s / n_sides
        x, y = radius * math.cos(a), radius * math.sin(a)
        bot.append(bm.verts.new((x, y, cz)))
        top.append(bm.verts.new((x, y, cz + height)))
    bm.verts.ensure_lookup_table()
    # All-but-one side wall: stone.
    glow_face_idx = 0  # +X-ish face — visible at default 35° azimuth camera
    for s in range(n_sides):
        ns = (s + 1) % n_sides
        face = bm.faces.new((bot[s], bot[ns], top[ns], top[s]))
        if s == glow_face_idx:
            # Track this face index for the glow slot assignment below.
            glow_face_global = len(bm.faces) - 1
    bm.faces.new(list(reversed(bot)))
    bm.faces.new(top)
    end = _bm_face_count(bm)
    # Assign the whole box to stone first…
    slot_ranges.append((start, end, stone_slot))
    # …then override the glow face. The glow face was face index
    # `start + glow_face_idx`. A second (start, start+1, glow_slot)
    # entry will overwrite the slot_index for that polygon when the
    # caller iterates the slot_ranges list in order.
    glow_face_global = start + glow_face_idx
    slot_ranges.append((glow_face_global, glow_face_global + 1, glow_slot))


def _add_curved_leg(bm, slot_ranges, slot, cx, cy, cz, height, thickness):
    """A short curved leg for the yukimi lantern — two stacked boxes
    with a slight outward kick so the foot reads as wider than the top."""
    # Lower foot — wider and offset outward.
    foot_r = math.hypot(cx, cy)
    if foot_r > 0:
        # Direction outward from center.
        kick = thickness * 0.5
        ux, uy = cx / foot_r, cy / foot_r
        fx, fy = cx + ux * kick, cy + uy * kick
    else:
        fx, fy = cx, cy
    _add_box(bm, slot_ranges, slot, fx, fy, cz + height * 0.25, thickness * 1.3, thickness * 1.3, height * 0.5)
    _add_box(bm, slot_ranges, slot, cx, cy, cz + height * 0.72, thickness, thickness, height * 0.55)


class LowPolyStoneLanternFactory(AssetFactory):
    """A Japanese stone lantern (tōrō) — formal pedestal or snow-viewing.

    Constructor knobs:
        factory_seed
        lantern_archetype : "tachi_gata" | "yukimi_gata"
        Most dimensions exposed as floats; pass None to use archetype
        default. n_sides defaults to 6 (hexagonal light box, classic).
        stone_color, glow_color : palette keys.
    """

    def __init__(
        self,
        factory_seed,
        lantern_archetype: str = "tachi_gata",
        n_sides: int = 6,
        stone_color: str | None = None,
        glow_color: str | None = None,
        emit_light: bool = True,
        light_energy: float = 38.0,
        light_radius: float = 0.72,
        emission_strength: float = 2.6,
        coarse: bool = False,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if lantern_archetype not in _LANTERN_ARCHETYPES:
            import sys
            print(
                f"[lantern_archetype] WARN: unknown {lantern_archetype!r}; "
                f"falling back to {_LANTERN_ARCHETYPES[0]!r}. "
                f"Valid: {_LANTERN_ARCHETYPES}",
                file=sys.stderr,
            )
            lantern_archetype = _LANTERN_ARCHETYPES[0]
        d = _ARCHETYPE_DEFAULTS[lantern_archetype]
        self.lantern_archetype = lantern_archetype
        # Hexagon is the canonical light-box shape; square (n=4) also reads
        # right for cottage-shrine variants.
        self.n_sides = max(4, int(n_sides))
        self.d = d
        self.stone_color = stone_color or d["stone_color"]
        self.glow_color = glow_color or d["glow_color"]
        self.emit_light = bool(emit_light)
        self.light_energy = float(light_energy)
        self.light_radius = float(light_radius)
        self.emission_strength = max(0.0, float(emission_strength))

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolyStoneLantern({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        bm = bmesh.new()
        slot_ranges: list[tuple[int, int, int]] = []
        d = self.d

        cursor_z = 0.0

        # 1. Ground stone (kiso) — wide squat hexagonal base.
        if d["base_height"] > 0:
            _add_prism(bm, slot_ranges, 0, cursor_z, d["base_radius"], d["base_height"], self.n_sides)
            cursor_z += d["base_height"]

        # 2. Shaft (sao) — slender vertical column, formal lanterns only.
        if d["shaft_height"] > 0:
            _add_prism(bm, slot_ranges, 0, cursor_z, d["shaft_radius"], d["shaft_height"], self.n_sides)
            cursor_z += d["shaft_height"]

        # 2b. Legs — snow-viewing lanterns sit on 3 short curved legs.
        if d["n_legs"] > 0:
            leg_h = 0.30
            leg_r = d["platform_radius"] * 0.7
            for i in range(d["n_legs"]):
                a = 2 * math.pi * i / d["n_legs"]
                _add_curved_leg(
                    bm, slot_ranges, 0,
                    cx=leg_r * math.cos(a), cy=leg_r * math.sin(a),
                    cz=cursor_z, height=leg_h, thickness=0.07,
                )
            cursor_z += leg_h

        # 3. Platform (chudai) — disc that the light box sits on.
        _add_prism(bm, slot_ranges, 0, cursor_z, d["platform_radius"], d["platform_height"], self.n_sides)
        cursor_z += d["platform_height"]

        # 4. Light box (hibukuro) — the lantern. One face glows.
        _add_light_box(
            bm, slot_ranges, 0, 1,
            cz=cursor_z, radius=d["box_radius"],
            height=d["box_height"], n_sides=self.n_sides,
        )
        cursor_z += d["box_height"]

        # 5. Roof (kasa) — wide stepped cap.
        _add_pyramid_cap(
            bm, slot_ranges, 0,
            cz=cursor_z, base_radius=d["roof_radius"],
            height=d["roof_height"], rise=d["roof_rise"],
            n_sides=self.n_sides,
        )
        cursor_z += d["roof_height"]

        # 6. Finial (hoju) — small onion-bulb on top. Approximated as a
        # narrow prism + a pointed cap for the apex.
        _add_prism(
            bm, slot_ranges, 0,
            cz=cursor_z, radius=d["finial_radius"],
            height=d["finial_height"] * 0.6, n_sides=self.n_sides,
        )

        me = bpy.data.meshes.new(f"LowPolyStoneLantern({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()

        obj = bpy.data.objects.new(
            f"LowPolyStoneLantern({self.factory_seed})", me,
        )
        bpy.context.scene.collection.objects.link(obj)
        while len(obj.data.materials) < 2:
            obj.data.materials.append(None)
        # Process slot_ranges in order — later entries override earlier ones
        # for the same face index. That's how the glow face gets re-assigned
        # after the whole light-box was assigned to stone.
        for start, end, slot in slot_ranges:
            for i in range(start, end):
                obj.data.polygons[i].material_index = slot
        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(obj, [self.stone_color, self.glow_color])
        apply_emission_palette_slot(
            obj,
            1,
            self.glow_color,
            strength=self.emission_strength,
        )
        if self.emit_light:
            light_z = (
                d["base_height"]
                + d["shaft_height"]
                + (0.30 if d["n_legs"] > 0 else 0.0)
                + d["platform_height"]
                + d["box_height"] * 0.52
            )
            add_palette_point_light(
                name=f"{obj.name}_PointLight",
                location=(0.0, 0.0, light_z),
                palette_key=self.glow_color,
                energy=self.light_energy,
                radius=self.light_radius,
                parent=obj,
            )
        return obj

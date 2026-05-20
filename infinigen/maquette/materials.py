"""Maquette material helpers.

Strips upstream Infinigen's complex shader-graph materials off a
mesh and replaces them with a single matte Principled BSDF tinted to
a Maquette palette color. That's the entire material story for v0:
one solid color per object, picked by the caller (or a future
class-based mapping).

Why single-color, not even per-face variation:
  - It's the foundational ingredient of the Firewatch look. Per-face
    color drift fights the silhouette.
  - Materials authoring is out of v0 scope; we want predictable
    output that's easy to A/B against geometry-only renders.
  - If a future asset class wants two-tone (e.g. trunk/leaves),
    that's a decision on the FACTORY side — call this helper twice
    on the two child meshes — not a complication of this primitive.

The created materials are named `Maquette_<palette_key>` and reused
across calls — every boulder asking for `rock_warm` shares the same
material data block, which keeps the .blend file size sane when
scattering hundreds.
"""

from __future__ import annotations

import bpy

from .palette import MAQUETTE_PALETTE, hex_to_rgba


_MATERIAL_PREFIX = "Maquette_"


def _get_or_create_palette_material(palette_key: str) -> bpy.types.Material:
    """Return the named Maquette material, creating it (with the palette
    color baked in) on first use. Reused across all callers."""
    if palette_key not in MAQUETTE_PALETTE:
        raise KeyError(f"unknown palette key {palette_key!r}; valid: {list(MAQUETTE_PALETTE)}")
    name = f"{_MATERIAL_PREFIX}{palette_key}"
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    bsdf.inputs["Base Color"].default_value = hex_to_rgba(MAQUETTE_PALETTE[palette_key])
    bsdf.inputs["Roughness"].default_value = 0.85   # matte for flat-shaded read
    bsdf.inputs["Metallic"].default_value = 0.0
    bsdf.inputs["IOR"].default_value = 1.45
    return mat


def _get_or_create_emission_material(
    palette_key: str,
    *,
    strength: float = 3.0,
) -> bpy.types.Material:
    """Return a reusable warm emission material for visible light parts.

    This is intentionally still palette-driven. Factories can make a flame,
    lantern pane, or beacon read as bright without inventing arbitrary hex
    colours outside the Maquette look.
    """
    if palette_key not in MAQUETTE_PALETTE:
        raise KeyError(f"unknown palette key {palette_key!r}; valid: {list(MAQUETTE_PALETTE)}")
    safe_strength = max(0.0, float(strength))
    name = f"{_MATERIAL_PREFIX}Emission_{palette_key}_{safe_strength:g}"
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    colour = hex_to_rgba(MAQUETTE_PALETTE[palette_key])
    bsdf.inputs["Base Color"].default_value = colour
    bsdf.inputs["Roughness"].default_value = 0.48
    bsdf.inputs["Metallic"].default_value = 0.0
    bsdf.inputs["IOR"].default_value = 1.45
    if "Emission Color" in bsdf.inputs:
        bsdf.inputs["Emission Color"].default_value = colour
    if "Emission Strength" in bsdf.inputs:
        bsdf.inputs["Emission Strength"].default_value = safe_strength
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def apply_palette(obj: bpy.types.Object, palette_key: str) -> bpy.types.Object:
    """Replace all materials on `obj` with the Maquette palette material
    named `palette_key`. Idempotent — calling repeatedly with the same key
    does not duplicate material slots.

    Mirrors the Firewatch-style "one color per object" decision. If an
    asset has child meshes that need different colors (e.g. trunk vs
    leaves on a tree), call apply_palette on each child individually.
    """
    if obj.type != "MESH":
        return obj
    mat = _get_or_create_palette_material(palette_key)
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    return obj


def apply_emission_palette_slot(
    obj: bpy.types.Object,
    slot_index: int,
    palette_key: str,
    *,
    strength: float = 3.0,
) -> bpy.types.Object:
    """Replace one material slot with a palette emission material."""
    if obj.type != "MESH":
        return obj
    mat = _get_or_create_emission_material(palette_key, strength=strength)
    while len(obj.data.materials) <= int(slot_index):
        obj.data.materials.append(None)
    obj.data.materials[int(slot_index)] = mat
    return obj


def add_palette_point_light(
    *,
    name: str,
    location: tuple[float, float, float],
    palette_key: str,
    energy: float,
    radius: float,
    parent: bpy.types.Object | None = None,
) -> bpy.types.Object:
    """Create a small point light tied to a palette colour.

    Factories parent these lights to their mesh object. Runtime template
    copies can duplicate child lights as needed, so a lantern copied along
    a path remains a real light source.
    """
    if palette_key not in MAQUETTE_PALETTE:
        raise KeyError(f"unknown palette key {palette_key!r}; valid: {list(MAQUETTE_PALETTE)}")
    rgba = hex_to_rgba(MAQUETTE_PALETTE[palette_key])
    data = bpy.data.lights.new(name, "POINT")
    data.color = (rgba[0], rgba[1], rgba[2])
    data.energy = max(0.0, float(energy))
    data.shadow_soft_size = max(0.01, float(radius))
    light = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(light)
    light.location = tuple(float(v) for v in location)
    if parent is not None:
        light.parent = parent
    return light


_SNOW_ROCK_MAT_PREFIX = "Maquette_snow_rock_"


def _get_or_create_snow_rock_material(
    snow_line: float = 20.0,
    snow_band: float = 4.0,
    rock_color: tuple[float, float, float, float] = (0.45, 0.43, 0.42, 1.0),
    snow_color: tuple[float, float, float, float] = (0.95, 0.96, 0.98, 1.0),
) -> bpy.types.Material:
    """Two-tone height-banded material: rock below `snow_line` meters,
    snow above. The transition band (`snow_band` meters wide, centered
    on the snow line) is quantized to a 2-stop hard ColorRamp so it
    reads as a flat painterly snow line, not a smooth gradient.

    Use for alpine, snowy mountain, glacier, fjord cliff scenes. The Z
    threshold is in *world* coordinates so set the snow line based on
    the scene's actual peak elevations.

    Cached per (snow_line, snow_band) tuple so repeated calls reuse
    the same material data block.
    """
    name = f"{_SNOW_ROCK_MAT_PREFIX}{snow_line:g}_{snow_band:g}"
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = 0.85
    bsdf.inputs["Metallic"].default_value = 0.0
    bsdf.inputs["IOR"].default_value = 1.45
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    # Geometry > Position → Separate XYZ → Z fed into Map Range to
    # normalise [snow_line - band/2, snow_line + band/2] → [0, 1] →
    # ColorRamp Constant interpolation with 2 stops (rock at 0, snow
    # at the threshold). The band gives some bedding allowance — small
    # rocks pierce the snow at the transition.
    geom = nt.nodes.new("ShaderNodeNewGeometry")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(geom.outputs["Position"], sep.inputs["Vector"])
    map_range = nt.nodes.new("ShaderNodeMapRange")
    band = max(float(snow_band), 0.5)
    map_range.inputs["From Min"].default_value = float(snow_line) - band * 0.5
    map_range.inputs["From Max"].default_value = float(snow_line) + band * 0.5
    map_range.inputs["To Min"].default_value = 0.0
    map_range.inputs["To Max"].default_value = 1.0
    nt.links.new(sep.outputs["Z"], map_range.inputs["Value"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.interpolation = "CONSTANT"
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = rock_color
    ramp.color_ramp.elements[1].position = 0.5
    ramp.color_ramp.elements[1].color = snow_color
    nt.links.new(map_range.outputs["Result"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])

    return mat


def apply_snow_rock_material(
    obj: bpy.types.Object,
    snow_line: float = 20.0,
    snow_band: float = 4.0,
) -> bpy.types.Object:
    """Replace `obj`'s materials with a height-banded snow/rock
    material. Snow line is in world Z meters; everything above
    (with a soft `snow_band` transition) is white snow, everything
    below is gray rock.
    """
    if obj.type != "MESH":
        return obj
    mat = _get_or_create_snow_rock_material(snow_line=snow_line, snow_band=snow_band)
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    return obj


_SNOW_SLOPE_MAT_PREFIX = "Maquette_snow_slope_"


def _get_or_create_snow_slope_material(
    slope_threshold: float = 0.65,
    rock_color: tuple[float, float, float, float] = (0.32, 0.30, 0.30, 1.0),
    snow_color: tuple[float, float, float, float] = (0.97, 0.97, 0.99, 1.0),
) -> bpy.types.Material:
    """Slope-aware snow/rock — snow accumulates on top-facing
    surfaces, rock shows on steep faces. Normal-Z (cosine of angle
    from vertical) drives a Constant-interp ColorRamp:

      Normal.Z > slope_threshold  → flat enough → snow
      Normal.Z ≤ slope_threshold  → too steep   → rock

    This is the dominant way real snow accumulates and the look
    every stylised low-poly snow scene uses (per reference image
    on prompt #3 — snowy alpine pass): cones show rocky faces on
    their slopes, snowy caps on the flatter top areas, and the
    valley floor is fully snow because it's flat.

    `slope_threshold` 0.65 ≈ 49° from vertical; tune lower for
    less rock visible (only the very steepest faces), higher for
    more (rock on moderate slopes too).
    """
    name = f"{_SNOW_SLOPE_MAT_PREFIX}{slope_threshold:g}"
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = 0.85
    bsdf.inputs["Metallic"].default_value = 0.0
    bsdf.inputs["IOR"].default_value = 1.45
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    # Geometry > Normal → Separate XYZ → Z component (cosine of angle
    # from world up). Constant-interp ColorRamp quantizes to 2 stops:
    # rock below threshold, snow above.
    geom = nt.nodes.new("ShaderNodeNewGeometry")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(geom.outputs["Normal"], sep.inputs["Vector"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.interpolation = "CONSTANT"
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = rock_color
    ramp.color_ramp.elements[1].position = float(slope_threshold)
    ramp.color_ramp.elements[1].color = snow_color
    nt.links.new(sep.outputs["Z"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])

    return mat


def apply_snow_slope_material(
    obj: bpy.types.Object,
    slope_threshold: float = 0.65,
) -> bpy.types.Object:
    """Replace `obj`'s materials with a slope-aware snow/rock material.
    Steep faces (cosine of angle-from-vertical < `slope_threshold`)
    show rock; flatter faces show snow. See
    `_get_or_create_snow_slope_material` for tuning notes.
    """
    if obj.type != "MESH":
        return obj
    mat = _get_or_create_snow_slope_material(slope_threshold=slope_threshold)
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    return obj


_WATER_MAT_NAME = "Maquette_water_translucent"


def _get_or_create_water_material() -> bpy.types.Material:
    """Stylised low-poly water — opaque, banded fresnel rim, voronoi
    cell-pattern shimmer overlay. Built per the recipe in memory
    `project_low_poly_water.md`:

      - Opaque (no transmission, no alpha BLEND) — depth communicated
        through *color*, not transparency.
      - Saturated teal base (shallow) → deep indigo (rim accent),
        mixed via a Layer-Weight fresnel with **Constant**-interpolated
        ColorRamp so the transition reads as 2 flat bands instead of
        a smooth glossy specular.
      - Voronoi cell-pattern overlay at low intensity for hand-drawn
        wave shimmer (no animation here — animation needs a frame
        driver which can be added per-scene).

    Reused across every water-using factory. Always applied via a
    mesh that has *thickness* — never a flat plane — so the volume
    reads as a body of water (see feedback memory `water_material_rule`).
    """
    mat = bpy.data.materials.get(_WATER_MAT_NAME)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(_WATER_MAT_NAME)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    out = nt.nodes.new("ShaderNodeOutputMaterial")

    # Deep saturated teal base — opaque, painterly. Specular killed
    # so HDRI sky doesn't reflect glossily.
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    deep_color = (0.06, 0.32, 0.50, 1.0)
    bsdf.inputs["Base Color"].default_value = deep_color
    bsdf.inputs["Roughness"].default_value = 0.65
    bsdf.inputs["Metallic"].default_value = 0.0
    bsdf.inputs["IOR"].default_value = 1.33
    for key in ("Specular IOR Level", "Specular"):
        if key in bsdf.inputs:
            bsdf.inputs[key].default_value = 0.05

    # Voronoi cell-pattern shimmer — adds the hand-drawn "wave cell"
    # texture to the flat base. ColorRamp Constant interpolation
    # quantizes to two flat tonal bands (deep + a slightly-paler
    # crest tint), keeping the painterly read.
    tex_coord = nt.nodes.new("ShaderNodeTexCoord")
    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (0.06, 0.06, 0.06)
    nt.links.new(tex_coord.outputs["Object"], mapping.inputs["Vector"])
    voronoi = nt.nodes.new("ShaderNodeTexVoronoi")
    voronoi.feature = "DISTANCE_TO_EDGE"
    voronoi.inputs["Scale"].default_value = 1.5
    nt.links.new(mapping.outputs["Vector"], voronoi.inputs["Vector"])
    voronoi_ramp = nt.nodes.new("ShaderNodeValToRGB")
    voronoi_ramp.color_ramp.interpolation = "CONSTANT"
    # Voronoi "Distance to Edge" returns LARGE in cell centers and
    # small near edges. So the deep base is the cell-center color
    # (the bulk of the surface), and the paler crest tint shows
    # only as thin streaks where neighbouring cells meet.
    voronoi_ramp.color_ramp.elements[0].position = 0.0
    voronoi_ramp.color_ramp.elements[0].color = (0.16, 0.50, 0.66, 1.0)  # paler crest streak
    voronoi_ramp.color_ramp.elements[1].position = 0.04
    voronoi_ramp.color_ramp.elements[1].color = deep_color  # bulk of the body
    nt.links.new(voronoi.outputs["Distance"], voronoi_ramp.inputs["Fac"])
    nt.links.new(voronoi_ramp.outputs["Color"], bsdf.inputs["Base Color"])

    # Banded fresnel rim — added as EMISSION so the rim accent only
    # brightens at grazing angles without washing out the deep base
    # color when viewed top-down. Constant-interp ramp = 2-band rim.
    fresnel = nt.nodes.new("ShaderNodeFresnel")
    fresnel.inputs["IOR"].default_value = 1.33
    fres_ramp = nt.nodes.new("ShaderNodeValToRGB")
    fres_ramp.color_ramp.interpolation = "CONSTANT"
    fres_ramp.color_ramp.elements[0].position = 0.0
    fres_ramp.color_ramp.elements[0].color = (0.0, 0.0, 0.0, 1.0)  # no emission
    fres_ramp.color_ramp.elements[1].position = 0.55
    fres_ramp.color_ramp.elements[1].color = (0.50, 0.82, 0.90, 1.0)  # pale grazing rim
    nt.links.new(fresnel.outputs["Fac"], fres_ramp.inputs["Fac"])
    if "Emission Color" in bsdf.inputs:
        nt.links.new(fres_ramp.outputs["Color"], bsdf.inputs["Emission Color"])
        bsdf.inputs["Emission Strength"].default_value = 0.45

    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    mat.blend_method = "OPAQUE"
    return mat


def apply_water_material(obj: bpy.types.Object) -> bpy.types.Object:
    """Replace `obj`'s materials with the translucent Maquette water
    shader. Caller must build `obj` as a mesh with non-zero Z thickness
    (a box, not a plane) — see `feedback_water_material_rule`.
    """
    if obj.type != "MESH":
        return obj
    mat = _get_or_create_water_material()
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    return obj


def apply_palette_slots(
    obj: bpy.types.Object, slot_colors: list[str]
) -> bpy.types.Object:
    """Set up multiple material slots on `obj`, one per palette key in
    `slot_colors`. Polygons' material_index values are preserved — caller is
    responsible for having set those before/during geometry construction.

    Important: this REPLACES existing slots in-place rather than calling
    obj.data.materials.clear(). Clearing the materials list silently
    resets every polygon's material_index to 0 (Blender clamps to a
    valid slot range), which would defeat the whole purpose of
    per-region indices set by the caller.

    Used by factories that want per-region color (e.g.
    NativeLowPolyTreeFactory splitting trunk from foliage). For a
    single-color asset, prefer apply_palette() — same end result with
    less ceremony.
    """
    if obj.type != "MESH":
        return obj
    mats = [_get_or_create_palette_material(key) for key in slot_colors]
    # Grow / fill slots in place
    for i, mat in enumerate(mats):
        if i < len(obj.data.materials):
            obj.data.materials[i] = mat
        else:
            obj.data.materials.append(mat)
    # Trim trailing slots beyond the requested count
    while len(obj.data.materials) > len(mats):
        obj.data.materials.pop()
    return obj

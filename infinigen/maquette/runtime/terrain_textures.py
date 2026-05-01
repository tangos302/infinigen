"""Realistic PBR shader for the eroded terrain mesh.

The vertex-color biome path (``_biome_colors`` in ``eroded_terrain``)
gives each vertex a flat linear RGB. That's fine for low-poly but reads
as "colored ground" rather than "ground". This module bolts a real PBR
texture set on top:

  * One CC0 set per biome (grass, forest, rock, snow, sand) — see
    ``runtime/textures/README.md`` for sources.
  * Box-projection (Blender's native triplanar equivalent) so cliffs
    don't streak. Per-axis blend factor 0.15 hides the seam.
  * A 5-channel **Splat** vertex attribute (R=grass, G=forest,
    B=rock, A=snow; sand stored alongside via a sixth channel
    encoded into a separate FLOAT_COLOR attribute). The shader uses
    these as mix weights so transitions between biomes happen at the
    same place the existing biome-color blend does.
  * A Voronoi macro-color overlay multiplied at low intensity into
    the diffuse so 1m-tile textures don't read as "tiled".
  * A detail-normal layer at 4× tiling for near-camera roughness
    that would otherwise flatten under the 1k texture's pixel scale.

glTF caveat: Voronoi macro + procedural splat mix won't survive the
glTF export — bake the combined diffuse / normal / roughness to flat
textures before export when shipping to the browser. This module
returns the live shader; the bake step lives in ``lod_bake.py`` (or
will, once we wire it).
"""
from __future__ import annotations

from pathlib import Path

# Resolve the textures directory relative to this file so it works
# regardless of the importing process's CWD.
_TEX_DIR = Path(__file__).resolve().parent / "textures"


# Per-biome diffuse tint — multiplied into the diffuse before blending
# so we can push grass green-er or rock cooler without re-downloading
# textures. Authored as sRGB-intent colours (the value you'd type into
# a paint program); the shader feeds them through a Combine Color so
# the multiply is per-channel.
#
# Default tints chosen 2026-05-01 after the user noted aerial textures
# read as warm/desaturated:
#   grass  : (0.85, 1.05, 0.70) — push green up, knock red+blue down
#   forest : (0.85, 1.00, 0.70) — slight green push, less aggressive
#   rock   : (1.00, 1.00, 1.05) — neutral with a tiny cool cast
#   snow   : (1.00, 1.00, 1.05) — same cool cast so snow doesn't pink
#   sand   : (1.05, 0.95, 0.80) — warmer, drier
_BIOME_TINTS: dict[str, tuple[float, float, float]] = {
    "grass":  (0.85, 1.05, 0.70),
    "forest": (0.85, 1.00, 0.70),
    "rock":   (1.00, 1.00, 1.05),
    "snow":   (1.00, 1.00, 1.05),
    "sand":   (1.05, 0.95, 0.80),
}


# Per-biome image sets — multiple options per biome so two scenes
# don't always render with the same diffuse. Selected per build via
# ``_pick_biome_sets(seed)``. Filenames match Polyhaven 1k JPG layout.
def _set(name: str) -> tuple[str, str, str]:
    return (f"{name}_diff_1k.jpg", f"{name}_nor_gl_1k.jpg", f"{name}_rough_1k.jpg")


_BIOME_SETS_OPTIONS: dict[str, list[tuple[str, str, str]]] = {
    "grass":  [
        _set("aerial_grass_rock"),  # mossy meadow with rocks
        _set("grass_path_2"),       # tighter grass with dirt patches
        _set("forest_floor"),       # mossy forest floor — reads as lush meadow
    ],
    "forest": [
        _set("forrest_ground_01"),  # leaf-and-twig duff
        _set("forrest_ground_03"),  # bare dark earth
        _set("brown_mud_leaves_01"),  # wet leaf litter
    ],
    "rock":   [
        _set("aerial_rocks_02"),    # mossy rocks
        _set("aerial_rocks_04"),    # bare grey scree
        _set("rock_face_03"),       # cliff face
        _set("rocky_terrain_02"),   # alpine talus
    ],
    "snow":   [
        _set("snow_02"),            # smooth snow
        _set("snow_03"),            # wind-swept ridges
    ],
    "sand":   [
        _set("coast_sand_rocks_02"),  # beach with pebbles
        _set("aerial_beach_03"),      # plain beach sand
        _set("brown_mud_dry"),        # cracked dry mud (riverbed)
    ],
}


def _pick_biome_sets(seed: int) -> dict[str, tuple[str, str, str]]:
    """Roll one (diffuse, normal, rough) tuple per biome from the
    options dict, deterministic on ``seed`` — same scene seed = same
    look. Different scene seeds get different texture rolls so
    consecutive runs feel distinct.
    """
    import random

    rng = random.Random(int(seed) ^ 0x7E22A1)
    return {biome: rng.choice(opts) for biome, opts in _BIOME_SETS_OPTIONS.items()}


# Backward-compat alias — picks the first option per biome (deterministic
# fallback for callers that don't pass a seed).
_BIOME_SETS: dict[str, tuple[str, str, str]] = {
    biome: opts[0] for biome, opts in _BIOME_SETS_OPTIONS.items()
}


def textures_available() -> bool:
    """True when each biome has at least one fully-present
    (diffuse, normal, roughness) trio. We only need ONE option per
    biome to be available — missing alternates just shrink the
    per-scene variety pool.
    """
    for biome, opts in _BIOME_SETS_OPTIONS.items():
        biome_ok = False
        for d, n, r in opts:
            if all((_TEX_DIR / f).is_file() for f in (d, n, r)):
                biome_ok = True
                break
        if not biome_ok:
            return False
    return True


def compute_splat_weights(elev, alpine_mask, sea_level: float):
    """Return a (res, res, 5) float32 array of [grass, forest, rock,
    snow, sand] weights — one per pixel — that the realistic shader
    uses as biome mix factors.

    Same elevation/slope reasoning as ``_biome_colors`` in
    ``eroded_terrain``: forest in the meadow→forest band, rock fades
    through scree on intermediate slopes, snow gated by both elevation
    and slope, sand at the shoreline. Computed at heightmap resolution
    so the splat mask is independent of the terrain LOD.
    """
    import numpy as np

    res = elev.shape[0]
    above = elev - float(sea_level)

    # Quantile thresholds — same logic as biome_colors so the texture
    # map and the vertex-color band stay aligned.
    land = above[above >= 0]
    if land.size < 16:
        beach_top, meadow_top, forest_top, alpine_top, snow_top = 0.18, 1.5, 3.5, 6.0, 12.0
    else:
        beach_top  = float(np.quantile(land, 0.06))
        meadow_top = float(np.quantile(land, 0.45))
        forest_top = float(np.quantile(land, 0.78))
        alpine_top = float(np.quantile(land, 0.93))
        snow_top   = float(np.quantile(land, 0.99))

    gy, gx = np.gradient(elev)
    slope = np.sqrt(gx * gx + gy * gy)

    grass  = np.zeros((res, res), dtype=np.float32)
    forest = np.zeros((res, res), dtype=np.float32)
    rock   = np.zeros((res, res), dtype=np.float32)
    snow   = np.zeros((res, res), dtype=np.float32)
    sand   = np.zeros((res, res), dtype=np.float32)

    # Sand — beach band + submerged shore.
    sand_band = np.clip(above / max(beach_top, 0.05), 0, 1) * (above < beach_top) * (above >= -0.5)
    sand += sand_band

    # Grass — meadow → forest range, weighted toward meadow.
    grass_band = np.clip((above - beach_top) / max(meadow_top - beach_top, 0.1), 0, 1) * (above >= beach_top) * (above < forest_top)
    grass += grass_band * (1.0 - 0.5 * np.clip((above - meadow_top) / max(forest_top - meadow_top, 0.1), 0, 1))

    # Forest — kicks in past meadow_top, fades by alpine_top.
    forest_band = np.clip((above - meadow_top) / max(forest_top - meadow_top, 0.1), 0, 1) * (above >= meadow_top) * (above < alpine_top)
    forest += forest_band * (1.0 - alpine_mask)

    # Rock — slope-driven scree on land that's above the meadow band.
    elev_factor = np.clip((above - 0.5 * meadow_top) / max(meadow_top, 1.0), 0, 1)
    rock_slope = np.clip((slope - 0.20) / 0.45, 0, 1)
    rock += rock_slope * elev_factor

    # Alpine band — boosts rock weight at high elevation.
    alpine_band = np.clip((above - forest_top) / max(alpine_top - forest_top, 0.1), 0, 1) * (above >= forest_top)
    rock += alpine_band

    # Snow — slope-gated, high elevation only.
    snow_elev = np.clip((above - alpine_top) / max(snow_top - alpine_top, 0.1), 0, 1)
    slope_gate = np.clip(1.0 - (slope - 0.45) / 0.35, 0, 1)
    snow += snow_elev * slope_gate

    # Stack and normalize so weights sum to 1.0 per pixel.
    splat = np.stack([grass, forest, rock, snow, sand], axis=-1)
    total = splat.sum(axis=-1, keepdims=True)
    total = np.maximum(total, 1e-4)
    splat = splat / total
    return splat.astype(np.float32)


def write_splat_attributes(me, splat) -> None:
    """Write the (res, res, 5) splat array to two FLOAT_COLOR vertex
    attributes on the mesh:

      * ``Splat`` — RGBA = (grass, forest, rock, snow). Used as the
        primary mix factor in the realistic shader.
      * ``Splat2`` — R = sand. Other channels unused (they default to
        whatever the encoder writes; the shader only reads R).

    The splat array has one row per heightmap pixel. We assume the
    mesh's verts are laid out in the same row-major order the heightmap
    was sampled in (which is how ``make_eroded_terrain`` builds it).
    """
    import numpy as np

    res = splat.shape[0]
    n_verts = len(me.vertices)
    expected = res * res

    # Decimation may have removed verts. We support that by sampling
    # the splat array at each vertex's world XY back through the
    # heightmap grid — done in the caller via ``write_splat_post_decimate``.
    if n_verts != expected:
        raise ValueError(
            f"write_splat_attributes called with {n_verts} verts but splat is "
            f"{res}×{res}={expected}; use write_splat_post_decimate for "
            f"decimated meshes"
        )

    splat_flat = splat.reshape(-1, 5)
    rgba_main = np.empty((n_verts, 4), dtype=np.float32)
    rgba_main[:, 0] = splat_flat[:, 0]  # grass
    rgba_main[:, 1] = splat_flat[:, 1]  # forest
    rgba_main[:, 2] = splat_flat[:, 2]  # rock
    rgba_main[:, 3] = splat_flat[:, 3]  # snow
    rgba_aux = np.zeros((n_verts, 4), dtype=np.float32)
    rgba_aux[:, 0] = splat_flat[:, 4]  # sand

    main = me.color_attributes.new(name="Splat", type="FLOAT_COLOR", domain="POINT")
    main.data.foreach_set("color", rgba_main.flatten())
    aux = me.color_attributes.new(name="Splat2", type="FLOAT_COLOR", domain="POINT")
    aux.data.foreach_set("color", rgba_aux.flatten())


def write_splat_post_decimate(me, splat, size: float) -> None:
    """Same as ``write_splat_attributes`` but for a decimated mesh —
    samples the splat grid bilinearly at each vertex's world XY.
    """
    import numpy as np

    res = splat.shape[0]
    span = 2.0 * float(size)
    n_verts = len(me.vertices)
    # foreach_get wants a flat float buffer; allocating directly as
    # n*3 and reshaping after is more reliable than allocating (n, 3)
    # and passing a reshape view (foreach_get behavior on views is
    # unstable across Blender versions).
    flat = np.zeros(n_verts * 3, dtype=np.float32)
    me.vertices.foreach_get("co", flat)
    coords = flat.reshape(n_verts, 3)

    u = (coords[:, 0] + size) / span * (res - 1)
    v = (coords[:, 1] + size) / span * (res - 1)
    u = np.clip(u, 0, res - 1.001)
    v = np.clip(v, 0, res - 1.001)
    i = u.astype(np.int32)
    j = v.astype(np.int32)
    fu = (u - i)[:, None]
    fv = (v - j)[:, None]

    s00 = splat[j, i]            # (n, 5)
    s10 = splat[j, i + 1]
    s01 = splat[j + 1, i]
    s11 = splat[j + 1, i + 1]
    a = s00 * (1 - fu) + s10 * fu
    b = s01 * (1 - fu) + s11 * fu
    sampled = a * (1 - fv) + b * fv  # (n, 5)

    rgba_main = np.empty((n_verts, 4), dtype=np.float32)
    rgba_main[:, :4] = sampled[:, :4]
    rgba_aux = np.zeros((n_verts, 4), dtype=np.float32)
    rgba_aux[:, 0] = sampled[:, 4]

    main = me.color_attributes.new(name="Splat", type="FLOAT_COLOR", domain="POINT")
    main.data.foreach_set("color", rgba_main.ravel().astype(np.float32, copy=False))
    aux = me.color_attributes.new(name="Splat2", type="FLOAT_COLOR", domain="POINT")
    aux.data.foreach_set("color", rgba_aux.ravel().astype(np.float32, copy=False))


def _load_image(name: str):
    """Load an image into Blender, idempotent on name. Sets color space
    so non-color maps don't get sRGB-decoded."""
    import bpy

    path = _TEX_DIR / name
    img = bpy.data.images.get(name)
    if img is None:
        img = bpy.data.images.load(str(path), check_existing=True)
    if "_diff" in name:
        img.colorspace_settings.name = "sRGB"
    else:
        img.colorspace_settings.name = "Non-Color"
    return img


def _build_biome_branch(nt, biome: str, mapping_out, normal_strength: float = 1.0,
                        sets: dict[str, tuple[str, str, str]] | None = None):
    """Build the (diffuse, normal, roughness) sub-graph for one biome.

    The diffuse goes through a per-biome tint multiply (see
    ``_BIOME_TINTS``) so we can push individual biomes warmer/cooler/
    greener without changing the source texture.

    ``sets`` overrides the default (first-option) biome image triple;
    pass the result of ``_pick_biome_sets(seed)`` to roll a per-scene
    variant.

    Returns (color_socket, normal_socket, rough_socket).
    """
    diff_name, nor_name, rough_name = (sets or _BIOME_SETS)[biome]
    tint = _BIOME_TINTS.get(biome, (1.0, 1.0, 1.0))
    nodes = nt.nodes
    links = nt.links

    diff_tex = nodes.new("ShaderNodeTexImage")
    diff_tex.image = _load_image(diff_name)
    diff_tex.projection = "BOX"
    diff_tex.projection_blend = 0.15
    links.new(mapping_out, diff_tex.inputs["Vector"])

    # Tint multiply — RGB MULTIPLY at full Fac. Tints near (1,1,1)
    # are no-ops; only colored multipliers actually shift the look.
    if tint != (1.0, 1.0, 1.0):
        tint_node = nodes.new("ShaderNodeMixRGB")
        tint_node.blend_type = "MULTIPLY"
        tint_node.inputs["Fac"].default_value = 1.0
        tint_node.inputs["Color2"].default_value = (tint[0], tint[1], tint[2], 1.0)
        links.new(diff_tex.outputs["Color"], tint_node.inputs["Color1"])
        diff_out = tint_node.outputs["Color"]
    else:
        diff_out = diff_tex.outputs["Color"]

    nor_tex = nodes.new("ShaderNodeTexImage")
    nor_tex.image = _load_image(nor_name)
    nor_tex.projection = "BOX"
    nor_tex.projection_blend = 0.15
    links.new(mapping_out, nor_tex.inputs["Vector"])

    nor_map = nodes.new("ShaderNodeNormalMap")
    nor_map.inputs["Strength"].default_value = float(normal_strength)
    links.new(nor_tex.outputs["Color"], nor_map.inputs["Color"])

    rough_tex = nodes.new("ShaderNodeTexImage")
    rough_tex.image = _load_image(rough_name)
    rough_tex.projection = "BOX"
    rough_tex.projection_blend = 0.15
    links.new(mapping_out, rough_tex.inputs["Vector"])

    return diff_out, nor_map.outputs["Normal"], rough_tex.outputs["Color"]


def _mix_color(nt, factor_socket, a_socket, b_socket):
    """factor=0 → A, factor=1 → B. ShaderNodeMixRGB for stable export."""
    n = nt.nodes.new("ShaderNodeMixRGB")
    n.blend_type = "MIX"
    nt.links.new(factor_socket, n.inputs["Fac"])
    nt.links.new(a_socket, n.inputs["Color1"])
    nt.links.new(b_socket, n.inputs["Color2"])
    return n.outputs["Color"]


def _scale_color(nt, factor_socket, color_socket):
    """color * scalar via ShaderNodeMix (new RGBA mix). Use Mix.B as
    color, Mix.A black, Fac as factor → result = Fac * color. Simpler
    + more reliable than MixRGB(MULTIPLY) which has interpretation
    quirks across Blender versions."""
    n = nt.nodes.new("ShaderNodeMix")
    n.data_type = "RGBA"
    n.blend_type = "MIX"
    # Inputs by name for the new mix node:
    #   Factor, A (Color), B (Color)
    n.inputs["A"].default_value = (0.0, 0.0, 0.0, 1.0)
    nt.links.new(factor_socket, n.inputs["Factor"])
    nt.links.new(color_socket, n.inputs["B"])
    return n.outputs["Result"]


def _add_color(nt, a_socket, b_socket):
    """RGB add via ShaderNodeMix(RGBA, ADD, Fac=1)."""
    n = nt.nodes.new("ShaderNodeMix")
    n.data_type = "RGBA"
    n.blend_type = "ADD"
    n.inputs["Factor"].default_value = 1.0
    nt.links.new(a_socket, n.inputs["A"])
    nt.links.new(b_socket, n.inputs["B"])
    return n.outputs["Result"]


def _weighted_sum_colors(nt, weight_socket_pairs):
    """Build a convex-combination shader: sum_i (w_i * tex_i).

    Splat weights are normalised in compute_splat_weights so they sum
    to 1 — using a weighted sum (not iterative MIX) avoids the issue
    where the "base" texture leaves residual contribution at every
    layer above it.
    """
    acc = None
    for weight, color in weight_socket_pairs:
        scaled = _scale_color(nt, weight, color)
        acc = scaled if acc is None else _add_color(nt, acc, scaled)
    return acc


def _mix_value(nt, factor_socket, a_socket, b_socket):
    """Same as _mix_color but for scalar values via Math.MULTIPLY_ADD;
    used for roughness blending where Mix RGB would treat the input
    as RGB. Implemented as: out = a*(1-f) + b*f."""
    one_minus = nt.nodes.new("ShaderNodeMath"); one_minus.operation = "SUBTRACT"
    one_minus.inputs[0].default_value = 1.0
    nt.links.new(factor_socket, one_minus.inputs[1])
    a_scaled = nt.nodes.new("ShaderNodeMath"); a_scaled.operation = "MULTIPLY"
    nt.links.new(a_socket, a_scaled.inputs[0])
    nt.links.new(one_minus.outputs[0], a_scaled.inputs[1])
    b_scaled = nt.nodes.new("ShaderNodeMath"); b_scaled.operation = "MULTIPLY"
    nt.links.new(b_socket, b_scaled.inputs[0])
    nt.links.new(factor_socket, b_scaled.inputs[1])
    add = nt.nodes.new("ShaderNodeMath"); add.operation = "ADD"
    nt.links.new(a_scaled.outputs[0], add.inputs[0])
    nt.links.new(b_scaled.outputs[0], add.inputs[1])
    return add.outputs[0]


def build_realistic_terrain_material(name: str = "eroded_terrain_realistic",
                                     seed: int = 0):
    """Construct a Cycles-friendly PBR shader that blends the 5 biome
    texture sets via the ``Splat`` / ``Splat2`` vertex attributes.

    Topology:
      coord(Generated) → mapping(scale 0.04) → 5× (diff/normal/rough)
        ↓
      diff blend chain: sand → grass → forest → rock → snow
        ↓
      voronoi macro overlay (Mix multiply, 0.18 strength)
        ↓
      Principled BSDF.Base Color
      Principled BSDF.Normal ← blended normals
      Principled BSDF.Roughness ← blended roughness

    Splat weights are normalised in ``compute_splat_weights`` so they
    sum to 1, so the chain ``mix(rock, snow, snow_w)`` produces a
    correct per-pixel blend with the upstream order being the "base
    layer" everywhere snow_w == 0.

    Returns the new ``bpy.types.Material``.
    """
    import bpy

    # Per-seed material name — distinct seeds get distinct materials so
    # two scenes with different rolls don't share a cached one.
    full_name = f"{name}_s{int(seed) & 0xFFFF}"
    mat = bpy.data.materials.get(full_name)
    if mat is not None:
        return mat
    sets = _pick_biome_sets(int(seed))
    mat = bpy.data.materials.new(full_name)
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        if n.type != "OUTPUT_MATERIAL":
            nt.nodes.remove(n)
    out = nt.nodes["Material Output"]

    # Box-projection coords. Object coords span [-size, +size]; the
    # mapping scale chooses how many texture tiles fit across the
    # world. Scale 0.08 ⇒ ~13 wraps across a 160 BU world ⇒ each
    # tile is ~12 BU — small enough that 1k textures resolve detail
    # at near-camera distance, big enough that tiling isn't an
    # obvious checker pattern. The macro Voronoi overlay below
    # further breaks any leftover tile rhythm.
    coord = nt.nodes.new("ShaderNodeTexCoord")
    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (0.08, 0.08, 0.08)
    nt.links.new(coord.outputs["Object"], mapping.inputs["Vector"])
    map_out = mapping.outputs["Vector"]

    # Per-biome branches — pass the rolled set for this scene.
    sand_d,   sand_n,   sand_r   = _build_biome_branch(nt, "sand",   map_out, 0.7, sets)
    grass_d,  grass_n,  grass_r  = _build_biome_branch(nt, "grass",  map_out, 0.9, sets)
    forest_d, forest_n, forest_r = _build_biome_branch(nt, "forest", map_out, 1.0, sets)
    rock_d,   rock_n,   rock_r   = _build_biome_branch(nt, "rock",   map_out, 1.2, sets)
    snow_d,   snow_n,   snow_r   = _build_biome_branch(nt, "snow",   map_out, 0.6, sets)

    # Splat weights from the two FLOAT_COLOR vertex attributes.
    # ShaderNodeVertexColor (a.k.a. Color Attribute node) is the one
    # purpose-built for reading domain=POINT color attributes; it
    # handles interpolation to face-corners correctly.
    splat = nt.nodes.new("ShaderNodeVertexColor"); splat.layer_name = "Splat"
    sep   = nt.nodes.new("ShaderNodeSeparateColor"); sep.mode = "RGB"
    nt.links.new(splat.outputs["Color"], sep.inputs[0])
    splat2 = nt.nodes.new("ShaderNodeVertexColor"); splat2.layer_name = "Splat2"
    sep2  = nt.nodes.new("ShaderNodeSeparateColor"); sep2.mode = "RGB"
    nt.links.new(splat2.outputs["Color"], sep2.inputs[0])

    grass_w  = sep.outputs["Red"]
    forest_w = sep.outputs["Green"]
    rock_w   = sep.outputs["Blue"]
    snow_w   = splat.outputs["Alpha"]   # Splat.A = snow weight
    sand_w   = sep2.outputs["Red"]      # Splat2.R = sand weight

    # Diffuse blend — proper weighted sum across all 5 biomes since
    # splat weights are normalised to sum to 1.
    base = _weighted_sum_colors(nt, [
        (sand_w,   sand_d),
        (grass_w,  grass_d),
        (forest_w, forest_d),
        (rock_w,   rock_d),
        (snow_w,   snow_d),
    ])

    # Voronoi macro-color overlay — breaks 1k tiling at the ~6 BU
    # scale. Multiplied at low intensity (0.85..1.10 range).
    voronoi = nt.nodes.new("ShaderNodeTexVoronoi")
    voronoi.feature = "DISTANCE_TO_EDGE"
    voronoi.inputs["Scale"].default_value = 0.18
    nt.links.new(coord.outputs["Object"], voronoi.inputs["Vector"])
    vor_ramp = nt.nodes.new("ShaderNodeValToRGB")
    vor_ramp.color_ramp.elements[0].position = 0.0
    vor_ramp.color_ramp.elements[0].color = (0.85, 0.85, 0.85, 1.0)
    vor_ramp.color_ramp.elements[1].position = 1.0
    vor_ramp.color_ramp.elements[1].color = (1.10, 1.10, 1.10, 1.0)
    nt.links.new(voronoi.outputs["Distance"], vor_ramp.inputs["Fac"])
    macro_mul = nt.nodes.new("ShaderNodeMixRGB")
    macro_mul.blend_type = "MULTIPLY"
    macro_mul.inputs["Fac"].default_value = 1.0
    nt.links.new(base, macro_mul.inputs["Color1"])
    nt.links.new(vor_ramp.outputs["Color"], macro_mul.inputs["Color2"])

    # Roughness — weighted sum (treated as grayscale color).
    rough = _weighted_sum_colors(nt, [
        (sand_w,   sand_r),
        (grass_w,  grass_r),
        (forest_w, forest_r),
        (rock_w,   rock_r),
        (snow_w,   snow_r),
    ])

    # Normal blend — weighted sum on the per-biome normals. Not the
    # mathematically perfect normal blend (RNM/UDN would be), but at
    # PS3-era polycount + low sun angle it reads cleanly.
    normal = _weighted_sum_colors(nt, [
        (sand_w,   sand_n),
        (grass_w,  grass_n),
        (forest_w, forest_n),
        (rock_w,   rock_n),
        (snow_w,   snow_n),
    ])

    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(macro_mul.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(rough,  bsdf.inputs["Roughness"])
    nt.links.new(normal, bsdf.inputs["Normal"])
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = 0.15
    elif "Specular" in bsdf.inputs:
        bsdf.inputs["Specular"].default_value = 0.15

    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def bake_realistic_for_export(obj, size: float, resolution: int = 2048) -> bool:
    """Bake the realistic shader to flat 2D textures so glTF export
    captures the actual look.

    The procedural Voronoi macro overlay + per-vertex Splat blends in
    ``build_realistic_terrain_material`` don't survive ``export_scene.gltf``
    — only Image Texture nodes wired straight into Principled BSDF do.
    This helper:

      1. Creates a single-island planar UV (top-down projection for the
         heightmap mesh — no seams, even sampling).
      2. Bakes Cycles passes (color / normal tangent-space / roughness)
         to three blank images at ``resolution × resolution``.
      3. Packs the baked images into the .blend so the glTF exporter
         embeds them directly.
      4. Replaces the procedural material with an exportable Principled
         BSDF that reads the baked maps.

    Returns True on success, False if Cycles isn't available or the bake
    step fails (caller keeps the live procedural material).

    Trade-off: the baked diffuse loses high-frequency tile detail (a
    2k bake over a 160 BU world is ~12 BU per texel, vs the live
    shader's effective ~13 wraps × 1k texels). Acceptable for the
    browser, where the 5-set splat shader couldn't run anyway.
    """
    import bpy

    if obj is None or obj.type != "MESH":
        return False
    me = obj.data
    if not me.materials or me.materials[0] is None:
        return False

    # 1. Planar top-down UV. Build per-loop UVs from each loop's vertex.
    if "UVMap" in me.uv_layers:
        me.uv_layers.remove(me.uv_layers["UVMap"])
    uv = me.uv_layers.new(name="UVMap")
    span = 2.0 * float(size)
    # Vectorized fill via foreach_set — per-loop array of 2 floats.
    import numpy as np
    n_loops = len(me.loops)
    loop_v_idx = np.zeros(n_loops, dtype=np.int32)
    me.loops.foreach_get("vertex_index", loop_v_idx)
    n_verts = len(me.vertices)
    v_co = np.zeros(n_verts * 3, dtype=np.float32)
    me.vertices.foreach_get("co", v_co)
    v_co = v_co.reshape(n_verts, 3)
    uvs = np.empty((n_loops, 2), dtype=np.float32)
    uvs[:, 0] = (v_co[loop_v_idx, 0] + size) / span
    uvs[:, 1] = (v_co[loop_v_idx, 1] + size) / span
    uv.data.foreach_set("uv", uvs.ravel())

    # 2. Empty bake target images. Float buffer for normals so we don't
    # quantise to 8 bits before Principled reads them.
    res = int(resolution)
    img_diff = bpy.data.images.new("terrain_baked_diffuse", res, res, alpha=False)
    img_diff.colorspace_settings.name = "sRGB"
    # Normal map at 8-bit — standard for game/web pipelines. Float
    # buffer would 3× the GLB size for marginal precision gain.
    img_norm = bpy.data.images.new("terrain_baked_normal", res, res, alpha=False)
    img_norm.colorspace_settings.name = "Non-Color"
    img_rough = bpy.data.images.new("terrain_baked_roughness", res, res, alpha=False)
    img_rough.colorspace_settings.name = "Non-Color"

    # 3. Wire a temporary Image Texture node into the live material.
    # Cycles bake writes into whichever IMAGE_TEXTURE node is selected
    # & active in the material's node tree.
    mat = me.materials[0]
    nt = mat.node_tree
    bake_tex = nt.nodes.new("ShaderNodeTexImage")
    for n in nt.nodes:
        n.select = False
    bake_tex.select = True
    nt.nodes.active = bake_tex

    # 4. Configure Cycles + run the three bakes.
    sc = bpy.context.scene
    prev_engine = sc.render.engine
    sc.render.engine = "CYCLES"
    # Bake quality — keep it modest; the input shader is already PBR.
    prev_samples = sc.cycles.samples
    sc.cycles.samples = 4
    bake_settings = sc.render.bake

    prev_active = bpy.context.view_layer.objects.active
    prev_selected = list(bpy.context.selected_objects)
    try:
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

        # Diffuse — only the color pass, no direct/indirect light.
        bake_tex.image = img_diff
        bake_settings.use_pass_direct = False
        bake_settings.use_pass_indirect = False
        bake_settings.use_pass_color = True
        bpy.ops.object.bake(type="DIFFUSE")

        # Normal — tangent-space, matches what NormalMap node expects.
        bake_tex.image = img_norm
        bake_settings.normal_space = "TANGENT"
        bpy.ops.object.bake(type="NORMAL")

        # Roughness.
        bake_tex.image = img_rough
        bpy.ops.object.bake(type="ROUGHNESS")
    except RuntimeError as exc:
        print(f"[terrain bake] failed: {exc}")
        nt.nodes.remove(bake_tex)
        sc.render.engine = prev_engine
        sc.cycles.samples = prev_samples
        return False
    finally:
        sc.cycles.samples = prev_samples
        sc.render.engine = prev_engine
        bpy.ops.object.select_all(action="DESELECT")
        for o in prev_selected:
            try:
                o.select_set(True)
            except (ReferenceError, RuntimeError):
                pass
        bpy.context.view_layer.objects.active = prev_active

    # Pack the bake outputs so the .blend ships them and glTF embeds them.
    for img in (img_diff, img_norm, img_rough):
        try:
            img.pack()
        except Exception as exc:
            print(f"[terrain bake] pack {img.name} skipped: {exc}")

    # 5. Build a flat exportable material and swap it in.
    flat = bpy.data.materials.new("eroded_terrain_baked")
    flat.use_nodes = True
    fnt = flat.node_tree
    for n in list(fnt.nodes):
        if n.type != "OUTPUT_MATERIAL":
            fnt.nodes.remove(n)
    out = fnt.nodes["Material Output"]
    bsdf = fnt.nodes.new("ShaderNodeBsdfPrincipled")

    diff_n = fnt.nodes.new("ShaderNodeTexImage"); diff_n.image = img_diff
    fnt.links.new(diff_n.outputs["Color"], bsdf.inputs["Base Color"])

    norm_n = fnt.nodes.new("ShaderNodeTexImage"); norm_n.image = img_norm
    nm = fnt.nodes.new("ShaderNodeNormalMap")
    fnt.links.new(norm_n.outputs["Color"], nm.inputs["Color"])
    fnt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])

    rough_n = fnt.nodes.new("ShaderNodeTexImage"); rough_n.image = img_rough
    fnt.links.new(rough_n.outputs["Color"], bsdf.inputs["Roughness"])

    fnt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    me.materials.clear()
    me.materials.append(flat)
    return True

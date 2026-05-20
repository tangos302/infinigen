"""Named factory presets — bundles of kwargs the LLM can request by name.

Pattern: ``factory_from_preset(LowPolyWatchtowerFactory, "lighthouse", 7)``
instead of ``LowPolyWatchtowerFactory(factory_seed=7,
watchtower_archetype="round_stone", shaft_radius=0.7, shaft_height=6.0,
crenel_count=0, ...)``. The LLM (or build script) doesn't need to know
each factory's knob names — it picks a vibe and the preset does the
rest.

Why this exists: every factory already accepts named-slot color kwargs
and dimensions, so "more variation" doesn't need new factory code, it
needs *coherent param bundles* surfaced as named menu items. One
preset is ~5-15 lines of dict literal. Two dozen presets = 2-3x the
variety the catalog ships today.

Adding a preset:
  - Append an entry to the per-factory dict below
  - Comment line should describe the *look* (what reads from a render),
    not the param values
  - Pick palette keys from infinigen.maquette.palette.MAQUETTE_PALETTE
    (don't invent new hex colors here — the palette is the design system)
  - All presets should override factory_seed via the caller, not bake one in

The keys here mirror the factory class names exactly so a static
analysis pass can validate every preset against the factory signature
without import-side-effects (see ``validate_presets`` below).
"""

from __future__ import annotations

from typing import Any


FactoryPresets = dict[str, dict[str, Any]]
"""{preset_name: kwargs} for one factory."""


# ============================================================================
#   NEW FACTORIES (shipped 2026-05-16)
# ============================================================================

# Stone watchtower — round_stone or square_keep. Variation across presets
# comes from: shaft proportions, crenellation count, roof presence, color.
WATCHTOWER_PRESETS: FactoryPresets = {
    "ancient_ruin": dict(
        watchtower_archetype="round_stone",
        shaft_radius=1.20, shaft_height=3.20,  # shorter — partially collapsed
        n_sides=10,
        crenel_height=0.32, crenel_count=5,    # missing teeth, irregular feel
        roof_height=0.0, roof_overhang=0.0,    # roof long gone
        door_width=0.50, door_height=0.95,
        stone_color="rock_shadow", wood_color="wood",
    ),
    "lighthouse": dict(
        watchtower_archetype="round_stone",
        shaft_radius=0.75, shaft_height=6.50,  # tall + slim silhouette
        n_sides=12,                            # smoother cylinder
        crenel_height=0.20, crenel_count=0,    # no battlements
        roof_height=1.20, roof_overhang=0.55,  # wide overhang = "lamp room"
        door_width=0.55, door_height=1.20,
        stone_color="stucco", wood_color="wood", roof_color="accent_red",
    ),
    "siege_tower": dict(
        watchtower_archetype="square_keep",
        shaft_radius=1.40, shaft_height=5.60,
        crenel_height=0.55, crenel_count=14,   # dense battlements
        door_width=0.80, door_height=1.55,
        stone_color="wood", wood_color="rust_metal",  # wooden siege rig
    ),
}

# Zen garden gate — roofed_wood, simple_post, or hagi_arch. Variation:
# archetype × color story × proportions.
ZEN_GARDEN_GATE_PRESETS: FactoryPresets = {
    "weathered_temple": dict(
        zen_gate_archetype="roofed_wood",
        span=1.80, post_height=2.30, post_thickness=0.22,
        roof_overhang=0.45, roof_pitch=0.35,
        wing_length=1.50, wing_height=0.60,
        wood_color="rock_shadow", roof_color="rock_shadow", base_color="rock_pale",
    ),
    "festival_gate": dict(
        zen_gate_archetype="roofed_wood",
        span=1.60, post_height=2.10, post_thickness=0.20,
        roof_overhang=0.40, roof_pitch=0.28,
        wing_length=1.20, wing_height=0.50,
        wood_color="accent_red", roof_color="rock_shadow", base_color="stucco",
    ),
    "mountain_path": dict(
        zen_gate_archetype="hagi_arch",
        span=1.30, post_height=2.00, post_thickness=0.14,
        wood_color="wood",
    ),
    "tea_house": dict(
        zen_gate_archetype="simple_post",
        span=1.20, post_height=1.70, post_thickness=0.13,
        beam_thickness=0.15,
        wood_color="wood",
    ),
}

# Japanese stone lantern (tōrō) — tachi_gata (tall formal) or yukimi_gata
# (snow-viewing). Variation: archetype × stone weathering color.
STONE_LANTERN_PRESETS: FactoryPresets = {
    "moss_garden": dict(
        lantern_archetype="tachi_gata",
        n_sides=6,
        stone_color="ground_grass",  # green-tinged weathered granite
        glow_color="stucco",
    ),
    "formal_avenue": dict(
        lantern_archetype="tachi_gata",
        n_sides=8,                   # smoother octagonal — formal/clean
        stone_color="rock_pale",
        glow_color="sky_warm",       # warm dusk glow
    ),
    "snow_garden": dict(
        lantern_archetype="yukimi_gata",
        n_sides=6,
        stone_color="rock_pale",
        glow_color="stucco",
    ),
    "ash_temple": dict(
        lantern_archetype="tachi_gata",
        n_sides=6,
        stone_color="rock_shadow",   # blackened volcanic
        glow_color="accent_red",     # ember glow
    ),
    "kasuga_avenue": dict(
        lantern_archetype="kasuga",
        n_sides=6,
        stone_color="rock_pale",
        glow_color="sky_warm",
    ),
    "oki_garden": dict(
        lantern_archetype="oki_gata",
        n_sides=6,
        stone_color="ground_grass",  # mossy weathered stone
        glow_color="stucco",
    ),
}

# Desert cactus — saguaro, barrel, a slim columnar stem, an old four-armed
# saguaro. (Thin-factory deepening pass: cactus went 2 -> 4 archetypes.)
CACTUS_PRESETS: FactoryPresets = {
    "desert_saguaro": dict(
        cactus_archetype="saguaro",
    ),
    "barrel_cactus": dict(
        cactus_archetype="barrel",
    ),
    "column_cactus": dict(
        cactus_archetype="column_cactus",
    ),
    "old_saguaro": dict(
        cactus_archetype="branching",
    ),
}

# Campfire / ember light source — actual point light + emission material.
CAMPFIRE_PRESETS: FactoryPresets = {
    "traveler_camp": dict(
        campfire_archetype="stone_ring",
        radius=0.82,
        stone_count=11,
        log_count=3,
        flame_color="foliage_amber",
        light_energy=120.0,
        light_radius=2.2,
    ),
    "bright_hearth": dict(
        campfire_archetype="log_pile",
        radius=0.72,
        stone_count=6,
        log_count=4,
        flame_color="foliage_lemon",
        light_energy=150.0,
        light_radius=2.5,
    ),
    "dying_embers": dict(
        campfire_archetype="ember_bed",
        radius=0.64,
        stone_count=8,
        log_count=2,
        flame_color="accent_red",
        light_energy=48.0,
        light_radius=1.35,
        emission_strength=2.8,
    ),
}

TORCH_PRESETS: FactoryPresets = {
    "village_path": dict(
        torch_archetype="pole",
        height=2.05,
        flame_color="foliage_amber",
        light_energy=72.0,
    ),
    "castle_wall": dict(
        torch_archetype="wall_sconce",
        height=1.0,
        metal_color="rust_metal",
        flame_color="foliage_lemon",
        light_energy=62.0,
    ),
    "camp_tripod": dict(
        torch_archetype="tripod",
        height=1.45,
        flame_color="foliage_amber",
        light_energy=88.0,
    ),
}

CANDLE_CLUSTER_PRESETS: FactoryPresets = {
    "altar_three": dict(
        candle_archetype="three_candles",
        candle_count=3,
        wax_color="stucco",
        flame_color="foliage_lemon",
    ),
    "chapel_row": dict(
        candle_archetype="altar_row",
        candle_count=6,
        wax_color="stucco",
        holder_color="rust_metal",
    ),
    "melted_crypt": dict(
        candle_archetype="melted_cluster",
        candle_count=8,
        wax_color="rock_pale",
        flame_color="foliage_amber",
        light_energy=34.0,
    ),
}

STRING_LIGHTS_PRESETS: FactoryPresets = {
    "market_evening": dict(
        lights_archetype="market_span",
        span=5.8,
        height=2.45,
        bulb_count=6,
        sag=0.34,
        glow_color="foliage_lemon",
        light_energy=72.0,
    ),
    "festival_square": dict(
        lights_archetype="festival_arc",
        span=7.4,
        height=2.85,
        bulb_count=8,
        sag=0.56,
        glow_color="sky_warm",
        light_energy=92.0,
    ),
    "camp_rope": dict(
        lights_archetype="camp_line",
        span=3.9,
        height=1.85,
        bulb_count=5,
        sag=0.28,
        glow_color="foliage_amber",
        light_energy=46.0,
    ),
}

# Hanging bell — temple (big + roofed), belfry (big + bare), cattle (small).
# Variation: archetype × bronze patina × roof presence.
BELL_PRESETS: FactoryPresets = {
    "monastery": dict(
        bell_archetype="temple",
        n_sides=12,                   # smoother bell silhouette
        bronze_color="rust_metal",
        wood_color="wood",
        roof_color="rock_shadow",
    ),
    "village_alarm": dict(
        bell_archetype="belfry",
        n_sides=10,
        bronze_color="rust_metal",
        wood_color="wood",
    ),
    "ceremonial": dict(
        bell_archetype="temple",
        n_sides=14,                   # very smooth — ornate
        bronze_color="accent_red",    # painted/lacquered
        wood_color="rock_shadow",     # dark stained frame
        roof_color="accent_red",
    ),
    "weathered_cattle": dict(
        bell_archetype="cattle",
        n_sides=8,
        bronze_color="wood",          # rusted-to-brown
        wood_color="wood",
    ),
}


# ============================================================================
#   BLACKSMITH KIT (shipped 2026-05-20)
# ============================================================================

# Blacksmith's forge — masonry hearth with a glowing coal bed + point light.
# Variation: archetype (open hearth / chimney workshop / portable pan) ×
# fire temperature × soot.
FORGE_PRESETS: FactoryPresets = {
    "village_smithy": dict(
        forge_archetype="stone_hearth",
        masonry_color="rock_cool",
        flame_color="foliage_amber",
        light_energy=150.0,
    ),
    "workshop_forge": dict(
        forge_archetype="brick_chimney",
        masonry_color="rock_warm",          # red brick flue
        flame_color="foliage_lemon",        # hotter, brighter fire
        light_energy=170.0,
    ),
    "farrier_camp": dict(
        forge_archetype="open_field_forge",
        flame_color="foliage_amber",
        light_energy=95.0,
        light_radius=1.9,
    ),
    "banked_coals": dict(
        forge_archetype="stone_hearth",
        masonry_color="rock_shadow",        # soot-blackened stone
        flame_color="accent_red",           # fire banked low to red embers
        light_energy=58.0,
        light_radius=1.5,
        emission_strength=3.0,
    ),
}

# Smithy yard props — anvil, quench trough, grindstone, tool rack, coal
# pile. One preset per archetype; the factory seed drives size variation.
SMITHY_PROPS_PRESETS: FactoryPresets = {
    "working_anvil": dict(
        prop_archetype="anvil",
    ),
    "cooling_trough": dict(
        prop_archetype="quench_trough",
        wood_color="wood",
    ),
    "sharpening_wheel": dict(
        prop_archetype="grindstone",
        stone_color="rock_pale",            # pale sandstone wheel
    ),
    "smith_tools": dict(
        prop_archetype="tool_rack",
    ),
    "coke_heap": dict(
        prop_archetype="coal_pile",
        coal_color="rock_shadow",
    ),
}


# ============================================================================
#   GARDEN VEGETATION (shipped 2026-05-21)
# ============================================================================

# Bamboo — segmented culms in groves, accent stalks, arched groves, and
# lashed garden screens. Variation: archetype × culm colour (green / golden).
BAMBOO_PRESETS: FactoryPresets = {
    "garden_grove": dict(
        bamboo_archetype="grove_clump",
    ),
    "golden_grove": dict(
        bamboo_archetype="grove_clump",
        culm_color="ground_sand",           # golden bamboo cultivar
        foliage_color="foliage_lemon",
    ),
    "path_accent": dict(
        bamboo_archetype="single_stalk",
    ),
    "windswept_grove": dict(
        bamboo_archetype="bent_arch",
    ),
    "garden_screen": dict(
        bamboo_archetype="bamboo_screen",
    ),
}

# Wetland reeds — pond, stream, oasis, and marsh edges. Variation:
# archetype × fresh-green vs dried-straw colouring.
REEDS_PRESETS: FactoryPresets = {
    "cattail_stand": dict(
        reed_archetype="cattail_clump",
    ),
    "marsh_reeds": dict(
        reed_archetype="tall_reeds",
    ),
    "dry_reeds": dict(
        reed_archetype="tall_reeds",
        stem_color="ground_sand",           # dried autumn reeds
        head_color="stucco",
    ),
    "bulrush_clump": dict(
        reed_archetype="bulrush",
    ),
    "papyrus_stand": dict(
        reed_archetype="papyrus",
    ),
}


# ============================================================================
#   VOLCANIC BIOME (shipped 2026-05-21)
# ============================================================================

# Molten lava features — pools, rifts, flows, fumaroles. Each emits a
# low-strength glow plus a parented point light.
LAVA_PRESETS: FactoryPresets = {
    "magma_pool": dict(
        lava_archetype="lava_pool",
    ),
    "lava_rift": dict(
        lava_archetype="lava_crack",
    ),
    "basalt_flow": dict(
        lava_archetype="cooled_flow",
        lava_color="accent_red",            # older, cooler flow
    ),
    "fumarole_vent": dict(
        lava_archetype="fumarole",
    ),
}

# Cooled volcanic rock — basalt columns, obsidian, cinder cones, boulders.
VOLCANIC_ROCK_PRESETS: FactoryPresets = {
    "basalt_columns": dict(
        volcanic_archetype="basalt_column",
    ),
    "obsidian_shards": dict(
        volcanic_archetype="obsidian_cluster",
    ),
    "scoria_cone": dict(
        volcanic_archetype="cinder_cone",
        accent_color="rock_warm",           # rust-red oxidised cinder
    ),
    "lava_boulder": dict(
        volcanic_archetype="cracked_boulder",
    ),
}


# ============================================================================
#   MARKET & GARDEN (shipped 2026-05-21)
# ============================================================================

# Stone fountains with translucent water basins — plaza centrepiece,
# village square, wall-mounted, and zen tsukubai.
FOUNTAIN_PRESETS: FactoryPresets = {
    "plaza_fountain": dict(
        fountain_archetype="tiered_basin",
    ),
    "village_well_fountain": dict(
        fountain_archetype="village_basin",
    ),
    "wall_fountain": dict(
        fountain_archetype="wall_spout",
    ),
    "zen_water_basin": dict(
        fountain_archetype="bamboo_basin",
    ),
}


# ============================================================================
#   TERRAIN WATER (shipped 2026-05-21)
# ============================================================================

# Waterfalls — vertical water for steep alpine and jungle terrain, where
# LowPolyWaterSurfaceFactory only offered flat water.
WATERFALL_PRESETS: FactoryPresets = {
    "cliff_waterfall": dict(
        waterfall_archetype="cliff_fall",
    ),
    "rocky_cascade": dict(
        waterfall_archetype="cascade",
    ),
    "tiered_falls": dict(
        waterfall_archetype="multi_tier",
    ),
    "mountain_spring": dict(
        waterfall_archetype="spring_source",
    ),
}


# ============================================================================
#   GROUND VEGETATION (shipped 2026-05-21)
# ============================================================================

# Shrubs and ferns — low ground vegetation for jungle understorey,
# temperate hedgerows, and desert scrub.
SHRUB_PRESETS: FactoryPresets = {
    "garden_bush": dict(
        shrub_archetype="round_bush",
    ),
    "flowering_shrub": dict(
        shrub_archetype="flowering_bush",
    ),
    "jungle_fern": dict(
        shrub_archetype="forest_fern",
    ),
    "dead_shrub": dict(
        shrub_archetype="dead_bush",
    ),
    "desert_scrub": dict(
        shrub_archetype="desert_scrub",
    ),
}

# Wooden furniture — seating and tables for markets, taverns, gardens.
FURNITURE_PRESETS: FactoryPresets = {
    "tavern_bench": dict(
        furniture_archetype="bench",
    ),
    "trestle_table": dict(
        furniture_archetype="trestle_table",
    ),
    "round_stool": dict(
        furniture_archetype="stool",
    ),
    "market_counter": dict(
        furniture_archetype="market_counter",
    ),
}

# Market wares — goods that fill stalls and counters.
MARKET_GOODS_PRESETS: FactoryPresets = {
    "fruit_pile": dict(
        goods_archetype="produce_pile",
    ),
    "clay_pots": dict(
        goods_archetype="pottery_stack",
    ),
    "grain_sacks": dict(
        goods_archetype="sack_cluster",
    ),
    "woven_baskets": dict(
        goods_archetype="basket_group",
    ),
}

# Natural rock landmarks — arches, sea stacks, balanced rocks.
NATURAL_ARCH_PRESETS: FactoryPresets = {
    "desert_arch": dict(
        formation_archetype="desert_arch",
    ),
    "sea_arch": dict(
        formation_archetype="sea_arch",
    ),
    "sea_stack": dict(
        formation_archetype="sea_stack",
    ),
    "balanced_rock": dict(
        formation_archetype="balanced_rock",
    ),
}

# East Asian temple buildings — pagodas, halls, pavilions, shrines.
PAGODA_PRESETS: FactoryPresets = {
    "red_pagoda": dict(
        pagoda_archetype="tiered_pagoda",
    ),
    "temple_hall": dict(
        pagoda_archetype="temple_hall",
    ),
    "tea_pavilion": dict(
        pagoda_archetype="garden_pavilion",
    ),
    "wayside_shrine": dict(
        pagoda_archetype="shrine",
    ),
}

# Path / road / stair segments — give a scene routes and direction.
PATH_PRESETS: FactoryPresets = {
    "village_path": dict(
        path_archetype="dirt_path",
    ),
    "cobbled_street": dict(
        path_archetype="cobbled_road",
    ),
    "garden_steps": dict(
        path_archetype="stone_steps",
    ),
    "gravel_track": dict(
        path_archetype="gravel_lane",
    ),
}


# ============================================================================
#   EXISTING FACTORIES — preset bundles add variation without new code
# ============================================================================

# Cottage / house — gabled/hipped/flat × biome color × ruin level.
HOUSE_PRESETS: FactoryPresets = {
    "cottage_thatched": dict(
        building_archetype="cottage",
        roof_archetype="gabled",
        width=3.6, depth=2.8, wall_height=2.2,
        roof_height=1.4, n_windows=3,
        wall_color="stucco", roof_color="ground_grass",  # straw/thatch read
        accent_color="wood",
        window_glow=True, window_glow_color="sky_warm",
        window_emission_strength=1.25,
    ),
    "ruined": dict(
        building_archetype="cottage",
        roof_archetype="flat",                            # collapsed roof
        width=3.2, depth=2.6, wall_height=1.4,            # partially collapsed
        roof_height=0.2, n_windows=1,
        wall_color="rock_shadow", roof_color="rock_shadow",
        accent_color="rust_metal",
    ),
    "snowbound": dict(
        building_archetype="cottage",
        roof_archetype="gabled",
        width=3.8, depth=3.0, wall_height=2.4,
        roof_height=1.8, n_windows=2,                     # fewer windows = cold
        wall_color="wood", roof_color="stucco",           # snow on roof
        accent_color="wood",
        window_glow=True, window_glow_color="foliage_lemon",
        window_emission_strength=1.15,
    ),
    "desert_adobe": dict(
        building_archetype="cottage",
        roof_archetype="flat",
        width=4.0, depth=3.2, wall_height=2.6,
        roof_height=0.2, n_windows=2,
        wall_color="ground_sand", roof_color="rock_warm",
        accent_color="rock_shadow",
        window_glow=True, window_glow_color="foliage_amber",
        window_emission_strength=1.1,
    ),
    "coastal_painted": dict(
        building_archetype="cottage",
        roof_archetype="hipped",
        width=3.6, depth=2.8, wall_height=2.2,
        roof_height=1.0, n_windows=3,
        wall_color="sky_cool",                            # painted clapboard
        roof_color="accent_red",
        accent_color="stucco",
        window_glow=True, window_glow_color="sky_warm",
        window_emission_strength=1.2,
    ),
}

# Boulder — three weathering states. Variation comes from polygon_multiplier
# (chunkier vs denser) + palette swap.
BOULDER_PRESETS: FactoryPresets = {
    "charred": dict(
        polygon_multiplier=1.0,
    ),
    "mossy": dict(
        polygon_multiplier=1.2,                           # slightly rounder
    ),
    "bleached": dict(
        polygon_multiplier=0.9,                           # blockier, weathered
    ),
}

# Tree — sapling-derived. Variation comes from trunk architecture plus
# crown grammar (pine stack, broadleaf lobes, cypress column, windswept
# crown, dead snag).
TREE_PRESETS: FactoryPresets = {
    "lush_pine": dict(
        foliage_archetype="tiered_cones",
        trunk_height=7.0, trunk_segments=8,
        trunk_radius_base=0.22, trunk_radius_top=0.06,
        n_branch_layers=7,
        branch_lower_z_fraction=0.70,
        foliage_radius=1.65, foliage_height=3.1, foliage_layers=4,
        palette_color="foliage_pine",
    ),
    "dead_pine": dict(
        foliage_archetype="crystal",
        trunk_height=5.5, trunk_segments=6,
        trunk_archetype="curved", trunk_curve_amplitude=0.22,
        trunk_radius_base=0.17, trunk_radius_top=0.04,
        n_branch_layers=2,                                # sparse / dying
        branches_per_layer=(2, 3),
        branch_length=(0.65, 1.25),
        foliage_layers=1,
        foliage_radius=0.45, foliage_height=0.85,
        palette_color="rock_shadow",
        trunk_color="wood",
    ),
    "young_pine": dict(
        foliage_archetype="tiered_cones",
        trunk_height=3.6, trunk_segments=4,
        trunk_radius_base=0.12, trunk_radius_top=0.04,
        n_branch_layers=5,
        branch_lower_z_fraction=0.68,
        foliage_radius=0.95, foliage_height=1.9, foliage_layers=3,
        palette_color="foliage_bush",
    ),
    "ancient_pine": dict(
        foliage_archetype="tiered_cones",
        trunk_height=9.5, trunk_segments=10,
        trunk_archetype="curved", trunk_curve_amplitude=0.34,
        trunk_radius_base=0.34, trunk_radius_top=0.075,
        n_branch_layers=9,
        branch_lower_z_fraction=0.66,
        branches_per_layer=(4, 6),
        foliage_radius=1.95, foliage_height=4.2, foliage_layers=5,
        palette_color="foliage_pine",
    ),
    "round_oak": dict(
        foliage_archetype="leaf_cards",
        trunk_height=5.8, trunk_segments=7,
        trunk_radius_base=0.30, trunk_radius_top=0.09,
        n_branch_layers=7,
        branches_per_layer=(4, 7),
        branch_length=(0.9, 2.0),
        branch_droop=(0.02, 0.22),
        crown_z_fraction=0.32,
        branch_lower_z_fraction=0.34,
        foliage_radius=2.25, foliage_height=2.45,
        palette_color="foliage_bush",
        trunk_color="wood",
    ),
    "umbrella_acacia": dict(
        foliage_archetype="umbrella",
        trunk_height=5.2, trunk_segments=6,
        trunk_archetype="curved", trunk_curve_amplitude=0.45,
        trunk_radius_base=0.24, trunk_radius_top=0.075,
        n_branch_layers=5,
        branches_per_layer=(4, 6),
        branch_length=(0.95, 1.85),
        branch_droop=(0.0, 0.16),
        crown_z_fraction=0.58,
        branch_lower_z_fraction=0.52,
        foliage_radius=1.65, foliage_height=1.45,
        palette_color="foliage_lemon",
        trunk_color="wood",
    ),
    "columnar_cypress": dict(
        foliage_archetype="columnar",
        trunk_archetype="no_branch",
        trunk_height=7.8, trunk_segments=8,
        trunk_radius_base=0.20, trunk_radius_top=0.06,
        n_branch_layers=0,
        crown_z_fraction=0.18,
        foliage_radius=0.78, foliage_height=6.2,
        palette_color="foliage_pine",
        trunk_color="wood",
    ),
    "wind_bent_headland": dict(
        foliage_archetype="windswept",
        trunk_archetype="curved", trunk_curve_amplitude=0.62,
        trunk_height=5.8, trunk_segments=7,
        trunk_radius_base=0.23, trunk_radius_top=0.07,
        n_branch_layers=5,
        branches_per_layer=(3, 5),
        branch_length=(0.85, 1.75),
        branch_droop=(0.02, 0.26),
        crown_z_fraction=0.48,
        foliage_radius=1.7, foliage_height=2.2,
        palette_color="foliage_pine",
        trunk_color="wood",
    ),
    "low_scrub": dict(
        foliage_archetype="leaf_cards",
        trunk_archetype="no_branch",
        trunk_height=1.45, trunk_segments=4,
        trunk_radius_base=0.10, trunk_radius_top=0.045,
        n_branch_layers=0,
        crown_z_fraction=0.10,
        foliage_radius=0.72, foliage_height=0.82,
        palette_color="foliage_bush",
        trunk_color="wood",
    ),
    "bare_winter": dict(
        foliage_archetype="none",
        trunk_archetype="curved", trunk_curve_amplitude=0.18,
        trunk_height=5.9, trunk_segments=7,
        trunk_radius_base=0.21, trunk_radius_top=0.055,
        n_branch_layers=7,
        branches_per_layer=(3, 5),
        branch_length=(0.7, 1.65),
        branch_droop=(-0.18, 0.22),
        branch_taper=0.72,
        branch_lower_z_fraction=0.32,
        trunk_color="wood",
        palette_color="rock_shadow",
    ),
    "thin_sapling": dict(
        foliage_archetype="round_ball",
        trunk_height=2.4, trunk_segments=4,
        trunk_radius_base=0.055, trunk_radius_top=0.025,
        n_branch_layers=2,
        branches_per_layer=(2, 3),
        branch_length=(0.18, 0.38),
        branch_droop=(0.0, 0.18),
        branch_lower_z_fraction=0.76,
        crown_z_fraction=0.72,
        foliage_radius=0.42, foliage_height=0.70,
        palette_color="foliage_mint",
        trunk_color="wood",
    ),
    "baobab_savanna": dict(
        foliage_archetype="baobab_crown",
        trunk_height=5.4, trunk_segments=7,
        trunk_radius_base=0.72, trunk_radius_top=0.34,
        n_branch_layers=4,
        branches_per_layer=(4, 6),
        branch_length=(1.05, 2.25),
        branch_droop=(-0.28, 0.08),
        branch_taper=0.45,
        branch_lower_z_fraction=0.70,
        crown_z_fraction=0.74,
        foliage_radius=2.35, foliage_height=2.0,
        palette_color="foliage_amber",
        trunk_color="rock_warm",
    ),
    "weeping_willow": dict(
        foliage_archetype="weeping",
        trunk_archetype="curved", trunk_curve_amplitude=0.32,
        trunk_height=5.8, trunk_segments=7,
        trunk_radius_base=0.24, trunk_radius_top=0.075,
        n_branch_layers=5,
        branches_per_layer=(4, 6),
        branch_length=(0.75, 1.55),
        branch_droop=(0.18, 0.55),
        branch_taper=0.55,
        branch_lower_z_fraction=0.58,
        crown_z_fraction=0.48,
        foliage_radius=1.9, foliage_height=3.0,
        palette_color="foliage_mint",
        trunk_color="wood",
    ),
    "flowering_broadleaf": dict(
        foliage_archetype="leaf_cards",
        trunk_height=4.9, trunk_segments=6,
        trunk_radius_base=0.22, trunk_radius_top=0.075,
        n_branch_layers=6,
        branches_per_layer=(4, 6),
        branch_length=(0.8, 1.75),
        branch_droop=(0.0, 0.25),
        branch_lower_z_fraction=0.50,
        crown_z_fraction=0.30,
        foliage_radius=1.95, foliage_height=2.15,
        palette_color="foliage_rose",
        trunk_color="wood",
    ),
}

# Palm — archetype-specific presets for oasis/coastal/desert scenes. These
# deliberately expose *looks* the LLM can choose, not raw geometry trivia.
PALM_PRESETS: FactoryPresets = {
    "lush_oasis": dict(
        palm_archetype="oasis_palm",
        trunk_height=7.6,
        n_fronds=17,
        fruit_count=12,
        dead_fronds=2,
        frond_color="foliage_bush",
    ),
    "wind_bent_coastal": dict(
        palm_archetype="coastal_wind_bent",
        trunk_curve=2.9,
        crown_asymmetry=0.48,
        dead_fronds=3,
    ),
    "young_cluster": dict(
        palm_archetype="young_palm",
        trunk_height=2.6,
        n_fronds=7,
        fruit_count=0,
    ),
    "dead_dry": dict(
        palm_archetype="dead_palm",
        dead_fronds=8,
        fruit_count=0,
    ),
    "grove_medium": dict(
        palm_archetype="grove_palm",
        trunk_height=5.4,
        n_fronds=12,
        fruit_count=4,
    ),
}

# Chapel — civic/religious landmarks. Variation: village stone, alpine
# snow roof, and a broken ruin vignette.
CHAPEL_PRESETS: FactoryPresets = {
    "village_stone": dict(
        chapel_archetype="village_chapel",
        length=6.6,
        depth=3.3,
        tower_height=4.4,
        wall_color="rock_pale",
        roof_color="rock_shadow",
        wood_color="wood",
        window_color="water",
        accent_color="stucco",
    ),
    "alpine_snow": dict(
        chapel_archetype="alpine_chapel",
        length=5.8,
        depth=3.0,
        roof_height=2.0,
        tower_height=4.9,
        wall_color="stucco",
        roof_color="rock_pale",
        wood_color="rock_shadow",
        window_color="water",
        accent_color="rock_pale",
    ),
    "ruined_wayside": dict(
        chapel_archetype="ruined_chapel",
        length=6.1,
        depth=3.2,
        tower_height=2.9,
        wall_color="rock_warm",
        roof_color="rock_shadow",
        wood_color="wood",
        window_color="rock_shadow",
        accent_color="rock_pale",
    ),
}

# Stone bridge — heavier road/river crossing than the wooden deck/pier.
STONE_BRIDGE_PRESETS: FactoryPresets = {
    "village_arch": dict(
        stone_bridge_archetype="single_arch",
        length=8.9,
        width=2.5,
        deck_z=1.55,
        arch_radius=2.25,
        stone_color="rock_pale",
        cap_color="rock_warm",
    ),
    "wide_double": dict(
        stone_bridge_archetype="double_arch",
        length=11.6,
        width=2.75,
        deck_z=1.48,
        arch_radius=1.72,
        stone_color="rock_cool",
        cap_color="rock_pale",
    ),
    "broken_old": dict(
        stone_bridge_archetype="ruined_arch",
        length=8.4,
        width=2.25,
        deck_z=1.34,
        arch_radius=1.95,
        stone_color="rock_warm",
        cap_color="rock_pale",
    ),
}

# Watermill — river-side landmark, differentiated from windmills by the
# side water wheel and sluice trough.
WATERMILL_PRESETS: FactoryPresets = {
    "timber_river": dict(
        watermill_archetype="timber_river",
        width=4.4,
        depth=3.4,
        wall_color="wood",
        roof_color="rock_shadow",
        wheel_color="wood",
    ),
    "stone_river": dict(
        watermill_archetype="stone_river",
        width=4.9,
        depth=3.6,
        wheel_radius=1.38,
        wall_color="rock_pale",
        roof_color="rock_warm",
        wheel_color="wood",
    ),
    "half_timber": dict(
        watermill_archetype="half_timber_mill",
        width=4.65,
        depth=3.35,
        wall_color="stucco",
        roof_color="rock_shadow",
        wheel_color="wood",
        trough_color="rust_metal",
    ),
}

# Ruins — clustered archeological vignettes for desert, castle, temple,
# and abandoned settlement prompts.
RUIN_PRESETS: FactoryPresets = {
    "desert_columns": dict(
        ruin_archetype="column_scatter",
        radius=3.7,
        density=1.1,
        stone_color="rock_pale",
        shadow_color="rock_warm",
        accent_color="stucco",
    ),
    "broken_arch": dict(
        ruin_archetype="archway",
        radius=3.4,
        density=1.0,
        stone_color="rock_warm",
        shadow_color="rock_shadow",
        accent_color="rock_pale",
    ),
    "collapsed_wall": dict(
        ruin_archetype="broken_walls",
        radius=4.0,
        density=1.2,
        stone_color="rock_warm",
        shadow_color="rock_shadow",
        accent_color="rock_pale",
    ),
    "buried_obelisk": dict(
        ruin_archetype="obelisk_fragment",
        radius=3.5,
        density=1.1,
        stone_color="rock_pale",
        shadow_color="rock_shadow",
        accent_color="rock_warm",
    ),
}

# People — tiny settlement-life figures. Keep low-poly and sparse; use as
# accent objects near roads/plazas/farms, not dense crowds.
PEASANT_PRESETS: FactoryPresets = {
    "farmer_hat": dict(
        peasant_archetype="farmer",
        height=1.55,
        body_color="ground_sand",
        accent_color="wood",
        tool="hoe",
    ),
    "market_merchant": dict(
        peasant_archetype="merchant",
        height=1.50,
        body_color="accent_red",
        accent_color="stucco",
        tool="bundle",
    ),
    "town_guard": dict(
        peasant_archetype="guard",
        height=1.62,
        body_color="rock_shadow",
        accent_color="rust_metal",
        tool="spear",
    ),
    "village_child": dict(
        peasant_archetype="child",
        height=1.05,
        body_color="foliage_amber",
        accent_color="wood",
        tool="none",
    ),
}

# Docks — shoreline infrastructure for fishing villages and river towns.
DOCK_PRESETS: FactoryPresets = {
    "straight_fishing_pier": dict(
        dock_archetype="straight_pier",
        length=8.0,
        width=1.7,
        rail=True,
        cargo=2,
    ),
    "working_wharf": dict(
        dock_archetype="fishing_wharf",
        length=6.4,
        width=3.2,
        side_length=3.0,
        cargo=5,
    ),
    "l_shaped_landing": dict(
        dock_archetype="l_wharf",
        length=7.2,
        width=1.9,
        side_length=4.2,
        cargo=3,
    ),
    "broken_jetty": dict(
        dock_archetype="ruined_jetty",
        length=6.8,
        width=1.5,
        rail=False,
        cargo=1,
        broken=0.42,
    ),
}

# Town gates — threshold objects for roads entering settlements/castles.
TOWN_GATE_PRESETS: FactoryPresets = {
    "timber_palisade": dict(
        town_gate_archetype="timber_palisade",
        span=3.7,
        height=3.3,
        wood_color="wood",
    ),
    "stone_road_arch": dict(
        town_gate_archetype="stone_arch",
        span=3.6,
        height=3.8,
        stone_color="rock_pale",
        metal_color="rock_shadow",
    ),
    "watch_gate": dict(
        town_gate_archetype="watch_gate",
        span=4.2,
        height=4.4,
        wood_color="wood",
        metal_color="rust_metal",
    ),
    "ruined_entry": dict(
        town_gate_archetype="ruined_gate",
        span=3.7,
        height=2.7,
        ruined=0.58,
        stone_color="rock_warm",
    ),
}

# Livestock — small but high-value life props for farm belts.
FARM_ANIMAL_PRESETS: FactoryPresets = {
    "white_sheep": dict(animal_archetype="sheep", scale=1.0, body_color="stucco"),
    "brown_goat": dict(animal_archetype="goat", scale=0.9, body_color="rock_pale"),
    "field_cow": dict(animal_archetype="cow", scale=1.20, body_color="rock_warm"),
    "yard_chicken": dict(animal_archetype="chicken", scale=0.55, body_color="foliage_amber"),
}

# Tavern / inn landmark — bigger public building than generic houses.
TAVERN_PRESETS: FactoryPresets = {
    "roadside_inn": dict(
        tavern_archetype="roadside_inn",
        wall_color="stucco",
        roof_color="rock_shadow",
        wood_color="wood",
        accent_color="rock_warm",
    ),
    "guildhall_tavern": dict(
        tavern_archetype="guildhall",
        width=5.6,
        wall_height=4.9,
        wall_color="rock_pale",
        roof_color="rock_shadow",
        wood_color="wood",
    ),
    "riverside_pub": dict(
        tavern_archetype="riverside_pub",
        wall_color="rock_pale",
        roof_color="rock_warm",
        accent_color="wood",
    ),
    "ruined_inn": dict(
        tavern_archetype="ruined_inn",
        ruined=0.48,
        wall_color="rock_warm",
        roof_color="rock_shadow",
    ),
}

# Street-front shops — commerce details for market towns.
SHOPFRONT_PRESETS: FactoryPresets = {
    "red_awning_shop": dict(
        shopfront_archetype="awning_shop",
        cloth_color="accent_red",
        goods_color="rock_warm",
    ),
    "bakery_counter": dict(
        shopfront_archetype="bakery_front",
        cloth_color="ground_sand",
        goods_color="foliage_amber",
    ),
    "apothecary_green": dict(
        shopfront_archetype="apothecary_front",
        wall_color="stucco",
        cloth_color="foliage_bush",
        goods_color="foliage_mint",
    ),
    "closed_evening": dict(
        shopfront_archetype="closed_shutters",
        wall_color="rock_pale",
        wood_color="rock_shadow",
    ),
}

# Stable-yard compound — non-living farm/road support.
STABLE_YARD_PRESETS: FactoryPresets = {
    "open_three_bay": dict(
        stable_yard_archetype="open_stable",
        width=6.5,
        depth=3.3,
        bays=3,
    ),
    "fenced_paddock": dict(
        stable_yard_archetype="paddock_yard",
        width=7.0,
        depth=5.0,
    ),
    "cart_shelter": dict(
        stable_yard_archetype="cart_shelter",
        width=5.9,
        depth=3.8,
    ),
    "collapsed_stable": dict(
        stable_yard_archetype="ruined_stable",
        ruined=0.55,
        roof_color="rock_shadow",
    ),
}

TOWN_BLOCK_PRESETS: FactoryPresets = {
    "busy_market_row": dict(
        town_block_archetype="market_row",
        width=8.4,
        depth=3.5,
        module_count=3,
        awnings=True,
        clutter=7,
        wall_color="stucco",
        roof_color="accent_red",
        accent_color="foliage_amber",
        window_glow=True,
        window_glow_color="sky_warm",
    ),
    "stacked_townhouses": dict(
        town_block_archetype="stacked_tenement",
        width=6.8,
        depth=4.1,
        module_count=2,
        storeys=3,
        balconies=True,
        stairs=True,
        wall_color="rock_pale",
        roof_color="rock_shadow",
        window_glow=True,
        window_glow_color="foliage_lemon",
    ),
    "workshop_court": dict(
        town_block_archetype="workshop_courtyard",
        width=7.5,
        depth=4.6,
        module_count=2,
        clutter=9,
        wall_color="wood",
        roof_color="rust_metal",
        accent_color="rock_warm",
    ),
    "stepped_hillside_row": dict(
        town_block_archetype="stepped_hillside",
        width=8.6,
        depth=3.8,
        module_count=3,
        balconies=True,
        stairs=True,
        wall_color="stucco",
        roof_color="rock_warm",
        window_glow=True,
        window_glow_color="sky_warm",
    ),
    "mudbrick_bazaar_row": dict(
        town_block_archetype="mudbrick_bazaar",
        width=8.2,
        depth=3.7,
        module_count=3,
        awnings=True,
        clutter=9,
        wall_color="ground_sand",
        roof_color="rock_warm",
        accent_color="foliage_amber",
        stone_color="rock_pale",
        window_glow=True,
        window_glow_color="foliage_amber",
    ),
    "coastal_clapboard_row": dict(
        town_block_archetype="coastal_row",
        width=8.0,
        depth=3.3,
        module_count=3,
        balconies=True,
        wall_color="sky_cool",
        roof_color="accent_red",
        accent_color="stucco",
        stone_color="rock_pale",
        window_glow=True,
        window_glow_color="sky_warm",
    ),
    "alpine_chalet_row": dict(
        town_block_archetype="alpine_chalet_row",
        width=8.6,
        depth=4.2,
        module_count=3,
        balconies=True,
        stairs=True,
        wall_color="wood",
        roof_color="stucco",
        accent_color="rock_pale",
        stone_color="rock_shadow",
        window_glow=True,
        window_glow_color="foliage_lemon",
    ),
}

# Premeshed low-poly tree bank — curated GLB silhouettes from
# runtime/models/nature. Prefer these for leafy trees; they have authored
# topology and read better than procedural blob/card crowns in scene renders.
LOADED_TREE_PRESETS: FactoryPresets = {
    "oak_green": dict(archetype="tree_oak", scale=1.0, scale_jitter=0.16, xy_jitter=0.08, z_jitter=0.10, tint_palette=("foliage_pine", "foliage_bush", "foliage_apple"), tint_strength=0.55),
    "oak_fall": dict(archetype="tree_oak_fall", scale=1.0, scale_jitter=0.14, xy_jitter=0.08, z_jitter=0.10, tint_palette=("foliage_amber", "foliage_coral", "ground_sand"), tint_strength=0.58),
    "default_green": dict(archetype="tree_default", scale=1.0, scale_jitter=0.18, xy_jitter=0.10, z_jitter=0.12, tint_palette=("foliage_pine", "foliage_bush", "foliage_apple"), tint_strength=0.52),
    "default_fall": dict(archetype="tree_default_fall", scale=1.0, scale_jitter=0.16, xy_jitter=0.08, z_jitter=0.10, tint_palette=("foliage_amber", "foliage_coral"), tint_strength=0.56),
    "blocky_green": dict(archetype="tree_blocks", scale=1.0, scale_jitter=0.18, xy_jitter=0.08, z_jitter=0.10, tint_palette=("foliage_mint", "foliage_bush", "foliage_pine"), tint_strength=0.52),
    "plateau": dict(archetype="tree_plateau", scale=1.0, scale_jitter=0.14, xy_jitter=0.10, z_jitter=0.08, tint_palette=("foliage_bush", "foliage_apple", "foliage_mint"), tint_strength=0.50),
    "fat_rounded": dict(archetype="tree_fat", scale=1.0, scale_jitter=0.16, xy_jitter=0.06, z_jitter=0.12, tint_palette=("foliage_pine", "foliage_bush"), tint_strength=0.50),
    "thin_column": dict(archetype="tree_thin", scale=1.0, scale_jitter=0.18, xy_jitter=0.06, z_jitter=0.18, tint_palette=("foliage_pine", "foliage_mint"), tint_strength=0.52),
    "tall_column": dict(archetype="tree_tall", scale=1.0, scale_jitter=0.14, xy_jitter=0.05, z_jitter=0.16, tint_palette=("foliage_pine", "foliage_bush"), tint_strength=0.50),
    "cone_simple": dict(archetype="tree_cone", scale=1.0, scale_jitter=0.18, xy_jitter=0.06, z_jitter=0.14, tint_palette=("foliage_pine", "foliage_mint"), tint_strength=0.52),
    "pine_default": dict(archetype="tree_pineDefaultA", scale=1.0, scale_jitter=0.18, xy_jitter=0.08, z_jitter=0.14, tint_palette=("foliage_pine", "foliage_mint"), tint_strength=0.52),
    "pine_round": dict(archetype="tree_pineRoundA", scale=1.0, scale_jitter=0.18, xy_jitter=0.08, z_jitter=0.12, tint_palette=("foliage_pine", "foliage_bush", "foliage_mint"), tint_strength=0.52),
    "pine_tall": dict(archetype="tree_pineTallA", scale=1.0, scale_jitter=0.16, xy_jitter=0.06, z_jitter=0.20, tint_palette=("foliage_pine", "foliage_mint"), tint_strength=0.50),
    "pine_small": dict(archetype="tree_pineSmallA", scale=1.0, scale_jitter=0.22, xy_jitter=0.10, z_jitter=0.12, tint_palette=("foliage_pine", "foliage_bush", "foliage_mint"), tint_strength=0.54),
    "palm_simple": dict(archetype="tree_palm", scale=1.0, scale_jitter=0.18, xy_jitter=0.08, z_jitter=0.16, tint_palette=("foliage_bush", "foliage_mint", "foliage_pine"), tint_strength=0.50),
    "palm_bent": dict(archetype="tree_palmBend", scale=1.0, scale_jitter=0.16, xy_jitter=0.06, z_jitter=0.18, tint_palette=("foliage_bush", "foliage_mint", "foliage_pine"), tint_strength=0.50),
    "palm_detailed_tall": dict(archetype="tree_palmDetailedTall", scale=1.0, scale_jitter=0.14, xy_jitter=0.08, z_jitter=0.16, tint_palette=("foliage_bush", "foliage_mint", "foliage_pine"), tint_strength=0.50),
}


# ============================================================================
#   Registry + lookup API
# ============================================================================

# Map factory class name → its preset dict. Adding new presets: drop the
# constant above + add an entry here. The key MUST match the class name
# exactly so `factory_from_preset` can route by string.
ALL_PRESETS: dict[str, FactoryPresets] = {
    "LowPolyWatchtowerFactory":      WATCHTOWER_PRESETS,
    "LowPolyZenGardenGateFactory":   ZEN_GARDEN_GATE_PRESETS,
    "LowPolyStoneLanternFactory":    STONE_LANTERN_PRESETS,
    "LowPolyCactusFactory":          CACTUS_PRESETS,
    "LowPolyCampfireFactory":        CAMPFIRE_PRESETS,
    "LowPolyTorchFactory":           TORCH_PRESETS,
    "LowPolyCandleClusterFactory":   CANDLE_CLUSTER_PRESETS,
    "LowPolyStringLightsFactory":    STRING_LIGHTS_PRESETS,
    "LowPolyBellFactory":            BELL_PRESETS,
    "LowPolyForgeFactory":           FORGE_PRESETS,
    "LowPolySmithyPropsFactory":     SMITHY_PROPS_PRESETS,
    "LowPolyBambooFactory":          BAMBOO_PRESETS,
    "LowPolyReedsFactory":           REEDS_PRESETS,
    "LowPolyLavaFactory":            LAVA_PRESETS,
    "LowPolyVolcanicRockFactory":    VOLCANIC_ROCK_PRESETS,
    "LowPolyFountainFactory":        FOUNTAIN_PRESETS,
    "LowPolyWaterfallFactory":       WATERFALL_PRESETS,
    "LowPolyShrubFactory":           SHRUB_PRESETS,
    "LowPolyFurnitureFactory":       FURNITURE_PRESETS,
    "LowPolyMarketGoodsFactory":     MARKET_GOODS_PRESETS,
    "LowPolyNaturalArchFactory":     NATURAL_ARCH_PRESETS,
    "LowPolyPagodaFactory":          PAGODA_PRESETS,
    "LowPolyPathFactory":            PATH_PRESETS,
    "LowPolyHouseFactory":           HOUSE_PRESETS,
    "LowPolyChapelFactory":          CHAPEL_PRESETS,
    "LowPolyStoneBridgeFactory":     STONE_BRIDGE_PRESETS,
    "LowPolyWatermillFactory":       WATERMILL_PRESETS,
    "LowPolyRuinFactory":            RUIN_PRESETS,
    "LowPolyPeasantFactory":         PEASANT_PRESETS,
    "LowPolyDockFactory":            DOCK_PRESETS,
    "LowPolyTownGateFactory":        TOWN_GATE_PRESETS,
    "LowPolyFarmAnimalFactory":      FARM_ANIMAL_PRESETS,
    "LowPolyTavernFactory":          TAVERN_PRESETS,
    "LowPolyShopfrontFactory":       SHOPFRONT_PRESETS,
    "LowPolyStableYardFactory":      STABLE_YARD_PRESETS,
    "LowPolyTownBlockFactory":       TOWN_BLOCK_PRESETS,
    "LowPolyBoulderFactory":         BOULDER_PRESETS,
    "NativeLowPolyTreeFactory":      TREE_PRESETS,
    "LowPolyPalmTreeFactory":        PALM_PRESETS,
    "LoadedTreeFactory":             LOADED_TREE_PRESETS,
}


def get_preset(factory_name: str, preset_name: str) -> dict[str, Any]:
    """Return the kwargs dict for one preset.

    Raises KeyError with a helpful message — listing the available
    presets — when the lookup fails. Better than returning None and
    letting the caller construct a factory with no overrides (which
    would silently fall back to the archetype default and produce a
    misleading render).
    """
    factory_presets = ALL_PRESETS.get(factory_name)
    if factory_presets is None:
        available = ", ".join(sorted(ALL_PRESETS)) or "(none registered)"
        raise KeyError(
            f"no presets registered for factory {factory_name!r}. "
            f"Factories with presets: {available}"
        )
    preset = factory_presets.get(preset_name)
    if preset is None:
        available = ", ".join(sorted(factory_presets)) or "(none)"
        raise KeyError(
            f"factory {factory_name!r} has no preset {preset_name!r}. "
            f"Available: {available}"
        )
    # Return a shallow copy so callers can't mutate the canonical dict.
    return dict(preset)


def factory_from_preset(factory_cls, preset_name: str, factory_seed: int):
    """Instantiate `factory_cls` with the kwargs from `preset_name`.

    `factory_seed` is always supplied by the caller — bakes-in seeds
    would defeat the per-instance variation point of every factory.
    """
    kwargs = get_preset(factory_cls.__name__, preset_name)
    return factory_cls(factory_seed=factory_seed, **kwargs)


def list_presets(factory_name: str | None = None) -> list[str] | dict[str, list[str]]:
    """For docs/CLI: ``list_presets("LowPolyBellFactory") → ["monastery", ...]``,
    or ``list_presets() → {"LowPolyBellFactory": [...], ...}``."""
    if factory_name is None:
        return {fn: sorted(p) for fn, p in ALL_PRESETS.items()}
    return sorted(ALL_PRESETS.get(factory_name, {}))

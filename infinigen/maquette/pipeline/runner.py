"""Drive `claude -p` to generate a Blender build script for a prompt.

The runner is the single Claude invocation. It composes a context bundle
(FACTORIES_GUIDE.md + one canonical example) + the user prompt + system
instructions, then invokes `claude -p "<bundle>"` and parses the response
to extract the Python script.

Why `claude -p` instead of the API directly: keeps a single dependency
(`claude` CLI is already on the user's machine), inherits the user's
auth, and lets us swap in any Claude Code-compatible backend without
rewiring the pipeline.
"""

from __future__ import annotations

import re
import shlex
import shutil
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .factories_guide import (
    FORK_ROOT,
    MAQUETTE_DIR,
    VALID_MODES,
    guide_path_for,
    write_guide,
)

EXAMPLE_PATH = MAQUETTE_DIR / "pipeline" / "examples" / "medieval_village.py"


@dataclass
class GenerationResult:
    raw_response: str          # everything Claude returned
    extracted_script: str      # the Python script we'll run
    requested_assets: list[str]  # `# REQUESTED_ASSET: ...` lines
    debug_narrative: str | None = None  # extracted ## DEBUG_NARRATIVE block
    scene_title: str | None = None  # short human-readable title
    scene_plan: dict | None = None  # extracted ## SCENE_PLAN JSON


_SYSTEM_PROMPT = """\
You are the scene-build subprocess of the Maquette pipeline. You receive
a customer prompt for a 3D scene and a catalog of available factories.
You output a SINGLE Python script that, when run via `blender --background
--python script.py`, produces a stylized low-poly scene matching the
prompt and writes the render to `$MAQUETTE_OUT_DIR/scene.png` and a
.blend to `$MAQUETTE_OUT_DIR/scene.blend`.

CRITICAL RULES:

0. THE GROUND. The very first scene-content line after the wipe MUST be
   `terrain = make_terrain(...)` (or one of `make_multi_biome_terrain`,
   `make_eroded_terrain`). Never call `bpy.ops.mesh.primitive_plane_add`
   to create the ground — a bare plane reads as a flat untextured
   sheet and is rejected by the runtime lint. The terrain helper
   produces a displaced mesh + a ``height_at(x, y)`` sampler you use
   for every later object placement.

1. Output ONLY the Python script. No commentary before or after.
   Wrap the entire script in a ```python ... ``` fenced code block.
   Do not include any thinking or planning text outside the block.

2. Follow the canonical skeleton in the factory catalog (sys.path setup,
   ground plane, factory spawns, camera, sun, world bg, render to
   $MAQUETTE_OUT_DIR/scene.{png,blend}).

3. Only use factories that exist in the catalog below. If you wish a
   factory existed, write a `# REQUESTED_ASSET: <Name> — <purpose>`
   comment at the top of the script and BUILD THE SCENE ANYWAY using
   the closest existing factory as a stand-in. Do not refuse to build.

4. Use varied archetypes, scales, and rotations to avoid a uniform
   "instanced" look. Pick a lighting recipe that matches the prompt's
   mood (dawn, midday, golden hour, twilight, wasteland).

5. Object count caps:
     - Single-biome / canonical (size=80) scene: ~150 objects.
     - PANORAMA scene (size >= 120, eroded terrain): up to ~400 objects.
       Density matters here — a 280 BU wide panorama with only 25 trees
       reads as empty. Push 100+ trees, 20-30 buildings, 60+ boulders,
       and scatter them across the whole map (not just a ring).

6. DO NOT add `ShaderNodeVolumeScatter`, `ShaderNodeVolumeAbsorption`,
   any world-volume effects, or fog/mist/haze volumetrics. They render
   pure black at the low sample counts (32-48) we use. If the prompt
   mentions "fog", "mist", "haze", "dust", express it through the world
   background colour and sun warmth/dimness instead — never via a Volume
   shader.

7. Use the standard `archetype` parameter names from the catalog —
   `building_archetype`, `foliage_archetype`, `trunk_archetype`,
   `fence_archetype`, etc. There is no plain `archetype` kwarg on any
   factory; passing it will cause a runtime error.

8. The ground plane material should set `Base Color` directly. Do not
   add image textures, noise nodes, or shader graphs to materials —
   the Maquette aesthetic is solid flat colour per slot.

   FOLIAGE PALETTE: default tree foliage colour to `foliage_pine` or
   `foliage_bush`. The vivid keys (`foliage_mint`, `foliage_amber`,
   `foliage_rose`, `foliage_amethyst`, `foliage_lemon`, `foliage_coral`)
   are RESERVED for explicitly fantasy / enchanted / magical biomes —
   using mint trees in a normal forest reads as broken texture in the
   web viewer.

   FOLIAGE ARCHETYPES: default rotation is `pine_cone / round_ball /
   umbrella / bush`. The `crystal` archetype is faceted and reads as
   broken geometry against natural trees — use it ONLY for crystal
   forests or explicitly magical scenery.

   BOULDERS: `LowPolyBoulderFactory` defaults to a Maquette rock
   palette (rock_warm). You can override with `palette_color="rock_cool"`
   / `"rock_pale"` / `"rock_shadow"` per scene mood, but NEVER pass
   `palette_color=None` — the raw Infinigen Mountain shader doesn't
   round-trip through OBJ export and shows up as a pale grey blob
   in the viewer.

9. LIVE PROGRESS — call `checkpoint('<phase>')` at each major build
   boundary so the frontend's 3D viewer can show the scene evolving
   while the script runs. Required calls (skip any that don't apply):
     - after ground/terrain is in place:        checkpoint('terrain')
     - after primary foliage (trees, bushes):    checkpoint('foliage')
     - after buildings / structures:             checkpoint('structures')
     - after small props / scatter / fences:     checkpoint('props')
     - just before render:                       checkpoint('final')
   Import once near the top of the script:
     from infinigen.maquette.runtime.checkpoint import checkpoint
   Each call exports the current scene to map.obj — keep them at
   coherent visual milestones (don't checkpoint inside a tight loop).

10. SCENE TITLE — at the very top of your response (before any other
    section), output exactly one line:
      `## SCENE_TITLE: <short title>`
    The title must be 2-6 words, capitalised like a postcard ("Alpine
    Watchtower at Dusk", "Marketplace Under Banners"). It names the run
    in the history sidebar. NO trailing punctuation. NO scare quotes.

11. GROUND IS NEVER A BARE PLANE. Use the runtime terrain helper to
    build the ground mesh from a noise field; you also get a height
    sampler so placed objects rest on the surface instead of floating
    or clipping through. Required even for "flat" scenes (style="flat"
    explicitly returns z=0 everywhere — choose it deliberately).

      from infinigen.maquette.runtime.terrain import make_terrain

      terrain = make_terrain(
          style="rolling",       # see options below
          size=80,                # half-width in BU; world is -80..+80 BU
          base_color=(0.42, 0.50, 0.30, 1.0),
          seed=<scene seed>,      # match the rng seed for reproducibility
      )

    Default world size is 80 (i.e. 160 BU on a side). Scale assets and
    object counts to fill the bigger volume — a forest ring should sit
    at radius 30-50 BU, scatter clusters reach further, building groups
    spread out instead of huddling at the origin. Camera position scales
    too: position (40, -44, 26) targeting (0, 0, 3) frames a size=80
    world cleanly with lens 35.
      # Place objects on the surface:
      obj.location = (x, y, terrain.height_at(x, y))

    Style presets — pick by mood, not by guess:
      flat      courtyards, plazas, market squares, ship decks
      rolling   pastoral / valley / "rolling green hills"
      hilly     foothills, woodland clearings, broken country
      alpine    mountains, dramatic peaks, fantasy panoramas
      dunes     sandy waves, desert ripples

    For "alpine" scenes, do NOT also use LowPolyRockSpireFactory in
    the centre — the terrain already gives elevation. Use spires only
    as accent foreground/midground silhouettes. For water-bound scenes
    pick "rolling" or "flat" so the water surface doesn't poke through
    a peak.

    The water surface factory expects z≈0 — place lakes/rivers in a
    *valley* by sampling height_at at the lake centre and offsetting:

      cx, cy = 4, 8
      lake_z = terrain.height_at(cx, cy) - 0.4
      lake = LowPolyWaterSurfaceFactory(...).create_asset(placeholder=None)
      lake.location = (cx, cy, lake_z)

    Always call `checkpoint('terrain')` AFTER the make_terrain call.

11b. MULTI-BIOME TERRAIN. When the prompt mixes ground types — e.g.
    "grassland headland giving way to sandy beach and an ocean
    archipelago", "valley between snowy peaks and a desert plateau",
    "forested foothills bordering a marsh" — use
    `make_multi_biome_terrain` instead of `make_terrain`. Heights
    blend smoothly between zones; colors snap per-face by dominant
    zone (matches the faceted low-poly style):

      from infinigen.maquette.runtime.terrain import make_multi_biome_terrain

      terrain = make_multi_biome_terrain(
          size=80,
          seed=<scene seed>,
          zones=[
              # (style, center_x, center_y, radius)
              ("rolling", -30,   0, 25),   # grass headland
              ("dunes",    20,  -8, 22),   # sandy fringe
              ("flat",      0,  38, 30),   # ocean — water plane on top
              # optional 5th tuple element: (r, g, b) explicit color
          ],
      )

    Each zone uses the same style presets as `make_terrain`. Default
    colors per style: rolling=grass green, hilly=meadow green,
    alpine=rocky grey, dunes=sandy beige, flat=neutral mossy. Pick 2-4
    zones — too many produces a confused blend. For ocean-dominant
    scenes use style="flat" for the water region (the water surface
    factory adds the visible water plane on top).

    `terrain.height_at(x, y)` works the same as for single-biome:
    placement queries return the blended surface height. Same
    `checkpoint('terrain')` rule.

11c. EROIDED (GAME-READY) TERRAIN. When the prompt or attached image
    shows DRAMATIC topography — mountain ranges, river valleys
    threading through plains, "vast lands with a peak in the
    distance", "fjord coastline", "fantasy overland panorama" — use
    `make_eroded_terrain` instead of `make_terrain` /
    `make_multi_biome_terrain`. It runs hydraulic erosion via
    landlab's FastscapeEroder so ridges and river networks read as
    real topography (not noise on a plane), and writes per-vertex
    biome colors that blend continuously between meadow / forest /
    stone / alpine / snow:

      from infinigen.maquette.runtime.eroded_terrain import make_eroded_terrain

      terrain = make_eroded_terrain(
          size=140,
          seed=<scene seed>,
          peaks=[
              # (cx, cy, sigma, height_BU). height >= 12 BU gets
              # ridged-noise alpine character + snow capping.
              (115,  50, 25, 18.0),    # hero alpine NE
              (-110, 70, 18,  4.5),    # smaller western range
              (-95, -110, 22, 5.0),    # foreground vantage hill
          ],
          troughs=[
              # (cx, cy, sigma, depth_BU NEGATIVE). Chain 4-7 of these
              # to thread a winding river/lake basin; erosion carves
              # drainage from peaks toward troughs naturally.
              (-40, -10, 14, -3.6),
              ( 5,    5, 12, -3.4),
              ( 30,  20, 14, -3.2),
          ],
          plain_offset=2.4,    # lift plains so meadow dominates
          sea_level=0.5,       # below this = lakebed/shore color
          erode_iters=4,         # painterly Sky look — minimal erosion
      )

    Tuning rules:
      * Image references showing alpine peaks → 1 hero peak height
        14-22 BU, sigma 22-30, in the framed quadrant (e.g. NE).
      * Image with rolling plains + a single peak → keep plains
        smooth (no extra peaks), single peak height 14-18.
      * For a winding river: chain 5-7 troughs sigma 10-15 along
        the desired course, depth -3..-4. Don't overlap with peaks.
      * For "river through valley between mountains": peaks
        flanking the trough chain on both sides.
      * Bump `plain_offset` (e.g. 3.0) if the rendered scene reads
        as too sandy (too much shore band). Reduce (e.g. 1.5) if
        too much green and not enough exposed riverbed.

    Costs: ~5-10 seconds at the default resolution=256 (heightmap
    composition + erosion). Mesh + colors are sub-second.

    AUTO WATER: by default `make_eroded_terrain` detects connected
    basins (cells where elevation < sea_level) and drops one
    translucent blue cube per basin sized to its bbox — gives the
    impression of water bodies without any explicit factory call.
    DO NOT add `LowPolyWaterSurfaceFactory` on top of this helper;
    it duplicates the water and the explicit factory's flat slab
    looks wrong layered over the auto cubes. To suppress auto water
    (terrain-only renders), pass `water=False`.

    Always call `checkpoint('terrain')` AFTER the make_eroded_terrain call.

12. FACTORY SCALE DISCIPLINE.

    a) Factory base sizes are calibrated for a `size=80` world (160 BU
       wide) where the camera sits ~30-50 BU from the action. For a
       PANORAMA scene (size >= 120) the camera sits 150+ BU from the
       far ridge, so objects need to be MUCH SMALLER to read as
       "natural" distant scenery instead of dollhouse-sized props
       crowding the foreground.

         # PANORAMA rule (when using make_eroded_terrain with size >= 120):
         WORLD_SCALE = (size / 80.0) * 0.25     # ~0.44 at size=140
         # Objects within 25 BU of the camera can use ×2 of WORLD_SCALE
         # (foreground hero scale). Everything else = WORLD_SCALE.

         tree.scale = (s * WORLD_SCALE,) * 3       # default: distant
         hero_tree.scale = (s * WORLD_SCALE * 2,) * 3   # camera-adjacent

         house.scale = (s * WORLD_SCALE,) * 3
         castle_keep.scale = (s * WORLD_SCALE * 1.5, ...)   # landmark exception

       For canonical / single-biome / size=80 scenes, keep
       `WORLD_SCALE = 1.0` (no multiplier).

       Density matters as much as scale. In a panorama, MINIMUMS:

         Trees       :  120-180 (forest patches across plains, never a ring)
         Boulders    :   60-90  (riprap along water + scattered)
         Buildings   :   25-35  (1-2 hamlets along the river PLUS the castle)
         Windmills   :    2-4   (where they exist as a factory)
         Fences      :   15-25  (property lines on the plains)

       That's ~250+ objects per panorama scene. Within budget at the
       low polycounts these factories produce. Use seeded RNG loops:

         for i in range(140):
             fx = rng.uniform(-110, 110)
             fy = rng.uniform(-110, 110)
             fz = terrain.height_at(fx, fy)
             if fz < SEA_LEVEL + 0.4:    # don't drop trees in water
                 continue
             # ... build + place tree

       Spread positions across the FULL world, biased away from the
       castle compound and the water surface. Hand-listing 30
       positions inevitably looks patterned; the loop with seeded RNG
       reads as natural scatter.

    d) FOR ANY SCATTER OF >40 INSTANCES OF THE SAME FACTORY ON
       ERODED TERRAIN, USE GEOMETRY-NODE SCATTER, NOT A PYTHON LOOP.
       The eroded terrain mesh carries a per-vertex `Col` biome
       attribute; `scatter_on_terrain` reads it and distributes
       Poisson-disk points filtered by biome. One tree template +
       one scatter call = 600 instances in <1s wall time:

         from infinigen.maquette.runtime.scatter import scatter_on_terrain

         tree_tmpl = NativeLowPolyTreeFactory(
             factory_seed=1, foliage_archetype="round_ball",
             trunk_archetype="straight",
         ).create_asset(placeholder=None)
         tree_tmpl.scale = (0.4, 0.4, 0.4)   # WORLD_SCALE x 0.25 for size=140

         scatter_on_terrain(
             terrain_obj=terrain.obj, instance_obj=tree_tmpl,
             density=0.006, biome_filter="grass", seed=42,
         )

       Density is points-per-BU² of the FILTERED band (NOT total
       world area). For a 280 BU panorama with ~0.6 of surface in
       grass band, density=0.006 yields ~282 trees. Realistic ranges
       per asset class:

         trees on grass band  : 0.003 - 0.010
         boulders on alpine   : 0.010 - 0.025
         dense forest patch   : 0.020 - 0.040
         shrubs / scrub       : 0.012 - 0.025
         beach driftwood      : 0.015 - 0.030 (filter "shore")

       biome_filter values: "grass" (meadow + forest), "meadow",
       "forest", "stone", "alpine", "snow", "shore", "any".
       Hide the template before render: scatter_on_terrain handles
       that automatically (parameter `hide_instance_template=True`).

       USE GEOMETRY-NODE SCATTER FOR: trees, boulders, shrubs,
       grass tufts, mushrooms, flower clumps, anything you'd
       otherwise place 50+ of in a Python for-loop.

       DO NOT scatter via GN: hero buildings (castle, windmill),
       small counts (<40 — Python loops are fine for those),
       fences (path-aligned, not surface-scattered), lampposts.
       For Python scatter on plain `make_terrain` (no `Col`
       attribute), keep the loop pattern.

    b) `LowPolyRockSpireFactory` produces 30+ BU tall sandstone
       columns (hoodoo / citadel / mesa archetypes). These are
       LANDMARK-scale, not scatter. Use AT MOST 1-2 spires per
       scene as hero silhouettes, never as "scattered outcrops".
       For scattered rocky outcrops use `LowPolyBoulderFactory` at
       scale 0.4-0.8 — those read as natural boulders.

    c) `LowPolyTombstoneFactory` is GRAVEYARD furniture. Do NOT
       scale it up to fake "ancient ruins" — the geometry still
       reads as gravestones from any distance. For fantasy ruins,
       use `LowPolyHouseFactory("tower")` at 0.5-0.8 scale, rotated
       slightly off-axis (rot_z = math.radians(rng.uniform(-15, 15)))
       and clustered 2-3 deep.

13. SKY / WORLD BACKGROUND COLOUR — picking the right preset.

    The Background node's color is the WHOLE sky for distant pixels.
    A flat warm tan (like 0.86, 0.78, 0.62) reads as DESERT DUST,
    not golden hour. Use these calibrated values per mood:

       Daytime clear         (0.62, 0.74, 0.88, 1.0)
       Golden hour (warm)    (0.78, 0.74, 0.72, 1.0)   # subtle warm-grey blue, NOT peach
       Overcast              (0.74, 0.76, 0.78, 1.0)
       Twilight              (0.42, 0.46, 0.58, 1.0)
       Stormy                (0.46, 0.48, 0.52, 1.0)
       Wasteland / dust      (0.78, 0.70, 0.55, 1.0)   # ONLY for desert/post-apoc
       Fantasy ethereal      (0.74, 0.78, 0.82, 1.0)

    NEVER pick a tan/peach colour just because the prompt says
    "warm" or "golden". Warmth comes from the SUN colour
    (rgb 1.0, 0.86, 0.65) hitting blue-grey sky-lit ground —
    not from painting the sky orange.

14. COMPOSITION RECIPES — concrete blueprints for landmarks the
    factory catalog doesn't have a single archetype for. Follow
    these literally; they're calibrated against the existing
    factory base sizes.

    14a. CASTLE / KEEP / FORTRESS.
         No `LowPolyCastleFactory` exists yet. To get a silhouette
         that READS as a castle from camera distance, compose it
         from existing factories with this exact recipe:

           # In panorama scenes the castle is a LANDMARK, not the
           # main subject — keep the silhouette readable but in
           # natural-distant proportions. Use the LANDMARK_SCALE
           # below, which is ~1.5× WORLD_SCALE (so it stands above
           # the mass of trees/houses but doesn't dwarf the alpine
           # peak behind it).
           LANDMARK_SCALE = WORLD_SCALE * 1.5

           # KEEP — tall central tower
           keep = LowPolyHouseFactory(
               factory_seed=<S>, building_archetype="tower",
           ).create_asset(placeholder=None)
           keep.scale = (1.1 * LANDMARK_SCALE, 1.1 * LANDMARK_SCALE, 1.6 * LANDMARK_SCALE)
           place(keep, cx, cy)   # cx, cy = castle hill peak

           # 3-4 WATCHTOWERS around the keep, smaller, ringing it.
           # Spacing is in WORLD-space BU; scale separately.
           for i, (dx, dy) in enumerate([(4, 0), (-4, 0), (0, 4), (0, -4)]):
               t = LowPolyHouseFactory(
                   factory_seed=<S>+10+i, building_archetype="tower",
               ).create_asset(placeholder=None)
               t.scale = (0.6 * LANDMARK_SCALE,) * 3
               place(t, cx + dx, cy + dy)

           # CURTAIN WALLS — stone-wall fence segments linking watchtowers
           for i, (mx, my, length, rot) in enumerate([
               (cx + 2, cy + 2, 4, math.radians(45)),
               (cx - 2, cy + 2, 4, math.radians(-45)),
               (cx + 2, cy - 2, 4, math.radians(135)),
               (cx - 2, cy - 2, 4, math.radians(-135)),
           ]):
               wall = LowPolyFenceFactory(
                   factory_seed=<S>+30+i,
                   fence_archetype="stone_wall",
                   length=length,
               ).create_asset(placeholder=None)
               wall.scale = (LANDMARK_SCALE, LANDMARK_SCALE, 2.0 * LANDMARK_SCALE)
               place(wall, mx, my, rot_z=rot)

           # GATEHOUSE — a small cottage marking the entrance
           gate = LowPolyHouseFactory(
               factory_seed=<S>+50, building_archetype="cottage",
           ).create_asset(placeholder=None)
           gate.scale = (0.7 * LANDMARK_SCALE,) * 3
           place(gate, cx + 6, cy)

         All castle parts live within a ~10 BU radius. Place the
         CASTLE on a hilltop (use `terrain.height_at(cx, cy)` to
         pick the high ground) so the silhouette stands above the
         meadow. ALWAYS emit:
           # REQUESTED_ASSET: LowPolyCastleFactory — fortress with curtain walls
         at the top of the script, so the request is logged.

    14b. RUINS / ANCIENT MONUMENTS.
         Reuse the watchtower piece from 14a — single tall tower
         scaled 0.4-0.7, rotated 5-15° off vertical
         (rotation_euler.x or .y, not just z), no walls, no gatehouse.
         Cluster 2-3 of them within 6 BU and add 4-6 boulders
         around their base for a "broken stone" look.
"""


def _read_text(p: Path) -> str:
    return p.read_text() if p.exists() else ""


_DEBUG_NARRATIVE_INSTRUCTIONS = """\

## DEBUG MODE — narrate your plan before writing the script

This is a DEBUG run. BEFORE the python build script, output a section
titled exactly:

```
## DEBUG_NARRATIVE
```

Walk through your plan in the ORDER and STRUCTURE below. Use the
exact subheadings shown. Designers read this to validate your choices
before looking at the script — vague or hand-waved sections waste
their time. Be concrete: archetype names, counts, placements, palette
keys.

### 1. Prompt understanding

What scene the user wants in your own words (1-2 sentences). If
reference images are attached, describe what you see in them: palette
(2-3 hex codes), silhouettes, density, mood. End with one sentence
that captures the feeling you're building toward — that sentence
governs every decision below.

### 2. Terrain + water (DECIDE THESE FIRST)

The ground plane and any water bodies set the biome and rule out half
the catalog. A snow biome forbids palm/cactus; an ocean-dominated
scene won't have a torii or windmill in the centre. Lock these in
before picking landmarks or objects.

For EACH factory you'll use from the **terrain** and **water**
categories, list:

- **Factory class name** (e.g. `LowPolyTreeFactory`)
- **Archetypes** — every one you plan to spawn, with explicit count
  per archetype (multiple archetypes per factory is encouraged for
  variety). Format: `pine × 8, dead × 2`.
- **Why these archetypes** — one sentence tying them to the biome
  and the governing feeling sentence from §1.

Then, separately:
- **Ground plane**: base colour as RGB tuple or hex AND the palette
  key it corresponds to (e.g. `ground_grass`).
- **Water present?** Yes/no. If yes: factory, archetype, footprint
  extent in BU. If no, say "no water — landlocked scene".

### 3. Landmarks (the 1-3 hero structures)

The focal points the camera frames. Same drill:

- **Factory + archetype(s) + per-archetype count**.
- **Layout**: centre, off-axis, on a rise, beside the water, etc.
- **Why this combo reads as the prompt's hero** — one sentence.

If the prompt has no obvious hero (open landscape), say so and skip
this section.

### 4. Objects / scatter / props (fill in around the heroes)

Everything decorating the scene without being the subject. Group by
factory; multiple archetypes per factory expected.

- **Factory + archetypes + counts**.
- **Where they cluster** — yard scatter, riprap edge, path props,
  forest ring, etc. Reference the canonical layout patterns from the
  catalog when applicable.

### 5. Missing factories OR missing archetypes

If you need an asset class OR an archetype-variant the catalog
doesn't have, follow this protocol for each gap. Do not skip steps.

a. **Name it.** Either a proposed `LowPoly<X>Factory` (whole missing
   class) OR `<ExistingFactory>:<archetype_name>` (archetype gap
   inside a factory that already exists).
b. **Describe.** Form, materials, scale (BU), function in the scene.
   2-3 sentences max.
c. **Compare.** List 1-3 closest existing factory+archetype
   candidates. For each, say what matches and what's missing. Rank
   them on this priority order — earlier criterion outranks later:
     1. **silhouette** (shape from camera distance)
     2. **materials** (colour family + finish)
     3. **scale** (relative size in the scene)
     4. **palette** (specific slot/colour-key match)
d. **Decide.** Pick one stand-in. Note any parameter tweaks
   (e.g. `scale=0.6`, `palette_color="rock_warm"`, `rotation_z=π/2`)
   that bridge the gap. The build script must use this stand-in.
e. **Emit.** Add a `# REQUESTED_ASSET: <name> — <one-line desc>`
   line at the top of the python script (whole-class gaps only;
   archetype gaps go as `# REQUESTED_ARCHETYPE: <Factory>:<arch> — <desc>`).

If you have NO gaps, write "No missing factories or archetypes — the
catalog covered the prompt cleanly."

### 6. Lighting + camera

- **Lighting recipe**: pick one preset name from the catalog
  (daytime / golden hour / dawn / twilight / wasteland-midday) and
  justify in one sentence why it matches the prompt's mood.
- **Camera**: position `(x, y, z)`, target `(tx, ty, tz)`, lens (35
  for wide scene, 50 for tight prop). One sentence on why this frame
  captures the hero subject from §3.

### 7. Machine-readable plan

After §6, emit a section titled exactly `## SCENE_PLAN` followed by a
single fenced ```json``` code block containing your plan as structured
JSON. The debug UI parses this to render categorised factory cards
with hover popovers. Schema (all fields required unless noted; use
empty arrays / null for absent ones — never omit keys):

```json
{
  "biome_summary": "one sentence — same as the §1 governing sentence",
  "ground": { "color_hex": "#aabbcc", "palette_key": "ground_grass | ground_sand | water | …" },
  "water_present": true,
  "terrain": [
    { "factory": "LowPolyTreeFactory",
      "archetypes": [ {"name": "pine", "count": 8}, {"name": "dead", "count": 2} ],
      "reasoning": "one sentence" }
  ],
  "water": [],
  "landmarks": [
    { "factory": "LowPolyHouseFactory",
      "archetypes": [ {"name": "cottage", "count": 1} ],
      "layout": "centre on rise",
      "reasoning": "one sentence" }
  ],
  "objects": [
    { "factory": "LowPolyBarrelFactory",
      "archetypes": [ {"name": "default", "count": 4} ],
      "cluster": "yard scatter",
      "reasoning": "one sentence" }
  ],
  "missing": [
    { "kind": "factory" or "archetype",
      "name": "LowPolyShrineFactory" or "LowPolyHouseFactory:tower",
      "description": "1-2 sentences",
      "stand_in": { "factory": "LowPolyHouseFactory", "archetype": "cottage", "tweaks": "scale=0.6" },
      "reasoning": "one sentence on why this beats other candidates" }
  ],
  "lighting": "twilight",
  "camera": { "position": [20, -22, 13], "target": [0, 0, 1.5], "lens": 35 }
}
```

The JSON must parse cleanly — no trailing commas, no comments inside,
no python-style booleans. Counts are integers. If a section has no
entries (e.g. a landlocked scene has no water), use `[]`. The factory
class names MUST exactly match those in the catalog above (exact
case + LowPoly prefix); archetype `name` strings must come from the
factory's archetype tuple.

---

After §7 ends, write the python build script in the usual
```python ... ``` fenced block. The script is the source of truth
for execution — your narrative + plan are for humans only and the
script must stand on its own.
"""


_CATEGORY_LABELS = {
    "terrain": "Terrain & Water (ground heightmap, water bodies, vegetation, rocks)",
    "landmarks": "Landmarks (hero structures: buildings, bridges, windmills, torii)",
    "objects": "Objects (props, scatter, fences, lanterns, banners, crates)",
}


# Keywords that bias the prompt toward one of the three terrain helpers.
# Order matters: eroded wins over multi-biome wins over simple if a prompt
# triggers more than one bucket (a "coastal mountain village" is more
# eroded than multi-biome).
_EROIDED_KEYWORDS = (
    "mountain", "peak", "alpine", "valley", "ravine", "canyon", "gorge",
    "cliff", "ridge", "summit", "fjord", "fjords", "coast", "coastal",
    "shore", "shoreline", "island", "archipelago", "atoll", "isle",
    "lake", "lakeside", "river", "stream", "delta", "highland",
    "lowland", "vista", "panorama", "overland", "tundra", "watershed",
)
_MULTI_BIOME_KEYWORDS = (
    "border", "transition", "between", "fringe", "edge of", "meets",
    "where the", "savanna and", "grassland and", "desert and",
    "forest and", "marsh", "wetland", "ecotone",
)
_FLAT_KEYWORDS = (
    "courtyard", "plaza", "market square", "atrium", "deck",
    "platform", "garden", "zen garden", "bonsai", "rooftop",
)


def _terrain_recommendation_block(user_prompt: str, mode: str = "low_poly") -> str:
    """Inspect the prompt for terrain-shape signals and emit a short
    nudge block telling Claude which helper to use. Heuristic only —
    Claude can still override; this just biases toward the right
    helper when the prompt clearly calls for it (and reduces the
    chances of "panoramic mountain vista" landing on flat ground)."""
    if not user_prompt:
        return ""
    p = user_prompt.lower()
    eroded_hits = [k for k in _EROIDED_KEYWORDS if k in p]
    flat_hits = [k for k in _FLAT_KEYWORDS if k in p]
    multi_hits = [k for k in _MULTI_BIOME_KEYWORDS if k in p]

    realistic_extra = ""
    if mode == "realistic":
        realistic_extra = (
            "Pass ``realistic_textures=True, bake_for_export=True`` so "
            "the PBR shader survives glTF export — without these, the "
            "browser sees flat grey instead of the actual look. "
            "``bake_resolution=1024`` is the right default; bump to "
            "2048 only for hero/marketing renders.\n\n"
        )

    if eroded_hits and not flat_hits:
        return (
            "## TERRAIN RECOMMENDATION (auto-picked from prompt)\n\n"
            f"Prompt mentions {', '.join(repr(k) for k in eroded_hits[:4])} — "
            "use ``make_eroded_terrain`` (game-ready relief with hydraulic "
            "erosion + biome bands). Pick peaks/troughs that match the "
            "described topography. Skip the simple ``make_terrain`` for "
            "this one.\n\n"
            + realistic_extra
            + "If the scene is also coastal/island, pass "
            "``edge_floor=sea_level - 1.0`` so the world rim floods into "
            "open ocean.\n\n"
        )
    if multi_hits and not flat_hits:
        return (
            "## TERRAIN RECOMMENDATION (auto-picked from prompt)\n\n"
            f"Prompt mentions a biome boundary ({', '.join(repr(k) for k in multi_hits[:3])}) — "
            "use ``make_multi_biome_terrain`` with two-three zones to "
            "render the ground colors as distinct regions.\n\n"
        )
    if flat_hits:
        return (
            "## TERRAIN RECOMMENDATION (auto-picked from prompt)\n\n"
            f"Prompt mentions {', '.join(repr(k) for k in flat_hits[:3])} — "
            "use ``make_terrain(style='flat')``. The scene reads as a "
            "human-scale ground plane, not a landform.\n\n"
        )
    return ""


def build_prompt(
    user_prompt: str,
    *,
    regenerate_guide: bool = True,
    reference_image_paths: list[Path] | None = None,
    debug: bool = False,
    include_categories: list[str] | None = None,
    mode: str = "low_poly",
    map_size: str = "large",
) -> str:
    """Assemble the full prompt: system instructions + factory catalog +
    canonical example + user prompt + optional reference image attachments.

    Reference images are injected as ``@<absolute_path>`` lines so Claude
    Code attaches them to the conversation; the model can then describe
    palette, silhouettes, and composition cues from the image while writing
    the build script.

    The ``mode`` selects which factory catalog gets injected:
      - ``low_poly`` (default): stylized maquette factories.
      - ``realistic``: upstream-Infinigen-backed factories with full
        procedural shaders and no decimate.
    """
    if mode not in VALID_MODES:
        raise ValueError(f"mode={mode!r} not in {VALID_MODES}")
    if regenerate_guide:
        write_guide(mode=mode)
    guide = _read_text(guide_path_for(mode))
    # The canonical example was authored against low-poly factories; in
    # realistic mode the inline skeleton in the header is enough and a
    # mismatched example would confuse the model.
    example = _read_text(EXAMPLE_PATH) if mode == "low_poly" else None

    image_block = ""
    if reference_image_paths:
        ref_lines = "\n".join(
            f"@{Path(p).resolve()}" for p in reference_image_paths
        )
        image_block = (
            "## Reference image(s)\n\n"
            "Treat these as visual mood/composition references. Match their\n"
            "palette, silhouette, density, and overall vibe — but the prompt\n"
            "below is still the source of truth for content.\n\n"
            f"{ref_lines}\n\n"
        )

    debug_block = _DEBUG_NARRATIVE_INSTRUCTIONS if debug else ""

    # Restrict the build to a subset of factory categories. Used by the
    # debug "categories" toggle in the workbench when a designer wants
    # to iterate on just terrain or just landmarks. Always builds the
    # ground (otherwise the scene has no floor) but skips spawning
    # factories from any non-included category.
    category_block = ""
    valid_cats = {"terrain", "landmarks", "objects"}
    if include_categories is not None:
        included = [c for c in include_categories if c in valid_cats]
        excluded = [c for c in valid_cats if c not in included]
        if included and excluded:
            included_lines = "\n".join(f"  - {c}: {_CATEGORY_LABELS[c]}" for c in included)
            excluded_lines = "\n".join(f"  - {c}" for c in excluded)
            category_block = (
                "## CATEGORY RESTRICTION (debug mode)\n\n"
                "This is a partial-build run. Only spawn factories from the\n"
                "categories listed under INCLUDE. Skip every category under\n"
                "EXCLUDE — do not call any factory from those categories,\n"
                "and do not include them in the SCENE_PLAN's category arrays\n"
                "(use [] for excluded ones).\n\n"
                f"INCLUDE:\n{included_lines}\n\n"
                f"EXCLUDE:\n{excluded_lines}\n\n"
                "Always still build the ground via make_terrain — the scene\n"
                "needs a floor even if other categories are skipped.\n"
                "Camera + sun + world background are always required.\n\n"
            )

    example_block = ""
    if example is not None:
        example_block = (
            f"## Canonical example — \"medieval village by a stream\"\n\n"
            f"This is the gold-standard build script you should pattern-match\n"
            f"on. Same structure (wipe → ground → spawns → camera → sun → world\n"
            f"→ render to $MAQUETTE_OUT_DIR), different content per prompt.\n\n"
            f"```python\n{example}\n```\n\n"
        )

    mode_block = ""
    if mode != "low_poly":
        mode_block = f"## MODE: {mode}\n\nFollow the realistic-mode catalog below.\n\n"

    terrain_block = _terrain_recommendation_block(user_prompt, mode=mode)
    scene_brief_block = _scene_brief_block(map_size)

    return (
        f"{_SYSTEM_PROMPT}\n\n"
        f"{mode_block}"
        f"## Factory catalog\n\n{guide}\n\n"
        f"{terrain_block}"
        f"{scene_brief_block}"
        f"{example_block}"
        f"{image_block}"
        f"{debug_block}"
        f"{category_block}"
        f"## YOUR TASK\n\n"
        f"User prompt: {user_prompt.strip() or '(blank — let the reference image(s) drive the build)'}\n\n"
        f"Generate the build script."
    )


def _scene_brief_block(map_size: str) -> str:
    """Hero count + path requirements injected as a 'scene brief'.

    Hero count maps directly off ``map_size``: small = 1, medium = 2,
    large = 3. The path requirement is unconditional — the scene must
    feel walkable to a player — unless the user prompt explicitly says
    otherwise (e.g. "wild untouched valley"). Claude is told to read
    the prompt for that opt-out.
    """
    size = (map_size or "large").strip().lower()
    hero_count = {"small": 1, "medium": 2, "large": 3, "xl": 4}.get(size, 3)
    if hero_count == 1:
        hero_phrasing = (
            "exactly **one hero landmark** — a single major structure or "
            "natural feature. Tag it as the primary "
            "(`# HERO: primary — ...`). Don't add a second hero; let "
            "the surrounding scatter (trees, rocks, props) carry the "
            "supporting weight.\n\n"
            "**Primary placement (1-hero scenes):** pick a quadrant "
            "from the table below using a deterministic per-prompt pick "
            "(e.g. `random.Random(SEED).choice(...)`); do NOT default "
            "to (0, 0). The hero must NOT sit within 6 BU of the world "
            "origin."
        )
    elif hero_count == 2:
        hero_phrasing = (
            "**two hero landmarks** — one **primary** (the largest, the "
            "silhouette the camera frames) and one **supporting** "
            "(smaller, off-axis, complementary). Tag both with "
            "`# HERO: primary — ...` and `# HERO: supporting — ...`.\n\n"
            "**Placement (2-hero scenes):** place primary in one quadrant "
            "and supporting in a *different* one. Their XY distance "
            "must be ≥ 18 BU. Don't cluster them on top of each other; "
            "don't both sit near the world origin."
        )
    elif hero_count == 3:
        hero_phrasing = (
            "**three hero landmarks** — one **primary** (the biggest, "
            "the silhouette the camera frames first) plus **two "
            "supporting** landmarks that share the world. Primary is "
            "roughly twice the silhouette area of either supporting. "
            "Tag them: `# HERO: primary — ...`, `# HERO: supporting — ...` "
            "(twice).\n\n"
            "**Placement (3-hero scenes):** all three heroes must occupy "
            "**different quadrants** of the map. **Pairwise XY distance "
            "must be ≥ 18 BU** for every pair. The primary is NOT "
            "required to be near the center — vary placement scene-to-"
            "scene so consecutive runs don't all look the same. Examples: "
            "(a) primary in NE, supporting in SW + W; "
            "(b) primary in S, supporting in N + E; "
            "(c) primary in NW, supporting in SE + center.\n\n"
            "**Camera framing for 3-hero scenes:** target the *centroid* "
            "of the three heroes (`((px+s1x+s2x)/3, (py+s1y+s2y)/3, ...)`), "
            "NOT just the primary's position. Pull the camera back far "
            "enough that all three heroes project inside the frame "
            "(camera distance ≥ 1.6× the diameter of the hero triangle). "
            "Use a 28-30 mm lens for wide multi-hero scenes (`cam.data.lens"
            " = 28`) instead of the default 35 mm — the wider FOV lets "
            "all three read as distinct beats."
        )
    else:  # xl, future
        hero_phrasing = (
            "**four+ hero landmarks** — one primary plus three or more "
            "supporting landmarks scattered across the map. Treat the "
            "scene as a small region with multiple settlements / vistas. "
            "Tag each in comments: `# HERO: primary — ...`, "
            "`# HERO: supporting — ...`. All heroes occupy distinct "
            "quadrants, pairwise XY distance ≥ 16 BU. Camera targets "
            "the heroes' centroid; lens 24-28 mm."
        )

    # Quadrant table — appears once per brief regardless of hero count.
    # Coordinates are world XY, sized for the default 80 BU half-extent
    # terrain. The LLM picks ranges from each quadrant; jitter within
    # those ranges so consecutive runs don't repeat.
    quadrant_table = (
        "\n\n**Hero quadrants (pick from these XY ranges):**\n"
        "- NW: x ∈ [-55, -20], y ∈ [+15, +50]\n"
        "- N : x ∈ [-15, +15], y ∈ [+20, +55]\n"
        "- NE: x ∈ [+20, +55], y ∈ [+15, +50]\n"
        "- W : x ∈ [-55, -20], y ∈ [-15, +15]\n"
        "- C : x ∈ [-12, +12], y ∈ [-12, +12]   (use sparingly)\n"
        "- E : x ∈ [+20, +55], y ∈ [-15, +15]\n"
        "- SW: x ∈ [-55, -20], y ∈ [-50, -15]\n"
        "- S : x ∈ [-15, +15], y ∈ [-55, -20]\n"
        "- SE: x ∈ [+20, +55], y ∈ [-50, -15]\n"
        "Pick exact coords inside each range using `rng = random.Random("
        "SEED)` so re-runs of the same seed land in the same place but "
        "different seeds vary."
    )
    hero_phrasing = hero_phrasing + quadrant_table
    return (
        "## SCENE BRIEF\n\n"
        f"### Hero density\n\n"
        f"This scene must have {hero_phrasing}\n\n"
        "Heroes are distinct from props/scatter — a hero gets its own "
        "factory call and explicit `place(...)` line; props live inside "
        "scatter calls or short loops. The hero count is non-negotiable: "
        "do not under-fill (smaller scenes feel empty) or over-fill "
        "(more heroes than briefed crowd the camera). Tagging is "
        "non-negotiable too — the post-build validator scans for "
        "`# HERO: primary` / `# HERO: supporting` comment lines and "
        "lints a count mismatch as a hard error.\n\n"
        "### Constraint-aware terrain (REQUIRED) — shape the ground to fit composition\n\n"
        "Decide hero positions, path waypoints, and water position **first**, "
        "then pass them to `make_eroded_terrain` (or `make_multi_biome_terrain`) "
        "as a `Composition` so the terrain is *built* to fit the scene — flat "
        "plateaus where heroes will stand, a saddle along the path, a basin "
        "under the water. This is much cleaner than carving the terrain "
        "after-the-fact and produces an intentional shape rather than a noisy "
        "surface heroes happen to sit on top of.\n\n"
        "```python\n"
        "from infinigen.maquette.runtime.influence import Composition, Hero, Pathway, Water\n"
        "# NOTE: it's `Pathway`, not `Path` — `Path` is reserved for "
        "`pathlib.Path` (used for the OUT_DIR). Don't `from infinigen... "
        "import Path` or you'll shadow pathlib.\n"
        "from infinigen.maquette.runtime.eroded_terrain import make_eroded_terrain\n"
        "\n"
        "# 1. Plan composition (positions / waypoints known up-front).\n"
        "P_X, P_Y    = 22, 16    # primary hero, NE\n"
        "S1_X, S1_Y  = -35, -22  # supporting #1, SW\n"
        "S2_X, S2_Y  = -5,  38   # supporting #2, N\n"
        "PATH_PTS = [(40, -56), (15, -22), (P_X, P_Y - 4)]\n"
        "WATER_CX, WATER_CY, WATER_R = P_X - 4, P_Y - 6, 6\n"
        "\n"
        "# 2. Build terrain WITH composition baked in.\n"
        "terrain = make_eroded_terrain(\n"
        "    size=80, seed=SEED,\n"
        "    peaks=[(0, 0, 30, 6.0)],\n"
        "    palette_preset='alpine',  # alpine|desert|wetland|volcanic|savanna|tundra|tropical\n"
        "    composition=Composition(\n"
        "        heroes=[\n"
        "            Hero(cx=P_X,  cy=P_Y,  radius=18, hardness=1.2),  # broad soft plateau\n"
        "            Hero(cx=S1_X, cy=S1_Y, radius=14, hardness=1.0),\n"
        "            Hero(cx=S2_X, cy=S2_Y, radius=14, hardness=1.0),\n"
        "        ],\n"
        "        paths=[\n"
        "            # Trunk: entry → primary hero. All branches share waypoint #0.\n"
        "            Pathway(waypoints=[(40, -56), (15, -22), (P_X, P_Y - 4)],\n"
        "                    width=2.4, depth=-0.05, archetype='dirt'),\n"
        "            # Branch to supporting #1 — fork off mid-trunk.\n"
        "            Pathway(waypoints=[(15, -22), (-12, -25), (S1_X, S1_Y + 3)],\n"
        "                    width=1.8, depth=-0.04, archetype='dirt'),\n"
        "            # Branch to supporting #2 — second fork.\n"
        "            Pathway(waypoints=[(P_X - 4, P_Y), (15, P_Y + 6), (S2_X, S2_Y - 3)],\n"
        "                    width=1.8, depth=-0.04, archetype='dirt'),\n"
        "        ],\n"
        "        water=Water(cx=WATER_CX, cy=WATER_CY, radius=WATER_R, depth=0.5),\n"
        "    ),\n"
        ")\n"
        "\n"
        "# 3. Place heroes — terrain.height_at returns the plateau-flat surface.\n"
        "place(hero_obj, P_X, P_Y)\n"
        "```\n\n"
        "Operator semantics:\n"
        "- **Hero(cx, cy, radius, hardness=1.2)** — Gaussian-falloff plateau "
        "centered at (cx, cy). For the painterly Sky-CotL look, prefer "
        "**broad soft plateaus**: `radius=14–22 BU`, `hardness=1.0–1.4`. "
        "Sharp `hardness=2.5+` is reserved for fortress/mesa scenes that "
        "explicitly call for cliff edges. Default `target_z=None` flattens "
        "toward the natural local height.\n"
        "- **Pathway(waypoints, width=2.5, depth=0.0, blend=1.5, "
        "archetype='dirt')** — smooth "
        "saddle along the polyline. Waypoint heights are sampled from the "
        "post-hero terrain (so paths land ON plateaus, not under them). "
        "`depth=-0.05` gives a worn track; `depth=0.0` is a level cobble "
        "road; `depth=+0.04` plus `width=1.6` is a boardwalk (raised plank). "
        "**`archetype` paints the corridor:** `dirt` (warm tan, wilderness "
        "default), `stone` (cool grey cobble, town/temple), `wood` (boardwalk "
        "plank, wetland/pier), `sand` (bright desert track). Match it to your "
        "PATH_ARCHETYPE comment so the visual and tag agree. **Multi-hero "
        "scenes should emit one trunk + a branch per supporting hero** "
        "(see the example above) — a single straight path past three "
        "landmarks reads as a procedural-generator shortcut. Branches reuse "
        "a waypoint of the trunk so they connect visually; narrower (~1.8 "
        "BU) and slightly shallower than the trunk so the trunk reads as "
        "primary.\n"
        "- **Water(cx, cy, radius, depth=0.4)** — round basin centered at "
        "(cx, cy). The basin floor sits `depth` BU below the natural "
        "surface; the surrounding water plane (`LowPolyWaterSurfaceFactory`) "
        "should be placed at `terrain.height_at(cx, cy) + 0.05` so the "
        "water surface reads ~5 cm above the basin floor.\n\n"
        "Hard rules:\n"
        "- **Always pass `composition=` when you have heroes/paths/water "
        "to place** — that is the strong-default approach. The fallback "
        "post-hoc `carve_path(...)` still works but produces inferior "
        "results (paths look bolted on; erosion washes the carve back).\n"
        "- **Cap `Hero` count at the requested map size** (small=1, "
        "medium=2, large=3). Stacking more flatten-radials than briefed "
        "saturates the influence weights and makes the terrain melt.\n"
        "- **`make_terrain` (the simple helper) does NOT support "
        "Composition.** Use `make_eroded_terrain` or "
        "`make_multi_biome_terrain` whenever the scene has heroes/paths/water.\n"
        "- **Always pass `palette_preset=...`** matching the prompt mood. "
        "Built-in presets: `alpine` (snow/forest/meadow — default, but pick "
        "explicitly so the colors track the prompt), `desert` (oasis/dune/"
        "sandstone), `wetland` (marsh/peat), `volcanic` (ash/basalt), "
        "`savanna` (yellow grass/scrub), `tundra` (cold rock/ice), "
        "`tropical` (turquoise lagoon/coral sand/jungle). Pick whichever "
        "is closest; you can also pass an explicit `palette={...}` dict to "
        "override individual slots (`lakebed`, `shore`, `meadow`, `forest`, "
        "`stone`, `alpine`, `snow`).\n\n"
        "### Pathing — make scenes gameable\n\n"
        "**A path is OPTIONAL — judge per scene.** Add one only when ALL "
        "of these hold:\n"
        "1. There are ≥2 settled / built / inhabited landmarks the player "
        "should associate as connected (e.g. watchtower ↔ chapel ↔ hamlet, "
        "town gate ↔ market ↔ temple). Single-landmark scenes don't need "
        "a path; the landmark IS the destination.\n"
        "2. The terrain between the landmarks is plausibly walkable — "
        "rolling slopes, saddles, riverbanks. If the heroes are separated "
        "by a cliff or wide water and you can't author a bridge, don't "
        "fake a runway path.\n"
        "3. The prompt doesn't actively exclude one. Skip the path on:\n"
        "   - water-dominated scenes (`archipelago`, `atoll`, `ocean`, "
        "isolated oasis with no perimeter activity)\n"
        "   - untouched-wilderness keywords: `untouched`, `pristine`, "
        "`wild`, `untrodden`, `secret valley`, `trackless`, `virgin`\n"
        "   - abstract / surreal / scaleless tableaux (zen garden, dream "
        "scene, floating islands without obvious connectors)\n"
        "   - single-peak / isolated-mountain scenes where climbing is "
        "the read\n\n"
        "If you skip the path, leave a `# NO_PATH: <reason>` comment so "
        "the validator doesn't lint it as missing, and don't pass `paths=` "
        "into the Composition.\n\n"
        "**When you DO add a path:**\n\n"
        "- **Archetype** — pick one and tag with `# PATH_ARCHETYPE: <name>`:\n"
        "  - `stone_road` — courtyards/towns/temple approaches; carve flat "
        "(`depth=0.0`), dress with stone-wall fence every 4–6 BU.\n"
        "  - `dirt_trail` — wilderness/alpine/frontier; carve worn "
        "(`depth=-0.05`), occasional bollards only.\n"
        "  - `boardwalk` — wetlands/coastal piers; don't carve, lay wood "
        "plane at `terrain.height_at(x,y)+0.04`, wooden_rail both sides.\n"
        "  - `river_crossing` — bridge or two lantern posts as ford marker; "
        "dirt-trail run-up carved (`depth=-0.03`).\n"
        "- **Waypoints** — 3–6 world-XY points entry → hero(es), threading "
        "saddles/shoulders/riverbanks. Adjacent heroes sit along or near "
        "the path, not behind it. Camera-foreground entry → primary hero "
        "is the safest default direction.\n"
        "- **Carve** the path before placing structures so factories sample "
        "the new height: `carve_path(terrain, [(x1,y1),(x2,y2),...], "
        "width=2.4, depth=-0.05)` (import from "
        "`infinigen.maquette.runtime.eroded_terrain`). Width 2.0–3.5 BU. "
        "Requires `make_eroded_terrain` or `make_multi_biome_terrain` — the "
        "simple `make_terrain` has no heightmap to mutate, so build with one "
        "of the heightmap helpers when you want a carved path. Skip carve "
        "for boardwalks.\n"
        "- **Dress** with lanterns/bollards/fences every 4–8 BU, alternating "
        "sides. Cluster barrels/crates at junctions and on the visitor-"
        "facing side of heroes.\n"
        "- **Orient** structures with a clear front toward the path: "
        "`rot_z = math.atan2(path_dy, path_dx) + math.pi/2`.\n"
        "- **Exclude scatter** from the corridor — every `scatter_on_terrain` "
        "call must pass `exclude_polylines=path_pts, "
        "exclude_radius=path_width * 0.7`. The helper caches the mask after "
        "the first call.\n"
        "- **Player spawn** — add an empty (`bpy.ops.object.empty_add(...)`) "
        "named exactly `Player_Spawn` at the first waypoint, "
        "Z = `terrain.height_at(x0,y0)+0.05`, rotated along the next-segment "
        "vector. Future Play mode reads this empty.\n\n"
        "If the prompt genuinely forbids a path, leave a `# NO_PATH: "
        "<reason>` comment so the validator skips the missing-path lint.\n\n"
        "### Foreground anchor — silhouette grounding\n\n"
        "Place at least one chunky prop within ~5 BU of the camera (boulder, "
        "fence post, broken cart, tree stump, half-buried statue, lantern, "
        "barrel cluster). Slightly off-center so it doesn't block the hero. "
        "Tag with `# FOREGROUND_ANCHOR: <kind>`.\n\n"
        "### Camera framing\n\n"
        "Primary hero's center must land within the central 60% of the frame "
        "(NDC ~[-0.6, +0.6]) in both axes. Aim with: "
        "`cam.rotation_euler = (primary_pos - cam_pos).to_track_quat('-Z', "
        "'Y').to_euler()` where `primary_pos = Vector((hx, hy, hz + "
        "hero_h*0.5))`. Use the primary hero's center as target unless the "
        "composition genuinely needs otherwise.\n\n"
        "### Time of day\n\n"
        "Pick one and tag with `# TIME_OF_DAY: <choice>`, then call "
        "`set_time_of_day('<choice>')` (from `infinigen.maquette.runtime."
        "composition`) after wiring the sun + world background:\n"
        "- `dawn` — peaceful/ancient/awakening (cold blue, low pink sun)\n"
        "- `morning` — default neutral (alpine vistas, fresh starts)\n"
        "- `golden` — heroic/markets/fortresses (warm low sun, long shadows)\n"
        "- `overcast` — zen/mournful/foreboding (flat cool, soft shadows)\n"
        "- `dusk` — desert oasis / settling villages (orange/violet)\n"
        "- `night` — lantern-lit/secretive (only when prompt asks)\n\n"
        "### Atmospheric depth (currently a no-op)\n\n"
        "`add_aerial_perspective(strength=...)` from "
        "`infinigen.maquette.runtime.composition` is a placeholder right "
        "now — calling it is harmless but produces no haze. Bounded-volume "
        "box implementation is pending; world-output volumes black out "
        "Sun-lit scenes. Don't waste tokens on tuning strength values.\n\n"
        "### View transform — use AgX, not Standard\n\n"
        "Set `scene.view_settings.view_transform = 'AgX'` (NOT 'Standard') "
        "and `scene.view_settings.look = 'AgX - Punchy'`. AgX bends warm "
        "highlights into pastel and compresses shadows softly — exactly "
        "the Sky CotL tone-map. `Standard` clips warmth and crushes "
        "shadows; you'll get muddy bands and blown-out clouds. This is a "
        "single-line change but it's the biggest visual lever in the "
        "render block.\n\n"
        "### Sun lighting — warm key, no fill\n\n"
        "`sun.data.color = (1.0, 0.78, 0.55)` (warm pink-gold), "
        "`sun.data.energy = 2.0`. Don't add a second area light or a hemi "
        "fill — the world volume + HDRI handle ambient. Sky's contrast "
        "comes from a single warm key against the cool aerial haze.\n\n"
        "### Walkable-surface markup\n\n"
        "When you carve a path, also call "
        "`mark_walkable(terrain.obj, kind='terrain')` (from "
        "`infinigen.maquette.runtime.composition`); optionally tag bridge/"
        "stair meshes too. Forward-compat for navmesh; skip if no path.\n\n"
    )


_CODE_FENCE = re.compile(r"```python\s*\n(.*?)\n```", re.DOTALL)
_REQUESTED_LINE = re.compile(
    r"^\s*#\s*REQUESTED_ASSET:\s*(?P<rest>.+?)\s*$", re.MULTILINE
)


def extract_script(response: str) -> str:
    """Pull the Python script out of Claude's response.

    Claude sometimes splits a single build script across multiple
    ``` python ... ``` fences with narrative text between them — usually
    when the script is long (Composition + heroes + scatter + camera).
    Concatenate ALL python blocks in order so the assembled script has
    its imports + first hero + path/water + remaining heroes + render.
    Earlier "first-match" and "longest-match" behaviours both produced
    a truncated build that started mid-function and missed heroes.
    """
    matches = list(_CODE_FENCE.finditer(response))
    if not matches:
        # Fallback: if the response *is* a Python script (no markdown), use
        # it as-is. Heuristic: starts with "import" / "from" / a docstring.
        stripped = response.strip()
        first = stripped.splitlines()[0] if stripped else ""
        if first.startswith(("import ", "from ", '"""', "'''")):
            return stripped
        raise ValueError(
            "no ```python code block in Claude response and response doesn't "
            "look like a bare script. First 200 chars:\n" + stripped[:200]
        )
    # Join with newlines so block boundaries don't merge two statements.
    return "\n".join(m.group(1) for m in matches)


def extract_requested_assets(script: str) -> list[str]:
    """Pull `# REQUESTED_ASSET: ...` markers from the script."""
    return [m.group("rest").strip() for m in _REQUESTED_LINE.finditer(script)]


_SCENE_TITLE_RE = re.compile(
    r"^##\s*SCENE_TITLE\s*:\s*(?P<title>.+?)\s*$",
    re.MULTILINE,
)


def extract_scene_title(response: str) -> str | None:
    """Pull the `## SCENE_TITLE: <...>` line from Claude's response.
    Returns None if no such line exists, the title (trimmed, no
    trailing punctuation, capped at 80 chars) otherwise."""
    match = _SCENE_TITLE_RE.search(response)
    if not match:
        return None
    raw = match.group("title").strip().strip('"\'')
    raw = raw.rstrip(".!?,;:")
    return raw[:80] or None


_SCENE_PLAN_RE = re.compile(
    r"^##\s*SCENE_PLAN\s*\n+```(?:json)?\s*\n(?P<body>.*?)\n```",
    re.MULTILINE | re.DOTALL,
)


def extract_scene_plan(response: str) -> dict | None:
    """Pull the `## SCENE_PLAN` JSON block from the response and parse
    it. Returns None on any failure — extraction is best-effort and
    must never block the build script execution path.

    Tolerant to:
      - missing ```json language tag
      - trailing whitespace / blank lines around the block
      - the rare model that puts the SCENE_PLAN inside the markdown
        narrative section instead of after it
    """
    import json as _json
    match = _SCENE_PLAN_RE.search(response)
    if not match:
        return None
    body = match.group("body").strip()
    if not body:
        return None
    try:
        data = _json.loads(body)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def extract_debug_narrative(response: str) -> str | None:
    """Extract the `## DEBUG_NARRATIVE` section from Claude's response.
    Returns None if no such section exists. The section ends at the next
    top-level heading or the start of the python fenced block."""
    match = re.search(
        r"^##\s*DEBUG_NARRATIVE\s*\n(?P<body>.*?)(?=^##\s|^```python|\Z)",
        response,
        re.MULTILINE | re.DOTALL,
    )
    if not match:
        return None
    body = match.group("body").strip()
    return body or None


def call_claude(prompt: str, *, model: str | None = None,
                timeout_seconds: int = 300) -> str:
    """Run `claude -p <prompt>` and return stdout. The prompt is passed via
    stdin to avoid shell-arg-length limits."""
    if shutil.which("claude") is None:
        raise RuntimeError(
            "`claude` CLI not found on PATH. Install Claude Code or "
            "ensure the binary is in PATH for this user."
        )
    cmd = ["claude", "-p"]
    if model:
        cmd.extend(["--model", model])
    # Run from a neutral dir so claude doesn't auto-discover the
    # caller's CLAUDE.md or auto-memory. Memory + project context are
    # keyed off cwd; a cwd of /tmp gives Claude an empty project ctx
    # and our build prompt is fully self-contained anyway. Also strip
    # CLAUDE_PROJECT_DIR / PWD from the env for the same reason.
    pipeline_env = {
        k: v for k, v in os.environ.items()
        if k not in ("CLAUDE_PROJECT_DIR", "PWD", "OLDPWD")
    }
    pipeline_env["PWD"] = "/tmp"
    proc = subprocess.run(
        cmd,
        input=prompt,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        cwd="/tmp",
        env=pipeline_env,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"`claude` exited {proc.returncode}.\n"
            f"stderr:\n{proc.stderr}\nstdout (first 2k):\n{proc.stdout[:2000]}"
        )
    return proc.stdout


def generate(user_prompt: str, *, model: str | None = None,
             timeout_seconds: int = 300,
             regenerate_guide: bool = True,
             reference_image_paths: list[Path] | None = None,
             debug: bool = False,
             include_categories: list[str] | None = None,
             mode: str = "low_poly",
             map_size: str = "large") -> GenerationResult:
    """End-to-end: prompt → Claude → extracted script.

    ``mode`` selects the factory catalog: ``low_poly`` (stylized maquette,
    default) or ``realistic`` (upstream Infinigen, post-baked to LODs).
    ``map_size`` (small|medium|large|xl) drives the hero-count brief
    injected into the prompt: 1/2/3/4 heroes respectively."""
    full_prompt = build_prompt(
        user_prompt,
        regenerate_guide=regenerate_guide,
        reference_image_paths=reference_image_paths,
        debug=debug,
        include_categories=include_categories,
        mode=mode,
        map_size=map_size,
    )
    # Sonnet stochastically truncates a complete build script to just the
    # final sections (~50% of the time), producing a build.py that starts
    # mid-function with no imports. Detect that here and retry once before
    # we burn the failed-validator budget downstream. The check: a sane
    # build always opens with `import bpy` (or `import math`) within the
    # first 30 lines. If not, we got the truncated tail.
    def _looks_truncated(script_text: str) -> bool:
        head = script_text.lstrip().splitlines()[:30]
        return not any(
            line.startswith(("import bpy", "import math", "import os",
                             "import random", "import sys", "from pathlib"))
            for line in head
        )

    response = call_claude(full_prompt, model=model, timeout_seconds=timeout_seconds)
    script = extract_script(response)
    if _looks_truncated(script):
        print("[runner] extracted script appears truncated (no imports in first 30 lines); retrying once")
        response = call_claude(full_prompt, model=model, timeout_seconds=timeout_seconds)
        script = extract_script(response)
    requested = extract_requested_assets(script)
    narrative = extract_debug_narrative(response) if debug else None
    plan = extract_scene_plan(response) if debug else None
    title = extract_scene_title(response)
    return GenerationResult(
        raw_response=response,
        extracted_script=script,
        requested_assets=requested,
        debug_narrative=narrative,
        scene_title=title,
        scene_plan=plan,
    )
